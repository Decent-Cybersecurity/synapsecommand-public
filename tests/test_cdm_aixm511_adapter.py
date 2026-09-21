"""AIXM 5.1.1 adapter (#19, `adapters/aixm511.py` on `adapters/aixm_codec.py`), adapter
expansion phase 4 (2026-09-21).

What is proved here, by section: the fixtures are what the record says and every twin is the
parse of its XML (an independent ElementTree re-derivation); every positive fixture validates
against the pinned XSD closure through an actual validator (BLOCKED, never PASS, without the
resource) and every counterexample is rejected at its declared layer; master §7's temporality
(one Entity per time slice, identity from gml:identifier, validity from validTime, the four
property states, the cancelled slice under an as-of context), references (every form, one hop,
the caller's table, a cycle), geometry (the EPSG:4326 / CRS84 pair, holes, orientation reported,
arcs and circles refused by default and typed under `report`, compositions typed and not drawn)
and vertical meaning (unit and reference member for member, feet not converted, unknown apart
from unlimited); the §9 cross-cutting list (stable ids, zero values, wrong version, unknown
fields, missing context, determinism, bounds at and past, no network, member order); the
independent Donlon reading; three targeted negatives.
"""
from __future__ import annotations

import ast
import copy
import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
from pydantic import TypeAdapter

import synapse_cdm
from synapse_cdm import harness, lossless, secure_xml
from synapse_cdm.adapter import InputTooLarge
from synapse_cdm.adapters import aixm511 as module
from synapse_cdm.adapters import aixm_codec as codec
from synapse_cdm.adapters.aixm511 import (
    AIXM511_MAX_DEPTH, AIXM511_MAX_ELEMENTS, AIXM511_MAX_INPUT_BYTES, AIXM511_MAX_OBJECTS,
    Aixm511Adapter, AsOf, ObjectCountExceeded, ReferenceTarget, TimeSliceBlock,
)
from synapse_cdm.enums import EntityType
from synapse_cdm.models import CDMObject, Entity, PlanObject
from tests import normative_support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "aixm511"
MALFORMED = FIXTURES / "malformed"
CASES = FIXTURES / "cases"
COUNTER = FIXTURES / "counterexamples"
INDEPENDENT = FIXTURES / "independent"
PIN = FIXTURES / "spec" / "aixm511_pin.json"
XML_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".xml")
TWIN_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".json")
BASELINE = FIXTURES / "airspace_baseline_polygon.xml"
DELTAS = FIXTURES / "airspace_deltas_same_feature.xml"
AERODROME = FIXTURES / "airport_runway_navaid.xml"
TOWER = FIXTURES / "vertical_structure_two_parts.xml"
HOLE = FIXTURES / "airspace_hole_crs84_snapshot.xml"
POSITIVE = XML_FILES + sorted(CASES.glob("*.xml")) + sorted(INDEPENDENT.glob("*.xml"))
TSA1 = "a1a40000-0001-4000-8000-000000000001"
AIRPORT = "a1a40000-0002-4000-8000-000000000001"
RUNWAY = "a1a40000-0003-4000-8000-000000000001"
DIRECTION = "a1a40000-0004-4000-8000-000000000001"
NAVAID = "a1a40000-0005-4000-8000-000000000001"
AS_OF = AsOf("2026-03-09T12:00:00Z", "the synthetic publication instant of the correction, stated by the fixture's author")
OBJECTS = TypeAdapter(list[CDMObject])


