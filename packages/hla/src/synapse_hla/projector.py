"""`project_state(snapshot, context)`: one object's state as a CDM Entity, or why it is not one.

WHAT GOES IN
------------
`snapshot` is the payload of a snapshot record, the shape `snapshot.schema.json` fixes: the
object's name, reported class, lifecycle, identity and incarnation, and its four attribute
slots, each with a status, the decoded value, the captured hex, the sequence number, elapsed time
and external effective time of the frame that supplied it. Its `projection_status` and
`suppression_reasons` are read past and recomputed here: they are this function's answer, which
the reducer copies into the snapshot it emits.

`context` carries what a snapshot does not (RED-19), as an object with exactly these members:

    config            the session configuration, as `validate_config` accepts it, or the
                      `config.ValidatedConfig` the reducer validated once for the session
    generation        the generation the snapshot belongs to (1 or more)
    object_token      the object's token in that generation ("o1", "o2", ...)
    identity          the identity the object holds, or null (equal to the snapshot's)
    incarnation       its incarnation, or null (equal to the snapshot's)
    seq, sha256       the sequence number and digest of the frame that triggered the snapshot
    capture_complete  null in a live session, true or false in a replay (SPEC:158)

WHAT COMES OUT
--------------
Either a `synapse_cdm.models.Entity`, or a `Suppression` naming every reason the state cannot be
projected: the sorted, unique list of SPEC:285's vocabulary, every reason that applies and not
just the first (RED-02). An object is eligible only with a VALID non-null EntityIdentifier, a
VALID EntityType, a VALID Spatial that passes the geographic gate, an external time for that
Spatial value, no quarantine, and a ForceIdentifier that is VALID or ABSENT (R23): so
TIME_UNRESOLVED is listed under time policy none in every snapshot, and GEOGRAPHY_UNPROJECTABLE
whenever Spatial is VALID and section 9 refuses it, whatever else is listed. In that last case
the suppression also names the code section 9 gave, E_ECEF_RANGE or E_GEODESY, because the
reducer reports it as a diagnostic (RED-02); this function reports nothing itself.

The Entity is R32's: the type from EntityType.kind alone (1 PLATFORM, 9 SENSOR, anything else
UNKNOWN; no name, class or lifeform is read), the affiliation from the configured `force_map`
alone, looked up by the canonical decimal of a VALID force value (absent or unmapped: UNKNOWN),
position and motion from section 9 (`geodesy`, the one implementation of its formulas), every
member R32 leaves empty null or empty, and `valid_from` the external effective time of the
Spatial value cut to milliseconds (CR-L05), never the time of a later update of another
attribute. `attributes.hla` is the provenance block of `hla-provenance.schema.json`: the decoded
values bit for bit, -0.0 included (COD-15, RED-18; only position and kinematics are normalised),
the SHA-256 of each cached attribute's raw bytes (not of its hex spelling) and the sequence
number of the frame that supplied it, the time block, and the completion flag of the context.
`source` is R27's, and `source_ids` holds the one SourceId of R26's identity (`_identity`).

Before the Entity is returned it is validated against the packaged CDM schema with format
checking, its provenance block against its schema (integers exact: a sequence number of 5.0 is
not one), its two timestamps by explicit code (the schemas' `date-time` is not checked by the
installed jsonschema, OPS-03), and the profile's own assertions (`check_entity_payload`); then
it is constructed as `synapse_cdm.models.Entity` from its canonical bytes, and the model must
give back exactly those bytes (R44). A failure there is a defect of this module, not a property
of the data, and raises `ProjectionDefect`: it is never turned into a suppression.
`entity_payload` and `entity_bytes` give an Entity in the form the output stream carries it
(RED-15).

THE REDUCER'S OWN ENTRY
-----------------------
The reducer does not call `project_state`: it calls `_project_from_reducer` with the snapshot it
has just built (lead ruling CR-L17). That entry leaves out the two checks by which this module
would hold the product's own data to the product's own schemas, and which were most of the cost
of an eligible reflection: the snapshot against `snapshot.schema.json` (the reducer built it
from values the capture rules and the decoders admitted, and its own `check_records` holds its
records), and the provenance block against `hla-provenance.schema.json` (this module wrote it a
moment earlier from those values). Everything else is the same code: the copy of the arguments
and its refusals, the context and the configuration, every slot decoded again from its hex and
compared bit for bit, geodesy, identity, and for the Entity the CDM schema with format checking,
the member sets, the timestamps, the profile's assertions, the model and the byte round trip
(R44). For a snapshot that satisfies its schema the two entries give the same answer, and a
test holds that over every fixture snapshot, the fuzz corpus and the 1000 x 60 load of CR-L07.
`project_state` keeps both checks for every other caller.

WHAT IS REFUSED
---------------
The arguments are the reducer's state, not data from the wire, so most faults in them are bugs
in the caller:
- a Python value that is not JSON (a tuple, a set, bytes, a subclass of dict, str or int, a key
  that is not a str) raises `TypeError`, as at `validate_config` (CR-R2-16);
- JSON that breaks the contract above raises `ValueError` (plain, never `HlaError`): a context
  without exactly its eight members or with one out of range, a snapshot that fails its schema
  (or nests deeper than 32, holds an integer beyond 2^53 - 1, a non-finite number or a lone
  surrogate), an attribute whose members contradict its status (SPEC:283), a VALID value that is
  not what its hex decodes to, bit for bit, an effective time that is not the configured epoch
  plus the elapsed time, a sequence number after the triggering frame's, an identity that
  disagrees with the context, or an eligible state whose identity is not its identifier.
  The snapshot's schema is read with exact integers: JSON Schema counts 5.0 as an integer, but
  the output would carry a sequence number of 5.0 as `5.0` where the same state with 5 writes
  `5`, so an integral float wherever the schema says integer is refused too.
Two faults are the session's and are reported as `HlaError` with catalogue codes: a
configuration `validate_config` refuses (E_CONFIG at its pointer), and an effective time past
9998-12-31T23:59:59.999999Z (E_CONFIG at `/time_policy/epoch`, SPEC:289 and RED-V-01). The
configuration is handed to `validate_config` as it came, not through this module's copy, so
whatever is wrong with it is refused there with its own code and pointer: a non-finite number,
an integer past 2^53 - 1, a lone surrogate or nesting past 32 is E_CONFIG, and a Python value
that is not JSON its `TypeError` (CR-R2-16). The one exception is a `config.ValidatedConfig`,
which only `config.validated_config` can build and nothing can change: it is the configuration
the reducer validated once for the session, and it is trusted as it is (lead ruling CR-L07).

Nothing here reads a clock, a file or the environment (D-08), and the arguments are only read:
they are copied first (the configuration by `validate_config`, or read through the frozen
wrapper), and the result shares no object with them.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import ValidationError
from synapse_cdm.models import Entity

from synapse_hla import _identity, _schema, _utc, canonical, codec, config, errors, geodesy
from synapse_hla.canonical import MAX_DEPTH, MAX_EXACT_INTEGER
from synapse_hla.codec import ENTITY_IDENTIFIER, ENTITY_TYPE, FORCE_IDENTIFIER, NAMES, SPATIAL
from synapse_hla.errors import HlaError
from synapse_hla.limits import V1

PROFILE = "SC-HLA-RPR2-OBS-1"

# --- the Entity's fixed members (R27, R30, R32) ---------------------------------------------------

CDM_SCHEMA_VERSION = "3.0.0"
OBJECT_KIND = "entity"
ADAPTER = _identity.SYSTEM
ADAPTER_VERSION = "1.0.0"
FORMAT_NAME = "HLA RPR FOM"
FORMAT_VERSION = "IEEE 1516-2010 / RPR FOM 2.0 / SC-HLA-RPR2-OBS-1"
POSITION_SOURCE = "ESTIMATED"
HASH_ALGORITHM = "sha256"
TIME_KIND = "external_elapsed"
UNKNOWN = "UNKNOWN"
#: R32: the CDM entity type of an EntityType kind; every kind not listed is UNKNOWN.
ENTITY_TYPE_BY_KIND = MappingProxyType({1: "PLATFORM", 9: "SENSOR"})

#: SPEC:134's transformations, in the order they are listed.
EXTERNAL_TIME_CONTEXT = "external-time-context"
ECEF_TO_WGS84 = "ecef-to-wgs84"
ECEF_VELOCITY_TO_ENU = "ecef-velocity-to-enu"

SNAPSHOT_SCHEMA = "snapshot.schema.json"
PROVENANCE_SCHEMA = "hla-provenance.schema.json"

# --- snapshot vocabulary --------------------------------------------------------------------------

ABSENT = "ABSENT"
VALID = "VALID"
INVALID = "INVALID"
QUARANTINED = "QUARANTINED"

#: The suppression reasons of SPEC:285, in the order the paragraph lists them.
MISSING_ENTITY_IDENTIFIER = "MISSING_ENTITY_IDENTIFIER"
MISSING_ENTITY_TYPE = "MISSING_ENTITY_TYPE"
MISSING_SPATIAL = "MISSING_SPATIAL"
INVALID_ENTITY_IDENTIFIER = "INVALID_ENTITY_IDENTIFIER"
INVALID_ENTITY_TYPE = "INVALID_ENTITY_TYPE"
INVALID_SPATIAL = "INVALID_SPATIAL"
INVALID_FORCE_IDENTIFIER = "INVALID_FORCE_IDENTIFIER"
NULL_ID = "NULL_ID"
QUARANTINED_REASON = "QUARANTINED"
TIME_UNRESOLVED = "TIME_UNRESOLVED"
GEOGRAPHY_UNPROJECTABLE = "GEOGRAPHY_UNPROJECTABLE"
REASONS: tuple[str, ...] = (
    MISSING_ENTITY_IDENTIFIER, MISSING_ENTITY_TYPE, MISSING_SPATIAL, INVALID_ENTITY_IDENTIFIER,
    INVALID_ENTITY_TYPE, INVALID_SPATIAL, INVALID_FORCE_IDENTIFIER, NULL_ID, QUARANTINED_REASON,
    TIME_UNRESOLVED, GEOGRAPHY_UNPROJECTABLE,
)
#: The required attributes and the reason each gives when it is ABSENT or INVALID (R23).
_REQUIRED = (
    (ENTITY_IDENTIFIER, MISSING_ENTITY_IDENTIFIER, INVALID_ENTITY_IDENTIFIER),
    (ENTITY_TYPE, MISSING_ENTITY_TYPE, INVALID_ENTITY_TYPE),
    (SPATIAL, MISSING_SPATIAL, INVALID_SPATIAL),
)
#: The codes section 9 refuses a Spatial value with (R29, CR-R1-01).
GEOGRAPHY_CODES = (errors.E_ECEF_RANGE, errors.E_GEODESY)

#: The members of a context, in the order the module text lists them (RED-19).
CONTEXT_KEYS = ("config", "generation", "object_token", "identity", "incarnation", "seq",
                "sha256", "capture_complete")
#: The object token form of the output schema: "o" and a positive decimal, at most 16 characters.
_TOKEN = re.compile(r"o[1-9][0-9]*")
_TOKEN_MAX_CHARS = 16
_SHA256 = re.compile(r"[0-9a-f]{64}")
#: Where an effective time past year 9998 is reported: the epoch it was counted from (RED-V-01).
EPOCH_POINTER = "/time_policy/epoch"

#: The members the profile writes in an Entity, its source, position and kinematics: every
#: member of the CDM schema's objects, the empty ones included (R32).
ENTITY_MEMBERS = frozenset({
    "schema_version", "object_kind", "entity_id", "entity_type", "affiliation", "symbol",
    "position", "kinematics", "attributes", "ontology_types", "valid_from", "valid_to",
    "confidence", "source", "source_ids", "integrity", "quality", "status", "residual"})
SOURCE_MEMBERS = frozenset({
    "system", "adapter", "adapter_version", "synthetic", "format_name", "format_version",
    "original_id", "source_hash", "record_index", "observed_at", "transformations"})
POSITION_MEMBERS = frozenset({"lat", "lon", "alt_m", "position_source", "accuracy_m",
                              "vertical"})
KINEMATICS_MEMBERS = frozenset({"speed_mps", "course_deg", "climb_mps"})


class ProjectionDefect(RuntimeError):
    """An Entity this module built fails its own checks: a defect here, never a data fault."""


@dataclass(frozen=True)
class Suppression:
    """Why a state is not projected: the reasons, and section 9's code when it refused Spatial.

    `reasons` is the snapshot's `suppression_reasons`: non-empty, sorted, unique, from SPEC:285's
    vocabulary. `geography_code` is E_ECEF_RANGE or E_GEODESY exactly when GEOGRAPHY_UNPROJECTABLE
    is among them, else None.
    """

    reasons: tuple[str, ...]
    geography_code: str | None = None

    def __post_init__(self) -> None:
        reasons = self.reasons
        if type(reasons) is not tuple or not all(type(r) is str for r in reasons):
            raise TypeError("suppression reasons are a tuple of str")
        if not reasons or list(reasons) != sorted(set(reasons)):
            raise ValueError("suppression reasons are non-empty, sorted and unique")
        if not set(reasons) <= set(REASONS):
            raise ValueError("a suppression reason outside the SPEC:285 vocabulary")
        if GEOGRAPHY_UNPROJECTABLE in reasons:
            named = self.geography_code in GEOGRAPHY_CODES
        else:
            named = self.geography_code is None
        if not named:
            raise ValueError("geography_code names section 9's code exactly when "
                             "GEOGRAPHY_UNPROJECTABLE is a reason")


def project_state(snapshot, context) -> Entity | Suppression:
    """The Entity of an eligible snapshot, or the `Suppression` of any other; see the module."""
    return _project(snapshot, context, from_reducer=False)


def _project_from_reducer(snapshot, context) -> Entity | Suppression:
    """`project_state` for the snapshot the reducer has just built, without the snapshot schema
    and the provenance schema (CR-L17, see the module text). Only `reducer` calls it."""
    return _project(snapshot, context, from_reducer=True)


def _project(snapshot, context, *, from_reducer: bool) -> Entity | Suppression:
    snapshot = _copy(snapshot, "snapshot", 1)
    context = _copy_context(context)
    _check_context(context)
    session = _session(context["config"])
    if type(snapshot) is not dict:
        raise ValueError("the snapshot is not a JSON object")
    if not from_reducer:
        problem = _schema.first_problem(SNAPSHOT_SCHEMA, snapshot, exact_integers=True)
        if problem is not None:
            raise ValueError(f"the snapshot does not satisfy {SNAPSHOT_SCHEMA} at "
                             f"'{canonical.json_pointer(problem.tokens)}' ({problem.keyword})")
    epoch = config.epoch_microsecond(session)
    attributes = snapshot["attributes"]
    decoded = {}
    for name in NAMES:
        value = _checked_attribute(name, attributes[name], epoch, context["seq"])
        if value is not None:
            decoded[name] = value
    _check_names(snapshot)
    _check_identity(snapshot, context)

    reasons, geography_code, projection = _assess(attributes, decoded, snapshot["lifecycle"],
                                                  epoch is None)
    if reasons:
        return Suppression(reasons, geography_code)
    identifier = decoded[ENTITY_IDENTIFIER]
    if context["identity"] is None or not _identical(context["identity"], identifier):
        raise ValueError("an eligible state's identity must be its VALID EntityIdentifier")
    spatial_effective = epoch + int(attributes[SPATIAL]["elapsed_ns"]) // 1000
    payload = _payload(snapshot, decoded, context, session, projection, spatial_effective)
    if from_reducer:
        _check_entity(payload, provenance_schema=False)
    else:
        check_entity_payload(payload)
    return _constructed(payload)


# --- the arguments --------------------------------------------------------------------------------

def _session(given):
    """The context's configuration: a `ValidatedConfig` is trusted as it is, because only
    `config.validated_config` builds one and nothing can change it (CR-L07); anything else goes
    through `validate_config` with its refusals (CR-R3-03)."""
    if type(given) is config.ValidatedConfig:
        return given.document
    return config.validate_config(given)


def _has_lone_surrogate(text: str) -> bool:
    return not text.isascii() and any(0xD800 <= ord(ch) <= 0xDFFF for ch in text)


def _copy(value, where: str, depth: int):
    """A deep copy of exact JSON types; the refusals of the module text, before anything else."""
    if depth > MAX_DEPTH:
        raise ValueError(f"the {where} nests deeper than {MAX_DEPTH} levels")
    kind = type(value)
    if kind is dict:
        out = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"a member name of the {where} is not a str")
            if _has_lone_surrogate(key):
                raise ValueError(f"a member name of the {where} holds a lone surrogate")
            out[key] = _copy(item, where, depth + 1)
        return out
    if kind is list:
        return [_copy(item, where, depth + 1) for item in value]
    if kind is str:
        if _has_lone_surrogate(value):
            raise ValueError(f"a string of the {where} holds a lone surrogate")
        return value
    if kind is int:
        if not -MAX_EXACT_INTEGER <= value <= MAX_EXACT_INTEGER:
            raise ValueError(f"an integer of the {where} lies beyond 2^53 - 1")
        return value
    if kind is float:
        if not math.isfinite(value):
            raise ValueError(f"a number of the {where} is not finite")
        return value
    if kind is bool or value is None:
        return value
    raise TypeError(f"the {where} holds a Python value that is not JSON")


def _copy_context(context):
    """The context copied as `_copy` copies it, all but its configuration, which goes to
    `validate_config` untouched: that function takes its own copy and refuses what JSON cannot
    carry as E_CONFIG at the member's pointer (CR-R2-11/12, CR-R2-16), where this module's copy
    would have made it a plain ValueError."""
    if type(context) is not dict:
        return _copy(context, "context", 1)
    out = {}
    for key, item in context.items():
        if type(key) is not str:
            raise TypeError("a member name of the context is not a str")
        if _has_lone_surrogate(key):
            raise ValueError("a member name of the context holds a lone surrogate")
        out[key] = item if key == "config" else _copy(item, "context", 2)
    return out


def _counter(value) -> bool:
    return type(value) is int and 1 <= value <= MAX_EXACT_INTEGER


def _check_context(context) -> None:
    if type(context) is not dict:
        raise ValueError("the context is not a JSON object")
    if set(context) != set(CONTEXT_KEYS):
        raise ValueError("the context holds exactly config, generation, object_token, identity, "
                         "incarnation, seq, sha256 and capture_complete")
    if not _counter(context["generation"]):
        raise ValueError("the context's generation is an int from 1 to 2^53 - 1")
    token = context["object_token"]
    if type(token) is not str or len(token) > _TOKEN_MAX_CHARS or not _TOKEN.fullmatch(token):
        raise ValueError("the context's object_token is 'o' and a positive decimal, "
                         "at most 16 characters")
    identity = context["identity"]
    if identity is not None:
        try:
            _identity.identifier_fields(identity)
        except TypeError:
            raise ValueError("the context's identity is an identifier or null") from None
    incarnation = context["incarnation"]
    if incarnation is not None and not _counter(incarnation):
        raise ValueError("the context's incarnation is an int from 1 to 2^53 - 1, or null")
    if not _counter(context["seq"]):
        raise ValueError("the context's seq is an int from 1 to 2^53 - 1")
    digest = context["sha256"]
    if type(digest) is not str or not _SHA256.fullmatch(digest):
        raise ValueError("the context's sha256 is 64 lowercase hexadecimal digits")
    if type(context["capture_complete"]) is not bool and context["capture_complete"] is not None:
        raise ValueError("the context's capture_complete is true, false or null")


def _identical(a, b) -> bool:
    """Equal as JSON values and as Python types: a bool is not an int, an int not a float, and
    -0.0 is not 0.0. Object member order is not compared (the output is written with sorted
    keys)."""
    if type(a) is not type(b):
        return False
    if type(a) is dict:
        return a.keys() == b.keys() and all(_identical(a[k], b[k]) for k in a)
    if type(a) is list:
        return len(a) == len(b) and all(_identical(x, y) for x, y in zip(a, b))
    if type(a) is float:
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b


def _checked_attribute(name: str, slot: dict, epoch: int | None, frame_seq: int):
    """SPEC:283's rules for one attribute slot; the value decoded afresh from its hex if VALID.

    The decoded value is what the Entity carries, and it must be the snapshot's value bit for
    bit: otherwise the hash of the bytes and the value beside it would describe two different
    attribute values.
    """
    status = slot["status"]
    sourced = (slot["hex"], slot["seq"], slot["elapsed_ns"])
    if status == ABSENT:
        if any(v is not None for v in sourced) or slot["value"] is not None \
                or slot["effective_at"] is not None:
            raise ValueError(f"the ABSENT {name} carries a value, source or time")
        return None
    if any(v is None for v in sourced):
        raise ValueError(f"the {status} {name} lacks its hex, seq or elapsed_ns")
    if (slot["value"] is None) != (status == INVALID):
        raise ValueError(f"the {status} {name} has a value exactly when it is VALID")
    if slot["seq"] > frame_seq:
        raise ValueError(f"the {name} comes from a frame after the triggering frame")
    expected_time = None
    if epoch is not None:
        effective = epoch + int(slot["elapsed_ns"]) // 1000
        if effective > _utc.MAX_MICROSECOND:
            raise HlaError(errors.E_CONFIG, EPOCH_POINTER,
                           "the external effective time passes 9998-12-31T23:59:59.999999Z")
        expected_time = _utc.format_microsecond(effective)
    if slot["effective_at"] != expected_time:
        raise ValueError(f"the effective_at of the {name} is not the configured epoch plus its "
                         "elapsed time (null under time policy none)")
    if status == INVALID:
        return None
    try:
        value = codec.decode_attribute(name, bytes.fromhex(slot["hex"]))["value"]
    except HlaError:
        raise ValueError(f"the VALID {name} does not decode from its hex") from None
    if not _identical(value, slot["value"]):
        raise ValueError(f"the VALID {name} is not the value its hex decodes to, bit for bit")
    return value


def _check_names(snapshot: dict) -> None:
    # The schema counts characters; the limits are UTF-8 bytes (SPEC:223-224, SPEC:289).
    if len(snapshot["name"].encode("utf-8")) > V1.object_name_utf8_bytes:
        raise ValueError("the object name is longer than its limit in UTF-8 bytes")
    if len(snapshot["reported_class"].encode("utf-8")) > V1.class_name_utf8_bytes:
        raise ValueError("the reported class name is longer than its limit in UTF-8 bytes")


def _check_identity(snapshot: dict, context: dict) -> None:
    identity, incarnation = snapshot["identity"], snapshot["incarnation"]
    if not _identical(identity, context["identity"]) \
            or not _identical(incarnation, context["incarnation"]):
        raise ValueError("the snapshot's identity and incarnation are not the context's")
    if (identity is None) != (incarnation is None):
        raise ValueError("an identity and its incarnation are both set or both null")
    if identity is not None:
        _identity.identifier_fields(identity)


# --- eligibility ----------------------------------------------------------------------------------

def _assess(attributes: dict, decoded: dict, lifecycle: str, time_unresolved: bool):
    """Every applicable reason (RED-02), section 9's code, and the projection when it succeeded."""
    reasons = set()
    for name, missing, invalid in _REQUIRED:
        status = attributes[name]["status"]
        if status == ABSENT:
            reasons.add(missing)
        elif status == INVALID:
            reasons.add(invalid)
    if attributes[FORCE_IDENTIFIER]["status"] == INVALID:
        reasons.add(INVALID_FORCE_IDENTIFIER)
    identifier = decoded.get(ENTITY_IDENTIFIER)
    if identifier is not None and identifier == {"site": 0, "application": 0, "entity": 0}:
        reasons.add(NULL_ID)
    if lifecycle == QUARANTINED:
        reasons.add(QUARANTINED_REASON)
    if time_unresolved:
        reasons.add(TIME_UNRESOLVED)
    geography_code = None
    projection = None
    spatial = decoded.get(SPATIAL)
    if spatial is not None:
        try:
            projection = geodesy.project_spatial(spatial)
        except HlaError as error:
            if error.code not in GEOGRAPHY_CODES:
                raise
            reasons.add(GEOGRAPHY_UNPROJECTABLE)
            geography_code = error.code
    return tuple(sorted(reasons)), geography_code, projection


