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
    VerticalReference,
    VerticalUnit,
)
from synapse_cdm.geo import (
    BoundingBox,
    Geometry,
    MultiPolygon,
    Polygon,
    VerticalExtent,
    VerticalPosition,
)
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


# IMPORTED HERE, NOT AT THE TOP, AND THE PLACEMENT IS THE POINT.
# `oes.py` carries the SC-OES block, and that block reuses two things declared above —
# `SourceId`, because `07-provenance-and-evidence.md` requires a SOURCE_RECORD citation to use
# the canonical source-identifier representation rather than a second one, and `Timestamp`,
# because `effective_from`/`effective_to` publish the same strict RFC 3339 pattern every other
# instant in this repository publishes. `Event` in turn needs `OesMetadata`. The two modules are
# therefore mutually dependent by construction, and one of the imports has to stand below the
# names it needs. It is this one, because `synapse_cdm/__init__.py` imports `models` before
# `oes` and a submodule import runs the package `__init__` first, so the cycle is only ever
# entered from this side.
from synapse_cdm.oes import OesMetadata, validate_ontology_identifier  # noqa: E402


class SourceHash(BaseModel):
    """A digest of the source record, as the ADAPTER computed it. Carried, never computed here.

    Rule 5 asks for "source hash where appropriate", and the appropriateness is the adapter's
    judgement: a hash of a 3-byte AIS sentence identifies nothing an external id does not, while a
    hash of a 4 MB NITF segment is how an auditor proves the bytes on the wire were the bytes
    described. So it is optional, and its absence means the adapter did not compute one.

    NO HASHING HAPPENS IN THIS PACKAGE. `tests/test_cdm_boundary.py` asserts that no module under
    `synapse_cdm/` imports `hashlib` or any crypto library, and this model does not change that:
    it is a container for a value produced outside the contract layer, exactly as `Integrity` is
    a container for a signature this package does not make. `algorithm` is therefore required and
    free-form — a digest with no algorithm cannot be reproduced by anyone, and an enum would make
    the day SHA-3 arrives a MAJOR bump for a string nobody branches on.
    """
    model_config = STRICT
    algorithm: str = Field(min_length=1, description="e.g. sha256. Named by the producer.")
    value: str = Field(min_length=1, description="The digest, in the producer's own encoding.")


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
    # ------------------------------------------------------------------ Rule 5, completed in P3
    #
    # ARCHITECTURE.md §4.5 named six items of Rule 5 that had no canonical home and told adapters
    # to park them in the residual "with a documented key" until this round landed them. These
    # seven fields are that landing. Every one is OPTIONAL, because every one is a fact some
    # sources have and others do not, and a required field would be filled with a guess by the
    # adapters that cannot read it — which is the failure `synthetic` has no default in order to
    # avoid, one field up.
    format_name: str | None = Field(
        default=None,
        description="The source STANDARD's name, e.g. 'ASTERIX'. Filled from the adapter's own "
                    "declared metadata.format; None only for an adapter that declares none.",
    )
    format_version: str | None = Field(
        default=None,
        description="The edition of that standard, e.g. 'Cat 062 ed 1.18'. None = no document "
                    "in this tree states which edition the adapter targets — a reading, never a "
                    "gap filled in.",
    )
    original_id: str | None = Field(
        default=None,
        description="The source record's OWN identifier, as a first-class provenance field. "
                    "Distinct from source_ids, which is the identity of the THING; this is the "
                    "identity of the RECORD that described it.",
    )
    source_hash: SourceHash | None = Field(
        default=None, description="Digest of the source record, computed by the adapter."
    )
    record_index: int | None = Field(
        default=None, ge=0,
        description="Which record of a multi-record payload this object came from, 0-based. "
                    "None = the payload was not a sequence, or the adapter does not track it. "
                    "Never -1 and never 0-as-unknown: 0 is the first record.",
    )
    observed_at: Timestamp | None = Field(
        default=None,
        description="The instant the SOURCE RECORD states for itself, when it states one and no "
                    "canonical field already carries it. Event.observed_at stays the event's "
                    "own time; this is the record's.",
    )
    transformations: list[str] = Field(
        default_factory=list,
        description="Rule 5's transformation chain: the TRANSFORMS reasons this adapter applied, "
                    "in the order it applied them. Empty = nothing was transformed, which is a "
                    "claim the lossless check can contradict.",
    )


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
    vertical: VerticalPosition | None = Field(
        default=None,
        description="The height AS THE SOURCE STATED IT — unit and datum carried, never "
                    "converted. `alt_m` above stays the canonical HAE-in-metres projection and "
                    "is None whenever the source's datum is not HAE.",
    )

    @model_validator(mode="after")
    def _altitude_projection(self) -> "Position":
        """`alt_m` is the canonical projection of `vertical`, and the two may not disagree.

        Two rules, and both of them exist because the alternative is a silent height error of up
        to a hundred metres:

        1. When `vertical` is HAE in metres, `alt_m` — if stated at all — must be the same
           number. A projection that disagrees with what it projects is worse than an absent one,
           because every consumer reading only `alt_m` gets a value the record itself refutes.
        2. When `vertical`'s datum is anything but HAE, `alt_m` must be None. MSL, AGL, BARO and
           FL are not metres above the ellipsoid and cannot be turned into metres above the
           ellipsoid without a geoid model, a terrain model or a pressure setting — none of which
           this package has. Rule 2 says unknown stays unknown; it does not say "close enough".

        Feet-HAE is deliberately NOT converted here either. 1000 ft HAE is 304.8 m HAE exactly,
        so the arithmetic is available — and doing it in a validator would mean this model writes
        a value no adapter stated, which is the boundary the whole class of defect lives on. An
        adapter that wants `alt_m` populated converts at the adapter, where the conversion is
        declared in TRANSFORMS and printed on every harness run.
        """
        if self.vertical is None:
            return self
        is_hae_metres = (self.vertical.reference is VerticalReference.HAE
                         and self.vertical.unit is VerticalUnit.METRES)
        if is_hae_metres:
            if self.alt_m is not None and self.alt_m != self.vertical.value:
                raise ValueError(
                    f"alt_m {self.alt_m} disagrees with vertical {self.vertical.value} m HAE. "
                    "alt_m is the canonical projection of the same height, not a second reading"
                )
        elif self.alt_m is not None:
            raise ValueError(
                f"alt_m is {self.alt_m} while vertical states {self.vertical.value} "
                f"{self.vertical.unit.value} {self.vertical.reference.value}. alt_m means metres "
                "HAE and nothing else; converting from that datum needs a model this package "
                "does not have, so alt_m stays None and `vertical` carries what the source said"
            )
        return self


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


