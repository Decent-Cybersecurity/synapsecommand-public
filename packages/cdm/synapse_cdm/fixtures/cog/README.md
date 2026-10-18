# cog fixtures

**Every one is synthetic.** No file from USGS 3DEP, NOAA's coastal elevation models, HLS, ECOSTRESS
or any other producer — not a file, not a byte range, not a value — is in this repository. Every
file here is written by `spec/build_fixtures.py` from literals in that script: eight GeoTIFFs by
GDAL 3.13.3 from an ASCII grid the script writes (through a small VRT where the band needs a
description, a unit, a scale or an offset), and two VRT indexes by the script itself. Edit the
script and run it, never a `.tif`, a `.vrt` or a twin. `python -I -B spec/build_fixtures.py
--check` rebuilds the set and prints `CURRENT` when the tree matches it; without GDAL on PATH it
holds the eight tool-written files to their recorded SHA-256 and says so, and `--require-gdal`
refuses to pass unless GDAL re-wrote them.

These are the fixtures of `cog` (#30 in the ordinal table, `adapters/cog.py`): one GeoTIFF, Cloud
Optimized GeoTIFF or GDAL VRT per payload. The layouts are read against OGC GeoTIFF 1.1, OGC COG
1.0 and TIFF 6.0, cited by reference in `spec/cog_pin.json` and not carried here.

## Why each fixture ships twice

`<name>.tif` or `<name>.vrt` is the file as a directory holds it. `<name>.parsed.json` is its twin:
the octets as `wire_hex`; for a GeoTIFF the header, every directory's entries under their TIFF
names (each with its TIFF type), each directory's block offsets and byte counts under `arrays`,
IFD 0's GeoKeys under their OGC GeoTIFF 1.1 names, its GDAL_METADATA items, the vertical system the
GeoKeys state, and the window — block 0 of the full-resolution image, its summary and, when it
holds at most 4096 cells, its values; for a VRT everything the index states, its sources listed.
The script writes the twin from the literals the file was written from, never by decoding it: for
a GDAL file, from the grid it gave GDAL and the directory layout GDAL chose, read once from GDAL's
octets with libtiff's `tiffdump` and `tiffinfo` and written into the script.
`tests/test_cdm_cog_adapter.py` holds the adapter's decode of each file to its twin, the twin's
own translation to the file's, and every footprint vertex to a hand-derived corner or PROJ's
reading of the same point.

## The places and the times

Every footprint lies inside the Baltic rectangle (56.0–58.5 N, 20.0–24.5 E, `CONTRIBUTING.md`,
"Identifiers and places in observation fixtures"). No file states a tile, granule or scene
identifier. The two band files that state a sensing time state one on 2026-04-29, before the
harness's frozen receipt instant (06:15); their processing clocks are later, and no file name is
read for a time.

## The set

| Fixture | Writer | What it exercises |
|---|---|---|
| `float32_lzw_predictor3` | GDAL | a 3 x 3 Float32 strip under LZW with the floating-point predictor, EPSG:4326; a DEM with no time, so an ANNOTATION PlanObject |
| `float32_deflate_nad83` | GDAL | Deflate with the floating-point predictor in EPSG:4269 (NAD83), stated as WGS84 without a datum shift |
| `int16_packbits_pixel_is_point` | GDAL | Int16 under PackBits marked PixelIsPoint: the tiepoint names a cell centre, so the outline lies half a cell further out |
| `utm_tiled_cog_lzw` | GDAL | a 256 x 256 COG in UTM zone 34N: four 128 x 128 tiles, an overview directory, the ghost header before IFD 0; the footprint converted point by point; the window (16,384 cells) summarised, not carried |
| `navd88_dem_deflate` | GDAL | EPSG:5498 (NAD83 + NAVD88 height): the vertical datum stated as `{name, namespace}` in the residual and never as an ellipsoidal height; a nodata cell; ImageDescription and DateTime carried |
| `hls_shaped_band_cog` | GDAL | an HLS-shaped band: a COG of Int16 under Deflate with horizontal differencing, scale 0.0001, a sensing instant (`SENSING_TIME`) and a processing clock (`HLS_PROCESSING_TIME`) in GDAL_METADATA, two coverage items; an `imagery-product/1` Event whose window is by reference with its summary |
| `float32_big_endian_nodata` | GDAL | an uncompressed big-endian file in strips of two rows: the window is the first strip, with two nodata cells and a NaN |
| `ecostress_shaped_lst_tiled` | GDAL | an ECOSTRESS-shaped tiled file: a sensing interval from `RangeBeginning`/`RangeEnding` items ending Z, unit K, NaN as nodata, an 8 x 8 image in a 16 x 16 tile; an Event whose 64 values are inline |
| `local_sources_index` | script | a VRT index of two local sources in EPSG:4326, listed and never opened |
| `compound_navd88_index` | script | a VRT whose SRS is the WKT1 COMPD_CS of EPSG:5498, read as NAD83 horizontally |

`malformed/` holds the payloads the adapter must refuse; its README names each one's refusal.
