"""Adapter #18 — C2SIM (SISO-STD-019-2020 v1.0, C2SIMArtifacts v1.0.1 schema), bidirectional,
`residual: structured`, the first adapter whose objects sit under a nested repeatable container.

One test per claim in `adapters/c2sim.py`'s docstring, plus master prompt §6's list — wrong
namespace/version, missing header fields, unresolved entity references, duplicate ids, repeated
and out-of-order reports, unsupported task codes, missing locations, malformed timestamps,
simulation-time conversion, extension fields, oversized XML — the §9 cross-cutting list, the
normative validation of every emitted document (BLOCKED, never PASS, without the resource), fresh
egress from records this adapter never produced, the semantic round trip, and three NEGATIVE
tests that prove the ledger and the typed contract catch a wrong mapping rather than blessing what
the implementation emits: a swapped reporter/subject, a dropped task time constraint and a wrong
namespace string are each fed in as if an adapter had produced them, and each reads LOST or is
refused.

The parsed twins are held to an independent ElementTree reading of the XML beside each
(`test_every_parsed_twin_corresponds_to_its_raw_fixture`), so the codec's own parse is never the
only oracle for what a twin contains.
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
from synapse_cdm import harness, ids, lossless, secure_xml
from synapse_cdm.adapter import InputTooLarge
from synapse_cdm.adapters import c2sim as module
from synapse_cdm.adapters import c2sim_codec as codec
from synapse_cdm.adapters.c2sim import (
    C2SIM_MAX_DEPTH,
    C2SIM_MAX_ELEMENTS,
    C2SIM_MAX_INPUT_BYTES,
    C2SIM_MAX_OBJECTS,
    C2simAdapter,
    EgressRefused,
    Envelope,
    ExerciseClock,
    ObjectCountExceeded,
)
from synapse_cdm.enums import Affiliation, EntityType, EventType, ObjectType, PositionSource
from synapse_cdm.manifest import Residual
from synapse_cdm.models import CDMObject, Entity, Event, PlanObject
from tests import normative_support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "c2sim"
MALFORMED = FIXTURES / "malformed"
CASES = FIXTURES / "cases"
EGRESS = FIXTURES / "egress"
SPEC = FIXTURES / "spec" / "c2sim_pin.json"
XML_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".xml")
TWIN_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".json")
EGRESS_FILES = sorted(harness.select_fixtures(EGRESS))
INIT = FIXTURES / "initialisation_three_sides.xml"
MOVE = FIXTURES / "order_move_to_location.xml"
HOLD = FIXTURES / "order_hold_in_place.xml"
POSITION = FIXTURES / "report_position_two_subjects.xml"
STATUS = FIXTURES / "report_status_observations.xml"

BLUE = "c2510000-0001-8000-8000-000000000001"
RED = "c2510000-0001-8000-8000-000000000002"
GREEN = "c2510000-0001-8000-8000-000000000003"
HQ = "c2510000-0002-8000-8000-000000000001"
A_COY = "c2510000-0002-8000-8000-000000000002"
B_COY = "c2510000-0002-8000-8000-000000000003"
RED_1 = "c2510000-0002-8000-8000-000000000004"
UAV = "c2510000-0003-8000-8000-000000000001"
APC = "c2510000-0003-8000-8000-000000000002"
ROUTE_ALPHA = "c2510000-0006-8000-8000-000000000001"
WITH_ROUTE = CASES / "initialisation_with_route.xml"
ORDER_WITH_ROUTE = CASES / "order_with_route.xml"
CLOCK = ExerciseClock(epoch="2026-09-21T06:00:00Z", rate=1.0,
                      basis="ScenarioSetting/DateTime of initialisation message a001 (test)")
ENVELOPE = Envelope(message_id="c2510000-0010-8000-8000-00000000a100",
                    conversation_id="c2510000-0010-8000-8000-00000000c100",
                    from_sending_system="EXERCISE-PLANNER", to_receiving_system="ALL",
                    communicative_act="Request", sending_time="2026-09-22T05:59:00Z",
                    system_entities=(("EXERCISE-SIM-BLUE", ("c2510000-0012-8000-8000-000000000001",
                                                            "c2510000-0013-8000-8000-000000000001")),))
OBJECTS = TypeAdapter(list[CDMObject])


def _xml(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def _twin(path: pathlib.Path) -> dict:
    return json.loads((path.parent / (path.stem + ".parsed.json")).read_text())


def _dump(objects):
    return [o if isinstance(o, dict) else o.model_dump(mode="json") for o in objects]


def _ledger(raw, objects):
    return lossless.ledger(raw, _dump(objects), C2simAdapter.MAPPINGS)


def _by_uuid(objects, uuid):
    return next(o for o in objects if o.source_ids[0].external_id == uuid)


def _block(obj):
    if isinstance(obj, Entity):
        return codec.ObjectBlock.model_validate(obj.attributes["c2sim"])
    if isinstance(obj, PlanObject):
        return codec.ObjectBlock.model_validate(obj.route.metadata["c2sim"])
    raise AssertionError(obj)


def _mutate(path: pathlib.Path, old: str, new: str, count: int = 1) -> bytes:
    text = path.read_text()
    assert text.count(old) >= count, (old, text.count(old))
    return text.replace(old, new, count).encode()


# ----------------------------------------------------------------- the fixtures themselves

def test_the_fixture_set_is_the_one_the_record_describes():
    spec = json.loads(SPEC.read_text())
    assert spec["adapter"]["name"] == "c2sim" and spec["adapter"]["ordinal"] == 18
    assert spec["standard"]["carried_here"] is False
    recorded = {row["file"]: row for row in spec["fixtures"]}
    assert set(recorded) == {p.name for p in XML_FILES} | {p.name for p in TWIN_FILES}
    for row in spec["fixtures"] + spec["malformed"]["files"] + spec["cases"]["files"] + spec["egress"]["files"]:
        path = FIXTURES / row["file"]
        octets = path.read_bytes()
        assert len(octets) == row["bytes"], row["file"]
        import hashlib
        assert hashlib.sha256(octets).hexdigest() == row["sha256"], row["file"]
    assert len(XML_FILES) == 5 and len(TWIN_FILES) == 5


def test_every_fixture_is_synthetic_by_default_and_names_no_real_unit():
    for path in XML_FILES + sorted(CASES.glob("*.xml")):
        text = path.read_text()
        assert "SYNTHETIC" in text, path.name
        objects = C2simAdapter(exercise=CLOCK).to_cdm(path.read_bytes())
        assert all(o.source.synthetic for o in objects), path.name
        for name in {n for o in objects for n in _names_of(o)}:
            assert name.startswith("EXERCISE") or name.startswith("EX-"), (path.name, name)


def _names_of(obj) -> list[str]:
    block = obj.attributes.get("c2sim") if isinstance(obj, Entity) else None
    if not block:
        return []
    return [n for n in [block.get("name"), block.get("marking")] + block.get("names", []) if n]


def test_every_parsed_twin_corresponds_to_its_raw_fixture():
    """The twin re-derived from the XML with the standard library ALONE — no codec table, the
    schema's repeatable children spelled here by hand — equals the committed twin."""
    repeatable = {"Name": {"ForceSide"}, "ObjectDefinitions": {"C2SIMInitializationBody"},
                  "SystemEntityList": {"C2SIMInitializationBody"}, "AbstractObject": {"ObjectDefinitions"},
                  "Entity": {"ObjectDefinitions", "OrderBody"}, "ActorReference": {"SystemEntityList"},
                  "ForceSideRelation": {"ForceSide"}, "CurrentTask": {"Unit"}, "AffiliatedWith": {"EntityDescriptor"},
                  "AllegianceRelationship": {"EntityDescriptor"}, "CommunicationsNetwork": {"EntityDescriptor"},
                  "Resource": {"Unit"}, "EntityType": {"Unit", "Aircraft", "Vehicle", "SurfaceVessel", "Route", "Resource"},
                  "Subordinate": {"Unit"}, "CommandRelation": {"Unit"}, "EntityHealthStatus": {"PhysicalState", "PositionReportContent", "HealthObservation"},
                  "Location": {"PhysicalState", "ManeuverWarfareTask"}, "ReportContent": {"ReportBody"},
                  "Observation": {"ObservationReportContent"}, "Task": {"OrderBody"}, "TaskReference": {"OrderBody"},
                  "ActionTemporalRelationship": {"ManeuverWarfareTask"}, "MapGraphicID": {"ManeuverWarfareTask"},
                  "AffectedEntity": {"ManeuverWarfareTask"}, "DesiredEffectCode": {"ManeuverWarfareTask"},
                  "RuleOfEngagement": {"ManeuverWarfareTask"}, "TaskFunctionalRelation": {"ManeuverWarfareTask"}}
    ns = "{http://www.sisostds.org/schemas/C2SIM/1.1}"

    def node(element, parent_local):
        out = {}
        for child in element:
            local = child.tag[len(ns):]
            value = node(child, local)
            if parent_local in repeatable.get(local, ()):
                out.setdefault(local, []).append(value)
            else:
                assert local not in out, (parent_local, local)
                out[local] = value
        text = (element.text or "").strip()
        return out if out else text

    for path in XML_FILES:
        root = ET.fromstring(path.read_bytes())
        assert root.tag == ns + "Message" and not root.attrib
        assert node(root, "Message") == _twin(path), path.name


