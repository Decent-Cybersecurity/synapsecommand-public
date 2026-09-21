"""The shared AIXM codec: the GML object-property model as a parsed twin, time slices and
their temporality, feature references, the pinned geometry forms, vertical limits and
schedules — parameterised by AIXM version where the schemas differ. No canonical object is
built here (`adapters/aixm511.py` does that) and nothing here reads a file or a socket.

THE PARSED TWIN
---------------
An AIXM document is GML: objects (upper-camel elements — `aixm:Airspace`,
`aixm:AirspaceTimeSlice`, `gml:TimePeriod`, `gml:Surface`) alternate with properties
(lower-camel — `aixm:timeSlice`, `gml:validTime`, `aixm:horizontalProjection`), ISO 19136 §7.2's
"object-property-object" pattern. `twin_of` keeps that pattern but spells it ONE level per
pair: a property that holds an object becomes the object's own dict with the object's element
name under `"$"`, so `aixm:timeSlice` → `{"$": "aixm:AirspaceTimeSlice", ...}` and
`gml:validTime` → `{"$": "gml:TimePeriod", "gml:beginPosition": ...}`. The rule is mechanical
and reversible (the object's name is kept, and a property's own attributes — rare with a child
object — are kept on the object under `"@@name"`), and it exists for a measured reason: a
polygon ring in an airspace volume sits twenty-five containers below the root when every element
is a level, and the harness loader holds a shipped twin to sixteen
(`tests/test_cdm_resource_envelope.py`, `LOADER_MAX_DEPTH / 4`); paired, the same ring sits at
sixteen exactly.

Keys: an element in the AIXM, GML, xlink, XML-Schema-instance or message namespace is spelled
with the conventional prefix (`aixm:`, `gml:`, `xlink:`, `xsi:`, `message:`); any other
namespace in Clark form `{uri}local`; an attribute as `@prefix:name`; text beside attributes as
`#text`; a property with no attributes and no child as its text. A property `REPEATABLE` names
under its parent object is ALWAYS a list, however many the document carried, so a twin's shape
does not depend on a count — the table is generated from the pinned XSD (every object element
reachable from the five pinned families, each with the properties whose particle is unbounded)
plus the GML containers the profile uses; an object the table does not name (an extension, an
object outside the pinned closure) lists a property when it repeats. The root
`message:AIXMBasicMessage` is implied: the twin is its content.

TEMPORALITY (AIXM Temporality Concept 1.1, February 2019, for AIXM 5.1.1)
--------------------------------------------------------------------------
A feature is identified by `gml:identifier` (a UUID, Feature Identification and Reference 1.0
§2.1–2.2) and consists of time slices; a slice is identified by its `interpretation`,
`sequenceNumber` and `correctionNumber` (§4.2: the correction with the highest number is the
valid one). `INTERPRETATIONS` are the four the schema enumerates; `VALID_TIME_FORM` is rules
TS_001–TS_004 (§4.3): BASELINE and TEMPDELTA carry a `gml:TimePeriod` or no validTime, PERMDELTA
and SNAPSHOT a `gml:TimeInstant`. A period's begin is included and its end excluded (§4.4.1); an
`indeterminatePosition="unknown"` end is an open baseline (§4.4.2); an empty validTime with
`nilReason="inapplicable"` cancels the slice (§4.4.8); every position is UTC with `Z` (TS_012).
`property_state` reads §4.4.6.1: in a delta slice an ABSENT property is UNCHANGED and a nil one
(`xsi:nil="true"`, with its nilReason) is WITHDRAWN; in a BASELINE or SNAPSHOT an absent property
is NOT STATED and a nil one is NIL with its reason. The four are distinct values of `state` and
`meaning`, never collapsed.

REFERENCES (Feature Identification and Reference 1.0 §3)
---------------------------------------------------------
`classify_href` names the form: `urn:uuid:<uuid>` (abstract reference by identifier, §3.4.1),
`#<gml:id>` (concrete local reference, §3.2), a URL with or without a fragment (concrete external
reference, §3.3 — CLASSIFIED and never fetched), `urn:aixm:` natural keys (§3.4.2) and anything
else. `DocumentIndex` resolves the first two against the document; a caller-provided table
resolves any `urn:uuid` the document does not hold. A reference is one hop: nothing follows a
resolved target's own references, so a cycle is two resolved references and cannot loop, and
every reference — resolved or not — is kept with its source property, its href and its form.

GEOMETRY (OGC 12-028r1 and the GML 3.2.1 schema AIXM imports; decision D4)
----------------------------------------------------------------------------
`srsName` is read explicitly, on the geometry or inherited from the nearest ancestor geometry
that states one (12-028r1 §6.4). Two CRS URNs are accepted and they differ in AXIS ORDER:
`urn:ogc:def:crs:EPSG::4326` is latitude-first, `urn:ogc:def:crs:OGC:1.3:CRS84` longitude-first;
the canonical position is always longitude, latitude. `srsDimension` other than 2 is
unsupported. The pinned forms are a Point with `gml:pos`; a Curve whose `gml:segments` are
`gml:LineStringSegment` (linear) or `gml:GeodesicString` (geodesic, kept distinct, never
relabelled) with `gml:posList` or `gml:pos`; a Surface whose `gml:patches` are `gml:PolygonPatch`
with a `gml:exterior` and zero or more `gml:interior` rings, each a `gml:Ring` of `gml:curveMember`
curves or a `gml:LinearRing`. Every other form — `gml:ArcByCenterPoint`, `gml:CircleByCenterPoint`,
`gml:Arc`, `gml:ArcString`, `gml:Circle`, `gml:CompositeCurve`, `gml:OrientableCurve`, any other
CRS, three-dimensional positions — raises `GeometryUnsupported` with the element form and the
source text, and NOTHING is approximated: no chord for an arc, no polygon for a circle. Ring
orientation is measured and reported, never repaired.

VERTICAL (AIXM 5.1.1 data model: ValDistanceVerticalType, CodeVerticalReferenceType)
--------------------------------------------------------------------------------------
A limit is a value with `uom` (FT, M, FL, SM) and a separately stated reference (SFC = above
the surface, MSL, W84 = the WGS84 ellipsoid, STD = altimeter at the standard atmosphere). The
CDM reading keeps every one distinct — FT/M against SFC → AGL, MSL → MSL, W84 → HAE, STD → BARO;
FL against STD → the flight-level scale — and converts nothing: feet stay feet, a datum stays
its datum. `UNL` (unlimited), `GND` (the ground), `FLOOR` and `CEILING` are tokens the pattern
admits and they are typed as what they say; SM (standard metres) and an FL against a non-STD
reference have no CDM member and are carried typed with the reason they are not projected.
An `ElevatedPoint`'s `elevation` is "the vertical distance of the point measured from Mean Sea
Level (MSL)" by the model's own definition (Class_ElevatedPoint), so its reference is MSL and its
`verticalDatum` (the geoid model) is carried beside it.
"""
from __future__ import annotations

import dataclasses
import datetime as _dt
import re
import xml.etree.ElementTree as ET
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from synapse_cdm import times

# ------------------------------------------------------------------------------- namespaces

GML_NAMESPACE = "http://www.opengis.net/gml/3.2"
XLINK_NAMESPACE = "http://www.w3.org/1999/xlink"
XSI_NAMESPACE = "http://www.w3.org/2001/XMLSchema-instance"
AIXM_511_NAMESPACE = "http://www.aixm.aero/schema/5.1.1"
AIXM_511_MESSAGE_NAMESPACE = "http://www.aixm.aero/schema/5.1.1/message"
AIXM_52_NAMESPACE = "http://www.aixm.aero/schema/5.2"
AIXM_52_MESSAGE_NAMESPACE = "http://www.aixm.aero/schema/5.2/message"
#: The Digital NOTAM Event Schema (AIXM 5.1.1 Event extension, revision 2.0.m, June 2025): the
#: `event:Event` feature, its `event:EventTimeSlice`, the `event:NOTAM` message objects and the
#: per-feature `event:<Feature>Extension` elements whose `event:theEvent` binds a feature time
#: slice to an Event. Every published revision targets AIXM 5.1.1 (or 5.1, under another
#: namespace); none targets 5.2, so only `VERSION_511` owns it (decision D3).
EVENT_511_NAMESPACE = "http://www.aixm.aero/schema/5.1.1/event"

#: The root of an AIXM data set, in the message namespace of its version.
ROOT_LOCAL = "AIXMBasicMessage"
ROOT_KEY = "message:" + ROOT_LOCAL


