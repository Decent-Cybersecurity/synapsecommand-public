"""SC Link16 Gateway 1.0.0 report -> CDM, and back. Adapter #23.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
SC Link16 Gateway 1.0.0 is an internal JSON interface this repository defines: one report is
one complete track snapshot that a gateway (outside this package) has already decoded from its
native traffic. This module reads that report and nothing else. It parses no JREAP C frame, no
Link 16 message and no J-series word, holds no socket, no store, no clock and no cache, and
claims no native interoperability: native traffic is the provider's, behind a boundary outside
this package that refuses with BLOCKED_EXTERNAL_EVIDENCE until a normative profile, independent
byte vectors and a peer test exist. The gateway contract is published beside the package as
`schemas/link16_gateway/report.schema.json` (and the notice and API schemas next to it);
`REPORT_SCHEMA` below is that schema as a module literal, because the wheel carries no
`schemas/` directory, and a repository-bound test holds the two equal.

ONE MODULE ON PURPOSE
---------------------
The contract (the schema literal, the strict parser, the validator, the refusal type and
`ExportContext`) and the adapter live in this one module. The JSON-decoder sweep of
`tests/test_cdm_parser_safety.py` derives the decoding adapters from each class's own modules,
so a helper module holding the `json.loads` call would take the adapter out of every JSON
sweep. The runtime bridge imports the contract from here, so the bridge's validation and the
translator's cannot diverge.

WHAT A REPORT BECOMES
---------------------
`[Entity]`, or `[Entity, Track]` when the report's position is present and projected. The
Entity carries the whole validated report in `residual.data.report`; the single-sample Track
carries `residual.data.record_id`. Identity is the uuid5 of the compact identity tuple
`[tenant, realm, synthetic, origin_scope, track_number, incarnation]` under system
`Link16Track`; reporter, session, gateway, record, sequence and receipt time are provenance and
never identity. `source.system` is the one token `SC_LINK16_GATEWAY` (the roster listing parses
whitespace-separated columns), while `source.format_name` keeps "SC Link16 Gateway".

A height stated as HAE in feet becomes metres in both `vertical` and `alt_m` (x 0.3048) with
the feet kept in the residual; every other datum keeps the stated value and unit, and `alt_m`
stays null. That departs from `Position.vertical`'s description ("never converted") because
the position model only lets `alt_m` stand beside an HAE vertical in metres, and the contract
asks for `alt_m` whenever the height is ellipsoidal.

`cdm_schema="3.0.0"` selects the compatibility projection: a report whose position method is
SENSOR or UNKNOWN (CDM 3.1.0 members) yields an Entity with no position and no Track, the
transformation `POSITION_NOT_PROJECTED_CDM3: source method is unrepresentable`, and the report
still whole in the residual. Every other report projects in full, stamped "3.0.0".

THE TWO EGRESS MODES
--------------------
`mode="mirror"` (the default) reconstructs the report from this adapter's own Entity and its
optional Track, and refuses every disagreement with the canonical projection as
CDM_SOURCE_CONFLICT. `mode="export"` builds one gateway report from a CDM Entity and an optional
single-sample Track under an immutable `ExportContext` the runtime supplies after it has
authorised the export; unrepresentable values are refused or omitted with a loss record, never
substituted. Neither mode transmits anything.

REFUSALS
--------
Every refusal is `Link16GatewayRefusal` (a `ValueError`) with a `code` from the contract's
error table, a `path` and a `rule`; its message is `CODE: path — rule` and never quotes a
payload value. Above the manifest's 1 048 576 octets or 64 containers the base class refuses
first, with `InputTooLarge` / `InputTooDeep`.
"""
from __future__ import annotations

import copy
import dataclasses
import datetime as _dt
import json
import math
import re
from typing import Any

import jsonschema

from synapse_cdm import ids, lossless, schemas, times
from synapse_cdm.adapter import Adapter, InputTooDeep, InputTooLarge, container_depth, \
    json_nesting_depth
from synapse_cdm.enums import Affiliation, EntityType, PositionSource, VerticalReference, \
    VerticalUnit
from synapse_cdm.geo import VerticalPosition
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                  Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                  Limitation, Limits, Maturity, MaturityLevel, Residual,
                                  UnknownFields, WireBinding)
from synapse_cdm.models import (CDMBase, Entity, Kinematics, Position, Quality, SourceId, Track,
                                TrackSample)
from synapse_cdm.models import Residual as ResidualBlock
from synapse_cdm.version import SCHEMA_VERSION

# ------------------------------------------------------------------------- the contract's names

#: The `profile` constant every report carries.
PROFILE = "sc-link16-gateway/1.0.0"
#: `metadata.format.name`: the residual namespace and `SourceRef.format_name`.
FORMAT_NAME = "SC Link16 Gateway"
FORMAT_VERSION = "1.0.0"
#: `SourceRef.system`: one token, because `--list-adapters` prints whitespace-separated columns.
SYSTEM = "SC_LINK16_GATEWAY"
#: The `SourceId.system` of the identity tuple, and the system `ids.derive` hashes under.
IDENTITY_SYSTEM = "Link16Track"
#: The `cdm_schema` value that selects the compatibility projection.
COMPAT_SCHEMA = "3.0.0"

#: The contract's per-report limits: 1 MiB of UTF-8, 32 levels, 10 000 JSON value nodes.
MAX_REPORT_BYTES = 1_048_576
MAX_REPORT_DEPTH = 32
MAX_REPORT_NODES = 10_000
#: The manifest's depth bound: the harness loader's own figure and at least eight times the
#: deepest JSON document this adapter ships. The contract's 32 is enforced inside, below it.
MAX_DEPTH = 64
UINT64_MAX = 2 ** 64 - 1
FEET_TO_METRES = 0.3048

#: The identity tuple, in the order the contract fixes (never sorted).
IDENTITY_KEYS = ("tenant", "realm", "synthetic", "origin_scope", "track_number", "incarnation")
#: The report tokens the CDM's four affiliations hold as they are.
CANONICAL_AFFILIATIONS = ("FRIENDLY", "HOSTILE", "NEUTRAL", "UNKNOWN")
#: Position methods the frozen 3.0.0 contract cannot state.
CDM_3_1_METHODS = ("SENSOR", "UNKNOWN")
#: Entity types a gateway report can state; the others refuse in export.
EXPORTABLE_ENTITY_TYPES = ("PLATFORM", "UNIT", "FACILITY", "UNKNOWN")
#: The report's `quality_code` holds at most this many characters (its schema's maxLength).
QUALITY_CODE_MAX = 128

#: The four timestamps a report carries, as paths.
TIME_PATHS = (("received_at",), ("effective_at",), ("position", "observed_at"),
              ("kinematics", "observed_at"))

T_IDENTITY = "identity: UUID5 over scoped track instance"
T_AFFILIATION = "identity: finer source affiliation projected to UNKNOWN"
T_FEET = "vertical: HAE feet converted to metres using 0.3048"
T_COMPAT = "POSITION_NOT_PROJECTED_CDM3: source method is unrepresentable"

#: The contract's error table, every code (eighteen). The bridge shares this vocabulary.
CODES = (
    "SCHEMA_INVALID", "JSON_INVALID", "LIMIT_EXCEEDED", "SYNTHETIC_MISMATCH",
    "SECURITY_CONTEXT_MISMATCH", "TIME_UNRESOLVED", "IDENTITY_SCOPE_UNRESOLVED",
    "REUSE_AMBIGUOUS", "UNSUPPORTED_MESSAGE", "UNSUPPORTED_FIELD_FORM",
    "NATIVE_PROFILE_INCOMPLETE", "CDM_SOURCE_CONFLICT", "ALTITUDE_DATUM_UNSUPPORTED",
    "VALUE_NOT_REPRESENTABLE", "DUPLICATE_CONFLICT", "CURSOR_EXPIRED", "STREAM_GAP",
    "SEND_OUTCOME_UNKNOWN",
)
#: The eight of them this adapter raises. The other ten are the runtime's.
ADAPTER_CODES = (
    "JSON_INVALID", "SCHEMA_INVALID", "LIMIT_EXCEEDED", "SYNTHETIC_MISMATCH", "TIME_UNRESOLVED",
    "CDM_SOURCE_CONFLICT", "ALTITUDE_DATUM_UNSUPPORTED", "VALUE_NOT_REPRESENTABLE",
)

