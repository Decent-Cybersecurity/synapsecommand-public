"""The TacticalAPI blue-force codec: the pinned contract's field table as data, a protobuf wire
reader, and the one twin form both input forms are brought to (the record §2, §3; the record is
the repository's `docs/tacticalapi-implementation.md`, this module's specification). Decode only.
No CDM object is built here — the adapter module does that — and nothing here opens a file, a
socket or a channel, or parses JSON text (`json` is imported to write it, once per measured value,
for the carried-copy measure `carried_size`).

THE TABLE IS PROTOC'S, NOT THIS MODULE'S
----------------------------------------
`MESSAGES` and `ENUMS` are the closure of the two supported responses (the record §3.1) — message
name -> field number -> `Field(name, kind, type, repeated, oneof)`, enum name -> number -> value
name — and nothing else: no comment text of the contract, no other message. They are printed by
`gates/tacticalapi_field_table.py` from protoc's own descriptor of the ten pinned files, located
and hash-checked through `synapse_cdm.normative_binding.resolve`, and pasted here whole between the
marker lines.
`tests/test_cdm_tacticalapi_codec.py::test_embedded_table_matches_the_pinned_descriptor`
regenerates the block and holds it equal byte for byte, so a hand edit, a stale paste or a new
upstream commit cannot pass as the pin. The decoder below is table-driven: it has no knowledge of
a field that the table does not give it.

TWO INPUT FORMS, ONE TWIN
-------------------------
The bytes form is a serialized `google.protobuf.Any` wrapping one response (§2.1). The dict form
is the twin itself (§2.2) — what the harness loads from a `.parsed.json` and what a caller that
already decoded the message passes. `decode()` turns the first into a twin; `validate_twin()`
holds the second to the same table and returns it normalised; `twin_of()` picks one by type.
Both forms of one message give the same twin, so the adapter translates exactly one shape.

The twin, as §2.2 states it: `@type` holds the `type_url`, the response's fields sit beside it
under the contract's own names, a key is present if and only if its field was on the wire (a
proto3 default that was on the wire is present), `int64` is decimal text, `int32` a number,
`Timestamp` RFC 3339 text in Z with the fewest of 0, 3, 6 or 9 fractional digits that hold the
nanoseconds, a wrapper is its bare value, an enum is its value name (a number the contract does
not name stays a number), and unknown wire fields sit under `@unknown` on the message that held
them as `{"number", "wire_type", "hex"}` in wire order. Key order is `@type`, the known fields by
field number, a dict-form input's unknown keys in input order, then `@unknown`.

WHAT IS REFUSED, BY NAME
------------------------
Every refusal is a `TacticalapiRefused`, a `ValueError` whose `code` is one of `DECODER_CODES`
and whose message begins with that code. Nothing is repaired: a lenient protobuf parser keeps the
last of two singular occurrences, the last of two `oneof` members, reads a mismatched wire type
as an unknown field, truncates an over-wide `int32`, reads any non-zero `bool` as true and reads
a tag padded past five octets; this decoder refuses each of them, and the adapter declares that
(`non-canonical-encoding-refused`).

A refusal is one printable line of bounded length whatever the input held. Every value it takes
from the input goes through `quote` (the value's repr, cut to `QUOTE_LIMIT` characters with the
number left out stated), every dict key through `_key` (a name of the table as itself,
anything else quoted), and every type name through `quote_type`, so a key holding a line break
or a lone surrogate, a type_url of four mebibytes, or a class whose name is either, reaches the
text escaped and cut. Every type test of a value of the input reads the value's own type
(`_of_type`), never a `__class__` that may name another, so a value is converted only when it
is what it says.

WHAT IS CARRIED
---------------
A field number the table does not name, in any message the twin renders as an object, is kept
with its number, wire type and raw value octets, and decoding continues. An enum number the
contract does not name is kept as the number. A dict-form key the contract does not name is kept
under its own key, its value unchanged. `unknown_fields()` lists both kinds with the path of the
message that held each.

THE TYPED BLOCK IS A CONTRACT, AND IT LIVES HERE
------------------------------------------------
`TypedBlock` is `tacticalapi-blueforce/1`, the never-drop carrier the adapter writes at
`Entity.attributes["tacticalapi"]` (the record §5.1): the message the element came from and the
element exactly as the twin states it, known fields only. It is a pydantic model with extra keys
forbidden, so a consumer validates a block with `TypedBlock.model_validate` and a key the
contract does not name is a mistake rather than data. It sits beside the field table because it
restates the table's names, and `tests/test_cdm_tacticalapi_adapter.py` holds each block model's
fields equal to the table's fields of the message it carries.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import math
import re
import struct
from typing import Annotated, Any, Iterator, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field as ModelField, model_validator

# ------------------------------------------------------------------------------- the contract

PACKAGE = "rheinmetall.tactical_api.v0"

#: The record §1: the two read-side responses of the `BlueForceTracking` service. Every other
#: message of the contract, and every type outside it, is refused `unsupported-message-type`.
GET_BLUE_FORCES_RESPONSE = f"{PACKAGE}.GetBlueForcesResponse"
SUBSCRIBE_BLUE_FORCE_EVENTS_RESPONSE = f"{PACKAGE}.SubscribeBlueForceEventsResponse"
SUPPORTED_TYPES = (GET_BLUE_FORCES_RESPONSE, SUBSCRIBE_BLUE_FORCE_EVENTS_RESPONSE)

#: The four well-known types of the closure. None of them is rendered as an object of its own in
#: the twin (the `Any` merges into the top level, the other three are bare values), so none has a
#: place for `@unknown`; an unknown field inside one is refused (the record's "Changes",
#: 2026-10-04).
ANY = "google.protobuf.Any"
TIMESTAMP = "google.protobuf.Timestamp"
STRING_VALUE = "google.protobuf.StringValue"
DOUBLE_VALUE = "google.protobuf.DoubleValue"
WELL_KNOWN_TYPES = (ANY, TIMESTAMP, STRING_VALUE, DOUBLE_VALUE)

#: `Timestamp`'s own stated range: 0001-01-01T00:00:00Z to 9999-12-31T23:59:59Z, as seconds from
#: the Unix epoch (719 162 days before it; 2 932 897 days after it, less one second).
TIMESTAMP_MIN_SECONDS = -62_135_596_800
TIMESTAMP_MAX_SECONDS = 253_402_300_799
TIMESTAMP_MAX_NANOS = 999_999_999
_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)

#: The protobuf encoding's wire types. 3 and 4 are the deprecated group delimiters; 6 and 7 are
#: unassigned. Field numbers are 29 bits wide (a tag is a 32-bit value: number << 3 | wire type).
WIRE_VARINT, WIRE_FIXED64, WIRE_LEN, WIRE_FIXED32 = 0, 1, 2, 5
MAX_FIELD_NUMBER = (1 << 29) - 1
#: A tag is a 32-bit value, so its varint is at most five octets (35 bits). A longer one is padded
#: with continuation octets; protoc refuses it, and a lenient parser reads it, which is a repair.
MAX_TAG_OCTETS = 5
_UINT64_MAX = (1 << 64) - 1
_INT32_MIN, _INT32_MAX = -(1 << 31), (1 << 31) - 1
_INT64_MIN, _INT64_MAX = -(1 << 63), (1 << 63) - 1

# ------------------------------------------------------------------------------------ limits
#
# The three bounds the adapter declares in `capabilities.limits`, plus one the manifest has no
# field for. Each is an IMPLEMENTATION CAP: the contract states no maximum for any of them.

#: `max_input_bytes`: octets of one serialized `Any`. 4 MiB is the default ceiling on a received
#: message in the common gRPC implementations (the C core, Java and Go each default to 4 MiB), so
#: a larger response does not reach a default-configured client in the first place. The extra
#: KiB is for the envelope around the response: the `type_url` of either supported type with the
#: conventional `type.googleapis.com/` prefix is 69 or 80 octets, plus two tags and two lengths.
MAX_INPUT_BYTES = 4 * 1024 * 1024 + 1024

#: `max_depth`: containers of the twin — one per object or list, counted the way
#: `synapse_cdm.adapter.container_depth` counts a parsed document — so that both forms of one
#: message have one depth and the base class's bound and this one are the same number. 64 is the
#: harness loader's own bound (`harness.LOADER_MAX_DEPTH`) and the figure the JSON-reading
#: adapters of `synapse_cdm` declare (`tak`, `ais`, `adsb`, `legion`, `pntmap`). The
#: closure has no recursive message and an unknown field is carried as opaque octets, so the
#: deepest twin the BYTES form can produce is 7 (response 1, list 2, element 3, `point_location`
#: or `symbol` 4, `geo_point` or `numeric_identifier` 5, `@unknown` 6, its entry 7); the bound is
#: reachable through the dict form, whose unknown keys carry arbitrary JSON.
MAX_DEPTH = 64

#: `max_objects`: blue forces in one message (the elements of `blue_forces` or
#: `updated_blue_forces`), counted before any element is decoded. Each becomes an `Entity` and an
#: `Event` (the record §4), so the bound is 20 000 CDM objects — the figure both in-tree AIXM
#: adapters bound one message to (`AIXM511_MAX_OBJECTS`, `AIXM52_MAX_OBJECTS`, one object per time
#: slice). Without it, a blue force with only an identity is six
#: octets on the wire and `MAX_INPUT_BYTES` would hold some seven hundred thousand of them.
MAX_OBJECTS = 10_000

#: Unknown fields in one input, both forms, every level (a second cap the manifest has no field
#: for, declared beside `max_objects` as the AIXM adapters declare their element cap). A carried
#: field is a three-member dict, some hundred times its two-octet minimum on the wire: without a
#: count, `MAX_INPUT_BYTES` of unknown fields would become two million carried entries. 65 536
#: admits six fields a newer contract revision might add on every one of `MAX_OBJECTS` elements.
#: The adapter holds the copies it carries to the same figure: a message- or header-level field
#: counts once for every Entity and once for every Event that carries it (since 2026-10-06, when
#: every Event came to carry the message-level part of the residual).
MAX_UNKNOWN_FIELDS = 65_536

#: Characters of message-level data carried across all the Entities and Events of one message (a
#: third cap the manifest has no field for, declared beside `max_objects` with
#: `MAX_UNKNOWN_FIELDS`; the adapter enforces it). Every Entity carries the typed block's `message`
#: member (type, type_url, list name, index, header with its error_message) and the message- and
#: header-level unknown fields in two places (`residual.data.response` and
#: `residual.data.unknown`), and since 2026-10-06 every Event carries those unknown fields again
#: in the same two places, so without a bound a 4 MiB error_message on `MAX_OBJECTS` elements
#: would serialise to some 40 GiB. The data is measured once with `carried_size` (its compact JSON
#: text with ASCII escaping, in characters), each Entity's index counted with its own digits, and
#: a message whose objects would carry more than this in all is refused
#: (`carried-copies-too-large`). 16 MiB is four
#: times the 4 MiB message ceiling `MAX_INPUT_BYTES` rests on. The `message` member of an
#: ordinary successful snapshot is 200 characters of JSON text (230 for a stream update), of
#: which its type_url and header are about 100, so `MAX_OBJECTS` such elements use about an
#: eighth of it (a snapshot) to just under a seventh (a stream update).
MAX_CARRIED_COPY_CHARS = 16 * 2**20


@dataclasses.dataclass(frozen=True)
class DecodeLimits:
    """The bounds one decode applies. `DEFAULT_LIMITS` holds the declared ones; a smaller value is
    for a test that exercises a guard the declared value leaves out of reach (see `MAX_DEPTH`)."""

    max_input_bytes: int = MAX_INPUT_BYTES
    max_depth: int = MAX_DEPTH
    max_objects: int = MAX_OBJECTS
    max_unknown_fields: int = MAX_UNKNOWN_FIELDS


DEFAULT_LIMITS = DecodeLimits()

# ---------------------------------------------------------------------------------- refusals

#: The record §3.2 (with `null-in-twin` from §2.2). The last five are the codes its "Changes"
#: section added on 2026-10-04.
DECODER_CODES = (
    "input-too-large", "truncated-varint", "varint-too-long", "length-exceeds-input",
    "unsupported-wire-type", "field-number-zero", "wire-type-mismatch", "invalid-utf8",
    "non-finite-number", "timestamp-out-of-range", "repeated-singular-field",
    "multiple-oneof-members", "nesting-too-deep", "too-many-objects", "malformed-type-url",
    "unsupported-message-type", "not-an-any-envelope", "null-in-twin",
    "field-number-too-large", "value-out-of-range", "unknown-field-in-well-known-type",
    "too-many-unknown-fields", "invalid-twin-value",
)

#: The record §4 and §5: the adapter's own refusals, raised through the same class. The last two
#: were added on 2026-10-04 (final verification).
ADAPTER_CODES = (
    "response-not-successful", "unknown-fields-without-carrier", "blue-force-without-identity",
    "empty-identity", "coordinate-out-of-range", "negative-speed", "carried-copies-too-large",
    "error-message-without-carrier",
)

REASON_CODES = DECODER_CODES + ADAPTER_CODES


class TacticalapiRefused(ValueError):
    """A payload this codec or the adapter declines. `code` is the reason code and the message
    begins with it, so a caller can branch on the attribute and a log reader on the text.

    A `ValueError`, as every refusal in `synapse_cdm` is: the conformance suite reads "refused
    without crashing" from the exception class.
    """

    def __init__(self, code: str, detail: str) -> None:
        if code not in REASON_CODES:
            raise ValueError(f"{code!r} is not a reason code docs/tacticalapi-implementation.md "
                             "names")
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}")

    def __reduce__(self):
        return type(self), (self.code, self.detail)


def _refuse(code: str, detail: str) -> TacticalapiRefused:
    return TacticalapiRefused(code, detail)


#: How many characters of a value's repr a refusal quotes. A refusal names what it read so that a
#: reader can find it in the input, not to carry it: a 4 MiB type_url, or a megabyte given for a
#: bool, would otherwise become a refusal text of the same size in every log that records it.
QUOTE_LIMIT = 120


def quote(value: Any) -> str:
    """How a refusal, the codec's or the adapter's, quotes a value taken from the input.

    The value's repr, escaped to printable ASCII when the repr is not printable (a `str`'s repr
    always is; another object's need not be), and cut to `QUOTE_LIMIT` characters with the number
    of characters left out stated. Python writes no integer of more decimal digits than
    `sys.get_int_max_str_digits()` as text and raises a plain `ValueError` instead, which would
    escape the refusal it was meant for; such a value is described, not written.

    So is a value whose own `__repr__` raises anything else, which an in-process caller's object
    can: the refusal it is quoted for is still the refusal raised, and the value is named by its
    type and by what its repr raised (added 2026-10-04, final verification). Only an `Exception`
    is caught; an interrupt is not a value to describe.

    The repr is taken as plain text, with `str.__str__`: `repr` accepts a `str` subclass from a
    `__repr__`, and such a subclass's own methods (`__format__`, `isprintable`, slicing) could
    write anything, a second line or a mebibyte, into the text it was quoted into. Every type
    name the description writes goes through `quote_type` (both added 2026-10-04, final
    verification).
    """
    try:
        text = str.__str__(repr(value))
    except Exception as error:                           # noqa: BLE001 - described, not raised
        # The interpreter's own error for the digit limit, in its own words (3.11 to 3.14 alike);
        # only an exact ValueError is read, since another exception's text is the caller's code.
        if type(error) is ValueError and "integer string conversion" in str(error):
            if _of_type(value, int):
                return f"an integer of {int.bit_length(value)} bits, too long to write as text"
            text = f"a {quote_type(value)} holding an integer too long to write as text"
        else:
            text = f"a {quote_type(value)} whose repr raised {quote_type(error)}"
    return _bounded(text)


def quote_type(value: Any) -> str:
    """How a refusal, or a `validate_source` line, names the type of a value: the type's name,
    escaped and cut as `quote` escapes and cuts a repr. A class name is whatever the class was
    made with, so an in-process caller's class may be named with a line break or a hundred
    thousand characters, or with a `str` subclass that formats as something else; every refusal
    text that names a type takes it from here (added 2026-10-04, final verification).

    The name is read from the type's own slot (`type.__dict__["__name__"]`) and taken as plain
    text, as values are taken with the base type's own conversion: a metaclass may define a
    `__name__` of its own, which could raise or return anything."""
    return _bounded(str.__str__(type.__dict__["__name__"].__get__(type(value))))


def _bounded(text: str) -> str:
    """Plain text as a refusal writes it: escaped to printable ASCII when it is not printable,
    and cut to `QUOTE_LIMIT` characters with the number of characters left out stated."""
    if not text.isprintable():
        text = text.encode("unicode_escape").decode("ascii")
    if len(text) > QUOTE_LIMIT:
        return f"{text[:QUOTE_LIMIT]}... ({len(text) - QUOTE_LIMIT} more characters)"
    return text


def quote_error(error: BaseException) -> str:
    """How a `validate_source` line writes the text of an exception that is not a refusal: one
    the host raised while measuring the input, or one an in-process caller's own code raised
    (the record, the opening paragraph). Neither text is this adapter's, so neither is known to
    be one line. It is taken as plain text, escaped and cut as `quote` escapes and cuts a repr,
    and a text that cannot be taken (an exception's own `__str__` may raise) is described by the
    two types instead (added 2026-10-04, final verification, item 37)."""
    try:
        text = str.__str__(str(error))
    except Exception as failure:                         # noqa: BLE001 - described, not raised
        text = f"a {quote_type(error)} whose text raised {quote_type(failure)}"
    return _bounded(text)


def _of_type(value: Any, kinds: type | tuple[type, ...]) -> bool:
    """Whether a value of the input is of one of `kinds`, read from the value's own type.

    `isinstance` also asks the value's `__class__`, which an in-process caller's object may
    define to name a type it is not, or to raise: such an object passed `isinstance(value, str)`
    and `str.__str__` then raised a `TypeError` that is not a refusal, and a `bool` that was not
    one was returned as given. `type(value)` cannot be redefined, so every type test this module
    applies to a value of the input reads it, and such an object is refused by its own type's
    name (added 2026-10-04, final verification, item 37). For every other value the two tests
    agree."""
    return issubclass(type(value), kinds)


# ------------------------------------------------------------------------- the field table


class Field(NamedTuple):
    """One field of a message, as protoc's descriptor states it. `kind` is the scalar type's name
    (`bool`, `int32`, `int64`, `double`, `string`, `bytes`), `enum` or `message`; `type` is the
    full name of the enum or message, else None; `oneof` is the group's name, else None."""

    name: str
    kind: str
    type: str | None
    repeated: bool
    oneof: str | None


# BEGIN GENERATED FIELD TABLE
# Generated by gates/tacticalapi_field_table.py from protoc's descriptor of the pinned contract,
# upstream commit 58661c9c5de7db1b944a37f6ed05fe16c603cd0e. Not edited by hand: regenerate it
# and replace this block whole. Names and numbers only.
MESSAGES: dict[str, dict[int, Field]] = {
    "google.protobuf.Any": {
        1: Field("type_url", "string", None, False, None),
        2: Field("value", "bytes", None, False, None),
    },
    "google.protobuf.DoubleValue": {
        1: Field("value", "double", None, False, None),
    },
    "google.protobuf.StringValue": {
        1: Field("value", "string", None, False, None),
    },
    "google.protobuf.Timestamp": {
        1: Field("seconds", "int64", None, False, None),
        2: Field("nanos", "int32", None, False, None),
    },
    "rheinmetall.tactical_api.v0.BlueForce": {
        1: Field("identity", "message", "rheinmetall.tactical_api.v0.Identity", False, None),
        2: Field("last_contact_time", "message", "google.protobuf.Timestamp", False, None),
        3: Field("callsign", "message", "google.protobuf.StringValue", False, None),
        4: Field("symbol", "message", "rheinmetall.tactical_api.v0.SymbolIdentifier", False, None),
        5: Field("blue_force_type", "message", "rheinmetall.tactical_api.v0.BlueForceType", False, None),
        6: Field("own_blue_force", "bool", None, False, None),
        7: Field("point_location", "message", "rheinmetall.tactical_api.v0.Point", False, None),
        8: Field("mount_host", "message", "rheinmetall.tactical_api.v0.Identity", False, None),
        9: Field("associated_organization_unit_identity", "message", "rheinmetall.tactical_api.v0.Identity", False, None),
        10: Field("is_deleted", "bool", None, False, None),
    },
    "rheinmetall.tactical_api.v0.BlueForceType": {
        1: Field("is_vehicle", "bool", None, False, None),
        2: Field("is_unmanned", "bool", None, False, None),
        3: Field("is_leader", "bool", None, False, None),
    },
    "rheinmetall.tactical_api.v0.GeoPoint": {
        1: Field("latitude_coordinate", "double", None, False, None),
        2: Field("longitude_coordinate", "double", None, False, None),
        3: Field("vertical_distance", "message", "google.protobuf.DoubleValue", False, None),
        4: Field("vertical_distance_reference_code", "enum", "rheinmetall.tactical_api.v0.VerticalDistanceReferenceCode", False, None),
        5: Field("measurement_code", "enum", "rheinmetall.tactical_api.v0.MeasurementCode", False, None),
    },
    "rheinmetall.tactical_api.v0.GetBlueForcesResponse": {
        1: Field("header", "message", "rheinmetall.tactical_api.v0.ResponseHeader", False, None),
        2: Field("blue_forces", "message", "rheinmetall.tactical_api.v0.BlueForce", True, None),
    },
    "rheinmetall.tactical_api.v0.Identity": {
        1: Field("uuid_identity", "string", None, False, "type"),
        2: Field("string_identity", "string", None, False, "type"),
        3: Field("int32_identity", "int32", None, False, "type"),
        4: Field("int64_identity", "int64", None, False, "type"),
    },
    "rheinmetall.tactical_api.v0.NumericIdentifier": {
        1: Field("first_ten_digits", "int64", None, False, None),
        2: Field("second_ten_digits", "int64", None, False, None),
    },
    "rheinmetall.tactical_api.v0.Point": {
        1: Field("name", "message", "google.protobuf.StringValue", False, None),
        2: Field("location_time", "message", "google.protobuf.Timestamp", False, None),
        3: Field("geo_point", "message", "rheinmetall.tactical_api.v0.GeoPoint", False, None),
        4: Field("course", "message", "google.protobuf.DoubleValue", False, None),
        5: Field("speed", "message", "google.protobuf.DoubleValue", False, None),
    },
    "rheinmetall.tactical_api.v0.ResponseHeader": {
        1: Field("success", "bool", None, False, None),
        2: Field("error_message", "message", "google.protobuf.StringValue", False, None),
    },
    "rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse": {
        1: Field("header", "message", "rheinmetall.tactical_api.v0.ResponseHeader", False, None),
        2: Field("updated_blue_forces", "message", "rheinmetall.tactical_api.v0.BlueForce", True, None),
    },
    "rheinmetall.tactical_api.v0.SymbolIdentifier": {
        1: Field("symbol_catalog", "enum", "rheinmetall.tactical_api.v0.SymbolCatalog", False, None),
        2: Field("string_identifier", "string", None, False, "identifier"),
        3: Field("numeric_identifier", "message", "rheinmetall.tactical_api.v0.NumericIdentifier", False, "identifier"),
    },
}
ENUMS: dict[str, dict[int, str]] = {
    "rheinmetall.tactical_api.v0.MeasurementCode": {
        0: "MEASUREMENT_CODE_UNSPECIFIED",
        1: "MEASUREMENT_CODE_UNKNOWN",
        2: "MEASUREMENT_CODE_GPS",
        3: "MEASUREMENT_CODE_INS",
        4: "MEASUREMENT_CODE_ESTIMATE",
        5: "MEASUREMENT_CODE_LRS",
    },
    "rheinmetall.tactical_api.v0.SymbolCatalog": {
        0: "SYMBOL_CATALOG_UNSPECIFIED",
        1: "SYMBOL_CATALOG_RME",
        2: "SYMBOL_CATALOG_APP6_B",
        3: "SYMBOL_CATALOG_APP6_D",
        4: "SYMBOL_CATALOG_MIL2525_C",
        5: "SYMBOL_CATALOG_MIL2525_D",
        6: "SYMBOL_CATALOG_APP6_E",
        7: "SYMBOL_CATALOG_MIL2525_E",
    },
    "rheinmetall.tactical_api.v0.VerticalDistanceReferenceCode": {
        0: "VERTICAL_DISTANCE_REFERENCE_CODE_UNSPECIFIED",
        1: "VERTICAL_DISTANCE_REFERENCE_CODE_UNKNOWN",
        2: "VERTICAL_DISTANCE_REFERENCE_CODE_CHART_DATUM",
        3: "VERTICAL_DISTANCE_REFERENCE_CODE_LOCAL_DATUM",
        4: "VERTICAL_DISTANCE_REFERENCE_CODE_MEAN_SEA_LEVEL",
        5: "VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_QFE",
        6: "VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_QNH",
        7: "VERTICAL_DISTANCE_REFERENCE_CODE_PRESSURE_DATUM_STANDARD_ATMOSPHERE",
        8: "VERTICAL_DISTANCE_REFERENCE_CODE_TOPOGRAPHIC_SURFACE",
        9: "VERTICAL_DISTANCE_REFERENCE_CODE_WATER_BOTTOM",
        10: "VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_GEOID",
        11: "VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID",
    },
}
# END GENERATED FIELD TABLE

#: The wire type each kind is encoded with. A field the table names arriving with another wire
#: type is refused (`wire-type-mismatch`); no kind here is ever packed (the closure has no
#: repeated scalar, and `gates/tacticalapi_field_table.py` refuses to print one).
WIRE_TYPE_OF_KIND = {
    "bool": WIRE_VARINT, "int32": WIRE_VARINT, "int64": WIRE_VARINT, "enum": WIRE_VARINT,
    "double": WIRE_FIXED64, "string": WIRE_LEN, "bytes": WIRE_LEN, "message": WIRE_LEN,
}

#: message name -> field name -> (number, Field), for the dict form.
FIELDS_BY_NAME: dict[str, dict[str, tuple[int, Field]]] = {
    message: {field.name: (number, field) for number, field in fields.items()}
    for message, fields in MESSAGES.items()
}

#: enum name -> value name -> number, for the dict form.
ENUM_NUMBERS: dict[str, dict[str, int]] = {
    enum: {name: number for number, name in values.items()} for enum, values in ENUMS.items()
}

#: The keys a refusal spells as themselves: every field name of the table, and `@unknown`. All of
#: them are identifiers, so they are printable and short.
_CONTRACT_KEYS = frozenset({field.name for fields in MESSAGES.values() for field in fields.values()}
                           | {"@unknown"})


def _key(key: Any) -> str:
    """How a refusal spells a dict key of the input, and the one way a key enters a refusal text:
    a field name of the table, or `@unknown`, as itself; anything else through `quote`. A key the
    contract does not name is the input's own text, and may hold a line break, a lone surrogate
    or a megabyte; quoted, it reaches the text escaped and cut. Only an exact `str` is spelled as
    itself, so a subclass cannot pass for a name."""
    if type(key) is str and key in _CONTRACT_KEYS:
        return key
    return quote(key)


# ---------------------------------------------------------------------------- the wire reader


def read_varint(data: bytes, offset: int, end: int) -> tuple[int, int]:
    """One base-128 varint at `offset`, reading no octet at or past `end`. Returns the value and
    the offset after it.

    Ten octets carry 70 bits and protobuf's varints are at most 64 wide, so an eleventh octet is
    refused (`varint-too-long`) before it is read, and so is a tenth octet that sets bits past the
    64th: a lenient parser drops those bits, which is a repair.
    """
    value = 0
    position = offset
    while True:
        if position - offset == 10:
            raise _refuse("varint-too-long", f"the varint at offset {offset} still has its "
                          "continuation bit set after ten octets")
        if position >= end:
            raise _refuse("truncated-varint", f"the varint at offset {offset} ends at offset "
                          f"{end} before an octet without the continuation bit")
        octet = data[position]
        value |= (octet & 0x7F) << (7 * (position - offset))
        position += 1
        if not octet & 0x80:
            break
    if value > _UINT64_MAX:
        raise _refuse("varint-too-long", f"the varint at offset {offset} encodes "
                      f"{value.bit_length()} bits; a protobuf varint carries at most 64")
    return value, position


class WireField(NamedTuple):
    """One field as it sat on the wire: its tag's offset, and the span of its value's octets
    (after the length prefix, for wire type 2). `varint` is the value for wire type 0."""

    number: int
    wire_type: int
    offset: int
    start: int
    end: int
    varint: int | None


def wire_fields(data: bytes, start: int, end: int) -> Iterator[WireField]:
    """Every field of the message occupying `data[start:end]`, in wire order.

    Every length is held to the octets that remain BEFORE anything is sliced or allocated: a
    declared length of four billion is refused by a comparison, not by running out of memory.
    The tag is checked in a fixed order — its length (at most `MAX_TAG_OCTETS`), field number 0,
    a number past 29 bits, then the wire type — and the first failing check is the refusal.
    """
    position = start
    while position < end:
        tag_offset = position
        tag, position = read_varint(data, position, end)
        if position - tag_offset > MAX_TAG_OCTETS:
            raise _refuse("varint-too-long", f"the tag at offset {tag_offset} is written in "
                          f"{position - tag_offset} octets; a tag is a 32-bit value and is "
                          f"written in at most {MAX_TAG_OCTETS}")
        number, wire_type = tag >> 3, tag & 7
        if number == 0:
            raise _refuse("field-number-zero", f"the tag at offset {tag_offset} names field "
                          "number 0, which no message can define")
        if number > MAX_FIELD_NUMBER:
            raise _refuse("field-number-too-large", f"the tag at offset {tag_offset} names field "
                          f"number {quote(number)}; field numbers are at most {MAX_FIELD_NUMBER}")
        if wire_type in (3, 4):
            raise _refuse("unsupported-wire-type", f"the tag at offset {tag_offset} (field "
                          f"{quote(number)}) has wire type {quote(wire_type)}, a group "
                          "delimiter; groups are not read")
        if wire_type in (6, 7):
            raise _refuse("unsupported-wire-type", f"the tag at offset {tag_offset} (field "
                          f"{quote(number)}) has wire type {quote(wire_type)}, which the "
                          "encoding does not assign")
        if wire_type == WIRE_VARINT:
            value, after = read_varint(data, position, end)
            yield WireField(number, wire_type, tag_offset, position, after, value)
            position = after
            continue
        if wire_type == WIRE_LEN:
            length, position = read_varint(data, position, end)
        else:
            length = 8 if wire_type == WIRE_FIXED64 else 4
        if length > end - position:
            raise _refuse("length-exceeds-input", f"field {quote(number)} at offset {tag_offset} "
                          f"declares {quote(length)} octets and {end - position} remain in its "
                          "message")
        yield WireField(number, wire_type, tag_offset, position, position + length, None)
        position += length


# ------------------------------------------------------------------------ the bytes form


@dataclasses.dataclass
class _Reading:
    """What one decode carries across messages: its limits and the unknown fields counted."""

    limits: DecodeLimits
    unknown_fields: int = 0

    def carry_unknown(self, where: str) -> None:
        self.unknown_fields += 1
        if self.unknown_fields > self.limits.max_unknown_fields:
            raise _refuse("too-many-unknown-fields", f"{_spell(where)} holds unknown field "
                          f"{self.unknown_fields} (counted across the whole input); at most "
                          f"{self.limits.max_unknown_fields} are carried")


#: How a refusal names the `Any` around the response, which the twin merges away.
ENVELOPE = "(envelope)"


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _spell(path: str) -> str:
    return path or "the response"


def _octets(raw: Any, limits: DecodeLimits, reader: str) -> bytes:
    """The one entry check of `decode`, `envelope_type_url` and `decode_message`: octets (bytes,
    bytearray or memoryview) and nothing else, measured in octets (a memoryview's `nbytes`,
    whatever its item size) against `max_input_bytes` before anything is copied, and returned as
    `bytes`, so every slice the reader takes is bytes and a string field decodes as text.

    Anything else is refused as `twin_of` refuses it, rather than read: a `str` or `None` would
    raise a `TypeError` that is not a refusal, and a list of small integers would be read as
    octets."""
    if not _of_type(raw, (bytes, bytearray, memoryview)):
        raise _refuse("not-an-any-envelope", f"the input is a {quote_type(raw)}; {reader} "
                      "reads octets (bytes, bytearray or memoryview)")
    size = raw.nbytes if _of_type(raw, memoryview) else len(raw)
    if size > limits.max_input_bytes:
        raise _refuse("input-too-large", f"the input is {size} octets and max_input_bytes is "
                      f"{limits.max_input_bytes}")
    return bytes(raw)


def decode(raw: bytes | bytearray | memoryview, *, limits: DecodeLimits = DEFAULT_LIMITS) -> dict:
    """The bytes form (a serialized `Any` wrapping one supported response) as its twin.

    The response is read in place inside the input, so every offset a refusal quotes counts from
    the input's first octet."""
    data = _octets(raw, limits, "decode")
    reading = _Reading(limits)
    envelope = _message(data, 0, len(data), ANY, ENVELOPE, 0, reading)
    if "type_url" not in envelope:
        raise _refuse("not-an-any-envelope", "the input has no type_url (field 1 of "
                      "google.protobuf.Any), so it is not the envelope the adapter reads "
                      "(docs/tacticalapi-implementation.md §2.1); "
                      "a serialized message does not name its own type")
    type_name = type_name_of(envelope["type_url"])
    value = envelope.get("value", slice(len(data), len(data)))
    response = _message(data, value.start, value.stop, type_name, "", 1, reading)
    return {"@type": envelope["type_url"], **response}


def envelope_type_url(raw: bytes | bytearray | memoryview, *,
                      limits: DecodeLimits = DEFAULT_LIMITS) -> str:
    """The `type_url` of a bytes-form input, reading the envelope only (the response's octets are
    bounded but not decoded). The same refusals as `decode` for everything it reads."""
    data = _octets(raw, limits, "envelope_type_url")
    envelope = _message(data, 0, len(data), ANY, ENVELOPE, 0, _Reading(limits))
    if "type_url" not in envelope:
        raise _refuse("not-an-any-envelope", "the input has no type_url (field 1 of "
                      "google.protobuf.Any)")
    return envelope["type_url"]


def decode_message(data: bytes | bytearray | memoryview, type_name: str, *,
                   limits: DecodeLimits = DEFAULT_LIMITS) -> Any:
    """One message of a type the table names, without an envelope, in its twin form (a bare value
    for `Timestamp`, `StringValue` and `DoubleValue`). For tests and for reading a part; the
    envelope itself is read by `decode`."""
    data = _octets(data, limits, "decode_message")
    if type_name not in MESSAGES or type_name == ANY:
        raise _refuse("unsupported-message-type", f"{quote(type_name)} is not a message of the "
                      "field table that decode_message reads")
    reading = _Reading(limits)
    if type_name in (TIMESTAMP, STRING_VALUE, DOUBLE_VALUE):
        return _well_known(data, 0, len(data), type_name, "", reading)
    return _message(data, 0, len(data), type_name, "", 1, reading)


def _count_objects(data: bytes, start: int, end: int, type_name: str, path: str,
                   limits: DecodeLimits) -> None:
    """A supported response's blue forces, counted on the wire before any element is decoded."""
    repeated = {number for number, field in MESSAGES[type_name].items() if field.repeated}
    count = 0
    for wire in wire_fields(data, start, end):
        if wire.number in repeated:
            count += 1
            if count > limits.max_objects:
                name = MESSAGES[type_name][wire.number].name
                raise _refuse("too-many-objects", f"{_spell(path)} carries more than "
                              f"{limits.max_objects} elements in {name} (max_objects); refused "
                              "before any element was decoded")


def _message(data: bytes, start: int, end: int, type_name: str, path: str, depth: int,
             reading: _Reading) -> dict:
    """The message occupying `data[start:end]` as a twin object. `depth` is the twin depth of the
    object this returns (the response is 1; the `Any` envelope, which the twin merges into the
    response, is 0)."""
    if depth > reading.limits.max_depth:
        raise _refuse("nesting-too-deep", f"{_spell(path)} would sit {depth} containers deep in "
                      f"the twin and max_depth is {reading.limits.max_depth}")
    if type_name in SUPPORTED_TYPES:
        _count_objects(data, start, end, type_name, path, reading.limits)
    table = MESSAGES[type_name]
    found: dict[int, Any] = {}
    members: dict[str, int] = {}
    unknown: list[dict] = []
    for wire in wire_fields(data, start, end):
        field = table.get(wire.number)
        if field is None:
            if type_name in WELL_KNOWN_TYPES:
                raise _refuse("unknown-field-in-well-known-type", f"{_spell(path)} "
                              f"({type_name}) holds field number {quote(wire.number)}, which "
                              "that type does not define; the twin renders it without an object "
                              "to carry the field on")
            reading.carry_unknown(path)
            unknown.append({"number": wire.number, "wire_type": wire.wire_type,
                            "hex": data[wire.start:wire.end].hex()})
            continue
        where = _join(path, field.name)
        expected = WIRE_TYPE_OF_KIND[field.kind]
        if wire.wire_type != expected:
            raise _refuse("wire-type-mismatch", f"{where} (field {wire.number}, {field.kind}) "
                          f"arrives with wire type {quote(wire.wire_type)} at offset "
                          f"{wire.offset}; its wire type is {expected}")
        if field.repeated:
            items = found.setdefault(wire.number, [])
            items.append(_value(data, wire, field, f"{where}[{len(items)}]", depth + 2, reading))
            continue
        if wire.number in found:
            raise _refuse("repeated-singular-field", f"{where} (field {wire.number}) occurs a "
                          f"second time at offset {wire.offset}; it is a singular field")
        if field.oneof is not None:
            other = members.get(field.oneof)
            if other is not None:
                raise _refuse("multiple-oneof-members", f"{_spell(path)} sets "
                              f"{table[other].name} and {field.name}, two members of the oneof "
                              f"{field.oneof!r}")
            members[field.oneof] = wire.number
        found[wire.number] = _value(data, wire, field, where, depth + 1, reading)
    twin = {table[number].name: found[number] for number in sorted(found)}
    if unknown:
        if depth + 2 > reading.limits.max_depth:
            raise _refuse("nesting-too-deep", f"the unknown fields of {_spell(path)} would sit "
                          f"{depth + 2} containers deep in the twin and max_depth is "
                          f"{reading.limits.max_depth}")
        twin["@unknown"] = unknown
    return twin


def _value(data: bytes, wire: WireField, field: Field, where: str, depth: int,
           reading: _Reading) -> Any:
    """One known field's value in its twin form. `depth` is the twin depth an object value would
    have."""
    kind = field.kind
    if kind == "message":
        if field.type in (TIMESTAMP, STRING_VALUE, DOUBLE_VALUE):
            return _well_known(data, wire.start, wire.end, field.type, where, reading)
        return _message(data, wire.start, wire.end, field.type, where, depth, reading)
    if kind == "string":
        return _utf8(data[wire.start:wire.end], where)
    if kind == "bytes":
        # The one bytes field of the table is `Any.value`. Its span is kept rather than copied,
        # and `decode` reads the response inside the input from it.
        return slice(wire.start, wire.end)
    if kind == "double":
        value = struct.unpack("<d", data[wire.start:wire.end])[0]
        if not math.isfinite(value):
            raise _refuse("non-finite-number", f"{where} is {quote(value)}; a NaN or an infinity "
                          "is not a value this contract's doubles describe")
        return value
    if kind == "bool":
        if wire.varint not in (0, 1):
            raise _refuse("value-out-of-range", f"{where} is a bool encoded as "
                          f"{quote(wire.varint)}; the encoding writes 0 or 1, and reading another "
                          "number as true is a repair")
        return wire.varint == 1
    signed = wire.varint - (1 << 64) if wire.varint > _INT64_MAX else wire.varint
    if kind == "int64":
        return str(signed)
    if not _INT32_MIN <= signed <= _INT32_MAX:
        raise _refuse("value-out-of-range", f"{where} is a 32-bit {kind} encoded as "
                      f"{quote(signed)}; a lenient parser keeps the low 32 bits, which is a "
                      "repair")
    if kind == "int32":
        return signed
    return ENUMS[field.type].get(signed, signed)


def _utf8(octets: bytes, where: str) -> str:
    try:
        return octets.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _refuse("invalid-utf8", f"{where} is a string field and its octets are not UTF-8 "
                      f"({error.reason} at octet {error.start})") from None


def _well_known(data: bytes, start: int, end: int, type_name: str, where: str,
                reading: _Reading) -> Any:
    """`Timestamp` as RFC 3339 text, `StringValue` and `DoubleValue` as their bare value. A field
    that is absent reads as its default, as protobuf defines: an empty wrapper is "" or 0.0."""
    fields = _message(data, start, end, type_name, where, 0, reading)
    if type_name == STRING_VALUE:
        return fields.get("value", "")
    if type_name == DOUBLE_VALUE:
        return fields.get("value", 0.0)
    return render_timestamp(int(fields.get("seconds", "0")), fields.get("nanos", 0), where)


def render_timestamp(seconds: int, nanos: int, where: str) -> str:
    """RFC 3339 text in UTC with `Z` and the fewest of 0, 3, 6 or 9 fractional digits that hold
    `nanos` exactly — the spelling protobuf's own JSON mapping writes."""
    if not TIMESTAMP_MIN_SECONDS <= seconds <= TIMESTAMP_MAX_SECONDS:
        raise _refuse("timestamp-out-of-range", f"{where} has seconds {quote(seconds)}, outside "
                      "0001-01-01T00:00:00Z … 9999-12-31T23:59:59Z")
    if not 0 <= nanos <= TIMESTAMP_MAX_NANOS:
        raise _refuse("timestamp-out-of-range", f"{where} has nanos {quote(nanos)}, outside "
                      f"0 … {TIMESTAMP_MAX_NANOS}")
    instant = _EPOCH + dt.timedelta(seconds=seconds)
    text = (f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d}T"
            f"{instant.hour:02d}:{instant.minute:02d}:{instant.second:02d}")
    if nanos == 0:
        return text + "Z"
    if nanos % 1_000_000 == 0:
        return f"{text}.{nanos // 1_000_000:03d}Z"
    if nanos % 1_000 == 0:
        return f"{text}.{nanos // 1_000:06d}Z"
    return f"{text}.{nanos:09d}Z"


