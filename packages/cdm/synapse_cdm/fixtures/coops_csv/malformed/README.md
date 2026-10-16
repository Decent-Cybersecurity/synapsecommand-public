# Malformed coops_csv payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/coops_csv/`, so a subdirectory is out of its reach by construction. They are read by the
conformance suite's check H, and by `tests/test_cdm_coops_csv_adapter.py`, which holds each one to
the exact refusal below:

```bash
synapse conformance run --adapter coops_csv --require H
```

Every one is built by `../spec/build_fixtures.py` from literals, with the one thing named below
wrong with it, and is read under the fixture context's request (station `0000001`, water_level,
MLLW, metric, gmt). Each is refused with `CoopsRefused`, a `ValueError` whose text begins with the
code in the second column and names the line, row or field, never a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `unknown_header.csv` | `unknown-header` | a header no product of this adapter writes |
| `air_pressure_header.csv` | `header-of-another-product` | the air-pressure header, trailing space and all, under a water-level request |
| `row_width_mismatch.csv` | `width-mismatch` | the second row has seven fields under an eight-field header |
| `not_a_number.csv` | `not-a-number` | the water level is written with a letter in it |
| `stamp_with_seconds.csv` | `bad-time` | the stamp carries seconds, `YYYY-MM-DD HH:MM:SS` |
| `blank_value.csv` | `blank-value` | the water level is blank |
| `quality_not_p_or_v.csv` | `bad-quality` | the quality level is neither p nor v |
| `cut_inside_a_row.csv` | `unterminated-line` | the response ends nine characters before its last line does |
| `json_station_disagrees.json` | `station-disagrees` | the JSON form's `metadata.id` is `0000002`, not the request's station |
| `json_unknown_key.json` | `not-a-response` | the JSON form holds a key besides `metadata` and `data` |
| `number_past_the_double_range.csv` | `number-out-of-range` | the water level is a decimal of 400 digits, which no binary double holds |
| `flag_past_the_double_range.csv` | `flag-out-of-range` | the O flag is an integer of 400 digits, which no binary double holds |