#: The gateway report schema (JSON Schema 2020-12), the published
#: `schemas/link16_gateway/report.schema.json` as data. 28 properties, 28 required.
REPORT_SCHEMA: dict[str, Any] = (
    {"type": "object",
     "properties": {"profile": {"const": "sc-link16-gateway/1.0.0"},
                    "record_id": {"type": "string", "format": "uuid"},
                    "gateway_id": {"type": "string",
                                   "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
                    "session_id": {"type": "string", "format": "uuid"},
                    "sequence": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,19})$"},
                    "received_at": {"type": "string",
                                    "format": "date-time",
                                    "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$"},
                    "effective_at": {"type": "string",
                                     "format": "date-time",
                                     "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$"},
                    "time_basis": {"type": "string",
                                   "enum": ["SOURCE", "RESOLVED_SOURCE", "EXERCISE"]},
                    "time_evidence": {"type": "string", "minLength": 1, "maxLength": 512},
                    "tenant": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
                    "realm": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
                    "synthetic": {"type": "boolean"},
                    "origin_scope": {"type": "string",
                                     "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
                    "reporter": {"type": "string", "minLength": 1, "maxLength": 128},
                    "track_number": {"type": "string", "minLength": 1, "maxLength": 64},
                    "incarnation": {"type": "string", "pattern": "^(0|[1-9][0-9]{0,19})$"},
                    "message_family": {"type": "string", "minLength": 1, "maxLength": 32},
                    "native_profile": {"type": "string", "minLength": 1, "maxLength": 128},
                    "domain": {"type": "string",
                               "enum": ["AIR", "SURFACE", "SUBSURFACE", "LAND", "UNKNOWN"]},
                    "entity_kind": {"type": "string",
                                    "enum": ["PLATFORM", "UNIT", "FACILITY", "UNKNOWN"]},
                    "identity": {"type": "string",
                                 "enum": ["FRIENDLY",
                                          "HOSTILE",
                                          "NEUTRAL",
                                          "UNKNOWN",
                                          "PENDING",
                                          "ASSUMED_FRIEND",
                                          "SUSPECT",
                                          "OTHER"]},
                    "identity_code": {"anyOf": [{"type": "string",
                                                 "minLength": 1,
                                                 "maxLength": 128},
                                                {"type": "null"}]},
                    "position": {"anyOf": [{"type": "object",
                                            "properties": {"observed_at": {"type": "string",
                                                                           "format": "date-time",
                                                                           "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$"},
                                                           "lat_deg": {"type": "number",
                                                                       "minimum": -90,
                                                                       "maximum": 90},
                                                           "lon_deg": {"type": "number",
                                                                       "minimum": -180,
                                                                       "maximum": 180},
                                                           "method": {"type": "string",
                                                                      "enum": ["GNSS",
                                                                               "INERTIAL",
                                                                               "MANUAL",
                                                                               "ESTIMATED",
                                                                               "SENSOR",
                                                                               "UNKNOWN"]},
                                                           "vertical": {"anyOf": [{"type": "object",
                                                                                   "properties": {"value": {"type": "number"},
                                                                                                  "unit": {"type": "string",
                                                                                                           "enum": ["m",
                                                                                                                    "ft",
                                                                                                                    "FL"]},
                                                                                                  "reference": {"type": "string",
                                                                                                                "enum": ["HAE",
                                                                                                                         "MSL",
                                                                                                                         "AGL",
                                                                                                                         "BARO",
                                                                                                                         "FL",
                                                                                                                         "UNKNOWN"]}},
                                                                                   "required": ["value",
                                                                                                "unit",
                                                                                                "reference"],
                                                                                   "additionalProperties": False},
                                                                                  {"type": "null"}]}},
                                            "required": ["observed_at",
                                                         "lat_deg",
                                                         "lon_deg",
                                                         "method",
                                                         "vertical"],
                                            "additionalProperties": False},
                                           {"type": "null"}]},
                    "kinematics": {"anyOf": [{"type": "object",
                                              "properties": {"observed_at": {"type": "string",
                                                                             "format": "date-time",
                                                                             "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}\\.\\d{3}Z$"},
                                                             "speed_mps": {"anyOf": [{"type": "number",
                                                                                      "minimum": 0},
                                                                                     {"type": "null"}]},
                                                             "course_deg": {"anyOf": [{"type": "number",
                                                                                       "minimum": 0,
                                                                                       "exclusiveMaximum": 360},
                                                                                      {"type": "null"}]},
                                                             "climb_mps": {"anyOf": [{"type": "number"},
                                                                                     {"type": "null"}]}},
                                              "required": ["observed_at",
                                                           "speed_mps",
                                                           "course_deg",
                                                           "climb_mps"],
                                              "additionalProperties": False},
                                             {"type": "null"}]},
                    "quality_code": {"anyOf": [{"type": "string", "minLength": 1, "maxLength": 128},
                                               {"type": "null"}]},
                    "security_context": {"type": "string",
                                         "pattern": "^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$"},
                    "source_fields": {"type": "object"},
                    "extensions": {"type": "object"}},
     "required": ["profile",
                  "record_id",
                  "gateway_id",
                  "session_id",
                  "sequence",
                  "received_at",
                  "effective_at",
                  "time_basis",
                  "time_evidence",
                  "tenant",
                  "realm",
                  "synthetic",
                  "origin_scope",
                  "reporter",
                  "track_number",
                  "incarnation",
                  "message_family",
                  "native_profile",
                  "domain",
                  "entity_kind",
                  "identity",
                  "identity_code",
                  "position",
                  "kinematics",
                  "quality_code",
                  "security_context",
                  "source_fields",
                  "extensions"],
     "additionalProperties": False,
     "$schema": "https://json-schema.org/draft/2020-12/schema",
     "$id": "urn:synapsecommand:sc-link16-gateway:report:1.0.0",
     "title": "SC Link16 Gateway report 1.0.0 internal profile"}
)


class Link16GatewayRefusal(ValueError):
    """A report, or an egress request, this adapter refuses.

    `code` is one of `ADAPTER_CODES`; `path` names the offending place in the report (or, in
    egress, in the CDM objects) with `lossless.render_path`'s spelling, `""` meaning the whole
    document; `rule` is a fixed phrase or a JSON Schema keyword. None of the three is ever a
    value taken from the payload. `losses` is the export loss record (empty otherwise), the
    refused entry last.
    """

    def __init__(self, code: str, path: str, rule: str, losses: tuple = ()) -> None:
        if code not in CODES:
            raise ValueError("link16_gateway: a refusal code outside the contract's table")
        self.code, self.path, self.rule = code, path, rule
        self.losses = tuple(losses)
        super().__init__(f"{code}: {path or '(report)'} — {rule}")


def _refuse(code: str, path: str, rule: str) -> Link16GatewayRefusal:
    return Link16GatewayRefusal(code, path, rule)


# --------------------------------------------------------------------------- the strict parser

def _exact_int(value: int) -> bool:
    """Is this integer exactly a finite double (so every JSON reader reads the same number)?"""
    try:
        return int(float(value)) == value
    except OverflowError:
        return False


def _parse_int(text: str) -> int:
    value = int(text)
    if not _exact_int(value):
        raise _refuse("JSON_INVALID", "", "integer not exactly representable as a double")
    return value


def _parse_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise _refuse("JSON_INVALID", "", "number overflows a finite double")
    if value == 0.0 and re.search(r"[1-9]", re.split(r"[eE]", text)[0]):
        raise _refuse("JSON_INVALID", "", "number underflows a double to zero")
    return value


def _parse_constant(name: str) -> Any:
    raise _refuse("JSON_INVALID", "", "non-finite number literal")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise _refuse("JSON_INVALID", "", "duplicate object key")
        out[key] = value
    return out


def _utf8(text: str) -> None:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise _refuse("JSON_INVALID", "", "invalid Unicode scalar value") from None


def _walk(document: Any) -> None:
    """Every node of a parsed document, iteratively: the node bound and the value types."""
    nodes, pending = 0, [document]
    while pending:
        node = pending.pop()
        nodes += 1
        if nodes > MAX_REPORT_NODES:
            raise _refuse("LIMIT_EXCEEDED", "", "more than 10000 JSON value nodes")
        kind = type(node)
        if kind is dict:
            for key, value in node.items():
                if type(key) is not str:
                    raise _refuse("JSON_INVALID", "", "object key is not a string")
                _utf8(key)
                pending.append(value)
        elif kind is list:
            pending.extend(node)
        elif kind is str:
            _utf8(node)
        elif kind is float:
            if not math.isfinite(node):
                raise _refuse("JSON_INVALID", "", "non-finite number")
        elif kind is int:
            if not _exact_int(node):
                raise _refuse("JSON_INVALID", "", "integer not exactly representable as a double")
        elif kind is bool or node is None:
            pass
        else:
            raise _refuse("JSON_INVALID", "", "not a JSON value")


