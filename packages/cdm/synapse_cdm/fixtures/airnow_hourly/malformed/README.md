# Malformed airnow_hourly payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/airnow_hourly/`, so a subdirectory is out of its reach by construction. They are read by
the conformance suite's check H, and by `tests/test_cdm_airnow_hourly_adapter.py`, which holds each
one to the exact refusal below:

```bash
synapse conformance run --adapter airnow_hourly --require H
```

Every one is built by `../spec/build_fixtures.py` from literals, with the one thing named below
wrong with it. Each is refused with `AirnowRefused`, a `ValueError` whose text begins with the code
in the second column and names the record or row, never a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `two_digit_year_out_of_range.dat` | `bad-date` | the two-digit date names month 13 |
| `four_digit_year_in_hourly_data.dat` | `bad-date` | a HourlyData date with a four-digit year |
| `not_on_the_hour.dat` | `not-an-hour` | the valid time is 10:30 |
| `width_mismatch.dat` | `width-mismatch` | a HourlyData line of eight fields |
| `not_a_number.dat` | `not-a-number` | the value is written with a letter in it |
| `bad_aqsid.dat` | `bad-aqsid` | an AQSID of eight characters |
| `repeated_record.dat` | `repeated-record` | two lines state one site, parameter and hour |
| `cut_inside_a_line.dat` | `unterminated-line` | the file ends twelve characters before its last line does |
| `unknown_header.dat` | `unknown-header` | a HourlyAQObs header spelling `OZONE_AQI` otherwise |
| `fact_sheet_measured_spelling.dat` | `unknown-header` | a HourlyAQObs header spelling `OZONE_Measured` as the fact sheet's field list does, `Ozone_Measured` |
| `number_past_the_double_range.dat` | `number-out-of-range` | the value is a decimal of 400 digits, which no binary double holds |