class Period(BaseModel):
    """A closed or open-ended interval. `start` required, `end` optional and open-ended if absent.

    `start` is required and `end` is not, because that asymmetry is what the sources state: an
    activation begins at a stated instant and ends "until further notice" far more often than the
    reverse. An interval with neither bound is not a period, it is the absence of one, and the
    field holding a Period is optional for exactly that case.
    """
    model_config = STRICT
    start: Timestamp = Field(description="When the interval opens.")
    end: Timestamp | None = Field(
        default=None, description="When it closes. None = open-ended, never 'unknown'."
    )

    @model_validator(mode="after")
    def _forwards(self) -> "Period":
        if self.end is not None and self.end < self.start:
            raise ValueError(
                f"end {times.render(self.end)} precedes start {times.render(self.start)} — an "
                "interval that runs backwards is a translation defect, not data"
            )
        return self


class TemporalValidity(BaseModel):
    """The four times an object can have, separated because they answer different questions.

    §27's four, and the separation is the point:

        observed_at   when the SOURCE saw the state
        valid_from    when the state BEGAN, which may be long before anyone saw it
        valid_to      when it ceased. None = still current, never "unknown"
        effective     the period the source declares the object OPERATIVE — an airspace
                      reservation published on Monday, effective Wednesday 0600 to 1200

    An airspace restriction shows why one timestamp cannot do the work of four: it is observed
    when the NOTAM is read, valid from the moment it is published, and effective for a window
    that has not started yet. Collapsing those into "the time" is how a restriction gets drawn on
    a map twelve hours early.

    EVERY FIELD IS OPTIONAL AND THAT IS DELIBERATE. A source that states only one of the four
    says one of the four; a model that required more would be filled by adapters copying one
    instant into three fields, and three copies of one reading look like corroboration. The
    PRESENCE of this block is itself information — the source described validity in time — and
    a block with nothing in it is the absence of the block.

    §27's epoch rule, stated where it is enforced: unknown time is NOT `1970-01-01` and NOT
    `now()`. It is the absence of the field. `Timestamp` does not refuse the epoch instant, and
    that is a decision rather than an omission — 1970-01-01T00:00:00Z is a real instant, some
    sources legitimately carry it as a base epoch, and a validator that refused it would refuse
    real data in order to catch a defect that lives in the ADAPTER. The rule is therefore
    enforced where the substitution would be made, in review of the adapter and in the
    conformance suite's own reading, and it is written down here and in `docs/docs/cdm/policies`.
    """
    model_config = STRICT
    observed_at: Timestamp | None = Field(
        default=None, description="When the source saw it. None = the source did not say."
    )
    valid_from: Timestamp | None = Field(
        default=None, description="When the state began. None = the source did not say."
    )
    valid_to: Timestamp | None = Field(
        default=None, description="When it ceased. None = still current / open-ended."
    )
    effective: Period | None = Field(
        default=None, description="The period the source declares the object operative."
    )

    @model_validator(mode="after")
    def _forwards(self) -> "TemporalValidity":
        if (self.valid_from is not None and self.valid_to is not None
                and self.valid_to < self.valid_from):
            raise ValueError(
                f"valid_to {times.render(self.valid_to)} precedes valid_from "
                f"{times.render(self.valid_from)} — an interval that runs backwards is a "
                "translation defect, not data"
            )
        return self


