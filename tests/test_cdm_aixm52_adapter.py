"""AIXM 5.2 adapter (#20, `adapters/aixm52.py` — a second profile on the 5.1.1 reader, on
`adapters/aixm_codec.py`), adapter expansion phase 6 (2026-09-21).

What is proved here, by section: the fixtures are what the record says, every one is the
generator's output and every twin is the parse of its XML (an independent ElementTree
re-derivation that lists the 5.2 repeatable properties by hand); every positive fixture is
VALID against the pinned AIXM 5.2.0 closure through an actual validator and INVALID against the
5.1.1 closure once its namespace is rewritten — so no fixture is a 5.1.1 document with the
namespace edited (BLOCKED, never PASS, without the resource); the 5.2 `REPEATABLE` table and the
pinned property paths are re-derived from the 5.2 schema; the version binding is real in both
directions; Digital NOTAM is declared unavailable on 5.2 consistently; then the Phase 4
requirement set on 5.2 documents — master §7's temporality, references, geometry and vertical
meaning, the §9 cross-cutting list, the 5.2 structures (the ElevatedPoint group, the repeated
`responsibleOrganisation` and `arrestingDevice`, the volume's `name` / `location`, the part's
`height`); four targeted negatives.
"""
from __future__ import annotations

import ast
import copy
import dataclasses
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
from synapse_cdm.adapters import aixm511
from synapse_cdm.adapters import aixm52 as module
from synapse_cdm.adapters import aixm_codec as codec
from synapse_cdm.adapters.aixm511 import Aixm511Adapter
from synapse_cdm.adapters.aixm52 import (
    AIXM52_MAX_DEPTH, AIXM52_MAX_ELEMENTS, AIXM52_MAX_INPUT_BYTES, AIXM52_MAX_OBJECTS,
    Aixm52Adapter, AsOf, ObjectCountExceeded, ReferenceTarget, TimeSliceBlock,
)
from synapse_cdm.evidence import digest
from synapse_cdm.models import CDMObject, Entity, PlanObject
from tests import normative_support

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "aixm52"
FIXTURES_511 = PKG / "fixtures" / "aixm511"
MALFORMED = FIXTURES / "malformed"
CASES = FIXTURES / "cases"
COUNTER = FIXTURES / "counterexamples"
SPEC = FIXTURES / "spec"
PIN = SPEC / "aixm52_pin.json"
XML_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".xml")
TWIN_FILES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".json")
BASELINE = FIXTURES / "airspace_baseline_polygon.xml"
DELTAS = FIXTURES / "airspace_deltas_same_feature.xml"
AERODROME = FIXTURES / "airport_runway_navaid.xml"
TOWER = FIXTURES / "vertical_structure_two_parts.xml"
HOLE = FIXTURES / "airspace_hole_crs84_snapshot.xml"
POSITIVE = XML_FILES + sorted(CASES.glob("*.xml"))
NS_52 = "http://www.aixm.aero/schema/5.2"
NS_511 = "http://www.aixm.aero/schema/5.1.1"
EVENT_511 = "http://www.aixm.aero/schema/5.1.1/event"


def _u(n: int) -> str:
    return f"a1a40000-0520-4000-8000-{n:012d}"


TSA1, AIRPORT, RUNWAY, DIRECTION, NAVAID, ORG, TOWER_ID, DANGER = (_u(n) for n in range(1, 9))
AS_OF = AsOf("2026-03-09T12:00:00Z", "the synthetic publication instant of the correction, stated by the fixture's author")
OBJECTS = TypeAdapter(list[CDMObject])


def _xml(path: pathlib.Path) -> bytes:
    return path.read_bytes()


def _twin(path: pathlib.Path) -> dict:
    return json.loads((path.parent / (path.stem + ".parsed.json")).read_text())


def _dump(objects):
    return [o if isinstance(o, dict) else o.model_dump(mode="json") for o in objects]


def _ledger(raw, objects, mappings=None):
    return lossless.ledger(raw, _dump(objects), mappings or Aixm52Adapter.MAPPINGS)


def _block(obj) -> TimeSliceBlock:
    return TimeSliceBlock.model_validate(obj.attributes["aixm"])


def _entities(objects, identifier: str | None = None) -> list[Entity]:
    return [o for o in objects if isinstance(o, Entity)
            and (identifier is None or o.source_ids[0].external_id == identifier)]


def _plans(objects) -> list[PlanObject]:
    return [o for o in objects if isinstance(o, PlanObject)]


def _twin_of(raw: bytes) -> dict:
    return codec.twin_of(secure_xml.parse(raw, module.XML_LIMITS).root, codec.VERSION_52)


def _as_511(raw: bytes) -> bytes:
    """The document with the 5.2 namespaces rewritten to 5.1.1 — what a namespace edit would be."""
    return raw.replace(NS_52.encode(), NS_511.encode())


def _slice(twin: dict, member: int = 0, s: int = 0) -> dict:
    return twin["message:hasMember"][member]["aixm:timeSlice"][s]


# ----------------------------------------------------------------- the fixtures themselves

def test_the_fixture_set_is_the_one_the_record_describes():
    assert [p.name for p in XML_FILES] == ["airport_runway_navaid.xml", "airspace_baseline_polygon.xml",
                                           "airspace_deltas_same_feature.xml", "airspace_hole_crs84_snapshot.xml",
                                           "vertical_structure_two_parts.xml"]
    assert [p.stem.removesuffix(".parsed") for p in TWIN_FILES] == [p.stem for p in XML_FILES]
    assert [p.name for p in XML_FILES] == [p.name for p in sorted(FIXTURES_511.glob("*.xml"))], "the Phase 4 set, mirrored"
    assert len(sorted(MALFORMED.glob("*.xml"))) == 17
    assert len(sorted(CASES.glob("*.xml"))) == 9
    assert len(sorted(COUNTER.glob("*.xml"))) == 6
    assert not (FIXTURES / "independent").exists(), "no independent 5.2 data set was pinned in Phase 0 (record: Remaining gaps)"
    pin = json.loads(PIN.read_text())
    assert pin["adapter"] == "aixm52" and pin["file_count"] == len(pin["files"])
    for rel, entry in pin["files"].items():
        assert digest(FIXTURES / rel) == (entry["sha256"], entry["bytes"]), rel
    assert all(str(p.relative_to(FIXTURES)) in pin["files"] for p in FIXTURES.rglob("*")
               if p.is_file() and "golden" not in p.parts and "__pycache__" not in p.parts
               and p.name not in ("PROVENANCE.json", "aixm52_pin.json"))


def test_the_generator_is_current_and_the_fixtures_are_its_output():
    """`spec/build_fixtures.py --check` rebuilds every fixture and twin in memory and compares;
    run with `-B` so no bytecode lands under `spec/`."""
    result = subprocess.run([sys.executable, "-B", str(SPEC / "build_fixtures.py"), "--check"],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(PKG.parent)})
    assert result.returncode == 0 and result.stdout.strip() == "CURRENT", result.stdout + result.stderr


def test_every_fixture_is_synthetic_by_default_and_names_no_real_place():
    for path in POSITIVE:
        for obj in Aixm52Adapter().to_cdm(_xml(path)):
            assert obj.source.synthetic is True
        text = path.read_text()
        assert "SYNTHETIC" in text and "a1a40000-0520-" in text, path.name
    assert Aixm52Adapter(synthetic=False).to_cdm(_xml(BASELINE))[0].source.synthetic is False


def test_every_parsed_twin_corresponds_to_its_raw_fixture():
    """The twin re-derived from the XML with the standard library ALONE — the object-property
    collapse spelled here by hand, the repeatable properties listed by hand, the 5.2 ones
    (`responsibleOrganisation`, `arrestingDevice`) among them — equals the committed twin."""
    prefixes = {NS_52: "aixm", NS_52 + "/message": "message", "http://www.opengis.net/gml/3.2": "gml",
                "http://www.w3.org/1999/xlink": "xlink", "http://www.w3.org/2001/XMLSchema-instance": "xsi"}
    always_list = {"message:hasMember", "aixm:timeSlice", "aixm:geometryComponent", "aixm:activation", "aixm:availability",
                   "aixm:timeInterval", "aixm:part", "aixm:navaidEquipment", "aixm:runwayDirection", "aixm:servedAirport",
                   "aixm:annotation", "aixm:translatedNote", "aixm:extension", "gml:patches", "gml:segments",
                   "gml:interior", "gml:curveMember", "gml:name", "aixm:servedCity", "aixm:contact",
                   "aixm:specialDateAuthority", "aixm:usage", "aixm:levels", "aixm:user", "aixm:aircraft", "aixm:class",
                   # AIXM 5.2: unbounded where 5.1.1 had one (responsibleOrganisation) or nothing (arrestingDevice).
                   "aixm:responsibleOrganisation", "aixm:arrestingDevice"}

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
        assert root.tag == "{" + NS_52 + "/message}AIXMBasicMessage"
        assert obj(root) == _twin(path), path.name
    aerodrome = _twin(AERODROME)
    assert isinstance(_slice(aerodrome)["aixm:responsibleOrganisation"], list) and len(_slice(aerodrome)["aixm:responsibleOrganisation"]) == 2
    assert isinstance(_slice(_twin(TOWER))["aixm:arrestingDevice"], list), "a 5.2 list even when the reading does not type it"


