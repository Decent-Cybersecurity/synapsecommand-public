# Malformed nexrad2 payloads — every one synthetic, every one refused

These are **not fixtures**. Checks A–F never see them: the harness selects the immediate files of
`fixtures/nexrad2/`, so a subdirectory is out of its reach by construction. They are read by the
conformance suite's check H, and by `tests/test_cdm_nexrad2_adapter.py`, which holds each one to
the exact refusal below:

```bash
synapse conformance run --adapter nexrad2 --require H
```

Every one is built by `../spec/build_fixtures.py` from the `all_moments_one_elevation` volume or
from literal octets, with the one thing named below wrong with it. Each is refused with
`Nexrad2Refused`, a `ValueError` whose text begins with the code in the second column and names
the field and its position, never a value from the payload.

| Payload | Code | What is wrong with it |
|---|---|---|
| `truncated_record.ar2v` | `record-past-the-end` | the volume is cut 40 octets before its end, inside its radial record |
| `short_volume_header.ar2v` | `short-volume-header` | 20 octets, fewer than the 24-octet volume header |
| `bzip2_crc_corrupt.ar2v` | `bzip2-corrupt` | one bit of the radial record's bzip2 block CRC is flipped |
| `bzip2_stream_cut_short.ar2v` | `truncated-bzip2` | the radial record's stream is cut by 20 octets and its control word rewritten to match |
| `negative_control_word_past_the_file.ar2v` | `record-past-the-end` | the first control word is -1,000,000,000: its absolute value runs past the file |
| `message_1_legacy_radial.ar2v` | `message-1` | the radial is typed message 1, the legacy radial |
| `message_29_model_data_record.ar2v` | `message-29` | a model data record (message 29, the `_MDM` content) follows the radials |
| `compression_indicator_bzip2.ar2v` | `radial-bzip2-compressed` | the radial's Compression Indicator is 1 |
| `compression_indicator_zlib.ar2v` | `radial-zlib-compressed` | the radial's Compression Indicator is 2 |
| `radial_length_out_of_range.ar2v` | `radial-length-out-of-range` | the design record's tiny form: one REF moment of four gates, a Radial Length of 196 |
| `decompresses_past_the_bound.ar2v` | `decompresses-past-the-bound` | 193 records of 862 RDA status segments each: 325,888 + 193 x 2,096,384 = 404,928,000 octets, past `max_decompressed_bytes` (402,979,072) |
| `metadata_record_past_its_size.ar2v` | `metadata-record-size` | the metadata record decompresses to 135 segments, past its fixed 325,888 octets |
| `azimuth_number_zero.ar2v` | `azimuth-number-out-of-range` | the radial's Azimuth Number is 0 |
| `unexpected_message_type.ar2v` | `unexpected-message-type` | a type 3 message follows the radial in a radial record |
| `archive_version_05.ar2v` | `unsupported-archive-version` | the tape name is `AR2V0005.` |
| `not_an_archive_ii_volume.ar2v` | `not-archive-ii` | the octets begin with a bzip2 stream's magic, not a tape name |