class Waypoint(BaseModel):
    """One ordered point of a route.

    `sequence` is REQUIRED and is the route's order of record. List position would be the obvious
    alternative and it is the wrong one: a route arrives split across messages, is filtered, is
    re-sent with one leg amended, and every one of those operations preserves the numbers while
    destroying the positions. A waypoint that knows its own sequence can be reassembled; one that
    knows only where it happened to sit in an array cannot.

    `altitude_constraint` is a `VerticalPosition` rather than a bare number for §26's reason: a
    crossing restriction published as "FL240" and one published as "8000 ft MSL" are different
    constraints and the difference is in the unit and the datum, not in the number.
    """
    model_config = STRICT
    position: Position = Field(description="Where the waypoint is.")
    name: str | None = Field(
        default=None, min_length=1,
        description="The source's own designator, e.g. an ICAO fix name. None = unnamed; never "
                    "an empty string.",
    )
    sequence: int = Field(
        ge=0, description="0-based order of record. Required — see the class docstring."
    )
    eta: Timestamp | None = Field(
        default=None, description="Estimated time at this waypoint. None = not estimated."
    )
    altitude_constraint: VerticalPosition | None = Field(
        default=None, description="A crossing restriction, with its unit and datum."
    )


class RouteLeg(BaseModel):
    """One segment between two waypoints, addressed BY SEQUENCE and not by index.

    `distance_m` and `course_deg` are optional because they are the SOURCE's numbers when the
    source states them, and nothing computes them here. Two waypoints determine a great-circle
    distance, so a computed value is always available — and a computed value that disagrees with
    the source's is a second truth in the same record, with nothing to say which one a consumer
    should plan against. The source's own leg lengths often encode a procedure the geometry does
    not (a DME arc, a holding pattern), which is exactly the information a computation destroys.
    """
    model_config = STRICT
    from_seq: int = Field(ge=0, description="`sequence` of the waypoint this leg leaves.")
    to_seq: int = Field(ge=0, description="`sequence` of the waypoint this leg reaches.")
    distance_m: float | None = Field(
        default=None, ge=0.0, description="Metres, as the SOURCE states it. None = not stated."
    )
    course_deg: float | None = Field(
        default=None, ge=0.0, lt=360.0,
        description="Degrees true, [0, 360), as the source states it. None = not stated.",
    )
    attributes: Attributes = Field(
        default_factory=dict, description="Leg-specific source fields with no canonical home."
    )

    @model_validator(mode="after")
    def _not_a_loop(self) -> "RouteLeg":
        if self.from_seq == self.to_seq:
            raise ValueError(
                f"leg runs from sequence {self.from_seq} to itself. A leg joins two waypoints; a "
                "hold or an orbit at one waypoint is a property of that waypoint, not a segment"
            )
        return self