@pytest.mark.parametrize("path", XML_FILES, ids=lambda p: p.stem)
def test_the_xml_and_its_twin_translate_to_the_same_objects(path):
    assert _dump(Aixm52Adapter().to_cdm(_xml(path))) == _dump(Aixm52Adapter().to_cdm(_twin(path)))


@pytest.mark.normative
@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_every_positive_fixture_validates_against_the_pinned_schema(path):
    verdict = normative_support.verdict("aixm52", path.read_bytes())
    assert verdict.outcome.value == "VALID", verdict.describe()


@pytest.mark.normative
@pytest.mark.parametrize("path", POSITIVE, ids=lambda p: p.stem)
def test_every_positive_fixture_is_a_5_2_document_and_not_a_namespace_edit(path):
    """The same bytes with the 5.2 namespaces rewritten to 5.1.1 are INVALID against the 5.1.1
    closure: every positive document carries a structure 5.1.1 has no element for."""
    verdict = normative_support.verdict("aixm511", _as_511(path.read_bytes()))
    assert verdict.outcome.value == "INVALID", verdict.describe()
    assert "5.1.1" in verdict.describe() or "not expected" in verdict.describe() or "not a valid value" in verdict.describe()


#: Counterexample -> the layer that rejects it. Every one is well-formed and schema-INVALID; the
#: adapter's structural reading refuses only what it cannot read at all.
COUNTEREXAMPLE_LAYERS = {
    "unknown_property_in_slice.xml": "normative",
    "properties_out_of_order.xml": "normative",
    "status_outside_enumeration.xml": "normative",
    "foreign_extension_element.xml": "normative",
    "missing_interpretation.xml": "adapter+normative",
    "property_removed_in_5_2.xml": "normative",
}


@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_is_rejected_at_its_declared_layer(name):
    raw = (COUNTER / name).read_bytes()
    layer = COUNTEREXAMPLE_LAYERS[name]
    if layer.startswith("adapter"):
        with pytest.raises(ValueError):
            Aixm52Adapter().to_cdm(raw)
    else:
        objects = Aixm52Adapter().to_cdm(raw)
        assert objects, "the structural layer reads it; the schema breach is carried, not repaired"
        assert _ledger(_twin_of(raw), objects).lost == ()
    if name == "property_removed_in_5_2.xml":
        airport = _entities(Aixm52Adapter().to_cdm(raw), AIRPORT)[0]
        assert "fieldElevationAccuracy" not in _block(airport).properties, "a 5.1.1 property is not a 5.2 pinned one"
        assert _slice(airport.residual.data)["aixm:fieldElevationAccuracy"] == {"#text": "1", "@uom": "FT"}, "carried where it was"
    readme = (COUNTER / "README.md").read_text()
    assert name in readme and layer.split("+")[0] in readme


@pytest.mark.normative
@pytest.mark.parametrize("name", sorted(COUNTEREXAMPLE_LAYERS), ids=lambda n: n.removesuffix(".xml"))
def test_every_counterexample_is_invalid_against_the_pinned_schema(name):
    verdict = normative_support.verdict("aixm52", (COUNTER / name).read_bytes())
    assert verdict.outcome.value == "INVALID", verdict.describe()


# ------------------------------------------------------------- the 5.2 schema, re-derived

def _schema(root: pathlib.Path):
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
    return xs, types, elements, groups


def _group_members(xs, groups, name: str) -> list[tuple[str, str | None, str]]:
    """(name, type, maxOccurs) of every named element in a property group, in order."""
    return [(e.get("name"), e.get("type"), e.get("maxOccurs", "1"))
            for e in groups[name].iter(xs + "element") if e.get("name")]


@pytest.mark.normative
def test_the_repeatable_table_is_the_pinned_5_2_schemas():
    """The AIXM rows of `REPEATABLE_52`, re-derived from the pinned AIXM 5.2.0 XSD from the same
    seventeen roots as the 5.1.1 derivation (`tests/test_cdm_aixm_codec.py`); and the rows the
    module says 5.2 moved are exactly the rows that differ from the 5.1.1 table."""
    resource = normative_support.resource("aixm52")
    xs, types, elements, groups = _schema(pathlib.Path(resource.directory) / "aixm-5.2.0")

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

    for start in codec.REPEATABLE_ROOTS:
        visit(start)
    embedded = {k: tuple(v for v in codec.REPEATABLE_52[k] if not v.startswith("gml:") or v == "gml:name")
                for k in codec.REPEATABLE_52 if k.startswith("aixm:")}
    assert embedded == derived
    assert not any(k.startswith("event:") for k in codec.REPEATABLE_52), "no Event schema exists for 5.2"
    differing = {k for k in set(codec.REPEATABLE_52) | set(codec.REPEATABLE)
                 if not k.startswith("event:") and codec.REPEATABLE_52.get(k) != codec.REPEATABLE.get(k)}
    assert differing == set(codec.REPEATABLE_52_MOVED)
    assert codec.REPEATABLE_BY_VERSION == {"5.1.1": codec.REPEATABLE, "5.2": codec.REPEATABLE_52}


@pytest.mark.normative
def test_the_pinned_property_paths_are_the_5_2_schemas_and_the_differences_are_the_records():
    """Every pinned simple property of every family is a scalar of the 5.2 group; everything the
    module says 5.2 removed is absent from the 5.2 group and present in the 5.1.1 one, and
    everything it says 5.2 added is the reverse; the part properties and the ElevatedPoint group
    likewise. The record's difference table is held to both schemas."""
    xs52, types52, _, groups52 = _schema(pathlib.Path(normative_support.resource("aixm52").directory) / "aixm-5.2.0")
    xs511, _, _, groups511 = _schema(pathlib.Path(normative_support.resource("aixm511").directory) / "aixm-5.1.1")
    families = {"Airspace": "AirspacePropertyGroup", "AirportHeliport": "AirportHeliportPropertyGroup",
                "Runway": "RunwayPropertyGroup", "RunwayDirection": "RunwayDirectionPropertyGroup",
                "Navaid": "NavaidPropertyGroup", "VerticalStructure": "VerticalStructurePropertyGroup",
                "VerticalStructurePart": "VerticalStructurePartPropertyGroup",
                "AirspaceVolume": "AirspaceVolumePropertyGroup", "ElevatedPoint": "ElevatedPointPropertyGroup"}
    for family, group in families.items():
        names52 = [n for n, _, _ in _group_members(xs52, groups52, group)]
        names511 = [n for n, _, _ in _group_members(xs511, groups511, group)]
        for removed in module.REMOVED_IN_52.get(family, ()):
            assert removed in names511 and removed not in names52, (family, removed)
        for added in module.ADDED_IN_52.get(family, ()):
            assert added in names52 and added not in names511, (family, added)
    for element, (_, _, _, pinned) in module.FAMILIES.items():
        members = _group_members(xs52, groups52, families[element.split(":")[1]])
        scalar = {n for n, t, _ in members if t and (t.split(":")[-1] in types52) and
                  types52[t.split(":")[-1]].find(xs52 + "simpleContent") is not None}
        assert set(pinned) <= scalar, (element, set(pinned) - scalar)
        order = [n for n, _, _ in members if n in pinned]
        assert list(pinned) == order, f"{element}: pinned in the 5.2 group's order"
    part = [n for n, _, _ in _group_members(xs52, groups52, "VerticalStructurePartPropertyGroup")]
    assert set(module.PART_PROPERTIES) <= set(part) and "verticalExtentAccuracy" not in part
    elevated = [n for n, _, _ in _group_members(xs52, groups52, "ElevatedPointPropertyGroup")]
    assert tuple(elevated) == codec.VERSION_52.elevated == ("elevation", "geoidUndulation", "verticalDatum", "horizontalAccuracy", "annotation")
    assert "verticalAccuracy" in codec.VERSION_511.elevated
    datum = [t for n, t, _ in _group_members(xs52, groups52, "ElevatedPointPropertyGroup") if n == "verticalDatum"]
    assert datum == ["aixm:TextNameType"], "free text in 5.2"
    org = [m for n, _, m in _group_members(xs52, groups52, "AirportHeliportPropertyGroup") if n == "responsibleOrganisation"]
    assert org == ["unbounded"]
    # A 5.2 «object» may carry gml:identifier; a 5.1.1 one may not (AbstractAIXMObjectType).
    root52 = pathlib.Path(normative_support.resource("aixm52").directory) / "aixm-5.2.0"
    root511 = pathlib.Path(normative_support.resource("aixm511").directory) / "aixm-5.1.1"
    for root, expected in ((root52, True), (root511, False)):
        text = (root / "AIXM_AbstractGML_ObjectTypes.xsd").read_text()
        body = text[text.index('name="AbstractAIXMObjectType"'):]
        body = body[:body.index("</complexType>")]
        assert ('ref="gml:identifier"' in body) is expected


