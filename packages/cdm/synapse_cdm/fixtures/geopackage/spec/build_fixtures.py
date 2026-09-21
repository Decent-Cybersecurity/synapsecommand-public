#!/usr/bin/env python3
"""Build the GeoPackage fixture set with GDAL. THE SOURCE OF TRUTH FOR EVERY ARTEFACT HERE.

    python build_fixtures.py            # from the directory this file is in; needs ogr2ogr,
                                        # ogrinfo, gdal_create, gdal_translate and sqlite3 on PATH
    python build_fixtures.py --check    # rebuild into a temporary directory and compare every
                                        # output's SHA-256 with the tree's; exit 1 on a difference

Edit this file, never a `.gpkg`, a `.parsed.json` twin, an `independent/` reading or the pin.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Every `.gpkg` under `fixtures/geopackage/` and `fixtures/geopackage/malformed/` is written by
GDAL's `ogr2ogr` (and `gdal_translate` for the one raster table) from the small synthetic GeoJSON
and CSV sources this script writes to `../sources/` from its own literals. GDAL is the INDEPENDENT
IMPLEMENTATION: it wrote the SQLite pages, the core tables, the R-tree, the GeoPackageBinary
headers and the WKB, and `adapters/geopackage.py` had no hand in any of them. GDAL is also the
independent READER: `../independent/` holds `ogrinfo -json -features` and `ogr2ogr -f GeoJSON` over
every harness fixture, and `tests/test_cdm_geopackage_adapter.py` compares the adapter's
geometries, attributes, ids, nulls and CRS against those files rather than against the adapter's
own twin.

Determinism: GDAL stamps `gpkg_contents.last_change` and `gpkg_metadata_reference.timestamp`
with the clock unless `OGR_CURRENT_DATE` is set; this script sets it to one fixed instant, so
two runs of one GDAL build produce byte-identical packages and `--check` can compare hashes. A
DIFFERENT GDAL build may lay pages out differently; the pin records the build every hash was
taken with, and a re-run under another build is a new pin, not a defect.

The fifteen `malformed/` packages are the refusal set the conformance suite's check H reads. Six
are GDAL's own output for a case the adapter refuses (WAL header, version 1.3.0, a projected CRS,
an undefined SRS, empty and NULL geometries with no as-of context, a GeometryCollection row); the
rest are one GDAL package with ONE octet string changed by a single SQL `UPDATE` or one slice of
its bytes — each mutation is a function below, named for the rule it breaks. They are NOT
claimed as independent evidence of anything; they are the adapter's own adversarial inputs.

EVERYTHING IS SYNTHETIC. Every name is prefixed EXERCISE, every coordinate is a plausible Baltic
or equatorial position chosen for the case it exercises, no file derives from any recorded
dataset, and the raster table is a 2x2 constant image.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED = FIXTURES / "malformed"
SOURCES = FIXTURES / "sources"
INDEPENDENT = FIXTURES / "independent"
PIN = HERE / "geopackage_pin.json"
FIXED_INSTANT = "2026-09-20T00:00:00.000Z"
ENV = {**os.environ, "OGR_CURRENT_DATE": FIXED_INSTANT, "GDAL_PAM_ENABLED": "NO"}

# ------------------------------------------------------------------------------ the sources


def _feature(fid, geometry, **properties):
    return {"type": "Feature", "id": fid, "geometry": geometry, "properties": properties}


def _collection(*features):
    return {"type": "FeatureCollection", "features": list(features)}


#: The demonstration package: three layers whose primary keys OVERLAP (1, 2, 3 in each), so a
#: consumer keying on the primary key alone would merge nine rows into three.
FACILITIES = _collection(
    _feature(1, {"type": "Point", "coordinates": [24.1052, 56.9496, 12.5]},
             name="EXERCISE HARBOUR OFFICE", category="port", capacity=120, ratio=0.5,
             note=None),
    _feature(2, {"type": "Point", "coordinates": [0.0, 0.0, 0.0]},
             name="EXERCISE ORIGIN BUOY", category="buoy", capacity=0, ratio=0.0, note="zero"),
    _feature(3, {"type": "Point", "coordinates": [24.4, 57.1, -3.25]},
             name="EXERCISE DEPOT", category="depot", capacity=None, ratio=None, note=None),
)
ROUTES = _collection(
    _feature(1, {"type": "LineString", "coordinates": [[24.1, 57.0], [24.3, 57.1], [24.5, 57.1]]},
             name="EXERCISE COASTAL ROUTE", length_km=31.5, active=1),
    _feature(2, {"type": "LineString", "coordinates": [[24.0, 56.9], [24.0, 57.2]]},
             name="EXERCISE MERIDIAN LEG", length_km=0.0, active=0),
    _feature(3, {"type": "LineString", "coordinates": [[23.9, 57.0], [24.6, 57.0]]},
             name="EXERCISE PARALLEL LEG", length_km=42.0, active=None),
)
AREAS = _collection(
    _feature(1, {"type": "Polygon", "coordinates": [
        [[24.0, 57.0], [24.6, 57.0], [24.6, 57.3], [24.0, 57.3], [24.0, 57.0]],
        [[24.2, 57.1], [24.2, 57.2], [24.4, 57.2], [24.4, 57.1], [24.2, 57.1]]]},
             name="EXERCISE TRAINING AREA", kind="exclusion", priority=1),
    _feature(2, {"type": "Polygon", "coordinates": [
        [[23.8, 56.8], [23.9, 56.8], [23.9, 56.9], [23.8, 56.9], [23.8, 56.8]]]},
             name="EXERCISE ANCHORAGE", kind="anchorage", priority=2),
    _feature(3, {"type": "Polygon", "coordinates": [
        [[24.7, 57.0], [24.9, 57.0], [24.9, 57.1], [24.7, 57.1], [24.7, 57.0]]]},
             name="EXERCISE RANGE", kind="range", priority=None),
)
#: One layer holding every family the profile carries, in a GEOMETRY column.
FAMILIES = _collection(
    _feature(10, {"type": "Point", "coordinates": [0.0, 0.0]}, name="EXERCISE POINT"),
    _feature(11, {"type": "MultiPoint", "coordinates": [[24.1, 57.1], [24.2, 57.2]]},
             name="EXERCISE MULTIPOINT"),
    _feature(12, {"type": "LineString", "coordinates": [[24.0, 57.0], [24.5, 57.5]]},
             name="EXERCISE LINESTRING"),
    _feature(13, {"type": "MultiLineString", "coordinates": [
        [[24.0, 57.0], [24.1, 57.0]], [[24.2, 57.0], [24.3, 57.0], [24.4, 57.1]]]},
             name="EXERCISE MULTILINESTRING"),
    _feature(14, {"type": "Polygon", "coordinates": [
        [[24.0, 57.0], [24.5, 57.0], [24.5, 57.5], [24.0, 57.5], [24.0, 57.0]]]},
             name="EXERCISE POLYGON"),
    _feature(15, {"type": "MultiPolygon", "coordinates": [
        [[[24.0, 57.0], [24.2, 57.0], [24.2, 57.2], [24.0, 57.2], [24.0, 57.0]],
         [[24.05, 57.05], [24.05, 57.15], [24.15, 57.15], [24.15, 57.05], [24.05, 57.05]]],
        [[[25.0, 57.0], [25.2, 57.0], [25.2, 57.2], [25.0, 57.2], [25.0, 57.0]]]]},
             name="EXERCISE MULTIPOLYGON"),
)
#: 3-D points with NO `-a_srs`: GDAL chooses EPSG:4979 for a Z layer from GeoJSON and writes its
#: WKT into the `gpkg_crs_wkt` extension column, leaving `definition` as 'undefined'.
ELEVATIONS = _collection(
    _feature(1, {"type": "Point", "coordinates": [24.1, 57.0, 100.0]}, name="EXERCISE MAST"),
    _feature(2, {"type": "Point", "coordinates": [24.2, 57.0, 0.0]}, name="EXERCISE SHORE"),
)
POSITIONS = _collection(
    _feature(1, {"type": "Point", "coordinates": [24.1, 57.0]}, name="EXERCISE P1"),
    _feature(2, {"type": "Point", "coordinates": [24.2, 57.1]}, name="EXERCISE P2"),
)
COLLECTION_ROW = _collection(
    _feature(1, {"type": "Point", "coordinates": [24.1, 57.0]}, name="EXERCISE POINT"),
    _feature(2, {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [24.2, 57.0]},
        {"type": "LineString", "coordinates": [[24.2, 57.0], [24.3, 57.0]]}]},
             name="EXERCISE COLLECTION"),
)
NOTES_CSV = "id,name,note\n1,EXERCISE N1,alpha\n2,EXERCISE N2,\n"
MEASURED_CSV = 'fid,WKT,name\n1,"POINT M (24.1 57.0 5)",EXERCISE MEASURED\n'
EMPTY_NULL_CSV = ('fid,WKT,name,count\n1,"POINT EMPTY",EXERCISE EMPTY,1\n'
                  '2,"POINT (24.1 57.0)",EXERCISE PRESENT,2\n3,,EXERCISE NULL,\n')
UNDEFINED_CSV = 'fid,WKT,name\n1,"POINT (24.1 57.0)",EXERCISE NO SRS\n'


def write_sources() -> None:
    SOURCES.mkdir(parents=True, exist_ok=True)
    for name, document in (("facilities", FACILITIES), ("routes", ROUTES), ("areas", AREAS),
                           ("families", FAMILIES), ("elevations", ELEVATIONS),
                           ("positions", POSITIONS), ("collection_row", COLLECTION_ROW)):
        (SOURCES / f"{name}.geojson").write_text(json.dumps(document, indent=1) + "\n")
    for name, text in (("notes", NOTES_CSV), ("measured", MEASURED_CSV),
                       ("empty_null", EMPTY_NULL_CSV), ("undefined_srs", UNDEFINED_CSV)):
        (SOURCES / f"{name}.csv").write_text(text)


# ------------------------------------------------------------------------------ GDAL calls

COMMANDS: list[str] = []


def run(*argv: str, cwd: pathlib.Path) -> str:
    COMMANDS.append(" ".join(argv))
    done = subprocess.run(argv, cwd=cwd, env=ENV, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise SystemExit(f"{argv[0]} failed ({done.returncode}):\n{done.stderr}")
    return done.stdout


def ogr2ogr(out: pathlib.Path, source: pathlib.Path, layer: str, *extra: str, update=False,
            version="1.4", fid="fid", geometry="geom", index=True) -> None:
    argv = ["ogr2ogr", "-f", "GPKG", str(out), str(source), "-nln", layer,
            "-lco", f"FID={fid}", "-lco", f"GEOMETRY_NAME={geometry}",
            "-lco", f"SPATIAL_INDEX={'YES' if index else 'NO'}", "-preserve_fid"]
    if update:
        argv.append("-update")
    else:
        argv += ["-dsco", f"VERSION={version}"]
    argv += list(extra)
    if source.suffix == ".csv":
        argv += ["-oo", "KEEP_GEOM_COLUMNS=NO", "-oo", "AUTODETECT_TYPE=YES"]
    run(*argv, cwd=out.parent)


def build_packages(fixtures: pathlib.Path, sources: pathlib.Path) -> None:
    malformed = fixtures / "malformed"
    malformed.mkdir(parents=True, exist_ok=True)
    # 1. the demonstration package: overlapping primary keys, a BLOB attribute (through the
    #    SQL passthrough below), NULLs, Z on the facilities layer under a FORCED
    #    EPSG:4326 so the package declares no vertical axis
    demo = fixtures / "exercise_facilities_routes_areas.gpkg"
    ogr2ogr(demo, sources / "facilities.geojson", "facilities", "-a_srs", "EPSG:4326")
    # the BLOB column, through GDAL's own SQL passthrough (its session carries the ST_*
    # functions the R-tree triggers call); the third row keeps a NULL BLOB
    run("ogrinfo", "-q", str(demo), "-sql", "ALTER TABLE facilities ADD COLUMN payload BLOB",
        cwd=fixtures)
    run("ogrinfo", "-q", str(demo), "-sql",
        "UPDATE facilities SET payload = X'DEADBEEF00' WHERE fid IN (1, 2)", cwd=fixtures)
    ogr2ogr(demo, sources / "routes.geojson", "routes", "-a_srs", "EPSG:4326", update=True)
    ogr2ogr(demo, sources / "areas.geojson", "areas", "-a_srs", "EPSG:4326", update=True)
    # 2. the six families in one GEOMETRY column
    ogr2ogr(fixtures / "six_families_geometry_column.gpkg", sources / "families.geojson",
            "families", "-a_srs", "EPSG:4326")
    # 3. GDAL's own CRS choices: EPSG:4979 for a Z layer (WKT in the crs_wkt extension column)
    #    and OGC:CRS84 written as srs_id 100000 / organization NONE
    crs = fixtures / "elevations_epsg4979_and_crs84.gpkg"
    ogr2ogr(crs, sources / "elevations.geojson", "elevations")
    ogr2ogr(crs, sources / "positions.geojson", "crs84_points", "-a_srs", "OGC:CRS84",
            update=True)
    # 4. mixed content: one feature layer beside an attributes-only table, a measured layer
    #    and a raster tile table
    mixed = fixtures / "mixed_content_partial_read.gpkg"
    ogr2ogr(mixed, sources / "positions.geojson", "positions", "-a_srs", "EPSG:4326")
    run("ogr2ogr", "-f", "GPKG", str(mixed), str(sources / "notes.csv"), "-nln", "notes",
        "-nlt", "NONE", "-update", cwd=fixtures)
    ogr2ogr(mixed, sources / "measured.csv", "measured", "-a_srs", "EPSG:4326", update=True)
    with tempfile.TemporaryDirectory() as scratch:
        tif = pathlib.Path(scratch) / "tiny.tif"
        run("gdal_create", "-of", "GTiff", "-outsize", "2", "2", "-bands", "1", "-burn", "7",
            "-a_srs", "EPSG:4326", "-a_ullr", "24", "58", "25", "57", str(tif), cwd=fixtures)
        run("gdal_translate", "-of", "GPKG", str(tif), str(mixed), "-co",
            "APPEND_SUBDATASET=YES", "-co", "RASTER_TABLE=tiles_sample", "-co",
            "TILING_SCHEME=GoogleMapsCompatible", cwd=fixtures)
    # --- malformed, GDAL's own output
    ogr2ogr(malformed / "user_version_1_3_0.gpkg", sources / "positions.geojson", "positions",
            "-a_srs", "EPSG:4326", version="1.3")
    ogr2ogr(malformed / "projected_crs_epsg3857.gpkg", sources / "positions.geojson",
            "positions", "-t_srs", "EPSG:3857")
    ogr2ogr(malformed / "undefined_srs_layer.gpkg", sources / "undefined_srs.csv", "positions")
    ogr2ogr(malformed / "empty_and_null_geometry_no_as_of.gpkg", sources / "empty_null.csv",
            "shapes", "-a_srs", "EPSG:4326")
    ogr2ogr(malformed / "geometry_collection_row.gpkg", sources / "collection_row.geojson",
            "shapes", "-a_srs", "EPSG:4326")
    wal = malformed / "wal_mode_header.gpkg"
    shutil.copyfile(fixtures / "mixed_content_partial_read.gpkg", wal)
    run("sqlite3", str(wal), "PRAGMA journal_mode=WAL;", cwd=malformed)
    for leftover in (wal.with_name(wal.name + "-wal"), wal.with_name(wal.name + "-shm")):
        if leftover.exists():
            leftover.unlink()
    # --- malformed, one mutation each on a GDAL package written WITHOUT a spatial index (the
    #     R-tree triggers call ST_IsEmpty, which the sqlite3 module lacks)
    base = malformed / ".mutation_base.gpkg"
    ogr2ogr(base, sources / "areas.geojson", "areas", "-a_srs", "EPSG:4326", index=False)
    for name, mutate in MUTATIONS.items():
        target = malformed / name
        shutil.copyfile(base, target)
        mutate(target)
    base.unlink()


def _blob(path: pathlib.Path, pk: int) -> bytes:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT geom FROM areas WHERE fid = ?", (pk,)).fetchone()[0]


def _replace(path: pathlib.Path, pk: int, blob: bytes) -> None:
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE areas SET geom = ? WHERE fid = ?", (blob, pk))


def _byte_order_octet_invalid(path):        # WKB byte-order octet 0x02: neither 0 nor 1
    blob = bytearray(_blob(path, 1))
    blob[8 + 32] = 0x02                       # header 8 + envelope (E = 1) 32 -> the WKB
    _replace(path, 1, bytes(blob))


def _extended_type_flag(path):              # X = 1: ExtendedGeoPackageBinary
    blob = bytearray(_blob(path, 1))
    blob[3] |= 0x20
    _replace(path, 1, bytes(blob))


def _srs_id_disagrees(path):                # header srs_id 4979 under a 4326 column
    blob = bytearray(_blob(path, 2))
    blob[4:8] = (4979).to_bytes(4, "little")
    _replace(path, 2, bytes(blob))


def _truncated_wkb(path):                   # the polygon cut in the middle of a ring
    blob = _blob(path, 3)
    _replace(path, 3, blob[:8 + 32 + 5 + 4 + 4 + 16 * 2])


def _envelope_disagrees(path):              # envelope min_x moved west of the ring
    blob = bytearray(_blob(path, 1))
    blob[8:16] = struct.pack("<d", struct.unpack("<d", blob[8:16])[0] - 1.0)
    _replace(path, 1, bytes(blob))


def _ewkb_flag(path):                       # PostGIS EWKB Z flag on the type word
    blob = bytearray(_blob(path, 2))
    at = 8 + 32 + 1
    blob[at:at + 4] = (3 | 0x80000000).to_bytes(4, "little")
    _replace(path, 2, bytes(blob))


def _plain_sqlite(path):                    # application_id and user_version zeroed
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA application_id = 0")
        conn.execute("PRAGMA user_version = 0")


def _truncated_container(path):             # the first two pages of the file
    path.write_bytes(path.read_bytes()[:8192])


def _not_sqlite(path):
    path.write_bytes(b"EXERCISE: this is not a SQLite database and not a GeoPackage\n" * 4)


MUTATIONS = {
    "gpb_byte_order_octet_invalid.gpkg": _byte_order_octet_invalid,
    "gpb_extended_type_flag.gpkg": _extended_type_flag,
    "gpb_srs_id_disagrees_with_layer.gpkg": _srs_id_disagrees,
    "wkb_truncated_polygon.gpkg": _truncated_wkb,
    "gpb_envelope_disagrees_with_wkb.gpkg": _envelope_disagrees,
    "wkb_ewkb_flag_bit.gpkg": _ewkb_flag,
    "plain_sqlite_not_a_geopackage.gpkg": _plain_sqlite,
    "truncated_container.gpkg": _truncated_container,
    "not_sqlite_at_all.gpkg": _not_sqlite,
}

# --------------------------------------------------------------------- the independent reading


def gdal_version() -> str:
    return run("ogr2ogr", "--version", cwd=HERE).strip()


def independent_readings(fixtures: pathlib.Path, out: pathlib.Path) -> dict[str, dict]:
    """`ogrinfo -json -features` and `ogr2ogr -f GeoJSON` per included layer of every harness
    fixture, written under `out/` and summarised for the pin."""
    out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict] = {}
    for package in sorted(fixtures.glob("*.gpkg")):
        listing = json.loads(run("ogrinfo", "-json", str(package), cwd=fixtures))
        layers = {}
        for layer in listing["layers"]:
            name = layer["name"]
            fields = layer.get("geometryFields") or []
            if not fields:
                layers[name] = {"geometry": None, "note": "no geometry field: not a vector "
                                                            "layer of the profile"}
                continue
            reading = json.loads(run("ogrinfo", "-json", "-features", str(package), name,
                                     cwd=fixtures))
            (out / f"{package.stem}.{name}.ogrinfo.json").write_text(
                json.dumps(reading, indent=1, sort_keys=True) + "\n")
            geojson = run("ogr2ogr", "-f", "GeoJSON", "/vsistdout/", str(package), "-sql",
                          f'SELECT {layer["fidColumnName"]} AS gpkg_fid, * FROM "{name}"',
                          "-lco", "ID_FIELD=gpkg_fid", cwd=fixtures)
            (out / f"{package.stem}.{name}.geojson").write_text(geojson)
            layers[name] = {
                "feature_count": reading["layers"][0]["featureCount"],
                "geometry_type": fields[0]["type"],
                "srs_wkt_first_line": (fields[0].get("coordinateSystem") or {}).get(
                    "wkt", "").split("\n")[0],
                "fids": [f["fid"] for f in reading["layers"][0]["features"]],
                "ogrinfo": f"{package.stem}.{name}.ogrinfo.json",
                "geojson": f"{package.stem}.{name}.geojson",
            }
        summary[package.name] = {"layers": layers}
    return summary


# ------------------------------------------------------------------------------- the twins


def twins(fixtures: pathlib.Path) -> None:
    sys.path.insert(0, str(FIXTURES.parents[2]))
    from synapse_cdm.adapters.geopackage import parse_payload
    for package in sorted(fixtures.glob("*.gpkg")):
        parsed = parse_payload(package.read_bytes())
        package.with_suffix(".parsed.json").write_text(
            json.dumps(parsed, indent=1, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------------- the pin


def _members(directory: pathlib.Path) -> list[pathlib.Path]:
    """The files of a directory minus its own README and provenance record — the harness's rule."""
    return sorted(p for p in directory.iterdir()
                  if p.is_file() and p.name not in ("README.md", "PROVENANCE.json"))


