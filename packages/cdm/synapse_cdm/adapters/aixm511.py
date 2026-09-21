"""AIXM 5.1.1 (EUROCONTROL & FAA, April 2016) -> CDM. Adapter #19, ingest-only,
`residual: structured`: the five feature families of the bounded profile, one canonical object
per TIME SLICE, every source assertion kept with its temporal basis and nothing resolved.

WHAT A TIME SLICE BECOMES
-------------------------
An AIXM data set (`message:AIXMBasicMessage`) is a list of features, and a feature is a
`gml:identifier` (a UUID that never changes) plus time slices, each of which asserts a set of
property values under an interpretation for a validity period. The adapter is stateless and
translates the ASSERTIONS, not a resolved state: every time slice of a feature in the five
families becomes one `Entity` whose identity is the feature's and whose `valid_from` /
`valid_to` are the slice's `gml:validTime`; a later slice of the same feature is a second state
of the same entity, never a second entity. The typed reading of the slice — feature and slice
identity, interpretation, sequence and correction numbers, validTime and featureLifetime with
the begin-included/end-excluded convention, every pinned property as a `PropertyState` that
keeps ABSENT, NIL, UNCHANGED and WITHDRAWN apart, geometry read under its stated CRS and axis
order, vertical limits with unit and reference and the unknown/unlimited distinction, schedules
as typed Timesheets, references with their form and resolution — is `attributes["aixm"]`, the
`aixm-timeslice/1` contract (`TimeSliceBlock`, a pydantic model a consumer validates).

    Airspace          Entity(OVERLAY_OBJECT, position None); and, when the slice states a
                      horizontal projection in the pinned forms with BASE components only, a
                      PlanObject(CONTROL_MEASURE) beside it whose `area` carries the polygon(s),
                      the vertical extent where the limits project onto the CDM's units and
                      datums, and the slice's validity. The PlanObject's id is derived from the
                      same identifier under its own kind, so a new BASELINE replaces the drawing
                      rather than adding one; the Entity names it in `plan_object_id`.
    AirportHeliport   Entity(FACILITY), position from the ARP ElevatedPoint (MSL elevation in
                      `vertical`, `alt_m` None because MSL is not HAE), availability typed.
    Runway            Entity(FACILITY), no position (a Runway's geometry is its RunwayElements,
                      outside the profile); designator, type, dimensions, the airport reference.
    RunwayDirection   Entity(FACILITY), no position; designator, bearings, TDZ elevation, the
                      ManoeuvringAreaAvailability structures a closure is stated in.
    Navaid            Entity(FACILITY), position from `location`; NavaidOperationalStatus typed;
                      component equipment and served airport / runway direction references.
    VerticalStructure Entity(FACILITY); every part typed with its stated height (`verticalExtent`,
                      an extent with a unit and no datum — the model states none) and its
                      location, linear or surface extent; `position` only when exactly one part
                      states a point location and none states another form.

A feature outside the five families (a Unit, an OrganisationAuthority …) gets the GENERIC
reading only: an Entity of type UNKNOWN with the feature and slice identity, the interpretation
and numbers, validTime and featureLifetime typed and every property in the residual — no
position, no status, nothing inferred; `validate_source` names it. A member that is not a
feature (no `aixm:timeSlice`) is carried whole in every object's residual at its position.

TEMPORALITY (AIXM Temporality Concept 1.1)
------------------------------------------
`valid_from` is the validTime's begin (a TimePeriod) or its instant (a TimeInstant);
`valid_to` the period's end when it is an instant, None when it is `indeterminatePosition=
"unknown"` (§4.4.2's open baseline). A slice with NO validTime — §4.4.8's cancellation, an
empty property with `nilReason="inapplicable"` — states no instant of its own, so an Entity
(which needs `valid_from`) can be built only under a caller's `AsOf(instant, basis)`; without
one the document is refused naming the slice, and nothing is stamped with the clock or the
epoch. The interpretation drives the reading of every pinned property (§4.4.6.1): under
PERMDELTA/TEMPDELTA an absent property means UNCHANGED and a nil one WITHDRAWN; under
BASELINE/SNAPSHOT they mean NOT STATED and NIL. Nothing here resolves a delta against a
baseline: that is the separate resolver (Phase 5), which takes explicit prior state.

REFERENCES
----------
`xlink:href` is resolved against the document (`urn:uuid:` by identifier, `#id` by gml:id) and
against the caller's `references` table, one hop, never over a network; every reference is kept
with its property, href, form and target, and the unresolved ones are listed on the block and
named by `validate_source`.

GEOMETRY AND VERTICAL
---------------------
The codec's readers (`aixm_codec`): two CRS URNs with their axis order, the pinned Point /
Curve / Surface forms, holes as interior rings. An unsupported form — an arc, a circle, a
composite or orientable curve, another CRS, a third dimension — REFUSES the document by default
(`GeometryUnsupported`, naming the element and the source text); under
`Aixm511Adapter(unsupported_geometry="report")` the slice is still an Entity with the form named
in its block and no PlanObject. A composition of volumes (`operation` UNION / INTERS / SUBTR) or
BASE volumes whose limits differ is REPORTED the same way: every component is typed, no Area is
drawn, because the CDM Area is one volume and composing one would be a derivation. Vertical
limits project onto `VerticalExtent` only where the CDM has the unit and the datum — FT/M
against SFC/MSL/W84/STD → AGL/MSL/HAE/BARO, FL against STD → FL — and are otherwise carried
typed with the reason; UNL/GND/FLOOR/CEILING are tokens and stay tokens. Nothing is converted.

PARSER LIMITS
-------------
`secure_xml.parse` with the three declared bounds (octets before a parser exists, depth and
elements on the element that crosses them; DTDs, entities, external references and XInclude
refused there); a parsed twin is held to `max_depth` by the base class; the time-slice count is
read before any object is built.
"""
from __future__ import annotations

import copy
import dataclasses
import json
from typing import Any, ClassVar, Literal, Mapping

from synapse_cdm import ids, lossless, secure_xml, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import aixm_codec as codec
from synapse_cdm.adapters.aixm_codec import (
    Contract, CurveReading, DocumentIndex, Elevation, FeatureIdentity, GeometryUnsupported,
    PointReading, PropertyState, Reference, ReferenceTarget, SurfaceReading, TimePrimitive,
    Timesheet, VerticalLimit,
)
from synapse_cdm.adapters.geojson import AsOf
from synapse_cdm.enums import (
    Affiliation, EntityType, ObjectType, PositionSource, VerticalReference, VerticalUnit,
)
from synapse_cdm.geo import VerticalExtent, VerticalPosition
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import (
    Area, CDMBase, Entity, OperationalStatus, Period, PlanObject, Position,
    Residual as ResidualBlock, SourceId, TemporalValidity,
)

SYSTEM = "AIXM"
VERSION = codec.VERSION_511
CONTRACT = "aixm-timeslice/1"

#: IMPLEMENTATION CAPS, declared in the manifest with their basis. 16 MiB admits a Digital NOTAM
#: message or an AIRAC delta many times over; a national baseline is a data set, not a message.
AIXM511_MAX_INPUT_BYTES = 16 * 1024 * 1024
AIXM511_MAX_DEPTH = 192
AIXM511_MAX_ELEMENTS = 500_000
AIXM511_MAX_OBJECTS = 20_000
XML_LIMITS = secure_xml.XmlLimits(max_bytes=AIXM511_MAX_INPUT_BYTES, max_depth=AIXM511_MAX_DEPTH,
                                  max_elements=AIXM511_MAX_ELEMENTS)


class ObjectCountExceeded(ValueError):
    """More time slices than `AIXM511_MAX_OBJECTS`, refused before any object is built."""


# ------------------------------------------------------------------ the five families, pinned

#: Feature element -> (family name, time-slice element, EntityType, pinned simple properties).
#: Every property name is the schema's own (`AIXM_Features.xsd`, the family's TimeSliceType).
FAMILIES: dict[str, tuple[str, str, EntityType, tuple[str, ...]]] = {
    "aixm:Airspace": ("Airspace", "aixm:AirspaceTimeSlice", EntityType.OVERLAY_OBJECT,
                      ("type", "designator", "name", "localType", "designatorICAO", "controlType",
                       "upperLowerSeparation")),
    "aixm:AirportHeliport": ("AirportHeliport", "aixm:AirportHeliportTimeSlice", EntityType.FACILITY,
                             ("designator", "name", "locationIndicatorICAO", "designatorIATA", "type",
                              "certifiedICAO", "privateUse", "controlType", "fieldElevation",
                              "fieldElevationAccuracy", "verticalDatum", "magneticVariation",
                              "abandoned")),
    "aixm:Runway": ("Runway", "aixm:RunwayTimeSlice", EntityType.FACILITY,
                    ("designator", "type", "nominalLength", "lengthAccuracy", "nominalWidth",
                     "widthAccuracy", "abandoned")),
    "aixm:RunwayDirection": ("RunwayDirection", "aixm:RunwayDirectionTimeSlice", EntityType.FACILITY,
                             ("designator", "trueBearing", "trueBearingAccuracy", "magneticBearing",
                              "elevationTDZ", "elevationTDZAccuracy")),
    "aixm:Navaid": ("Navaid", "aixm:NavaidTimeSlice", EntityType.FACILITY,
                    ("type", "designator", "name", "flightChecked", "purpose", "signalPerformance")),
    "aixm:VerticalStructure": ("VerticalStructure", "aixm:VerticalStructureTimeSlice", EntityType.FACILITY,
                               ("name", "type", "lighted", "markingICAOStandard", "group", "length",
                                "width", "radius", "lightingICAOStandard", "synchronisedLighting")),
}
#: The generic reading of a feature outside the five families: no pinned property, no position,
#: no status; identity and the time slice only. `EntityType.UNKNOWN` is the CDM's own word for a
#: thing whose structural class is none of the others, and nothing about the feature is inferred.
OTHER_FAMILY: tuple[str, str | None, EntityType, tuple[str, ...]] = ("other", None, EntityType.UNKNOWN, ())
#: The union — the properties the MAPPINGS ledger binds at slice level whatever the family.
PINNED_SIMPLE: tuple[str, ...] = tuple(sorted({p for _, _, _, props in FAMILIES.values() for p in props}))

#: Reference properties at slice level, by family: single-valued and repeatable.
REFERENCES_SINGLE: dict[str, tuple[str, ...]] = {
    "Airspace": ("protectedRoute",), "Runway": ("associatedAirportHeliport",),
    "RunwayDirection": ("usedRunway", "startingElement"), "AirportHeliport": (), "Navaid": (),
    "VerticalStructure": (),
}
REFERENCES_MANY: dict[str, tuple[str, ...]] = {
    "Navaid": ("runwayDirection", "servedAirport"), "Airspace": (), "AirportHeliport": (),
    "Runway": (), "RunwayDirection": (), "VerticalStructure": (),
}
ALL_REFERENCES_SINGLE = tuple(sorted({p for v in REFERENCES_SINGLE.values() for p in v}))
ALL_REFERENCES_MANY = tuple(sorted({p for v in REFERENCES_MANY.values() for p in v}))

#: The schedule-bearing structures a status is stated in, by family: (property, object element,
#: status property, the other simple properties typed beside it).
SCHEDULED: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "Airspace": ("aixm:activation", "aixm:AirspaceActivation", "status", ("activity",)),
    "AirportHeliport": ("aixm:availability", "aixm:AirportHeliportAvailability", "operationalStatus",
                        ("warning",)),
    "RunwayDirection": ("aixm:availability", "aixm:ManoeuvringAreaAvailability", "operationalStatus",
                        ("warning",)),
    "Navaid": ("aixm:availability", "aixm:NavaidOperationalStatus", "operationalStatus", ("signalType",)),
}
STATUS_CODE_TYPE = {"Airspace": "CodeStatusAirspaceType", "AirportHeliport": "CodeStatusAirportType",
                    "RunwayDirection": "CodeStatusAirportType", "Navaid": "CodeStatusNavaidType"}

PART_PROPERTIES = ("verticalExtent", "verticalExtentAccuracy", "type", "constructionStatus",
                   "markingPattern", "markingFirstColour", "markingSecondColour", "mobile",
                   "frangible", "visibleMaterial", "designator")
NAVAID_COMPONENT_PROPERTIES = ("collocationGroup", "markerPosition", "providesNavigableLocation")
VOLUME_LIMITS = (("upper", "aixm:upperLimit", "aixm:upperLimitReference"),
                 ("lower", "aixm:lowerLimit", "aixm:lowerLimitReference"),
                 ("maximum", "aixm:maximumLimit", "aixm:maximumLimitReference"),
                 ("minimum", "aixm:minimumLimit", "aixm:minimumLimitReference"))
