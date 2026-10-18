# iem_n0q fixtures

**Every one is synthetic.** No file from the Iowa Environmental Mesonet's archive — not a file, not
a byte range, not a value, not its palette — is in this repository. Every PNG here is written by
`spec/build_fixtures.py`, in pure Python, from a description in that script: which rows hold
which cells and under which PNG filter type, a palette ramp it writes itself, and the chunks it
adds. Edit the script and run it, never a `.png` or a twin. `python -I -B spec/build_fixtures.py
--check` rebuilds the set and prints `CURRENT` when the tree matches it.

These are the fixtures of `iem_n0q` (#31 in the ordinal table, `adapters/iem_n0q.py`): one IEM
NEXRAD N0Q composite PNG per payload. The format is read against the PNG Third Edition and IEM's
composite and raster-catalogue pages, cited by URL in `spec/iem_n0q_pin.json` and not carried
here.

## The product's real size

Every PNG is 12200 x 5400 cells of 8-bit palette indices, the size the adapter holds every file
to, so each one inflates to the product's 65,885,400 octets of rows. Almost every cell is index 0
(missing), so each file is about 64 KB: the script writes its own DEFLATE stream (one
dynamic-Huffman block whose 258-octet copy costs two bits), because a zlib build is free to choose
other matches and `--check` must give the same bytes on every machine.

## Why each fixture ships twice

`<name>.png` is the file as the archive would hold it. `<name>.parsed.json` is its twin: the octets
as `wire_hex`, IHDR's seven fields, the palette, every ancillary chunk in file order (a `tEXt`
chunk as its keyword and text, any other as its octets in hexadecimal) and `index_summary` — the
cell count, the count of index-0 cells and the least and greatest non-zero index. The script
writes the twin from its description, never by decoding the PNG;
`tests/test_cdm_iem_n0q_adapter.py` holds the adapter's decode of each file to its twin, the
cells the codec reads back to the script's literals, and every dBZ to (index - 65) / 2 worked by
hand.

## The places and the times

A PNG states no place: the footprint every Event carries is the adapter's PRODUCT CONSTANT, the
IEM composite's documented grid (research-raster F1, F11), not something these files state, so
the Baltic-rectangle rule for what a fixture states (`CONTRIBUTING.md`, "Identifiers and places
in observation fixtures") has nothing here to apply to; no file names a radar, a site or a tile.
A PNG states no slot either: the packaged fixtures are translated under the slot
2026-04-29T06:05:00Z (`IemN0qAdapter.fixture_instance`), before the harness's frozen receipt
instant (06:15). Each `gentime` text is a synthetic stamp earlier than that slot — the generation
clock IEM writes can precede the slot it names — and it is carried verbatim as
`product_version.production_time_verbatim`, never as a time.

## The set

| Fixture | What it exercises |
|---|---|
| `ramp_ends_every_filter_type` | ten rows under filter types 0, 1, 2, 3, 4, 0, 1, 2, 3, 4, eight cells each of indices 1, 65, 66 and 255 rotated a cell a row: the ramp's ends (-32.0 and 95.0 dBZ), its zero and its half step; a `gentime` |
| `echo_patch_split_idat` | a patch of index 65 and 66 under Sub and Up (0.0 and 0.5 dBZ); the image data split over three IDAT chunks; a `tRNS` chunk kept verbatim; a `gentime` |
| `all_missing_no_gentime` | every cell index 0: a summary with no extremes, no `gentime`, so no `product_version` |
| `corner_cells_paeth_average` | one cell in each corner (indices 100, 150, 200, 255) on the first row under Paeth and the last under Average; a second `tEXt` chunk and a `tIME` chunk after the image data, both kept verbatim and read for nothing |

`malformed/` holds the payloads the adapter must refuse; its README names each one's refusal.