def digest(path: pathlib.Path) -> dict:
    from synapse_cdm.evidence import digest as content_digest
    sha256, size = content_digest(path)
    return {"file": path.name, "sha256": sha256, "bytes": size}


def write_pin(fixtures: pathlib.Path, summary: dict[str, dict], version: str) -> dict:
    record = {
        "what_this_is": (
            "The provenance record for every GeoPackage payload under fixtures/geopackage/: the "
            "standard the payloads follow, the INDEPENDENT IMPLEMENTATION that wrote every one "
            "of them (GDAL), the exact commands, the SHA-256 and byte count of every output, and "
            "GDAL's own reading of every harness fixture (spec/independent/) so the adapter's "
            "parse is never the only oracle for what a fixture contains. House style follows "
            "fixtures/geojson/spec/geojson_pin.json. No node here pairs a `local_path` with a "
            "`sha256`, deliberately: gates/pin_paths.py's corpus is the pinned STANDARDS, and "
            "this record pins fixtures, which are the repository's own files."),
        "adapter": {"name": "geopackage", "ordinal": 17, "direction": "ingest",
                    "fixture_directory": "geopackage", "mapping_profile": "geo-object/1"},
        "standard": {
            "document": "OGC GeoPackage Encoding Standard, version 1.4.0, OGC 12-128r19 "
                        "(approved 2024)",
            "document_identifier": "OGC 12-128r19",
            "url": "https://docs.ogc.org/is/12-128r19/12-128r19.html",
            "publisher": "Open Geospatial Consortium",
            "terms": "OGC document licence; freely retrievable and freely implementable, which "
                     "is the reading the adapter's OPEN licence class rests on",
            "carried_here": False,
            "why_not_carried": "The standard is a stable, freely retrievable HTML document at one "
                               "URL; the requirements the adapter cites (1, 2, 6, 10, 11, 13, "
                               "19, 22, 25-33, 146, Table 5, F.10) are named in "
                               "adapters/geopackage.py and adapters/geopackage_codec.py at the "
                               "line that applies each one.",
            "read_on": "2026-09-20",
        },
        "independent_implementation": {
            "tool": "GDAL (ogr2ogr, ogrinfo, gdal_create, gdal_translate) and the sqlite3 CLI",
            "version": version,
            "taken_on": "2026-09-20",
            "environment": {"OGR_CURRENT_DATE": FIXED_INSTANT, "GDAL_PAM_ENABLED": "NO"},
            "what_it_shows": (
                "Every .gpkg here was written by GDAL from the synthetic sources under "
                "fixtures/geopackage/sources/ (this script's own literals). fixtures/geopackage/independent/ holds GDAL's "
                "reading of every harness fixture: `ogrinfo -json -features` (fid, properties, "
                "geometry per feature, the layer's CRS as WKT) and `ogr2ogr -f GeoJSON` (with "
                "the fid carried as the feature id through `-lco ID_FIELD`). "
                "tests/test_cdm_geopackage_adapter.py::test_the_adapter_agrees_with_the_independent_gdal_reading "
                "compares the adapter's geometry, attributes, ids, nulls and CRS against them."),
            "commands": COMMANDS,
        },
        "fixtures_are_synthetic": (
            "Every source is a literal in spec/build_fixtures.py, written on 2026-09-20 by the "
            "adapter-expansion arc's phase 2. Every name is prefixed EXERCISE, every coordinate "
            "is a plausible Baltic or equatorial position chosen for the case it exercises and "
            "describes no real feature, the raster is a 2x2 constant image, and no file derives "
            "from any recorded dataset."),
        "regenerate": "python synapse_cdm/fixtures/geopackage/spec/build_fixtures.py, from the directory holding the package "
                      "(--check rebuilds into a temporary directory and compares hashes); the "
                      "hashes below are what the tree holds, re-derived by "
                      "tests/test_cdm_geopackage_adapter.py::test_every_fixture_matches_the_record_in_spec "
                      "on every run.",
        "fixtures": [{**digest(p), **summary[p.name]} for p in sorted(fixtures.glob("*.gpkg"))],
        "twins": [digest(p) for p in sorted(fixtures.glob("*.parsed.json"))],
        "malformed": {
            "what_these_are": (
                "The refusal set the conformance suite's check H reads. Six are GDAL's own "
                "output for a case the adapter refuses; the rest are one GDAL package "
                "(areas, no spatial index) with one mutation each, named for the rule broken. "
                "None is claimed as independent evidence."),
            "files": [digest(p) for p in sorted((fixtures / "malformed").glob("*.gpkg"))],
        },
        "sources": [digest(p) for p in _members(SOURCES)],
        "independent": [digest(p) for p in _members(INDEPENDENT)],
    }
    return record