# --------------------------------------------------------------------- the version binding

def test_the_version_binding_is_real_in_both_directions():
    """aixm52 refuses a 5.1.1 document at the root and aixm511 refuses a 5.2 one; each names the
    namespace it read and the one it reads. `detect` answers False across the line, the
    malformed fixture is the 5.1.1-namespace case, and the two profiles disagree on what they are."""
    raw_511 = (FIXTURES_511 / "airspace_baseline_polygon.xml").read_bytes()
    raw_52 = _xml(BASELINE)
    with pytest.raises(ValueError, match=r"namespace 'http://www.aixm.aero/schema/5.1.1/message'.*reads AIXM 5.2"):
        Aixm52Adapter().to_cdm(raw_511)
    with pytest.raises(ValueError, match=r"namespace 'http://www.aixm.aero/schema/5.2/message'.*reads AIXM 5.1.1"):
        Aixm511Adapter().to_cdm(raw_52)
    with pytest.raises(ValueError, match="schema/5.1.1/message"):
        Aixm52Adapter().to_cdm(_xml(MALFORMED / "wrong_namespace_5_1_1.xml"))
    assert Aixm52Adapter().detect(raw_511) is False and Aixm511Adapter().detect(raw_52) is False
    assert Aixm52Adapter().detect(raw_52) is True and Aixm511Adapter().detect(raw_511) is True
    assert Aixm52Adapter.PROFILE.version is codec.VERSION_52 and Aixm511Adapter.PROFILE.version is codec.VERSION_511
    assert Aixm52Adapter.PROFILE.version.aixm != Aixm511Adapter.PROFILE.version.aixm
    assert _block(Aixm52Adapter().to_cdm(raw_52)[0]).aixm_version == "5.2"
    assert _block(Aixm511Adapter().to_cdm(raw_511)[0]).aixm_version == "5.1.1"
    # The same reader, two profiles: the pinned property sets differ exactly by the record's table.
    for element, (family, _, _, pinned52) in module.FAMILIES.items():
        pinned511 = aixm511.FAMILIES[element][3]
        assert set(pinned511) - set(pinned52) <= set(module.REMOVED_IN_52.get(family, ())), family
        assert set(pinned52) - set(pinned511) == set(module.ADDED_IN_52.get(family, ())) - {"arrestingDevice"}, family
    assert Aixm52Adapter.MAPPINGS != Aixm511Adapter.MAPPINGS
    assert not any(".event:" in k or "dnotam" in v.to for k, v in Aixm52Adapter.MAPPINGS.items())


def test_digital_notam_is_declared_unavailable_on_5_2_and_never_read():
    """Manifest, module and the reading agree: no profile, the limitation with its source, no
    `dnotam` block on any object, and a 5.1.1-namespace Event inside a 5.2 document named by
    `validate_source`, carried whole and typed by nothing."""
    limitation = {lim.id: lim for lim in Aixm52Adapter.metadata.limitations if not isinstance(lim, str)}["digital-notam-not-available"]
    assert Aixm52Adapter.metadata.profiles == [] and codec.VERSION_52.event is None
    assert module.DIGITAL_NOTAM_STATEMENT in limitation.summary and "aixm.aero/page/aixm-52" in limitation.summary
    assert "based on AIXM 5.1.1" in limitation.summary and Aixm52Adapter.PROFILE.digital_notam is False
    assert "Digital NOTAM" in module.__doc__ and "NOT AVAILABLE" in module.__doc__
    coverage = (PKG / "FORMAT_COVERAGE.md").read_text()
    section = coverage[coverage.index("## AIXM 5.2 ("):]
    section = section[:section.index("\n## ", 1)]
    assert "digital-notam-not-available" in section and "No Digital NOTAM Event schema exists for AIXM 5.2" in section
    repo = pathlib.Path(__file__).resolve().parent.parent
    for rel, needle in (("docs/docs/cdm/support-matrix.mdx", "No Digital NOTAM Event schema exists for AIXM 5.2"),
                        ("docs/adapter-expansion-implementation.md", "No Digital NOTAM Event schema exists for AIXM 5.2")):
        page = repo / rel
        if page.exists():                                     # the repository beside the tests, not the wheel
            assert needle in page.read_text(), rel
    for path in POSITIVE:
        for obj in _entities(Aixm52Adapter().to_cdm(_xml(path))):
            assert set(obj.attributes) == {"aixm"}
    event = (f'<message:hasMember><event:Event xmlns:event="{EVENT_511}" gml:id="uuid.{_u(900)}">'
             f'<gml:identifier codeSpace="urn:uuid:">{_u(900)}</gml:identifier><event:timeSlice>'
             '<event:EventTimeSlice gml:id="EV_BL"><aixm:interpretation>BASELINE</aixm:interpretation>'
             '<event:scenario>RWY.CLS</event:scenario></event:EventTimeSlice></event:timeSlice></event:Event></message:hasMember>')
    raw = _xml(BASELINE).replace(b"</message:AIXMBasicMessage>", event.encode() + b"</message:AIXMBasicMessage>")
    objects = Aixm52Adapter().to_cdm(raw)
    assert len(objects) == 2 and set(objects[0].attributes) == {"aixm"} and isinstance(objects[1], PlanObject)
    problems = Aixm52Adapter().validate_source(raw)
    assert any("Digital NOTAM event:Event" in p and "no Event schema exists for AIXM 5.2" in p
               and "digital-notam-not-available" in p for p in problems), problems
    carried = objects[0].residual.data["message:hasMember"][1]
    assert carried["$"] == "{" + EVENT_511 + "}Event" and "{" + EVENT_511 + "}timeSlice" in carried
    assert _ledger(_twin_of(raw), objects).lost == ()


# ------------------------------------------------------------- identity and temporality

def test_one_entity_per_time_slice_and_the_feature_identity_holds_across_slices_and_documents():
    baseline = Aixm52Adapter().to_cdm(_xml(BASELINE))
    deltas = Aixm52Adapter().to_cdm(_xml(DELTAS))
    assert [type(o).__name__ for o in baseline] == ["Entity", "PlanObject"]
    assert [type(o).__name__ for o in deltas] == ["Entity", "Entity", "Entity"]
    assert len({o.entity_id for o in _entities(baseline) + _entities(deltas)}) == 1
    assert all(o.source_ids[0].external_id == TSA1 for o in baseline + deltas)
    assert [o.source_ids[1].external_id for o in deltas] == [f"{TSA1}/TEMPDELTA/2/0", f"{TSA1}/TEMPDELTA/2/1", f"{TSA1}/PERMDELTA/3/0"]
    assert [o.source.original_id for o in deltas] == ["TSA1_TD_2_0", "TSA1_TD_2_1", "TSA1_PD_3_0"]
    assert _entities(Aixm52Adapter().to_cdm(_xml(HOLE)))[0].entity_id != _entities(baseline)[0].entity_id
    assert _entities(baseline)[0].entity_type.value == "OVERLAY_OBJECT"
    aerodrome = _entities(Aixm52Adapter().to_cdm(_xml(AERODROME)))
    assert [o.entity_type.value for o in aerodrome] == ["FACILITY"] * 4 + ["UNKNOWN"]
    other = _block(aerodrome[4])
    assert other.feature.family == "other" and other.feature.element == "aixm:OrganisationAuthority"
    assert aerodrome[4].position is None and aerodrome[4].status is None
    assert other.properties["name"].value == "SYNTHETIC AIRPORT OPERATOR"
    # The 5.2 identity rule: a volume's own gml:identifier is a property of the object, not an identity.
    block = _block(_entities(baseline)[0])
    source = block.geometry_components[0].source["aixm:theAirspaceVolume"]
    assert source["gml:identifier"] == {"#text": _u(21), "@codeSpace": "urn:uuid:"}
    assert block.feature.identifier == TSA1 and _u(21) not in json.dumps([str(o.entity_id) for o in _entities(baseline)])
    td0 = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))[0]
    assert _block(td0).activation[0].source["gml:identifier"]["#text"] == _u(22), "the 5.2 object identifier, carried"
    # The same feature under 5.1.1 and 5.2 is ONE entity: identity is the UUID, not the version.
    twin_511 = json.loads((FIXTURES_511 / "airspace_baseline_polygon.parsed.json").read_text())
    same = copy.deepcopy(twin_511)
    same["message:hasMember"][0]["gml:identifier"]["#text"] = TSA1
    assert Aixm511Adapter().to_cdm(same)[0].entity_id == _entities(baseline)[0].entity_id


