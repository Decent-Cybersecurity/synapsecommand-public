"""Adapter #16 — GeoJSON (RFC 7946), the first `residual: structured` adapter.

One test per claim in `adapters/geojson.py`'s docstring, plus the master prompt's cross-cutting
list (stable identity, zeros kept, wrong profile refused, coordinate order, missing context, hash
seeds and member order, bounds at and past the limit, fresh egress, semantic round trip) and the
three NEGATIVE tests that prove the ledger catches a wrong mapping rather than blessing whatever
the implementation emits: a swapped lon/lat, a dropped property and a wrong identity policy are
each fed to the ledger as if an adapter had produced them, and each reads LOST.

Every fixture is JSON, so the harness's `lossless` column runs the ledger on every one and no
parsed twin is needed — the one XML/binary case CONTRIBUTING.md's twin rule exists for does not
arise here, and `test_no_fixture_needs_a_parsed_twin` says so in code.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

import synapse_cdm
from synapse_cdm import adapter as adapter_module
from synapse_cdm import harness, lossless, times
from synapse_cdm.adapters import geojson as module
from synapse_cdm.adapters.geojson import (
    EXCHANGE_PREFIX,
    EXPORT_EXCHANGE,
    EXPORT_GENERIC,
    GEOJSON_MAX_DEPTH,
    GEOJSON_MAX_FEATURES,
    GEOJSON_MAX_INPUT_BYTES,
    GEOJSON_MAX_POSITIONS,
    IDENTITY_RECORD_INDEX,
    AsOf,
    FeatureCountExceeded,
    GeojsonAdapter,
    PositionCountExceeded,
    ring_orientation,
)
from synapse_cdm.models import KINDS, Entity, Event, PlanObject
from synapse_cdm.manifest import Residual

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "geojson"
MALFORMED = FIXTURES / "malformed"
EGRESS = FIXTURES / "egress"
SPEC = FIXTURES / "spec" / "geojson_pin.json"
FIXTURE_FILES = sorted(p for p in harness.select_fixtures(FIXTURES))
EGRESS_FILES = sorted(p for p in harness.select_fixtures(EGRESS))
AS_OF = AsOf("2026-04-29T06:00:00Z", "the synthetic dataset's stated snapshot instant")


def _raw(path: pathlib.Path):
    return json.loads(path.read_text())


def _dump(objects):
    return [o.model_dump(mode="json") for o in objects]


def _ledger(raw, objects):
    return lossless.ledger(raw, _dump(objects), GeojsonAdapter.MAPPINGS)


def _feature(fid=None, geometry=None, properties=None, **members):
    feature = {"type": "Feature", **members}
    if fid is not None:
        feature["id"] = fid
    feature["geometry"] = geometry if geometry is not None else {
        "type": "Point", "coordinates": [24.1, 57.0]}
    feature["properties"] = {"name": "EXERCISE"} if properties is None else properties
    return feature


def _collection(*features, **members):
    return {"type": "FeatureCollection", **members, "features": list(features)}


# ------------------------------------------------------------------ the fixtures themselves

def test_the_fixture_set_is_the_documented_one():
    assert [p.name for p in FIXTURE_FILES] == [
        "antimeridian_bbox_repeated_values.json",
        "feature_zero_meridian_clockwise_ring.json",
        "null_and_empty_properties_typed_ids.json",
        "six_geometries_baltic.json",
    ]
    assert len(EGRESS_FILES) == 3


def test_every_fixture_is_synthetic_by_default():
    """No real GeoJSON data in this repository, and the objects must say so (TR-12)."""
    for path in FIXTURE_FILES:
        for obj in GeojsonAdapter().to_cdm(_raw(path)):
            assert obj.source.synthetic is True, path.name
            assert obj.source.system == "GeoJSON"
            assert obj.source.format_name == "GeoJSON"
            assert obj.source.format_version == "RFC 7946 (August 2016)"


def test_every_fixture_matches_the_record_in_spec():
    """`spec/geojson_pin.json` states a SHA-256 and a byte count for every payload in the three
    directories; the tree must be what the record says, and the record must name every file."""
    record = json.loads(SPEC.read_text())
    listed = {(FIXTURES, e["file"]): e for e in record["fixtures"]}
    listed.update({(MALFORMED, e["file"]): e for e in record["malformed"]["files"]})
    listed.update({(EGRESS, e["file"]): e for e in record["egress"]["files"]})
    on_disk = {(d, p.name) for d in (FIXTURES, MALFORMED, EGRESS)
               for p in harness.select_fixtures(d)}
    assert set(listed) == on_disk, set(listed) ^ on_disk
    for (directory, name), entry in listed.items():
        path = directory / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], name
        assert path.stat().st_size == entry["bytes"], name
    pending = [record]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            assert not ("local_path" in node and "sha256" in node), \
                "a node pairing local_path with sha256 is what gates/pin_paths.py reads as a pin"
            pending.extend(node.values())
        elif isinstance(node, list):
            pending.extend(node)


def test_the_adapter_agrees_with_the_independent_gdal_reading():
    """The pin record carries GDAL 3.13.3's WKT per feature. Feature count, geometry type and
    every coordinate must agree with what the adapter read — an oracle the adapter cannot
    influence, so a swapped axis or a dropped vertex here is a disagreement and not a pass."""
    record = json.loads(SPEC.read_text())
    for entry in record["fixtures"]:
        reading = entry["independent_reading_gdal"]
        objects = GeojsonAdapter().to_cdm(_raw(FIXTURES / entry["file"]))
        assert len(objects) == reading["feature_count"] == entry["feature_count"]
        for obj, wkt in zip(objects, reading["wkt"]):
            kind = wkt.split(" ", 1)[0].replace(" Z", "")
            wanted = obj.geometry.type.upper()
            assert kind.startswith(wanted), (entry["file"], wkt, wanted)
            numbers = [float(t) for t in wkt.replace("(", " ").replace(")", " ").replace(",", " ")
                       .split()[1 if " Z " not in wkt else 2:]]
            flat: list[float] = []
            pending = [obj.geometry.coordinates]
            while pending:
                node = pending.pop(0)
                if isinstance(node, list) and node and isinstance(node[0], list):
                    pending = list(node) + pending
                else:
                    flat.extend(float(v) for v in node)
            assert flat == numbers, (entry["file"], wkt)


def test_no_fixture_needs_a_parsed_twin():
    """Every fixture is JSON: the harness hands the adapter the parsed document and runs the
    ledger on it, so the twin an XML or binary adapter ships has no counterpart here."""
    assert all(p.suffix == ".json" for p in FIXTURE_FILES)
    assert not list(FIXTURES.glob("*.parsed.json"))


def test_the_harness_passes_every_check_on_every_fixture():
    report = harness.run(GeojsonAdapter(clock=times.frozen_clock()), FIXTURES,
                         schema_dir=pathlib.Path("schemas") if pathlib.Path("schemas").is_dir()
                         else None)
    assert report["failed"] == 0, [r["problems"] for r in report["results"]]
    assert report["preservation"]["basis"] == "ledger"
    for result in report["results"]:
        assert result["checks"]["lossless"] == "PASS"
        assert result["checks"]["roundtrip"] == "PASS"
        assert result["checks"]["golden"] == "PASS", result["problems"]
        assert result["preservation"]["counts"]["LOST"] == 0


# ------------------------------------------------------------------ the structured residual

def test_the_residual_is_structured_and_named_for_the_format():
    for path in FIXTURE_FILES:
        for obj in GeojsonAdapter().to_cdm(_raw(path)):
            assert obj.residual is not None
            assert obj.residual.namespace == GeojsonAdapter.metadata.format.name == "GeoJSON"
            assert "document" in obj.residual.data
            dumped = obj.model_dump(mode="json")
            assert "source_extras" not in json.dumps(dumped)
    assert GeojsonAdapter.metadata.residual is Residual.STRUCTURED


def test_properties_null_empty_and_nested_are_preserved_with_their_types():
    objects = GeojsonAdapter().to_cdm(_raw(FIXTURES / "null_and_empty_properties_typed_ids.json"))
    assert objects[0].residual.data["feature"]["properties"] is None
    assert objects[1].residual.data["feature"]["properties"] == {}
    assert objects[0].residual.data["document"] == {"type": "FeatureCollection", "metadata": {}}
    square = GeojsonAdapter().to_cdm(_raw(FIXTURES / "feature_zero_meridian_clockwise_ring.json"))[0]
    props = square.residual.data["document"]["properties"]
    assert props["nested"] == {"a": [1, 2, {"b": None}], "c": ""}
    assert props["depth_m"] == 0 and isinstance(props["depth_m"], int)
    assert props["ratio"] == 0.0 and isinstance(props["ratio"], float)


def test_foreign_members_at_collection_feature_and_geometry_level_are_kept():
    objects = GeojsonAdapter().to_cdm(_raw(FIXTURES / "six_geometries_baltic.json"))
    assert objects[0].residual.data["document"]["name"] == "EXERCISE synthetic Baltic layer"
    assert objects[2].residual.data["feature"]["vendor_flag"] is True
    square = GeojsonAdapter().to_cdm(_raw(FIXTURES / "feature_zero_meridian_clockwise_ring.json"))[0]
    assert square.residual.data["document"]["geometry"] == {
        "source_note": "EXERCISE — synthetic ring on the zero meridian"}
    assert square.geometry.model_dump(mode="json").keys() == {"type", "coordinates"}


def test_zero_coordinates_and_zero_values_are_real_values():
    square = GeojsonAdapter().to_cdm(_raw(FIXTURES / "feature_zero_meridian_clockwise_ring.json"))[0]
    assert square.geometry.coordinates[0][0] == [0.0, 0.0]
    assert square.residual.data["document"]["properties"]["depth_m"] == 0
    assert square.residual.data["document"]["properties"]["ratio"] == 0.0


def test_the_six_geometry_types_land_on_the_cdm_geometry_in_order():
    objects = GeojsonAdapter().to_cdm(_raw(FIXTURES / "six_geometries_baltic.json"))
    assert [o.geometry.type for o in objects] == [
        "Point", "LineString", "Polygon", "MultiPoint", "MultiLineString", "MultiPolygon"]
    assert all(isinstance(o, PlanObject) and o.object_type.value == "ANNOTATION" for o in objects)
    assert all(o.label is None and o.style == {} for o in objects), "no property is promoted"
    assert [o.source.record_index for o in objects] == [0, 1, 2, 3, 4, 5]


def test_the_vertical_third_element_is_preserved_and_time_zones_normalise_to_utc():
    objects = GeojsonAdapter(as_of=AsOf("2026-04-29T08:00:00+02:00", "a stated local snapshot")
                             ).to_cdm(_raw(FIXTURES / "antimeridian_bbox_repeated_values.json"))
    assert objects[0].geometry.coordinates == [179.8, -16.5, 120.0]
    assert times.render(objects[0].validity.observed_at) == "2026-04-29T06:00:00.000Z"
    assert any("as-of context" in line for line in objects[0].source.transformations)


# ------------------------------------------------------------------ identity

def test_numeric_and_string_ids_are_two_identities_and_original_id_shows_which():
    objects = GeojsonAdapter().to_cdm(_raw(FIXTURES / "null_and_empty_properties_typed_ids.json"))
    assert objects[0].object_id != objects[1].object_id
    assert [o.source.original_id for o in objects] == ["7", '"7"']
    assert [o.source_ids[0].external_id for o in objects] == ["7", "7"]
    assert objects[0].residual.data["feature"]["id"] == 7
    assert objects[1].residual.data["feature"]["id"] == "7"


def test_identity_is_stable_across_updates_of_mutable_properties():
    before = GeojsonAdapter().to_cdm(_collection(_feature("A", properties={"status": "open"})))
    after = GeojsonAdapter().to_cdm(_collection(
        _feature("A", geometry={"type": "Point", "coordinates": [25.0, 58.0]},
                 properties={"status": "closed", "extra": 1})))
    assert before[0].object_id == after[0].object_id
    assert before[0].object_id.version == 5


def test_identities_are_distinct_across_dataset_namespaces():
    a = GeojsonAdapter(dataset="roads").to_cdm(_collection(_feature("A")))[0]
    b = GeojsonAdapter(dataset="rivers").to_cdm(_collection(_feature("A")))[0]
    unnamed = GeojsonAdapter().to_cdm(_collection(_feature("A")))[0]
    assert len({a.object_id, b.object_id, unnamed.object_id}) == 3
    assert a.source_ids[0].system == "GeoJSON:roads"
    assert unnamed.source_ids[0].system == "GeoJSON"


def test_an_id_less_feature_is_refused_under_the_default_policy_and_nothing_is_guessed():
    with pytest.raises(ValueError, match="no `id` and the adapter's identity policy is 'refuse'"):
        GeojsonAdapter().to_cdm(_collection(_feature()))


def test_the_record_index_policy_is_deterministic_and_says_it_cannot_survive_an_insertion():
    adapter = GeojsonAdapter(identity=IDENTITY_RECORD_INDEX)
    first = adapter.to_cdm(_collection(_feature(properties={"n": 1}), _feature(properties={"n": 2})))
    again = adapter.to_cdm(_collection(_feature(properties={"n": 1}), _feature(properties={"n": 2})))
    assert [o.object_id for o in first] == [o.object_id for o in again]
    assert first[0].object_id != first[1].object_id
    assert first[1].source_ids[0].external_id == "#1"
    assert any("NOT stable across dataset updates" in t for t in first[1].source.transformations)
    shifted = adapter.to_cdm(_collection(_feature(properties={"n": 0}), _feature(properties={"n": 1}),
                                         _feature(properties={"n": 2})))
    assert shifted[1].object_id == first[1].object_id, "the position, not the content, is the key"
    with pytest.raises(ValueError, match="bare Feature has none"):
        adapter.to_cdm(_feature())


def test_the_property_policy_keys_on_the_named_property_and_refuses_a_feature_without_it():
    adapter = GeojsonAdapter(identity="property:ref")
    one = adapter.to_cdm(_collection(_feature(properties={"ref": "R-1", "v": 1})))[0]
    two = adapter.to_cdm(_collection(_feature(properties={"ref": "R-1", "v": 2}),
                                     _feature(properties={"ref": 9})))
    assert one.object_id == two[0].object_id
    assert one.source_ids[0].external_id == "R-1" and two[1].source_ids[0].external_id == "9"
    assert one.source.original_id is None
    with pytest.raises(ValueError, match="no property 'ref'"):
        adapter.to_cdm(_collection(_feature(properties={"name": "x"})))
    with pytest.raises(ValueError, match="non-empty string or a number"):
        adapter.to_cdm(_collection(_feature(properties={"ref": [1]})))
    with pytest.raises(ValueError, match="identity must be"):
        GeojsonAdapter(identity="content")


def test_a_present_id_wins_over_any_fallback_policy():
    a = GeojsonAdapter().to_cdm(_collection(_feature("A")))[0]
    b = GeojsonAdapter(identity=IDENTITY_RECORD_INDEX).to_cdm(_collection(_feature("A")))[0]
    assert a.object_id == b.object_id


# ------------------------------------------------------------------ null geometry and as-of

def test_null_geometry_is_an_entity_with_no_position_and_needs_the_as_of_context():
    document = _collection(_feature("nowhere", properties={"name": "EXERCISE"}))
    document["features"][0]["geometry"] = None
    with pytest.raises(ValueError, match="null geometry.*as-of context") as refusal:
        GeojsonAdapter().to_cdm(document)
    assert "1970" not in str(refusal.value)
    objects = GeojsonAdapter(as_of=AS_OF).to_cdm(document)
    entity = objects[0]
    assert isinstance(entity, Entity)
    assert entity.position is None and entity.symbol is None
    assert entity.entity_type.value == "OVERLAY_OBJECT" and entity.affiliation.value == "UNKNOWN"
    assert entity.valid_from == AS_OF.instant
    assert entity.residual.data["feature"]["geometry"] is None
    assert any(AS_OF.basis in t for t in entity.source.transformations)
    assert _ledger(document, objects).lost == ()


def test_a_feature_keeps_its_identity_when_its_geometry_goes_null():
    with_geometry = GeojsonAdapter(as_of=AS_OF).to_cdm(_collection(_feature("A")))[0]
    document = _collection(_feature("A"))
    document["features"][0]["geometry"] = None
    without = GeojsonAdapter(as_of=AS_OF).to_cdm(document)[0]
    assert with_geometry.object_id == without.entity_id


def test_as_of_lands_on_validity_and_never_on_the_clock():
    document = _collection(_feature("A"))
    plain = GeojsonAdapter(clock=times.frozen_clock()).to_cdm(document)[0]
    assert plain.validity is None
    dated = GeojsonAdapter(clock=times.frozen_clock(), as_of=AS_OF).to_cdm(document)[0]
    assert dated.validity.observed_at == AS_OF.instant
    assert dated.validity.valid_from is None
    with pytest.raises(ValueError, match="basis"):
        AsOf("2026-04-29T06:00:00Z", "x")


# ------------------------------------------------------------------ refusals, by name

def test_every_malformed_payload_is_refused_by_name():
    expected = {
        "a_json_array.json": "JSON array, not an object",
        "bare_geometry.json": "bare Point geometry",
        "empty_coordinates.json": "empty `coordinates` array",
        "feature_without_properties.json": "no `properties` member",
        "geometry_collection_feature.json": "GeometryCollection",
        "id_less_feature_default_policy.json": "identity policy is 'refuse'",
        "legacy_crs_member.json": "carries a `crs` member",
        "non_finite_number.json": "refuses nan",
        "null_geometry_without_as_of.json": "as-of context",
        "swapped_lat_lon_point.json": "latitude 95.0 outside",
        "unclosed_ring.json": "not closed",
    }
    for path in harness.select_fixtures(MALFORMED):
        if path.name == "malformed_json.json":
            with pytest.raises(ValueError):
                GeojsonAdapter().to_cdm(path.read_bytes())
            continue
        with pytest.raises(ValueError) as refusal:
            GeojsonAdapter().to_cdm(harness.load_raw(path))
        assert expected[path.name] in str(refusal.value), (path.name, str(refusal.value))


def test_the_swapped_axis_is_refused_when_it_can_be_and_agrees_with_gdal_when_it_cannot():
    """[lat, lon] with a latitude past 90 is refused by geo.py; inside the equatorial band the
    swap is legal and only an external anchor can see it — which is what the GDAL reading test
    is for."""
    with pytest.raises(ValueError, match="usual cause is \\[lat, lon\\] order"):
        GeojsonAdapter().to_cdm(_feature("s", geometry={"type": "Point", "coordinates": [35.7, 139.7]}))
    point = GeojsonAdapter().to_cdm(_raw(FIXTURES / "six_geometries_baltic.json"))[0]
    assert (point.geometry.lon, point.geometry.lat) == (24.1052, 56.9496)


def test_a_crs_member_is_refused_at_every_level_even_when_it_names_wgs84():
    crs = {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}}
    for where in ("collection", "feature", "geometry"):
        document = _collection(_feature("A"))
        target = {"collection": document, "feature": document["features"][0],
                  "geometry": document["features"][0]["geometry"]}[where]
        target["crs"] = crs
        with pytest.raises(ValueError, match="carries a `crs` member"):
            GeojsonAdapter().to_cdm(document)


def test_non_finite_numbers_are_refused_from_text_and_from_a_parsed_twin():
    with pytest.raises(ValueError, match="refuses"):
        GeojsonAdapter().to_cdm(b'{"type": "Feature", "id": 1, "geometry": null, "properties": {"v": Infinity}}')
    with pytest.raises(ValueError, match="refuses"):
        GeojsonAdapter(as_of=AS_OF).to_cdm(_feature("A", geometry=None, properties={"v": float("nan")}))


def test_an_empty_collection_is_no_object_and_its_members_are_reported_lost_not_hidden():
    document = _collection(name="EXERCISE empty layer")
    assert GeojsonAdapter().to_cdm(document) == []
    book = _ledger(document, [])
    assert {e.source_path for e in book.lost} == {"type", "name", "features"}
    assert all(e.loss == "MISSING" for e in book.lost)


def test_ring_orientation_is_accepted_kept_and_reported_never_repaired():
    raw = _raw(FIXTURES / "feature_zero_meridian_clockwise_ring.json")
    square = GeojsonAdapter().to_cdm(raw)[0]
    assert square.geometry.coordinates == raw["geometry"]["coordinates"], "not reversed"
    notes = [t for t in square.source.transformations if t.startswith("ring orientation")]
    assert len(notes) == 2 and "exterior) is clockwise" in notes[0] and "hole) is counterclockwise" in notes[1]
    assert ring_orientation(raw["geometry"]["coordinates"][0]) == "clockwise"
    problems = GeojsonAdapter().validate_source(raw)
    assert len(problems) == 2 and all("RFC 7946 §3.1.6" in p for p in problems)
    conformant = GeojsonAdapter().to_cdm(_raw(FIXTURES / "six_geometries_baltic.json"))[2]
    assert not [t for t in conformant.source.transformations if t.startswith("ring orientation")]


def test_an_antimeridian_bbox_is_preserved_verbatim_and_reported_as_uncarriable():
    raw = _raw(FIXTURES / "antimeridian_bbox_repeated_values.json")
    for obj in GeojsonAdapter().to_cdm(raw):
        assert obj.residual.data["document"]["bbox"] == [179.5, -17.0, -179.5, -16.0]
        note = next(t for t in obj.source.transformations if t.startswith("bbox"))
        assert "crosses the antimeridian (west 179.5 > east -179.5" in note
    ordinary = GeojsonAdapter().to_cdm(_raw(FIXTURES / "six_geometries_baltic.json"))[2]
    notes = [t for t in ordinary.source.transformations if t.startswith("bbox")]
    assert len(notes) == 2 and not any("antimeridian" in n for n in notes)
    assert ordinary.residual.data["feature"]["geometry"]["bbox"] == [21.5, 57.0, 22.0, 57.5]


# ------------------------------------------------------------------ the ledger, and the three negatives

def test_repeated_identical_values_cannot_conceal_a_value_on_the_wrong_feature():
    """Both features carry `reading: 7`. The `#[*]` target holds each leaf to its own object, so
    swapping the two residuals reads WRONG_OBJECT and not MAPPED."""
    raw = _raw(FIXTURES / "antimeridian_bbox_repeated_values.json")
    dumped = _dump(GeojsonAdapter().to_cdm(raw))
    assert lossless.ledger(raw, dumped, GeojsonAdapter.MAPPINGS).lost == ()
    swapped = copy.deepcopy(dumped)
    swapped[0]["residual"], swapped[1]["residual"] = dumped[1]["residual"], dumped[0]["residual"]
    lost = lossless.ledger(raw, swapped, GeojsonAdapter.MAPPINGS).lost
    assert {e.source_path for e in lost} >= {"features[0].id", "features[0].properties.name",
                                             "features[1].properties.name"}
    assert not any(e.source_path.endswith("properties.reading") for e in lost), \
        "the repeated 7 is on both objects, so it is the id and the name that expose the swap"


def test_negative_a_swapped_lon_lat_in_the_output_is_caught_by_the_ledger():
    raw = _raw(FIXTURES / "six_geometries_baltic.json")
    dumped = _dump(GeojsonAdapter().to_cdm(raw))
    dumped[0]["geometry"]["coordinates"] = [56.9496, 24.1052]
    lost = lossless.ledger(raw, dumped, GeojsonAdapter.MAPPINGS).lost
    assert {e.source_path for e in lost} == {"features[0].geometry.coordinates[0]",
                                             "features[0].geometry.coordinates[1]"}
    assert {e.loss for e in lost} == {"ORDER"}, "each value is on the SIBLING index: the swap, named"


def test_negative_a_dropped_property_is_caught_by_the_ledger():
    raw = _raw(FIXTURES / "six_geometries_baltic.json")
    dumped = _dump(GeojsonAdapter().to_cdm(raw))
    del dumped[1]["residual"]["data"]["feature"]["properties"]["length_km"]
    lost = lossless.ledger(raw, dumped, GeojsonAdapter.MAPPINGS).lost
    assert [e.source_path for e in lost] == ["features[1].properties.length_km"]
    assert lost[0].loss == "MISSING"


def test_negative_a_wrong_identity_policy_is_caught_by_the_ledger():
    """An adapter keying a feature that HAS an id on its record index would put `#0` where the
    ledger expects the id — LOST on `source_ids[0].external_id`, whatever the residual holds."""
    raw = _raw(FIXTURES / "six_geometries_baltic.json")
    dumped = _dump(GeojsonAdapter().to_cdm(raw))
    dumped[0]["source_ids"][0]["external_id"] = "#0"
    lost = lossless.ledger(raw, dumped, GeojsonAdapter.MAPPINGS).lost
    assert [e.source_path for e in lost] == ["features[0].id"]
    assert lost[0].expected["destination"] == "#[*]:source_ids[0].external_id"


def test_the_ledger_binds_every_leaf_of_every_fixture_with_no_loss():
    for path in FIXTURE_FILES:
        raw = _raw(path)
        book = _ledger(raw, GeojsonAdapter().to_cdm(raw))
        assert book.lost == (), (path.name, book.problem_lines())
        assert book.total == len(lossless.typed_leaves(raw))


# ------------------------------------------------------------------ determinism

def test_determinism_across_runs_and_across_hash_seeds():
    """Two fresh instances agree, and two INTERPRETERS with different PYTHONHASHSEED values
    agree on the canonical serialisation of every fixture."""
    for path in FIXTURE_FILES:
        assert _dump(GeojsonAdapter().to_cdm(_raw(path))) == _dump(GeojsonAdapter().to_cdm(_raw(path)))
    script = (
        "import json, sys, pathlib\n"
        "from synapse_cdm.adapters.geojson import GeojsonAdapter\n"
        "from synapse_cdm import canonical\n"
        "out = [canonical.serialise([o.model_dump(mode='json') for o in GeojsonAdapter().to_cdm("
        "json.loads(pathlib.Path(p).read_text()))]) for p in sys.argv[1:]]\n"
        "print(json.dumps(out))\n")
    readings = []
    for seed in ("0", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(PKG.parent)}
        result = subprocess.run([sys.executable, "-c", script, *map(str, FIXTURE_FILES)],
                                capture_output=True, text=True, env=env, check=True)
        readings.append(result.stdout)
    assert readings[0] == readings[1]


def test_member_order_does_not_change_the_output_but_feature_order_does():
    raw = _raw(FIXTURES / "six_geometries_baltic.json")
    reordered = {k: raw[k] for k in reversed(list(raw))}
    reordered["features"] = [{k: f[k] for k in reversed(list(f))} for f in raw["features"]]
    assert _dump(GeojsonAdapter().to_cdm(raw)) == _dump(GeojsonAdapter().to_cdm(reordered))
    shuffled = dict(raw, features=list(reversed(raw["features"])))
    a, b = _dump(GeojsonAdapter().to_cdm(raw)), _dump(GeojsonAdapter().to_cdm(shuffled))
    assert [o["object_id"] for o in a] == [o["object_id"] for o in reversed(b)]
    assert [o["source"]["record_index"] for o in b] == [0, 1, 2, 3, 4, 5], \
        "record_index is the position in the document as sent: feature order is meaningful"


# ------------------------------------------------------------------ bounds, at and past

def _bare(features: int, props: int = 0) -> bytes:
    feature = '{"type":"Feature","id":%d,"geometry":{"type":"Point","coordinates":[1.0,2.0]},"properties":{}}'
    return ('{"type":"FeatureCollection","features":[' + ",".join(feature % i for i in range(features))
            + "]}").encode()


def test_the_byte_bound_admits_a_document_at_it_and_refuses_one_octet_past():
    head = b'{"type":"Feature","id":1,"geometry":{"type":"Point","coordinates":[1.0,2.0]},"properties":{"pad":"'
    tail = b'"}}'
    at = head + b"x" * (GEOJSON_MAX_INPUT_BYTES - len(head) - len(tail)) + tail
    assert len(at) == GEOJSON_MAX_INPUT_BYTES
    assert len(GeojsonAdapter().to_cdm(at)) == 1
    with pytest.raises(adapter_module.InputTooLarge):
        GeojsonAdapter().to_cdm(at + b" ")


def test_the_depth_bound_admits_a_document_at_it_and_refuses_one_level_past():
    def nest(levels: int) -> dict:
        value: object = 1
        for _ in range(levels):
            value = [value]
        return _feature("d", properties={"deep": value})
    # a Feature document is 1 container, properties 2, the first list 3 ... so `deep` nests
    # GEOJSON_MAX_DEPTH - 2 lists to sit exactly at the bound.
    at = nest(GEOJSON_MAX_DEPTH - 2)
    assert adapter_module.container_depth(at) == GEOJSON_MAX_DEPTH
    assert len(GeojsonAdapter().to_cdm(at)) == 1
    assert len(GeojsonAdapter().to_cdm(json.dumps(at).encode())) == 1
    past = nest(GEOJSON_MAX_DEPTH - 1)
    with pytest.raises(adapter_module.InputTooDeep):
        GeojsonAdapter().to_cdm(past)
    with pytest.raises(adapter_module.InputTooDeep):
        GeojsonAdapter().to_cdm(json.dumps(past).encode())


def test_the_feature_bound_admits_a_collection_at_it_and_refuses_one_feature_past():
    at = _bare(GEOJSON_MAX_FEATURES)
    assert len(at) < GEOJSON_MAX_INPUT_BYTES
    assert len(GeojsonAdapter().to_cdm(at)) == GEOJSON_MAX_FEATURES
    with pytest.raises(FeatureCountExceeded, match="nothing is truncated"):
        GeojsonAdapter().to_cdm(_bare(GEOJSON_MAX_FEATURES + 1))


def test_the_position_bound_admits_a_geometry_at_it_and_refuses_one_position_past():
    def line(n: int) -> dict:
        return _feature("p", geometry={"type": "LineString",
                                       "coordinates": [[0.0, 0.0]] * n})
    assert len(GeojsonAdapter().to_cdm(line(GEOJSON_MAX_POSITIONS))) == 1
    with pytest.raises(PositionCountExceeded):
        GeojsonAdapter().to_cdm(line(GEOJSON_MAX_POSITIONS + 1))
    two = _collection(line(GEOJSON_MAX_POSITIONS // 2 + 1), line(GEOJSON_MAX_POSITIONS // 2))
    with pytest.raises(PositionCountExceeded, match="across the whole document|more than"):
        GeojsonAdapter().to_cdm(two)


def test_the_declared_limits_are_the_enforced_constants():
    limits = GeojsonAdapter.metadata.capabilities.limits
    assert limits.max_input_bytes == GEOJSON_MAX_INPUT_BYTES
    assert limits.max_depth == GEOJSON_MAX_DEPTH
    assert limits.max_objects == GEOJSON_MAX_FEATURES
    assert set(limits.declared_because) == {"max_input_bytes", "max_depth", "max_objects"}
    for basis in limits.declared_because.values():
        assert basis.kind.value == "implementation_cap"
        path, _, function = basis.test.partition("::")
        assert f"def {function}(" in (pathlib.Path(__file__).resolve().parents[1] / path
                                       ).read_text(), basis.test


def test_the_adapter_resolves_no_reference_and_touches_no_file_or_network():
    """Read from the module's AST: nothing that opens a file, a socket or a URL is imported or
    called, so a property holding a path or a URL is inert data."""
    tree = ast.parse(pathlib.Path(module.__file__).read_text())
    imported = {n.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                for n in node.names}
    imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                 if isinstance(node, ast.ImportFrom)}
    assert not imported & {"urllib", "socket", "http", "requests", "pathlib", "os", "io"}, imported
    calls = {node.func.id for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "open" not in calls
    document = _feature("A", properties={"href": "https://example.invalid/x", "path": "/etc/passwd"})
    obj = GeojsonAdapter().to_cdm(document)[0]
    assert obj.residual.data["document"]["properties"]["href"] == "https://example.invalid/x"


# ------------------------------------------------------------------ egress

def _semantically_equal(a, b) -> None:
    """The module docstring's definition, asserted: type, feature order, typed ids, numeric
    coordinates, null geometry, properties with null, foreign members, bbox."""
    assert a["type"] == b["type"]
    fa = a["features"] if a["type"] == "FeatureCollection" else [a]
    fb = b["features"] if b["type"] == "FeatureCollection" else [b]
    assert len(fa) == len(fb)
    for x, y in zip(fa, fb):
        assert ("id" in x) == ("id" in y)
        if "id" in x:
            assert x["id"] == y["id"] and type(x["id"]) is type(y["id"])
        assert (x["geometry"] is None) == (y["geometry"] is None)
        if x["geometry"] is not None:
            assert x["geometry"]["type"] == y["geometry"]["type"]
            assert json.dumps(_floats(x["geometry"]["coordinates"])) == \
                json.dumps(_floats(y["geometry"]["coordinates"]))
            assert {k: v for k, v in x["geometry"].items() if k not in ("type", "coordinates")} == \
                {k: v for k, v in y["geometry"].items() if k not in ("type", "coordinates")}
        assert x["properties"] == y["properties"]
        assert {k: v for k, v in x.items() if k not in ("geometry", "properties")} == \
            {k: v for k, v in y.items() if k not in ("geometry", "properties")}
    assert {k: v for k, v in a.items() if k != "features"} == \
        {k: v for k, v in b.items() if k != "features"}


def _floats(node):
    return [_floats(v) for v in node] if isinstance(node, list) and node and isinstance(node[0], list) \
        else [float(v) for v in node]


def test_semantic_round_trip_of_every_fixture():
    for path in FIXTURE_FILES:
        raw = _raw(path)
        adapter = GeojsonAdapter()
        emitted = adapter.from_cdm(adapter.to_cdm(raw))
        _semantically_equal(raw, json.loads(emitted))
        assert emitted == adapter.from_cdm(GeojsonAdapter().to_cdm(raw)), "deterministic bytes"
        assert json.loads(emitted) == json.loads(GeojsonAdapter().from_cdm(
            GeojsonAdapter().to_cdm(json.loads(emitted)))), "a second trip is a fixed point"


def test_a_bare_feature_comes_back_as_a_feature_and_a_collection_as_a_collection():
    raw = _raw(FIXTURES / "feature_zero_meridian_clockwise_ring.json")
    assert json.loads(GeojsonAdapter().from_cdm(GeojsonAdapter().to_cdm(raw)))["type"] == "Feature"
    two = GeojsonAdapter().to_cdm(raw) + GeojsonAdapter().to_cdm(_feature("B"))
    out = json.loads(GeojsonAdapter().from_cdm(two))
    assert out["type"] == "FeatureCollection" and [f["id"] for f in out["features"]] == ["eq-0", "B"]
    assert set(out) == {"type", "features"}, "two bare Features share no collection members"
    raw = _raw(FIXTURES / "six_geometries_baltic.json")
    out = json.loads(GeojsonAdapter().from_cdm(GeojsonAdapter().to_cdm(raw)))
    assert out["type"] == "FeatureCollection" and out["name"] == raw["name"] and out["bbox"] == raw["bbox"]


def test_null_geometry_round_trips_as_null():
    document = _feature("nowhere", properties={"k": None})
    document["geometry"] = None
    adapter = GeojsonAdapter(as_of=AS_OF)
    out = json.loads(adapter.from_cdm(adapter.to_cdm(document)))
    assert out["geometry"] is None and out["properties"] == {"k": None} and out["id"] == "nowhere"


@pytest.mark.parametrize("path", EGRESS_FILES, ids=lambda p: p.stem)
def test_every_egress_fixture_matches_its_golden_under_both_profiles(path):
    """Fresh egress: records a planning stub wrote, never this adapter, under both profiles."""
    record = json.loads(path.read_text())
    obj = KINDS[record["object_kind"]].model_validate(record)
    for profile, tag in ((EXPORT_GENERIC, "generic"), (EXPORT_EXCHANGE, "exchange")):
        emitted = GeojsonAdapter(export=profile).from_cdm([obj])
        golden = (EGRESS / "golden" / f"{path.stem}.{tag}.geojson").read_bytes()
        assert emitted == golden, (path.name, tag)
        document = json.loads(emitted)
        feature = document["features"][0]
        assert feature["id"] == str(record.get("object_id") or record["entity_id"])
        if tag == "generic":
            assert feature["properties"] == {} and "sc:profile" not in document
        else:
            assert document["sc:profile"] == EXPORT_EXCHANGE
            assert feature["properties"]["sc:object_kind"] == record["object_kind"]
            assert feature["properties"]["sc:source_ids"] == record["source_ids"]
            assert feature["properties"]["sc:synthetic"] is True
    entity_geometry = json.loads(GeojsonAdapter().from_cdm([obj]))["features"][0]["geometry"]
    if isinstance(obj, Entity) and obj.position is not None:
        assert entity_geometry == {"type": "Point", "coordinates": [24.1052, 56.9496, 8.0]}
    elif isinstance(obj, Entity):
        assert entity_geometry is None


def test_the_exchange_profile_never_overwrites_a_source_property_in_its_namespace():
    raw = _collection(_feature("A", properties={EXCHANGE_PREFIX + "object_id": "theirs"}))
    objects = GeojsonAdapter().to_cdm(raw)
    assert objects[0].residual.data["feature"]["properties"] == {"sc:object_id": "theirs"}, \
        "on ingest an sc: key is an ordinary source property, never read as canonical meaning"
    assert json.loads(GeojsonAdapter().from_cdm(objects))["features"][0]["properties"] == {
        "sc:object_id": "theirs"}
    with pytest.raises(ValueError, match="never overwritten"):
        GeojsonAdapter(export=EXPORT_EXCHANGE).from_cdm(objects)
    exported = GeojsonAdapter(export=EXPORT_EXCHANGE).from_cdm(
        GeojsonAdapter().to_cdm(_collection(_feature("B"))))
    with pytest.raises(ValueError, match="never overwritten"):
        GeojsonAdapter(export=EXPORT_EXCHANGE).from_cdm(GeojsonAdapter().to_cdm(json.loads(exported)))


def test_egress_refuses_an_incompatible_kind_and_a_mix_of_source_collections():
    with pytest.raises(ValueError, match="not compatible"):
        GeojsonAdapter().from_cdm([Event.model_validate({
            "object_kind": "event", "source": {"system": "X", "adapter": "x", "adapter_version": "1.0.0",
                                              "synthetic": True},
            "source_ids": [{"system": "X", "external_id": "1"}],
            "event_id": "f1c70000-0016-8000-8000-000000000009", "event_type": "ALERT",
            "severity": "INFO", "observed_at": "2026-04-29T06:00:00Z",
            "received_at": "2026-04-29T06:00:00Z"})])
    a = GeojsonAdapter().to_cdm(_collection(_feature("A"), name="one"))
    b = GeojsonAdapter().to_cdm(_collection(_feature("B"), name="two"))
    with pytest.raises(ValueError, match="two different collection-level blocks"):
        GeojsonAdapter().from_cdm(a + b)
    fresh = KINDS["plan_object"].model_validate(json.loads(
        (EGRESS / "fresh_control_measure_polygon.json").read_text()))
    with pytest.raises(ValueError, match="others carry none"):
        GeojsonAdapter().from_cdm(a + [fresh])


# ------------------------------------------------------------------ the v2 surface and the manifest

def test_detect_is_the_cheap_structural_test():
    adapter = GeojsonAdapter()
    assert adapter.detect(_feature("A")) is True
    assert adapter.detect(b'{"type": "FeatureCollection", "features": []}') is True
    assert adapter.detect({"type": "Point", "coordinates": [1.0, 2.0]}) is False
    assert adapter.detect(b"<event/>") is False
    assert adapter.detect(42) is None


def test_the_manifest_is_generator_output_and_declares_the_structured_residual():
    """`manifests/geojson.json` on disk is held to this by `tests/test_cdm_manifests.py`, which
    is repository-bound; this half judges the declaration the generator reads."""
    from synapse_cdm import manifests
    generated = manifests.generate()["geojson"]
    assert generated["adapter"]["id"] == "geojson"
    assert generated["adapter"]["residual"] == "structured"
    assert generated["adapter"]["evidence"]["available"] is False
    assert generated["adapter"]["maturity"]["level"] == "L4"
    assert generated["adapter"]["capabilities"]["limits"]["max_objects"] == GEOJSON_MAX_FEATURES


def test_the_module_docstring_claims_the_ordinal_and_the_structured_residual():
    assert module.__doc__.lstrip().startswith("GeoJSON (RFC 7946) Feature / FeatureCollection <-> CDM. Adapter #16")
    assert "residual: structured" in module.__doc__