# --- the Entity -----------------------------------------------------------------------------------

def _payload(snapshot: dict, decoded: dict, context: dict, session: dict,
             projection: geodesy.Projection, spatial_effective: int) -> dict:
    session_id = session["session_id"]
    generation = context["generation"]
    token = context["object_token"]
    seq = context["seq"]
    attributes = snapshot["attributes"]
    external = _identity.external_id(session_id, generation, context["identity"],
                                     context["incarnation"])
    force = decoded.get(FORCE_IDENTIFIER)
    force_value = None if force is None else force["value"]
    affiliation = UNKNOWN if force_value is None else session["force_map"].get(str(force_value),
                                                                               UNKNOWN)
    transformations = [EXTERNAL_TIME_CONTEXT, ECEF_TO_WGS84]
    if projection.kinematics is not None:
        transformations.append(ECEF_VELOCITY_TO_ENU)
    position = dict(projection.position)
    position.update({"position_source": POSITION_SOURCE, "accuracy_m": None, "vertical": None})
    hla = {
        "profile": PROFILE,
        "session_id": session_id,
        "generation": generation,
        "object_token": token,
        "reported_class": snapshot["reported_class"],
        "name": snapshot["name"],
        "identifier": decoded[ENTITY_IDENTIFIER],
        "entity_type": decoded[ENTITY_TYPE],
        "force_identifier": force_value,
        "spatial": decoded[SPATIAL],
        "attribute_sequences": {name: attributes[name]["seq"] for name in NAMES},
        "attribute_hashes": {name: _raw_hash(attributes[name]) for name in NAMES},
        "time": {
            "kind": TIME_KIND,
            "basis": session["time_policy"]["basis"],
            "effective_at": _utc.format_microsecond(spatial_effective),
            "spatial_seq": attributes[SPATIAL]["seq"],
        },
        "profile_verification": session["profile_declaration"],
        "capture_complete": context["capture_complete"],
    }
    return {
        "schema_version": CDM_SCHEMA_VERSION,
        "object_kind": OBJECT_KIND,
        "entity_id": _identity.entity_id(external),
        "entity_type": ENTITY_TYPE_BY_KIND.get(decoded[ENTITY_TYPE]["kind"], UNKNOWN),
        "affiliation": affiliation,
        "symbol": None,
        "position": position,
        "kinematics": projection.kinematics,
        "attributes": {"hla": hla},
        "ontology_types": [],
        "valid_from": _utc.format_millisecond(spatial_effective),
        "valid_to": None,
        "confidence": None,
        "source": {
            "system": session["source_system"],
            "adapter": ADAPTER,
            "adapter_version": ADAPTER_VERSION,
            "synthetic": session["synthetic"],
            "format_name": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "original_id": f"{session_id}/{generation}/{token}/{seq}",
            "source_hash": {"algorithm": HASH_ALGORITHM, "value": context["sha256"]},
            "record_index": seq - 1,
            "observed_at": None,
            "transformations": transformations,
        },
        "source_ids": [{"system": _identity.SYSTEM, "external_id": external}],
        "integrity": None,
        "quality": None,
        "status": None,
        "residual": None,
    }


