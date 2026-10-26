"""Canonical JSON for captures and outputs; the strict reader of configurations and capture lines.

ONE SPELLING PER VALUE
----------------------
A capture line is hashed as bytes (R15, SPEC:68), so a value has exactly one admissible
spelling: keys sorted, `,` and `:` without spaces, every non-ASCII character escaped (supplementary
characters as surrogate pairs, escapes in lowercase hexadecimal), `/` not escaped. That is what
`json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)` writes,
and the specification names that call, so `canonical_bytes` is that call with the value checked
first. The check is the part `json.dumps` does not do: it would write a lone surrogate as an
escape without complaint, an integer of any size, and a float wherever one appears. A capture
holds no float at all (SPEC:68) and only integers within 2^53 - 1; the output stream (RED-15)
may hold finite floats, written with Python's shortest repr, so `floats=True` admits them there.

THE STRICT READER
-----------------
Python's `json` module is lenient in exactly the places the contract is not (OPS-06, RED-04): it
keeps the last of two duplicate keys, turns `NaN` and `1e400` into non-finite floats, accepts a
lone surrogate escape, and parses `1.0` where an integer belongs (jsonschema then calls it an
integer, and the canonical round trip writes `1.0` back, so neither later check notices).
`strict_loads` therefore parses through hooks that refuse nothing on the spot but leave a marker
in place of each suspicious item, and then walks the result in document order: the first marker
it meets is the refusal, with the JSON Pointer of where it sits. Refusing in document order, not
in the order the parser happened to call its hooks (inner objects first), is what makes "the
first error" well defined.

Nesting is bounded before parsing: no valid configuration or capture line nests deeper than
four, and Python's parser fails on very deep input with an interpreter-dependent RecursionError,
so a document deeper than `MAX_DEPTH` is refused as a whole, the same way on every interpreter.

This module raises `StrictJsonError` (a `ValueError`) for content it refuses and `TypeError` for
a Python value that is not JSON at all. Neither ever leaves the public API: `config` and
`capture` turn a refusal into the `HlaError` of their own path form.
"""

from __future__ import annotations

import hashlib
import json
import math

from synapse_hla import errors

#: SPEC:68: "All raw numeric values are integers <= 9007199254740991", the largest integer an
#: IEEE double holds exactly, so that a reader in any language gets the number that was written.
MAX_EXACT_INTEGER = 9007199254740991

#: The deepest nesting either reader admits. A configuration nests two levels, a capture line
#: four (frame, event, attributes, attribute); the bound only has to sit far above that and far
#: below the interpreter's recursion limit.
MAX_DEPTH = 32

# Reasons a document is refused, as constants so that callers can map them to their own messages
# without matching text.
INVALID_UTF8 = "invalid_utf8"
BYTE_ORDER_MARK = "byte_order_mark"
CARRIAGE_RETURN = "carriage_return"
TOO_DEEP = "too_deep"
NOT_JSON = "not_json"
DUPLICATE_KEY = "duplicate_key"
NON_FINITE = "non_finite"
FLOAT = "float"
INTEGER_RANGE = "integer_range"
LONE_SURROGATE = "lone_surrogate"


class StrictJsonError(ValueError):
    """A document or value the canonical rules refuse: `reason` and the pointer tokens of where.

    `tokens` is the path from the root as keys and list indexes; `()` means the whole document
    (a syntax error, invalid UTF-8, a byte order mark, too deep a nesting).
    """

    def __init__(self, reason: str, tokens: tuple = ()) -> None:
        super().__init__(reason, tokens)
        self.reason = reason
        self.tokens = tokens


# ------------------------------------------------------------------------------------- pointers

def json_pointer(tokens) -> str:
    """RFC 6901 pointer for `tokens`, each key made safe first (CR-R0-04, CR-R1-04).

    A key comes from the input and the pointer ends up in an `HlaError` path, so each key goes
    through `errors.safe_text` (refused code points replaced, at most 64 characters) before `~`
    and `/` are escaped. A list index is written in decimal.
    """
    parts = []
    for token in tokens:
        text = str(token) if type(token) is int else errors.safe_text(token)
        parts.append("/" + text.replace("~", "~0").replace("/", "~1"))
    return "".join(parts)


