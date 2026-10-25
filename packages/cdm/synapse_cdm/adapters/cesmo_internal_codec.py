"""SC CESMO Internal Exchange 1.0 (`sc.cesmo.internal/1.0`): the contract half of adapter #34.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
The contract of the "SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0" (Decent
Cybersecurity, 4 October 2026): an INTERNAL JSON exchange that a gateway outside this repository
emits after it has decoded, checked and journalled its native traffic. This module holds the
contract's JSON Schema as a module literal (`SCHEMA`, published byte-identical beside the package
as `schemas/cesmo_internal/cesmo-internal-1.0.schema.json`, because the wheel carries no
`schemas/` directory), the strict parser for octets and for a dict, the contract's caps, the
validator and the refusal type. It parses no CESMO unit and no STANAG 4658 or AEDP-13 message:
that binding is BLOCKED on the kit's unresolved register N01-N12 and nothing of it exists here.
The mapping to CDM is `adapters/cesmo_internal.py`.

THE ORDER A DOCUMENT IS JUDGED IN (first failure wins)
------------------------------------------------------
1. The entry: JSON octets (`bytes`, `bytearray`, `memoryview`) or a `dict`; anything else is
   E_SCHEMA. Octets: more than 1 048 576 is E_LIMIT, judged on the INPUT octets before any parse
   (never on a re-serialisation); a byte order mark, invalid UTF-8, more than the manifest's 64
   nested containers (read off the characters, before the decoder), a duplicate key,
   `NaN`/`Infinity`, a number no binary64 holds (overflow, or a non-zero literal that underflows
   to zero), an integer literal longer than 309 digits, and trailing content are refused before
   any object exists. A dict is never re-serialised to be measured.
2. The tree, on both paths, in one walk that stops at the 100 001st value: more than 100 000
   JSON values (containers included), then more than the contract's 16 nested containers (the
   root counted as one), then a text value or key longer than 4 096 code points are E_LIMIT; a
   non-`str` key, a lone surrogate, a non-finite float, an integer outside binary64 and a value
   of any type but `dict`, `list`, `str`, `int`, `float`, `bool` or `None` (exact types: no
   subclass, no `Decimal`, no `bytes`, no `set`, no `tuple`) are E_SCHEMA. The count comes first
   because a dict, unlike JSON text, can be cyclic or share one subtree many times over: a walk
   that stops at the bound is finite for every dict, where an unbounded depth walk is not.
3. The discriminator: a `contract` string other than `sc.cesmo.internal/1.0` is
   E_UNSUPPORTED_MESSAGE.
4. The schema (`SCHEMA`, 2020-12): every error is collected and the first by JSON path wins
   (array indices compared as numbers, keys as text, then the keyword), so the verdict never
   depends on dict order or on the interpreter. Each missing `required` key is a finding of its
   own whose path ends in that key, so of several keys missing from one object the first in
   text order is the refusal (`message_id` before `mode`), and the diagnostics name every one
   of them once. `pattern` is read as ECMA-262 reads it: `$`
   only at the end of input and `\\d` only `[0-9]`. `format: date-time` is this module's own
   grammar and calendar (`instant`), never `jsonschema.FormatChecker`, which registers no
   `date-time` checker unless an optional package is importable. `integer` is a JSON integer
   (`4.0` is refused, as the kit says) and neither type admits a `bool`. All of it is E_SCHEMA,
   `records` past 1 000 included (the schema's `maxItems`).
5. The rules the schema cannot state, in the order the specification states them: the mode
   against the constructor (E_MODE_MISMATCH, kit L106), then E_SEMANTIC for a repeated
   `record_id` and an empty `records` without a snapshot (L110), an `object_id` repeated in a
   snapshot (L110), an `eob_upsert` or `eob_delete` without `object_id` (L112), a `status`
   carrying an emitter field (L112), an `eob_delete` carrying a measurement (L112), an ellipse
   without a position and an ellipse whose major semi-axis is shorter than its minor (L139), and
   a snapshot holding a record that is not an `eob_upsert` or whose revision is not the
   snapshot's (L187). Within a rule, records are judged in index order.

REFUSALS
--------
`CesmoError` is a `ValueError` carrying `code`, `path` (slash-separated, `records/<i>/...`, `""`
the whole document), `record_index` (the `<i>` of a `records/<i>` path, else None) and `detail`,
a fixed phrase or a JSON Schema keyword. The message is `"<CODE> <path> <detail>"`, the root
written `(root)`, at most 512 characters; it never quotes a payload value, and every path
component is a name the schema defines or an array index. `CesmoInputTooLarge` and
`CesmoInputTooDeep` are BOTH a `CesmoError` with code E_LIMIT and the SDK's `InputTooLarge` /
`InputTooDeep`: the refusals of the manifest's 1 048 576 octets and 64 containers reach a caller
as either. `CODES` is the specification's §19 table; this module raises the five in
`RAISED_CODES`. E_BINDING_BLOCKED, E_EDITION, E_FRAMING, E_TIME_UNRESOLVED, E_UNKNOWN_CRITICAL,
E_ID_CONFLICT, E_REVISION_CONFLICT, E_LABEL_UNRESOLVED, E_POLICY_DENIED, E_STALE_REPLAY and
E_EGRESS_UNREPRESENTABLE belong to the gateway, the edition plugin and the EOB projector, none of
which is in this repository, and are never raised here.

WHERE THIS IS STRICTER THAN THE KIT'S `validate_contract.py` 1.0
---------------------------------------------------------------
Recorded so a reader of the kit knows why the two disagree; each rests on the specification,
which the kit itself says governs (kit L102 pairs the schema with that validator, and §8 and §19
state the rules below):
- a token ending in a newline is refused (L104: letters, digits, `_`, `-`, `.` only), where the
  kit's Python `$` admits one;
- hour 24 is refused on every interpreter (L108: ordinary seconds), where the kit's
  `datetime.fromisoformat` admits it on Python 3.14;
- a non-ASCII digit in a timestamp is refused by the pattern itself, not only by a later parse;
- the byte cap is on the input octets (L237: "before JSON parse"), not on the kit's
  re-serialisation, so a dict is never refused for its re-serialised size;
- 1 001 records are E_SCHEMA by the schema's `maxItems` on both paths, as in the kit;
- a non-zero number that underflows binary64 to zero and an integer outside binary64 are refused
  (L134: "Overflow or unrepresentable values fail rather than clamp"), where the kit admits them;
- the first failure is chosen by the order above, where the kit sorts schema paths as text
  (`records/10` before `records/2`) and runs its own rules in code order.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import math
import re
from typing import Any, Iterator

import jsonschema

from synapse_cdm import schemas
from synapse_cdm.adapter import InputTooDeep, InputTooLarge, json_nesting_depth

# ------------------------------------------------------------------------- the contract's names

#: The `contract` constant every exchange carries.
CONTRACT = "sc.cesmo.internal/1.0"
#: The record kinds, in the specification's order (L110).
KINDS = ("observation", "eob_upsert", "eob_delete", "status")
#: The reserved record identifier of the snapshot event (L148). `$` is outside the token alphabet,
#: so no source token can carry it: the schema's pattern refuses it as E_SCHEMA.
SNAPSHOT_RECORD_ID = "$snapshot"

#: The caps of the specification's §19, enforced here. They are implementation caps of the
#: internal contract, not statements about any CESMO normative maximum (L234).
MAX_INPUT_BYTES = 1_048_576
MAX_RECORDS = 1_000
MAX_OBJECTS = 2_001
MAX_CONTRACT_DEPTH = 16
MAX_VALUES = 100_000
MAX_TEXT = 4_096
MAX_DIAGNOSTIC = 512
#: The manifest's depth bound, enforced by the SDK before this module runs: the figure most
#: JSON-reading adapters of synapse_cdm declare, and at least eight times the deepest JSON document
#: this adapter ships. The contract's 16 is enforced inside it.
MAX_DEPTH = 64
#: A decimal integer literal of more than 309 digits is above binary64's largest finite value
#: (about 1.8e308), so it is refused before `int()` is asked to read it: the verdict then never
#: depends on the interpreter's integer-string limit (`PYTHONINTMAXSTRDIGITS`).
MAX_INTEGER_DIGITS = 309

#: The specification's §19 error table, every code, in its order.
CODES = (
    "E_BINDING_BLOCKED",
    "E_EDITION",
    "E_FRAMING",
    "E_SCHEMA",
    "E_SEMANTIC",
    "E_TIME_UNRESOLVED",
    "E_MODE_MISMATCH",
    "E_LIMIT",
    "E_UNSUPPORTED_MESSAGE",
    "E_UNKNOWN_CRITICAL",
    "E_ID_CONFLICT",
    "E_REVISION_CONFLICT",
    "E_LABEL_UNRESOLVED",
    "E_POLICY_DENIED",
    "E_STALE_REPLAY",
    "E_EGRESS_UNREPRESENTABLE",
)
#: The five of them this module raises; the other eleven are the gateway's and the projector's.
RAISED_CODES = ("E_SCHEMA", "E_SEMANTIC", "E_MODE_MISMATCH", "E_LIMIT", "E_UNSUPPORTED_MESSAGE")

#: The kit's `cesmo-internal-1.0.schema.json` as data, key for key and in its order. A
#: repository-bound test holds it equal to the published copy, and the copy's SHA-256 to the kit's.
SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contract": {"const": "sc.cesmo.internal/1.0"},
        "mode": {"enum": ["synthetic", "live"]},
        "source": {
            "type": "object",
            "properties": {
                "network_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
                "originator_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
                "identity_epoch": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
            },
            "required": ["network_id", "originator_id", "identity_epoch"],
            "additionalProperties": False,
        },
        "message_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
        "observed_at": {
            "type": "string",
            "format": "date-time",
            "pattern": "^(?:19[7-9][0-9]|[2-9][0-9]{3})-\\d{2}-\\d{2}T\\d{2}:\\d{2}:[0-5]\\d(?:\\.\\d{1,6})?Z$",
        },
        "records": {"type": "array", "maxItems": 1000, "items": {"$ref": "#/$defs/record"}},
        "snapshot": {
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
                "complete": {"type": "boolean"},
                "revision": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
            },
            "required": ["snapshot_id", "complete", "revision"],
            "additionalProperties": False,
        },
    },
    "required": ["contract", "mode", "source", "message_id", "observed_at", "records"],
    "additionalProperties": False,
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:sc:cesmo:internal:1.0",
    "title": "SC CESMO internal exchange only - not an AEDP-13 wire schema",
    "$defs": {
        "record": {
            "type": "object",
            "properties": {
                "record_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
                "kind": {"enum": ["observation", "eob_upsert", "eob_delete", "status"]},
                "revision": {"type": "integer", "minimum": 0, "maximum": 9007199254740991},
                "observed_at": {
                    "type": "string",
                    "format": "date-time",
                    "pattern": "^(?:19[7-9][0-9]|[2-9][0-9]{3})-\\d{2}-\\d{2}T\\d{2}:\\d{2}:[0-5]\\d(?:\\.\\d{1,6})?Z$",
                },
                "object_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
                "position": {"$ref": "#/$defs/position"},
                "signal": {"$ref": "#/$defs/signal"},
                "uncertainty": {"$ref": "#/$defs/ellipse"},
                "affiliation": {"enum": ["FRIENDLY", "HOSTILE", "NEUTRAL", "UNKNOWN"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "extensions": {"type": "object"},
            },
            "required": ["record_id", "kind", "revision", "observed_at"],
            "additionalProperties": False,
        },
        "position": {
            "type": "object",
            "properties": {
                "latitude_deg": {"type": "number", "minimum": -90, "maximum": 90},
                "longitude_deg": {"type": "number", "minimum": -180, "maximum": 180},
                "hae_m": {"type": "number"},
                "method": {"enum": ["estimated", "gnss", "inertial", "manual"]},
            },
            "required": ["latitude_deg", "longitude_deg", "method"],
            "additionalProperties": False,
        },
        "signal": {
            "type": "object",
            "properties": {
                "frequency_hz": {"type": "number", "minimum": 0},
                "bandwidth_hz": {"type": "number", "minimum": 0},
                "pulse_width_s": {"type": "number", "exclusiveMinimum": 0},
                "pri_s": {"type": "number", "exclusiveMinimum": 0},
                "power_dbm": {"type": "number"},
                "bearing_deg_true": {"type": "number", "minimum": 0, "exclusiveMaximum": 360},
                "sensor_id": {"type": "string", "pattern": "^[A-Za-z0-9_.-]{1,64}$"},
            },
            "required": [],
            "additionalProperties": False,
            "minProperties": 1,
        },
        "ellipse": {
            "type": "object",
            "properties": {
                "semi_major_m": {"type": "number", "exclusiveMinimum": 0},
                "semi_minor_m": {"type": "number", "exclusiveMinimum": 0},
                "orientation_deg": {"type": "number", "minimum": 0, "exclusiveMaximum": 180},
                "probability": {"type": "number", "exclusiveMinimum": 0, "maximum": 1},
                "frame": {"const": "ENU_TRUE_NORTH"},
            },
            "required": [
                "semi_major_m",
                "semi_minor_m",
                "orientation_deg",
                "probability",
                "frame",
            ],
            "additionalProperties": False,
        },
    },
}


# -------------------------------------------------------------------------------- the refusals


class CesmoError(ValueError):
    """An exchange this contract refuses.

    `code` is one of `RAISED_CODES`; `path` the slash-separated place (`""` the whole
    document); `record_index` the record a `records/<i>` path names, else None; `detail` a
    fixed phrase or a JSON Schema keyword. None of them is ever a value taken from the payload.
    """

    def __init__(self, code: str, path: str, detail: str) -> None:
        if code not in RAISED_CODES:
            raise ValueError("cesmo_internal: a refusal code this module does not raise")
        self.code, self.path, self.detail = code, path, detail
        parts = path.split("/")
        self.record_index = (
            int(parts[1])
            if len(parts) > 1 and parts[0] == "records" and parts[1].isdigit()
            else None
        )
        super().__init__(f"{code} {path or '(root)'} {detail}"[:MAX_DIAGNOSTIC])

    def __reduce__(self):
        # The conformance suite runs decoders in a worker process and pickles what they raise.
        return (type(self), (self.code, self.path, self.detail))


class CesmoInputTooLarge(CesmoError, InputTooLarge):
    """More than 1 048 576 input octets: E_LIMIT, and the SDK's `InputTooLarge`."""