_TIMESTAMP_TEXT = re.compile(
    r"([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})"
    r"(?:\.([0-9]{3}|[0-9]{6}|[0-9]{9}))?Z")


def parse_timestamp(text: str, where: str) -> tuple[int, int]:
    """Twin `Timestamp` text -> (seconds, nanos). Only §2.2's spelling is read: UTC with `Z` and
    0, 3, 6 or 9 fractional digits; an offset, another digit count or a leap second is not it."""
    match = _TIMESTAMP_TEXT.fullmatch(text)
    if match is None:
        raise _refuse("invalid-twin-value", f"{where} is {quote(text)}; a twin Timestamp is RFC "
                      "3339 in UTC with Z and 0, 3, 6 or 9 fractional digits")
    year, month, day, hour, minute, second = (int(part) for part in match.groups()[:6])
    if year == 0:
        raise _refuse("timestamp-out-of-range", f"{where} is {quote(text)}, before "
                      "0001-01-01T00:00:00Z")
    try:
        instant = dt.datetime(year, month, day, hour, minute, second, tzinfo=dt.timezone.utc)
    except ValueError as error:
        raise _refuse("invalid-twin-value", f"{where} is {quote(text)}, not a calendar instant "
                      f"({error})") from None
    seconds = (instant - _EPOCH) // dt.timedelta(seconds=1)
    fraction = match.group(7)
    nanos = int(fraction.ljust(9, "0")) if fraction else 0
    return seconds, nanos