@dataclasses.dataclass(frozen=True)
class Version:
    """The two namespaces an AIXM version owns — and, for 5.1.1 only, the Event extension's
    (`event`); a version without one spells an event-namespace element in Clark form, as it
    spells any other foreign namespace. `elevated` is the version's `ElevatedPointPropertyGroup`
    (the same group serves ElevatedCurve and ElevatedSurface), the one structure the codec's
    readers branch on: 5.1.1's `ElevatedPoint` extends `aixm:PointType` and adds `elevation`,
    `geoidUndulation`, `verticalDatum` (a code list) and `verticalAccuracy`; 5.2's extends
    `gml:PointType` DIRECTLY and its group is `elevation`, `geoidUndulation`, `verticalDatum`
    (free text, `TextNameType`), `horizontalAccuracy` and `annotation` — no `verticalAccuracy`
    exists in 5.2 (phase 6, `_tools/aixm_family_diff.py`; decision D56). Everything else in the
    twin is shared; the REPEATABLE table is looked up by `name`."""

    name: str
    aixm: str
    message: str
    event: str | None = None
    elevated: tuple[str, ...] = ("elevation", "geoidUndulation", "verticalDatum", "verticalAccuracy")

    @property
    def prefixes(self) -> dict[str, str]:
        out = {self.aixm: "aixm", self.message: "message", GML_NAMESPACE: "gml",
               XLINK_NAMESPACE: "xlink", XSI_NAMESPACE: "xsi"}
        if self.event is not None:
            out[self.event] = "event"
        return out


VERSION_511 = Version("5.1.1", AIXM_511_NAMESPACE, AIXM_511_MESSAGE_NAMESPACE, EVENT_511_NAMESPACE)
VERSION_52 = Version("5.2", AIXM_52_NAMESPACE, AIXM_52_MESSAGE_NAMESPACE,
                     elevated=("elevation", "geoidUndulation", "verticalDatum", "horizontalAccuracy", "annotation"))
VERSIONS = {VERSION_511.name: VERSION_511, VERSION_52.name: VERSION_52}


def key_of(tag: str, version: Version) -> str:
    """ElementTree's `{uri}local` -> the twin key: a prefixed name for the five known
    namespaces, Clark form for any other, the bare local name for no namespace."""
    if not tag.startswith("{"):
        return tag
    uri, local = tag[1:].split("}", 1)
    prefix = version.prefixes.get(uri)
    return f"{prefix}:{local}" if prefix else tag


# ------------------------------------------------------------------------- the twin builder

#: Object element -> the properties that are ALWAYS a list under it. Generated on 2026-09-21
#: from the pinned AIXM 5.1.1 XSD (`AIXM_Features.xsd`, `AIXM_AbstractGML_ObjectTypes.xsd`):
#: every object element reachable through by-value properties from the five pinned families
#: and — since phase 5, because the NAV.UNS Digital NOTAM scenario binds them by name — from the
#: eleven NavaidEquipment specialisations (Azimuth, DME, DirectionFinder, Elevation, Glidepath,
#: Localizer, MarkerBeacon, NDB, SDF, TACAN, VOR), each with the child elements whose particle is
#: `maxOccurs="unbounded"` (`gml:name` comes from `gml:AbstractGMLType`).
#: `tests/test_cdm_aixm_codec.py` re-derives the AIXM rows from the schema under the `normative`
#: marker. The GML rows are the containers the pinned geometry and time forms use, read from
#: `geometryPrimitives.xsd` / `geometryBasic0d1d.xsd` / `geometryAggregates.xsd`; the message row
#: from `AIXM_BasicMessage.xsd`.
REPEATABLE: dict[str, tuple[str, ...]] = {
    "message:AIXMBasicMessage": ("message:hasMember",),
    "aixm:AircraftCharacteristic": ("aixm:annotation", "aixm:extension"),
    "aixm:AirportHeliport": ("aixm:timeSlice", "gml:name"),
    "aixm:AirportHeliportAvailability": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval", "aixm:usage"),
    "aixm:AirportHeliportContamination": ("aixm:annotation", "aixm:criticalRidge", "aixm:extension", "aixm:layer"),
    "aixm:AirportHeliportResponsibilityOrganisation": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:AirportHeliportTimeSlice": ("aixm:altimeterSource", "aixm:annotation", "aixm:availability", "aixm:contact", "aixm:contaminant", "aixm:extension", "aixm:servedCity"),
    "aixm:AirportHeliportUsage": ("aixm:annotation", "aixm:contact", "aixm:extension"),
    "aixm:Airspace": ("aixm:timeSlice", "gml:name"),
    "aixm:AirspaceActivation": ("aixm:aircraft", "aixm:annotation", "aixm:extension", "aixm:levels", "aixm:specialDateAuthority", "aixm:timeInterval", "aixm:user"),
    "aixm:AirspaceGeometryComponent": ("aixm:annotation", "aixm:extension"),
    "aixm:AirspaceLayer": ("aixm:annotation", "aixm:extension"),
    "aixm:AirspaceLayerClass": ("aixm:annotation", "aixm:associatedLevels", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:AirspaceTimeSlice": ("aixm:activation", "aixm:annotation", "aixm:class", "aixm:extension", "aixm:geometryComponent"),
    "aixm:AirspaceVolume": ("aixm:annotation", "aixm:extension"),
    "aixm:AirspaceVolumeDependency": ("aixm:annotation", "aixm:extension"),
    "aixm:City": ("aixm:annotation", "aixm:extension"),
    "aixm:ConditionCombination": ("aixm:aircraft", "aixm:annotation", "aixm:extension", "aixm:flight", "aixm:specialDateAuthority", "aixm:subCondition", "aixm:timeInterval", "aixm:weather"),
    "aixm:ContactInformation": ("aixm:address", "aixm:annotation", "aixm:extension", "aixm:networkNode", "aixm:phoneFax"),
    "aixm:Curve": ("aixm:annotation", "gml:segments"),
    "aixm:ElevatedCurve": ("aixm:annotation", "aixm:extension", "gml:segments"),
    "aixm:ElevatedPoint": ("aixm:annotation", "aixm:extension"),
    "aixm:ElevatedSurface": ("aixm:annotation", "aixm:extension", "gml:patches"),
    "aixm:FlightCharacteristic": ("aixm:annotation", "aixm:extension"),
    "aixm:LightElement": ("aixm:annotation", "aixm:availability", "aixm:extension"),
    "aixm:LightElementStatus": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:LinguisticNote": ("aixm:extension",),
    "aixm:ManoeuvringAreaAvailability": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval", "aixm:usage"),
    "aixm:ManoeuvringAreaUsage": ("aixm:annotation", "aixm:contact", "aixm:extension"),
    "aixm:Meteorology": ("aixm:annotation", "aixm:extension"),
    "aixm:Navaid": ("aixm:timeSlice", "gml:name"),
    "aixm:NavaidComponent": ("aixm:annotation", "aixm:extension"),
    "aixm:NavaidOperationalStatus": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:NavaidTimeSlice": ("aixm:annotation", "aixm:availability", "aixm:extension", "aixm:navaidEquipment", "aixm:runwayDirection", "aixm:servedAirport", "aixm:touchDownLiftOff"),
    "aixm:Note": ("aixm:extension", "aixm:translatedNote"),
    "aixm:OnlineContact": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:PostalAddress": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:Ridge": ("aixm:annotation", "aixm:extension"),
    "aixm:Runway": ("aixm:timeSlice", "gml:name"),
    "aixm:RunwayContamination": ("aixm:annotation", "aixm:criticalRidge", "aixm:extension", "aixm:layer"),
    "aixm:RunwayDirection": ("aixm:timeSlice", "gml:name"),
    "aixm:RunwayDirectionTimeSlice": ("aixm:annotation", "aixm:availability", "aixm:extension"),
    "aixm:RunwaySectionContamination": ("aixm:annotation", "aixm:criticalRidge", "aixm:extension", "aixm:layer"),
    "aixm:RunwayTimeSlice": ("aixm:annotation", "aixm:areaContaminant", "aixm:extension", "aixm:overallContaminant"),
    "aixm:Surface": ("aixm:annotation", "gml:patches"),
    "aixm:SurfaceCharacteristics": ("aixm:annotation", "aixm:extension"),
    "aixm:SurfaceContaminationLayer": ("aixm:annotation", "aixm:extension", "aixm:extent"),
    "aixm:TelephoneContact": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:Timesheet": ("aixm:annotation", "aixm:extension"),
    "aixm:VerticalStructure": ("aixm:timeSlice", "gml:name"),
    "aixm:VerticalStructureLightingStatus": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:VerticalStructurePart": ("aixm:annotation", "aixm:extension", "aixm:lighting", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:VerticalStructureTimeSlice": ("aixm:annotation", "aixm:extension", "aixm:hostedNavaidEquipment", "aixm:hostedOrganisation", "aixm:hostedPassengerService", "aixm:hostedSpecialNavStation", "aixm:hostedUnit", "aixm:lightingAvailability", "aixm:part", "aixm:supportedGroundLight", "aixm:supportedService"),
    "aixm:AuthorityForNavaidEquipment": ("aixm:annotation", "aixm:extension"),
    "aixm:Azimuth": ("aixm:timeSlice", "gml:name"),
    "aixm:AzimuthTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:DME": ("aixm:timeSlice", "gml:name"),
    "aixm:DMETimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:DirectionFinder": ("aixm:timeSlice", "gml:name"),
    "aixm:DirectionFinderTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:informationProvision", "aixm:monitoring"),
    "aixm:Elevation": ("aixm:timeSlice", "gml:name"),
    "aixm:ElevationTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:Glidepath": ("aixm:timeSlice", "gml:name"),
    "aixm:GlidepathTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:Localizer": ("aixm:timeSlice", "gml:name"),
    "aixm:LocalizerTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:MarkerBeacon": ("aixm:timeSlice", "gml:name"),
    "aixm:MarkerBeaconTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:NDB": ("aixm:timeSlice", "gml:name"),
    "aixm:NDBTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:NavaidEquipmentMonitoring": ("aixm:annotation", "aixm:extension", "aixm:specialDateAuthority", "aixm:timeInterval"),
    "aixm:SDF": ("aixm:timeSlice", "gml:name"),
    "aixm:SDFTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:TACAN": ("aixm:timeSlice", "gml:name"),
    "aixm:TACANTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    "aixm:VOR": ("aixm:timeSlice", "gml:name"),
    "aixm:VORTimeSlice": ("aixm:annotation", "aixm:authority", "aixm:availability", "aixm:extension", "aixm:monitoring"),
    # GML containers of the pinned geometry forms (geometryPrimitives.xsd, geometryBasic0d1d.xsd,
    # geometryAggregates.xsd, GML 3.2.1 as served with AIXM 5.1.1).
    "gml:Surface": ("gml:patches",),
    "gml:Polygon": ("gml:interior",),
    "gml:PolygonPatch": ("gml:interior",),
    "gml:Ring": ("gml:curveMember",),
    "gml:Curve": ("gml:segments",),
    "gml:CompositeCurve": ("gml:curveMember",),
    "gml:LineString": ("gml:pos", "gml:pointProperty"),
    "gml:LinearRing": ("gml:pos", "gml:pointProperty"),
    "gml:LineStringSegment": ("gml:pos", "gml:pointProperty"),
    "gml:GeodesicString": ("gml:pos", "gml:pointProperty"),
    "gml:ArcString": ("gml:pos", "gml:pointProperty"),
    "gml:Arc": ("gml:pos", "gml:pointProperty"),
    "gml:Circle": ("gml:pos", "gml:pointProperty"),
    "gml:MultiSurface": ("gml:surfaceMember",),
    "gml:MultiCurve": ("gml:curveMember",),
    "gml:MultiPoint": ("gml:pointMember",),
    # The Digital NOTAM Event Schema 2.0.m (`Event_Features.xsd`, namespace `EVENT_511_NAMESPACE`):
    # every event-namespace object element reachable from `event:Event` by value, each with its
    # `maxOccurs="unbounded"` children — derived from the pinned schema on 2026-09-21 (the AIS
    # message objects `event:NOTAM` / `event:SNOWTAM` / `event:ASHTAM` and `event:AISProduct`
    # are what an EventTimeSlice's `notification` and `container` hold). The
    # `event:<Feature>Extension` elements repeat nothing (`event:theEvent` is maxOccurs 1).
    # `tests/test_cdm_aixm511_dnotam.py` re-derives these rows under the `normative` marker.
    "event:Event": ("event:timeSlice",),
    "event:EventTimeSlice": ("event:annotation", "event:concernedAirportHeliport", "event:concernedAirspace",
                             "event:container", "event:extension", "event:notification"),
    "event:NOTAM": ("event:annotation", "event:extension"),
    "event:SNOWTAM": ("event:annotation", "event:extension", "event:runwayCondition"),
    "event:ASHTAM": ("event:annotation", "event:extension"),
    "event:AISProduct": ("event:annotation", "event:extension"),
    "event:RunwayAssessment": ("event:annotation", "event:extension"),
}

