from __future__ import annotations

from .ast import (
    BlankLine,
    Comment,
    DhcpdConfig,
    Group,
    Host,
    Node,
    Option,
    Parameter,
    Subnet,
    UnknownBlock,
)

INDENT = "    "


def serialize(config: DhcpdConfig) -> str:
    return _serialize_nodes(config.nodes, 0) + "\n"


def _serialize_nodes(nodes: list[Node], level: int) -> str:
    pad = INDENT * level
    lines: list[str] = []
    for node in nodes:
        if isinstance(node, BlankLine):
            lines.append("")
        elif isinstance(node, Comment):
            lines.append(f"{pad}# {node.text}" if node.text else f"{pad}#")
        elif isinstance(node, Parameter):
            lines.append(f"{pad}{node.name} {node.value};" if node.value else f"{pad}{node.name};")
        elif isinstance(node, Option):
            lines.append(f"{pad}option {node.name} {node.value};")
        elif isinstance(node, Host):
            lines.append(f"{pad}host {node.name} {{")
            lines.append(_serialize_nodes(node.body, level + 1))
            lines.append(f"{pad}}}")
        elif isinstance(node, Subnet):
            lines.append(f"{pad}subnet {node.network} netmask {node.netmask} {{")
            lines.append(_serialize_nodes(node.body, level + 1))
            lines.append(f"{pad}}}")
        elif isinstance(node, Group):
            lines.append(f"{pad}group {{")
            lines.append(_serialize_nodes(node.body, level + 1))
            lines.append(f"{pad}}}")
        elif isinstance(node, UnknownBlock):
            # Reproduce the original bytes between the braces exactly - never
            # reformat content this parser doesn't structurally understand.
            lines.append(f"{pad}{node.header} {{{node.raw_body}}}")
        else:
            raise TypeError(f"unknown node type: {type(node)!r}")
    return "\n".join(lines)
