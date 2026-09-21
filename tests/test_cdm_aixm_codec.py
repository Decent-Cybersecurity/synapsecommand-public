"""The shared AIXM codec (`adapters/aixm_codec.py`), adapter expansion phase 4 (2026-09-21).

Master prompt §7: temporality kept as stated with absent, nil, unchanged and withdrawn apart;
references resolved in the document and in a caller's table, never remotely; geometry read under
its CRS with EPSG:4326 latitude-first distinguished from CRS84 longitude-first; arcs, circles and
composite curves refused, never approximated; vertical limits with their unit and reference,
unknown apart from unlimited, and no conversion. Each of those is a function here with its own
test; the adapter tests (`test_cdm_aixm511_adapter.py`) prove the same properties end to end.
"""
from __future__ import annotations

import ast
import pathlib
import xml.etree.ElementTree as ET

import pytest

from synapse_cdm.adapters import aixm511, aixm_codec as codec
from synapse_cdm.adapters.aixm_codec import (
    CrsReading, DocumentIndex, GeometryUnsupported, ReferenceTarget, VERSION_511,
)
from tests import normative_support

NS = ('xmlns:message="http://www.aixm.aero/schema/5.1.1/message" xmlns:aixm="http://www.aixm.aero/schema/5.1.1" '
      'xmlns:gml="http://www.opengis.net/gml/3.2" xmlns:xlink="http://www.w3.org/1999/xlink" '
      'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"')
EPSG = "urn:ogc:def:crs:EPSG::4326"
CRS84 = "urn:ogc:def:crs:OGC:1.3:CRS84"


def _twin(body: str) -> dict:
    root = ET.fromstring(f'<message:AIXMBasicMessage {NS} gml:id="m">{body}</message:AIXMBasicMessage>')
    return codec.twin_of(root, VERSION_511)


def _node(xml: str) -> dict:
    """A geometry/property object as its twin node (the object-property collapse applied)."""
    twin = _twin(f"<message:hasMember>{xml}</message:hasMember>")
    return twin["message:hasMember"][0]


# ------------------------------------------------------------------------------- the twin

def test_the_twin_collapses_each_property_object_pair_and_keeps_the_object_name():
    twin = _twin('<message:hasMember><aixm:Airspace gml:id="a"><gml:identifier codeSpace="urn:uuid:">x</gml:identifier>'
                 '<aixm:timeSlice><aixm:AirspaceTimeSlice gml:id="ts"><gml:validTime><gml:TimePeriod gml:id="p">'
                 '<gml:beginPosition>2026-01-01T00:00:00Z</gml:beginPosition><gml:endPosition indeterminatePosition="unknown"/>'
                 '</gml:TimePeriod></gml:validTime><aixm:interpretation>BASELINE</aixm:interpretation>'
                 '<aixm:name xsi:nil="true" nilReason="unknown"/><aixm:type>D</aixm:type>'
                 '</aixm:AirspaceTimeSlice></aixm:timeSlice></aixm:Airspace></message:hasMember>')
    member = twin["message:hasMember"][0]
    assert member["$"] == "aixm:Airspace" and member["@gml:id"] == "a"
    assert member["gml:identifier"] == {"@codeSpace": "urn:uuid:", "#text": "x"}
    ts = member["aixm:timeSlice"][0]
    assert ts["$"] == "aixm:AirspaceTimeSlice"
    assert ts["gml:validTime"] == {"$": "gml:TimePeriod", "@gml:id": "p",
                                   "gml:beginPosition": "2026-01-01T00:00:00Z",
                                   "gml:endPosition": {"@indeterminatePosition": "unknown"}}
    assert ts["aixm:interpretation"] == "BASELINE"
    assert ts["aixm:name"] == {"@xsi:nil": "true", "@nilReason": "unknown"}
    assert list(ts)[-2:] == ["aixm:name", "aixm:type"], "document order is kept"