@pytest.mark.parametrize("path", XML_FILES, ids=lambda p: p.stem)
def test_the_xml_and_its_twin_translate_to_the_same_objects(path):
    a = _dump(C2simAdapter().to_cdm(_xml(path)))
    b = _dump(C2simAdapter().to_cdm(_twin(path)))
    for x, y in zip(a, b):
        x["source"].pop("transformations"), y["source"].pop("transformations")
        x.pop("received_at", None), y.pop("received_at", None)
    assert a == b


@pytest.mark.normative
@pytest.mark.parametrize("path", XML_FILES, ids=lambda p: p.stem)
def test_every_harness_fixture_validates_against_the_pinned_schema(path):
    verdict = normative_support.verdict("c2sim", path.read_bytes())
    assert verdict.outcome is verdict.outcome.VALID, verdict.describe()


@pytest.mark.normative
def test_the_embedded_content_model_is_the_pinned_schemas():
    """`c2sim_codec.CONTENT` re-derived from the pinned XSD: every complex global element, its
    children in sequence order, repeatability from the particle. Data, not prose."""
    resource = normative_support.resource("c2sim")
    xsd = pathlib.Path(resource.entry) if hasattr(resource, "entry") else None
    if xsd is None or not xsd.is_file():
        directory = pathlib.Path(os.environ["SYNAPSE_CDM_C2SIM_XSD_DIR"])
        xsd = directory / "C2SIM_SMX_LOX.xsd"
    XS = "{http://www.w3.org/2001/XMLSchema}"
    root = ET.parse(xsd).getroot()
    types = {e.get("name"): e for e in root if e.tag in (XS + "complexType", XS + "simpleType", XS + "group")}
    elements = {e.get("name"): e for e in root if e.tag == XS + "element"}

    def children(node, many=False):
        out = []
        for ch in node:
            tag = ch.tag.replace(XS, "")
            unbounded = many or ch.get("maxOccurs", "1") == "unbounded"
            if tag == "element":
                out.append((ch.get("ref") or ch.get("name"), unbounded))
            elif tag in ("sequence", "choice", "all"):
                out += children(ch, unbounded)
            elif tag == "group":
                out += children(types[ch.get("ref")], unbounded)
            elif tag in ("complexContent", "simpleContent", "extension", "restriction"):
                out += children(ch, many)
        return out

    derived = {name: tuple(children(types[e.get("type")])) for name, e in elements.items()
               if e.get("type") in types and types[e.get("type")].tag == XS + "complexType"}
    assert derived == codec.CONTENT
    for code, values in codec.ENUMERATIONS.items():
        stated = tuple(x.get("value") for x in types[code + "Type"].iter(XS + "enumeration"))
        assert stated == values, code
    task_codes = [x.get("value") for x in types["TaskActionCodeType"].iter(XS + "enumeration")]
    assert set(codec.SUPPORTED_TASK_ACTIONS) <= set(task_codes)
    assert "ATTACK" in task_codes, "the refused code in malformed/unsupported_task_code.xml is one the schema admits"


# ------------------------------------------------------------------- initialisation

def test_an_initialisation_becomes_sides_units_platforms_and_a_route():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    kinds = [(type(o).__name__, _block(o).object_class) for o in objects]
    assert kinds == [("Entity", "ForceSide")] * 3 + [("Entity", "Unit")] * 5 + [
        ("Entity", "Aircraft"), ("Entity", "Vehicle"), ("Entity", "SurfaceVessel")]
    assert [o.entity_type for o in objects] == [EntityType.UNIT] * 8 + [EntityType.PLATFORM] * 3
    assert [o.source.record_index for o in objects] == list(range(11))
    with_route = C2simAdapter().to_cdm(WITH_ROUTE.read_bytes())
    assert [(type(o).__name__, _block(o).object_class) for o in with_route] == [
        ("Entity", "ForceSide"), ("Entity", "Unit"), ("PlanObject", "Route")]
    assert all(o.source.original_id == "c2510000-0000-8000-8000-00000000a001" for o in objects)
    assert all(o.source.observed_at.isoformat() == "2026-09-21T05:58:30+00:00" for o in objects)
    assert all(o.residual is not None and o.residual.namespace == "C2SIM" for o in objects)
    assert C2simAdapter.metadata.residual is Residual.STRUCTURED


def test_identity_is_derived_from_the_c2sim_uuid_and_the_side_and_unit_spaces_do_not_collide():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    hq = _by_uuid(objects, HQ)
    assert hq.entity_id == ids.derive("C2SIM", HQ, kind="object")
    assert [s.model_dump() for s in hq.source_ids] == [{"system": "C2SIM", "external_id": HQ}]
    route = _by_uuid(C2simAdapter().to_cdm(WITH_ROUTE.read_bytes()), ROUTE_ALPHA)
    assert route.object_id == ids.derive("C2SIM", ROUTE_ALPHA, kind="object")
    assert len({str(o.entity_id if isinstance(o, Entity) else o.object_id) for o in objects}) == 11


def test_identity_is_stable_across_updates_of_mutable_properties():
    moved = _mutate(INIT, "<Latitude>58.5125</Latitude>\n                          <Longitude>24.7100</Longitude>",
                    "<Latitude>58.6000</Latitude>\n                          <Longitude>24.9000</Longitude>")
    renamed = _mutate(INIT, "EXERCISE-BLUE-A-COY", "EXERCISE-BLUE-A-COY-RENAMED")
    before = _by_uuid(C2simAdapter().to_cdm(_xml(INIT)), A_COY)
    for variant in (moved, renamed):
        after = _by_uuid(C2simAdapter().to_cdm(variant), A_COY)
        assert after.entity_id == before.entity_id