def _raw_hash(slot: dict) -> str | None:
    """SHA-256 of the attribute's raw value bytes, not of their hex spelling (SPEC:134)."""
    if slot["status"] == ABSENT:
        return None
    return hashlib.sha256(bytes.fromhex(slot["hex"])).hexdigest()


def _constructed(payload: dict) -> Entity:
    """The Entity of a payload that has passed its checks: the model must give back exactly its
    canonical bytes (R44)."""
    try:
        data = canonical.canonical_bytes(payload, floats=True)
    except canonical.StrictJsonError as exc:
        raise ProjectionDefect("the Entity has no canonical form") from exc
    try:
        entity = Entity.model_validate_json(data)
    except ValidationError as exc:
        raise ProjectionDefect("synapse_cdm.models.Entity refuses the Entity") from exc
    try:
        again = entity_bytes(entity)
    except canonical.StrictJsonError as exc:
        raise ProjectionDefect("the constructed Entity has no canonical form") from exc
    if again != data:
        raise ProjectionDefect("synapse_cdm.models.Entity does not give the Entity back unchanged")
    return entity


def entity_payload(entity: Entity) -> dict:
    """The Entity as a JSON value, the `payload` of an upsert record (RED-15)."""
    if type(entity) is not Entity:
        raise TypeError("entity_payload takes a synapse_cdm.models.Entity")
    return entity.model_dump(mode="json")