class CesmoInputTooDeep(CesmoError, InputTooDeep):
    """More than the manifest's 64 containers: E_LIMIT, and the SDK's `InputTooDeep`."""


def render_path(tokens: tuple | list) -> str:
    """`("records", 0, "position")` -> `"records/0/position"`."""
    return "/".join(str(t) for t in tokens)


# --------------------------------------------------------------------------- the strict parser


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            # json.loads would keep the last one silently: a value lost unseen (L102).
            raise CesmoError("E_SCHEMA", "", "duplicate object key")
        out[key] = value
    return out


def _no_constant(_name: str) -> Any:
    raise CesmoError("E_SCHEMA", "", "non-finite number literal")


def _parse_int(text: str) -> int:
    if len(text.lstrip("-")) > MAX_INTEGER_DIGITS:
        raise CesmoError("E_SCHEMA", "", "integer outside binary64")
    value = int(text)
    if not _finite_int(value):
        raise CesmoError("E_SCHEMA", "", "integer outside binary64")
    return value


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise CesmoError("E_SCHEMA", "", "number outside binary64")
    if value == 0.0 and re.search("[1-9]", re.split("[eE]", text)[0]):
        raise CesmoError("E_SCHEMA", "", "number underflows binary64 to zero")
    return value


def _finite_int(value: int) -> bool:
    try:
        float(value)
    except OverflowError:
        return False
    return True


