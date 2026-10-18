# Malformed iem_n0q payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/iem_n0q/`, so a subdirectory is out of its reach by construction. They are read by the
conformance suite's check H, and by `tests/test_cdm_iem_n0q_adapter.py`, which holds each one to
the exact refusal below:

```bash
synapse conformance run --adapter iem_n0q --require H
```

Every one is built by `../spec/build_fixtures.py` with its own PNG and DEFLATE writers, from the
description of the packaged `all_missing_no_gentime` image (12200 x 5400 cells of index 0, the
builder's palette ramp) with the one thing named below changed. Each is refused with
`IemN0qRefused`, a `ValueError` whose text begins with the code in the second column and names
the structure, never a value from the payload. The three IHDR refusals happen before a single
octet of image data is inflated.

| Payload | Code | What is wrong with it |
|---|---|---|
| `wrong_image_size.png` | `not-the-n0q-grid` | IHDR states 1220 x 540, a tenth of the product's 12200 x 5400 a side |
| `truecolour_colour_type_2.png` | `not-the-n0q-grid` | IHDR states colour type 2 (truecolour, three samples a cell) at the product's size, with no palette |
| `four_bit_indices.png` | `not-the-n0q-grid` | IHDR states colour type 3 at bit depth 4, two cells an octet, with a 16-entry palette |
| `idat_crc_failure.png` | `png-crc` | the IDAT chunk's CRC has its last octet inverted |
| `truncated_idat_stream.png` | `png-truncated` | the IDAT chunk holds the first half of the zlib stream, correctly framed: the stream never ends |
| `inflates_past_its_rows.png` | `png-data-past-its-rows` | the zlib stream inflates to 258 octets more than the 65,885,400 the rows hold; refused at the first octet past them |
| `index_past_the_palette.png` | `index-past-the-palette` | a 16-entry palette and one cell of index 200 |
| `gentime_twice.png` | `gentime-twice` | two `tEXt` chunks named `gentime` |

The slot the caller hands in is a constructor argument, not a payload, so a slot off IEM's
five-minute grid cannot be a file here: `IemN0qAdapter(slot=...)` refuses it with
`slot-off-the-five-minute-grid`, bound by
`test_a_slot_off_the_five_minute_grid_is_refused_when_the_adapter_is_built`.
