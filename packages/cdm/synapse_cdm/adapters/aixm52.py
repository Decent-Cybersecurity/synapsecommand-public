"""AIXM 5.2 (EUROCONTROL & FAA, schema release 5.2.0, 17 January 2025) -> CDM. Adapter #20,
ingest-only, `residual: structured`: the same five feature families as the AIXM 5.1.1 adapter,
read by the SAME reader (`aixm511.AixmAdapterBase` on the shared `aixm_codec`) under a SECOND
PROFILE — the 5.2 namespaces, the 5.2 schema closure, the 5.2 property paths and the 5.2
structures where the schema moved them. Nothing here is a namespace substitution: every row of
`FAMILIES` is the 5.2 `<Family>PropertyGroup`'s own member list, the parsed twin's list-shape
table is `aixm_codec.REPEATABLE_52` (derived from the 5.2 XSD), and an ElevatedPoint is read
with the 5.2 property group (`Version.elevated`).

WHAT 5.2 CHANGED IN THE FIVE FAMILIES (the Phase 0 structural diff, `xsd_pin.json`)
---------------------------------------------------------------------------------------
    every object      `AbstractAIXMObjectType` gains `gml:identifier` — an «object» (an
                      AirspaceVolume, an ElevatedPoint, an availability structure) may carry a
                      UUID of its own; the twin keeps it as the property it is, and a feature's
                      identity is still the FEATURE's `gml:identifier`, never an object's.
    ElevatedPoint /   extend `gml:PointType` / `CurveType` / `SurfaceType` DIRECTLY (5.1.1:
    Curve / Surface   `aixm:PointType` …); the property group is `elevation`, `geoidUndulation`,
                      `verticalDatum` (now `TextNameType`, free text, where 5.1.1 had the
                      `CodeVerticalDatumType` code list), `horizontalAccuracy`, `annotation` —
                      `verticalAccuracy` NO LONGER EXISTS, so `Elevation.vertical_accuracy` is
                      None on every 5.2 reading (a property the schema cannot state is not
                      "not stated").
    Airspace          unchanged (Airspace, AirspaceGeometryComponent, AirspaceLayer,
                      AirspaceActivation); `AirspaceVolume` gains `name` and `location` (an
                      `aixm:Point` by value) — both ride in the component's verbatim `source`
                      (residual-kind in the ledger) and are not typed: a volume's `location` is a
                      characteristic point, not the drawable projection, and the shared
                      `VolumeReading` contract is not widened for one version.
    AirportHeliport   +`timeZone`, +`segmentedCircleMarker`; −`fieldElevationAccuracy`,
                      −`magneticVariationAccuracy`; `verticalDatum` `CodeVerticalDatumType` →
                      `TextNameType`; `responsibleOrganisation` 1 → unbounded (a list in the twin,
                      `REPEATABLE_52`); `altimeterSource` holds an AltimeterSource object by value.
    Runway            +`depth`, +`referenceCodeFieldLength`, +`referenceCodeWingspan`;
                      −`lengthAccuracy`, −`widthAccuracy`.
    RunwayDirection   +`slope`, +`approachGuidance`; −`precisionApproachGuidance`,
                      −`elevationTDZAccuracy`, −`trueBearingAccuracy`.
    Navaid            +`codeICAOCountry`; NavaidOperationalStatus and NavaidComponent unchanged.
    VerticalStructure +`designator`, +`marked`, +`placeName`, +`dataAssessmentStatus`,
                      +`arrestingDevice` (unbounded, a list in the twin);
                      `VerticalStructurePart` +`height`, −`verticalExtentAccuracy`, `designator`
                      retyped `TextDesignatorLongType`.
    temporality       every TimeSlice type's `interpretation` / `sequenceNumber` /
                      `correctionNumber` / `featureLifetime` skeleton and `Timesheet` unchanged,
                      so the Temporality Concept 1.1 rules the codec applies are the same rules.

The pinned simple properties per family are the 5.2 group's scalars (`FAMILIES`); the part
properties are the 5.2 `VerticalStructurePartPropertyGroup`'s (`PART_PROPERTIES`, with `height`
and without `verticalExtentAccuracy`); references, schedule-bearing structures, status code types
and the carried elements are the 5.1.1 tables, which the diff proves unchanged, imported from
`aixm511` rather than re-spelled so the record has one source for them.

DIGITAL NOTAM ON 5.2: NOT AVAILABLE (declared, not claimed)
-----------------------------------------------------------
No Digital NOTAM Event schema exists for AIXM 5.2: every published revision of the Event Schema
(5.1-e, 5.1.1-f, -j, -k, -l, -m) targets the `…/5.1.1/event` (or `…/5.1/event`) namespace, and
the publisher states "The current specifications for … Digital NOTAM are based on AIXM 5.1.1"
(aixm.aero/page/aixm-52, read 2026-09-20; decision D3, the `aixm52` normative record's
`digital_notam` field). This adapter therefore reads NO Event, pins NO scenario profile
(`metadata.profiles` is empty) and declares the limitation `digital-notam-not-available`; a
member in the 5.1.1 Event namespace inside a 5.2 document is named by `validate_source`, carried
whole in the residual and never typed. The `dnotam` block never appears on a 5.2 object.

Everything else — one Entity per time slice, the four property states, references in every
form, the pinned geometry forms under the two CRS URNs, vertical limits member for member, the
as-of context, the structured residual with list positions kept, the parser limits — is the
5.1.1 module's documented reading; see `adapters/aixm511.py`. The version binding is REAL in
both directions: a 5.1.1 document is refused at the root by this adapter and a 5.2 document by
the 5.1.1 one (`tests/test_cdm_aixm52_adapter.py::test_the_version_binding_is_real_in_both_directions`).
"""
from __future__ import annotations