def _parse_octets(octets: bytes) -> Any:
    if len(octets) > MAX_INPUT_BYTES:
        raise CesmoInputTooLarge(
            "E_LIMIT", "", f"{len(octets)} octets past the cap of {MAX_INPUT_BYTES}"
        )
    if octets.startswith(b"\xef\xbb\xbf"):
        raise CesmoError("E_SCHEMA", "", "byte order mark")
    try:
        text = octets.decode("utf-8")
    except UnicodeDecodeError:
        raise CesmoError("E_SCHEMA", "", "not UTF-8") from None
    depth = json_nesting_depth(text)
    if depth > MAX_DEPTH:
        # Before the decoder, which recurses: CPython 3.11's raises RecursionError a little under
        # a thousand containers deep (`adapter.InputTooDeep`'s reading). `to_cdm` has already
        # run the SDK's own bound; this is the same bound for a direct caller.
        raise CesmoInputTooDeep(
            "E_LIMIT", "", f"nesting {depth} containers deep, past the bound of {MAX_DEPTH}"
        )
    try:
        return json.loads(
            text,
            object_pairs_hook=_no_duplicate_keys,
            parse_constant=_no_constant,
            parse_int=_parse_int,
            parse_float=_parse_float,
        )
    except CesmoError:
        raise
    except ValueError:
        # Truncated text, trailing content, a comment, an empty input: not one JSON text.
        raise CesmoError("E_SCHEMA", "", "not one JSON text") from None