def test_organisational_relationships_are_typed_with_their_endpoints():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    hq, a_coy, b_coy = (_block(_by_uuid(objects, u)) for u in (HQ, A_COY, B_COY))
    assert hq.organisation.side == BLUE and hq.organisation.superior is None
    assert hq.organisation.subordinates == [A_COY, B_COY]
    assert hq.organisation.echelon == "BN"
    assert hq.organisation.communications_networks == ["c2510000-0005-8000-8000-000000000001"]
    assert a_coy.organisation.superior == HQ
    assert a_coy.organisation.command_relations == [codec.CommandRelation(actor=HQ, code="OPCON")]
    assert b_coy.organisation.affiliated_with == [A_COY]
    assert b_coy.organisation.allegiance_relationships == [
        codec.Allegiance(actor="c2510000-0002-8000-8000-000000000005", code="NeutralTo", in_pinned_enumeration=True)]
    assert b_coy.organisation.current_tasks == ["c2510000-0004-8000-8000-000000000001"]
    blue = _block(_by_uuid(objects, BLUE))
    assert blue.names == ["EXERCISE-BLUE", "EXERCISE-BLUE-COALITION"]
    assert [(r.other_side, r.hostility) for r in blue.organisation.force_side_relations] == [(RED, "HO"), (GREEN, "NEUTRL")]
    red = _block(_by_uuid(objects, RED))
    assert [(r.hostility, r.in_pinned_enumeration) for r in red.organisation.force_side_relations] == [("HO", True), ("SUSPCT", True)]


def test_classifications_are_source_vocabulary_and_never_a_cdm_symbol():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    red_1 = _by_uuid(objects, RED_1)
    assert red_1.symbol is None
    assert [c.form for c in _block(red_1).classifications] == ["APP6-SIDC", "DISEntityType"]
    assert _block(red_1).classifications[0].sidc == "SHGPUCI--------"
    assert _block(red_1).classifications[1].dis == {"DISCategory": "1", "DISCountry": "0", "DISDomain": "1",
                                                     "DISExtra": "0", "DISKind": "1", "DISSpecific": "0",
                                                     "DISSubCategory": "1"}
    assert _block(_by_uuid(objects, UAV)).classifications == [codec.Classification(form="NamedEntityType", name="EXERCISE-UAS-CLASS-I")]
    assert _block(_by_uuid(objects, UAV)).marking == "EX-UAV-1"


def test_positions_keep_zero_values_and_msl_agl_heights_unconverted():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    hq = _by_uuid(objects, HQ)
    assert (hq.position.lat, hq.position.lon) == (58.5125, 24.625)
    assert hq.position.alt_m is None and hq.position.vertical.value == 42.5
    assert hq.position.vertical.reference.value == "MSL" and hq.position.vertical.unit.value == "m"
    assert hq.position.position_source is PositionSource.ESTIMATED
    assert hq.kinematics.speed_mps == 0.0 and hq.kinematics.course_deg == 0.0, "zero is a real value"
    a_coy = _by_uuid(objects, A_COY)
    assert a_coy.position.vertical.reference.value == "AGL" and a_coy.position.vertical.value == 2.0
    assert a_coy.kinematics.speed_mps == 4.2 and a_coy.kinematics.course_deg == 270.5
    b_coy = _by_uuid(objects, B_COY)
    assert b_coy.position.vertical is None and b_coy.kinematics is None
    assert [loc.latitude for loc in _block(b_coy).state.locations] == [58.49, 58.495], "every location typed"
    assert (b_coy.position.lat, b_coy.position.lon) == (58.49, 24.71), "the first is the position"
    green = _by_uuid(objects, "c2510000-0002-8000-8000-000000000005")
    assert green.position is None and _block(green).state is None, "no state, no position, never 0, 0"
    boat = _by_uuid(objects, "c2510000-0003-8000-8000-000000000003")
    assert boat.position.vertical.value == 0.0, "a zero MSL height is a real height"


def test_repeated_identical_values_cannot_conceal_a_value_on_the_wrong_object():
    """Two units share latitude 58.5125 and two share strength 95; the typed block holds each
    to its own object, and the ledger's `entity` target reads each leaf on SOME entity — so the
    path-specific assertion here is what tells the two apart."""
    objects = C2simAdapter().to_cdm(_xml(INIT))
    hq, a_coy = _by_uuid(objects, HQ), _by_uuid(objects, A_COY)
    assert hq.position.lat == a_coy.position.lat == 58.5125
    assert (hq.position.lon, a_coy.position.lon) == (24.625, 24.71)
    assert [h.strength_percentage for h in _block(hq).state.health if h.form == "Strength"] == [95.0]
    assert [h.code for h in _block(hq).state.health if h.form == "OperationalStatus"] == ["FullyOperational"]
    assert [h.form for h in _block(a_coy).state.health] == ["Strength"]


def test_affiliation_is_a_viewpoint_read_from_the_own_sides_stated_relations():
    unknown = C2simAdapter().to_cdm(_xml(INIT))
    assert {o.affiliation for o in unknown if isinstance(o, Entity)} == {Affiliation.UNKNOWN}
    assert "no own side" in _block(unknown[0]).affiliation_basis
    blue = C2simAdapter(own_side=BLUE).to_cdm(_xml(INIT))
    by = {o.source_ids[0].external_id: o.affiliation for o in blue if isinstance(o, Entity)}
    assert by[BLUE] is Affiliation.FRIENDLY and by[HQ] is Affiliation.FRIENDLY and by[UAV] is Affiliation.FRIENDLY
    assert by[RED] is Affiliation.HOSTILE and by[RED_1] is Affiliation.HOSTILE
    assert by[GREEN] is Affiliation.NEUTRAL
    red = C2simAdapter(own_side=RED).to_cdm(_xml(INIT))
    by = {o.source_ids[0].external_id: o for o in red if isinstance(o, Entity)}
    assert by[BLUE].affiliation is Affiliation.HOSTILE
    assert by[GREEN].affiliation is Affiliation.UNKNOWN, "SUSPCT is a judgement, not a fact this axis carries"
    assert "SUSPCT" in _block(by[GREEN]).affiliation_basis
    stranger = C2simAdapter(own_side="c2510000-0001-8000-8000-0000000000ee").to_cdm(_xml(INIT))
    assert {o.affiliation for o in stranger if isinstance(o, Entity)} == {Affiliation.UNKNOWN}


def test_a_route_map_graphic_is_a_route_plan_object_with_its_block_in_the_metadata():
    objects = C2simAdapter().to_cdm(WITH_ROUTE.read_bytes())
    route = _by_uuid(objects, ROUTE_ALPHA)
    assert isinstance(route, PlanObject) and route.object_type is ObjectType.ROUTE
    assert route.label == "EXERCISE-ROUTE-ALPHA"
    assert route.geometry.coordinates == [[24.71, 58.5125], [24.76, 58.53], [24.81, 58.55]]
    assert [w.sequence for w in route.route.waypoints] == [0, 1, 2]
    assert route.route.waypoints[1].position.vertical.value == 55.0
    assert route.route.waypoints[0].position.vertical is None
    assert route.validity.observed_at.isoformat() == "2026-09-21T06:00:00+00:00"
    block = _block(route)
    assert block.object_class == "Route" and block.owner == HQ
    assert block.classifications[0].sidc == "GFGPGLC--------"
    assert block.message.message_id == "c2510000-0000-8000-8000-00000000a007"
    twin = codec.twin_of(ET.fromstring(WITH_ROUTE.read_bytes()))
    assert _ledger(twin, objects).lost == (), "the route's every leaf is bound"
    assert "Entity" not in route.residual.data, "every leaf of the route became typed (the MSL height on the waypoint's vertical)"
    assert set(route.residual.data) == {"C2SIMHeader", "MessageBody"}
    emitted = C2simAdapter().from_cdm(objects)
    assert [type(o) for o in C2simAdapter().to_cdm(emitted)] == [Entity, Entity, PlanObject]
    order_objects = C2simAdapter().to_cdm(ORDER_WITH_ROUTE.read_bytes())
    assert isinstance(order_objects[1], PlanObject) and order_objects[1].label == "EXERCISE-ROUTE-BRAVO"
    assert _ledger(codec.twin_of(ET.fromstring(ORDER_WITH_ROUTE.read_bytes())), order_objects).lost == ()


