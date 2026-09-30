"""Best-effort parser for isc-dhcp-server's syslog output.

dhcpd logs each protocol event as one line, e.g.:

    Sep  2 09:15:00 host dhcpd[1234]: DHCPDISCOVER from aa:bb:cc:dd:ee:ff via eth0
    Sep  2 09:15:00 host dhcpd[1234]: DHCPACK on 192.168.1.101 to aa:bb:cc:dd:ee:ff via eth0
    Sep  2 11:05:12 host dhcpd[1234]: DHCPNAK on 192.168.1.220 to aa:bb:cc:00:11:22 via eth0
    Sep  2 12:40:07 host dhcpd[1234]: DHCPDISCOVER from de:ad:be:ef:00:01 via eth1: no free leases

This is the only place DHCP protocol activity (as opposed to config/lease
*state*) is available at all - the leases file only records the current
outcome, not the negotiation. Reading it is always optional: if the file
is missing or unreadable, callers get an explicit unavailability reason
instead of a crash or a silently empty result, so diagnostics can say
"insufficient evidence" honestly rather than "no problem found".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings

# Only the tail matters for diagnostics, and a system syslog can be huge
# (and full of unrelated services' lines) - cap how much we ever read.
MAX_LOG_BYTES = 2_000_000

_LINE_RE = re.compile(r"^(?P<ts>\S+\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+dhcpd(?:\[\d+\])?:\s*(?P<msg>.*)$")

_MAC = r"(?P<mac>[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})"
_HOST = r"(?: \((?P<hostname>[^)]+)\))?"
_IFACE = r"via (?P<iface>\S+)"

# Ordered by message shape, not priority - each dhcpd message type has one
# fixed wording, so a message matches exactly one of these (or none, if
# it's a message shape this parser doesn't recognize).
_KNOWN_EVENTS: list[tuple[str, re.Pattern]] = [
    ("DHCPDISCOVER", re.compile(rf"^DHCPDISCOVER from {_MAC}{_HOST} {_IFACE}(?::\s*(?P<reason>.*))?$")),
    ("DHCPOFFER", re.compile(rf"^DHCPOFFER on (?P<ip>\S+) to {_MAC}{_HOST} {_IFACE}$")),
    ("DHCPREQUEST", re.compile(rf"^DHCPREQUEST for (?P<ip>\S+)(?: \(\S+\))? from {_MAC}{_HOST} {_IFACE}(?::\s*(?P<reason>.*))?$")),
    ("DHCPACK", re.compile(rf"^DHCPACK on (?P<ip>\S+) to {_MAC}{_HOST} {_IFACE}$")),
    ("DHCPNAK", re.compile(rf"^DHCPNAK on (?P<ip>\S+) to {_MAC}{_HOST} {_IFACE}(?::\s*(?P<reason>.*))?$")),
    ("DHCPDECLINE", re.compile(rf"^DHCPDECLINE of (?P<ip>\S+) from {_MAC}{_HOST} {_IFACE}(?::\s*(?P<reason>.*))?$")),
    ("DHCPRELEASE", re.compile(rf"^DHCPRELEASE of (?P<ip>\S+) from {_MAC}{_HOST} {_IFACE}$")),
    ("DHCPINFORM", re.compile(rf"^DHCPINFORM from (?P<ip>\S+) {_IFACE}$")),
]

EVENT_KINDS = [kind for kind, _ in _KNOWN_EVENTS]

# Substrings that make an unrecognized dhcpd log line worth surfacing as a
# server-health signal. Deliberately just a literal-match list, not a
# "smart" classifier - this only ever says "this line matched a keyword",
# never why, so it can't overclaim a root cause.
ERROR_KEYWORDS = ("error", "fail", "denied", "cannot", "can't", "unable", "warning", "bad ", "no free leases")


@dataclass
class DhcpEvent:
    timestamp: str
    kind: str  # one of the _KNOWN_EVENTS names, or "OTHER"
    ip: str | None
    mac: str | None
    hostname: str | None
    iface: str | None
    reason: str | None
    raw: str


def parse_dhcp_log(text: str) -> list[DhcpEvent]:
    events = []
    for line in text.splitlines():
        match = _LINE_RE.match(line)
        if not match:
            continue
        msg = match.group("msg").strip()
        timestamp = match.group("ts")
        for kind, pattern in _KNOWN_EVENTS:
            event_match = pattern.match(msg)
            if event_match:
                groups = event_match.groupdict()
                mac = groups.get("mac")
                events.append(
                    DhcpEvent(
                        timestamp=timestamp,
                        kind=kind,
                        ip=groups.get("ip"),
                        mac=mac.lower() if mac else None,
                        hostname=groups.get("hostname"),
                        iface=groups.get("iface"),
                        reason=groups.get("reason") or None,
                        raw=line.strip(),
                    )
                )
                break
        else:
            events.append(
                DhcpEvent(timestamp=timestamp, kind="OTHER", ip=None, mac=None, hostname=None, iface=None, reason=None, raw=line.strip())
            )
    return events


def _tail(path: Path, max_bytes: int) -> str:
    size = path.stat().st_size
    with path.open("rb") as handle:
        if size > max_bytes:
            handle.seek(size - max_bytes)
        data = handle.read()
    return data.decode("utf-8", errors="replace")


def load_dhcp_events(settings: Settings) -> tuple[list[DhcpEvent], str | None]:
    """Returns (events, unavailable_reason). unavailable_reason is None on
    success (even if there happen to be zero matching events); otherwise
    it's a human-readable explanation callers should surface verbatim
    rather than silently treating "couldn't read the log" the same as "log
    says nothing happened"."""
    path = settings.dhcp_log_path
    if not path.exists():
        return [], f"DHCP log not found at {path}"
    try:
        text = _tail(path, MAX_LOG_BYTES)
    except OSError as exc:
        return [], f"DHCP log not readable: {exc}"
    return parse_dhcp_log(text), None


def matches(event: DhcpEvent, mac: str | None, ip: str | None) -> bool:
    if mac and event.mac == mac:
        return True
    return bool(ip and event.ip == ip)


def events_for(events: list[DhcpEvent], mac: str | None, ip: str | None) -> list[DhcpEvent]:
    if not mac and not ip:
        return []
    return [event for event in events if event.kind != "OTHER" and matches(event, mac, ip)]


def error_like_lines(events: list[DhcpEvent], limit: int = 5) -> list[DhcpEvent]:
    matches_found = [
        event for event in events if any(keyword in event.raw.lower() for keyword in ERROR_KEYWORDS)
    ]
    return matches_found[-limit:]