#: The tree's E_SCHEMA findings, in the order they are reported when several are present.
_TREE_SCHEMA = (
    "object key is not a string",
    "lone surrogate",
    "non-finite number",
    "integer outside binary64",
    "not a JSON value",
)
_SURROGATE = re.compile("[\ud800-\udfff]")


def _text_problem(text: str, found: set[str]) -> None:
    if len(text) > MAX_TEXT:
        found.add("text")
    if _SURROGATE.search(text) is not None:
        found.add("lone surrogate")


def check_tree(document: Any) -> None:
    """The caps and the value types, on a parsed document from either path.

    One walk, which stops at the 100 001st value (100 000 JSON values, containers included, is
    the cap), so it is finite for a cyclic dict and for one that shares a subtree many times.
    After it: depth (16 containers, the root counted as one), then text past 4 096 code points,
    then the type findings in `_TREE_SCHEMA`'s order. Every finding but the count is collected
    over the whole tree before one is reported, so the verdict depends on the content, never on
    the order a dict was built in.
    """
    found: set[str] = set()
    count, deepest, pending = 0, 0, [(document, 1)]
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > MAX_VALUES:
            raise CesmoError("E_LIMIT", "", f"more than {MAX_VALUES} JSON values")
        kind = type(node)
        if kind is dict:
            deepest = max(deepest, depth)
            for key, value in node.items():
                if type(key) is str:
                    _text_problem(key, found)
                else:
                    found.add("object key is not a string")
                pending.append((value, depth + 1))
        elif kind is list:
            deepest = max(deepest, depth)
            pending.extend((value, depth + 1) for value in node)
        elif kind is str:
            _text_problem(node, found)
        elif kind is float:
            if not math.isfinite(node):
                found.add("non-finite number")
        elif kind is int:
            if not _finite_int(node):
                found.add("integer outside binary64")
        elif kind is not bool and node is not None:
            found.add("not a JSON value")
    if deepest > MAX_CONTRACT_DEPTH:
        raise CesmoError("E_LIMIT", "", f"nesting deeper than {MAX_CONTRACT_DEPTH} containers")
    if "text" in found:
        raise CesmoError("E_LIMIT", "", f"text longer than {MAX_TEXT} code points")
    for detail in _TREE_SCHEMA:
        if detail in found:
            raise CesmoError("E_SCHEMA", "", detail)


