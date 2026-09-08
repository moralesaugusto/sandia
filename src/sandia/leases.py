from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_LEASE_BLOCK_RE = re.compile(r"lease\s+(?P<ip>\S+)\s*\{(?P<body>.*?)\n\}", re.DOTALL)
# Field names can be multi-word (e.g. "binding state", "next binding state"),
# so each field we care about gets its own targeted, line-anchored pattern
# rather than one generic "name value;" splitter.
_MAC_RE = re.compile(r"^\s*hardware ethernet\s+(?P<value>\S+);", re.MULTILINE)
_HOSTNAME_RE = re.compile(r'^\s*client-hostname\s+"(?P<value>[^"]*)";', re.MULTILINE)
_STARTS_RE = re.compile(r"^\s*starts\s+(?P<value>.+);", re.MULTILINE)
_ENDS_RE = re.compile(r"^\s*ends\s+(?P<value>.+);", re.MULTILINE)
_BINDING_STATE_RE = re.compile(r"^\s*binding state\s+(?P<value>\w+);", re.MULTILINE)


@dataclass
class Lease:
    ip: str
    mac: str | None
    hostname: str | None
    starts: str | None
    ends: str | None
    binding_state: str | None

    @property
    def is_active(self) -> bool:
        return self.binding_state == "active"


def _parse_lease_blocks(text: str) -> list[Lease]:
    """Every `lease <ip> { ... }` block in file order, unfiltered - dhcpd
    appends a new block on every state change rather than rewriting old
    ones in place, so this is the only place the file's actual history
    lives. Most callers want parse_leases() (current state only); this is
    for callers that need that history (see devices.py)."""
    records = []
    for match in _LEASE_BLOCK_RE.finditer(text):
        ip = match.group("ip")
        body = match.group("body")

        def field(pattern: re.Pattern) -> str | None:
            m = pattern.search(body)
            return m.group("value").strip() if m else None

        records.append(
            Lease(
                ip=ip,
                mac=field(_MAC_RE),
                hostname=field(_HOSTNAME_RE) or None,
                starts=field(_STARTS_RE),
                ends=field(_ENDS_RE),
                binding_state=field(_BINDING_STATE_RE),
            )
        )
    return records


def parse_leases(text: str) -> list[Lease]:
    """Parse an ISC dhcpd.leases file.

    The file is a flat, possibly-repeated sequence of `lease <ip> { ... }`
    blocks; later blocks for the same IP supersede earlier ones (dhcpd
    appends new state rather than rewriting old entries in place), so only
    the last occurrence per IP is kept.
    """
    by_ip: dict[str, Lease] = {}
    for record in _parse_lease_blocks(text):
        by_ip[record.ip] = record
    return list(by_ip.values())


def parse_lease_history(text: str) -> list[Lease]:
    """Every historical block, unfiltered, in file order - used to answer
    "what IPs has this MAC held, and when" (see devices.py). Unlike
    parse_leases(), a given IP may appear more than once here."""
    return _parse_lease_blocks(text)


# dhcpd writes "starts"/"ends" as "<weekday 0-6> <YYYY/MM/DD> <HH:MM:SS>",
# e.g. "3 2026/09/02 22:00:01". The weekday is redundant with the date and
# is ignored rather than validated.
_LEASE_TIMESTAMP_RE = re.compile(r"^\d\s+(?P<date>\d{4}/\d{2}/\d{2})\s+(?P<time>\d{2}:\d{2}:\d{2})$")


def parse_lease_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    match = _LEASE_TIMESTAMP_RE.match(value.strip())
    if not match:
        return None
    try:
        return datetime.strptime(f"{match.group('date')} {match.group('time')}", "%Y/%m/%d %H:%M:%S")
    except ValueError:
        return None


def load_leases(path: Path) -> list[Lease]:
    if not path.exists():
        return []
    return parse_leases(path.read_text())


def load_lease_history(path: Path) -> list[Lease]:
    if not path.exists():
        return []
    return parse_lease_history(path.read_text())
