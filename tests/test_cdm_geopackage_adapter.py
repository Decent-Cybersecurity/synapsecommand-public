"""Adapter #17 — GeoPackage 1.4.0 (OGC 12-128r19), ingest only, `residual: structured`.

One test per claim in `adapters/geopackage.py`'s docstring, plus the master prompt's
cross-cutting list (stable identity across layers and namespaces, zeros kept, wrong
version/profile refused, coordinate order and vertical meaning, missing context, hash seeds,
bounds at and past the limit, no network, egress refused) and the NEGATIVE tests that prove a
wrong mapping is caught rather than blessed: a swapped lon/lat, a dropped attribute and a wrong
primary key are each fed to the ledger as if the adapter had produced them and each reads LOST;
a flipped byte-order octet and an SRS whose id says 4326 while its definition says Web Mercator
are each fed to the decoder and each is refused.

THE ORACLE IS GDAL, NOT THE ADAPTER. Every `.gpkg` here was written by GDAL 3.13.3 from the
synthetic sources under `sources/` (`spec/build_fixtures.py`), and `independent/`
holds GDAL's own reading of every layer; `test_the_adapter_agrees_with_the_independent_gdal_reading`
compares geometry, attributes, ids, nulls and CRS against those files. The `.parsed.json` twin
beside each package is the adapter's parsed form, shipped so the harness has leaves to bind,
and `test_every_twin_is_the_parse_of_its_octets_and_translates_identically` is what makes the
twin evidence rather than a second opinion.

The in-test packages for the bounds are built by `_package()` with `sqlite3` and `struct` —
not by hand as fixtures and not claimed as independent: they exist only to hold the limits to
their constants at and one past the bound.
"""
from __future__ import annotations

import ast
import copy
import hashlib
import json
import math
import os
import pathlib
import sqlite3
import struct
import subprocess
import sys

import pytest

import synapse_cdm
from synapse_cdm import harness, ids, lossless, times
from synapse_cdm.adapter import InputTooDeep
from synapse_cdm.adapters import geopackage as module
from synapse_cdm.adapters import geopackage_codec as codec
from synapse_cdm.adapters.geojson import EXPORT_EXCHANGE, GeojsonAdapter
from synapse_cdm.adapters.geopackage import (
    GEOPACKAGE_MAX_BLOB_BYTES,
    GEOPACKAGE_MAX_COORDINATES,
    GEOPACKAGE_MAX_DEPTH,
    GEOPACKAGE_MAX_INPUT_BYTES,
    GEOPACKAGE_MAX_OUTPUT_BYTES,
    GEOPACKAGE_MAX_ROWS,
    AsOf,
    BlobSizeExceeded,
    GeopackageAdapter,
    GeopackageError,
    OutputSizeExceeded,
    RowCountExceeded,
    parse_payload,
)
from synapse_cdm.models import Entity, PlanObject

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
TESTS = pathlib.Path(__file__).resolve().parent
FIXTURES = PKG / "fixtures" / "geopackage"
MALFORMED = FIXTURES / "malformed"
SPEC = FIXTURES / "spec"
PIN = SPEC / "geopackage_pin.json"
PACKAGES = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".gpkg")
TWINS = sorted(p for p in harness.select_fixtures(FIXTURES) if p.suffix == ".json")
DEMO = FIXTURES / "exercise_facilities_routes_areas.gpkg"
FAMILIES = FIXTURES / "six_families_geometry_column.gpkg"
CRS = FIXTURES / "elevations_epsg4979_and_crs84.gpkg"
MIXED = FIXTURES / "mixed_content_partial_read.gpkg"
AS_OF = AsOf("2026-04-29T06:00:00Z", "the synthetic dataset's stated snapshot instant")


def _dump(objects):
    return [o.model_dump(mode="json") for o in objects]


def _twin(path: pathlib.Path) -> dict:
    return json.loads(path.with_suffix(".parsed.json").read_text())


def _ledger(raw, objects):
    return lossless.ledger(raw, _dump(objects), GeopackageAdapter.MAPPINGS)


# ------------------------------------------------------------- an in-test package builder

WGS84 = ('GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
         'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433],AUTHORITY["EPSG","4326"]]')
MERCATOR = ('PROJCS["WGS 84 / Pseudo-Mercator",GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",'
            '6378137,298.257223563]]],PROJECTION["Mercator_1SP"],AUTHORITY["EPSG","3857"]]')


def _gpb(coordinates, *, kind="Point", little=True, srs_id=4326, flags_extra=0) -> bytes:
    """A StandardGeoPackageBinary Point or LineString, envelope indicator 0."""
    order = "<" if little else ">"
    flags = (1 if little else 0) | flags_extra
    header = b"GP\x00" + bytes([flags]) + struct.pack(order + "i", srs_id)
    if kind == "Point":
        wkb = bytes([1 if little else 0]) + struct.pack(order + "I", 1) + struct.pack(
            order + "dd", *coordinates)
    else:
        wkb = bytes([1 if little else 0]) + struct.pack(order + "II", 2, len(coordinates))
        wkb += b"".join(struct.pack(order + "dd", *p) for p in coordinates)
    return header + wkb