def type_name_of(type_url: str) -> str:
    """The type a `type_url` names: the part after its last `/` (the record §2.1). The prefix is
    carried verbatim and not otherwise checked. A refusal quotes the type_url once, through
    `quote`: the name after the last `/` is part of it, and either may be megabytes long."""
    if "/" not in type_url:
        raise _refuse("malformed-type-url", f"type_url {quote(type_url)} has no '/'; an Any's "
                      "type_url is a prefix, a '/' and the full type name")
    type_name = type_url.rsplit("/", 1)[1]
    if type_name not in SUPPORTED_TYPES:
        raise _refuse("unsupported-message-type", f"type_url {quote(type_url)} names neither "
                      f"supported type; this adapter reads {SUPPORTED_TYPES[0]} and "
                      f"{SUPPORTED_TYPES[1]} only")
    return type_name


# --------------------------------------------------------------------------- the dict form


def twin_depth(document: Any, limit: int | None = None) -> int:
    """Container nesting — one level per dict or list — counted with a stack, as
    `synapse_cdm.adapter.container_depth` counts it, so no deep input recurses here.

    With a `limit`, the walk stops at the first container deeper than the limit and returns that
    container's depth, `limit + 1`: the answer is then "past the limit", not the full depth.
    Without the stop, a dict that holds itself (an in-process caller can build one; JSON text
    cannot) is a walk that never ends, so the bound it is measured for would never be reached;
    with it, such a dict is past the bound like any other input that nests too deep (added
    2026-10-04, final verification)."""
    deepest, pending = 0, [(document, 1)]
    while pending:
        node, depth = pending.pop()
        if _of_type(node, (dict, list)):
            if limit is not None and depth > limit:
                return depth
            deepest = max(deepest, depth)
            pending.extend((child, depth + 1)
                           for child in (node.values() if _of_type(node, dict) else node))
    return deepest


