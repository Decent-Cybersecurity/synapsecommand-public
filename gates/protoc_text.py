"""protoc's text format, read back into Python values. Build-time and test-time only.

`protoc` prints a message as text in the two places the `tacticalapi` adapter's checks use it as
the oracle: `--decode=google.protobuf.FileDescriptorSet` (the field table,
`gates/tacticalapi_field_table.py`) and `--decode=<type>` of a written payload (the independent
readings under `fixtures/tacticalapi/independent/`, read by
`tests/test_cdm_tacticalapi_fixtures.py`). Reading that text with the adapter's own protobuf
decoder would make the decoder its own judge, so the text is read here instead, by a parser that
knows the text format and nothing about the contract. Moved here on 2026-10-06 with the adapter;
nothing in the package imports it.

WHAT IS READ
------------
The subset protoc's printer writes: `name: scalar`, `name { ... }` (and `name: { ... }`, and
`< ... >` as the alternative delimiters), a field name that is an identifier, a bare field number
(how `--decode` prints a field the type does not name) or a bracketed name (how an expanded `Any`
or an extension is printed), and `#` comments. A scalar is a quoted string, a number or an
identifier. List syntax (`name: [a, b]`) is not read; protoc never prints it.

WHAT COMES BACK
---------------
A message is a list of `(name, value)` pairs in text order, because a name may repeat and order
is part of what protoc said. A value is `bytes` (a quoted string, with its C escapes undone — the
text format's strings are octets, and a caller that knows the field is a `string` decodes them),
`int`, `float`, an `Identifier` (an enum value name, `true`, `false`, `inf`, `nan`), or a nested
message. Nothing is coerced by guessing at the field's type: that is the caller's knowledge.
"""
from __future__ import annotations

import re
from typing import Any, Iterator


class TextFormatError(ValueError):
    """Text this reader does not accept, with the character offset where it stopped."""


class Identifier(str):
    """A bare word in a value position: an enum value name, `true`, `false`, `inf`, `nan`.

    A subclass of `str` so it compares and prints as the word, and a distinct type so a caller can
    tell the enum value `FOO` from the string `"FOO"`.
    """


#: Field-name / value tokens, one alternative per kind. Whitespace and `#` comments are skipped.
#: The number pattern admits what protoc prints for integers and doubles (`-12`, `0x1F`, `1.5`,
#: `1e+30`, `-0`); `inf`, `-inf` and `nan` arrive as identifiers, as protoc spells them.
_TOKEN = re.compile(r"""
    (?P<skip>[ \t\r\n\f\v]+|\#[^\n]*)
  | (?P<string>"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*')
  | (?P<bracket>\[[^\]\n]*\])
  | (?P<punct>[{}<>:;,])
  | (?P<number>-?(?:0[xX][0-9a-fA-F]+|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)[fF]?(?![A-Za-z_]))
  | (?P<ident>-?[A-Za-z_][A-Za-z0-9_.]*)
""", re.VERBOSE)

_SIMPLE_ESCAPES = {
    "n": b"\n", "r": b"\r", "t": b"\t", '"': b'"', "'": b"'", "\\": b"\\",
    "a": b"\a", "b": b"\b", "f": b"\f", "v": b"\v", "?": b"?",
}


def _tokens(text: str) -> Iterator[tuple[str, str, int]]:
    position = 0
    while position < len(text):
        match = _TOKEN.match(text, position)
        if match is None:
            raise TextFormatError(f"unreadable text at offset {position}: {text[position:position + 20]!r}")
        kind = match.lastgroup
        if kind != "skip":
            yield kind, match.group(), position
        position = match.end()