#: The complex slice elements the MAPPINGS ledger binds residual-kind at slice level WHATEVER
#: the family — its keys walk `hasMember[_].timeSlice[_]` and cannot see the feature element.
#: The schema puts `location` in 17 property groups and `availability` in 23 (NavaidEquipment,
#: SpecialNavigationStation, Taxiway, RouteSegment, …), so a slice outside the family that types
#: one still carries it. Such an element is CARRIED at the same block field: its source
#: verbatim, its identity and the schema-common parts read (a point by value, a schedule's
#: timesheets), nothing family-specific inferred and no Entity.position or status derived from
#: it (D41). A repeatable one stated ONCE on such a slice is a dict in the twin (the family
#: tables alone list a single item), which the ledger's `[*]` key does not reach: it stays in
#: the residual at its position. Otherwise the ledger would claim leaves at the field and find
#: them in the residual — LOST on a Donlon NavaidEquipment feature, which is how this was found.
CARRIED_ELEMENTS: tuple[tuple[str, str], ...] = (
    ("aixm:geometryComponent", "geometry_components"), ("aixm:activation", "activation"),
    ("aixm:availability", "availability"), ("aixm:part", "parts"),
    ("aixm:navaidEquipment", "navaid_equipment"), ("aixm:location", "location"), ("aixm:ARP", "arp"))


# ------------------------------------------------------ the Digital NOTAM Event binding, pinned

#: The Event feature of the Digital NOTAM Event Schema 2.0.m (`event:Event`, substitution group
#: `aixm:AbstractAIXMFeature`): its time slices are `event:timeSlice` / `event:EventTimeSlice`
#: (extending `aixm:AbstractAIXMTimeSliceType`, so the interpretation, numbers, validTime and
#: featureLifetime are the AIXM-namespace ones every slice carries). One Entity per slice, as for
#: every feature; `EntityType.UNKNOWN` because the CDM has no structural class for an operational
#: situation and nothing is inferred from one. The pinned simple properties are the
#: `EventPropertyGroup`'s scalars (`summary` is XHTML and stays in the residual whatever its shape).
EVENT_FEATURE = "event:Event"
EVENT_TIME_SLICE = "event:EventTimeSlice"
EVENT_TIME_SLICE_PROPERTY = "event:timeSlice"
EVENT_FAMILY: tuple[str, str, EntityType, tuple[str, ...]] = (
    "Event", EVENT_TIME_SLICE, EntityType.UNKNOWN,
    ("name", "designator", "scenario", "version", "estimatedValidity", "activity"))
EVENT_REFERENCES_SINGLE = ("parentEvent", "causeEvent", "provider")
EVENT_REFERENCES_MANY = ("concernedAirspace", "concernedAirportHeliport")
#: The NOTAM message object's scalars typed beside its verbatim source (`event:NOTAM`,
#: `AISMessagePropertyGroup` + `NOTAMPropertyGroup`); `type` is N / R / C — the text NOTAM's own
#: word for new / replacement / cancellation, which the typed source assertion reads.
NOTAM_PROPERTIES = ("series", "number", "year", "issued", "processed", "type", "referredSeries",
                    "referredNumber", "referredYear", "affectedFIR", "selectionCode", "traffic",
                    "purpose", "scope", "minimumFL", "maximumFL", "coordinates", "radius", "location",
                    "effectiveStart", "effectiveEnd", "estimatedEnd", "permanent", "text")
#: The NavaidEquipment specialisations NAV.UNS binds beside the Navaid (Event_Features.xsd declares
#: an `event:<Class>Extension` for each; the scenario page's editorial note lists them).
NAVAID_EQUIPMENT_FEATURES = ("aixm:Azimuth", "aixm:DME", "aixm:DirectionFinder", "aixm:Elevation",
                             "aixm:Glidepath", "aixm:Localizer", "aixm:MarkerBeacon", "aixm:NDB",
                             "aixm:SDF", "aixm:TACAN", "aixm:VOR")
DNOTAM_SPECIFICATION = "Digital NOTAM Specification 2.0 (DRAFT — 'in preparation', validated by implementation; EUROCONTROL/FAA, swim-eurocontrol.atlassian.net/wiki/spaces/DNOTAM)"
DNOTAM_EVENT_SCHEMA = "AIXM 5.1.1 Event Schema 2.0.m (June 2025; namespace http://www.aixm.aero/schema/5.1.1/event; permitted base: AIXM 5.1.1 April 2016)"
DNOTAM_CONTRACT = "aixm-dnotam/1"


class ScenarioProfile(Contract):
    """One pinned Digital NOTAM coding scenario: its identifier and version as the guidance
    spells them, the page and page version they were read from, the rule identifiers, the
    features a bound TEMPDELTA may sit on and the status structure it must state."""

    id: str
    version: str
    family: str
    specification: str = DNOTAM_SPECIFICATION
    status: Literal["DRAFT"] = "DRAFT"
    guidance_page: str
    guidance_page_version: str
    rules: list[str]
    affected_features: list[str]
    status_element: str
    status_property: str
    #: ANY bound slice's status structure must state one of these (None: no such requirement).
    required_status: list[str] | None = None
    #: EVERY stated status must be one of these (None: no such requirement).
    permitted_status: list[str] | None = None
    #: No stated status may be one of these.
    forbidden_status: list[str] = []


#: The three scenario families of master §7, resolved to the guidance's own identifiers on
#: 2026-09-20 (decision D3). "Airspace activation/reservation or availability change" is two
#: identifiers in the guidance — published ATS airspace and published special activity area —
#: and both are pinned. Every identifier is at scenario version 2.0; the specification is a
#: DRAFT and is never described here as an approved final standard. Rule ids are the pages' own
#: (RWY.CLS and NAV.UNS renumbered to `<ID>.nn`; ATSA.ACT and SAA.ACT still `ER-nn`).
#: The REMARK text ATSA.ACT ER-04, SAA.ACT ER-06 and NAV.UNS.08 attach to every AirspaceActivation
#: / NavaidOperationalStatus the encoder copies from the BASELINE "for completeness sake" (the
#: TEMPDELTA replaces the whole property list, so the unchanged times are restated in it). Such a
#: copy restates the baseline's own status — the pinned DN_ATSA.ACT_2 example carries the
#: baseline's AVBL_FOR_ACTIVATION under it — and is not the change's assertion, so the status
#: rules do not judge it; the copy is still translated and kept like every other structure.
BASELINE_COPY_REMARK = "Baseline data copy. Not included in the NOTAM text generation"

SCENARIO_PROFILES: dict[str, ScenarioProfile] = {
    "RWY.CLS": ScenarioProfile(
        id="RWY.CLS", version="2.0", family="runway closure/unavailability",
        guidance_page="220791360", guidance_page_version="v30, 2025-12-09",
        rules=["RWY.CLS.01", "RWY.CLS.02", "RWY.CLS.03", "RWY.CLS.04", "RWY.CLS.05", "RWY.CLS.06"],
        affected_features=["aixm:RunwayDirection"], status_element="aixm:ManoeuvringAreaAvailability",
        status_property="operationalStatus", required_status=["CLOSED"]),
    "ATSA.ACT": ScenarioProfile(
        id="ATSA.ACT", version="2.0", family="airspace activation/reservation or availability change (published ATS airspace)",
        guidance_page="220791511", guidance_page_version="v35, 2025-09-25",
        rules=["ER-01", "ER-02", "ER-03", "ER-04", "ER-05", "ER-06"],
        affected_features=["aixm:Airspace"], status_element="aixm:AirspaceActivation",
        status_property="status", permitted_status=["ACTIVE", "INACTIVE"]),
    "SAA.ACT": ScenarioProfile(
        id="SAA.ACT", version="2.0", family="airspace activation/reservation or availability change (published special activity area)",
        guidance_page="220791162", guidance_page_version="v57, 2023-09-19",
        rules=["ER-01", "ER-02", "ER-03", "ER-04", "ER-05", "ER-06", "ER-07", "ER-08", "ER-09"],
        affected_features=["aixm:Airspace"], status_element="aixm:AirspaceActivation",
        status_property="status", required_status=["ACTIVE", "IN_USE", "INTERMITTENT"]),
    "NAV.UNS": ScenarioProfile(
        id="NAV.UNS", version="2.0", family="navaid outage/unavailability",
        guidance_page="220791463", guidance_page_version="v35, 2026-03-20",
        rules=["NAV.UNS.01", "NAV.UNS.02", "NAV.UNS.03", "NAV.UNS.04", "NAV.UNS.05", "NAV.UNS.06",
               "NAV.UNS.07", "NAV.UNS.08", "NAV.UNS.10", "NAV.UNS.11"],
        affected_features=["aixm:Navaid", *NAVAID_EQUIPMENT_FEATURES], status_element="aixm:NavaidOperationalStatus",
        status_property="operationalStatus", forbidden_status=["FALSE_POSSIBLE", "CONDITIONAL", "DISPLACED"]),
}
#: What the manifest declares, one string per profile, generated so it cannot drift.
SCENARIO_PROFILE_DECLARATIONS = [
    f"{p.specification.split(' (')[0]} scenario {p.id} version {p.version} (DRAFT guidance, page "
    f"{p.guidance_page} {p.guidance_page_version}; rules {p.rules[0]}–{p.rules[-1]}) on {DNOTAM_EVENT_SCHEMA.split(' (')[0]}"
    for p in SCENARIO_PROFILES.values()]


class NotamReading(Contract):
    """One `event:notification` item: the NOTAM's scalars typed, the object verbatim."""
    nil: bool = False
    element: str | None = None
    gml_id: str | None = None
    properties: dict[str, PropertyState] = {}
    source: Any


class SourceAssertion(Contract):
    """What ONE time slice asserts about the Event's or the feature's temporary state, read
    from the slice alone: its kind under the Temporality Concept and the guidance's "Event
    update or cancellation" page, and its temporal basis as stated. Nothing here is resolved
    against another slice — that is `aixm_resolve`."""

    #: `initial`: the first slice of a sequence (correction 0 or none). `correction`: a later
    #: correction of the same sequence (§3.6 — the highest correction number is the valid one;
    #: TS_017 admits only an end-of-validity change on an active slice). `cancellation`: a
    #: correction whose validTime is empty with nilReason (§4.4.8 — the sequence is taken off the
    #: timeline, the record stays). `termination`: an Event correction carrying a NOTAM of type C
    #: (immediate termination). `replacement`: an Event slice carrying a NOTAM of type R.
    kind: Literal["initial", "correction", "cancellation", "termination", "replacement"]
    basis: str
    interpretation: str
    sequence_number: int | None = None
    correction_number: int | None = None
    valid_time_form: str
    effective_from: str | None = None
    effective_to: str | None = None
    #: True when the end is `indeterminatePosition="unknown"` (an open temporary change).
    end_open: bool = False
    #: `featureLifetime` end of an Event slice — the Event's end of life.
    lifetime_end: str | None = None
    #: The Event states `estimatedValidity` or a NOTAM says `estimatedEnd` YES: the end is an
    #: estimate, not a stated expiry.
    estimated_end: bool = False
    notam_types: list[str] = []
    convention: str = codec.PERIOD_CONVENTION


class DigitalNotamBlock(Contract):
    """`attributes["dnotam"]` on a slice the Event extension binds: the Event's own slices
    (`role="event"`) and any feature slice whose `aixm:extension` carries `event:theEvent`
    (`role="affected-feature"`). Absent on every other slice."""

    contract: Literal["aixm-dnotam/1"] = DNOTAM_CONTRACT
    event_schema: str = DNOTAM_EVENT_SCHEMA
    role: Literal["event", "affected-feature"]
    #: role event: the scenario identifier and version the slice states, and the pinned profile
    #: they name (None with `profile_finding` when they name none).
    scenario: PropertyState | None = None
    scenario_version: PropertyState | None = None
    profile: ScenarioProfile | None = None
    profile_finding: str | None = None
    notifications: list[NotamReading] = []
    #: role affected-feature: the binding as stated — the extension element, its gml:id and the
    #: `theEvent` reference (resolved in the document or the caller's table, or kept unresolved) —
    #: and the scenario the Event it names states, when that Event is in the document.
    extension_element: str | None = None
    extension_gml_id: str | None = None
    the_event: Reference | None = None
    event_scenario: str | None = None
    assertion: SourceAssertion
    #: The scenario RULE layer's findings on this slice (the schema layer is `normative_validation`).
    rule_findings: list[str] = []


# ------------------------------------------------------------------------- the profile

@dataclasses.dataclass(frozen=True)
class Profile:
    """What differs between AIXM versions on the SAME reading: the namespaces, the pinned
    property paths per family, the schedule-bearing structures, the part and component
    properties, the carried elements, the parser limits and whether the Digital NOTAM Event
    binding exists for the version. `AixmAdapterBase._translate` and `_SliceReader` read
    everything version-specific from here and nothing from a module global, so
    `adapters/aixm52.py` is a second profile on the same reader rather than a copy of it, and
    a 5.2 structure that differs from 5.1.1 is mapped by its own table row, never by a
    namespace substitution (phase 6, decision D56)."""

    version: codec.Version
    adapter_class: str
    families: Mapping[str, tuple[str, str, EntityType, tuple[str, ...]]]
    references_single: Mapping[str, tuple[str, ...]]
    references_many: Mapping[str, tuple[str, ...]]
    scheduled: Mapping[str, tuple[str, str, str, tuple[str, ...]]]
    status_code_type: Mapping[str, str]
    part_properties: tuple[str, ...]
    navaid_component_properties: tuple[str, ...]
    carried_elements: tuple[tuple[str, str], ...]
    max_objects: int
    xml_limits: secure_xml.XmlLimits
    digital_notam: bool

    @property
    def pinned_simple(self) -> tuple[str, ...]:
        """The union — the properties the MAPPINGS ledger binds at slice level whatever the family."""
        return tuple(sorted({p for _, _, _, props in self.families.values() for p in props}))

    @property
    def references_single_all(self) -> tuple[str, ...]:
        return tuple(sorted({p for v in self.references_single.values() for p in v}))

    @property
    def references_many_all(self) -> tuple[str, ...]:
        return tuple(sorted({p for v in self.references_many.values() for p in v}))