from synapse_cdm import secure_xml
from synapse_cdm.adapters import aixm511, aixm_codec as codec
from synapse_cdm.adapters.aixm511 import (
    AixmAdapterBase, AsOf, ObjectCountExceeded, Profile, ReferenceTarget, TimeSliceBlock,
)
from synapse_cdm.enums import EntityType
from synapse_cdm.manifest import (AdapterMetadata, Capabilities, ClaimStatus, Direction,
                                   Evidence, FormatRef, LicenseClass, LimitBasis, LimitKind,
                                   Limitation, Limits, Maturity, MaturityLevel, Residual,
                                   UnknownFields, WireBinding)
from synapse_cdm.models import CDMBase

SYSTEM = aixm511.SYSTEM
VERSION = codec.VERSION_52
CONTRACT = aixm511.CONTRACT

#: IMPLEMENTATION CAPS, the 5.1.1 adapter's figures under this module's names: the documents
#: are the same size class (an AIRAC delta, an aerodrome's data set) and the deepest shipped
#: 5.2 fixture nests as the 5.1.1 one does.
AIXM52_MAX_INPUT_BYTES = 16 * 1024 * 1024
AIXM52_MAX_DEPTH = 192
AIXM52_MAX_ELEMENTS = 500_000
AIXM52_MAX_OBJECTS = 20_000
XML_LIMITS = secure_xml.XmlLimits(max_bytes=AIXM52_MAX_INPUT_BYTES, max_depth=AIXM52_MAX_DEPTH,
                                  max_elements=AIXM52_MAX_ELEMENTS)

#: The publisher's statement the Digital NOTAM declaration rests on (decision D3).
DIGITAL_NOTAM_STATEMENT = ("No Digital NOTAM Event schema exists for AIXM 5.2: every published Event Schema "
                           "revision (5.1-e, 5.1.1-f/-j/-k/-l/-m) targets http://www.aixm.aero/schema/5.1.1/event "
                           "or …/5.1/event, and the publisher states 'The current specifications for … Digital "
                           "NOTAM are based on AIXM 5.1.1' (https://aixm.aero/page/aixm-52, read 2026-09-20)")

# ------------------------------------------------------------------ the five families, pinned