# ------------------------------------------------------------------------------------- writing

def _has_lone_surrogate(text: str) -> bool:
    # An ASCII string cannot hold one; that covers nearly every string a capture carries.
    return not text.isascii() and any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _check_value(value, tokens: tuple, floats: bool, depth: int) -> None:
    if depth > MAX_DEPTH:
        raise StrictJsonError(TOO_DEEP, ())
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError("a JSON object key must be a str")
            here = tokens + (key,)
            if _has_lone_surrogate(key):
                raise StrictJsonError(LONE_SURROGATE, here)
            _check_value(item, here, floats, depth + 1)
    elif kind is list:
        for index, item in enumerate(value):
            _check_value(item, tokens + (index,), floats, depth + 1)
    elif kind is str:
        if _has_lone_surrogate(value):
            raise StrictJsonError(LONE_SURROGATE, tokens)
    elif kind is int:
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            raise StrictJsonError(INTEGER_RANGE, tokens)
    elif kind is float:
        if not floats:
            raise StrictJsonError(FLOAT, tokens)
        if not math.isfinite(value):
            raise StrictJsonError(NON_FINITE, tokens)
    elif kind is bool or value is None:
        return
    else:
        raise TypeError(f"{kind.__name__} is not a JSON value")


def canonical_bytes(value, *, floats: bool = False) -> bytes:
    """The one canonical spelling of `value`, as ASCII bytes without a line end.

    Refuses (StrictJsonError) a lone surrogate in any key or string, an integer beyond 2^53 - 1, a
    non-finite float, any float unless `floats`, and nesting deeper than `MAX_DEPTH`; refuses
    (TypeError) anything that is not exactly dict, list, str, int, float, bool or None, and a key
    that is not a str. Subclasses are refused too: an int subclass or a str subclass can change
    how it prints.
    """
    _check_value(value, (), floats, 1)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def sha256_hex(data: bytes) -> str:
    """Lowercase hexadecimal SHA-256 of `data`: the 64-character digest form of SPEC:68."""
    return hashlib.sha256(data).hexdigest()


def record_sha256(record: dict) -> str:
    """The digest a frame or footer carries: SHA-256 of the canonical record without `sha256`.

    SPEC:68 for frames, RED-20 for the footer. The header is not hashed this way: its digest is
    that of its exact line bytes, which `sha256_hex` gives.
    """
    body = {key: value for key, value in record.items() if key != "sha256"}
    return sha256_hex(canonical_bytes(body))


# ------------------------------------------------------------------------------------- reading

class _Object:
    """An object as the parser saw it: its members in document order, duplicates included."""

    __slots__ = ("pairs",)

    def __init__(self, pairs) -> None:
        self.pairs = pairs


class _Refused:
    """A number token the walk will refuse, standing where the parser met it."""

    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        self.reason = reason


def _depth_exceeds(text: str, bound: int) -> bool:
    # Fast path: fewer opening brackets than the bound cannot nest deeper than it.
    if text.count("[") + text.count("{") <= bound:
        return False
    depth = 0
    in_string = escaped = False
    for ch in text:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "[{":
            depth += 1
            if depth > bound:
                return True
        elif ch in "]}":
            depth -= 1
    return False


def _parse_int(text: str):
    # Bounded before conversion: int() of a very long digit string is refused by the interpreter
    # with a ValueError of its own, and a value beyond 2^53 - 1 is refused by SPEC:68 anyway.
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > len(str(MAX_EXACT_INTEGER)):
        return _Refused(INTEGER_RANGE)
    value = int(text)
    if abs(value) > MAX_EXACT_INTEGER:
        return _Refused(INTEGER_RANGE)
    return value