def test_valid_from_is_the_states_instant_or_the_scenario_start_and_never_the_clock():
    clock = lambda: _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc)  # noqa: E731
    objects = C2simAdapter(clock=clock).to_cdm(_xml(INIT))
    hq, b_coy = _by_uuid(objects, HQ), _by_uuid(objects, B_COY)
    assert hq.valid_from.isoformat() == "2026-09-21T06:00:00+00:00"
    assert any(t.startswith("valid_from: CurrentState") for t in hq.source.transformations)
    assert b_coy.valid_from.isoformat() == "2026-09-21T06:00:00+00:00"
    assert any("ScenarioSetting/DateTime" in t for t in b_coy.source.transformations)
    assert _block(hq).scenario.version == "EXERCISE-2026-09-21-v1"
    assert all(o.valid_from.year == 2026 for o in objects if isinstance(o, Entity))


def test_the_residual_is_the_source_structure_minus_what_was_typed():
    objects = C2simAdapter().to_cdm(_xml(INIT))
    hq = _by_uuid(objects, HQ)
    own = hq.residual.data["Entity"]["ActorEntity"]["CollectiveEntity"]["MilitaryOrganization"]["Unit"]
    assert list(own) == ["Resource"], "everything else became typed"
    assert own["Resource"][0]["Quantity"] == "1200"
    assert set(hq.residual.data) == {"C2SIMHeader", "MessageBody", "Entity"}
    body = hq.residual.data["MessageBody"]["C2SIMInitializationBody"]
    assert set(body) == {"ScenarioSetting", "SystemEntityList"}
    assert len(body["SystemEntityList"]) == 2
    assert "Entity" not in _by_uuid(objects, A_COY).residual.data, "a fully typed element leaves nothing"
    assert "unknown" not in hq.residual.data


def test_the_ledger_binds_every_leaf_of_every_fixture_with_no_loss():
    for path in XML_FILES:
        book = _ledger(_twin(path), C2simAdapter().to_cdm(_twin(path)))
        assert book.lost == (), (path.name, [e.line() for e in book.lost][:5])
        categories = {e.category for e in book.entries}
        assert "MAPPED" in categories and "RESIDUAL" in categories, path.name


def test_the_typed_blocks_validate_against_their_contracts():
    for path in XML_FILES:
        for obj in C2simAdapter().to_cdm(_xml(path)):
            if isinstance(obj, Event):
                payload = obj.payload["c2sim"]
                if payload["contract"] == codec.ORDER_CONTRACT:
                    codec.OrderPayload.model_validate(payload)
                else:
                    codec.ReportPayload.model_validate(payload)
                assert payload["message"]["message_id"] == obj.source.original_id
            else:
                assert _block(obj).contract == codec.OBJECT_CONTRACT
                assert _block(obj).message.protocol_matches_pin is True


# ---------------------------------------------------------------------------- reports

def test_a_position_report_is_an_event_per_content_with_the_reports_identity_and_the_subjects():
    events = C2simAdapter().to_cdm(_xml(POSITION))
    assert [e.event_type for e in events] == [EventType.TRACK_UPDATE] * 2
    report = "c2510000-0009-8000-8000-000000000001"
    assert [e.source_ids[0].external_id for e in events] == [report + "#0", report + "#1"]
    assert events[0].event_id == ids.derive("C2SIM", report + "#0", kind="report")
    assert events[0].related_entities == [ids.derive("C2SIM", A_COY, kind="object")]
    assert events[1].related_entities == [ids.derive("C2SIM", APC, kind="object")]
    assert events[0].event_id != events[1].event_id
    first, second = (codec.ReportPayload.model_validate(e.payload["c2sim"]) for e in events)
    assert (first.reporting_entity, first.subject_entity) == (A_COY, A_COY)
    assert (second.reporting_entity, second.subject_entity) == (A_COY, APC)
    assert (first.content_index, first.content_count, second.content_index) == (0, 2, 1)
    assert events[0].geometry.coordinates == [24.74, 58.521] and events[1].geometry.coordinates == [24.74, 58.514]
    assert first.location.altitude_msl_m == 48.0 and second.location.altitude_agl_m == 0.0
    assert [h.form for h in first.health] == ["OperationalStatus", "Strength"] and second.health == []
    assert first.duration == "P00Y00M00DT00H00M30S" and first.duration_seconds == 30
    assert events[0].observed_at.isoformat() == "2026-09-21T06:40:00+00:00"
    assert first.time_of_observation.form == "DateTime" and first.time_of_observation.resolution == "stated"


def test_a_second_report_about_the_same_unit_is_a_second_event_about_the_same_entity():
    events = C2simAdapter(exercise=CLOCK).to_cdm((CASES / "reports_out_of_order.xml").read_bytes())
    assert len({e.event_id for e in events}) == 3
    assert len({e.related_entities[0] for e in events}) == 1
    assert [e.observed_at.strftime("%H:%M") for e in events] == ["06:50", "06:40", "06:45"], "order as sent, not sorted"
    again = C2simAdapter(exercise=CLOCK).to_cdm((CASES / "reports_out_of_order.xml").read_bytes())
    assert [e.event_id for e in again] == [e.event_id for e in events], "a repeated report is the same report"
    assert all(e.related_entities[0] == _by_uuid(C2simAdapter().to_cdm(_xml(INIT)), A_COY).entity_id for e in events)


def test_status_vocabulary_is_verbatim_and_an_unknown_code_is_preserved_as_unknown():
    events = C2simAdapter().to_cdm(_xml(STATUS))
    assert [e.event_type for e in events] == [EventType.STATUS_CHANGE] * 2
    observation, task = (codec.ReportPayload.model_validate(e.payload["c2sim"]) for e in events)
    forms = [(o.form, o.typed) for o in observation.observations]
    assert forms == [("HealthObservation", True), ("LocationObservation", True), ("NameObservation", True),
                     ("ActivityObservation", False)]
    health = observation.observations[0]
    assert health.actor_reference == RED_1 and health.confidence_level == 0.75
    assert [(h.code, h.in_pinned_enumeration) for h in health.health if h.form == "OperationalStatus"] == [("PartlyOperational", True)]
    location = observation.observations[1]
    assert (location.location.latitude, location.speed_mps, location.heading_deg, location.uncertainty_interval) == (58.61, 3.5, 225.0, 150.0)
    name = observation.observations[2]
    assert (name.name, name.marking, name.hostility_status, name.hostility_in_pinned_enumeration, name.side) == (
        "EXERCISE-RED-1", "EX-RED-1", "HO", True, RED)
    assert observation.observations[3].raw == {"ActivityObservation": {"ActorReference": RED_1, "ConfidenceLevel": "0.5",
                                                                        "ActionCode": {"TaskActionCode": "Observe"}}}
    assert observation.time_of_observation.name == "EXERCISE-OBSERVED"
    assert (task.current_task, task.task_status_code, task.task_status_in_pinned_enumeration) == (
        "c2510000-0004-8000-8000-000000000002", "TASKINPRG", True)
    unknown = C2simAdapter().to_cdm((CASES / "report_unknown_status_code.xml").read_bytes())
    payloads = [codec.ReportPayload.model_validate(e.payload["c2sim"]) for e in unknown]
    assert payloads[0].observations[0].health[0].code == "Degraded"
    assert payloads[0].observations[0].health[0].in_pinned_enumeration is False
    assert (payloads[1].task_status_code, payloads[1].task_status_in_pinned_enumeration) == ("TASKHOLD", False)
    problems = C2simAdapter().validate_source((CASES / "report_unknown_status_code.xml").read_bytes())
    assert any("Degraded" not in p and "outside its pinned enumeration" in p for p in problems)
    assert len([p for p in problems if "outside its pinned enumeration" in p]) == 2