PROFILE_511 = Profile(
    version=VERSION, adapter_class="Aixm511Adapter", families=FAMILIES,
    references_single=REFERENCES_SINGLE, references_many=REFERENCES_MANY, scheduled=SCHEDULED,
    status_code_type=STATUS_CODE_TYPE, part_properties=PART_PROPERTIES,
    navaid_component_properties=NAVAID_COMPONENT_PROPERTIES, carried_elements=CARRIED_ELEMENTS,
    max_objects=AIXM511_MAX_OBJECTS, xml_limits=XML_LIMITS, digital_notam=True)


# ---------------------------------------------------------------------- the typed contract

class SliceIdentity(Contract):
    element: str
    gml_id: str | None = None
    interpretation: str
    sequence_number: int | None = None
    correction_number: int | None = None
    valid_time: TimePrimitive
    feature_lifetime: TimePrimitive
    valid_from_basis: str
    temporality_problems: list[str] = []


class UnsupportedGeometry(Contract):
    kind: str
    element: str | None = None
    reason: str
    source: Any = None


class ContributorReading(Contract):
    dependency: PropertyState
    airspace: Reference | None = None


class VolumeReading(Contract):
    gml_id: str | None = None
    upper: VerticalLimit
    lower: VerticalLimit
    maximum: VerticalLimit
    minimum: VerticalLimit
    width: PropertyState
    horizontal_projection: SurfaceReading | None = None
    horizontal_projection_state: PropertyState
    centreline: CurveReading | None = None
    centreline_state: PropertyState
    unsupported: list[UnsupportedGeometry] = []
    contributor: ContributorReading | None = None


class GeometryComponentReading(Contract):
    nil: bool = False
    operation: PropertyState
    operation_sequence: PropertyState
    volume: VolumeReading | None = None
    source: Any


class ScheduledStatus(Contract):
    element: str | None = None
    nil: bool = False
    gml_id: str | None = None
    properties: dict[str, PropertyState] = {}
    time_interval: list[Timesheet] = []
    source: Any


class LocatedPoint(Contract):
    point: PointReading | None = None
    elevation: Elevation | None = None
    unsupported: UnsupportedGeometry | None = None
    #: The property's verbatim content: the ElevatedPoint's dict, or whatever else the source
    #: stated there (a reference, a distance, a repeated property's list) when `unsupported`.
    source: Any


class PartReading(Contract):
    nil: bool = False
    gml_id: str | None = None
    properties: dict[str, PropertyState] = {}
    location: PointReading | None = None
    location_elevation: Elevation | None = None
    linear_extent: CurveReading | None = None
    surface_extent: SurfaceReading | None = None
    unsupported: list[UnsupportedGeometry] = []
    time_interval: list[Timesheet] = []
    source: Any


class NavaidComponentReading(Contract):
    nil: bool = False
    gml_id: str | None = None
    properties: dict[str, PropertyState] = {}
    equipment: Reference | None = None
    source: Any


class TimeSliceBlock(Contract):
    """`attributes["aixm"]` on every Entity: the typed reading of ONE time slice."""

    contract: Literal["aixm-timeslice/1"] = "aixm-timeslice/1"
    aixm_version: str
    feature: FeatureIdentity
    time_slice: SliceIdentity
    properties: dict[str, PropertyState]
    geometry_components: list[GeometryComponentReading] = []
    volume_projection: str | None = None
    plan_object_id: str | None = None
    activation: list[ScheduledStatus] = []
    availability: list[ScheduledStatus] = []
    arp: LocatedPoint | None = None
    location: LocatedPoint | None = None
    parts: list[PartReading] = []
    navaid_equipment: list[NavaidComponentReading] = []
    references: dict[str, Reference | list[Reference]] = {}
    unresolved_references: list[str] = []
    as_of: dict | None = None
    notes: list[str] = []


# ------------------------------------------------------------------------- the ledger

_F = "message:hasMember[_]"
_S = _F + ".aixm:timeSlice[_]"
_E = _F + "." + EVENT_TIME_SLICE_PROPERTY + "[_]"
_B = "entity:attributes.aixm."
_D = "entity:attributes.dnotam."


def _m(to: str, rule: str = "identity", **params: Any) -> lossless.Mapping:
    return lossless.Mapping(to=to, rule=rule, params=params)


def _r(to: str) -> lossless.Mapping:
    return lossless.Mapping(to=to, kind="residual")


def _position_keys(source: str, dest: str) -> dict:
    return {source: _m(dest + ".text", "text"), source + ".#text": _m(dest + ".text", "text"),
            source + ".@indeterminatePosition": _m(dest + ".indeterminate", "text"),
            source + ".@frame": _m(dest + ".frame", "text")}


def _primitive_keys(source: str, dest: str) -> dict:
    out = {source + ".$": _m(dest + ".element"), source + ".@gml:id": _m(dest + ".gml_id", "text"),
           source + ".@nilReason": _m(dest + ".nil_reason", "text")}
    out.update(_position_keys(source + ".gml:beginPosition", dest + ".begin"))
    out.update(_position_keys(source + ".gml:endPosition", dest + ".end"))
    out.update(_position_keys(source + ".gml:timePosition", dest + ".time"))
    return out


def _reference_keys(source: str, dest: str) -> dict:
    return {source + ".@xlink:href": _m(dest + ".href", "text"),
            source + ".@xlink:title": _m(dest + ".title", "text"),
            source + ".@nilReason": _m(dest + ".nil_reason", "text")}


def _build_mappings(profile: Profile = PROFILE_511) -> dict:
    m: dict[str, Any] = {
        _S + ".$": _m(_B + "time_slice.element"),
        _S + ".@gml:id": _m(_B + "time_slice.gml_id", "text"),
        _S + ".aixm:interpretation": _m(_B + "time_slice.interpretation", "text"),
        _S + ".aixm:sequenceNumber": _m(_B + "time_slice.sequence_number", "numeric_text"),
        _S + ".aixm:correctionNumber": _m(_B + "time_slice.correction_number", "numeric_text"),
    }
    m.update(_primitive_keys(_S + ".gml:validTime", _B + "time_slice.valid_time"))
    m.update(_primitive_keys(_S + ".aixm:featureLifetime", _B + "time_slice.feature_lifetime"))
    for prop in profile.pinned_simple:
        source, dest = f"{_S}.aixm:{prop}", f"{_B}properties.{prop}"
        m[source] = _m(dest + ".value", "text")
        m[source + ".#text"] = _m(dest + ".value", "text")
        m[source + ".@uom"] = _m(dest + ".uom", "text")
        m[source + ".@nilReason"] = _m(dest + ".nil_reason", "text")
        m[source + ".@xsi:nil"] = _m(dest + ".state", "enum_map", table={"true": "nil", "1": "nil"})
    for prop in profile.references_single_all:
        m.update(_reference_keys(f"{_S}.aixm:{prop}", f"{_B}references.{prop}"))
    for prop in profile.references_many_all:
        m.update(_reference_keys(f"{_S}.aixm:{prop}[*]", f"{_B}references.{prop}[*]"))
    for prop, field in profile.carried_elements:
        many = prop not in ("aixm:location", "aixm:ARP")
        m[_S + "." + prop + ("[*]" if many else "")] = _r(_B + field + ("[*].source" if many else ".source"))
    if not profile.digital_notam:
        m[""] = _r("*:residual.data")
        return m
    # The Event feature's slices: `event:timeSlice[_]`, the same identity and temporality leaves
    # (AIXM-namespace on an EventTimeSlice too), the EventPropertyGroup scalars, its references,
    # the NOTAM objects verbatim under the dnotam block.
    m.update({
        _E + ".$": _m(_B + "time_slice.element"),
        _E + ".@gml:id": _m(_B + "time_slice.gml_id", "text"),
        _E + ".aixm:interpretation": _m(_B + "time_slice.interpretation", "text"),
        _E + ".aixm:sequenceNumber": _m(_B + "time_slice.sequence_number", "numeric_text"),
        _E + ".aixm:correctionNumber": _m(_B + "time_slice.correction_number", "numeric_text"),
    })
    m.update(_primitive_keys(_E + ".gml:validTime", _B + "time_slice.valid_time"))
    m.update(_primitive_keys(_E + ".aixm:featureLifetime", _B + "time_slice.feature_lifetime"))
    for prop in EVENT_FAMILY[3]:
        source, dest = f"{_E}.event:{prop}", f"{_B}properties.{prop}"
        m[source] = _m(dest + ".value", "text")
        m[source + ".#text"] = _m(dest + ".value", "text")
        m[source + ".@uom"] = _m(dest + ".uom", "text")
        m[source + ".@nilReason"] = _m(dest + ".nil_reason", "text")
        m[source + ".@xsi:nil"] = _m(dest + ".state", "enum_map", table={"true": "nil", "1": "nil"})
    for prop in EVENT_REFERENCES_SINGLE:
        m.update(_reference_keys(f"{_E}.event:{prop}", f"{_B}references.{prop}"))
    for prop in EVENT_REFERENCES_MANY:
        m.update(_reference_keys(f"{_E}.event:{prop}[*]", f"{_B}references.{prop}[*]"))
    m[_E + ".event:notification[*]"] = _r(_D + "notifications[*].source")
    m[""] = _r("*:residual.data")
    return m


# ---------------------------------------------------------------------------- the adapter

