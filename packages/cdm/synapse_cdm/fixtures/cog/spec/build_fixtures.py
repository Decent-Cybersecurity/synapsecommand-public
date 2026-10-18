#!/usr/bin/env python3
"""Build the cog fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py                 # writes every generated file under fixtures/cog/
    python -I -B build_fixtures.py --check         # builds everything in memory and compares it,
                                                   # byte for byte, with the tree; prints CURRENT
                                                   # and exits 0, or STALE: <names> and exits 1
    python -I -B build_fixtures.py --check --require-gdal
                                                   # the same, and refuses to pass unless GDAL
                                                   # 3.13.3 re-wrote the tool-written files

Edit this file, never a `.tif`, a `.vrt`, a twin or a provenance record. `README.md` beside the
payloads, `malformed/README.md` and `spec/cog_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Ten payloads, each `<name>.<ext>` with its twin `<name>.parsed.json`, and the refusal set under
`malformed/`. Two writers, neither sharing a line with `adapters/cog.py` or
`adapters/raster_codec.py`:

- GDAL 3.13.3 writes eight GeoTIFFs (`GDAL_FIXTURES`): Float32 under LZW with the floating-point
  predictor, under Deflate in NAD83, Int16 under PackBits marked PixelIsPoint, a tiled COG in UTM
  with an overview, a DEM in NAD83 + NAVD88 height (EPSG:5498) with a nodata cell, an HLS-shaped
  band (a COG of Int16 under Deflate with horizontal differencing, a scale, a sensing instant and
  a processing clock in GDAL_METADATA), an uncompressed big-endian Float32 file in strips of two
  rows with nodata and NaN cells, and an ECOSTRESS-shaped tiled file whose sensing interval and
  unit are stated and whose nodata is NaN. GDAL is run from a temporary directory, with relative
  file names and `GDAL_PAM_ENABLED=NO` (no `.aux.xml` beside the output), from an ESRI ASCII grid
  this script writes from its literals, through a VRT where the band needs a description, a unit,
  a scale or an offset.
- this script writes two VRT indexes as text and every malformed payload with its own small TIFF
  writer (`tiff_file`), after the TIFF 6.0 layouts.

Each twin is written from LITERALS, never by decoding a payload: the grid literals the file was
written from, and for a GDAL file the directory layout GDAL chose — read once from GDAL's octets
with libtiff's `tiffdump -m 100000` and `tiffinfo` and listgeo's GeoKey listing on 2026-10-17,
and written down in `GDAL_FIXTURES` (the doubles from the grid literals, which those tools print
rounded). The window of each twin — block 0 of the full-resolution image, its summary and, when
it holds at most 4096 cells, its values — is computed here from the grid literals. The twin is
the expectation `tests/test_cdm_cog_adapter.py` holds the adapter's decode to.

GDAL AND `--check`
------------------
With GDAL 3.13.3 on PATH, `--check` re-runs GDAL and compares its octets with the tree's. Without
it — every CI runner, which carries no GDAL — the eight tool-written files are checked against
the SHA-256 of each recorded in `GDAL_DIGESTS` (and in the pin), and a line says so; everything
else is rebuilt either way. `--require-gdal` makes the GDAL re-run a condition of passing: that is
the reading the maintainer takes on the named build before a release (DECISIONS U-11).

EVERYTHING IS SYNTHETIC. Every footprint lies in the Baltic rectangle (56.0-58.5 N, 20.0-24.5 E,
CONTRIBUTING.md, "Identifiers and places in observation fixtures"), no file states a tile or
granule identifier, every instant is on 2026-04-29 or 2026-04-30, and every value is a literal
below, not taken from a product.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED_DIR = FIXTURES / "malformed"

ORIGIN_GDAL = (
    "Synthetic GeoTIFF written on 2026-10-17 for the cog adapter's landing by GDAL 3.13.3, run by "
    "fixtures/cog/spec/build_fixtures.py from an ASCII grid of literals in that script; the "
    "footprint lies in the Baltic rectangle and nothing is recorded data."
)
ORIGIN_VRT = (
    "Synthetic GDAL VRT index written on 2026-10-17 for the cog adapter's landing by "
    "fixtures/cog/spec/build_fixtures.py from literals in that script, in the form GDAL writes; "
    "its sources are names only, the footprint lies in the Baltic rectangle and nothing is "
    "recorded data."
)
ORIGIN_TWIN = (
    "Synthetic parsed twin of a cog fixture, written on 2026-10-17 by "
    "fixtures/cog/spec/build_fixtures.py from the literals the file was written from, never by "
    "decoding it; the footprint lies in the Baltic rectangle and nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed payload written on 2026-10-17 by fixtures/cog/spec/build_fixtures.py, "
    "from literals in that script, for the conformance suite's check H; malformed/README.md names "
    "what is wrong with it and the refusal it expects. Nothing is recorded data."
)

GDAL_VERSION = 'GDAL 3.13.3 "Iowa City", released 2026/08/13'


def north_first(width: int, height: int, value) -> list[list]:
    return [[value(r, c) for c in range(width)] for r in range(height)]


#: The eight GDAL-written files. `grid` is the ASCII grid GDAL reads (rows north first, `None`
#: for the nodata cells, the string "nan" for a NaN); `band` the VRT band GDAL reads it through,
#: when the band needs more than the grid states; `args` the gdal_translate arguments; `layout`
#: the header, the directories and the block arrays GDAL wrote; `geokeys`, `gdal_metadata` and
#: `vertical` the twin's literals; `window` where block 0 lies and how it is stored.
GDAL_FIXTURES: dict[str, dict] = {}
WGS84_INVERSE_FLATTENING = 298.257223563
NAD83_INVERSE_FLATTENING = 298.257222101

#: OGC GeoTIFF 1.1's key names for the keys GDAL wrote here (19-008r4, Annex).
GEOGRAPHIC_KEYS_WGS84 = [
    {"id": 1024, "name": "GTModelTypeGeoKey", "value": 2},
    {"id": 1025, "name": "GTRasterTypeGeoKey", "value": 1},
    {"id": 2048, "name": "GeodeticCRSGeoKey", "value": 4326},
    {"id": 2049, "name": "GeodeticCitationGeoKey", "value": "WGS 84"},
    {"id": 2054, "name": "GeogAngularUnitsGeoKey", "value": 9102},
    {"id": 2057, "name": "EllipsoidSemiMajorAxisGeoKey", "value": [6378137.0]},
    {"id": 2059, "name": "EllipsoidInvFlatteningGeoKey", "value": [WGS84_INVERSE_FLATTENING]},
]


def utm_keys(zone: int) -> list[dict]:
    return [
        {"id": 1024, "name": "GTModelTypeGeoKey", "value": 1},
        {"id": 1025, "name": "GTRasterTypeGeoKey", "value": 1},
        {"id": 1026, "name": "GTCitationGeoKey", "value": f"WGS 84 / UTM zone {zone}N"},
        {"id": 2049, "name": "GeodeticCitationGeoKey", "value": "WGS 84"},
        {"id": 2054, "name": "GeogAngularUnitsGeoKey", "value": 9102},
        {"id": 3072, "name": "ProjectedCRSGeoKey", "value": 32600 + zone},
        {"id": 3076, "name": "ProjLinearUnitsGeoKey", "value": 9001},
    ]


def item(name, value, sample=None, role=None, domain=None) -> dict:
    return {"name": name, "sample": sample, "role": role, "domain": domain, "value": value}


OVERVIEW_ITEM = item("OVERVIEW_RESAMPLING", "CUBIC", domain="IMAGE_STRUCTURE")


def encoding(compression: int, predictor: int) -> str:
    names = {1: "none", 5: "LZW", 8: "Deflate", 32773: "PackBits"}
    predictors = {1: "none", 2: "horizontal differencing", 3: "floating point"}
    return (
        f"TIFF Compression {compression} ({names[compression]}), "
        f"Predictor {predictor} ({predictors[predictor]})"
    )


#: The eight GDAL-written files. `grid` is the ASCII grid GDAL reads (rows north first, `None`
#: for a nodata cell, the string "nan" for a NaN); `band` the VRT band GDAL reads it through when
#: the band needs a description, a unit, a scale or an offset; `args` the gdal_translate
#: arguments; `layout` the header, the directories and the block arrays GDAL wrote (IFD 0's GeoKey
#: and GDAL_METADATA tags are the `geokeys` and `gdal_metadata` literals instead); `vertical` the
#: twin's vertical block; `window` block 0 of the full-resolution image and how it is stored.
GDAL_FIXTURES: dict[str, dict] = {
    "float32_lzw_predictor3": {
        "grid": {
            "rows": [[12.5, 13.25, 14.0], [15.5, 16.75, 18.0], [19.25, 20.5, 21.75]],
            "west": 21.0,
            "south": 57.0,
            "cell": 0.25,
            "nodata": "-9999",
        },
        "band": None,
        "args": ["-of", "GTiff", "-ot", "Float32", "-a_srs", "EPSG:4326"]
        + ["-co", "COMPRESS=LZW", "-co", "PREDICTOR=3"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [3]),
                        (257, "SHORT", [3]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [5]),
                        (262, "SHORT", [1]),
                        (273, "LONG", [396]),
                        (277, "SHORT", [1]),
                        (278, "SHORT", [3]),
                        (279, "LONG", [30]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [3]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [0.25, 0.25, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 21.0, 57.75, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {"minor_revision": 0, "keys": GEOGRAPHIC_KEYS_WGS84},
        "gdal_metadata": None,
        "vertical": None,
        "window": {
            "width": 3,
            "height": 3,
            "dtype": "Float32",
            "encoding": encoding(5, 3),
            "missing_mechanism": None,
        },
    },
    "float32_deflate_nad83": {
        "grid": {
            "rows": [[-3.5, -1.25, 0.0], [2.75, 4.5, 6.25], [8.0, 9.75, 11.5]],
            "west": 22.0,
            "south": 57.5,
            "cell": 0.125,
            "nodata": "-9999",
        },
        "band": None,
        "args": ["-of", "GTiff", "-ot", "Float32", "-a_srs", "EPSG:4269"]
        + ["-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [3]),
                        (257, "SHORT", [3]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [8]),
                        (262, "SHORT", [1]),
                        (273, "LONG", [395]),
                        (277, "SHORT", [1]),
                        (278, "SHORT", [3]),
                        (279, "LONG", [34]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [3]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [0.125, 0.125, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 22.0, 57.875, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {
            "minor_revision": 0,
            "keys": [
                {"id": 1024, "name": "GTModelTypeGeoKey", "value": 2},
                {"id": 1025, "name": "GTRasterTypeGeoKey", "value": 1},
                {"id": 2048, "name": "GeodeticCRSGeoKey", "value": 4269},
                {"id": 2049, "name": "GeodeticCitationGeoKey", "value": "NAD83"},
                {"id": 2054, "name": "GeogAngularUnitsGeoKey", "value": 9102},
                {"id": 2057, "name": "EllipsoidSemiMajorAxisGeoKey", "value": [6378137.0]},
                {
                    "id": 2059,
                    "name": "EllipsoidInvFlatteningGeoKey",
                    "value": [NAD83_INVERSE_FLATTENING],
                },
            ],
        },
        "gdal_metadata": None,
        "vertical": None,
        "window": {
            "width": 3,
            "height": 3,
            "dtype": "Float32",
            "encoding": encoding(8, 3),
            "missing_mechanism": None,
        },
    },
    "int16_packbits_pixel_is_point": {
        "grid": {
            "rows": [[7, 7, 7, 7], [7, -3, -3, 1200]],
            "west": 20.5,
            "south": 56.25,
            "cell": 0.25,
            "nodata": "-9999",
        },
        "band": None,
        "args": ["-of", "GTiff", "-ot", "Int16", "-a_srs", "EPSG:4326"]
        + ["-mo", "AREA_OR_POINT=Point", "-co", "COMPRESS=PACKBITS"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [4]),
                        (257, "SHORT", [2]),
                        (258, "SHORT", [16]),
                        (259, "SHORT", [32773]),
                        (262, "SHORT", [1]),
                        (273, "LONG", [384]),
                        (277, "SHORT", [1]),
                        (278, "SHORT", [2]),
                        (279, "LONG", [18]),
                        (284, "SHORT", [1]),
                        (339, "SHORT", [2]),
                        (33550, "DOUBLE", [0.25, 0.25, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 20.625, 56.625, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {
            "minor_revision": 0,
            "keys": [
                dict(key, value=2) if key["id"] == 1025 else key for key in GEOGRAPHIC_KEYS_WGS84
            ],
        },
        "gdal_metadata": None,
        "vertical": None,
        "window": {
            "width": 4,
            "height": 2,
            "dtype": "Int16",
            "encoding": encoding(32773, 1),
            "missing_mechanism": None,
        },
    },
    "utm_tiled_cog_lzw": {
        "grid": {
            "rows": north_first(256, 256, lambda r, c: 10 + 0.5 * r + 0.25 * c),
            "west": 470000.0,
            "south": 6320000.0,
            "cell": 30.0,
            "nodata": "-9999",
        },
        "band": None,
        "args": ["-of", "COG", "-ot", "Float32", "-a_srs", "EPSG:32634"]
        + ["-co", "COMPRESS=LZW", "-co", "PREDICTOR=3", "-co", "BLOCKSIZE=128"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 192,
            "ifds": [
                {
                    "offset": 192,
                    "next_ifd_offset": 704,
                    "tags": [
                        (256, "SHORT", [256]),
                        (257, "SHORT", [256]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [5]),
                        (262, "SHORT", [1]),
                        (277, "SHORT", [1]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [3]),
                        (322, "SHORT", [128]),
                        (323, "SHORT", [128]),
                        (324, "LONG", [3850, 5812, 7795, 10371]),
                        (325, "LONG", [1954, 1975, 2568, 2185]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [30.0, 30.0, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 470000.0, 6327680.0, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
                {
                    "offset": 704,
                    "next_ifd_offset": 0,
                    "tags": [
                        (254, "LONG", [1]),
                        (256, "SHORT", [128]),
                        (257, "SHORT", [128]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [5]),
                        (262, "SHORT", [1]),
                        (277, "SHORT", [1]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [3]),
                        (322, "SHORT", [128]),
                        (323, "SHORT", [128]),
                        (324, "LONG", [932]),
                        (325, "LONG", [2910]),
                        (339, "SHORT", [3]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {"minor_revision": 0, "keys": utm_keys(34)},
        "gdal_metadata": [OVERVIEW_ITEM],
        "vertical": None,
        "window": {
            "width": 128,
            "height": 128,
            "dtype": "Float32",
            "encoding": encoding(5, 3),
            "missing_mechanism": None,
        },
    },
    "navd88_dem_deflate": {
        "grid": {
            "rows": [
                [-12.5, -7.25, -2.0, 1.5],
                [None, 3.25, 5.0, 8.75],
                [10.5, 12.25, 14.0, 15.75],
            ],
            "west": 23.0,
            "south": 57.25,
            "cell": 0.0625,
            "nodata": "-99999",
        },
        "band": None,
        "args": ["-of", "GTiff", "-ot", "Float32", "-a_srs", "EPSG:5498"]
        + ["-mo", "TIFFTAG_IMAGEDESCRIPTION=synthetic topography-bathymetry; NAVD88"]
        + ["-mo", "TIFFTAG_DATETIME=2026:04:01 12:00:00"]
        + ["-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [4]),
                        (257, "SHORT", [3]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [8]),
                        (262, "SHORT", [1]),
                        (270, "ASCII", "synthetic topography-bathymetry; NAVD88"),
                        (273, "LONG", [453]),
                        (277, "SHORT", [1]),
                        (278, "SHORT", [3]),
                        (279, "LONG", [46]),
                        (284, "SHORT", [1]),
                        (306, "ASCII", "2026:04:01 12:00:00"),
                        (317, "SHORT", [3]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [0.0625, 0.0625, 1.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 23.0, 57.4375, 0.0]),
                        (42113, "ASCII", "-99999"),
                    ],
                },
            ],
        },
        "geokeys": {
            "minor_revision": 1,
            "keys": [
                {"id": 1024, "name": "GTModelTypeGeoKey", "value": 2},
                {"id": 1025, "name": "GTRasterTypeGeoKey", "value": 1},
                {"id": 1026, "name": "GTCitationGeoKey", "value": "NAD83 + NAVD88 height"},
                {"id": 2048, "name": "GeodeticCRSGeoKey", "value": 4269},
                {"id": 4096, "name": "VerticalGeoKey", "value": 5703},
            ],
        },
        "gdal_metadata": None,
        "vertical": {
            "datum": {
                "name": "NAVD88 height",
                "namespace": "EPSG:5703, read from OGC GeoTIFF 1.1 VerticalGeoKey (4096)",
            },
            "unit": "metre",
            "unit_namespace": "the axis unit of EPSG:5703 in PROJ's EPSG database",
            "orthometric": True,
        },
        "window": {
            "width": 4,
            "height": 3,
            "dtype": "Float32",
            "encoding": encoding(8, 3),
            "missing_mechanism": "GDAL_NODATA (TIFF tag 42113): -99999",
        },
    },
    "hls_shaped_band_cog": {
        "grid": {
            "rows": north_first(
                256, 256, lambda r, c: None if r == 0 and c < 5 else 1000 + 3 * r + 2 * c
            ),
            "west": 520000.0,
            "south": 6290000.0,
            "cell": 30.0,
            "nodata": "-9999",
        },
        "band": {
            "type": "Int16",
            "description": "Red",
            "nodata": "-9999",
            "offset": "0",
            "scale": "0.0001",
        },
        "args": ["-of", "COG", "-a_srs", "EPSG:32634"]
        + ["-mo", "SENSING_TIME=2026-04-29T05:41:07.250000Z"]
        + ["-mo", "HLS_PROCESSING_TIME=2026-04-30T02:11:45Z"]
        + ["-mo", "CLOUD_COVERAGE=17", "-mo", "SPATIAL_COVERAGE=100"]
        + ["-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=2", "-co", "BLOCKSIZE=128"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 192,
            "ifds": [
                {
                    "offset": 192,
                    "next_ifd_offset": 1096,
                    "tags": [
                        (256, "SHORT", [256]),
                        (257, "SHORT", [256]),
                        (258, "SHORT", [16]),
                        (259, "SHORT", [8]),
                        (262, "SHORT", [1]),
                        (277, "SHORT", [1]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [2]),
                        (322, "SHORT", [128]),
                        (323, "SHORT", [128]),
                        (324, "LONG", [1770, 2212, 2642, 3067]),
                        (325, "LONG", [434, 422, 417, 417]),
                        (339, "SHORT", [2]),
                        (33550, "DOUBLE", [30.0, 30.0, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 520000.0, 6297680.0, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
                {
                    "offset": 1096,
                    "next_ifd_offset": 0,
                    "tags": [
                        (254, "LONG", [1]),
                        (256, "SHORT", [128]),
                        (257, "SHORT", [128]),
                        (258, "SHORT", [16]),
                        (259, "SHORT", [8]),
                        (262, "SHORT", [1]),
                        (277, "SHORT", [1]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [2]),
                        (322, "SHORT", [128]),
                        (323, "SHORT", [128]),
                        (324, "LONG", [1324]),
                        (325, "LONG", [438]),
                        (339, "SHORT", [2]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {"minor_revision": 0, "keys": utm_keys(34)},
        "gdal_metadata": [
            item("CLOUD_COVERAGE", "17"),
            item("HLS_PROCESSING_TIME", "2026-04-30T02:11:45Z"),
            item("SENSING_TIME", "2026-04-29T05:41:07.250000Z"),
            item("SPATIAL_COVERAGE", "100"),
            item("OFFSET", "0", sample=0, role="offset"),
            item("SCALE", "0.0001", sample=0, role="scale"),
            item("DESCRIPTION", "Red", sample=0, role="description"),
            OVERVIEW_ITEM,
        ],
        "vertical": None,
        "window": {
            "width": 128,
            "height": 128,
            "dtype": "Int16",
            "encoding": encoding(8, 2),
            "missing_mechanism": "GDAL_NODATA (TIFF tag 42113): -9999",
        },
    },
    "float32_big_endian_nodata": {
        "grid": {
            "rows": [
                [1.5, None, 2.5, "nan"],
                [3.0, 3.5, None, 4.5],
                [5.0, 5.5, 6.0, 6.5],
                [7.0, 7.5, 8.0, 8.5],
            ],
            "west": 20.5,
            "south": 56.0,
            "cell": 0.125,
            "nodata": "-9999",
        },
        "band": None,
        "args": ["-of", "GTiff", "-ot", "Float32", "-a_srs", "EPSG:4326"]
        + ["-co", "ENDIANNESS=BIG", "-co", "BLOCKYSIZE=2"],
        "layout": {
            "byte_order": "MM",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [4]),
                        (257, "SHORT", [4]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [1]),
                        (262, "SHORT", [1]),
                        (273, "LONG", [392, 424]),
                        (277, "SHORT", [1]),
                        (278, "SHORT", [2]),
                        (279, "SHORT", [32, 32]),
                        (284, "SHORT", [1]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [0.125, 0.125, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 20.5, 56.5, 0.0]),
                        (42113, "ASCII", "-9999"),
                    ],
                },
            ],
        },
        "geokeys": {"minor_revision": 0, "keys": GEOGRAPHIC_KEYS_WGS84},
        "gdal_metadata": None,
        "vertical": None,
        "window": {
            "width": 4,
            "height": 2,
            "dtype": "Float32",
            "encoding": encoding(1, 1),
            "missing_mechanism": "GDAL_NODATA (TIFF tag 42113): -9999; a NaN sample, "
            "which states no number",
        },
    },
    "ecostress_shaped_lst_tiled": {
        "grid": {
            "rows": north_first(
                8, 8, lambda r, c: "nan" if (r, c) == (2, 3) else 280 + 0.25 * r + 0.5 * c
            ),
            "west": 320000.0,
            "south": 6340000.0,
            "cell": 70.0,
            "nodata": "nan",
        },
        "band": {"type": "Float32", "description": "LST", "nodata": "nan", "unit": "K"},
        "args": ["-of", "GTiff", "-a_srs", "EPSG:32635"]
        + ["-mo", "RangeBeginningDate=2026-04-29", "-mo", "RangeBeginningTime=04:17:20.000000Z"]
        + ["-mo", "RangeEndingDate=2026-04-29", "-mo", "RangeEndingTime=04:18:12.000000Z"]
        + ["-mo", "ProductionDateTime=2026-04-29T11:02:33.000000Z"]
        + ["-co", "TILED=YES", "-co", "BLOCKXSIZE=16", "-co", "BLOCKYSIZE=16"]
        + ["-co", "COMPRESS=DEFLATE", "-co", "PREDICTOR=3"],
        "layout": {
            "byte_order": "II",
            "first_ifd_offset": 8,
            "ifds": [
                {
                    "offset": 8,
                    "next_ifd_offset": 0,
                    "tags": [
                        (256, "SHORT", [8]),
                        (257, "SHORT", [8]),
                        (258, "SHORT", [32]),
                        (259, "SHORT", [8]),
                        (262, "SHORT", [1]),
                        (277, "SHORT", [1]),
                        (284, "SHORT", [1]),
                        (317, "SHORT", [3]),
                        (322, "SHORT", [16]),
                        (323, "SHORT", [16]),
                        (324, "LONG", [852]),
                        (325, "LONG", [101]),
                        (339, "SHORT", [3]),
                        (33550, "DOUBLE", [70.0, 70.0, 0.0]),
                        (33922, "DOUBLE", [0.0, 0.0, 0.0, 320000.0, 6340560.0, 0.0]),
                        (42113, "ASCII", "nan"),
                    ],
                },
            ],
        },
        "geokeys": {"minor_revision": 0, "keys": utm_keys(35)},
        "gdal_metadata": [
            item("ProductionDateTime", "2026-04-29T11:02:33.000000Z"),
            item("RangeBeginningDate", "2026-04-29"),
            item("RangeBeginningTime", "04:17:20.000000Z"),
            item("RangeEndingDate", "2026-04-29"),
            item("RangeEndingTime", "04:18:12.000000Z"),
            item("UNITTYPE", "K", sample=0, role="unittype"),
            item("DESCRIPTION", "LST", sample=0, role="description"),
        ],
        "vertical": None,
        "window": {
            "width": 8,
            "height": 8,
            "dtype": "Float32",
            "encoding": encoding(8, 3),
            "missing_mechanism": "GDAL_NODATA (TIFF tag 42113): nan",
        },
    },
}

#: The SHA-256 of each GDAL-written file, as GDAL 3.13.3 wrote it twice on 2026-10-17.
GDAL_DIGESTS = {
    "float32_lzw_predictor3": "5886c1ceb060c6a81b69b3a8f09299bbcd913329c4943ebc840f415f96ad643e",
    "float32_deflate_nad83": "903db94091fa41085dc872d808145f8d3ef37908541f15d90c216687e19b76c2",
    "int16_packbits_pixel_is_point": (
        "008392bde85255ce403aeebceac8b81d60ae86417baa2fb275b1a208e87826f0"
    ),
    "utm_tiled_cog_lzw": "589ed1f54081cd80980be071b5ad9d8c980c0903c025a960f1556f5c315c39dc",
    "navd88_dem_deflate": "d8773c26a3bf2f3597c10310accbd3ec7c973990144605e2394e88a482840d86",
    "hls_shaped_band_cog": "da1a65e81924c8ae6de4d1b89767da3718137853dc8e41160ec8def73792a55f",
    "float32_big_endian_nodata": (
        "180f4c942b26273882a3b8a08efbe9a0c31716a838f45d2542326707cbdb2565"
    ),
    "ecostress_shaped_lst_tiled": (
        "2c37ed58c7afdbf3fd222f80f1cdec8d588de0f6b7e398d97d4b6430589515a8"
    ),
}

#: TIFF 6.0 and OGC GeoTIFF 1.1 tag names, for the twin's directory entries.
TAG_NAMES = {
    254: "NewSubfileType",
    256: "ImageWidth",
    257: "ImageLength",
    258: "BitsPerSample",
    259: "Compression",
    262: "PhotometricInterpretation",
    270: "ImageDescription",
    273: "StripOffsets",
    277: "SamplesPerPixel",
    278: "RowsPerStrip",
    279: "StripByteCounts",
    284: "PlanarConfiguration",
    306: "DateTime",
    317: "Predictor",
    322: "TileWidth",
    323: "TileLength",
    324: "TileOffsets",
    325: "TileByteCounts",
    339: "SampleFormat",
    33550: "ModelPixelScaleTag",
    33922: "ModelTiepointTag",
    42113: "GDAL_NODATA",
}
ARRAY_TAGS = {273, 279, 324, 325}


# -- GDAL ----------------------------------------------------------------------------------------


def ascii_grid(grid: dict) -> str:
    rows = grid["rows"]
    lines = [
        f"ncols {len(rows[0])}",
        f"nrows {len(rows)}",
        f"xllcorner {grid['west']!r}",
        f"yllcorner {grid['south']!r}",
        f"cellsize {grid['cell']!r}",
        f"NODATA_value {grid['nodata']}",
    ]
    lines += [
        " ".join(grid["nodata"] if v is None else v if isinstance(v, str) else repr(v) for v in row)
        for row in rows
    ]
    return "\n".join(lines) + "\n"


def band_vrt(grid: dict, band: dict) -> str:
    """The VRT GDAL reads the ASCII grid through when the band needs more than the grid says."""
    rows = grid["rows"]
    north = grid["south"] + len(rows) * grid["cell"]
    lines = [
        f'<VRTDataset rasterXSize="{len(rows[0])}" rasterYSize="{len(rows)}">',
        f"  <GeoTransform>{grid['west']!r}, {grid['cell']!r}, 0.0, {north!r}, 0.0, "
        f"{-grid['cell']!r}</GeoTransform>",
        f'  <VRTRasterBand dataType="{band["type"]}" band="1">',
        f"    <Description>{band['description']}</Description>",
        f"    <NoDataValue>{band['nodata']}</NoDataValue>",
    ]
    if "unit" in band:
        lines.append(f"    <UnitType>{band['unit']}</UnitType>")
    if "offset" in band:
        lines.append(f"    <Offset>{band['offset']}</Offset>")
    if "scale" in band:
        lines.append(f"    <Scale>{band['scale']}</Scale>")
    lines += [
        "    <SimpleSource>",
        '      <SourceFilename relativeToVRT="1">source.asc</SourceFilename>',
        "      <SourceBand>1</SourceBand>",
        "    </SimpleSource>",
        "  </VRTRasterBand>",
        "</VRTDataset>",
    ]
    return "\n".join(lines) + "\n"


def sha256(octets: bytes) -> str:
    """The package's one content digest (`evidence.digest_bytes`): this package imports no
    hashing module anywhere else (tests/test_cdm_boundary.py), and the geopackage and grib2
    builders take their digests the same way."""
    from synapse_cdm.evidence import digest_bytes

    return digest_bytes(octets)[0]


def gdal_available() -> bool:
    if shutil.which("gdal_translate") is None:
        return False
    done = subprocess.run(
        ["gdal_translate", "--version"], capture_output=True, text=True, check=False
    )
    return done.returncode == 0 and done.stdout.strip() == GDAL_VERSION


def gdal_write(name: str) -> bytes:
    """One GDAL-written file, from a temporary directory with relative file names."""
    spec = GDAL_FIXTURES[name]
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    with tempfile.TemporaryDirectory() as tmp:
        pathlib.Path(tmp, "source.asc").write_text(ascii_grid(spec["grid"]))
        source = "source.asc"
        if spec["band"] is not None:
            pathlib.Path(tmp, "source.vrt").write_text(band_vrt(spec["grid"], spec["band"]))
            source = "source.vrt"
        done = subprocess.run(
            ["gdal_translate", "-q", *spec["args"], source, "out.tif"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode != 0 or done.stderr.strip():
            raise RuntimeError(f"gdal_translate failed: {done.stderr.strip()}")
        return pathlib.Path(tmp, "out.tif").read_bytes()


# -- twins ---------------------------------------------------------------------------------------


def window(spec: dict) -> dict:
    """Block 0 of the full-resolution image, from the grid literals: the cells it covers in the
    image (north-west first), the nodata cells and NaNs missing, the summary of the rest."""
    w = spec["window"]
    integer = w["dtype"].startswith(("Int", "UInt"))
    cells = []
    for row in spec["grid"]["rows"][: w["height"]]:
        for value in row[: w["width"]]:
            if value is None or value == "nan":
                cells.append(None)
            else:
                cells.append(int(value) if integer else float(value))
    present = [v for v in cells if v is not None]
    return {
        "ifd": 0,
        "block": 0,
        "column": 0,
        "row": 0,
        "width": w["width"],
        "height": w["height"],
        "dtype": w["dtype"],
        "encoding": w["encoding"],
        "count": len(cells),
        "missing_count": len(cells) - len(present),
        "min": min(present) if present else None,
        "max": max(present) if present else None,
        "values": cells if len(cells) <= 4096 else None,
        "missing_mechanism": w["missing_mechanism"],
    }


def gdal_twin(name: str, octets: bytes) -> dict:
    spec = GDAL_FIXTURES[name]
    layout = spec["layout"]
    ifds, arrays = [], []
    for directory in layout["ifds"]:
        tags, blocks = {}, {}
        for tag, kind, value in directory["tags"]:
            if tag in ARRAY_TAGS:
                blocks[TAG_NAMES[tag]] = value
            else:
                tags[TAG_NAMES[tag]] = {"type": kind, "value": value}
        ifds.append(
            {
                "offset": directory["offset"],
                "next_ifd_offset": directory["next_ifd_offset"],
                "tags": tags,
            }
        )
        arrays.append(blocks)
    return {
        "wire_hex": octets.hex(),
        "header": {
            "byte_order": layout["byte_order"],
            "first_ifd_offset": layout["first_ifd_offset"],
        },
        "ifds": ifds,
        "arrays": arrays,
        "geokeys": {
            "version": 1,
            "revision": 1,
            "minor_revision": spec["geokeys"]["minor_revision"],
            "keys": spec["geokeys"]["keys"],
        },
        "gdal_metadata": spec["gdal_metadata"],
        "vertical": spec["vertical"],
        "window": window(spec),
    }


# -- the two VRT indexes, written here ------------------------------------------------------------

#: The SRS texts, as GDAL 3.13.3's gdalbuildvrt writes them for EPSG:4326 and EPSG:5498.
WKT_4326 = (
    'GEOGCS["WGS 84",DATUM["WGS_1984",SPHEROID["WGS 84",6378137,298.257223563,AUTHORITY["EPSG",'
    '"7030"]],AUTHORITY["EPSG","6326"]],PRIMEM["Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT['
    '"degree",0.0174532925199433,AUTHORITY["EPSG","9122"]],AXIS["Latitude",NORTH],AXIS['
    '"Longitude",EAST],AUTHORITY["EPSG","4326"]]'
)
WKT_5498 = (
    'COMPD_CS["NAD83 + NAVD88 height",GEOGCS["NAD83",DATUM["North_American_Datum_1983",SPHEROID['
    '"GRS 1980",6378137,298.257222101,AUTHORITY["EPSG","7019"]],AUTHORITY["EPSG","6269"]],PRIMEM['
    '"Greenwich",0,AUTHORITY["EPSG","8901"]],UNIT["degree",0.0174532925199433,AUTHORITY["EPSG",'
    '"9122"]],AXIS["Latitude",NORTH],AXIS["Longitude",EAST],AUTHORITY["EPSG","4269"]],VERT_CS['
    '"NAVD88 height",VERT_DATUM["North American Vertical Datum 1988",2005,AUTHORITY["EPSG","5103"]]'
    ',UNIT["metre",1,AUTHORITY["EPSG","9001"]],AXIS["Gravity-related height",UP],AUTHORITY["EPSG",'
    '"5703"]],AUTHORITY["EPSG","5498"]]'
)


def source(element, filename, size, dst, *, relative="1", nodata=None) -> dict:
    width, height = size
    entry = {
        "element": element,
        "source_filename": filename,
        "relative": relative,
        "SourceBand": "1",
        "SourceProperties": {
            "BlockXSize": str(width),
            "BlockYSize": str(height),
            "DataType": "Float32",
            "RasterXSize": str(width),
            "RasterYSize": str(height),
        },
        "SrcRect": {"xOff": "0", "xSize": str(width), "yOff": "0", "ySize": str(height)},
        "DstRect": {
            "xOff": str(dst[0]),
            "xSize": str(width),
            "yOff": str(dst[1]),
            "ySize": str(height),
        },
    }
    if nodata is not None:
        entry["NODATA"] = nodata
    return entry


VRT_FIXTURES: dict[str, dict] = {
    "local_sources_index": {
        "size": (6, 3),
        "srs": WKT_4326,
        "mapping": "2,1",
        "geo_transform": [21.0, 0.25, 0.0, 57.75, 0.0, -0.25],
        "metadata": [("AREA_OR_POINT", "Area")],
        "band": {
            "type": "Float32",
            "fields": [("NoDataValue", "-9999"), ("ColorInterp", "Gray")],
            "sources": [
                source(
                    "ComplexSource", "float32_lzw_predictor3.tif", (3, 3), (0, 0), nodata="-9999"
                ),
                source(
                    "ComplexSource", "east/float32_east_half.tif", (3, 3), (3, 0), nodata="-9999"
                ),
            ],
        },
    },
    "compound_navd88_index": {
        "size": (8, 4),
        "srs": WKT_5498,
        "mapping": "2,1,3",
        "geo_transform": [23.0, 0.0625, 0.0, 57.5, 0.0, -0.0625],
        "metadata": [],
        "band": {
            "type": "Float32",
            "fields": [("NoDataValue", "-99999"), ("ColorInterp", "Gray")],
            "sources": [
                source("SimpleSource", "navd88_dem_deflate.tif", (4, 3), (0, 1)),
            ],
        },
    },
}


def vrt_text(spec: dict, source_override: str | None = None, prologue: str = "") -> bytes:
    """The VRT as GDAL writes one: two-space indentation, the GeoTransform at %24.16e."""
    width, height = spec["size"]
    transform = ",".join(f"{v:24.16e}" for v in spec["geo_transform"])
    lines = [
        f'<VRTDataset rasterXSize="{width}" rasterYSize="{height}">',
        f'  <SRS dataAxisToSRSAxisMapping="{spec["mapping"]}">{spec["srs"]}</SRS>',
        f"  <GeoTransform>{transform}</GeoTransform>",
    ]
    if spec["metadata"]:
        lines.append("  <Metadata>")
        lines += [f'    <MDI key="{k}">{v}</MDI>' for k, v in spec["metadata"]]
        lines.append("  </Metadata>")
    band = spec["band"]
    lines.append(f'  <VRTRasterBand dataType="{band["type"]}" band="1">')
    lines += [f"    <{k}>{v}</{k}>" for k, v in band["fields"]]
    for entry in band["sources"]:
        name = source_override or entry["source_filename"]
        attributes = lambda d: " ".join(f'{k}="{d[k]}"' for k in d)  # noqa: E731
        props = entry["SourceProperties"]
        ordered = {
            k: props[k]
            for k in ("RasterXSize", "RasterYSize", "DataType", "BlockXSize", "BlockYSize")
        }
        rect = ("xOff", "yOff", "xSize", "ySize")
        lines += [
            f"    <{entry['element']}>",
            f'      <SourceFilename relativeToVRT="{entry["relative"]}">{name}</SourceFilename>',
            f"      <SourceBand>{entry['SourceBand']}</SourceBand>",
            f"      <SourceProperties {attributes(ordered)} />",
            f"      <SrcRect {attributes({k: entry['SrcRect'][k] for k in rect})} />",
            f"      <DstRect {attributes({k: entry['DstRect'][k] for k in rect})} />",
        ]
        if "NODATA" in entry:
            lines.append(f"      <NODATA>{entry['NODATA']}</NODATA>")
        lines.append(f"    </{entry['element']}>")
    lines += ["  </VRTRasterBand>", "</VRTDataset>"]
    return (prologue + "\n".join(lines) + "\n").encode("utf-8")


def vrt_twin(spec: dict, octets: bytes) -> dict:
    band = spec["band"]
    sources = []
    for entry in band["sources"]:
        twin = {
            "element": entry["element"],
            "source_filename": entry["source_filename"],
            "relative_to_vrt": entry["relative"] == "1",
            "shared": None,
            "SourceBand": entry["SourceBand"],
            "SourceProperties": entry["SourceProperties"],
            "SrcRect": entry["SrcRect"],
            "DstRect": entry["DstRect"],
        }
        if "NODATA" in entry:
            twin["NODATA"] = entry["NODATA"]
        sources.append(twin)
    return {
        "wire_hex": octets.hex(),
        "vrt": {
            "raster_x_size": spec["size"][0],
            "raster_y_size": spec["size"][1],
            "srs": {"text": spec["srs"], "data_axis_to_srs_axis_mapping": spec["mapping"]},
            "geo_transform": spec["geo_transform"],
            "metadata": [
                {"domain": None, "items": [{"key": k, "value": v} for k, v in spec["metadata"]]}
            ]
            if spec["metadata"]
            else [],
            "bands": [
                {
                    "band": 1,
                    "data_type": band["type"],
                    "fields": dict(band["fields"]),
                    "metadata": [],
                    "sources": sources,
                }
            ],
        },
    }


# -- a small TIFF writer, for the refusal set ---------------------------------------------------

TYPE_CODES = {
    "BYTE": (1, "B"),
    "ASCII": (2, None),
    "SHORT": (3, "H"),
    "LONG": (4, "I"),
    "DOUBLE": (12, "d"),
}


def _encode(kind: str, value, e: str) -> bytes:
    code, fmt = TYPE_CODES[kind]
    if kind == "ASCII":
        return value.encode("utf-8") + b"\x00"
    return struct.pack(e + fmt * len(value), *value)


def tiff_file(
    entries: list[tuple[int, str, object]],
    blocks: list[bytes] = (),
    *,
    order: str = "II",
    tiled: bool = False,
    next_ifd: int | None = None,
    block_offsets: list[int] | None = None,
    version: int = 42,
) -> bytes:
    """A one-directory classic TIFF: the header, the directory, its long values, then the
    blocks, whose offsets and byte counts are written into tags 273/279 (or 324/325) here.
    `next_ifd` is the next-directory offset as written (0 when None), `block_offsets` replaces
    the computed offsets, `version` the header's version: each lets a refusal be built."""
    e = "<" if order == "II" else ">"
    offsets_tag, counts_tag = (324, 325) if tiled else (273, 279)
    full = list(entries)
    if blocks:
        full += [
            (offsets_tag, "LONG", [0] * len(blocks)),
            (counts_tag, "LONG", [len(b) for b in blocks]),
        ]
    full.sort(key=lambda t: t[0])
    directory_size = 2 + 12 * len(full) + 4
    values_at = 8 + directory_size
    long_values = [_encode(k, v, e) for _, k, v in full]
    values_size = sum(len(v) for v in long_values if len(v) > 4)
    data_at = values_at + values_size
    positions, at = [], data_at
    for block in blocks:
        positions.append(at)
        at += len(block)
    if block_offsets is not None:
        positions = block_offsets
    out = bytearray(order.encode("ascii") + struct.pack(e + "HI", version, 8))
    out += struct.pack(e + "H", len(full))
    extra = bytearray()
    for tag, kind, value in full:
        if tag == offsets_tag and blocks:
            value = positions
        raw = _encode(kind, value, e)
        count = len(value) + 1 if kind == "ASCII" else len(value)
        out += struct.pack(e + "HHI", tag, TYPE_CODES[kind][0], count)
        if len(raw) <= 4:
            out += raw.ljust(4, b"\x00")
        else:
            out += struct.pack(e + "I", values_at + len(extra))
            extra += raw
    out += struct.pack(e + "I", 0 if next_ifd is None else next_ifd)
    out += extra
    for block in blocks:
        out += block
    return bytes(out)