def _settle(value, tokens: tuple, surrogates: bool, values: bool):
    """Plain dicts from the parser's objects, refusing a duplicate key; with `values`, also the
    value problems (a refused number, a lone surrogate), all in one walk in document order."""
    kind = type(value)
    if kind is _Object:
        out = {}
        for key, item in value.pairs:
            here = tokens + (key,)
            if values and not surrogates and _has_lone_surrogate(key):
                raise StrictJsonError(LONE_SURROGATE, here)
            if key in out:
                raise StrictJsonError(DUPLICATE_KEY, here)
            out[key] = _settle(item, here, surrogates, values)
        return out
    if kind is list:
        return [_settle(item, tokens + (index,), surrogates, values)
                for index, item in enumerate(value)]
    if values:
        _value_problem(value, tokens, surrogates)
    return value


def _value_problem(value, tokens: tuple, surrogates: bool) -> None:
    kind = type(value)
    if kind is str:
        if not surrogates and _has_lone_surrogate(value):
            raise StrictJsonError(LONE_SURROGATE, tokens)
    elif kind is _Refused:
        raise StrictJsonError(value.reason, tokens)


def _value_problems(value, tokens: tuple, surrogates: bool) -> None:
    """The second stage of a staged read: value problems, in document order."""
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            here = tokens + (key,)
            if not surrogates and _has_lone_surrogate(key):
                raise StrictJsonError(LONE_SURROGATE, here)
            _value_problems(item, here, surrogates)
    elif kind is list:
        for index, item in enumerate(value):
            _value_problems(item, tokens + (index,), surrogates)
    else:
        _value_problem(value, tokens, surrogates)


def strict_loads(data: bytes, *, floats: bool, surrogates: bool, staged: bool = False):
    """Parse one JSON document from `data` as the contract reads it, or raise StrictJsonError.

    In order: strict UTF-8 (never a replacement decode), no byte order mark, no carriage return
    (inside a JSON string it would be the escape `\\r`, so a raw one can only be a CRLF line end
    or stray whitespace), nesting at most `MAX_DEPTH`, JSON syntax; then the refusal of a
    duplicate key, and of the value problems: a NaN or Infinity literal, a number that overflows
    to infinity, an integer beyond 2^53 - 1, a float token unless `floats`, and a lone surrogate
    (in a key or a string) unless `surrogates`.

    Which of two such problems is reported follows the rule of the caller. A configuration's
    first error is the first in document order (OPS-06), so by default one walk finds both kinds
    together. A capture line's checks are stages (RED-06: JSON and duplicate keys, then float and
    surrogate), so with `staged` every duplicate key is looked for before any value problem.
    Capture lines are read with neither floats nor surrogates; a configuration with both,
    because R07 admits a finite number where the schema then refuses it, and OPS-06 places the
    surrogate rule after the schema, in `validate_config`.
    """
    if type(data) is not bytes:
        raise TypeError("strict_loads reads bytes")
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise StrictJsonError(INVALID_UTF8) from None
    if text.startswith("\N{ZERO WIDTH NO-BREAK SPACE}"):
        raise StrictJsonError(BYTE_ORDER_MARK)
    if "\r" in text:
        raise StrictJsonError(CARRIAGE_RETURN)
    if _depth_exceeds(text, MAX_DEPTH):
        raise StrictJsonError(TOO_DEEP)

    def number(token: str):
        if not floats:
            return _Refused(FLOAT)
        value = float(token)
        return value if math.isfinite(value) else _Refused(NON_FINITE)

    try:
        parsed = json.loads(text, object_pairs_hook=_Object, parse_int=_parse_int,
                            parse_float=number, parse_constant=lambda _name: _Refused(NON_FINITE))
    except json.JSONDecodeError:
        raise StrictJsonError(NOT_JSON) from None
    if not staged:
        return _settle(parsed, (), surrogates, values=True)
    document = _settle(parsed, (), surrogates, values=False)
    _value_problems(document, (), surrogates)
    return document