# ------------------------------------------------------------------------------------ main


def build(fixtures: pathlib.Path) -> dict:
    version = gdal_version()
    write_sources()
    build_packages(fixtures, SOURCES)
    twins(fixtures)
    summary = independent_readings(fixtures, INDEPENDENT)
    return write_pin(fixtures, summary, version)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--check", action="store_true",
                        help="rebuild into a temporary directory and compare with the tree")
    args = parser.parse_args(argv)
    if not args.check:
        record = build(FIXTURES)
        PIN.write_text(json.dumps(record, indent=2) + "\n")
        print(f"wrote {len(record['fixtures'])} fixtures, {len(record['malformed']['files'])} "
              f"malformed, {len(record['twins'])} twins, {len(record['independent'])} "
              f"independent readings; pin {PIN.name}")
        return 0
    with tempfile.TemporaryDirectory() as scratch:
        rebuilt = pathlib.Path(scratch) / "geopackage"
        rebuilt.mkdir()
        version = gdal_version()
        build_packages(rebuilt, SOURCES)
        recorded = json.loads(PIN.read_text())
        wanted = {e["file"]: e["sha256"] for e in recorded["fixtures"]}
        wanted.update({"malformed/" + e["file"]: e["sha256"]
                       for e in recorded["malformed"]["files"]})
        differences = []
        for relative, sha in sorted(wanted.items()):
            path = rebuilt / relative
            actual = digest(path)["sha256"] if path.exists() else None
            if actual != sha:
                differences.append(f"{relative}: pin {sha[:12]}… rebuilt {str(actual)[:12]}…")
        pinned = recorded["independent_implementation"]["version"]
        print(f"GDAL now: {version}; pinned: {pinned}")
        for line in differences:
            print(line)
        print(f"{len(wanted)} packages compared, {len(differences)} differ")
        return 1 if differences else 0


if __name__ == "__main__":
    raise SystemExit(main())
