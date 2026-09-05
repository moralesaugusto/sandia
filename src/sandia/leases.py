from __future__ import annotations

import re
from dataclasses import dataclass
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


def parse_leases(text: str) -> list[Lease]:
    """Parse an ISC dhcpd.leases file.

    The file is a flat, possibly-repeated sequence of `lease <ip> { ... }`
    blocks; later blocks for the same IP supersede earlier ones (dhcpd
    appends new state rather than rewriting old entries in place), so only
    the last occurrence per IP is kept.
    """
    by_ip: dict[str, Lease] = {}
    for match in _LEASE_BLOCK_RE.finditer(text):
        ip = match.group("ip")
        body = match.group("body")

        def field(pattern: re.Pattern) -> str | None:
            m = pattern.search(body)
            return m.group("value").strip() if m else None

        by_ip[ip] = Lease(
            ip=ip,
            mac=field(_MAC_RE),
            hostname=field(_HOSTNAME_RE) or None,
            starts=field(_STARTS_RE),
            ends=field(_ENDS_RE),
            binding_state=field(_BINDING_STATE_RE),
        )
    return list(by_ip.values())


def load_leases(path: Path) -> list[Lease]:
    if not path.exists():
        return []
    return parse_leases(path.read_text())