#: The AIXM 5.2 table: the SAME derivation over the pinned AIXM 5.2.0 XSD (17 January 2025)
#: from the same seventeen roots, on 2026-09-21 (phase 6). It is the 5.1.1 table's AIXM and GML
#: rows with the eight rows the 5.2 schema moves — no event rows, because no Event schema exists
#: for 5.2 (decision D3) — and `tests/test_cdm_aixm52_adapter.py` re-derives every AIXM row of it
#: from the 5.2 schema under the `normative` marker, as the 5.1.1 test does for its table.
REPEATABLE_52_MOVED: dict[str, tuple[str, ...]] = {
    # AircraftCharacteristic gains the unbounded `radioNavigationEquipment` (a new object).
    "aixm:AircraftCharacteristic": ("aixm:annotation", "aixm:extension", "aixm:radioNavigationEquipment"),
    "aixm:AircraftNavigationEquipment": ("aixm:annotation", "aixm:extension"),
    # `responsibleOrganisation` is 1 in 5.1.1 and unbounded in 5.2.
    "aixm:AirportHeliportTimeSlice": ("aixm:altimeterSource", "aixm:annotation", "aixm:availability", "aixm:contact",
                                      "aixm:contaminant", "aixm:extension", "aixm:responsibleOrganisation",
                                      "aixm:servedCity"),
    # `altimeterSource` holds an AltimeterSource OBJECT by value in 5.2; in 5.1.1 AltimeterSource
    # is a feature and the property a reference, so the object was not reachable by value.
    "aixm:AltimeterSource": ("aixm:annotation", "aixm:extension"),
    # `aixm:Point` / `Curve` / `Surface` gain their own `extension` (the Elevated forms no
    # longer extend them and keep theirs).
    "aixm:Curve": ("aixm:annotation", "aixm:extension", "gml:segments"),
    "aixm:Point": ("aixm:annotation", "aixm:extension"),
    "aixm:Surface": ("aixm:annotation", "aixm:extension", "gml:patches"),
    # VerticalStructure gains the unbounded `arrestingDevice`.
    "aixm:VerticalStructureTimeSlice": ("aixm:annotation", "aixm:arrestingDevice", "aixm:extension",
                                        "aixm:hostedNavaidEquipment", "aixm:hostedOrganisation",
                                        "aixm:hostedPassengerService", "aixm:hostedSpecialNavStation",
                                        "aixm:hostedUnit", "aixm:lightingAvailability", "aixm:part",
                                        "aixm:supportedGroundLight", "aixm:supportedService"),
}
REPEATABLE_52: dict[str, tuple[str, ...]] = {
    **{k: v for k, v in REPEATABLE.items() if not k.startswith("event:")}, **REPEATABLE_52_MOVED}
REPEATABLE_BY_VERSION: dict[str, dict[str, tuple[str, ...]]] = {VERSION_511.name: REPEATABLE,
                                                                  VERSION_52.name: REPEATABLE_52}

#: The event-namespace rows of `REPEATABLE` — re-derived from `Event_Features.xsd` by a test.
REPEATABLE_EVENT_ROWS: tuple[str, ...] = tuple(k for k in REPEATABLE if k.startswith("event:"))

#: The AIXM rows of `REPEATABLE` — the half a normative test re-derives from the schema.
REPEATABLE_AIXM_ROWS: tuple[str, ...] = tuple(k for k in REPEATABLE if k.startswith("aixm:"))
#: The feature elements the derivation starts from: the five families and NAV.UNS's equipment.
REPEATABLE_ROOTS: tuple[str, ...] = ("Airspace", "AirportHeliport", "Runway", "RunwayDirection", "Navaid",
                                     "VerticalStructure", "Azimuth", "DME", "DirectionFinder", "Elevation",
                                     "Glidepath", "Localizer", "MarkerBeacon", "NDB", "SDF", "TACAN", "VOR")

#: Properties whose particle is unbounded in EVERY type of the pinned schema that declares them
#: (read 2026-09-21: `timeSlice` 125 declarations, `annotation` 156, `extension` 242, all
#: `maxOccurs="unbounded"`; `gml:name` from `gml:AbstractGMLType`; `message:hasMember` from the
#: message schema), so they are lists under ANY object — a feature outside the five families
#: keeps the same shape as one inside them.
REPEATABLE_ANYWHERE: frozenset[str] = frozenset(
    {"aixm:timeSlice", "aixm:annotation", "aixm:extension", "gml:name", "message:hasMember"})


