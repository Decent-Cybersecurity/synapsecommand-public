# Malformed GeoJSON payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects immediate children of
the fixture directory that are files (`harness.select_fixtures`), so a subdirectory is out of its
reach by construction. They are read by the Synapse Conformance Suite's check H (§21):

```bash
python -m synapse_cdm.suite conformance run --adapter geojson --require H
```

Each one must be REFUSED — any exception except `SystemExit`, `KeyboardInterrupt`, `MemoryError`
or `RecursionError`, inside the time bound, returning no object — and the exception class and the
refusing LAYER are recorded. `tests/test_cdm_geojson_adapter.py::test_every_malformed_payload_is_refused_by_name`
states the words each refusal must carry.

| Payload | What is wrong with it | Refused by |
|---|---|---|
| `malformed_json.json` | §21's malformed JSON: a collection cut off inside its `features` array | the fixture LOADER, which is what parses JSON; the adapter refuses the same bytes when handed them directly |
| `a_json_array.json` | a well-formed Feature wrapped in a JSON array | adapter — "a JSON array, not an object" |
| `bare_geometry.json` | a `Point` at the top level, which RFC 7946 §3 permits and this adapter declares unsupported (limitation `bare-geometry`) | adapter |
| `empty_coordinates.json` | a `LineString` whose `coordinates` is `[]` — the RFC lets a processor read it as null; this adapter does not (limitation `empty-coordinates`) | adapter |
| `feature_without_properties.json` | a Feature with no `properties` member (§3.2 requires one; its value may be null) | adapter |
| `geometry_collection_feature.json` | a Feature carrying a `GeometryCollection` (limitation `geometry-collection`) | adapter |
| `id_less_feature_default_policy.json` | a feature with no `id` under the default identity policy, `refuse` | adapter — nothing is guessed |
| `legacy_crs_member.json` | a `crs` member naming EPSG:3857 with projected coordinates — the 2008 specification's profile (limitation `legacy-crs`); the coordinates are never relabelled WGS84 | adapter |
| `non_finite_number.json` | `NaN` in a position. Python's decoder accepts the token; the adapter's own decoder refuses it, and a parsed twin carrying a `nan` float is refused by the finiteness walk | adapter |
| `null_geometry_without_as_of.json` | a `null` geometry with no caller as-of context: the Entity it would become needs a `valid_from` the source does not state, and no time is fabricated | adapter |
| `swapped_lat_lon_point.json` | `[24.1052, 95.0]` — a latitude past 90, the signature of `[lat, lon]` order | `geo.py`'s validator, through the adapter (a `ValidationError`, which is a `ValueError`) |
| `unclosed_ring.json` | a Polygon whose ring does not end where it began — refused, never closed for it | `geo.py`'s validator, through the adapter |

None is derived from recorded traffic. All twelve are built from this directory's own synthetic
payloads by cutting, corrupting or wrapping them, so they carry no third party's data.