def entity_bytes(entity: Entity) -> bytes:
    """The canonical bytes of an Entity as the output stream writes its payload (RED-15)."""
    return canonical.canonical_bytes(entity_payload(entity), floats=True)


# --- the checks of an Entity (R44) ----------------------------------------------------------------

def _first_schema_error(validator, instance) -> str | None:
    """The first error by pointer (indexes before names at one level), then keyword."""
    found = []
    for error in validator.iter_errors(instance):
        path = tuple(error.absolute_path)
        key = tuple((0, t, "") if type(t) is int else (1, 0, t) for t in path)
        found.append((key, error.validator, path))
    if not found:
        return None
    _, keyword, path = min(found)
    return f"'{canonical.json_pointer(path)}' ({keyword})"


def check_entity_payload(payload) -> None:
    """R44 on one Entity payload: schema with format checking, timestamps, profile assertions.

    Raises `ProjectionDefect` naming the first failure; returns None when every check holds.
    """
    _check_entity(payload, provenance_schema=True)


def _check_entity(payload, *, provenance_schema: bool) -> None:
    """`check_entity_payload`; without `provenance_schema` for an Entity `_payload` has just
    written from a snapshot the reducer built (CR-L17): the block's shape is then this module's
    own construction, and every other check still runs."""
    if type(payload) is not dict:
        raise ProjectionDefect("an Entity payload is a JSON object")
    try:
        # What the output stream could not write is not an Entity, and the schema validator
        # must never meet an integer it cannot print or a NaN that every bound lets through.
        canonical.canonical_bytes(payload, floats=True)
    except (canonical.StrictJsonError, TypeError) as exc:
        raise ProjectionDefect("the Entity is not canonical JSON") from exc
    problem = _first_schema_error(_schema.entity_validator(), payload)
    if problem is not None:
        raise ProjectionDefect(f"the Entity fails cdm-entity.schema.json at {problem}")
    attributes = payload.get("attributes")
    if type(attributes) is not dict or set(attributes) != {"hla"}:
        raise ProjectionDefect("the Entity's attributes are exactly the hla provenance block")
    hla = attributes["hla"]
    if provenance_schema:
        problem = _first_schema_error(_schema.checked_validator(PROVENANCE_SCHEMA), hla)
        if problem is not None:
            raise ProjectionDefect(f"the provenance block fails {PROVENANCE_SCHEMA} at {problem}")
    shapes = [(ENTITY_MEMBERS, payload, "the Entity"),
              (SOURCE_MEMBERS, payload["source"], "source"),
              (POSITION_MEMBERS, payload.get("position"), "position")]
    if payload.get("kinematics") is not None:
        shapes.append((KINEMATICS_MEMBERS, payload["kinematics"], "kinematics"))
    for members, value, what in shapes:
        if type(value) is not dict or set(value) != members:
            raise ProjectionDefect(f"{what} does not carry exactly the members the profile writes")
    try:
        valid_from = _utc.parse_millisecond(payload["valid_from"])
        effective = _utc.parse_microsecond(hla["time"]["effective_at"])
    except ValueError:
        raise ProjectionDefect("an Entity timestamp is not a real UTC instant of the profile's "
                               "form and range") from None
    for holds, what in _assertions(payload, hla, valid_from, effective):
        if not holds:
            raise ProjectionDefect(f"the Entity breaks the profile: {what}")