def repeatable(parent_object: str, prop: str, version: Version = VERSION_511) -> bool:
    return prop in REPEATABLE_ANYWHERE or prop in REPEATABLE_BY_VERSION[version.name].get(parent_object, ())


def twin_of(root: ET.Element, version: Version) -> dict:
    """The document as its parsed twin: the content of `message:AIXMBasicMessage`. A root in
    another namespace or of another name is refused with what it was."""
    key = key_of(root.tag, version)
    if key != ROOT_KEY:
        if key.startswith("{"):
            uri, local = key[1:].split("}", 1)
            raise ValueError(f"AIXM root element <{local}> is in namespace {uri!r}; this adapter reads "
                             f"AIXM {version.name} whose message namespace is {version.message!r} "
                             f"(and whose feature namespace is {version.aixm!r}); a document in another "
                             "namespace or version is refused, not read")
        raise ValueError(f"AIXM root element is <{key}>, not <{ROOT_KEY}> (AIXM_BasicMessage.xsd)")
    return object_node(root, key, version)


def object_node(element: ET.Element, name: str, version: Version) -> dict:
    """One OBJECT element -> its dict: attributes, then its properties in document order."""
    node: dict[str, Any] = {}
    for attribute, value in element.attrib.items():
        node["@" + key_of(attribute, version)] = value
    text = (element.text or "").strip()
    if text:
        node["#text"] = text
    for child in element:
        prop = key_of(child.tag, version)
        objects = [c for c in child]
        if objects:
            values: list[Any] = []
            for obj in objects:
                item = object_node(obj, key_of(obj.tag, version), version)
                item = {"$": key_of(obj.tag, version), **item}
                for attribute, value in child.attrib.items():
                    item["@@" + key_of(attribute, version)] = value
                values.append(item)
            _add(node, name, prop, values, force_list=len(values) != 1, version=version)
        else:
            _add(node, name, prop, [scalar_node(child, version)], force_list=False, version=version)
    return node


def scalar_node(element: ET.Element, version: Version) -> Any:
    """A PROPERTY with no child object: its text, or a dict of attributes and `#text`."""
    node: dict[str, Any] = {"@" + key_of(a, version): v for a, v in element.attrib.items()}
    text = (element.text or "").strip()
    if not node:
        return text
    if text:
        node["#text"] = text
    return node


def _add(node: dict, parent: str, prop: str, values: list, *, force_list: bool,
         version: Version = VERSION_511) -> None:
    if repeatable(parent, prop, version) or force_list or prop in node:
        existing = node.get(prop)
        if existing is None:
            node[prop] = list(values)
        elif isinstance(existing, list):
            existing.extend(values)
        else:
            node[prop] = [existing, *values]
    else:
        node[prop] = values[0]


def as_list(node: dict, prop: str) -> list:
    """A property as a list whatever its twin form (absent -> [], one -> [one])."""
    value = node.get(prop)
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def object_name(node: Any) -> str | None:
    return node.get("$") if isinstance(node, dict) else None


# ------------------------------------------------------------------ scalar properties

class Contract(BaseModel):
    """Every typed block is closed: a key the contract does not name is a mistake, not data."""
    model_config = ConfigDict(extra="forbid")


@dataclasses.dataclass(frozen=True)
class Scalar:
    """One simple property as the document stated it."""

    text: str | None
    nil: bool
    nil_reason: str | None
    uom: str | None
    attributes: dict[str, str]

    @property
    def present(self) -> bool:
        return self.text is not None and self.text != ""


def scalar(node: Any) -> Scalar:
    """Read a simple property node (text, or attributes + `#text`)."""
    if node is None:
        return Scalar(None, False, None, None, {})
    if isinstance(node, list):
        raise ValueError("a simple property occurred more than once where the schema admits one; "
                         "the twin holds a list and the reading refuses to pick")
    if not isinstance(node, dict):
        return Scalar(str(node), False, None, None, {})
    if "$" in node:
        raise ValueError(f"expected a simple property and found the object <{node['$']}>")
    attributes = {k[1:]: v for k, v in node.items() if k.startswith("@")}
    nil = attributes.get("xsi:nil") in ("true", "1")
    text = node.get("#text")
    return Scalar(None if text is None else str(text), nil, attributes.get("nilReason"),
                  attributes.get("uom"), attributes)


INTERPRETATIONS = ("BASELINE", "PERMDELTA", "TEMPDELTA", "SNAPSHOT")
DELTA_INTERPRETATIONS = ("PERMDELTA", "TEMPDELTA")
NIL_REASONS = ("inapplicable", "missing", "template", "unknown", "withheld")


class PropertyState(Contract):
    """One pinned property of a time slice: what the document said, and what that means under
    the slice's interpretation (Temporality Concept 1.1 §4.4.6.1)."""

    state: Literal["stated", "nil", "absent"]
    meaning: Literal["stated", "nil", "withdrawn", "unchanged", "not stated"]
    value: str | None = None
    uom: str | None = None
    nil_reason: str | None = None


def property_state(node: Any, interpretation: str) -> PropertyState:
    """Absent, nil and stated kept apart, and read under the slice's interpretation: a delta's
    absent property is UNCHANGED and its nil property WITHDRAWN; a baseline's are NOT STATED
    and NIL. The nilReason is carried in both readings."""
    delta = interpretation in DELTA_INTERPRETATIONS
    if node is None:
        return PropertyState(state="absent", meaning="unchanged" if delta else "not stated")
    value = scalar(node)
    if value.nil or (not value.present and value.nil_reason is not None):
        return PropertyState(state="nil", meaning="withdrawn" if delta else "nil",
                             nil_reason=value.nil_reason, uom=value.uom)
    return PropertyState(state="stated", meaning="stated", value=value.text, uom=value.uom,
                         nil_reason=value.nil_reason)


# --------------------------------------------------------------------------- temporality

#: TS_001–TS_004: the GML time primitive each interpretation's validTime carries.
VALID_TIME_FORM = {"BASELINE": "gml:TimePeriod", "PERMDELTA": "gml:TimeInstant",
                   "TEMPDELTA": "gml:TimePeriod", "SNAPSHOT": "gml:TimeInstant"}
INDETERMINATE = ("unknown", "now", "before", "after")


class TimePosition(Contract):
    """A `gml:beginPosition` / `gml:endPosition` / `gml:timePosition` as stated: the text, the
    instant it denotes when it denotes one, the `indeterminatePosition` when it carries one, and
    whether the text carried the `Z` rule TS_012 requires."""

    text: str | None = None
    instant: str | None = None
    indeterminate: str | None = None
    utc: bool | None = None
    frame: str | None = None
    problem: str | None = None


class TimePrimitive(Contract):
    """`gml:validTime` or `aixm:featureLifetime`: a period, an instant, nothing, or an empty
    property with a nilReason (§4.4.8's cancellation form)."""

    form: Literal["period", "instant", "absent", "nil"]
    element: str | None = None
    gml_id: str | None = None
    begin: TimePosition | None = None
    end: TimePosition | None = None
    time: TimePosition | None = None
    nil_reason: str | None = None
    convention: str | None = None


PERIOD_CONVENTION = ("begin included, end excluded — AIXM Temporality Concept 1.1 §4.4.1; the "
                     "end position is the first instant the slice no longer applies")


def read_time_position(node: Any) -> TimePosition:
    value = scalar(node)
    indeterminate = value.attributes.get("indeterminatePosition")
    frame = value.attributes.get("frame")
    if not value.present:
        return TimePosition(indeterminate=indeterminate, frame=frame,
                            problem=None if indeterminate else "empty position with no "
                                                                "indeterminatePosition")
    text = value.text or ""
    try:
        instant = times.parse(text)
    except (TypeError, ValueError):
        return TimePosition(text=text, indeterminate=indeterminate, frame=frame,
                            problem=f"{text!r} is not an ISO 8601 date-time")
    utc = text.endswith("Z")
    problem = None if utc else (f"{text!r} does not carry the 'Z' zone designator TS_012 "
                                "requires; read as the offset it states")
    if "T24" in text:
        problem = f"{text!r} spells 24:00 (TS_020 forbids it)"
    return TimePosition(text=text, instant=times.render(instant), indeterminate=indeterminate,
                        utc=utc, frame=frame, problem=problem)


