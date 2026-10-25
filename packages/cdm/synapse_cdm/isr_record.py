"""The internal ISR gateway record `urn:synapsecommand:isr:record:1`: its contract, its transport
rules, its second validation pass and its identity, which the three `stanag4559_*` translators
share (SC ISR 4559 001, revision 1.0 of 4 October 2026, sections 6, 7 and 28).

WHAT THE RECORD IS
------------------
One record is one decoded intelligence-library observation as a SynapseCommand ISR gateway
normalises it: a catalogue entry (`family` `catalog`), a stream description (`stream`) or a
workflow entity (`workflow`), with its tenant, security domain, connector, origin, revision,
change kind, two clocks, a reference to the raw capture, two security labels and a family body.
It is THIS PROJECT'S INTERNAL CONTRACT and not a NATO encoding: section 6 says so ("It is not a
representation to send to a NATO peer"), and the translators declare
`provisional-internal-profile` for exactly that reason. The JSON Schema is the bundle's
`contracts/isr-record.schema.json`, carried byte for byte as package data under
`registry/isr/` and read through `importlib.resources`, never from a checkout.

THE THREE LAYERS, IN THE ORDER A CALLER MEETS THEM
--------------------------------------------------
`parse(raw)`
    Section 6's JSON TRANSPORT rules, which exist only on octets or text: UTF-8 without a
    byte-order mark, no duplicate object key, no NaN or infinity, no trailing document, and no
    integer outside the interoperable domain (counted on its digits, before Python converts it);
    and, before the decoder runs at all, no nesting deeper than `MAX_DEPTH`.
    A caller that hands over a parsed `dict` has already lost what these rules protect: the
    decoder that built the dict kept the last of two duplicate keys and said nothing. That is the
    caller's decoder, and the translators' manifests say so.
`validate(record)`
    What a parsed record can still break, on either path: a lone surrogate (by path), a
    non-finite or out-of-domain number, a value that is not JSON, nesting deeper than
    `MAX_DEPTH`; then the published JSON Schema
    (2020-12, ECMA-262 `pattern`, through `schemas.EcmaPatternValidator`); then section 28's
    deterministic second pass — timestamps that are real instants in the one lexical form, an
    interval that runs forwards, `identity_scope=LOCAL_LIBRARY` bound to `library_id`, valid
    polygon geometry, and a graph whose edges resolve, whose node ids are unique, whose repeated
    attribute occurrences run from zero and whose nil attributes carry no value.
`object_key` / `revision_key` / `record_id` / `event_id`
    Section 7's identity, rule `ISR-ID-001` (below).

THE TRANSFORMATION RULE `ISR-ID-001` (DECISIONS L-05 of the arc that landed this module)
---------------------------------------------------------------------------------------
The specification asks for "stable rule IDs" and defines none; the bundle's nine goldens carry
exactly `["ISR-ID-001"]`. Here it is defined as the identity derivation and nothing else:

- K is the canonical JSON array `[tenant_id, security_domain, origin.authority, family,
  origin.object_id]`, and `object_key` is the unpadded base64url encoding of K's UTF-8 octets;
- `revision_key` is the same encoding of `[object_key, revision.token,
  revision.semantic_sha256]` (a null token is the JSON `null`, an empty one `""`);
- the record id is `ids.derive("NSILI", object_key, kind="isr-record")` and the event id
  `ids.derive("NSILI", revision_key, kind="event")`.

"Canonical JSON" is RFC 8785. For an array of strings and nulls, RFC 8785's string form (section
3.2.2.2) and `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` are the same characters
for every Unicode scalar value — the two-character escapes for backspace, tab, line feed, form
feed, carriage return, quote and backslash, lower-case `\\u00xx` for the other C0 controls, and
every other code point literal — which `tests/test_cdm_stanag4559_catalog_adapter.py` measures
against a serialiser written from the RFC's sentences. A lone surrogate has no UTF-8 form and no
RFC 8785 form, so it is refused by name before a key is built. The timestamps and the geometry the
Event carries are PROJECTIONS of record fields, not transformations, and the record itself is
carried verbatim; so `ISR-ID-001` is the only rule an Event names.

`revision.semantic_sha256` is COPIED. Section 6 gives the gateway the digest and the translators
none: "Translators copy supplied digests without importing hashlib. They may reject malformed
digest syntax but cannot claim to authenticate it." Its syntax is the schema's (64 lower-case hex
digits); nothing here recomputes it.

REFUSALS
--------
`IsrRecordRefused(code, text)`, a `ValueError`, before any output. The text names a path and a
rule, NEVER a value from the record: a record carries security labels and may carry restricted
metadata, and a diagnostic is published. One code per rule:

  section 6, transport    unsupported-input, byte-order-mark, not-utf8, not-json,
                          trailing-document, duplicate-key, non-finite-number,
                          integer-out-of-range, not-an-object, depth-over-cap
  values, either path     lone-surrogate, not-a-json-value, non-string-key (and
                          non-finite-number, integer-out-of-range, depth-over-cap again,
                          for a record handed over already parsed)
  the contract            kind-family-mismatch, unknown-key, missing-field, schema-violation
  section 28              bad-timestamp, impossible-instant, interval-reversed,
                          local-library-authority, geometry-over-cap, ring-not-closed,
                          ring-repeated-vertex, ring-degenerate, ring-self-intersects,
                          rings-cross, hole-outside-exterior, holes-nested, parts-overlap,
                          graph-duplicate-node, graph-dangling-edge, graph-occurrence-gap,
                          graph-nil-with-value, graph-value-unretained
  the translator          wrong-family (`adapters/stanag4559_common.py`)

Section 28 names INVALID_INPUT for internal violations and SOURCE_INVALID for decoded peer ones;
which applies depends on where the record came from, which a pure translator cannot know, so the
codes here name the RULE and the gateway maps them onto its section 19 error codes.

PURE
----
No socket, no fetch, no clock, no file but the packaged schema, no hashing: `base64`, `json` and
`ids.derive` (uuid5) are the only encodings used, and `hashlib` is never imported
(`tests/test_cdm_boundary.py`).
"""