def unescape(quoted: str) -> bytes:
    """The octets a quoted text-format string stands for: C escapes (`\\n`, `\\"`, octal `\\ooo`,
    hex `\\xHH`) undone, `\\u`/`\\U` written as UTF-8, every other character written as UTF-8."""
    body = quoted[1:-1]
    out = bytearray()
    index = 0
    while index < len(body):
        char = body[index]
        if char != "\\":
            out += char.encode("utf-8")
            index += 1
            continue
        index += 1
        if index >= len(body):
            raise TextFormatError(f"string ends in a lone backslash: {quoted!r}")
        char = body[index]
        if char in _SIMPLE_ESCAPES:
            out += _SIMPLE_ESCAPES[char]
            index += 1
        elif char in "01234567":
            digits = re.match(r"[0-7]{1,3}", body[index:]).group()
            value = int(digits, 8)
            if value > 0xFF:
                raise TextFormatError(f"octal escape \\{digits} is past one octet in {quoted!r}")
            out.append(value)
            index += len(digits)
        elif char in "xX":
            match = re.match(r"[0-9a-fA-F]{1,2}", body[index + 1:])
            if match is None:
                raise TextFormatError(f"\\x without hex digits in {quoted!r}")
            out.append(int(match.group(), 16))
            index += 1 + len(match.group())
        elif char in "uU":
            width = 4 if char == "u" else 8
            digits = body[index + 1:index + 1 + width]
            if not re.fullmatch(r"[0-9a-fA-F]{%d}" % width, digits):
                raise TextFormatError(f"\\{char} needs {width} hex digits in {quoted!r}")
            out += chr(int(digits, 16)).encode("utf-8")
            index += 1 + width
        else:
            raise TextFormatError(f"unknown escape \\{char} in {quoted!r}")
    return bytes(out)


def _number(token: str) -> int | float:
    body = token[:-1] if token[-1] in "fF" and not token.lower().startswith(("0x", "-0x")) else token
    if re.fullmatch(r"-?0[xX][0-9a-fA-F]+", body):
        return int(body, 16)
    if re.fullmatch(r"-?[0-9]+", body):
        return int(body, 10)
    return float(body)


def parse(text: str) -> list[tuple[str, Any]]:
    """The message `text` prints, as `(name, value)` pairs in text order (see the module doc)."""
    tokens = list(_tokens(text))
    position = 0

    def peek() -> tuple[str, str, int] | None:
        return tokens[position] if position < len(tokens) else None

    def take() -> tuple[str, str, int]:
        nonlocal position
        token = peek()
        if token is None:
            raise TextFormatError("text ends inside a message")
        position += 1
        return token

    def scalar() -> Any:
        kind, value, offset = take()
        if kind == "string":
            octets = unescape(value)
            # Adjacent quoted strings are one value, as in C.
            while (following := peek()) is not None and following[0] == "string":
                octets += unescape(take()[1])
            return octets
        if kind == "number":
            return _number(value)
        if kind == "ident":
            return Identifier(value)
        raise TextFormatError(f"expected a value at offset {offset}, found {value!r}")

    def message(close: str | None) -> list[tuple[str, Any]]:
        fields: list[tuple[str, Any]] = []
        while True:
            token = peek()
            if token is None:
                if close is None:
                    return fields
                raise TextFormatError(f"text ends before the closing {close!r}")
            kind, value, offset = token
            if kind == "punct" and value == close:
                take()
                return fields
            if kind not in ("ident", "number", "bracket"):
                raise TextFormatError(f"expected a field name at offset {offset}, found {value!r}")
            take()
            name = value
            colon = False
            if (following := peek()) is not None and following[:2] == ("punct", ":"):
                take()
                colon = True
            following = peek()
            if following is not None and following[0] == "punct" and following[1] in "{<":
                take()
                fields.append((name, message("}" if following[1] == "{" else ">")))
            elif colon:
                fields.append((name, scalar()))
            else:
                raise TextFormatError(f"field {name!r} at offset {offset} has neither ':' nor a "
                                      "message body")
            if (following := peek()) is not None and following[0] == "punct" and following[1] in ";,":
                take()

    return message(None)


def values(fields: list[tuple[str, Any]], name: str) -> list[Any]:
    """Every value printed under `name`, in text order (a repeated field, or nothing)."""
    return [value for key, value in fields if key == name]


def single(fields: list[tuple[str, Any]], name: str, default: Any = None) -> Any:
    """The one value printed under `name`, `default` when it is absent; two is an error."""
    found = values(fields, name)
    if len(found) > 1:
        raise TextFormatError(f"{name!r} is printed {len(found)} times where one was expected")
    return found[0] if found else default


def text(fields: list[tuple[str, Any]], name: str, default: str | None = None) -> str | None:
    """`single()` for a string field, decoded as UTF-8."""
    value = single(fields, name)
    if value is None:
        return default
    if not isinstance(value, bytes):
        raise TextFormatError(f"{name!r} is {value!r}, not a quoted string")
    return value.decode("utf-8")
