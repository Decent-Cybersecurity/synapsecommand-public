# NOAA CO-OPS data API fixtures

**Every one is synthetic.** No response for any CO-OPS station — not a sample, not a value — is
in this repository, and no real station is named. Every file here is written by
`spec/build_fixtures.py` from literals in that script; edit the script and run it, never a `.csv`,
a `.json` or a twin. `python -I -B spec/build_fixtures.py --check` rebuilds the set in memory and
prints `CURRENT` when the tree matches it.

These are the fixtures of `coops_csv` (#27 in the ordinal table, `adapters/coops_csv.py`): one
response of the CO-OPS data API (`datagetter`) per payload, in its CSV form or its JSON form. The
API's pages are cited by URL in `spec/coops_csv_pin.json` and not carried.

## One request for the whole set

A response states neither the datum, the units, the time zone nor (in the CSV form) the station
it was requested with (research-station-text F05), so the adapter takes the request as a required
`CoopsRequest`. Every fixture here is a response to the adapter's fixture context: station
**`0000001`** (the synthetic seven-digit block of `CONTRIBUTING.md`), product `water_level`, datum
MLLW, units metric, time zone gmt, interval 6. The `lst` reading, `lst_ldt`'s refusal, the other
two products and a request with no zone are bound in `tests/test_cdm_coops_csv_adapter.py`, where
each test builds its own request.

## Why the CSV fixtures ship twice

`<name>.csv` is the response as the API writes it: one header line, then one row a sample.
`<name>.parsed.json` is its twin: `form` "csv", the header line as written and every row's
fields, which is what the harness's lossless ledger reads. The JSON-form fixture is a `.json`
document, so the harness hands it over parsed and it needs no twin. The builder writes each from
its literals, never by reading one back.

## The identifiers and places

The station is `0000001`. The JSON form states the station's position as strings, `57.0213` N,
`21.0877` E, inside the Baltic rectangle (56.0–58.5 N, 20.0–24.5 E); the CSV form states none. The
days are 2026-04-27 and 2026-04-28.

## The set

| Fixture | What it exercises |
|---|---|
| `water_level_preliminary` | preliminary samples six minutes apart; one O flag of 3, a count of samples outside three sigma |
| `water_level_verified` | verified samples, whose flags are I, F, R and T; one inferred |
| `water_level_below_datum_flagged` | water below MLLW (negative values), the flat, rate and limit flags set, preliminary then verified |
| `water_level_json_form` | the JSON form: the station and its position in `metadata`, every value a string, `f` the four flags in one string |
