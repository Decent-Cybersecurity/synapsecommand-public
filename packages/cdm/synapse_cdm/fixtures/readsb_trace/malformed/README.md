# Malformed readsb_trace payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/readsb_trace/`, so a subdirectory is out of its reach by construction. They are read by
the conformance suite's check H, and by `tests/test_cdm_readsb_trace_adapter.py`, which holds each
one to the exact refusal below:

```bash
synapse conformance run --adapter readsb_trace --require H
```

Every one is built by `../spec/build_fixtures.py` from the airborne fixture's document or from
literal octets, with the one thing named below wrong with it. Each is refused with
`ReadsbTraceRefused`, a `ValueError` whose text begins with the code in the second column and never
quotes a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `fewer_than_nine_elements.trace` | `fewer-than-nine-elements` | point 1 has eight elements |
| `offsets_not_monotonic.trace` | `offsets-not-monotonic` | point 2's element 0 is earlier than point 1's |
| `negative_offset.trace` | `negative-offset` | point 0's element 0 is negative |
| `latitude_out_of_range.trace` | `coordinate-out-of-range` | point 1's latitude is 91 |
| `longitude_out_of_range.trace` | `coordinate-out-of-range` | point 3's longitude is 180.5 |
| `ground_outside_element_three.trace` | `ground-outside-element-3` | point 2's element 4 is the string `ground` |
| `timestamp_not_a_number.trace` | `bad-timestamp` | `timestamp` is text |
| `deflate_data_corrupt.trace` | `does-not-inflate` | the first deflate octet names block type 3, which RFC 1951 reserves |
| `crc_mismatch.trace` | `does-not-inflate` | the member's CRC-32 has one bit flipped |
| `truncated_gzip.trace` | `truncated-gzip` | the member is cut at 200 octets |
| `trailing_octets_after_the_member.trace` | `trailing-octets` | one octet follows the member |
| `inflates_past_the_bound.trace` | `inflates-past-the-bound` | it inflates to 64 MiB and one octet (`max_decompressed_bytes` is 64 MiB) |
| `truncated_json.trace` | `not-json` | the JSON inside the member is cut at 300 octets |
| `not_gzip.trace` | `not-gzip` | the document as plain JSON octets, with no gzip member around it |
| `empty_trace.trace` | `empty-trace` | `trace` is `[]` |
| `unknown_top_level_key.trace` | `unknown-key` | a `squawk` key at the top level, which readsb never writes there |
| `uppercase_address.trace` | `bad-address` | the address is upper case; readsb writes lower case |
| `flags_outside_four_bits.trace` | `bad-flags` | point 1's flags are 16 |
| `unknown_position_source.trace` | `unknown-source` | point 3's element 9 is a source README-json.md does not list |
| `duplicate_key.trace` | `duplicate-key` | the top-level object states `icao` twice |
| `nan_literal.trace` | `non-finite-number` | `timestamp` is the literal `NaN` |
| `timestamp_past_a_double.trace` | `bad-timestamp` | `timestamp` is a 401-digit integer, which JSON allows and no double holds |
| `lone_surrogate_in_version.trace` | `not-unicode` | `version` holds the escape `\ud800`, a lone surrogate that no UTF-8 text can carry |

Nothing here derives from recorded data, and no standard's text is carried.