def read_time_primitive(node: Any) -> TimePrimitive:
    """validTime / featureLifetime -> `TimePrimitive`. A property holding a TimePeriod or a
    TimeInstant, an empty property (with or without a nilReason), or nothing at all."""
    if node is None:
        return TimePrimitive(form="absent")
    if isinstance(node, list):
        raise ValueError("validTime/featureLifetime occurred more than once on one time slice")
    name = object_name(node)
    if name is None:
        value = scalar(node)
        return TimePrimitive(form="nil", nil_reason=value.nil_reason)
    gml_id = node.get("@gml:id")
    if name == "gml:TimePeriod":
        return TimePrimitive(form="period", element=name, gml_id=gml_id,
                             begin=read_time_position(node.get("gml:beginPosition")),
                             end=read_time_position(node.get("gml:endPosition")),
                             convention=PERIOD_CONVENTION)
    if name == "gml:TimeInstant":
        return TimePrimitive(form="instant", element=name, gml_id=gml_id,
                             time=read_time_position(node.get("gml:timePosition")))
    raise ValueError(f"validTime/featureLifetime holds <{name}>, which is neither gml:TimePeriod "
                     "nor gml:TimeInstant")


def instant_of(position: TimePosition | None) -> _dt.datetime | None:
    if position is None or position.instant is None:
        return None
    return times.parse(position.instant)


def temporality_problems(interpretation: str | None, sequence: str | None, correction: str | None,
                         valid_time: TimePrimitive, lifetime: TimePrimitive, where: str) -> list[str]:
    """The Temporality Concept's coding rules a single slice can be held to on its own:
    TS_001–TS_004 (form per interpretation), TS_006 (no numbers on a SNAPSHOT), TS_012/TS_013
    (UTC), TS_016 (no lifetime in a TEMPDELTA), TS_020 (no 24:00). Cross-slice rules (TS_005,
    TS_009–TS_011) are the document reader's."""
    problems: list[str] = []
    if interpretation not in INTERPRETATIONS:
        problems.append(f"{where}: interpretation {interpretation!r} is not one of {INTERPRETATIONS}")
        return problems
    expected = VALID_TIME_FORM[interpretation]
    if valid_time.form in ("period", "instant") and valid_time.element != expected:
        rule = {"BASELINE": "TS_001", "PERMDELTA": "TS_002", "TEMPDELTA": "TS_003", "SNAPSHOT": "TS_004"}
        problems.append(f"{where}: a {interpretation} slice carries validTime/{valid_time.element}; "
                        f"{rule[interpretation]} requires {expected}")
    if interpretation == "SNAPSHOT":
        if valid_time.form != "instant":
            problems.append(f"{where}: TS_004 requires a SNAPSHOT to carry validTime/gml:TimeInstant")
        if sequence is not None or correction is not None:
            problems.append(f"{where}: TS_006 forbids sequenceNumber/correctionNumber on a SNAPSHOT")
    if interpretation == "TEMPDELTA" and lifetime.form != "absent":
        problems.append(f"{where}: TS_016 forbids featureLifetime in a TEMPDELTA")
    for label, primitive in (("validTime", valid_time), ("featureLifetime", lifetime)):
        for position in (primitive.begin, primitive.end, primitive.time):
            if position is not None and position.problem:
                problems.append(f"{where}: {label} {position.problem}")
    return problems


# ---------------------------------------------------------------------------- identity

UUID_PATTERN = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


class FeatureIdentity(Contract):
    element: str
    family: str
    gml_id: str | None = None
    identifier: str | None = None
    identifier_code_space: str | None = None


def read_identifier(node: dict) -> tuple[str | None, str | None]:
    """`gml:identifier` -> (UUID text, codeSpace). The text is normalised to lower case for the
    identity derivation only; the stated text is what the block carries."""
    value = scalar(node.get("gml:identifier"))
    return (value.text if value.present else None), value.attributes.get("codeSpace")


# --------------------------------------------------------------------------- references

REFERENCE_FORMS = ("urn-uuid", "local-id", "url", "natural-key", "other")


class ReferenceTarget(Contract):
    """What a reference resolved to: the feature's element and identifier, its document
    position when it is in the document, and where the resolution came from."""

    element: str | None = None
    identifier: str | None = None
    gml_id: str | None = None
    member_index: int | None = None
    where: Literal["document", "table"]


class Reference(Contract):
    """One xlink reference, resolved or not, with its source property and form."""

    property: str
    href: str | None = None
    title: str | None = None
    form: Literal["urn-uuid", "local-id", "url", "natural-key", "other", "none"]
    key: str | None = None
    resolved: bool
    target: ReferenceTarget | None = None
    nil_reason: str | None = None


def classify_href(href: str) -> tuple[str, str | None]:
    """(form, lookup key). `urn:uuid:` and `#id` are the two forms resolved in a document;
    a URL is classified by its scheme and NEVER fetched; `urn:aixm:` natural keys are kept."""
    text = href.strip()
    lower = text.lower()
    if lower.startswith("urn:uuid:"):
        return "urn-uuid", text[9:].lower()
    if text.startswith("#"):
        return "local-id", text[1:]
    if lower.startswith("urn:aixm:"):
        return "natural-key", text
    scheme = text.partition(":")[0]
    if text.partition(":")[1] and scheme.isalpha() and lower.startswith(("http:", "https:", "ftp:", "file:")):
        return "url", text
    return "other", text


@dataclasses.dataclass
class DocumentIndex:
    """Features of one document by identifier (lower-cased UUID text) and by gml:id."""

    by_identifier: dict[str, ReferenceTarget] = dataclasses.field(default_factory=dict)
    by_gml_id: dict[str, ReferenceTarget] = dataclasses.field(default_factory=dict)
    duplicates: list[str] = dataclasses.field(default_factory=list)

    @classmethod
    def of(cls, members: list[Any]) -> "DocumentIndex":
        index = cls()
        for position, member in enumerate(members):
            if not isinstance(member, dict) or "$" not in member:
                continue
            identifier, _ = read_identifier(member)
            gml_id = member.get("@gml:id")
            target = ReferenceTarget(element=member["$"], identifier=identifier, gml_id=gml_id,
                                     member_index=position, where="document")
            if identifier:
                key = identifier.lower()
                if key in index.by_identifier:
                    index.duplicates.append(f"gml:identifier {identifier} is carried by members "
                                            f"{index.by_identifier[key].member_index} and {position}")
                else:
                    index.by_identifier[key] = target
            if gml_id:
                if gml_id in index.by_gml_id:
                    index.duplicates.append(f"gml:id {gml_id!r} is carried by members "
                                            f"{index.by_gml_id[gml_id].member_index} and {position}")
                else:
                    index.by_gml_id[gml_id] = target
        return index


def resolve_reference(prop: str, node: Any, index: DocumentIndex,
                      table: dict[str, ReferenceTarget] | None = None) -> Reference:
    """One reference property -> `Reference`. Resolution is by identifier (`urn:uuid:`), by
    gml:id (`#id`, and the `#uuid.<uuid>` convention falls back to the identifier), or through
    the caller's table keyed by lower-cased UUID text. One hop; nothing is fetched."""
    if node is None or isinstance(node, list):
        raise ValueError(f"reference property {prop} is absent or repeated where one was expected")
    if isinstance(node, dict) and "$" in node:
        raise ValueError(f"reference property {prop} holds the object <{node['$']}> by value; "
                         "the pinned profile references features by xlink:href")
    value = scalar(node)
    href = value.attributes.get("xlink:href")
    title = value.attributes.get("xlink:title")
    if href is None:
        return Reference(property=prop, title=title, form="none", resolved=False,
                         nil_reason=value.nil_reason)
    form, key = classify_href(href)
    target: ReferenceTarget | None = None
    if form == "urn-uuid" and key is not None:
        target = index.by_identifier.get(key)
        if target is None and table:
            target = table.get(key)
    elif form == "local-id" and key is not None:
        target = index.by_gml_id.get(key)
        if target is None and key.lower().startswith("uuid.") and UUID_PATTERN.fullmatch(key[5:]):
            target = index.by_identifier.get(key[5:].lower())
            if target is None and table:
                target = table.get(key[5:].lower())
    return Reference(property=prop, href=href, title=title, form=form, key=key,  # type: ignore[arg-type]
                     resolved=target is not None, target=target, nil_reason=value.nil_reason)


# ----------------------------------------------------------------------------- geometry

#: The two CRS URNs the profile admits, with their AXIS ORDER (OGC 12-028r1 §6.2–6.3).
CRS_AXIS_ORDER: dict[str, tuple[str, str]] = {
    "urn:ogc:def:crs:EPSG::4326": ("latitude", "longitude"),
    "urn:ogc:def:crs:OGC:1.3:CRS84": ("longitude", "latitude"),
}
LINEAR_SEGMENTS = {"gml:LineStringSegment": "linear", "gml:GeodesicString": "geodesic"}
UNSUPPORTED_SEGMENTS = ("gml:ArcByCenterPoint", "gml:CircleByCenterPoint", "gml:Arc",
                        "gml:ArcString", "gml:Circle", "gml:ArcByBulge", "gml:ArcStringByBulge",
                        "gml:Bezier", "gml:BSpline", "gml:Clothoid", "gml:CubicSpline",
                        "gml:OffsetCurve", "gml:GeodesicString-with-arcs")