def _package(rows, *, definition=WGS84, srs_id=4326, geometry_type="POINT", z=0, m=0,
             description="", extra_sql=(), contents_extra=(), pk="fid") -> bytes:
    """A minimal GeoPackage 1.4.0 with one feature table `t` (columns fid, geom, name, payload)
    holding `rows` = [(fid, blob-or-None, name, payload-or-None), ...]."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(f"""
        CREATE TABLE gpkg_spatial_ref_sys (srs_name TEXT NOT NULL, srs_id INTEGER NOT NULL
            PRIMARY KEY, organization TEXT NOT NULL, organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL, description TEXT);
        CREATE TABLE gpkg_contents (table_name TEXT NOT NULL PRIMARY KEY, data_type TEXT NOT
            NULL, identifier TEXT UNIQUE, description TEXT DEFAULT '', last_change DATETIME NOT
            NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), min_x DOUBLE, min_y DOUBLE,
            max_x DOUBLE, max_y DOUBLE, srs_id INTEGER);
        CREATE TABLE gpkg_geometry_columns (table_name TEXT NOT NULL, column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL, srs_id INTEGER NOT NULL, z TINYINT NOT NULL,
            m TINYINT NOT NULL);
        CREATE TABLE gpkg_extensions (table_name TEXT, column_name TEXT, extension_name TEXT NOT
            NULL, definition TEXT NOT NULL, scope TEXT NOT NULL);
        CREATE TABLE t ("{pk}" INTEGER PRIMARY KEY, geom {geometry_type}, name TEXT,
            payload BLOB);
        PRAGMA application_id = 0x47504B47;
        PRAGMA user_version = 10400;
    """)
    conn.executemany("INSERT INTO gpkg_spatial_ref_sys VALUES (?, ?, ?, ?, ?, ?)", [
        ("Undefined cartesian SRS", -1, "NONE", -1, "undefined", None),
        ("Undefined geographic SRS", 0, "NONE", 0, "undefined", None),
        ("WGS 84 geodetic", srs_id, "EPSG", srs_id, definition, None)])
    conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, description, "
                 "last_change, srs_id) VALUES ('t', 'features', 't', ?, "
                 "'2026-09-20T00:00:00.000Z', ?)", (description, srs_id))
    for row in contents_extra:
        conn.execute("INSERT INTO gpkg_contents (table_name, data_type, identifier, last_change,"
                     " srs_id) VALUES (?, ?, ?, '2026-09-20T00:00:00.000Z', ?)", row)
    conn.execute("INSERT INTO gpkg_geometry_columns VALUES ('t', 'geom', ?, ?, ?, ?)",
                 (geometry_type, srs_id, z, m))
    conn.executemany("INSERT INTO t VALUES (?, ?, ?, ?)", rows)
    for sql in extra_sql:
        conn.execute(sql)
    conn.commit()
    octets = conn.serialize()
    conn.close()
    return octets


# ------------------------------------------------------------------ the fixtures themselves

def test_the_fixture_set_is_the_documented_one():
    assert [p.name for p in PACKAGES] == [
        "elevations_epsg4979_and_crs84.gpkg",
        "exercise_facilities_routes_areas.gpkg",
        "mixed_content_partial_read.gpkg",
        "six_families_geometry_column.gpkg",
    ]
    assert [p.name for p in TWINS] == [p.with_suffix(".parsed.json").name for p in PACKAGES]
    assert len(harness.select_fixtures(MALFORMED)) == 15


def test_every_fixture_is_synthetic_by_default():
    """No real GeoPackage data in this repository, and the objects must say so (TR-12)."""
    for path in PACKAGES:
        for obj in GeopackageAdapter().to_cdm(path.read_bytes()):
            assert obj.source.synthetic is True, path.name
            assert obj.source.system == "GeoPackage"
            assert obj.source.format_name == "GeoPackage"
            assert obj.source.format_version == "1.4.0 (OGC 12-128r19)"


def test_every_fixture_matches_the_record_in_spec():
    """`spec/geopackage_pin.json` states a SHA-256 and a byte count for every package, twin,
    malformed package, source and independent reading; the tree must be what the record says
    and the record must name every file."""
    record = json.loads(PIN.read_text())
    listed = {(FIXTURES, e["file"]): e for e in record["fixtures"]}
    listed.update({(FIXTURES, e["file"]): e for e in record["twins"]})
    listed.update({(MALFORMED, e["file"]): e for e in record["malformed"]["files"]})
    listed.update({(FIXTURES / "sources", e["file"]): e for e in record["sources"]})
    listed.update({(FIXTURES / "independent", e["file"]): e for e in record["independent"]})
    on_disk = {(d, p.name) for d in (FIXTURES, MALFORMED) for p in harness.select_fixtures(d)}
    on_disk |= {(d, p.name) for d in (FIXTURES / "sources", FIXTURES / "independent")
                for p in harness.select_fixtures(d)}
    assert set(listed) == on_disk, set(listed) ^ on_disk
    for (directory, name), entry in listed.items():
        path = directory / name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"], name
        assert path.stat().st_size == entry["bytes"], name
    assert record["independent_implementation"]["version"].startswith("GDAL 3.13.3")
    assert "ogr2ogr --version" in " ".join(record["independent_implementation"]["commands"])


def test_every_twin_is_the_parse_of_its_octets_and_translates_identically():
    """CONTRIBUTING.md's twin rule, proved rather than asserted: the shipped `.parsed.json` IS
    `parse_payload(octets)`, and the adapter produces the same CDM from either form."""
    for path in PACKAGES:
        octets = path.read_bytes()
        assert parse_payload(octets) == _twin(path), path.name
        assert _dump(GeopackageAdapter().to_cdm(octets)) == \
            _dump(GeopackageAdapter().to_cdm(_twin(path))), path.name


def _independent(package: pathlib.Path, layer: str) -> tuple[dict, dict]:
    ogrinfo = json.loads((FIXTURES / "independent" / f"{package.stem}.{layer}.ogrinfo.json")
                         .read_text())
    geojson = json.loads((FIXTURES / "independent" / f"{package.stem}.{layer}.geojson").read_text())
    return ogrinfo["layers"][0], geojson


def _flat(node) -> list[float]:
    out: list[float] = []
    pending = [node]
    while pending:
        current = pending.pop(0)
        if isinstance(current, list) and current and isinstance(current[0], list):
            pending = list(current) + pending
        else:
            out.extend(float(v) for v in current)
    return out


def test_the_adapter_agrees_with_the_independent_gdal_reading():
    """GDAL's `ogrinfo -json -features` and `ogr2ogr -f GeoJSON` over every included layer:
    feature count, every fid, every geometry (type and every coordinate, Z included), every
    attribute with NULL kept and a BLOB as hex, and the CRS — an oracle the adapter cannot
    influence, so a swapped axis, a dropped vertex or a misread NULL is a disagreement."""
    record = json.loads(PIN.read_text())
    compared = 0
    for path in PACKAGES:
        objects = GeopackageAdapter().to_cdm(path.read_bytes())
        entry = next(e for e in record["fixtures"] if e["file"] == path.name)
        included = json.loads(path.with_suffix(".parsed.json").read_text())["inventory"]["included"]
        for layer in included:
            reading, geojson = _independent(path, layer)
            mine = [o for o in objects if o.residual.data["row"]["layer"] == layer]
            assert len(mine) == reading["featureCount"] == entry["layers"][layer]["feature_count"]
            assert [int(o.source.original_id) for o in mine] == [f["fid"] for f in
                                                                 reading["features"]]
            wkt = reading["geometryFields"][0]["coordinateSystem"]["wkt"]
            accepted = mine[0].residual.data["package"]["layers"]
            accepted = next(d for d in accepted if d["name"] == layer)["crs"]["accepted_as"]
            assert "WGS 84" in wkt.split("\n")[0]
            if accepted.startswith("EPSG:"):
                assert f'ID["EPSG",{accepted[5:]}]' in wkt, (layer, accepted)
            else:
                assert accepted == "OGC:CRS84" and "CRS84" in wkt
            for obj, feature, exported in zip(mine, reading["features"], geojson["features"]):
                assert exported["id"] == feature["fid"] == int(obj.source.original_id)
                assert obj.geometry.type == feature["geometry"]["type"] == \
                    exported["geometry"]["type"]
                assert _flat(obj.geometry.model_dump(mode="json")["coordinates"]) == \
                    _flat(feature["geometry"]["coordinates"]) == \
                    _flat(exported["geometry"]["coordinates"]), (layer, feature["fid"])
                attributes = dict(obj.residual.data["row"]["attributes"])
                binary = {f["name"] for f in reading["fields"] if f["type"] == "Binary"}
                for key, value in attributes.items():
                    if isinstance(value, dict) and value.get("encoding") == "hex":
                        assert key in binary, (layer, key)
                        attributes[key] = value["hex"]
                assert attributes == exported["properties"], (layer, feature["fid"])
                # `ogrinfo -json` writes a Binary field only when it is NULL and leaves a
                # non-null one out of `properties` (the GeoJSON export carries its hex, compared
                # above); every other field must agree exactly, NULLs included
                for key in binary:
                    assert feature["properties"].get(key) is None
                    assert (key in feature["properties"]) == (attributes[key] is None), key
                assert {k: v for k, v in attributes.items() if k not in binary} == \
                    {k: v for k, v in feature["properties"].items() if k not in binary}, \
                    (layer, feature["fid"])
                compared += 1
    assert compared == 21, "4 + 9 + 2 + 6 rows across the four packages"


def test_the_harness_passes_every_check_on_every_fixture():
    report = harness.run(GeopackageAdapter(clock=times.frozen_clock()), FIXTURES,
                         schema_dir=pathlib.Path("schemas") if pathlib.Path("schemas").is_dir()
                         else None)
    assert report["failed"] == 0, [r["problems"] for r in report["results"]]
    assert report["preservation"]["basis"] == "ledger"
    for result in report["results"]:
        assert result["checks"]["golden"] == "PASS", result["problems"]
        assert result["checks"]["roundtrip"] == "SKIP"        # ingest only: never PASS
        if result["fixture"].endswith(".json"):
            assert result["checks"]["lossless"] == "PASS"
            assert result["preservation"]["counts"]["LOST"] == 0
        else:
            assert result["checks"]["lossless"] == "SKIP"     # octets have no leaves


# ------------------------------------------------------------------ the structured residual

def test_the_residual_is_structured_and_named_for_the_format():
    obj = GeopackageAdapter().to_cdm(DEMO.read_bytes())[0]
    assert obj.residual.namespace == "GeoPackage"
    assert set(obj.residual.data) == {"package", "row"}
    assert set(obj.residual.data["package"]) == {"sqlite", "spatial_ref_sys", "contents",
                                                 "geometry_columns", "extensions", "inventory",
                                                 "layers"}
    assert obj.residual.data["package"]["sqlite"]["user_version"] == 10400
    assert obj.residual.data["package"]["sqlite"]["application_id"] == "GPKG"
    assert "type" not in obj.residual.data["row"]["geometry"]
    assert "coordinates" not in obj.residual.data["row"]["geometry"]
    assert obj.residual.data["row"]["geometry"]["flags"]["byte_order"] == "little"


def test_attributes_are_typed_nulls_kept_and_blobs_carry_their_encoding():
    objects = GeopackageAdapter().to_cdm(DEMO.read_bytes())
    facilities = {o.source.original_id: o.residual.data["row"] for o in objects
                  if o.residual.data["row"]["layer"] == "facilities"}
    first, third = facilities["1"], facilities["3"]
    assert first["attributes"] == {"name": "EXERCISE HARBOUR OFFICE", "category": "port",
                                   "capacity": 120, "ratio": 0.5, "note": None,
                                   "payload": {"encoding": "hex", "hex": "DEADBEEF00"}}
    assert first["attribute_types"] == {"name": "text", "category": "text", "capacity": "integer",
                                        "ratio": "real", "note": "null", "payload": "blob"}
    assert third["attributes"]["capacity"] is None and third["attribute_types"]["capacity"] == "null"
    assert third["attributes"]["payload"] is None
    assert isinstance(first["attributes"]["capacity"], int)
    assert isinstance(first["attributes"]["ratio"], float)


def test_zero_coordinates_and_zero_values_are_real_values():
    objects = GeopackageAdapter().to_cdm(DEMO.read_bytes())
    buoy = next(o for o in objects if o.source_ids[0].external_id == "facilities/2")
    assert buoy.geometry.coordinates == [0.0, 0.0, 0.0]
    assert buoy.residual.data["row"]["attributes"]["capacity"] == 0
    assert buoy.residual.data["row"]["attributes"]["ratio"] == 0.0
    leg = next(o for o in objects if o.source_ids[0].external_id == "routes/2")
    assert leg.residual.data["row"]["attributes"]["length_km"] == 0.0
    assert leg.residual.data["row"]["attributes"]["active"] == 0


def test_the_six_geometry_families_land_on_the_cdm_geometry_with_holes_kept():
    objects = GeopackageAdapter().to_cdm(FAMILIES.read_bytes())
    assert [o.geometry.type for o in objects] == ["Point", "MultiPoint", "LineString",
                                                  "MultiLineString", "Polygon", "MultiPolygon"]
    multipolygon = objects[5].geometry.model_dump(mode="json")["coordinates"]
    assert len(multipolygon) == 2 and len(multipolygon[0]) == 2, "first part keeps its hole"
    assert multipolygon[0][1][0] == [24.05, 57.05]
    for obj in objects:
        assert obj.residual.data["row"]["geometry"]["envelope"] is None or \
            set(obj.residual.data["row"]["geometry"]["envelope"]) == {"min_x", "max_x",
                                                                       "min_y", "max_y"}
    area = next(o for o in GeopackageAdapter().to_cdm(DEMO.read_bytes())
                if o.source_ids[0].external_id == "areas/1")
    assert len(area.geometry.model_dump(mode="json")["coordinates"]) == 2, "the hole is kept"


def test_z_is_carried_with_the_meaning_the_package_declares_and_never_read_as_hae():
    """Facilities: EPSG:4326, z = 1 — no vertical axis, so the note says UNDECLARED. Elevations:
    EPSG:4979 — the SRS declares ellipsoidal height in metres, and the note says so. In both a
    negative or zero Z is kept as the third element and nothing lands in `alt_m`."""
    depot = next(o for o in GeopackageAdapter().to_cdm(DEMO.read_bytes())
                 if o.source_ids[0].external_id == "facilities/3")
    assert depot.geometry.coordinates == [24.4, 57.1, -3.25]
    z_note = next(n for n in depot.source.transformations if n.startswith("z:"))
    assert "UNDECLARED" in z_note and "EPSG:4326" in z_note and "z = 1" in z_note
    mast = next(o for o in GeopackageAdapter().to_cdm(CRS.read_bytes())
                if o.source_ids[0].external_id == "elevations/1")
    assert mast.geometry.coordinates == [24.1, 57.0, 100.0]
    z_note = next(n for n in mast.source.transformations if n.startswith("z:"))
    assert "ellipsoidal height" in z_note and "EPSG:4979" in z_note
    crs_note = next(n for n in mast.source.transformations if n.startswith("crs:"))
    assert "definition_12_063" in crs_note, "the crs_wkt extension column carried the WKT"
    shore = next(o for o in GeopackageAdapter().to_cdm(CRS.read_bytes())
                 if o.source_ids[0].external_id == "elevations/2")
    assert shore.geometry.coordinates[2] == 0.0


def test_coordinates_are_longitude_then_latitude_and_the_crs_is_judged_by_definition():
    objects = GeopackageAdapter().to_cdm(CRS.read_bytes())
    crs84 = [o for o in objects if o.residual.data["row"]["layer"] == "crs84_points"]
    assert crs84[0].geometry.coordinates == [24.1, 57.0], "[lon, lat]: 24.1E 57.0N is Baltic"
    layer = next(d for d in crs84[0].residual.data["package"]["layers"]
                 if d["name"] == "crs84_points")
    assert layer["srs_id"] == 100000 and layer["crs"]["accepted_as"] == "OGC:CRS84"
    srs = next(s for s in crs84[0].residual.data["package"]["spatial_ref_sys"]
               if s["srs_id"] == 100000)
    assert srs["organization"] == "NONE", "the id and organization say nothing; the WKT did"


# ------------------------------------------------------------------ identity

def test_identity_is_namespace_layer_and_primary_key_and_equal_keys_do_not_collide():
    objects = GeopackageAdapter().to_cdm(DEMO.read_bytes())
    assert len(objects) == 9
    assert len({o.object_id for o in objects}) == 9
    assert sorted(o.source_ids[0].external_id for o in objects) == sorted(
        f"{layer}/{pk}" for layer in ("areas", "facilities", "routes") for pk in (1, 2, 3))
    areas_1 = next(o for o in objects if o.source_ids[0].external_id == "areas/1")
    assert areas_1.object_id == ids.derive("GeoPackage", json.dumps(["areas", 1]), kind="feature")
    assert areas_1.source.original_id == "1"
    assert [o.source.record_index for o in objects] == list(range(9))
    assert [o.residual.data["row"]["layer"] for o in objects] == ["areas"] * 3 + \
        ["facilities"] * 3 + ["routes"] * 3, "layer name order, then primary-key order"


def test_identity_is_stable_across_updates_of_mutable_attributes():
    twin = _twin(DEMO)
    before = GeopackageAdapter().to_cdm(twin)[0]
    changed = copy.deepcopy(twin)
    changed["rows"][0]["attributes"]["name"] = "EXERCISE RENAMED"
    changed["rows"][3]["geometry"]["coordinates"] = [24.2, 57.0, 1.0]
    after = GeopackageAdapter().to_cdm(changed)
    assert after[0].object_id == before.object_id
    assert after[3].object_id == GeopackageAdapter().to_cdm(twin)[3].object_id
    assert after[0].residual.data["row"]["attributes"]["name"] == "EXERCISE RENAMED"
    assert after[3].geometry.coordinates == [24.2, 57.0, 1.0]


def test_identities_are_distinct_across_dataset_namespaces():
    octets = DEMO.read_bytes()
    plain = GeopackageAdapter().to_cdm(octets)[0]
    named = GeopackageAdapter(dataset="exercise-baltic").to_cdm(octets)[0]
    assert plain.object_id != named.object_id
    assert named.source_ids[0].system == "GeoPackage:exercise-baltic"
    assert plain.source_ids[0].system == "GeoPackage"
    with pytest.raises(ValueError):
        GeopackageAdapter(dataset="  ")


# ------------------------------------------------------------------ the snapshot

def test_the_source_bytes_are_unchanged_by_translation():
    """Hash before and after, on an immutable `bytes` AND on a mutable `bytearray` handed over
    directly — `deserialize` copies, `query_only` is ON, nothing writes."""
    octets = DEMO.read_bytes()
    before = hashlib.sha256(octets).hexdigest()
    mutable = bytearray(octets)
    GeopackageAdapter().to_cdm(octets)
    GeopackageAdapter().to_cdm(mutable)
    GeopackageAdapter().validate_source(mutable)
    assert hashlib.sha256(octets).hexdigest() == before
    assert hashlib.sha256(bytes(mutable)).hexdigest() == before


def test_wal_mode_bytes_are_refused_unless_the_caller_asserts_a_checkpoint():
    octets = (MALFORMED / "wal_mode_header.gpkg").read_bytes()
    assert octets[18] == 2 and octets[19] == 2
    with pytest.raises(GeopackageError, match="WAL mode.*not a complete snapshot"):
        GeopackageAdapter().to_cdm(octets)
    objects = GeopackageAdapter(wal_checkpointed=True).to_cdm(octets)
    assert len(objects) == 2
    assert any(n.startswith("wal: the SQLite header declares WAL mode") for n in
               objects[0].source.transformations)
    assert objects[0].residual.data["package"]["sqlite"]["wal_read_as_checkpointed"] is True
    assert objects[0].residual.data["package"]["sqlite"]["write_version"] == 2
    assert hashlib.sha256(octets).hexdigest() == hashlib.sha256(
        (MALFORMED / "wal_mode_header.gpkg").read_bytes()).hexdigest()
    # the same rows as the package the WAL copy was made from
    plain = GeopackageAdapter().to_cdm(MIXED.read_bytes())
    assert [o.geometry for o in objects] == [o.geometry for o in plain]
    assert [o.object_id for o in objects] == [o.object_id for o in plain]


def test_an_unsupported_version_is_refused_with_the_value_reported():
    with pytest.raises(GeopackageError, match=r"user_version is 10300 \(GeoPackage 1\.3\.0\).*"
                                              r"unsupported, not malformed"):
        GeopackageAdapter().to_cdm((MALFORMED / "user_version_1_3_0.gpkg").read_bytes())
    octets = bytearray(DEMO.read_bytes())
    octets[68:72] = b"GP10"
    with pytest.raises(GeopackageError, match="GP10 \\(GeoPackage 1.0\\)"):
        GeopackageAdapter().to_cdm(bytes(octets))
    octets = bytearray(DEMO.read_bytes())
    octets[60:64] = (10500).to_bytes(4, "big")
    with pytest.raises(GeopackageError, match=r"10500 \(GeoPackage 1\.5\.0\)"):
        GeopackageAdapter().to_cdm(bytes(octets))


@pytest.mark.parametrize("name, needle", [
    ("empty_and_null_geometry_no_as_of.gpkg", "as-of context is needed"),
    ("geometry_collection_row.gpkg", "GeometryCollection"),
    ("gpb_byte_order_octet_invalid.gpkg", "byte-order octet at offset 40 is 0x02"),
    ("gpb_envelope_disagrees_with_wkb.gpkg", "envelope min_x .* disagrees with the decoded"),
    ("gpb_extended_type_flag.gpkg", "X = 1, an ExtendedGeoPackageBinary"),
    ("gpb_srs_id_disagrees_with_layer.gpkg", "srs_id 4979 differs from the layer's declared 4326"),
    ("not_sqlite_at_all.gpkg", "does not start with the SQLite magic"),
    ("plain_sqlite_not_a_geopackage.gpkg", "SQLite database but not a GeoPackage"),
    ("projected_crs_epsg3857.gpkg", "root is PROJCS, not a geographic CRS"),
    ("truncated_container.gpkg", "SQLite refused"),
    ("undefined_srs_layer.gpkg", "srs_id 99999 .*'Undefined SRS'.* root is LOCAL_CS"),
    ("user_version_1_3_0.gpkg", "GeoPackage 1.3.0"),
    ("wal_mode_header.gpkg", "WAL-dependent"),
    ("wkb_ewkb_flag_bit.gpkg", "PostGIS EWKB flag bit"),
    ("wkb_truncated_polygon.gpkg", "declares 5 ring points needing at least 80 octets and 32 remain"),
])
def test_every_malformed_payload_is_refused_by_name(name, needle):
    with pytest.raises(GeopackageError, match=needle):
        GeopackageAdapter().to_cdm((MALFORMED / name).read_bytes())


def test_measured_geometry_is_refused_explicitly_and_never_dropped_or_read_as_height():
    twin = _twin(MIXED)
    measured = next(u for u in twin["inventory"]["unsupported"] if u["table"] == "measured")
    assert "m = 2" in measured["reason"] and "never read as height" in measured["reason"]
    with pytest.raises(GeopackageError, match="unsupported content: m = 2"):
        GeopackageAdapter(layers=("measured",)).to_cdm(MIXED.read_bytes())
    # an XYM point in the decoder itself, whatever the layer declares
    blob = bytearray(_gpb([24.1, 57.0]))
    blob[9:13] = (2001).to_bytes(4, "little")
    blob += struct.pack("<d", 5.0)
    with pytest.raises(GeopackageError, match="M ordinates .* never dropped and never read as height"):
        codec.geopackage_binary(bytes(blob), budget=[10], where="row")


def test_the_snapshot_denies_writes_attach_other_tables_functions_and_views():
    """The authorizer, exercised directly: after a translation the connection is closed, so the
    proof drives `_Snapshot` itself. Every denied class raises SQLite's `not authorized`."""
    snapshot = module._Snapshot(DEMO.read_bytes(), wal_checkpointed=False)
    try:
        snapshot.readable.add("facilities")
        assert snapshot.query('SELECT count(*) FROM "facilities"') == [(3,)]
        for sql in ("ATTACH DATABASE ':memory:' AS other",
                    "CREATE TABLE x (a)",
                    "INSERT INTO gpkg_contents (table_name, data_type) VALUES ('x', 'features')",
                    "UPDATE gpkg_contents SET description = 'x'",
                    "DELETE FROM gpkg_extensions",
                    "SELECT * FROM rtree_facilities_geom",
                    "SELECT * FROM gpkg_metadata",
                    "SELECT * FROM routes",
                    "SELECT load_extension('x')",
                    "SELECT hex(geom) FROM facilities",
                    "PRAGMA journal_mode",
                    "SELECT * FROM sqlite_master WHERE sql LIKE '%' AND random() > -1"):
            with pytest.raises(GeopackageError, match="not authorized|is prohibited"):
                snapshot.query(sql)
    finally:
        snapshot.close()