from __future__ import annotations

import base64
import datetime as _dt
import functools
import importlib.resources
import itertools
import json
import math
import re
from typing import Any

import jsonschema

from synapse_cdm import ids, schemas
from synapse_cdm.adapter import json_nesting_depth

RECORD_SCHEMA_ID = "urn:synapsecommand:isr:record:1"
SYSTEM = "NSILI"
FORMAT_NAME = "SC ISR gateway record"
FORMAT_VERSION = "1.0.0"
ADAPTER_VERSION = "1.0.0"
#: The one transformation rule an Event names (see the module docstring).
IDENTITY_RULE = "ISR-ID-001"

FAMILY_KIND = {
    "catalog": "catalog.record",
    "stream": "stream.record",
    "workflow": "workflow.record",
}

#: 2**53 - 1: the integer bound of RFC 7493 (I-JSON) and of RFC 8785's number model. Section 6:
#: "Integers that can exceed JavaScript's exact range are represented as decimal strings".
MAX_SAFE_INTEGER = 9007199254740991
#: The longest digit run that can still be inside the bound (`len("9007199254740991")`). A longer
#: run is refused before `int()` sees it, so a ten-thousand-digit literal costs nothing.
_MAX_SAFE_DIGITS = 16

#: The deepest container nesting a record may have, one level per object or array, on either
#: path: eight times the deepest JSON document shipped beside the translators' fixtures (a
#: workflow golden nesting eleven containers, 88), rounded up to a multiple of 32. An
#: IMPLEMENTATION CAP; the contract states none. The translators declare it as their `max_depth`
#: (`adapters/stanag4559_common.py`), so behind an adapter the base class refuses a deeper
#: document first (`adapter.InputTooDeep`); `parse` and `validate` hold the same number
#: themselves, because they are this module's entries and a direct caller has no base class in
#: front of it. `parse` reads the depth off the characters BEFORE `json.loads` runs: the decoder
#: recurses, and where it gives up moved between the interpreters this package supports
#: (`adapter.InputTooDeep` has the readings), so a depth measured after it would make the verdict
#: depend on the interpreter (review of 2026-10-24).
MAX_DEPTH = 96

#: Section 28's polygon checks compare every edge of a geometry with every other edge whose box it
#: overlaps, which is quadratic in the worst case; a record of 16 MiB could hold millions of
#: positions. This IMPLEMENTATION CAP bounds that pass: a geometry stating more positions in all
#: its rings than this is refused (`geometry-over-cap`) before the schema or any ring check reads it, the fail-closed
#: direction, because a geometry this module cannot validate in bounded time is a geometry it has
#: not validated. The contract admits more (10 000 positions a ring); no fixture or example comes
#: near this. Chosen so the worst arrangement measured when it was set — a sawtooth ring of 2 047
#: positions whose edges' boxes nearly all overlap — is checked in about a second on the machine
#: it was measured on (`tests/test_cdm_stanag4559_catalog_adapter.py` holds that case to a
#: generous bound, so a slower algorithm fails a test rather than a deployment).
MAX_GEOMETRY_POSITIONS = 2048

#: Section 6: "All timestamps in the internal contract use YYYY-MM-DDTHH:MM:SS.sssZ". ASCII digits
#: and `fullmatch`, because Python's `\d` also takes the other scripts' digits and `$` also
#: matches before a final newline, neither of which ECMA-262 does — and the schema's own pattern
#: is `\d`.
_TIMESTAMP = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})\.([0-9]{3})Z"
)

#: The record's timestamp fields, top level and per family body (the schema's `date-time`
#: members, every one of them).
_TOP_TIMESTAMPS = ("source_time", "captured_at")
_BODY_TIMESTAMPS = {
    "catalog": ("created_at", "modified_at", "temporal_start", "temporal_end"),
    "stream": ("temporal_start", "temporal_end"),
    "workflow": ("source_changed_at",),
}