def parse_report(raw: Any) -> Any:
    """One report as JSON octets or a dict -> the parsed document, before the schema.

    Octets: size, byte order mark, strict UTF-8, depth off the characters, then `json.loads`
    refusing duplicate keys, non-finite literals and numbers no double holds, then the node
    walk. A dict: depth off the containers, the node walk, then its compact UTF-8 size. Any
    other input — text, a list, a subclass — is refused: a report arrives as octets or as the
    dict a caller already parsed (duplicate keys, a byte order mark, invalid UTF-8 and
    non-finite literals are visible in octets only).
    """
    kind = type(raw)
    if kind is bytes or kind is bytearray or kind is memoryview:
        octets = bytes(raw)
        if len(octets) > MAX_REPORT_BYTES:
            raise _refuse("LIMIT_EXCEEDED", "", "report above 1048576 octets")
        if octets.startswith(b"\xef\xbb\xbf"):
            raise _refuse("JSON_INVALID", "", "byte order mark")
        try:
            text = octets.decode("utf-8")
        except UnicodeDecodeError:
            raise _refuse("JSON_INVALID", "", "not UTF-8") from None
        if json_nesting_depth(text) > MAX_REPORT_DEPTH:
            raise _refuse("LIMIT_EXCEEDED", "", "nesting above 32")
        try:
            document = json.loads(text, object_pairs_hook=_no_duplicate_keys,
                                  parse_constant=_parse_constant, parse_int=_parse_int,
                                  parse_float=_parse_float)
        except Link16GatewayRefusal:
            raise
        except (ValueError, RecursionError):
            raise _refuse("JSON_INVALID", "", "not a JSON text") from None
        _walk(document)
        return document
    if kind is dict:
        if container_depth(raw) > MAX_REPORT_DEPTH:
            raise _refuse("LIMIT_EXCEEDED", "", "nesting above 32")
        _walk(raw)
        size = len(json.dumps(raw, ensure_ascii=False, separators=(",", ":"),
                              allow_nan=False).encode("utf-8"))
        if size > MAX_REPORT_BYTES:
            raise _refuse("LIMIT_EXCEEDED", "", "report above 1048576 octets")
        return raw
    raise _refuse("JSON_INVALID", "", "expected JSON octets or a dict")


# ------------------------------------------------------------------------------ the validator

_PATTERNS: dict[str, re.Pattern] = {}


def _ecma_digits(pattern: str) -> str:
    """`\\d` as ECMA-262 reads it, `[0-9]` (inside a class `0-9`): Python's matches every
    Unicode decimal digit, and the house rule is that the Python answer is the one a
    validator in another language gives."""
    out, i, in_class = [], 0, False
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\" and i + 1 < len(pattern):
            pair = pattern[i:i + 2]
            out.append(("0-9" if in_class else "[0-9]") if pair == "\\d" else pair)
            i += 2
            continue
        if in_class:
            in_class = ch != "]"
        elif ch == "[":
            in_class = True
        out.append(ch)
        i += 1
    return "".join(out)


def _ecma_pattern(validator, pattern, instance, schema):
    if not validator.is_type(instance, "string"):
        return
    compiled = _PATTERNS.get(pattern)
    if compiled is None:
        compiled = _PATTERNS[pattern] = re.compile(
            schemas._ecma_end_anchors(_ecma_digits(pattern)))
    if compiled.search(instance) is None:
        yield jsonschema.ValidationError("pattern")


#: 2020-12, `pattern` read as ECMA-262 reads it (end anchors AND `\d`), and NO format checker:
#: `jsonschema.FormatChecker()` registers `date-time` only where an optional package is
#: importable, so the refusal code would depend on the environment. `format: uuid` and
#: `format: date-time` are enforced below, explicitly.
_ReportValidator = jsonschema.validators.extend(schemas.EcmaPatternValidator,
                                                {"pattern": _ecma_pattern})
VALIDATOR = _ReportValidator(REPORT_SCHEMA, format_checker=None)

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_DECIMAL = re.compile(r"0|[1-9][0-9]{0,19}")
_TIMESTAMP = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
                        r"\.([0-9]{3})Z")


def _leaf(error: jsonschema.ValidationError) -> jsonschema.ValidationError:
    """The error a refusal names, for one schema error: an `anyOf` (the contract's "object or
    null" fields) is descended into the one branch that did not fail on the instance's type, and
    inside it the deepest error wins, ties broken by path and keyword, so the choice never
    depends on iteration order; when every branch fails on the type, the refusal is `type`.
    `best_match` alone stops at the `anyOf` whenever two errors of the branch are equally
    relevant (four missing keys, say)."""
    while error.context:
        here = list(error.absolute_path)
        branches: dict = {}
        for inner in error.context:
            branches.setdefault(inner.relative_schema_path[0], []).append(inner)
        live = [errs for _branch, errs in sorted(branches.items(), key=lambda kv: str(kv[0]))
                if not all(e.validator == "type" and list(e.absolute_path) == here for e in errs)]
        if not live:                    # no branch admits the instance's type at all
            return min(error.context, key=lambda e: str(e.relative_schema_path))
        if len(live) > 1:
            return error
        error = min(live[0], key=lambda e: (-len(e.absolute_path),
                                            [str(t) for t in e.absolute_path], str(e.validator)))
    return error


def _schema_refusal(errors: list) -> Link16GatewayRefusal:
    best = _leaf(jsonschema.exceptions.best_match(errors))
    leaves = [_leaf(e) for e in errors]
    if all(e.validator == "pattern" and tuple(e.absolute_path) in TIME_PATHS for e in leaves):
        # D-17: a timestamp whose SHAPE is wrong (a non-ASCII digit, no milliseconds) is an
        # unresolved time, as the contract says of every time it cannot read.
        return _refuse("TIME_UNRESOLVED", lossless.render_path(tuple(best.absolute_path)),
                       "not YYYY-MM-DDTHH:mm:ss.sssZ")
    path = tuple(best.absolute_path)
    if best.validator == "required" and isinstance(best.instance, dict):
        # The missing key is the schema's name, not the payload's, so it may be named.
        missing = [k for k in best.validator_value if k not in best.instance]
        if missing:
            path += (missing[0],)
    return _refuse("SCHEMA_INVALID", lossless.render_path(path), str(best.validator))


def instant(text: str, path: str) -> _dt.datetime:
    """One contract timestamp -> an aware UTC datetime, on a strict calendar.

    Built from the ASCII groups with the `datetime` constructor, which refuses second 60, hour 24
    and February 30 on every interpreter this package supports. Never `times.parse`: on Python
    3.14 `fromisoformat` accepts hour 24 and moves it to the next midnight.
    """
    match = _TIMESTAMP.fullmatch(text) if type(text) is str else None
    if match is None:
        raise _refuse("TIME_UNRESOLVED", path, "not YYYY-MM-DDTHH:mm:ss.sssZ")
    y, mo, d, h, mi, s, ms = (int(g) for g in match.groups())
    try:
        return _dt.datetime(y, mo, d, h, mi, s, ms * 1000, tzinfo=_dt.timezone.utc)
    except ValueError:
        raise _refuse("TIME_UNRESOLVED", path, "not a calendar instant") from None