def test_a_view_named_as_a_feature_table_is_inventoried_and_never_selected_from():
    octets = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", None)],
                      extra_sql=("CREATE VIEW v AS SELECT * FROM t",),
                      contents_extra=(("v", "features", "v", 4326),))
    objects = GeopackageAdapter().to_cdm(octets)
    inventory = objects[0].residual.data["package"]["inventory"]
    assert inventory["included"] == ["t"]
    assert inventory["unsupported"] == [{"table": "v", "data_type": "features",
                                         "reason": "a view: this adapter never selects from a "
                                                   "view (a source-defined query is never "
                                                   "executed)"}]
    with pytest.raises(GeopackageError, match="unsupported content: a view"):
        GeopackageAdapter(layers=("v",)).to_cdm(octets)


def test_a_generated_column_is_refused_rather_than_evaluated():
    octets = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", None)],
                      extra_sql=("ALTER TABLE t ADD COLUMN twice AS (fid * 2)",))
    with pytest.raises(GeopackageError, match="generated or hidden"):
        GeopackageAdapter().to_cdm(octets)


# ------------------------------------------------------------------ inventory and selection

def test_a_mixed_package_ingests_the_vector_layer_only_and_every_object_says_so():
    objects = GeopackageAdapter().to_cdm(MIXED.read_bytes())
    assert len(objects) == 2
    inventory = objects[0].residual.data["package"]["inventory"]
    assert inventory["included"] == ["positions"]
    assert inventory["unselected"] == []
    assert [(u["table"], u["data_type"]) for u in inventory["unsupported"]] == [
        ("measured", "features"), ("notes", "attributes"), ("tiles_sample", "tiles")]
    note = objects[1].source.transformations[0]
    assert note.startswith("inventory: 1 layer(s) included ['positions'], 0 unselected, "
                           "3 unsupported (['measured', 'notes', 'tiles_sample'])")
    contents = {c["table_name"]: c["data_type"] for c in
                objects[0].residual.data["package"]["contents"]}
    assert contents == {"measured": "features", "notes": "attributes", "positions": "features",
                        "tiles_sample": "tiles"}, "every gpkg_contents row is carried"