#: Feature element -> (family name, time-slice element, EntityType, pinned simple properties).
#: Every property name is the 5.2 schema's own (`AIXM_Features.xsd` 5.2.0, the family's
#: `<Family>PropertyGroup`), in the group's order; a name 5.1.1 pinned and 5.2 removed is absent
#: here and a name 5.2 added is present — the module docstring lists both per family.
FAMILIES: dict[str, tuple[str, str, EntityType, tuple[str, ...]]] = {
    "aixm:Airspace": ("Airspace", "aixm:AirspaceTimeSlice", EntityType.OVERLAY_OBJECT,
                      ("type", "designator", "localType", "name", "designatorICAO", "controlType",
                       "upperLowerSeparation")),
    "aixm:AirportHeliport": ("AirportHeliport", "aixm:AirportHeliportTimeSlice", EntityType.FACILITY,
                             ("designator", "name", "locationIndicatorICAO", "designatorIATA", "type",
                              "certifiedICAO", "privateUse", "controlType", "fieldElevation", "verticalDatum",
                              "magneticVariation", "abandoned", "timeZone", "segmentedCircleMarker")),
    "aixm:Runway": ("Runway", "aixm:RunwayTimeSlice", EntityType.FACILITY,
                    ("designator", "type", "nominalLength", "nominalWidth", "abandoned",
                     "referenceCodeFieldLength", "referenceCodeWingspan", "depth")),
    "aixm:RunwayDirection": ("RunwayDirection", "aixm:RunwayDirectionTimeSlice", EntityType.FACILITY,
                             ("designator", "trueBearing", "magneticBearing", "elevationTDZ", "slope",
                              "approachGuidance")),
    "aixm:Navaid": ("Navaid", "aixm:NavaidTimeSlice", EntityType.FACILITY,
                    ("type", "designator", "name", "flightChecked", "purpose", "signalPerformance",
                     "codeICAOCountry")),
    "aixm:VerticalStructure": ("VerticalStructure", "aixm:VerticalStructureTimeSlice", EntityType.FACILITY,
                               ("name", "type", "lighted", "markingICAOStandard", "group", "length", "width",
                                "radius", "lightingICAOStandard", "synchronisedLighting", "marked",
                                "designator", "placeName", "dataAssessmentStatus")),
}
PINNED_SIMPLE: tuple[str, ...] = tuple(sorted({p for _, _, _, props in FAMILIES.values() for p in props}))
#: The 5.2 `VerticalStructurePartPropertyGroup`'s scalars: `height` is new, `verticalExtentAccuracy`
#: is gone, `designator` is `TextDesignatorLongType`.
PART_PROPERTIES = ("verticalExtent", "type", "constructionStatus", "markingPattern", "markingFirstColour",
                   "markingSecondColour", "mobile", "frangible", "visibleMaterial", "designator", "height")
#: Unchanged between 5.1.1 and 5.2 (the Phase 0 family diff: AirspaceActivation,
#: AirportHeliportAvailability, ManoeuvringAreaAvailability, NavaidOperationalStatus,
#: NavaidComponent, AirspaceGeometryComponent, AirspaceVolumeDependency and the reference
#: properties of every family keep their member lists), so the 5.1.1 tables are THE tables.
REFERENCES_SINGLE = aixm511.REFERENCES_SINGLE
REFERENCES_MANY = aixm511.REFERENCES_MANY
SCHEDULED = aixm511.SCHEDULED
STATUS_CODE_TYPE = aixm511.STATUS_CODE_TYPE
NAVAID_COMPONENT_PROPERTIES = aixm511.NAVAID_COMPONENT_PROPERTIES
CARRIED_ELEMENTS = aixm511.CARRIED_ELEMENTS
#: What 5.1.1 pinned and 5.2 has no element for, per family — the record's difference table,
#: kept here so a test can hold the module to it against the 5.2 schema.
REMOVED_IN_52: dict[str, tuple[str, ...]] = {
    "AirportHeliport": ("fieldElevationAccuracy", "magneticVariationAccuracy"),
    "Runway": ("lengthAccuracy", "widthAccuracy"),
    "RunwayDirection": ("precisionApproachGuidance", "elevationTDZAccuracy", "trueBearingAccuracy"),
    "VerticalStructurePart": ("verticalExtentAccuracy",),
    "ElevatedPoint": ("verticalAccuracy",),
}
ADDED_IN_52: dict[str, tuple[str, ...]] = {
    "AirportHeliport": ("timeZone", "segmentedCircleMarker"),
    "Runway": ("depth", "referenceCodeFieldLength", "referenceCodeWingspan"),
    "RunwayDirection": ("slope", "approachGuidance"),
    "Navaid": ("codeICAOCountry",),
    "VerticalStructure": ("designator", "marked", "placeName", "dataAssessmentStatus", "arrestingDevice"),
    "VerticalStructurePart": ("height",),
    "AirspaceVolume": ("name", "location"),
    "ElevatedPoint": ("horizontalAccuracy", "annotation"),
}

