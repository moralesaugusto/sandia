"""Comment-preserving edits to Kea's JSON-with-comments config text.

patch_json(text, old, new) rewrites only the parts of `text` whose parsed
value differs between `old` (what `text` parses to) and `new`: changed
scalars are replaced in place, removed members/elements are cut out,
added ones are inserted next to their siblings. Everything else - comments,
formatting, key order, unknown keys - stays byte-for-byte as it was. Only
comments *inside* a value that is replaced wholesale are lost.
"""

from __future__ import annotations

import difflib
import json
import re
from dataclasses import dataclass, field

from .parser import ParseError

_SCALAR_RE = re.compile(r"-?\d[\d.eE+-]*|true|false|null")


@dataclass
class _Node:
    kind: str  # "object" | "array" | "scalar"
    start: int
    end: int
    # object: (key, member_start, value); array: (None, item_start, value)
    children: list[tuple[str | None, int, _Node]] = field(default_factory=list)


class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.i = 0

    def skip(self) -> None:
        text, n = self.text, len(self.text)
        while self.i < n:
            c = text[self.i]
            if c.isspace():
                self.i += 1
            elif c == "#" or text.startswith("//", self.i):
                while self.i < n and text[self.i] != "\n":
                    self.i += 1
            elif text.startswith("/*", self.i):
                end = text.find("*/", self.i + 2)
                self.i = n if end == -1 else end + 2
            elif text.startswith("<?include", self.i):
                raise ParseError("this Kea config uses <?include?>; edit it on the Raw Config page")
            else:
                return

    def string_end(self) -> int:
        i = self.i + 1
        while i < len(self.text) and self.text[i] != '"':
            i += 2 if self.text[i] == "\\" else 1
        if i >= len(self.text):
            raise ParseError("unterminated string in Kea config")
        return i + 1

    def value(self) -> _Node:
        self.skip()
        if self.i >= len(self.text):
            raise ParseError("unexpected end of Kea config")
        c = self.text[self.i]
        if c in "{[":
            return self.container("}" if c == "{" else "]")
        start = self.i
        if c == '"':
            self.i = self.string_end()
        else:
            match = _SCALAR_RE.match(self.text, self.i)
            if not match:
                raise ParseError(f"unexpected character {c!r} in Kea config")
            self.i = match.end()
        return _Node("scalar", start, self.i)

    def container(self, close: str) -> _Node:
        node = _Node("object" if close == "}" else "array", self.i, -1)
        self.i += 1
        while True:
            self.skip()
            if self.i >= len(self.text):
                raise ParseError("unterminated block in Kea config")
            c = self.text[self.i]
            if c == close:
                self.i += 1
                node.end = self.i
                return node
            if c == ",":
                self.i += 1
                continue
            member_start = self.i
            key = None
            if node.kind == "object":
                if c != '"':
                    raise ParseError("expected a quoted key in Kea config")
                end = self.string_end()
                key = json.loads(self.text[self.i : end])
                self.i = end
                self.skip()
                if self.text[self.i : self.i + 1] != ":":
                    raise ParseError("expected ':' in Kea config")
                self.i += 1
            node.children.append((key, member_start, self.value()))


def _line_start(text: str, pos: int) -> int:
    return text.rfind("\n", 0, pos) + 1


def _indent_at(text: str, pos: int) -> str:
    start = _line_start(text, pos)
    line = text[start:pos]
    return line[: len(line) - len(line.lstrip())]


def _dump(value, indent: str) -> str:
    return json.dumps(value, indent=4).replace("\n", "\n" + indent)


def _member_text(key: str | None, value, indent: str) -> str:
    body = _dump(value, indent)
    return body if key is None else f"{json.dumps(key)}: {body}"


# Keys that identify a Kea list entry (subnet, pool, reservation, option,
# class): an edited entry is patched in place only if one of these still
# matches, so an unrelated replacement is a clean delete + insert instead.
_IDENTITY_KEYS = ("id", "subnet", "pool", "name", "code", "hw-address", "client-id", "duid", "circuit-id", "flex-id", "ip-address")