def validate_report(document: Any, *, synthetic: bool | None = None) -> dict:
    """The schema, then the contract's rules the schema cannot state, first failure wins.

    In order: the schema (`SCHEMA_INVALID`, or `TIME_UNRESOLVED` when the only failures are the
    shape of timestamps); `record_id` and `session_id` in canonical lowercase 8-4-4-4-12 form;
    `sequence` and `incarnation` within uint64; the flight-level unit and reference together; the
    four timestamps on a strict calendar; component times at or before `effective_at`; and, when
    `synthetic` is given, the report's flag equal to it (`SYNTHETIC_MISMATCH`). Returns a deep
    copy, so the caller's containers are never shared with an emitted object.
    """
    errors = list(VALIDATOR.iter_errors(document))
    if errors:
        raise _schema_refusal(errors)
    for key in ("record_id", "session_id"):
        if _UUID.fullmatch(document[key]) is None:
            raise _refuse("SCHEMA_INVALID", key, "canonical lowercase UUID")
    for key in ("sequence", "incarnation"):
        if int(document[key]) > UINT64_MAX:
            raise _refuse("SCHEMA_INVALID", key, "uint64")
    position = document["position"]
    if position is not None and position["vertical"] is not None:
        vertical = position["vertical"]
        if (vertical["unit"] == "FL") != (vertical["reference"] == "FL"):
            raise _refuse("SCHEMA_INVALID", "position.vertical",
                          "FL unit and FL reference together")
    instant(document["received_at"], "received_at")
    effective = instant(document["effective_at"], "effective_at")
    for component in ("position", "kinematics"):
        if document[component] is not None:
            path = f"{component}.observed_at"
            if instant(document[component]["observed_at"], path) > effective:
                raise _refuse("TIME_UNRESOLVED", path, "component time after effective_at")
    if synthetic is not None and document["synthetic"] is not synthetic:
        raise _refuse("SYNTHETIC_MISMATCH", "synthetic", "constructor value differs")
    return copy.deepcopy(document)


def identity_key(report: dict) -> str:
    """The identity tuple as compact, ASCII-escaped JSON, in the contract's fixed order."""
    return json.dumps([report[k] for k in IDENTITY_KEYS], ensure_ascii=True,
                      separators=(",", ":"))


# ----------------------------------------------------------------------------- export context

def _context_error(field: str, rule: str, kind: type = ValueError) -> Exception:
    return kind(f"link16_gateway configuration: export_context.{field} — {rule}")


_CONTEXT_TEXT = {
    # field: (pattern or None, min length, max length)
    "gateway_id": (_IDENTIFIER, 1, 128), "tenant": (_IDENTIFIER, 1, 128),
    "realm": (_IDENTIFIER, 1, 128), "origin_scope": (_IDENTIFIER, 1, 128),
    "security_context": (_IDENTIFIER, 1, 128), "record_id": (_UUID, 36, 36),
    "session_id": (_UUID, 36, 36), "sequence": (_DECIMAL, 1, 20),
    "incarnation": (_DECIMAL, 1, 20), "time_evidence": (None, 1, 512),
    "reporter": (None, 1, 128), "track_number": (None, 1, 64), "message_family": (None, 1, 32),
    "native_profile": (None, 1, 128), "source_field_profile": (None, 1, 128),
}
_CONTEXT_ENUM = {
    "time_basis": ("SOURCE", "RESOLVED_SOURCE", "EXERCISE"),
    "domain": ("AIR", "SURFACE", "SUBSURFACE", "LAND", "UNKNOWN"),
}
_UNITS = ("m", "ft", "FL")
_REFERENCES = ("HAE", "MSL", "AGL", "BARO", "FL", "UNKNOWN")
#: The two object-valued context fields and how many containers of an emitted report sit above
#: each: `source_fields` is a report key (the report itself), and `provenance` lands at
#: `extensions["sc-link16-export/1"].provenance` (the report, `extensions` and the namespace
#: object). Each field's depth bound is the contract's 32 less that figure, so a context that
#: constructs never fails an export on its own depth (2026-10-10).
_CONTEXT_OBJECTS = {"source_fields": 1, "provenance": 3}


@dataclasses.dataclass(frozen=True, slots=True)
class ExportContext:
    """Everything an export needs that a CDM object cannot supply (the contract's REQ091).

    Prepared by the runtime AFTER it has authorised the export, and immutable: the envelope
    (`record_id` … `time_evidence`), the destination-allocated identity tuple (`tenant`,
    `realm`, `synthetic`, `origin_scope`, `track_number`, `incarnation`), the reporting
    authority, the provider-supported `message_family`, the selected `native_profile`, the
    `domain` (the CDM has none), the `security_context`, the source-field mapping profile and
    the fields prepared under it, the provenance for the destination, the explicit export times
    of the position and of the motion, and the vertical forms the destination's native form
    supports (`(unit, reference)` pairs; empty means it carries no height).

    Each field is checked at construction against the rule the report schema applies to the
    report field of the same name; a refusal names the field and the rule and never the value.
    `source_fields` and `provenance` are given as JSON objects and STORED AS THEIR COMPACT JSON
    TEXT, so no caller can change a frozen context through a nested dict:
    `source_fields_object()` and `provenance_object()` return a fresh copy each time.

    Which bound is checked where (2026-10-10). At construction, each of the two objects ALONE
    against the contract's limits at the place it lands in an emitted report: depth 31 for
    `source_fields` (one container, the report, above it) and depth 29 for `provenance` (three
    above it: the report, `extensions` and `extensions["sc-link16-export/1"]`), at most 10 000
    JSON value nodes, and at most 1 048 576 octets of compact UTF-8. The depth check is
    sufficient: a context that constructs never fails an export on one field's depth. The node
    and octet checks are necessary, not sufficient: the rest of the report takes nodes and
    octets too, so a field near either limit can construct and still be refused at export.
    What no single field shows — the two objects together, or either with the rest of the
    report, over the node or octet bound — is checked at export: the assembled report passes
    `parse_report` and `validate_report` again (the self-check), and an excess is refused there
    as LIMIT_EXCEEDED with no loss record, nothing being emitted.
    """

    record_id: str
    gateway_id: str
    session_id: str
    sequence: str
    received_at: str
    time_basis: str
    time_evidence: str
    tenant: str
    realm: str
    synthetic: bool
    origin_scope: str
    track_number: str
    incarnation: str
    reporter: str
    message_family: str
    native_profile: str
    domain: str
    security_context: str
    source_field_profile: str
    source_fields: Any
    provenance: Any
    position_observed_at: str | None = None
    kinematics_observed_at: str | None = None
    vertical_forms: Any = ()
    vertical_required: bool = False

    def __post_init__(self) -> None:
        for name, (pattern, low, high) in _CONTEXT_TEXT.items():
            value = getattr(self, name)
            if type(value) is not str:
                raise _context_error(name, "must be a str", TypeError)
            if not low <= len(value) <= high or \
                    (pattern is not None and pattern.fullmatch(value) is None):
                raise _context_error(name, "does not satisfy the report field's rule")
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise _context_error(name, "invalid Unicode scalar value") from None
        for name in ("sequence", "incarnation"):
            if int(getattr(self, name)) > UINT64_MAX:
                raise _context_error(name, "uint64")
        for name, allowed in _CONTEXT_ENUM.items():
            value = getattr(self, name)
            if type(value) is not str:
                raise _context_error(name, "must be a str", TypeError)
            if value not in allowed:
                raise _context_error(name, "not a member of the report field's enumeration")
        for name in ("synthetic", "vertical_required"):
            if type(getattr(self, name)) is not bool:
                raise _context_error(name, "must be a bool", TypeError)
        self._time("received_at", self.received_at, required=True)
        self._time("position_observed_at", self.position_observed_at, required=False)
        self._time("kinematics_observed_at", self.kinematics_observed_at, required=False)
        for name, above in _CONTEXT_OBJECTS.items():
            value = getattr(self, name)
            if type(value) is not dict:
                raise _context_error(name, "must be a JSON object (dict)", TypeError)
            try:
                bound = MAX_REPORT_DEPTH - above
                if container_depth(value) > bound:
                    raise _refuse("LIMIT_EXCEEDED", "", f"nesting above {bound}")
                _walk(value)
                text = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                                  allow_nan=False)
                if len(text.encode("utf-8")) > MAX_REPORT_BYTES:
                    raise _refuse("LIMIT_EXCEEDED", "", "above 1048576 octets")
            except Link16GatewayRefusal as refusal:
                raise _context_error(name, f"not a bounded JSON object ({refusal.rule})") \
                    from None
            object.__setattr__(self, name, text)
        forms = self.vertical_forms
        if type(forms) not in (tuple, list):
            raise _context_error("vertical_forms", "must be a tuple of (unit, reference)",
                                 TypeError)
        normal = []
        for pair in forms:
            if type(pair) not in (tuple, list) or len(pair) != 2 or \
                    not all(type(x) is str for x in pair):
                raise _context_error("vertical_forms", "each entry is a (unit, reference) pair",
                                     TypeError)
            unit, reference = pair
            if unit not in _UNITS or reference not in _REFERENCES or \
                    (unit == "FL") != (reference == "FL"):
                raise _context_error("vertical_forms",
                                     "a pair the report's vertical object cannot state")
            if (unit, reference) not in normal:
                normal.append((unit, reference))
        object.__setattr__(self, "vertical_forms", tuple(normal))

    @staticmethod
    def _time(name: str, value: Any, *, required: bool) -> None:
        if value is None and not required:
            return
        if type(value) is not str:
            raise _context_error(name, "must be a str timestamp", TypeError)
        try:
            instant(value, name)
        except Link16GatewayRefusal:
            raise _context_error(name, "not a YYYY-MM-DDTHH:mm:ss.sssZ calendar instant") \
                from None

    def source_fields_object(self) -> dict:
        """A fresh copy of the source fields, as a dict."""
        return json.loads(self.source_fields)

    def provenance_object(self) -> dict:
        """A fresh copy of the provenance, as a dict."""
        return json.loads(self.provenance)