def test_repeatable_properties_are_always_lists_and_others_list_only_when_repeated():
    single = _twin('<message:hasMember><aixm:Airspace gml:id="a"><aixm:timeSlice><aixm:AirspaceTimeSlice gml:id="t">'
                   '<aixm:geometryComponent><aixm:AirspaceGeometryComponent gml:id="g"/></aixm:geometryComponent>'
                   '</aixm:AirspaceTimeSlice></aixm:timeSlice></aixm:Airspace></message:hasMember>')
    ts = single["message:hasMember"][0]["aixm:timeSlice"][0]
    assert isinstance(ts["aixm:geometryComponent"], list) and len(ts["aixm:geometryComponent"]) == 1
    # An object outside the table (an extension's own object) lists a property only when it repeats.
    ext = _node('<aixm:Airspace gml:id="a"><aixm:timeSlice><aixm:AirspaceTimeSlice gml:id="t"><aixm:extension>'
                '<syn:Ext xmlns:syn="urn:syn" gml:id="e"><syn:a>1</syn:a><syn:b>1</syn:b><syn:b>2</syn:b></syn:Ext>'
                '</aixm:extension></aixm:AirspaceTimeSlice></aixm:timeSlice></aixm:Airspace>')
    ext_obj = ext["aixm:timeSlice"][0]["aixm:extension"][0]
    assert ext_obj["$"] == "{urn:syn}Ext", "a foreign namespace is spelled in Clark form"
    assert ext_obj["{urn:syn}a"] == "1" and ext_obj["{urn:syn}b"] == ["1", "2"]
    # gml:segments holds several objects: one property, a list of collapsed objects.
    curve = _node('<aixm:Curve gml:id="c"><gml:segments><gml:LineStringSegment><gml:posList>0 0 1 1</gml:posList>'
                  '</gml:LineStringSegment><gml:GeodesicString><gml:posList>1 1 2 2</gml:posList></gml:GeodesicString>'
                  '</gml:segments></aixm:Curve>')
    assert [s["$"] for s in curve["gml:segments"]] == ["gml:LineStringSegment", "gml:GeodesicString"]


def test_a_property_attribute_beside_a_child_object_is_kept_under_a_double_at():
    node = _node('<aixm:Airspace gml:id="a"><aixm:timeSlice owns="true"><aixm:AirspaceTimeSlice gml:id="t"/>'
                 '</aixm:timeSlice></aixm:Airspace>')
    assert node["aixm:timeSlice"][0] == {"$": "aixm:AirspaceTimeSlice", "@gml:id": "t", "@@owns": "true"}


def test_the_root_is_refused_with_its_namespace_or_its_name():
    root = ET.fromstring('<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1/message" gml:id="m" '
                         'xmlns:gml="http://www.opengis.net/gml/3.2"/>')
    with pytest.raises(ValueError, match="namespace 'http://www.aixm.aero/schema/5.1/message'"):
        codec.twin_of(root, VERSION_511)
    root = ET.fromstring(f'<aixm:Airspace {NS} gml:id="m"/>')
    with pytest.raises(ValueError, match="<aixm:Airspace>, not <message:AIXMBasicMessage>"):
        codec.twin_of(root, VERSION_511)
    # The 5.2 version object names the other namespaces; the shared code takes the version as data.
    root = ET.fromstring('<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.2/message" '
                         'xmlns:gml="http://www.opengis.net/gml/3.2" gml:id="m"/>')
    assert codec.twin_of(root, codec.VERSION_52) == {"@gml:id": "m"}