class Route(BaseModel):
    """Ordered waypoints, the legs between them, and the route's own metadata.

    At least two waypoints, because a route to one place from nowhere is a position. `sequence`
    values must be distinct — two waypoints numbered 3 make the order unrecoverable, which is the
    single thing `sequence` exists to preserve — and every leg must name sequences that exist,
    because a leg to a waypoint nobody sent is a route with a hole in it that renders as a line
    to the origin.

    Legs may be EMPTY. A source that sends points and no segments has described a route whose
    legs are the implied consecutive pairs, and manufacturing those pairs here would publish
    segments the source never stated — including, for a route the source meant as a set of
    reporting points, segments that are not flyable.
    """
    model_config = STRICT
    waypoints: list[Waypoint] = Field(
        min_length=2, description="At least two. Ordered by `sequence`, not by list position."
    )
    legs: list[RouteLeg] = Field(
        default_factory=list,
        description="Segments the SOURCE stated. Empty = the source stated none; consecutive "
                    "pairs are NOT invented here.",
    )
    metadata: Attributes = Field(
        default_factory=dict,
        description="Route-level source fields with no canonical home — a procedure name, a "
                    "flight rules letter, an airway designator.",
    )

    @model_validator(mode="after")
    def _sequences_are_a_key(self) -> "Route":
        seen: dict[int, int] = {}
        for index, waypoint in enumerate(self.waypoints):
            if waypoint.sequence in seen:
                raise ValueError(
                    f"waypoints {seen[waypoint.sequence]} and {index} both carry sequence "
                    f"{waypoint.sequence}. `sequence` is the route's order of record and a "
                    "duplicate makes that order unrecoverable"
                )
            seen[waypoint.sequence] = index
        for index, leg in enumerate(self.legs):
            for end, value in (("from_seq", leg.from_seq), ("to_seq", leg.to_seq)):
                if value not in seen:
                    raise ValueError(
                        f"leg {index}'s {end} is {value}, which no waypoint carries. Known "
                        f"sequences: {sorted(seen)}"
                    )
        return self


class Area(BaseModel):
    """A region with lateral geometry, optional vertical limits and optional time validity.

    The three together are what an airspace, a danger area, a jamming footprint and a search box
    all are, and the reason they are one model is that any two of them without the third is a
    different claim: a polygon with no ceiling is the whole column of sky above it, and a polygon
    with no validity is permanent.

    `geometry` is a `Polygon` or a `MultiPolygon` and nothing else. A point or a line is not an
    area — a corridor drawn as a line has no width, and a consumer that buffered it would be
    choosing the width itself, which is an operational decision an adapter may not make (Rule 6).
    """
    model_config = STRICT
    geometry: Polygon | MultiPolygon = Field(
        discriminator="type", description="Lateral extent. WGS84, [lon, lat]."
    )
    vertical: VerticalExtent | None = Field(
        default=None,
        description="Floor and ceiling. None = the source stated no vertical limits, which is "
                    "not the same as surface-to-unlimited (that is a VerticalExtent with both "
                    "bounds absent, and it says the source described the column).",
    )
    validity: TemporalValidity | None = Field(
        default=None, description="When the area applies. None = the source stated no times."
    )
    bounds: BoundingBox | None = Field(
        default=None,
        description="The coarse extent the SOURCE declared about this area, when it declared "
                    "one. NEVER computed from `geometry` here: a sensor's declared coverage "
                    "rectangle and its footprint's envelope are different facts and are allowed "
                    "to differ, so a computed value would overwrite one with the other.",
    )


class Quality(BaseModel):
    """How good the source says its own data is. Four ways of saying it, none derived.

    `confidence` is 0..1 and comparable across sources; `source_quality` is the source's OWN
    grade, a free string, because ASTERIX's track quality, AIS's position accuracy flag and a
    NATO track's evaluation code are three ordinal scales with no defined mapping between them
    and inventing one would be a fusion decision made inside a translator.

    `uncertainty` is a NAMED dict — `{"along_track_m": 40.0, "cross_track_m": 12.0}` — rather
    than a single number, because an error ellipse is not a radius and flattening it loses the
    orientation that made it worth sending. Names are the source's; the CDM does not fix a
    vocabulary here, and the unit belongs in the key exactly as `signal_strength_dbm` carries
    its own unit in its name.
    """
    model_config = STRICT
    source_quality: str | None = Field(
        default=None, min_length=1,
        description="The source's own grade, verbatim. None = the source stated none.",
    )
    confidence: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="0..1. None = unknown; 0 means certainty-that-not, which is a claim.",
    )
    accuracy_m: float | None = Field(
        default=None, ge=0.0, description="Metres, 1-sigma. None = unknown, never 0."
    )
    uncertainty: dict[str, float] = Field(
        default_factory=dict,
        description="Named components, e.g. along_track_m / cross_track_m. The unit is in the "
                    "key. Empty = the source named none.",
    )