# -------------------------------------------------------------------------------- the ledger

def _m(to: str, rule: str = "identity", **params: Any) -> lossless.Mapping:
    return lossless.Mapping(to, rule, params=params)


def _r(path: str) -> lossless.Mapping:
    return lossless.Mapping(f"entity:residual.data.report.{path}", kind="residual")


def _null_or_number(to: str) -> lossless.Mapping:
    return lossless.Mapping(to, "absent_if", params={"sentinel": None, "else": "number"})


def _build_mappings() -> dict:
    """The ledger (REQ085). Every leaf of the report lands in `residual.data.report` (the last
    key, a residual by prefix), and each leaf the projection reads is ALSO declared canonical,
    the residual member first so the entry's category is the canonical one. Three projections
    the grammar cannot state stay residual-only and are asserted by the mapping tests: the
    vertical value and unit under the HAE-feet conversion, the identity tuple composite in
    `source_ids[0].external_id`, and every position field under the compatibility projection
    (`MAPPINGS` is read off the class, and the harness and the suite build the default)."""
    return {
        "record_id": (_r("record_id"), _m("entity:source.original_id")),
        "effective_at": (_r("effective_at"), _m("entity:valid_from", "instant"),
                         _m("entity:source.observed_at", "instant")),
        "synthetic": (_r("synthetic"), _m("entity:source.synthetic")),
        "entity_kind": (_r("entity_kind"), _m("entity:entity_type")),
        "identity": (_r("identity"), _m("entity:affiliation", "enum_map",
                                        table={k: k for k in ("FRIENDLY", "HOSTILE", "NEUTRAL")},
                                        default="UNKNOWN")),
        "quality_code": (_r("quality_code"),
                         _m("entity:quality.source_quality", "absent_if", sentinel=None)),
        "position": (_r("position"), _m("entity:position", "absent_if", sentinel=None)),
        "position.observed_at": (_r("position.observed_at"),
                                 _m("track:samples[0].observed_at", "instant")),
        "position.lat_deg": (_r("position.lat_deg"), _m("entity:position.lat", "number"),
                             _m("track:samples[0].position.lat", "number")),
        "position.lon_deg": (_r("position.lon_deg"), _m("entity:position.lon", "number"),
                             _m("track:samples[0].position.lon", "number")),
        "position.method": (_r("position.method"), _m("entity:position.position_source"),
                            _m("track:samples[0].position.position_source")),
        "position.vertical": (_r("position.vertical"),
                              _m("entity:position.vertical", "absent_if", sentinel=None)),
        "position.vertical.reference": (_r("position.vertical.reference"),
                                        _m("entity:position.vertical.reference"),
                                        _m("track:samples[0].position.vertical.reference")),
        "kinematics": (_r("kinematics"), _m("entity:kinematics", "absent_if", sentinel=None)),
        "kinematics.speed_mps": (_r("kinematics.speed_mps"),
                                 _null_or_number("entity:kinematics.speed_mps")),
        "kinematics.course_deg": (_r("kinematics.course_deg"),
                                  _null_or_number("entity:kinematics.course_deg")),
        "kinematics.climb_mps": (_r("kinematics.climb_mps"),
                                 _null_or_number("entity:kinematics.climb_mps")),
        "": lossless.Mapping("entity:residual.data.report", kind="residual"),
    }


# ----------------------------------------------------------------------------------- adapter

_CONFIG = "link16_gateway configuration:"


