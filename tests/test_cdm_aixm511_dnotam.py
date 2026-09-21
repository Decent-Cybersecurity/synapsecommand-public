"""Digital NOTAM on the AIXM 5.1.1 adapter (#19): the Event Schema 2.0.m binding and the three
pinned scenario profiles — adapter expansion phase 5 (2026-09-21).

What is proved here: the `dnotam/` fixture set is what the record describes and every twin is
the standard library's own reading of its XML; every positive document validates against the
pinned AIXM 5.1.1 + Event 2.0.m closure (BLOCKED, never PASS, without the resource) and the
base 5.1.1 closure alone rejects an Event document; both counterexample classes are caught at
their declared layer (schema by `normative_validation`, scenario rule by the adapter); an Event
slice is an Entity with the `aixm-dnotam/1` block, its scenario resolved to the pinned profile
(identifier, version, page, rule ids, DRAFT), its NOTAMs typed beside their source, its source
assertion read from the slice alone — initial, correction, termination, cancellation,
replacement — with its temporal basis and expiry; a bound feature slice carries the binding, the
Event's scenario and the rule layer's findings; the ledger loses nothing on any document; the
manifest names exactly the pinned identifiers and rule versions; and the targeted negative for
a wrong scenario-code mapping.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import xml.etree.ElementTree as ET

import pytest

import synapse_cdm
from synapse_cdm import lossless, secure_xml
from synapse_cdm.adapters import aixm511 as module
from synapse_cdm.adapters import aixm_codec as codec
from synapse_cdm.adapters.aixm511 import (
    NAVAID_EQUIPMENT_FEATURES, SCENARIO_PROFILE_DECLARATIONS, SCENARIO_PROFILES, Aixm511Adapter, AsOf,
    DigitalNotamBlock, TimeSliceBlock,
)
from synapse_cdm.enums import EntityType
from synapse_cdm.models import Entity
from tests import normative_support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "aixm511"
DNOTAM = FIXTURES / "dnotam"
CASES = DNOTAM / "cases"
COUNTER = DNOTAM / "counterexamples"
PIN = FIXTURES / "spec" / "aixm511_pin.json"
XML_FILES = sorted(p for p in DNOTAM.glob("*.xml"))
POSITIVE = XML_FILES + sorted(CASES.glob("*.xml"))
RWY_CLS = DNOTAM / "rwy_cls_baseline_and_closure.xml"
ATSA = DNOTAM / "atsa_act_baseline_and_activation.xml"
SAA = DNOTAM / "saa_act_activation_with_schedule.xml"
NAV_UNS = DNOTAM / "nav_uns_baseline_and_outage.xml"
NILS = DNOTAM / "explicit_nil_values.xml"
UNRESOLVED = DNOTAM / "unresolved_references.xml"
OUT_OF_ORDER = DNOTAM / "corrections_out_of_order.xml"
EXPIRY = DNOTAM / "expiry.xml"
CANCELLATION = CASES / "cancellation.xml"
RWY_DIR = "a1a40000-00d0-4000-8000-000000000002"
NAVAID = "a1a40000-00d0-4000-8000-000000000005"
VOR = "a1a40000-00d0-4000-8000-000000000006"
EVENT_1 = "a1a40000-00e0-4000-8000-000000000001"
AS_OF = AsOf("2026-03-25T12:00:00Z", "the synthetic issue instant of the cancellation, stated by the fixture's author")


def _xml(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def _twin(path: pathlib.Path) -> dict:
    return json.loads((path.parent / (path.stem + ".parsed.json")).read_text())


def _twin_of(raw: bytes) -> dict:
    return codec.twin_of(secure_xml.parse(raw, module.XML_LIMITS).root, codec.VERSION_511)


def _dump(objects):
    return [o.model_dump(mode="json") for o in objects]


def _ledger(raw, objects):
    return lossless.ledger(raw, _dump(objects), Aixm511Adapter.MAPPINGS)


def _read(path: pathlib.Path, **kwargs) -> list[Entity]:
    return [o for o in Aixm511Adapter(**kwargs).to_cdm(_xml(path)) if isinstance(o, Entity)]


def _block(obj) -> TimeSliceBlock:
    return TimeSliceBlock.model_validate(obj.attributes["aixm"])


def _dnotam(obj) -> DigitalNotamBlock:
    return DigitalNotamBlock.model_validate(obj.attributes["dnotam"])


def _slices(objects, identifier: str) -> list[Entity]:
    return [o for o in objects if o.source_ids[0].external_id == identifier]


# ----------------------------------------------------------------- the fixtures themselves

def test_the_fixture_set_is_the_one_the_record_describes():
    assert [p.name for p in XML_FILES] == [
        "atsa_act_baseline_and_activation.xml", "corrections_out_of_order.xml", "expiry.xml",
        "explicit_nil_values.xml", "future_effective_change.xml", "nav_uns_baseline_and_outage.xml",
        "overlapping_tempdeltas.xml", "rwy_cls_baseline_and_closure.xml", "saa_act_activation_with_schedule.xml",
        "unresolved_references.xml"]
    assert [p.stem.removesuffix(".parsed") for p in sorted(DNOTAM.glob("*.parsed.json"))] == [p.stem for p in XML_FILES]
    assert [p.name for p in sorted(CASES.glob("*.xml"))] == ["cancellation.xml"]
    assert [p.name for p in sorted(COUNTER.glob("*.xml"))] == [
        "rule_invalid_rwy_cls_on_an_airspace.xml", "rule_invalid_rwy_cls_without_closed_status.xml",
        "schema_invalid_event_schema_1_0_namespace.xml", "schema_invalid_unknown_event_property.xml"]
    assert sorted(p.name for p in (DNOTAM / "golden").iterdir()) == sorted(
        [p.stem + ".cdm.json" for p in XML_FILES] + [p.stem + ".parsed.cdm.json" for p in XML_FILES])
    pin = json.loads(PIN.read_text())
    for path in POSITIVE + sorted(COUNTER.glob("*.xml")) + [DNOTAM / "spec" / "build_fixtures.py", DNOTAM / "README.md"]:
        rel = str(path.relative_to(FIXTURES))
        assert pin["files"][rel]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest(), rel
    for path in POSITIVE + sorted(COUNTER.glob("*.xml")):
        text = path.read_text()
        assert "SYNTHETIC" in text and "a1a40000-00" in text and "build_fixtures.py" in text, path.name
    for record in (DNOTAM, CASES, COUNTER):
        listed = {f["file"] for f in json.loads((record / "PROVENANCE.json").read_text())["fixtures"]}
        assert listed == {p.name for p in record.iterdir() if p.is_file() and p.name not in ("README.md", "PROVENANCE.json")}


def test_every_parsed_twin_corresponds_to_its_raw_fixture():
    """The twin re-derived from the XML with the standard library ALONE — the object-property
    collapse spelled by hand, the repeatable properties listed by hand, the event namespace
    given its prefix — equals the committed twin. No codec table is consulted."""
    prefixes = {"http://www.aixm.aero/schema/5.1.1": "aixm", "http://www.aixm.aero/schema/5.1.1/message": "message",
                "http://www.aixm.aero/schema/5.1.1/event": "event", "http://www.opengis.net/gml/3.2": "gml",
                "http://www.w3.org/1999/xlink": "xlink", "http://www.w3.org/2001/XMLSchema-instance": "xsi"}
    always_list = {"message:hasMember", "aixm:timeSlice", "aixm:activation", "aixm:availability", "aixm:timeInterval",
                   "aixm:navaidEquipment", "aixm:annotation", "aixm:extension", "aixm:levels", "gml:name",
                   "event:timeSlice", "event:concernedAirspace", "event:concernedAirportHeliport", "event:notification",
                   "event:container", "event:annotation", "event:extension", "aixm:translatedNote"}

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
        assert obj(root) == _twin(path), path.name


@pytest.mark.parametrize("path", XML_FILES, ids=lambda p: p.stem)
def test_the_xml_and_its_twin_translate_to_the_same_objects(path):
    assert _dump(Aixm511Adapter().to_cdm(_xml(path))) == _dump(Aixm511Adapter().to_cdm(_twin(path)))


def test_the_generator_is_current_and_the_fixtures_are_its_output():
    """`build_fixtures.py --check` in a subprocess (no bytecode is written under `spec/`, which
    the pin test would otherwise see), and the set it writes is the set on disk."""
    import subprocess
    import sys
    run = subprocess.run([sys.executable, "-B", str(DNOTAM / "spec" / "build_fixtures.py"), "--check"],
                         capture_output=True, text=True, timeout=120)
    assert run.returncode == 0 and run.stdout.strip() == "CURRENT", run.stdout + run.stderr
    listing = subprocess.run([sys.executable, "-B", "-c",
                              "import runpy, json, sys; g = runpy.run_path(sys.argv[1]); print(json.dumps(sorted(g['build']())))",
                              str(DNOTAM / "spec" / "build_fixtures.py")], capture_output=True, text=True, timeout=120)
    assert listing.returncode == 0, listing.stderr
    assert set(json.loads(listing.stdout)) == {p.name for p in XML_FILES} | {"cases/cancellation.xml"} | {
        "counterexamples/" + p.name for p in COUNTER.glob("*.xml")}


# ------------------------------------------------------------------- the schema layer

@pytest.mark.normative
@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_every_positive_fixture_validates_against_the_pinned_event_closure(path):
    verdict = normative_support.verdict("dnotam", path.read_bytes())
    assert verdict.outcome.value == "VALID", verdict.describe()


@pytest.mark.normative
def test_the_base_closure_alone_does_not_admit_an_event_document():
    """The permitted combination is AIXM 5.1.1 + Event 2.0.m; the 5.1.1 closure without the
    Event schema has no `event:Event`, so the same document is INVALID there (D3)."""
    verdict = normative_support.verdict("aixm511", RWY_CLS.read_bytes())
    assert verdict.outcome.value == "INVALID" and "Event" in "".join(verdict.problems), verdict.describe()


@pytest.mark.normative
def test_the_event_repeatable_rows_are_the_pinned_event_schemas():
    """The event-namespace rows of `REPEATABLE`, re-derived from `Event_Features.xsd`: every
    event object element with a type in the event namespace and at least one unbounded child."""
    resource = normative_support.resource("dnotam")
    xsd = pathlib.Path(resource.directory) / "aixm-5.1.1" / "event" / "version_5.1.1-m" / "Event_Features.xsd"
    xs = "{http://www.w3.org/2001/XMLSchema}"
    root = ET.parse(xsd).getroot()
    types = {t.get("name"): t for t in root.iter(xs + "complexType")}
    groups = {g.get("name"): g for g in root.iter(xs + "group")}

    def props(tname, seen=()):
        out = []
        for el in types.get(tname, ()).iter() if tname in types else ():
            if el.tag == xs + "element" and el.get("name"):
                out.append((el.get("name"), el.get("maxOccurs", "1")))
            elif el.tag == xs + "group" and el.get("ref"):
                out.extend((e.get("name"), e.get("maxOccurs", "1")) for e in groups[el.get("ref").split(":")[-1]].iter(xs + "element"))
            elif el.tag == xs + "extension" and (el.get("base") or "").startswith("event:"):
                base = el.get("base").split(":")[1]
                if base not in seen:
                    out.extend(props(base, seen + (base,)))
        return out

    derived = {}
    for e in root.findall(xs + "element"):
        typ = e.get("type") or ""
        if typ.startswith("event:"):
            unbounded = tuple(sorted("event:" + n for n, m in props(typ.split(":")[1]) if m == "unbounded"))
            if unbounded:
                derived["event:" + e.get("name")] = unbounded
    assert {k: codec.REPEATABLE[k] for k in codec.REPEATABLE_EVENT_ROWS} == derived


#: Counterexample -> (schema layer verdict, the rule finding's text or None).
COUNTEREXAMPLE_LAYERS = {
    "schema_invalid_unknown_event_property.xml": ("INVALID", None),
    "schema_invalid_event_schema_1_0_namespace.xml": ("INVALID", "which is not an event:Event"),
    "rule_invalid_rwy_cls_on_an_airspace.xml": ("VALID", "RWY.CLS RWY.CLS.02: the Event binds a <aixm:Airspace> slice"),
    "rule_invalid_rwy_cls_without_closed_status.xml": ("VALID", "RWY.CLS RWY.CLS.03: no aixm:ManoeuvringAreaAvailability on the TEMPDELTA states operationalStatus in ['CLOSED']"),
}


@pytest.mark.normative
@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_has_its_declared_schema_verdict(name):
    verdict = normative_support.verdict("dnotam", (COUNTER / name).read_bytes())
    assert verdict.outcome.value == COUNTEREXAMPLE_LAYERS[name][0], verdict.describe()


@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_is_read_by_the_adapter_and_caught_at_its_declared_layer(name):
    raw = (COUNTER / name).read_bytes()
    adapter = Aixm511Adapter()
    objects = adapter.to_cdm(raw)
    assert objects, "the structural layer reads every counterexample; what it finds is reported, not repaired"
    assert _ledger(_twin_of(raw), objects).lost == ()
    findings = [f for o in objects if isinstance(o, Entity) and "dnotam" in o.attributes for f in _dnotam(o).rule_findings]
    expected = COUNTEREXAMPLE_LAYERS[name][1]
    if expected is None:
        assert findings == [], "a schema breach the rule layer has nothing to say about"
        if name == "schema_invalid_unknown_event_property.xml":
            event = _slices([o for o in objects if isinstance(o, Entity)], EVENT_1)[0]
            assert event.residual.data["message:hasMember"][0]["event:timeSlice"][0]["event:closureReason"] == "maintenance"
    else:
        assert any(expected in f for f in findings), findings
        assert any(expected in p for p in adapter.validate_source(raw))
    readme = (COUNTER.parent / "README.md").read_text()
    assert name in readme


# ------------------------------------------------------------------ the Event binding

def test_an_event_slice_is_an_entity_with_the_dnotam_block_and_the_pinned_profile():
    objects = _read(RWY_CLS)
    assert [o.attributes["aixm"]["feature"]["element"] for o in objects] == [
        "aixm:AirportHeliport", "aixm:Airspace", "event:Event", "aixm:RunwayDirection", "aixm:RunwayDirection"]
    event = _slices(objects, EVENT_1)[0]
    assert event.entity_type == EntityType.UNKNOWN and event.position is None and event.status is None
    assert event.source_ids[1].external_id == f"{EVENT_1}/BASELINE/1/0" and event.source.original_id == "EVT_1_BL_1_0"
    block = _block(event)
    assert block.feature.family == "Event" and block.time_slice.element == "event:EventTimeSlice"
    assert block.time_slice.interpretation == "BASELINE" and block.time_slice.feature_lifetime.form == "period"
    assert {k: v.value for k, v in block.properties.items()} == {
        "name": "ZZSY 09", "designator": "DNOTAM", "scenario": "RWY.CLS", "version": "2.0",
        "estimatedValidity": None, "activity": None}
    assert block.properties["estimatedValidity"].meaning == "not stated"
    assert block.references["concernedAirspace"][0].resolved and block.references["concernedAirspace"][0].target.element == "aixm:Airspace"
    assert block.references["concernedAirportHeliport"][0].resolved and block.unresolved_references == []
    d = _dnotam(event)
    assert d.contract == "aixm-dnotam/1" and d.role == "event" and "2.0.m" in d.event_schema
    assert d.scenario.value == "RWY.CLS" and d.scenario_version.value == "2.0"
    assert d.profile is not None and d.profile_finding is None and d.rule_findings == []
    assert (d.profile.id, d.profile.version, d.profile.status, d.profile.guidance_page) == ("RWY.CLS", "2.0", "DRAFT", "220791360")
    assert d.profile.rules == ["RWY.CLS.01", "RWY.CLS.02", "RWY.CLS.03", "RWY.CLS.04", "RWY.CLS.05", "RWY.CLS.06"]
    assert "DRAFT" in d.profile.specification and d.profile.affected_features == ["aixm:RunwayDirection"]
    assert [n.element for n in d.notifications] == ["event:NOTAM"]
    notam = d.notifications[0]
    assert (notam.properties["type"].value, notam.properties["number"].value, notam.properties["series"].value) == ("N", "101", "S")
    assert notam.properties["estimatedEnd"].value == "NO" and notam.source["event:text"]["#text"].startswith("RWY 09 CLOSED")
    assert set(event.attributes) == {"aixm", "dnotam"}


def test_a_bound_feature_slice_carries_the_binding_the_scenario_and_keeps_the_extension_in_the_residual():
    objects = _read(RWY_CLS)
    baseline, tempdelta = _slices(objects, RWY_DIR)
    assert "dnotam" not in baseline.attributes, "the BASELINE is bound to no Event"
    assert baseline.status.state == "NORMAL" and tempdelta.status is None, \
        "two availability structures on the TEMPDELTA: the adapter asserts no status (D48); the resolver ranks them"
    d = _dnotam(tempdelta)
    assert d.role == "affected-feature" and d.extension_element == "event:RunwayDirectionExtension"
    assert d.extension_gml_id == "RDN_ZZSY_09_TD_1_0_EXT" and d.the_event.resolved and d.the_event.form == "urn-uuid"
    assert d.the_event.target.element == "event:Event" and d.the_event.key == EVENT_1
    assert d.event_scenario == "RWY.CLS" and d.rule_findings == [] and d.profile is None
    assert d.assertion.kind == "initial" and d.assertion.effective_from == "2026-03-10T06:00:00.000Z"
    assert d.assertion.effective_to == "2026-03-10T10:00:00.000Z" and d.assertion.notam_types == []
    availability = _block(tempdelta).availability
    assert [s.properties["operationalStatus"].value for s in availability] == ["NORMAL", "CLOSED"]
    left = tempdelta.residual.data["message:hasMember"][3]["aixm:timeSlice"][1]
    assert list(left) == ["aixm:extension"], "the extension is read and NOT consumed; the rest of the slice was typed"
    assert left["aixm:extension"][0]["event:theEvent"]["@xlink:href"] == "urn:uuid:" + EVENT_1
    twin = _twin(RWY_CLS)
    assert _ledger(twin, Aixm511Adapter().to_cdm(twin)).lost == ()


@pytest.mark.parametrize("path", XML_FILES + [CANCELLATION], ids=lambda p: p.stem)
def test_the_ledger_binds_every_leaf_of_every_document_with_no_loss(path):
    twin = _twin_of(_xml(path))
    objects = Aixm511Adapter(as_of=AS_OF).to_cdm(twin)
    ledger = _ledger(twin, objects)
    assert ledger.lost == (), [e.line() for e in ledger.lost[:5]]
    assert ledger.counts["MAPPED"] > 0 and ledger.counts.get("RESIDUAL", 0) > 0


def test_the_navaid_scenario_binds_the_equipment_class_and_types_its_availability():
    objects = _read(NAV_UNS)
    navaid_bl, navaid_td = _slices(objects, NAVAID)
    vor_bl, vor_td = _slices(objects, VOR)
    assert vor_td.entity_type == EntityType.UNKNOWN and _block(vor_td).feature.family == "other"
    assert _dnotam(vor_td).event_scenario == "NAV.UNS" and _dnotam(vor_td).extension_element == "event:VORExtension"
    assert _dnotam(vor_td).rule_findings == [], "a VOR is one of the NavaidEquipment specialisations NAV.UNS binds"
    assert "aixm:VOR" in NAVAID_EQUIPMENT_FEATURES and "aixm:VOR" in SCENARIO_PROFILES["NAV.UNS"].affected_features
    carried = _block(vor_td).availability
    assert len(carried) == 1 and carried[0].properties == {} and carried[0].source["aixm:operationalStatus"] == "UNSERVICEABLE"
    assert _block(navaid_td).properties["type"].value == "DME" and navaid_td.status.state == "PARTIAL"
    assert _block(navaid_td).properties["designator"].meaning == "unchanged"
    assert _dnotam(_slices(objects, "a1a40000-00e0-4000-8000-000000000004")[0]).profile.rules[-1] == "NAV.UNS.11"


def test_airspace_activation_scenarios_bind_both_pinned_identifiers():
    tma = _read(ATSA)
    event, = [o for o in tma if _block(o).feature.family == "Event"]
    assert _dnotam(event).profile.id == "ATSA.ACT" and _dnotam(event).profile.permitted_status == ["ACTIVE", "INACTIVE"]
    baseline, tempdelta = _slices(tma, "a1a40000-00d0-4000-8000-000000000003")
    assert baseline.status is None, "the baseline's activation is scheduled: typed, not asserted"
    assert tempdelta.status.state == "ACTIVE" and _dnotam(tempdelta).event_scenario == "ATSA.ACT"
    tsa = _read(SAA)
    event, = [o for o in tsa if _block(o).feature.family == "Event"]
    assert _dnotam(event).profile.id == "SAA.ACT" and _dnotam(event).profile.required_status == ["ACTIVE", "IN_USE", "INTERMITTENT"]
    tempdelta = _slices(tsa, "a1a40000-00d0-4000-8000-000000000004")[1]
    assert tempdelta.status is None and [s.properties["status"].value for s in _block(tempdelta).activation] == ["ACTIVE", "INACTIVE"]
    assert [len(s.time_interval) for s in _block(tempdelta).activation] == [1, 1]


# ------------------------------------------------------- the typed source assertions

def test_correction_termination_cancellation_and_replacement_are_typed_from_the_slice_alone():
    objects = _read(OUT_OF_ORDER)
    event_11, event_10 = _slices(objects, EVENT_1)
    assert [(o.source_ids[1].external_id.rsplit("/", 2)[-1]) for o in (event_11, event_10)] == ["1", "0"], "document order kept"
    a11, a10 = _dnotam(event_11).assertion, _dnotam(event_10).assertion
    assert (a10.kind, a10.notam_types, a10.effective_to, a10.lifetime_end) == (
        "initial", ["N"], "2026-03-10T10:00:00.000Z", "2026-03-10T10:00:00.000Z")
    assert (a11.kind, a11.notam_types, a11.effective_to, a11.lifetime_end) == (
        "termination", ["N", "C"], "2026-03-10T08:00:00.000Z", "2026-03-10T08:00:00.000Z")
    assert "NOTAM of type C" in a11.basis and "§3.6" in a11.basis
    td_11, td_10 = _slices(objects, RWY_DIR)[1:]
    assert _dnotam(td_11).assertion.kind == "correction" and _dnotam(td_10).assertion.kind == "initial"
    assert _dnotam(td_11).assertion.effective_to == "2026-03-10T08:00:00.000Z" and "TS_017" in _dnotam(td_11).assertion.basis
    # A replacement: the NOTAM type R on the Event slice (the guidance's new BASELINE with the NOTAMR).
    twin = copy.deepcopy(_twin(OUT_OF_ORDER))
    twin["message:hasMember"][0]["event:timeSlice"][1]["event:notification"][0]["event:type"] = "R"
    replaced = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], EVENT_1)[1]
    assert _dnotam(replaced).assertion.kind == "replacement" and "NOTAMR" in _dnotam(replaced).assertion.basis
    # A cancellation: the correction's empty validTime with nilReason (§4.4.8) — the as-of context
    # is needed for the Entity's valid_from, and the assertion says what the slice is.
    with pytest.raises(ValueError, match="cancelled-slice-needs-as-of"):
        Aixm511Adapter().to_cdm(_xml(CANCELLATION))
    cancelled = _read(CANCELLATION, as_of=AS_OF)
    event_10, event_11 = _slices(cancelled, EVENT_1)
    assert _dnotam(event_11).assertion.kind == "cancellation" and _dnotam(event_11).assertion.valid_time_form == "nil"
    assert "§4.4.8" in _dnotam(event_11).assertion.basis and _dnotam(event_11).assertion.notam_types == ["C"]
    assert _block(event_11).time_slice.feature_lifetime.form == "nil" and event_11.valid_from == AS_OF.instant
    assert _dnotam(event_10).assertion.kind == "initial", "the record of the cancelled sequence's first slice stands"
    td_10, td_11 = _slices(cancelled, RWY_DIR)[1:]
    assert _dnotam(td_11).assertion.kind == "cancellation" and _dnotam(td_11).the_event.resolved
    assert _block(td_11).availability == [], "a cancelling correction states no availability"


def test_expiry_is_the_stated_end_and_an_estimated_end_is_marked_as_such():
    objects = _read(EXPIRY)
    event = _slices(objects, EVENT_1)[0]
    a = _dnotam(event).assertion
    assert a.effective_to == "2026-03-10T10:00:00.000Z" and a.estimated_end is True and a.end_open is False
    assert _block(event).properties["estimatedValidity"].value == "2026-03-10T10:00:00Z"
    assert _dnotam(event).notifications[0].properties["estimatedEnd"].value == "YES"
    assert "end excluded" in a.convention
    plain = _slices(_read(RWY_CLS), EVENT_1)[0]
    assert _dnotam(plain).assertion.estimated_end is False
    # An open end (`indeterminatePosition="unknown"`) is typed as such, not as an expiry.
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][3]["aixm:timeSlice"][1]["gml:validTime"]["gml:endPosition"] = {"@indeterminatePosition": "unknown"}
    open_end = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], RWY_DIR)[1]
    assert _dnotam(open_end).assertion.end_open is True and _dnotam(open_end).assertion.effective_to is None and open_end.valid_to is None


def test_explicit_nils_are_typed_as_nil_and_a_nil_availability_is_a_withdrawal():
    objects = _read(NILS)
    event = _slices(objects, "a1a40000-00e0-4000-8000-000000000008")[0]
    block = _block(event)
    assert (block.properties["estimatedValidity"].state, block.properties["estimatedValidity"].meaning) == ("nil", "nil")
    assert (block.properties["activity"].state, block.properties["activity"].nil_reason) == ("nil", "unknown")
    assert _dnotam(event).assertion.estimated_end is False, "a nil estimatedValidity is not an estimate"
    baseline, tempdelta = _slices(objects, NAVAID)
    assert baseline.status.state == "OPERATIONAL"
    availability = _block(tempdelta).availability
    assert len(availability) == 1 and availability[0].nil is True and availability[0].source == {"@xsi:nil": "true", "@nilReason": "unknown"}
    assert tempdelta.status is None and _dnotam(tempdelta).event_scenario == "NAV.UNS"


def test_unresolved_bindings_and_references_are_kept_named_and_reported():
    adapter = Aixm511Adapter()
    objects = [o for o in adapter.to_cdm(_xml(UNRESOLVED)) if isinstance(o, Entity)]
    event, tempdelta = objects
    assert _block(event).unresolved_references == [
        "concernedAirspace -> 'urn:uuid:a1a40000-00d0-4000-8000-000000000007' (urn-uuid)",
        "concernedAirportHeliport -> 'urn:uuid:a1a40000-00d0-4000-8000-000000000001' (urn-uuid)"]
    d = _dnotam(tempdelta)
    assert d.the_event.resolved is False and d.the_event.href == "urn:uuid:a1a40000-00e0-4000-8000-000000000099"
    assert d.event_scenario is None and any("unresolved" in f for f in d.rule_findings)
    assert _block(tempdelta).unresolved_references == ["extension[0].theEvent -> 'urn:uuid:a1a40000-00e0-4000-8000-000000000099' (urn-uuid)"]
    problems = adapter.validate_source(_xml(UNRESOLVED))
    assert sum("unresolved reference" in p for p in problems) == 3
    # The caller's table resolves it — and says the scenario is not readable from a table entry.
    from synapse_cdm.adapters.aixm511 import ReferenceTarget
    table = Aixm511Adapter(references={"a1a40000-00e0-4000-8000-000000000099": ReferenceTarget(element="event:Event", identifier="a1a40000-00e0-4000-8000-000000000099", where="table")})
    tempdelta = [o for o in table.to_cdm(_xml(UNRESOLVED)) if isinstance(o, Entity)][1]
    assert _dnotam(tempdelta).the_event.resolved and _dnotam(tempdelta).the_event.target.where == "table"
    assert any("caller's table" in f for f in _dnotam(tempdelta).rule_findings)


# ------------------------------------------------------------------ the rule layer

def test_a_baseline_copy_restates_the_baseline_status_and_the_status_rule_passes_over_it():
    """ATSA.ACT ER-04 (SAA.ACT ER-06, NAV.UNS.08): the structures the encoder copies from the
    BASELINE for completeness carry the REMARK "Baseline data copy. Not included in the NOTAM
    text generation" and restate the baseline's own status — the pinned DN_ATSA.ACT_2 example
    copies an AVBL_FOR_ACTIVATION activation this way. The status rule judges the change's own
    structure only; the same value without the REMARK is the finding the rule exists for."""
    twin = copy.deepcopy(_twin(ATSA))
    activation = twin["message:hasMember"][2]["aixm:timeSlice"][1]["aixm:activation"]
    copied = copy.deepcopy(activation[0])
    copied["@gml:id"] = "ASE_TMA_TD_1_0_ACT2"
    copied["aixm:status"] = "AVBL_FOR_ACTIVATION"
    copied["aixm:annotation"] = [{"$": "aixm:Note", "@gml:id": "ASE_TMA_TD_1_0_ACT2_N", "aixm:purpose": "REMARK",
                                  "aixm:translatedNote": [{"$": "aixm:LinguisticNote", "@gml:id": "ASE_TMA_TD_1_0_ACT2_LN",
                                                           "aixm:note": {"@lang": "ENG", "#text": module.BASELINE_COPY_REMARK + "."}}]}]
    activation.append(copied)
    tma = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], "a1a40000-00d0-4000-8000-000000000003")[1]
    assert _dnotam(tma).rule_findings == []
    # Every copied structure is still translated and kept: two activations on the TEMPDELTA.
    assert [a.properties["status"].value for a in _block(tma).activation] == ["ACTIVE", "AVBL_FOR_ACTIVATION"]
    # The same value with another REMARK, or with no annotation, is the change's own statement.
    copied["aixm:annotation"][0]["aixm:translatedNote"][0]["aixm:note"]["#text"] = "Expect radar vectoring"
    tma = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], "a1a40000-00d0-4000-8000-000000000003")[1]
    assert _dnotam(tma).rule_findings == ["ATSA.ACT ER-01 (activation status: only ACTIVE or INACTIVE): status 'AVBL_FOR_ACTIVATION' is outside ['ACTIVE', 'INACTIVE']"]
    del copied["aixm:annotation"]
    tma = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], "a1a40000-00d0-4000-8000-000000000003")[1]
    assert len(_dnotam(tma).rule_findings) == 1
    # A required-status rule is not met by a copy either: the change itself must state CLOSED.
    twin = copy.deepcopy(_twin(RWY_CLS))
    availability = twin["message:hasMember"][3]["aixm:timeSlice"][1]["aixm:availability"]
    own = [a for a in availability if "aixm:annotation" not in a or "Baseline data copy" not in json.dumps(a["aixm:annotation"])]
    assert [a["aixm:operationalStatus"] for a in own] == ["CLOSED"]
    own[0]["aixm:operationalStatus"] = "NORMAL"
    rwy = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], RWY_DIR)[1]
    assert _dnotam(rwy).rule_findings == ["RWY.CLS RWY.CLS.03: no aixm:ManoeuvringAreaAvailability on the TEMPDELTA states operationalStatus in ['CLOSED']; stated: ['NORMAL']"]


def test_the_scenario_rule_layer_names_the_rule_it_applies():
    twin = copy.deepcopy(_twin(NAV_UNS))
    twin["message:hasMember"][4]["aixm:timeSlice"][1]["aixm:availability"][0]["aixm:operationalStatus"] = "FALSE_POSSIBLE"
    vor = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], VOR)[1]
    assert _dnotam(vor).rule_findings == ["NAV.UNS NAV.UNS.04: operationalStatus 'FALSE_POSSIBLE' cannot be used in this scenario"]
    twin = copy.deepcopy(_twin(ATSA))
    twin["message:hasMember"][2]["aixm:timeSlice"][1]["aixm:activation"][0]["aixm:status"] = "IN_USE"
    tma = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], "a1a40000-00d0-4000-8000-000000000003")[1]
    assert _dnotam(tma).rule_findings == ["ATSA.ACT ER-01 (activation status: only ACTIVE or INACTIVE): status 'IN_USE' is outside ['ACTIVE', 'INACTIVE']"]
    twin = copy.deepcopy(_twin(SAA))
    for item in twin["message:hasMember"][2]["aixm:timeSlice"][1]["aixm:activation"]:
        item["aixm:status"] = "INACTIVE"
    tsa = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], "a1a40000-00d0-4000-8000-000000000004")[1]
    # The second AirspaceActivation is the ER-06 baseline copy: it is not among the stated.
    assert _dnotam(tsa).rule_findings == ["SAA.ACT ER-02: no aixm:AirspaceActivation on the TEMPDELTA states status in ['ACTIVE', 'IN_USE', 'INTERMITTENT']; stated: ['INACTIVE']"]
    # The binding rule: a BASELINE bound to an Event, and an Event coded as a TEMPDELTA.
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][3]["aixm:timeSlice"][1]["aixm:interpretation"] = "BASELINE"
    bound = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], RWY_DIR)[1]
    assert _dnotam(bound).rule_findings[0].startswith("RWY.CLS RWY.CLS.02: the slice bound to the Event is BASELINE")
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][2]["event:timeSlice"][0]["aixm:interpretation"] = "TEMPDELTA"
    del twin["message:hasMember"][2]["event:timeSlice"][0]["aixm:featureLifetime"]
    event = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], EVENT_1)[0]
    assert _dnotam(event).rule_findings == ["RWY.CLS.01: an Event is coded as a BASELINE TimeSlice (a PERMDELTA may also be provided); this slice is TEMPDELTA"]


def test_an_unpinned_scenario_or_version_is_carried_with_a_finding_and_no_rule_is_invented():
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][2]["event:timeSlice"][0]["event:scenario"] = "OBS.NEW"
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    event = _slices(objects, EVENT_1)[0]
    assert _dnotam(event).profile is None and "'OBS.NEW' is not one of the pinned" in _dnotam(event).profile_finding
    assert _block(event).properties["scenario"].value == "OBS.NEW", "typed as stated"
    assert _dnotam(_slices(objects, RWY_DIR)[1]).event_scenario == "OBS.NEW"
    assert _dnotam(_slices(objects, RWY_DIR)[1]).rule_findings == [
        "the Event this slice is bound to states scenario 'OBS.NEW', not a pinned profile; no scenario rule is checked"]
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][2]["event:timeSlice"][0]["event:version"] = "1.0"
    event = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], EVENT_1)[0]
    assert _dnotam(event).profile.id == "RWY.CLS" and "pinned at version '2.0'" in _dnotam(event).profile_finding
    twin = copy.deepcopy(_twin(RWY_CLS))
    del twin["message:hasMember"][2]["event:timeSlice"][0]["event:scenario"]
    event = _slices([o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)], EVENT_1)[0]
    assert _dnotam(event).profile is None and "states no event:scenario" in _dnotam(event).profile_finding


def test_the_manifest_names_exactly_the_pinned_identifiers_and_rule_versions():
    assert sorted(SCENARIO_PROFILES) == ["ATSA.ACT", "NAV.UNS", "RWY.CLS", "SAA.ACT"]
    assert all(p.version == "2.0" and p.status == "DRAFT" for p in SCENARIO_PROFILES.values())
    declared = Aixm511Adapter.metadata.profiles
    assert declared == SCENARIO_PROFILE_DECLARATIONS and len(declared) == 4
    for profile in SCENARIO_PROFILES.values():
        line, = [d for d in declared if f"scenario {profile.id} version {profile.version}" in d]
        assert "DRAFT" in line and profile.guidance_page in line and profile.rules[0] in line and profile.rules[-1] in line
        assert "Event Schema 2.0.m" in line
    # The exported `manifests/aixm511.json` is the metadata by construction and is judged by
    # `python -m synapse_cdm.manifests --check` (a repository file; this module judges the package).
    limitation, = [lim for lim in Aixm511Adapter.metadata.limitations
                   if not isinstance(lim, str) and lim.id == "digital-notam-profiles"]
    assert "DRAFT" in limitation.summary and "aixm_resolve" in limitation.summary
    assert "approved final standard" in limitation.summary
    assert "approved" not in " ".join(declared).lower()


def test_a_wrong_scenario_code_mapping_is_caught():
    """Targeted negative: the profile table keyed by the WRONG identifier — RWY.CLS's rules
    served under NAV.UNS's key and vice versa — is caught by the invariant that a profile's
    `id` is the scenario the Event states, and by the rule layer refusing the fixture's own
    RunwayDirection binding."""
    swapped = dict(SCENARIO_PROFILES)
    swapped["RWY.CLS"], swapped["NAV.UNS"] = SCENARIO_PROFILES["NAV.UNS"], SCENARIO_PROFILES["RWY.CLS"]
    original = dict(SCENARIO_PROFILES)
    try:
        SCENARIO_PROFILES.clear()
        SCENARIO_PROFILES.update(swapped)
        objects = _read(RWY_CLS)
        event = _slices(objects, EVENT_1)[0]
        assert _dnotam(event).profile.id != _dnotam(event).scenario.value, "the mapping is wrong and the block shows it"
        tempdelta = _slices(objects, RWY_DIR)[1]
        assert _dnotam(tempdelta).rule_findings and "binds a <aixm:RunwayDirection> slice" in _dnotam(tempdelta).rule_findings[0]
    finally:
        SCENARIO_PROFILES.clear()
        SCENARIO_PROFILES.update(original)
    objects = _read(RWY_CLS)
    assert _dnotam(_slices(objects, EVENT_1)[0]).profile.id == "RWY.CLS"
    assert all(p.id == key for key, p in SCENARIO_PROFILES.items())
    assert _dnotam(_slices(objects, RWY_DIR)[1]).rule_findings == []


def test_the_adapter_stays_stateless_and_deterministic_across_documents_and_order():
    """Two documents about one feature are two independent readings — no state crosses; and
    the member order of one document does not change what any slice reads."""
    first = _dump(Aixm511Adapter().to_cdm(_xml(RWY_CLS)))
    _ = Aixm511Adapter().to_cdm(_xml(OUT_OF_ORDER))
    assert _dump(Aixm511Adapter().to_cdm(_xml(RWY_CLS))) == first
    adapter = Aixm511Adapter()
    adapter.to_cdm(_xml(OUT_OF_ORDER))
    assert _dump(adapter.to_cdm(_xml(RWY_CLS))) == first, "one adapter instance, two documents: nothing remembered"
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"].reverse()
    reordered = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    by_identity = {o.source_ids[1].external_id: o for o in reordered}
    for original in Aixm511Adapter().to_cdm(_xml(RWY_CLS)):
        if not isinstance(original, Entity):
            continue
        moved = by_identity[original.source_ids[1].external_id]
        before, after = original.attributes.get("dnotam"), moved.attributes.get("dnotam")
        if before and before.get("the_event"):
            # The one thing that moves with the member order is the target's position in the document.
            assert after["the_event"]["target"]["member_index"] != before["the_event"]["target"]["member_index"]
            before, after = copy.deepcopy(before), copy.deepcopy(after)
            before["the_event"]["target"]["member_index"] = after["the_event"]["target"]["member_index"] = 0
        assert after == before
        assert moved.entity_id == original.entity_id and moved.valid_from == original.valid_from