def test_validity_is_the_slices_valid_time_under_the_begin_included_end_excluded_convention():
    baseline = _entities(Aixm52Adapter().to_cdm(_xml(BASELINE)))[0]
    assert baseline.valid_from == _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc) and baseline.valid_to is None
    block = _block(baseline)
    assert block.time_slice.valid_time.end.indeterminate == "unknown" and "§4.4.1" in block.time_slice.valid_time.convention
    assert block.time_slice.feature_lifetime.form == "period" and block.time_slice.valid_from_basis.endswith("gml:beginPosition")
    td0, td1, pd = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))
    assert (td0.valid_from.hour, td0.valid_to.hour) == (8, 16) and (td1.valid_from.hour, td1.valid_to.hour) == (8, 14)
    assert _block(td1).time_slice.correction_number == 1
    assert pd.valid_from == _dt.datetime(2026, 4, 1, tzinfo=_dt.timezone.utc) and pd.valid_to is None
    assert _block(pd).time_slice.valid_time.form == "instant"
    snapshot = _entities(Aixm52Adapter().to_cdm(_xml(HOLE)))[1]
    assert _block(snapshot).time_slice.interpretation == "SNAPSHOT"
    assert _block(snapshot).time_slice.sequence_number is None and _block(snapshot).time_slice.correction_number is None
    plan = _plans(Aixm52Adapter().to_cdm(_xml(BASELINE)))[0]
    assert plan.validity.valid_from == baseline.valid_from and plan.expires_at is None
    ended = _entities(Aixm52Adapter().to_cdm(_xml(CASES / "nil_absent_withdrawn.xml")))[0]
    assert ended.valid_to == _dt.datetime(2027, 1, 1, tzinfo=_dt.timezone.utc)


def test_absent_nil_unchanged_and_withdrawn_are_four_distinct_typed_states():
    baseline, delta = _entities(Aixm52Adapter().to_cdm(_xml(CASES / "nil_absent_withdrawn.xml")))
    b, d = _block(baseline).properties, _block(delta).properties
    assert (b["designator"].state, b["designator"].meaning, b["designator"].value) == ("stated", "stated", "SYNR1")
    assert (b["name"].state, b["name"].meaning, b["name"].nil_reason) == ("nil", "nil", "missing")
    assert (b["localType"].state, b["localType"].meaning) == ("absent", "not stated")
    assert (d["name"].state, d["name"].meaning, d["name"].nil_reason) == ("nil", "withdrawn", "inapplicable")
    assert (d["designator"].state, d["designator"].meaning) == ("absent", "unchanged")
    td0, _, pd = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))
    assert _block(pd).properties["localType"].meaning == "withdrawn" and _block(pd).properties["name"].value == "SYNTHETIC TSA ONE RENAMED"
    assert {p.meaning for p in _block(td0).properties.values()} == {"unchanged"}
    assert _block(td0).volume_projection == "none: the slice states no geometryComponent"