def test_simulation_time_resolves_only_against_a_caller_supplied_epoch():
    document = (CASES / "report_position_simulation_time.xml").read_bytes()
    with pytest.raises(ValueError, match="SimulationTime that this adapter cannot resolve"):
        C2simAdapter().to_cdm(document)
    events = C2simAdapter(exercise=CLOCK).to_cdm(document)
    assert events[0].observed_at.isoformat() == "2026-09-21T06:40:00+00:00"
    instant = codec.ReportPayload.model_validate(events[0].payload["c2sim"]).time_of_observation
    assert (instant.form, instant.elapsed, instant.elapsed_seconds) == ("SimulationTime", "P00Y00M00DT00H40M00S", 2400)
    assert instant.resolved == "2026-09-21T06:40:00.000Z" and instant.resolution.startswith("epoch+elapsed: 2400 s after")
    assert events[0].payload["c2sim"]["exercise_clock"] == {"epoch": "2026-09-21T06:00:00.000Z", "rate": 1.0, "basis": CLOCK.basis}
    fast = ExerciseClock(epoch="2026-09-21T06:00:00Z", rate=4.0, basis="the same epoch at four times wall clock")
    assert C2simAdapter(exercise=fast).to_cdm(document)[0].observed_at == events[0].observed_at, \
        "rate is recorded and enters no conversion: a SimulationTime is scenario seconds"
    assert C2simAdapter(exercise=fast).to_cdm(document)[0].payload["c2sim"]["exercise_clock"]["rate"] == 4.0
    with pytest.raises(ValueError, match="RelativeTime that this adapter cannot resolve"):
        C2simAdapter(exercise=CLOCK).to_cdm((MALFORMED / "relative_time_observation.xml").read_bytes())


def test_message_time_simulation_time_and_the_epoch_are_three_separate_typed_values():
    events = C2simAdapter(exercise=CLOCK).to_cdm((CASES / "report_position_simulation_time.xml").read_bytes())
    event = events[0]
    assert event.source.observed_at.isoformat() == "2026-09-21T06:40:05+00:00", "SendingTime: the message's own time"
    assert event.observed_at.isoformat() == "2026-09-21T06:40:00+00:00", "the scenario instant"
    assert event.payload["c2sim"]["exercise_clock"]["epoch"] == "2026-09-21T06:00:00.000Z"
    assert event.payload["c2sim"]["message"]["sending_time"] == "2026-09-21T06:40:05Z"
    assert event.received_at != event.observed_at


# ------------------------------------------------------------------------------ orders

def test_a_move_order_is_a_plan_inject_event_with_typed_tasks_and_its_route():
    event, = C2simAdapter().to_cdm(_xml(MOVE))
    assert isinstance(event, Event) and event.event_type is EventType.PLAN_INJECT
    order = codec.OrderPayload.model_validate(event.payload["c2sim"])
    assert order.order_id == "c2510000-0007-8000-8000-000000000001"
    assert event.event_id == ids.derive("C2SIM", order.order_id, kind="order")
    assert (order.from_sender, order.to_receiver, order.requesting_entity) == (HQ, A_COY, HQ)
    assert event.observed_at.isoformat() == "2026-09-21T06:05:00+00:00"
    task, = order.tasks
    assert task.action_code == "MoveToLocation" and task.performing_entity == A_COY
    assert task.affected_entities == [B_COY] and task.desired_effects == ["TaskSuccess"]
    assert task.locations[0].latitude == 58.56 and task.map_graphic_ids == ["c2510000-0006-8000-8000-000000000002"]
    assert task.start_time.form == "DateTime" and task.start_time.resolved == "2026-09-21T06:30:00.000Z"
    assert task.end_time.form == "SimulationTime" and task.end_time.elapsed_seconds == 7200 and task.end_time.resolved is None
    assert (task.duration, task.duration_seconds) == ("P00Y00M00DT01H30M00S", 5400)
    assert task.temporal_relationships[0].model_dump() == {"code": "STREND", "in_pinned_enumeration": True,
                                                            "duration": "P00Y00M00DT00H10M00S", "duration_seconds": 600,
                                                            "action": "c2510000-0004-8000-8000-000000000001",
                                                            "resolved_in_order": False}
    assert event.related_entities == [ids.derive("C2SIM", u, kind="object") for u in (A_COY, B_COY, HQ)]
    with_clock = C2simAdapter(exercise=CLOCK).to_cdm(_xml(MOVE))[0]
    assert with_clock.payload["c2sim"]["tasks"][0]["end_time"]["resolved"] == "2026-09-21T08:00:00.000Z"


def test_a_hold_order_carries_relative_time_dependencies_and_rules_of_engagement():
    event, = C2simAdapter().to_cdm(_xml(HOLD))
    order = codec.OrderPayload.model_validate(event.payload["c2sim"])
    first, second = order.tasks
    assert (first.action_code, second.action_code) == ("HoldInPlace", "HoldInPlace")
    assert first.start_time.form == "RelativeTime" and first.start_time.event_reference == "c2510000-0008-8000-8000-000000000001"
    assert first.start_time.time_reference_code == "IntervalEndTime" and first.start_time.resolved is None
    assert first.rules_of_engagement == [{"MipWeaponUseROE": {"WeaponROECode": {"WeaponRuleOfEngagementCode": "ROEHold"}}}]
    assert second.temporal_relationships[0].action == first.uuid and second.temporal_relationships[0].resolved_in_order is True
    assert second.functional_relations[0].model_dump() == {"code": "IOT", "in_pinned_enumeration": True,
                                                            "task": first.uuid, "resolved_in_order": True}
    assert order.task_references == ["c2510000-0004-8000-8000-000000000002"]
    assert order.issued_time.name == "EXERCISE-ISSUED"
    assert order.message.in_reply_to_message_id == "c2510000-0000-8000-8000-00000000a002"
    assert "Task" not in event.residual.data, "both tasks fully typed, so no task residual"
    move, = C2simAdapter().to_cdm(_xml(MOVE))
    assert "Task" not in move.residual.data


def test_an_unsupported_task_code_is_refused_by_name_and_never_substituted():
    with pytest.raises(ValueError, match="'ATTACK' is outside the pinned task forms \\('HoldInPlace', 'MoveToLocation'\\)"):
        C2simAdapter().to_cdm((MALFORMED / "unsupported_task_code.xml").read_bytes())
    event, = C2simAdapter().to_cdm(_xml(HOLD))
    payload = copy.deepcopy(event.payload)
    payload["c2sim"]["tasks"][0]["action_code"] = "Observe"
    forged = event.model_copy(update={"payload": payload})
    with pytest.raises(EgressRefused, match="outside the pinned forms"):
        C2simAdapter().from_cdm([forged])


# --------------------------------------------------------------------------- refusals

REFUSALS = {
    "wrong_namespace_version.xml": "namespace 'http://www.sisostds.org/schemas/C2SIM/1.2'",
    "missing_header_fields.xml": "lacks required field\\(s\\) \\['ConversationID', 'MessageID'\\]",
    "unresolved_entity_reference.xml": "references UUID c2510000-0002-8000-8000-0000000000ff, which no object",
    "duplicate_ids.xml": "already declared by ObjectDefinitions\\[0\\].Entity\\[0\\]",
    "unsupported_task_code.xml": "outside the pinned task forms",
    "move_without_destination.xml": "no Location and no MapGraphicID",
    "position_report_without_location.xml": "has no Location; a position report without a position is refused",
    "malformed_timestamp.xml": "not the schema's IsoDateTime form",
    "simulation_time_without_clock.xml": "SimulationTime that this adapter cannot resolve",
    "relative_time_observation.xml": "RelativeTime that this adapter cannot resolve",
    "system_command_body.xml": "MessageBody/SystemCommandBody is outside this adapter's declared subset",
    "billion_laughs_dtd.xml": "XML refused \\(dtd\\)",
    "truncated_document.xml": "XML refused \\(malformed\\)",
    "over_depth_document.xml": "XML refused \\(depth\\): .* 193 deep against max_depth = 192",
}


