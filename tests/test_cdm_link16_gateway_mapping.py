"""`link16_gateway` mapping: the handoff's section 9 table (REQ080–REQ085), the CDM 3.0.0
compatibility projection (REQ013) and the gateway contract's publication.

Every canonical value is asserted here independently of the ledger (REQ085: residual preservation
alone proves nothing about the projection), and the expected values are written from the mapping
table and the fixture README by hand. The handoff's own reference projections, carried under
`fixtures/link16_gateway/reference/`, are a second, independent oracle.

REPO-BOUND: it reads `tests/frozen/cdm/3.0.0/` (the frozen compatibility contract), the published
`schemas/link16_gateway/` copies and `FORMAT_COVERAGE.md` through the repository, none of which
the wheel carries beside the package.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import re

import pytest
import synapse_cdm
from synapse_cdm import harness, lossless, schemas
from synapse_cdm.adapter import json_nesting_depth
from synapse_cdm.enums import Affiliation, PositionSource
from synapse_cdm.version import SCHEMA_VERSION

from synapse_cdm.adapters import link16_gateway as module
from synapse_cdm.adapters.link16_gateway import REPORT_SCHEMA, Link16GatewayAdapter

REPO = pathlib.Path(__file__).resolve().parents[1]
PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
SET = PKG / "fixtures" / "link16_gateway"
REFERENCE = SET / "reference"
FROZEN_3_0_0 = REPO / "tests" / "frozen" / "cdm" / "3.0.0"
PUBLISHED = REPO / "schemas" / "link16_gateway"

HANDOFF = ("air_flight_level", "air_msl", "air_sensor", "land_unknown_position",
           "subsurface_unknown_method", "surface_zero")
T_IDENTITY = "identity: UUID5 over scoped track instance"
T_AFFILIATION = "identity: finer source affiliation projected to UNKNOWN"
T_FEET = "vertical: HAE feet converted to metres using 0.3048"
T_COMPAT = "POSITION_NOT_PROJECTED_CDM3: source method is unrepresentable"


def raw_of(name: str):
    return harness.load_raw(SET / name)


def doc_of(name: str) -> dict:
    return json.loads((SET / name).read_bytes())


def project(doc_or_name, **kwargs) -> list[dict]:
    raw = raw_of(doc_or_name) if isinstance(doc_or_name, str) else doc_or_name
    return [o.model_dump(mode="json") for o in Link16GatewayAdapter(**kwargs).to_cdm(raw)]


def edited(**changes) -> dict:
    doc = doc_of("air_sensor.json")
    for path, value in changes.items():
        node = doc
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return doc


# ============================================================ the handoff's reference projections

IGNORED = ("schema_version", "source.system", "position.vertical.uncertainty",
           "samples[*].position.vertical.uncertainty", "quality.accuracy_m")


def _strip(objects: list[dict]) -> list:
    """Remove, on either side, exactly the keys the comparison names — and the three model
    defaults only when they are null, so a value there would still be compared."""
    out = copy.deepcopy(objects)
    for obj in out:
        obj.pop("schema_version")
        obj["source"].pop("system")
        positions = [obj.get("position")] + [s["position"] for s in obj.get("samples", [])]
        for position in positions:
            if position and position.get("vertical") and \
                    "uncertainty" in position["vertical"] and \
                    position["vertical"]["uncertainty"] is None:
                del position["vertical"]["uncertainty"]
        if obj.get("quality") and "accuracy_m" in obj["quality"] and \
                obj["quality"]["accuracy_m"] is None:
            del obj["quality"]["accuracy_m"]
    # Compared as JSON values: the handoff writes 125 where the models write 125.0.
    return json.loads(json.dumps(out), parse_int=float)


@pytest.mark.parametrize("stem", HANDOFF)
def test_projection_matches_the_bundle_reference_goldens(stem):
    reference = json.loads((REFERENCE / f"{stem}.cdm.json").read_bytes())
    ours = project(f"{stem}.json")
    assert _strip(ours) == _strip(reference)


@pytest.mark.parametrize("stem", HANDOFF)
def test_the_ignored_keys_hold_their_expected_values(stem):
    """The ignore list cannot hide a regression: each ignored key holds a known value on each
    side — the reference's 4.0.0 and spaced system name, this repository's own values."""
    reference = json.loads((REFERENCE / f"{stem}.cdm.json").read_bytes())
    ours = project(f"{stem}.json")
    assert {o["schema_version"] for o in reference} == {"4.0.0"}
    assert {o["source"]["system"] for o in reference} == {"SC Link16 Gateway"}
    assert {o["schema_version"] for o in ours} == {SCHEMA_VERSION}
    assert {o["source"]["system"] for o in ours} == {"SC_LINK16_GATEWAY"}
    for obj in ours:
        assert obj["quality"]["accuracy_m"] is None
        for position in [obj.get("position")] + [s["position"] for s in obj.get("samples", [])]:
            if position and position["vertical"]:
                assert position["vertical"]["uncertainty"] is None
    for obj in reference:
        assert "accuracy_m" not in obj["quality"]


def test_the_reference_directory_is_the_handoff_set_byte_for_byte():
    pin = json.loads((SET / "spec" / "link16_gateway_pin.json").read_text())
    pinned = {f["carried_as"]: (f["sha256"], f["bytes"]) for f in pin["files"]
              if f.get("carried_here") is True and f["carried_as"].startswith("link16_gateway/")}
    assert len(pinned) == 12
    for carried_as, (sha256, size) in pinned.items():
        data = (PKG / "fixtures" / carried_as).read_bytes()
        assert (hashlib.sha256(data).hexdigest(), len(data)) == (sha256, size), carried_as


# ============================================================ C01, P01–P04

EXPECTED_KINDS = {
    "air_flight_level.json": ["entity", "track"], "air_msl.json": ["entity", "track"],
    "air_sensor.json": ["entity", "track"], "land_unknown_position.json": ["entity"],
    "subsurface_unknown_method.json": ["entity", "track"], "surface_zero.json": ["entity", "track"],
    "air_hae_metres_friendly.json": ["entity", "track"],
    "air_hae_feet_gnss_hostile.json": ["entity", "track"],
    "surface_baro_pending_null_quality.json": ["entity", "track"],
    "land_agl_assumed_friend_earlier_components.json": ["entity", "track"],
    "subsurface_unit_other_depth_unknown_reference.json": ["entity", "track"],
    "unknown_domain_poles_uint64_unicode.json": ["entity", "track"],
    "air_south_pole_antimeridian_resolved.json": ["entity", "track"],
}


@pytest.mark.parametrize("name", sorted(EXPECTED_KINDS))
def test_entity_first_track_iff_position(name):
    objects = project(name)
    assert [o["object_kind"] for o in objects] == EXPECTED_KINDS[name]
    if len(objects) == 1:
        assert objects[0]["position"] is None
    else:
        assert objects[1]["samples"][0]["position"] == objects[0]["position"]
        assert len(objects[1]["samples"]) == 1


def test_zero_poles_antimeridian_preserved():
    cases = {"surface_zero.json": (0.0, 0.0), "unknown_domain_poles_uint64_unicode.json":
             (90.0, 180.0), "air_south_pole_antimeridian_resolved.json": (-90.0, -180.0)}
    for name, (lat, lon) in cases.items():
        entity, track = project(name)
        assert (entity["position"]["lat"], entity["position"]["lon"]) == (lat, lon)
        assert (track["samples"][0]["position"]["lat"], track["samples"][0]["position"]["lon"]) \
            == (lat, lon)
    # A height of zero is a value, kept as stated, never dropped as a sentinel.
    entity, _ = project("air_south_pole_antimeridian_resolved.json")
    assert entity["position"]["vertical"] == {"value": 0.0, "unit": "m", "reference": "MSL",
                                              "uncertainty": None}


def test_sensor_and_unknown_methods_project_under_cdm_3_1():
    generated = schemas.generate()
    for name, method in (("air_sensor.json", "SENSOR"), ("subsurface_unknown_method.json",
                                                          "UNKNOWN")):
        entity, track = project(name)
        assert entity["position"]["position_source"] == method
        assert track["samples"][0]["position"]["position_source"] == method
        for obj in (entity, track):
            assert list(schemas.validator_for(generated[obj["object_kind"]]).iter_errors(obj)) \
                == []
    assert PositionSource("SENSOR") is PositionSource.SENSOR
    assert PositionSource("UNKNOWN") is PositionSource.UNKNOWN


def _frozen(kind: str):
    return schemas.validator_for(json.loads((FROZEN_3_0_0 / f"{kind}.schema.json").read_text()))


@pytest.mark.parametrize("name", sorted(EXPECTED_KINDS))
def test_compatibility_projection_validates_against_frozen_3_0_0(name):
    for obj in project(name, cdm_schema="3.0.0"):
        assert obj["schema_version"] == "3.0.0"
        assert list(_frozen(obj["object_kind"]).iter_errors(obj)) == []


def test_compatibility_projection_omits_unrepresentable_positions():
    """P04 and REQ013: SENSOR and UNKNOWN cannot be stated under 3.0.0, so the position is not
    projected, no Track is emitted, the transformation says so, and the report stays whole.
    D-20: the feet conversion is NOT listed, because no converted height reached an object."""
    for name in ("air_sensor.json", "subsurface_unknown_method.json"):
        (entity,) = project(name, cdm_schema="3.0.0")
        assert entity["position"] is None
        assert entity["source"]["transformations"] == [T_IDENTITY, T_COMPAT]
        assert entity["residual"]["data"]["report"] == doc_of(name)
    # The full projection of the same two reports is exactly what 3.0.0 refuses, and the method
    # is the whole reason: with GNSS written in its place the same objects validate.
    for name in ("air_sensor.json", "subsurface_unknown_method.json"):
        for obj in project(name):
            assert list(_frozen(obj["object_kind"]).iter_errors(obj))
            positions = [obj.get("position")] + [s["position"] for s in obj.get("samples", [])]
            for position in filter(None, positions):
                position["position_source"] = "GNSS"
            assert list(_frozen(obj["object_kind"]).iter_errors(obj)) == []


def test_compatibility_projection_keeps_representable_positions_with_a_track():
    full = project("air_hae_feet_gnss_hostile.json")
    compat = project("air_hae_feet_gnss_hostile.json", cdm_schema="3.0.0")
    assert [o["object_kind"] for o in compat] == ["entity", "track"]
    assert compat[0]["position"] == full[0]["position"]
    assert compat[0]["source"]["transformations"] == [T_IDENTITY, T_FEET]
    assert {o["schema_version"] for o in compat} == {"3.0.0"}


# ============================================================ V01–V03

def test_hae_feet_becomes_metres_in_vertical_and_alt_m_and_feet_stay_in_residual():
    entity, track = project("air_sensor.json")             # 10000 ft HAE
    assert entity["position"]["vertical"] == {"value": 3048.0, "unit": "m", "reference": "HAE",
                                              "uncertainty": None}
    assert entity["position"]["alt_m"] == 3048.0
    assert entity["residual"]["data"]["report"]["position"]["vertical"] == \
        {"value": 10000, "unit": "ft", "reference": "HAE"}
    assert track["samples"][0]["position"]["alt_m"] == 3048.0
    entity, _ = project("air_hae_feet_gnss_hostile.json")  # 10001 ft HAE
    assert entity["position"]["alt_m"] == entity["position"]["vertical"]["value"] == \
        10001 * 0.3048


def test_hae_metres_copies_to_alt_m():
    entity, _ = project("air_hae_metres_friendly.json")
    assert entity["position"]["alt_m"] == 1524.0
    assert entity["position"]["vertical"] == {"value": 1524.0, "unit": "m", "reference": "HAE",
                                              "uncertainty": None}
    assert entity["source"]["transformations"] == [T_IDENTITY]


OTHER_DATUMS = {
    "air_flight_level.json": {"value": 180.0, "unit": "FL", "reference": "FL"},
    "air_msl.json": {"value": 5000.0, "unit": "ft", "reference": "MSL"},
    "surface_baro_pending_null_quality.json": {"value": 30.0, "unit": "m", "reference": "BARO"},
    "land_agl_assumed_friend_earlier_components.json":
        {"value": 12.5, "unit": "ft", "reference": "AGL"},
    "subsurface_unit_other_depth_unknown_reference.json":
        {"value": -30.0, "unit": "m", "reference": "UNKNOWN"},
}


@pytest.mark.parametrize("name", sorted(OTHER_DATUMS))
def test_other_datums_keep_source_vertical_and_null_alt_m(name):
    entity, track = project(name)
    for position in (entity["position"], track["samples"][0]["position"]):
        assert position["alt_m"] is None
        assert position["vertical"] == {**OTHER_DATUMS[name], "uncertainty": None}
    assert T_FEET not in entity["source"]["transformations"]


def test_subsurface_depth_is_never_a_negative_alt_m():
    entity, _ = project("subsurface_unknown_method.json")
    assert entity["position"]["alt_m"] is None and entity["position"]["vertical"] is None
    assert entity["residual"]["data"]["report"]["source_fields"]["depth_m"] == 30
    entity, _ = project("subsurface_unit_other_depth_unknown_reference.json")
    assert entity["position"]["alt_m"] is None
    assert entity["residual"]["data"]["report"]["source_fields"]["depth_m"] == 30


# ============================================================ A01, kinematics, times, quality

AFFILIATIONS = {"FRIENDLY": "FRIENDLY", "HOSTILE": "HOSTILE", "NEUTRAL": "NEUTRAL",
                "UNKNOWN": "UNKNOWN", "PENDING": "UNKNOWN", "ASSUMED_FRIEND": "UNKNOWN",
                "SUSPECT": "UNKNOWN", "OTHER": "UNKNOWN"}


@pytest.mark.parametrize("token", sorted(AFFILIATIONS))
def test_affiliation_projects_to_four_and_keeps_the_token(token):
    entity, _ = project(edited(identity=token))
    assert entity["affiliation"] == AFFILIATIONS[token]
    assert Affiliation(entity["affiliation"])
    assert entity["residual"]["data"]["report"]["identity"] == token
    finer = token != AFFILIATIONS[token]
    assert (T_AFFILIATION in entity["source"]["transformations"]) is finer
    assert entity["attributes"] == {}


def test_kinematics_copied_with_nulls_and_time_in_residual_only():
    entity, _ = project("air_sensor.json")
    assert entity["kinematics"] == {"speed_mps": 125.0, "course_deg": 90.0, "climb_mps": None}
    entity, _ = project("subsurface_unit_other_depth_unknown_reference.json")
    assert entity["kinematics"] == {"speed_mps": None, "course_deg": None, "climb_mps": None}
    entity, _ = project("land_agl_assumed_friend_earlier_components.json")
    assert entity["kinematics"] == {"speed_mps": 0.0, "course_deg": 0.0, "climb_mps": 0.0}
    assert "observed_at" not in entity["kinematics"]
    assert entity["residual"]["data"]["report"]["kinematics"]["observed_at"] == \
        "2026-10-04T11:59:58.500Z"
    entity, _ = project("surface_baro_pending_null_quality.json")
    assert entity["kinematics"] is None


def test_valid_from_is_effective_at_never_received_at():
    doc = edited(received_at="2026-10-04T12:05:00.000Z", effective_at="2026-10-04T12:00:00.250Z",
                 position__observed_at="2026-10-04T11:59:00.000Z",
                 kinematics__observed_at="2026-10-04T11:59:30.000Z")
    entity, track = project(doc)
    assert entity["valid_from"] == entity["source"]["observed_at"] == "2026-10-04T12:00:00.250Z"
    assert track["source"]["observed_at"] == "2026-10-04T12:00:00.250Z"
    assert "2026-10-04T12:05:00.000Z" not in json.dumps({k: v for k, v in entity.items()
                                                         if k != "residual"})


def test_track_sample_time_is_position_observed_at():
    entity, track = project("land_agl_assumed_friend_earlier_components.json")
    assert track["samples"][0]["observed_at"] == "2026-10-04T11:59:55.000Z"
    assert entity["valid_from"] == "2026-10-04T12:00:00.000Z"     # the two may differ (REQ090)


def test_quality_code_is_source_quality_only():
    entity, track = project("air_sensor.json")
    for obj in (entity, track):
        assert obj["quality"] == {"source_quality": "SYNTHETIC-GRADE-A", "confidence": None,
                                  "accuracy_m": None, "uncertainty": {}}
    entity, track = project("surface_baro_pending_null_quality.json")
    assert entity["quality"] is None and track["quality"] is None
    assert entity["confidence"] is None and track["track_quality"] is None


TRANSFORMATIONS = {
    "air_sensor.json": [T_IDENTITY, T_FEET],
    "air_hae_feet_gnss_hostile.json": [T_IDENTITY, T_FEET],
    "air_hae_metres_friendly.json": [T_IDENTITY],
    "land_unknown_position.json": [T_IDENTITY, T_AFFILIATION],
    "surface_zero.json": [T_IDENTITY],
    "subsurface_unit_other_depth_unknown_reference.json": [T_IDENTITY, T_AFFILIATION],
}


def test_transformations_exact_strings_and_order():
    for name, expected in TRANSFORMATIONS.items():
        for obj in project(name):
            assert obj["source"]["transformations"] == expected, name
    # All four at once, in the specified order: a finer token, HAE feet under the full
    # projection; then under compatibility the omission and no conversion (D-20).
    doc = edited(identity="SUSPECT")
    assert project(doc)[0]["source"]["transformations"] == [T_IDENTITY, T_AFFILIATION, T_FEET]
    assert project(doc, cdm_schema="3.0.0")[0]["source"]["transformations"] == \
        [T_IDENTITY, T_AFFILIATION, T_COMPAT]
    assert (module.T_IDENTITY, module.T_AFFILIATION, module.T_FEET, module.T_COMPAT) == \
        (T_IDENTITY, T_AFFILIATION, T_FEET, T_COMPAT)


def test_source_ref_fields():
    entity, track = project("air_sensor.json")
    for obj in (entity, track):
        assert obj["source"] == {
            "system": "SC_LINK16_GATEWAY", "adapter": "link16_gateway", "adapter_version": "1.0.0",
            "synthetic": True, "format_name": "SC Link16 Gateway", "format_version": "1.0.0",
            "original_id": "11111111-1111-4111-8111-111111111111", "source_hash": None,
            "record_index": None, "observed_at": "2026-10-04T12:00:00.000Z",
            "transformations": [T_IDENTITY, T_FEET]}
        assert obj["integrity"] is None and obj["status"] is None


def test_residual_is_the_whole_report_and_track_residual_is_record_id():
    for name in EXPECTED_KINDS:
        objects = project(name)
        assert objects[0]["residual"] == {"namespace": "SC Link16 Gateway",
                                          "data": {"report": doc_of(name)}}
        if len(objects) == 2:
            assert objects[1]["residual"] == {"namespace": "SC Link16 Gateway",
                                              "data": {"record_id": doc_of(name)["record_id"]}}


# ============================================================ the ledger and REQ083

#: (MAPPED, RESIDUAL) per JSON fixture, derived by hand: MAPPED counts record_id, effective_at,
#: synthetic, entity_kind, identity, quality_code, then position.observed_at/lat/lon/method and
#: vertical.reference (or `vertical` itself when null), the three motion values — or `position` /
#: `kinematics` themselves when null — and RESIDUAL every other leaf of the report.
LEDGER = {
    "air_flight_level.json": (14, 25), "air_msl.json": (14, 25), "air_sensor.json": (14, 25),
    "land_unknown_position.json": (8, 22), "subsurface_unknown_method.json": (14, 23),
    "surface_zero.json": (14, 23), "air_hae_metres_friendly.json": (14, 24),
    "air_hae_feet_gnss_hostile.json": (14, 24),
    "surface_baro_pending_null_quality.json": (12, 23),
    "land_agl_assumed_friend_earlier_components.json": (14, 24),
    "subsurface_unit_other_depth_unknown_reference.json": (14, 26),
    "unknown_domain_poles_uint64_unicode.json": (14, 31),
    "air_south_pole_antimeridian_resolved.json": (14, 24),
}


@pytest.mark.parametrize("name", sorted(LEDGER))
def test_mappings_ledger_has_no_lost_leaf_on_every_fixture(name):
    raw = doc_of(name)
    ledger = lossless.ledger(raw, project(name), Link16GatewayAdapter.MAPPINGS)
    assert ledger.declared_mappings == 18
    assert ledger.counts == {"MAPPED": LEDGER[name][0], "RESIDUAL": LEDGER[name][1],
                             "DECLARED_LIMITATION": 0, "LOST": 0}


def test_the_ledger_catches_a_wrong_projection():
    """A negative control: the same ledger over a deliberately wrong projection reports LOST."""
    raw = doc_of("air_sensor.json")
    objects = project("air_sensor.json")
    objects[0]["position"]["lat"] = 48.16
    objects[1]["samples"][0]["position"]["lat"] = 48.16
    ledger = lossless.ledger(raw, objects, Link16GatewayAdapter.MAPPINGS)
    assert [e.source_path for e in ledger.lost] == ["position.lat_deg"]


def test_residual_only_projections_are_asserted_here():
    """L-08's three projections the ledger grammar cannot state, asserted by value."""
    # (a) the vertical value and unit under the HAE-feet conversion
    entity, _ = project("air_sensor.json")
    assert (entity["position"]["vertical"]["value"], entity["position"]["vertical"]["unit"]) == \
        (3048.0, "m")
    # (b) the identity tuple composite in source_ids[0].external_id
    doc = edited(tenant="t-1", realm="r-2", origin_scope="s-3", track_number="TN 4",
                 incarnation="5")
    entity, track = project(doc)
    assert entity["source_ids"] == track["source_ids"] == [
        {"system": "Link16Track", "external_id": '["t-1","r-2",true,"s-3","TN 4","5"]'}]
    # (c) the compatibility projection's positions: kept for a 3.0.0 method, omitted otherwise
    assert project("air_msl.json", cdm_schema="3.0.0")[0]["position"] == \
        project("air_msl.json")[0]["position"]
    assert project("air_sensor.json", cdm_schema="3.0.0")[0]["position"] is None


