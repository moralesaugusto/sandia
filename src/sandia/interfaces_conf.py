"""Read/write the `INTERFACESv4` setting in `/etc/default/isc-dhcp-server`
(the shell-sourced defaults file the isc-dhcp-server init script/systemd
unit reads to decide which interfaces dhcpd actually listens on).

This is the file that *really* controls which interfaces dhcpd serves -
unlike a subnet's "interface" tag in Sandia (a `# interface: eth2` comment
in dhcpd.conf, which is just an organizational label). Only the
`INTERFACESv4="..."` line is touched; every other line (comments, other
defaults like DHCPDv4_CONF, OPTIONS, INTERFACESv6) is preserved exactly.
"""

from __future__ import annotations

import re
from pathlib import Path

_LINE_RE = re.compile(r'^[ \t]*#?[ \t]*INTERFACESv4[ \t]*=[ \t]*"(?P<value>[^"]*)"[ \t]*$', re.MULTILINE)


def get_interfaces(text: str) -> list[str]:
    match = _LINE_RE.search(text)
    if not match:
        return []
    return match.group("value").split()


def read_configured_interfaces(path: Path) -> list[str]:
    return get_interfaces(path.read_text()) if path.exists() else []


def set_interfaces(text: str, interfaces: list[str]) -> str:
    new_line = f'INTERFACESv4="{" ".join(interfaces)}"'
    if _LINE_RE.search(text):
        return _LINE_RE.sub(lambda _match: new_line, text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + new_line + "\n"
