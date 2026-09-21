#!/usr/bin/env python3
"""Writes the synthetic AIXM 5.2 fixtures of `fixtures/aixm52/` — the five harness documents with
their parsed twins, the `cases/`, `malformed/` and `counterexamples/` sets — from the templates
below, so each file is reproducible byte for byte and its provenance is this script.

    python build_fixtures.py            # write, from the directory this file is in
    python build_fixtures.py --check    # compare with the committed files, write nothing
    python build_fixtures.py --pin      # rewrite spec/aixm52_pin.json from the files on disk

`--check` rebuilds in memory and reports whether the committed files are what the script writes
(exit 0 CURRENT, 1 STALE). The twins are the codec's own `twin_of` reading of each XML under the
5.2 version (`tests/test_cdm_aixm52_adapter.py` re-derives them with the standard library alone).
The goldens under `golden/` are NOT written here: `python -m synapse_cdm.harness --adapter aixm52
--update-golden` writes them, and the harness judges them.

THESE ARE 5.2 DOCUMENTS, NOT 5.1.1 DOCUMENTS WITH THE NAMESPACE EDITED. Every time slice is
spelled in the order of its AIXM 5.2.0 `<Family>PropertyGroup` and every one carries what 5.2
added and 5.1.1 has no element for: an AirspaceVolume's `name` and `location` and its own
`gml:identifier` (an «object» may carry one in 5.2), an AirportHeliport's `timeZone`,
`segmentedCircleMarker` and REPEATED `responsibleOrganisation`, a Runway's `depth` and reference
codes, a RunwayDirection's `slope` and `approachGuidance`, a Navaid's `codeICAOCountry`, a
VerticalStructure's `designator`, `marked`, `placeName`, `dataAssessmentStatus` and
`arrestingDevice`, a part's `height`, an ElevatedPoint's 5.2 property group (`verticalDatum` as
free text, `horizontalAccuracy`, no `verticalAccuracy`). Every positive document validates
against the pinned 5.2 closure through an actual validator (`normative_validation`, the `aixm52`
binding) and — because of exactly those properties — is INVALID against the 5.1.1 closure; the
tests read both verdicts. Everything is SYNTHETIC: designators start with `SYN`, every UUID sits
under `a1a40000-0520-`, the aerodrome `ZZSY` and every position and instant are fictitious, and
no file derives from any published aeronautical data set.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

AIXM = "http://www.aixm.aero/schema/5.2"
MESSAGE = "http://www.aixm.aero/schema/5.2/message"
NS = (f'xmlns:message="{MESSAGE}"\n'
      f'    xmlns:aixm="{AIXM}" xmlns:gml="http://www.opengis.net/gml/3.2"\n'
      '    xmlns:xlink="http://www.w3.org/1999/xlink" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')

# Identifiers: every feature under a1a40000-0520-, numbered in the last group.
def uuid(n: int) -> str:
    return f"a1a40000-0520-4000-8000-{n:012d}"


TSA1, AIRPORT, RUNWAY, DIRECTION, NAVAID, ORG, TOWER, DANGER = (uuid(n) for n in range(1, 9))
VOR_EQ, DME_EQ = uuid(11), uuid(12)
CASE = {n: uuid(100 + n) for n in range(1, 40)}
EPSG = "urn:ogc:def:crs:EPSG::4326"
CRS84 = "urn:ogc:def:crs:OGC:1.3:CRS84"


# --------------------------------------------------------------------------------- pieces

def document(gml_id: str, comment: str, members: list[str], *, ns: str = NS) -> str:
    body = "\n".join(f"  <message:hasMember>\n{m}\n  </message:hasMember>" for m in members)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<!-- SYNTHETIC. {comment} -->\n'
            f'<message:AIXMBasicMessage {ns}\n    gml:id="{gml_id}">\n{body}\n</message:AIXMBasicMessage>\n')


def period(gml_id: str, begin: str, end: str | None, indent: int = 12) -> str:
    pad = " " * indent
    end_xml = (f"<gml:endPosition>{end}</gml:endPosition>" if end
               else '<gml:endPosition indeterminatePosition="unknown"/>')
    return (f'<gml:TimePeriod gml:id="{gml_id}">\n{pad}  <gml:beginPosition>{begin}</gml:beginPosition>\n'
            f"{pad}  {end_xml}\n{pad}</gml:TimePeriod>")


def instant(gml_id: str, when: str, indent: int = 12) -> str:
    pad = " " * indent
    return f'<gml:TimeInstant gml:id="{gml_id}">\n{pad}  <gml:timePosition>{when}</gml:timePosition>\n{pad}</gml:TimeInstant>'


def head(gml_id: str, interpretation: str, sequence: int | None, correction: int | None,
         valid: str | None, lifetime: str | None = None, *, valid_raw: str | None = None) -> str:
    """The AbstractAIXMTimeSlice skeleton: validTime, interpretation, numbers, featureLifetime —
    unchanged between 5.1.1 and 5.2."""
    lines = []
    if valid_raw is not None:
        lines.append(valid_raw)
    elif valid is not None:
        lines.append(f"          <gml:validTime>\n            {valid}\n          </gml:validTime>")
    lines.append(f"          <aixm:interpretation>{interpretation}</aixm:interpretation>")
    if sequence is not None:
        lines.append(f"          <aixm:sequenceNumber>{sequence}</aixm:sequenceNumber>")
    if correction is not None:
        lines.append(f"          <aixm:correctionNumber>{correction}</aixm:correctionNumber>")
    if lifetime is not None:
        lines.append(f"          <aixm:featureLifetime>\n            {lifetime}\n          </aixm:featureLifetime>")
    return "\n".join(lines)


def feature(element: str, identifier: str | None, slices: list[str], *, gml_id: str | None = None,
            slice_element: str | None = None) -> str:
    slice_element = slice_element or element + "TimeSlice"
    gml_id = gml_id or ("uuid." + identifier if identifier else "NOID")
    ident = (f'      <gml:identifier codeSpace="urn:uuid:">{identifier}</gml:identifier>\n' if identifier else "")
    body = "\n".join(f"      <aixm:timeSlice>\n        <aixm:{slice_element} gml:id=\"{sid}\">\n{s}\n"
                     f"        </aixm:{slice_element}>\n      </aixm:timeSlice>" for sid, s in slices)
    return f'    <aixm:{element} gml:id="{gml_id}">\n{ident}{body}\n    </aixm:{element}>'


def props(indent: int, *pairs) -> str:
    """`(name, text)` -> `<aixm:name>text</aixm:name>`; `(name, None)` -> `xsi:nil="true"`; a
    `(name, text, attrs)` triple spells attributes; a bare string is raw XML."""
    pad = " " * indent
    out = []
    for pair in pairs:
        if isinstance(pair, str):
            out.append(pad + pair)
            continue
        name, text = pair[0], pair[1]
        attrs = (" " + pair[2]) if len(pair) > 2 and pair[2] else ""
        if text is None:
            out.append(f'{pad}<aixm:{name}{attrs} xsi:nil="true"/>')
        else:
            out.append(f"{pad}<aixm:{name}{attrs}>{text}</aixm:{name}>")
    return "\n".join(out)


def surface(gml_id: str, srs: str, poslist: str, *, segment: str = "gml:GeodesicString",
            interior: str | None = None, element: str = "aixm:Surface", indent: int = 20,
            curve_id: str | None = None) -> str:
    pad = " " * indent
    curve_id = curve_id or gml_id + "_CV"
    hole = ""
    if interior is not None:
        hole = (f"\n{pad}      <gml:interior>\n{pad}        <gml:LinearRing>\n{pad}          <gml:posList>{interior}"
                f"</gml:posList>\n{pad}        </gml:LinearRing>\n{pad}      </gml:interior>")
    return (f'{pad}<{element} gml:id="{gml_id}" srsName="{srs}">\n{pad}  <gml:patches>\n{pad}    <gml:PolygonPatch>\n'
            f"{pad}      <gml:exterior>\n{pad}        <gml:Ring>\n{pad}          <gml:curveMember>\n"
            f'{pad}            <aixm:Curve gml:id="{curve_id}">\n{pad}              <gml:segments>\n'
            f"{pad}                <{segment}>\n{pad}                  <gml:posList>{poslist}</gml:posList>\n"
            f"{pad}                </{segment}>\n{pad}              </gml:segments>\n{pad}            </aixm:Curve>\n"
            f"{pad}          </gml:curveMember>\n{pad}        </gml:Ring>\n{pad}      </gml:exterior>{hole}\n"
            f"{pad}    </gml:PolygonPatch>\n{pad}  </gml:patches>\n{pad}</{element}>")


def volume(gml_id: str, limits: str, projection: str | None, *, identifier: str | None = None,
           name: str | None = None, location: str | None = None, extra: str = "", indent: int = 16) -> str:
    """A 5.2 AirspaceVolume: its own gml:identifier (new in 5.2, first), the limits, the
    projection, then — after `annotation` in the 5.2 group — `name` and `location`."""
    pad = " " * indent
    ident = f'\n{pad}  <gml:identifier codeSpace="urn:uuid:">{identifier}</gml:identifier>' if identifier else ""
    proj = f"\n{pad}  <aixm:horizontalProjection>\n{projection}\n{pad}  </aixm:horizontalProjection>" if projection else ""
    tail = ""
    if name is not None:
        tail += f"\n{pad}  <aixm:name>{name}</aixm:name>"
    if location is not None:
        tail += (f"\n{pad}  <aixm:location>\n{pad}    <aixm:Point gml:id=\"{gml_id}_LOC\" srsName=\"{EPSG}\">\n"
                 f"{pad}      <gml:pos>{location}</gml:pos>\n{pad}    </aixm:Point>\n{pad}  </aixm:location>")
    return (f'{pad}<aixm:AirspaceVolume gml:id="{gml_id}">{ident}\n{limits}{proj}{extra}{tail}\n{pad}</aixm:AirspaceVolume>')


def limits(indent: int, upper: tuple | None, lower: tuple | None, *, maximum: tuple | None = None,
           minimum: tuple | None = None) -> str:
    """`(value, uom, reference)`; `(None, None, None)` spells a nil limit; uom None spells no uom."""
    pairs: list = []
    for name, limit in (("upper", upper), ("maximum", maximum), ("lower", lower), ("minimum", minimum)):
        if limit is None:
            continue
        value, uom, reference = limit
        pairs.append((f"{name}Limit", value, f'uom="{uom}"' if uom else ""))
        if reference is not None or value is None:
            pairs.append((f"{name}LimitReference", reference))
    return props(indent, *pairs)


def component(gml_id: str, operation: str | None, sequence: str, vol: str, indent: int = 10) -> str:
    pad = " " * indent
    op = f'{pad}    <aixm:operation>{operation}</aixm:operation>\n' if operation else ""
    return (f"{pad}<aixm:geometryComponent>\n{pad}  <aixm:AirspaceGeometryComponent gml:id=\"{gml_id}\">\n{op}"
            f"{pad}    <aixm:operationSequence>{sequence}</aixm:operationSequence>\n{pad}    <aixm:theAirspaceVolume>\n"
            f"{vol}\n{pad}    </aixm:theAirspaceVolume>\n{pad}  </aixm:AirspaceGeometryComponent>\n{pad}</aixm:geometryComponent>")


def timesheet(gml_id: str, indent: int, *, day: str = "WORK_DAY", start: str = "07:00", end: str = "17:00") -> str:
    pad = " " * indent
    return (f"{pad}<aixm:timeInterval>\n{pad}  <aixm:Timesheet gml:id=\"{gml_id}\">\n{pad}    <aixm:timeReference>UTC</aixm:timeReference>\n"
            f"{pad}    <aixm:day>{day}</aixm:day>\n{pad}    <aixm:startTime>{start}</aixm:startTime>\n"
            f"{pad}    <aixm:endTime>{end}</aixm:endTime>\n{pad}  </aixm:Timesheet>\n{pad}</aixm:timeInterval>")


def activation(gml_id: str, status: str, *, activity: str | None = "MILOPS", schedule: str | None = None,
               indent: int = 10, identifier: str | None = None) -> str:
    """`identifier` puts a gml:identifier on the AirspaceActivation OBJECT — admitted by 5.2's
    AbstractAIXMObjectType and by no 5.1.1 type."""
    pad = " " * indent
    inner = (f'{pad}    <gml:identifier codeSpace="urn:uuid:">{identifier}</gml:identifier>\n' if identifier else "")
    inner += (schedule + "\n" if schedule else "")
    inner += f"{pad}    <aixm:activity>{activity}</aixm:activity>\n" if activity else ""
    inner += f"{pad}    <aixm:status>{status}</aixm:status>\n"
    return (f"{pad}<aixm:activation>\n{pad}  <aixm:AirspaceActivation gml:id=\"{gml_id}\">\n{inner}"
            f"{pad}  </aixm:AirspaceActivation>\n{pad}</aixm:activation>")


def availability(gml_id: str, element: str, status: str, *, schedule: str | None = None,
                 warning: str | None = None, indent: int = 10, extra: str = "") -> str:
    pad = " " * indent
    inner = (schedule + "\n" if schedule else "")
    inner += f"{pad}    <aixm:operationalStatus>{status}</aixm:operationalStatus>\n"
    inner += f"{pad}    <aixm:warning>{warning}</aixm:warning>\n" if warning else ""
    inner += extra
    return (f"{pad}<aixm:availability>\n{pad}  <aixm:{element} gml:id=\"{gml_id}\">\n{inner}"
            f"{pad}  </aixm:{element}>\n{pad}</aixm:availability>")


def elevated_point(gml_id: str, pos: str, *, srs: str = EPSG, elevation: tuple[str, str] | None = ("12", "FT"),
                   datum: str | None = "EGM 96 GEOID (free text in 5.2)", undulation: str | None = None,
                   horizontal_accuracy: tuple[str, str] | None = ("1", "M"), indent: int = 12,
                   annotation: str | None = None) -> str:
    """The 5.2 ElevatedPoint: `gml:pos`, then `elevation`, `geoidUndulation`, `verticalDatum`
    (TextNameType), `horizontalAccuracy`, `annotation` — no `verticalAccuracy` in 5.2."""
    pad = " " * indent
    out = [f'{pad}<aixm:ElevatedPoint gml:id="{gml_id}" srsName="{srs}">', f"{pad}  <gml:pos>{pos}</gml:pos>"]
    if elevation is not None:
        out.append(f'{pad}  <aixm:elevation uom="{elevation[1]}">{elevation[0]}</aixm:elevation>')
    if undulation is not None:
        out.append(f'{pad}  <aixm:geoidUndulation uom="M">{undulation}</aixm:geoidUndulation>')
    if datum is not None:
        out.append(f"{pad}  <aixm:verticalDatum>{datum}</aixm:verticalDatum>")
    if horizontal_accuracy is not None:
        out.append(f'{pad}  <aixm:horizontalAccuracy uom="{horizontal_accuracy[1]}">{horizontal_accuracy[0]}</aixm:horizontalAccuracy>')
    if annotation is not None:
        out.append(annotation)
    out.append(f"{pad}</aixm:ElevatedPoint>")
    return "\n".join(out)


def note(gml_id: str, text: str, indent: int = 10, prop: str | None = None) -> str:
    pad = " " * indent
    pn = f"{pad}    <aixm:propertyName>{prop}</aixm:propertyName>\n" if prop else ""
    return (f"{pad}<aixm:annotation>\n{pad}  <aixm:Note gml:id=\"{gml_id}\">\n{pn}{pad}    <aixm:purpose>REMARK</aixm:purpose>\n"
            f"{pad}    <aixm:translatedNote>\n{pad}      <aixm:LinguisticNote gml:id=\"{gml_id}_LN\">\n"
            f'{pad}        <aixm:note lang="eng">{text}</aixm:note>\n{pad}      </aixm:LinguisticNote>\n'
            f"{pad}    </aixm:translatedNote>\n{pad}  </aixm:Note>\n{pad}</aixm:annotation>")


def ref(name: str, href: str, title: str | None = None, indent: int = 10) -> str:
    t = f' xlink:title="{title}"' if title else ""
    return f'{" " * indent}<aixm:{name} xlink:href="{href}"{t}/>'


# ------------------------------------------------------------------- the harness documents

def airspace_baseline() -> str:
    sf = surface("TSA1_SF_1", EPSG, "52.0 5.0 52.0 5.5 52.5 5.5 52.5 5.0 52.0 5.0")
    vol = volume("TSA1_AV_1", limits(18, ("195", "FL", "STD"), ("2500", "FT", "MSL")), sf,
                 identifier=uuid(21), name="SYNTHETIC TSA ONE VOLUME", location="52.25 5.25")
    body = "\n".join([
        head("TSA1_BL_1_0", "BASELINE", 1, 0, period("TSA1_BL_1_0_VT", "2026-01-01T00:00:00Z", None),
             period("TSA1_BL_1_0_LT", "2026-01-01T00:00:00Z", None)),
        props(10, ("type", "TSA"), ("designator", "SYNTSA1"), ("name", "SYNTHETIC TSA ONE"), ("designatorICAO", "NO")),
        component("TSA1_GC_1", "BASE", "1", vol),
        activation("TSA1_ACT_1", "AVBL_FOR_ACTIVATION", schedule=timesheet("TSA1_TS_1", 14)),
        note("TSA1_N_1", "Activation announced by NOTAM.", prop="activation"),
    ])
    return document("M_AIRSPACE_BASELINE", "A fictitious temporary segregated area over a fictitious position; not an\n"
                    "     operational airspace. Written by spec/build_fixtures.py on 2026-09-21 for the SynapseCommand aixm52\n"
                    "     adapter: one BASELINE time slice, one BASE volume whose horizontal projection is the pinned Surface\n"
                    "     form (PolygonPatch, exterior Ring, one Curve, one GeodesicString, EPSG:4326 = LATITUDE first),\n"
                    "     FL 195 STD over 2500 FT MSL, an activation with a schedule, an annotation the adapter does not\n"
                    "     type. AIXM 5.2: the AirspaceVolume carries its own gml:identifier, a name and a location (none\n"
                    "     of the three exists in 5.1.1).",
                    [feature("Airspace", TSA1, [("TSA1_BL_1_0", body)])])


def airspace_deltas() -> str:
    td0 = "\n".join([head("TSA1_TD_2_0", "TEMPDELTA", 2, 0, period("TSA1_TD_2_0_VT", "2026-03-10T08:00:00Z", "2026-03-10T16:00:00Z")),
                     activation("TSA1_ACT_2", "ACTIVE", activity=None, identifier=uuid(22))])
    td1 = "\n".join([head("TSA1_TD_2_1", "TEMPDELTA", 2, 1, period("TSA1_TD_2_1_VT", "2026-03-10T08:00:00Z", "2026-03-10T14:00:00Z")),
                     activation("TSA1_ACT_3", "ACTIVE", activity=None, identifier=uuid(23))])
    pd = "\n".join([head("TSA1_PD_3_0", "PERMDELTA", 3, 0, instant("TSA1_PD_3_0_VT", "2026-04-01T00:00:00Z")),
                    props(10, ("localType", None, 'nilReason="inapplicable"'), ("name", "SYNTHETIC TSA ONE RENAMED"))])
    return document("M_AIRSPACE_DELTAS", "Three later time slices of the SAME fictitious airspace as\n"
                    "     airspace_baseline_polygon.xml: a TEMPDELTA activating it, its correction ending two hours\n"
                    "     earlier, and a PERMDELTA at an instant that renames it and withdraws localType (xsi:nil).\n"
                    "     Written by spec/build_fixtures.py on 2026-09-21 for the SynapseCommand aixm52 adapter. AIXM 5.2:\n"
                    "     each AirspaceActivation object carries its own gml:identifier (no 5.1.1 object may).",
                    [feature("Airspace", TSA1, [("TSA1_TD_2_0", td0), ("TSA1_TD_2_1", td1), ("TSA1_PD_3_0", pd)])])


def org_member(gml_id: str, identifier: str, name: str, designator: str) -> str:
    body = "\n".join([head(gml_id + "_BL", "BASELINE", 1, 0, period(gml_id + "_VT", "2026-01-01T00:00:00Z", None)),
                      props(10, ("name", name), ("designator", designator), ("type", "OTHER"), ("military", "CIVIL"))])
    return feature("OrganisationAuthority", identifier, [(gml_id + "_BL", body)])


def aerodrome() -> str:
    arp = elevated_point("AP1_ARP", "52.30833 4.76389", undulation="43.5", indent=12)
    airport = "\n".join([
        head("AP1_BL_1_0", "BASELINE", 1, 0, period("AP1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("designator", "ZZSY"), ("name", "SYNTHETIC FIELD"), ("locationIndicatorICAO", "ZZSY"),
              ("type", "AD"), ("controlType", "CIVIL"), ("fieldElevation", "12", 'uom="FT"'),
              ("verticalDatum", "EGM 96 GEOID (free text in 5.2)"), ("magneticVariation", "1.5"), ("abandoned", "NO")),
        "\n".join(f"          <aixm:responsibleOrganisation>\n            <aixm:AirportHeliportResponsibilityOrganisation gml:id=\"AP1_RO_{i}\">\n"
                  f"              <aixm:role>{role}</aixm:role>\n"
                  f"              <aixm:theOrganisationAuthority xlink:href=\"urn:uuid:{ORG}\"/>\n"
                  f"            </aixm:AirportHeliportResponsibilityOrganisation>\n          </aixm:responsibleOrganisation>"
                  for i, role in ((1, "OPERATE"), (2, "OWN"))),
        f"          <aixm:ARP>\n{arp}\n          </aixm:ARP>",
        availability("AP1_AV_1", "AirportHeliportAvailability", "NORMAL"),
        props(10, ("timeZone", "UTC"), ("segmentedCircleMarker", "YES_LIGHTED")),
    ])
    runway = "\n".join([
        head("RWY1_BL_1_0", "BASELINE", 1, 0, period("RWY1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("designator", "SYN09/27"), ("type", "RWY"), ("nominalLength", "2500", 'uom="M"'),
              ("nominalWidth", "45", 'uom="M"'), ("abandoned", "NO")),
        ref("associatedAirportHeliport", "urn:uuid:" + AIRPORT, "ZZSY SYNTHETIC FIELD"),
        props(10, ("referenceCodeFieldLength", "4"), ("referenceCodeWingspan", "D"), ("depth", "0.9", 'uom="M"')),
    ])
    direction = "\n".join([
        head("RD1_BL_1_0", "BASELINE", 1, 0, period("RD1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("designator", "SYN09"), ("trueBearing", "92.5"), ("magneticBearing", "91.0"),
              ("elevationTDZ", "10", 'uom="FT"')),
        ref("usedRunway", "#uuid." + RUNWAY),
        availability("RD1_AV_1", "ManoeuvringAreaAvailability", "CLOSED",
                     schedule=timesheet("RD1_TS_1", 14, day="ANY", start="22:00", end="06:00"), warning="WIP"),
        props(10, ("slope", "0.4"), ("approachGuidance", "PRECISION_CAT_I")),
    ])
    navaid = "\n".join([
        head("NAV1_BL_1_0", "BASELINE", 1, 0, period("NAV1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("type", "VOR_DME"), ("designator", "SYV"), ("name", "SYNTHETIC VOR DME"), ("flightChecked", "YES")),
        "\n".join(f"          <aixm:navaidEquipment>\n            <aixm:NavaidComponent gml:id=\"NAV1_NC_{i}\">\n"
                  f"              <aixm:collocationGroup>1</aixm:collocationGroup>\n"
                  f"              <aixm:theNavaidEquipment xlink:href=\"urn:uuid:{eq}\"/>\n"
                  f"            </aixm:NavaidComponent>\n          </aixm:navaidEquipment>"
                  for i, eq in ((1, VOR_EQ), (2, DME_EQ))),
        "          <aixm:location>\n" + elevated_point("NAV1_LOC", "4.80000 52.31000", srs=CRS84, elevation=("15", "M"),
                                                      datum="EGM 96 GEOID (free text in 5.2)", horizontal_accuracy=None,
                                                      indent=12) + "\n          </aixm:location>",
        ref("runwayDirection", "#uuid." + DIRECTION),
        ref("servedAirport", "urn:uuid:" + AIRPORT),
        availability("NAV1_AV_1", "NavaidOperationalStatus", "OPERATIONAL"),
        props(10, ("codeICAOCountry", "ZZ")),
    ])
    return document("M_AERODROME", "A fictitious aerodrome ZZSY with one runway, one runway direction (CLOSED under\n"
                    "     a night-time Timesheet — typed, not asserted), a VOR/DME whose location is CRS84 (LONGITUDE\n"
                    "     first) and whose two component equipments the document does not carry, and an\n"
                    "     OrganisationAuthority outside the five families. Written by spec/build_fixtures.py on 2026-09-21\n"
                    "     for the SynapseCommand aixm52 adapter. AIXM 5.2: the ARP is the 5.2 ElevatedPoint (verticalDatum\n"
                    "     free text, geoidUndulation, horizontalAccuracy, no verticalAccuracy), timeZone,\n"
                    "     segmentedCircleMarker, TWO responsibleOrganisation (unbounded in 5.2), the runway's depth and\n"
                    "     reference codes, the direction's slope and approachGuidance, the navaid's codeICAOCountry.",
                    [feature("AirportHeliport", AIRPORT, [("AP1_BL_1_0", airport)]),
                     feature("Runway", RUNWAY, [("RWY1_BL_1_0", runway)]),
                     feature("RunwayDirection", DIRECTION, [("RD1_BL_1_0", direction)]),
                     feature("Navaid", NAVAID, [("NAV1_BL_1_0", navaid)]),
                     org_member("ORG1", ORG, "SYNTHETIC AIRPORT OPERATOR", "SYNOPS")])


def part(gml_id: str, extent: tuple[str, str], kind: str, *, designator: str | None = None,
         location: str | None = None, height: tuple[str, str] | None = None, indent: int = 10,
         extra: str = "") -> str:
    pad = " " * indent
    inner = f'{pad}    <aixm:verticalExtent uom="{extent[1]}">{extent[0]}</aixm:verticalExtent>\n{pad}    <aixm:type>{kind}</aixm:type>\n'
    if designator:
        inner += f"{pad}    <aixm:designator>{designator}</aixm:designator>\n"
    if location:
        inner += f"{pad}    <aixm:horizontalProjection_location>\n{location}\n{pad}    </aixm:horizontalProjection_location>\n"
    inner += extra
    if height:
        inner += f'{pad}    <aixm:height uom="{height[1]}">{height[0]}</aixm:height>\n'
    return f"{pad}<aixm:part>\n{pad}  <aixm:VerticalStructurePart gml:id=\"{gml_id}\">\n{inner}{pad}  </aixm:VerticalStructurePart>\n{pad}</aixm:part>"


def tower() -> str:
    loc = elevated_point("VS1_P1_LOC", "52.4 5.1", elevation=("250", "FT"), horizontal_accuracy=("5", "M"), indent=14)
    body = "\n".join([
        head("VS1_BL_1_0", "BASELINE", 1, 0, period("VS1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("name", "SYNTHETIC TOWER"), ("type", "TOWER"), ("lighted", "YES")),
        part("VS1_P1", ("120", "M"), "TOWER", designator="SYNTOWER-MAST-LONG-DESIGNATOR", location=loc, height=("120", "M")),
        part("VS1_P2", ("15", "M"), "ANTENNA", designator="SYNTOWER-ANT", height=("15", "M")),
        props(10, ("marked", "YES"), ("designator", "SYNTWR1"), ("placeName", "SYNTHETIC HILL"),
              ("dataAssessmentStatus", "VERIFIED")),
        ref("arrestingDevice", "urn:uuid:" + uuid(31)),
        ref("arrestingDevice", "urn:uuid:" + uuid(32)),
    ])
    return document("M_TOWER", "A fictitious lit tower with two parts: a mast with a point location (250 FT MSL)\n"
                    "     and a 120 M vertical extent, and an antenna with no geometry. Written by spec/build_fixtures.py on\n"
                    "     2026-09-21 for the SynapseCommand aixm52 adapter. AIXM 5.2: each part states its height, the\n"
                    "     structure its designator, marked, placeName and dataAssessmentStatus, and two arrestingDevice\n"
                    "     references (unbounded in 5.2, unresolved here); the part's location is the 5.2 ElevatedPoint.",
                    [feature("VerticalStructure", TOWER, [("VS1_BL_1_0", body)])])


def danger_area() -> str:
    sf = surface("DA1_SF_1", CRS84, "6.0 51.0 6.5 51.0 6.5 51.5 6.0 51.5 6.0 51.0", segment="gml:LineStringSegment",
                 interior="6.2 51.2 6.3 51.2 6.3 51.3 6.2 51.3 6.2 51.2")
    vol = volume("DA1_AV_1", limits(18, (None, None, None), ("GND", None, "SFC")), sf, name="SYNTHETIC DANGER VOLUME")
    body = "\n".join([
        head("DA1_BL_1_0", "BASELINE", 1, 0, period("DA1_BL_1_0_VT", "2026-01-01T00:00:00Z", None)),
        props(10, ("type", "D"), ("designator", "SYND1"), ("name", "SYNTHETIC DANGER AREA")),
        component("DA1_GC_1", "BASE", "1", vol),
    ])
    snapshot = "\n".join([
        head("DA1_SS", "SNAPSHOT", None, None, instant("DA1_SS_VT", "2026-06-01T12:00:00Z")),
        props(10, ("type", "D"), ("designator", "SYND1"), ("name", "SYNTHETIC DANGER AREA")),
        activation("DA1_ACT_1", "INACTIVE", activity=None),
    ])
    return document("M_DANGER", "A fictitious danger area with a hole (exterior Ring of one Curve with a linear\n"
                    "     segment, interior LinearRing) under CRS84 (LONGITUDE first), a nil upper limit and a GND lower\n"
                    "     limit, and a SNAPSHOT slice with no sequence or correction number. Written by\n"
                    "     spec/build_fixtures.py on 2026-09-21 for the SynapseCommand aixm52 adapter. AIXM 5.2: the\n"
                    "     volume carries a name.",
                    [feature("Airspace", DANGER, [("DA1_BL_1_0", body), ("DA1_SS", snapshot)])])


# ------------------------------------------------------------------------------ the cases

def simple_airspace(gml_id: str, identifier: str, designator: str, comment: str, srs: str, poslist: str,
                    *, message_id: str, upper=("100", "FL", "STD"), lower=("0", "FT", "SFC"),
                    segment: str = "gml:GeodesicString", name: str | None = "SYNTHETIC VOLUME (5.2 name)") -> str:
    sf = surface(gml_id + "_SF", srs, poslist, segment=segment)
    vol = volume(gml_id + "_AV", limits(18, upper, lower), sf, name=name)
    body = "\n".join([head(gml_id + "_BL", "BASELINE", 1, 0, period(gml_id + "_VT", "2026-01-01T00:00:00Z", None)),
                      props(10, ("type", "TSA"), ("designator", designator)), component(gml_id + "_GC", "BASE", "1", vol)])
    return document(message_id, comment, [feature("Airspace", identifier, [(gml_id + "_BL", body)])])


def cases() -> dict[str, str]:
    out: dict[str, str] = {}
    out["cases/axis_order_epsg4326.xml"] = simple_airspace(
        "AX1", CASE[1], "SYNAX1", "The same fictitious quadrilateral as axis_order_crs84.xml, stated under EPSG:4326\n"
        "     (LATITUDE first). Written by spec/build_fixtures.py on 2026-09-21 (aixm52).", EPSG,
        "52.1 5.2 52.1 5.4 52.3 5.4 52.3 5.2 52.1 5.2", message_id="M_AXIS_EPSG")
    out["cases/axis_order_crs84.xml"] = simple_airspace(
        "AX2", CASE[2], "SYNAX2", "The same fictitious quadrilateral as axis_order_epsg4326.xml, stated under CRS84\n"
        "     (LONGITUDE first). Written by spec/build_fixtures.py on 2026-09-21 (aixm52).", CRS84,
        "5.2 52.1 5.4 52.1 5.4 52.3 5.2 52.3 5.2 52.1", message_id="M_AXIS_CRS84")
    # An interior Ring of curves (deeper than a shipped twin admits; read by name).
    pad = " " * 20
    inner_ring = (f"\n{pad}      <gml:interior>\n{pad}        <gml:Ring>\n{pad}          <gml:curveMember>\n"
                  f'{pad}            <aixm:Curve gml:id="IR1_CV_2">\n{pad}              <gml:segments>\n'
                  f"{pad}                <gml:GeodesicString>\n{pad}                  <gml:posList>52.2 5.2 52.2 5.3 52.3 5.3 52.3 5.2 52.2 5.2</gml:posList>\n"
                  f"{pad}                </gml:GeodesicString>\n{pad}              </gml:segments>\n{pad}            </aixm:Curve>\n"
                  f"{pad}          </gml:curveMember>\n{pad}        </gml:Ring>\n{pad}      </gml:interior>")
    sf = surface("IR1_SF", EPSG, "52.1 5.1 52.1 5.4 52.4 5.4 52.4 5.1 52.1 5.1").replace(
        f"\n{pad}    </gml:PolygonPatch>", inner_ring + f"\n{pad}    </gml:PolygonPatch>")
    vol = volume("IR1_AV", limits(18, ("100", "FL", "STD"), ("0", "FT", "SFC")), sf, name="SYNTHETIC VOLUME (5.2 name)")
    body = "\n".join([head("IR1_BL", "BASELINE", 1, 0, period("IR1_VT", "2026-01-01T00:00:00Z", None)),
                      props(10, ("type", "TSA"), ("designator", "SYNIR1")), component("IR1_GC", "BASE", "1", vol)])
    out["cases/interior_ring_of_curves.xml"] = document("M_INTERIOR_RING", "A fictitious airspace whose hole is a gml:Ring\n"
                                                        "     of curves rather than a LinearRing. Written by spec/build_fixtures.py on 2026-09-21 (aixm52).",
                                                        [feature("Airspace", CASE[3], [("IR1_BL", body)])])
    # A composition (UNION of two contributors) with a cycle: A's volume depends on B and B's on A.
    def dependent(gml_id: str, identifier: str, designator: str, other: str) -> str:
        dep = (f"\n                  <aixm:contributorAirspace>\n                    <aixm:AirspaceVolumeDependency gml:id=\"{gml_id}_DEP\">\n"
               f"                      <aixm:dependency>FULL_GEOMETRY</aixm:dependency>\n"
               f"                      <aixm:theAirspace xlink:href=\"urn:uuid:{other}\"/>\n"
               f"                    </aixm:AirspaceVolumeDependency>\n                  </aixm:contributorAirspace>")
        vol = volume(gml_id + "_AV", limits(18, ("100", "FL", "STD"), ("0", "FT", "SFC")), None, extra=dep,
                     identifier=uuid(40 + int(gml_id[-1])))
        body = "\n".join([head(gml_id + "_BL", "BASELINE", 1, 0, period(gml_id + "_VT", "2026-01-01T00:00:00Z", None)),
                          props(10, ("type", "TSA"), ("designator", designator)), component(gml_id + "_GC", "UNION", "1", vol)])
        return feature("Airspace", identifier, [(gml_id + "_BL", body)])
    out["cases/composite_and_cyclic_contributors.xml"] = document(
        "M_COMPOSITE", "Two fictitious airspaces each composed (UNION) of the OTHER — a cycle of contributor\n"
        "     references, resolved one hop each and never followed. Written by spec/build_fixtures.py on 2026-09-21 (aixm52).",
        [dependent("CY1", CASE[4], "SYNCY1", CASE[5]), dependent("CY2", CASE[5], "SYNCY2", CASE[4])])
    # Every reference form on one Runway: urn:uuid (resolved), #gml:id (resolved), a URL, a natural key, other.
    airport = "\n".join([head("RF_AP_BL", "BASELINE", 1, 0, period("RF_AP_VT", "2026-01-01T00:00:00Z", None)),
                         props(10, ("designator", "ZZSR"), ("name", "SYNTHETIC REFERENCE FIELD"), ("timeZone", "UTC"))])
    runway = "\n".join([head("RF_RWY_BL", "BASELINE", 1, 0, period("RF_RWY_VT", "2026-01-01T00:00:00Z", None)),
                        props(10, ("designator", "SYN18/36")), ref("associatedAirportHeliport", "urn:uuid:" + CASE[6])])
    d1 = "\n".join([head("RF_RD1_BL", "BASELINE", 1, 0, period("RF_RD1_VT", "2026-01-01T00:00:00Z", None)),
                    props(10, ("designator", "SYN18")), ref("usedRunway", "#uuid." + CASE[7]),
                    ref("startingElement", "https://example.invalid/aixm/RunwayElement#uuid." + CASE[20])])
    d2 = "\n".join([head("RF_RD2_BL", "BASELINE", 1, 0, period("RF_RD2_VT", "2026-01-01T00:00:00Z", None)),
                    props(10, ("designator", "SYN36")), ref("usedRunway", "urn:aixm:Runway:ZZSR:SYN18/36"),
                    ref("startingElement", "unresolvable-token")])
    out["cases/reference_forms.xml"] = document(
        "M_REFERENCES", "Every xlink:href form Feature Identification and Reference 1.0 names, on fictitious\n"
        "     features: urn:uuid (resolved in the document), #gml:id (resolved), a URL (classified, never fetched), a\n"
        "     natural key and an opaque token (kept unresolved). Written by spec/build_fixtures.py on 2026-09-21 (aixm52).",
        [feature("AirportHeliport", CASE[6], [("RF_AP_BL", airport)]), feature("Runway", CASE[7], [("RF_RWY_BL", runway)]),
         feature("RunwayDirection", CASE[8], [("RF_RD1_BL", d1)]), feature("RunwayDirection", CASE[9], [("RF_RD2_BL", d2)])])
    # Twelve ways of stating a vertical limit, one airspace each, the designator naming the form.
    forms = [("VFTSFC", ("1000", "FT", "SFC"), ("0", "FT", "SFC")), ("VFTMSL", ("5000", "FT", "MSL"), ("1000", "FT", "MSL")),
             ("VMW84", ("300", "M", "W84"), ("0", "M", "W84")), ("VFLSTD", ("245", "FL", "STD"), ("95", "FL", "STD")),
             ("VFTSTD", ("10000", "FT", "STD"), ("5000", "FT", "STD")), ("VSM", ("300", "SM", "MSL"), ("0", "SM", "MSL")),
             ("VFLMSL", ("100", "FL", "MSL"), ("0", "FT", "MSL")), ("VUNL", ("UNL", None, "STD"), ("100", "FL", "STD")),
             ("VGND", ("100", "FL", "STD"), ("GND", None, "SFC")), ("VNIL", (None, None, None), ("0", "FT", "SFC")),
             ("VFLOOR", ("CEILING", None, "STD"), ("FLOOR", None, "STD")), ("VNOREF", ("2000", "FT", None), ("0", "FT", None))]
    members = []
    for i, (designator, upper, lower) in enumerate(forms):
        gid = f"VF{i}"
        sf = surface(gid + "_SF", EPSG, f"5{i % 10}.0 5.0 5{i % 10}.0 5.5 5{i % 10}.5 5.5 5{i % 10}.5 5.0 5{i % 10}.0 5.0")
        vol = volume(gid + "_AV", limits(18, upper, lower), sf, name=f"SYNTHETIC VOLUME {designator}")
        body = "\n".join([head(gid + "_BL", "BASELINE", 1, 0, period(gid + "_VT", "2026-01-01T00:00:00Z", None)),
                          props(10, ("type", "TSA"), ("designator", designator)), component(gid + "_GC", "BASE", "1", vol)])
        members.append(feature("Airspace", CASE[10 + i], [(gid + "_BL", body)]))
    out["cases/vertical_references.xml"] = document(
        "M_VERTICAL", "Twelve fictitious airspaces, one per way of stating a vertical limit (the designator\n"
        "     names the form): FT/M/FL against SFC/MSL/W84/STD, SM, FL against MSL, UNL, GND, a nil upper limit,\n"
        "     FLOOR/CEILING tokens, an unstated reference. Written by spec/build_fixtures.py on 2026-09-21 (aixm52).", members)
    # nil / absent / withdrawn: a BASELINE with a nil name and no localType, then a PERMDELTA withdrawing name.
    bl = "\n".join([head("NAW_BL", "BASELINE", 1, 0, period("NAW_VT", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z"),
                         period("NAW_LT", "2026-01-01T00:00:00Z", "2027-01-01T00:00:00Z")),
                    props(10, ("type", "R"), ("designator", "SYNR1"), ("name", None, 'nilReason="missing"')),
                    component("NAW_GC", "BASE", "1", volume("NAW_AV", limits(18, ("100", "FL", "STD"), ("GND", None, "SFC")),
                                                             None, name="SYNTHETIC VOLUME (5.2 name)"))])
    pd = "\n".join([head("NAW_PD", "PERMDELTA", 2, 0, instant("NAW_PD_VT", "2026-02-01T00:00:00Z")),
                    props(10, ("name", None, 'nilReason="inapplicable"'))])
    out["cases/nil_absent_withdrawn.xml"] = document(
        "M_NIL_ABSENT", "A fictitious restricted area whose BASELINE states a nil name (missing) and no localType,\n"
        "     with a validTime and a featureLifetime that end, a volume with no projection (a 5.2 name on it), and a\n"
        "     PERMDELTA that withdraws the name (nil, inapplicable) and states nothing else. Written by\n"
        "     spec/build_fixtures.py on 2026-09-21 (aixm52).",
        [feature("Airspace", CASE[22], [("NAW_BL", bl), ("NAW_PD", pd)])])
    # TS_001: a schema-valid BASELINE with a TimeInstant.
    body = "\n".join([head("TS1_BL", "BASELINE", 1, 0, instant("TS1_VT", "2026-01-01T00:00:00Z")),
                      props(10, ("type", "TSA"), ("designator", "SYNTS1")),
                      activation("TS1_ACT", "AVBL_FOR_ACTIVATION", activity=None, identifier=uuid(24))])
    out["cases/baseline_with_time_instant_ts001.xml"] = document(
        "M_TS001", "A fictitious airspace whose BASELINE carries a gml:TimeInstant — schema-VALID, and a breach\n"
        "     of Temporality Concept rule TS_001 the adapter reports and does not repair. Written by\n"
        "     spec/build_fixtures.py on 2026-09-21 (aixm52).", [feature("Airspace", CASE[23], [("TS1_BL", body)])])
    # Two features outside the families whose ledger-bound elements are carried: a DME with location
    # and one availability (a 5.2 DME states tuningFrequencyVHF, not 5.1.1's ghostFrequency), a
    # Taxiway with two availability structures.
    # The 5.2 DMEPropertyGroup is the NavaidEquipmentPropertyGroup (designator … location …
    # availability, annotation) followed by type, channel, displace, tuningFrequencyVHF.
    dme = "\n".join([head("DME_BL", "BASELINE", 1, 0, period("DME_VT", "2026-01-01T00:00:00Z", None)),
                     props(10, ("designator", "SYD"), ("name", "SYNTHETIC DME")),
                     "          <aixm:location>\n" + elevated_point("DME_LOC", "52.5 5.5", elevation=("30", "M"), horizontal_accuracy=None,
                                                                    datum=None, indent=12) + "\n          </aixm:location>",
                     availability("DME_AV", "NavaidOperationalStatus", "OPERATIONAL"),
                     props(10, ("channel", "84X"), ("tuningFrequencyVHF", "113.7", 'uom="MHZ"'))])
    twy = "\n".join([head("TWY_BL", "BASELINE", 1, 0, period("TWY_VT", "2026-01-01T00:00:00Z", None)),
                     props(10, ("designator", "SYNA"), ("type", "PARALLEL")),
                     availability("TWY_AV1", "ManoeuvringAreaAvailability", "NORMAL"),
                     availability("TWY_AV2", "ManoeuvringAreaAvailability", "CLOSED",
                                  schedule=timesheet("TWY_TS", 14, day="ANY", start="23:00", end="05:00"))])
    out["cases/other_feature_location_availability.xml"] = document(
        "M_OTHER_CARRIED", "Two fictitious features OUTSIDE the five families whose ledger-bound elements the\n"
        "     generic reading carries: a DME with a location and one availability (and 5.2's tuningFrequencyVHF),\n"
        "     a Taxiway with two availability structures. Written by spec/build_fixtures.py on 2026-09-21 (aixm52).",
        [feature("DME", CASE[24], [("DME_BL", dme)]), feature("Taxiway", CASE[25], [("TWY_BL", twy)])])
    return out


# --------------------------------------------------------------------------- the refusals

def malformed(baseline: str) -> dict[str, str]:
    out: dict[str, str] = {}
    def variant(name: str, text: str, note_: str) -> None:
        out["malformed/" + name] = text.replace("<!-- SYNTHETIC. ", f"<!-- SYNTHETIC, MALFORMED ON PURPOSE ({note_}). ", 1)
    segment = re.compile(r"<gml:GeodesicString>.*?</gml:GeodesicString>", re.S)
    arc = ('<gml:ArcByCenterPoint numArc="1">\n                                      <gml:pos>52.25 5.25</gml:pos>\n'
           '                                      <gml:radius uom="NM">5</gml:radius>\n'
           '                                      <gml:startAngle uom="deg">0</gml:startAngle>\n'
           '                                      <gml:endAngle uom="deg">90</gml:endAngle>\n'
           '                                    </gml:ArcByCenterPoint>')
    circle = ('<gml:CircleByCenterPoint numArc="1">\n                                      <gml:pos>52.25 5.25</gml:pos>\n'
              '                                      <gml:radius uom="NM">5</gml:radius>\n'
              '                                    </gml:CircleByCenterPoint>')
    assert segment.search(baseline)
    variant("arc_by_centre_point_airspace.xml", segment.sub(arc, baseline, count=1), "an arc, refused by default and never chorded")
    variant("circle_by_centre_point_airspace.xml", segment.sub(circle, baseline, count=1), "a circle, refused by default and never polygonised")
    variant("unsupported_crs_epsg3857.xml", baseline.replace(EPSG, "urn:ogc:def:crs:EPSG::3857"), "a CRS outside the two accepted")
    variant("three_dimensional_positions.xml",
            baseline.replace(f'srsName="{EPSG}"', f'srsName="{EPSG}" srsDimension="3"').replace(
                "52.0 5.0 52.0 5.5 52.5 5.5 52.5 5.0 52.0 5.0", "52.0 5.0 0 52.0 5.5 0 52.5 5.5 0 52.5 5.0 0 52.0 5.0 0"),
            "srsDimension 3")
    variant("unclosed_ring.xml", baseline.replace("52.0 5.0 52.0 5.5 52.5 5.5 52.5 5.0 52.0 5.0", "52.0 5.0 52.0 5.5 52.5 5.5 52.5 5.0"),
            "a ring whose last position is not its first")
    variant("end_before_begin.xml", baseline.replace('<gml:endPosition indeterminatePosition="unknown"/>',
                                                     "<gml:endPosition>2025-01-01T00:00:00Z</gml:endPosition>", 1),
            "a validTime running backwards, SEM-007")
    variant("feature_without_identifier.xml", baseline.replace(f'      <gml:identifier codeSpace="urn:uuid:">{TSA1}</gml:identifier>\n', ""),
            "a feature with no gml:identifier")
    variant("non_integer_sequence_number.xml", baseline.replace("<aixm:sequenceNumber>1</aixm:sequenceNumber>",
                                                                "<aixm:sequenceNumber>one</aixm:sequenceNumber>"), "a non-integer sequenceNumber")
    variant("unknown_interpretation.xml", baseline.replace("<aixm:interpretation>BASELINE</aixm:interpretation>",
                                                           "<aixm:interpretation>CURRENT</aixm:interpretation>"), "an interpretation outside the four")
    variant("cancelled_slice_without_as_of.xml",
            baseline.replace("          <gml:validTime>\n            " + period("TSA1_BL_1_0_VT", "2026-01-01T00:00:00Z", None) + "\n          </gml:validTime>",
                             '          <gml:validTime nilReason="inapplicable"/>').replace(
                "<aixm:interpretation>BASELINE</aixm:interpretation>", "<aixm:interpretation>TEMPDELTA</aixm:interpretation>").replace(
                "          <aixm:featureLifetime>\n            " + period("TSA1_BL_1_0_LT", "2026-01-01T00:00:00Z", None) + "\n          </aixm:featureLifetime>\n", ""),
            "a §4.4.8 cancellation with no as-of context")
    variant("wrong_namespace_5_1_1.xml", baseline.replace("http://www.aixm.aero/schema/5.2", "http://www.aixm.aero/schema/5.1.1"),
            "the AIXM 5.1.1 namespaces — the sibling adapter's version, refused at the root here")
    variant("wrong_root_element.xml", baseline.replace("<message:AIXMBasicMessage ", "<message:AIXMMessage ").replace(
        "</message:AIXMBasicMessage>", "</message:AIXMMessage>"), "a root that is not AIXMBasicMessage")
    variant("truncated_document.xml", baseline[: baseline.index("<aixm:activation>")], "cut mid-document")
    out["malformed/no_feature_member.xml"] = document("M_NO_FEATURE", "MALFORMED ON PURPOSE: no member is a feature (no aixm:timeSlice).",
                                                       ["    <aixm:Note gml:id=\"N_ONLY\">\n      <aixm:purpose>REMARK</aixm:purpose>\n    </aixm:Note>"])
    out["malformed/billion_laughs_dtd.xml"] = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!-- SYNTHETIC, MALFORMED ON PURPOSE: a DOCTYPE with entity expansion, refused at its declaration. -->\n'
        '<!DOCTYPE message:AIXMBasicMessage [\n  <!ENTITY a "aaaaaaaaaa">\n  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">\n'
        '  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">\n]>\n' + baseline.split("\n", 2)[2].replace("SYNTHETIC TSA ONE", "&c;", 1))
    out["malformed/unresolved_entity_reference.xml"] = baseline.replace("SYNTHETIC TSA ONE</aixm:name>", "&undefined;</aixm:name>", 1)
    out["malformed/xinclude_element.xml"] = baseline.replace(
        "  <message:hasMember>", '  <xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="/etc/hostname" parse="text"/>\n  <message:hasMember>', 1)
    return out


def counterexamples(baseline: str, aerodrome_xml: str) -> dict[str, str]:
    out: dict[str, str] = {}
    def variant(name: str, text: str, note_: str) -> None:
        out["counterexamples/" + name] = text.replace("<!-- SYNTHETIC. ", f"<!-- SYNTHETIC, SCHEMA-INVALID ON PURPOSE ({note_}). ", 1)
    variant("unknown_property_in_slice.xml", baseline.replace("          <aixm:type>TSA</aixm:type>",
                                                             "          <aixm:type>TSA</aixm:type>\n          <aixm:colour>RED</aixm:colour>"),
            "a property the AirspaceTimeSlice does not declare")
    variant("properties_out_of_order.xml", baseline.replace(
        "          <aixm:type>TSA</aixm:type>\n          <aixm:designator>SYNTSA1</aixm:designator>",
        "          <aixm:designator>SYNTSA1</aixm:designator>\n          <aixm:type>TSA</aixm:type>"), "designator before type")
    variant("status_outside_enumeration.xml", baseline.replace("AVBL_FOR_ACTIVATION", "SOMETIMES"), "a status outside CodeStatusAirspaceType")
    variant("foreign_extension_element.xml", baseline.replace(
        "          <aixm:activation>", '          <aixm:extension>\n            <syn:AirspaceExtension xmlns:syn="urn:synthetic:ext" gml:id="TSA1_EXT_1">\n'
        "              <syn:colour>RED</syn:colour>\n            </syn:AirspaceExtension>\n          </aixm:extension>\n          <aixm:activation>", 1),
        "an extension in a namespace with no schema, before activation")
    variant("missing_interpretation.xml", baseline.replace("          <aixm:interpretation>BASELINE</aixm:interpretation>\n", ""),
            "no interpretation, required on every time slice")
    variant("property_removed_in_5_2.xml", aerodrome_xml.replace(
        '          <aixm:fieldElevation uom="FT">12</aixm:fieldElevation>',
        '          <aixm:fieldElevation uom="FT">12</aixm:fieldElevation>\n          <aixm:fieldElevationAccuracy uom="FT">1</aixm:fieldElevationAccuracy>'),
        "fieldElevationAccuracy is an AIXM 5.1.1 property with no element in 5.2")
    return out


# ------------------------------------------------------------------------------- the set

def build() -> dict[str, str]:
    files = {"airspace_baseline_polygon.xml": airspace_baseline(), "airspace_deltas_same_feature.xml": airspace_deltas(),
             "airport_runway_navaid.xml": aerodrome(), "vertical_structure_two_parts.xml": tower(),
             "airspace_hole_crs84_snapshot.xml": danger_area()}
    files.update(cases())
    files.update(malformed(files["airspace_baseline_polygon.xml"]))
    files.update(counterexamples(files["airspace_baseline_polygon.xml"], files["airport_runway_navaid.xml"]))
    return files


def twin_json(xml: str) -> str:
    from synapse_cdm import secure_xml
    from synapse_cdm.adapters import aixm52, aixm_codec
    twin = aixm_codec.twin_of(secure_xml.parse(xml.encode("utf-8"), aixm52.XML_LIMITS).root, aixm_codec.VERSION_52)
    return json.dumps(twin, indent=2, ensure_ascii=False) + "\n"


def write_pin() -> None:
    from synapse_cdm.evidence import digest
    pin_path = HERE / "aixm52_pin.json"
    record = json.loads(pin_path.read_text(encoding="utf-8"))
    files = {}
    for path in sorted(ROOT.rglob("*")):
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file() or "golden" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name in ("PROVENANCE.json", "aixm52_pin.json"):
            continue
        sha256, size = digest(path)
        files[rel] = {"sha256": sha256, "bytes": size}
    record["files"] = files
    record["file_count"] = len(files)
    pin_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"pinned {len(files)} files in {pin_path.name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--check", action="store_true", help="compare with the committed files, write nothing")
    parser.add_argument("--pin", action="store_true", help="rewrite spec/aixm52_pin.json's file table from the disk")
    args = parser.parse_args(argv)
    if args.pin:
        write_pin()
        return 0
    files = build()
    for name in [n for n in files if "/" not in n]:
        files[name.removesuffix(".xml") + ".parsed.json"] = twin_json(files[name])
    stale = []
    for rel, content in sorted(files.items()):
        path = ROOT / rel
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(rel)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if args.check:
        print("CURRENT" if not stale else "STALE: " + ", ".join(stale))
        return 1 if stale else 0
    print(f"wrote {len(files)} files under {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