def _assertions(payload: dict, hla: dict, valid_from: int, effective: int):
    """The profile's own rules on an Entity, each with what it says, in a fixed order."""
    source = payload["source"]
    position = payload["position"]
    kinematics = payload["kinematics"]
    spatial = hla["spatial"]
    sequences = hla["attribute_sequences"]
    hashes = hla["attribute_hashes"]
    yield payload["schema_version"] == CDM_SCHEMA_VERSION, "schema_version is 3.0.0"
    yield payload["object_kind"] == OBJECT_KIND, "object_kind is entity"
    for member in ("symbol", "confidence", "quality", "status", "residual", "integrity",
                   "valid_to"):
        yield payload[member] is None, f"{member} is null"
    yield payload["ontology_types"] == [], "ontology_types is empty"
    yield valid_from == effective - effective % 1000, \
        "valid_from is the Spatial effective time cut to milliseconds"
    yield hla["time"]["kind"] == TIME_KIND, "the time kind is external_elapsed"
    yield hla["time"]["spatial_seq"] == sequences[SPATIAL], "the time block names Spatial's seq"
    yield position is not None and position["position_source"] == POSITION_SOURCE \
        and position["accuracy_m"] is None and position["vertical"] is None \
        and position["alt_m"] is not None, "position is ESTIMATED HAE with no accuracy or vertical"
    yield payload["entity_type"] == ENTITY_TYPE_BY_KIND.get(hla["entity_type"]["kind"], UNKNOWN), \
        "entity_type follows EntityType.kind"
    yield (spatial["frame"] == codec.WORLD) == (spatial["algorithm"] <= 5), \
        "the Spatial frame is its algorithm's"
    yield kinematics is None or spatial["algorithm"] in geodesy.WORLD_VELOCITY_ALGORITHMS, \
        "only a WORLD velocity gives kinematics"
    base = [EXTERNAL_TIME_CONTEXT, ECEF_TO_WGS84]
    yield source["transformations"] == (base if kinematics is None
                                        else base + [ECEF_VELOCITY_TO_ENU]), \
        "the transformations are SPEC:134's, with the ENU step exactly when there is motion"
    yield (source["adapter"], source["adapter_version"], source["format_name"],
           source["format_version"]) == (ADAPTER, ADAPTER_VERSION, FORMAT_NAME, FORMAT_VERSION), \
        "the adapter and format are R27's"
    yield source["observed_at"] is None, "observed_at is null"
    digest = source["source_hash"]
    yield digest is not None and digest["algorithm"] == HASH_ALGORITHM \
        and type(digest["value"]) is str and _SHA256.fullmatch(digest["value"]) is not None, \
        "source_hash is the frame's SHA-256"
    record_index = source["record_index"]
    seq = None if record_index is None else record_index + 1
    yield seq is not None and source["original_id"] == (
        f"{hla['session_id']}/{hla['generation']}/{hla['object_token']}/{seq}"), \
        "original_id is session/generation/token/seq with record_index seq - 1"
    yield seq is not None and all(s is None or s <= seq for s in sequences.values()), \
        "no attribute comes from a frame after the triggering frame"
    yield all((sequences[n] is None) == (hashes[n] is None) for n in NAMES) \
        and all(sequences[n] is not None for n in (ENTITY_IDENTIFIER, ENTITY_TYPE, SPATIAL)), \
        "the three required attributes have a seq and a hash, an absent force has neither"
    yield (hla["force_identifier"] is None) == (sequences[FORCE_IDENTIFIER] is None), \
        "the force identifier is null exactly when ForceIdentifier is absent"
    yield hla["identifier"] != {"site": 0, "application": 0, "entity": 0}, \
        "the identifier is not the null identifier"
    yield _identity_agrees(payload, hla), \
        "source_ids is the one hla-rpr2 SourceId of R26 and entity_id is its UUID"


def _identity_agrees(payload: dict, hla: dict) -> bool:
    source_ids = payload["source_ids"]
    if len(source_ids) != 1 or source_ids[0]["system"] != _identity.SYSTEM:
        return False
    external = source_ids[0]["external_id"]
    try:
        session_id, generation, site, application, entity, _ = _identity.parts(external)
    except ValueError:
        return False
    identifier = hla["identifier"]
    return (session_id == hla["session_id"] and generation == hla["generation"]
            and (site, application, entity) == (identifier["site"], identifier["application"],
                                                identifier["entity"])
            and payload["entity_id"] == _identity.entity_id(external))
