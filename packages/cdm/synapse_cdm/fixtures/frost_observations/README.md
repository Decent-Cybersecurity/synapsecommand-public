# frost_observations fixtures

**Every one is synthetic.** No station, value or link of a real Frost response is here. The
stations are in the **`SN0000x` block** CONTRIBUTING.md reserves for Frost station fixtures
(`SN00001` to `SN00099`, the leading zeros making the id visibly synthetic), and every value was
made up. All files are written by `spec/build_fixtures.py` from literals in that script; `--check`
prints `CURRENT` when the files match it and writes nothing. Do not edit a fixture by hand.

Each fixture is one `GET /observations/v0.jsonld` response in the shape Frost documents at
<https://frost.met.no/concepts2.html>, written twice: `<name>.jsonld`, the response's octets
(compact UTF-8 JSON), and `<name>.parsed.json`, the same document parsed, which is what the
harness's `lossless` column reads. The adapter takes either form, and
`tests/test_cdm_frost_observations_adapter.py` holds the two translations and the two goldens of
every pair equal.

## Fixture context

The harness builds the adapter with `FrostObservationsAdapter.fixture_instance()`. That call passes
`FIXTURE_STATIONS`, a synthetic station table with these positions, all inside CONTRIBUTING.md's
Baltic rectangle (a Frost response states no position; the table is the caller's):

- `SN00001` at 57.2 N, 21.3 E
- `SN00002` at 56.8 N, 23.9 E
- `SN00003` at 58.1 N, 22.4 E

`SN00009` is left out of the table on purpose. `fixture_instance()` also passes `FIXTURE_ELEMENTS`,
a synthetic element table with three units: `wind_speed` m/s, `wind_from_direction` degrees and
`air_temperature` degC. `synthetic_element_x` is left out on purpose.

## The set

| Fixture | What it exercises |
|---|---|
| `two_stations_hourly` | Two stations in the table, two hours each, all seven requested elements. Includes `sum(precipitation_amount PT1H)` and observations with no `level` (pressure, precipitation). The midnight item is all PT1H, so Frost's Case 1 applies. |
| `quality_codes_no_level_unknown_keys` | Non-zero `qualityCode`s (2, 5, 7, 1). Hourly `surface_snow_thickness` with no `level`. One observation states no flags, and one item states none at all, so the contract gives `quality_flags_basis`. Unknown keys at three depths: top level, item and observation. |
| `station_missing_parallel_sensors` | `SN00009`, which is not in the table, so its position is null. Parallel sensors `SN00001:0` and `SN00001:1` map to one Entity. One element appears in two series (timeOffset PT0H and PT6H) and at two levels. `SN00002` has no sensor suffix. A P1D value at a referenceTime that is not midnight (12:30), so referenceTime is the observation time. |
| `midnight_mixed_daily` | A midnight item that mixes PT1H, PT10M, PT1M and PT3H observations with two P1D values. The P1D value with timeOffset PT0H becomes a daily Event covering the calendar date. The P1D value with timeOffset PT6H becomes a daily Event covering the 24 h ending at 06:00. A P1M value is set aside on the station Entity. A second station has only a daily value at midnight. |
| `observation_without_unit` | wind_speed and wind_from_direction with no `unit`, at a 47 m level and PT10M resolution. Their units come from the element table. `synthetic_element_x` has no unit and no table row, so it becomes a `unit_unknown` Absence. |

`malformed/` holds payloads the adapter must refuse (the conformance suite's check H and the test
module read it): ten structural cases as `.json` (a timeResolution that is not a duration, a blank
unit, a bad sourceId, a referenceTime with no zone, a repeated item, the wrong `@type`, empty
`data`, a value given as text, a level value with no unit, a boolean qualityCode) and two octet
cases as `.jsonld` (a duplicate JSON key and a truncated document). `golden/` was written with
`--update-golden` and read before it was kept.

`spec/frost_observations_pin.json` cites the Frost documentation the time rules are read from (by
URL, never carried, the sentences quoted short) and `spec/frost_observations_terms.json` records
MET Norway's licence statements behind the adapter's `PUBLIC_GOVERNMENT` class.