def test_symbol_confidence_valid_to_attributes_stay_empty():
    for name in EXPECTED_KINDS:
        entity = project(name)[0]
        assert (entity["symbol"], entity["confidence"], entity["valid_to"]) == (None, None, None)
        assert (entity["attributes"], entity["ontology_types"]) == ({}, [])


def test_eight_times_depth_rule_for_every_shipped_json():
    deepest = 0
    for path in SET.rglob("*.json"):
        depth = json_nesting_depth(path.read_text())
        assert depth <= 16, path
        if "malformed" not in path.parts and "spec" not in path.parts and \
                path.name != "PROVENANCE.json":
            assert depth <= 8, path
            deepest = max(deepest, depth)
    assert deepest * 8 <= Link16GatewayAdapter.metadata.capabilities.limits.max_depth == 64
    assert deepest == 8          # the Unicode report's golden: source_fields.nested.empty


def test_missing_origin_scope_is_schema_invalid():
    """REQ071 says a missing scope is IDENTITY_SCOPE_UNRESOLVED; the report schema makes the key
    required, so at the translator it is SCHEMA_INVALID (D-24). The runtime keeps the other code
    for a scope the channel has not approved."""
    doc = doc_of("air_sensor.json")
    del doc["origin_scope"]
    with pytest.raises(module.Link16GatewayRefusal) as caught:
        Link16GatewayAdapter().to_cdm(doc)
    assert str(caught.value) == "SCHEMA_INVALID: origin_scope — required"
    with pytest.raises(module.Link16GatewayRefusal) as caught:
        Link16GatewayAdapter().to_cdm(edited(origin_scope=""))
    assert str(caught.value) == "SCHEMA_INVALID: origin_scope — pattern"


