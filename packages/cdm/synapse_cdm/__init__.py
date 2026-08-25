"""The Canonical Data Model — one internal schema every adapter translates into.

WHY THIS EXISTS
---------------
Twelve integration adapters are shipped (PNTMAP GNSS alerts, TAK / Cursor-on-Target, AIS,
ADS-B 1090ES, Picogrid Legion, ASTERIX category 021, STANAG 4676 NITS, STANAG 4607 GMTI,
ASTERIX category 048 and ASTERIX category 034), with the other ASTERIX categories
(062 system tracks, 023 service status) landing next.
Without a canonical model in the middle, twelve adapters means sixty-six translations and
twelve
private notions of "a contact", and the integration layer becomes the place where meaning is
quietly lost. With one, an adapter is a thin translator and nothing else: external format in,
CDM out.

The CDM is deliberately NOT the Track contract (`synapse-data/contracts/track.schema.json`,
which lives in the SynapseCommand product repository, not here).
That contract is the datastore's fused surface picture — one object type, flat, tuned for the
map. The CDM is wider (entities, events, tracks, plan objects) and is what an ADAPTER speaks
before fusion happens. The two agree where they overlap, and the agreements they inherit are
recorded as invariants below because they were each paid for by a defect.

INHERITED INVARIANTS (from the Track contract, chapters 8-9)
------------------------------------------------------------
1. An unknown position is null, NEVER (0, 0). Coordinate zero is a real point in the Gulf of
   Guinea, so a null-to-zero defect anywhere along the path paints a contact where nothing
   exists. In the CDM this is structural: `Position` REQUIRES lat and lon, so "unknown" has
   no way to be spelled as zeros — it is spelled by the absence of a Position.
2. An unknown scalar is null, never 0. Zero is a measurement: 0 kt is measured stillness,
   0 deg is due north, confidence 0 is certainty-that-not. Every optional number here means
   "not known" when absent and "measured" when present.
3. Source sentinels are translated, not passed through. AIS says "speed unknown" with 102.3.
   An adapter that forwards that number puts a ship at 102 knots on a commander's map.

THE RULE THAT MATTERS MOST
--------------------------
Adapters never drop data. A field the CDM has no home for goes into `attributes` (entities)
or `payload` (events) — parked, not discarded. This is enforced, not requested: the harness
compares every scalar in the source payload against the CDM output and FAILS the adapter on
any value that appears nowhere. An adapter may declare a value transformed (a unit
conversion, a rounding) and the harness prints those declarations in its report, so the
exemption is visible rather than a quiet hole.

IMPORT BOUNDARY
---------------
`synapse_cdm` depends on nothing but `pydantic` and `jsonschema` — in particular nothing from
the SynapseCommand product repository (`agents/`, `core/`, `platform/`, `synapse-data/`,
`airtasking/`), which is why it could be lifted out of it into this one at all. This is the
contract layer, and a contract that depends on a consumer is not a contract: it cannot be
published, cannot be lifted into another service, and turns every change in a consumer into a
possible change in the contract. Enforced by AST in tests/test_cdm_boundary.py, the same way
agent isolation and the airtasking boundary are enforced in the repository this came from.
"""
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    InterferenceType,
    ObjectType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import (
    CDMObject,
    Entity,
    Event,
    GnssInterferencePayload,
    Integrity,
    Kinematics,
    PlanObject,
    Position,
    SourceId,
    SourceRef,
    Track,
    TrackSample,
)
from synapse_cdm.adapter import Adapter, REGISTRY, load_adapter
from synapse_cdm.version import SCHEMA_VERSION

__all__ = [
    "SCHEMA_VERSION",
    "Adapter", "REGISTRY", "load_adapter",
    "Affiliation", "EntityType", "EventType", "InterferenceType", "ObjectType",
    "PositionSource", "Severity",
    "CDMObject", "Entity", "Event", "GnssInterferencePayload", "Integrity", "Kinematics",
    "PlanObject", "Position", "SourceId", "SourceRef", "Track", "TrackSample",
]