class OperationalStatus(BaseModel):
    """What state the source says a thing is in, in the SOURCE's vocabulary, namespaced.

    THERE IS NO ENUM HERE AND THERE WILL NOT BE ONE. "SERVICEABLE", "DEGRADED", "MISSION CAPABLE",
    "RED" and "U/S" come from five different domains and mean five different things, and a closed
    CDM vocabulary would have to map each of them onto a member — which is a judgement about
    somebody else's operational language, made inside a translator, invisible in the output, and
    exactly what Rule 6 forbids. `namespace` says whose vocabulary `state` belongs to, so a
    consumer meeting an unfamiliar value can find out what it means instead of guessing; a
    consumer MUST NOT compare `state` across namespaces.

    `since` is when the state began, not when it was reported. Absent means the source did not
    say — never the receipt time, which would make every restart look like a state change.
    """
    model_config = STRICT
    state: str = Field(
        min_length=1, description="The source's own token, verbatim and untranslated."
    )
    namespace: str = Field(
        min_length=1,
        description="Whose vocabulary `state` is in — normally the source format's name. "
                    "Required: an unnamespaced status is a word with no owner.",
    )
    since: Timestamp | None = Field(
        default=None, description="When the state began. None = the source did not say."
    )
    attributes: Attributes = Field(
        default_factory=dict, description="Status-specific source fields with no canonical home."
    )


