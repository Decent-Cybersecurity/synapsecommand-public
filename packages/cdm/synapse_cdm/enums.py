"""The CDM's closed vocabularies.

Every enum here carries UNKNOWN as a MEMBER rather than expressing it as null. That is the
Track contract's rule (`cls` is UNKNOWN in its own right, never null) and it is the right
way round: "we do not know the affiliation" is a fact worth recording and worth rendering on
a map. A null would be indistinguishable from a field the adapter forgot to fill.

Adding a member is a MINOR version bump; removing one is MAJOR. See MIGRATIONS.md.
"""
from enum import StrEnum


class EntityType(StrEnum):
    UNIT = "UNIT"
    PLATFORM = "PLATFORM"
    SENSOR = "SENSOR"
    FACILITY = "FACILITY"
    EVACUEE_GROUP = "EVACUEE_GROUP"
    INTERFERENCE_SOURCE = "INTERFERENCE_SOURCE"
    OVERLAY_OBJECT = "OVERLAY_OBJECT"
    UNKNOWN = "UNKNOWN"


class Affiliation(StrEnum):
    """Maps to MIL-STD-2525 standard identity — see models.standard_identity().

    Four members, not 2525's seven: PENDING, ASSUMED_FRIEND and SUSPECT are judgements a
    fusion layer makes, not facts an adapter can read off a wire format. An adapter that
    invented ASSUMED_FRIEND would be doing business logic, which adapters may not do.
    The source's own wording is preserved in `attributes` when it is finer than this.
    """
    FRIENDLY = "FRIENDLY"
    HOSTILE = "HOSTILE"
    NEUTRAL = "NEUTRAL"
    UNKNOWN = "UNKNOWN"


class PositionSource(StrEnum):
    """How the position was obtained. Load-bearing in a GNSS-denied environment.

    This is the field that lets a commander tell a fix from a guess. When PNTMAP reports
    jamming over an area, every GNSS-sourced position inside that area becomes suspect and
    every INERTIAL or MANUAL one does not — a distinction that is impossible to make after
    the fact if the adapter flattened them all to "position".
    """
    GNSS = "GNSS"
    INERTIAL = "INERTIAL"
    MANUAL = "MANUAL"
    ESTIMATED = "ESTIMATED"


class EventType(StrEnum):
    DETECTION = "DETECTION"
    GNSS_INTERFERENCE = "GNSS_INTERFERENCE"
    TRACK_UPDATE = "TRACK_UPDATE"
    ALERT = "ALERT"
    STATUS_CHANGE = "STATUS_CHANGE"
    PLAN_INJECT = "PLAN_INJECT"
    SIM_RESULT = "SIM_RESULT"


class Severity(StrEnum):
    INFO = "INFO"
    ADVISORY = "ADVISORY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class InterferenceType(StrEnum):
    """JAMMING denies, SPOOFING deceives, and the difference decides the response.

    Kept distinct from UNKNOWN deliberately: a receiver that has lost lock knows it is being
    jammed, whereas a receiver reporting a plausible but false position does not know it is
    being spoofed. An adapter that cannot tell says UNKNOWN rather than guessing JAMMING.
    """
    JAMMING = "JAMMING"
    SPOOFING = "SPOOFING"
    UNKNOWN = "UNKNOWN"


class ObjectType(StrEnum):
    """What we push OUT — the egress direction, e.g. to TAK as a drawing object."""
    COA_SKETCH = "COA_SKETCH"
    ROUTE = "ROUTE"
    CONTROL_MEASURE = "CONTROL_MEASURE"
    ANNOTATION = "ANNOTATION"


class VerticalUnit(StrEnum):
    """The unit a `VerticalPosition` states its number in. §26's "value plus unit", closed.

    Three members and no UNKNOWN, which is a departure from this module's opening paragraph and
    is the unit policy rather than an oversight. §26 forbids "ambiguous naked numeric fields
    where unit ambiguity matters"; a vertical measurement whose unit nobody knows IS that naked
    number wearing a wrapper, and recording it would let a consumer render 300 as metres when
    the source meant feet. An adapter that cannot read the unit therefore has no vertical
    position to state — it parks the raw number in the residual, where nothing reads it as a
    height. Absence is expressible (the whole `VerticalPosition` is optional); an unknown unit
    is not, deliberately.

    `FL` is a unit as well as a reference because a flight level IS its own scale: FL350 is
    "35000 feet on the 1013.25 hPa isobaric surface", a number that is neither metres nor feet
    above anything on the ground. Converting it needs the local pressure, which the adapter does
    not have, so it is carried as it was stated.
    """
    METRES = "m"
    FEET = "ft"
    FLIGHT_LEVEL = "FL"


class VerticalReference(StrEnum):
    """What a `VerticalPosition` is measured FROM. The datum, never assumed.

    The six here are the ones the formats in scope actually state. HAE is the WGS84 ellipsoid —
    what a GNSS receiver computes natively and what `Position.alt_m` has always meant. MSL is a
    geoid model, and the separation between the two reaches 100 m in places, so a silent
    substitution moves an aircraft by more than its own vertical separation minimum. AGL is
    height above the terrain beneath the object, which is not a datum at all but a difference,
    and is therefore not convertible to either of the others without a terrain model. BARO is an
    altimeter reading against a stated or unstated pressure setting; FL is BARO against the
    standard setting.

    UNKNOWN is a MEMBER, unlike `VerticalUnit`'s absent one, and the asymmetry is the point: a
    number with no unit cannot be rendered at all, whereas a number whose datum is unstated can
    still be shown to an operator beside the words "reference unknown". That is a worse fix than
    a referenced one and a far better one than a fix silently labelled MSL.
    """
    HAE = "HAE"
    MSL = "MSL"
    AGL = "AGL"
    BARO = "BARO"
    FL = "FL"
    UNKNOWN = "UNKNOWN"
