# GeoPackage fixtures — adapter #17, OGC 12-128r19 (GeoPackage 1.4.0)

These are the harness fixtures for `adapters/geopackage.py`, ingest only, the second adapter in
this repository to declare `residual: structured`. Every `.gpkg` is the octets of a SQLite
container and ships beside its `.parsed.json` twin — `parse_payload`'s reading of the same
octets — because the harness's lossless column harvests leaves from a JSON document and a byte
string has none; `tests/test_cdm_geopackage_adapter.py::test_every_twin_is_the_parse_of_its_octets_and_translates_identically`
is what makes the twin evidence rather than a second opinion.

**Every one was written by GDAL, not by hand, and every one is synthetic.**
`spec/build_fixtures.py` writes the small GeoJSON and CSV sources under `sources/` from its
own literals and drives `ogr2ogr` (and `gdal_translate` for the one raster table) over them; GDAL
3.13.3 wrote every SQLite page, core table, R-tree, GeoPackageBinary header and WKB in this
directory, and the adapter had no hand in any of them. The same script captures GDAL's own reading
of every layer (`ogrinfo -json -features`, `ogr2ogr -f GeoJSON`) under `independent/`, so
the adapter's parse is never the only oracle for what a fixture contains, and
`spec/geopackage_pin.json` records the GDAL build, the exact commands, and the SHA-256 and byte
count of every file here. Every name is prefixed `EXERCISE`, every coordinate is a plausible
Baltic or equatorial position chosen for the case it exercises, and no file derives from any
recorded dataset. `python spec/build_fixtures.py --check` rebuilds the set into a temporary
directory under the same fixed `OGR_CURRENT_DATE` and compares hashes.

## The fixtures, and what each one is for

| Fixture | Layers | Exercises |
|---|---|---|
| `exercise_facilities_routes_areas.gpkg` | `facilities` (POINT, XYZ, EPSG:4326 forced), `routes` (LINESTRING), `areas` (POLYGON) | **the demonstration package** (`examples/geopackage_to_geojson`): the primary keys 1, 2, 3 in EVERY layer, so identity must be namespace + layer + key; NULL attributes beside typed ones; a BLOB attribute (`payload`, NULL on one row); a zero-valued position `[0, 0, 0]` and zero-valued attributes; a negative Z; a polygon with a hole; Z under an SRS that declares no vertical axis, so every facilities object says its Z meaning is UNDECLARED |
| `six_families_geometry_column.gpkg` | `families` (GEOMETRY) | one row of each of the six families the profile carries, in one `GEOMETRY` column, including a MultiLineString of two parts and a MultiPolygon whose first part has a hole; envelope indicator 1 on every non-point row, held equal to the decoded bounds |
| `elevations_epsg4979_and_crs84.gpkg` | `elevations` (POINT, XYZ, EPSG:4979 — GDAL's own choice for a Z layer), `crs84_points` (POINT, OGC:CRS84 as srs_id 100000 / organization NONE) | the CRS judged by DEFINITION: 4979's `definition` column is `undefined` and its WKT sits in the `gpkg_crs_wkt` extension column `definition_12_063`; CRS84's id and organization say nothing and its WKT says WGS 84; the Z of the elevations layer carries the meaning the SRS declares (ellipsoidal height, metres) |
| `mixed_content_partial_read.gpkg` | `positions` (POINT) beside `notes` (attributes-only), `measured` (GEOMETRY, m = 2) and `tiles_sample` (raster tiles, EPSG:3857) | the inventory: one layer included, three unsupported (an attributes table, a measured layer, a raster table), every one named in every object's `residual.data.package.inventory` and in a `source.transformations` line; the R-tree, metadata and `gpkg_ogr_contents` tables tolerated and never read |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter geopackage --update-golden` and read before being kept.

`malformed/` holds fifteen refusal packages for the conformance suite's check H: six are GDAL's
own output for a case the adapter refuses (`wal_mode_header`, `user_version_1_3_0`,
`projected_crs_epsg3857`, `undefined_srs_layer`, `empty_and_null_geometry_no_as_of`,
`geometry_collection_row`) and nine are one GDAL package with a single mutation each, named for
the rule broken (`gpb_*`, `wkb_*`, `plain_sqlite_not_a_geopackage`, `truncated_container`,
`not_sqlite_at_all`). `test_every_malformed_payload_is_refused_by_name` states what each is
refused for. `wal_mode_header.gpkg` and `empty_and_null_geometry_no_as_of.gpkg` are refused only
under the default constructor: with `wal_checkpointed=True` and with an `AsOf` context
respectively they translate, and the adapter tests read them that way too.

## What the goldens show, and where to look

- **Nothing in the attributes is promoted.** `label` is `null` and `style` is `{}` on every
  object; the attributes are under `residual.data.row.attributes`, typed as stored, with each
  value's SQLite storage class beside them in `row.attribute_types`.
- **`residual.data.package`** is the whole reading of the container minus its rows: the SQLite
  header, `spatial_ref_sys`, `contents` (with `last_change`), `geometry_columns`, `extensions`,
  the layer descriptors (`layers[]`, each with its CRS reading) and the `inventory`.
  **`residual.data.row`** is the row minus the geometry's `type` and `coordinates`: `layer`,
  `pk`, the geometry header (`flags`, `srs_id`, `envelope`, `dimension`, `byte_order`), the
  attributes and their types.
- **`source.transformations`** carries the notes: the inventory counts, the CRS acceptance and
  what it rested on, `last_change` named as package metadata and not a time, the identity
  derivation, the Z meaning where a layer has Z, the WAL assertion where one was made, and the
  as-of basis when the caller gave one.
- **`source_ids[0].external_id`** is `<layer>/<pk>` and `source.original_id` the key as text;
  `object_id` differs between `areas/1`, `facilities/1` and `routes/1`.