class Link16GatewayAdapter(Adapter):
    """One SC Link16 Gateway 1.0.0 report in; an Entity and an optional one-sample Track out."""

    name = "link16_gateway"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: Adapter API v2's declaration (DECISIONS L-05). `PROVISIONAL` beside
    #: `provisional-internal-profile`: the wire form is an interface this repository defines,
    #: bound to no normative document. `OPEN`: the contract (the three schemas and the page
    #: `docs/docs/cdm/link16-gateway.mdx`) is published in this repository under Apache-2.0.
    metadata = AdapterMetadata(
        id="link16_gateway",
        name="SC Link16 Gateway report translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.PROVISIONAL_INTERNAL_PROFILE,
        direction=Direction.BIDIRECTIONAL,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L4,
            basis="L4 ROUND-TRIP VERIFIED for the SC Link16 Gateway 1.0.0 internal profile, from "
                  "evidence that runs today: `synapse_cdm.harness --adapter link16_gateway` "
                  "reports `translate`, `schema` and `provenance` PASS on every packaged fixture "
                  "(L1 to L3); its `lossless` column rests on the path-bound ledger (`MAPPINGS` "
                  "declared, the whole report a structured residual) with no LOST leaf; its "
                  "`roundtrip` column is PASS on every parsed fixture under the `values` "
                  "tolerance (`ROUNDTRIP_TOLERANCE`) the class declares, egress being mirror "
                  "reconstruction, so `synapse conformance run --adapter link16_gateway` computes "
                  "E = PASS and D on the ledger basis. The adapter's own statement of the "
                  "round-trip claim is "
                  "tests/test_cdm_link16_gateway_adapter.py::test_mirror_reproduces_every_packaged_report. "
                  "L5 is NOT declared: it rests on `M` (streaming) being inapplicable, and a rung "
                  "passed vacuously is not a rung declared (ARCHITECTURE.md §3.6, rule 4). The "
                  "rung is about the internal profile and says nothing about native JREAP C or "
                  "Link 16.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.PROVISIONAL,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest", "egress"],
            message_types=[
                "SC Link16 Gateway 1.0.0 report (profile sc-link16-gateway/1.0.0), one per "
                "call, as UTF-8 JSON octets or a dict: one Entity, and one single-sample Track "
                "when the position is present and projected",
                "egress, mode mirror (default): the same report reconstructed from this "
                "adapter's own Entity and Track",
                "egress, mode export: one gateway report from an Entity and an optional "
                "single-sample Track under a runtime-supplied ExportContext",
            ],
            limits=Limits(
                max_input_bytes=MAX_REPORT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=None,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_objects":
                        "not a bound this format needs: one report yields exactly one Entity "
                        "and at most one Track, so the count of objects is fixed by the "
                        "contract; the contract's bound on the input instead, 10 000 JSON value "
                        "nodes, is enforced and refused as LIMIT_EXCEEDED (see the "
                        "resource-limits limitation)",
                    "max_decompressed_bytes":
                        "this adapter accepts no compressed payload: it is handed one "
                        "already-received report, and any transport compression is undone by "
                        "the caller before the report reaches it",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced: runtime code reads no clock, and the "
                        "byte, depth and node bounds make every walk of the parser and of this "
                        "module linear in a bounded input; the conformance suite's parser worker "
                        "kills a decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The gateway contract (the specification's REQ061) limits one "
                            "report to 1 MiB of encoded UTF-8: 1 048 576 octets "
                            "(`MAX_REPORT_BYTES`, `adapters/link16_gateway.py`). The contract "
                            "is an internal interface this repository defines, so the figure is "
                            "a design decision of that interface and no external standard's. "
                            "This is an IMPLEMENTATION CAP and is NOT the format's normative "
                            "maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so octets or text past the bound are refused "
                            "with `InputTooLarge` before this module's parser runs; "
                            "`parse_report` reads the same bound again for a direct caller and "
                            "for a dict, by its compact UTF-8 encoding, and refuses "
                            "LIMIT_EXCEEDED"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The gateway contract limits one report to depth 32, and this "
                            "module enforces that inside (`MAX_REPORT_DEPTH`), refusing 33 to "
                            "64 as LIMIT_EXCEEDED. 64 (`MAX_DEPTH`, "
                            "`adapters/link16_gateway.py`) is the harness loader's own bound "
                            "and the parser-safety bound the base class enforces, at least "
                            "eight times the deepest JSON document this adapter ships (the "
                            "eight-times rule); it is the figure most JSON-reading adapters of "
                            "synapse_cdm declare. This is an IMPLEMENTATION CAP and is NOT the "
                            "format's normative maximum."),
                        enforced_at=(
                            "the base class: `Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` at class-definition time "
                            "(`_bind_input_bound`) before this class's `to_cdm` runs and refuses "
                            "with `InputTooDeep`, reading JSON text off its characters and a "
                            "dict off its containers"),
                        test="tests/test_cdm_link16_gateway_adapter.py::test_depth_32_is_limit_free_33_is_limit_exceeded_65_is_input_too_deep",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the contract rejects every key it does not define, at every level, as "
                "SCHEMA_INVALID (the specification's section 6: all objects reject unknown keys "
                "except source_fields and extensions); `source_fields` and `extensions` are the "
                "contract's own open objects, carried whole in residual.data.report like every "
                "other leaf, so an injected unknown key is refused, not preserved"),
        ),
        limitations=[
            Limitation(
                id="provisional-internal-profile",
                summary="the wire form is SC Link16 Gateway 1.0.0, an interface defined in this "
                        "repository: a provisional internal profile bound to no normative "
                        "document. Green gates prove agreement with that profile only",
            ),
            Limitation(
                id="no-native-bytes",
                summary="no JREAP C or Link 16 bytes, frames or J-series words are parsed or "
                        "produced, and no native interoperability, radio participation, "
                        "encryption, accreditation or certification is claimed. The native "
                        "boundary lives outside this package and refuses with "
                        "BLOCKED_EXTERNAL_EVIDENCE until a normative profile, independent byte "
                        "vectors and a peer test exist",
            ),
            Limitation(
                id="one-report-per-call",
                summary="exactly one report per call, as UTF-8 JSON octets or as a dict; a "
                        "stream, NDJSON, a list, text and the contract's lifecycle notices are "
                        "refused (JSON_INVALID or SCHEMA_INVALID)",
            ),
            Limitation(
                id="octet-only-refusals",
                summary="duplicate keys, a byte order mark, invalid UTF-8 and non-finite number "
                        "literals are refused on octets only: a dict was parsed by its caller, "
                        "who already lost them. The runtime bridge always passes octets",
            ),
            Limitation(
                id="contract-limits",
                summary="the contract's 1 MiB of UTF-8, depth 32 and 10 000 JSON value nodes are "
                        "enforced here as LIMIT_EXCEEDED; past the manifest's 1 MiB and 64 "
                        "containers the base class refuses first with InputTooLarge and "
                        "InputTooDeep",
            ),
            Limitation(
                id="position-methods-cdm-3-1",
                summary="SENSOR and UNKNOWN are CDM 3.1.0 members of PositionSource. Under "
                        "`cdm_schema=\"3.0.0\"` a report with either method yields an Entity "
                        "with position null and no Track, marked POSITION_NOT_PROJECTED_CDM3, "
                        "the report kept whole in the residual; every other report projects in "
                        "full. The conformance suite judges the default projection only",
            ),
            Limitation(
                id="hae-feet-converted",
                summary="a height stated as HAE in feet becomes metres (x 0.3048) in both "
                        "`vertical` and `alt_m`, departing from the description of "
                        "`Position.vertical` (never converted), because `alt_m` may stand only "
                        "beside an HAE vertical in metres; the feet stay in "
                        "residual.data.report. No other datum or unit is converted, and `alt_m` "
                        "is null for each of them",
            ),
            Limitation(
                id="affiliation-four",
                summary="the report's eight identity tokens project to the CDM's four: "
                        "FRIENDLY, HOSTILE and NEUTRAL as they are, and UNKNOWN, PENDING, "
                        "ASSUMED_FRIEND, SUSPECT and OTHER to UNKNOWN. The token stays in "
                        "residual.data.report and is not written into `attributes`, which the "
                        "contract forbids, although the Affiliation enumeration's own "
                        "description says finer wording is kept there",
            ),
            Limitation(
                id="motion-time-residual",
                summary="`kinematics.observed_at` has no home on the CDM's Kinematics and stays "
                        "in residual.data.report; the Track's sample time is "
                        "`position.observed_at`, and `valid_from` is `effective_at`, never "
                        "`received_at`",
            ),
            Limitation(
                id="no-symbol",
                summary="`Entity.symbol` is null: no symbol profile is defined for this "
                        "contract, and `confidence`, `valid_to` and `attributes` stay unset too",
            ),
            Limitation(
                id="egress-evidence-is-mirror",
                summary="the conformance suite builds this adapter without an ExportContext, so "
                        "its egress evidence (check E) is mirror reconstruction of the same "
                        "report; export mode is judged by this adapter's own tests, and "
                        "`docs/docs/cdm/link16-gateway.mdx` is its contract. Neither mode "
                        "transmits anything",
            ),
            Limitation(
                id="synthetic-fixtures",
                summary="every packaged fixture is synthetic and labelled so; none is a capture "
                        "and none is a native byte vector. The six reports of the engineering "
                        "handoff are carried byte-identical, and its six projections are kept "
                        "under reference/ as a semantic oracle",
            ),
            Limitation(
                id="evidence-availability",
                summary="`evidence.available` is false because no published Release carries "
                        "this adapter's records yet; it becomes true at the first release that "
                        "attaches them",
            ),
            Limitation(
                id="resource-limits",
                summary="of the five resource limits the manifest has fields for, two are "
                        "declared with their bases — `max_input_bytes` and `max_depth` — and "
                        "three are absent with their reasons in "
                        "`capabilities.limits.absent_because`; inside them the contract's own "
                        "depth 32 and node bound of 10 000 are enforced as LIMIT_EXCEEDED",
            ),
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    #: The contract states "roundtrip tolerance is values" for the internal JSON profile.
    ROUNDTRIP_TOLERANCE = "values"
    #: Nothing is exempted: every leaf survives in the residual, and the canonical projections
    #: are declared in `MAPPINGS`.
    TRANSFORMS: dict[str, str] = {}
    MAPPINGS = _build_mappings()

    def __init__(self, clock: Any = None, *, synthetic: bool = True, mode: str = "mirror",
                 export_context: ExportContext | None = None,
                 cdm_schema: str | None = None) -> None:
        """`synthetic` keeps the SDK default for the packaged fixtures; the runtime always
        passes it. `mode` is "mirror" (default) or "export", and export needs an
        `ExportContext`. `cdm_schema=None` is the full projection stamped `SCHEMA_VERSION`;
        `"3.0.0"` is the compatibility projection. No clock is ever read."""
        if type(synthetic) is not bool:
            raise TypeError(f"{_CONFIG} synthetic must be a bool")
        if type(mode) is not str or mode not in ("mirror", "export"):
            raise ValueError(f"{_CONFIG} mode must be 'mirror' or 'export'")
        if mode == "export":
            if export_context is None:
                raise ValueError(f"{_CONFIG} mode 'export' needs an ExportContext")
            if type(export_context) is not ExportContext:
                raise TypeError(f"{_CONFIG} export_context must be an ExportContext")
        elif export_context is not None:
            raise ValueError(f"{_CONFIG} an ExportContext is given only in mode 'export'")
        if cdm_schema is not None and (type(cdm_schema) is not str
                                       or cdm_schema not in (SCHEMA_VERSION, COMPAT_SCHEMA)):
            raise ValueError(f"{_CONFIG} cdm_schema must be None, SCHEMA_VERSION or '3.0.0'")
        super().__init__(clock, synthetic=synthetic)
        self._mode = mode
        self._context = export_context
        self._compat = cdm_schema == COMPAT_SCHEMA

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        return self._project(validate_report(parse_report(raw), synthetic=self._synthetic))

    def _project(self, report: dict) -> list[CDMBase]:
        key = identity_key(report)
        transforms = [T_IDENTITY]
        affiliation = report["identity"]
        if affiliation not in CANONICAL_AFFILIATIONS:
            affiliation = "UNKNOWN"
            transforms.append(T_AFFILIATION)
        position = None
        source_position = report["position"]
        if source_position is not None:
            if self._compat and source_position["method"] in CDM_3_1_METHODS:
                transforms.append(T_COMPAT)
            else:
                position = self._position(source_position, transforms)
        effective = instant(report["effective_at"], "effective_at")
        stamp = self.source_ref().model_copy(update={
            "original_id": report["record_id"], "observed_at": effective,
            "transformations": list(transforms)})
        version = COMPAT_SCHEMA if self._compat else SCHEMA_VERSION
        quality = report["quality_code"]
        source_ids = [SourceId(system=IDENTITY_SYSTEM, external_id=key)]
        motion = report["kinematics"]
        entity_id = ids.derive(IDENTITY_SYSTEM, key, kind="entity")
        entity = Entity(
            schema_version=version, source=stamp, source_ids=source_ids,
            quality=None if quality is None else Quality(source_quality=quality),
            entity_id=entity_id, entity_type=EntityType(report["entity_kind"]),
            affiliation=Affiliation(affiliation), position=position,
            kinematics=None if motion is None else Kinematics(
                speed_mps=motion["speed_mps"], course_deg=motion["course_deg"],
                climb_mps=motion["climb_mps"]),
            valid_from=effective,
            residual=ResidualBlock(namespace=FORMAT_NAME, data={"report": report}))
        if position is None:
            return [entity]
        track = Track(
            schema_version=version,
            source=stamp.model_copy(update={"transformations": list(transforms)}),
            source_ids=[s.model_copy() for s in source_ids],
            quality=None if quality is None else Quality(source_quality=quality),
            track_id=ids.derive(IDENTITY_SYSTEM, key, kind="track"), entity_id=entity_id,
            samples=[TrackSample(position=position.model_copy(deep=True),
                                 observed_at=instant(source_position["observed_at"],
                                                     "position.observed_at"))],
            residual=ResidualBlock(namespace=FORMAT_NAME,
                                   data={"record_id": report["record_id"]}))
        return [entity, track]

    @staticmethod
    def _position(source: dict, transforms: list[str]) -> Position:
        vertical, alt_m = None, None
        stated = source["vertical"]
        if stated is not None:
            value, unit, reference = stated["value"], stated["unit"], stated["reference"]
            if reference == "HAE":
                if unit == "ft":
                    value, unit = value * FEET_TO_METRES, "m"
                    transforms.append(T_FEET)
                alt_m = value
            vertical = VerticalPosition(value=value, unit=VerticalUnit(unit),
                                        reference=VerticalReference(reference))
        return Position(lat=source["lat_deg"], lon=source["lon_deg"], alt_m=alt_m,
                        position_source=PositionSource(source["method"]), vertical=vertical)

    # ---------------------------------------------------------------------- the v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The cheap structural test: the `profile` constant. Never the schema."""
        if type(raw) is dict:
            return raw.get("profile") == PROFILE
        if type(raw) in (bytes, bytearray, memoryview):
            octets = bytes(raw)
            if len(octets) > MAX_REPORT_BYTES:
                return False
            try:
                document = parse_report(octets)
            except Link16GatewayRefusal:
                return False
            return type(document) is dict and document.get("profile") == PROFILE
        return None

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Problems with `raw` as a report, then the noteworthy things the projection did.

        A refusal is reported as its class and message, which never quote the payload; any
        other exception as its class only. An accepted plain report returns `[]`.
        """
        try:
            objects = self.to_cdm(raw)
        except (Link16GatewayRefusal, InputTooLarge, InputTooDeep) as problem:
            return [f"{type(problem).__name__}: {problem}"]
        except Exception as problem:                    # noqa: BLE001 - reported, not raised
            return [f"{type(problem).__name__}: message withheld (it may quote the payload)"]
        entity = objects[0]
        said = []
        if T_AFFILIATION in entity.source.transformations:
            said.append("identity: a finer source token was projected to UNKNOWN; the token "
                        "stays in residual.data.report.identity")
        if T_FEET in entity.source.transformations:
            said.append("position.vertical: HAE feet converted to metres (x 0.3048) in vertical "
                        "and alt_m; the feet stay in residual.data.report.position.vertical")
        if entity.position is not None and entity.position.vertical is not None and \
                entity.position.vertical.reference is not VerticalReference.HAE:
            said.append("position.vertical: the reference is not HAE, so alt_m is null and no "
                        "datum conversion was made")
        if T_COMPAT in entity.source.transformations:
            said.append("position: not projected under CDM 3.0.0 (POSITION_NOT_PROJECTED_CDM3); "
                        "the report stays whole in residual.data.report")
        return said

    # ------------------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> dict:
        if self._mode == "export":
            return self._export(objects)
        return self._mirror(objects)

    def _mirror(self, objects: list[CDMBase]) -> dict:
        """Reconstruct the report from this adapter's own Entity (and its Track); never sends.

        Every refusal is CDM_SOURCE_CONFLICT: the list's shape, another adapter's object or
        residual, a residual that is not a valid report, a synthetic flag other than this
        instance's, and any difference at all from what this instance projects from the
        preserved report (declared tolerance 0). The refusal's path is the first CDM path that
        differs; no value is quoted.
        """
        if type(objects) is not list or not 1 <= len(objects) <= 2 or \
                type(objects[0]) is not Entity or \
                (len(objects) == 2 and type(objects[1]) is not Track):
            raise _refuse("CDM_SOURCE_CONFLICT", "", "one Entity, then at most one Track")
        entity = objects[0]
        if entity.source.adapter != self.name:
            raise _refuse("CDM_SOURCE_CONFLICT", "entity.source.adapter", "not this adapter's Entity")
        residual = entity.residual
        if residual is None or residual.namespace != FORMAT_NAME or \
                type(residual.data) is not dict or list(residual.data) != ["report"]:
            raise _refuse("CDM_SOURCE_CONFLICT", "entity.residual", "not this adapter's residual")
        try:
            report = validate_report(parse_report(residual.data["report"]))
        except (Link16GatewayRefusal, InputTooDeep, InputTooLarge):
            raise _refuse("CDM_SOURCE_CONFLICT", "entity.residual.data.report", "not a valid report") \
                from None
        if report["synthetic"] is not self._synthetic:
            raise _refuse("CDM_SOURCE_CONFLICT", "entity.source.synthetic", "constructor value differs")
        expected = [o.model_dump(mode="json") for o in self._project(report)]
        given = [o.model_dump(mode="json") for o in objects]
        if expected != given:
            raise _refuse("CDM_SOURCE_CONFLICT", _first_difference(expected, given),
                          "differs from the projection of the preserved report")
        return copy.deepcopy(report)

    def _export(self, objects: list[CDMBase]) -> dict:
        """One gateway report from a CDM Entity and an optional one-sample Track.

        Reads no residual and no clock. Everything a CDM object cannot say comes from the
        `ExportContext`. A canonical value the report cannot carry is a loss: `OMITTED` or
        `TRUNCATED` ones ride inside the report under `extensions["sc-link16-export/1"]`, and a
        `REFUSED` one raises `Link16GatewayRefusal` with every loss found so far, the refused
        one last. The assembled report passes the contract's own validation before it is
        returned.
        """
        context = self._context
        if type(objects) is not list or not 1 <= len(objects) <= 2 or \
                type(objects[0]) is not Entity:
            raise _refuse("CDM_SOURCE_CONFLICT", "", "exactly one Entity, first")
        entity = objects[0]
        track = None
        if len(objects) == 2:
            track = objects[1]
            if type(track) is not Track:
                raise _refuse("CDM_SOURCE_CONFLICT", "", "the second object must be a Track")
            if track.track_id == entity.entity_id:
                raise _refuse("CDM_SOURCE_CONFLICT", "track.track_id", "duplicate identifier")
            if track.entity_id != entity.entity_id:
                raise _refuse("CDM_SOURCE_CONFLICT", "track.entity_id", "not the Entity's identifier")
            if len(track.samples) != 1:
                raise _refuse("CDM_SOURCE_CONFLICT", "track.samples", "exactly one sample")
            if entity.position is None:
                raise _refuse("CDM_SOURCE_CONFLICT", "track.samples", "a Track with no Entity position")
            if track.samples[0].position.model_dump(mode="json") != \
                    entity.position.model_dump(mode="json"):
                raise _refuse("CDM_SOURCE_CONFLICT", "track.samples[0].position",
                              "differs from the Entity position")
            if context.position_observed_at is not None and track.samples[0].observed_at != \
                    instant(context.position_observed_at, "position_observed_at"):
                raise _refuse("CDM_SOURCE_CONFLICT", "track.samples[0].observed_at",
                              "differs from the export position time")
        flags = {self._synthetic, context.synthetic, entity.source.synthetic}
        if track is not None:
            flags.add(track.source.synthetic)
        if len(flags) != 1:
            raise _refuse("SYNTHETIC_MISMATCH", "entity.source.synthetic",
                          "constructor, export context and objects disagree")
        losses: list[dict] = []

        def loss(path: str, code: str, disposition: str, rule: str) -> None:
            entry = {"path": path, "code": code, "disposition": disposition, "rule": rule}
            losses.append(entry)
            if disposition == "REFUSED":
                raise Link16GatewayRefusal(code, path, rule,
                                           losses=tuple(dict(x) for x in losses))

        if entity.valid_to is not None:
            loss("entity.valid_to", "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "a closed source state has no snapshot form")
        if entity.entity_type.value not in EXPORTABLE_ENTITY_TYPES:
            loss("entity.entity_type", "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "the contract's entity_kind has no such member")
        if entity.valid_from.microsecond % 1000:
            loss("entity.valid_from", "VALUE_NOT_REPRESENTABLE", "TRUNCATED",
                 "the contract's timestamps stop at the millisecond")
        position = None
        if entity.position is not None:
            position = self._export_position(entity.position, loss)
        kinematics = None
        if entity.kinematics is not None:
            if context.kinematics_observed_at is None:
                loss("entity.kinematics", "VALUE_NOT_REPRESENTABLE", "OMITTED",
                     "no export motion time in the context")
            else:
                motion = entity.kinematics
                for field in ("speed_mps", "course_deg", "climb_mps"):
                    _export_finite(f"entity.kinematics.{field}", getattr(motion, field), loss)
                kinematics = {"observed_at": context.kinematics_observed_at,
                              "speed_mps": motion.speed_mps, "course_deg": motion.course_deg,
                              "climb_mps": motion.climb_mps}
        grade = self._export_quality_code(entity, loss)
        for prefix, obj in (("entity", entity), ("track", track)):
            if obj is None:
                continue
            self._export_always_omitted(prefix, obj, loss, grade)
        report = {
            "profile": PROFILE,
            "record_id": context.record_id,
            "gateway_id": context.gateway_id,
            "session_id": context.session_id,
            "sequence": context.sequence,
            "received_at": context.received_at,
            "effective_at": times.render(entity.valid_from),
            "time_basis": context.time_basis,
            "time_evidence": context.time_evidence,
            "tenant": context.tenant,
            "realm": context.realm,
            "synthetic": context.synthetic,
            "origin_scope": context.origin_scope,
            "reporter": context.reporter,
            "track_number": context.track_number,
            "incarnation": context.incarnation,
            "message_family": context.message_family,
            "native_profile": context.native_profile,
            "domain": context.domain,
            "entity_kind": entity.entity_type.value,
            "identity": entity.affiliation.value,
            "identity_code": None,
            "position": position,
            "kinematics": kinematics,
            "quality_code": grade,
            "security_context": context.security_context,
            "source_fields": context.source_fields_object(),
            "extensions": {"sc-link16-export/1": {
                "source_field_profile": context.source_field_profile,
                "provenance": context.provenance_object(),
                "losses": losses,
            }},
        }
        return validate_report(parse_report(report))

    def _export_position(self, canonical: Position, loss) -> dict:
        context = self._context
        if context.position_observed_at is None:
            loss("entity.position", "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "no export position time in the context")
        _export_finite("entity.position.lat", canonical.lat, loss)
        _export_finite("entity.position.lon", canonical.lon, loss)
        if canonical.accuracy_m is not None:
            loss("entity.position.accuracy_m", "VALUE_NOT_REPRESENTABLE", "OMITTED",
                 "the contract's position has no accuracy")
        height = None
        if canonical.vertical is not None:
            stated = canonical.vertical
            if stated.uncertainty is not None:
                loss("entity.position.vertical.uncertainty", "VALUE_NOT_REPRESENTABLE", "OMITTED",
                     "the contract's vertical has no uncertainty")
            height = (stated.value, stated.unit.value, stated.reference.value,
                      "entity.position.vertical", "entity.position.vertical.value")
        elif canonical.alt_m is not None:
            height = (canonical.alt_m, "m", "HAE", "entity.position.alt_m",
                      "entity.position.alt_m")
        vertical = None
        disposition = "REFUSED" if context.vertical_required else "OMITTED"
        if height is not None:
            value, unit, reference, path, value_path = height
            if (unit, reference) in context.vertical_forms:
                _export_finite(value_path, value, loss)
                vertical = {"value": value, "unit": unit, "reference": reference}
            elif reference not in {r for _u, r in context.vertical_forms}:
                loss(path, "ALTITUDE_DATUM_UNSUPPORTED", disposition,
                     "the destination form does not carry this datum")
            else:
                loss(path, "VALUE_NOT_REPRESENTABLE", disposition,
                     "the destination form does not carry this unit for this datum")
        elif context.vertical_required:
            loss("entity.position.vertical", "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "the destination form requires a height and the position has none")
        return {"observed_at": context.position_observed_at, "lat_deg": canonical.lat,
                "lon_deg": canonical.lon, "method": canonical.position_source.value,
                "vertical": vertical}

    @staticmethod
    def _export_quality_code(entity: Entity, loss) -> str | None:
        """`quality_code` is the Entity's `Quality.source_quality`, verbatim: the inverse of the
        ingest row, not a conversion. Null when the Entity states no grade; a grade the report's
        `quality_code` (1 to 128 characters of Unicode scalar values) cannot hold is refused."""
        grade = None if entity.quality is None else entity.quality.source_quality
        if grade is None:
            return None
        path = "entity.quality.source_quality"
        if type(grade) is not str or not 1 <= len(grade) <= QUALITY_CODE_MAX:
            loss(path, "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "the contract's quality_code holds 1 to 128 characters")
        try:
            grade.encode("utf-8")
        except UnicodeEncodeError:
            loss(path, "VALUE_NOT_REPRESENTABLE", "REFUSED",
                 "the contract's quality_code holds Unicode scalar values only")
        return grade

    @staticmethod
    def _export_always_omitted(prefix: str, obj: CDMBase, loss, grade: str | None) -> None:
        """Canonical fields the contract has no field for: never silent, always OMITTED. The
        Entity's `source_quality` is `quality_code`; a Track's is carried by it when the two
        are equal and is otherwise an OMITTED loss."""
        rule = "the contract has no field for it"
        quality = obj.quality
        if quality is not None:
            if prefix == "track" and quality.source_quality is not None and \
                    quality.source_quality != grade:
                loss("track.quality.source_quality", "VALUE_NOT_REPRESENTABLE", "OMITTED",
                     "the report carries the Entity's grade only")
            for field in ("confidence", "accuracy_m"):
                if getattr(quality, field) is not None:
                    loss(f"{prefix}.quality.{field}", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)
            if quality.uncertainty:
                loss(f"{prefix}.quality.uncertainty", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)
        for field in ("status", "integrity"):
            if getattr(obj, field) is not None:
                loss(f"{prefix}.{field}", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)
        if prefix == "entity":
            for field in ("confidence", "symbol"):
                if getattr(obj, field) is not None:
                    loss(f"entity.{field}", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)
            for field in ("attributes", "ontology_types"):
                if getattr(obj, field):
                    loss(f"entity.{field}", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)
        elif obj.track_quality is not None:
            loss("track.track_quality", "VALUE_NOT_REPRESENTABLE", "OMITTED", rule)


def _export_finite(path: str, value: Any, loss) -> None:
    """A canonical number the export writes must be finite: the contract's JSON has no infinity
    and no NaN, so a non-finite one is refused at its own path with a loss record, before the
    self-check would see it."""
    if type(value) is float and not math.isfinite(value):
        loss(path, "VALUE_NOT_REPRESENTABLE", "REFUSED", "the contract's numbers are finite")


#: Containers whose keys are not the models' own field names, so a path stops at them.
_OPAQUE = frozenset({"attributes", "residual", "uncertainty", "data"})


def _first_difference(expected: list, given: list) -> str:
    """The first CDM path at which two dumped object lists differ, keys only, never a value.

    The walk stops at containers whose keys come from a payload (`attributes`, the residual),
    so a key somebody else wrote is never echoed into a refusal.
    """
    if len(expected) != len(given):
        return "(objects)"
    for a, b in zip(expected, given):
        if a == b:
            continue
        path = [str(a.get("object_kind", "object"))]
        while isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
            key = next(k for k in a if a[k] != b[k])
            path.append(key)
            if key in _OPAQUE:
                break
            a, b = a[key], b[key]
            if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                index = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
                path[-1] = f"{key}[{index}]"
                a, b = a[index], b[index]
        return ".".join(path)
    return "(objects)"