class Residual(BaseModel):
    """Source information the CDM does not model, kept under the name of the format it came from.

    §28's container, and its two rules are load-bearing in opposite directions:

    1. **It MUST identify its origin.** `namespace` is the source format's own name — the same
       string as the adapter's `metadata.format.name` — so a reader meeting an unfamiliar key
       inside `data` can find out which standard's vocabulary it belongs to. An unnamespaced bag
       of leftovers is the free-form dict this model exists to replace.
    2. **It MUST NOT be treated as semantically trusted merely because it survived translation.**
       A residual says "the source said this and the CDM has no home for it". It is a fact about
       the source RECORD, not an assertion about the world. A consumer MUST NOT promote a
       residual value into a canonical field, and a later adapter MUST NOT read another adapter's
       residual as an input — ARCHITECTURE.md §5 states both as normative text.

    `data` preserves the source's own STRUCTURE, which is why it is a dict and not a list of
    dotted paths: `lossless.residual()` learned that the hard way when a two-element list came
    back as two keys named `affected_constellations[0]` and `[1]`, satisfying the never-drop rule
    in the letter while destroying the reader's ability to see a list.

    THE FOURTEEN ADAPTERS IN THIS REPOSITORY DO NOT USE THIS YET, deliberately. ARCHITECTURE.md
    §5 rules that they keep their `attributes` / `payload` parking under `source_extras` through
    the whole of Part 1 and declare `residual: legacy` in their manifests, because the
    information is already preserved and paying for a placement change with every golden file and
    every downstream consumer buys nothing a reader can use (§29: no breaking change for
    stylistic cleanliness). Every Part 2 adapter declares `residual: structured` and uses this.
    """
    model_config = STRICT
    namespace: str = Field(
        min_length=1,
        description="The source format's name — normally metadata.format.name. Required.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="The unconsumed source structure, preserved as the source shaped it.",
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
    quality: Quality | None = Field(
        default=None,
        description="How good the SOURCE says this object is. None = the source said nothing "
                    "about quality, which is not the same as saying it is poor.",
    )
    status: OperationalStatus | None = Field(
        default=None,
        description="The source's own operational state for this object, namespaced. None = the "
                    "source stated none.",
    )
    residual: Residual | None = Field(
        default=None,
        description="Source information the CDM does not model, under the name of the format it "
                    "came from (§28). None = nothing was left over, or — for the fourteen "
                    "adapters shipped before this container existed — the leftovers are parked "
                    "in `attributes` / `payload` under `source_extras`, which ARCHITECTURE.md §5 "
                    "rules they keep through Part 1.",
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
    ontology_types: list[str] = Field(
        default_factory=list,
        description="Optional SC-OES semantic types — absolute ontology identifiers saying what "
                    "this thing IS in operational terms. Empty = the producer asserted none. "
                    "Never derived from entity_type, and entity_type is never derived from it.",
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

    @field_validator("ontology_types")
    @classmethod
    def _ontology_types(cls, v: list[str]) -> list[str]:
        """Each identifier valid and absolute; no duplicates; nothing rewritten.

        `entity_type` stays the closed structural classification the map renders and this stays
        the open semantic one — `09-entity-semantics.md` forbids deriving either from the other,
        so a FACILITY that is also a runway says both and neither is inferred from the other.

        Duplicates are REJECTED rather than deduplicated, on §101's rule. Silently collapsing
        them would make the record disagree with what was sent, and a producer emitting the same
        term twice has a defect it would never be shown.
        """
        seen: set[str] = set()
        for term in v:
            validate_ontology_identifier(term)
            if term in seen:
                raise ValueError(
                    f"duplicate ontology type {term!r}: identifiers are rejected rather than "
                    "deduplicated, because a set silently repaired is a defect never reported"
                )
            seen.add(term)
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
    oes: OesMetadata | None = Field(
        default=None,
        description="The SC-OES wire-semantic block. None = the producer made no SC-OES "
                    "assertion, which is NOT the producer asserting defaults. Optional so that "
                    "every object written before SC-OES existed stays structurally valid and "
                    "every producer that knows nothing about SC-OES keeps emitting objects "
                    "these models accept.",
    )

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

    @model_validator(mode="after")
    def _oes_relations(self) -> "Event":
        """The two SC-OES rules that need the EVENT, not just the block.

        Both are §80's and both are invisible one level down. A self-reference is a relation
        whose target is the citing event, which needs `event_id`; and every `entity_relations`
        subject must also appear in `related_entities`, which needs that list. The membership
        rule is the load-bearing one: `related_entities` remains the single answer to "which
        entities does this event concern", so a consumer that reads only the CDM sees every
        entity involved and a consumer that reads SC-OES sees the same set with roles attached.
        A role naming an entity the event does not otherwise relate to would make the two lists
        disagree about the event's own scope.

        References to events that are NOT locally available stay permitted, deliberately — a
        consumer holds a subset of the history by definition, and rejecting an event because its
        antecedent has not arrived would make delivery order part of the contract.
        """
        if self.oes is None:
            return self
        for relation in self.oes.event_relations:
            if relation.event_id == self.event_id:
                raise ValueError(
                    f"event relation {relation.predicate.value} points at the citing event "
                    f"{self.event_id}: an event cannot stand in a relation to itself"
                )
        related = set(self.related_entities)
        for entity_relation in self.oes.entity_relations:
            if entity_relation.entity_id not in related:
                raise ValueError(
                    f"entity relation {entity_relation.predicate} names entity "
                    f"{entity_relation.entity_id}, which is not in related_entities. A role for "
                    "an entity the event does not otherwise relate to would make the two lists "
                    "disagree about what the event concerns"
                )
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
                    "which for a stale COA sketch on a live map is a decision, so state it. "
                    "KEPT beside `validity` below, of which it is the projection: a receiving "
                    "client that only knows how to expire an overlay reads this one field.",
    )
    validity: TemporalValidity | None = Field(
        default=None,
        description="The four times the source states about this object (§27). `expires_at` "
                    "above is the projection of `validity.valid_to` for clients that read one "
                    "field; when both are stated they must agree.",
    )
    route: Route | None = Field(
        default=None,
        description="Ordered waypoints and legs, when this object IS a route "
                    "(ObjectType.ROUTE). `geometry` above stays REQUIRED and stays the LineString "
                    "projection of the waypoints, so every consumer written before routes existed "
                    "still draws it.",
    )
    area: Area | None = Field(
        default=None,
        description="Lateral geometry with vertical limits and time validity, when this object "
                    "is a region. `geometry` above stays the required projection of its lateral "
                    "extent.",
    )

    @model_validator(mode="after")
    def _expiry_projection(self) -> "PlanObject":
        """`expires_at` and `validity.valid_to` are one fact stated twice; they may not differ.

        The duplication is deliberate and is documented on both fields: a TAK client knows how to
        expire an overlay and does not know what a TemporalValidity is, so the projection has to
        stay. What must not happen is the two drifting apart, because then the drawing disappears
        at one time on the map and at another in the record, and nobody can say which was meant.
        """
        if self.validity is None or self.validity.valid_to is None or self.expires_at is None:
            return self
        if self.expires_at != self.validity.valid_to:
            raise ValueError(
                f"expires_at {times.render(self.expires_at)} disagrees with validity.valid_to "
                f"{times.render(self.validity.valid_to)}. expires_at is the projection of "
                "valid_to, not a second deadline"
            )
        return self


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