@pytest.mark.normative
def test_the_repeatable_table_is_the_pinned_schemas():
    """The AIXM rows of `REPEATABLE`, re-derived from the pinned AIXM 5.1.1 XSD: every object
    element reachable by value from the five families and (phase 5, NAV.UNS) the eleven
    NavaidEquipment specialisations — `REPEATABLE_ROOTS` — with its unbounded properties."""
    resource = normative_support.resource("aixm511")
    root = pathlib.Path(resource.directory) / "aixm-5.1.1"
    xs = "{http://www.w3.org/2001/XMLSchema}"
    types: dict[str, ET.Element] = {}
    elements: dict[str, ET.Element] = {}
    groups: dict[str, ET.Element] = {}
    for name in ("AIXM_Features.xsd", "AIXM_DataTypes.xsd", "AIXM_AbstractGML_ObjectTypes.xsd"):
        for child in ET.parse(root / name).getroot():
            n = child.get("name")
            if child.tag in (xs + "simpleType", xs + "complexType") and n:
                types[n] = child
            elif child.tag == xs + "element" and n:
                elements[n] = child
            elif child.tag == xs + "group" and n:
                groups[n] = child

    def particles(node, out, many=False, stack=()):
        for c in node:
            tag = c.tag[len(xs):]
            mo = c.get("maxOccurs", "1")
            m = many or mo == "unbounded" or (mo.isdigit() and int(mo) > 1)
            if tag == "element":
                name = ("aixm:" + c.get("name")) if c.get("name") else c.get("ref")
                typ = c.get("type")
                if typ is None and c.get("name"):
                    typ = "anon:" + ",".join(e.get("ref") for e in c.iter(xs + "element") if e.get("ref"))
                out.append((name, typ, m))
            elif tag in ("sequence", "choice", "all"):
                particles(c, out, m, stack)
            elif tag == "group" and c.get("ref"):
                particles(groups[c.get("ref").split(":")[-1]], out, m, stack)
            elif tag in ("complexContent", "extension", "restriction", "simpleContent"):
                base = (c.get("base") or "").split(":")[-1]
                if base in types and tag == "extension" and base not in stack:
                    particles(types[base], out, many, stack + (base,))
                particles(c, out, m, stack)

    def objects_of(ptype):
        if ptype is None or ptype.startswith("anon:"):
            return [r for r in (ptype or "anon:")[5:].split(",") if r]
        t = types.get(ptype.split(":")[-1])
        return [] if t is None else [e.get("ref") for e in t.iter(xs + "element") if e.get("ref")]

    derived: dict[str, tuple[str, ...]] = {}
    seen: set[str] = set()

    def visit(element_name):
        if element_name in seen or element_name not in elements:
            return
        seen.add(element_name)
        t = types.get((elements[element_name].get("type") or "").split(":")[-1])
        if t is None:
            return
        out: list = []
        particles(t, out)
        rep = tuple(sorted({name for name, _, m in out if m}))
        if rep:
            derived["aixm:" + element_name] = rep
        for name, ptyp, _ in out:
            if ptyp and (ptyp.endswith("PropertyType") or ptyp.startswith("anon:")):
                for obj in objects_of(ptyp):
                    visit(obj.split(":")[-1])

    assert codec.REPEATABLE_ROOTS[:6] == ("Airspace", "AirportHeliport", "Runway", "RunwayDirection", "Navaid", "VerticalStructure")
    assert set(codec.REPEATABLE_ROOTS[6:]) == {n.split(":")[1] for n in aixm511.NAVAID_EQUIPMENT_FEATURES}
    for start in codec.REPEATABLE_ROOTS:
        visit(start)
    embedded = {k: tuple(v for v in codec.REPEATABLE[k] if not v.startswith("gml:") or v == "gml:name")
                for k in codec.REPEATABLE_AIXM_ROWS}
    assert embedded == derived


# ------------------------------------------------------------------------ property states

def test_absent_nil_and_stated_are_read_under_the_interpretation():
    for delta in ("PERMDELTA", "TEMPDELTA"):
        assert codec.property_state(None, delta).model_dump(exclude_none=True) == {"state": "absent", "meaning": "unchanged"}
        withdrawn = codec.property_state({"@xsi:nil": "true", "@nilReason": "inapplicable"}, delta)
        assert (withdrawn.state, withdrawn.meaning, withdrawn.nil_reason) == ("nil", "withdrawn", "inapplicable")
    for full in ("BASELINE", "SNAPSHOT"):
        assert codec.property_state(None, full).meaning == "not stated"
        nil = codec.property_state({"@xsi:nil": "true", "@nilReason": "unknown"}, full)
        assert (nil.state, nil.meaning, nil.nil_reason) == ("nil", "nil", "unknown")
    stated = codec.property_state({"@uom": "FT", "#text": "2500"}, "BASELINE")
    assert (stated.state, stated.meaning, stated.value, stated.uom) == ("stated", "stated", "2500", "FT")
    assert codec.property_state("TSA", "TEMPDELTA").value == "TSA"
    # A nilReason with no xsi:nil and no text is still nil; a text beside a nilReason is stated.
    assert codec.property_state({"@nilReason": "withheld"}, "BASELINE").state == "nil"
    assert codec.property_state({"@nilReason": "other:x", "#text": "A"}, "BASELINE").state == "stated"
    with pytest.raises(ValueError, match="more than once"):
        codec.scalar(["a", "b"])


# ------------------------------------------------------------------------------- time

def test_time_positions_keep_the_text_the_instant_the_indeterminacy_and_the_zone_rule():
    ok = codec.read_time_position("2026-03-10T08:00:00Z")
    assert (ok.text, ok.instant, ok.utc, ok.problem) == ("2026-03-10T08:00:00Z", "2026-03-10T08:00:00.000Z", True, None)
    offset = codec.read_time_position("2026-03-10T10:00:00+02:00")
    assert offset.instant == "2026-03-10T08:00:00.000Z" and offset.utc is False and "TS_012" in offset.problem
    unknown = codec.read_time_position({"@indeterminatePosition": "unknown"})
    assert unknown.instant is None and unknown.indeterminate == "unknown" and unknown.problem is None
    assert "TS_020" in codec.read_time_position("2026-03-10T24:00:00Z").problem
    assert "not an ISO 8601" in codec.read_time_position("10 MAR 2026").problem
    assert "empty position" in codec.read_time_position("").problem