def _same_item(old, new) -> bool:
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return not isinstance(old, (dict, list)) and not isinstance(new, (dict, list))
    return any(key in old and old.get(key) == new.get(key) for key in _IDENTITY_KEYS)


class _Patcher:
    def __init__(self, text: str):
        self.text = text
        self.edits: list[tuple[int, int, str]] = []

    def comma_after(self, pos: int) -> int | None:
        """Index of the separator comma following a value ending at pos."""
        parser = _Parser(self.text)
        parser.i = pos
        parser.skip()
        return parser.i if self.text[parser.i : parser.i + 1] == "," else None

    def diff(self, node: _Node, old, new) -> None:
        if old == new:
            return
        if node.kind == "object" and isinstance(old, dict) and isinstance(new, dict) and node.children:
            members = {key: (index, child) for index, (key, _, child) in enumerate(node.children)}
            remove = [members[key][0] for key in old if key not in new and key in members]
            for key in old.keys() & new.keys():
                self.diff(members[key][1], old[key], new[key])
            self.resize(node, remove, [(key, new[key]) for key in new if key not in old], new)
        elif node.kind == "array" and isinstance(old, list) and isinstance(new, list) and node.children:
            canon = lambda v: json.dumps(v, sort_keys=True)
            matcher = difflib.SequenceMatcher(a=[canon(v) for v in old], b=[canon(v) for v in new], autojunk=False)
            remove, add = [], []
            for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                if tag == "equal":
                    continue
                paired = 0
                if tag == "replace":
                    while paired < min(i2 - i1, j2 - j1) and _same_item(old[i1 + paired], new[j1 + paired]):
                        self.diff(node.children[i1 + paired][2], old[i1 + paired], new[j1 + paired])
                        paired += 1
                remove.extend(range(i1 + paired, i2))
                add.extend((None, value) for value in new[j1 + paired : j2])
            self.resize(node, remove, add, new)
        else:
            self.edits.append((node.start, node.end, _dump(new, _indent_at(self.text, node.start))))

    def resize(self, node: _Node, remove: list[int], add: list[tuple[str | None, object]], new) -> None:
        children = node.children
        removed = set(remove)
        kept = [i for i in range(len(children)) if i not in removed]
        if not kept and add:
            self.edits.append((node.start, node.end, _dump(new, _indent_at(self.text, node.start))))
            return
        for index in sorted(removed):
            _, start, child = children[index]
            begin = _line_start(self.text, start) if not self.text[_line_start(self.text, start) : start].strip() else start
            comma = self.comma_after(child.end)
            end = comma + 1 if comma is not None else child.end
            newline = self.text.find("\n", end)
            if newline != -1 and not self.text[end:newline].strip():
                end = newline + 1
            self.edits.append((begin, end, ""))
        if not kept:
            return
        last_kept = kept[-1]
        if removed and max(removed) > last_kept:
            # The last surviving child's separator would become a trailing comma.
            comma = self.comma_after(children[last_kept][2].end)
            if comma is not None:
                self.edits.append((comma, comma + 1, ""))
        if not add:
            return
        if "\n" in self.text[node.start : node.end]:
            child_indent = _indent_at(self.text, children[0][1])
            separator = ",\n" + child_indent
            items = [_member_text(key, value, child_indent) for key, value in add]
        else:  # keep a one-line container on one line
            separator = ", "
            items = [json.dumps(value) if key is None else f"{json.dumps(key)}: {json.dumps(value)}" for key, value in add]
        end = children[last_kept][2].end
        self.edits.append((end, end, separator + separator.join(items)))

    def result(self) -> str:
        text = self.text
        for start, end, replacement in sorted(self.edits, key=lambda e: (e[0], e[1]), reverse=True):
            text = text[:start] + replacement + text[end:]
        return text


def patch_json(text: str, old, new) -> str:
    if not text.strip():
        return json.dumps(new, indent=4) + "\n"
    parser = _Parser(text)
    root = parser.value()
    patcher = _Patcher(text)
    patcher.diff(root, old, new)
    return patcher.result()