def test_an_explicit_layer_selection_reads_those_layers_and_names_the_rest_as_unselected():
    objects = GeopackageAdapter(layers=["routes"]).to_cdm(DEMO.read_bytes())
    assert [o.source_ids[0].external_id for o in objects] == ["routes/1", "routes/2", "routes/3"]
    inventory = objects[0].residual.data["package"]["inventory"]
    assert inventory["included"] == ["routes"]
    assert inventory["unselected"] == [
        {"table": "areas", "reason": "not in the caller's layer selection"},
        {"table": "facilities", "reason": "not in the caller's layer selection"}]
    assert "1 layer(s) included ['routes'], 2 unselected" in objects[0].source.transformations[0]
    with pytest.raises(GeopackageError, match="'harbours' was selected and is not a feature table"):
        GeopackageAdapter(layers=("harbours",)).to_cdm(DEMO.read_bytes())
    with pytest.raises(ValueError):
        GeopackageAdapter(layers="routes")


def test_extension_rows_and_extension_columns_are_carried_as_package_metadata():
    obj = GeopackageAdapter().to_cdm(CRS.read_bytes())[0]
    extensions = obj.residual.data["package"]["extensions"]
    assert {e["extension_name"] for e in extensions} >= {"gpkg_crs_wkt_1_1", "gpkg_rtree_index"}
    srs = next(s for s in obj.residual.data["package"]["spatial_ref_sys"] if s["srs_id"] == 4979)
    assert srs["definition"] == "undefined" and srs["definition_12_063"].startswith("GEODCRS")
    assert "epoch" in srs, "the extension column rides beside the standard ones"