def test_every_malformed_payload_is_refused_by_name():
    on_disk = sorted(p.name for p in harness.select_fixtures(MALFORMED))
    assert on_disk == sorted(REFUSALS), "every refusal fixture has a stated reason and vice versa"
    for name, pattern in REFUSALS.items():
        with pytest.raises(ValueError, match=pattern):
            C2simAdapter().to_cdm((MALFORMED / name).read_bytes())
        assert C2simAdapter().validate_source((MALFORMED / name).read_bytes())[0].startswith(("ValueError", "XmlRefused"))


def test_two_message_bodies_a_missing_scenario_setting_and_a_wrong_root_are_refused():
    with pytest.raises(ValueError, match="exactly one body element"):
        C2simAdapter().to_cdm(_mutate(INIT, "  </MessageBody>", "    <SystemCommandBody><SystemCommandTypeCode>x</SystemCommandTypeCode></SystemCommandBody>\n  </MessageBody>"))
    with pytest.raises(ValueError, match="has no ScenarioSetting"):
        C2simAdapter().to_cdm(_mutate(INIT, "      <ScenarioSetting>", "      <Not><ScenarioSetting>").replace(b"</ScenarioSetting>", b"</ScenarioSetting></Not>"))
    with pytest.raises(ValueError, match="root element is <Order>, not <Message>"):
        C2simAdapter().to_cdm(b'<Order xmlns="http://www.sisostds.org/schemas/C2SIM/1.1"/>')
    with pytest.raises(ValueError, match="has no EchelonCode"):
        C2simAdapter().to_cdm(_mutate(INIT, "<EchelonCode>BN</EchelonCode>", ""))
    with pytest.raises(ValueError, match="not the schema's IsoTimeDuration form"):
        C2simAdapter().to_cdm(_mutate(POSITION, "P00Y00M00DT00H00M30S", "PT30S"))


def test_an_extension_element_or_attribute_is_preserved_listed_and_not_reemitted():
    document = (CASES / "extension_fields.xml").read_bytes()
    objects = C2simAdapter().to_cdm(document)
    unknown = objects[0].residual.data["unknown"]
    assert [(u["namespace"], u["name"], u["position"]) for u in unknown] == [
        ("urn:exercise:ext", "Callsign", 6), ("http://www.sisostds.org/schemas/C2SIM/1.1", "Remarks", 7),
        ("urn:exercise:ext", "Trailer", 2)]
    assert unknown[0]["path"].startswith("MessageBody.") and unknown[0]["path"].endswith("Unit.{urn:exercise:ext}Callsign")
    assert unknown[2]["path"] == "{urn:exercise:ext}Trailer"
    hq = _by_uuid(objects, HQ)
    own = hq.residual.data["Entity"]["ActorEntity"]["CollectiveEntity"]["MilitaryOrganization"]["Unit"]
    assert own["{urn:exercise:ext}Callsign"] == {"@{urn:exercise:ext}priority": "1", "#text": "EX-HQ"}
    assert own["Remarks"] == "Not a schema element"
    assert hq.residual.data["{urn:exercise:ext}Trailer"] == "after the body"
    problems = C2simAdapter().validate_source(document)
    assert len([p for p in problems if "outside the pinned vocabulary" in p]) == 3
    emitted = C2simAdapter().from_cdm(objects)
    assert b"ext:" not in emitted and b"Remarks" not in emitted and b"urn:exercise" not in emitted
    assert len(C2simAdapter().to_cdm(emitted)) == len(objects) == 12


def test_untyped_object_classes_are_carried_in_the_residual_and_named():
    document = (CASES / "initialisation_untyped_classes.xml").read_bytes()
    objects = C2simAdapter().to_cdm(document)
    assert [_block(o).object_class for o in objects] == ["ForceSide", "Unit"]
    definitions = objects[1].residual.data["MessageBody"]["C2SIMInitializationBody"]["ObjectDefinitions"]
    assert [None if a is None else list(a) for a in definitions[0]["AbstractObject"]] == [None, ["CommunicationNetwork"], ["Overlay"]]
    assert [None if e is None else list(e["ActorEntity"]) for e in definitions[0]["Entity"]] == [None, ["CollectiveEntity"], ["Person"]]
    problems = C2simAdapter().validate_source(document)
    assert [p.split(":")[0] for p in problems] == ["ObjectDefinitions[0].AbstractObject[1]", "ObjectDefinitions[0].AbstractObject[2]",
                                                  "ObjectDefinitions[0].Entity[1]", "ObjectDefinitions[0].Entity[2]"]
    assert _ledger(codec.twin_of(ET.fromstring(document)), objects).lost == ()


def test_header_strings_off_the_profile_rule_are_carried_and_named():
    document = _mutate(INIT, "<ProtocolVersion>1.0.0</ProtocolVersion>", "<ProtocolVersion>1.0.1</ProtocolVersion>")
    objects = C2simAdapter().to_cdm(document)
    assert _block(objects[0]).message.protocol_version == "1.0.1"
    assert _block(objects[0]).message.protocol_matches_pin is False
    assert any("differ from the profile rule" in p for p in C2simAdapter().validate_source(document))
    assert C2simAdapter().validate_source(_xml(INIT)) == []


# ------------------------------------------------------------------------------ bounds

def test_the_byte_bound_admits_a_document_at_it_and_refuses_one_octet_past():
    text = _xml(INIT)
    padding = C2SIM_MAX_INPUT_BYTES - len(text)
    at = text.replace(b"</Message>", b"<!--" + b"x" * (padding - 7) + b"--></Message>")
    assert len(at) == C2SIM_MAX_INPUT_BYTES
    assert len(C2simAdapter().to_cdm(at)) == 11
    with pytest.raises(InputTooLarge):
        C2simAdapter().to_cdm(at + b"\n")


def test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past():
    def nested(depth):
        return (b'<Message xmlns="http://www.sisostds.org/schemas/C2SIM/1.1">' + b"<n>" * (depth - 1) + b"x"
                + b"</n>" * (depth - 1) + b"</Message>")
    with pytest.raises(ValueError) as at_bound:
        C2simAdapter().to_cdm(nested(C2SIM_MAX_DEPTH))
    assert not isinstance(at_bound.value, secure_xml.XmlRefused), "at the bound the document parses; the header is what refuses it"
    assert "C2SIMHeader is missing" in str(at_bound.value)
    for depth in (C2SIM_MAX_DEPTH + 1, 1000):
        # Refused AT the element that crosses the bound — the 193rd — however deep the rest goes.
        with pytest.raises(secure_xml.XmlRefused, match=f"{C2SIM_MAX_DEPTH + 1} deep against max_depth = {C2SIM_MAX_DEPTH}") as past:
            C2simAdapter().to_cdm(nested(depth))
        assert past.value.kind == "depth"
    deepest = max(secure_xml.tree_depth(ET.fromstring(p.read_bytes())) for p in XML_FILES)
    assert deepest * 8 <= C2SIM_MAX_DEPTH, deepest


def test_the_element_bound_refuses_a_document_one_element_past():
    body = b'<Message xmlns="http://www.sisostds.org/schemas/C2SIM/1.1">' + b"<n/>" * C2SIM_MAX_ELEMENTS + b"</Message>"
    with pytest.raises(secure_xml.XmlRefused, match="elements") as past:
        C2simAdapter().to_cdm(body)
    assert past.value.kind == "elements"


