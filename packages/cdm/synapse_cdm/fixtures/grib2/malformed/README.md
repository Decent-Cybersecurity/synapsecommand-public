# Malformed grib2 payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/grib2/`, so a subdirectory is out of its reach by construction. They are read by the
conformance suite's check H, and by `tests/test_cdm_grib2_adapter.py`, which holds each one to the
exact refusal below:

```bash
synapse conformance run --adapter grib2 --require H
```

Every one is built by `../spec/build_fixtures.py` from one of the script's own messages or from
literal octets, with the one thing named below wrong with it. Each is refused with `Grib2Refused`,
a `ValueError` whose text begins with the code in the second column and names the section and the
field, never a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `truncated_message.grb2` | `truncated-message` | the two-field message cut 30 octets before its end |
| `total_length_short_of_the_payload.grb2` | `octets-after-message` | Section 0's total length is 4 octets less than the message |
| `missing_end_section.grb2` | `no-end-section` | the last four octets are `7778`, not `7777` |
| `grib_edition_1.grb2` | `grib-edition-1` | Section 0 octet 8 says edition 1 |
| `unknown_packing_template.grb2` | `unsupported-packing-template` | the first field's data representation template is 5.4 (IEEE floating point) |
| `bitmap_count_disagrees.grb2` | `bitmap-count-disagrees` | one more bit set in the bitmap: ten points marked where Section 5 counts nine |
| `png_crc_failure.grb2` | `png-crc` | the MRMS-style message with the last octet of its IDAT chunk's CRC flipped |
| `png_rows_past_the_decompression_bound.grb2` | `png-past-the-decompression-bound` | an 8192 x 4096 grid of 16-bit samples: 33,554,432 points (MAX_GRID_POINTS exactly) whose rows inflate to 4096 x (1 + 16384) = 67,112,960 octets, past `max_decompressed_bytes` (67,108,864); refused before any octet is inflated |
| `png_data_past_its_rows.grb2` | `png-data-past-its-rows` | a 4 x 5 PNG whose image data inflates to one octet more than its 45 octets of rows |
| `grid_template_32769.grb2` | `unsupported-grid-template` | the grid template is 3.32769, the local rotated grid of the RAP wrfmsl product |
| `repeated_grid_section.grb2` | `repeated-grid-section` | Section 3 written again after the first field's Section 7 |