# ------------------------------------------------------------------ time and the as-of context

def test_last_change_is_package_metadata_and_never_an_observation_time():
    obj = GeopackageAdapter(clock=times.frozen_clock()).to_cdm(DEMO.read_bytes())[0]
    assert obj.validity is None
    assert obj.source.observed_at is None
    note = next(n for n in obj.source.transformations if n.startswith("last_change:"))
    assert "'2026-09-20T00:00:00.000Z'" in note and "NOT an observation time" in note


def test_empty_and_null_geometries_need_the_as_of_context_and_become_entities_without_position():
    octets = (MALFORMED / "empty_and_null_geometry_no_as_of.gpkg").read_bytes()
    with pytest.raises(GeopackageError, match="geometry is empty .* as-of context is needed"):
        GeopackageAdapter().to_cdm(octets)
    objects = GeopackageAdapter(as_of=AS_OF).to_cdm(octets)
    assert [type(o).__name__ for o in objects] == ["Entity", "PlanObject", "Entity"]
    empty, present, null = objects
    assert isinstance(empty, Entity) and empty.position is None
    assert empty.valid_from == AS_OF.instant
    assert empty.residual.data["row"]["geometry"]["flags"]["empty"] is True
    assert empty.residual.data["row"]["geometry"]["coordinates"] is None
    assert empty.residual.data["row"]["geometry"]["type"] == "Point"
    assert null.residual.data["row"]["geometry"] is None
    assert any("SQL NULL" in n and "never (0, 0)" in n for n in null.source.transformations)
    assert isinstance(present, PlanObject) and present.validity.observed_at == AS_OF.instant
    # the ledger reads the empty geometry's `type` as the one leaf with no canonical home: an
    # Entity has no geometry field, and the leaf stays in the residual under row.geometry.type
    lost = _ledger(parse_payload(octets), objects).lost
    assert [e.source_path for e in lost] == ["rows[0].geometry.type"]