# ============================================================ the contract's publication

def test_the_published_report_schema_is_the_module_literal():
    published = json.loads((PUBLISHED / "report.schema.json").read_text())
    assert published == REPORT_SCHEMA


@pytest.mark.parametrize("stem", ["report", "notice", "api"])
def test_the_published_schemas_are_the_pinned_handoff_files(stem):
    pin = json.loads((SET / "spec" / "link16_gateway_pin.json").read_text())
    entry = next(f for f in pin["files"] if f["file"] == f"{stem}.schema.json")
    data = (PUBLISHED / f"{stem}.schema.json").read_bytes()
    assert (hashlib.sha256(data).hexdigest(), len(data)) == (entry["sha256"], entry["bytes"])
    assert entry["carried_here"] is True
    assert json.loads(data)["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert sorted(p.name for p in PUBLISHED.iterdir()) == \
        ["api.schema.json", "notice.schema.json", "report.schema.json"]


def test_the_module_docstring_and_format_coverage_name_the_same_ordinal():
    """The ordinal sweep cannot bind the module's own docstring sentence to this adapter (no
    alias is registered for it), so the two statements are held together here."""
    first_line = module.__doc__.splitlines()[0]
    claimed = re.fullmatch(r"SC Link16 Gateway 1\.0\.0 report -> CDM, and back\. Adapter #(\d+)\.",
                           first_line)
    assert claimed
    table = (PKG / "FORMAT_COVERAGE.md").read_text()
    row = re.search(r"^\| (\d+) \| `link16_gateway` \| shipped \|", table, re.M)
    assert row and row.group(1) == claimed.group(1)
    assert len(re.findall(r"#\d+", module.__doc__)) == 1


def test_the_package_fixture_tree_holds_no_schema_file():
    assert not [p for p in SET.rglob("*.schema.json")]