class AixmAdapterBase(Adapter):
    """The reading every AIXM version shares, parameterised by `PROFILE` (phase 6): the twin
    from the guarded parse, the document walk, one Entity per time slice through `_SliceReader`.
    Abstract — it registers no name; a concrete adapter sets its identity, metadata, `PROFILE`
    and `MAPPINGS`, and defines its own `to_cdm` so the base class's input-bound wrapper is
    installed on it (`adapter._bind_input_bound` wraps the class that DEFINES `to_cdm`)."""

    abstract = True
    system = SYSTEM
    PROFILE: ClassVar[Profile]

    #: Nothing a source states changes value in translation: a posList is carried verbatim
    #: beside the positions it denotes, feet stay feet, instants are the text stated.
    TRANSFORMS: dict[str, str] = {}

    def __init__(self, clock=None, *, synthetic: bool = True, as_of: AsOf | None = None,
                 references: Mapping[str, ReferenceTarget | Mapping[str, Any]] | None = None,
                 unsupported_geometry: Literal["refuse", "report"] = "refuse") -> None:
        """`as_of` is the instant a slice with no validTime instant is read at (D26's class,
        from the GeoJSON adapter). `references` maps UUID text (any case) to the feature it
        names, for hrefs the document does not hold. `unsupported_geometry` is the policy for
        forms outside the profile. Each is part of §6.1's determinism tuple; none is inferred."""
        super().__init__(clock, synthetic=synthetic)
        if as_of is not None and not isinstance(as_of, AsOf):
            raise TypeError("as_of must be an AsOf(instant, basis)")
        if unsupported_geometry not in ("refuse", "report"):
            raise ValueError("unsupported_geometry is 'refuse' or 'report'")
        table: dict[str, ReferenceTarget] = {}
        for key, value in (references or {}).items():
            if not codec.UUID_PATTERN.fullmatch(str(key)):
                raise ValueError(f"a references key is the UUID text of a gml:identifier, not {key!r}")
            target = value if isinstance(value, ReferenceTarget) else ReferenceTarget(
                **{**dict(value), "where": "table"})
            if target.where != "table":
                target = target.model_copy(update={"where": "table"})
            table[str(key).lower()] = target
        self._as_of = as_of
        self._references = table
        self._unsupported = unsupported_geometry

    # ------------------------------------------------------------------------------ ingest

    def _ingest(self, raw: bytes | dict) -> list[CDMBase]:
        problems: list[str] = []
        return self._translate(self._as_twin(raw), problems)

    def detect(self, raw: bytes | dict) -> bool | None:
        """The root element and its namespace only; nothing below it is read for the answer."""
        try:
            twin = self._as_twin(raw)
        except Exception:                                      # noqa: BLE001 - "not mine"
            return False
        return isinstance(twin, dict) and "message:hasMember" in twin

    def validate_source(self, raw: bytes | dict) -> list[str]:
        """Structural problems and the profile's findings: temporality coding rules
        (TS_001–TS_006, TS_012, TS_016, TS_020), duplicate identities, unresolved references,
        members outside the families, unsupported or composite geometry, slices needing an as-of
        context. Normative schema validation is `normative_validation`, not this."""
        problems: list[str] = []
        try:
            twin = self._as_twin(raw)
        except Exception as e:                                 # noqa: BLE001 - reported, not raised
            return [f"{type(e).__name__}: {e}"]
        try:
            self._translate(twin, problems)
        except Exception as e:                                 # noqa: BLE001 - reported, not raised
            problems.append(f"{type(e).__name__}: {e}")
        return problems

    def _as_twin(self, raw: bytes | dict) -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, memoryview, str)):
            octets = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
            if octets.lstrip(b"\xef\xbb\xbf").lstrip()[:1] == b"{":
                document = json.loads(octets)
                if not isinstance(document, dict):
                    raise ValueError("an AIXM parsed twin is a JSON object holding the "
                                     "AIXMBasicMessage's content")
                return document
            profile = self.PROFILE
            return codec.twin_of(secure_xml.parse(octets, profile.xml_limits).root, profile.version)
        raise TypeError(f"AIXM adapter takes XML bytes, a JSON twin or a parsed dict, got "
                        f"{type(raw).__name__}")

    # -------------------------------------------------------------------------- the document

    def _translate(self, twin: dict, problems: list[str]) -> list[CDMBase]:
        profile = self.PROFILE
        if not isinstance(twin, dict) or "message:hasMember" not in twin:
            raise ValueError("an AIXM twin is the content of message:AIXMBasicMessage and carries "
                             f"message:hasMember; found {sorted(twin) if isinstance(twin, dict) else twin!r}")
        members = twin["message:hasMember"]
        if not isinstance(members, list):
            raise ValueError("message:hasMember in a twin is a list (REPEATABLE), not "
                             f"{type(members).__name__}")
        slices_total = 0
        typed: list[tuple[int, dict, tuple]] = []
        for position, member in enumerate(members):
            name = codec.object_name(member) if isinstance(member, dict) else None
            slices = member.get("aixm:timeSlice") if isinstance(member, dict) else None
            if profile.digital_notam and name == EVENT_FEATURE:
                # The Digital NOTAM Event: its slices are `event:timeSlice`, typed like any
                # feature's, plus the `dnotam` block (the scenario, the NOTAMs, the assertion).
                family = EVENT_FAMILY
                slices = member.get(EVENT_TIME_SLICE_PROPERTY)
                if not isinstance(slices, list):
                    raise ValueError(f"member {position} <{name}> carries no {EVENT_TIME_SLICE_PROPERTY} list")
            elif name in profile.families:
                family = profile.families[name]
                if not isinstance(slices, list):
                    raise ValueError(f"member {position} <{name}> carries no aixm:timeSlice list")
            elif name is not None and isinstance(slices, list):
                # A feature outside the five families: the GENERIC reading (identity, time-slice
                # identity, validTime, featureLifetime) and nothing else typed; see the docstring.
                family = OTHER_FAMILY
                problems.append(f"member {position} <{name}> is outside the five pinned families; "
                                "typed generically (identity and time slice only), its properties "
                                "in the residual")
            else:
                if not profile.digital_notam and name == "{" + codec.EVENT_511_NAMESPACE + "}Event":
                    # A Digital NOTAM Event of the AIXM 5.1.1 Event Schema inside a document of a
                    # version no Event schema exists for (decision D3): named, carried, not read.
                    problems.append(f"member {position} is a Digital NOTAM event:Event of the AIXM 5.1.1 "
                                    f"Event Schema ({codec.EVENT_511_NAMESPACE}); no Event schema exists "
                                    f"for AIXM {profile.version.name}, so it is carried whole in the "
                                    "residual and nothing of it is typed (limitation "
                                    "digital-notam-not-available)")
                    continue
                problems.append(f"member {position} <{name or type(member).__name__}> is not an AIXM "
                                "feature (no aixm:timeSlice); carried in the residual, no canonical object")
                continue
            slices_total += len(slices)
            if slices_total > profile.max_objects:
                raise ObjectCountExceeded(
                    f"the document carries more than {profile.max_objects} time slices "
                    f"(AIXM{profile.version.name.replace('.', '')}_MAX_OBJECTS); refused at member "
                    f"{position} before any object is built")
            typed.append((position, member, family))
        if not typed:
            raise ValueError("the document carries no AIXM feature (no member with an aixm:timeSlice "
                             "list); nothing here is typed by this adapter, and an empty translation "
                             "would drop the members it does carry")
        index = DocumentIndex.of(members)
        problems.extend(index.duplicates)
        events = _index_events(typed, problems) if profile.digital_notam else {}
        consumed_all: set[tuple] = set()
        for position, member, _ in typed:
            consumed_all.add(("message:hasMember", position))
        stamp = self.source_ref()
        objects: list[CDMBase] = []
        record = 0
        for position, member, family in typed:
            identifier, code_space = codec.read_identifier(member)
            if identifier is None or not codec.UUID_PATTERN.fullmatch(identifier.strip()):
                raise ValueError(f"member {position} <{member['$']}> carries no gml:identifier UUID "
                                 f"(found {identifier!r}); identity is derived from it and nothing "
                                 "else, so the feature cannot be translated (limitation "
                                 "identifier-required)")
            feature = FeatureIdentity(element=member["$"], family=family[0], gml_id=member.get("@gml:id"),
                                      identifier=identifier, identifier_code_space=code_space)
            seen: set[tuple] = set()
            slice_prop = EVENT_TIME_SLICE_PROPERTY if family is EVENT_FAMILY else "aixm:timeSlice"
            for s, slice_node in enumerate(member[slice_prop]):
                where = f"member {position} <{member['$']}> {identifier} slice {s}"
                if not isinstance(slice_node, dict) or "$" not in slice_node or (
                        family[1] is not None and slice_node["$"] != family[1]):
                    raise ValueError(f"{where}: {slice_prop} holds "
                                     f"<{codec.object_name(slice_node)}>, not {family[1] or 'a time slice object'}")
                consumed: set[tuple] = set(consumed_all)
                consumed.discard(("message:hasMember", position))
                for other in range(len(member[slice_prop])):
                    if other != s:
                        consumed.add(("message:hasMember", position, slice_prop, other))
                reading = _SliceReader(self, twin, position, member, s, slice_node, feature,
                                       family, index, consumed, problems, where, slice_prop, events).read()
                key = (reading.block.time_slice.interpretation, reading.block.time_slice.sequence_number,
                       reading.block.time_slice.correction_number)
                if key[0] != "SNAPSHOT":
                    if key in seen:
                        problems.append(f"{where}: TS_005 — a second {key[0]} slice with sequenceNumber "
                                        f"{key[1]} and correctionNumber {key[2]}")
                    seen.add(key)
                objects.extend(reading.objects(stamp, record))
                record += 1
        return objects


