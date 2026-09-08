"""Manual lease-file cleanup: dhcpd appends a new `lease <ip> { ... }`
block on every state change rather than rewriting old ones in place (it
only compacts the file itself occasionally, on its own schedule), so a
long-running server accumulates a lot of superseded history for the same
IP. This keeps only the last (current) block per IP and drops the rest.

Deliberately narrow: only bytes that are part of a *removed* `lease {...}`
block are touched. Anything else in the file - header comments,
`server-duid`, failover-peer state, the kept blocks themselves - is left
completely untouched, the same "never touch what we don't have to"
approach as the dhcpd.conf UnknownBlock handling.
"""

from __future__ import annotations

import re

_LEASE_BLOCK_RE = re.compile(r"lease\s+(?P<ip>\S+)\s*\{.*?\n\}\n?", re.DOTALL)


def clean_leases_text(text: str) -> tuple[str, int]:
    """Returns (cleaned_text, number_of_blocks_removed)."""
    matches = list(_LEASE_BLOCK_RE.finditer(text))
    if not matches:
        return text, 0

    last_index_by_ip: dict[str, int] = {}
    for i, match in enumerate(matches):
        last_index_by_ip[match.group("ip")] = i
    keep = set(last_index_by_ip.values())

    removed = len(matches) - len(keep)
    if removed == 0:
        return text, 0

    pieces: list[str] = []
    cursor = 0
    for i, match in enumerate(matches):
        if i in keep:
            continue
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces), removed


def delete_lease_records(text: str, ip: str) -> tuple[str, int]:
    """Removes every block (current and superseded) for one specific IP.

    This is Sandia's copy of that address's history, not a live command to
    dhcpd - there is no OMAPI/live-protocol channel in this app, so this
    cannot force-revoke an address a client is actively holding. If the
    device is still active, dhcpd will simply append a fresh block on its
    next renewal. Same safety model as clean_leases_text(): a targeted text
    edit, not a new mechanism - see docs/DECISIONS.md."""
    matches = [m for m in _LEASE_BLOCK_RE.finditer(text) if m.group("ip") == ip]
    if not matches:
        return text, 0

    pieces: list[str] = []
    cursor = 0
    for match in matches:
        pieces.append(text[cursor : match.start()])
        cursor = match.end()
    pieces.append(text[cursor:])
    return "".join(pieces), len(matches)