def test_a_cancelled_slice_needs_the_as_of_context_and_never_the_clock():
    raw = _xml(MALFORMED / "cancelled_slice_without_as_of.xml")
    with pytest.raises(ValueError, match="nilReason='inapplicable'.*as-of context.*Aixm52Adapter"):
        Aixm52Adapter().to_cdm(raw)
    with pytest.raises(ValueError, match="cancelled-slice-needs-as-of"):
        Aixm52Adapter(clock=lambda: _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    one = Aixm52Adapter(as_of=AS_OF, clock=lambda: _dt.datetime(2030, 1, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    two = Aixm52Adapter(as_of=AS_OF, clock=lambda: _dt.datetime(2031, 6, 1, tzinfo=_dt.timezone.utc)).to_cdm(raw)
    assert _dump(one) == _dump(two)
    entity = _entities(one)[0]
    assert entity.valid_from == AS_OF.instant and entity.valid_to is None
    block = _block(entity)
    assert block.time_slice.valid_time.form == "nil" and block.as_of["basis"] == AS_OF.basis
    assert any("§4.4.8" in note and AS_OF.basis in note for note in entity.source.transformations)
    assert "1970" not in json.dumps(_dump(one))
    with pytest.raises(TypeError):
        Aixm52Adapter(as_of="2026-01-01T00:00:00Z")


def test_the_temporality_rules_are_reported_by_validate_source_and_not_repaired():
    raw = _xml(CASES / "baseline_with_time_instant_ts001.xml")
    objects = Aixm52Adapter().to_cdm(raw)
    assert objects and _entities(objects)[0].valid_from == _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)
    problems = Aixm52Adapter().validate_source(raw)
    assert problems == [f"member 0 <aixm:Airspace> {_u(123)} slice 0: a BASELINE slice carries validTime/gml:TimeInstant; "
                        "TS_001 requires gml:TimePeriod"]
    assert _block(_entities(objects)[0]).time_slice.temporality_problems == problems
    twin = copy.deepcopy(_twin(DELTAS))
    _slice(twin, 0, 1)["aixm:correctionNumber"] = "0"
    assert any("TS_005" in p for p in Aixm52Adapter().validate_source(twin))
    twin = copy.deepcopy(_twin(DELTAS))
    _slice(twin)["gml:validTime"]["gml:beginPosition"] = "2026-03-10T10:00:00+02:00"
    assert _entities(Aixm52Adapter().to_cdm(twin))[0].valid_from == _dt.datetime(2026, 3, 10, 8, tzinfo=_dt.timezone.utc)
    assert any("TS_012" in p for p in Aixm52Adapter().validate_source(twin))


# ----------------------------------------------------------------------------- references

def test_references_are_resolved_in_every_form_kept_when_they_are_not_and_a_cycle_is_two_hops():
    objects = Aixm52Adapter().to_cdm(_xml(AERODROME))
    runway = _block(_entities(objects, RUNWAY)[0])
    airport_ref = runway.references["associatedAirportHeliport"]
    assert airport_ref.form == "urn-uuid" and airport_ref.resolved and airport_ref.target.element == "aixm:AirportHeliport"
    direction = _block(_entities(objects, DIRECTION)[0])
    assert direction.references["usedRunway"].form == "local-id" and direction.references["usedRunway"].resolved
    navaid = _block(_entities(objects, NAVAID)[0])
    assert [r.resolved for r in navaid.references["servedAirport"]] == [True]
    assert len(navaid.unresolved_references) == 2 and all("theNavaidEquipment" in u for u in navaid.unresolved_references)
    assert [c.equipment.form for c in navaid.navaid_equipment] == ["urn-uuid", "urn-uuid"]
    table = {_u(11): ReferenceTarget(element="aixm:VOR", where="table")}
    resolved = _block(_entities(Aixm52Adapter(references=table).to_cdm(_xml(AERODROME)), NAVAID)[0])
    assert resolved.navaid_equipment[0].equipment.resolved and resolved.navaid_equipment[0].equipment.target.where == "table"
    assert len(resolved.unresolved_references) == 1
    forms = Aixm52Adapter().to_cdm(_xml(CASES / "reference_forms.xml"))
    d1, d2 = (_block(_entities(forms, _u(108))[0]), _block(_entities(forms, _u(109))[0]))
    assert (d1.references["usedRunway"].form, d1.references["usedRunway"].resolved) == ("local-id", True)
    assert (d1.references["startingElement"].form, d1.references["startingElement"].resolved) == ("url", False)
    assert (d2.references["usedRunway"].form, d2.references["startingElement"].form) == ("natural-key", "other")
    assert len(Aixm52Adapter().validate_source(_xml(CASES / "reference_forms.xml"))) == 3
    cyclic = Aixm52Adapter().to_cdm(_xml(CASES / "composite_and_cyclic_contributors.xml"))
    a, b = (_block(e) for e in _entities(cyclic))
    assert a.geometry_components[0].volume.contributor.airspace.resolved and b.geometry_components[0].volume.contributor.airspace.resolved
    assert a.geometry_components[0].volume.contributor.airspace.target.member_index == 1
    assert not _plans(cyclic) and a.volume_projection.startswith("none: component 0 operation 'UNION'")


def test_the_adapter_resolves_no_reference_over_a_network_and_touches_no_file():
    for path in (pathlib.Path(module.__file__), pathlib.Path(aixm511.__file__), pathlib.Path(codec.__file__)):
        tree = ast.parse(path.read_text())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        imports = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
            (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not imports & {"socket", "urllib", "http", "requests", "ssl", "subprocess", "os", "pathlib"}, path.name
        assert "open" not in names and "urlopen" not in names, path.name
    raw = _xml(CASES / "reference_forms.xml")
    block = _block(_entities(Aixm52Adapter().to_cdm(raw), _u(108))[0])
    assert block.references["startingElement"].href.startswith("https://example.invalid/")


# --------------------------------------------------------------------------------- geometry

def test_epsg4326_and_crs84_encodings_of_the_same_numbers_are_two_different_places():
    epsg = _plans(Aixm52Adapter().to_cdm(_xml(CASES / "axis_order_epsg4326.xml")))[0]
    crs84 = _plans(Aixm52Adapter().to_cdm(_xml(CASES / "axis_order_crs84.xml")))[0]
    assert epsg.geometry.coordinates == crs84.geometry.coordinates
    assert epsg.geometry.coordinates[0][0] == [5.2, 52.1], "canonical is [lon, lat]"
    airport = _entities(Aixm52Adapter().to_cdm(_xml(AERODROME)), AIRPORT)[0]
    navaid = _entities(Aixm52Adapter().to_cdm(_xml(AERODROME)), NAVAID)[0]
    assert (airport.position.lat, airport.position.lon) == (52.30833, 4.76389), "EPSG:4326: latitude first"
    assert (navaid.position.lat, navaid.position.lon) == (52.31, 4.8), "CRS84: longitude first"
    block = _block(airport)
    assert block.arp.point.crs.axis_order == ("latitude", "longitude") and block.arp.point.pos_text == "52.30833 4.76389"


def test_the_pinned_surface_forms_holes_and_the_interior_ring_of_curves_land_on_the_area():
    hole = Aixm52Adapter().to_cdm(_xml(HOLE))
    plan = _plans(hole)[0]
    assert plan.geometry.type == "Polygon" and len(plan.geometry.coordinates) == 2
    assert plan.geometry.coordinates[1][0] == [6.2, 51.2] and plan.label == "SYND1"
    block = _block(_entities(hole)[0])
    surface = block.geometry_components[0].volume.horizontal_projection
    patch = surface.patches[0]
    assert (patch.exterior.role, [r.role for r in patch.interiors]) == ("exterior", ["interior"])
    assert patch.exterior.curves[0].segments[0].interpolation == "linear" and patch.interiors[0].element == "gml:LinearRing"
    ring = Aixm52Adapter().to_cdm(_xml(CASES / "interior_ring_of_curves.xml"))
    assert len(_plans(ring)[0].geometry.coordinates) == 2
    assert _block(_entities(ring)[0]).geometry_components[0].volume.horizontal_projection.patches[0].interiors[0].element == "gml:Ring"
    baseline = _block(_entities(Aixm52Adapter().to_cdm(_xml(BASELINE)))[0])
    assert baseline.geometry_components[0].volume.horizontal_projection.patches[0].exterior.curves[0].segments[0].interpolation == "geodesic"
    assert baseline.volume_projection == "Polygon" and baseline.plan_object_id is not None


def test_arcs_and_circles_are_refused_by_default_and_typed_with_their_source_under_report():
    for name, form in (("arc_by_centre_point_airspace.xml", "gml:ArcByCenterPoint"),
                       ("circle_by_centre_point_airspace.xml", "gml:CircleByCenterPoint")):
        raw = _xml(MALFORMED / name)
        with pytest.raises(ValueError, match=form + ".*unsupported-geometry-refused.*Aixm52Adapter"):
            Aixm52Adapter().to_cdm(raw)
        objects = Aixm52Adapter(unsupported_geometry="report").to_cdm(raw)
        assert [type(o).__name__ for o in objects] == ["Entity"], "no PlanObject, no chord, no polygon"
        block = _block(objects[0])
        unsupported = block.geometry_components[0].volume.unsupported[0]
        assert unsupported.element == form and unsupported.kind == "segment" and "52.25 5.25" in json.dumps(unsupported.source)
        assert block.volume_projection == "none: component 0 states no projectable horizontalProjection (stated, segment)"
        assert any(form in p for p in Aixm52Adapter(unsupported_geometry="report").validate_source(raw))
        assert _ledger(_twin_of(raw), objects).lost == ()
    with pytest.raises(ValueError):
        Aixm52Adapter(unsupported_geometry="chord")


def test_other_crs_forms_and_a_third_dimension_are_refused_with_the_form_named():
    with pytest.raises(ValueError, match="EPSG::3857"):
        Aixm52Adapter().to_cdm(_xml(MALFORMED / "unsupported_crs_epsg3857.xml"))
    with pytest.raises(ValueError, match="srsDimension 3"):
        Aixm52Adapter().to_cdm(_xml(MALFORMED / "three_dimensional_positions.xml"))
    with pytest.raises(ValueError, match="not closed"):
        Aixm52Adapter().to_cdm(_xml(MALFORMED / "unclosed_ring.xml"))
    reported = _block(Aixm52Adapter(unsupported_geometry="report").to_cdm(_xml(MALFORMED / "unsupported_crs_epsg3857.xml"))[0])
    assert reported.geometry_components[0].volume.unsupported[0].kind == "crs"


# --------------------------------------------------------------------------------- vertical

def _upper(plan):
    v = plan.area.vertical.upper
    return (v.value, v.unit.value, v.reference.value)


def test_vertical_limits_project_member_for_member_and_feet_to_metres_does_not_change_the_datum():
    objects = Aixm52Adapter().to_cdm(_xml(CASES / "vertical_references.xml"))
    plans = {p.label: p for p in _plans(objects)}
    blocks = {_block(e).properties["designator"].value: _block(e) for e in _entities(objects)}
    assert _upper(plans["VFTSFC"]) == (1000.0, "ft", "AGL") and _upper(plans["VFTMSL"]) == (5000.0, "ft", "MSL")
    assert _upper(plans["VMW84"]) == (300.0, "m", "HAE") and _upper(plans["VFLSTD"]) == (245.0, "FL", "FL")
    assert _upper(plans["VFTSTD"]) == (10000.0, "ft", "BARO")
    assert plans["VFTSFC"].area.vertical.lower.value == 0.0, "a zero floor is a real floor"
    for designator in ("VSM", "VFLMSL", "VUNL", "VNIL", "VFLOOR"):
        volume = blocks[designator].geometry_components[0].volume
        assert volume.upper.cdm is None and volume.upper.not_projected, designator
    assert blocks["VUNL"].geometry_components[0].volume.upper.kind == "unlimited"
    assert blocks["VNIL"].geometry_components[0].volume.upper.kind == "unknown"
    assert blocks["VGND"].geometry_components[0].volume.lower.kind == "ground"
    assert blocks["VFLOOR"].geometry_components[0].volume.lower.kind == "floor"
    assert blocks["VNOREF"].geometry_components[0].volume.upper.cdm is not None
    assert blocks["VNOREF"].geometry_components[0].volume.upper.cdm.reference == "UNKNOWN", "no reference stated is not a datum"
    assert plans["VFTSFC"].area.vertical.upper.unit.value == "ft", "feet stay feet"
    assert "1000" in json.dumps(blocks["VFTSFC"].geometry_components[0].source) and "304.8" not in json.dumps(_dump(objects))


def test_positions_are_surveyed_fixes_with_the_5_2_elevated_point_group_and_alt_m_none():
    """The 5.2 ElevatedPoint: elevation MSL by definition, verticalDatum free text, the geoid
    undulation typed, `vertical_accuracy` None (no such property in 5.2), horizontalAccuracy in
    the verbatim source; the Entity's position is the surveyed fix with the MSL elevation."""
    aerodrome = Aixm52Adapter().to_cdm(_xml(AERODROME))
    airport = _entities(aerodrome, AIRPORT)[0]
    assert airport.position.position_source.value == "MANUAL" and airport.position.alt_m is None
    assert (airport.position.vertical.value, airport.position.vertical.unit.value, airport.position.vertical.reference.value) == (12.0, "ft", "MSL")
    arp = _block(airport).arp
    assert arp.elevation.vertical_accuracy is None, "a property the 5.2 schema cannot state is not 'not stated'"
    assert arp.elevation.vertical_datum.value == "EGM 96 GEOID (free text in 5.2)"
    assert arp.elevation.geoid_undulation.value == "43.5" and arp.elevation.geoid_undulation.uom == "M"
    assert arp.source["aixm:horizontalAccuracy"] == {"#text": "1", "@uom": "M"}
    assert "aixm:verticalAccuracy" not in arp.source
    navaid = _entities(aerodrome, NAVAID)[0]
    assert (navaid.position.vertical.value, navaid.position.vertical.unit.value) == (15.0, "m")
    tower = _entities(Aixm52Adapter().to_cdm(_xml(TOWER)))[0]
    assert (tower.position.lat, tower.position.lon, tower.position.vertical.value) == (52.4, 5.1, 250.0)
    parts = _block(tower).parts
    assert parts[0].location_elevation.vertical_accuracy is None
    assert [p.properties["height"].value for p in parts] == ["120", "15"], "the 5.2 part height, typed"
    assert all("verticalExtentAccuracy" not in p.properties for p in parts)
    assert [p.properties["verticalExtent"].uom for p in parts] == ["M", "M"]
    # The same reader under the 5.1.1 profile still reads the 5.1.1 group: the version is the switch.
    arp_511 = _block(_entities(Aixm511Adapter().to_cdm((FIXTURES_511 / "airport_runway_navaid.xml").read_bytes()), "a1a40000-0002-4000-8000-000000000001")[0]).arp
    assert arp_511.elevation.vertical_accuracy is not None


def test_zero_values_are_real_and_missing_stays_missing():
    twin = copy.deepcopy(_twin(AERODROME))
    arp = _slice(twin)["aixm:ARP"]
    arp["gml:pos"] = "0.0 0.0"
    arp["aixm:elevation"]["#text"] = "0"
    _slice(twin)["aixm:magneticVariation"] = "0"
    _slice(twin, 2)["aixm:slope"] = "0"
    objects = Aixm52Adapter().to_cdm(twin)
    airport = _entities(objects, AIRPORT)[0]
    assert (airport.position.lat, airport.position.lon, airport.position.vertical.value) == (0.0, 0.0, 0.0)
    assert _block(airport).properties["magneticVariation"].value == "0"
    assert _block(_entities(objects, DIRECTION)[0]).properties["slope"].value == "0"
    twin = copy.deepcopy(_twin(AERODROME))
    del _slice(twin)["aixm:ARP"]
    del _slice(twin)["aixm:timeZone"]
    airport = _entities(Aixm52Adapter().to_cdm(twin), AIRPORT)[0]
    assert airport.position is None and _block(airport).arp is None
    assert _block(airport).properties["timeZone"].state == "absent" and _block(airport).properties["timeZone"].meaning == "not stated"


# ------------------------------------------------------------------- status and schedules

def test_status_is_asserted_only_from_one_unconditional_structure_and_schedules_stay_typed():
    aerodrome = Aixm52Adapter().to_cdm(_xml(AERODROME))
    airport, direction, navaid = (_entities(aerodrome, i)[0] for i in (AIRPORT, DIRECTION, NAVAID))
    assert (airport.status.state, airport.status.namespace) == ("NORMAL", "AIXM 5.2 CodeStatusAirportType")
    assert (navaid.status.state, navaid.status.namespace) == ("OPERATIONAL", "AIXM 5.2 CodeStatusNavaidType")
    assert direction.status is None, "CLOSED under a Timesheet is typed, not asserted"
    closure = _block(direction).availability[0]
    assert closure.properties["operationalStatus"].value == "CLOSED" and closure.properties["warning"].value == "WIP"
    assert [(t.properties["day"].value, t.properties["startTime"].value, t.properties["endTime"].value)
            for t in closure.time_interval] == [("ANY", "22:00", "06:00")]
    baseline = _entities(Aixm52Adapter().to_cdm(_xml(BASELINE)))[0]
    assert baseline.status is None and _block(baseline).activation[0].properties["status"].value == "AVBL_FOR_ACTIVATION"
    td0 = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))[0]
    assert (td0.status.state, td0.status.namespace) == ("ACTIVE", "AIXM 5.2 CodeStatusAirspaceType")
    snapshot = _entities(Aixm52Adapter().to_cdm(_xml(HOLE)))[1]
    assert snapshot.status.state == "INACTIVE"


# ---------------------------------------------------------------------- residual and ledger

def test_the_residual_is_the_source_structure_minus_what_was_typed_with_the_5_2_additions_where_declared():
    objects = Aixm52Adapter().to_cdm(_xml(AERODROME))
    airport = _entities(objects, AIRPORT)[0]
    residual = airport.residual.data
    assert airport.residual.namespace == "AIXM"
    members = residual["message:hasMember"]
    assert len(members) == 5 and members[1:] == [None] * 4, "the other features' members are their own objects (null at their positions)"
    own = _slice(residual)
    assert list(own) == ["aixm:responsibleOrganisation"], "the 5.2 repeated organisation is the only untyped property"
    assert [o["aixm:role"] for o in own["aixm:responsibleOrganisation"]] == ["OPERATE", "OWN"]
    assert "aixm:timeZone" not in own and "aixm:segmentedCircleMarker" not in own, "typed, so consumed"
    tower = _entities(Aixm52Adapter().to_cdm(_xml(TOWER)))[0]
    assert list(_slice(tower.residual.data)) == ["aixm:arrestingDevice"]
    assert [a["@xlink:href"] for a in _slice(tower.residual.data)["aixm:arrestingDevice"]] == ["urn:uuid:" + _u(31), "urn:uuid:" + _u(32)]
    baseline = _entities(Aixm52Adapter().to_cdm(_xml(BASELINE)))[0]
    volume = _block(baseline).geometry_components[0].source["aixm:theAirspaceVolume"]
    assert volume["aixm:name"] == "SYNTHETIC TSA ONE VOLUME" and volume["aixm:location"]["$"] == "aixm:Point"
    assert volume["aixm:location"]["gml:pos"] == "52.25 5.25"
    assert "aixm:geometryComponent" not in _slice(baseline.residual.data), "consumed whole, carried at its block field"
    assert list(_slice(baseline.residual.data)) == ["aixm:annotation"]
    deltas = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))
    assert [_slice(d.residual.data, 0, i) if "aixm:timeSlice" in d.residual.data["message:hasMember"][0] else None
            for i, d in enumerate(deltas)] == [None, None, None], "a fully typed slice leaves nothing"