def test_as_of_lands_on_validity_and_never_on_the_clock():
    clock = times.frozen_clock()
    obj = GeopackageAdapter(clock=clock, as_of=AS_OF).to_cdm(DEMO.read_bytes())[0]
    assert obj.validity.observed_at == AS_OF.instant != clock()
    assert any(n.startswith("validity.observed_at: the caller's as-of context")
               for n in obj.source.transformations)
    with pytest.raises(TypeError):
        GeopackageAdapter(as_of="2026-04-29T06:00:00Z")


# ------------------------------------------------------------------ negative tests

def test_repeated_identical_values_cannot_conceal_a_value_on_the_wrong_row():
    """Facilities 1 and 2 carry the same BLOB. The `#[*]` target holds each leaf to its own
    object, so swapping the two residuals reads LOST on the name and key, not MAPPED."""
    twin = _twin(DEMO)
    dumped = _dump(GeopackageAdapter().to_cdm(twin))
    assert _ledger(twin, GeopackageAdapter().to_cdm(twin)).lost == ()
    swapped = copy.deepcopy(dumped)
    swapped[3]["residual"], swapped[4]["residual"] = dumped[4]["residual"], dumped[3]["residual"]
    lost = lossless.ledger(twin, swapped, GeopackageAdapter.MAPPINGS).lost
    assert {e.source_path for e in lost} >= {"rows[3].pk", "rows[3].attributes.name",
                                             "rows[4].attributes.name"}
    assert not any(e.source_path.endswith("payload.hex") for e in lost)


def test_negative_a_swapped_lon_lat_in_the_output_is_caught_by_the_ledger():
    twin = _twin(DEMO)
    dumped = _dump(GeopackageAdapter().to_cdm(twin))
    dumped[3]["geometry"]["coordinates"] = [56.9496, 24.1052, 12.5]
    lost = lossless.ledger(twin, dumped, GeopackageAdapter.MAPPINGS).lost
    assert {e.source_path for e in lost} == {"rows[3].geometry.coordinates[0]",
                                             "rows[3].geometry.coordinates[1]"}
    assert {e.loss for e in lost} == {"ORDER"}


def test_negative_a_dropped_attribute_is_caught_by_the_ledger():
    twin = _twin(DEMO)
    dumped = _dump(GeopackageAdapter().to_cdm(twin))
    del dumped[6]["residual"]["data"]["row"]["attributes"]["length_km"]
    lost = lossless.ledger(twin, dumped, GeopackageAdapter.MAPPINGS).lost
    assert [e.source_path for e in lost] == ["rows[6].attributes.length_km"]
    # WRONG_OBJECT rather than MISSING: the leaf is absent from ITS row's object while the two
    # sibling rows carry the same path, which is exactly what the ledger reports
    assert lost[0].loss == "WRONG_OBJECT"


def test_negative_a_wrong_primary_key_is_caught_by_the_ledger():
    twin = _twin(DEMO)
    dumped = _dump(GeopackageAdapter().to_cdm(twin))
    dumped[0]["source"]["original_id"] = "0"
    lost = lossless.ledger(twin, dumped, GeopackageAdapter.MAPPINGS).lost
    assert [e.source_path for e in lost] == ["rows[0].pk"]
    assert lost[0].expected["destination"] == "#[*]:source.original_id"


def test_negative_a_flipped_byte_order_octet_is_refused_not_misread():
    """The WKB byte-order octet says big-endian over little-endian doubles: the header's own
    order flag is untouched, so the decoder reads the payload the other way round and refuses
    what it finds — never a silently transposed position."""
    blob = bytearray(_gpb([24.1, 57.0]))
    blob[8] = 0                                     # WKB order octet: 1 (little) -> 0 (big)
    with pytest.raises(GeopackageError):
        codec.geopackage_binary(bytes(blob), budget=[10], where="row")
    blob = bytearray(_gpb([24.1, 57.0]))
    blob[3] ^= 1                                    # GPB flag B flipped: srs_id reads 0x4E100000
    with pytest.raises(GeopackageError, match="srs_id"):
        octets = _package([(1, bytes(blob), "EXERCISE", None)])
        GeopackageAdapter().to_cdm(octets)


def test_negative_an_srs_id_that_says_4326_over_a_mercator_definition_is_refused():
    """Judged by DEFINITION and not by id: the row is srs_id 4326, organization EPSG, code 4326,
    and its WKT is Web Mercator. An adapter trusting the number would relabel projected metres
    as degrees."""
    octets = _package([(1, _gpb([2682000.0, 7800000.0]), "EXERCISE", None)], definition=MERCATOR)
    with pytest.raises(GeopackageError, match="srs_id 4326 .* is not WGS 84 .* PROJCS"):
        GeopackageAdapter().to_cdm(octets)
    octets = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", None)], definition="undefined")
    with pytest.raises(GeopackageError, match="srs_id 4326 .* definition is 'undefined'"):
        GeopackageAdapter().to_cdm(octets)
    twin = _twin(DEMO)
    twin["spatial_ref_sys"][2]["definition"] = MERCATOR
    with pytest.raises(GeopackageError, match="the srs definition reads as .* PROJCS"):
        GeopackageAdapter().to_cdm(twin)


def test_the_ledger_binds_every_leaf_of_every_twin_with_no_loss():
    for path in PACKAGES:
        twin = _twin(path)
        book = _ledger(twin, GeopackageAdapter().to_cdm(twin))
        assert book.lost == (), (path.name, book.problem_lines())
        assert book.total == len(lossless.typed_leaves(twin))


# ------------------------------------------------------------------ determinism

def test_determinism_across_runs_and_across_hash_seeds():
    for path in PACKAGES:
        octets = path.read_bytes()
        assert _dump(GeopackageAdapter().to_cdm(octets)) == _dump(GeopackageAdapter().to_cdm(octets))
    script = (
        "import sys, pathlib\n"
        "from synapse_cdm.adapters.geopackage import GeopackageAdapter\n"
        "from synapse_cdm import canonical\n"
        "out = [canonical.serialise([o.model_dump(mode='json') for o in GeopackageAdapter()"
        ".to_cdm(pathlib.Path(p).read_bytes())]) for p in sys.argv[1:]]\n"
        "sys.stdout.write('\\n'.join(out))\n"
    )
    outputs = []
    for seed in ("0", "12345"):
        done = subprocess.run([sys.executable, "-c", script, *map(str, PACKAGES)],
                              capture_output=True, text=True, check=True,
                              env={**os.environ, "PYTHONHASHSEED": seed})
        outputs.append(done.stdout)
    assert outputs[0] == outputs[1]


