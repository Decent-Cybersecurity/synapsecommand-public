# Demonstration 3 — GeoPackage → CDM → GeoJSON exchange profile

One command, self-checking, synthetic throughout:

```bash
python examples/geopackage_to_geojson/run.py
```

It ingests the packaged fixture
`packages/cdm/synapse_cdm/fixtures/geopackage/exercise_facilities_routes_areas.gpkg` — three
vector layers (`facilities` points with Z, `routes` lines, `areas` polygons, one with a hole)
whose primary keys are **1, 2 and 3 in every layer**, with NULL attributes, a BLOB attribute and
a zero-valued position — through `adapters/geopackage.py` (adapter #17, ingest only) under the
dataset namespace `exercise-baltic`, then exports the nine `PlanObject`s through
`adapters/geojson.py` under the `synapsecommand-exchange/1` profile, and compares the result
against expectations established independently of both adapters. The script prints one line per
check and exits 0 only when every check agrees.

## What is compared, and against what

| Claim | Independent expectation |
|---|---|
| geometry (type, every coordinate, Z) | GDAL 3.13.3's `ogr2ogr -f GeoJSON` export of the same layer (`fixtures/geopackage/independent/*.geojson`) |
| attributes, NULLs kept, BLOB as hex (at the CDM stage, joined to the feature on `sc:object_id`) | GDAL's export `properties` |
| the row's id | GDAL's `ogrinfo -json -features` fid |
| identity | `ids.derive("GeoPackage:exercise-baltic", '["<layer>", <pk>]', kind="feature")`, recomputed by the script; nine distinct ids from three distinct primary keys |
| provenance | `sc:source_system` GeoPackage, `sc:source_adapter` geopackage, `sc:synthetic` true, `sc:source_ids` = `<layer>/<pk>` under the dataset namespace; every CDM object's residual carries the package inventory naming the three layers as included |
| no promotion, no carrier | every top-level property of every exported feature is inside the `sc:` namespace and none is `sc:residual` — no GeoPackage attribute is presented as generic GeoJSON meaning and the GeoJSON adapter carries nothing it does not type |
| the whole document | `expected/exercise_facilities_routes_areas.exchange.geojson`, byte for byte (`--update` rewrites it after a reviewed change) |

## Where the attributes are — and where they are not

The GeoJSON adapter is used exactly as Phase 1 shipped it. Its exchange profile carries what
CDM types — geometry, `sc:object_kind`, `sc:object_id`, `sc:source_ids`, `sc:source_system`,
`sc:source_adapter`, `sc:synthetic`, as-of — and **not** another adapter's structured residual,
so the document holds no GeoPackage attribute anywhere: not promoted to a top-level property
(which would claim generic GeoJSON carries that meaning) and not tucked under a reserved key
either. The row's attributes live at the CDM stage, in each object's `residual.data.row`
(`attributes` with their SQLite storage classes beside them in `attribute_types`, the geometry
header under `geometry`, the package's own metadata and inventory under `residual.data.package`).
The script joins the two stages on `sc:object_id` — the identity both carry — and compares the
residual's attributes with GDAL's export `properties` there, while geometry, identity and
provenance are compared in the exported document itself.

## What this is not

Cross-format translation, not a round trip: the GeoPackage adapter is ingest only, nothing here
writes a `.gpkg`, and byte identity with the source container is neither claimed nor possible.
The comparison is against GDAL's reading of a synthetic package this repository generated with
GDAL (`fixtures/geopackage/spec/build_fixtures.py`); it is `independent_expected` evidence and
not a live partner integration.