def test_a_feature_outside_the_families_carries_what_the_ledger_binds_and_loses_nothing():
    raw = _xml(CASES / "other_feature_location_availability.xml")
    objects = Aixm52Adapter().to_cdm(raw)
    dme, taxiway = _entities(objects)
    assert dme.entity_type.value == "UNKNOWN" and dme.position is None and dme.status is None
    block = _block(dme)
    assert block.feature.family == "other" and block.location.point is not None and block.location.point.latitude == 52.5
    assert block.location.elevation.vertical_accuracy is None
    assert "aixm:availability" not in _slice(dme.residual.data) and len(block.availability) == 1, "a single availability on a NavaidEquipment class is listed by REPEATABLE_52 (D53), so it is carried"
    assert _slice(dme.residual.data)["aixm:tuningFrequencyVHF"] == {"#text": "113.7", "@uom": "MHZ"}, "5.2's DME property, in the residual"
    assert len(_block(taxiway).availability) == 2 and _block(taxiway).availability[1].time_interval
    assert any("outside the five pinned families" in p for p in Aixm52Adapter().validate_source(raw))
    assert _ledger(_twin_of(raw), objects).lost == ()


def test_unknown_members_and_attributes_are_preserved_at_their_position():
    twin = copy.deepcopy(_twin(BASELINE))
    _slice(twin)["@syn:origin"] = "test"
    _slice(twin)["{urn:synthetic:ext}colour"] = "RED"
    twin["message:hasMember"].append({"$": "aixm:Note", "@gml:id": "N_X", "aixm:purpose": "REMARK"})
    objects = Aixm52Adapter().to_cdm(twin)
    residual = objects[0].residual.data
    assert _slice(residual)["@syn:origin"] == "test" and _slice(residual)["{urn:synthetic:ext}colour"] == "RED"
    assert residual["message:hasMember"][1] == {"$": "aixm:Note", "@gml:id": "N_X", "aixm:purpose": "REMARK"}
    assert _ledger(twin, objects).lost == ()
    assert any("not an AIXM feature" in p for p in Aixm52Adapter().validate_source(twin))


#: Every document the adapter reads: the positives and the five counterexamples the structural
#: layer accepts (`missing_interpretation.xml` is refused at that layer and has nothing to ledger).
LEDGERED = POSITIVE + sorted(p for p in COUNTER.glob("*.xml") if COUNTEREXAMPLE_LAYERS[p.name] == "normative")


