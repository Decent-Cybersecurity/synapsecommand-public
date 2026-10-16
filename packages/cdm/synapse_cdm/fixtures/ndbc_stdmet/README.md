# NDBC standard meteorological fixtures

**Every one is synthetic.** No file of any NDBC station — not a row, not a value — is in this
repository, and no real station is named. Every file here is written by `spec/build_fixtures.py`
from a literal token table in that script; edit the script and run it, never a `.stdmet` or a
twin. `python -I -B spec/build_fixtures.py --check` rebuilds the set in memory and prints
`CURRENT` when the tree matches it.

These are the fixtures of `ndbc_stdmet` (#26 in the ordinal table, `adapters/ndbc_stdmet.py`): one
NDBC standard meteorological ("stdmet") text file per payload. The format is read from the NDBC
Web Data Guide (Version 2.0, June 2023) and NDBC's measurement descriptions; the guide and the
quality-control handbook T80-10 are pinned by SHA-256 in `spec/ndbc_stdmet_pin.json` and not
carried, and the measurement descriptions are cited by URL.

## Why each fixture ships twice, and why the extension is `.stdmet`

`<name>.stdmet` is the file as NDBC writes it: whitespace-aligned columns under a header line and,
from 2007 on, a units line, LF line ends. NDBC names it `<station>.txt`, and `.gitignore` ignores
`*.txt` everywhere, so the payload is named for its data type instead (research-station-text
F13). `<name>.parsed.json` is its twin: the header, the units line (or null) and every row as the
tokens a whitespace split gives, which is what the harness's lossless ledger reads. The builder
writes both from the same token lists, never by reading one back, and
`tests/test_cdm_ndbc_stdmet_adapter.py` holds the adapter's parse of each `.stdmet` to its twin and
the two goldens of each pair to each other.

## The identifiers and places

A stdmet file names no station and no position. The adapter's fixture context names the station
**`EX001`**, the synthetic five-character block of `CONTRIBUTING.md` ("Identifiers and places in
observation fixtures"), and places it at 57.25 N, 21.5 E, inside the Baltic rectangle (56.0–58.5
N, 20.0–24.5 E). The days are 1998-06-15, 2004-09-01, 2025-11-03 and 2026-04-28.

## The set

| Fixture | What it exercises |
|---|---|
| `realtime_newest_first` | the realtime layout: 19 columns with `PTDY`, a units line, rows newest first, `MM` for every missing value (whole rows of waves and the tide), the pressure tendency with its printed sign (`+0.3`, `-0.5` and the signed zero `+0.0`), visibility in `nmi` |
| `historical_nine_runs` | the historical layout: 18 columns, no `PTDY`, rows oldest first, missing values as runs of 9s at the widths documented for their columns (`99.00`, `999`, `99.0`, `999.0`), visibility in `mi` |
| `before_2007_no_units_line` | the 2004 layout: 17 columns, `YYYY`, no minute column, `WD` and `BAR`, `TIDE`, and no units line, so each value is a reading whose unit the file does not state |
| `two_digit_year_1998` | the 1998 layout: 16 columns, a two-digit `YY` (`98`, the one two-digit year the adapter reads), no minute column, `WD` and `BAR`, no units line |