def _xml(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def _twin(path: pathlib.Path) -> dict:
    return json.loads((path.parent / (path.stem + ".parsed.json")).read_text())


def _dump(objects):
    return [o if isinstance(o, dict) else o.model_dump(mode="json") for o in objects]


def _ledger(raw, objects):
    return lossless.ledger(raw, _dump(objects), Aixm511Adapter.MAPPINGS)


def _block(obj) -> TimeSliceBlock:
    return TimeSliceBlock.model_validate(obj.attributes["aixm"])


def _entities(objects, identifier: str | None = None) -> list[Entity]:
    return [o for o in objects if isinstance(o, Entity)
            and (identifier is None or o.source_ids[0].external_id == identifier)]


def _plans(objects) -> list[PlanObject]:
    return [o for o in objects if isinstance(o, PlanObject)]


def _twin_of(raw: bytes) -> dict:
    return codec.twin_of(secure_xml.parse(raw, module.XML_LIMITS).root, codec.VERSION_511)


# ----------------------------------------------------------------- the fixtures themselves

def test_the_fixture_set_is_the_one_the_record_describes():
    assert [p.name for p in XML_FILES] == ["airport_runway_navaid.xml", "airspace_baseline_polygon.xml",
                                           "airspace_deltas_same_feature.xml", "airspace_hole_crs84_snapshot.xml",
                                           "vertical_structure_two_parts.xml"]
    assert [p.stem.removesuffix(".parsed") for p in TWIN_FILES] == [p.stem for p in XML_FILES]
    assert len(sorted(MALFORMED.glob("*.xml"))) == 17
    assert len(sorted(CASES.glob("*.xml"))) == 9
    assert len(sorted(COUNTER.glob("*.xml"))) == 5
    assert sorted(p.name for p in INDEPENDENT.iterdir() if p.name != "PROVENANCE.json") == [
        "README.md", "donlon_extract.xml", "donlon_extract_arc_airspace.xml", "expected.json"]
    pin = json.loads(PIN.read_text())
    import hashlib
    for rel, entry in pin["files"].items():
        assert hashlib.sha256((FIXTURES / rel).read_bytes()).hexdigest() == entry["sha256"], rel
    # `__pycache__` is pip's byte-compilation of the two `spec/build_fixtures.py` in an installed
    # wheel (the wheel gate runs this module against site-packages); bytecode is not a fixture.
    assert all(str(p.relative_to(FIXTURES)) in pin["files"] for p in FIXTURES.rglob("*")
               if p.is_file() and "golden" not in p.parts and "__pycache__" not in p.parts
               and p.name not in ("PROVENANCE.json", "aixm511_pin.json"))


def test_every_fixture_is_synthetic_by_default_and_names_no_real_place():
    for path in XML_FILES + sorted(CASES.glob("*.xml")):
        for obj in Aixm511Adapter().to_cdm(_xml(path)):
            assert obj.source.synthetic is True
        text = path.read_text()
        assert "SYNTHETIC" in text and "a1a40000-" in text, path.name
    assert Aixm511Adapter(synthetic=False).to_cdm(_xml(BASELINE))[0].source.synthetic is False


def test_every_parsed_twin_corresponds_to_its_raw_fixture():
    """The twin re-derived from the XML with the standard library ALONE — the object-property
    collapse spelled here by hand, the repeatable properties listed by hand — equals the
    committed twin. No codec table is consulted."""
    prefixes = {"http://www.aixm.aero/schema/5.1.1": "aixm", "http://www.aixm.aero/schema/5.1.1/message": "message",
                "http://www.opengis.net/gml/3.2": "gml", "http://www.w3.org/1999/xlink": "xlink",
                "http://www.w3.org/2001/XMLSchema-instance": "xsi"}
    always_list = {"message:hasMember", "aixm:timeSlice", "aixm:geometryComponent", "aixm:activation", "aixm:availability",
                   "aixm:timeInterval", "aixm:part", "aixm:navaidEquipment", "aixm:runwayDirection", "aixm:servedAirport",
                   "aixm:annotation", "aixm:translatedNote", "aixm:extension", "gml:patches", "gml:segments",
                   "gml:interior", "gml:curveMember", "gml:name", "aixm:servedCity", "aixm:contact",
                   "aixm:specialDateAuthority", "aixm:usage", "aixm:levels", "aixm:user", "aixm:aircraft", "aixm:class"}

    def key(tag):
        uri, local = tag[1:].split("}", 1)
        return f"{prefixes[uri]}:{local}" if uri in prefixes else tag

    def obj(element):
        node = {"@" + key(a) if a.startswith("{") else "@" + a: v for a, v in element.attrib.items()}
        for child in element:
            k = key(child.tag)
            kids = list(child)
            if kids:
                values = [{"$": key(g.tag), **obj(g), **{"@@" + (key(a) if a.startswith("{") else a): v
                                                         for a, v in child.attrib.items()}} for g in kids]
                force = len(values) != 1
            else:
                attrs = {"@" + (key(a) if a.startswith("{") else a): v for a, v in child.attrib.items()}
                text = (child.text or "").strip()
                values = [({**attrs, **({"#text": text} if text else {})} if attrs else text)]
                force = False
            if k in always_list or force or k in node:
                existing = node.get(k)
                node[k] = (existing if isinstance(existing, list) else ([existing] if existing is not None else [])) + values
            else:
                node[k] = values[0]
        return node

    for path in XML_FILES:
        root = ET.fromstring(path.read_bytes())
        assert root.tag == "{http://www.aixm.aero/schema/5.1.1/message}AIXMBasicMessage"
        assert obj(root) == _twin(path), path.name


@pytest.mark.parametrize("path", XML_FILES, ids=lambda p: p.stem)
def test_the_xml_and_its_twin_translate_to_the_same_objects(path):
    assert _dump(Aixm511Adapter().to_cdm(_xml(path))) == _dump(Aixm511Adapter().to_cdm(_twin(path)))


@pytest.mark.normative
@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_every_positive_fixture_validates_against_the_pinned_schema(path):
    verdict = normative_support.verdict("aixm511", path.read_bytes())
    assert verdict.outcome.value == "VALID", verdict.describe()


#: Counterexample -> the layer that rejects it. Every one is well-formed and schema-INVALID; the
#: adapter's structural reading refuses only what it cannot read at all.
COUNTEREXAMPLE_LAYERS = {
    "unknown_property_in_slice.xml": "normative",
    "properties_out_of_order.xml": "normative",
    "status_outside_enumeration.xml": "normative",
    "foreign_extension_element.xml": "normative",
    "missing_interpretation.xml": "adapter+normative",
}


@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_is_rejected_at_its_declared_layer(name):
    raw = (COUNTER / name).read_bytes()
    layer = COUNTEREXAMPLE_LAYERS[name]
    if layer.startswith("adapter"):
        with pytest.raises(ValueError):
            Aixm511Adapter().to_cdm(raw)
    else:
        objects = Aixm511Adapter().to_cdm(raw)
        assert objects, "the structural layer reads it; the schema breach is carried, not repaired"
        assert _ledger(_twin_of(raw), objects).lost == ()
    readme = (COUNTER / "README.md").read_text()
    assert name in readme and layer.split("+")[0] in readme


@pytest.mark.normative
@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_is_invalid_against_the_pinned_schema(name):
    verdict = normative_support.verdict("aixm511", (COUNTER / name).read_bytes())
    assert verdict.outcome.value == "INVALID", verdict.describe()


# ------------------------------------------------------------- identity and temporality

def test_one_entity_per_time_slice_and_the_feature_identity_holds_across_slices_and_documents():
    baseline = Aixm511Adapter().to_cdm(_xml(BASELINE))
    deltas = Aixm511Adapter().to_cdm(_xml(DELTAS))
    assert [type(o).__name__ for o in baseline] == ["Entity", "PlanObject"]
    assert [type(o).__name__ for o in deltas] == ["Entity", "Entity", "Entity"]
    ids_ = {o.entity_id for o in _entities(baseline) + _entities(deltas)}
    assert len(ids_) == 1, "four slices of one feature are four states of one entity, never four entities"
    assert all(o.source_ids[0].external_id == TSA1 for o in baseline + deltas)
    assert [o.source_ids[1].external_id for o in deltas] == [f"{TSA1}/TEMPDELTA/2/0", f"{TSA1}/TEMPDELTA/2/1", f"{TSA1}/PERMDELTA/3/0"]
    assert [o.source.original_id for o in deltas] == ["TSA1_TD_2_0", "TSA1_TD_2_1", "TSA1_PD_3_0"]
    assert [o.source.record_index for o in deltas] == [0, 1, 2]
    other = Aixm511Adapter().to_cdm(_xml(HOLE))
    assert _entities(other)[0].entity_id != _entities(baseline)[0].entity_id
    assert _entities(baseline)[0].entity_type.value == "OVERLAY_OBJECT"
    aerodrome = _entities(Aixm511Adapter().to_cdm(_xml(AERODROME)))
    assert [o.entity_type.value for o in aerodrome] == ["FACILITY"] * 4 + ["UNKNOWN"]
    other = _block(aerodrome[4])
    assert other.feature.family == "other" and other.feature.element == "aixm:OrganisationAuthority"
    assert other.time_slice.interpretation == "BASELINE" and aerodrome[4].position is None and aerodrome[4].status is None
    assert other.properties["name"].value == "SYNTHETIC AIRPORT OPERATOR", "a pinned name is typed whatever the family"


def test_validity_is_the_slices_valid_time_under_the_begin_included_end_excluded_convention():
    baseline = _entities(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    assert baseline.valid_from == _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc) and baseline.valid_to is None
    block = _block(baseline)
    assert block.time_slice.valid_time.end.indeterminate == "unknown" and "§4.4.1" in block.time_slice.valid_time.convention
    assert block.time_slice.feature_lifetime.form == "period" and block.time_slice.valid_from_basis.endswith("gml:beginPosition")
    td0, td1, pd = _entities(Aixm511Adapter().to_cdm(_xml(DELTAS)))
    assert (td0.valid_from.hour, td0.valid_to.hour) == (8, 16) and (td1.valid_from.hour, td1.valid_to.hour) == (8, 14)
    assert _block(td1).time_slice.correction_number == 1, "the correction keeps the sequence and moves the end"
    assert pd.valid_from == _dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc) and pd.valid_to is None
    assert _block(pd).time_slice.valid_time.form == "instant" and _block(pd).time_slice.valid_from_basis.endswith("gml:timePosition")
    snapshot = _entities(Aixm511Adapter().to_cdm(_xml(HOLE)))[1]
    assert _block(snapshot).time_slice.interpretation == "SNAPSHOT"
    assert _block(snapshot).time_slice.sequence_number is None and _block(snapshot).time_slice.correction_number is None
    plan = _plans(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    assert plan.validity.valid_from == baseline.valid_from and plan.validity.effective.start == baseline.valid_from
    assert plan.expires_at is None and plan.validity.valid_to is None
    ended = _entities(Aixm511Adapter().to_cdm(_xml(CASES / "nil_absent_withdrawn.xml")))[0]
    assert ended.valid_to == _dt.datetime(2027, 1, 1, tzinfo=_dt.timezone.utc)
    assert _block(ended).time_slice.feature_lifetime.end.instant == "2027-01-01T00:00:00.000Z"


def test_absent_nil_unchanged_and_withdrawn_are_four_distinct_typed_states():
    baseline, delta = _entities(Aixm511Adapter().to_cdm(_xml(CASES / "nil_absent_withdrawn.xml")))
    b, d = _block(baseline).properties, _block(delta).properties
    assert (b["designator"].state, b["designator"].meaning, b["designator"].value) == ("stated", "stated", "SYNR1")
    assert (b["name"].state, b["name"].meaning, b["name"].nil_reason) == ("nil", "nil", "missing")
    assert (b["localType"].state, b["localType"].meaning) == ("absent", "not stated")
    assert (d["name"].state, d["name"].meaning, d["name"].nil_reason) == ("nil", "withdrawn", "inapplicable")
    assert (d["designator"].state, d["designator"].meaning) == ("absent", "unchanged")
    td0, _, pd = _entities(Aixm511Adapter().to_cdm(_xml(DELTAS)))
    assert _block(pd).properties["localType"].meaning == "withdrawn" and _block(pd).properties["name"].value == "SYNTHETIC TSA ONE RENAMED"
    assert _block(td0).properties["type"].meaning == "unchanged"
    assert _block(td0).volume_projection == "none: the slice states no geometryComponent"
    assert {p.meaning for p in _block(td0).properties.values()} == {"unchanged"}, "a delta states only what changed"


def test_a_cancelled_slice_needs_the_as_of_context_and_never_the_clock():
    raw = _xml(MALFORMED / "cancelled_slice_without_as_of.xml")
    with pytest.raises(ValueError, match="nilReason='inapplicable'.*as-of context"):
        Aixm511Adapter().to_cdm(raw)
    with pytest.raises(ValueError, match="cancelled-slice-needs-as-of"):
        Aixm511Adapter(clock=lambda: _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    one = Aixm511Adapter(as_of=AS_OF, clock=lambda: _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    two = Aixm511Adapter(as_of=AS_OF, clock=lambda: _dt.datetime(2031, 6, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    assert _dump(one) == _dump(two), "the clock reaches nothing on an entity"
    entity = _entities(one)[0]
    assert entity.valid_from == AS_OF.instant and entity.valid_to is None
    block = _block(entity)
    assert block.time_slice.valid_time.form == "nil" and block.time_slice.valid_time.nil_reason == "inapplicable"
    assert block.time_slice.valid_from_basis.startswith("as_of") and block.as_of["basis"] == AS_OF.basis
    assert any("§4.4.8" in note and AS_OF.basis in note for note in entity.source.transformations)
    assert block.activation[0].properties["status"].value == "ACTIVE"
    assert "1970" not in json.dumps(_dump(one))
    with pytest.raises(TypeError):
        Aixm511Adapter(as_of="2026-01-01T00:00:00Z")


def test_the_temporality_rules_are_reported_by_validate_source_and_not_repaired():
    raw = _xml(CASES / "baseline_with_time_instant_ts001.xml")
    objects = Aixm511Adapter().to_cdm(raw)
    assert objects and _entities(objects)[0].valid_from == _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)
    problems = Aixm511Adapter().validate_source(raw)
    assert problems == [f"member 0 <aixm:Airspace> {TSA1} slice 0: a BASELINE slice carries validTime/gml:TimeInstant; "
                        "TS_001 requires gml:TimePeriod"]
    assert _block(_entities(objects)[0]).time_slice.temporality_problems == problems
    twin = copy.deepcopy(_twin(DELTAS))
    twin["message:hasMember"][0]["aixm:timeSlice"][1]["aixm:correctionNumber"] = "0"
    assert any("TS_005" in p for p in Aixm511Adapter().validate_source(twin))
    twin = copy.deepcopy(_twin(DELTAS))
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["gml:validTime"]["gml:beginPosition"] = "2026-03-10T10:00:00+02:00"
    entity = _entities(Aixm511Adapter().to_cdm(twin))[0]
    assert entity.valid_from == _dt.datetime(2026, 3, 10, 8, tzinfo=_dt.timezone.utc), "the offset is honoured, not stripped"
    assert any("TS_012" in p for p in Aixm511Adapter().validate_source(twin))


# ----------------------------------------------------------------------------- references

def test_references_are_resolved_in_the_document_in_every_form_and_kept_when_they_are_not():
    objects = Aixm511Adapter().to_cdm(_xml(AERODROME))
    runway = _block(_entities(objects, RUNWAY)[0])
    airport_ref = runway.references["associatedAirportHeliport"]
    assert airport_ref.form == "urn-uuid" and airport_ref.resolved and airport_ref.target.element == "aixm:AirportHeliport"
    assert airport_ref.target.member_index == 0 and airport_ref.title == "ZZSY SYNTHETIC FIELD"
    direction = _block(_entities(objects, DIRECTION)[0])
    assert direction.references["usedRunway"].form == "local-id" and direction.references["usedRunway"].target.identifier == RUNWAY
    navaid = _block(_entities(objects, NAVAID)[0])
    assert navaid.references["runwayDirection"][0].resolved and navaid.references["runwayDirection"][0].target.identifier == DIRECTION
    assert navaid.references["servedAirport"][0].resolved
    assert [c.equipment.resolved for c in navaid.navaid_equipment] == [False, False]
    assert navaid.unresolved_references == [
        "navaidEquipment[0].theNavaidEquipment -> 'urn:uuid:a1a40000-0006-4000-8000-000000000001' (urn-uuid)",
        "navaidEquipment[1].theNavaidEquipment -> 'urn:uuid:a1a40000-0006-4000-8000-000000000002' (urn-uuid)"]
    assert any("unresolved reference navaidEquipment[0]" in p for p in Aixm511Adapter().validate_source(_xml(AERODROME)))
    table = {"a1a40000-0006-4000-8000-000000000001": {"element": "aixm:VOR", "identifier": "a1a40000-0006-4000-8000-000000000001"}}
    resolved = _block(_entities(Aixm511Adapter(references=table).to_cdm(_xml(AERODROME)), NAVAID)[0])
    assert resolved.navaid_equipment[0].equipment.resolved and resolved.navaid_equipment[0].equipment.target.where == "table"
    assert len(resolved.unresolved_references) == 1
    with pytest.raises(ValueError, match="UUID text"):
        Aixm511Adapter(references={"not-a-uuid": {"element": "aixm:VOR"}})


def test_every_reference_form_a_repeat_and_a_cycle_are_typed_and_nothing_is_fetched():
    objects = Aixm511Adapter().to_cdm(_xml(CASES / "reference_forms.xml"))
    navaid = _block(_entities(objects)[1])
    served = navaid.references["servedAirport"]
    assert [r.form for r in served] == ["urn-uuid", "local-id", "local-id", "url", "natural-key"]
    assert [r.resolved for r in served] == [True, True, True, False, False], "a URL is classified and never dereferenced"
    assert served[1].href == served[2].href, "a repeated reference is kept twice, in order"
    directions = navaid.references["runwayDirection"]
    assert [(r.form, r.resolved) for r in directions] == [("local-id", False), ("urn-uuid", False)]
    assert len(navaid.unresolved_references) == 4
    cyclic = Aixm511Adapter().to_cdm(_xml(CASES / "composite_and_cyclic_contributors.xml"))
    assert [type(o).__name__ for o in cyclic] == ["Entity", "Entity"], "a composition draws no Area"
    a, b = (_block(o) for o in cyclic)
    assert a.geometry_components[1].volume.contributor.airspace.target.identifier == b.feature.identifier
    assert b.geometry_components[1].volume.contributor.airspace.target.identifier == a.feature.identifier
    assert a.geometry_components[1].volume.contributor.dependency.value == "FULL_GEOMETRY"
    assert a.volume_projection.startswith("none: component 1 operation 'SUBTR'")
    assert b.volume_projection.startswith("none: component 1 operation 'UNION'")
    assert a.geometry_components[0].volume.horizontal_projection.geojson["type"] == "Polygon", "every component is still typed"
    problems = Aixm511Adapter().validate_source(_xml(CASES / "composite_and_cyclic_contributors.xml"))
    assert sum("composite geometry is not drawn" in p for p in problems) == 2


def test_the_adapter_resolves_no_reference_over_a_network_and_touches_no_file():
    for path in (module.__file__, codec.__file__):
        tree = ast.parse(pathlib.Path(path).read_text())
        imported = {n.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for n in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not imported & {"urllib", "socket", "http", "requests", "pathlib", "os", "io", "subprocess"}, (path, imported)
        assert "open" not in {node.func.id for node in ast.walk(tree)
                              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    import socket

    def refuse(*a, **k):  # pragma: no cover - a refusal is the assertion
        raise AssertionError("the adapter opened a socket")

    original = socket.socket
    socket.socket = refuse  # type: ignore[assignment]
    try:
        objects = Aixm511Adapter().to_cdm(_xml(CASES / "reference_forms.xml"))
    finally:
        socket.socket = original  # type: ignore[assignment]
    assert _block(_entities(objects)[1]).references["servedAirport"][3].href.startswith("http://example.invalid/")


# ------------------------------------------------------------------------------- geometry

def test_epsg4326_and_crs84_encodings_of_the_same_numbers_are_two_different_places():
    epsg = Aixm511Adapter().to_cdm(_xml(CASES / "axis_order_epsg4326.xml"))
    crs84 = Aixm511Adapter().to_cdm(_xml(CASES / "axis_order_crs84.xml"))
    epsg_polygon, crs84_polygon = _plans(epsg)[0].geometry.coordinates[0], _plans(crs84)[0].geometry.coordinates[0]
    assert epsg_polygon[0] == [5.2, 52.1] and crs84_polygon[0] == [52.1, 5.2]
    assert epsg_polygon != crs84_polygon
    epsg_point, crs84_point = _entities(epsg)[1].position, _entities(crs84)[1].position
    assert (epsg_point.lon, epsg_point.lat) == (5.20833, 52.18556)
    assert (crs84_point.lon, crs84_point.lat) == (52.18556, 5.20833)
    surface = _block(_entities(epsg)[0]).geometry_components[0].volume.horizontal_projection
    assert surface.crs.srs_name.endswith("EPSG::4326") and surface.crs.axis_order == ("latitude", "longitude")
    assert surface.patches[0].exterior.curves[0].segments[0].pos_list_text == "52.1 5.2 52.1 5.4 52.3 5.4 52.3 5.2 52.1 5.2"
    assert _block(_entities(crs84)[0]).geometry_components[0].volume.horizontal_projection.crs.axis_order == ("longitude", "latitude")
    assert any("clockwise" in n and "not reversed" in n for n in _plans(crs84)[0].source.transformations)
    assert not any("clockwise" in n for n in _plans(epsg)[0].source.transformations)


def test_the_pinned_surface_forms_holes_and_multipolygons_land_on_the_area():
    plan = _plans(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    assert plan.object_type.value == "CONTROL_MEASURE" and plan.label == "SYNTSA1"
    assert plan.geometry.type == "Polygon" and plan.geometry.coordinates == [[[5.0, 52.0], [5.5, 52.0], [5.5, 52.5], [5.0, 52.5], [5.0, 52.0]]]
    assert plan.area.geometry.coordinates == plan.geometry.coordinates and plan.area.bounds is None
    block = _block(_entities(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0])
    assert block.plan_object_id == str(plan.object_id) and block.volume_projection == "Polygon"
    segment = block.geometry_components[0].volume.horizontal_projection.patches[0].exterior.curves[0].segments[0]
    assert (segment.element, segment.interpolation, segment.count) == ("gml:GeodesicString", "geodesic", 5)
    hole = _plans(Aixm511Adapter().to_cdm(_xml(HOLE)))[0]
    assert len(hole.geometry.coordinates) == 2 and hole.geometry.coordinates[1][0] == [6.1, 53.1]
    hole_block = _block(_entities(Aixm511Adapter().to_cdm(_xml(HOLE)))[0])
    patch = hole_block.geometry_components[0].volume.horizontal_projection.patches[0]
    assert patch.exterior.curves[0].segments[0].interpolation == "linear" and patch.interiors[0].element == "gml:LinearRing"
    ring_hole = _plans(Aixm511Adapter().to_cdm(_xml(CASES / "interior_ring_of_curves.xml")))[0]
    assert ring_hole.geometry.coordinates == hole.geometry.coordinates, "a Ring-of-curves hole and a LinearRing hole are one polygon"
    two = copy.deepcopy(_twin(BASELINE))
    component = two["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:geometryComponent"][0]
    second = copy.deepcopy(component)
    surface = second["aixm:theAirspaceVolume"]["aixm:horizontalProjection"]
    surface["gml:patches"][0]["gml:exterior"]["gml:curveMember"][0]["gml:segments"][0]["gml:posList"] = \
        "53.0 5.0 53.0 5.5 53.5 5.5 53.5 5.0 53.0 5.0"
    two["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:geometryComponent"].append(second)
    multi = _plans(Aixm511Adapter().to_cdm(two))[0]
    assert multi.geometry.type == "MultiPolygon" and len(multi.geometry.coordinates) == 2


def test_arcs_and_circles_are_refused_by_default_and_typed_with_their_source_under_report():
    for name, element in (("arc_by_centre_point_airspace.xml", "gml:ArcByCenterPoint"),
                          ("circle_by_centre_point_airspace.xml", "gml:CircleByCenterPoint")):
        raw = _xml(MALFORMED / name)
        with pytest.raises(ValueError, match=f"{element}.*not approximated by a chord") as refused:
            Aixm511Adapter().to_cdm(raw)
        assert "unsupported_geometry='report'" in str(refused.value)
        reported = Aixm511Adapter(unsupported_geometry="report").to_cdm(raw)
        assert [type(o).__name__ for o in reported] == ["Entity"], "no Area is drawn from an arc"
        block = _block(reported[0])
        unsupported = block.geometry_components[0].volume.unsupported[0]
        assert (unsupported.kind, unsupported.element) == ("segment", element)
        assert unsupported.source["gml:radius"]["#text"] in ("6", "5"), "the source is preserved on the reading"
        assert block.volume_projection.startswith("none:")
        assert any(element in p for p in Aixm511Adapter(unsupported_geometry="report").validate_source(raw))
        assert "ArcByCenterPoint" in json.dumps(block.geometry_components[0].source) or "CircleByCenterPoint" in json.dumps(block.geometry_components[0].source)
    donlon = _xml(INDEPENDENT / "donlon_extract_arc_airspace.xml")
    with pytest.raises(ValueError, match="CircleByCenterPoint"):
        Aixm511Adapter().to_cdm(donlon)
    assert _block(Aixm511Adapter(unsupported_geometry="report").to_cdm(donlon)[0]).volume_projection.startswith("none")
    with pytest.raises(ValueError):
        Aixm511Adapter(unsupported_geometry="approximate")


def test_other_crs_forms_and_a_third_dimension_are_refused_with_the_form_named():
    for name, text in (("unsupported_crs_epsg3857.xml", "EPSG::3857"), ("three_dimensional_positions.xml", "srsDimension 3"),
                       ("unclosed_ring.xml", "not closed")):
        with pytest.raises(ValueError, match=text):
            Aixm511Adapter().to_cdm(_xml(MALFORMED / name))


# ------------------------------------------------------------------------------- vertical

def _upper(plan: PlanObject):
    return None if plan.area.vertical is None or plan.area.vertical.upper is None else (
        plan.area.vertical.upper.value, plan.area.vertical.upper.unit.value, plan.area.vertical.upper.reference.value)


def test_vertical_limits_project_member_for_member_and_feet_to_metres_does_not_change_the_datum():
    objects = Aixm511Adapter().to_cdm(_xml(CASES / "vertical_references.xml"))
    by_designator = {p.label: p for p in _plans(objects)}
    assert _upper(by_designator["VFTMSL"]) == (2500.0, "ft", "MSL")
    assert _upper(by_designator["VMMSL"]) == (762.0, "m", "MSL"), "the same height in metres keeps the same datum"
    assert _upper(by_designator["VFTMSL"])[2] == _upper(by_designator["VMMSL"])[2]
    assert _upper(by_designator["VFTSFC"]) == (1000.0, "ft", "AGL")
    assert _upper(by_designator["VFTW84"]) == (3000.0, "ft", "HAE")
    assert _upper(by_designator["VFTSTD"]) == (10000.0, "ft", "BARO")
    assert _upper(by_designator["VFL"]) == (100.0, "FL", "FL")
    assert _upper(by_designator["VNOREF"]) == (1000.0, "ft", "UNKNOWN")
    for label in ("VSM", "VFLMSL", "VUNL", "VNILUNKNOW"):
        assert _upper(by_designator[label]) is None, label
        assert by_designator[label].area.vertical is not None, "the source described a column"
    for plan in by_designator.values():
        assert plan.area.vertical.lower is None, "GND is a token, not a number"
    blocks = {_block(e).properties["designator"].value: _block(e) for e in _entities(objects)}
    volume = lambda label: blocks[label].geometry_components[0].volume  # noqa: E731
    assert volume("VUNL").upper.kind == "unlimited" and volume("VNILUNKNOW").upper.kind == "unknown"
    assert volume("VUNL").upper.kind != volume("VNILUNKNOW").upper.kind, "unlimited is not unknown"
    assert volume("VFTMSL").lower.kind == "ground" and volume("VFTMSL").lower.reference.value == "SFC"
    assert "SM" in volume("VSM").upper.not_projected and "flight level against reference 'MSL'" in volume("VFLMSL").upper.not_projected
    assert volume("VFTMSL").upper.limit.value == "2500" and volume("VFTMSL").upper.limit.uom == "FT", "the text stays"
    notes = {p.label: p.source.transformations for p in _plans(objects)}
    assert any("not projected onto Area.vertical" in n for n in notes["VSM"]) and any("unlimited" in n for n in notes["VUNL"])
    differ = _entities(objects)[-1]
    assert _block(differ).properties["designator"].value == "VDIFFER" and _block(differ).plan_object_id is None
    assert "different upper/lower limits" in _block(differ).volume_projection
    assert any("different upper/lower limits" in p for p in Aixm511Adapter().validate_source(_xml(CASES / "vertical_references.xml")))
    baseline = _plans(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    assert _upper(baseline) == (195.0, "FL", "FL")
    lower = baseline.area.vertical.lower
    assert (lower.value, lower.unit.value, lower.reference.value) == (2500.0, "ft", "MSL")


def test_positions_are_surveyed_fixes_with_msl_elevations_kept_in_their_unit_and_alt_m_none():
    objects = Aixm511Adapter().to_cdm(_xml(AERODROME))
    airport = _entities(objects, AIRPORT)[0]
    assert (airport.position.lat, airport.position.lon, airport.position.alt_m) == (52.30833, 4.76389, None)
    assert airport.position.position_source.value == "MANUAL"
    assert (airport.position.vertical.value, airport.position.vertical.unit.value, airport.position.vertical.reference.value) == (12.0, "ft", "MSL")
    assert _block(airport).arp.elevation.vertical_datum.value == "EGM_96"
    assert _block(airport).properties["fieldElevation"].uom == "FT"
    navaid = _entities(objects, NAVAID)[0]
    assert (navaid.position.lon, navaid.position.lat) == (4.7, 52.3), "CRS84: longitude first"
    assert (navaid.position.vertical.value, navaid.position.vertical.unit.value) == (30.0, "m")
    assert _entities(objects, RUNWAY)[0].position is None and _entities(objects, DIRECTION)[0].position is None
    tower = _entities(Aixm511Adapter().to_cdm(_xml(TOWER)))[0]
    assert (tower.position.lat, tower.position.lon) == (51.98, 5.1)
    assert (tower.position.vertical.value, tower.position.vertical.unit.value, tower.position.vertical.reference.value) == (250.0, "ft", "MSL")
    parts = _block(tower).parts
    assert [(p.properties["verticalExtent"].value, p.properties["verticalExtent"].uom) for p in parts] == [("120", "M"), ("15", "M")]
    assert parts[0].location_elevation.cdm.reference == "MSL" and parts[1].location is None
    assert "verticalExtent" not in json.dumps(tower.position.model_dump(mode="json")), "an extent is never added to an elevation"
    twin = copy.deepcopy(_twin(TOWER))
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:part"][1]["aixm:horizontalProjection_location"] = copy.deepcopy(
        twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:part"][0]["aixm:horizontalProjection_location"])
    two_located = _entities(Aixm511Adapter().to_cdm(twin))[0]
    assert two_located.position is None and any("2 part(s) state a point location" in n for n in two_located.source.transformations)


def test_zero_values_are_real_and_missing_stays_missing():
    twin = copy.deepcopy(_twin(AERODROME))
    arp = twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:ARP"]
    arp["gml:pos"] = "0.0 0.0"
    arp["aixm:elevation"] = {"@uom": "M", "#text": "0"}
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:magneticVariation"] = "0"
    airport = _entities(Aixm511Adapter().to_cdm(twin), AIRPORT)[0]
    assert (airport.position.lat, airport.position.lon, airport.position.vertical.value) == (0.0, 0.0, 0.0)
    assert _block(airport).properties["magneticVariation"].value == "0"
    del twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:ARP"]
    without = _entities(Aixm511Adapter().to_cdm(twin), AIRPORT)[0]
    assert without.position is None and _block(without).arp is None


# --------------------------------------------------------------------- status and schedules

def test_status_is_asserted_only_from_one_unconditional_structure_and_schedules_stay_typed():
    objects = Aixm511Adapter().to_cdm(_xml(AERODROME))
    airport, direction, navaid = (_entities(objects, i)[0] for i in (AIRPORT, DIRECTION, NAVAID))
    assert (airport.status.state, airport.status.namespace) == ("NORMAL", "AIXM 5.1.1 CodeStatusAirportType")
    assert (navaid.status.state, navaid.status.namespace) == ("OPERATIONAL", "AIXM 5.1.1 CodeStatusNavaidType")
    assert direction.status is None, "a scheduled closure is not an unconditional one"
    closure = _block(direction).availability[0]
    assert closure.properties["operationalStatus"].value == "CLOSED" and closure.properties["warning"].value == "WIP"
    sheet = closure.time_interval[0].properties
    assert (sheet["day"].value, sheet["startTime"].value, sheet["endTime"].value, sheet["dayTil"].value) == ("ANY", "22:00", "05:00", "ANY")
    baseline = _entities(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    assert baseline.status is None and _block(baseline).activation[0].properties["status"].value == "AVBL_FOR_ACTIVATION"
    assert _block(baseline).activation[0].time_interval[0].properties["day"].value == "WORK_DAY"
    td0 = _entities(Aixm511Adapter().to_cdm(_xml(DELTAS)))[0]
    assert (td0.status.state, td0.status.namespace, td0.status.since) == ("ACTIVE", "AIXM 5.1.1 CodeStatusAirspaceType", None)
    twin = copy.deepcopy(_twin(DELTAS))
    slice0 = twin["message:hasMember"][0]["aixm:timeSlice"][0]
    slice0["aixm:activation"].append(copy.deepcopy(slice0["aixm:activation"][0]))
    assert _entities(Aixm511Adapter().to_cdm(twin))[0].status is None, "two structures: none is THE status"
    slice0["aixm:activation"] = [{"@xsi:nil": "true"}]
    nil_only = _entities(Aixm511Adapter().to_cdm(twin))[0]
    assert nil_only.status is None and _block(nil_only).activation[0].nil is True


# --------------------------------------------------------------------- residual and ledger

def test_the_residual_is_the_source_structure_minus_what_was_typed():
    entity = _entities(Aixm511Adapter().to_cdm(_xml(BASELINE)))[0]
    data = entity.residual.data
    assert entity.residual.namespace == "AIXM" == Aixm511Adapter.metadata.format.name
    assert data["@gml:id"] == "M_AIRSPACE_BASELINE"
    member = data["message:hasMember"][0]
    assert member["$"] == "aixm:Airspace" and member["gml:identifier"]["#text"] == TSA1, "the envelope stays at its position"
    leftovers = member["aixm:timeSlice"][0]
    assert list(leftovers) == ["aixm:annotation"], "everything typed is gone; the annotation is not typed"
    assert leftovers["aixm:annotation"][0]["aixm:translatedNote"][0]["aixm:note"]["#text"] == "Activation announced by NOTAM."
    td0, td1, pd = _entities(Aixm511Adapter().to_cdm(_xml(DELTAS)))
    assert td0.residual.data["message:hasMember"][0].get("aixm:timeSlice") is None, "fully typed slices leave nothing"
    aerodrome = Aixm511Adapter().to_cdm(_xml(AERODROME))
    for obj in aerodrome[:4]:
        members = obj.residual.data["message:hasMember"]
        assert members[4] is None, "another feature's slices are that feature's objects, not this one's residual"
    assert any("OrganisationAuthority> is outside the five pinned families" in p
               for p in Aixm511Adapter().validate_source(_xml(AERODROME)))
    runway_members = _entities(aerodrome, RUNWAY)[0].residual.data["message:hasMember"]
    assert runway_members[0] is None and runway_members[1]["aixm:timeSlice"][0] == {"aixm:widthShoulder": {"@uom": "M", "#text": "7.5"}}
    twin = copy.deepcopy(_twin(AERODROME))
    twin["message:hasMember"].append({"$": "aixm:Unit", "@gml:id": "u", "gml:identifier": "not-a-feature"})
    with_non_feature = Aixm511Adapter().to_cdm(twin)
    assert len(with_non_feature) == 5 and with_non_feature[0].residual.data["message:hasMember"][5]["$"] == "aixm:Unit"
    assert any("not an AIXM feature" in p for p in Aixm511Adapter().validate_source(twin))


def test_a_feature_outside_the_families_carries_what_the_ledger_binds_and_loses_nothing():
    """The Donlon Navaid file's 39 NavaidEquipment features state `aixm:location`; the ledger binds
    that key at slice level whatever the family, so the generic reading must carry it (found as
    LOST 46 by the Phase 4 verifier). The same for every `CARRIED_ELEMENTS` member: typed by the
    family that reads it, carried source-verbatim on any other slice; a repeatable one stated
    once on a slice whose type is OUTSIDE the `REPEATABLE` closure (a dict in the twin, unreached
    by the ledger's `[*]` key) stays in the residual. Re-anchored in phase 5: the DME's time-slice
    type joined the closure with NAV.UNS (`REPEATABLE_ROOTS`), so its single availability is now
    a one-item list and is CARRIED like the Taxiway's repeated one; the residual rule is shown on
    a Taxiway stating one availability, whose type is still outside the closure."""
    raw = _xml(CASES / "other_feature_location_availability.xml")
    twin = _twin_of(raw)
    objects = Aixm511Adapter().to_cdm(twin)
    dme, taxiway = _entities(objects)
    assert (dme.entity_type, taxiway.entity_type) == (EntityType.UNKNOWN, EntityType.UNKNOWN)
    assert dme.position is None and taxiway.position is None and dme.status is None and taxiway.status is None, \
        "the generic reading projects nothing to the Entity (D41)"
    location = _block(dme).location
    assert location is not None and location.point is not None and location.unsupported is None
    assert (location.point.latitude, location.point.longitude) == (52.31, 4.71), "EPSG:4326, latitude first"
    assert location.elevation is not None and location.elevation.cdm is not None
    assert (location.elevation.cdm.value, location.elevation.cdm.unit, location.elevation.cdm.reference) == (98.0, "ft", "MSL")
    assert location.source["@gml:id"] == "DME_SYN_LOC" and location.source["gml:pos"] == "52.31000 4.71000"
    assert isinstance(twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:availability"], list), \
        "aixm:DMETimeSlice lists availability since NAV.UNS pinned the equipment classes (REPEATABLE_ROOTS)"
    assert [(s.element, s.gml_id, s.properties, s.source["aixm:operationalStatus"]) for s in _block(dme).availability] == [
        ("aixm:NavaidOperationalStatus", "DME_SYN_OPS_1", {}, "OPERATIONAL")], "carried, status not typed, source verbatim"
    dme_left = dme.residual.data["message:hasMember"][0]["aixm:timeSlice"][0]
    assert dme_left == {"aixm:channel": "84X"}
    assert {k: v.value for k, v in _block(dme).properties.items()} == {"designator": "SYD", "name": "SYNTHETIC DME"}, \
        "the union of pinned simple properties is typed on any slice; `channel` is not one of them"
    carried = _block(taxiway).availability
    assert [(s.element, s.gml_id, s.nil, s.properties, len(s.time_interval)) for s in carried] == [
        ("aixm:ManoeuvringAreaAvailability", "TWY_SYN_AVBL_1", False, {}, 1),
        ("aixm:ManoeuvringAreaAvailability", "TWY_SYN_AVBL_2", False, {}, 0)], \
        "element, gml:id and timesheets read; the status property is not typed"
    assert carried[0].time_interval[0].properties["startTime"].value == "22:00"
    assert carried[0].source["aixm:operationalStatus"] == "CLOSED" and carried[1].source["aixm:operationalStatus"] == "NORMAL"
    assert taxiway.residual.data["message:hasMember"][1].get("aixm:timeSlice") is None, "the repeated availability was the slice's only leftover"
    notes = _block(dme).notes + _block(taxiway).notes
    assert len(notes) == 3 and "<aixm:DME> is outside the families that type aixm:availability" in notes[0]
    assert "<aixm:DME> is outside the families that type aixm:location" in notes[1]
    assert "carried at attributes.aixm.availability" in notes[2] and "nothing projected to the Entity" in notes[2]
    ledger = _ledger(twin, objects)
    assert ledger.lost == () and ledger.counts["MAPPED"] > 0
    # The residual rule, on a type outside the closure: a Taxiway stating ONE availability keeps
    # it as a dict in the twin, which no `[*]` key reaches, so it stays in the residual — and the
    # ledger still finds every leaf there.
    once = copy.deepcopy(twin)
    once["message:hasMember"][1]["aixm:timeSlice"][0]["aixm:availability"] = once["message:hasMember"][1]["aixm:timeSlice"][0]["aixm:availability"][1]
    assert not codec.repeatable("aixm:TaxiwayTimeSlice", "aixm:availability")
    objects_once = Aixm511Adapter().to_cdm(once)
    taxiway_once = _entities(objects_once)[1]
    assert _block(taxiway_once).availability == []
    assert taxiway_once.residual.data["message:hasMember"][1]["aixm:timeSlice"][0]["aixm:availability"]["$"] == "aixm:ManoeuvringAreaAvailability"
    assert _ledger(once, objects_once).lost == ()
    # The shapes the schema allows elsewhere: a repeated reference-form `location` (Service,
    # RadioCommunicationChannel), a distance-typed one (SafeAltitudeArea) and a repeated
    # `navaidEquipment` of another object type (RunwayCentrelinePoint) — every leaf still bound.
    shapes = copy.deepcopy(twin)
    shapes["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:location"] = {"@uom": "M", "#text": "10"}
    slice_ = shapes["message:hasMember"][1]["aixm:timeSlice"][0]
    slice_["aixm:location"] = [{"@xlink:href": "urn:uuid:" + NAVAID}, {"@xlink:href": "#x"}]
    slice_["aixm:navaidEquipment"] = [{"$": "aixm:NavaidEquipmentDistance", "@gml:id": "NED_1",
                                       "aixm:theNavaidEquipment": {"@xlink:href": "#x"}},
                                      {"$": "aixm:NavaidEquipmentDistance", "@gml:id": "NED_2"}]
    objects = Aixm511Adapter().to_cdm(shapes)
    dme, taxiway = _entities(objects)
    assert _block(dme).location.point is None and _block(dme).location.unsupported.reason == "aixm:location holds no point by value"
    assert _block(dme).location.source == {"@uom": "M", "#text": "10"}
    assert _block(taxiway).location.source == slice_["aixm:location"] and _block(taxiway).location.point is None
    assert [(c.gml_id, c.equipment, c.properties) for c in _block(taxiway).navaid_equipment] == [("NED_1", None, {}), ("NED_2", None, {})]
    assert _ledger(shapes, objects).lost == ()


def test_unknown_members_and_attributes_are_preserved_at_their_position():
    twin = copy.deepcopy(_twin(BASELINE))
    twin["@syn:extra"] = "kept"
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["{urn:syn}colour"] = "RED"
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:geometryComponent"][0]["{urn:syn}note"] = "on the component"
    objects = Aixm511Adapter().to_cdm(twin)
    entity = _entities(objects)[0]
    assert entity.residual.data["@syn:extra"] == "kept"
    assert entity.residual.data["message:hasMember"][0]["aixm:timeSlice"][0]["{urn:syn}colour"] == "RED"
    assert _block(entity).geometry_components[0].source["{urn:syn}note"] == "on the component"
    assert _ledger(twin, objects).lost == ()


@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_the_ledger_binds_every_leaf_of_every_fixture_with_no_loss(path):
    raw = _xml(path)
    adapter = Aixm511Adapter(unsupported_geometry="report")
    twin = _twin_of(raw)
    ledger = _ledger(twin, adapter.to_cdm(twin))
    assert ledger.lost == (), [e.line() for e in ledger.lost[:5]]
    assert ledger.counts["MAPPED"] > 0


def test_repeated_identical_values_cannot_conceal_a_value_on_the_wrong_slice():
    """The two TEMPDELTA slices share every value but the end position and the correction
    number; a reading that put slice 1's end on slice 0 is caught by the path-specific
    assertion, not by presence."""
    td0, td1, _ = _entities(Aixm511Adapter().to_cdm(_xml(DELTAS)))
    assert td0.valid_from == td1.valid_from and td0.status.state == td1.status.state
    assert (td0.valid_to.hour, td1.valid_to.hour) == (16, 14)
    assert (_block(td0).time_slice.correction_number, _block(td1).time_slice.correction_number) == (0, 1)
    aerodrome = Aixm511Adapter().to_cdm(_xml(AERODROME))
    airport = _entities(aerodrome, AIRPORT)[0]
    assert _block(airport).properties["fieldElevation"].value == "12" == _block(airport).arp.elevation.elevation.value
    assert airport.position.vertical.value == 12.0, "the ARP elevation, which happens to equal the field elevation"
    twin = copy.deepcopy(_twin(AERODROME))
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["aixm:ARP"]["aixm:elevation"]["#text"] = "13"
    moved = _entities(Aixm511Adapter().to_cdm(twin), AIRPORT)[0]
    assert moved.position.vertical.value == 13.0 and _block(moved).properties["fieldElevation"].value == "12"


def test_the_typed_blocks_validate_against_the_contract_and_the_manifest_matches_the_module():
    for path in XML_FILES:
        for obj in _entities(Aixm511Adapter().to_cdm(_xml(path))):
            block = TimeSliceBlock.model_validate(obj.attributes["aixm"])
            assert block.contract == "aixm-timeslice/1" and block.aixm_version == "5.1.1"
            assert set(obj.attributes) == {"aixm"}
    limits = Aixm511Adapter.metadata.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (
        AIXM511_MAX_INPUT_BYTES, AIXM511_MAX_DEPTH, AIXM511_MAX_OBJECTS)
    assert module.XML_LIMITS == secure_xml.XmlLimits(AIXM511_MAX_INPUT_BYTES, AIXM511_MAX_DEPTH, AIXM511_MAX_ELEMENTS)
    for name in ("max_input_bytes", "max_depth", "max_objects"):
        test = limits.declared_because[name].test
        module_name, test_name = test.split("::")
        # The named test module is read beside THIS file, not through the package's path — the
        # wheel gate runs this module against site-packages, where the repository is not.
        assert test_name in (pathlib.Path(__file__).resolve().parent / pathlib.Path(module_name).name).read_text(), test
    assert Aixm511Adapter.direction == "ingest" and Aixm511Adapter.metadata.residual.value == "structured"
    assert {lim.id for lim in Aixm511Adapter.metadata.limitations if not isinstance(lim, str)} >= {
        "pinned-families", "unsupported-geometry-refused", "composite-volumes-not-drawn", "vertical-projection-by-member",
        "cancelled-slice-needs-as-of", "identifier-required", "references-one-hop", "schedules-not-resolved"}
    # The exported `manifests/aixm511.json` is this metadata by construction and is judged by
    # `python -m synapse_cdm.manifests --check` (a repository file; this module judges the package).
    # `evidence.available` moved false -> true in the 3.1.0 release commit (2026-09-21): the first
    # release carrying this adapter attaches its records; `tests/test_cdm_evidence.py` holds the value.
    assert Aixm511Adapter.metadata.maturity.level.value == "L3" and Aixm511Adapter.metadata.evidence.available is True
    assert Aixm511Adapter.MAPPINGS[""].to == "*:residual.data"


# ------------------------------------------------------------------------------ refusals

REFUSALS = {
    "arc_by_centre_point_airspace.xml": (ValueError, "gml:ArcByCenterPoint"),
    "billion_laughs_dtd.xml": (secure_xml.XmlRefused, "DOCTYPE"),
    "cancelled_slice_without_as_of.xml": (ValueError, "as-of context"),
    "circle_by_centre_point_airspace.xml": (ValueError, "gml:CircleByCenterPoint"),
    "end_before_begin.xml": (ValueError, "SEM-007"),
    "feature_without_identifier.xml": (ValueError, "no gml:identifier"),
    "no_feature_member.xml": (ValueError, "no AIXM feature"),
    "non_integer_sequence_number.xml": (ValueError, "not an integer"),
    "three_dimensional_positions.xml": (ValueError, "srsDimension 3"),
    "truncated_document.xml": (secure_xml.XmlRefused, "not well-formed"),
    "unclosed_ring.xml": (ValueError, "not closed"),
    "unknown_interpretation.xml": (ValueError, "'CURRENT' is not one of"),
    "unresolved_entity_reference.xml": (secure_xml.XmlRefused, "entity"),
    "unsupported_crs_epsg3857.xml": (ValueError, "EPSG::3857"),
    "wrong_namespace_5_1.xml": (ValueError, "schema/5.1/message"),
    "wrong_root_element.xml": (ValueError, "not <message:AIXMBasicMessage>"),
    "xinclude_element.xml": (secure_xml.XmlRefused, "XInclude"),
}


def test_every_malformed_payload_is_refused_by_name():
    assert sorted(REFUSALS) == sorted(p.name for p in MALFORMED.glob("*.xml"))
    for name, (kind, text) in REFUSALS.items():
        with pytest.raises(kind, match=text):
            Aixm511Adapter().to_cdm(_xml(MALFORMED / name))
        problems = Aixm511Adapter().validate_source(_xml(MALFORMED / name))
        assert problems and any(text.split(".*")[0] in p for p in problems), (name, problems)
    twin = copy.deepcopy(_twin(BASELINE))
    twin["message:hasMember"][0]["aixm:timeSlice"][0]["$"] = "aixm:RunwayTimeSlice"
    with pytest.raises(ValueError, match="not aixm:AirspaceTimeSlice"):
        Aixm511Adapter().to_cdm(twin)
    with pytest.raises(ValueError, match="carries message:hasMember"):
        Aixm511Adapter().to_cdm({"@gml:id": "x"})
    with pytest.raises(TypeError):
        Aixm511Adapter().to_cdm(42)  # type: ignore[arg-type]


def test_detect_answers_on_the_root_and_the_namespace_only():
    adapter = Aixm511Adapter()
    assert adapter.detect(_xml(BASELINE)) is True and adapter.detect(_twin(BASELINE)) is True
    assert adapter.detect(_xml(MALFORMED / "wrong_namespace_5_1.xml")) is False
    assert adapter.detect(_xml(MALFORMED / "wrong_root_element.xml")) is False
    assert adapter.detect(b"<x/>") is False and adapter.detect({"a": 1}) is False
    assert adapter.detect(_xml(MALFORMED / "arc_by_centre_point_airspace.xml")) is True, "it is AIXM; the arc is a later refusal"


# --------------------------------------------------------------------------------- bounds

def test_the_byte_bound_admits_a_document_at_it_and_refuses_one_octet_past():
    text = _xml(BASELINE)
    padding = AIXM511_MAX_INPUT_BYTES - len(text)
    at = text.replace(b"</message:AIXMBasicMessage>", b"<!--" + b"x" * (padding - 7) + b"--></message:AIXMBasicMessage>")
    assert len(at) == AIXM511_MAX_INPUT_BYTES
    assert len(Aixm511Adapter().to_cdm(at)) == 2
    with pytest.raises(InputTooLarge):
        Aixm511Adapter().to_cdm(at + b"\n")


def test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past():
    def nested(depth):
        return (b'<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message">'
                + b"<n>" * (depth - 1) + b"x" + b"</n>" * (depth - 1) + b"</message:AIXMBasicMessage>")
    with pytest.raises(ValueError) as at_bound:
        Aixm511Adapter().to_cdm(nested(AIXM511_MAX_DEPTH))
    assert not isinstance(at_bound.value, secure_xml.XmlRefused), "at the bound the document parses; the content refuses it"
    assert "carries message:hasMember" in str(at_bound.value)
    for depth in (AIXM511_MAX_DEPTH + 1, 1000):
        with pytest.raises(secure_xml.XmlRefused, match=f"{AIXM511_MAX_DEPTH + 1} deep against max_depth = {AIXM511_MAX_DEPTH}") as past:
            Aixm511Adapter().to_cdm(nested(depth))
        assert past.value.kind == "depth"
    deepest = max(secure_xml.tree_depth(ET.fromstring(p.read_bytes())) for p in POSITIVE)
    assert deepest * 8 <= AIXM511_MAX_DEPTH, deepest


def test_the_element_bound_refuses_a_document_one_element_past():
    body = (b'<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.1.1/message">'
            + b"<n/>" * AIXM511_MAX_ELEMENTS + b"</message:AIXMBasicMessage>")
    with pytest.raises(secure_xml.XmlRefused, match="elements") as past:
        Aixm511Adapter().to_cdm(body)
    assert past.value.kind == "elements"


def test_the_object_bound_admits_a_message_at_it_and_refuses_one_past():
    def with_slices(count):
        twin = copy.deepcopy(_twin(DELTAS))
        member = twin["message:hasMember"][0]
        base = member["aixm:timeSlice"][0]
        member["aixm:timeSlice"] = [{**copy.deepcopy(base), "@gml:id": f"TS_{i}", "aixm:sequenceNumber": str(i + 10)}
                                    for i in range(count)]
        return twin
    assert len(Aixm511Adapter().to_cdm(with_slices(AIXM511_MAX_OBJECTS))) == AIXM511_MAX_OBJECTS
    with pytest.raises(ObjectCountExceeded, match=f"more than {AIXM511_MAX_OBJECTS} time slices"):
        Aixm511Adapter().to_cdm(with_slices(AIXM511_MAX_OBJECTS + 1))


# ------------------------------------------------------------------------- determinism

def test_determinism_across_runs_hash_seeds_and_member_order():
    for path in XML_FILES:
        clock = lambda: _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)  # noqa: E731
        assert _dump(Aixm511Adapter(clock=clock).to_cdm(_xml(path))) == _dump(Aixm511Adapter(clock=clock).to_cdm(_xml(path)))
    script = (
        "import json, sys, pathlib, datetime\n"
        "from synapse_cdm.adapters.aixm511 import Aixm511Adapter\n"
        "from synapse_cdm import canonical\n"
        "clock = lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)\n"
        "out = [canonical.serialise([o.model_dump(mode='json') for o in Aixm511Adapter(clock=clock).to_cdm("
        "pathlib.Path(p).read_bytes())]) for p in sys.argv[1:]]\n"
        "print(json.dumps(out))\n")
    readings = []
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(PKG.parent)}
        result = subprocess.run([sys.executable, "-c", script, *map(str, XML_FILES)],
                                capture_output=True, text=True, env=env, check=True)
        readings.append(result.stdout)
    assert readings[0] == readings[1]
    twin = copy.deepcopy(_twin(AERODROME))
    members = twin["message:hasMember"]
    members[1], members[2] = members[2], members[1]
    original = _dump(Aixm511Adapter().to_cdm(_twin(AERODROME)))
    swapped = _dump(Aixm511Adapter().to_cdm(twin))
    assert [o["source_ids"][0]["external_id"] for o in swapped][1:3] == [DIRECTION, RUNWAY]
    assert [o["source"]["record_index"] for o in swapped] == [0, 1, 2, 3, 4]
    assert original[1]["entity_id"] == swapped[2]["entity_id"], "order moves the record index, never the identity"


# ---------------------------------------------------------------------- the independent reading

def test_the_adapter_agrees_with_the_independent_donlon_reading():
    """`independent/expected.json` is an ElementTree/XPath reading of the Donlon SOURCE files by
    `spec/build_fixtures.py`, never through the adapter; every feature and slice is compared."""
    expected = json.loads((INDEPENDENT / "expected.json").read_text())
    objects = Aixm511Adapter().to_cdm(_xml(INDEPENDENT / "donlon_extract.xml"))
    by_identifier: dict[str, list[Entity]] = {}
    for entity in _entities(objects):
        by_identifier.setdefault(entity.source_ids[0].external_id, []).append(entity)
    arc = json.loads((INDEPENDENT / "expected.json").read_text())["21a13c9f-a8ff-4fdd-9aaa-5dbfd91514b8"]
    assert "CircleByCenterPoint" in arc["slices"][0]["volume"]["segment_elements"]
    checked = 0
    for identifier, reading in expected.items():
        if identifier == "21a13c9f-a8ff-4fdd-9aaa-5dbfd91514b8":
            continue
        entities = by_identifier[identifier]
        assert len(entities) == len(reading["slices"]) and _block(entities[0]).feature.family == reading["family"]
        assert _block(entities[0]).feature.gml_id == reading["gml_id"]
        for entity, slice_reading in zip(entities, reading["slices"]):
            block = _block(entity)
            assert block.time_slice.gml_id == slice_reading["gml_id"]
            assert block.time_slice.interpretation == slice_reading["interpretation"]
            assert str(block.time_slice.sequence_number) == slice_reading["sequence_number"]
            assert block.time_slice.valid_time.begin.text == slice_reading["begin_position"]
            assert block.time_slice.valid_time.end.indeterminate == slice_reading["end_indeterminate"]
            for prop in ("designator", "type", "name"):
                state = block.properties.get(prop)
                assert (state.value if state is not None and state.state == "stated" else None) == slice_reading[prop], (identifier, prop)
            if "point" in slice_reading:
                lat_text, lon_text = slice_reading["point"]["pos"].split()
                assert slice_reading["point"]["srs_name"] == "urn:ogc:def:crs:EPSG::4326"
                assert (entity.position.lat, entity.position.lon) == (float(lat_text), float(lon_text)), identifier
                if slice_reading["point"]["elevation_uom"] in ("M", "FT"):
                    assert entity.position.vertical.value == float(slice_reading["point"]["elevation"])
                    assert entity.position.vertical.reference.value == "MSL"
                else:
                    assert entity.position.vertical is None
            if "volume" in slice_reading:
                volume = block.geometry_components[0].volume
                v = slice_reading["volume"]
                assert (volume.upper.limit.value, volume.upper.limit.uom) == (v["upper_limit"], v["upper_uom"])
                assert (volume.lower.limit.value, volume.lower.limit.uom) == (v["lower_limit"], v["lower_uom"])
                assert (volume.upper.reference.value, volume.lower.reference.value) == (v["upper_reference"], v["lower_reference"])
                if volume.horizontal_projection is not None:
                    assert volume.horizontal_projection.crs.srs_name == v["srs_name"]
                    positions = sum(s.count for c in volume.horizontal_projection.patches[0].exterior.curves for s in c.segments)
                    assert positions * 2 == v["pos_list_numbers"]
            assert [c.operation.value for c in block.geometry_components if not c.nil] == slice_reading["operations"]
            typed_refs = [r for group in block.references.values() for r in (group if isinstance(group, list) else [group])]
            typed_refs += [c.equipment for c in block.navaid_equipment if c.equipment is not None]
            typed_refs += [c.volume.contributor.airspace for c in block.geometry_components
                           if c.volume is not None and c.volume.contributor is not None and c.volume.contributor.airspace is not None]
            hrefs = [r.href for r in typed_refs if r.href is not None]
            assert set(hrefs) <= set(slice_reading["hrefs"]), "every typed href is one the source states"
            assert all(h.startswith("urn:uuid:") for h in hrefs)
            codes = [s.properties[next(iter(s.properties))].value for s in block.availability + block.activation if not s.nil]
            assert codes == slice_reading["status_codes"]
            assert sum(len(s.time_interval) for s in block.availability + block.activation) == slice_reading["timesheets"]
            assert len([p for p in block.parts if not p.nil]) == slice_reading["parts"]
            checked += 1
    assert checked == 12
    plans = _plans(objects)
    assert len(plans) == 1 and plans[0].label == "EAD21A"
    assert _entities(objects, "d1806917-9ca1-4213-83b5-9fac67e4f508")[0].attributes["aixm"]["volume_projection"].startswith("none")


# ------------------------------------------------------------------------------- negatives

def test_negative_a_swapped_axis_order_is_caught_by_the_position_and_polygon_checks(monkeypatch):
    """An implementation that read EPSG:4326 longitude-first would put every point in the wrong
    place; the fixture's stated numbers, not the adapter's own output, are the oracle."""
    monkeypatch.setitem(codec.CRS_AXIS_ORDER, "urn:ogc:def:crs:EPSG::4326", ("longitude", "latitude"))
    airport = _entities(Aixm511Adapter().to_cdm(_xml(AERODROME)), AIRPORT)[0]
    assert (airport.position.lat, airport.position.lon) != (52.30833, 4.76389), "the swap is visible against the fixture"
    with pytest.raises(AssertionError):
        assert (airport.position.lat, airport.position.lon) == (52.30833, 4.76389)
    plan = _plans(Aixm511Adapter().to_cdm(_xml(CASES / "axis_order_epsg4326.xml")))
    assert not plan or plan[0].geometry.coordinates[0][0] != [5.2, 52.1]


def test_negative_a_dropped_vertical_reference_is_caught_by_the_member_for_member_check(monkeypatch):
    """An implementation that lost the SFC reference would either project the limit against
    nothing or against the wrong datum; both disagree with the fixture's stated reference."""
    monkeypatch.delitem(codec.REFERENCE_TO_DATUM, "SFC")
    objects = Aixm511Adapter().to_cdm(_xml(CASES / "vertical_references.xml"))
    by_designator = {p.label: p for p in _plans(objects)}
    assert _upper(by_designator["VFTSFC"]) != (1000.0, "ft", "AGL")
    block = {_block(e).properties["designator"].value: _block(e) for e in _entities(objects)}["VFTSFC"]
    assert block.geometry_components[0].volume.upper.reference.value == "SFC", "the source still says SFC"
    assert block.geometry_components[0].volume.upper.cdm is None, "and nothing was projected in its place"
    monkeypatch.setitem(codec.REFERENCE_TO_DATUM, "SFC", "MSL")
    wrong = {p.label: p for p in _plans(Aixm511Adapter().to_cdm(_xml(CASES / "vertical_references.xml")))}
    assert _upper(wrong["VFTSFC"]) == (1000.0, "ft", "MSL") != (1000.0, "ft", "AGL"), "a wrong datum is a different value"


def test_negative_a_wrong_interpretation_mapping_is_caught_by_the_ledger_and_the_states(monkeypatch):
    """An implementation that read every slice as BASELINE would type a delta's nil property as
    NIL rather than WITHDRAWN and its absent ones as NOT STATED; the ledger's identity rule on
    `aixm:interpretation` catches the value, the state test catches the meaning."""
    original = module._SliceReader._interpretation

    def wrong(self):
        original(self)
        return "BASELINE"

    monkeypatch.setattr(module._SliceReader, "_interpretation", wrong)
    twin = _twin(DELTAS)
    objects = Aixm511Adapter().to_cdm(twin)
    ledger = _ledger(twin, objects)
    lost = [e for e in ledger.lost if e.source_path.endswith("aixm:interpretation")]
    assert len(lost) == 3 and all(e.loss in ("VALUE_MISMATCH", "TRANSFORM_MISMATCH") for e in lost)
    pd = _entities(objects)[2]
    assert _block(pd).properties["localType"].meaning == "nil" != "withdrawn"
    assert _block(pd).properties["type"].meaning == "not stated" != "unchanged"


def test_the_public_surface_is_declared_and_the_codec_is_pure():
    assert set(module.__all__) >= {"Aixm511Adapter", "AsOf", "ObjectCountExceeded", "TimeSliceBlock", "ReferenceTarget"}
    assert all(hasattr(codec, name) for name in codec.__all__)
    assert ReferenceTarget(element="aixm:Runway", where="table").where == "table"
    objects = OBJECTS.validate_python(_dump(Aixm511Adapter().to_cdm(_xml(AERODROME))))
    assert len(objects) == 5