def count_values(document: Any) -> None:
    """The value cap alone, in a walk that stops at the 100 001st value: what `to_cdm` runs on a
    dict before the SDK's depth bound, whose own walk of a cyclic dict would never end."""
    count, pending = 0, [document]
    while pending:
        node = pending.pop()
        count += 1
        if count > MAX_VALUES:
            raise CesmoError("E_LIMIT", "", f"more than {MAX_VALUES} JSON values")
        if type(node) is dict:
            pending.extend(node.values())
        elif type(node) is list:
            pending.extend(node)


def parse(raw: Any) -> dict:
    """One exchange as JSON octets or a dict -> the parsed document, checked as a tree but not
    yet against the schema. A `str` is refused: the internal JSON arrives as UTF-8 octets or as
    the dict a caller already parsed (duplicate keys, a byte order mark, invalid UTF-8 and
    non-finite literals are visible in octets only)."""
    kind = type(raw)
    if kind is bytes or kind is bytearray or kind is memoryview:
        document = _parse_octets(bytes(raw))
    elif kind is dict:
        document = raw
    else:
        raise CesmoError("E_SCHEMA", "", "expected JSON octets or a dict")
    check_tree(document)
    if type(document) is not dict:
        raise CesmoError("E_SCHEMA", "", "not a JSON object")
    return document


# ------------------------------------------------------------------------------ the timestamps

_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,6}))?Z",
    re.ASCII,
)