# ------------------------------------------------------------------ bounds

def test_the_row_bound_admits_a_package_at_it_and_refuses_one_row_past():
    rows = [(i, _gpb([24.0 + i * 1e-5, 57.0]), "EXERCISE", None)
            for i in range(1, GEOPACKAGE_MAX_ROWS + 1)]
    assert len(GeopackageAdapter().to_cdm(_package(rows))) == GEOPACKAGE_MAX_ROWS
    rows.append((GEOPACKAGE_MAX_ROWS + 1, _gpb([24.0, 57.0]), "EXERCISE", None))
    with pytest.raises(RowCountExceeded, match="before any row was fetched"):
        GeopackageAdapter().to_cdm(_package(rows))


def test_the_blob_bound_admits_a_value_at_it_and_refuses_one_octet_past():
    at = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", b"\x01" * GEOPACKAGE_MAX_BLOB_BYTES)])
    objects = GeopackageAdapter().to_cdm(at)
    assert len(objects[0].residual.data["row"]["attributes"]["payload"]["hex"]) == \
        2 * GEOPACKAGE_MAX_BLOB_BYTES
    past = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", b"\x01" * (GEOPACKAGE_MAX_BLOB_BYTES + 1))])
    with pytest.raises(BlobSizeExceeded, match="before any row was fetched"):
        GeopackageAdapter().to_cdm(past)


def test_the_coordinate_bound_admits_a_package_at_it_and_refuses_one_coordinate_past():
    per_row = GEOPACKAGE_MAX_COORDINATES // GEOPACKAGE_MAX_ROWS
    line = [[24.0 + i * 1e-4, 57.0] for i in range(per_row)]
    rows = [(i, _gpb(line, kind="LineString"), None, None)
            for i in range(1, GEOPACKAGE_MAX_ROWS + 1)]
    objects = GeopackageAdapter().to_cdm(_package(rows, geometry_type="LINESTRING"))
    assert sum(len(o.geometry.coordinates) for o in objects) == GEOPACKAGE_MAX_COORDINATES
    rows[-1] = (GEOPACKAGE_MAX_ROWS, _gpb(line + [[24.9, 57.0]], kind="LineString"), None, None)
    with pytest.raises(GeopackageError, match="coordinate budget is exhausted"):
        GeopackageAdapter().to_cdm(_package(rows, geometry_type="LINESTRING"))


def test_the_output_bound_is_applied_from_the_package_block_before_any_row_is_fetched():
    rows = [(i, _gpb([24.1, 57.0]), "EXERCISE", None) for i in range(1, 101)]
    accepted = _package(rows, description="x" * (GEOPACKAGE_MAX_OUTPUT_BYTES // 100 - 4096))
    assert len(GeopackageAdapter().to_cdm(accepted)) == 100
    refused = _package(rows, description="x" * (GEOPACKAGE_MAX_OUTPUT_BYTES // 100 + 1))
    with pytest.raises(OutputSizeExceeded, match="refused before any row was fetched"):
        GeopackageAdapter().to_cdm(refused)


def test_the_depth_bound_admits_a_twin_at_it_and_refuses_one_level_past():
    def nested(depth: int) -> dict:
        node: dict = {}
        for _ in range(depth - 1):
            node = {"n": node}
        return node
    twin = _twin(MIXED)
    twin["sqlite"]["deep"] = nested(GEOPACKAGE_MAX_DEPTH - 2)
    assert len(GeopackageAdapter().to_cdm(twin)) == 2
    twin["sqlite"]["deep"] = nested(GEOPACKAGE_MAX_DEPTH - 1)
    with pytest.raises(InputTooDeep):
        GeopackageAdapter().to_cdm(twin)


def test_a_wkb_count_the_octets_cannot_hold_is_refused_before_allocation():
    blob = bytearray(_gpb([[24.0, 57.0], [24.1, 57.0]], kind="LineString"))
    blob[13:17] = (2 ** 31).to_bytes(4, "little")
    with pytest.raises(GeopackageError, match="declares 2147483648 points needing at least"):
        codec.geopackage_binary(bytes(blob), budget=[10 ** 9], where="row")


def test_the_declared_limits_are_the_enforced_constants():
    limits = GeopackageAdapter.metadata.capabilities.limits
    assert limits.max_input_bytes == GEOPACKAGE_MAX_INPUT_BYTES == 64 * 1024 * 1024
    assert limits.max_depth == GEOPACKAGE_MAX_DEPTH == harness.LOADER_MAX_DEPTH
    assert limits.max_objects == GEOPACKAGE_MAX_ROWS
    assert set(limits.declared_because) == {"max_input_bytes", "max_depth", "max_objects"}
    for basis in limits.declared_because.values():
        assert basis.kind.value == "implementation_cap"
        path, _, function = basis.test.partition("::")
        assert f"def {function}(" in (TESTS.parent / path).read_text(), basis.test
    assert set(limits.absent_because) == {"max_decompressed_bytes", "max_parse_seconds"}
    assert max(harness.json_nesting_depth(p.read_text()) for p in TWINS) * 8 <= GEOPACKAGE_MAX_DEPTH


# ------------------------------------------------------------------ boundaries of the module

def test_the_adapter_resolves_no_reference_and_touches_no_file_or_network():
    """Read from both modules' ASTs: nothing that opens a file, a socket or a URL, and no
    caller-supplied SQL — the only `execute` calls take this module's own statements. The
    connection is in memory and `sqlite3.connect` is called with ':memory:' and nothing else."""
    for source in (module, codec):
        tree = ast.parse(pathlib.Path(source.__file__).read_text())
        imported = {n.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import)
                    for n in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom)}
        assert not imported & {"urllib", "socket", "http", "requests", "pathlib", "os", "io",
                               "subprocess"}, imported
        calls = {node.func.id for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        assert "open" not in calls and "eval" not in calls and "exec" not in calls
    tree = ast.parse(pathlib.Path(module.__file__).read_text())
    connects = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr == "connect"]
    assert len(connects) == 1
    assert [a.value for a in connects[0].args] == [":memory:"]
    loaders = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
               and isinstance(node.func, ast.Attribute)
               and node.func.attr == "enable_load_extension"]
    assert len(loaders) == 1 and loaders[0].args[0].value is False
    handlers = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "set_progress_handler"]
    assert len(handlers) == 1


def test_a_statement_past_the_step_budget_is_aborted_by_the_progress_handler(monkeypatch):
    monkeypatch.setattr(module, "_PROGRESS_EVERY", 1)
    monkeypatch.setattr(module, "GEOPACKAGE_MAX_SQL_STEPS", 1)
    with pytest.raises(GeopackageError, match="exceeded 1 SQLite VM steps .* aborted"):
        GeopackageAdapter().to_cdm(DEMO.read_bytes())


