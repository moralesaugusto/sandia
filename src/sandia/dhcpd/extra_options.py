"""Helpers for the free-form "extra options" field on subnet/reservation
forms: whatever Parameter/Option statements a form doesn't explicitly
manage are shown back as raw text, editable, and merged back in on save -
the same "structured fields plus an escape hatch" approach the raw config
page uses for the whole file, just scoped to one block."""

from __future__ import annotations

from .ast import Option, Parameter
from .parser import parse_body_fragment
from .serializer import serialize_nodes


def get_extra_options(body: list, managed_names: set[str]) -> str:
    extra = [node for node in body if isinstance(node, (Parameter, Option)) and node.name not in managed_names]
    return serialize_nodes(extra).strip()


def apply_extra_options(body: list, managed_names: set[str], text: str) -> list:
    """Returns a new body list: managed fields are kept as-is, any
    previously-unmanaged Parameter/Option is dropped and replaced with
    whatever `text` now parses to."""
    kept = [node for node in body if not (isinstance(node, (Parameter, Option)) and node.name not in managed_names)]
    if text.strip():
        kept.extend(parse_body_fragment(text))
    return kept