def instant(text: Any) -> tuple[_dt.datetime, bool] | None:
    """A contract timestamp -> (the aware UTC instant, whether the CDM's millisecond rendering
    drops a non-zero digit), or None when it is not one.

    ASCII digits only; year 1970 to 9999; a real calendar day; hour 00-23, minute and second
    00-59; zero to six fraction digits; a literal `Z` (L108). Built with the `datetime`
    constructor from the groups, which refuses hour 24, second 60 and 30 February on every
    interpreter; never `datetime.fromisoformat`, which accepts hour 24 on Python 3.14."""
    match = _TIMESTAMP.fullmatch(text) if type(text) is str else None
    if match is None:
        return None
    year, month, day, hour, minute, second = (int(g) for g in match.groups()[:6])
    fraction = (match.group(7) or "").ljust(6, "0")
    if not 1970 <= year <= 9999:
        return None
    try:
        stamp = _dt.datetime(
            year, month, day, hour, minute, second, int(fraction), tzinfo=_dt.timezone.utc
        )
    except ValueError:
        return None
    return stamp, fraction[3:] != "000"


# ------------------------------------------------------------------------------- the validator

_PATTERNS: dict[str, re.Pattern] = {}


def _ecma_pattern(validator, pattern, instance, schema) -> Iterator[jsonschema.ValidationError]:
    """`pattern` as ECMA-262 reads it: `$` at the end of input only (the repository's
    `schemas._ecma_end_anchors`) and `\\d` as `[0-9]` (`re.ASCII`)."""
    if not validator.is_type(instance, "string"):
        return
    compiled = _PATTERNS.get(pattern)
    if compiled is None:
        compiled = _PATTERNS[pattern] = re.compile(schemas._ecma_end_anchors(pattern), re.ASCII)
    if compiled.search(instance) is None:
        yield jsonschema.ValidationError("pattern")


def _date_time(validator, format_, instance, schema) -> Iterator[jsonschema.ValidationError]:
    if (
        format_ == "date-time"
        and validator.is_type(instance, "string")
        and instant(instance) is None
    ):
        yield jsonschema.ValidationError("date-time")


def _required(validator, required, instance, schema) -> Iterator[jsonschema.ValidationError]:
    """One finding per missing key, the key the last component of its own path. The stock
    keyword reports every missing key at the object's path, which would leave the diagnostics
    unable to say which key each finding is about. The key is the schema's name, not the
    payload's, so it may be named."""
    if not validator.is_type(instance, "object"):
        return
    for key in required:
        if key not in instance:
            yield jsonschema.ValidationError("required", path=(key,))


_TYPES = jsonschema.Draft202012Validator.TYPE_CHECKER.redefine_many(
    {
        # A JSON integer is an integer token: 4.0 is a number and not an integer (L110).
        "integer": lambda _checker, instance: type(instance) is int,
        "number": lambda _checker, instance: type(instance) is int or type(instance) is float,
    }
)
_Validator = jsonschema.validators.extend(
    schemas.EcmaPatternValidator,
    validators={"pattern": _ecma_pattern, "format": _date_time, "required": _required},
    type_checker=_TYPES,
)
#: 2020-12 with the contract's own `pattern`, `format`, `required` and integer readings, and no
#: format checker.
VALIDATOR = _Validator(SCHEMA, format_checker=None)


def _order(error: jsonschema.ValidationError) -> tuple:
    path = tuple((0, t, "") if type(t) is int else (1, 0, str(t)) for t in error.absolute_path)
    return (path, str(error.validator), [str(t) for t in error.relative_schema_path])


def _schema_errors(document: dict) -> list[CesmoError]:
    errors = sorted(VALIDATOR.iter_errors(document), key=_order)
    return [
        CesmoError(
            "E_SCHEMA", render_path(tuple(e.absolute_path)), _DETAIL.get(e.validator, e.validator)
        )
        for e in errors
    ]


#: The detail a schema error carries: the keyword, or for `format` the format's name.
_DETAIL = {"format": "date-time"}


#: The emitter fields a `status` record cannot carry, and the measurements a withdrawal cannot,
#: in the record schema's own order (L112).
STATUS_EXCLUDED = ("object_id", "position", "signal", "uncertainty", "affiliation", "confidence")
DELETE_EXCLUDED = ("position", "signal", "uncertainty", "affiliation", "confidence")