GEOMETRY_KINDS = ("crs", "dimension", "segment", "patch", "ring", "curve", "element", "coordinates",
                  "closure", "composite")


class GeometryUnsupported(ValueError):
    """A geometry form outside the pinned profile, refused with its source text — never
    approximated. `kind` is one of `GEOMETRY_KINDS`; `element` the GML element met; `source` the
    text (a posList, a radius, an srsName) the reader stopped at."""

    def __init__(self, kind: str, element: str | None, message: str, source: Any = None) -> None:
        if kind not in GEOMETRY_KINDS:
            raise ValueError(f"{kind!r} is not one of {GEOMETRY_KINDS}")
        self.kind, self.element, self.source = kind, element, source
        super().__init__(f"unsupported geometry ({kind}{', ' + element if element else ''}): {message}")


class CrsReading(Contract):
    srs_name: str
    axis_order: tuple[str, str]
    srs_dimension: int | None = None
    inherited: bool = False


class PointReading(Contract):
    element: str
    gml_id: str | None = None
    crs: CrsReading
    pos_text: str
    longitude: float
    latitude: float


class SegmentReading(Contract):
    """One segment as stated. Its positions are in the CURVE's `coordinates` (joins kept once);
    the segment carries the source text and the count, which keeps a shipped golden inside the
    harness loader's depth margin."""

    element: str
    interpolation: Literal["linear", "geodesic"]
    stated_interpolation: str | None = None
    pos_list_text: str | None = None
    pos_texts: list[str] = []
    count: int


class CurveReading(Contract):
    element: str
    gml_id: str | None = None
    crs: CrsReading
    segments: list[SegmentReading]
    coordinates: list[list[float]]


class RingReading(Contract):
    role: Literal["exterior", "interior"]
    element: str
    gml_id: str | None = None
    curves: list[CurveReading] = []
    pos_list_text: str | None = None
    coordinates: list[list[float]]
    orientation: Literal["counter-clockwise", "clockwise", "degenerate"]


class PatchReading(Contract):
    element: str
    stated_interpolation: str | None = None
    exterior: RingReading
    interiors: list[RingReading] = []


class SurfaceReading(Contract):
    element: str
    gml_id: str | None = None
    crs: CrsReading
    patches: list[PatchReading]
    geojson: dict


def _srs(node: dict, inherited: CrsReading | None, element: str) -> CrsReading:
    stated = node.get("@srsName")
    dimension_text = node.get("@srsDimension")
    if stated is None:
        if inherited is None:
            raise GeometryUnsupported("crs", element, "no srsName on the geometry or any ancestor; "
                                      "OGC 12-028r1 §6.4 requires the CRS to be stated and this "
                                      "reader assumes none", source=None)
        crs = CrsReading(srs_name=inherited.srs_name, axis_order=inherited.axis_order,
                         srs_dimension=inherited.srs_dimension, inherited=True)
    else:
        order = CRS_AXIS_ORDER.get(stated)
        if order is None:
            raise GeometryUnsupported("crs", element, f"srsName {stated!r} is not one of the two "
                                      f"pinned CRS forms {sorted(CRS_AXIS_ORDER)}", source=stated)
        crs = CrsReading(srs_name=stated, axis_order=order)
    if dimension_text is not None:
        try:
            dimension = int(dimension_text)
        except ValueError:
            raise GeometryUnsupported("dimension", element, f"srsDimension {dimension_text!r} is not "
                                      "an integer", source=dimension_text) from None
        if dimension != 2:
            raise GeometryUnsupported("dimension", element, f"srsDimension {dimension} positions are "
                                      "outside the two-dimensional profile", source=dimension_text)
        crs = crs.model_copy(update={"srs_dimension": dimension})
    return crs


def _numbers(text: str, element: str) -> list[float]:
    out = []
    for token in text.split():
        try:
            value = float(token)
        except ValueError:
            raise GeometryUnsupported("coordinates", element, f"{token!r} is not a number", source=text) from None
        if value != value or value in (float("inf"), float("-inf")):
            raise GeometryUnsupported("coordinates", element, f"{token!r} is not finite", source=text)
        out.append(value)
    return out


def _pairs(numbers: list[float], crs: CrsReading, element: str, source: str) -> list[list[float]]:
    if len(numbers) % 2:
        raise GeometryUnsupported("coordinates", element, f"{len(numbers)} ordinates do not pair into "
                                  "two-dimensional positions", source=source)
    lat_first = crs.axis_order[0] == "latitude"
    coordinates = []
    for i in range(0, len(numbers), 2):
        a, b = numbers[i], numbers[i + 1]
        lon, lat = (b, a) if lat_first else (a, b)
        if not -180.0 <= lon <= 180.0 or not -90.0 <= lat <= 90.0:
            raise GeometryUnsupported("coordinates", element, f"position ({a}, {b}) read under "
                                      f"{crs.srs_name} ({crs.axis_order[0]} first) is longitude {lon}, "
                                      f"latitude {lat}, outside WGS84 range", source=source)
        coordinates.append([lon, lat])
    return coordinates


def read_point(node: Any, inherited: CrsReading | None = None) -> PointReading:
    """`aixm:Point` / `aixm:ElevatedPoint` / `gml:Point` with ONE `gml:pos`."""
    name = object_name(node)
    if name not in ("aixm:Point", "aixm:ElevatedPoint", "gml:Point"):
        raise GeometryUnsupported("element", name, "a point property holds none of aixm:Point, "
                                  "aixm:ElevatedPoint or gml:Point", source=name)
    crs = _srs(node, inherited, name)
    if "gml:posList" in node:
        raise GeometryUnsupported("element", name, "a Point carries gml:posList; the pinned form is "
                                  "a single gml:pos (decision D4)", source=node.get("gml:posList"))
    positions = as_list(node, "gml:pos")
    if len(positions) != 1:
        raise GeometryUnsupported("element", name, f"a Point carries {len(positions)} gml:pos "
                                  "elements; exactly one is the pinned form", source=positions)
    pos = scalar(positions[0])
    if not pos.present:
        raise GeometryUnsupported("coordinates", name, "gml:pos is empty", source=pos.text)
    pair = _pairs(_numbers(pos.text or "", name), crs, name, pos.text or "")
    if len(pair) != 1:
        raise GeometryUnsupported("coordinates", name, f"gml:pos holds {len(pair)} positions",
                                  source=pos.text)
    return PointReading(element=name, gml_id=node.get("@gml:id"), crs=crs, pos_text=pos.text or "",
                        longitude=pair[0][0], latitude=pair[0][1])


def _segment(node: Any, crs: CrsReading) -> tuple[SegmentReading, list[list[float]]]:
    name = object_name(node)
    if name in UNSUPPORTED_SEGMENTS or name not in LINEAR_SEGMENTS:
        raise GeometryUnsupported("segment", name, f"curve segment <{name}> is outside the pinned "
                                  "linear profile (LineStringSegment, GeodesicString); it is not "
                                  "approximated by a chord",
                                  source={k: v for k, v in (node or {}).items() if k != "$"})
    stated = node.get("@interpolation")
    interpolation = LINEAR_SEGMENTS[name]
    if stated is not None and stated != interpolation:
        raise GeometryUnsupported("segment", name, f"interpolation {stated!r} on <{name}>, whose "
                                  f"schema fixes {interpolation!r}", source=stated)
    if node.get("@srsName") is not None and node.get("@srsName") != crs.srs_name:
        raise GeometryUnsupported("crs", name, "a segment states a CRS different from its curve",
                                  source=node.get("@srsName"))
    pos_list = node.get("gml:posList")
    pos_texts = [scalar(p).text or "" for p in as_list(node, "gml:pos")]
    if "gml:pointProperty" in node or "gml:pointRep" in node:
        raise GeometryUnsupported("segment", name, "positions by pointProperty are not read",
                                  source=node.get("gml:pointProperty"))
    if pos_list is not None and pos_texts:
        raise GeometryUnsupported("segment", name, "both gml:posList and gml:pos on one segment",
                                  source=pos_list)
    if pos_list is not None:
        value = scalar(pos_list)
        if value.attributes.get("srsDimension") not in (None, "2"):
            raise GeometryUnsupported("dimension", name, "posList srsDimension is not 2",
                                      source=value.attributes.get("srsDimension"))
        coordinates = _pairs(_numbers(value.text or "", name), crs, name, value.text or "")
        if value.attributes.get("count") not in (None, str(len(coordinates))):
            raise GeometryUnsupported("coordinates", name, f"posList count={value.attributes['count']} "
                                      f"but {len(coordinates)} positions are stated", source=value.text)
        text = value.text
    else:
        coordinates = []
        for pos in pos_texts:
            coordinates.extend(_pairs(_numbers(pos, name), crs, name, pos))
        text = None
    if len(coordinates) < 2:
        raise GeometryUnsupported("coordinates", name, f"{len(coordinates)} positions; a segment "
                                  "needs at least two", source=text or pos_texts)
    return SegmentReading(element=name, interpolation=interpolation, stated_interpolation=stated,
                          pos_list_text=text, pos_texts=pos_texts, count=len(coordinates)), coordinates


