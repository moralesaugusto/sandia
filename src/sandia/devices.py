"""Device inventory: correlates reservations, current leases, lease
history, and DHCP log activity into one row per MAC address - the primary
identity for a device, not its current IP (which can change).

Deliberately not a new data model: a Device is a view over the existing
Host/Lease/DhcpEvent types (see dhcpd/ast.py, leases.py,
diagnostics/dhcp_log.py). Nothing here is invented - a field is None
whenever the underlying data doesn't support a value, and the device
"status" is computed from real timestamps/state, never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .device_icons import device_icon_for
from .dhcpd import DhcpdConfig, Host, Subnet
from .diagnostics import normalize_mac
from .diagnostics.dhcp_log import DhcpEvent
from .ip_map import denied_macs
from .leases import Lease, parse_lease_timestamp
from .utilization import find_containing_subnet
from .vendors import lookup_vendor

# A device with no active lease but DHCP activity within this window is
# "recently seen" rather than "inactive" - a fixed, documented threshold,
# not a tunable heuristic (see docs/DECISIONS.md).
RECENT_WINDOW = timedelta(hours=24)


class DeviceStatus(str, Enum):
    PROBLEM = "problem"
    ACTIVE = "active"
    RECENTLY_SEEN = "recently_seen"
    INACTIVE = "inactive"
    RESERVED = "reserved"
    UNKNOWN = "unknown"


STATUS_LABELS: dict[DeviceStatus, str] = {
    DeviceStatus.PROBLEM: "Problem",
    DeviceStatus.ACTIVE: "Active",
    DeviceStatus.RECENTLY_SEEN: "Recently seen",
    DeviceStatus.INACTIVE: "Inactive",
    DeviceStatus.RESERVED: "Reserved",
    DeviceStatus.UNKNOWN: "Unknown",
}

_STATUS_SORT_RANK = {
    DeviceStatus.PROBLEM: 0,
    DeviceStatus.ACTIVE: 1,
    DeviceStatus.RECENTLY_SEEN: 2,
    DeviceStatus.RESERVED: 3,
    DeviceStatus.INACTIVE: 4,
    DeviceStatus.UNKNOWN: 5,
}


@dataclass
class Device:
    mac: str
    reservation: Host | None
    current_lease: Lease | None
    history: list[Lease]  # all historical records for this mac, newest first
    subnet: Subnet | None
    hostname: str | None  # best-known client-reported hostname - not the reservation label
    vendor: str | None
    icon: str
    first_seen: datetime | None
    last_seen: datetime | None
    status: DeviceStatus
    status_detail: str
    has_problem: bool
    problem_summary: str | None

    @property
    def display_name(self) -> str:
        if self.hostname:
            return self.hostname
        if self.reservation:
            return self.reservation.name
        return self.mac

    @property
    def current_ip(self) -> str | None:
        if self.current_lease:
            return self.current_lease.ip
        if self.reservation:
            return self.reservation.fixed_address
        return None

    @property
    def previous_ips(self) -> list[str]:
        current = self.current_lease.ip if self.current_lease else None
        seen: set[str] = set()
        ips: list[str] = []
        for record in self.history:
            if record.ip == current or record.ip in seen:
                continue
            seen.add(record.ip)
            ips.append(record.ip)
        return ips

    @property
    def status_label(self) -> str:
        return STATUS_LABELS[self.status]


def _format_delta(delta: timedelta) -> str:
    seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return "under a minute"


def _lease_status_detail(lease: Lease, now: datetime) -> str:
    ends = parse_lease_timestamp(lease.ends)
    if ends is None:
        return "Active - lease state active"
    if ends > now:
        return f"Active - lease expires in {_format_delta(ends - now)}"
    return f"Active - lease expired {_format_delta(now - ends)} ago (dhcpd has not updated its state yet)"


def _build_status(
    current_lease: Lease | None,
    last_seen: datetime | None,
    reservation: Host | None,
    has_problem: bool,
    problem_summary: str | None,
    now: datetime,
) -> tuple[DeviceStatus, str]:
    if has_problem:
        return DeviceStatus.PROBLEM, f"Problem - {problem_summary}"
    if current_lease and current_lease.is_active:
        return DeviceStatus.ACTIVE, _lease_status_detail(current_lease, now)
    if last_seen is not None:
        delta = now - last_seen
        if delta <= RECENT_WINDOW:
            return DeviceStatus.RECENTLY_SEEN, f"Recently seen - last DHCP activity {_format_delta(delta)} ago"
        return DeviceStatus.INACTIVE, f"Inactive - last DHCP activity {_format_delta(delta)} ago"
    if reservation:
        return DeviceStatus.RESERVED, "Reserved - no DHCP activity recorded"
    return DeviceStatus.UNKNOWN, "Unknown - insufficient evidence"


def _duplicate_reservation_macs(config: DhcpdConfig) -> set[str]:
    by_ip: dict[str, set[str]] = {}
    for host in config.all_hosts:
        if host.mac and host.fixed_address:
            by_ip.setdefault(host.fixed_address, set()).add(host.mac)
    conflicted: set[str] = set()
    for macs in by_ip.values():
        if len(macs) > 1:
            conflicted.update(macs)
    return conflicted


def _recent_nak_macs(events: list[DhcpEvent]) -> set[str]:
    return {event.mac for event in events if event.kind == "DHCPNAK" and event.mac}


def _pick_current_lease(candidates: list[Lease]) -> Lease | None:
    if not candidates:
        return None
    active = [lease for lease in candidates if lease.is_active]
    if active:
        return active[0]
    return max(candidates, key=lambda lease: parse_lease_timestamp(lease.starts) or datetime.min)


def build_devices(
    config: DhcpdConfig,
    current_leases: list[Lease],
    lease_history: list[Lease],
    events: list[DhcpEvent],
) -> list[Device]:
    now = datetime.now()

    macs: set[str] = set()
    reservation_by_mac: dict[str, Host] = {}
    for host in config.all_hosts:
        if host.mac:
            macs.add(host.mac)
            reservation_by_mac.setdefault(host.mac, host)

    current_by_mac: dict[str, list[Lease]] = {}
    for lease in current_leases:
        if lease.mac:
            macs.add(lease.mac)
            current_by_mac.setdefault(lease.mac, []).append(lease)

    history_by_mac: dict[str, list[Lease]] = {}
    for record in lease_history:
        if record.mac:
            macs.add(record.mac)
            history_by_mac.setdefault(record.mac, []).append(record)

    conflict_macs = _duplicate_reservation_macs(config)
    denied = denied_macs(config)
    nak_macs = _recent_nak_macs(events)

    devices = []
    for mac in macs:
        reservation = reservation_by_mac.get(mac)
        current_lease = _pick_current_lease(current_by_mac.get(mac, []))
        history = sorted(
            history_by_mac.get(mac, []),
            key=lambda lease: parse_lease_timestamp(lease.starts) or datetime.min,
            reverse=True,
        )

        timestamps = [ts for ts in (parse_lease_timestamp(lease.starts) for lease in history) if ts]
        first_seen = min(timestamps) if timestamps else None
        last_seen = max(timestamps) if timestamps else None

        ip_for_subnet = current_lease.ip if current_lease else (reservation.fixed_address if reservation else None)
        subnet = find_containing_subnet(config, ip_for_subnet) if ip_for_subnet else None

        hostname = None
        if current_lease and current_lease.hostname:
            hostname = current_lease.hostname
        if not hostname and history:
            hostname = next((lease.hostname for lease in history if lease.hostname), None)
        if not hostname and reservation:
            declared = reservation.get("host-name")
            if declared:
                hostname = declared.strip('"') or None

        problems = []
        if mac in denied:
            problems.append("client is denied")
        if mac in conflict_macs:
            problems.append("reservation conflict with another device")
        if mac in nak_macs:
            problems.append("recent DHCPNAK observed")
        problem_summary = "; ".join(problems) if problems else None

        status, status_detail = _build_status(current_lease, last_seen, reservation, bool(problems), problem_summary, now)

        devices.append(
            Device(
                mac=mac,
                reservation=reservation,
                current_lease=current_lease,
                history=history,
                subnet=subnet,
                hostname=hostname,
                vendor=lookup_vendor(mac),
                icon=device_icon_for(hostname or (reservation.name if reservation else mac), mac),
                first_seen=first_seen,
                last_seen=last_seen,
                status=status,
                status_detail=status_detail,
                has_problem=bool(problems),
                problem_summary=problem_summary,
            )
        )

    return devices


def find_device(devices: list[Device], mac: str) -> Device | None:
    normalized = normalize_mac(mac)
    return next((device for device in devices if device.mac == normalized), None)


def filter_devices(
    devices: list[Device],
    q: str = "",
    status: str = "",
    reservation: str = "",
    lease: str = "",
    subnet_key: str = "",
    vendor: str = "",
) -> list[Device]:
    result = devices

    if q:
        needle = q.lower()
        result = [
            d
            for d in result
            if needle in d.mac.lower()
            or (d.hostname and needle in d.hostname.lower())
            or (d.current_ip and needle in d.current_ip.lower())
            or (d.vendor and needle in d.vendor.lower())
            or (d.reservation and needle in d.reservation.name.lower())
        ]

    if status:
        result = [d for d in result if d.status.value == status]

    if reservation == "yes":
        result = [d for d in result if d.reservation]
    elif reservation == "no":
        result = [d for d in result if not d.reservation]

    if lease == "yes":
        result = [d for d in result if d.current_lease]
    elif lease == "no":
        result = [d for d in result if not d.current_lease]

    if subnet_key:
        result = [d for d in result if d.subnet and d.subnet.key == subnet_key]

    if vendor:
        needle = vendor.lower()
        result = [d for d in result if d.vendor and needle in d.vendor.lower()]

    return result


def sort_devices(devices: list[Device], sort: str = "") -> list[Device]:
    if sort == "mac":
        return sorted(devices, key=lambda d: d.mac)
    if sort == "hostname":
        return sorted(devices, key=lambda d: d.display_name.lower())
    if sort == "last_seen":
        return sorted(devices, key=lambda d: d.last_seen or datetime.min, reverse=True)
    return sorted(
        devices,
        key=lambda d: (_STATUS_SORT_RANK[d.status], -(d.last_seen.timestamp() if d.last_seen else 0)),
    )