def _semantic_errors(document: dict, synthetic: bool | None) -> Iterator[CesmoError]:
    """The rules the schema cannot state, in the specification's order (the module docstring)."""
    if synthetic is not None and (document["mode"] == "synthetic") is not synthetic:
        yield CesmoError("E_MODE_MISMATCH", "mode", "mode differs from the constructor's")
    records = document["records"]
    snapshot = document.get("snapshot")
    seen: set[str] = set()
    for i, record in enumerate(records):
        if record["record_id"] in seen:
            yield CesmoError("E_SEMANTIC", f"records/{i}/record_id", "repeated record_id")
        seen.add(record["record_id"])
    if not records and snapshot is None:
        yield CesmoError("E_SEMANTIC", "records", "empty records without a snapshot")
    if snapshot is not None:
        objects: set[str] = set()
        for i, record in enumerate(records):
            if "object_id" in record:
                if record["object_id"] in objects:
                    yield CesmoError(
                        "E_SEMANTIC", f"records/{i}/object_id", "object_id repeated in a snapshot"
                    )
                objects.add(record["object_id"])
    for i, record in enumerate(records):
        if record["kind"] in ("eob_upsert", "eob_delete") and "object_id" not in record:
            yield CesmoError("E_SEMANTIC", f"records/{i}/object_id", "object_id required")
    for i, record in enumerate(records):
        if record["kind"] == "status":
            for key in STATUS_EXCLUDED:
                if key in record:
                    yield CesmoError(
                        "E_SEMANTIC", f"records/{i}/{key}", "status carries no emitter field"
                    )
                    break
    for i, record in enumerate(records):
        if record["kind"] == "eob_delete":
            for key in DELETE_EXCLUDED:
                if key in record:
                    yield CesmoError(
                        "E_SEMANTIC", f"records/{i}/{key}", "withdrawal carries no measurement"
                    )
                    break
    for i, record in enumerate(records):
        if "uncertainty" in record and "position" not in record:
            yield CesmoError(
                "E_SEMANTIC", f"records/{i}/uncertainty", "ellipse requires a position"
            )
    for i, record in enumerate(records):
        ellipse = record.get("uncertainty")
        if ellipse is not None and ellipse["semi_major_m"] < ellipse["semi_minor_m"]:
            yield CesmoError(
                "E_SEMANTIC",
                f"records/{i}/uncertainty/semi_minor_m",
                "semi_minor_m above semi_major_m",
            )
    if snapshot is not None:
        for i, record in enumerate(records):
            if record["kind"] != "eob_upsert":
                yield CesmoError(
                    "E_SEMANTIC", f"records/{i}/kind", "a snapshot holds eob_upsert only"
                )
        for i, record in enumerate(records):
            if record["revision"] != snapshot["revision"]:
                yield CesmoError(
                    "E_SEMANTIC", f"records/{i}/revision", "revision differs from the snapshot's"
                )


def _judge(raw: Any, synthetic: bool | None) -> tuple[dict, list[CesmoError]]:
    """The parsed document and every finding of the first judging stage that has any (`[]`
    when it is accepted). The entry, the tree and the discriminator refuse by raising."""
    document = parse(raw)
    contract = document.get("contract")
    if type(contract) is str and contract != CONTRACT:
        raise CesmoError("E_UNSUPPORTED_MESSAGE", "contract", "not sc.cesmo.internal/1.0")
    found = _schema_errors(document)
    if not found:
        found = list(_semantic_errors(document, synthetic))
    return document, found


def validate(raw: Any, *, synthetic: bool | None = None) -> dict:
    """The whole judgement, first failure wins; returns a deep copy of the accepted document, so
    no container of the caller's is ever shared with an emitted object or changed. `synthetic`
    given is the constructor's flag the document's `mode` must agree with."""
    document, found = _judge(raw, synthetic)
    if found:
        raise found[0]
    return copy.deepcopy(document)


def diagnostics(raw: Any, *, synthetic: bool | None = None) -> list[str]:
    """Every finding of the first stage that has any, each `"<CODE> <path> <detail>"`, in the
    order `validate` judges them (so the first is the refusal `validate` raises); `[]` when the
    document is accepted. A refusal is returned, never raised."""
    try:
        return [str(e) for e in _judge(raw, synthetic)[1]]
    except CesmoError as refusal:
        return [str(refusal)]