def read_curve(node: Any, inherited: CrsReading | None = None) -> CurveReading:
    """`aixm:Curve` / `aixm:ElevatedCurve` / `gml:Curve` -> its connected segments. Consecutive
    segments share their join position (the first of the next repeats the last of the previous)
    and the join is kept once in the curve's coordinates; a join that does not meet is refused."""
    name = object_name(node)
    if name not in ("aixm:Curve", "aixm:ElevatedCurve", "gml:Curve"):
        raise GeometryUnsupported("curve", name, "a curve member is none of aixm:Curve, "
                                  "aixm:ElevatedCurve or gml:Curve (CompositeCurve and "
                                  "OrientableCurve are outside the profile)", source=name)
    crs = _srs(node, inherited, name)
    readings = [_segment(s, crs) for s in as_list(node, "gml:segments")]
    if not readings:
        raise GeometryUnsupported("curve", name, "a curve with no segments", source=None)
    segments = [reading for reading, _ in readings]
    coordinates: list[list[float]] = []
    for segment, positions in readings:
        if coordinates and coordinates[-1] == positions[0]:
            coordinates.extend(positions[1:])
        elif coordinates:
            raise GeometryUnsupported("closure", name, f"segment {segment.element} starts at "
                                      f"{positions[0]} where the previous segment ended at "
                                      f"{coordinates[-1]}; segments of one curve must be connected",
                                      source=segment.pos_list_text)
        else:
            coordinates.extend(positions)
    return CurveReading(element=name, gml_id=node.get("@gml:id"), crs=crs, segments=segments,
                        coordinates=coordinates)


def _orientation(ring: list[list[float]]) -> str:
    area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        area += x1 * y2 - x2 * y1
    if area > 0:
        return "counter-clockwise"
    if area < 0:
        return "clockwise"
    return "degenerate"


def _ring(node: Any, role: str, crs: CrsReading) -> RingReading:
    name = object_name(node)
    if name == "gml:LinearRing":
        if "gml:pos" in node or "gml:pointProperty" in node:
            raise GeometryUnsupported("ring", name, "a LinearRing by gml:pos is not read; the pinned "
                                      "form is one gml:posList", source=node.get("gml:pos"))
        value = scalar(node.get("gml:posList"))
        if not value.present:
            raise GeometryUnsupported("ring", name, "a LinearRing with no gml:posList", source=None)
        coordinates = _pairs(_numbers(value.text or "", name), crs, name, value.text or "")
        curves: list[CurveReading] = []
        text = value.text
    elif name == "gml:Ring":
        members = as_list(node, "gml:curveMember")
        if not members:
            raise GeometryUnsupported("ring", name, "a Ring with no curveMember", source=None)
        curves = []
        for member in members:
            if not isinstance(member, dict) or "$" not in member:
                raise GeometryUnsupported("curve", name, "a curveMember by reference (xlink:href) is "
                                          "not read; the pinned form holds the curve by value",
                                          source=member)
            curves.append(read_curve(member, crs))
        coordinates = []
        for curve in curves:
            if coordinates and coordinates[-1] == curve.coordinates[0]:
                coordinates.extend(curve.coordinates[1:])
            elif coordinates:
                raise GeometryUnsupported("closure", name, f"curve {curve.gml_id or '?'} starts at "
                                          f"{curve.coordinates[0]} where the previous curve ended at "
                                          f"{coordinates[-1]}; a ring's curves must be connected",
                                          source=curve.gml_id)
            else:
                coordinates.extend(curve.coordinates)
        text = None
    else:
        raise GeometryUnsupported("ring", name, f"a {role} ring is <{name}>, neither gml:Ring nor "
                                  "gml:LinearRing", source=name)
    if len(coordinates) < 4 or coordinates[0] != coordinates[-1]:
        raise GeometryUnsupported("closure", name, f"the {role} ring has {len(coordinates)} positions "
                                  f"from {coordinates[0] if coordinates else None} to "
                                  f"{coordinates[-1] if coordinates else None}; a ring closes on its "
                                  "first position and is not closed here (RFC 7946 / GML 3.2.1 "
                                  "10.5.11.1)", source=text)
    return RingReading(role=role, element=name, gml_id=node.get("@gml:id"), curves=curves,  # type: ignore[arg-type]
                       pos_list_text=text, coordinates=coordinates, orientation=_orientation(coordinates))  # type: ignore[arg-type]


def read_surface(node: Any, inherited: CrsReading | None = None) -> SurfaceReading:
    """`aixm:Surface` / `aixm:ElevatedSurface` / `gml:Surface` -> its PolygonPatches, each an
    exterior ring and its interior rings (holes), plus the GeoJSON projection (one patch ->
    Polygon, several -> MultiPolygon)."""
    name = object_name(node)
    if name not in ("aixm:Surface", "aixm:ElevatedSurface", "gml:Surface"):
        raise GeometryUnsupported("element", name, "a surface property holds none of aixm:Surface, "
                                  "aixm:ElevatedSurface or gml:Surface", source=name)
    crs = _srs(node, inherited, name)
    patches = []
    for patch in as_list(node, "gml:patches"):
        patch_name = object_name(patch)
        if patch_name != "gml:PolygonPatch":
            raise GeometryUnsupported("patch", patch_name, "a surface patch that is not a "
                                      "gml:PolygonPatch", source=patch_name)
        stated = patch.get("@interpolation")
        if stated not in (None, "planar"):
            raise GeometryUnsupported("patch", patch_name, f"interpolation {stated!r}; the schema fixes "
                                      "planar", source=stated)
        exterior_node = patch.get("gml:exterior")
        if exterior_node is None:
            raise GeometryUnsupported("ring", patch_name, "a PolygonPatch with no gml:exterior", source=None)
        if isinstance(exterior_node, list):
            raise GeometryUnsupported("ring", patch_name, "a PolygonPatch with more than one exterior",
                                      source=None)
        exterior = _ring(exterior_node, "exterior", crs)
        interiors = [_ring(i, "interior", crs) for i in as_list(patch, "gml:interior")]
        patches.append(PatchReading(element=patch_name, stated_interpolation=stated,
                                    exterior=exterior, interiors=interiors))
    if not patches:
        raise GeometryUnsupported("patch", name, "a surface with no patches", source=None)
    polygons = [[p.exterior.coordinates, *[i.coordinates for i in p.interiors]] for p in patches]
    geojson = ({"type": "Polygon", "coordinates": polygons[0]} if len(polygons) == 1
               else {"type": "MultiPolygon", "coordinates": polygons})
    return SurfaceReading(element=name, gml_id=node.get("@gml:id"), crs=crs, patches=patches,
                          geojson=geojson)


def orientation_notes(surface: SurfaceReading, where: str) -> list[str]:
    """OGC 12-028r1 §8.2.6: exterior counter-clockwise, interior clockwise. Departures are
    reported, never repaired."""
    notes = []
    for index, patch in enumerate(surface.patches):
        if patch.exterior.orientation != "counter-clockwise":
            notes.append(f"{where}: patch {index} exterior ring is {patch.exterior.orientation}; "
                         "OGC 12-028r1 §8.2.6 expects counter-clockwise — kept as stated, not reversed")
        for j, interior in enumerate(patch.interiors):
            if interior.orientation != "clockwise":
                notes.append(f"{where}: patch {index} interior ring {j} is {interior.orientation}; "
                             "OGC 12-028r1 §8.2.6 expects clockwise — kept as stated, not reversed")
    return notes


# ----------------------------------------------------------------------------- vertical

UOM_TO_UNIT = {"FT": "ft", "M": "m", "FL": "FL"}
REFERENCE_TO_DATUM = {"SFC": "AGL", "MSL": "MSL", "W84": "HAE", "STD": "BARO"}
VERTICAL_TOKENS = {"UNL": "unlimited", "GND": "ground", "FLOOR": "floor", "CEILING": "ceiling"}


