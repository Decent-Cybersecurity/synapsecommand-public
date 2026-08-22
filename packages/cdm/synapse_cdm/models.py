"""The canonical objects. Four of them, and everything an adapter emits is one of the four.

    Entity      anything that EXISTS on the map          (a unit, a jammer, an evacuee group)
    Event       anything that HAPPENS                    (a detection, an interference alert)
    Track       an entity's position history, ordered    (STANAG 4676's shape)
    PlanObject  anything we push OUT                     (a COA sketch, a route, to TAK)

WHY `extra="forbid"` EVERYWHERE
-------------------------------
A canonical model whose objects accept unknown keys is not canonical — it is a dict with a
docstring. `additionalProperties: false` is what the Track contract already does, and the
reason the strictness is safe here is that the CDM pairs it with a DECLARED escape hatch:
`Entity.attributes` and `Event.payload` accept anything, so an adapter never has to choose
between dropping a field and failing validation. Strict where the meaning is fixed, open
where it is not, and the boundary between the two written down.

The alternative — `extra="allow"` on the objects themselves — puts source-specific fields at
the same level as canonical ones, and six months later nobody can tell which fields the model
guarantees and which one adapter happens to send. That is the failure mode the escape hatch
exists to prevent.

WHY TIMESTAMPS ARE A CUSTOM ANNOTATED TYPE
------------------------------------------
`Timestamp` parses loosely (sources are undisciplined) and serialises to exactly one string
form (see times.py), and it carries its own JSON Schema so the exported contract states the
strict pattern rather than the permissive `format: date-time`. Parse wide, emit narrow,
publish narrow.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainSerializer,
    WithJsonSchema,
    field_validator,
    model_validator,
)

from synapse_cdm import times
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    InterferenceType,
    ObjectType,
    PositionSource,
    Severity,
)
from synapse_cdm.geo import Geometry
from synapse_cdm.version import SCHEMA_VERSION

STRICT = ConfigDict(extra="forbid", use_enum_values=False, validate_assignment=True)

Timestamp = Annotated[
    _dt.datetime,
    BeforeValidator(times.parse),
    PlainSerializer(times.render, return_type=str),
    WithJsonSchema({
        "type": "string",
        "pattern": times.TIMESTAMP_RE.pattern,
        "description": "RFC 3339 UTC, exactly three decimal places, always Z.",
    }),
]

# An extension bag. `Any` is deliberate: this is where a source's own shape lands untouched,
# and narrowing it would start dropping the very data the bag exists to keep.
Attributes = dict[str, Any]


class SourceId(BaseModel):
    """One external identifier for an object — the provenance mapping.

    A list of these, not one, because the same object arrives from several systems: the same
    vessel is an MMSI to AIS, a track number to STANAG 4676 and a UID to TAK. Fusion joins
    them later; the adapter's job is to record which name its own system used, and never to
    overwrite another system's entry.
    """
    model_config = STRICT
    system: str = Field(min_length=1, description="The external system, e.g. PNTMAP, TAK.")
    external_id: str = Field(min_length=1, description="That system's own identifier.")


class SourceRef(BaseModel):
    """Which adapter produced this object, from which system, and whether it is real.

    `synthetic` is required and has no default. Every fixture in this repository is synthetic
    and every scenario package is too (TR-12), and the platform keeps the synthetic and live
    layers apart over one interface — so an object that does not say which layer it belongs to
    cannot be filed. A default of `false` would silently promote exercise data to operational
    data, which is the dangerous direction; a default of `true` would silently demote live
    data and hide it from an operator. There is no safe default, so there is no default.
    """
    model_config = STRICT
    system: str = Field(min_length=1, description="The external system this came from.")
    adapter: str = Field(min_length=1, description="Adapter name, e.g. pntmap.")
    adapter_version: str = Field(min_length=1, description="Adapter semver.")
    synthetic: bool = Field(description="true for anything not from a real source (TR-12).")


class Integrity(BaseModel):
    """DESIGNED, NOT IMPLEMENTED — the field the PQC signature will occupy.

    No crypto happens in this package (tests/test_cdm_boundary.py asserts the package imports
    no crypto module). The field exists from day one so that turning signing on is a value
    change rather than a schema change: a schema change would be a MAJOR bump rippling through
    every store and every consumer, and would arrive exactly when the signing work is already
    late.

    `algorithm` is a free string rather than an enum, naming what the platform's ledger
    already uses — ML-DSA-87 for entry signatures, SLH-DSA for checkpoints. Free, because the
    algorithm that replaces those is not knowable now, and an enum would make the migration a
    MAJOR bump for a value nobody reasons over programmatically.

    All three fields or none. A block holding a signature with no algorithm is unverifiable,
    and an unverifiable signature that LOOKS present is worse than an absent one: it reads as
    assurance to everything downstream that does not check.
    """
    model_config = STRICT
    signature: str = Field(min_length=1)
    algorithm: str = Field(min_length=1, description="e.g. ML-DSA-87, SLH-DSA-SHAKE-256s.")
    chain_hash: str = Field(min_length=1, description="Hash binding this object to the chain.")


class Position(BaseModel):
    """A fix. Both coordinates required — that is how the null-never-zero rule is structural.

    An unknown position is the ABSENCE of this object (`entity.position is None`), never a
    Position holding zeros. Because lat and lon are required here, an adapter cannot express
    "unknown" as (0, 0) even by accident: it has to either omit the Position or state a real
    coordinate. Coordinate zero is a real point in the Gulf of Guinea, and a contact painted
    there is a contact that does not exist.

    `accuracy_m` absent means unknown accuracy, NOT perfect accuracy. Zero would mean a fix
    with no error, which no sensor produces.
    """
    model_config = STRICT
    lat: float = Field(ge=-90.0, le=90.0, description="WGS84 decimal degrees.")
    lon: float = Field(ge=-180.0, le=180.0, description="WGS84 decimal degrees.")
    alt_m: float | None = Field(default=None, description="Metres HAE. None = unknown.")
    position_source: PositionSource = Field(
        description="How the fix was obtained — the field that survives GNSS denial."
    )
    accuracy_m: float | None = Field(
        default=None, ge=0.0, description="Metres, 1-sigma. None = unknown, never 0."
    )


class Kinematics(BaseModel):
    """Motion. Every field optional, and absent means UNKNOWN, never zero.

    This is the AIS sentinel lesson in schema form: 0 kt is measured stillness, 0 deg is a
    course due north, 0 m/s climb is level flight. All three are real measurements, so none of
    them can double as "no data" — the adapter translates the source's sentinel to None.
    """
    model_config = STRICT
    speed_mps: float | None = Field(default=None, ge=0.0, description="Metres per second.")
    course_deg: float | None = Field(
        default=None, ge=0.0, lt=360.0, description="Degrees true, [0, 360)."
    )
    climb_mps: float | None = Field(
        default=None, description="Metres per second, negative = descending."
    )


class CDMBase(BaseModel):
    """What every canonical object carries: its version, its provenance, and its source ids.

    `source_ids` is here rather than on Entity alone, which is a deliberate departure from the
    original specification. The harness found the reason within a minute of first running: a
    PNTMAP alert whose emitter carries its own id produced an Entity keyed on the emitter and
    an Event keyed on nothing, so the alert's own identifier — `PNTMAP-2026-04-29-0117` —
    appeared nowhere in the output. Three consequences, none acceptable:

    - the same alert redelivered cannot be recognised as a duplicate, because nothing in the
      CDM object holds the identifier the source deduplicates on;
    - an auditor holding a CDM event cannot get back to the source record it came from, which
      is the one question an audit trail exists to answer;
    - and the loss was SILENT. Every other check passed.

    Required with min_length=1 on every kind, for the same reason `SourceRef.synthetic` has no
    default: an adapter whose source genuinely has no identifier must say what it keyed on
    instead (ids.derive_with_basis makes that explicit), and "I could not trace this" is a
    sentence the format should force someone to write rather than allow by omission.
    """
    model_config = STRICT
    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Semver of the CDM this object was written against.",
    )
    source: SourceRef = Field(
        description="Which adapter produced this object. Required on every kind."
    )
    source_ids: list[SourceId] = Field(
        min_length=1,
        description="Every external identifier this object is known by. At least one, on "
                    "EVERY kind — see the class docstring.",
    )
    integrity: Integrity | None = Field(
        default=None, description="PQC signature block — designed, not yet populated."
    )

    @field_validator("schema_version")
    @classmethod
    def _semver(cls, v: str) -> str:
        try:
            major, minor, patch = (int(p) for p in v.split("."))
        except ValueError as e:
            raise ValueError(f"schema_version must be semver MAJOR.MINOR.PATCH, got {v!r}") from e
        if min(major, minor, patch) < 0:
            raise ValueError(f"schema_version parts must not be negative: {v!r}")
        return v


class Entity(CDMBase):
    """Anything that exists on the map, at a stated time, with stated confidence."""
    object_kind: Literal["entity"] = "entity"
    entity_id: uuid.UUID = Field(
        description="Stable across updates — derived, see ids.derive(). Never drawn at random."
    )
    entity_type: EntityType
    affiliation: Affiliation
    symbol: str | None = Field(
        default=None,
        description="MIL-STD-2525D SIDC, 20 digits. None when the source states no symbol — "
                    "see symbology.sidc_from_affiliation() for deriving one.",
    )
    position: Position | None = Field(
        default=None,
        description="None = position unknown. NEVER a Position holding zeros.",
    )
    kinematics: Kinematics | None = None
    attributes: Attributes = Field(
        default_factory=dict,
        description="Source-specific fields the CDM has no home for. The never-drop bag: "
                    "park data here rather than discarding it.",
    )
    valid_from: Timestamp = Field(description="When this state began.")
    valid_to: Timestamp | None = Field(
        default=None, description="When it ceased. None = still current / open-ended."
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="0..1. None = unknown; 0 means certainty-that-not, which is a claim.",
    )

    @field_validator("symbol")
    @classmethod
    def _sidc(cls, v: str | None) -> str | None:
        """2525D SIDC is twenty digits. Checked, because a malformed one renders as nothing.

        A symbol code that a renderer cannot parse produces either a blank on the map or a
        default 'unknown' glyph, and both are worse than no symbol at all: the operator sees
        a contact whose affiliation is silently wrong rather than visibly absent.
        """
        if v is None:
            return None
        if not (len(v) == 20 and v.isdigit()):
            raise ValueError(
                f"symbol must be a 20-digit MIL-STD-2525D SIDC, got {v!r} "
                f"(length {len(v)}) — 2525C 15-character codes belong in attributes"
            )
        return v

    @model_validator(mode="after")
    def _interval(self) -> "Entity":
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(
                f"valid_to {times.render(self.valid_to)} precedes valid_from "
                f"{times.render(self.valid_from)} — an interval that runs backwards is a "
                "translation defect, not data"
            )
        return self


class GnssInterferencePayload(BaseModel):
    """The typed payload for EventType.GNSS_INTERFERENCE.

    `extra="allow"` here, unlike the canonical objects: this model's job is to give the fields
    we DO understand a checked shape while letting a source's extra fields ride along in the
    same dict. Forbidding extras here would force an adapter to split one payload across two
    places, and the never-drop rule would be satisfied by the letter while the meaning
    scattered.
    """
    model_config = ConfigDict(extra="allow")
    frequency_band: str = Field(
        min_length=1, description="GNSS band, e.g. L1, L2, L5, E1, B1 — the source's own name."
    )
    interference_type: InterferenceType
    signal_strength_dbm: float | None = Field(
        default=None,
        description="Received power in dBm, negative in practice. None = not reported; the "
                    "unit is in the field name because a bare 'signal_strength' has been read "
                    "as dBW, dBm and a 0-100 bar by three different consumers.",
    )


# event_type -> the model its payload is checked against. Registering one is a MINOR bump;
# an event_type with no entry keeps a free-form payload, which is how a new source lands
# before its shape is understood well enough to pin.
PAYLOAD_MODELS: dict[EventType, type[BaseModel]] = {
    EventType.GNSS_INTERFERENCE: GnssInterferencePayload,
}


class Event(CDMBase):
    """Anything that happens. The audit-bearing object: two timestamps and a source, always."""
    object_kind: Literal["event"] = "event"
    event_id: uuid.UUID
    event_type: EventType
    severity: Severity
    related_entities: list[uuid.UUID] = Field(
        default_factory=list,
        description="entity_id values this event concerns. Empty when the event concerns no "
                    "specific entity (a feed-level status change).",
    )
    geometry: Geometry | None = Field(
        default=None,
        description="GeoJSON, WGS84, [lon, lat] order — e.g. a jamming footprint.",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific fields. Validated against PAYLOAD_MODELS[event_type] "
                    "when one is registered; free-form otherwise. Also the never-drop bag "
                    "for events.",
    )
    observed_at: Timestamp = Field(description="When the SOURCE saw it. Never receipt time.")
    received_at: Timestamp = Field(description="When WE took delivery. Never source time.")

    @model_validator(mode="after")
    def _payload_shape(self) -> "Event":
        """Validate the payload against its registered model WITHOUT rewriting it.

        The dict stays exactly as the adapter wrote it, for three reasons: the wire form stays
        plain JSON with no discriminated union to negotiate; the exported JSON Schema stays
        readable; and extra keys survive byte-identically instead of being round-tripped
        through a model that might reorder or coerce them. Validation is a CHECK here, not a
        transformation — `typed_payload()` is where a consumer gets the parsed object.
        """
        model = PAYLOAD_MODELS.get(self.event_type)
        if model is not None:
            model.model_validate(self.payload)
        return self

    def typed_payload(self) -> BaseModel | None:
        """The parsed payload, or None when this event_type has no registered model."""
        model = PAYLOAD_MODELS.get(self.event_type)
        return None if model is None else model.model_validate(self.payload)


class TrackSample(BaseModel):
    """One position at one instant. The unit STANAG 4676 calls a track point."""
    model_config = STRICT
    position: Position
    observed_at: Timestamp


class Track(CDMBase):
    """An entity's position history, in time order. The order is a contract, not a hope.

    A scrambled sample list produces nonsense the moment anything differentiates it — speed
    from consecutive positions, a heading arrow, a predicted point. So non-decreasing
    timestamps are validated here, at the boundary, where the defect is one adapter's bug
    rather than a mystery in a fusion layer three hops downstream.

    Equal timestamps are ALLOWED: two sensors reporting the same instant is real, and
    rejecting it would refuse legitimate multi-source data.
    """
    object_kind: Literal["track"] = "track"
    track_id: uuid.UUID
    entity_id: uuid.UUID = Field(description="The Entity this history belongs to.")
    samples: list[TrackSample] = Field(
        min_length=1, description="Time-ordered, non-decreasing. At least one."
    )
    track_quality: float | None = Field(
        default=None, ge=0.0, le=1.0, description="0..1. None = not assessed, never 0."
    )

    @model_validator(mode="after")
    def _ordered(self) -> "Track":
        stamps = [s.observed_at for s in self.samples]
        for earlier, later in zip(stamps, stamps[1:]):
            if later < earlier:
                raise ValueError(
                    f"samples are not in time order: {times.render(later)} follows "
                    f"{times.render(earlier)}. Sort at the adapter — a track that runs "
                    "backwards yields a negative speed downstream"
                )
        return self


class PlanObject(CDMBase):
    """What we push OUT: a drawing a commander's plan puts on someone else's map.

    Geometry is REQUIRED here, unlike on Event. An overlay with no geometry cannot be drawn,
    so an egress adapter would have to either invent a location or silently drop the object —
    and a COA sketch that quietly fails to appear on the TAK client is the worst of the three
    outcomes, because everyone assumes it arrived.
    """
    object_kind: Literal["plan_object"] = "plan_object"
    object_id: uuid.UUID
    object_type: ObjectType
    label: str | None = Field(
        default=None, min_length=1,
        description="What a client shows next to the drawing. None = unlabelled; never an "
                    "empty string, which renders as a blank callout.",
    )
    geometry: Geometry = Field(description="GeoJSON, WGS84, [lon, lat] order. Required.")
    style: Attributes = Field(
        default_factory=dict,
        description="Rendering HINTS, not requirements — stroke, fill, opacity, dash. A "
                    "receiving client is free to ignore them, so nothing that changes MEANING "
                    "may live here (an affiliation belongs on the entity, not in a colour).",
    )
    expires_at: Timestamp | None = Field(
        default=None,
        description="When the drawing should disappear. None = until explicitly removed — "
                    "which for a stale COA sketch on a live map is a decision, so state it.",
    )


CDMObject = Annotated[
    Union[Entity, Event, Track, PlanObject], Field(discriminator="object_kind")
]

# The kinds, by their discriminator value — the harness and the schema exporter both walk this
# rather than keeping their own list, so adding a fifth kind cannot leave one of them behind.
KINDS: dict[str, type[CDMBase]] = {
    "entity": Entity,
    "event": Event,
    "track": Track,
    "plan_object": PlanObject,
}