def validate_twin(document: Any, *, limits: DecodeLimits = DEFAULT_LIMITS) -> dict:
    """A dict-form input held to the table and returned normalised, as a new dict.

    The same refusals as the bytes form where they apply; `input-too-large` does not (a parsed
    twin is not an input size: `synapse_cdm.adapter.wire_size`), nor do the wire-level codes. Two
    normalisations, both to the spelling `decode` writes for the same wire value: a `double` given
    as a JSON integer becomes a float (an integer a double cannot hold exactly is refused, since
    rounding it would be a repair), and a `Timestamp` given with 3, 6 or 9 fractional digits is
    written with the fewest that hold it. A repeated field or `@unknown` given as an empty list
    is dropped, since nothing of it could have been on the wire. Nothing else is rewritten.

    The result is made of plain JSON types: every accepted value comes back as an exact `int`,
    `str`, `float` or `bool` (a subclass, such as an `IntEnum` member, as its plain value; a
    `bool` is never accepted where an integer or a double is due), every container is new, and
    a value is converted before it is checked, so what is returned is what was checked.

    The conversion is the base type's own — `str.__str__`, `int.__int__`, `float.__float__` —
    never `str()`, `int()` or `float()`, which call a subclass's override: `str()` of a
    `(str, Enum)` member is `Class.MEMBER`, not the characters the member holds, so two inputs
    that compare equal would translate differently. Keys are converted the same way before they
    are looked up, and two keys of one object that hold the same text (a subclass may hash
    otherwise than its text) are refused rather than one of them dropped (changed 2026-10-04,
    final verification).
    """
    if not _of_type(document, dict):
        raise _refuse("not-an-any-envelope", f"the input is a {quote_type(document)}; the "
                      "dict form is an object holding @type")
    depth = twin_depth(document, limits.max_depth)
    if depth > limits.max_depth:
        raise _refuse("nesting-too-deep", f"the twin nests {depth} or more containers deep and "
                      f"max_depth is {limits.max_depth}")
    type_url = twin_type_url(document)
    type_name = type_name_of(type_url)
    body = {key: value for key, value in document.items() if not _is_type_key(key)}
    response = _twin_message(body, type_name, "", _Reading(limits))
    return {"@type": type_url, **response}


