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
