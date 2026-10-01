"""Best-effort parser for kea-dhcp4 log output, normalized to the same
DhcpEvent shape as the isc-dhcp-server parser so diagnostics, the event log
and the Wall of Shame don't need to know which server wrote the log.

Kea logs one message ID per line. Accepted line shapes:

    2026-09-02 09:15:00.123 INFO  [kea-dhcp4.leases/812.140] DHCP4_LEASE_ALLOC [hwtype=1 aa:bb:cc:dd:ee:ff], cid=[no info], tid=0x1a2b: lease 192.0.2.10 has been allocated for 3600 seconds
    Sep  2 09:15:00 host kea-dhcp4[812]: INFO  [kea-dhcp4.leases.140] DHCP4_LEASE_ALLOC ...
    Sep  2 09:15:00 host kea-dhcp4[812]: INFO  DHCP4_LEASE_ALLOC ...

(file output with Kea's default pattern; `"output": "syslog"`; and the
Debian package's stdout pattern as forwarded to syslog by journald).

At Kea's default INFO severity there is no line for DISCOVER/REQUEST/NAK -
only offers, allocations, releases and declines. The two failure messages
below are DEBUG-level and only appear when debug logging is enabled.
Message templates are from Kea 2.6.3's dhcp4_messages.mes.
"""

from __future__ import annotations

import re
from datetime import datetime

from .dhcp_log import DhcpEvent

_ISO_LINE_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})\S*\s+(?P<rest>.*)$")
_SYSLOG_LINE_RE = re.compile(r"^(?P<ts>\S+\s+\d+\s+\d{2}:\d{2}:\d{2})\s+\S+\s+kea-dhcp4(?:\[\d+\])?:\s*(?P<rest>.*)$")
_MSG_RE = re.compile(r"^(?:[A-Z]+\s+)?(?:\[kea-dhcp4[^\]]*\]\s+)?(?P<id>[A-Z][A-Z0-9_]+)\s+(?P<msg>.*)$")

_LABEL = r"\[hwtype=\d+ (?P<mac>[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\][^:]*"

_KNOWN_EVENTS: dict[str, tuple[str, re.Pattern]] = {
    "DHCP4_LEASE_OFFER": ("DHCPOFFER", re.compile(rf"^{_LABEL}: lease (?P<ip>\S+) will be offered")),
    "DHCP4_LEASE_ALLOC": ("DHCPACK", re.compile(rf"^{_LABEL}: lease (?P<ip>\S+) has been allocated")),
    "DHCP4_RELEASE": ("DHCPRELEASE", re.compile(rf"^{_LABEL}: address (?P<ip>\S+) was released properly")),
    "DHCP4_DECLINE_LEASE": ("DHCPDECLINE", re.compile(rf"^Received DHCPDECLINE for addr (?P<ip>\S+) from client {_LABEL}")),
    # DEBUG: no lease could be offered after a DISCOVER.
    "DHCP4_PACKET_NAK_0003": ("DHCPDISCOVER", re.compile(rf"^{_LABEL}: (?P<reason>failed to advertise a lease)")),
    # DEBUG: a REQUEST could not be granted; Kea answers it with DHCPNAK.
    "DHCP4_PACKET_NAK_0004": (
        "DHCPNAK",
        re.compile(rf"^{_LABEL}: (?P<reason>failed to grant a lease), client sent ciaddr \S+, requested-ip-address (?P<ip>[0-9.]+)"),
    ),
}


def _syslog_style(iso: str) -> str:
    # The rest of the app reads event timestamps in syslog form
    # ("Sep  2 09:15:00", see wall_of_shame.parse_syslog_timestamp).
    moment = datetime.fromisoformat(iso.replace("T", " "))
    return f"{moment:%b} {moment.day:2d} {moment:%H:%M:%S}"


def parse_kea_log(text: str) -> list[DhcpEvent]:
    events = []
    for line in text.splitlines():
        if "kea-dhcp4" not in line:
            continue
        match = _SYSLOG_LINE_RE.match(line)
        if match:
            timestamp = match.group("ts")
        else:
            match = _ISO_LINE_RE.match(line)
            if not match:
                continue
            timestamp = _syslog_style(match.group("ts"))
        msg_match = _MSG_RE.match(match.group("rest").strip())
        known = _KNOWN_EVENTS.get(msg_match.group("id")) if msg_match else None
        event_match = known[1].match(msg_match.group("msg")) if known else None
        if event_match:
            groups = event_match.groupdict()
            events.append(
                DhcpEvent(
                    timestamp=timestamp,
                    kind=known[0],
                    ip=groups.get("ip"),
                    mac=groups["mac"].lower(),
                    hostname=None,
                    iface=None,
                    reason=groups.get("reason"),
                    raw=line.strip(),
                )
            )
        else:
            events.append(
                DhcpEvent(timestamp=timestamp, kind="OTHER", ip=None, mac=None, hostname=None, iface=None, reason=None, raw=line.strip())
            )
    return events
