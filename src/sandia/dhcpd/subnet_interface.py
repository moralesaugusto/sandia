"""Subnet-to-interface tagging.

ISC dhcpd has no `interface` statement inside a `subnet` block - which
physical interface serves a subnet is determined by IP addressing and the
separate INTERFACESv4 setting the service is started with, not by
dhcpd.conf. Injecting a fake `interface eth0;` parameter would fail
`dhcpd -t` (unknown statement) and get rejected by the apply pipeline.

So this is a documentation/organization feature, not a live directive:
the interface name is stored as a `# interface: <name>` comment
immediately above the subnet's declaration - valid syntax, round-trips
safely, and is enough for the UI to show and filter by "which interface
is this subnet meant for" across a multi-homed server.
"""

from __future__ import annotations

import re

from .ast import Comment, DhcpdConfig, Subnet

_INTERFACE_COMMENT_RE = re.compile(r"^interface:\s*(\S+)$")


def _index_of(nodes: list, target: object) -> int | None:
    for i, node in enumerate(nodes):
        if node is target:
            return i
    return None


def get_subnet_interface(config: DhcpdConfig, subnet: Subnet) -> str | None:
    idx = _index_of(config.nodes, subnet)
    if idx is None or idx == 0:
        return None
    prev = config.nodes[idx - 1]
    if isinstance(prev, Comment):
        match = _INTERFACE_COMMENT_RE.match(prev.text.strip())
        if match:
            return match.group(1)
    return None


def set_subnet_interface(config: DhcpdConfig, subnet: Subnet, interface: str) -> None:
    """Set (or clear, if `interface` is empty) the interface tag on a
    subnet that's already present in `config.nodes`."""
    idx = _index_of(config.nodes, subnet)
    if idx is None:
        return
    if idx > 0:
        prev = config.nodes[idx - 1]
        if isinstance(prev, Comment) and _INTERFACE_COMMENT_RE.match(prev.text.strip()):
            config.nodes.pop(idx - 1)
            idx -= 1
    if interface:
        config.nodes.insert(idx, Comment(f"interface: {interface}"))