#: Where each family keeps its geometry (section 9: "catalogue/stream coverage or workflow GAOI
#: geometry") and its typed graph (sections 8 and 14).
GEOMETRY_KEY = {"catalog": "coverage", "stream": "coverage", "workflow": "geometry"}
GRAPH_PATH = {"catalog": ("graph",), "stream": ("graph",), "workflow": ("artifact", "graph")}


class IsrRecordRefused(ValueError):
    """A record refused. `code` names the rule (module docstring, REFUSALS); the text names the
    path, never a value from the record."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        # Picklable with its code: the conformance suite refuses payloads in a worker process
        # and ships the exception back.
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> IsrRecordRefused:
    refusal = IsrRecordRefused(code, "")
    refusal.args = (message,)
    return refusal


def _segment(text: Any) -> str:
    """One path segment as a diagnostic may print it: ASCII, at most 64 characters. Keys are part
    of a path; a key that is itself a payload is not printed in full."""
    rendered = json.dumps(str(text), ensure_ascii=True)[1:-1]
    return rendered if len(rendered) <= 64 else rendered[:61] + "..."


def _pointer(parts) -> str:
    """A JSON-Pointer-shaped location for a diagnostic, `(root)` for the document itself."""
    parts = list(parts)
    return "/" + "/".join(_segment(p) for p in parts) if parts else "(root)"


# --------------------------------------------------------------------------- the contract


@functools.lru_cache(maxsize=1)
def schema() -> dict:
    """The record contract, read from PACKAGE DATA (`registry/isr/`), never from a checkout."""
    resource = (
        importlib.resources.files("synapse_cdm") / "registry" / "isr" / "isr-record.schema.json"
    )
    document = json.loads(resource.read_text(encoding="utf-8"))
    if document.get("$id") != RECORD_SCHEMA_ID:
        raise RuntimeError(
            "registry/isr/isr-record.schema.json is not the "
            f"{RECORD_SCHEMA_ID} contract this module was written against"
        )
    return document


@functools.lru_cache(maxsize=1)
def _validator():
    # `format` is NOT asserted here, and that is a choice about determinism. The contract's only
    # format is `date-time`, which `jsonschema` asserts only when the optional `rfc3339-validator`
    # is installed, so the same record would be refused with one code on one machine and another
    # code elsewhere. The second pass below checks every timestamp field itself, more strictly
    # than RFC 3339 does (one lexical form, ASCII digits, a real instant).
    return schemas.EcmaPatternValidator(schema(), format_checker=jsonschema.FormatChecker(()))


# ------------------------------------------------------------------- section 6: transport


def _no_constant(name: str) -> Any:
    raise IsrRecordRefused(
        "non-finite-number",
        "a NaN or Infinity literal; section 6 rejects NaN and the infinities, which are not "
        "JSON (RFC 8259)",
    )


def _finite_float(text: str) -> float:
    value = float(text)
    if not math.isfinite(value):
        raise IsrRecordRefused(
            "non-finite-number",
            "a number literal that overflows to an infinity; section 6 rejects it",
        )
    return value


def _bounded_int(text: str) -> int:
    digits = text[1:] if text.startswith("-") else text
    if len(digits) > _MAX_SAFE_DIGITS or abs(int(text)) > MAX_SAFE_INTEGER:
        raise IsrRecordRefused(
            "integer-out-of-range",
            "an integer literal outside -(2**53-1)..2**53-1; section 6 carries wide integers as "
            "decimal strings",
        )
    return int(text)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict:
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise IsrRecordRefused(
                "duplicate-key",
                f"an object states the key {_pointer([key])[1:]!s} twice; section 6 rejects "
                "duplicate keys before normalisation",
            )
        out[key] = value
    return out


def parse(raw: bytes | bytearray | memoryview | str) -> dict:
    """Octets or text -> the record object, under section 6's transport rules.

    Only the transport rules run here; `validate` is the contract. The octet path is the only
    place a duplicate key, a byte-order mark, invalid UTF-8, a NaN literal or a trailing document
    can be seen at all.
    """
    if isinstance(raw, (bytes, bytearray, memoryview)):
        octets = bytes(raw)
        if octets.startswith(b"\xef\xbb\xbf"):
            raise IsrRecordRefused(
                "byte-order-mark",
                "the document starts with a UTF-8 byte-order mark; section 6 requires UTF-8 "
                "without one",
            )
        try:
            text = octets.decode("utf-8", errors="strict")
        except UnicodeDecodeError as problem:
            raise IsrRecordRefused(
                "not-utf8",
                f"the octets are not UTF-8 (the first invalid sequence at offset {problem.start})",
            ) from None
    elif isinstance(raw, str):
        text = raw
        if text.startswith("\ufeff"):
            raise IsrRecordRefused(
                "byte-order-mark", "the text starts with a byte-order mark (U+FEFF)"
            )
    else:
        raise IsrRecordRefused(
            "unsupported-input",
            f"an ISR record is handed over as UTF-8 octets, text or a parsed object, not "
            f"{type(raw).__name__}",
        )
    depth = json_nesting_depth(text)
    if depth > MAX_DEPTH:
        raise IsrRecordRefused(
            "depth-over-cap",
            f"the document nests {depth} containers deep, more than the {MAX_DEPTH} this module "
            "decodes (isr_record.MAX_DEPTH, an implementation cap); refused before the decoder "
            "recurses into it",
        )
    try:
        document = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_constant=_no_constant,
            parse_float=_finite_float,
            parse_int=_bounded_int,
        )
    except IsrRecordRefused:
        raise
    except json.JSONDecodeError as problem:
        # The decoder skips JSON's four whitespace characters around the value and nothing else,
        # and reports anything after it as "Extra data": section 6's trailing document. Its
        # message and position quote nothing of the payload.
        if problem.msg == "Extra data":
            raise IsrRecordRefused(
                "trailing-document",
                f"text follows the JSON value at character {problem.pos}; section 6 rejects "
                "trailing documents",
            ) from None
        raise IsrRecordRefused(
            "not-json", f"the document is not one JSON value (at character {problem.pos})"
        ) from None
    if not isinstance(document, dict):
        raise IsrRecordRefused("not-an-object", "the document is not a JSON object")
    return document


# --------------------------------------------------------- values, on either path


def _scan_values(record: dict) -> None:
    """What a parsed record can still break after (or instead of) `parse`: a lone surrogate in a
    string or a key, a non-finite float, an integer outside the interoperable domain, a key that
    is not a string, and a value that is not JSON at all (a tuple, bytes, a datetime). Types are
    compared EXACTLY: a subclass of `dict` or `str` can redefine what it holds, and a record is
    plain JSON or it is refused. Iterative, so depth costs no stack; and a container deeper than
    `MAX_DEPTH` is refused as `parse` refuses it, so a record too deep for one path is too deep
    for the other, and the walk never copies a path longer than the cap."""
    stack: list[tuple[Any, tuple]] = [(record, ())]
    while stack:
        value, where = stack.pop()
        kind = type(value)
        if (kind is dict or kind is list) and len(where) >= MAX_DEPTH:
            raise IsrRecordRefused(
                "depth-over-cap",
                f"{_pointer(where[:8])}...: the object nests more than {MAX_DEPTH} containers "
                "deep (isr_record.MAX_DEPTH, an implementation cap)",
            )
        if kind is dict:
            for key, sub in value.items():
                if type(key) is not str:
                    raise IsrRecordRefused(
                        "non-string-key", f"{_pointer(where)}: a key that is not a string"
                    )
                _no_surrogate(key, where, "a key")
                stack.append((sub, (*where, key)))
        elif kind is list:
            stack.extend((sub, (*where, index)) for index, sub in enumerate(value))
        elif kind is str:
            _no_surrogate(value, where, "the string")
        elif value is None or kind is bool:
            continue
        elif kind is float:
            if not math.isfinite(value):
                raise IsrRecordRefused(
                    "non-finite-number", f"{_pointer(where)}: NaN or an infinity, which is not JSON"
                )
        elif kind is int:
            if abs(value) > MAX_SAFE_INTEGER:
                raise IsrRecordRefused(
                    "integer-out-of-range",
                    f"{_pointer(where)}: an integer outside -(2**53-1)..2**53-1; section 6 carries "
                    "wide integers as decimal strings",
                )
        else:
            raise IsrRecordRefused(
                "not-a-json-value", f"{_pointer(where)}: a {kind.__name__} is not a JSON value"
            )


def _no_surrogate(text: str, where: tuple, what: str) -> None:
    for ch in text:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            raise IsrRecordRefused(
                "lone-surrogate",
                f"{_pointer(where)}: {what} holds a lone surrogate, which is not Unicode text and "
                "has no UTF-8 or RFC 8785 form",
            )


# -------------------------------------------------------------------- the published schema


def _schema_refusal(error: jsonschema.ValidationError) -> IsrRecordRefused:
    """The refusal for the most relevant schema error, naming the path and the keyword and never
    the value (`jsonschema`'s own messages quote the instance, so they are not used)."""
    path = list(error.absolute_path)
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        known = error.schema.get("properties", {})
        extra = sorted(key for key in error.instance if key not in known)
        return IsrRecordRefused(
            "unknown-key",
            f"{_pointer(path + extra[:1])}: a key the record contract does not define (section 6: "
            "unknown keys are rejected; extension material belongs in the body's graph)",
        )
    if error.validator == "required" and isinstance(error.instance, dict):
        missing = [key for key in error.schema.get("required", []) if key not in error.instance]
        return IsrRecordRefused(
            "missing-field",
            f"{_pointer(path + missing[:1])}: a member the record contract requires is absent",
        )
    return IsrRecordRefused(
        "schema-violation",
        f"{_pointer(path)}: the value breaks the record contract's `{error.validator}` keyword "
        f"({RECORD_SCHEMA_ID})",
    )


def _order(error: jsonschema.ValidationError) -> tuple:
    return (len(error.absolute_path), [str(p) for p in error.absolute_path], str(error.validator))


def _most_relevant(errors) -> jsonschema.ValidationError:
    """The error a diagnostic names: the shallowest, and inside an `anyOf` / `oneOf` the branch
    that failed least (a Polygon with one bad latitude fails the Polygon branch once and the
    MultiPolygon branch everywhere), down to the deepest error that branch reports. Deterministic
    for one record, and never dependent on dict or set order. `errors` is consumed as a stream and
    only the best so far is kept, so a record breaking the contract a million times costs one
    error's memory at the top level."""
    error = None
    for candidate in errors:
        if error is None or _order(candidate) < _order(error):
            error = candidate
    while error.context:
        branches: dict = {}
        for sub in error.context:
            branches.setdefault(sub.relative_schema_path[0], []).append(sub)
        _, chosen = min(branches.items(), key=lambda item: (len(item[1]), item[0]))
        error = min(chosen, key=_order)
    return error


def _check_schema(record: dict) -> None:
    errors = _validator().iter_errors(record)
    first = next(errors, None)
    if first is not None:
        raise _schema_refusal(_most_relevant(itertools.chain((first,), errors)))


def _positions(coordinates: Any) -> int:
    """How many positions a `coordinates` member holds, read before the schema: a list none of
    whose members is a list is one position. Iterative; a malformed shape is counted as it stands
    and the schema then refuses it."""
    count, stack = 0, [coordinates]
    while stack:
        node = stack.pop()
        if type(node) is not list:
            continue
        if node and all(type(child) is list for child in node):
            stack.extend(node)
        else:
            count += 1
    return count


def _known_family(record: dict) -> str | None:
    """The record's `family` when it is one of the three, else None, for the steps that run
    BEFORE the schema has judged the record. There `family` can be any JSON value, and a list or
    an object is not hashable: a dict lookup on it raised `TypeError` out of the translators
    (review of 2026-10-24) where the schema refuses it by path. The type is read first, so a value
    that is not one of the three strings is simply not a family yet and the schema says why."""
    family = record.get("family")
    return family if type(family) is str and family in FAMILY_KIND else None


def _cap_geometry(record: dict) -> None:
    """`MAX_GEOMETRY_POSITIONS`, BEFORE the schema. The contract states a geometry as `anyOf`
    Polygon, MultiPolygon or null, and a validator judging `anyOf` collects every error of every
    branch before it can say which failed: a geometry of a million bad positions would build
    millions of error objects inside the 16 MiB bound. Held here, no branch ever sees more than the
    cap, and the polygon pass after the schema meets the same number."""
    family, body = _known_family(record), record.get("body")
    if family is None or type(body) is not dict:
        return
    geometry = body.get(GEOMETRY_KEY[family])
    if type(geometry) is not dict:
        return
    positions = _positions(geometry.get("coordinates"))
    if positions > MAX_GEOMETRY_POSITIONS:
        raise IsrRecordRefused(
            "geometry-over-cap",
            f"/body/{GEOMETRY_KEY[family]}: the geometry states {positions} positions, more than "
            f"the {MAX_GEOMETRY_POSITIONS} this translator validates in bounded time "
            "(isr_record.MAX_GEOMETRY_POSITIONS, an implementation cap)",
        )


# ------------------------------------------------------------- section 28: the second pass


def _instant(value: str, where: tuple):
    match = _TIMESTAMP.fullmatch(value)
    if match is None:
        raise IsrRecordRefused(
            "bad-timestamp",
            f"{_pointer(where)}: not YYYY-MM-DDTHH:MM:SS.sssZ in ASCII digits (section 6)",
        )
    year, month, day, hour, minute, second, millis = (int(part) for part in match.groups())
    try:
        # The datetime CONSTRUCTOR, not `fromisoformat`: the parser's leniency moved between the
        # interpreters this package supports (3.14 reads `T24:00` as the next midnight, 3.11 and
        # 3.12 refuse it), and the same record must get the same verdict on each. The
        # constructor refuses hour 24, minute or second 60, 30 February and year 0 on all three.
        return _dt.datetime(
            year, month, day, hour, minute, second, millis * 1000, tzinfo=_dt.timezone.utc
        )
    except ValueError:
        # An impossible date, or a literal second 60, which datetime cannot hold and section 6
        # forbids changing silently to 59 ("Leap-second handling requires the binding's documented
        # conversion rule"; no binding is held here).
        raise IsrRecordRefused(
            "impossible-instant",
            f"{_pointer(where)}: the date or time does not exist (section 6: reject impossible "
            "dates; a literal second 60 is not changed to 59)",
        ) from None


def _check_times(record: dict) -> None:
    body = record["body"]
    for key in _TOP_TIMESTAMPS:
        if record[key] is not None:
            _instant(record[key], (key,))
    stamps = {}
    for key in _BODY_TIMESTAMPS[record["family"]]:
        if body[key] is not None:
            stamps[key] = _instant(body[key], ("body", key))
    start, end = stamps.get("temporal_start"), stamps.get("temporal_end")
    if start is not None and end is not None and start > end:
        raise IsrRecordRefused(
            "interval-reversed",
            "/body/temporal_start: the source interval starts after it ends (section 28: every "
            "source interval with two bounds has start <= end)",
        )


def _check_scope(record: dict) -> None:
    if (
        record["body"]["identity_scope"] == "LOCAL_LIBRARY"
        and record["origin"]["authority"] != record["library_id"]
    ):
        raise IsrRecordRefused(
            "local-library-authority",
            "/origin/authority: identity_scope LOCAL_LIBRARY requires origin.authority to equal "
            "library_id (sections 7 and 28)",
        )


# -- geometry ----------------------------------------------------------------------------------
#
# WHAT "VALID POLYGON TOPOLOGY" MEANS HERE. Section 28 asks for rings that are "closed, have
# distinct nondegenerate vertices and valid polygon topology" and defines none of the three. This
# module reads them as the OGC Simple Features rules that can be decided edge by edge and vertex by
# vertex, in exact arithmetic:
#   - every ring is closed, its vertices are distinct, and it encloses a non-zero area;
#   - every ring is simple: no two non-adjacent edges of one ring touch or cross, and no two
#     adjacent edges fold back over each other;
#   - no edge of one ring crosses an edge of another ring of the same geometry at a point inside
#     both, or runs along it (rings may touch at points);
#   - no vertex of an interior ring lies outside its polygon's exterior ring, and none lies inside
#     another interior ring of that polygon;
#   - no vertex of one MultiPolygon part's exterior ring lies inside another part (inside that
#     part's exterior and not in one of its holes).
# What is NOT decided: that a polygon's interior is connected (an interior ring touching the
# exterior at two points), and a ring meeting another only at vertices while crossing it there
# without leaving a vertex inside it. The adapters' manifests state that limitation.
#
# EXACT ARITHMETIC. Coordinates are JSON numbers, so integers or binary floats, and every binary
# float is a fraction with a power-of-two denominator. All of one geometry's coordinates are put
# over their largest denominator, which makes them integers with no rounding, and every
# orientation and containment test below is integer arithmetic: a near-collinear edge is judged
# exactly, not by the rounding of a float cross product.


def _orient(a, b, c) -> int:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (value > 0) - (value < 0)


def _within(a, b, c) -> bool:
    """`c`, known collinear with `a`-`b`, lies on the closed segment between them."""
    return min(a[0], b[0]) <= c[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= c[1] <= max(a[1], b[1])


def _contact(a, b, c, d) -> str | None:
    """How the closed segments a-b and c-d meet: None (they do not), "cross" (at one point inside
    both), "overlap" (collinear, sharing more than a point) or "touch" (any other contact)."""
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if o1 == o2 == o3 == o4 == 0:
        # Collinear: project on the axis the segment spans and compare the two intervals.
        axis = 0 if a[0] != b[0] else 1
        lo1, hi1 = sorted((a[axis], b[axis]))
        lo2, hi2 = sorted((c[axis], d[axis]))
        low, high = max(lo1, lo2), min(hi1, hi2)
        if low > high:
            return None
        return "overlap" if low < high else "touch"
    if o1 * o2 < 0 and o3 * o4 < 0:
        return "cross"
    if (
        (o1 == 0 and _within(a, b, c))
        or (o2 == 0 and _within(a, b, d))
        or (o3 == 0 and _within(c, d, a))
        or (o4 == 0 and _within(c, d, b))
    ):
        return "touch"
    return None


def _box(ring) -> tuple:
    xs = [point[0] for point in ring]
    ys = [point[1] for point in ring]
    return min(xs), max(xs), min(ys), max(ys)


def _locate(point, ring, box) -> int:
    """1 strictly inside the closed ring, 0 on its boundary, -1 strictly outside (crossing number
    with exact on-edge detection). `box` is the ring's bounding box: a point outside it is outside
    the ring, which keeps the vertex tests near-linear for parts and holes that lie apart."""
    x, y = point
    if x < box[0] or x > box[1] or y < box[2] or y > box[3]:
        return -1
    inside = False
    for i in range(len(ring) - 1):
        a, b = ring[i], ring[i + 1]
        if _orient(a, b, point) == 0 and _within(a, b, point):
            return 0
        if (a[1] > y) != (b[1] > y):
            # The sign of the crossing's x relative to the point, without a division.
            side = (b[0] - a[0]) * (y - a[1]) - (x - a[0]) * (b[1] - a[1])
            if (side > 0) == (b[1] > a[1]):
                inside = not inside
    return 1 if inside else -1


def _exact_polygons(polygons: list) -> list:
    denominator = 1
    for polygon in polygons:
        for ring in polygon:
            for position in ring:
                for coordinate in position:
                    denominator = max(denominator, coordinate.as_integer_ratio()[1])
    exact = []
    for polygon in polygons:
        rings = []
        for ring in polygon:
            points = []
            for position in ring:
                pair = []
                for coordinate in position:
                    numerator, below = coordinate.as_integer_ratio()
                    pair.append(numerator * (denominator // below))
                points.append(tuple(pair))
            rings.append(points)
        exact.append(rings)
    return exact


def _check_ring(ring: list, where: str) -> None:
    if ring[0] != ring[-1]:
        raise IsrRecordRefused(
            "ring-not-closed", f"{where}: the ring's last position is not its first (section 28)"
        )
    vertices = ring[:-1]
    if len(set(vertices)) != len(vertices):
        raise IsrRecordRefused(
            "ring-repeated-vertex",
            f"{where}: the ring repeats a vertex (section 28: distinct vertices)",
        )
    twice_area = sum(
        a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1])
    )
    if len(vertices) < 3 or twice_area == 0:
        raise IsrRecordRefused(
            "ring-degenerate", f"{where}: the ring encloses no area (section 28: nondegenerate)"
        )


def _check_edges(rings: list[tuple[str, list]]) -> None:
    """Every pair of edges whose boxes overlap, found by a sweep over the boxes' west edges."""
    edges = []
    for ring_index, (where, ring) in enumerate(rings):
        count = len(ring) - 1
        for i in range(count):
            a, b = ring[i], ring[i + 1]
            edges.append(
                (
                    min(a[0], b[0]),
                    max(a[0], b[0]),
                    min(a[1], b[1]),
                    max(a[1], b[1]),
                    ring_index,
                    i,
                    count,
                    a,
                    b,
                )
            )
    edges.sort(key=lambda edge: edge[0])
    active: list = []
    for edge in edges:
        west, east, south, north, ring_index, i, count, a, b = edge
        active = [other for other in active if other[1] >= west]
        for other in active:
            if other[2] > north or other[3] < south:
                continue
            other_ring, j, c, d = other[4], other[5], other[7], other[8]
            if other_ring != ring_index:
                if _contact(a, b, c, d) in ("cross", "overlap"):
                    raise IsrRecordRefused(
                        "rings-cross",
                        f"{rings[ring_index][0]}: an edge crosses or runs along an edge of "
                        f"{rings[other_ring][0]} (section 28: valid polygon topology)",
                    )
                continue
            adjacent = abs(i - j) == 1 or abs(i - j) == count - 1
            if adjacent:
                # They share one vertex; the other two ends must not fold back along them.
                shared = b if b in (c, d) else a
                far1 = a if shared == b else b
                far2 = d if shared == c else c
                if _orient(shared, far1, far2) == 0 and (
                    (far1[0] - shared[0]) * (far2[0] - shared[0])
                    + (far1[1] - shared[1]) * (far2[1] - shared[1])
                    > 0
                ):
                    raise IsrRecordRefused(
                        "ring-self-intersects",
                        f"{rings[ring_index][0]}: two adjacent edges fold back over each other "
                        "(section 28: valid polygon topology)",
                    )
            elif _contact(a, b, c, d) is not None:
                raise IsrRecordRefused(
                    "ring-self-intersects",
                    f"{rings[ring_index][0]}: two edges of the ring touch or cross (section 28: "
                    "valid polygon topology)",
                )
        active.append(edge)


def _check_geometry(geometry: dict | None, where: str) -> None:
    # `_cap_geometry` has already held the positions to `MAX_GEOMETRY_POSITIONS`, before the schema.
    if geometry is None:
        return
    multi = geometry["type"] == "MultiPolygon"
    polygons = geometry["coordinates"] if multi else [geometry["coordinates"]]
    exact = _exact_polygons(polygons)

    def label(p: int, r: int) -> str:
        return f"{where}/coordinates/{p}/{r}" if multi else f"{where}/coordinates/{r}"

    rings = []
    for p, polygon in enumerate(exact):
        for r, ring in enumerate(polygon):
            _check_ring(ring, label(p, r))
            rings.append((label(p, r), ring))
    _check_edges(rings)
    boxes = [[_box(ring) for ring in polygon] for polygon in exact]
    for p, polygon in enumerate(exact):
        exterior, holes = polygon[0], polygon[1:]
        for h, hole in enumerate(holes, start=1):
            if any(_locate(v, exterior, boxes[p][0]) < 0 for v in hole[:-1]):
                raise IsrRecordRefused(
                    "hole-outside-exterior",
                    f"{label(p, h)}: an interior ring reaches outside its exterior ring (section "
                    "28: valid polygon topology)",
                )
            for k, other in enumerate(holes, start=1):
                if k != h and any(_locate(v, other, boxes[p][k]) > 0 for v in hole[:-1]):
                    raise IsrRecordRefused(
                        "holes-nested",
                        f"{label(p, h)}: an interior ring lies inside the interior ring "
                        f"{label(p, k)} (section 28: valid polygon topology)",
                    )
    for p, polygon in enumerate(exact):
        for q, other in enumerate(exact):
            if p == q:
                continue
            for v in polygon[0][:-1]:
                if _locate(v, other[0], boxes[q][0]) > 0 and all(
                    _locate(v, hole, boxes[q][k]) < 0 for k, hole in enumerate(other[1:], start=1)
                ):
                    raise IsrRecordRefused(
                        "parts-overlap",
                        f"{label(p, 0)}: a vertex lies inside the part {where}/coordinates/{q} "
                        "(section 28: valid polygon topology)",
                    )


# -- the typed graph ---------------------------------------------------------------------------


def _check_graph(graph: dict, where: str) -> None:
    seen: set[str] = set()
    for n, node in enumerate(graph["nodes"]):
        if node["id"] in seen:
            raise IsrRecordRefused(
                "graph-duplicate-node",
                f"{where}/nodes/{n}/id: a node id the graph already holds (section 28: node ids "
                "are unique)",
            )
        seen.add(node["id"])
        occurrences: dict[str, list[int]] = {}
        for a, attribute in enumerate(node["attributes"]):
            occurrences.setdefault(attribute["name"], []).append(attribute["occurrence"])
            if attribute["nil"] is True and attribute["value"] is not None:
                raise IsrRecordRefused(
                    "graph-nil-with-value",
                    f"{where}/nodes/{n}/attributes/{a}: nil is true and value is not null "
                    "(section 28: nil=true requires value=null)",
                )
            if (
                attribute["nil"] is False
                and attribute["value"] is None
                and attribute["lexical"] is None
            ):
                raise IsrRecordRefused(
                    "graph-value-unretained",
                    f"{where}/nodes/{n}/attributes/{a}: neither a normalised value nor the lexical "
                    "form is retained for a value that is not nil (section 28: when conversion is "
                    "unknown the value is null and lexical retains the source value)",
                )
        for found in occurrences.values():
            if found != list(range(len(found))):
                raise IsrRecordRefused(
                    "graph-occurrence-gap",
                    f"{where}/nodes/{n}/attributes: the occurrence indices of a repeated attribute "
                    "do not run 0, 1, 2 ... in order (section 28: contiguous from zero)",
                )
    for e, edge in enumerate(graph["edges"]):
        if edge["source"] not in seen or edge["target"] not in seen:
            raise IsrRecordRefused(
                "graph-dangling-edge",
                f"{where}/edges/{e}: the edge names a node the graph does not hold (section 28: "
                "every graph edge resolves to a node)",
            )


def validate(record: Any) -> dict:
    """The value scan, the contract, then section 28's second pass. Returns the record unchanged;
    raises `IsrRecordRefused` naming the rule and the path."""
    if type(record) is not dict:
        raise IsrRecordRefused("not-an-object", "an ISR record is one JSON object")
    _scan_values(record)
    # Before the schema, so `family` and `kind` are read only when they are strings
    # (`_known_family`); any other value reaches the schema, which refuses it by path.
    family, kind = _known_family(record), record.get("kind")
    if (
        family is not None
        and type(kind) is str
        and kind in FAMILY_KIND.values()
        and FAMILY_KIND[family] != kind
    ):
        raise IsrRecordRefused(
            "kind-family-mismatch",
            "/kind: the record kind does not correspond to its family (section 6)",
        )
    _cap_geometry(record)
    _check_schema(record)
    _check_times(record)
    _check_scope(record)
    family = record["family"]
    body = record["body"]
    _check_geometry(body[GEOMETRY_KEY[family]], f"/body/{GEOMETRY_KEY[family]}")
    graph = body
    for key in GRAPH_PATH[family]:
        graph = graph[key]
    _check_graph(graph, "/body/" + "/".join(GRAPH_PATH[family]))
    return record


# ------------------------------------------------------------- section 7: identity, ISR-ID-001


def canonical_array(items: list[str | None]) -> str:
    """RFC 8785 text of a JSON array whose members are strings or null (see the module docstring
    for why `json.dumps` with these arguments is that text, and for the lone-surrogate refusal)."""
    for index, item in enumerate(items):
        if item is not None and type(item) is not str:
            raise IsrRecordRefused(
                "not-a-json-value", f"identity component {index} is neither a string nor null"
            )
        if item is not None:
            _no_surrogate(item, ("identity component", index), "the component")
    return json.dumps(items, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def object_key(record: dict) -> str:
    """`ISR-ID-001`: unpadded base64url of K = [tenant_id, security_domain, origin.authority,
    family, origin.object_id]."""
    return _b64url(
        canonical_array(
            [
                record["tenant_id"],
                record["security_domain"],
                record["origin"]["authority"],
                record["family"],
                record["origin"]["object_id"],
            ]
        )
    )


def revision_key(record: dict) -> str:
    """`ISR-ID-001`: unpadded base64url of [object_key, revision.token, revision.semantic_sha256]."""
    return _b64url(
        canonical_array(
            [object_key(record), record["revision"]["token"], record["revision"]["semantic_sha256"]]
        )
    )


def record_id(record: dict):
    return ids.derive(SYSTEM, object_key(record), kind="isr-record")


def event_id(record: dict):
    return ids.derive(SYSTEM, revision_key(record), kind="event")