#: The GeoTIFF tags of a 2 x 2 image at 21.0 E 57.5 N in EPSG:4326, cells of 0.25 degree.
GEO_4326 = [
    (33550, "DOUBLE", [0.25, 0.25, 0.0]),
    (33922, "DOUBLE", [0.0, 0.0, 0.0, 21.0, 57.5, 0.0]),
    (34735, "SHORT", [1, 1, 0, 3, 1024, 0, 1, 2, 1025, 0, 1, 1, 2048, 0, 1, 4326]),
]


def base_entries(width: int = 2, height: int = 2, *, compression: int = 1) -> list:
    return [
        (256, "SHORT", [width]),
        (257, "SHORT", [height]),
        (258, "SHORT", [32]),
        (259, "SHORT", [compression]),
        (262, "SHORT", [1]),
        (277, "SHORT", [1]),
        (339, "SHORT", [3]),
        *GEO_4326,
    ]


def float32_block(values: list[float], order: str = "II") -> bytes:
    return struct.pack(("<" if order == "II" else ">") + "f" * len(values), *values)


def deflate_zeros(count: int) -> bytes:
    """A zlib stream of `count` zero octets, assembled bit by bit: one final block of fixed
    Huffman codes (RFC 1951 3.2.6) — the literal 0, then matches of length 258 at distance 1 —
    so no zlib build can change an octet of it."""
    bits: list[int] = []

    def put(value: int, width: int, msb_first: bool) -> None:
        order = range(width - 1, -1, -1) if msb_first else range(width)
        bits.extend((value >> i) & 1 for i in order)

    put(1, 1, False)  # BFINAL
    put(1, 2, False)  # BTYPE 01, fixed Huffman codes
    put(0x30, 8, True)  # literal 0: codes 0-143 are 00110000 + value, eight bits
    written = 1
    while count - written >= 258:
        put(0xC5, 8, True)  # length code 285 (length 258): codes 280-287 are 11000000 + n - 280
        put(0, 5, True)  # distance code 0 (distance 1), five bits
        written += 258
    while written < count:
        put(0x30, 8, True)
        written += 1
    put(0, 7, True)  # end of block, code 256: seven zero bits
    while len(bits) % 8:
        bits.append(0)
    body = bytes(
        sum(bit << i for i, bit in enumerate(bits[k : k + 8])) for k in range(0, len(bits), 8)
    )
    return b"\x78\x01" + body + struct.pack(">I", zlib.adler32(b"\x00" * count))