@pytest.mark.parametrize("path", LEDGERED, ids=lambda p: p.stem)
def test_the_ledger_binds_every_leaf_of_every_fixture_with_no_loss(path):
    raw = _xml(path)
    adapter = Aixm52Adapter(unsupported_geometry="report")
    twin = _twin_of(raw)
    ledger = _ledger(twin, adapter.to_cdm(twin))
    assert ledger.lost == (), [e.line() for e in ledger.lost[:5]]
    assert ledger.counts["MAPPED"] > 0


def test_repeated_identical_values_cannot_conceal_a_value_on_the_wrong_slice():
    td0, td1, _ = _entities(Aixm52Adapter().to_cdm(_xml(DELTAS)))
    assert td0.valid_from == td1.valid_from and td0.status.state == td1.status.state
    assert (td0.valid_to.hour, td1.valid_to.hour) == (16, 14)
    aerodrome = Aixm52Adapter().to_cdm(_xml(AERODROME))
    airport = _entities(aerodrome, AIRPORT)[0]
    assert _block(airport).properties["fieldElevation"].value == "12" == _block(airport).arp.elevation.elevation.value
    twin = copy.deepcopy(_twin(AERODROME))
    _slice(twin)["aixm:ARP"]["aixm:elevation"]["#text"] = "13"
    moved = _entities(Aixm52Adapter().to_cdm(twin), AIRPORT)[0]
    assert moved.position.vertical.value == 13.0 and _block(moved).properties["fieldElevation"].value == "12"
    tower = _block(_entities(Aixm52Adapter().to_cdm(_xml(TOWER)))[0])
    assert tower.parts[0].properties["verticalExtent"].value == tower.parts[0].properties["height"].value == "120"
    twin = copy.deepcopy(_twin(TOWER))
    _slice(twin)["aixm:part"][0]["aixm:height"]["#text"] = "121"
    tower = _block(_entities(Aixm52Adapter().to_cdm(twin))[0])
    assert (tower.parts[0].properties["verticalExtent"].value, tower.parts[0].properties["height"].value) == ("120", "121")


def test_the_typed_blocks_validate_against_the_contract_and_the_manifest_matches_the_module():
    for path in XML_FILES:
        for obj in _entities(Aixm52Adapter().to_cdm(_xml(path))):
            block = TimeSliceBlock.model_validate(obj.attributes["aixm"])
            assert block.contract == "aixm-timeslice/1" and block.aixm_version == "5.2"
            assert set(obj.attributes) == {"aixm"}
    limits = Aixm52Adapter.metadata.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (
        AIXM52_MAX_INPUT_BYTES, AIXM52_MAX_DEPTH, AIXM52_MAX_OBJECTS)
    assert module.XML_LIMITS == secure_xml.XmlLimits(AIXM52_MAX_INPUT_BYTES, AIXM52_MAX_DEPTH, AIXM52_MAX_ELEMENTS)
    assert Aixm52Adapter.PROFILE.xml_limits is module.XML_LIMITS and Aixm52Adapter.PROFILE.max_objects == AIXM52_MAX_OBJECTS
    for name in ("max_input_bytes", "max_depth", "max_objects"):
        test = limits.declared_because[name].test
        module_name, test_name = test.split("::")
        assert test_name in (pathlib.Path(__file__).resolve().parent / pathlib.Path(module_name).name).read_text(), test
    assert Aixm52Adapter.direction == "ingest" and Aixm52Adapter.metadata.residual.value == "structured"
    assert {lim.id for lim in Aixm52Adapter.metadata.limitations if not isinstance(lim, str)} == {
        "pinned-families", "digital-notam-not-available", "unsupported-geometry-refused", "composite-volumes-not-drawn",
        "vertical-projection-by-member", "cancelled-slice-needs-as-of", "identifier-required", "references-one-hop",
        "schedules-not-resolved"}
    # `evidence.available` moved false -> true in the 3.1.0 release commit (2026-09-21): the first
    # release carrying this adapter attaches its records; `tests/test_cdm_evidence.py` holds the value.
    assert Aixm52Adapter.metadata.maturity.level.value == "L3" and Aixm52Adapter.metadata.evidence.available is True
    assert Aixm52Adapter.MAPPINGS[""].to == "*:residual.data"
    assert "5.2.0" in Aixm52Adapter.metadata.format.version and "17 January 2025" in Aixm52Adapter.metadata.format.version
    assert Aixm52Adapter.metadata.id == Aixm52Adapter.name == "aixm52"
    with pytest.raises(NotImplementedError, match="does not emit"):
        Aixm52Adapter().from_cdm([])


# ------------------------------------------------------------------------------ refusals

REFUSALS = {
    "arc_by_centre_point_airspace.xml": (ValueError, "gml:ArcByCenterPoint"),
    "billion_laughs_dtd.xml": (secure_xml.XmlRefused, "DOCTYPE"),
    "cancelled_slice_without_as_of.xml": (ValueError, "as-of context"),
    "circle_by_centre_point_airspace.xml": (ValueError, "gml:CircleByCenterPoint"),
    "end_before_begin.xml": (ValueError, "SEM-00"),
    "feature_without_identifier.xml": (ValueError, "no gml:identifier"),
    "no_feature_member.xml": (ValueError, "no AIXM feature"),
    "non_integer_sequence_number.xml": (ValueError, "not an integer"),
    "three_dimensional_positions.xml": (ValueError, "srsDimension 3"),
    "truncated_document.xml": (secure_xml.XmlRefused, "not well-formed"),
    "unclosed_ring.xml": (ValueError, "not closed"),
    "unknown_interpretation.xml": (ValueError, "'CURRENT' is not one of"),
    "unresolved_entity_reference.xml": (secure_xml.XmlRefused, "entity"),
    "unsupported_crs_epsg3857.xml": (ValueError, "EPSG::3857"),
    "wrong_namespace_5_1_1.xml": (ValueError, "schema/5.1.1/message"),
    "wrong_root_element.xml": (ValueError, "not <message:AIXMBasicMessage>"),
    "xinclude_element.xml": (secure_xml.XmlRefused, "XInclude"),
}


def test_every_malformed_payload_is_refused_by_name():
    assert sorted(REFUSALS) == sorted(p.name for p in MALFORMED.glob("*.xml"))
    for name, (kind, text) in REFUSALS.items():
        with pytest.raises(kind, match=text):
            Aixm52Adapter().to_cdm(_xml(MALFORMED / name))
        problems = Aixm52Adapter().validate_source(_xml(MALFORMED / name))
        assert problems and any(text in p for p in problems), (name, problems)
    twin = copy.deepcopy(_twin(BASELINE))
    _slice(twin)["$"] = "aixm:RunwayTimeSlice"
    with pytest.raises(ValueError, match="not aixm:AirspaceTimeSlice"):
        Aixm52Adapter().to_cdm(twin)
    with pytest.raises(ValueError, match="carries message:hasMember"):
        Aixm52Adapter().to_cdm({"@gml:id": "x"})
    with pytest.raises(TypeError):
        Aixm52Adapter().to_cdm(42)  # type: ignore[arg-type]


def test_detect_answers_on_the_root_and_the_namespace_only():
    adapter = Aixm52Adapter()
    assert adapter.detect(_xml(BASELINE)) is True and adapter.detect(_twin(BASELINE)) is True
    assert adapter.detect(_xml(MALFORMED / "wrong_namespace_5_1_1.xml")) is False
    assert adapter.detect(_xml(MALFORMED / "wrong_root_element.xml")) is False
    assert adapter.detect(b"<x/>") is False and adapter.detect({"a": 1}) is False
    assert adapter.detect(_xml(MALFORMED / "arc_by_centre_point_airspace.xml")) is True


# --------------------------------------------------------------------------------- bounds

def test_the_byte_bound_admits_a_document_at_it_and_refuses_one_octet_past():
    text = _xml(BASELINE)
    padding = AIXM52_MAX_INPUT_BYTES - len(text)
    at = text.replace(b"</message:AIXMBasicMessage>", b"<!--" + b"x" * (padding - 7) + b"--></message:AIXMBasicMessage>")
    assert len(at) == AIXM52_MAX_INPUT_BYTES
    assert len(Aixm52Adapter().to_cdm(at)) == 2
    with pytest.raises(InputTooLarge):
        Aixm52Adapter().to_cdm(at + b"\n")