def twin_type_url(document: dict) -> str:
    """The `type_url` a dict-form input states: the value of the one top-level key whose text is
    `@type`, as plain text that can be written as UTF-8. Refused as `validate_twin` refuses it
    when no key, or two keys, hold that text, or the value is null or not text.

    A key is read by its text, as every key of the dict form is: a `str` subclass may hash
    otherwise than its text, so `document.get("@type")` would not find it. `validate_twin` and
    the adapter's `detect` both read the type here, so the two cannot disagree about which key
    states it (added 2026-10-04, final verification)."""
    stated = [value for key, value in document.items() if _is_type_key(key)]
    if not stated:
        raise _refuse("not-an-any-envelope", "the twin has no @type, so it is not the envelope "
                      "the adapter reads (docs/tacticalapi-implementation.md §2.2)")
    if len(stated) > 1:
        raise _refuse("invalid-twin-value", "the twin has the key @type twice, as two keys that "
                      "hold the same text")
    type_url = stated[0]
    if type_url is None:
        raise _refuse("null-in-twin", "@type is null")
    if not _of_type(type_url, str):
        raise _refuse("invalid-twin-value", f"@type is a {quote_type(type_url)}, not text")
    return _check_text(_plain_text(type_url), "@type")


def _plain_text(value: str) -> str:
    """A `str`, or a subclass of one, as a plain `str` holding the same characters:
    `str.__str__` copies them whatever the subclass's own `__str__` says."""
    return str.__str__(value)