def malformed() -> dict[str, bytes]:
    base = tiff_file(base_entries(), [float32_block([1.0, 2.0, 3.0, 4.0])])
    tiled = base_entries(16, 16) + [
        (322, "SHORT", [16]),
        (323, "SHORT", [16]),
    ]
    out = {
        "bigtiff_header.tif": b"II" + struct.pack("<HHHQ", 43, 8, 0, 16) + b"\x00" * 16,
        "truncated_ifd.tif": base[: 8 + 2 + 12 * 5],
        "tile_offset_past_the_end.tif": tiff_file(
            tiled, [float32_block([0.0] * 256)], tiled=True, block_offsets=[1 << 20]
        ),
        "jpeg_compression.tif": tiff_file(base_entries(compression=7), [b"\xff\xd8\xff\xd9"]),
        "unsupported_crs.tif": tiff_file(
            [e for e in base_entries() if e[0] != 34735]
            + [(34735, "SHORT", [1, 1, 0, 3, 1024, 0, 1, 1, 1025, 0, 1, 1, 3072, 0, 1, 3035])],
            [float32_block([1.0, 2.0, 3.0, 4.0])],
        ),
        "tile_inflates_past_its_size.tif": tiff_file(
            base_entries(512, 512, compression=8) + [(322, "SHORT", [512]), (323, "SHORT", [512])],
            [deflate_zeros(2 * 1024 * 1024)],
            tiled=True,
        ),
        "tile_past_the_decompression_bound.tif": tiff_file(
            base_entries(16, 16, compression=8) + [(322, "SHORT", [1024]), (323, "SHORT", [1024])],
            [deflate_zeros(16)],
            tiled=True,
        ),
        "ifd_loop.tif": tiff_file(
            base_entries(), [float32_block([1.0, 2.0, 3.0, 4.0])], next_ifd=8
        ),
        "vsicurl_source.vrt": vrt_text(
            VRT_FIXTURES["local_sources_index"],
            source_override="/vsicurl/https://example.invalid/tiles/east_half.tif",
        ),
        "entity_declaration.vrt": vrt_text(
            VRT_FIXTURES["local_sources_index"],
            prologue='<!DOCTYPE VRTDataset [<!ENTITY name "east/float32_east_half.tif">]>\n',
        ),
    }
    return out