def test_valid_time_forms_and_the_temporality_rules_a_slice_is_held_to():
    period = codec.read_time_primitive({"$": "gml:TimePeriod", "@gml:id": "p", "gml:beginPosition": "2026-01-01T00:00:00Z",
                                        "gml:endPosition": {"@indeterminatePosition": "unknown"}})
    assert period.form == "period" and period.convention == codec.PERIOD_CONVENTION
    instant = codec.read_time_primitive({"$": "gml:TimeInstant", "gml:timePosition": "2026-04-01T00:00:00Z"})
    assert instant.form == "instant" and instant.time.instant == "2026-04-01T00:00:00.000Z"
    cancelled = codec.read_time_primitive({"@nilReason": "inapplicable"})
    assert (cancelled.form, cancelled.nil_reason) == ("nil", "inapplicable")
    assert codec.read_time_primitive(None).form == "absent"
    absent = codec.read_time_primitive(None)
    assert codec.temporality_problems("BASELINE", "1", "0", period, absent, "w") == []
    assert any("TS_001" in p for p in codec.temporality_problems("BASELINE", "1", "0", instant, absent, "w"))
    assert any("TS_002" in p for p in codec.temporality_problems("PERMDELTA", "1", "0", period, absent, "w"))
    assert any("TS_003" in p for p in codec.temporality_problems("TEMPDELTA", "1", "0", instant, absent, "w"))
    snapshot = codec.temporality_problems("SNAPSHOT", "1", None, period, absent, "w")
    assert any("TS_004" in p for p in snapshot) and any("TS_006" in p for p in snapshot)
    assert any("TS_016" in p for p in codec.temporality_problems("TEMPDELTA", "2", "0", period, period, "w"))
    assert codec.temporality_problems("CURRENT", None, None, absent, absent, "w") == [
        "w: interpretation 'CURRENT' is not one of ('BASELINE', 'PERMDELTA', 'TEMPDELTA', 'SNAPSHOT')"]
    with pytest.raises(ValueError, match="neither gml:TimePeriod nor gml:TimeInstant"):
        codec.read_time_primitive({"$": "gml:TimeNode"})


# --------------------------------------------------------------------------- references

def test_href_forms_are_classified_and_resolved_one_hop_in_the_document_or_the_table():
    uuid_a, uuid_b = "a1a40000-00c0-4000-8000-000000000001", "A1A40000-00C0-4000-8000-000000000002"
    members = [{"$": "aixm:AirportHeliport", "@gml:id": "uuid." + uuid_a,
                "gml:identifier": {"@codeSpace": "urn:uuid:", "#text": uuid_a}},
               {"$": "aixm:Runway", "@gml:id": "RWY1", "gml:identifier": uuid_b}, "not a member"]
    index = DocumentIndex.of(members)
    assert index.duplicates == []
    assert codec.classify_href("urn:uuid:" + uuid_b) == ("urn-uuid", uuid_b.lower())
    assert codec.classify_href("#RWY1") == ("local-id", "RWY1")
    assert codec.classify_href("http://example.invalid/svc#uuid." + uuid_a)[0] == "url"
    assert codec.classify_href("urn:aixm:AirportHeliport:designator=ZZSY")[0] == "natural-key"
    assert codec.classify_href("something else")[0] == "other"
    by_urn = codec.resolve_reference("servedAirport", {"@xlink:href": "urn:uuid:" + uuid_b}, index)
    assert by_urn.resolved and by_urn.target.element == "aixm:Runway" and by_urn.target.member_index == 1
    by_id = codec.resolve_reference("usedRunway", {"@xlink:href": "#RWY1", "@xlink:title": "09/27"}, index)
    assert by_id.resolved and by_id.form == "local-id" and by_id.title == "09/27"
    by_uuid_id = codec.resolve_reference("servedAirport", {"@xlink:href": "#uuid." + uuid_a}, index)
    assert by_uuid_id.resolved and by_uuid_id.target.where == "document"
    url = codec.resolve_reference("servedAirport", {"@xlink:href": "http://example.invalid/svc#uuid." + uuid_a}, index)
    assert not url.resolved and url.form == "url" and url.href.startswith("http://")
    missing = "a1a40000-00c0-4000-8000-000000000009"
    unresolved = codec.resolve_reference("theAirspace", {"@xlink:href": "urn:uuid:" + missing}, index)
    assert not unresolved.resolved and unresolved.key == missing
    table = {missing: ReferenceTarget(element="aixm:Airspace", identifier=missing, where="table")}
    from_table = codec.resolve_reference("theAirspace", {"@xlink:href": "urn:uuid:" + missing.upper()}, index, table)
    assert from_table.resolved and from_table.target.where == "table"
    none = codec.resolve_reference("protectedRoute", {"@nilReason": "unknown"}, index)
    assert none.form == "none" and none.nil_reason == "unknown"
    with pytest.raises(ValueError, match="by value"):
        codec.resolve_reference("usedRunway", {"$": "aixm:Runway"}, index)
    twice = [{"$": "aixm:Runway", "@gml:id": "same", "gml:identifier": uuid_a}] * 2
    assert len(DocumentIndex.of(twice).duplicates) == 2