PROFILE_52 = Profile(
    version=VERSION, adapter_class="Aixm52Adapter", families=FAMILIES,
    references_single=REFERENCES_SINGLE, references_many=REFERENCES_MANY, scheduled=SCHEDULED,
    status_code_type=STATUS_CODE_TYPE, part_properties=PART_PROPERTIES,
    navaid_component_properties=NAVAID_COMPONENT_PROPERTIES, carried_elements=CARRIED_ELEMENTS,
    max_objects=AIXM52_MAX_OBJECTS, xml_limits=XML_LIMITS, digital_notam=False)


# ---------------------------------------------------------------------------- the adapter

class Aixm52Adapter(AixmAdapterBase):
    name = "aixm52"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM
    PROFILE = PROFILE_52

    #: Adapter API v2's declaration (ARCHITECTURE.md §3). Licence class from the XSD package's
    #: own header: BSD-style, © 2025 EUROCONTROL & FAA, redistribution with the notice permitted
    #: (the `aixm52` normative record's `usage_rights`); the closure is held outside the repository.
    metadata = AdapterMetadata(
        id="aixm52",
        name="AIXM 5.2",
        adapter_version="1.0.0",
        format=FormatRef(name="AIXM", version="5.2 (XML Schema release 5.2.0, 17 January 2025; GML 3.2.1; "
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
                  "featureLifetime positions, every pinned 5.2 simple property with its uom and "
                  "nilReason, every reference's href — and residual-kind mappings for the "
                  "complex structures it reads (geometry components, activation, availability, "
                  "parts, navaid components, ARP, location), each carried verbatim beside its "
                  "typed reading, with everything else in the structured residual at its own "
                  "position; the ledger reports no LOST leaf on any fixture. L4 is NOT declared: "
                  "the adapter is ingest-only and emits nothing, so `roundtrip` (E) is the "
                  "declared inapplicability of a translator with no egress, not a passed check "
                  "(ARCHITECTURE.md §3.6, rule 4). Normative validation of every positive fixture "
                  "against the pinned AIXM 5.2.0 XSD closure is "
                  "tests/test_cdm_aixm52_adapter.py::test_every_positive_fixture_validates_against_the_pinned_schema, "
                  "which records BLOCKED_EXTERNAL_EVIDENCE rather than passing when the resource or "
                  "the `validate` extra is absent.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        #: No Digital NOTAM scenario profile is pinned on 5.2: none exists (limitation
        #: digital-notam-not-available).
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "AIXMBasicMessage (5.2) / Airspace time slices — type, designator, name, geometry "
                "components (AirspaceVolume limits with references, horizontalProjection in the "
                "pinned Surface forms, contributor airspace; the 5.2 `name` and `location` of a "
                "volume carried verbatim), activation with schedules; one Entity per slice and a "
                "CONTROL_MEASURE PlanObject with an Area when the slice states a projectable BASE "
                "geometry; ingest",
                "AIXMBasicMessage (5.2) / AirportHeliport time slices — designators, ICAO/IATA codes, "
                "type, field elevation, verticalDatum (free text in 5.2), timeZone, "
                "segmentedCircleMarker, ARP ElevatedPoint (the 5.2 property group: no "
                "verticalAccuracy), availability (operationalStatus, warning, schedules); one "
                "FACILITY Entity per slice; ingest",
                "AIXMBasicMessage (5.2) / Runway and RunwayDirection time slices — designators, type, "
                "dimensions, depth, reference codes, bearings, TDZ elevation, slope, approach "
                "guidance, the airport / runway / starting element references, "
                "ManoeuvringAreaAvailability (closures) with schedules; one FACILITY Entity per "
                "slice; ingest",
                "AIXMBasicMessage (5.2) / Navaid time slices — type, designator, name, codeICAOCountry, "
                "location ElevatedPoint, NavaidOperationalStatus with schedules, component "
                "equipment, served airport and runway direction references; one FACILITY Entity "
                "per slice; ingest",
                "AIXMBasicMessage (5.2) / VerticalStructure time slices — name, designator, type, "
                "lighting and marking flags, placeName, dataAssessmentStatus, dimensions, every part "
                "with its verticalExtent, its 5.2 height and its point, linear or surface "
                "horizontal projection; one FACILITY Entity per slice; ingest",
            ],
            limits=Limits(
                max_input_bytes=AIXM52_MAX_INPUT_BYTES,
                max_depth=AIXM52_MAX_DEPTH,
                max_objects=AIXM52_MAX_OBJECTS,
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
                            "AIXM 5.2 states no maximum document size. 16 MiB "
                            "(`AIXM52_MAX_INPUT_BYTES`, `adapters/aixm52.py`) is the 5.1.1 "
                            "adapter's figure, chosen on 2026-09-21 for the same document class: "
                            "an AIRAC delta of one aerodrome under 1 MiB, the largest fixture in "
                            "`fixtures/aixm52/` under 16 KiB; a national baseline data set is "
                            "larger and is a data set, not a message. This is an IMPLEMENTATION "
                            "CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the payload is measured and refused before "
                            "any decoder runs; `secure_xml.parse` reads the same bound off the "
                            "octets again before it creates a parser"),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "AIXM 5.2 states no maximum nesting; the pinned geometry forms are the "
                            "5.1.1 ones (an interior Ring of curves nests 22 elements below the "
                            "root) and the deepest XML shipped under `fixtures/aixm52/` nests no "
                            "deeper than 24. 192 (`AIXM52_MAX_DEPTH`, `adapters/aixm52.py`) is "
                            "chosen on 2026-09-21 by the repository's rule of at least eight "
                            "times the deepest shipped document, with room. This is an "
                            "IMPLEMENTATION CAP and is NOT the format's normative maximum."),
                        enforced_at=(
                            "`secure_xml.parse` counts the depth in expat's StartElementHandler "
                            "and refuses on the element that crosses the bound, before the rest "
                            "of the document is read; a parsed twin (a dict) is held to the same "
                            "bound by `Adapter.__init_subclass__`'s `enforce_depth_bound` before "
                            "`to_cdm` runs"),
                        test="tests/test_cdm_aixm52_adapter.py::test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "AIXM 5.2 states no maximum feature or time-slice count. 20 000 "
                            "(`AIXM52_MAX_OBJECTS`, `adapters/aixm52.py`) time slices per "
                            "message, the 5.1.1 adapter's figure (an AIRAC delta with room to "
                            "spare). A second cap the manifest schema has no field for is "
                            "declared beside it: `AIXM52_MAX_ELEMENTS` (500 000), the elements "
                            "across the document, refused by `secure_xml.parse` on the element "
                            "that crosses it. This is an IMPLEMENTATION CAP and is NOT the "
                            "format's normative maximum."),
                        enforced_at=(
                            "`Aixm52Adapter.to_cdm` counts the time slices of every member on the "
                            "twin and raises `ObjectCountExceeded` (a `ValueError`) before any "
                            "canonical object is built"),
                        test="tests/test_cdm_aixm52_adapter.py::test_the_object_bound_admits_a_message_at_it_and_refuses_one_past",
                    ),
                },
            ),
            unknown_fields=UnknownFields.PRESERVED,
            unknown_fields_basis=(
                "an element or attribute this adapter does not type — a property outside the "
                "pinned set, an aixm:extension, an aixm:annotation, an object's own gml:identifier "
                "(new in 5.2), every property of a feature outside the five families, any "
                "foreign-namespace member — is kept in the structured residual at its own path and "
                "position (`residual.data` is the parsed twin minus what the typed block "
                "consumed); `validate_source` names members outside the families"),
        ),
        limitations=[
            Limitation(
                id="pinned-families",
                summary="the five families are Airspace, AirportHeliport, Runway, RunwayDirection, "
                        "Navaid and VerticalStructure, with the AIXM 5.2 property groups pinned "
                        "(the implementation record lists the 5.2 paths per family and the 5.1.1 → "
                        "5.2 differences); a feature of any other class (Unit, "
                        "OrganisationAuthority, Route, Procedure …) becomes an Entity of type UNKNOWN "
                        "carrying the GENERIC reading only — identity, interpretation, sequence and "
                        "correction numbers, validTime, featureLifetime, the pinned simple properties "
                        "the slice happens to state, and the ledger-bound complex elements "
                        "(`CARRIED_ELEMENTS`: location, ARP, a repeated availability, activation, "
                        "part, navaidEquipment, geometryComponent) carried source-verbatim at their "
                        "block field — with every other property in the residual and no position or "
                        "status, and `validate_source` names it; a member that is not a feature at "
                        "all (no aixm:timeSlice) is carried whole in the residual. Within a family "
                        "only the pinned properties are typed; the rest is residual — including the "
                        "5.2 AirspaceVolume `name` and `location`, which ride in the component's "
                        "verbatim source and are not typed",
                unsupported_paths=[],
            ),
            Limitation(
                id="digital-notam-not-available",
                summary=DIGITAL_NOTAM_STATEMENT + ". This adapter therefore reads NO Digital NOTAM: no "
                        "Event feature, no scenario profile (`profiles` is empty), no `attributes.dnotam` "
                        "block and no scenario rule; a member in the AIXM 5.1.1 Event namespace inside a "
                        "5.2 document is named by `validate_source`, carried whole in the residual and "
                        "never typed. Digital NOTAM is the AIXM 5.1.1 adapter's (`aixm511`, limitation "
                        "digital-notam-profiles), on the AIXM 5.1.1 + Event Schema 2.0.m combination "
                        "only; nothing here claims that the same extension works with 5.2",
                unsupported_paths=[],
            ),
            Limitation(
                id="unsupported-geometry-refused",
                summary="gml:ArcByCenterPoint, gml:CircleByCenterPoint, gml:Arc, gml:ArcString, "
                        "gml:Circle, gml:CompositeCurve, gml:OrientableCurve, a CRS other than "
                        "urn:ogc:def:crs:EPSG::4326 and urn:ogc:def:crs:OGC:1.3:CRS84, and a third "
                        "dimension refuse the document by default with the element form and the "
                        "source text named; under `Aixm52Adapter(unsupported_geometry='report')` "
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
                        "converted. An ElevatedPoint's `verticalDatum` is free text in 5.2 "
                        "(`TextNameType`) and is carried as the text stated",
                unsupported_paths=[],
            ),
            Limitation(
                id="cancelled-slice-needs-as-of",
                summary="a time slice with no validTime instant of its own (§4.4.8's cancellation "
                        "with nilReason='inapplicable', an absent validTime, an indeterminate "
                        "begin) can be an Entity only under `Aixm52Adapter(as_of=AsOf(instant, "
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
                        "make the same feature two entities in two documents. The gml:identifier a "
                        "5.2 «object» may carry is a property of that object, never an identity",
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
            "`max_depth` and `max_objects` in the shared reader before any object is built — plus "
            "an element count the manifest schema has no field for. The other two are absent with "
            "their reasons in `capabilities.limits.absent_because`",
            "XML is parsed with the standard library's expat through `secure_xml` and NOT with "
            "`defusedxml`, which is not a dependency of this package: a DOCTYPE is refused at "
            "its declaration before any entity is read, every entity reference other than the "
            "five predefined ones is refused, no external resource is fetched and XInclude is "
            "refused where it starts (`tests/test_cdm_secure_xml.py`). The tree is "
            "`xml.etree.ElementTree`'s own, built through its TreeBuilder",
            "this adapter reads AIXM 5.2 only: a document in the 5.1 or 5.1.1 namespace is "
            "refused at the root with its namespace named; AIXM 5.1.1 is the sibling adapter "
            "`aixm511`, and the two share one reader under two profiles (`aixm511.Profile`)",
        ],
        limitations_empty_reason=None,
        residual=Residual.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    MAPPINGS = aixm511._build_mappings(PROFILE_52)

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        return self._ingest(raw)


__all__ = ["Aixm52Adapter", "AsOf", "ObjectCountExceeded", "TimeSliceBlock", "ReferenceTarget",
           "FAMILIES", "PINNED_SIMPLE", "PART_PROPERTIES", "PROFILE_52", "ADDED_IN_52", "REMOVED_IN_52",
           "DIGITAL_NOTAM_STATEMENT", "AIXM52_MAX_INPUT_BYTES", "AIXM52_MAX_DEPTH", "AIXM52_MAX_ELEMENTS",
           "AIXM52_MAX_OBJECTS"]
