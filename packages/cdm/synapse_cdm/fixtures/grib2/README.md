# GRIB2 fixtures

**Every one is synthetic.** No message from the NOAA archives (HRRR, RAP, MRMS) or any other
producer — not a message, not a byte range, not a value — is in this repository. Every file here is
written by `spec/build_fixtures.py` from literals in that script: seven by GDAL 3.13.3's GRIB
driver from an ASCII grid the script writes, six by the script's own encoder. Edit the script and
run it, never a `.grb2` or a twin. `python -I -B spec/build_fixtures.py --check` rebuilds the set
and prints `CURRENT` when the tree matches it; without GDAL on PATH it holds the seven
tool-written messages to their recorded SHA-256 and says so, and `--require-gdal` refuses to pass
unless GDAL re-wrote them.

These are the fixtures of `grib2` (#29 in the ordinal table, `adapters/grib2.py`): one GRIB
edition 2 message per payload. The layouts are read against NCEP's WMO GRIB2 documentation and
WMO-No. 306, both cited by reference in `spec/grib2_pin.json` and not carried here.

## Why each fixture ships twice

`<name>.grb2` is the message as a file holds it. `<name>.parsed.json` is its twin: the octets as
`wire_hex`; Sections 0, 1 and 2 under `indicator`, `identification` and `local_use`; each field's
Sections 3 to 7 under `fields`, every template octet under its own name (a signed field whose
octets are all ones, the documentation's "missing", is `null`); each field's summary of its decoded
values under `summaries` (`null` for a JPEG 2000 field, which is not decoded); each field's bitmap
and packed values as hexadecimal under `arrays`; and a JPEG 2000 field's codestream under
`codestreams`. The script writes the twin from the literals the message was written from, never by
decoding it: for a GDAL message, from the options it gave GDAL and the packing GDAL chose, read once
from GDAL's octets and written into the script. `tests/test_cdm_grib2_adapter.py` holds the
adapter's decode of each `.grb2` to its twin, the twin's own translation to the octets', and every
value of every field to the grid literal it was written from.

## The places and the times

Every grid lies inside the Baltic rectangle (56.0–58.5 N, 20.0–24.5 E, `CONTRIBUTING.md`,
"Identifiers and places in observation fixtures"). Every reference time is 2026-04-29T06:00:00Z.
The centre codes are table codes chosen to exercise the adapter: 7 for most, and 161 with
discipline 209 for the MRMS-style message, because the one local parameter row the adapter states a
unit and sentinels for is keyed by them.

## The set

| Fixture | Writer | What it exercises |
|---|---|---|
| `simple_packing_latlon` | GDAL | Template 5.0 on a 3 x 2 lat/lon grid (3.0); a u-component of wind at 10 m, a one-hour forecast; GDAL's empty Section 2 |
| `png_16_bit` | GDAL | Template 5.41, a 16-bit greyscale PNG, the same field |
| `png_8_bit` | GDAL | Template 5.41 at 8 bits; a visibility analysis at the surface (no unit, so no level value) |
| `jpeg2000_reference_form` | GDAL | Template 5.40: Sections 0 to 6 read, the codestream checked and declared unsupported, no summary |
| `complex_order_1` | GDAL | Template 5.3, spatial differencing of order 1, two groups on an 8 x 8 grid; GDAL writes management 1 with nothing missing |
| `complex_order_2_missing` | GDAL | Template 5.3 of order 2 with ten nodata cells, Table 5.5 management 1 |
| `lambert_conformal_simple` | GDAL | Grid template 3.30, a 3 x 2 Lambert conformal grid of 3 km cells on a sphere of 6,371,229 m (shape 1); the footprint converted point by point |
| `bitmap_simple_packing` | script | a Section 6 bitmap (indicator 0) leaving three of twelve points out, Section 5 counting nine |
| `two_fields_one_message` | script | Sections 4 to 7 repeated: the u and v components at 100 hPa under one grid, no Section 2 |
| `zero_width_accumulation` | script | a zero-width field (0 bits per value, a Section 7 of five octets): accumulated precipitation over the hour after the reference, Template 4.8 |
| `complex_order_2_with_bitmap` | script | the HRRR form: Template 5.3 of order 2 with management 0 under a bitmap, so the output is sized from Section 3 and not Section 5 |
| `complex_order_1_primary_and_secondary_missing` | script | Table 5.5 management 2: a group wholly primary-missing, one wholly secondary-missing, two mixing both with values |
| `mrms_style_png_sentinels` | script | discipline 209 under centre 161, master tables 255, an observation-time reference (Table 1.2 code 3) and processed radar observations (Table 1.4 code 7): a modelled estimate; -1 "Missing" and -3 "No Coverage" written as data and counted as missing; one PNG row per filter type |

`malformed/` holds the messages the adapter must refuse; its README names each one's refusal.
