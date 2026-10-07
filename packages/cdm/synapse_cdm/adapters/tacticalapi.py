"""TacticalAPI blue-force read side (`rheinmetall.tactical_api.v0`) -> CDM. Ingest only.
Adapter #22.

The repository's `docs/tacticalapi-implementation.md` (the record, below) is this module's
specification, section by section; `tacticalapi_codec` holds the contract's field table, the wire
reader and the twin, and this module is the translation and nothing else. This repository is not
affiliated with the interface's publisher; the name says which published contract the adapter
reads.

WHAT A MESSAGE BECOMES
----------------------
One `to_cdm` call takes one response: a `GetBlueForcesResponse` (a snapshot) or a
`SubscribeBlueForceEventsResponse` (one update of a stream), as a serialized
`google.protobuf.Any` (bytes) or as its twin (dict). Both forms go through one twin
(`codec.twin_of`), so both give the same objects. Each element of `blue_forces` /
`updated_blue_forces` yields one `Entity` (the blue force as stated) followed by one `Event` (the
report that stated it), in list order. A stream is a sequence of calls: the adapter holds no
session, no stream position and nothing between two calls, and two elements with one identity
in one message are two entities with one `entity_id`, both kept, in order — merging them would
be fusion.

THE ELEMENT IS CARRIED WHOLE, AND THE CANONICAL FIELDS ARE PROJECTIONS OF IT
---------------------------------------------------------------------------
`Entity.attributes["tacticalapi"]` is the typed block `tacticalapi-blueforce/1`
(`codec.TypedBlock`): the message the element came from and the element exactly as the twin
states it — times as their text, `int64` as decimal text, enums as stated. Every canonical field
is a projection of what that block holds, so a rule that declines to project something (a 2525C
symbol, a course of 360, a height with no position) loses nothing. What the
contract does not name — an unknown wire field, a dict-form key — is the residual's: it sits at
its own path under `residual.data.response` (message and header level) and
`residual.data.blue_force` (the element's), and `residual.data.unknown` lists every one with the
path of the message that held it. `MAPPINGS` binds every leaf of the twin to one of those places
and the harness's ledger checks it.

WHAT IS READ, AND WHAT IS DECLINED
----------------------------------
Identity is the `Identity` oneof member and its value, keyed with the member's name, so the text
`7` and the integer `7` stay two identities. Affiliation is UNKNOWN (R3, ruled 2026-10-06): the
message carries no affiliation field, and that the service's own definition names the members of
its list blue forces is a statement about the service, not a field of the message, so the adapter
asserts no affiliation from it or from the deployment context a message arrives in — the
`stanag4586` reading. A caller that knows better says so: `TacticalapiAdapter(affiliation=...)`
takes one of the four `Affiliation` members, as `c2sim` takes its `own_side`, and every Entity
gets it with a basis saying the caller supplied it. Nothing is ever read from a symbol, and a
supplied affiliation is compared with nothing in the message. A symbol becomes
`Entity.symbol` only when it is a MIL-STD-2525D numeric code; nothing is converted and nothing
derived. A position needs at least one coordinate on the wire: under proto3 an unset pair and
0°N 0°E are the same bytes, and the CDM forbids a zero position standing for unknown. A course
in [0, 360) is `Kinematics.course_deg`, read as degrees true: the contract states degrees and no
north reference, so the reference is an assumption, and `course_basis` says so on every Entity it
is applied to (R5, ruled 2026-10-06); a course outside that range is not mapped and nothing
normalises it. A deleted element is a status
and a STATUS_CHANGE event, with no `valid_to` invented. Every one of these readings is written
on the object as a `*_basis` attribute, so a consumer meets the reason beside the value.

TIME
----
`point_location.location_time`, else `last_contact_time`, else — the read side marks no time
field mandatory — the receipt instant from the injected clock, with `valid_from_basis` and
`observed_at_basis` saying which. A Timestamp holding seconds 0 and nanos 0 is what a
default-constructed one serialises to, so it is passed over like an absent one and the basis
says so: the CDM forbids an unknown time becoming 1970-01-01. One of seconds 0 and nanos 1 to
999 999 is a stated time and is used as stated, although the CDM's millisecond text of it is
the epoch's; `validate_source` says so. `received_at` is always the injected clock, read once
per message. Nothing here reads the wall clock.

WHAT IS REFUSED
---------------
Everything `tacticalapi_codec` refuses, and the eight adapter-level codes of the record §4 and
§5, all raised as `TacticalapiRefused` (a `ValueError` whose message begins with its code) before
any object is returned. The declared size and depth bounds are enforced first by the base class
(`InputTooLarge`, `InputTooDeep`, both `ValueError`s), then again by the codec. A value a refusal
here takes from the input is quoted through `tacticalapi_codec.quote`, as the codec's are. Apart
from those, the constructor refuses an `affiliation` that is not an `Affiliation` member with a
`ValueError` whose text begins `invalid-affiliation` (R3): a refusal of the caller's context, not
of an input.

WHAT EVERY ENTITY AND EVERY EVENT CARRIES, AND OWNS
---------------------------------------------------
Every Entity and every Event carries a `residual` whose `data` is never empty (the record §5.9;
changed 2026-10-06, the landing, for the host's rule that every object of a `structured` adapter
carries one): `unknown` always, listing the unknown fields the object carries (`[]` when there
are none), and `response` / `blue_force` when the message or the element holds one. An Event
carries the message-level part of its Entity's: `response` and the message- and header-level
entries of `unknown`, never the element's own.

The message's own data (the typed block's `message` member, and the message- and header-level
unknown fields) is carried on every Entity, and its unknown fields again on every Event, so it
is measured once, as compact JSON text, and held, times the number of elements, to
`MAX_CARRIED_COPY_CHARS` before any object is built (`carried-copies-too-large`). Each object
gets its own copy of every container it carries: mutating one Entity's or Event's residual, or
an Entity's typed block, changes no other object and not the input. Each Entity and each Event
has its own provenance stamp (`SourceRef`) and its own transformation list. Strings, which cannot
change, are shared.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter, InputTooDeep, InputTooLarge
from synapse_cdm.enums import (Affiliation, EntityType, EventType, PositionSource, Severity,
                               VerticalReference, VerticalUnit)
from synapse_cdm.geo import VerticalPosition
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import (CDMBase, Entity, Event, Kinematics, OperationalStatus, Position,
                                Residual as ResidualBlock, SourceRef)

from synapse_cdm.adapters import tacticalapi_codec as codec
from synapse_cdm.adapters.tacticalapi_codec import TacticalapiRefused

#: `source_ids[].system`, the residual namespace and `metadata.format.name` (the record §5).
SYSTEM = "TacticalAPI"

BLUE_FORCE = f"{codec.PACKAGE}.BlueForce"
IDENTITY = f"{codec.PACKAGE}.Identity"
VERTICAL_CODES = f"{codec.PACKAGE}.VerticalDistanceReferenceCode"
MEASUREMENT_CODES = f"{codec.PACKAGE}.MeasurementCode"

#: The repeated field of each supported response that holds its blue forces.
ELEMENT_LIST: dict[str, str] = {
    type_name: next(field.name for field in codec.MESSAGES[type_name].values() if field.repeated)
    for type_name in codec.SUPPORTED_TYPES
}

#: The record §5.5's vertical reference table, all twelve codes. A number the contract does not
#: name is treated as code 0. Only code 11 is metres above the ellipsoid, so only code 11 sets
#: `alt_m`; nothing is converted from another datum.
VERTICAL_REFERENCE: dict[int, VerticalReference] = {
    0: VerticalReference.UNKNOWN,     # UNSPECIFIED: a value this interface version does not know
    1: VerticalReference.UNKNOWN,     # UNKNOWN: stated unknown
    2: VerticalReference.UNKNOWN,     # CHART_DATUM: no CDM member for a tidal chart datum
    3: VerticalReference.UNKNOWN,     # LOCAL_DATUM: no CDM member for a local datum
    4: VerticalReference.MSL,         # MEAN_SEA_LEVEL
    5: VerticalReference.BARO,        # PRESSURE_DATUM_QFE: altimeter against a stated setting
    6: VerticalReference.BARO,        # PRESSURE_DATUM_QNH: as above
    7: VerticalReference.BARO,        # STANDARD_ATMOSPHERE: CDM `FL` needs the FL unit; metres here
    8: VerticalReference.AGL,         # TOPOGRAPHIC_SURFACE: height above the surface beneath
    9: VerticalReference.UNKNOWN,     # WATER_BOTTOM: no CDM member
    10: VerticalReference.MSL,        # WGS84_GEOID: the CDM defines MSL as a geoid model
    11: VerticalReference.HAE,        # WGS84_REFERENCE_ELLIPSOID: metres above the ellipsoid
}
HAE_CODE = 11

#: The record §5.5's measurement codes. Every other code — UNSPECIFIED, UNKNOWN, LRS, a number
#: the contract does not name, or no code — is ESTIMATED: `position_source` is required, has four
#: members and none of them means unknown or laser-ranged, so the understating member stands and
#: the basis states the source's own code (the `tak` precedent).
POSITION_SOURCE: dict[int, PositionSource] = {
    2: PositionSource.GNSS,           # GPS
    3: PositionSource.INERTIAL,       # INS
    4: PositionSource.MANUAL,         # ESTIMATE: a position a person entered by judgement
}

#: The record §5.4: a 2525D numeric code, the only symbol `Entity.symbol` is set from.
SYMBOL_CATALOG_2525D = "SYMBOL_CATALOG_MIL2525_D"
FIRST_SET = (1_000_000_000, 9_999_999_999)
SECOND_SET = (0, 9_999_999_999)
#: The 2525D standard-identity digit of a friend, and where it sits in the twenty-digit code.
FRIEND_DIGIT, IDENTITY_DIGIT = "3", 3
#: The length of the contract's string symbol form (the record §8 question 4), and the two
#: catalogs the contract states that length for; under any other catalog it states none, so
#: `validate_source` reports a length only under these two (changed 2026-10-04, final
#: verification).
SYMBOL_STRING_LENGTH = 15
SYMBOL_STRING_CATALOGS = ("SYMBOL_CATALOG_APP6_B", "SYMBOL_CATALOG_MIL2525_C")

#: The record §5.6: `Kinematics.course_deg` holds degrees true in [0, 360) (the host's model,
#: `ge=0.0, lt=360.0`). A course in that range is mapped as stated; any other is not mapped and
#: nothing normalises it. The codec refuses a NaN or an infinity before this rule is reached.
COURSE_RANGE = (0.0, 360.0)
#: The basis of a mapped course (R5, ruled 2026-10-06): the contract states degrees and no north
#: reference, so the reference is an assumption, stated on every value it is applied to.
COURSE_ASSUMED_TRUE = (
    "point_location.course in degrees as stated, read as degrees true: the contract states "
    "degrees and no north reference, so the north reference is ASSUMED true, which "
    "Kinematics.course_deg means (limitation course-reference-not-stated; R5, ruled 2026-10-06)")
#: How a basis and `validate_source` say why a course outside [0, 360) is not mapped.
COURSE_OUT_OF_RANGE = (
    "outside [0, 360), the range Kinematics.course_deg holds, so it is not mapped and "
    "course_deg stays None; nothing normalises it (no modulo, no clamping), and the value stays "
    "in the typed block")

#: The record §5.4, R3 as ruled 2026-10-06: the basis of the default affiliation, UNKNOWN (the
#: `stanag4586` reading of a format that states no affiliation field).
AFFILIATION_BASIS = (
    "UNKNOWN: the message carries no affiliation field. The BlueForceTracking service's own "
    "definition names the members of this list blue forces, which is a statement about the "
    "service and not a field of the message, so the adapter asserts no affiliation from it or "
    "from the deployment context a message arrives in; nothing is read from a symbol code. A "
    "caller that knows the affiliation supplies it: TacticalapiAdapter(affiliation=...) (R3, "
    "ruled 2026-10-06)")
#: The basis when the caller supplied the affiliation (the `c2sim` precedent of caller context),
#: formatted with the member.
SUPPLIED_AFFILIATION_BASIS = (
    "{member}: supplied by the caller, TacticalapiAdapter(affiliation=Affiliation.{member}); the "
    "message carries no affiliation field, and the adapter asserts none of its own and compares "
    "the supplied one with nothing in the message, a symbol code included (R3, ruled "
    "2026-10-06)")
#: The reason code a construction with an affiliation that is not an `Affiliation` member is
#: refused with. A `ValueError` of the constructor, not a `TacticalapiRefused` of an input.
INVALID_AFFILIATION = "invalid-affiliation"
SEVERITY_BASIS = "INFO: the contract carries no urgency field; INFO is the format's silence"
NO_TIME_BASIS = (
    "the receipt instant: the element states neither point_location.location_time nor "
    "last_contact_time (the read side marks no time field mandatory), so the injected clock "
    "stands in")
#: The twin's text for a Timestamp holding seconds 0 and nanos 0 (the record §5.3).
ZERO_TIMESTAMP = "1970-01-01T00:00:00Z"
#: How a basis or `validate_source` says that a source time was passed over for being zero.
ZERO_PASSED_OVER = (
    f"is the zero Timestamp ({ZERO_TIMESTAMP}), which is what a default-constructed one "
    "serialises to, so proto3 cannot tell it from a time never set and it is passed over "
    "(limitation proto3-zero-indistinguishable); its text stays in the typed block")
#: Nanoseconds in a millisecond, the CDM's precision: a Timestamp of seconds 0 and fewer nanos
#: than this is rendered as the epoch's text (the record §5.3).
NANOS_PER_MILLISECOND = 1_000_000
#: The CDM's text of the epoch, which it forbids for an unknown time (the host's check J).
EPOCH_TEXT = "1970-01-01T00:00:00.000Z"
#: How `validate_source` describes a Timestamp of seconds 0 and nanos 1 … 999 999 after naming
#: it (added 2026-10-04, final verification). Not proto3's default, so it is used as stated.
BELOW_A_MILLISECOND = (
    "less than a millisecond after the epoch: a stated time, not what a default-constructed "
    "Timestamp serialises to, so it is read as the instant stated; the CDM renders it to the "
    f"millisecond as {EPOCH_TEXT}, the text it forbids for an unknown time, and the host's "
    "check J cannot tell the two apart")
#: The suffix the record §5.8 gives the event id input of a deleted element.
DELETED_SUFFIX = "#is_deleted"
#: The refusals whose text is bounded where it is written: this adapter's, and the base
#: class's two for an input past a declared bound. `validate_source` writes their text whole
#: and every other exception's through `codec.quote_error` (item 37).
REFUSALS = (TacticalapiRefused, InputTooLarge, InputTooDeep)


def _refuse(code: str, detail: str) -> TacticalapiRefused:
    return TacticalapiRefused(code, detail)


# ---------------------------------------------------------------------------- the MAPPINGS ledger
#
# Source keys are paths in the twin. `[_]` matches an element index without binding it: every
# element's leaves go to the typed block of the entity that element became, and an element's
# entity is found by kind (`entity:`), as `c2sim` binds its objects — the output interleaves an
# Entity and an Event per element, so the index-bound target `#[*]` would name the wrong object.

_BLOCK = "entity:attributes.tacticalapi"


def _m(to: str, rule: str = "identity", tolerance: float | None = None) -> lossless.Mapping:
    return lossless.Mapping(to, rule, tolerance)


def _block_leaves(type_name: str, source: str, dest: str) -> dict:
    """Every field of a message, from the field table: a nested message's own path (the leaf
    the ledger sees when it arrives empty) and each of its fields, recursively; a scalar, an
    enum and a well-known type are leaves."""
    out: dict = {}
    for field in codec.MESSAGES[type_name].values():
        here, there = f"{source}.{field.name}", f"{dest}.{field.name}"
        out[here] = _m(there)
        if field.kind == "message" and field.type not in codec.WELL_KNOWN_TYPES:
            out.update(_block_leaves(field.type, here, there))
    return out


def _build_mappings() -> dict:
    """Specific leaves first, then the residual subtrees, then the message itself: the ledger
    tries the keys in this order and the first that matches binds the leaf.

    Four leaves are also held to the canonical field they project to, as a tuple every member
    of which must hold: the coordinates (to the position and to the event's geometry), the
    speed and, since 2026-10-06 (R5), the course. The first three projections are unconditional
    whenever their leaf exists. The course's is not: a course outside [0, 360) is not mapped
    (the record §5.6). It is held by `absent_if`, the one rule whose expected outcome can be
    absence, with 360 as its sentinel (the full turn, which some sources write for north) and
    `number` for every other value; the grammar has one sentinel per rule and no
    range, so a negative course or one past 360 would read LOST here although the adapter
    carries it in the typed block and names it (a reading of the grammar, written down in the record
    and in a test; no shipped fixture holds one). The other conditional projections (the symbol,
    the height, both times) are held to the typed block only.

    The location time was held to its projection too until 2026-10-04 (final verification): a
    zero Timestamp is now passed over (the record §5.3), so its projection to `valid_from` and
    `observed_at` holds only when the text is not the zero one, and `absent_if` cannot hold it,
    since it asks the destination to be absent and `valid_from` never is. The projection is held
    by the tests and the goldens instead."""
    out: dict = {
        "@type": _m(f"{_BLOCK}.message.type_url"),
        "header.success": _m(f"{_BLOCK}.message.header.success"),
        "header.error_message": _m(f"{_BLOCK}.message.header.error_message"),
    }
    for list_name in ELEMENT_LIST.values():
        element, block = f"{list_name}[_]", f"{_BLOCK}.blue_force"
        out.update(_block_leaves(BLUE_FORCE, element, block))
        geo = "point_location.geo_point"
        out[f"{element}.{geo}.latitude_coordinate"] = (
            _m(f"{block}.{geo}.latitude_coordinate"), _m("entity:position.lat", "number"),
            _m("event:geometry.coordinates[1]", "number"))
        out[f"{element}.{geo}.longitude_coordinate"] = (
            _m(f"{block}.{geo}.longitude_coordinate"), _m("entity:position.lon", "number"),
            _m("event:geometry.coordinates[0]", "number"))
        out[f"{element}.point_location.speed"] = (
            _m(f"{block}.point_location.speed"), _m("entity:kinematics.speed_mps", "number"))
        out[f"{element}.point_location.course"] = (
            _m(f"{block}.point_location.course"),
            lossless.Mapping("entity:kinematics.course_deg", "absent_if",
                             params={"sentinel": COURSE_RANGE[1], "else": "number"}))
    for list_name in ELEMENT_LIST.values():
        out[f"{list_name}[_]"] = lossless.Mapping("entity:residual.data.blue_force",
                                                  kind="residual")
    out[""] = lossless.Mapping("entity:residual.data.response", kind="residual")
    return out


# ----------------------------------------------------------------------------------- the adapter


class TacticalapiAdapter(Adapter):
    """One TacticalAPI blue-force response in; an Entity and an Event per blue force out."""

    name = "tacticalapi"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration, the record §6. `OPEN` is the maintainer's ruling R7 of
    #: 2026-10-06 (the record's rulings): ARCHITECTURE.md §3.2 defines it as a source standard
    #: publicly available under terms permitting free implementation, which the upstream files are
    #: under the Eclipse Public License 2.0 (R8), and R10 ruled the adapter no controlled item, so
    #: `CONTROLLED` does not apply. `VERIFIED` beside `standard-encoding` is R2, confirmed the
    #: same day: the host's ruling (B) of 2026-09-20 makes it what green public gates assert for
    #: that binding, and the in-tree manifest gate admits nothing else.
    metadata = AdapterMetadata(
        id="tacticalapi",
        name="TacticalAPI blue-force read side",
        adapter_version="1.0.0",
        format=FormatRef(name=SYSTEM,
                         version="rheinmetall.tactical_api.v0, commit 58661c9 (2026-09-01); no "
                                 "tag or release exists"),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
                  "`synapse_cdm.harness --adapter tacticalapi` over the packaged fixture set "
                  "reports `translate`, `schema` and `provenance` PASS on every "
                  "fixture, which carries L1 to L3, and its `lossless` column rests on the "
                  "path-bound ledger (`MAPPINGS` declared) with no LOST leaf on any parsed twin. "
                  "L4 is NOT declared: this adapter is ingest-only, so there is no egress "
                  "direction for information to be lost in and the roundtrip check is "
                  "inapplicable rather than absent (ARCHITECTURE.md §3.6, rule 4). A rung passed "
                  "vacuously is not a rung declared, so the declaration stops at the last one "
                  "positively verified.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=list(codec.SUPPORTED_TYPES),
            limits=Limits(
                max_input_bytes=codec.MAX_INPUT_BYTES,
                max_depth=codec.MAX_DEPTH,
                max_objects=codec.MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes":
                        "this adapter accepts no compressed payload: it is handed one "
                        "already-received message, and any transport compression is undone by "
                        "the caller before the message reaches it",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced: runtime code reads no clock but the "
                        "injected one, and the byte, object, unknown-field and carried-copy "
                        "bounds make every walk of the decoder and of this module linear in a "
                        "bounded input read from octets or JSON text (a dict whose containers an "
                        "in-process caller shares is walked as the tree it stands for; "
                        "docs/tacticalapi-implementation.md §6 states that cost); the "
                        "conformance suite's parser worker kills a "
                        "decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The contract states no maximum message size. 4 MiB plus 1 KiB "
                            "(`MAX_INPUT_BYTES`, `adapters/tacticalapi_codec.py`) "
                            "is chosen on 2026-10-04: 4 MiB is the default ceiling on a "
                            "received message in the common gRPC implementations, so a larger "
                            "response does not reach a default-configured client, and the KiB "
                            "is for the Any envelope around the response. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused with "
                            "`InputTooLarge` before any decoder of this package runs; "
                            "`tacticalapi_codec.decode` reads the same bound off the octets "
                            "again and refuses `input-too-large` for a direct caller"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The contract's closure has no recursive message and an unknown "
                            "wire field is carried as octets, so the bytes form's twin nests at "
                            "most 7 containers; the dict form's unknown keys carry arbitrary "
                            "JSON. 64 (`MAX_DEPTH`, `adapters/tacticalapi_codec.py`) is the "
                            "harness loader's own bound and the "
                            "figure the JSON-reading adapters of synapse_cdm declare, counted "
                            "in containers as `adapter.container_depth` counts them. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "a dict is measured by the base class: `Adapter.__init_subclass__`'s "
                            "wrapper calls `adapter.enforce_depth_bound` before this class's "
                            "`to_cdm` runs and refuses with `InputTooDeep`; "
                            "`tacticalapi_codec.validate_twin` counts the same containers and "
                            "refuses `nesting-too-deep`, and `tacticalapi_codec.decode` refuses "
                            "a bytes-form twin on the object that would cross the bound, before "
                            "it is built"),
                        test="tests/test_cdm_tacticalapi_adapter.py::test_max_depth_admits_the_bound_and_refuses_one_past",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The contract states no maximum number of blue forces in one "
                            "response. 10 000 elements of `blue_forces` or "
                            "`updated_blue_forces` (`MAX_OBJECTS`, "
                            "`adapters/tacticalapi_codec.py`), each becoming an Entity and an "
                            "Event, so 20 000 CDM objects — the figure both in-tree AIXM "
                            "adapters bound one message to. Two caps the manifest schema has no "
                            "field for are declared beside it: `MAX_UNKNOWN_FIELDS` (65 536), the "
                            "unknown fields carried for one input in either form, counting a "
                            "message- or header-level field once for every Entity and once for "
                            "every Event that carries it; and `MAX_CARRIED_COPY_CHARS` "
                            "(16 777 216), the characters of compact JSON text, with ASCII "
                            "escaping, that the message-level data every Entity and every Event "
                            "carries (the typed block's message member, on the Entity, and the "
                            "message- and header-level unknown fields, in both places each object "
                            "holds them) adds to all the objects of one message: four times the "
                            "4 MiB message ceiling `max_input_bytes` rests on. A dict-form integer "
                            "outside the 64-bit range is refused, so no number is longer than "
                            "twenty digits. This is an IMPLEMENTATION CAP and is NOT the "
                            "format's normative maximum."),
                        enforced_at=(
                            "`tacticalapi_codec` counts the elements on the wire, or the list's "
                            "length in the dict form, before any element is decoded and refuses "
                            "`too-many-objects`; it counts unknown fields as it carries them and "
                            "refuses `too-many-unknown-fields`, and `TacticalapiAdapter.to_cdm` "
                            "counts the carried copies, refusing with the same code, then "
                            "measures the carried message-level data once and refuses "
                            "`carried-copies-too-large`, all before any object is built"),
                        test="tests/test_cdm_tacticalapi_adapter.py::test_max_objects_admits_the_bound_and_refuses_one_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "a protobuf field number the pinned contract does not name, at any level but "
                "inside the four well-known types (where it is refused), is carried with its "
                "number, wire type and raw octets, and a dict-form key the contract does not name "
                "is carried with its value; both sit in the structured residual of every Entity "
                "they concern, at their own path under `residual.data.response` or "
                "`residual.data.blue_force`, and are listed under `residual.data.unknown` with "
                "the path of the message that held them, and every Event carries the message- "
                "and header-level ones the same way; `validate_source` names each one. An "
                "enum number the contract does not name is kept as the number"),
        ),
        limitations=[
            Limitation(
                id="blue-force-read-side-only",
                summary="reads the two read-side responses of the BlueForceTracking service, "
                        "GetBlueForcesResponse and SubscribeBlueForceEventsResponse, and nothing "
                        "else: every other message of the contract (own pose, situation objects, "
                        "every request, the write-side blue-force messages) and every type "
                        "outside it is refused `unsupported-message-type`, naming the two. Ingest "
                        "only; no encoder exists",
            ),
            Limitation(
                id="capture-envelope",
                summary="the unit of ingest is one response wrapped in google.protobuf.Any "
                        "(bytes) or its twin (dict), because a serialized message does not name "
                        "its own type. gRPC framing, calls, sessions, stream bookkeeping and "
                        "keep-alive timing are not read and not held: the caller receives each "
                        "message and hands it over, and a stream is a sequence of calls",
            ),
            Limitation(
                id="pinned-commit-v0",
                summary="written against rheinmetall.tactical_api.v0 at upstream commit 58661c9 "
                        "(2026-09-01), which has no tag or release; the embedded field table is "
                        "generated from protoc's descriptor of those pinned files. A field a "
                        "later revision adds is carried as an unknown field; a new upstream "
                        "commit is a new pin and a new adapter version, never a silent update",
            ),
            Limitation(
                id="coordinate-unit-not-stated",
                summary="the contract places the point on the WGS 84 ellipsoid and states no "
                        "angular unit for latitude_coordinate and longitude_coordinate; they are "
                        "read as decimal degrees, inferred from every other angle in the "
                        "contract, not stated by it",
            ),
            Limitation(
                id="course-reference-not-stated",
                summary="point_location.course is in degrees with no stated north reference, and "
                        "`Kinematics.course_deg` means degrees true: a course in [0, 360) is "
                        "mapped to `course_deg` with the north reference ASSUMED true, an "
                        "assumption `course_basis` states on every Entity it is applied to (R5, "
                        "ruled 2026-10-06). A course outside that range, 360 included, is not "
                        "mapped and not normalised; it stays in the typed block and "
                        "`validate_source` names it",
            ),
            Limitation(
                id="symbol-2525d-only",
                summary="`Entity.symbol` is set only from a MIL-STD-2525D numeric code (catalog "
                        "SYMBOL_CATALOG_MIL2525_D, first set 1 000 000 000 to 9 999 999 999, "
                        "second set 0 to 9 999 999 999), unrewritten. Every other symbol — "
                        "another catalog, the string form, a set out of range — is carried in "
                        "the typed block unconverted and named by `validate_source`; no symbol "
                        "is derived from the affiliation (R4, ruled 2026-10-06)",
            ),
            Limitation(
                id="proto3-zero-indistinguishable",
                summary="proto3 writes no scalar holding its default, so an unset coordinate "
                        "pair and 0°N 0°E are the same bytes and a false bool reads as an unset "
                        "one. A geo_point with neither coordinate on the wire yields no position, "
                        "one with a single coordinate on the wire reads the other as 0.0 and "
                        "`position_basis` says so, and `blue_force_type` flags that are not true "
                        "give `entity_type` UNKNOWN, never a person or a unit. Likewise a "
                        "Timestamp holding seconds 0 and nanos 0 (1970-01-01T00:00:00Z) is what "
                        "a default-constructed one serialises to, so neither "
                        "point_location.location_time nor last_contact_time holding it is read "
                        "as a source time: the next choice stands, the basis says the zero "
                        "Timestamp was passed over, `validate_source` names it, and its text "
                        "stays in the typed block",
            ),
            Limitation(
                id="non-canonical-encoding-refused",
                summary="encodings a lenient protobuf parser accepts and repairs are refused by "
                        "name: a singular field twice, two members of one oneof, a named field "
                        "with another wire type, an int32 or enum varint outside 32 bits, a bool "
                        "other than 0 or 1, a varint whose tenth octet sets bits past the 64th, "
                        "a tag written in more than five octets, and a field the well-known "
                        "types Any, Timestamp, StringValue and DoubleValue do not define. "
                        "Nothing is repaired",
            ),
            Limitation(
                id="source-time-optional",
                summary="the read side marks no time field mandatory: `valid_from` and "
                        "`observed_at` come from point_location.location_time, else "
                        "last_contact_time, else the receipt instant from the injected clock, "
                        "a zero Timestamp being passed over (proto3-zero-indistinguishable), "
                        "and `valid_from_basis` and `observed_at_basis` say which. The CDM "
                        "renders instants to the millisecond; the source text stays whole in "
                        "the typed block. A deleted element gets no `valid_to`: the contract "
                        "says only that the blue force is no longer present (R6, ruled "
                        "2026-10-06)",
            ),
            Limitation(
                id="no-endpoint-exercised",
                summary="no TacticalAPI server, client or captured message has been exercised. "
                        "Every payload is synthetic, and every one starts as protoc's own "
                        "encoding of a text source against the pinned files; none was written "
                        "from scratch by hand. Fourteen are protoc's bytes unchanged. Seven were "
                        "changed afterwards by the fixture builder: three have hand-encoded "
                        "fields appended, and four refusal payloads are protoc's bytes after one "
                        "byte surgery each. protoc's own readings of the payloads are the only "
                        "independent oracle",
            ),
            Limitation(
                id="evidence-availability",
                summary="`evidence.available` is false because no published Release carries "
                        "this adapter's records yet; it becomes true at the first release that "
                        "attaches them",
            ),
            Limitation(
                id="resource-limits",
                summary="of the five resource limits this adapter enforces three — "
                        "`max_input_bytes`, `max_depth` and `max_objects`, each an "
                        "implementation cap declared with its basis and refused before any "
                        "object is built — plus two the manifest has no field for, declared "
                        "beside `max_objects`: `MAX_UNKNOWN_FIELDS` (65 536 carried unknown "
                        "fields per input) and `MAX_CARRIED_COPY_CHARS` (16 777 216 characters "
                        "of compact JSON text, with ASCII escaping, of the message-level data "
                        "carried across all the Entities and Events of one message, each copy "
                        "counted). "
                        "`max_decompressed_bytes` and `max_parse_seconds` are absent, each with "
                        "its reason in `capabilities.limits.absent_because`",
            ),
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    #: Nothing a source states changes value in translation: every known leaf is carried verbatim
    #: in the typed block and every unknown one in the residual, so no path is exempted from the
    #: value-presence heuristic. The canonical fields are projections, held by `MAPPINGS`.
    TRANSFORMS: dict[str, str] = {}

    MAPPINGS = _build_mappings()

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 affiliation: Affiliation | None = None) -> None:
        """`affiliation` is the caller's context (R3, ruled 2026-10-06; the record §5.4): `None`,
        the default, gives every Entity `UNKNOWN`, since the message states no affiliation; one
        of the four `Affiliation` members gives every Entity that member, with a basis saying the
        caller supplied it, as `c2sim`'s `own_side` is context its caller supplies. Anything
        else, a text that spells a member included, is refused here with a `ValueError` whose
        text begins `invalid-affiliation`: nothing is converted, and a construction refusal is
        not a refusal of an input. The type is read from the value itself, `type(affiliation)`,
        as the codec reads every type (item 37). `fixture_instance` is not overridden, so the
        packaged fixtures are replayed with no caller affiliation."""
        super().__init__(clock, synthetic=synthetic)
        if affiliation is not None and type(affiliation) is not Affiliation:
            raise ValueError(
                f"{INVALID_AFFILIATION}: the affiliation a caller supplies is one of the four "
                f"Affiliation members ({', '.join(member.name for member in Affiliation)}) or "
                f"None, and {codec.quote(affiliation)}, of type {codec.quote_type(affiliation)}, "
                "is neither; a text that spells a member is not the member, and nothing is "
                "converted")
        self._affiliation = affiliation

    def _affiliation_of_every_entity(self) -> tuple[Affiliation, str]:
        """(affiliation, affiliation_basis), the same for every Entity this instance emits."""
        if self._affiliation is None:
            return Affiliation.UNKNOWN, AFFILIATION_BASIS
        return self._affiliation, SUPPLIED_AFFILIATION_BASIS.format(member=self._affiliation.name)

    # ------------------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One response -> an Entity and an Event per blue force, in list order. A successful
        response with no blue force, nothing unknown and no error_message text is `[]`."""
        return self._translate(codec.twin_of(raw))

    def _translate(self, twin: dict) -> list[CDMBase]:
        type_name = codec.type_name_of(twin["@type"])
        list_name = ELEMENT_LIST[type_name]
        _require_success(twin)
        elements = twin.get(list_name, [])
        unknown = codec.unknown_fields(twin)
        if not elements:
            _require_a_carrier(twin, unknown)
            return []
        message_level, by_element = _split_unknown(unknown, list_name, len(elements))
        response_residual = codec.unknown_only(twin, type_name)
        _bound_carried_copies(codec.message_block(twin, list_name, 0), response_residual,
                              message_level, len(elements))
        received = self.now()
        source = self.source_ref()
        out: list[CDMBase] = []
        for index, element in enumerate(elements):
            out.extend(self._element(twin, list_name, index, element, message_level,
                                     by_element[index], response_residual, received, source))
        return out

    def _element(self, twin: dict, list_name: str, index: int, element: dict,
                 message_level: list, own_unknown: list, response_residual: dict,
                 received: dt.datetime, source: SourceRef) -> list[CDMBase]:
        where = f"{list_name}[{index}]"
        external_id, id_basis = _identity(element, where)
        entity_id = ids.derive(SYSTEM, external_id, kind="entity")
        point = element.get("point_location", {})
        instant, time_basis = _time(element, point, received, where)
        position, position_basis, source_basis = _position(element, where)
        kinematics, course_basis = _kinematics(point, where)
        symbol, symbol_basis = _symbol(element.get("symbol"))
        entity_type, type_basis = _entity_type(element.get("blue_force_type"))
        deleted = element.get("is_deleted") is True
        event_id, event_id_basis = _event_id(external_id, instant, deleted)
        affiliation, affiliation_basis = self._affiliation_of_every_entity()

        attributes: dict[str, Any] = {
            "tacticalapi": codec.typed_block(twin, list_name, index),
            "entity_id_basis": id_basis,
            "valid_from_basis": time_basis,
            "affiliation_basis": affiliation_basis,
            "entity_type_basis": type_basis,
            "symbol_basis": symbol_basis,
            "position_basis": position_basis,
        }
        if source_basis is not None:
            attributes["position_source_basis"] = source_basis
        if course_basis is not None:
            attributes["course_basis"] = course_basis
        source_ids = [{"system": SYSTEM, "external_id": external_id}]
        entity = Entity(
            source=_stamp(source, index),
            source_ids=source_ids,
            entity_id=entity_id,
            entity_type=entity_type,
            affiliation=affiliation,
            symbol=symbol,
            position=position,
            kinematics=kinematics,
            attributes=attributes,
            valid_from=instant,
            # The record §5.7: the state token is the source's own field name, and `since` is
            # None because the contract does not say when the blue force ceased to be present.
            status=(OperationalStatus(state="is_deleted", namespace=SYSTEM, since=None)
                    if deleted else None),
            residual=self._residual(element, message_level + own_unknown, response_residual),
        )
        event = Event(
            source=_stamp(source, index),
            source_ids=source_ids,
            event_id=event_id,
            event_type=EventType.STATUS_CHANGE if deleted else EventType.TRACK_UPDATE,
            severity=Severity.INFO,
            related_entities=[entity_id],
            geometry=({"type": "Point", "coordinates": [position.lon, position.lat]}
                      if position is not None else None),
            payload={
                "contract": codec.TYPED_BLOCK_CONTRACT,
                "observed_at_basis": time_basis,
                "event_id_basis": event_id_basis,
                "severity_basis": SEVERITY_BASIS,
            },
            observed_at=instant,
            received_at=received,
            residual=self._residual(None, message_level, response_residual),
        )
        return [entity, event]

    def _residual(self, element: dict | None, carried: list,
                  response_residual: dict) -> ResidualBlock:
        """The record §5.9: the residual every Entity and every Event carries, whose `data` is
        never empty. `unknown` is always present: every unknown field the object carries, with
        the path of the message that held it — message and header level first, then the
        element's, each in twin order — and `[]` when it carries none. The message's and the
        header's unknown fields sit at their own paths under `response`, and an Entity's
        element's under `blue_force`, each key present only when it holds something.

        `element` is the Entity's element; for its Event it is None and `carried` is the
        message-level entries alone, so the Event carries the message-level part of its Entity's
        residual and nothing of the element's (changed 2026-10-06, the landing: until then an
        object with nothing unknown carried `None`, and an Event always did, which the host's
        lossless sweep refuses for a `structured` adapter).

        Every container is this object's own copy (`_owned`): the message-level part is the same
        for every Entity and Event of the message and an unknown key's value sits both at its
        path and in `unknown`, and a shared container would let a change to one place appear in
        another."""
        data: dict[str, Any] = {}
        if response_residual:
            data["response"] = _owned(response_residual)
        own = {} if element is None else codec.unknown_only(element, BLUE_FORCE)
        if own:
            data["blue_force"] = _owned(own)
        data["unknown"] = [_owned(entry) for entry in carried]
        return ResidualBlock(namespace=self.metadata.format.name, data=data)

    # ---------------------------------------------------------------------------- v2 surface

    def detect(self, raw: bytes | dict) -> bool | None:
        """The cheap structural test: the envelope's type names one of the two supported types.
        Bytes are read as far as the envelope; a dict's `@type` is read and nothing else, found
        and read by `codec.twin_type_url` exactly as `to_cdm` finds and reads it (the one
        top-level key whose text is `@type`; changed 2026-10-04, final verification: a lookup by
        `raw.get` missed a `str` subclass key that `to_cdm` translates). Any other input is
        neither form, so the answer is "cannot tell". The form is read from the input's own
        type, as the codec reads every type, never from a `__class__` that may name another
        (item 37)."""
        kind = type(raw)
        if issubclass(kind, (bytes, bytearray, memoryview)):
            try:
                codec.type_name_of(codec.envelope_type_url(raw))
            except TacticalapiRefused:
                return False
            return True
        if issubclass(kind, dict):
            try:
                codec.type_name_of(codec.twin_type_url(raw))
            except TacticalapiRefused:
                return False
            return True
        return None

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """The refusal, when there is one. Otherwise what the adapter accepts and a reader
        should know (the record §6): each unknown field, each symbol not promoted and why, a
        promoted symbol whose standard-identity digit is not the friend digit, a symbol string
        whose length is not 15 under the two catalogs the contract states that length for, each
        zero Timestamp passed over, each Timestamp less than a millisecond after the epoch (used
        as stated, and rendered as the epoch's text; added 2026-10-04, final verification) and
        each at 0001-01-01T00:00:00Z, each element with no source time left, and each course
        outside [0, 360), which is not mapped (R5, ruled 2026-10-06). Nothing listed is
        refused.

        Every line is printable and bounded as a refusal is: an unknown key, the one text of the
        input a line names, goes through `tacticalapi_codec.quote` (changed 2026-10-04, final
        verification; it was written whole, so a key of a mebibyte made a line of a mebibyte).
        A refusal's text, this adapter's or the base class's, is bounded where it is written and
        is written whole; the text of any other exception (the host's own, on an input only an
        in-process caller builds) goes through `tacticalapi_codec.quote_error` (item 37)."""
        try:
            self.to_cdm(raw)
            twin = codec.twin_of(raw)
        except REFUSALS as refusal:
            return [f"{codec.quote_type(refusal)}: {refusal}"]
        except Exception as problem:                     # noqa: BLE001 - reported, not raised
            return [f"{codec.quote_type(problem)}: {codec.quote_error(problem)}"]
        problems: list[str] = []
        for entry in codec.unknown_fields(twin):
            where = entry["path"] or "the response"
            if "key" in entry:
                problems.append(f"{where}: key {codec.quote(entry['key'])} is not a field the "
                                "pinned contract names; carried in the residual")
            else:
                problems.append(f"{where}: field number {entry['number']} (wire type "
                                f"{entry['wire_type']}) is not in the pinned contract; carried "
                                "in the residual")
        list_name = ELEMENT_LIST[codec.type_name_of(twin["@type"])]
        for index, element in enumerate(twin.get(list_name, [])):
            where = f"{list_name}[{index}]"
            symbol = element.get("symbol")
            if symbol is not None:
                code, basis = _symbol(symbol)
                if code is None:
                    problems.append(f"{where}.symbol: {basis}")
                elif code[IDENTITY_DIGIT] != FRIEND_DIGIT:
                    # A source-consistency observation against the service's own definition,
                    # not against Entity.affiliation, which is never read from a symbol nor,
                    # when the caller supplies it, compared with one (R3, ruled 2026-10-06).
                    problems.append(f"{where}.symbol: the 2525D code's standard-identity digit "
                                    f"is {code[IDENTITY_DIGIT]!r}, not the friend digit "
                                    f"{FRIEND_DIGIT!r}, while the service's own definition names "
                                    "the members of this list blue forces; the symbol is "
                                    "carried unchanged, and Entity.affiliation is neither read "
                                    "from it nor compared with it")
                text = symbol.get("string_identifier")
                if text is not None and symbol.get("symbol_catalog") in SYMBOL_STRING_CATALOGS \
                        and len(text) != SYMBOL_STRING_LENGTH:
                    problems.append(f"{where}.symbol.string_identifier is {len(text)} "
                                    f"characters; the contract's string form is "
                                    f"{SYMBOL_STRING_LENGTH} (reported, not enforced)")
            stated = _source_times(element, element.get("point_location", {}), where)
            for field, seconds, nanos in stated:
                if (seconds, nanos) == (0, 0):
                    problems.append(f"{where}.{field} {ZERO_PASSED_OVER}")
                elif seconds == 0 and nanos < NANOS_PER_MILLISECOND:
                    text = codec.render_timestamp(seconds, nanos, f"{where}.{field}")
                    problems.append(f"{where}.{field} is {text}, {BELOW_A_MILLISECOND}")
                elif (seconds, nanos) == (codec.TIMESTAMP_MIN_SECONDS, 0):
                    problems.append(f"{where}.{field} is 0001-01-01T00:00:00Z, the earliest "
                                    "instant a Timestamp holds, which some platforms write for a "
                                    "time never set; it is read as the instant stated")
            if not stated:
                problems.append(f"{where}: states no source time; valid_from and observed_at "
                                "are the receipt instant from the injected clock")
            elif all((seconds, nanos) == (0, 0) for _, seconds, nanos in stated):
                problems.append(f"{where}: states no source time but the zero Timestamp; "
                                "valid_from and observed_at are the receipt instant from the "
                                "injected clock")
            course = element.get("point_location", {}).get("course")
            if course is not None and not _course_in_range(course):
                problems.append(f"{where}.point_location.course is {codec.quote(course)}, "
                                f"{COURSE_OUT_OF_RANGE}")
        return problems


# ------------------------------------------------------------------------------ the rules


def _require_success(twin: dict) -> None:
    """The record §4: `header.success` must be true. Absent from the wire is false — proto3
    writes no false — so an absent header or an absent `success` is refused like a false one,
    quoting `error_message` when the header states one."""
    header = twin.get("header")
    if header is None:
        raise _refuse("response-not-successful", "the response has no header, so it states no "
                      "success; only a response whose header.success is true is translated")
    if header.get("success") is True:
        return
    said = ("header.success is false" if "success" in header
            else "header.success is absent from the wire, which reads false")
    if "error_message" in header:
        said += f"; header.error_message: {codec.quote(header['error_message'])}"
    raise _refuse("response-not-successful", f"{said}; only a response whose header.success "
                  "is true is translated")


def _require_a_carrier(twin: dict, unknown: list[dict]) -> None:
    """The record §4, a successful response with no blue force: what the message holds beyond
    its success needs an object to be carried on, and there is none. An unknown field is refused
    first, then a header error_message of one or more characters, which is the header's own text
    and would otherwise be dropped without a word (added 2026-10-04, final verification). An
    error_message present and empty holds no text, so such a response is `[]` like any other
    successful empty snapshot."""
    if unknown:
        raise _refuse("unknown-fields-without-carrier", f"the response carries {len(unknown)} "
                      "unknown field(s) and no blue force, so no object exists to carry them; "
                      "refused rather than dropped")
    said = twin["header"].get("error_message", "")
    if said:
        raise _refuse("error-message-without-carrier", f"the response is successful, carries no "
                      f"blue force, and its header.error_message is {codec.quote(said)}; no "
                      "object exists to carry it, so it is refused rather than dropped")


def _bound_carried_copies(message: dict, response_residual: dict, message_level: list[dict],
                          count: int) -> None:
    """The record §4 and §6: the data every element of the message brings with it — on its
    Entity, the typed block's `message` member and the message- and header-level unknown fields
    at their paths under `residual.data.response` and as entries of `residual.data.unknown`; on
    its Event, those unknown fields again in the same two places (the record §5.9, since
    2026-10-06) — measured with `codec.carried_size` (compact JSON text with ASCII escaping),
    every copy an Entity or an Event holds counted, and held for all the objects together to
    `MAX_CARRIED_COPY_CHARS`. Refused before any object is built; the count of carried unknown
    fields has already been held by `_split_unknown`. The response residual is measured only when
    the objects carry it, which is when it is not empty.

    Measured once and multiplied: the text is written for the first element's data alone, never
    per element. Only the `message` member's index differs from one Entity to the next, so the
    first Entity's index (`0`, one character) is taken out and the indices' own digits are added
    for all of them (`_index_digits`): the total is the characters the objects really carry."""
    unknown = sum(codec.carried_size(entry) for entry in message_level)
    if response_residual:
        unknown += codec.carried_size(response_residual)
    size = codec.carried_size(message) + 2 * unknown
    total = (size - len(str(message["index"]))) * count + _index_digits(count)
    if total > codec.MAX_CARRIED_COPY_CHARS:
        raise _refuse("carried-copies-too-large", f"the message-level data the first entity and "
                      f"its event carry measures {size}, and the {count} entities and {count} "
                      f"events of the message would carry {total}; at most "
                      f"{codec.MAX_CARRIED_COPY_CHARS} are carried for one message "
                      "(MAX_CARRIED_COPY_CHARS)")


def _index_digits(count: int) -> int:
    """The characters of the indices 0 … count − 1 written in decimal, added up a decade at a
    time rather than written out: ten one-digit indices, ninety two-digit ones, and so on."""
    total, width, low = 0, 1, 0
    while low < count:
        high = min(count, 10 ** width)
        total += width * (high - low)
        low, width = high, width + 1
    return total


def _stamp(source: SourceRef, index: int) -> SourceRef:
    """The provenance stamp of one object: the message's stamp with the element's index, as a
    new `SourceRef` with a new transformation list, so that each Entity and each Event owns its
    own (equal values, separate objects; added 2026-10-04, final verification). A shallow
    `model_copy` alone would leave every object of the message holding one list."""
    return source.model_copy(update={"record_index": index,
                                     "transformations": list(source.transformations)})


def _owned(value: Any) -> Any:
    """A JSON value with every dict and list copied, so the Entity that holds it is the only
    holder of its containers. Strings and numbers are shared: they cannot change. The twin's
    depth is bounded by `max_depth` before anything reaches here, which bounds the recursion."""
    if isinstance(value, dict):
        return {key: _owned(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_owned(item) for item in value]
    return value


def _split_unknown(unknown: list[dict], list_name: str,
                   count: int) -> tuple[list[dict], list[list[dict]]]:
    """The message's unknown fields (response and header level) and each element's, and the
    count the record §3.3 bounds: a message- or header-level field is carried on every Entity and
    on every Event (the record §5.9, since 2026-10-06), so it counts twice per element; an
    element's own field is carried on its Entity alone and counts once. Refused before any
    object is built."""
    message_level: list[dict] = []
    by_element: list[list[dict]] = [[] for _ in range(count)]
    prefix = f"{list_name}["
    for entry in unknown:
        path = entry["path"]
        if path.startswith(prefix):
            by_element[int(path[len(prefix):path.index("]")])].append(entry)
        else:
            message_level.append(entry)
    shared = 2 * len(message_level) * count
    carried = shared + sum(len(own) for own in by_element)
    if carried > codec.MAX_UNKNOWN_FIELDS:
        raise _refuse("too-many-unknown-fields", f"{len(message_level)} message- or header-level "
                      f"unknown field(s) carried on each of {count} entities and {count} events "
                      f"and {carried - shared} element-level ones make {carried} carried unknown "
                      f"fields; at most {codec.MAX_UNKNOWN_FIELDS} are carried for one input")
    return message_level, by_element


def _identity(element: dict, where: str) -> tuple[str, str]:
    """The record §5.2: `<member>:<value>`, the member's name kept so that the text `7` and the
    integer `7` stay two identities."""
    identity = element.get("identity")
    if identity is None:
        raise _refuse("blue-force-without-identity", f"{where} has no identity, so the entity "
                      "cannot be keyed")
    member = next((field.name for field in codec.MESSAGES[IDENTITY].values()
                   if field.name in identity), None)
    if member is None:
        raise _refuse("blue-force-without-identity", f"{where}.identity sets no member of its "
                      "oneof, so the entity cannot be keyed")
    value = identity[member]
    if value == "":
        raise _refuse("empty-identity", f"{where}.identity.{member} is the empty string")
    return (f"{member}:{value}",
            f"identity.{member}: the blue force's own identity, keyed as <member>:<value> so "
            "two members holding one value stay two identities")


def _source_times(element: dict, point: dict, where: str) -> list[tuple[str, int, int]]:
    """The element's source times in the record §5.3's order of preference, as (field, seconds,
    nanos), each read with the codec's own parser so the nanoseconds are read the same on every
    interpreter; a time absent from the element is left out."""
    stated = []
    for field, text in (("point_location.location_time", point.get("location_time")),
                        ("last_contact_time", element.get("last_contact_time"))):
        if text is not None:
            stated.append((field, *codec.parse_timestamp(text, f"{where}.{field}")))
    return stated


def _time(element: dict, point: dict, received: dt.datetime,
          where: str) -> tuple[dt.datetime, str]:
    """The record §5.3: the location time, else the last contact time, else the receipt
    instant — for live and deleted elements alike. A Timestamp holding seconds 0 and nanos 0 is
    passed over as an absent one is (added 2026-10-04, final verification): it is what a
    default-constructed Timestamp serialises to, and the CDM forbids an unknown time becoming
    1970-01-01. The basis names each time passed over and why. The CDM keeps microseconds and
    renders milliseconds, truncating; the text stays whole in the typed block. A Timestamp of
    seconds 0 and nanos 1 … 999 999 is not passed over: it is a stated value, which proto3 does
    not write for one never set, and inferring that it is unset would be a repair; it renders as
    the epoch's text, and `validate_source` says so (stated 2026-10-04, final verification)."""
    location = "point_location.location_time"
    said = {location: "is absent", "last_contact_time": "is absent"}
    for field, seconds, nanos in _source_times(element, point, where):
        if (seconds, nanos) == (0, 0):
            said[field] = ZERO_PASSED_OVER
            continue
        instant = (dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)
                   + dt.timedelta(seconds=seconds, microseconds=nanos // 1000))
        if field == location:
            return instant, location
        return instant, f"last_contact_time: {location} {said[location]}"
    if said[location] == said["last_contact_time"] == "is absent":
        return received, NO_TIME_BASIS
    return received, (f"the receipt instant: {location} {said[location]}, and last_contact_time "
                      f"{said['last_contact_time']}, so the injected clock stands in")


def _event_id(external_id: str, instant: dt.datetime, deleted: bool) -> tuple[uuid.UUID, str]:
    """The record §5.8: (event_id, event_id_basis). The id input is `<external_id>@<instant>`,
    the instant written by `_id_instant`; a deleted element's input ends `#is_deleted`, so the
    deletion of a blue force and its last live report at the same instant are two reports with
    two ids (changed 2026-10-04, final verification). A live input ends in the instant's `Z`, so
    no live input can equal a deleted one. The id never depends on the element's place in the
    message: two elements with one identity and one instant share one id (§4, §5.8)."""
    member = external_id.split(":", 1)[0]
    if deleted:
        return (ids.derive(SYSTEM, f"{external_id}@{_id_instant(instant)}{DELETED_SUFFIX}",
                           kind="event"),
                f"identity.{member} + observed_at as rendered + {DELETED_SUFFIX}: the deletion "
                "report of one blue force at one instant, kept apart from a live report at that "
                "instant")
    return (ids.derive(SYSTEM, f"{external_id}@{_id_instant(instant)}", kind="event"),
            f"identity.{member} + observed_at as rendered: one report of one blue force at one "
            "instant")


def _id_instant(instant: dt.datetime) -> str:
    """The instant in the event id input, written here rather than by `times.render`: UTC, to
    the millisecond (truncated), `Z`, and a year of four digits, zero-padded. Before synapse-cdm
    3.2.0, `times.render` wrote the year with `strftime('%Y')`, which glibc under CPython 3.11
    and 3.12 writes unpadded below the year 1000, so an id taken from it would have differed by
    platform. Since 3.2.0 the host writes four digits itself and the two texts are equal for
    every year; the id keeps its own writer so that it depends on no host version (added
    2026-10-04, final verification; host change noted 2026-10-06)."""
    stamp = times.parse(instant)
    return (f"{stamp.year:04d}-{stamp.month:02d}-{stamp.day:02d}T{stamp.hour:02d}:"
            f"{stamp.minute:02d}:{stamp.second:02d}.{stamp.microsecond // 1000:03d}Z")


def _enum_number(value: Any, enum: str) -> int:
    """A twin enum value as its number: a name through the contract's table, a number the
    contract does not name as itself, and absent as 0, proto3's default."""
    if value is None:
        return 0
    if isinstance(value, str):
        return codec.ENUM_NUMBERS[enum][value]
    return value


def _stated(value: Any, enum: str) -> str:
    """How a basis quotes an enum value: its name and number, or the bare number."""
    number = _enum_number(value, enum)
    name = codec.ENUMS[enum].get(number)
    return f"{name} ({number})" if name else f"{number}, a number the contract does not name"


def _position(element: dict, where: str) -> tuple[Position | None, str, str | None]:
    """The record §5.5: (position, position_basis, position_source_basis or None)."""
    if "point_location" not in element:
        return None, "no position: the element has no point_location", None
    if "geo_point" not in element["point_location"]:
        return None, "no position: point_location has no geo_point", None
    geo = element["point_location"]["geo_point"]
    has_lat = "latitude_coordinate" in geo
    has_lon = "longitude_coordinate" in geo
    if not (has_lat or has_lon):
        said = ("no position: point_location.geo_point carries neither latitude_coordinate nor "
                "longitude_coordinate on the wire; under proto3 an unset pair and 0°N 0°E are "
                "the same bytes, and the CDM forbids a zero position standing for unknown "
                "(limitation proto3-zero-indistinguishable)")
        return None, said, None
    lat = geo.get("latitude_coordinate", 0.0)
    lon = geo.get("longitude_coordinate", 0.0)
    if not -90.0 <= lat <= 90.0:
        raise _refuse("coordinate-out-of-range", f"{where}.point_location.geo_point."
                      f"latitude_coordinate is {codec.quote(lat)}; a latitude is -90 … 90")
    if not -180.0 <= lon <= 180.0:
        raise _refuse("coordinate-out-of-range", f"{where}.point_location.geo_point."
                      f"longitude_coordinate is {codec.quote(lon)}; a longitude is -180 … 180")
    basis = ("point_location.geo_point latitude_coordinate and longitude_coordinate, read as "
             "WGS 84 decimal degrees: the contract states the ellipsoid and no angular unit "
             "(limitation coordinate-unit-not-stated)")
    for name, present in (("latitude_coordinate", has_lat), ("longitude_coordinate", has_lon)):
        if not present:
            basis += (f"; {name} is absent from the wire and reads 0.0, proto3's default "
                      "(limitation proto3-zero-indistinguishable)")

    vertical, alt_m = None, None
    if "vertical_distance" in geo:
        code = _enum_number(geo.get("vertical_distance_reference_code"), VERTICAL_CODES)
        value = geo["vertical_distance"]
        vertical = VerticalPosition(value=value, unit=VerticalUnit.METRES,
                                    reference=VERTICAL_REFERENCE.get(code,
                                                                     VerticalReference.UNKNOWN))
        alt_m = value if code == HAE_CODE else None

    stated = geo.get("measurement_code")
    code = _enum_number(stated, MEASUREMENT_CODES)
    source = POSITION_SOURCE.get(code, PositionSource.ESTIMATED)
    if stated is None:
        source_basis = (f"{source.value}: geo_point.measurement_code is absent from the wire and "
                        "reads 0 (MEASUREMENT_CODE_UNSPECIFIED)")
    else:
        source_basis = (f"{source.value}: geo_point.measurement_code "
                        f"{_stated(stated, MEASUREMENT_CODES)}")
    if code not in POSITION_SOURCE:
        source_basis += ("; position_source is required and none of its four members means "
                         "unknown or laser-ranged, so the understating ESTIMATED stands and the "
                         "code stays in the typed block")
    position = Position(lat=lat, lon=lon, alt_m=alt_m, position_source=source,
                        vertical=vertical)
    return position, basis, source_basis


def _course_in_range(course: float) -> bool:
    """The record §5.6: a course `Kinematics.course_deg` can hold, [0, 360). -0.0 compares equal
    to 0 and is in range; 360, a negative and anything past 360 are not."""
    return COURSE_RANGE[0] <= course < COURSE_RANGE[1]


def _kinematics(point: dict, where: str) -> tuple[Kinematics | None, str | None]:
    """The record §5.6: (kinematics, course_basis or None). Speed as stated, in metres per second;
    absent is unknown, never zero. Course (R5, ruled 2026-10-06) as stated, in degrees, read as
    degrees true with the north reference ASSUMED, when it is in [0, 360); any other course is
    not mapped and not normalised, and its basis says why. `kinematics` exists when the speed or
    a mapped course is present: a point that states only a course outside the range has none.
    `course_basis` is written whenever the point states a course, mapped or not."""
    speed = point.get("speed")
    if speed is not None and speed < 0:
        raise _refuse("negative-speed", f"{where}.point_location.speed is {codec.quote(speed)}; "
                      "a speed is not negative")
    course, course_basis = point.get("course"), None
    if course is not None:
        if _course_in_range(course):
            course_basis = COURSE_ASSUMED_TRUE
        else:
            course_basis = (f"point_location.course is {codec.quote(course)}, "
                            f"{COURSE_OUT_OF_RANGE}; validate_source names it (R5, ruled "
                            "2026-10-06)")
            course = None
    if speed is None and course is None:
        return None, course_basis
    return Kinematics(speed_mps=speed, course_deg=course), course_basis


def _symbol(symbol: dict | None) -> tuple[str | None, str]:
    """The record §5.4: (Entity.symbol or None, symbol_basis). Only a 2525D numeric code is
    promoted, as its two sets written out; nothing is converted and nothing derived."""
    if symbol is None:
        return None, ("no symbol: the element states none, and none is derived from the "
                      "affiliation (R4, ruled 2026-10-06)")
    catalog = symbol.get("symbol_catalog")
    if catalog is None:
        said = "symbol_catalog is absent from the wire and reads SYMBOL_CATALOG_UNSPECIFIED"
    else:
        said = f"symbol_catalog {catalog}"
    if catalog != SYMBOL_CATALOG_2525D:
        return None, (f"not promoted: {said}; only a {SYMBOL_CATALOG_2525D} numeric code becomes "
                      "Entity.symbol, no converter exists for another catalog and none is "
                      "written, and the symbol stays in the typed block")
    if "numeric_identifier" not in symbol and "string_identifier" in symbol:
        return None, (f"not promoted: {said} in the string form; only the numeric form is a "
                      "2525D code, and the string stays in the typed block")
    if "numeric_identifier" not in symbol:
        # Neither member of the `identifier` oneof is on the wire (changed 2026-10-04, final
        # verification: this read "in the string form", which the source does not hold).
        return None, (f"not promoted: {said} and no identifier: the symbol sets neither "
                      "string_identifier nor numeric_identifier, so there is no code to "
                      "promote, and the catalog stays in the typed block")
    numeric = symbol["numeric_identifier"]
    first = int(numeric.get("first_ten_digits", "0"))
    second = int(numeric.get("second_ten_digits", "0"))
    if not FIRST_SET[0] <= first <= FIRST_SET[1]:
        return None, (f"not promoted: numeric_identifier.first_ten_digits is {first}, outside "
                      "1 000 000 000 … 9 999 999 999 (a set absent from the wire reads 0), so it "
                      "is not a 2525D code; it stays in the typed block")
    if not SECOND_SET[0] <= second <= SECOND_SET[1]:
        return None, (f"not promoted: numeric_identifier.second_ten_digits is {second}, outside "
                      "0 … 9 999 999 999, so it is not a 2525D code; it stays in the typed block")
    basis = (f"symbol.numeric_identifier with {said}: first_ten_digits followed by "
             "second_ten_digits zero-padded to ten digits, not rewritten")
    if "second_ten_digits" not in numeric:
        basis += "; second_ten_digits is absent from the wire and reads 0, the valid set 0000000000"
    return f"{first}{second:010d}", basis


def _entity_type(flags: dict | None) -> tuple[EntityType, str]:
    """The record §5.4: PLATFORM when `is_vehicle` or `is_unmanned` is true; otherwise UNKNOWN,
    because a proto3 bool has no presence and "not a vehicle" is not "a person" or "a unit"."""
    named = [name for name in ("is_vehicle", "is_unmanned")
             if flags is not None and flags.get(name) is True]
    if named:
        return EntityType.PLATFORM, f"PLATFORM: blue_force_type.{' and '.join(named)} true"
    said = ("the element has no blue_force_type" if flags is None
            else "blue_force_type sets neither is_vehicle nor is_unmanned true")
    return EntityType.UNKNOWN, (f"UNKNOWN: {said}; a proto3 bool has no presence, so false and "
                                "unset are one reading and 'not a vehicle' is not readable as a "
                                "person or a unit")