class Aixm511Adapter(AixmAdapterBase):
    name = "aixm511"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM
    PROFILE = PROFILE_511

    #: Adapter API v2's declaration (ARCHITECTURE.md §3). Licence class from the XSD package's
    #: own header: BSD-style, © 2016 EUROCONTROL & FAA, redistribution with the notice permitted
    #: (`xsd_pin.json`, `usage_rights`); the schema closure is held outside the repository.
    metadata = AdapterMetadata(
        id="aixm511",
        name="AIXM 5.1.1",
        adapter_version="1.0.0",
        format=FormatRef(name="AIXM", version="5.1.1 (XML Schema, April 2016; GML 3.2.1; "
                                              "AIXM Temporality Concept 1.1)"),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today. The harness's "
                  "`translate`, `schema` and `provenance` checks are PASS on every fixture of "
                  "this adapter (L1 to L3). Its `lossless` column rests on the PATH-BOUND LEDGER: "
                  "this adapter declares `MAPPINGS` for every leaf it types — feature and slice "
                  "identity, interpretation, sequence and correction numbers, validTime and "
                  "featureLifetime positions, every pinned simple property with its uom and "
                  "nilReason, every reference's href — and residual-kind mappings for the "
                  "complex structures it reads (geometry components, activation, availability, "
                  "parts, navaid components, ARP, location), each carried verbatim beside its "
                  "typed reading, with everything else in the structured residual at its own "
                  "position; the ledger reports no LOST leaf on any fixture. L4 is NOT declared: "
                  "the adapter is ingest-only and emits nothing, so `roundtrip` (E) is the "
                  "declared inapplicability of a translator with no egress, not a passed check "
                  "(ARCHITECTURE.md §3.6, rule 4). Normative validation of every positive fixture "
                  "against the pinned XSD closure is "
                  "tests/test_cdm_aixm511_adapter.py::test_every_positive_fixture_validates_against_the_pinned_schema, "
                  "which records BLOCKED_EXTERNAL_EVIDENCE rather than passing when the resource or "
                  "the `validate` extra is absent.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        #: The Digital NOTAM scenario profiles this adapter reads (phase 5): the guidance's own
        #: identifiers and versions, generated from `SCENARIO_PROFILES` so the manifest cannot
        #: name a scenario the module does not pin. The guidance is a DRAFT and is declared so.
        profiles=SCENARIO_PROFILE_DECLARATIONS,
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "AIXMBasicMessage / Airspace time slices — type, designator, name, geometry "
                "components (AirspaceVolume limits with references, horizontalProjection in the "
                "pinned Surface forms, contributor airspace), activation with schedules; one "
                "Entity per slice and a CONTROL_MEASURE PlanObject with an Area when the slice "
                "states a projectable BASE geometry; ingest",
                "AIXMBasicMessage / AirportHeliport time slices — designators, ICAO/IATA codes, "
                "type, field elevation, ARP ElevatedPoint, availability (operationalStatus, "
                "warning, schedules); one FACILITY Entity per slice; ingest",
                "AIXMBasicMessage / Runway and RunwayDirection time slices — designators, type, "
                "dimensions, bearings, TDZ elevation, the airport / runway / starting element "
                "references, ManoeuvringAreaAvailability (closures) with schedules; one FACILITY "
                "Entity per slice; ingest",
                "AIXMBasicMessage / Navaid time slices — type, designator, name, location "
                "ElevatedPoint, NavaidOperationalStatus with schedules, component equipment, "
                "served airport and runway direction references; one FACILITY Entity per slice; "
                "ingest",
                "AIXMBasicMessage / VerticalStructure time slices — name, type, lighting and "
                "marking flags, dimensions, every part with its verticalExtent and its point, "
                "linear or surface horizontal projection; one FACILITY Entity per slice; ingest",
                "AIXMBasicMessage / event:Event time slices (Digital NOTAM Event Schema 2.0.m on "
                "AIXM 5.1.1) — name, designator, scenario, version, estimatedValidity, activity, "
                "concernedAirspace / concernedAirportHeliport / parentEvent / causeEvent / provider "
                "references, every NOTAM notification typed beside its source, the pinned scenario "
                "profile (RWY.CLS, ATSA.ACT, SAA.ACT, NAV.UNS at 2.0) and the slice's source "
                "assertion (initial, correction, cancellation, termination, replacement) with its "
                "temporal basis; one UNKNOWN Entity per slice with `attributes.dnotam` "
                "(aixm-dnotam/1); and, on any feature slice whose aixm:extension carries "
                "event:theEvent, the binding, the Event's scenario and the scenario rule layer's "
                "findings; ingest",
            ],
            limits=Limits(
                max_input_bytes=AIXM511_MAX_INPUT_BYTES,
                max_depth=AIXM511_MAX_DEPTH,
                max_objects=AIXM511_MAX_OBJECTS,
                max_decompressed_bytes=None,
                max_parse_seconds=None,
                absent_because={
                    "max_decompressed_bytes":
                        "this adapter accepts no archived or compressed payload, so there is "
                        "no expansion to bound",
                    "max_parse_seconds":
                        "no wall-clock bound is enforced by this adapter; the conformance "
                        "suite's parser worker kills a decode that overruns its deadline, and "
                        "the byte, depth, element and object bounds make every walk in this "
                        "module linear in a bounded input",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "AIXM 5.1.1 states no maximum document size. 16 MiB "
                            "(`AIXM511_MAX_INPUT_BYTES`, `adapters/aixm511.py`) is chosen on "
                            "2026-09-21: a Digital NOTAM event message is under 100 KiB, an AIRAC "
                            "delta of one aerodrome under 1 MiB, and the largest fixture in "
                            "`fixtures/aixm511/` is under 16 KiB; a national baseline data set is "
                            "larger and is a data set, not a message. This is an IMPLEMENTATION "
                            "CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused before "
                            "any decoder in this module runs; `secure_xml.parse` reads the same "
                            "bound off the octets again before it creates a parser"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "AIXM 5.1.1 states no maximum nesting; a polygon ring's posList inside "
                            "an airspace volume sits 20 elements below the root in the pinned "
                            "forms (an interior Ring of curves, 22), the deepest XML shipped under "
                            "`fixtures/aixm511/` nests 22 and the deepest JSON twin 16 containers. "
                            "192 (`AIXM511_MAX_DEPTH`, `adapters/aixm511.py`) is chosen on "
                            "2026-09-21 by the repository's rule of at least eight times the "
                            "deepest shipped document, with room. This is an IMPLEMENTATION CAP "
                            "and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`secure_xml.parse` counts the depth in expat's StartElementHandler "
                            "and refuses on the element that crosses the bound, before the rest "
                            "of the document is read; a parsed twin (a dict) is held to the same "
                            "bound by `Adapter.__init_subclass__`'s `enforce_depth_bound` before "
                            "`to_cdm` runs"),
                        test="tests/test_cdm_aixm511_adapter.py::test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "AIXM 5.1.1 states no maximum feature or time-slice count. 20 000 "
                            "(`AIXM511_MAX_OBJECTS`, `adapters/aixm511.py`) time slices per "
                            "message, chosen on 2026-09-21 as an AIRAC delta with room to spare. A "
                            "second cap the manifest schema has no field for is declared beside "
                            "it: `AIXM511_MAX_ELEMENTS` (500 000), the elements across the "
                            "document, refused by `secure_xml.parse` on the element that crosses "
                            "it. This is an IMPLEMENTATION CAP and is NOT the format's normative "
                            "maximum."),
                        enforced_at=(
                            "`Aixm511Adapter.to_cdm` counts the time slices of every member on the "
                            "twin and raises `ObjectCountExceeded` (a `ValueError`) before any "
                            "canonical object is built"),
                        test="tests/test_cdm_aixm511_adapter.py::test_the_object_bound_admits_a_message_at_it_and_refuses_one_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "an element or attribute this adapter does not type — a property outside the "
                "pinned set, an aixm:extension, an aixm:annotation, every property of a feature "
                "outside the five families, any foreign-namespace member — is kept in the structured residual at "
                "its own path and position (`residual.data` is the parsed twin minus what the "
                "typed block consumed); `validate_source` names members outside the families"),
        ),
        limitations=[
            Limitation(
                id="pinned-families",
                summary="the five families are Airspace, AirportHeliport, Runway, RunwayDirection, "
                        "Navaid and VerticalStructure, plus the Digital NOTAM event:Event (its own "
                        "reading, limitation digital-notam-profiles); a feature of any other class (Unit, "
                        "OrganisationAuthority, Route, Procedure …) becomes an Entity of type UNKNOWN "
                        "carrying the GENERIC reading only — identity, interpretation, sequence and "
                        "correction numbers, validTime, featureLifetime, the pinned simple properties "
                        "the slice happens to state, and the ledger-bound complex elements "
                        "(`CARRIED_ELEMENTS`: location, ARP, a repeated availability — or a single one "
                        "on the eleven NavaidEquipment classes NAV.UNS binds, whose time-slice types "
                        "list it — activation, part, navaidEquipment, geometryComponent) carried "
                        "source-verbatim at their "
                        "block field — with every other property in the residual and no position or "
                        "status, and `validate_source` names it; a member that is not a feature at "
                        "all (no aixm:timeSlice) is carried whole in the residual. Within a family "
                        "only the pinned properties are typed (the implementation record lists "
                        "them); the rest is residual",
                unsupported_paths=[],
            ),
            Limitation(
                id="digital-notam-profiles",
                summary="Digital NOTAM is read on the AIXM 5.1.1 + Event Schema 2.0.m combination only "
                        "(Event 2.0.k and 2.0.l accept the same documents; 1.0 / 2.0.f / 2.0.j do not; "
                        "no Event schema targets AIXM 5.2). The pinned scenario profiles are exactly "
                        "RWY.CLS, ATSA.ACT, SAA.ACT and NAV.UNS at scenario version 2.0 of the Digital "
                        "NOTAM Specification 2.0, which is a DRAFT ('in preparation', validated by "
                        "implementation) and is never described as an approved final standard; an "
                        "Event stating any other scenario is typed and carried with "
                        "`profile_finding` and no scenario rule is checked. The rule layer holds a "
                        "bound slice to the rules it can be held to on its own — the binding rule "
                        "(TEMPDELTA on a feature class the profile names) and the status rule "
                        "(RWY.CLS.03, ER-01/ER-02, NAV.UNS.04) on the change's own structures; a "
                        "structure carrying the REMARK 'Baseline data copy. Not included in the "
                        "NOTAM text generation' (ATSA.ACT ER-04, SAA.ACT ER-06, NAV.UNS.08) restates "
                        "the baseline and is kept, not judged — as findings, never repairs; the "
                        "schema layer is normative_validation. NOTHING is resolved by this adapter: "
                        "correction, cancellation, replacement and expiry are typed as the slice's "
                        "own source assertion, and the resolved view at an instant is "
                        "`synapse_cdm.aixm_resolve`, which takes explicit prior state. The "
                        "event extension on a feature slice is read and not consumed (it stays in "
                        "the residual at its position)",
                unsupported_paths=[],
            ),
            Limitation(
                id="unsupported-geometry-refused",
                summary="gml:ArcByCenterPoint, gml:CircleByCenterPoint, gml:Arc, gml:ArcString, "
                        "gml:Circle, gml:CompositeCurve, gml:OrientableCurve, a CRS other than "
                        "urn:ogc:def:crs:EPSG::4326 and urn:ogc:def:crs:OGC:1.3:CRS84, and a third "
                        "dimension refuse the document by default with the element form and the "
                        "source text named; under `Aixm511Adapter(unsupported_geometry='report')` "
                        "the slice is an Entity with the form named in `attributes.aixm` and no "
                        "PlanObject. No arc is replaced by a chord and no circle by a polygon",
                unsupported_paths=[],
            ),
            Limitation(
                id="composite-volumes-not-drawn",
                summary="an Airspace whose geometry components use UNION, INTERS or SUBTR, or whose "
                        "BASE components state different vertical limits, is typed component by "
                        "component and produces no PlanObject: the CDM Area is one volume and "
                        "composing one would be a derivation the source did not state. "
                        "`volume_projection` on the block says why; `validate_source` names it",
                unsupported_paths=[],
            ),
            Limitation(
                id="vertical-projection-by-member",
                summary="a vertical limit projects onto the CDM only where a VerticalUnit and a "
                        "VerticalReference exist for it (FT/M against SFC/MSL/W84/STD, FL against "
                        "STD); SM, a flight level against another reference, an unstated uom and "
                        "the tokens UNL/GND/FLOOR/CEILING are carried typed with the reason they "
                        "are not projected. Feet are never converted to metres and no datum is "
                        "converted",
                unsupported_paths=[],
            ),
            Limitation(
                id="cancelled-slice-needs-as-of",
                summary="a time slice with no validTime instant of its own (§4.4.8's cancellation "
                        "with nilReason='inapplicable', an absent validTime, an indeterminate "
                        "begin) can be an Entity only under `Aixm511Adapter(as_of=AsOf(instant, "
                        "basis))`, whose instant becomes `valid_from` with the basis in "
                        "`source.transformations`; without it the document is refused naming the "
                        "slice. Nothing is stamped with the clock or the epoch",
                unsupported_paths=[],
            ),
            Limitation(
                id="identifier-required",
                summary="a feature of a pinned family without a gml:identifier is refused: identity "
                        "is derived from the UUID the feature carries across documents (Feature "
                        "Identification and Reference 1.0 §2.1), and a document-local gml:id would "
                        "make the same feature two entities in two documents",
                unsupported_paths=[],
            ),
            Limitation(
                id="references-one-hop",
                summary="xlink:href is resolved against the document and the caller's `references` "
                        "table, one hop, never over a network; a URL is classified and not "
                        "fetched; unresolved references are kept with their property, href and "
                        "form under `attributes.aixm.references` and listed in "
                        "`unresolved_references`",
                unsupported_paths=[],
            ),
            Limitation(
                id="schedules-not-resolved",
                summary="Timesheets, activation and availability structures are carried as typed "
                        "validity, never resolved to instants; `status` on an Entity is set only "
                        "when the slice states exactly one such structure and it carries no "
                        "timeInterval, so an unconditional status is never asserted from a "
                        "scheduled one",
                unsupported_paths=[],
            ),
            "positions carry `position_source: MANUAL` — a surveyed, published coordinate is none "
            "of GNSS, INERTIAL or ESTIMATED — with the MSL elevation of an ElevatedPoint in "
            "`vertical` (its uom kept, reference MSL by the model's own definition of `elevation`) "
            "and `alt_m` None because MSL is not height above the ellipsoid",
            "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
            "untracked and unpackaged. `evidence.available` is false because no published "
            "Release carries this adapter's records yet; it becomes true at the first release "
            "that attaches them",
            "of §3.5's five resource limits this adapter enforces THREE — `max_input_bytes` by "
            "the base class before decode and again by `secure_xml` before a parser exists, "
            "`max_depth` and `max_objects` in this module before any object is built — plus an "
            "element count the manifest schema has no field for. The other two are absent with "
            "their reasons in `capabilities.limits.absent_because`",
            "XML is parsed with the standard library's expat through `secure_xml` and NOT with "
            "`defusedxml`, which is not a dependency of this package: a DOCTYPE is refused at "
            "its declaration before any entity is read, every entity reference other than the "
            "five predefined ones is refused, no external resource is fetched and XInclude is "
            "refused where it starts (`tests/test_cdm_secure_xml.py`). The tree is "
            "`xml.etree.ElementTree`'s own, built through its TreeBuilder",
            "this adapter reads AIXM 5.1.1 only: a document in the 5.1 or 5.2 namespace is "
            "refused at the root with its namespace named; AIXM 5.2 is a sibling adapter",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    MAPPINGS = _build_mappings(PROFILE_511)

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        return self._ingest(raw)


# -------------------------------------------------------------------------- one time slice

class _EventInfo:
    """One Event feature of the document, as the scenario rules need it: where it sits and the
    scenario identifier and version its slices state."""

    def __init__(self, member_index: int, scenario: str | None, version: str | None) -> None:
        self.member_index, self.scenario, self.version = member_index, scenario, version


def _index_events(typed: list[tuple[int, dict, tuple]], problems: list[str]) -> dict[str, _EventInfo]:
    """Every `event:Event` member by lower-cased identifier. The scenario and version are read
    from the slices that state them; slices of one Event that disagree are reported and the
    first stated value kept (a scenario is a property of the Event, not of a slice)."""
    events: dict[str, _EventInfo] = {}
    for position, member, family in typed:
        if family is not EVENT_FAMILY:
            continue
        identifier, _ = codec.read_identifier(member)
        if not identifier:
            continue
        scenarios: list[str] = []
        versions: list[str] = []
        for node in member.get(EVENT_TIME_SLICE_PROPERTY, []):
            if not isinstance(node, dict):
                continue
            for key, bucket in (("event:scenario", scenarios), ("event:version", versions)):
                try:
                    value = codec.scalar(node.get(key))
                except ValueError:
                    continue
                if value.present and value.text not in bucket:
                    bucket.append(value.text or "")
        for label, bucket in (("scenario", scenarios), ("version", versions)):
            if len(bucket) > 1:
                problems.append(f"member {position} <{EVENT_FEATURE}> {identifier}: its slices state "
                                f"{len(bucket)} different event:{label} values {bucket}; the first is "
                                "the one the scenario rules are applied under")
        events[identifier.strip().lower()] = _EventInfo(position, scenarios[0] if scenarios else None,
                                                         versions[0] if versions else None)
    return events


def _is_baseline_copy(structure: dict) -> bool:
    """True when the structure carries the guidance's copy REMARK (BASELINE_COPY_REMARK) on one
    of its aixm:Note annotations: a baseline restatement, not the change's own status."""
    for note in codec.as_list(structure, "aixm:annotation"):
        if not (isinstance(note, dict) and note.get("$") == "aixm:Note"):
            continue
        for translated in codec.as_list(note, "aixm:translatedNote"):
            if not (isinstance(translated, dict) and translated.get("$") == "aixm:LinguisticNote"):
                continue
            try:
                text = codec.scalar(translated.get("aixm:note"))
            except ValueError:
                continue
            if text.present and (text.text or "").strip().rstrip(".") == BASELINE_COPY_REMARK:
                return True
    return False


class _SliceResult:
    def __init__(self, block: TimeSliceBlock, entity_kwargs: dict, plan_kwargs: dict | None,
                 residual: dict, notes: list[str], dnotam: DigitalNotamBlock | None = None) -> None:
        self.block, self.entity_kwargs, self.plan_kwargs = block, entity_kwargs, plan_kwargs
        self.residual, self.notes, self.dnotam = residual, notes, dnotam

    def objects(self, stamp, record: int) -> list[CDMBase]:
        block = self.block
        identity = f"{block.feature.identifier}/{block.time_slice.interpretation}/" \
                   f"{'-' if block.time_slice.sequence_number is None else block.time_slice.sequence_number}/" \
                   f"{'-' if block.time_slice.correction_number is None else block.time_slice.correction_number}"
        source = stamp.model_copy(update={
            "original_id": block.time_slice.gml_id or identity, "record_index": record,
            "transformations": list(self.notes)})
        source_ids = [SourceId(system=SYSTEM, external_id=block.feature.identifier or ""),
                      SourceId(system=SYSTEM, external_id=identity)]
        residual = ResidualBlock(namespace="AIXM", data=self.residual)
        attributes = {"aixm": block.model_dump(mode="json")}
        if self.dnotam is not None:
            attributes["dnotam"] = self.dnotam.model_dump(mode="json")
        entity = Entity(source=source, source_ids=source_ids, residual=residual,
                        attributes=attributes, **self.entity_kwargs)
        out: list[CDMBase] = [entity]
        if self.plan_kwargs is not None:
            out.append(PlanObject(source=source, source_ids=source_ids, residual=residual,
                                  **self.plan_kwargs))
        return out


class _SliceReader:
    """Reads one time slice into its block, its Entity arguments and — for an Airspace with a
    drawable volume — its PlanObject arguments, recording every consumed twin path so the
    residual is exactly the rest."""

    def __init__(self, adapter: AixmAdapterBase, twin: dict, position: int, member: dict, s: int,
                 node: dict, feature: FeatureIdentity, family: tuple, index: DocumentIndex,
                 consumed: set[tuple], problems: list[str], where: str,
                 slice_prop: str = "aixm:timeSlice", events: Mapping[str, _EventInfo] | None = None) -> None:
        self.adapter, self.twin, self.position, self.member, self.s = adapter, twin, position, member, s
        self.profile = adapter.PROFILE
        self.node, self.feature, self.family, self.index = node, feature, family, index
        self.consumed, self.problems, self.where = consumed, problems, where
        self.events: Mapping[str, _EventInfo] = events or {}
        self.notes: list[str] = []
        #: The CARRIED_ELEMENTS a family reading typed on this slice; the rest are carried.
        self.typed_elements: set[str] = set()
        self.rel = ("message:hasMember", position, slice_prop, s)

    # -- consumption bookkeeping

    def take(self, *path: Any) -> None:
        self.consumed.add(self.rel + path)

    def take_scalar(self, prop: str) -> None:
        """A simple property: its text or its `#text` and the three attributes the reading
        carries; any other attribute stays in the residual."""
        node = self.node.get(prop)
        if node is None:
            return
        if isinstance(node, dict):
            for key in ("#text", "@uom", "@nilReason", "@xsi:nil"):
                if key in node:
                    self.take(prop, key)
        else:
            self.take(prop)

    def take_reference(self, prop: str, index: int | None = None) -> None:
        path = (prop,) if index is None else (prop, index)
        node = self.node[prop] if index is None else self.node[prop][index]
        if isinstance(node, dict):
            for key in ("@xlink:href", "@xlink:title", "@nilReason"):
                if key in node:
                    self.take(*path, key)
        else:
            self.take(*path)

    def take_primitive(self, prop: str) -> None:
        node = self.node.get(prop)
        if node is None:
            return
        if not isinstance(node, dict):
            self.take(prop)
            return
        for key in ("$", "@gml:id", "@nilReason"):
            if key in node:
                self.take(prop, key)
        for pos in ("gml:beginPosition", "gml:endPosition", "gml:timePosition"):
            value = node.get(pos)
            if value is None:
                continue
            if isinstance(value, dict):
                for key in ("#text", "@indeterminatePosition", "@frame"):
                    if key in value:
                        self.take(prop, pos, key)
            else:
                self.take(prop, pos)

    def items_of(self, prop: str, element: str | None) -> list[tuple[int, dict | None, Any]]:
        """Every item of a repeatable object property, consumed whole, with its verbatim copy:
        (index, the object, copy) — or (index, None, copy) for a nil or empty item
        (`<aixm:availability xsi:nil="true"/>`, common in published data), which is typed as a
        nil entry at the SAME index so the ledger finds its leaves under `[i].source`. An item
        of another element is refused; `element=None` (the carrying reading) accepts any."""
        out = []
        self.typed_elements.add(prop)
        for i, item in enumerate(codec.as_list(self.node, prop)):
            self.take(prop, i)
            if isinstance(item, dict) and "$" in item:
                if element is not None and item["$"] != element:
                    raise ValueError(f"{self.where}: {prop}[{i}] holds <{item['$']}>, not {element}")
                out.append((i, item, self._verbatim(item)))
            else:
                out.append((i, None, copy.deepcopy(item)))
        return out

    # -- the reading

    def read(self) -> _SliceResult:
        node, family_name, interpretation = self.node, self.family[0], self._interpretation()
        for key in ("$", "@gml:id"):
            if key in node:
                self.take(key)
        # The member's envelope (`$`, `@gml:id`, `gml:identifier`) is READ into `feature` and
        # deliberately NOT consumed: it stays in the residual at the member's position, exactly
        # where a member outside the five families keeps its own, so one residual mapping
        # covers every member's envelope whether or not it became an object.
        sequence_text = codec.scalar(node.get("aixm:sequenceNumber")).text
        correction_text = codec.scalar(node.get("aixm:correctionNumber")).text
        sequence = self._number("aixm:sequenceNumber")
        correction = self._number("aixm:correctionNumber")
        valid_time = codec.read_time_primitive(node.get("gml:validTime"))
        lifetime = codec.read_time_primitive(node.get("aixm:featureLifetime"))
        self.take_primitive("gml:validTime")
        self.take_primitive("aixm:featureLifetime")
        rules = codec.temporality_problems(interpretation, sequence_text, correction_text, valid_time,
                                           lifetime, self.where)
        self.problems.extend(rules)
        valid_from, valid_to, basis = self._validity(valid_time)
        slice_identity = SliceIdentity(element=node["$"], gml_id=node.get("@gml:id"),
                                       interpretation=interpretation, sequence_number=sequence,
                                       correction_number=correction, valid_time=valid_time,
                                       feature_lifetime=lifetime, valid_from_basis=basis,
                                       temporality_problems=rules)
        properties = {}
        prefix = "event:" if self.family is EVENT_FAMILY else "aixm:"
        for prop in (EVENT_FAMILY[3] if self.family is EVENT_FAMILY else self.profile.pinned_simple):
            key = prefix + prop
            if key in node:
                properties[prop] = codec.property_state(node[key], interpretation)
                self.take_scalar(key)
            elif prop in self.family[3]:
                properties[prop] = codec.property_state(None, interpretation)
        references: dict[str, Any] = {}
        unresolved: list[str] = []
        for prop in self.profile.references_single.get(family_name, ()):
            key = "aixm:" + prop
            if key in node:
                references[prop] = self._reference(prop, node[key], unresolved)
                self.take_reference(key)
        for prop in self.profile.references_many.get(family_name, ()):
            key = "aixm:" + prop
            if key in node:
                references[prop] = [self._reference(prop, item, unresolved)
                                    for item in codec.as_list(node, key)]
                for i in range(len(codec.as_list(node, key))):
                    self.take_reference(key, i)
        block = TimeSliceBlock(aixm_version=self.profile.version.name, feature=self.feature,
                               time_slice=slice_identity, properties=properties,
                               references=references)
        entity_kwargs: dict[str, Any] = dict(
            entity_id=ids.derive(SYSTEM, (self.feature.identifier or "").lower(), "feature"),
            entity_type=self.family[2], affiliation=Affiliation.UNKNOWN, symbol=None,
            position=None, valid_from=valid_from, valid_to=valid_to)
        plan_kwargs = None
        if family_name == "Airspace":
            plan_kwargs = self._airspace(block, interpretation, valid_from, valid_to, entity_kwargs)
        elif family_name == "AirportHeliport":
            block.arp = self._located_point("aixm:ARP", interpretation)
            entity_kwargs["position"] = self._position_of(block.arp)
        elif family_name == "Navaid":
            block.location = self._located_point("aixm:location", interpretation)
            entity_kwargs["position"] = self._position_of(block.location)
            block.navaid_equipment = self._navaid_components(interpretation, unresolved)
        elif family_name == "VerticalStructure":
            block.parts = self._parts(interpretation)
            located = [p for p in block.parts if p.location is not None]
            extents = [p for p in block.parts if p.linear_extent or p.surface_extent or p.unsupported]
            if len(located) == 1 and not extents:
                entity_kwargs["position"] = self._position_from(located[0].location, located[0].location_elevation)
            elif block.parts:
                self.notes.append(f"{self.where}: {len(located)} part(s) state a point location and "
                                  f"{len(extents)} another form; Entity.position stays None and every "
                                  "part's geometry is typed in attributes.aixm.parts")
        if family_name in self.profile.scheduled:
            statuses = self._scheduled(interpretation)
            if family_name == "Airspace":
                block.activation = statuses
            else:
                block.availability = statuses
            entity_kwargs["status"] = self._status(statuses, family_name)
        self._carry_unread(block, interpretation)
        dnotam = None
        if self.family is EVENT_FAMILY:
            dnotam = self._dnotam_event(block, interpretation, valid_time, lifetime, unresolved)
        elif self.profile.digital_notam:
            dnotam = self._dnotam_binding(interpretation, valid_time, unresolved)
        if self.adapter._as_of is not None:
            block.as_of = {"instant": times.render(self.adapter._as_of.instant),
                           "basis": self.adapter._as_of.basis}
        for item in unresolved:
            self.problems.append(f"{self.where}: unresolved reference {item}")
        block.unresolved_references = unresolved
        block.notes = list(self.notes)
        residual = _prune(self.twin, self.consumed)
        if not isinstance(residual, dict):
            residual = {}
        return _SliceResult(block, entity_kwargs, plan_kwargs, residual, self.notes, dnotam)

    # -- the Digital NOTAM Event binding

    def _dnotam_event(self, block: TimeSliceBlock, interpretation: str, valid_time: TimePrimitive,
                      lifetime: TimePrimitive, unresolved: list[str]) -> DigitalNotamBlock:
        """An Event slice: its references, its NOTAM objects, the pinned profile its scenario
        names, the source assertion, and the rule layer's findings on the Event itself."""
        node = self.node
        for prop in EVENT_REFERENCES_SINGLE:
            key = "event:" + prop
            if key in node:
                block.references[prop] = self._reference(prop, node[key], unresolved)
                self.take_reference(key)
        for prop in EVENT_REFERENCES_MANY:
            key = "event:" + prop
            if key in node:
                block.references[prop] = [self._reference(prop, item, unresolved)
                                          for item in codec.as_list(node, key)]
                for i in range(len(codec.as_list(node, key))):
                    self.take_reference(key, i)
        notifications: list[NotamReading] = []
        for _i, item, source in self.items_of("event:notification", None):
            if item is None:
                notifications.append(NotamReading(nil=True, source=source))
                continue
            properties = {}
            if item["$"] == "event:NOTAM":
                properties = {p: codec.property_state(item.get("event:" + p), interpretation)
                              for p in NOTAM_PROPERTIES}
            notifications.append(NotamReading(element=item["$"], gml_id=item.get("@gml:id"),
                                              properties=properties, source=source))
        scenario, version = block.properties["scenario"], block.properties["version"]
        findings: list[str] = []
        profile: ScenarioProfile | None = None
        profile_finding: str | None = None
        if scenario.state != "stated":
            profile_finding = (f"the Event slice states no event:scenario ({scenario.meaning}); no pinned "
                               "profile applies and no scenario rule is checked")
        elif scenario.value not in SCENARIO_PROFILES:
            profile_finding = (f"event:scenario {scenario.value!r} is not one of the pinned Digital NOTAM "
                               f"profiles {sorted(SCENARIO_PROFILES)}; the Event is typed and carried, "
                               "no scenario rule is checked")
        else:
            profile = SCENARIO_PROFILES[scenario.value or ""]
            if version.state != "stated" or version.value != profile.version:
                profile_finding = (f"scenario {profile.id} is pinned at version {profile.version!r} "
                                   f"({profile.rules[0]}); this slice states event:version "
                                   f"{version.value!r}")
            if interpretation not in ("BASELINE", "PERMDELTA"):
                findings.append(f"{profile.rules[0]}: an Event is coded as a BASELINE TimeSlice (a "
                                f"PERMDELTA may also be provided); this slice is {interpretation}")
        if profile_finding:
            findings.append(profile_finding)
        notam_types = [n.properties["type"].value or "" for n in notifications
                       if not n.nil and n.properties and n.properties["type"].state == "stated"]
        estimated = block.properties["estimatedValidity"].state == "stated" or any(
            n.properties.get("estimatedEnd") is not None and n.properties["estimatedEnd"].value == "YES"
            for n in notifications if not n.nil)
        assertion = self._assertion(interpretation, valid_time, lifetime, block.time_slice.sequence_number,
                                    block.time_slice.correction_number, notam_types, estimated)
        for finding in findings:
            self.problems.append(f"{self.where}: {finding}")
        return DigitalNotamBlock(role="event", scenario=scenario, scenario_version=version, profile=profile,
                                 profile_finding=profile_finding, notifications=notifications,
                                 assertion=assertion, rule_findings=findings)

    def _dnotam_binding(self, interpretation: str, valid_time: TimePrimitive,
                        unresolved: list[str]) -> DigitalNotamBlock | None:
        """A feature slice whose `aixm:extension` carries an `event:<Feature>Extension` with
        `event:theEvent`: the binding typed, the Event's scenario looked up in the document, the
        scenario rules the slice can be held to on its own. The extension is READ and NOT
        consumed — it stays in the residual at its position, like the member envelope (D43), so a
        foreign extension beside it keeps the same shape and the ledger finds every leaf."""
        bindings = [(i, item) for i, item in enumerate(codec.as_list(self.node, "aixm:extension"))
                    if isinstance(item, dict) and (codec.object_name(item) or "").startswith("event:")
                    and "event:theEvent" in item]
        if not bindings:
            return None
        findings: list[str] = []
        if len(bindings) > 1:
            findings.append(f"{len(bindings)} event extensions carry event:theEvent; a slice is bound to "
                            "one Event (the first is read, all are kept in the residual)")
        i, item = bindings[0]
        reference = self._reference(f"extension[{i}].theEvent", item["event:theEvent"], unresolved)
        scenario: str | None = None
        profile: ScenarioProfile | None = None
        target = reference.target
        if target is not None and target.where == "document" and target.identifier:
            info = self.events.get(target.identifier.strip().lower())
            if info is None:
                findings.append(f"event:theEvent names member {target.member_index} <{target.element}>, "
                                f"which is not an {EVENT_FEATURE}")
            else:
                scenario = info.scenario
                profile = SCENARIO_PROFILES.get(scenario or "")
                if scenario is None:
                    findings.append("the Event this slice is bound to states no scenario; no scenario rule is checked")
                elif profile is None:
                    findings.append(f"the Event this slice is bound to states scenario {scenario!r}, not a "
                                    "pinned profile; no scenario rule is checked")
        elif target is not None:
            findings.append("event:theEvent resolves through the caller's table, not in the document; the "
                            "Event's scenario is not readable here and no scenario rule is checked")
        else:
            findings.append(f"event:theEvent {reference.href!r} is unresolved; the Event's scenario is not "
                            "readable and no scenario rule is checked")
        if profile is not None:
            findings.extend(self._scenario_rules(profile, interpretation, valid_time))
        assertion = self._assertion(interpretation, valid_time, TimePrimitive(form="absent"),
                                    self._number_of("aixm:sequenceNumber"), self._number_of("aixm:correctionNumber"),
                                    [], False)
        for finding in findings:
            self.problems.append(f"{self.where}: {finding}")
        return DigitalNotamBlock(role="affected-feature", extension_element=item.get("$"),
                                 extension_gml_id=item.get("@gml:id"), the_event=reference,
                                 event_scenario=scenario, assertion=assertion, rule_findings=findings)

    def _number_of(self, prop: str) -> int | None:
        value = codec.scalar(self.node.get(prop))
        try:
            return int(value.text) if value.present else None
        except ValueError:
            return None

    def _scenario_rules(self, profile: ScenarioProfile, interpretation: str, valid_time: TimePrimitive) -> list[str]:
        """The scenario RULE layer, on one bound slice: the interpretation the profile's binding
        rule requires, the feature class it may sit on, and the status its structure must (or
        must not) state — the guidance's rules by identifier. A cancellation slice (no validTime
        period) states no status to hold to the rule."""
        findings: list[str] = []
        binding_rule = profile.rules[1] if profile.id in ("RWY.CLS", "NAV.UNS") else profile.rules[0]
        if interpretation != "TEMPDELTA":
            findings.append(f"{profile.id} {binding_rule}: the slice bound to the Event is {interpretation}, "
                            "not the TEMPDELTA the scenario codes the temporary change in")
        if self.feature.element not in profile.affected_features:
            findings.append(f"{profile.id} {binding_rule}: the Event binds a <{self.feature.element}> slice; "
                            f"the profile's TEMPDELTA sits on {profile.affected_features}")
            return findings
        if valid_time.form != "period":
            return findings
        prop = "aixm:activation" if profile.status_element == "aixm:AirspaceActivation" else "aixm:availability"
        stated: list[str] = []
        for item in codec.as_list(self.node, prop):
            if isinstance(item, dict) and item.get("$") == profile.status_element:
                if _is_baseline_copy(item):
                    continue
                try:
                    value = codec.scalar(item.get("aixm:" + profile.status_property))
                except ValueError:
                    continue
                if value.present:
                    stated.append(value.text or "")
        status_rule = {"RWY.CLS": "RWY.CLS.03", "ATSA.ACT": "ER-01 (activation status: only ACTIVE or INACTIVE)",
                       "SAA.ACT": "ER-02", "NAV.UNS": "NAV.UNS.04"}[profile.id]
        if profile.required_status is not None and not any(v in profile.required_status for v in stated):
            findings.append(f"{profile.id} {status_rule}: no {profile.status_element} on the TEMPDELTA states "
                            f"{profile.status_property} in {profile.required_status}; stated: {stated}")
        if profile.permitted_status is not None:
            for value in stated:
                if value not in profile.permitted_status:
                    findings.append(f"{profile.id} {status_rule}: {profile.status_property} {value!r} is outside "
                                    f"{profile.permitted_status}")
        for value in stated:
            if value in profile.forbidden_status:
                findings.append(f"{profile.id} {status_rule}: {profile.status_property} {value!r} cannot be used "
                                "in this scenario")
        return findings

    def _assertion(self, interpretation: str, valid_time: TimePrimitive, lifetime: TimePrimitive,
                   sequence: int | None, correction: int | None, notam_types: list[str],
                   estimated: bool) -> SourceAssertion:
        """The slice's own assertion: kind and temporal basis, from the slice alone."""
        begin = end = None
        end_open = False
        if valid_time.form == "period":
            begin, end = codec.instant_of(valid_time.begin), codec.instant_of(valid_time.end)
            end_open = end is None and valid_time.end is not None and valid_time.end.indeterminate is not None
        elif valid_time.form == "instant":
            begin = codec.instant_of(valid_time.time)
        corrected = (correction or 0) >= 1
        if corrected and valid_time.form in ("nil", "absent"):
            kind = "cancellation"
            basis = (f"correction {correction} of sequence {sequence} with an empty gml:validTime "
                     f"(nilReason={valid_time.nil_reason!r}) — Temporality Concept 1.1 §4.4.8: the sequence is "
                     "taken off the timeline before its effect; the earlier corrections stay on record")
        elif corrected:
            kind = "termination" if "C" in notam_types else "correction"
            basis = (f"correction {correction} of sequence {sequence}: the highest correction number is the "
                     "valid slice (§3.6); TS_017 admits only a change of the end of validity on an active slice"
                     + (" — a NOTAM of type C: immediate termination (guidance 'Event update or cancellation')"
                        if kind == "termination" else ""))
        elif "R" in notam_types:
            kind = "replacement"
            basis = (f"sequence {sequence}, correction {correction}, carrying a NOTAM of type R: a replacement "
                     "of the Event's earlier sequence (guidance 'Event update or cancellation': a new BASELINE "
                     "with the NOTAMR)")
        else:
            kind = "initial"
            basis = f"sequence {sequence}, correction {correction}: the first slice of its sequence"
        lifetime_end = codec.instant_of(lifetime.end) if lifetime.form == "period" else None
        return SourceAssertion(kind=kind, basis=basis, interpretation=interpretation, sequence_number=sequence,
                               correction_number=correction, valid_time_form=valid_time.form,
                               effective_from=times.render(begin) if begin else None,
                               effective_to=times.render(end) if end else None, end_open=end_open,
                               lifetime_end=times.render(lifetime_end) if lifetime_end else None,
                               estimated_end=estimated, notam_types=notam_types)

    # -- pieces

    def _interpretation(self) -> str:
        value = codec.scalar(self.node.get("aixm:interpretation"))
        self.take_scalar("aixm:interpretation")
        if not value.present:
            raise ValueError(f"{self.where}: aixm:interpretation is required on every time slice "
                             "(AbstractAIXMTimeSliceType) and is absent")
        if value.text not in codec.INTERPRETATIONS:
            raise ValueError(f"{self.where}: interpretation {value.text!r} is not one of "
                             f"{codec.INTERPRETATIONS}")
        return value.text or ""

    def _number(self, prop: str) -> int | None:
        value = codec.scalar(self.node.get(prop))
        self.take_scalar(prop)
        if not value.present:
            return None
        try:
            return int(value.text or "")
        except ValueError:
            raise ValueError(f"{self.where}: {prop} {value.text!r} is not an integer") from None

    def _validity(self, valid_time: TimePrimitive):
        begin = end = None
        if valid_time.form == "period":
            begin, end = codec.instant_of(valid_time.begin), codec.instant_of(valid_time.end)
        elif valid_time.form == "instant":
            begin = codec.instant_of(valid_time.time)
        if begin is not None:
            return begin, end, ("gml:validTime/" + (valid_time.element or "") +
                                ("/gml:beginPosition" if valid_time.form == "period" else "/gml:timePosition"))
        as_of = self.adapter._as_of
        why = {"absent": "no gml:validTime", "nil": f"an empty gml:validTime with nilReason="
                                                     f"{valid_time.nil_reason!r} (Temporality Concept 1.1 "
                                                     "§4.4.8: the slice is cancelled)"}.get(
            valid_time.form, "a validTime whose begin is indeterminate")
        if as_of is None:
            raise ValueError(f"{self.where}: {why}; the slice states no instant of its own, so an "
                             "Entity's valid_from needs the caller's as-of context — "
                             f"{self.profile.adapter_class}(as_of=AsOf(instant, basis)) — and nothing is stamped "
                             "with the clock or the epoch (limitation cancelled-slice-needs-as-of)")
        self.notes.append(f"{self.where}: {why}; valid_from is the caller's as-of instant "
                          f"({as_of.basis}), not a source time")
        return as_of.instant, end, f"as_of ({why})"

    def _reference(self, prop: str, node: Any, unresolved: list[str]) -> Reference:
        reference = codec.resolve_reference(prop, node, self.index, self.adapter._references)
        if not reference.resolved and reference.form != "none":
            unresolved.append(f"{prop} -> {reference.href!r} ({reference.form})")
        return reference

    def _verbatim(self, node: Any) -> dict:
        return copy.deepcopy(node) if isinstance(node, dict) else {"#value": node}

    def _unsupported(self, e: GeometryUnsupported) -> UnsupportedGeometry:
        if self.adapter._unsupported == "refuse":
            raise ValueError(f"{self.where}: {e} (limitation unsupported-geometry-refused; "
                             f"{self.profile.adapter_class}(unsupported_geometry='report') keeps the slice "
                             "with the form named)") from e
        self.problems.append(f"{self.where}: {e}")
        source = e.source if isinstance(e.source, (str, int, float, dict, list, type(None))) else str(e.source)
        return UnsupportedGeometry(kind=e.kind, element=e.element, reason=str(e), source=source)

    def _located_point(self, prop: str, interpretation: str) -> LocatedPoint | None:
        node = self.node.get(prop)
        if node is None:
            return None
        self.take(prop)
        self.typed_elements.add(prop)
        if not isinstance(node, dict) or "$" not in node:
            return LocatedPoint(source=copy.deepcopy(node), unsupported=UnsupportedGeometry(
                kind="element", element=None, reason=f"{prop} holds no point by value", source=None))
        elevation = codec.read_elevation(node, interpretation, self.profile.version)
        try:
            point = codec.read_point(node)
        except GeometryUnsupported as e:
            return LocatedPoint(elevation=elevation, unsupported=self._unsupported(e), source=self._verbatim(node))
        return LocatedPoint(point=point, elevation=elevation, source=self._verbatim(node))

    def _carry_unread(self, block: TimeSliceBlock, interpretation: str) -> None:
        """Every CARRIED_ELEMENTS member the slice states and no family reading typed lands at
        its block field with its source verbatim (see the constant): a point property through
        the same GML reading as a Navaid's `location`, a schedule-bearing list with each item's
        element, gml:id and timesheets, the other lists with each item's gml:id. No pinned
        property of the object is read and nothing is projected to the Entity; a note says so."""
        for prop, field in self.profile.carried_elements:
            if prop not in self.node or prop in self.typed_elements:
                continue
            if prop in ("aixm:location", "aixm:ARP"):
                setattr(block, field, self._located_point(prop, interpretation))
                read = "the point by value and its elevation"
            elif not isinstance(self.node[prop], list):
                # Stated once on a slice the twin does not list it for: the ledger's `[*]` key
                # does not reach it and it stays in the residual at its position (D41).
                continue
            else:
                items: list[Any] = []
                for _i, item, source in self.items_of(prop, None):
                    nil, gml_id = item is None, None if item is None else item.get("@gml:id")
                    if prop in ("aixm:activation", "aixm:availability"):
                        items.append(ScheduledStatus(
                            nil=nil, element=None if item is None else item["$"], gml_id=gml_id,
                            time_interval=[] if item is None else codec.read_schedule(item, interpretation),
                            source=source))
                    elif prop == "aixm:part":
                        items.append(PartReading(nil=nil, gml_id=gml_id, source=source))
                    elif prop == "aixm:navaidEquipment":
                        items.append(NavaidComponentReading(nil=nil, gml_id=gml_id, source=source))
                    else:
                        get = (lambda _k: None) if item is None else item.get
                        items.append(GeometryComponentReading(
                            nil=nil, operation=codec.property_state(get("aixm:operation"), interpretation),
                            operation_sequence=codec.property_state(get("aixm:operationSequence"), interpretation),
                            source=source))
                setattr(block, field, items)
                read = {"aixm:activation": "each item's element, gml:id and timesheets",
                        "aixm:availability": "each item's element, gml:id and timesheets",
                        "aixm:geometryComponent": "each item's operation and operationSequence",
                        }.get(prop, "each item's gml:id")
            self.notes.append(f"{self.where}: <{self.feature.element}> is outside the families that "
                              f"type {prop}; carried at attributes.aixm.{field} with its source "
                              f"verbatim, {read} read, nothing else of it typed and nothing projected "
                              "to the Entity")

    def _position_of(self, located: LocatedPoint | None) -> Position | None:
        if located is None or located.point is None:
            return None
        return self._position_from(located.point, located.elevation)

    def _position_from(self, point: PointReading | None, elevation: Elevation | None) -> Position | None:
        if point is None:
            return None
        vertical = None
        if elevation is not None and elevation.cdm is not None:
            vertical = VerticalPosition(value=elevation.cdm.value, unit=VerticalUnit(elevation.cdm.unit),
                                        reference=VerticalReference(elevation.cdm.reference))
        elif elevation is not None and elevation.elevation.state == "stated":
            self.notes.append(f"{self.where}: elevation {elevation.elevation.value!r} "
                              f"{elevation.elevation.uom!r} is not projected ({elevation.not_projected}); "
                              "carried typed")
        return Position(lat=point.latitude, lon=point.longitude, alt_m=None,
                        position_source=PositionSource.MANUAL, vertical=vertical)

    def _scheduled(self, interpretation: str) -> list[ScheduledStatus]:
        prop, element, status_prop, others = self.profile.scheduled[self.family[0]]
        out = []
        for i, item, source in self.items_of(prop, element):
            if item is None:
                out.append(ScheduledStatus(nil=True, source=source))
                continue
            properties = {p: codec.property_state(item.get("aixm:" + p), interpretation)
                          for p in (status_prop, *others)}
            out.append(ScheduledStatus(element=element, gml_id=item.get("@gml:id"), properties=properties,
                                       time_interval=codec.read_schedule(item, interpretation),
                                       source=source))
        return out

    def _status(self, statuses: list[ScheduledStatus], family_name: str) -> OperationalStatus | None:
        stated = [s for s in statuses if not s.nil]
        if len(stated) != 1:
            return None
        only = stated[0]
        code = only.properties[self.profile.scheduled[family_name][2]]
        if code.state != "stated" or only.time_interval:
            return None
        return OperationalStatus(state=code.value or "",
                                 namespace=f"AIXM {self.profile.version.name} {self.profile.status_code_type[family_name]}",
                                 since=None, attributes={})

    def _navaid_components(self, interpretation: str, unresolved: list[str]) -> list[NavaidComponentReading]:
        out = []
        for i, item, source in self.items_of("aixm:navaidEquipment", "aixm:NavaidComponent"):
            if item is None:
                out.append(NavaidComponentReading(nil=True, source=source))
                continue
            equipment = None
            if "aixm:theNavaidEquipment" in item:
                equipment = self._reference("navaidEquipment[%d].theNavaidEquipment" % i,
                                            item["aixm:theNavaidEquipment"], unresolved)
            out.append(NavaidComponentReading(
                gml_id=item.get("@gml:id"),
                properties={p: codec.property_state(item.get("aixm:" + p), interpretation)
                            for p in self.profile.navaid_component_properties},
                equipment=equipment, source=source))
        return out

    def _parts(self, interpretation: str) -> list[PartReading]:
        out = []
        for i, item, source in self.items_of("aixm:part", "aixm:VerticalStructurePart"):
            if item is None:
                out.append(PartReading(nil=True, source=source))
                continue
            part = PartReading(gml_id=item.get("@gml:id"),
                               properties={p: codec.property_state(item.get("aixm:" + p), interpretation)
                                           for p in self.profile.part_properties},
                               time_interval=codec.read_schedule(item, interpretation),
                               source=source)
            location = item.get("aixm:horizontalProjection_location")
            if isinstance(location, dict) and "$" in location:
                part.location_elevation = codec.read_elevation(location, interpretation, self.profile.version)
                try:
                    part.location = codec.read_point(location)
                except GeometryUnsupported as e:
                    part.unsupported.append(self._unsupported(e))
            linear = item.get("aixm:horizontalProjection_linearExtent")
            if isinstance(linear, dict) and "$" in linear:
                try:
                    part.linear_extent = codec.read_curve(linear)
                except GeometryUnsupported as e:
                    part.unsupported.append(self._unsupported(e))
            surface = item.get("aixm:horizontalProjection_surfaceExtent")
            if isinstance(surface, dict) and "$" in surface:
                try:
                    part.surface_extent = codec.read_surface(surface)
                    self.notes.extend(codec.orientation_notes(part.surface_extent, f"{self.where} part {i}"))
                except GeometryUnsupported as e:
                    part.unsupported.append(self._unsupported(e))
            out.append(part)
        return out

    def _airspace(self, block: TimeSliceBlock, interpretation: str, valid_from, valid_to,
                  entity_kwargs: dict) -> dict | None:
        components = []
        for i, item, source in self.items_of("aixm:geometryComponent", "aixm:AirspaceGeometryComponent"):
            if item is None:
                components.append(GeometryComponentReading(
                    nil=True, operation=codec.property_state(None, interpretation),
                    operation_sequence=codec.property_state(None, interpretation), source=source))
                continue
            volume = None
            volume_node = item.get("aixm:theAirspaceVolume")
            if isinstance(volume_node, dict) and volume_node.get("$") == "aixm:AirspaceVolume":
                volume = self._volume(volume_node, interpretation, block, i)
            components.append(GeometryComponentReading(
                operation=codec.property_state(item.get("aixm:operation"), interpretation),
                operation_sequence=codec.property_state(item.get("aixm:operationSequence"), interpretation),
                volume=volume, source=source))
        block.geometry_components = components
        stated = [(i, c) for i, c in enumerate(components) if not c.nil]
        if not stated:
            block.volume_projection = ("none: the slice states no geometryComponent" if not components
                                       else "none: every geometryComponent is nil")
            return None
        reasons = []
        for i, component in stated:
            operation = component.operation
            if operation.state == "stated" and operation.value != "BASE":
                reasons.append(f"component {i} operation {operation.value!r}")
            if component.volume is None:
                reasons.append(f"component {i} has no AirspaceVolume")
            elif component.volume.horizontal_projection is None:
                reasons.append(f"component {i} states no projectable horizontalProjection "
                               f"({component.volume.horizontal_projection_state.state}"
                               f"{', ' + component.volume.unsupported[0].kind if component.volume.unsupported else ''})")
        if reasons:
            block.volume_projection = "none: " + "; ".join(reasons)
            if any("operation" in r for r in reasons):
                self.problems.append(f"{self.where}: composite geometry is not drawn — "
                                     + "; ".join(reasons))
            return None
        volumes = [c.volume for _, c in stated if c.volume is not None]
        first = volumes[0]
        limits = [(v.upper.model_dump(mode="json"), v.lower.model_dump(mode="json")) for v in volumes]
        if any(limit != limits[0] for limit in limits[1:]):
            block.volume_projection = ("none: the BASE components state different upper/lower limits; one "
                                       "Area holds one vertical extent and none is derived")
            self.problems.append(f"{self.where}: {block.volume_projection}")
            return None
        polygons = []
        for v in volumes:
            assert v.horizontal_projection is not None
            geojson = v.horizontal_projection.geojson
            polygons.extend(geojson["coordinates"] if geojson["type"] == "MultiPolygon" else [geojson["coordinates"]])
        geometry = ({"type": "Polygon", "coordinates": polygons[0]} if len(polygons) == 1
                    else {"type": "MultiPolygon", "coordinates": polygons})
        vertical = None
        if any(limit.kind != "absent" for limit in (first.upper, first.lower, first.maximum, first.minimum)):
            vertical = VerticalExtent(lower=self._bound(first.lower, "lower"), upper=self._bound(first.upper, "upper"))
        validity = TemporalValidity(valid_from=valid_from, valid_to=valid_to,
                                    effective=Period(start=valid_from, end=valid_to))
        label = block.properties.get("designator")
        plan_id = ids.derive(SYSTEM, (self.feature.identifier or "").lower(), "airspace-volume")
        block.plan_object_id = str(plan_id)
        block.volume_projection = geometry["type"]
        return dict(object_id=plan_id, object_type=ObjectType.CONTROL_MEASURE,
                    label=label.value if label is not None and label.state == "stated" and label.value else None,
                    geometry=geometry, style={}, expires_at=valid_to, validity=validity,
                    area=Area(geometry=geometry, vertical=vertical, validity=validity, bounds=None))

    def _bound(self, limit: VerticalLimit, which: str) -> VerticalPosition | None:
        if limit.cdm is not None:
            return VerticalPosition(value=limit.cdm.value, unit=VerticalUnit(limit.cdm.unit),
                                    reference=VerticalReference(limit.cdm.reference))
        if limit.kind != "absent":
            self.notes.append(f"{self.where}: {which} limit {limit.limit.value!r} {limit.limit.uom!r} "
                              f"reference {limit.reference.value!r} is not projected onto Area.vertical "
                              f"({limit.not_projected}); carried typed in attributes.aixm")
        return None

    def _volume(self, node: dict, interpretation: str, block: TimeSliceBlock, i: int) -> VolumeReading:
        limits = {name: codec.read_vertical_limit(node.get(value), node.get(reference), interpretation)
                  for name, value, reference in VOLUME_LIMITS}
        surface = curve = None
        unsupported: list[UnsupportedGeometry] = []
        projection = node.get("aixm:horizontalProjection")
        projection_state = codec.property_state(None if isinstance(projection, dict) and "$" in projection
                                                else projection, interpretation)
        if isinstance(projection, dict) and "$" in projection:
            projection_state = PropertyState(state="stated", meaning="stated", value=projection["$"])
            try:
                surface = codec.read_surface(projection)
                self.notes.extend(codec.orientation_notes(surface, f"{self.where} component {i}"))
            except GeometryUnsupported as e:
                unsupported.append(self._unsupported(e))
        centreline = node.get("aixm:centreline")
        centreline_state = codec.property_state(None if isinstance(centreline, dict) and "$" in centreline
                                                else centreline, interpretation)
        if isinstance(centreline, dict) and "$" in centreline:
            centreline_state = PropertyState(state="stated", meaning="stated", value=centreline["$"])
            try:
                curve = codec.read_curve(centreline)
            except GeometryUnsupported as e:
                unsupported.append(self._unsupported(e))
        contributor = None
        dependency = node.get("aixm:contributorAirspace")
        if isinstance(dependency, dict) and dependency.get("$") == "aixm:AirspaceVolumeDependency":
            airspace = None
            if "aixm:theAirspace" in dependency:
                airspace = self._reference(f"geometryComponent[{i}].contributorAirspace.theAirspace",
                                           dependency["aixm:theAirspace"], block.unresolved_references)
            contributor = ContributorReading(
                dependency=codec.property_state(dependency.get("aixm:dependency"), interpretation),
                airspace=airspace)
        return VolumeReading(gml_id=node.get("@gml:id"), upper=limits["upper"], lower=limits["lower"],
                             maximum=limits["maximum"], minimum=limits["minimum"],
                             width=codec.property_state(node.get("aixm:width"), interpretation),
                             horizontal_projection=surface, horizontal_projection_state=projection_state,
                             centreline=curve, centreline_state=centreline_state, unsupported=unsupported,
                             contributor=contributor)


# ------------------------------------------------------------------------------- residual

_DROPPED = object()


def _prune(node: Any, consumed: set[tuple], path: tuple = ()) -> Any:
    """`node` minus every consumed path, the source's structure — LIST POSITIONS included —
    intact: an emptied list item becomes `None` so a leaf the adapter did not consume keeps the
    index the ledger looks for it at; an emptied dict is dropped from its parent; a dict that
    was empty in the source is kept."""
    if path in consumed:
        return _DROPPED
    if isinstance(node, dict):
        kept: dict = {}
        for key, sub in node.items():
            result = _prune(sub, consumed, path + (key,))
            if result is not _DROPPED:
                kept[key] = result
        if not kept and node:
            return _DROPPED
        return kept
    if isinstance(node, list):
        items = []
        for index, sub in enumerate(node):
            result = _prune(sub, consumed, path + (index,))
            items.append(None if result is _DROPPED else result)
        if all(item is None for item in items) and node:
            return _DROPPED
        return items
    return node


__all__ = ["Aixm511Adapter", "AixmAdapterBase", "AsOf", "ObjectCountExceeded", "Profile", "PROFILE_511",
           "TimeSliceBlock", "ReferenceTarget", "FAMILIES", "PINNED_SIMPLE", "AIXM511_MAX_INPUT_BYTES",
           "AIXM511_MAX_DEPTH", "AIXM511_MAX_ELEMENTS", "AIXM511_MAX_OBJECTS"]
