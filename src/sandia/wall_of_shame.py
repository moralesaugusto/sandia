"""Wall of Shame: the DHCP clients causing the most obvious, countable
problems - DHCPNAKs, IP churn, and abandoned addresses - straight
aggregation over data Sandia already parses (leases.py, diagnostics/
dhcp_log.py, devices.py). No scoring, no inference, no new event/cache
system: every number here is a literal count of real events/records.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .devices import Device
from .dhcpd import DhcpdConfig
from .diagnostics.dhcp_log import DhcpEvent
from .leases import Lease, parse_lease_timestamp
from .utilization import find_containing_subnet

TOP_N = 10

TIME_WINDOWS: dict[str, timedelta | None] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "all": None,
}
DEFAULT_WINDOW = "24h"


def parse_syslog_timestamp(raw: str, now: datetime) -> datetime | None:
    """dhcpd's syslog lines carry no year ("Sep  2 09:00:00"). Assume the
    current year, then roll back one year if that would place the event in
    the future (a log line from just before a year boundary) - the same
    convention standard syslog readers use for this timestamp format."""
    try:
        parsed = datetime.strptime(f"{now.year} {raw}", "%Y %b %d %H:%M:%S")
    except ValueError:
        return None
    if parsed > now + timedelta(days=1):
        parsed = parsed.replace(year=now.year - 1)
    return parsed


@dataclass
class NakEntry:
    mac: str
    device: Device | None
    count: int
    last_nak: datetime | None


@dataclass
class IpChangeEntry:
    mac: str
    device: Device | None
    count: int
    last_change: datetime | None


@dataclass
class AbandonedEntry:
    mac: str | None
    ip: str
    device: Device | None
    subnet_key: str | None
    count: int
    last_seen: datetime | None


def _device_by_mac(devices: list[Device]) -> dict[str, Device]:
    return {device.mac: device for device in devices}


def top_nak_devices(events: list[DhcpEvent], devices: list[Device], now: datetime, window_key: str) -> list[NakEntry]:
    window = TIME_WINDOWS.get(window_key, TIME_WINDOWS[DEFAULT_WINDOW])
    by_mac = _device_by_mac(devices)

    timestamps_by_mac: dict[str, list[datetime | None]] = {}
    for event in events:
        if event.kind != "DHCPNAK" or not event.mac:
            continue
        ts = parse_syslog_timestamp(event.timestamp, now)
        if window is not None and (ts is None or ts < now - window):
            continue
        timestamps_by_mac.setdefault(event.mac, []).append(ts)

    entries = [
        NakEntry(mac=mac, device=by_mac.get(mac), count=len(timestamps), last_nak=max((t for t in timestamps if t), default=None))
        for mac, timestamps in timestamps_by_mac.items()
    ]
    entries.sort(key=lambda e: (e.count, e.last_nak or datetime.min), reverse=True)
    return entries[:TOP_N]


def top_ip_changers(lease_history: list[Lease], devices: list[Device], now: datetime, window_key: str) -> list[IpChangeEntry]:
    window = TIME_WINDOWS.get(window_key, TIME_WINDOWS[DEFAULT_WINDOW])
    by_mac = _device_by_mac(devices)

    records_by_mac: dict[str, list[Lease]] = {}
    for record in lease_history:
        if record.mac:
            records_by_mac.setdefault(record.mac, []).append(record)

    entries = []
    for mac, records in records_by_mac.items():
        ordered = sorted(records, key=lambda r: parse_lease_timestamp(r.starts) or datetime.min)
        change_times: list[datetime | None] = []
        previous_ip = None
        for record in ordered:
            # Renewals (same IP, new block) are not IP changes - only a
            # different address than the immediately preceding one counts.
            if previous_ip is not None and record.ip != previous_ip:
                change_times.append(parse_lease_timestamp(record.starts))
            previous_ip = record.ip

        if window is not None:
            change_times = [ts for ts in change_times if ts is not None and ts >= now - window]
        if not change_times:
            continue

        entries.append(
            IpChangeEntry(
                mac=mac,
                device=by_mac.get(mac),
                count=len(change_times),
                last_change=max((t for t in change_times if t), default=None),
            )
        )

    entries.sort(key=lambda e: (e.count, e.last_change or datetime.min), reverse=True)
    return entries[:TOP_N]


def top_abandoned(
    lease_history: list[Lease], devices: list[Device], config: DhcpdConfig, now: datetime, window_key: str
) -> list[AbandonedEntry]:
    window = TIME_WINDOWS.get(window_key, TIME_WINDOWS[DEFAULT_WINDOW])
    by_mac = _device_by_mac(devices)

    # Grouped by MAC when the abandoned block actually names one; dhcpd
    # doesn't always record hardware info for an abandoned address (e.g. a
    # ping-conflict abandonment with no client ever claiming it), and that
    # relationship is never invented - such records are grouped by IP alone.
    groups: dict[str, list[Lease]] = {}
    for record in lease_history:
        if (record.binding_state or "").lower() != "abandoned":
            continue
        ts = parse_lease_timestamp(record.starts)
        if window is not None and (ts is None or ts < now - window):
            continue
        key = record.mac if record.mac else f"ip:{record.ip}"
        groups.setdefault(key, []).append(record)

    entries = []
    for key, records in groups.items():
        ordered = sorted(records, key=lambda r: parse_lease_timestamp(r.starts) or datetime.min)
        latest = ordered[-1]
        timestamps = [parse_lease_timestamp(r.starts) for r in records]
        subnet = find_containing_subnet(config, latest.ip)
        entries.append(
            AbandonedEntry(
                mac=latest.mac,
                ip=latest.ip,
                device=by_mac.get(latest.mac) if latest.mac else None,
                subnet_key=subnet.key if subnet else None,
                count=len(records),
                last_seen=max((t for t in timestamps if t), default=None),
            )
        )

    entries.sort(key=lambda e: (e.count, e.last_seen or datetime.min), reverse=True)
    return entries[:TOP_N]