def test_egress_is_refused_by_the_framework_and_the_manifest_advertises_none():
    objects = GeopackageAdapter().to_cdm(MIXED.read_bytes())
    with pytest.raises(NotImplementedError, match="ingest-only and does not emit"):
        GeopackageAdapter().from_cdm(objects)
    with pytest.raises(NotImplementedError):
        GeopackageAdapter().encode(objects)
    assert GeopackageAdapter.direction == "ingest"
    assert not hasattr(GeopackageAdapter, "ROUNDTRIP_TOLERANCE") or \
        "ROUNDTRIP_TOLERANCE" not in GeopackageAdapter.__dict__
    from synapse_cdm import manifests
    generated = manifests.generate()["geopackage"]
    assert generated["adapter"]["direction"] == "ingest"
    assert generated["adapter"]["capabilities"]["directions_exercised"] == ["ingest"]
    assert "egress" not in json.dumps(generated["adapter"]["capabilities"]["directions_exercised"])


def test_the_cross_format_path_is_the_unmodified_geojson_exchange_profile_joined_on_object_id():
    """The GeoJSON adapter is not this phase's to change: its exchange profile emits what CDM
    types and nothing of this adapter's residual, so the row's attributes live at the CDM stage
    and meet their feature on `sc:object_id` (the join `examples/geopackage_to_geojson` uses)."""
    objects = GeopackageAdapter(dataset="exercise-baltic").to_cdm(DEMO.read_bytes())
    document = json.loads(GeojsonAdapter(export=EXPORT_EXCHANGE).from_cdm(objects))
    assert document["sc:profile"] == EXPORT_EXCHANGE and len(document["features"]) == 9
    feature = document["features"][3]
    obj = {str(o.object_id): o for o in objects}[feature["properties"]["sc:object_id"]]
    assert obj.residual.namespace == "GeoPackage"
    assert obj.residual.data["row"]["attributes"]["name"] == "EXERCISE HARBOUR OFFICE"
    assert feature["properties"]["sc:source_ids"] == [{"system": "GeoPackage:exercise-baltic",
                                                       "external_id": "facilities/1"}]
    assert "sc:residual" not in feature["properties"], \
        "the exchange profile carries no foreign residual — the GeoJSON adapter is unchanged"
    assert "EXERCISE HARBOUR OFFICE" not in json.dumps(feature), \
        "no GeoPackage attribute reaches the document, promoted or otherwise"
    assert set(feature["properties"]) <= {k for k in feature["properties"] if k.startswith("sc:")}, \
        "no GeoPackage attribute is promoted to a top-level GeoJSON property"


def test_detect_is_the_cheap_structural_test():
    adapter = GeopackageAdapter()
    assert adapter.detect(DEMO.read_bytes()) is True
    assert adapter.detect(DEMO.read_bytes()[:100]) is True, "the header alone decides"
    assert adapter.detect((MALFORMED / "user_version_1_3_0.gpkg").read_bytes()) is False
    assert adapter.detect((MALFORMED / "plain_sqlite_not_a_geopackage.gpkg").read_bytes()) is False
    assert adapter.detect(b"{}") is False
    assert adapter.detect(_twin(DEMO)) is True
    assert adapter.detect({"type": "FeatureCollection", "features": []}) is False
    assert adapter.detect(42) is None


def test_validate_source_names_a_two_d_row_under_a_mandatory_z_column_and_a_stale_extent():
    octets = _package([(1, _gpb([24.1, 57.0]), "EXERCISE", None)], z=1,
                      extra_sql=("UPDATE gpkg_contents SET min_x = 0, min_y = 0, max_x = 1, "
                                 "max_y = 1",))
    problems = GeopackageAdapter().validate_source(octets)
    assert any("z = 1 (Z mandatory) and this geometry is 2-D" in p for p in problems)
    assert any("gpkg_contents extent [0.0, 0.0, 1.0, 1.0] disagrees" in p for p in problems)
    assert GeopackageAdapter().validate_source(DEMO.read_bytes()) == []
    assert GeopackageAdapter().validate_source(b"nope")[0].startswith("GeopackageError:")


def test_the_manifest_is_generator_output_and_declares_ingest_l3_and_the_structured_residual():
    from synapse_cdm import manifests
    generated = manifests.generate()["geopackage"]
    assert generated["adapter"]["id"] == "geopackage"
    assert generated["adapter"]["residual"] == "structured"
    # `evidence.available` moved false -> true in the 3.1.0 release commit (2026-09-21): the first
    # release carrying this adapter attaches its records; `tests/test_cdm_evidence.py` holds the value.
    assert generated["adapter"]["evidence"]["available"] is True
    assert generated["adapter"]["maturity"]["level"] == "L3"
    assert generated["adapter"]["capabilities"]["limits"]["max_objects"] == GEOPACKAGE_MAX_ROWS
    ids_ = {e["id"] for e in generated["adapter"]["limitations"] if isinstance(e, dict)}
    assert ids_ == {"version-1-4-0-only", "wgs84-only", "measured-geometry",
                    "geometry-collection-and-extended-types", "non-vector-content",
                    "wal-dependent", "no-source-time", "z-meaning-as-declared"}


def test_the_module_docstring_claims_the_ordinal_and_the_structured_residual():
    assert module.__doc__.lstrip().startswith(
        "OGC GeoPackage 1.4.0 (OGC 12-128r19) vector features -> CDM. Adapter #17")
    assert "residual: structured" in module.__doc__


def test_the_crs_reader_accepts_the_three_wgs84_identifiers_and_nothing_else_by_id():
    for text, kind in ((WGS84, "geographic-2d"),
                       ('GEOGCS["WGS 84 (CRS84)",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,'
                        '298.257223563]],AUTHORITY["OGC","CRS84"]]', "geographic-2d"),
                       ('GEODCRS["WGS 84",DATUM["World Geodetic System 1984",ELLIPSOID["WGS 84",'
                        '6378137,298.257223563,LENGTHUNIT["metre",1]]],CS[ellipsoidal,3],'
                        'AXIS["lat",north],AXIS["lon",east],AXIS["h",up],ID["EPSG",4979]]',
                        "geographic-3d")):
        reading = codec.crs_profile(text)
        assert reading["accepted"] and reading["kind"] == kind, text
    for text in ("undefined", "",
                 'GEOGCS["ETRS89",DATUM["European_Terrestrial_Reference_System_1989",SPHEROID['
                 '"GRS 1980",6378137,298.257222101]],AUTHORITY["EPSG","4258"]]',
                 'GEOGCS["WGS 72",DATUM["WGS_1972",SPHEROID["WGS 72",6378135,298.26]]]',
                 'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563]],'
                 'AUTHORITY["EPSG","4326"],AXIS["lat",north],AXIS["lon",east],AXIS["h",up]]',
                 MERCATOR):
        assert codec.crs_profile(text)["accepted"] is False, text
    with pytest.raises(GeopackageError):
        codec.crs_profile("GEOGCS[")
    assert math.isclose(codec.WGS84_INVERSE_FLATTENING, 298.257223563)
