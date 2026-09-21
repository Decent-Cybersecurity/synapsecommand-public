# GeoJSON egress fixtures — fresh export of records this adapter never produced

Three CDM records written as if by a planning stub (`source.adapter: planner_stub`, ids under
the fictitious `f1c70000-0016-` version-8 UUID prefix), so the `from_cdm` direction is proved on
input this adapter did not make — the round trip through the harness is self-consistency, and
this is the other half. Under `golden/` is what `from_cdm` emits for each, under both export
profiles, in ARCHITECTURE.md §6.2's canonical serialisation:

| Record | Kind | `generic` emits | `synapsecommand-exchange/1` adds |
|---|---|---|---|
| `fresh_control_measure_polygon.json` | `PlanObject` (CONTROL_MEASURE, labelled, with `validity.observed_at`) | a Feature with `id` = the CDM `object_id`, the Polygon, `properties: {}` — generic GeoJSON is not claimed to carry the label or the type | `sc:object_kind`, `sc:object_id`, `sc:object_type`, `sc:label`, `sc:as_of`, `sc:schema_version`, `sc:source_*`, `sc:synthetic`, `sc:source_ids`, and `sc:profile` on the collection |
| `fresh_entity_with_position.json` | `Entity` with a position and `alt_m` | a `Point` `[lon, lat, alt_m]` (RFC 7946 §3.1.1's third element is height above the WGS 84 ellipsoid, which is what `alt_m` is) | `sc:entity_id`, `sc:entity_type`, `sc:affiliation`, `sc:valid_from`, the provenance keys |
| `fresh_entity_without_position.json` | `Entity` with `position: null` | `geometry: null` — an absent position stays absent, never `[0, 0]` | as above |

`tests/test_cdm_geojson_adapter.py::test_every_egress_fixture_matches_its_golden_under_both_profiles`
compares byte for byte. An `Event` or a `Track` is refused by `from_cdm`: neither has a geometry
this adapter may choose for it.