def test_the_codec_opens_no_socket_and_no_file():
    tree = ast.parse(pathlib.Path(codec.__file__).read_text())
    imported = {n.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for n in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imported & {"urllib", "socket", "http", "requests", "pathlib", "os", "io", "subprocess"}, imported
    assert "open" not in {node.func.id for node in ast.walk(tree)
                          if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}


# ------------------------------------------------------------------------------ geometry

def _surface(srs: str, poslist: str, form: str = "gml:GeodesicString", interior: str | None = None,
             extra: str = "") -> dict:
    hole = f'<gml:interior><gml:LinearRing><gml:posList>{interior}</gml:posList></gml:LinearRing></gml:interior>' if interior else ""
    return _node(f'<aixm:Surface gml:id="s" srsName="{srs}"{extra}><gml:patches><gml:PolygonPatch><gml:exterior><gml:Ring>'
                 f'<gml:curveMember><aixm:Curve gml:id="c"><gml:segments><{form}><gml:posList>{poslist}</gml:posList>'
                 f'</{form}></gml:segments></aixm:Curve></gml:curveMember></gml:Ring></gml:exterior>{hole}'
                 '</gml:PolygonPatch></gml:patches></aixm:Surface>')


SQUARE = "52.1 5.2 52.1 5.4 52.3 5.4 52.3 5.2 52.1 5.2"


def test_epsg4326_is_latitude_first_and_crs84_longitude_first_and_they_are_not_the_same_place():
    epsg = codec.read_surface(_surface(EPSG, SQUARE))
    crs84 = codec.read_surface(_surface(CRS84, SQUARE))
    assert epsg.crs.axis_order == ("latitude", "longitude") and crs84.crs.axis_order == ("longitude", "latitude")
    assert epsg.geojson["coordinates"][0][0] == [5.2, 52.1], "canonical [lon, lat] from a lat-first posList"
    assert crs84.geojson["coordinates"][0][0] == [52.1, 5.2], "the same text under CRS84 is another place"
    assert epsg.geojson != crs84.geojson
    assert epsg.patches[0].exterior.orientation == "counter-clockwise"
    assert crs84.patches[0].exterior.orientation == "clockwise", "the mirror image runs the other way, and is reported"
    assert codec.orientation_notes(crs84, "w") and not codec.orientation_notes(epsg, "w")
    point = codec.read_point(_node(f'<aixm:ElevatedPoint gml:id="p" srsName="{EPSG}"><gml:pos>52.18556 5.20833</gml:pos></aixm:ElevatedPoint>'))
    assert (point.longitude, point.latitude, point.pos_text) == (5.20833, 52.18556, "52.18556 5.20833")
    point84 = codec.read_point(_node(f'<aixm:ElevatedPoint gml:id="p" srsName="{CRS84}"><gml:pos>52.18556 5.20833</gml:pos></aixm:ElevatedPoint>'))
    assert (point84.longitude, point84.latitude) == (52.18556, 5.20833)


def test_srs_name_is_inherited_from_the_nearest_ancestor_and_never_assumed():
    inherited = codec.read_point(_node('<aixm:Point gml:id="p"><gml:pos>52.1 5.2</gml:pos></aixm:Point>'),
                                 CrsReading(srs_name=EPSG, axis_order=("latitude", "longitude")))
    assert inherited.crs.inherited and (inherited.longitude, inherited.latitude) == (5.2, 52.1)
    with pytest.raises(GeometryUnsupported, match="no srsName") as none:
        codec.read_point(_node('<aixm:Point gml:id="p"><gml:pos>52.1 5.2</gml:pos></aixm:Point>'))
    assert none.value.kind == "crs"
    with pytest.raises(GeometryUnsupported, match="EPSG::3857") as other:
        codec.read_surface(_surface("urn:ogc:def:crs:EPSG::3857", SQUARE))
    assert other.value.kind == "crs" and other.value.source == "urn:ogc:def:crs:EPSG::3857"
    with pytest.raises(GeometryUnsupported, match="srsDimension 3") as three:
        codec.read_surface(_surface(EPSG, "52.1 5.2 0 52.1 5.4 0 52.3 5.4 0 52.3 5.2 0 52.1 5.2 0", extra=' srsDimension="3"'))
    assert three.value.kind == "dimension"


def test_arcs_circles_and_composite_curves_are_refused_with_their_source_and_never_approximated():
    arc = _node(f'<aixm:Surface gml:id="s" srsName="{EPSG}"><gml:patches><gml:PolygonPatch><gml:exterior><gml:Ring>'
                '<gml:curveMember><aixm:Curve gml:id="c"><gml:segments><gml:ArcByCenterPoint numArc="1"><gml:pos>52.2 5.3</gml:pos>'
                '<gml:radius uom="NM">5</gml:radius><gml:startAngle uom="deg">0</gml:startAngle><gml:endAngle uom="deg">90</gml:endAngle>'
                '</gml:ArcByCenterPoint></gml:segments></aixm:Curve></gml:curveMember></gml:Ring></gml:exterior>'
                '</gml:PolygonPatch></gml:patches></aixm:Surface>')
    with pytest.raises(GeometryUnsupported, match="not approximated by a chord") as e:
        codec.read_surface(arc)
    assert (e.value.kind, e.value.element) == ("segment", "gml:ArcByCenterPoint")
    assert e.value.source["gml:radius"] == {"@uom": "NM", "#text": "5"}, "the source is on the refusal"
    for segment in ("gml:CircleByCenterPoint", "gml:Arc", "gml:ArcString", "gml:Circle"):
        with pytest.raises(GeometryUnsupported) as u:
            codec.read_curve(_node(f'<aixm:Curve gml:id="c" srsName="{EPSG}"><gml:segments><{segment}><gml:posList>'
                                   f'52.1 5.2 52.2 5.3 52.3 5.2</gml:posList></{segment}></gml:segments></aixm:Curve>'))
        assert u.value.element == segment and u.value.kind == "segment"
    with pytest.raises(GeometryUnsupported, match="CompositeCurve and") as composite:
        codec.read_surface(_node(f'<aixm:Surface gml:id="s" srsName="{EPSG}"><gml:patches><gml:PolygonPatch><gml:exterior>'
                                 '<gml:Ring><gml:curveMember><gml:CompositeCurve gml:id="cc"/></gml:curveMember></gml:Ring>'
                                 '</gml:exterior></gml:PolygonPatch></gml:patches></aixm:Surface>'))
    assert composite.value.kind == "curve"
    with pytest.raises(GeometryUnsupported, match="by reference") as ref:
        codec.read_surface(_node(f'<aixm:Surface gml:id="s" srsName="{EPSG}"><gml:patches><gml:PolygonPatch><gml:exterior>'
                                 '<gml:Ring><gml:curveMember xlink:href="#elsewhere"/></gml:Ring>'
                                 '</gml:exterior></gml:PolygonPatch></gml:patches></aixm:Surface>'))
    assert ref.value.kind == "curve"
    with pytest.raises(GeometryUnsupported, match="interpolation 'circularArc3Points'"):
        codec.read_curve(_node(f'<aixm:Curve gml:id="c" srsName="{EPSG}"><gml:segments><gml:GeodesicString interpolation="circularArc3Points">'
                               '<gml:posList>52.1 5.2 52.2 5.3</gml:posList></gml:GeodesicString></gml:segments></aixm:Curve>'))


def test_linear_and_geodesic_segments_stay_distinct_and_joins_are_kept_once():
    curve = codec.read_curve(_node(f'<aixm:Curve gml:id="c" srsName="{EPSG}"><gml:segments>'
                                   '<gml:LineStringSegment interpolation="linear"><gml:posList>52.1 5.2 52.1 5.4</gml:posList></gml:LineStringSegment>'
                                   '<gml:GeodesicString><gml:pos>52.1 5.4</gml:pos><gml:pos>52.3 5.4</gml:pos></gml:GeodesicString>'
                                   '</gml:segments></aixm:Curve>'))
    assert [s.interpolation for s in curve.segments] == ["linear", "geodesic"]
    assert curve.segments[0].pos_list_text == "52.1 5.2 52.1 5.4" and curve.segments[1].pos_texts == ["52.1 5.4", "52.3 5.4"]
    assert curve.coordinates == [[5.2, 52.1], [5.4, 52.1], [5.4, 52.3]], "the shared join position appears once"
    with pytest.raises(GeometryUnsupported, match="must be connected") as gap:
        codec.read_curve(_node(f'<aixm:Curve gml:id="c" srsName="{EPSG}"><gml:segments>'
                               '<gml:GeodesicString><gml:posList>52.1 5.2 52.1 5.4</gml:posList></gml:GeodesicString>'
                               '<gml:GeodesicString><gml:posList>52.2 5.4 52.3 5.4</gml:posList></gml:GeodesicString>'
                               '</gml:segments></aixm:Curve>'))
    assert gap.value.kind == "closure"


def test_holes_and_several_patches_land_as_polygon_rings_and_a_multipolygon():
    with_hole = codec.read_surface(_surface(CRS84, "6.0 53.0 6.4 53.0 6.4 53.3 6.0 53.3 6.0 53.0", "gml:LineStringSegment",
                                            interior="6.1 53.1 6.1 53.2 6.3 53.2 6.3 53.1 6.1 53.1"))
    assert with_hole.geojson["type"] == "Polygon" and len(with_hole.geojson["coordinates"]) == 2
    assert with_hole.patches[0].interiors[0].element == "gml:LinearRing"
    assert with_hole.patches[0].interiors[0].orientation == "clockwise"
    ring_hole = codec.read_surface(_node(
        f'<aixm:Surface gml:id="s" srsName="{CRS84}"><gml:patches><gml:PolygonPatch>'
        '<gml:exterior><gml:LinearRing><gml:posList>6.0 53.0 6.4 53.0 6.4 53.3 6.0 53.3 6.0 53.0</gml:posList></gml:LinearRing></gml:exterior>'
        '<gml:interior><gml:Ring><gml:curveMember><aixm:Curve gml:id="i"><gml:segments><gml:LineStringSegment>'
        '<gml:posList>6.1 53.1 6.1 53.2 6.3 53.2 6.3 53.1 6.1 53.1</gml:posList></gml:LineStringSegment></gml:segments>'
        '</aixm:Curve></gml:curveMember></gml:Ring></gml:interior></gml:PolygonPatch>'
        '<gml:PolygonPatch><gml:exterior><gml:LinearRing><gml:posList>7.0 53.0 7.1 53.0 7.1 53.1 7.0 53.1 7.0 53.0</gml:posList>'
        '</gml:LinearRing></gml:exterior></gml:PolygonPatch></gml:patches></aixm:Surface>'))
    assert ring_hole.geojson["type"] == "MultiPolygon" and len(ring_hole.geojson["coordinates"]) == 2
    assert ring_hole.patches[0].interiors[0].element == "gml:Ring" and ring_hole.patches[0].interiors[0].curves[0].gml_id == "i"
    with pytest.raises(GeometryUnsupported, match="not closed") as open_ring:
        codec.read_surface(_surface(EPSG, "52.1 5.2 52.1 5.4 52.3 5.4 52.3 5.2"))
    assert open_ring.value.kind == "closure"
    with pytest.raises(GeometryUnsupported, match="do not pair"):
        codec.read_surface(_surface(EPSG, "52.1 5.2 52.1"))
    with pytest.raises(GeometryUnsupported, match="count=3"):
        codec.read_curve(_node(f'<aixm:Curve gml:id="c" srsName="{EPSG}"><gml:segments><gml:GeodesicString>'
                               '<gml:posList count="3">52.1 5.2 52.1 5.4</gml:posList></gml:GeodesicString></gml:segments></aixm:Curve>'))
    with pytest.raises(GeometryUnsupported, match="outside WGS84 range"):
        codec.read_point(_node(f'<aixm:Point gml:id="p" srsName="{EPSG}"><gml:pos>95.0 5.2</gml:pos></aixm:Point>'))
    with pytest.raises(GeometryUnsupported, match="not a gml:PolygonPatch"):
        codec.read_surface(_node(f'<aixm:Surface gml:id="s" srsName="{EPSG}"><gml:patches><gml:Rectangle/></gml:patches></aixm:Surface>'))


# ------------------------------------------------------------------------------ vertical

def _limit(value: str | None, uom: str | None, reference: str | None, interpretation: str = "BASELINE"):
    node = None if value is None else ({"@uom": uom, "#text": value} if uom else value)
    return codec.read_vertical_limit(node, reference, interpretation)


def test_units_and_references_project_member_for_member_and_nothing_is_converted():
    cases = {("2500", "FT", "MSL"): ("ft", "MSL"), ("762", "M", "MSL"): ("m", "MSL"), ("1000", "FT", "SFC"): ("ft", "AGL"),
             ("3000", "FT", "W84"): ("ft", "HAE"), ("10000", "FT", "STD"): ("ft", "BARO"), ("100", "FL", "STD"): ("FL", "FL"),
             ("100", "FL", None): ("FL", "FL"), ("1000", "FT", None): ("ft", "UNKNOWN")}
    for (value, uom, reference), (unit, datum) in cases.items():
        limit = _limit(value, uom, reference)
        assert limit.kind == "numeric" and limit.cdm is not None, (value, uom, reference)
        assert (limit.cdm.value, limit.cdm.unit, limit.cdm.reference) == (float(value), unit, datum)
    feet, metres = _limit("2500", "FT", "MSL"), _limit("762", "M", "MSL")
    assert feet.cdm.reference == metres.cdm.reference == "MSL", "a change of unit is not a change of datum"
    assert feet.cdm.value == 2500.0 and feet.cdm.unit == "ft", "feet stay feet"


def test_what_the_cdm_has_no_member_for_is_carried_with_the_reason_and_unknown_is_not_unlimited():
    sm = _limit("300", "SM", "STD")
    assert sm.kind == "numeric" and sm.cdm is None and "SM" in sm.not_projected
    fl_msl = _limit("100", "FL", "MSL")
    assert fl_msl.cdm is None and "flight level against reference 'MSL'" in fl_msl.not_projected
    other = _limit("100", "FT", "OTHER:LOCAL")
    assert other.cdm is None and "not one of SFC, MSL, W84, STD" in other.not_projected
    no_uom = _limit("100", None, "MSL")
    assert no_uom.cdm is None and "unstated uom" in no_uom.not_projected
    unlimited = _limit("UNL", None, None)
    unknown = codec.read_vertical_limit({"@xsi:nil": "true", "@nilReason": "unknown"}, None, "BASELINE")
    absent = _limit(None, None, None)
    assert (unlimited.kind, unknown.kind, absent.kind) == ("unlimited", "unknown", "absent")
    assert unlimited.cdm is None and unknown.cdm is None and unknown.limit.nil_reason == "unknown"
    assert _limit("GND", "FT", "SFC").kind == "ground"
    assert _limit("FLOOR", None, None).kind == "floor" and _limit("CEILING", None, None).kind == "ceiling"
    withdrawn = codec.read_vertical_limit({"@xsi:nil": "true", "@nilReason": "inapplicable"}, None, "TEMPDELTA")
    assert withdrawn.limit.meaning == "withdrawn"
    assert _limit(None, None, None, "TEMPDELTA").limit.meaning == "unchanged"


def test_an_elevated_points_elevation_is_msl_by_the_models_definition_and_alt_stays_unprojected_otherwise():
    elevation = codec.read_elevation({"aixm:elevation": {"@uom": "FT", "#text": "12"}, "aixm:verticalDatum": "EGM_96",
                                      "aixm:geoidUndulation": {"@uom": "M", "#text": "44.1"}}, "BASELINE")
    assert (elevation.cdm.value, elevation.cdm.unit, elevation.cdm.reference) == (12.0, "ft", "MSL")
    assert elevation.vertical_datum.value == "EGM_96" and elevation.geoid_undulation.value == "44.1"
    assert codec.read_elevation({}, "BASELINE").cdm is None
    assert codec.read_elevation({"aixm:elevation": {"@uom": "SM", "#text": "1"}}, "BASELINE").cdm is None
    nil = codec.read_elevation({"aixm:elevation": {"@xsi:nil": "true", "@nilReason": "unknown"}}, "BASELINE")
    assert nil.cdm is None and nil.not_projected == "nil (unknown)"


# ----------------------------------------------------------------------------- schedules

def test_timesheets_are_typed_validity_and_nil_intervals_are_no_schedule():
    node = {"$": "aixm:AirspaceActivation",
            "aixm:timeInterval": [{"@xsi:nil": "true"},
                                  {"$": "aixm:Timesheet", "@gml:id": "t", "aixm:timeReference": "UTC", "aixm:day": "WORK_DAY",
                                   "aixm:startTime": "07:00", "aixm:endTime": "17:00", "aixm:startEvent": {"@xsi:nil": "true", "@nilReason": "inapplicable"}}]}
    sheets = codec.read_schedule(node, "BASELINE")
    assert len(sheets) == 1 and sheets[0].gml_id == "t"
    props = sheets[0].properties
    assert props["day"].value == "WORK_DAY" and props["startTime"].value == "07:00" and props["endTime"].value == "17:00"
    assert props["startEvent"].state == "nil" and props["endDate"].state == "absent"
    assert set(props) == {p.split(":", 1)[1] for p in codec.TIMESHEET_PROPERTIES}
    with pytest.raises(ValueError, match="not aixm:Timesheet"):
        codec.read_timesheet({"$": "aixm:Note"}, "BASELINE")