# -- provenance and the build --------------------------------------------------------------------


def twin_text(twin: dict) -> bytes:
    """Indented JSON, ASCII, with a final newline."""
    return (json.dumps(twin, indent=2, ensure_ascii=True) + "\n").encode("ascii")


def provenance(directory: str, rows: list[tuple[str, str]]) -> bytes:
    record = {
        "directory": directory,
        "fixtures": [
            {
                "classification": "PUBLIC",
                "file": name,
                "operational_data": False,
                "origin": origin,
                "personal_data": False,
                "standard_ref": "cog/spec/cog_pin.json",
                "synthetic": True,
            }
            for name, origin in sorted(rows)
        ],
        "schema_id": "synapse.fixture-provenance/v1",
    }
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(require_gdal: bool = False) -> tuple[dict[pathlib.Path, bytes], dict[str, str], str]:
    """(path -> octets for every file this script writes, name -> digest for the GDAL files to
    check against the tree when GDAL is absent, a line saying which reading was taken)."""
    out: dict[pathlib.Path, bytes] = {}
    rows: list[tuple[str, str]] = []
    digest_only: dict[str, str] = {}
    have_gdal = gdal_available()
    if require_gdal and not have_gdal:
        raise SystemExit(f"--require-gdal: {GDAL_VERSION} is not the gdal_translate on PATH")
    for name in GDAL_FIXTURES:
        path = FIXTURES / f"{name}.tif"
        if have_gdal:
            octets = gdal_write(name)
            out[path] = octets
        else:
            octets = path.read_bytes() if path.is_file() else b""
            digest_only[name] = GDAL_DIGESTS[name]
        if sha256(octets) != GDAL_DIGESTS[name]:
            raise SystemExit(f"STALE: {name}.tif is not the file GDAL_DIGESTS records")
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(gdal_twin(name, octets))
        rows += [(f"{name}.tif", ORIGIN_GDAL), (f"{name}.parsed.json", ORIGIN_TWIN)]
    for name, spec in VRT_FIXTURES.items():
        octets = vrt_text(spec)
        out[FIXTURES / f"{name}.vrt"] = octets
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(vrt_twin(spec, octets))
        rows += [(f"{name}.vrt", ORIGIN_VRT), (f"{name}.parsed.json", ORIGIN_TWIN)]
    out[FIXTURES / "PROVENANCE.json"] = provenance("cog", rows)
    bad = malformed()
    for name, octets in bad.items():
        out[MALFORMED_DIR / name] = octets
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "cog/malformed", [(name, MALFORMED_ORIGIN) for name in bad]
    )
    reading = (
        f"GDAL: {GDAL_VERSION} re-wrote the {len(GDAL_FIXTURES)} tool-written files"
        if have_gdal
        else f"GDAL: {GDAL_VERSION} is not on PATH; the {len(GDAL_FIXTURES)} tool-written "
        "files were checked against their recorded SHA-256"
    )
    return out, digest_only, reading


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    if not directory.is_dir():
        return set()
    return {
        p
        for p in directory.iterdir()
        if p.is_file()
        and (
            p.suffix in (".tif", ".vrt")
            or p.name.endswith(".parsed.json")
            or p.name == "PROVENANCE.json"
        )
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument(
        "--require-gdal", action="store_true", help="fail unless GDAL 3.13.3 re-writes its eight"
    )
    args = parser.parse_args(argv)
    built, digest_only, reading = build(args.require_gdal)
    if args.check:
        expected = set(built) | {FIXTURES / f"{name}.tif" for name in digest_only}
        on_disk = _generated_here(FIXTURES) | _generated_here(MALFORMED_DIR)
        stale = sorted(
            {
                str(p.relative_to(FIXTURES))
                for p in built
                if not p.is_file() or p.read_bytes() != built[p]
            }
            | {str(p.relative_to(FIXTURES)) for p in on_disk - expected}
        )
        print(reading)
        if stale:
            print("STALE: " + ", ".join(stale))
            return 1
        print("CURRENT")
        return 0
    if digest_only:
        raise SystemExit(f"writing needs {GDAL_VERSION} on PATH")
    MALFORMED_DIR.mkdir(exist_ok=True)
    for path, octets in built.items():
        path.write_bytes(octets)
    print(reading)
    print(f"wrote {len(built)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
