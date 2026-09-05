from __future__ import annotations

from .ast import (
    BlankLine,
    Comment,
    DhcpdConfig,
    Group,
    Host,
    Option,
    Parameter,
    Subnet,
    UnknownBlock,
)


class ParseError(Exception):
    pass


def parse(text: str) -> DhcpdConfig:
    return _Scanner(text).parse_config()


def _find_matching_brace(text: str, start: int) -> int:
    """start points just after an opening '{'. Returns the index of the matching '}'."""
    depth = 1
    i = start
    n = len(text)
    in_quotes = False
    while i < n:
        c = text[i]
        if in_quotes:
            if c == '"':
                in_quotes = False
            i += 1
            continue
        if c == '"':
            in_quotes = True
            i += 1
            continue
        if c == "#":
            j = text.find("\n", i)
            i = n if j == -1 else j
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ParseError("unterminated block: missing closing '}'")


def _make_statement(header_text: str) -> Parameter | Option:
    first, _, rest = header_text.partition(" ")
    rest = rest.strip()
    if first == "option":
        name, _, value = rest.partition(" ")
        return Option(name=name, value=value.strip())
    return Parameter(name=first, value=rest)


def _make_block(header_text: str, body: list) -> Host | Subnet | Group:
    words = header_text.split()
    kind = words[0]
    if kind == "subnet":
        network = words[1] if len(words) > 1 else ""
        netmask = words[3] if len(words) > 3 and words[2] == "netmask" else ""
        return Subnet(network=network, netmask=netmask, body=body)
    if kind == "host":
        name = words[1] if len(words) > 1 else ""
        return Host(name=name, body=body)
    return Group(body=body)


_KNOWN_BLOCK_KEYWORDS = {"subnet", "host", "group"}


class _Scanner:
    def __init__(self, text: str, line_already_has_content: bool = False):
        self.text = text
        self.n = len(text)
        self.i = 0
        # True for block bodies: the char right before this slice was the
        # block's opening '{', so the very first "line" here is really a
        # continuation of the header line, not a fresh one - its immediate
        # trailing newline must not be mistaken for a blank line.
        self._pending_first_line = line_already_has_content

    def parse_config(self) -> DhcpdConfig:
        return DhcpdConfig(nodes=self._parse_body())

    def _parse_body(self) -> list:
        nodes: list = []
        buf_start = self.i
        line_start = self.i
        in_quotes = False
        while self.i < self.n:
            c = self.text[self.i]
            if in_quotes:
                if c == '"':
                    in_quotes = False
                self.i += 1
                continue
            if c == '"':
                in_quotes = True
                self.i += 1
                continue
            if c == "#":
                pending = self.text[buf_start : self.i]
                if pending.strip():
                    raise ParseError(f"unexpected comment after {pending.strip()!r}")
                j = self.text.find("\n", self.i)
                end = self.n if j == -1 else j
                nodes.append(Comment(self.text[self.i + 1 : end].strip()))
                self.i = end
                buf_start = self.i
                continue
            if c == "\n":
                line_text = self.text[line_start : self.i]
                if not line_text.strip() and not self._pending_first_line:
                    nodes.append(BlankLine())
                self._pending_first_line = False
                line_start = self.i + 1
                self.i += 1
                continue
            if c == ";":
                header_text = self.text[buf_start : self.i].strip()
                self.i += 1
                buf_start = self.i
                if not header_text:
                    raise ParseError("empty statement (stray ';')")
                nodes.append(_make_statement(header_text))
                continue
            if c == "{":
                header_text = self.text[buf_start : self.i].strip()
                if not header_text:
                    raise ParseError("block with empty header")
                close = _find_matching_brace(self.text, self.i + 1)
                inner = self.text[self.i + 1 : close]
                first_word = header_text.split(None, 1)[0]
                if first_word in _KNOWN_BLOCK_KEYWORDS:
                    body = _Scanner(inner, line_already_has_content=True)._parse_body()
                    nodes.append(_make_block(header_text, body))
                else:
                    nodes.append(UnknownBlock(header=header_text, raw_body=inner))
                self.i = close + 1
                buf_start = self.i
                continue
            if c == "}":
                raise ParseError("unexpected '}'")
            self.i += 1
        trailing = self.text[buf_start : self.i].strip()
        if trailing:
            raise ParseError(f"unexpected trailing content: {trailing!r}")
        return nodes
