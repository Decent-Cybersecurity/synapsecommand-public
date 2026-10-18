#!/usr/bin/env python3
"""Build the grib2 fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py                 # writes every generated file under fixtures/grib2/
    python -I -B build_fixtures.py --check         # builds everything in memory and compares it,
                                                   # byte for byte, with the tree; prints CURRENT
                                                   # and exits 0, or STALE: <names> and exits 1
    python -I -B build_fixtures.py --check --require-gdal
                                                   # the same, and refuses to pass unless GDAL
                                                   # 3.13.3 re-wrote the tool-written messages

Edit this file, never a `.grb2`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/grib2_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Thirteen GRIB2 messages, each `<name>.grb2` with its twin `<name>.parsed.json`, and the refusal
set under `malformed/`. Two writers, neither sharing a line with `adapters/grib2.py`:

- GDAL 3.13.3's GRIB driver writes seven (`GDAL_FIXTURES`): simple packing on a lat/lon and on a
  Lambert conformal grid, complex packing with spatial differencing of orders 1 and 2 (GDAL marks
  a nodata cell with Table 5.5 management 1, which is the only way it can say "missing"), PNG at
  16 and 8 bits and JPEG 2000. It is run from a temporary directory, with relative file names,
  `GDAL_PAM_ENABLED=NO` (no `.aux.xml` beside the output) and nothing else in its environment
  changed, from an ESRI ASCII grid this script writes from its literals. Its parameter is never
  0/0: GDAL converts that field from Celsius to Kelvin on write (research-grib2 T4).
- this script's own ENCODER writes six (`HAND_FIXTURES`), the forms GDAL cannot write: a Section 6
  bitmap (GDAL never writes one; research-grib2 T2), two fields in one message, a zero-width field
  under Product Definition Template 4.8, complex packing with management 0 under a bitmap (the
  HRRR form, gap-grib2-wire-facts F01) and with management 2, and a PNG whose five rows use the five
  PNG filters, under an MRMS-style local parameter whose sentinels are data. Its PNG is written
  with a stored (uncompressed) zlib stream assembled here, so no zlib build can change a byte.

Each twin is written from LITERALS, never by decoding a message: the fields this script encoded,
or for a GDAL message the options it passed GDAL and the packing GDAL chose — read once from
GDAL's octets with the design record's walker (`work/gap-grib2-wire-facts/grib2_walk.py`) on
2026-10-17 and written down in `GDAL_FIXTURES` — with the field's packed octets cut from the
message at the section lengths written down beside them. The summary of each field (count,
missing count, minimum, maximum) is computed here from the grid literals. The twin is the
expectation `tests/test_cdm_grib2_adapter.py` holds the adapter's decode to.

GDAL AND `--check`
------------------
With GDAL 3.13.3 on PATH, `--check` re-runs GDAL and compares its octets with the tree's. Without
it — every CI runner, which carries no GDAL — the seven tool-written messages are checked against
the SHA-256 of each recorded in `GDAL_DIGESTS` (and in the pin), and a line says so; everything
else is rebuilt either way. `--require-gdal` makes the GDAL re-run a condition of passing: that
is the reading the maintainer takes on the named build before a release (DECISIONS U-11). Two
simple-packing GDAL messages are also re-encoded by this script from the literals and must come
out identical to GDAL's, octet for octet: the two writers agree where both can write.

EVERYTHING IS SYNTHETIC. Every grid lies in the Baltic rectangle (56.0-58.5 N, 20.0-24.5 E,
CONTRIBUTING.md, "Identifiers and places in observation fixtures"), every reference time is
2026-04-29T06:00:00Z, and every value is a literal below, not taken from a message.
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
    "Synthetic GRIB2 message written on 2026-10-17 for the grib2 adapter's landing by GDAL 3.13.3's "
    "GRIB driver, run by fixtures/grib2/spec/build_fixtures.py from an ASCII grid of literals in "
    "that script; the grid lies in the Baltic rectangle and nothing is recorded data."
)
ORIGIN_HAND = (
    "Synthetic GRIB2 message written on 2026-10-17 for the grib2 adapter's landing by "
    "fixtures/grib2/spec/build_fixtures.py's own encoder from literals in that script, after the "
    "section layouts of the GRIB2 documentation (cited by reference, never carried); the grid "
    "lies in the Baltic rectangle and nothing is recorded data."
)
ORIGIN_TWIN = (
    "Synthetic parsed twin of a GRIB2 message, written on 2026-10-17 by "
    "fixtures/grib2/spec/build_fixtures.py from the literals the message was written from, never "
    "by decoding it; the grid lies in the Baltic rectangle and nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed GRIB2 message written on 2026-10-17 by "
    "fixtures/grib2/spec/build_fixtures.py, from literals in that script, for the conformance "
    "suite's check H; malformed/README.md names what is wrong with it and the refusal it "
    "expects. Nothing is recorded data."
)

GDAL_VERSION = 'GDAL 3.13.3 "Iowa City", released 2026/08/13'
REFERENCE = (2026, 4, 29, 6, 0, 0)

# -- writing sections ----------------------------------------------------------------------------


def sm(value: int, size: int) -> int:
    """A signed integer as GRIB2 writes it: sign and magnitude, the top bit the sign."""
    top = 1 << (8 * size - 1)
    if abs(value) >= top:
        raise ValueError("magnitude too large for the field")
    return abs(value) | (top if value < 0 else 0)


def section(number: int, body: bytes) -> bytes:
    return struct.pack(">IB", 5 + len(body), number) + body


def message(discipline: int, sections: list[bytes]) -> bytes:
    body = b"".join(sections)
    total = 16 + len(body) + 4
    return (
        b"GRIB" + b"\x00\x00" + bytes((discipline, 2)) + struct.pack(">Q", total) + body + b"7777"
    )


def s1_octets(s1: dict) -> bytes:
    return section(
        1,
        struct.pack(
            ">HHBBBHBBBBBBB",
            s1["centre"],
            s1["subcentre"],
            s1["master_table_version"],
            s1["local_table_version"],
            s1["reference_time_significance"],
            s1["year"],
            s1["month"],
            s1["day"],
            s1["hour"],
            s1["minute"],
            s1["second"],
            s1["production_status"],
            s1["data_type"],
        ),
    )


def s3_octets(grid: dict) -> bytes:
    p = grid["parameters"]
    head = struct.pack(">BIBBH", 0, grid["points"], 0, 0, grid["template"])
    earth = struct.pack(
        ">BBIBIBI",
        p["earth_shape"],
        p["radius_scale_factor"],
        p["radius_scaled_value"],
        p["major_axis_scale_factor"],
        p["major_axis_scaled_value"],
        p["minor_axis_scale_factor"],
        p["minor_axis_scaled_value"],
    )
    if grid["template"] == 0:
        rest = struct.pack(
            ">IIIIIIBIIIIB",
            p["ni"],
            p["nj"],
            p["basic_angle"],
            p["basic_angle_subdivisions"],
            sm(p["la1"], 4),
            p["lo1"],
            p["resolution_flags"],
            sm(p["la2"], 4),
            p["lo2"],
            p["di"],
            p["dj"],
            p["scanning_mode"],
        )
    else:
        rest = struct.pack(
            ">IIIIBIIIIBBIIII",
            p["nx"],
            p["ny"],
            sm(p["la1"], 4),
            p["lo1"],
            p["resolution_flags"],
            sm(p["lad"], 4),
            p["lov"],
            p["dx"],
            p["dy"],
            p["projection_centre"],
            p["scanning_mode"],
            sm(p["latin1"], 4),
            sm(p["latin2"], 4),
            0xFFFFFFFF if p["south_pole_lat"] is None else sm(p["south_pole_lat"], 4),
            p["south_pole_lon"],
        )
    return section(3, head + earth + rest)


def s4_octets(product: dict) -> bytes:
    p = product["parameters"]
    body = struct.pack(
        ">HHBBBBBHBBIBBIBBI",
        0,
        product["template"],
        p["category"],
        p["number"],
        p["generating_process"],
        p["background_process"],
        p["forecast_process"],
        p["cutoff_hours"],
        p["cutoff_minutes"],
        p["time_unit"],
        sm(p["forecast_time"], 4),
        p["surface1_type"],
        sm(p["surface1_scale"], 1),
        sm(p["surface1_value"], 4),
        p["surface2_type"],
        sm(p["surface2_scale"], 1),
        sm(p["surface2_value"], 4),
    )
    if product["template"] == 8:
        body += struct.pack(
            ">HBBBBBBIBBBIBI",
            p["end_year"],
            p["end_month"],
            p["end_day"],
            p["end_hour"],
            p["end_minute"],
            p["end_second"],
            p["time_ranges"],
            p["missing_in_statistical_process"],
            p["statistical_process"],
            p["increment_type"],
            p["range_unit"],
            p["range_length"],
            p["increment_unit"],
            p["increment"],
        )
    return section(4, body)


def s5_octets(representation: dict) -> bytes:
    r = representation["parameters"]
    body = struct.pack(">IH", representation["points"], representation["template"])
    body += struct.pack(
        ">fHHBB",
        r["reference_value"],
        sm(r["binary_scale"], 2),
        sm(r["decimal_scale"], 2),
        r["bits"],
        r["original_type"],
    )
    if representation["template"] == 3:

        def substitute(value):
            if value is None:
                return b"\xff\xff\xff\xff"
            return struct.pack(">f", value) if r["original_type"] == 0 else struct.pack(">I", value)

        body += struct.pack(">BB", r["group_splitting"], r["missing_management"])
        body += substitute(r["primary_missing"]) + substitute(r["secondary_missing"])
        body += struct.pack(
            ">IBBIBIBBB",
            r["groups"],
            r["group_width_reference"],
            r["group_width_bits"],
            r["group_length_reference"],
            r["group_length_increment"],
            r["last_group_length"],
            r["group_length_bits"],
            r["spatial_differencing_order"],
            r["spatial_differencing_octets"],
        )
    if representation["template"] == 40:
        body += struct.pack(">BB", r["compression_type"], r["target_compression_ratio"])
    return section(5, body)


def pack_bits(values: list[int], width: int) -> bytes:
    """Unsigned integers of `width` bits, most significant bit first, padded to an octet."""
    if width == 0:
        return b""
    accumulated = 0
    for value in values:
        if value < 0 or value >= 1 << width:
            raise ValueError("a value does not fit its width")
        accumulated = (accumulated << width) | value
    bits = width * len(values)
    pad = -bits % 8
    return (accumulated << pad).to_bytes((bits + pad) // 8, "big")


def bitmap_octets(present: list[bool]) -> bytes:
    return pack_bits([1 if p else 0 for p in present], 1)


def codes_of(values: list[float], r: dict) -> list[int]:
    """The integers X a writer stores for Y: X = (Y x 10^D - R) x 2^-E, each exact or refused."""
    out = []
    for y in values:
        x = (y * 10 ** r["decimal_scale"] - r["reference_value"]) / 2.0 ** r["binary_scale"]
        if x != int(x) or x < 0:
            raise ValueError("a literal is not exactly representable in the packing chosen")
        out.append(int(x))
    return out


def complex_data(r: dict, points: list, lengths: list[int]) -> tuple[bytes, dict]:
    """Template 7.3 for `points` (an int code, or "primary" / "secondary"), with the group lengths
    given; returns Section 7's data octets and the Section 5 fields the encoding chose."""
    order, size, management = (
        r["spatial_differencing_order"],
        r["spatial_differencing_octets"],
        r["missing_management"],
    )
    known = [p for p in points if isinstance(p, int)]
    diffs = []
    for k, v in enumerate(known):
        if k < order:
            diffs.append(None)
        elif order == 1:
            diffs.append(v - known[k - 1])
        else:
            diffs.append(v - 2 * known[k - 1] + known[k - 2])
    minimum = min(d for d in diffs if d is not None)
    stored = iter([0 if d is None else d - minimum for d in diffs])
    sequence = [next(stored) if isinstance(p, int) else p for p in points]
    head = sm(known[0], size).to_bytes(size, "big")
    if order == 2:
        head += sm(known[1], size).to_bytes(size, "big")
    head += sm(minimum, size).to_bytes(size, "big")
    groups, at = [], 0
    for length in lengths:
        groups.append(sequence[at : at + length])
        at += length
    assert at == len(sequence)
    refs, widths, packed_groups = [], [], []
    for group in groups:
        data = [v for v in group if isinstance(v, int)]
        if management == 1 and "secondary" in group:
            raise ValueError("management 1 has no secondary missing value")
        if not data:
            refs.append(("primary" if "primary" in group else "secondary", None))
            widths.append(0 if len(set(group)) == 1 else 2)
            packed_groups.append(group)
            continue
        # Under management 1 or 2 the top one or two codes of EVERY group's width mean "missing",
        # so a group's data must stay below them whether or not it holds a missing value.
        ref = min(data)
        width = (max(data) - ref + management).bit_length()
        refs.append((ref, width))
        widths.append(width)
        packed_groups.append(group)
    numeric_refs = [ref for ref, _ in refs if isinstance(ref, int)]
    ref_bits = max(max(numeric_refs) + (2 if management else 0), 1).bit_length()
    top_ref = (1 << ref_bits) - 1
    ref_values, value_bits = [], []
    for (ref, width), group in zip(refs, packed_groups):
        if ref == "primary":
            ref_values.append(top_ref if widths[len(ref_values)] == 0 else 0)
        elif ref == "secondary":
            ref_values.append(top_ref - 1 if widths[len(ref_values)] == 0 else 0)
        else:
            ref_values.append(ref)
        w = widths[len(ref_values) - 1]
        base = ref_values[-1] if isinstance(ref, int) else 0
        for v in group:
            if w == 0:
                continue
            if v == "primary":
                value_bits.append(((1 << w) - 1, w))
            elif v == "secondary":
                value_bits.append(((1 << w) - 2, w))
            else:
                value_bits.append((v - base, w))
    width_reference = min(widths)
    width_bits = max(w - width_reference for w in widths).bit_length()
    length_reference = min(lengths[:-1]) if len(lengths) > 1 else lengths[-1]
    length_bits = max((n - length_reference for n in lengths[:-1]), default=0).bit_length()
    stream = 0
    count = 0
    for value, width in value_bits:
        stream = (stream << width) | value
        count += width
    pad = -count % 8
    values_octets = (stream << pad).to_bytes((count + pad) // 8, "big") if count else b""
    data = (
        head
        + pack_bits(ref_values, ref_bits)
        + pack_bits([w - width_reference for w in widths], width_bits)
        + pack_bits([n - length_reference for n in lengths[:-1]] + [0], length_bits)
        + values_octets
    )
    chosen = {
        "bits": ref_bits,
        "groups": len(lengths),
        "group_width_reference": width_reference,
        "group_width_bits": width_bits,
        "group_length_reference": length_reference,
        "group_length_increment": 1,
        "last_group_length": lengths[-1],
        "group_length_bits": length_bits,
    }
    return data, chosen


def zlib_stored(data: bytes) -> bytes:
    """A zlib stream of stored deflate blocks, assembled here so no zlib build can move a byte."""
    out = bytearray(b"\x78\x01")
    blocks = [data[i : i + 65535] for i in range(0, len(data), 65535)] or [b""]
    for index, block in enumerate(blocks):
        out.append(1 if index == len(blocks) - 1 else 0)
        out += struct.pack("<HH", len(block), len(block) ^ 0xFFFF) + block
    out += struct.pack(">I", zlib.adler32(data) & 0xFFFFFFFF)
    return bytes(out)


def png_chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_filter(rows: list[bytes], filters: list[int], step: int) -> bytes:
    """Each row filtered with its own filter type (PNG 1.2 section 9), filter byte first."""
    out = bytearray()
    prior = bytes(len(rows[0]))
    for row, kind in zip(rows, filters):
        line = bytearray()
        for x, value in enumerate(row):
            a = row[x - step] if x >= step else 0
            b = prior[x]
            c = prior[x - step] if x >= step else 0
            if kind == 0:
                predictor = 0
            elif kind == 1:
                predictor = a
            elif kind == 2:
                predictor = b
            elif kind == 3:
                predictor = (a + b) >> 1
            else:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
            line.append((value - predictor) & 0xFF)
        out.append(kind)
        out += line
        prior = row
    return bytes(out)


def png(width: int, height: int, depth: int, codes: list[int], filters: list[int]) -> bytes:
    step = depth // 8
    raw = b"".join(c.to_bytes(step, "big") for c in codes)
    rows = [raw[y * width * step : (y + 1) * width * step] for y in range(height)]
    header = struct.pack(">IIBBBBB", width, height, depth, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", header)
        + png_chunk(b"IDAT", zlib_stored(png_filter(rows, filters, step)))
        + png_chunk(b"IEND", b"")
    )


# -- the literals shared by the set --------------------------------------------------------------


def identification(**over) -> dict:
    s1 = {
        "section_length": 21,
        "centre": 7,
        "subcentre": 0,
        "master_table_version": 2,
        "local_table_version": 0,
        "reference_time_significance": 1,
        "year": 2026,
        "month": 4,
        "day": 29,
        "hour": 6,
        "minute": 0,
        "second": 0,
        "production_status": 0,
        "data_type": 1,
    }
    s1.update(over)
    return s1


def latlon(ni: int, nj: int, west: int, south: int, step: int, **over) -> dict:
    """A lat/lon grid as GDAL writes one from an ASCII grid: the first point is the south-west
    cell's centre, rows run south to north (scanning mode 0x40) and the earth is WGS84 (shape 5)
    with its radius and axes left missing; `west`, `south`, `step` in 10^-6 degree."""
    p = {
        "earth_shape": 5,
        "radius_scale_factor": 255,
        "radius_scaled_value": 0xFFFFFFFF,
        "major_axis_scale_factor": 255,
        "major_axis_scaled_value": 0xFFFFFFFF,
        "minor_axis_scale_factor": 255,
        "minor_axis_scaled_value": 0xFFFFFFFF,
        "ni": ni,
        "nj": nj,
        "basic_angle": 0,
        "basic_angle_subdivisions": 0xFFFFFFFF,
        "la1": south,
        "lo1": west,
        "resolution_flags": 0x30,
        "la2": south + (nj - 1) * step,
        "lo2": west + (ni - 1) * step,
        "di": step,
        "dj": step,
        "scanning_mode": 0x40,
    }
    p.update(over)
    return {
        "section_length": 72,
        "source": 0,
        "points": ni * nj,
        "optional_list_octets": 0,
        "optional_list_interpretation": 0,
        "template": 0,
        "parameters": p,
    }


def product0(category, number, process, unit, forecast, surface, scale, value, **over) -> dict:
    p = {
        "category": category,
        "number": number,
        "generating_process": process,
        "background_process": 255,
        "forecast_process": 0,
        "cutoff_hours": 0,
        "cutoff_minutes": 0,
        "time_unit": unit,
        "forecast_time": forecast,
        "surface1_type": surface,
        "surface1_scale": scale,
        "surface1_value": value,
        "surface2_type": 255,
        "surface2_scale": 0,
        "surface2_value": 0,
    }
    p.update(over)
    return {"section_length": 34, "coordinate_values": 0, "template": 0, "parameters": p}


def representation(template: int, points: int, length: int, **parameters) -> dict:
    return {
        "section_length": length,
        "points": points,
        "template": template,
        "parameters": parameters,
    }


def scaling(reference, binary, decimal, bits, original=0) -> dict:
    return {
        "reference_value": reference,
        "binary_scale": binary,
        "decimal_scale": decimal,
        "bits": bits,
        "original_type": original,
    }


NO_BITMAP = {"section_length": 6, "indicator": 255}


def summary(values: list, sentinels: tuple = ()) -> dict:
    """count, missing count, minimum and maximum of a field's grid literals; None is missing."""
    kept = [v for v in values if v is not None and v not in sentinels]
    return {
        "count": len(values),
        "missing_count": len(values) - len(kept),
        "min": min(kept) if kept else None,
        "max": max(kept) if kept else None,
    }


def stored_order(rows_north_first: list[list]) -> list:
    """An ASCII grid's rows (north first) in the order GDAL's scanning mode 0x40 stores them."""
    return [v for row in reversed(rows_north_first) for v in row]


# -- the GDAL-written seven ----------------------------------------------------------------------

W3x2 = [[1.5, 2.25, 3.125], [4.0, 5.5, 6.75]]
VIS3x2 = [[1000.0, 1100.0, 1200.0], [1250.0, 1255.0, 1003.0]]
G8 = [
    [10.0 + 0.5 * i + 0.25 * j + ((i * 7 + j * 3) % 5) * 0.125 for i in range(8)] for j in range(8)
]
G8_NODATA = [
    [None if (i + j) % 7 == 0 else v for i, v in enumerate(row)] for j, row in enumerate(G8)
]

UGRD_10M = product0(2, 2, 2, 1, 1, 103, 0, 10)
RH_2M = product0(1, 1, 0, 1, 0, 103, 0, 2)
VIS_SFC = product0(19, 0, 0, 1, 0, 1, 0, 0)

#: (section 7 length, the ASCII grid, the GDAL options, and the twin's literals). The Section 5
#: parameters are what GDAL chose: R, E, D and the group layout read from its octets.
GDAL_FIXTURES = {
    "simple_packing_latlon": {
        "grid_rows": W3x2,
        "corner": (21.0, 57.0, 0.25),
        "type": 1,
        "pds": "2 2 2 255 0 0 0 1 1 103 0 10 255 0 0",
        "options": ["NBITS=16", "DECIMAL_SCALE_FACTOR=3", "DATA_ENCODING=SIMPLE_PACKING"],
        "grid": latlon(3, 2, 21_125_000, 57_125_000, 250_000),
        "product": UGRD_10M,
        "representation": representation(0, 6, 21, **scaling(1500.0, -3, 3, 16)),
        "data_length": 17,
    },
    "png_16_bit": {
        "grid_rows": W3x2,
        "corner": (21.0, 57.0, 0.25),
        "type": 1,
        "pds": "2 2 2 255 0 0 0 1 1 103 0 10 255 0 0",
        "options": ["NBITS=16", "DECIMAL_SCALE_FACTOR=3", "DATA_ENCODING=PNG"],
        "grid": latlon(3, 2, 21_125_000, 57_125_000, 250_000),
        "product": UGRD_10M,
        "representation": representation(41, 6, 21, **scaling(1500.0, -3, 3, 16)),
        "data_length": 84,
    },
    "jpeg2000_reference_form": {
        "grid_rows": W3x2,
        "corner": (21.0, 57.0, 0.25),
        "type": 1,
        "pds": "2 2 2 255 0 0 0 1 1 103 0 10 255 0 0",
        "options": ["NBITS=16", "DECIMAL_SCALE_FACTOR=3", "DATA_ENCODING=JPEG2000"],
        "grid": latlon(3, 2, 21_125_000, 57_125_000, 250_000),
        "product": UGRD_10M,
        "representation": representation(
            40,
            6,
            23,
            **scaling(1500.0, -3, 3, 16),
            compression_type=0,
            target_compression_ratio=255,
        ),
        "data_length": 165,
    },
    "png_8_bit": {
        "grid_rows": VIS3x2,
        "corner": (20.5, 56.5, 0.25),
        "type": 0,
        "pds": "19 0 0 255 0 0 0 1 0 1 0 0 255 0 0",
        "options": ["NBITS=8", "DECIMAL_SCALE_FACTOR=0", "DATA_ENCODING=PNG"],
        "grid": latlon(3, 2, 20_625_000, 56_625_000, 250_000),
        "product": VIS_SFC,
        "representation": representation(41, 6, 21, **scaling(1000.0, 0, 0, 8)),
        "data_length": 78,
    },
    "complex_order_1": {
        "grid_rows": G8,
        "corner": (22.0, 57.5, 0.01),
        "type": 0,
        "pds": "1 1 0 255 0 0 0 1 0 103 0 2 255 0 0",
        "options": [
            "NBITS=16",
            "DECIMAL_SCALE_FACTOR=3",
            "DATA_ENCODING=COMPLEX_PACKING",
            "SPATIAL_DIFFERENCING_ORDER=1",
        ],
        "grid": latlon(8, 8, 22_005_000, 57_505_000, 10_000),
        "product": RH_2M,
        "representation": representation(
            3,
            64,
            49,
            **scaling(10000.0, -3, 3, 16),
            group_splitting=1,
            missing_management=1,
            groups=2,
            group_width_reference=13,
            group_width_bits=2,
            group_length_reference=57,
            group_length_increment=1,
            last_group_length=7,
            group_length_bits=0,
            spatial_differencing_order=1,
            spatial_differencing_octets=2,
            primary_missing=-9999.0,
            secondary_missing=None,
        ),
        "data_length": 140,
    },
    "complex_order_2_missing": {
        "grid_rows": G8_NODATA,
        "corner": (22.0, 57.5, 0.01),
        "type": 0,
        "pds": "1 1 0 255 0 0 0 1 0 103 0 2 255 0 0",
        "options": [
            "NBITS=16",
            "DECIMAL_SCALE_FACTOR=3",
            "DATA_ENCODING=COMPLEX_PACKING",
            "SPATIAL_DIFFERENCING_ORDER=2",
        ],
        "nodata": True,
        "grid": latlon(8, 8, 22_005_000, 57_505_000, 10_000),
        "product": RH_2M,
        "representation": representation(
            3,
            64,
            49,
            **scaling(10625.0, -3, 3, 14),
            group_splitting=1,
            missing_management=1,
            groups=5,
            group_width_reference=16,
            group_width_bits=1,
            group_length_reference=2,
            group_length_increment=1,
            last_group_length=22,
            group_length_bits=4,
            spatial_differencing_order=2,
            spatial_differencing_octets=3,
            primary_missing=-9999.0,
            secondary_missing=None,
        ),
        "data_length": 158,
    },
    "lambert_conformal_simple": {
        "grid_rows": W3x2,
        "lambert": (
            "+proj=lcc +lat_1=57 +lat_2=57 +lat_0=57 +lon_0=22 +R=6371229 +units=m +no_defs",
            ("0", "6000", "9000", "0"),
        ),
        "type": 1,
        "pds": "2 2 2 255 0 0 0 1 1 103 0 10 255 0 0",
        "options": ["NBITS=16", "DECIMAL_SCALE_FACTOR=3", "DATA_ENCODING=SIMPLE_PACKING"],
        # GDAL's PROJ put the first point (the south-west cell's centre, 1500 m east and 1000 m
        # north of the projection's origin) at 57.013487 N, 22.024776 E; the rest are literals
        # GDAL wrote from the options: a sphere of 6,371,229 m stated as shape 1, 3 km cells.
        "grid": {
            "section_length": 81,
            "source": 0,
            "points": 6,
            "optional_list_octets": 0,
            "optional_list_interpretation": 0,
            "template": 30,
            "parameters": {
                "earth_shape": 1,
                "radius_scale_factor": 2,
                "radius_scaled_value": 637_122_900,
                "major_axis_scale_factor": 255,
                "major_axis_scaled_value": 0xFFFFFFFF,
                "minor_axis_scale_factor": 255,
                "minor_axis_scaled_value": 0xFFFFFFFF,
                "nx": 3,
                "ny": 2,
                "la1": 57_013_487,
                "lo1": 22_024_776,
                "resolution_flags": 0,
                "lad": 57_000_000,
                "lov": 22_000_000,
                "dx": 3_000_000,
                "dy": 3_000_000,
                "projection_centre": 0,
                "scanning_mode": 0x40,
                "latin1": 57_000_000,
                "latin2": 57_000_000,
                "south_pole_lat": None,
                "south_pole_lon": 0xFFFFFFFF,
            },
        },
        "product": UGRD_10M,
        "representation": representation(0, 6, 21, **scaling(1500.0, -3, 3, 16)),
        "data_length": 17,
    },
}

#: The SHA-256 of each GDAL-written message as GDAL 3.13.3 wrote it on 2026-10-17 (twice, the
#: same octets both times). Without GDAL, `--check` holds the tree to these.
GDAL_DIGESTS = {
    "simple_packing_latlon": "2fe1a492187532dc2f96e0e79908aaf14964b9cbc0271452f3415e5fe8078e6e",
    "png_16_bit": "2fc1630cfd36f2ddb67480b5a3ec207321a2a7771d4d9c23c044659cd9634e82",
    "jpeg2000_reference_form": "e25439c1df5f8efb9e83c1f6186224e989e3f9a0d0cf29913b78eeee43a09db9",
    "png_8_bit": "bd1e5c1cbccc6efdb73579229a1a0b997aa0c2a070155c01c72433f3c4b123b6",
    "complex_order_1": "4cdede0b9167b0e2f1f990a655afc9e640345b6043d35ee2c7770b3f2a25b3bc",
    "complex_order_2_missing": "b953e40ac675c49ef2e567b3593f11bd35083d3c8000e6fdb325eb19a495b5bb",
    "lambert_conformal_simple": "a4e138bb97ad3b3621fd5617cd393bba50e7a2eca534af5933d1ea73992c91c6",
}


def ascii_grid(rows: list[list], west: float, south: float, cell: float) -> str:
    lines = [
        f"ncols {len(rows[0])}",
        f"nrows {len(rows)}",
        f"xllcorner {west!r}",
        f"yllcorner {south!r}",
        f"cellsize {cell!r}",
        "NODATA_value -9999",
    ]
    lines += [" ".join("-9999" if v is None else repr(v) for v in row) for row in rows]
    return "\n".join(lines) + "\n"


def sha256(octets: bytes) -> str:
    """The package's one content digest (`evidence.digest_bytes`): this package imports no
    hashing module anywhere else (tests/test_cdm_boundary.py), and the geopackage builder takes
    its digests the same way."""
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
    """One GDAL-written message, from a temporary directory with relative file names."""
    spec = GDAL_FIXTURES[name]
    env = {**os.environ, "GDAL_PAM_ENABLED": "NO"}
    ids = [
        "IDS_CENTER=7",
        "IDS_SUBCENTER=0",
        "IDS_MASTER_TABLE=2",
        "IDS_SIGNF_REF_TIME=1",
        "IDS_REF_TIME=2026-04-29T06:00:00Z",
        "IDS_PROD_STATUS=0",
        f"IDS_TYPE={spec['type']}",
        "DISCIPLINE=0",
        "PDS_PDTN=0",
        f"PDS_TEMPLATE_ASSEMBLED_VALUES={spec['pds']}",
        *spec["options"],
    ]
    creation = [arg for option in ids for arg in ("-co", option)]
    with tempfile.TemporaryDirectory() as tmp:
        west, south, cell = spec.get("corner", (21.0, 57.0, 0.25))
        pathlib.Path(tmp, "source.asc").write_text(ascii_grid(spec["grid_rows"], west, south, cell))
        source, srs = "source.asc", ["-a_srs", "EPSG:4326"]
        if "lambert" in spec:
            proj, corners = spec["lambert"]
            run(
                ["gdal_translate", "-q", "-of", "GTiff", "-ot", "Float32", "-a_srs", proj]
                + ["-a_ullr", *corners, "source.asc", "source.tif"],
                tmp,
                env,
            )
            source, srs = "source.tif", []
        nodata = ["-a_nodata", "-9999"] if spec.get("nodata") else []
        run(
            ["gdal_translate", "-q", "-of", "GRIB", "-ot", "Float32", *srs, *nodata, *creation]
            + [source, "out.grb2"],
            tmp,
            env,
        )
        return pathlib.Path(tmp, "out.grb2").read_bytes()


def run(argv: list[str], cwd: str, env: dict) -> None:
    done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if done.returncode != 0 or done.stderr.strip():
        raise RuntimeError(f"{argv[0]} failed: {done.stderr.strip()}")


def cut_sections(octets: bytes) -> list[tuple[int, bytes]]:
    """(number, section octets) of every section, cut at the lengths the message states. Framing
    only: no field of a section is read."""
    out, position = [], 16
    while position < len(octets) - 4:
        length = int.from_bytes(octets[position : position + 4], "big")
        out.append((octets[position + 4], octets[position : position + length]))
        position += length
    return out


def gdal_twin(name: str, octets: bytes) -> dict:
    spec = GDAL_FIXTURES[name]
    s1 = identification(data_type=spec["type"])
    sections = cut_sections(octets)
    numbers = [n for n, _ in sections]
    if numbers != [1, 2, 3, 4, 5, 6, 7]:
        raise RuntimeError(f"{name}: GDAL wrote sections {numbers}")
    lengths = {n: len(body) for n, body in sections}
    expected = {
        1: 21,
        2: 5,
        3: spec["grid"]["section_length"],
        4: spec["product"]["section_length"],
        5: spec["representation"]["section_length"],
        6: 6,
        7: spec["data_length"],
    }
    if lengths != expected:
        raise RuntimeError(f"{name}: GDAL's section lengths are not the literals")
    data = dict(sections)[7][5:]
    template = spec["representation"]["template"]
    values = stored_order(spec["grid_rows"])
    return {
        "wire_hex": octets.hex(),
        "indicator": {"discipline": 0, "edition": 2, "total_length": len(octets)},
        "identification": s1,
        "local_use": {"section_length": 5, "octets_hex": ""},
        "fields": [
            {
                "grid": spec["grid"],
                "product": spec["product"],
                "representation": spec["representation"],
                "bitmap": NO_BITMAP,
                "data": {"section_length": spec["data_length"]},
            }
        ],
        "summaries": [None if template == 40 else summary(values)],
        "arrays": [{"bitmap_hex": None, "packed_hex": None if template == 40 else data.hex()}],
        "codestreams": [data.hex() if template == 40 else None],
    }


def gdal_reencoded(name: str) -> bytes:
    """A simple-packing GDAL message written again by this script's encoder from the literals."""
    spec = GDAL_FIXTURES[name]
    r = spec["representation"]
    codes = codes_of(stored_order(spec["grid_rows"]), r["parameters"])
    return message(
        0,
        [
            s1_octets(identification(data_type=spec["type"])),
            section(2, b""),
            s3_octets(spec["grid"]),
            s4_octets(spec["product"]),
            s5_octets(r),
            section(6, b"\xff"),
            section(7, pack_bits(codes, r["parameters"]["bits"])),
        ],
    )


# -- the hand-written six ------------------------------------------------------------------------


def hand(
    s1: dict,
    grid: dict,
    fields: list[dict],
    *,
    discipline: int = 0,
    local: bytes | None = None,
) -> tuple[bytes, dict]:
    """Encode one message and write its twin from the same literals.

    Each field is {product, representation, bitmap (list of bools or None), data (octets),
    values (grid literals, None for a point the bitmap leaves out or management marks),
    sentinels}."""
    sections = [s1_octets(s1)]
    if local is not None:
        sections.append(section(2, local))
    sections.append(s3_octets(grid))
    twin_fields, summaries, arrays, codestreams = [], [], [], []
    for field in fields:
        bitmap = field.get("bitmap")
        if bitmap is None:
            s6 = section(6, b"\xff")
            bitmap_state = NO_BITMAP
        else:
            s6 = section(6, b"\x00" + bitmap_octets(bitmap))
            bitmap_state = {"section_length": len(s6), "indicator": 0}
        s7 = section(7, field["data"])
        sections += [s4_octets(field["product"]), s5_octets(field["representation"]), s6, s7]
        twin_fields.append(
            {
                "grid": grid,
                "product": field["product"],
                "representation": field["representation"],
                "bitmap": bitmap_state,
                "data": {"section_length": len(s7)},
            }
        )
        summaries.append(summary(field["values"], field.get("sentinels", ())))
        arrays.append(
            {
                "bitmap_hex": None if bitmap is None else bitmap_octets(bitmap).hex(),
                "packed_hex": field["data"].hex(),
            }
        )
        codestreams.append(None)
    octets = message(discipline, sections)
    return octets, {
        "wire_hex": octets.hex(),
        "indicator": {"discipline": discipline, "edition": 2, "total_length": len(octets)},
        "identification": s1,
        "local_use": None
        if local is None
        else {"section_length": 5 + len(local), "octets_hex": local.hex()},
        "fields": twin_fields,
        "summaries": summaries,
        "arrays": arrays,
        "codestreams": codestreams,
    }


def simple_field(product, values, r, *, bitmap=None, sentinels=()) -> dict:
    present = [v for v in values if v is not None]
    rep = representation(0, len(present), 21, **r)
    data = pack_bits(codes_of(present, r), r["bits"])
    return {
        "product": product,
        "representation": rep,
        "bitmap": bitmap,
        "data": data,
        "values": values,
        "sentinels": sentinels,
    }


def complex_field(product, values, r, lengths, *, bitmap=None) -> dict:
    """`values` per grid point: a number, None (the bitmap leaves it out), or "primary" /
    "secondary" (a point Table 5.5 marks missing)."""
    points = []
    for present, value in zip(bitmap or [True] * len(values), values):
        if not present:
            continue
        points.append(value if isinstance(value, str) else codes_of([value], r)[0])
    data, chosen = complex_data(r, points, lengths)
    parameters = {**r, **chosen}
    rep = representation(3, len(points), 49, **parameters)
    return {
        "product": product,
        "representation": rep,
        "bitmap": bitmap,
        "data": data,
        "values": [None if isinstance(v, str) else v for v in values],
    }


#: A visibility field on a 4 x 3 grid with a Section 6 bitmap: three points have no value.
BITMAP_VALUES = [
    1500.0,
    2400.0,
    None,
    9000.0,
    None,
    4000.0,
    4100.0,
    4200.0,
    7000.0,
    None,
    300.0,
    15000.0,
]

#: Relative humidity on a 5 x 4 grid, complex packing of order 2 with management 0 under a
#: bitmap that leaves four points out: the HRRR form.
HRRR_FORM_VALUES = [
    61.5, 62.0, 62.5, None, 64.0,
    60.0, None, 61.0, 61.5, 63.5,
    58.5, 59.0, 59.0, 59.5, None,
    None, 57.0, 56.5, 56.0, 55.5,
]  # fmt: skip

#: A v-component of wind on a 4 x 4 grid, complex packing of order 1 with management 2: a group
#: wholly primary-missing, a group wholly secondary-missing and groups that mix both with values.
MANAGEMENT_2_VALUES = [
    3.5, 4.0, "primary", 4.5,
    "primary", "primary", "primary", "primary",
    5.0, "secondary", 5.5, 6.0,
    "secondary", "secondary", "secondary", "secondary",
]  # fmt: skip

#: An MRMS-style 1-hour QPE on a 4 x 5 grid: -1 is "Missing" and -3 "No Coverage" in the local
#: table, written as data, and each of the five PNG rows uses another filter.
QPE_VALUES = [
    0.0, 2.5, 12.7, -1.0,
    0.5, 0.5, 3.0, 4.5,
    -3.0, -3.0, 1.0, 0.0,
    7.5, 25.0, 6.2, -1.0,
    0.0, 0.1, 0.2, 0.4,
]  # fmt: skip


def hand_fixtures() -> dict[str, tuple[bytes, dict]]:
    out = {}
    vis_sfc = product0(19, 0, 0, 1, 0, 1, 0, 0)
    out["bitmap_simple_packing"] = hand(
        identification(data_type=0),
        latlon(4, 3, 23_000_000, 58_000_000, 250_000),
        [
            simple_field(
                vis_sfc,
                BITMAP_VALUES,
                scaling(300.0, 0, 0, 14),
                bitmap=[v is not None for v in BITMAP_VALUES],
            )
        ],
    )
    wind = latlon(3, 3, 20_500_000, 56_250_000, 500_000)
    ugrd = product0(2, 2, 2, 1, 2, 100, 0, 10000)
    vgrd = product0(2, 3, 2, 1, 2, 100, 0, 10000)
    out["two_fields_one_message"] = hand(
        identification(),
        wind,
        [
            simple_field(
                ugrd, [-4.0, -3.5, -3.0, -2.5, -2.0, -1.5, -1.0, -0.5, 0.0], scaling(-40.0, 0, 1, 6)
            ),
            simple_field(
                vgrd, [12.5, 12.0, 11.5, 11.0, 10.5, 10.0, 9.5, 9.0, 8.5], scaling(85.0, 0, 1, 6)
            ),
        ],
    )
    apcp = {
        "section_length": 58,
        "coordinate_values": 0,
        "template": 8,
        "parameters": {
            **product0(1, 8, 2, 1, 0, 1, 0, 0)["parameters"],
            "end_year": 2026,
            "end_month": 4,
            "end_day": 29,
            "end_hour": 7,
            "end_minute": 0,
            "end_second": 0,
            "time_ranges": 1,
            "missing_in_statistical_process": 0,
            "statistical_process": 1,
            "increment_type": 2,
            "range_unit": 1,
            "range_length": 1,
            "increment_unit": 255,
            "increment": 0,
        },
    }
    out["zero_width_accumulation"] = hand(
        identification(),
        latlon(3, 2, 24_000_000, 56_000_000, 250_000),
        [simple_field(apcp, [0.0] * 6, scaling(0.0, 0, 0, 0))],
    )
    out["complex_order_2_with_bitmap"] = hand(
        identification(data_type=0),
        latlon(5, 4, 20_000_000, 57_750_000, 100_000),
        [
            complex_field(
                RH_2M,
                HRRR_FORM_VALUES,
                {
                    **scaling(550.0, 0, 1, 0),
                    "group_splitting": 1,
                    "missing_management": 0,
                    "primary_missing": None,
                    "secondary_missing": None,
                    "spatial_differencing_order": 2,
                    "spatial_differencing_octets": 2,
                },
                [5, 5, 6],
                bitmap=[v is not None for v in HRRR_FORM_VALUES],
            )
        ],
    )
    out["complex_order_1_primary_and_secondary_missing"] = hand(
        identification(),
        latlon(4, 4, 21_500_000, 56_500_000, 250_000),
        [
            complex_field(
                product0(2, 3, 2, 1, 1, 103, 0, 10),
                MANAGEMENT_2_VALUES,
                {
                    **scaling(35.0, 0, 1, 0),
                    "group_splitting": 1,
                    "missing_management": 2,
                    "primary_missing": 9999.0,
                    "secondary_missing": -9999.0,
                    "spatial_differencing_order": 1,
                    "spatial_differencing_octets": 1,
                },
                [4, 4, 4, 4],
            )
        ],
    )
    qpe_r = scaling(-30.0, 0, 1, 16)
    qpe_codes = codes_of(QPE_VALUES, qpe_r)
    out["mrms_style_png_sentinels"] = hand(
        identification(
            centre=161,
            master_table_version=255,
            local_table_version=1,
            reference_time_significance=3,
            data_type=7,
        ),
        latlon(4, 5, 22_500_000, 58_000_000, 10_000),
        [
            {
                "product": product0(6, 37, 0, 0, 0, 102, 0, 0),
                "representation": representation(41, 20, 21, **qpe_r),
                "bitmap": None,
                "data": png(4, 5, 16, qpe_codes, [1, 2, 3, 4, 0]),
                "values": QPE_VALUES,
                "sentinels": (-1.0, -3.0),
            }
        ],
        discipline=209,
    )
    return out


# -- the refusal set -----------------------------------------------------------------------------


def malformed(hands: dict) -> dict[str, bytes]:
    two = hands["two_fields_one_message"][0]
    bitmap = hands["bitmap_simple_packing"][0]
    qpe = hands["mrms_style_png_sentinels"][0]
    out = {}
    out["truncated_message"] = two[:-30]
    out["total_length_short_of_the_payload"] = two[:8] + struct.pack(">Q", len(two) - 4) + two[16:]
    out["missing_end_section"] = two[:-4] + b"7778"
    out["grib_edition_1"] = two[:7] + b"\x01" + two[8:]
    # The first Section 5 of the two-field message, its template number made 4 (IEEE): octets
    # 10-11 of the section, at 16 + 21 + 72 + 34 into the message.
    at = 16 + 21 + 72 + 34
    out["unknown_packing_template"] = two[: at + 9] + b"\x00\x04" + two[at + 11 :]
    # One more bit set in the bitmap: ten points marked where Section 5 counts nine.
    at = 16 + 21 + 72 + 34 + 21 + 6
    out["bitmap_count_disagrees"] = bitmap[:at] + bytes((bitmap[at] | 0x20,)) + bitmap[at + 1 :]
    # The PNG's IDAT CRC with its last octet flipped.
    idat = qpe.index(b"IDAT")
    crc_end = idat + 4 + int.from_bytes(qpe[idat - 4 : idat], "big") + 4
    out["png_crc_failure"] = qpe[: crc_end - 1] + bytes((qpe[crc_end - 1] ^ 0xFF,)) + qpe[crc_end:]
    out["png_rows_past_the_decompression_bound"] = _big_png()
    out["png_data_past_its_rows"] = _png_message(
        4, 5, png_chunk(b"IDAT", zlib_stored(png_filter([b"\x00" * 8] * 5, [0] * 5, 2) + b"\x00"))
    )
    out["grid_template_32769"] = _grid_template(two, 32769)
    out["repeated_grid_section"] = _repeated_grid(two)
    return out


def _png_message(ni: int, nj: int, idat: bytes, depth: int = 16) -> bytes:
    """A one-field 5.41 message whose PNG has the given IDAT chunk."""
    header = struct.pack(">IIBBBBB", ni, nj, depth, 0, 0, 0, 0)
    stream = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + idat + png_chunk(b"IEND", b"")
    return message(
        209,
        [
            s1_octets(identification(centre=161, data_type=7, reference_time_significance=3)),
            s3_octets(latlon(ni, nj, 22_500_000, 58_000_000, 1)),
            s4_octets(product0(6, 37, 0, 0, 0, 102, 0, 0)),
            s5_octets(representation(41, ni * nj, 21, **scaling(-30.0, 0, 1, depth))),
            section(6, b"\xff"),
            section(7, stream),
        ],
    )


def _big_png() -> bytes:
    """8192 x 4096 points of 16 bits: 33,554,432 points, MAX_GRID_POINTS exactly, whose rows,
    4096 x (1 + 16384) = 67,112,960 octets, are past max_decompressed_bytes (67,108,864). The IDAT
    is a few octets: the refusal comes before any is inflated."""
    return _png_message(8192, 4096, png_chunk(b"IDAT", zlib_stored(b"\x00" * 16)))


def _grid_template(octets: bytes, template: int) -> bytes:
    at = 16 + 21
    return octets[: at + 12] + struct.pack(">H", template) + octets[at + 14 :]


def _repeated_grid(octets: bytes) -> bytes:
    """Section 3 written again after the first field's Section 7."""
    sections = cut_sections(octets)
    grid = dict(sections)[3]
    body, inserted = b"", False
    for number, chunk in sections:
        body += chunk
        if number == 7 and not inserted:
            body += grid
            inserted = True
    return message(octets[6], [body])


# -- writing -------------------------------------------------------------------------------------


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
                "standard_ref": "grib2/spec/grib2_pin.json",
                "synthetic": True,
            }
            for name, origin in sorted(rows)
        ],
        "schema_id": "synapse.fixture-provenance/v1",
    }
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build(require_gdal: bool = False) -> tuple[dict[pathlib.Path, bytes], dict[str, str], str]:
    """(path -> octets for every file this script writes, name -> digest for the GDAL messages to
    check against the tree when GDAL is absent, a line saying which reading was taken)."""
    out: dict[pathlib.Path, bytes] = {}
    rows: list[tuple[str, str]] = []
    digest_only: dict[str, str] = {}
    have_gdal = gdal_available()
    if require_gdal and not have_gdal:
        raise SystemExit(f"--require-gdal: {GDAL_VERSION} is not the gdal_translate on PATH")
    for name in GDAL_FIXTURES:
        path = FIXTURES / f"{name}.grb2"
        if have_gdal:
            octets = gdal_write(name)
            out[path] = octets
        else:
            octets = path.read_bytes() if path.is_file() else b""
            digest_only[name] = GDAL_DIGESTS[name]
        if sha256(octets) != GDAL_DIGESTS[name]:
            raise SystemExit(f"STALE: {name}.grb2 is not the message GDAL_DIGESTS records")
        if (
            GDAL_FIXTURES[name]["representation"]["template"] == 0
            and gdal_reencoded(name) != octets
        ):
            raise SystemExit(f"STALE: {name}.grb2 is not what this script's encoder writes")
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(gdal_twin(name, octets))
        rows += [(f"{name}.grb2", ORIGIN_GDAL), (f"{name}.parsed.json", ORIGIN_TWIN)]
    hands = hand_fixtures()
    for name, (octets, twin) in hands.items():
        out[FIXTURES / f"{name}.grb2"] = octets
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(twin)
        rows += [(f"{name}.grb2", ORIGIN_HAND), (f"{name}.parsed.json", ORIGIN_TWIN)]
    out[FIXTURES / "PROVENANCE.json"] = provenance("grib2", rows)
    bad = malformed(hands)
    for name, octets in bad.items():
        out[MALFORMED_DIR / f"{name}.grb2"] = octets
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "grib2/malformed", [(f"{name}.grb2", MALFORMED_ORIGIN) for name in bad]
    )
    reading = (
        f"GDAL: {GDAL_VERSION} re-wrote the {len(GDAL_FIXTURES)} tool-written messages"
        if have_gdal
        else f"GDAL: {GDAL_VERSION} is not on PATH; the {len(GDAL_FIXTURES)} tool-written "
        "messages were checked against their recorded SHA-256"
    )
    return out, digest_only, reading


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    if not directory.is_dir():
        return set()
    return {
        p
        for p in directory.iterdir()
        if p.is_file()
        and (p.suffix == ".grb2" or p.name.endswith(".parsed.json") or p.name == "PROVENANCE.json")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument(
        "--require-gdal", action="store_true", help="fail unless GDAL 3.13.3 re-writes its seven"
    )
    args = parser.parse_args(argv)
    built, digest_only, reading = build(args.require_gdal)
    if args.check:
        expected = set(built) | {FIXTURES / f"{name}.grb2" for name in digest_only}
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