def test_the_depth_bound_admits_a_document_at_it_and_refuses_one_past():
    def nested(depth):
        return (b'<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.2/message">'
                + b"<n>" * (depth - 1) + b"x" + b"</n>" * (depth - 1) + b"</message:AIXMBasicMessage>")
    with pytest.raises(ValueError) as at_bound:
        Aixm52Adapter().to_cdm(nested(AIXM52_MAX_DEPTH))
    assert not isinstance(at_bound.value, secure_xml.XmlRefused)
    assert "carries message:hasMember" in str(at_bound.value)
    for depth in (AIXM52_MAX_DEPTH + 1, 1000):
        with pytest.raises(secure_xml.XmlRefused, match=f"{AIXM52_MAX_DEPTH + 1} deep against max_depth = {AIXM52_MAX_DEPTH}") as past:
            Aixm52Adapter().to_cdm(nested(depth))
        assert past.value.kind == "depth"
    deepest = max(secure_xml.tree_depth(ET.fromstring(p.read_bytes())) for p in POSITIVE)
    assert deepest * 8 <= AIXM52_MAX_DEPTH, deepest


def test_the_element_bound_refuses_a_document_one_element_past():
    body = (b'<message:AIXMBasicMessage xmlns:message="http://www.aixm.aero/schema/5.2/message">'
            + b"<n/>" * AIXM52_MAX_ELEMENTS + b"</message:AIXMBasicMessage>")
    with pytest.raises(secure_xml.XmlRefused, match="elements") as past:
        Aixm52Adapter().to_cdm(body)
    assert past.value.kind == "elements"


def test_the_object_bound_admits_a_message_at_it_and_refuses_one_past():
    def with_slices(count):
        twin = copy.deepcopy(_twin(DELTAS))
        member = twin["message:hasMember"][0]
        base = member["aixm:timeSlice"][0]
        member["aixm:timeSlice"] = [{**copy.deepcopy(base), "@gml:id": f"TS_{i}", "aixm:sequenceNumber": str(i + 10)}
                                    for i in range(count)]
        return twin
    assert len(Aixm52Adapter().to_cdm(with_slices(AIXM52_MAX_OBJECTS))) == AIXM52_MAX_OBJECTS
    with pytest.raises(ObjectCountExceeded, match=f"more than {AIXM52_MAX_OBJECTS} time slices .AIXM52_MAX_OBJECTS"):
        Aixm52Adapter().to_cdm(with_slices(AIXM52_MAX_OBJECTS + 1))


# ------------------------------------------------------------------------- determinism

def test_determinism_across_runs_hash_seeds_and_member_order():
    for path in XML_FILES:
        clock = lambda: _dt.datetime(2026, 1, 1, tzinfo=_dt.timezone.utc)  # noqa: E731
        assert _dump(Aixm52Adapter(clock=clock).to_cdm(_xml(path))) == _dump(Aixm52Adapter(clock=clock).to_cdm(_xml(path)))
    script = (
        "import json, sys, pathlib, datetime\n"
        "from synapse_cdm.adapters.aixm52 import Aixm52Adapter\n"
        "from synapse_cdm import canonical\n"
        "clock = lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)\n"
        "out = [canonical.serialise([o.model_dump(mode='json') for o in Aixm52Adapter(clock=clock).to_cdm("
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
    original = _dump(Aixm52Adapter().to_cdm(_twin(AERODROME)))
    swapped = _dump(Aixm52Adapter().to_cdm(twin))
    assert [o["source_ids"][0]["external_id"] for o in swapped][1:3] == [DIRECTION, RUNWAY]
    assert [o["source"]["record_index"] for o in swapped] == [0, 1, 2, 3, 4]
    assert original[1]["entity_id"] == swapped[2]["entity_id"]


# ------------------------------------------------------------------------ targeted negatives

def test_negative_a_wrong_version_binding_is_caught_by_the_cross_version_test(monkeypatch):
    """An implementation whose profile named the 5.1.1 namespaces would read a 5.1.1 document as
    if it were 5.2 and refuse the 5.2 fixtures; both halves of the binding test see it."""
    wrong = dataclasses.replace(module.PROFILE_52, version=codec.VERSION_511)
    monkeypatch.setattr(Aixm52Adapter, "PROFILE", wrong)
    raw_511 = (FIXTURES_511 / "airspace_baseline_polygon.xml").read_bytes()
    objects = Aixm52Adapter().to_cdm(raw_511)
    assert objects and _block(objects[0]).aixm_version == "5.1.1" != "5.2", "the block names the version it read"
    with pytest.raises(AssertionError):
        assert Aixm52Adapter().detect(raw_511) is False
    with pytest.raises(ValueError, match="schema/5.2/message"):
        Aixm52Adapter().to_cdm(_xml(BASELINE))


def test_negative_a_dropped_5_2_property_is_caught_by_the_ledger(monkeypatch):
    """An implementation that forgot `slope` (new in 5.2) on the RunwayDirection would leave it
    in the residual while the ledger binds it to `properties.slope.value`: LOST, not silence."""
    families = dict(module.FAMILIES)
    name, element, kind, pinned = families["aixm:RunwayDirection"]
    families["aixm:RunwayDirection"] = (name, element, kind, tuple(p for p in pinned if p != "slope"))
    monkeypatch.setattr(Aixm52Adapter, "PROFILE", dataclasses.replace(module.PROFILE_52, families=families))
    twin = _twin(AERODROME)
    objects = Aixm52Adapter().to_cdm(twin)
    assert "slope" not in _block(_entities(objects, DIRECTION)[0]).properties
    lost = [e for e in _ledger(twin, objects).lost if e.source_path.endswith("aixm:slope")]
    assert lost, "the ledger's declared mapping for slope finds no value at the field"


def test_negative_the_5_1_1_elevated_point_group_applied_to_5_2_is_caught_by_the_contract(monkeypatch):
    """An implementation that read a 5.2 ElevatedPoint with the 5.1.1 property group would type a
    `verticalAccuracy` the 5.2 schema does not have as 'not stated'; the reading test holds
    `vertical_accuracy` to None on 5.2 and the fixture (which carries no such element) is the oracle."""
    version = dataclasses.replace(codec.VERSION_52, elevated=codec.VERSION_511.elevated)
    monkeypatch.setattr(Aixm52Adapter, "PROFILE", dataclasses.replace(module.PROFILE_52, version=version))
    arp = _block(_entities(Aixm52Adapter().to_cdm(_xml(AERODROME)), AIRPORT)[0]).arp
    assert arp.elevation.vertical_accuracy is not None and arp.elevation.vertical_accuracy.meaning == "not stated"
    with pytest.raises(AssertionError):
        assert arp.elevation.vertical_accuracy is None
    assert "aixm:verticalAccuracy" not in arp.source, "the fixture never stated one"


def test_negative_a_swapped_axis_order_is_caught_by_the_position_and_polygon_checks(monkeypatch):
    monkeypatch.setitem(codec.CRS_AXIS_ORDER, "urn:ogc:def:crs:EPSG::4326", ("longitude", "latitude"))
    airport = _entities(Aixm52Adapter().to_cdm(_xml(AERODROME)), AIRPORT)[0]
    assert (airport.position.lat, airport.position.lon) != (52.30833, 4.76389)
    with pytest.raises(AssertionError):
        assert (airport.position.lat, airport.position.lon) == (52.30833, 4.76389)
    epsg = _plans(Aixm52Adapter().to_cdm(_xml(CASES / "axis_order_epsg4326.xml")))[0]
    crs84 = _plans(Aixm52Adapter().to_cdm(_xml(CASES / "axis_order_crs84.xml")))[0]
    assert epsg.geometry.coordinates != crs84.geometry.coordinates, "the pair no longer agrees"


def test_the_public_surface_is_declared_and_the_reader_is_shared():
    assert set(module.__all__) >= {"Aixm52Adapter", "AsOf", "ObjectCountExceeded", "TimeSliceBlock", "ReferenceTarget",
                                   "PROFILE_52", "ADDED_IN_52", "REMOVED_IN_52"}
    assert all(hasattr(module, name) for name in module.__all__)
    assert issubclass(Aixm52Adapter, aixm511.AixmAdapterBase) and not issubclass(Aixm52Adapter, Aixm511Adapter)
    assert aixm511.AixmAdapterBase.__dict__.get("abstract") is True and "" not in synapse_cdm.adapter.REGISTRY
    assert synapse_cdm.adapter.REGISTRY["aixm52"] is Aixm52Adapter and synapse_cdm.adapter.REGISTRY["aixm511"] is Aixm511Adapter
    assert Aixm52Adapter.to_cdm.__input_bounded__ and Aixm511Adapter.to_cdm.__input_bounded__
    assert module.SCHEDULED is aixm511.SCHEDULED and module.CARRIED_ELEMENTS is aixm511.CARRIED_ELEMENTS
    objects = OBJECTS.validate_python(_dump(Aixm52Adapter().to_cdm(_xml(AERODROME))))
    assert len(objects) == 5
