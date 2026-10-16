# Malformed ndbc_stdmet payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/ndbc_stdmet/`, so a subdirectory is out of its reach by construction. They are read by
the conformance suite's check H, and by `tests/test_cdm_ndbc_stdmet_adapter.py`, which holds each
one to the exact refusal below:

```bash
synapse conformance run --adapter ndbc_stdmet --require H
```

Every one is built by `../spec/build_fixtures.py` from literal tokens, with the one thing named
below wrong with it, and is read in the fixture context (station `EX001`). Each is refused with
`NdbcStdmetRefused`, a `ValueError` whose text begins with the code in the second column and names
the line, row or column, never a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `row_width_mismatch.stdmet` | `width-mismatch` | the second row of a realtime file has 18 columns under a 19-column header |
| `undocumented_sentinel_width.stdmet` | `undocumented-sentinel` | a historical file's `PRES` is a run of 9s, a column with no documented sentinel width |
| `documented_column_other_width.stdmet` | `undocumented-sentinel` | a historical file's `WVHT` is `99.0`, not the documented `99.00` |
| `mm_in_historical_file.stdmet` | `mm-in-historical-file` | `MM` in a file whose header has no `PTDY` |
| `not_a_number.stdmet` | `not-a-number` | `WSPD` is written with a decimal comma |
| `unknown_column.stdmet` | `unknown-column` | the header names `SWH`, a column of no stdmet layout |
| `cut_inside_a_row.stdmet` | `unterminated-line` | the file ends twelve characters before its last line does |
| `repeated_instant.stdmet` | `repeated-instant` | two rows state one instant |
| `two_digit_year_under_yyyy.stdmet` | `bad-time` | a two-digit year under a `YYYY` header |
| `two_digit_year_under_hash_yy.stdmet` | `bad-time` | a two-digit year under the realtime `#YY` header, whose years are four digits |
| `two_digit_year_outside_the_record.stdmet` | `undocumented-year` | the two-digit year `05` under `YY`: only `98` is a two-digit year the layout is recorded with |
| `number_past_the_double_range.stdmet` | `number-out-of-range` | `WSPD` is a decimal of 400 digits, which no binary double holds |
| `signed_value_outside_ptdy.stdmet` | `not-a-number` | `WSPD` is written `+5.5`: only `PTDY` is printed with a sign |
