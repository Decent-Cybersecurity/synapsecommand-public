# GeoJSON fixtures — adapter #16, RFC 7946

These are the harness fixtures for `adapters/geojson.py`, the first adapter in this repository to
declare `residual: structured`. Every one is a JSON document, so the harness hands the adapter
the parsed form and runs the path-bound preservation ledger on every leaf of it — there is no
`.parsed.json` twin here because there is nothing for one to be the twin of.

**Every one is synthetic.** Hand-written on 2026-09-20 for the case each exercises. Every name is
prefixed `EXERCISE`, no coordinate describes a real feature, and no file derives from any recorded
dataset. `spec/geojson_pin.json` records each file's SHA-256 and byte count and an INDEPENDENT
reading of each harness fixture taken with GDAL 3.13.3 (`ogr2ogr … -lco GEOMETRY=AS_WKT`), so the
adapter's own parse is never the only oracle for what a fixture contains;
`tests/test_cdm_geojson_adapter.py` holds the tree to the record and the adapter to the reading.

## The fixtures, and what each one is for

| Fixture | Form | Exercises |
|---|---|---|
| `six_geometries_baltic.json` | FeatureCollection, 6 features | every geometry type the CDM models once, in RFC 7946 §3.1's order; numeric and string ids side by side; a `null` property; a zero-valued property (`length_km: 0`); a foreign member on the collection (`name`), on a feature (`vendor_flag`) and a `bbox` on a geometry; a collection `bbox` |
| `feature_zero_meridian_clockwise_ring.json` | bare Feature | a Polygon on the zero meridian and the equator whose exterior ring is CLOCKWISE and whose hole is counterclockwise — the interoperability case RFC 7946 §3.1.6 tells a parser to accept; `0` and `0.0` property values; a nested property holding a list with a `null` inside it and an empty string; a foreign member on the geometry; a feature `bbox` |
| `antimeridian_bbox_repeated_values.json` | FeatureCollection, 2 features | a collection `bbox` whose west edge (179.5) is east of its east edge (−179.5) — §5.2's antimeridian form, which `geo.BoundingBox` refuses and the residual keeps; three-element positions; the same scalar (`reading: 7`, `unit: "kt"`) on both features, so a value landing on the WRONG feature's object cannot pass as preserved; a foreign object on the collection |
| `null_and_empty_properties_typed_ids.json` | FeatureCollection, 2 features | `properties: null` beside `properties: {}`; the numeric id `7` beside the string id `"7"` at the same position (two identities; GDAL reads them as one FID and says so in the pin record); an empty foreign object on the collection |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter geojson --update-golden` and read before being kept.

## What the goldens show, and where to look

- **Nothing in `properties` is promoted.** `label` is `null` and `style` is `{}` on every
  object; the properties are under `residual.data.feature.properties` (or
  `residual.data.document.properties` for the bare Feature), typed as sent.
- **`residual.data.document`** is the top-level object minus what became canonical — for a
  collection its `type`, `bbox` and foreign members; for a bare Feature the Feature itself minus
  its geometry's `type` and `coordinates`. **`residual.data.feature`** is the record inside a
  collection.
- **`source.transformations`** carries the notes: every ring that breaks the right-hand rule
  (kept, not reversed), every `bbox` (kept, not projected; the antimeridian one named as such),
  the identity policy when a feature had no `id`, and the as-of basis when the caller gave one.
- **`source.original_id`** is the feature id as JSON text — `7` for the number, `"7"` for the
  string — and `source_ids[0].external_id` is the id as plain text; `object_id` differs between
  the two. **`source.record_index`** is the feature's position in the collection.

## Subdirectories

- `malformed/` — twelve refusal payloads for the conformance suite's check H, each built by
  cutting, corrupting or wrapping the payloads above (its own README says what each is refused
  for).
- `egress/` — three CDM records a planning stub wrote, never this adapter, and under `golden/`
  what `from_cdm` emits for each under both export profiles (`generic` and
  `synapsecommand-exchange/1`). The egress direction is proved on records this adapter did not
  produce, so the proof is not the adapter reading its own output.
- `spec/` — `geojson_pin.json`, the provenance record (above). Nothing under `spec/` is fed to
  the adapter: the harness selects immediate children of this directory only.

## Reproducing

```bash
python -m synapse_cdm.harness --adapter geojson --schemas schemas
python -m synapse_cdm.suite conformance run --adapter geojson --format json
python -m pytest tests/test_cdm_geojson_adapter.py -q
```