def _is_type_key(key: Any) -> bool:
    """Whether a key of the dict form's top level is the envelope's `@type`, read as text."""
    return _of_type(key, str) and _plain_text(key) == "@type"


def twin_of(raw: Any, *, limits: DecodeLimits = DEFAULT_LIMITS) -> dict:
    """Either input form as the normalised twin: octets through `decode`, a dict through
    `validate_twin`. Anything else is not the envelope either form describes."""
    if _of_type(raw, (bytes, bytearray, memoryview)):
        return decode(raw, limits=limits)
    if _of_type(raw, dict):
        return validate_twin(raw, limits=limits)
    raise _refuse("not-an-any-envelope", f"the input is a {quote_type(raw)}; the adapter "
                  "reads the serialized Any (bytes) or its twin (dict)")


def _check_text(text: str, where: str) -> str:
    """A `str` that can be written as UTF-8: a lone surrogate cannot, and is what a string field
    that was not UTF-8 would have to become."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _refuse("invalid-utf8", f"{where} holds "
                      f"{quote(error.object[error.start:error.end])}, which is not encodable as "
                      "UTF-8") from None
    return text


def _twin_message(node: Any, type_name: str, path: str, reading: _Reading) -> dict:
    if not _of_type(node, dict):
        raise _refuse("invalid-twin-value", f"{_spell(path)} is a {quote_type(node)}; a "
                      f"{type_name} is an object")
    table = MESSAGES[type_name]
    by_name = FIELDS_BY_NAME[type_name]
    if type_name in SUPPORTED_TYPES:
        lists = {field.name for field in table.values() if field.repeated}
        for key, items in node.items():
            name = _plain_text(key) if _of_type(key, str) else None
            if name in lists and _of_type(items, list) \
                    and len(items) > reading.limits.max_objects:
                raise _refuse("too-many-objects", f"{_spell(path)} carries {len(items)} elements "
                              f"in {name} and max_objects is {reading.limits.max_objects}; "
                              "refused before any element was read")
    known: dict[int, Any] = {}
    extra: dict[str, Any] = {}
    unknown: list[dict] = []
    members: dict[str, int] = {}
    seen: set[str] = set()
    for key, value in node.items():
        if not _of_type(key, str):
            raise _refuse("invalid-twin-value", f"{_spell(path)} has the key {_key(key)}; twin "
                          "keys are text")
        key = _plain_text(key)
        if key in seen:
            raise _refuse("invalid-twin-value", f"{_spell(path)} has the key {_key(key)} twice, "
                          "as two keys that hold the same text")
        seen.add(key)
        where = _join(path, _key(key))
        if value is None:
            raise _refuse("null-in-twin", f"{where} is null; presence is stated by the key, so a "
                          "field that was not on the wire has no key")
        if key == "@unknown":
            unknown = _twin_unknown(value, type_name, where, reading)
            continue
        entry = by_name.get(key)
        if entry is None:
            name = _check_text(key, f"the key of {where}")
            reading.carry_unknown(path)
            extra[name] = _twin_json(value, where)
            continue
        number, field = entry
        if field.oneof is not None:
            other = members.get(field.oneof)
            if other is not None:
                raise _refuse("multiple-oneof-members", f"{_spell(path)} sets "
                              f"{table[other].name} and {field.name}, two members of the oneof "
                              f"{field.oneof!r}")
            members[field.oneof] = number
        if field.repeated:
            if not _of_type(value, list):
                raise _refuse("invalid-twin-value", f"{where} is a {quote_type(value)}; a "
                              "repeated field is a list")
            items = [_twin_value(field, item, f"{where}[{index}]", reading)
                     for index, item in enumerate(value)]
            if items:
                known[number] = items
            continue
        known[number] = _twin_value(field, value, where, reading)
    twin = {table[number].name: known[number] for number in sorted(known)}
    twin.update(extra)
    if unknown:
        twin["@unknown"] = unknown
    return twin


def _twin_value(field: Field, value: Any, where: str, reading: _Reading) -> Any:
    if value is None:
        raise _refuse("null-in-twin", f"{where} is null")
    kind = field.kind
    if kind == "message":
        if field.type == TIMESTAMP:
            if not _of_type(value, str):
                raise _refuse("invalid-twin-value", f"{where} is a {quote_type(value)}; a "
                              "twin Timestamp is RFC 3339 text")
            return render_timestamp(*parse_timestamp(_plain_text(value), where), where)
        if field.type == STRING_VALUE:
            return _twin_string(value, where)
        if field.type == DOUBLE_VALUE:
            return _twin_double(value, where)
        return _twin_message(value, field.type, where, reading)
    if kind == "string":
        return _twin_string(value, where)
    if kind == "double":
        return _twin_double(value, where)
    if kind == "bool":
        if not _of_type(value, bool):
            raise _refuse("invalid-twin-value", f"{where} is {quote(value)}; a bool is true or "
                          "false")
        return value
    if kind == "int64":
        if not _of_type(value, str):
            raise _refuse("invalid-twin-value", f"{where} is {quote(value)}; a twin int64 is "
                          "decimal text without leading zeros")
        text = _plain_text(value)
        if not re.fullmatch(r"0|-?[1-9][0-9]*", text):
            raise _refuse("invalid-twin-value", f"{where} is {quote(text)}; a twin int64 is "
                          "decimal text without leading zeros")
        number = int(text) if len(text) <= 20 else None
        if number is None or not _INT64_MIN <= number <= _INT64_MAX:
            raise _refuse("value-out-of-range", f"{where} is {quote(text)}, outside the int64 "
                          "range")
        return text
    if kind == "enum" and _of_type(value, str):
        name = _plain_text(value)
        if name not in ENUM_NUMBERS[field.type]:
            raise _refuse("invalid-twin-value", f"{where} is {quote(name)}, which {field.type} "
                          "does not name")
        return name
    if kind in ("int32", "enum"):
        if _of_type(value, bool) or not _of_type(value, int):
            raise _refuse("invalid-twin-value", f"{where} is {quote(value)}; a twin {kind} is "
                          + ("a JSON integer" if kind == "int32" else "a value name or a number "
                             "the contract does not name"))
        number = int.__int__(value)
        if not _INT32_MIN <= number <= _INT32_MAX:
            raise _refuse("value-out-of-range", f"{where} is {quote(number)}, outside the 32-bit "
                          "range")
        if kind == "enum" and number in ENUMS[field.type]:
            raise _refuse("invalid-twin-value", f"{where} is {number}, which {field.type} names "
                          f"{ENUMS[field.type][number]}; the twin spells a named value by name")
        return number
    raise _refuse("invalid-twin-value", f"{where} is a {kind} field, which has no twin form")


def _twin_string(value: Any, where: str) -> str:
    if not _of_type(value, str):
        raise _refuse("invalid-twin-value", f"{where} is a {quote_type(value)}; a string is "
                      "text")
    return _check_text(_plain_text(value), where)


def _twin_double(value: Any, where: str) -> float:
    """A JSON number as the float the bytes path would read. An integer is converted only when a
    double holds it exactly: 2^53 + 1 would come back as 2^53, a different value, and rounding it
    without a word would be a repair (the record §2.2)."""
    if _of_type(value, bool) or not _of_type(value, (int, float)):
        raise _refuse("invalid-twin-value", f"{where} is {quote(value)}; a double is a JSON "
                      "number")
    if _of_type(value, int):
        whole = int.__int__(value)
        try:
            number = float(whole)
        except OverflowError:
            raise _refuse("non-finite-number", f"{where} is an integer past the double range") \
                from None
        if int(number) != whole:
            raise _refuse("invalid-twin-value", f"{where} is the integer {quote(whole)}, which a "
                          f"double cannot hold exactly (the nearest is {quote(number)}); the twin "
                          "is not rounded")
        return number
    number = float.__float__(value)
    if not math.isfinite(number):
        raise _refuse("non-finite-number", f"{where} is {quote(number)}; a NaN or an infinity is "
                      "not a value this contract's doubles describe")
    return number


_HEX = re.compile(r"(?:[0-9a-f]{2})*")


def _twin_unknown(value: Any, type_name: str, where: str, reading: _Reading) -> list[dict]:
    """A dict-form `@unknown`: each entry exactly `{"number", "wire_type", "hex"}`, describing a
    field the table does not name in this message, with octets its wire type could carry."""
    if not _of_type(value, list):
        raise _refuse("invalid-twin-value", f"{where} is a {quote_type(value)}; @unknown is "
                      "a list")
    entries = []
    for index, entry in enumerate(value):
        here = f"{where}[{index}]"
        if entry is None:
            raise _refuse("null-in-twin", f"{here} is null")
        if not _of_type(entry, dict):
            raise _refuse("invalid-twin-value", f"{here} is a {quote_type(entry)}; an "
                          "@unknown entry is an object")
        for key, member in entry.items():
            if member is None:
                raise _refuse("null-in-twin", f"{here}.{_key(key)} is null")
        # The keys as plain text, as `_twin_message` reads keys; two that become one text leave
        # the entry with fewer keys than it held, and are refused with the rest of its shape.
        plain = {(_plain_text(key) if _of_type(key, str) else key): member
                 for key, member in entry.items()}
        if len(plain) != len(entry) or set(plain) != {"number", "wire_type", "hex"}:
            named = sorted(_plain_text(key) if _of_type(key, str) else quote(key)
                           for key in entry)
            raise _refuse("invalid-twin-value", f"{here} has the keys {quote(named)}; an "
                          "@unknown entry has exactly number, wire_type and hex")
        for name in ("number", "wire_type"):
            member = plain[name]
            if _of_type(member, bool) or not _of_type(member, int):
                raise _refuse("invalid-twin-value", f"{here}.{name} is {quote(member)}, not an "
                              "integer")
        number, wire_type = int.__int__(plain["number"]), int.__int__(plain["wire_type"])
        octets = plain["hex"]
        if number < 0:
            raise _refuse("invalid-twin-value", f"{here} names field number {quote(number)}")
        if number == 0:
            raise _refuse("field-number-zero", f"{here} names field number 0")
        if number > MAX_FIELD_NUMBER:
            raise _refuse("field-number-too-large", f"{here} names field number {quote(number)}; "
                          f"field numbers are at most {MAX_FIELD_NUMBER}")
        if number in MESSAGES[type_name]:
            raise _refuse("invalid-twin-value", f"{here} names field {number}, which {type_name} "
                          f"defines as {MESSAGES[type_name][number].name}; a known field is never "
                          "carried as unknown")
        if wire_type in (3, 4, 6, 7):
            raise _refuse("unsupported-wire-type", f"{here} has wire type {wire_type}")
        if wire_type not in (WIRE_VARINT, WIRE_FIXED64, WIRE_LEN, WIRE_FIXED32):
            raise _refuse("invalid-twin-value", f"{here} has wire type {quote(wire_type)}; wire "
                          "types are 0 … 7")
        if not _of_type(octets, str):
            raise _refuse("invalid-twin-value", f"{here}.hex is {quote(octets)}; it is lowercase "
                          "hexadecimal, two digits per octet")
        octets = _plain_text(octets)
        if not _HEX.fullmatch(octets):
            raise _refuse("invalid-twin-value", f"{here}.hex is {quote(octets)}; it is lowercase "
                          "hexadecimal, two digits per octet")
        raw = bytes.fromhex(octets)
        if wire_type == WIRE_VARINT:
            if not raw:
                raise _refuse("truncated-varint", f"{here}.hex is empty and a varint has at least "
                              "one octet")
            _, after = read_varint(raw, 0, len(raw))
            if after != len(raw):
                raise _refuse("invalid-twin-value", f"{here}.hex holds {len(raw) - after} octets "
                              "after its varint")
        elif wire_type in (WIRE_FIXED64, WIRE_FIXED32):
            width = 8 if wire_type == WIRE_FIXED64 else 4
            if len(raw) != width:
                raise _refuse("invalid-twin-value", f"{here}.hex holds {len(raw)} octets and wire "
                              f"type {wire_type} carries exactly {width}")
        reading.carry_unknown(where)
        entries.append({"number": number, "wire_type": wire_type, "hex": octets})
    return entries


def _twin_json(value: Any, where: str) -> Any:
    """The value of a dict-form key the contract does not name, copied: JSON values only, no
    null, no NaN or infinity, text writable as UTF-8 (the twin is JSON and the carried value ends
    up in the CDM's JSON). Every container is new and every scalar a plain `bool`, `int`,
    `float` or `str`, so nothing returned is the caller's object.

    An integer outside −2^63 … 2^64 − 1 is refused (`invalid-twin-value`): ProtoJSON has no wider
    integer (an `int64` or a `uint64` is the widest the encoding writes), and past some 4 300
    decimal digits Python's own JSON writer and reader cannot write or read the number back, so
    the Entity carrying it could not be serialised. Parsing JSON text never makes one this long;
    an in-process caller can. Two keys of one object that hold the same text are refused, as
    `_twin_message` refuses them (both added 2026-10-04, final verification)."""
    if value is None:
        raise _refuse("null-in-twin", f"{where} is null")
    if _of_type(value, bool):
        return value
    if _of_type(value, int):
        number = int.__int__(value)
        if not _INT64_MIN <= number <= _UINT64_MAX:
            raise _refuse("invalid-twin-value", f"{where} is {quote(number)}, outside "
                          "-2^63 … 2^64 - 1, the widest integer ProtoJSON writes")
        return number
    if _of_type(value, float):
        number = float.__float__(value)
        if not math.isfinite(number):
            raise _refuse("non-finite-number", f"{where} is {quote(number)}; JSON has no NaN or "
                          "infinity")
        return number
    if _of_type(value, str):
        return _check_text(_plain_text(value), where)
    if _of_type(value, list):
        return [_twin_json(item, f"{where}[{index}]") for index, item in enumerate(value)]
    if _of_type(value, dict):
        copied = {}
        for key, item in value.items():
            if not _of_type(key, str):
                raise _refuse("invalid-twin-value", f"{where} has the key {_key(key)}; JSON keys "
                              "are text")
            key = _plain_text(key)
            here = _join(where, _key(key))
            if key in copied:
                raise _refuse("invalid-twin-value", f"{here} occurs twice, as two keys that hold "
                              "the same text")
            name = _check_text(key, f"the key of {here}")
            copied[name] = _twin_json(item, here)
        return copied
    raise _refuse("invalid-twin-value", f"{where} is a {quote_type(value)}, which is not a "
                  "JSON value")


# ------------------------------------------------------------------------ reading a twin


def unknown_fields(twin: dict) -> list[dict]:
    """Every unknown field of a normalised twin with the path of the message that held it ("" for
    the response itself): `{"path", "number", "wire_type", "hex"}` for a field read from the wire,
    `{"path", "key", "value"}` for a key of the dict form. Twin order, depth first."""
    found: list[dict] = []

    def walk(node: dict, type_name: str, path: str) -> None:
        by_name = FIELDS_BY_NAME[type_name]
        for key, value in node.items():
            if key == "@type" and not path:
                continue
            if key == "@unknown":
                found.extend({"path": path, **entry} for entry in value)
                continue
            entry = by_name.get(key)
            if entry is None:
                found.append({"path": path, "key": key, "value": value})
                continue
            field = entry[1]
            if field.kind != "message" or field.type in WELL_KNOWN_TYPES:
                continue
            if field.repeated:
                for index, item in enumerate(value):
                    walk(item, field.type, f"{_join(path, key)}[{index}]")
            else:
                walk(value, field.type, _join(path, key))

    walk(twin, type_name_of(twin["@type"]), "")
    return found


# --------------------------------------------------------------------------- the typed block
#
# The record §5.1 and "Typed block layout (as built)". One model per message of the closure that
# an element can hold, each field named and typed as the twin states it: an `int64` as decimal
# text, a `Timestamp` as §2.2's RFC 3339 text, a wrapper as its bare value, an enum as its value
# name or, for a number the contract does not name, the number. Every field is optional because
# presence is the wire's: a field that was not on the wire has no key, and a field that was on
# the wire with its default value keeps its key. The block is dumped with `exclude_unset`, so
# what the twin stated is exactly what the block holds.

#: The block's contract name, written on the block and on every event the adapter emits.
TYPED_BLOCK_CONTRACT = "tacticalapi-blueforce/1"

Int64Text = Annotated[str, ModelField(pattern=r"^(0|-?[1-9][0-9]*)$")]
TimestampText = Annotated[str, ModelField(
    pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(\.([0-9]{3}|[0-9]{6}|[0-9]{9}))?Z$")]
#: An enum as the twin states it: the contract's value name, or a number it does not name.
EnumValue = str | int


class BlockModel(BaseModel):
    """Closed and strict: a key the contract does not name is refused, a value is never coerced
    (a bool is not an int, a number is not text), and `null` is refused because presence is
    stated by the key — the twin's own rule (`null-in-twin`), restated for a block validated on
    its own."""

    model_config = ConfigDict(extra="forbid", strict=True)

    @model_validator(mode="before")
    @classmethod
    def _no_null(cls, data: Any) -> Any:
        if isinstance(data, dict):
            nulls = sorted(str(key) for key, value in data.items() if value is None)
            if nulls:
                raise ValueError(f"{nulls} are null; a field that was not on the wire has no key")
        return data


class IdentityBlock(BlockModel):
    """`Identity`: the one `oneof type` member that was on the wire."""

    uuid_identity: str | None = None
    string_identity: str | None = None
    int32_identity: int | None = None
    int64_identity: Int64Text | None = None


class NumericIdentifierBlock(BlockModel):
    first_ten_digits: Int64Text | None = None
    second_ten_digits: Int64Text | None = None


class SymbolBlock(BlockModel):
    symbol_catalog: EnumValue | None = None
    string_identifier: str | None = None
    numeric_identifier: NumericIdentifierBlock | None = None


class BlueForceTypeBlock(BlockModel):
    is_vehicle: bool | None = None
    is_unmanned: bool | None = None
    is_leader: bool | None = None


class GeoPointBlock(BlockModel):
    latitude_coordinate: float | None = None
    longitude_coordinate: float | None = None
    vertical_distance: float | None = None
    vertical_distance_reference_code: EnumValue | None = None
    measurement_code: EnumValue | None = None


class PointBlock(BlockModel):
    name: str | None = None
    location_time: TimestampText | None = None
    geo_point: GeoPointBlock | None = None
    course: float | None = None
    speed: float | None = None


class BlueForceBlock(BlockModel):
    """`BlueForce`, every field the contract defines, in field-number order (the twin's)."""

    identity: IdentityBlock | None = None
    last_contact_time: TimestampText | None = None
    callsign: str | None = None
    symbol: SymbolBlock | None = None
    blue_force_type: BlueForceTypeBlock | None = None
    own_blue_force: bool | None = None
    point_location: PointBlock | None = None
    mount_host: IdentityBlock | None = None
    associated_organization_unit_identity: IdentityBlock | None = None
    is_deleted: bool | None = None


class HeaderBlock(BlockModel):
    """`ResponseHeader` as stated. `success` is always present and true on a translated message:
    a response without it is refused before any block exists."""

    success: bool | None = None
    error_message: str | None = None


class MessageBlock(BlockModel):
    """Which message the element came from: its type name, the `type_url` as stated, the
    repeated field that held the element, the element's index in it, and the header."""

    type: Literal["rheinmetall.tactical_api.v0.GetBlueForcesResponse",
                  "rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse"]
    type_url: str
    list: Literal["blue_forces", "updated_blue_forces"]
    index: Annotated[int, ModelField(ge=0)]
    header: HeaderBlock


class TypedBlock(BlockModel):
    """`tacticalapi-blueforce/1`: `Entity.attributes["tacticalapi"]`."""

    contract: Literal["tacticalapi-blueforce/1"]
    message: MessageBlock
    blue_force: BlueForceBlock


#: message name -> the block model carrying it, for the test that holds the two to one another.
BLOCK_MODELS: dict[str, type[BlockModel]] = {
    f"{PACKAGE}.BlueForce": BlueForceBlock,
    f"{PACKAGE}.Identity": IdentityBlock,
    f"{PACKAGE}.SymbolIdentifier": SymbolBlock,
    f"{PACKAGE}.NumericIdentifier": NumericIdentifierBlock,
    f"{PACKAGE}.BlueForceType": BlueForceTypeBlock,
    f"{PACKAGE}.Point": PointBlock,
    f"{PACKAGE}.GeoPoint": GeoPointBlock,
    f"{PACKAGE}.ResponseHeader": HeaderBlock,
}


def typed_block(twin: dict, list_name: str, index: int) -> dict:
    """Element `index` of `twin[list_name]` as its validated typed block, in its JSON form.

    The element's known fields are copied as the twin states them and its unknown ones (dict-form
    keys the contract does not name, `@unknown` lists) are left out at every level — they are the
    residual's. The header is the twin's, known fields only, for the same reason. Validation
    changes nothing: the block dumped is the block built, which the adapter's tests assert.
    """
    block = {
        "contract": TYPED_BLOCK_CONTRACT,
        "message": message_block(twin, list_name, index),
        "blue_force": known_only(twin[list_name][index], f"{PACKAGE}.BlueForce"),
    }
    return TypedBlock.model_validate(block).model_dump(mode="json", exclude_unset=True)


def message_block(twin: dict, list_name: str, index: int) -> dict:
    """The typed block's `message` member for element `index` of `twin[list_name]`: the type
    name, the type_url as stated, the list, the index, and the header's known fields. One
    definition, because the adapter also measures it (`MAX_CARRIED_COPY_CHARS`) before it builds
    any block: every Entity of the message carries it, and only the index differs."""
    return {"type": type_name_of(twin["@type"]), "type_url": twin["@type"], "list": list_name,
            "index": index,
            "header": known_only(twin.get("header", {}), f"{PACKAGE}.ResponseHeader")}


def carried_size(value: Any) -> int:
    """The measure `MAX_CARRIED_COPY_CHARS` bounds (the record §4, §6): the number of characters
    of the value written as compact JSON text with ASCII escaping, which is exactly what
    `json.dumps(value, separators=(",", ":"))` writes — quotes, separators, every escape and
    every digit of every number counted. That is what the value adds to each serialised Entity
    or Event that carries it, so the bound bounds the output it is declared for.

    Changed 2026-10-04 (final verification) from "the characters of every string plus one for
    every number, boolean and container": that count let a number of thousands of digits, or a
    string of control characters (six characters each when written), stand for far more output
    than it counted, and a dict-form twin read from 3.6 million characters of JSON text was
    measured as within the bound and serialised to some 64 billion.

    The value is built from a validated twin: JSON types only, no NaN or infinity, no integer
    outside the 64-bit range (`_twin_json` refuses those), at most `max_depth` containers deep,
    so the writer neither fails on it nor recurses deeply. The text is built once per measured
    value, never per object."""
    return len(json.dumps(value, separators=(",", ":")))


def known_only(node: dict, type_name: str) -> dict:
    """A twin message with every key the contract does not name removed, at every level."""
    by_name = FIELDS_BY_NAME[type_name]
    kept: dict = {}
    for key, value in node.items():
        entry = by_name.get(key)
        if entry is None:
            continue
        field = entry[1]
        if field.kind == "message" and field.type not in WELL_KNOWN_TYPES:
            kept[key] = known_only(value, field.type)
        else:
            kept[key] = value
    return kept


def unknown_only(node: dict, type_name: str) -> dict:
    """The complement of `known_only`: a twin message reduced to what the contract does not name
    — its dict-form unknown keys with their values, its `@unknown` list, and every nested message
    that holds either — at the paths the twin gives them. Empty when nothing is unknown. Repeated
    fields are not descended: the element lists are the adapter's to split.

    `@type` is left out on the response alone, where it is the envelope's type_url. Below the
    top level a dict-form key `@type` is a key the contract does not name, as `unknown_fields`
    lists it, and it is kept at its own path like any other (changed 2026-10-04, final
    verification: it was left out at every level, so it was listed and not placed)."""
    by_name = FIELDS_BY_NAME[type_name]
    kept: dict = {}
    for key, value in node.items():
        if key == "@type" and type_name in SUPPORTED_TYPES:
            continue
        entry = by_name.get(key)
        if entry is None:
            kept[key] = value
            continue
        field = entry[1]
        if field.kind == "message" and field.type not in WELL_KNOWN_TYPES and not field.repeated:
            inner = unknown_only(value, field.type)
            if inner:
                kept[key] = inner
    return kept