def test_the_object_bound_admits_a_message_at_it_and_refuses_one_past():
    def with_units(count):
        twin = copy.deepcopy(_twin(INIT))
        definitions = twin["MessageBody"]["C2SIMInitializationBody"]["ObjectDefinitions"][0]
        base = definitions["Entity"][1]
        entities = []
        for i in range(count - len(definitions["AbstractObject"])):
            unit = copy.deepcopy(base)
            u = unit["ActorEntity"]["CollectiveEntity"]["MilitaryOrganization"]["Unit"]
            u["UUID"] = f"c2510000-00ff-8000-8000-{i:012d}"
            del u["EntityDescriptor"]["Superior"], u["CommandRelation"]
            entities.append(unit)
        definitions["Entity"] = entities
        return twin
    assert len(C2simAdapter().to_cdm(with_units(C2SIM_MAX_OBJECTS))) == C2SIM_MAX_OBJECTS
    with pytest.raises(ObjectCountExceeded, match=f"{C2SIM_MAX_OBJECTS + 1} object-bearing elements"):
        C2simAdapter().to_cdm(with_units(C2SIM_MAX_OBJECTS + 1))


def test_the_declared_limits_are_the_enforced_constants():
    limits = C2simAdapter.metadata.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (
        C2SIM_MAX_INPUT_BYTES, C2SIM_MAX_DEPTH, C2SIM_MAX_OBJECTS)
    assert module.XML_LIMITS == secure_xml.XmlLimits(C2SIM_MAX_INPUT_BYTES, C2SIM_MAX_DEPTH, C2SIM_MAX_ELEMENTS)
    for name in ("max_input_bytes", "max_depth", "max_objects"):
        assert name in limits.declared_because
        test = limits.declared_because[name].test
        module_name, test_name = test.split("::")
        # Read beside THIS file, not through the package's path: the wheel gate runs this module
        # against site-packages, where the repository is not (phase 5 finding).
        named = pathlib.Path(__file__).resolve().parent / pathlib.Path(module_name).name
        assert named.is_file(), test
        assert test_name in named.read_text(), test
    assert "max_parse_seconds" in limits.absent_because and "max_decompressed_bytes" in limits.absent_because


def test_the_adapter_resolves_no_reference_and_touches_no_file_or_network():
    for path in (module.__file__, codec.__file__):
        tree = ast.parse(pathlib.Path(path).read_text())
        imported = {n.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for n in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom)}
        assert not imported & {"urllib", "socket", "http", "requests", "pathlib", "os", "io"}, (path, imported)
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert "open" not in calls
    document = _mutate(INIT, "<Name>EXERCISE-BLUE-BN-HQ</Name>", "<Name>https://example.invalid/x</Name>")
    assert _block(_by_uuid(C2simAdapter().to_cdm(document), HQ)).name == "https://example.invalid/x"