class CdmVertical(Contract):
    value: float
    unit: Literal["m", "ft", "FL"]
    reference: Literal["HAE", "MSL", "AGL", "BARO", "FL", "UNKNOWN"]


class VerticalLimit(Contract):
    """One limit of a volume (upper, lower, maximum, minimum) with its separately stated
    reference: the source values, what kind of statement they are, and the CDM projection when
    one exists — with the reason when it does not. Nothing is converted."""

    limit: PropertyState
    reference: PropertyState
    kind: Literal["numeric", "unlimited", "ground", "floor", "ceiling", "unknown", "absent"]
    cdm: CdmVertical | None = None
    not_projected: str | None = None


class Elevation(Contract):
    """An ElevatedPoint's elevation: MSL by the model's definition, the geoid model beside it.
    `vertical_accuracy` is None where the version's ElevatedPoint has no such property (AIXM
    5.2, `Version.elevated`): a property the schema cannot state is not "not stated"."""

    elevation: PropertyState
    vertical_datum: PropertyState
    geoid_undulation: PropertyState
    vertical_accuracy: PropertyState | None = None
    cdm: CdmVertical | None = None
    not_projected: str | None = None


def _project(value_text: str | None, uom: str | None, reference: str | None,
             reference_stated: bool) -> tuple[CdmVertical | None, str | None]:
    if value_text is None:
        return None, "no value"
    try:
        number = float(value_text)
    except ValueError:
        return None, f"{value_text!r} is not a number"
    if uom not in UOM_TO_UNIT:
        return None, (f"uom {uom!r} has no VerticalUnit member (SM, standard metres, and an unstated "
                      "uom are carried here and not projected)")
    unit = UOM_TO_UNIT[uom]
    if unit == "FL":
        if reference in (None, "STD"):
            return CdmVertical(value=number, unit="FL", reference="FL"), None
        return None, (f"a flight level against reference {reference!r}: FL is its own scale and datum "
                      "and is not projected against another reference")
    if not reference_stated or reference is None:
        return CdmVertical(value=number, unit=unit, reference="UNKNOWN"), None  # type: ignore[arg-type]
    datum = REFERENCE_TO_DATUM.get(reference)
    if datum is None:
        return None, f"reference {reference!r} is not one of SFC, MSL, W84, STD"
    return CdmVertical(value=number, unit=unit, reference=datum), None  # type: ignore[arg-type]


def read_vertical_limit(limit_node: Any, reference_node: Any, interpretation: str) -> VerticalLimit:
    limit = property_state(limit_node, interpretation)
    reference = property_state(reference_node, interpretation)
    if limit.state == "absent":
        return VerticalLimit(limit=limit, reference=reference, kind="absent")
    if limit.state == "nil":
        return VerticalLimit(limit=limit, reference=reference, kind="unknown",
                             not_projected=f"nil ({limit.nil_reason or 'no nilReason'}); unknown is "
                                           "not a bound")
    text = (limit.value or "").strip()
    if text in VERTICAL_TOKENS:
        return VerticalLimit(limit=limit, reference=reference, kind=VERTICAL_TOKENS[text],  # type: ignore[arg-type]
                             not_projected=f"{text!r} is a token, not a number: "
                                           + {"UNL": "unlimited — the absence of a ceiling, distinct "
                                                     "from an unknown one",
                                              "GND": "the ground — a floor at the surface with no "
                                                     "number stated",
                                              "FLOOR": "the floor of another airspace",
                                              "CEILING": "the ceiling of another airspace"}[text])
    cdm, reason = _project(text, limit.uom, reference.value if reference.state == "stated" else None,
                           reference.state == "stated")
    return VerticalLimit(limit=limit, reference=reference, kind="numeric", cdm=cdm, not_projected=reason)


def read_elevation(node: dict, interpretation: str, version: Version = VERSION_511) -> Elevation:
    elevation = property_state(node.get("aixm:elevation"), interpretation)
    datum = property_state(node.get("aixm:verticalDatum"), interpretation)
    undulation = property_state(node.get("aixm:geoidUndulation"), interpretation)
    accuracy = (property_state(node.get("aixm:verticalAccuracy"), interpretation)
                if "verticalAccuracy" in version.elevated else None)
    cdm, reason = (None, "not stated")
    if elevation.state == "stated":
        text = (elevation.value or "").strip()
        if text in VERTICAL_TOKENS:
            cdm, reason = None, f"{text!r} is a token, not an elevation"
        else:
            cdm, reason = _project(text, elevation.uom, "MSL", True)
    elif elevation.state == "nil":
        reason = f"nil ({elevation.nil_reason or 'no nilReason'})"
    return Elevation(elevation=elevation, vertical_datum=datum, geoid_undulation=undulation,
                     vertical_accuracy=accuracy, cdm=cdm, not_projected=reason)


# ----------------------------------------------------------------------------- schedules

TIMESHEET_PROPERTIES = ("aixm:timeReference", "aixm:startDate", "aixm:endDate", "aixm:day",
                        "aixm:dayTil", "aixm:startTime", "aixm:startEvent",
                        "aixm:startTimeRelativeEvent", "aixm:startEventInterpretation",
                        "aixm:endTime", "aixm:endEvent", "aixm:endTimeRelativeEvent",
                        "aixm:endEventInterpretation", "aixm:daylightSavingAdjust", "aixm:excluded")


class Timesheet(Contract):
    """An `aixm:Timesheet` as typed validity: every property as stated, none resolved to
    instants — a schedule is a rule, and applying it needs a date and a sunrise table this
    adapter does not have (Temporality Concept 1.1 §4.4.7)."""

    gml_id: str | None = None
    properties: dict[str, PropertyState]


def read_timesheet(node: Any, interpretation: str) -> Timesheet:
    name = object_name(node)
    if name != "aixm:Timesheet":
        raise ValueError(f"timeInterval holds <{name}>, not aixm:Timesheet")
    return Timesheet(gml_id=node.get("@gml:id"),
                     properties={p.split(":", 1)[1]: property_state(node.get(p), interpretation)
                                 for p in TIMESHEET_PROPERTIES})


def read_schedule(node: dict, interpretation: str) -> list[Timesheet]:
    """The Timesheets a PropertiesWithSchedule states. A nil or empty `timeInterval`
    (`<aixm:timeInterval xsi:nil="true"/>`, common in published data) is no schedule and is
    left where it was; only object items are read."""
    return [read_timesheet(t, interpretation) for t in as_list(node, "aixm:timeInterval")
            if isinstance(t, dict) and "$" in t]


__all__ = [
    "AIXM_511_MESSAGE_NAMESPACE", "AIXM_511_NAMESPACE", "AIXM_52_MESSAGE_NAMESPACE",
    "AIXM_52_NAMESPACE", "CRS_AXIS_ORDER", "EVENT_511_NAMESPACE", "CdmVertical", "Contract", "CrsReading", "CurveReading",
    "DELTA_INTERPRETATIONS", "DocumentIndex", "Elevation", "FeatureIdentity", "GEOMETRY_KINDS",
    "GML_NAMESPACE", "GeometryUnsupported", "INTERPRETATIONS", "NIL_REASONS", "PERIOD_CONVENTION",
    "PatchReading", "PointReading", "PropertyState", "REFERENCE_FORMS", "REFERENCE_TO_DATUM",
    "REPEATABLE", "REPEATABLE_52", "REPEATABLE_52_MOVED", "REPEATABLE_AIXM_ROWS", "REPEATABLE_ANYWHERE",
    "REPEATABLE_BY_VERSION", "REPEATABLE_EVENT_ROWS", "REPEATABLE_ROOTS", "ROOT_KEY", "Reference", "ReferenceTarget", "RingReading",
    "Scalar", "SegmentReading", "SurfaceReading", "TIMESHEET_PROPERTIES", "TimePosition",
    "TimePrimitive", "Timesheet", "UOM_TO_UNIT", "UUID_PATTERN", "VALID_TIME_FORM", "VERSIONS",
    "VERSION_511", "VERSION_52", "VERTICAL_TOKENS", "Version", "VerticalLimit", "XLINK_NAMESPACE",
    "XSI_NAMESPACE", "as_list", "classify_href", "instant_of", "key_of", "object_name",
    "object_node", "orientation_notes", "property_state", "read_curve", "read_elevation",
    "read_identifier", "read_point", "read_schedule", "read_surface", "read_time_position",
    "read_time_primitive", "read_timesheet", "read_vertical_limit", "repeatable",
    "resolve_reference", "scalar", "scalar_node", "temporality_problems", "twin_of",
]
