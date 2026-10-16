# EPA AirNow hourly observation fixtures

**Every one is synthetic.** No line of any AirNow file — not a site, not a value — is in this
repository, and no real site is named. Every file here is written by `spec/build_fixtures.py` from
literals in that script; edit the script and run it, never a `.dat` or a twin. `python -I -B
spec/build_fixtures.py --check` rebuilds the set in memory and prints `CURRENT` when the tree
matches it.

These are the fixtures of `airnow_hourly` (#28 in the ordinal table, `adapters/airnow_hourly.py`):
one of AirNow's two hourly observation files per payload, `HourlyData_yyyymmddhh.dat` or
`HourlyAQObs_yyyymmddhh.dat`. Both layouts are read from AirNow's fact sheets, pinned by SHA-256
with the AirNow Data Exchange Guidelines in `spec/airnow_hourly_pin.json` and not carried. The
HourlyAQObs header here is spelled as the files write it: the fact sheet's field list spells one
name `Ozone_Measured` where the files write `OZONE_Measured`, and the adapter refuses the fact
sheet's spelling (`malformed/fact_sheet_measured_spelling.dat`).

## Why each fixture ships twice

`<name>.dat` is the file as AirNow writes it, CRLF line ends included: a HourlyData file is
header-less, nine `|`-delimited fields a line; a HourlyAQObs file is a quoted CSV under its
34-name header. `<name>.parsed.json` is its twin: `form`, then every line's fields as written
(`records` for HourlyData, `header` and `rows` for HourlyAQObs), which is what the harness's
lossless ledger reads. The builder writes both from the same field lists, never by reading one
back.

## The identifiers and places

The sites are **`000000001`**, **`000000002`**, **`000000003`** and **`000000000011`**, the synthetic
nine- and twelve-digit blocks of `CONTRIBUTING.md` ("Identifiers and places in observation
fixtures"), named `EX site one` and so on, reported by `EX synthetic agency`. The adapter's fixture
context places three of them — `000000001` at 56.95 N, 24.1 E, `000000002` at 57.4 N, 21.6 E and
`000000000011` at 56.5 N, 21.0 E — and leaves `000000003` out, so a HourlyData line names a site
with no position. Every stated position lies inside the Baltic rectangle (56.0–58.5 N, 20.0–24.5
E). The hours are on 2026-04-28.

## The set

| Fixture | What it exercises |
|---|---|
| `hourly_data_two_sites` | HourlyData: two sites the table places, four parameters, a negative raw concentration (-1.4 µg/m³) |
| `hourly_data_site_without_position` | HourlyData: a twelve-digit AQSID, a parameter (`RWS`) the fact sheet's table does not list, and a site the table does not place |
| `hourly_aqobs_two_sites` | HourlyAQObs with the four-digit date the files write: positions stated in the file, blank fields for what a site does not measure, a negative raw SO2 |
| `hourly_aqobs_fact_sheet_date_blank_unit` | HourlyAQObs with the fact sheet's two-digit date: no position stated (the table places the site), status `Inactive`, and a concentration whose unit field is blank |