def test_determinism_across_runs_and_across_hash_seeds():
    for path in XML_FILES:
        a = _dump(C2simAdapter(clock=lambda: _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(_xml(path)))
        b = _dump(C2simAdapter(clock=lambda: _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(_xml(path)))
        assert a == b
    script = (
        "import json, sys, pathlib, datetime\n"
        "from synapse_cdm.adapters.c2sim import C2simAdapter\n"
        "from synapse_cdm import canonical\n"
        "clock = lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)\n"
        "out = [canonical.serialise([o.model_dump(mode='json') for o in C2simAdapter(clock=clock).to_cdm("
        "pathlib.Path(p).read_bytes())]) for p in sys.argv[1:]]\n"
        "print(json.dumps(out))\n")
    readings = []
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(PKG.parent)}
        result = subprocess.run([sys.executable, "-c", script, *map(str, XML_FILES)],
                                capture_output=True, text=True, env=env, check=True)
        readings.append(result.stdout)
    assert readings[0] == readings[1]


def test_element_order_is_meaningful_and_kept():
    """Two objects swapped in the document swap their record_index and their positions in the
    output; nothing else moves. The order the source stated is the order of record."""
    twin = copy.deepcopy(_twin(INIT))
    entities = twin["MessageBody"]["C2SIMInitializationBody"]["ObjectDefinitions"][0]["Entity"]
    entities[0], entities[1] = entities[1], entities[0]
    original = _dump(C2simAdapter().to_cdm(_twin(INIT)))
    swapped = _dump(C2simAdapter().to_cdm(twin))
    assert [o["source_ids"][0]["external_id"] for o in swapped][3:5] == [A_COY, HQ]
    assert [o["source"]["record_index"] for o in swapped] == list(range(11))
    assert original[3]["entity_id"] == swapped[4]["entity_id"]


def test_detect_answers_on_the_root_and_the_namespace_only():
    adapter = C2simAdapter()
    assert adapter.detect(_xml(INIT)) is True and adapter.detect(_twin(INIT)) is True
    assert adapter.detect((MALFORMED / "wrong_namespace_version.xml").read_bytes()) is False
    assert adapter.detect(b'<event version="2.0"/>') is False and adapter.detect({"event": {}}) is False
    assert adapter.detect({"C2SIMHeader": {}, "MessageBody": {}}) is True
    assert adapter.detect(b"\xff\xfe") is False and adapter.detect(12) is None


# ------------------------------------------------------------------------------ egress

def test_semantic_round_trip_of_every_fixture():
    """source -> CDM -> source -> CDM: every mapped field equal, the emitted document
    re-ingests to the same objects (transformations and receipt time aside), and the second
    emission is a fixed point."""
    for path in XML_FILES:
        adapter = C2simAdapter(exercise=CLOCK)
        first = adapter.to_cdm(_xml(path))
        emitted = adapter.from_cdm(first)
        second = adapter.to_cdm(emitted)
        a, b = _dump(first), _dump(second)
        for x, y in zip(a, b):
            for key in ("received_at",):
                x.pop(key, None), y.pop(key, None)
        assert a == b, path.name
        assert adapter.from_cdm(second) == emitted, path.name
        assert lossless.value_presence_heuristic(_twin(path), _dump(second), {}) == {}, path.name
        assert lossless.value_presence_heuristic(_twin(path), [codec.twin_of(ET.fromstring(emitted))], {}) == {}, \
            "every source value is in the emitted document itself"


@pytest.mark.normative
@pytest.mark.parametrize("path", XML_FILES + sorted(CASES.glob("*.xml")), ids=lambda p: p.stem)
def test_every_emitted_document_validates_against_the_pinned_schema(path):
    adapter = C2simAdapter(exercise=CLOCK)
    emitted = adapter.from_cdm(adapter.to_cdm(path.read_bytes()))
    verdict = normative_support.verdict("c2sim", emitted)
    if path.name == "report_unknown_status_code.xml":
        assert verdict.outcome is verdict.outcome.INVALID, "a code outside the enumeration is carried verbatim, and the validator says so"
        assert any("Degraded" in p for p in verdict.problems)
        return
    assert verdict.outcome is verdict.outcome.VALID, verdict.describe()


@pytest.mark.parametrize("path", EGRESS_FILES, ids=lambda p: p.stem)
def test_every_egress_fixture_emits_its_golden_and_validates(path):
    """Fresh egress: records a planning stub wrote, never this adapter's output. The golden is
    compared byte for byte; the normative half is its own BLOCKED-aware step below."""
    objects = OBJECTS.validate_python(json.loads(path.read_text()))
    assert all(o.source.adapter == "planner_stub" and o.residual is None for o in objects)
    emitted = C2simAdapter(envelope=ENVELOPE).from_cdm(objects)
    golden = EGRESS / "golden" / (path.stem + ".c2sim.xml")
    assert emitted == golden.read_bytes(), f"{golden} differs; review before rewriting"
    again = C2simAdapter(envelope=ENVELOPE).to_cdm(emitted)
    assert [o.source_ids[0].external_id for o in again] == [o.source_ids[0].external_id for o in objects]
    assert [type(o) for o in again] == [type(o) for o in objects]


@pytest.mark.normative
@pytest.mark.parametrize("path", EGRESS_FILES, ids=lambda p: p.stem)
def test_every_egress_golden_validates_against_the_pinned_schema(path):
    golden = EGRESS / "golden" / (path.stem + ".c2sim.xml")
    verdict = normative_support.verdict("c2sim", golden.read_bytes())
    assert verdict.outcome is verdict.outcome.VALID, verdict.describe()


def test_egress_refuses_what_it_would_otherwise_have_to_invent():
    fresh = OBJECTS.validate_python(json.loads((EGRESS / "fresh_initialisation_side_unit_platform_route.json").read_text()))
    side, unit, aircraft, route = fresh
    with pytest.raises(EgressRefused, match="no Envelope was constructed"):
        C2simAdapter().from_cdm(fresh)
    with pytest.raises(EgressRefused, match="SystemEntityList"):
        C2simAdapter(envelope=Envelope(ENVELOPE.message_id, ENVELOPE.conversation_id, "A", "B")).from_cdm(fresh)
    bare = unit.model_copy(update={"attributes": {}})
    with pytest.raises(EgressRefused, match="no `attributes.c2sim` block"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([side, bare])
    no_echelon = copy.deepcopy(unit.attributes)
    del no_echelon["c2sim"]["organisation"]["echelon"]
    with pytest.raises(EgressRefused, match="states no echelon"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([unit.model_copy(update={"attributes": no_echelon})])
    no_type = copy.deepcopy(aircraft.attributes)
    no_type["c2sim"]["classifications"] = []
    with pytest.raises(EgressRefused, match="states no classification"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([aircraft.model_copy(update={"attributes": no_type})])
    no_route_block = route.model_copy(update={"route": route.route.model_copy(update={"metadata": {}})})
    with pytest.raises(EgressRefused, match="no `route.metadata.c2sim` block"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([no_route_block])
    order, = OBJECTS.validate_python(json.loads((EGRESS / "fresh_order_move_and_hold.json").read_text()))
    report, = OBJECTS.validate_python(json.loads((EGRESS / "fresh_report_position_no_header.json").read_text()))
    with pytest.raises(EgressRefused, match="an order and a report cannot share one Message"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([order, report])
    with pytest.raises(EgressRefused, match="carry no `payload.c2sim` block"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([order.model_copy(update={"payload": {}})])
    with pytest.raises(EgressRefused, match="no objects"):
        C2simAdapter(envelope=ENVELOPE).from_cdm([])
    with pytest.raises(EgressRefused, match="two different message headers"):
        C2simAdapter().from_cdm(C2simAdapter().to_cdm(_xml(POSITION)) + C2simAdapter().to_cdm(_xml(STATUS)))


def test_egress_of_a_report_orders_its_contents_and_refuses_two_reports():
    events = C2simAdapter().to_cdm(_xml(POSITION))
    emitted = C2simAdapter().from_cdm(list(reversed(events)))
    assert C2simAdapter().from_cdm(events) == emitted, "contents are written in content_index order"
    other = C2simAdapter().to_cdm(_xml(STATUS))
    with pytest.raises(EgressRefused, match="two different message headers"):
        C2simAdapter().from_cdm(events + other)
    with pytest.raises(EgressRefused, match="belong to 2 reports"):
        C2simAdapter(envelope=ENVELOPE).from_cdm(events + other)


# ---------------------------------------------------------------------- the negatives

def test_negative_a_swapped_reporter_and_subject_is_caught_by_the_ledger():
    twin = _twin(POSITION)
    events = C2simAdapter().to_cdm(twin)
    assert _ledger(twin, events).lost == ()
    wrong = _dump(events)
    for event in wrong:
        block = event["payload"]["c2sim"]
        block["reporting_entity"], block["subject_entity"] = block["subject_entity"], block["reporting_entity"]
    lost = {e.source_path.split(".")[-1] for e in _ledger(twin, wrong).lost}
    assert lost == {"SubjectEntity"}, lost
    # ReportingEntity is one value for the whole report and the first content's subject IS the
    # reporter, so the swap leaves A-COY at both paths on event 0 and the `event` target reads
    # the leaf on it; the second content's subject (the APC) is what the ledger sees vanish.
    # The path-specific reading is the sharper oracle:
    assert wrong[1]["payload"]["c2sim"]["subject_entity"] != twin["MessageBody"]["DomainMessageBody"]["ReportBody"]["ReportContent"][1]["PositionReportContent"]["SubjectEntity"]


def test_negative_a_dropped_task_time_constraint_is_caught_by_the_ledger_and_the_contract():
    twin = _twin(MOVE)
    objects = C2simAdapter().to_cdm(twin)
    wrong = _dump(objects)
    del wrong[0]["payload"]["c2sim"]["tasks"][0]["start_time"]
    lost = [e for e in _ledger(twin, wrong).lost]
    assert [e.source_path.split("ManeuverWarfareTask.")[-1] for e in lost] == ["StartTime.DateTime.IsoDateTime"]
    assert lost[0].loss == "MISSING"
    dropped = copy.deepcopy(objects[0].payload)
    dropped["c2sim"]["tasks"][0]["start_time"] = {"form": "DateTime", "resolution": "stated"}
    with pytest.raises(ValueError, match="needs iso_date_time"):
        C2simAdapter().from_cdm([objects[0].model_copy(update={"payload": dropped})])


def test_negative_a_wrong_namespace_string_on_egress_is_caught_by_re_ingest():
    """An emitter that spelled the namespace wrong would produce a document this adapter's own
    ingest refuses — and, under the resource, the validator refuses."""
    emitted = C2simAdapter().from_cdm(C2simAdapter().to_cdm(_xml(HOLD)))
    wrong = emitted.replace(b"C2SIM/1.1", b"C2SIM/1.2")
    assert wrong != emitted
    with pytest.raises(ValueError, match="is in namespace 'http://www.sisostds.org/schemas/C2SIM/1.2'"):
        C2simAdapter().to_cdm(wrong)
    assert C2simAdapter().detect(wrong) is False


def test_the_ledger_catches_a_value_landing_on_the_wrong_list_index():
    """The `[_]` wildcard's reason: bind the outer containers too and the ObjectDefinitions index
    goes into `locations[*]`, and B-COY's second location reads LOST."""
    twin = _twin(INIT)
    objects = C2simAdapter().to_cdm(twin)
    bound = {k.replace("[_]", "[*]"): v for k, v in C2simAdapter.MAPPINGS.items()}
    book = lossless.ledger(twin, _dump(objects), bound)
    assert any(e.source_path.endswith("Location[1].GeodeticCoordinate.Latitude") for e in book.lost)
    assert _ledger(twin, objects).lost == ()


# ------------------------------------------------------------------------- the surface

def test_the_public_surface_is_declared_and_the_codec_is_pure():
    assert set(module.__all__) >= {"C2simAdapter", "Envelope", "ExerciseClock", "EgressRefused"}
    with pytest.raises(ValueError, match="own_side must be a C2SIM UUID"):
        C2simAdapter(own_side="blue")
    with pytest.raises(TypeError):
        C2simAdapter(exercise="2026-09-21T06:00:00Z")
    with pytest.raises(ValueError, match="basis must say"):
        ExerciseClock(epoch="2026-09-21T06:00:00Z", basis="x")
    with pytest.raises(ValueError, match="rate is scenario seconds"):
        ExerciseClock(epoch="2026-09-21T06:00:00Z", basis="the scenario start", rate=0)
    with pytest.raises(ValueError, match="must be a UUID text"):
        Envelope("not-a-uuid", ENVELOPE.conversation_id, "A", "B")
    assert codec.duration_seconds("P00Y00M01DT02H03M04S", "x") == 93784
    assert codec.duration_seconds("P01Y00M00DT00H00M00S", "x") is None, "a year has no fixed length"
    assert codec.render_duration(93784) == "P00Y00M01DT02H03M04S"
    with pytest.raises(ValueError, match="not the schema's IsoTimeDuration form"):
        codec.duration_seconds("PT5M", "x")
    with pytest.raises(ValueError, match="not a calendar instant"):
        codec.parse_iso_date_time("2026-02-30T00:00:00Z", "x")
