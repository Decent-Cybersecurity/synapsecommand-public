#!/usr/bin/env python3
"""Build the iem_n0q fixture set. THE SOURCE OF TRUTH FOR EVERY GENERATED FILE HERE.

    python -I -B build_fixtures.py             # writes every generated file under fixtures/iem_n0q/
    python -I -B build_fixtures.py --check     # builds everything in memory and compares it, byte
                                               # for byte, with the tree; prints CURRENT and exits
                                               # 0, or STALE: <names> and exits 1

Edit this file, never a `.png`, a twin or a provenance record. `README.md` beside the payloads,
`malformed/README.md` and `spec/iem_n0q_pin.json` are the hand-written files of the set, and
`golden/` is the harness's.

WHAT THIS BUILDS, AND FROM WHAT
-------------------------------
Four payloads, each `<name>.png` with its twin `<name>.parsed.json`, and the refusal set under
`malformed/`. Every PNG is written by this script alone, in pure Python, at the IEM N0Q product's
real size — 12200 x 5400 cells of 8-bit palette indices (research-raster F1) — and shares not a
line with `adapters/iem_n0q.py` or `adapters/raster_codec.py`:

- the image is a description, not an array: every row is index 0 (missing) and filter type 0
  unless `rows` names it, and a named row states its PNG filter type and its non-zero cells;
- the filtered scanlines are encoded by THIS SCRIPT's own DEFLATE writer (`deflate_runs`), never
  by `zlib.compress`: a zlib build is free to choose other matches at the same level, and a
  `--check` that compared one machine's compressor with another's would fail on a byte nobody
  changed (the reason `grib2`'s builder writes a stored stream, D-R5-19). A stored stream of
  65,885,400 octets would be past the adapter's 8 MiB input bound, so the writer emits ONE
  dynamic-Huffman block whose code is fixed here: the length symbol 285 (a 258-octet match) has
  a one-bit code, the distance alphabet one one-bit code (distance 1), every literal and the end
  of the block nine or ten bits. A run of one octet value is a literal and then 258-octet copies
  of the octet before; 65,885,400 octets of index 0 come to about 64 KB, the most DEFLATE can do;
- each filter type is applied by `filter_row`, the PNG Third Edition's definitions written out
  again (none, Sub, Up, Average, Paeth), from the row and the row above.

`zlib` is used for two things only: the CRC-32 every chunk carries and the Adler-32 that closes
the zlib stream, both checksums the PNG and zlib specifications define; and, once a payload is
written, `zlib.decompress` reads every correct stream back and the build stops unless it is
exactly the scanlines described — an independent inflater holding this writer to RFC 1950/1951.

Each twin is written from the DESCRIPTION, never by decoding a payload: the IHDR fields it was
given, its palette, its ancillary chunks as this script wrote them (a `tEXt` chunk as its keyword
and text, any other as its octets in hexadecimal), and `index_summary` — the count of cells, the
count of index-0 cells, and the least and greatest non-zero index — counted from the named rows.
The twin is the expectation `tests/test_cdm_iem_n0q_adapter.py` holds the adapter's decode to.

EVERYTHING IS SYNTHETIC. No IEM file, and no value read from one, is used: the palette is a ramp
written below, the cells are literals below, and every `gentime` text is a synthetic stamp on
2026-04-29, before the five-minute slot (06:05Z) the packaged fixtures are translated under. A
PNG states no place and no slot; the footprint the adapter states is its product constant.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys
import zlib

HERE = pathlib.Path(__file__).resolve().parent
FIXTURES = HERE.parent
MALFORMED_DIR = FIXTURES / "malformed"

ORIGIN_PNG = (
    "Synthetic 12200 x 5400 indexed-colour PNG written on 2026-10-17 for the iem_n0q adapter's "
    "landing by fixtures/iem_n0q/spec/build_fixtures.py, in pure Python from literal cells, a "
    "literal palette ramp and literal chunks; no IEM file or value is used and nothing is "
    "recorded data."
)
ORIGIN_TWIN = (
    "Synthetic parsed twin of an iem_n0q fixture, written on 2026-10-17 by "
    "fixtures/iem_n0q/spec/build_fixtures.py from the description the PNG was written from, "
    "never by decoding it; nothing is recorded data."
)
MALFORMED_ORIGIN = (
    "Synthetic malformed payload written on 2026-10-17 by fixtures/iem_n0q/spec/build_fixtures.py "
    "from literals in that script, for the conformance suite's check H; malformed/README.md names "
    "what is wrong with it and the refusal it expects. Nothing is recorded data."
)

SIGNATURE = b"\x89PNG\r\n\x1a\n"
#: The IEM N0Q product's image (research-raster F1): 12200 x 5400 cells, 8-bit indexed colour.
WIDTH = 12200
HEIGHT = 5400

# -- the DEFLATE writer (RFC 1951) -----------------------------------------------------------------

#: Code lengths of the literal/length alphabet: 0..254 nine bits, 255 and 256 (the end of the
#: block) ten bits, 285 (length 258) one bit, 257..284 unused. 1/2 + 255/512 + 2/1024 = 1: a
#: complete code, which inflate requires of this alphabet.
LITLEN_LENGTHS = [9] * 255 + [10, 10] + [0] * 28 + [1]
#: One distance code, distance 1, of length 1: the single-code case RFC 1951 section 3.2.7 allows.
DIST_LENGTHS = [1]
#: The code-length alphabet's order of transmission (RFC 1951 section 3.2.7).
CL_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)
#: The code lengths this block transmits are 0, 1, 9 and 10, each with a two-bit code.
CL_LENGTHS = {0: 2, 1: 2, 9: 2, 10: 2}
MAX_MATCH = 258


def canonical_codes(lengths: list[int] | dict[int, int]) -> dict[int, tuple[int, int]]:
    """symbol -> (code, length): RFC 1951 section 3.2.2's canonical Huffman assignment."""
    pairs = dict(enumerate(lengths)) if isinstance(lengths, list) else dict(lengths)
    longest = max(pairs.values())
    count = [0] * (longest + 1)
    for length in pairs.values():
        if length:
            count[length] += 1
    nxt, code = [0] * (longest + 2), 0
    for bits in range(1, longest + 1):
        code = (code + count[bits - 1]) << 1
        nxt[bits] = code
    codes = {}
    for symbol in sorted(pairs):
        length = pairs[symbol]
        if length:
            codes[symbol] = (nxt[length], length)
            nxt[length] += 1
    return codes


LITLEN = canonical_codes(LITLEN_LENGTHS)
DIST = canonical_codes(DIST_LENGTHS)
CL = canonical_codes(CL_LENGTHS)


def _lsb(value: int, width: int) -> str:
    """`width` bits of `value`, least significant first: a header field's order on the wire."""
    return "".join("1" if value >> i & 1 else "0" for i in range(width))


def _huffman(table: dict[int, tuple[int, int]], symbol: int) -> str:
    """A Huffman code, most significant bit first: a code's order on the wire."""
    code, length = table[symbol]
    return format(code, f"0{length}b")


def deflate_runs(runs: list[tuple[int, int]]) -> bytes:
    """One final dynamic-Huffman DEFLATE block holding `runs` [(octet, count), ...]."""
    head = ["1", _lsb(2, 2), _lsb(len(LITLEN_LENGTHS) - 257, 5), _lsb(len(DIST_LENGTHS) - 1, 5)]
    order = [CL_LENGTHS.get(symbol, 0) for symbol in CL_ORDER]
    while order[-1] == 0:
        order.pop()
    head.append(_lsb(len(order) - 4, 4))
    head += [_lsb(length, 3) for length in order]
    head += [_huffman(CL, length) for length in LITLEN_LENGTHS + DIST_LENGTHS]
    copy = _huffman(LITLEN, 285) + _huffman(DIST, 0)
    body = []
    for octet, count in runs:
        literal = _huffman(LITLEN, octet)
        copies, rest = divmod(count - 1, MAX_MATCH)
        body.append(literal + copy * copies + literal * rest)
    bits = "".join(head) + "".join(body) + _huffman(LITLEN, 256)
    bits += "0" * (-len(bits) % 8)
    return bytes(int(bits[i : i + 8][::-1], 2) for i in range(0, len(bits), 8))


def adler32(runs: list[tuple[int, int]]) -> int:
    value = 1
    for octet, count in runs:
        piece = bytes([octet]) * min(count, 1 << 20)
        while count:
            take = min(count, len(piece))
            value = zlib.adler32(piece[:take], value)
            count -= take
    return value


def zlib_stream(runs: list[tuple[int, int]]) -> bytes:
    """RFC 1950: CMF 0x78 (deflate, 32 KiB window), FLG 0xDA (a multiple of 31 with CMF), the
    block, then the Adler-32 of the uncompressed octets."""
    return b"\x78\xda" + deflate_runs(runs) + struct.pack(">I", adler32(runs))


def expand(runs: list[tuple[int, int]]) -> bytes:
    return b"".join(bytes([octet]) * count for octet, count in runs)


# -- the image -------------------------------------------------------------------------------------


def paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def filter_row(kind: int, row: bytes, above: bytes, step: int) -> bytes:
    """One scanline under filter type `kind` (PNG Third Edition, 7.3 and 9.2), filter byte first."""
    out = bytearray([kind])
    for x, value in enumerate(row):
        a = row[x - step] if x >= step else 0
        b = above[x]
        c = above[x - step] if x >= step else 0
        predictor = (0, a, b, (a + b) >> 1, paeth(a, b, c))[kind]
        out.append((value - predictor) & 0xFF)
    return bytes(out)


def _runs_of(octets: bytes) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for octet in octets:
        if runs and runs[-1][0] == octet:
            runs[-1] = (octet, runs[-1][1] + 1)
        else:
            runs.append((octet, 1))
    return runs


def _append(runs: list[tuple[int, int]], more: list[tuple[int, int]]) -> None:
    for octet, count in more:
        if runs and runs[-1][0] == octet:
            runs[-1] = (octet, runs[-1][1] + count)
        else:
            runs.append((octet, count))


def scanlines(spec: dict) -> list[tuple[int, int]]:
    """The filtered scanlines of an image as runs: rows not named are index 0 under filter 0."""
    width, height = spec["width"], spec["height"]
    channels = {0: 1, 2: 3, 3: 1}[spec["colour_type"]]
    stride = (width * channels * spec["bit_depth"] + 7) // 8
    step = max(1, channels * spec["bit_depth"] // 8)
    zero = bytes(stride)
    runs: list[tuple[int, int]] = []
    above = zero
    y = 0
    named = spec.get("rows", {})
    while y < height:
        if y not in named:
            following = min([r for r in named if r > y], default=height)
            _append(runs, [(0, (following - y) * (1 + stride))])
            above, y = zero, following
            continue
        kind, cells = named[y]
        row = bytearray(stride)
        for x, index in cells.items():
            row[x] = index
        _append(runs, _runs_of(filter_row(kind, bytes(row), above, step)))
        above, y = bytes(row), y + 1
    return runs


def index_summary(spec: dict) -> dict:
    """Counted from the description: every cell a named row does not set is index 0."""
    present = [i for _, cells in spec.get("rows", {}).values() for i in cells.values() if i]
    count = spec["width"] * spec["height"]
    return {
        "count": count,
        "missing_count": count - len(present),
        "min": min(present) if present else None,
        "max": max(present) if present else None,
    }


#: A palette ramp written here, not IEM's colours: index 0 black, the rest a deterministic ramp.
def palette_ramp(entries: int) -> list[list[int]]:
    return [[0, 0, 0]] + [[i, 255 - i, (i * 7) % 256] for i in range(1, entries)]


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def text_body(keyword: str, text: str) -> bytes:
    return keyword.encode("latin-1") + b"\x00" + text.encode("latin-1")


def png(spec: dict, stream: bytes) -> bytes:
    header = struct.pack(
        ">IIBBBBB", spec["width"], spec["height"], spec["bit_depth"], spec["colour_type"], 0, 0, 0
    )
    out = [SIGNATURE, chunk(b"IHDR", header)]
    if spec.get("palette") is not None:
        out.append(chunk(b"PLTE", b"".join(bytes(rgb) for rgb in spec["palette"])))
    for kind, body in spec.get("before_idat", []):
        out.append(chunk(kind, body))
    pieces = spec.get("idat_pieces", 1)
    cut = [len(stream) * i // pieces for i in range(pieces + 1)]
    out += [chunk(b"IDAT", stream[cut[i] : cut[i + 1]]) for i in range(pieces)]
    for kind, body in spec.get("after_idat", []):
        out.append(chunk(kind, body))
    out.append(chunk(b"IEND", b""))
    return b"".join(out)


def ancillary_record(kind: bytes, body: bytes) -> dict:
    if kind == b"tEXt":
        keyword, _, text = body.partition(b"\x00")
        return {
            "chunk": "tEXt",
            "keyword": keyword.decode("latin-1"),
            "text": text.decode("latin-1"),
        }
    return {"chunk": kind.decode("ascii"), "octets_hex": body.hex()}


def twin(spec: dict, octets: bytes) -> dict:
    return {
        "wire_hex": octets.hex(),
        "header": {
            "width": spec["width"],
            "height": spec["height"],
            "bit_depth": spec["bit_depth"],
            "colour_type": spec["colour_type"],
            "compression_method": 0,
            "filter_method": 0,
            "interlace_method": 0,
        },
        "palette": spec["palette"],
        "ancillary": [
            ancillary_record(kind, body)
            for kind, body in spec.get("before_idat", []) + spec.get("after_idat", [])
        ],
        "index_summary": index_summary(spec),
    }


# -- the set ---------------------------------------------------------------------------------------

PALETTE = palette_ramp(256)


def _n0q(**fields) -> dict:
    return {
        "width": WIDTH,
        "height": HEIGHT,
        "bit_depth": 8,
        "colour_type": 3,
        "palette": PALETTE,
        **fields,
    }


#: The ramp's two ends and its zero: indices 1 (-32 dBZ), 65 (0 dBZ), 66 (0.5 dBZ) and 255 (95
#: dBZ), rotated one cell a row over ten rows whose filter types run 0, 1, 2, 3, 4 twice.
RAMP_CELLS = (65, 66, 255, 1, 66, 65, 255, 1)

FIXTURES_SPEC = {
    "ramp_ends_every_filter_type": _n0q(
        rows={
            2700 + k: (k % 5, {6100 + j: RAMP_CELLS[(j + k) % 8] for j in range(8)})
            for k in range(10)
        },
        before_idat=[(b"tEXt", text_body("gentime", "2026-04-29T06:03:24Z"))],
    ),
    "echo_patch_split_idat": _n0q(
        rows={
            100 + k: (1 if k == 0 else 2, {**{200 + j: 65 for j in range(4)}, 204: 66, 205: 66})
            for k in range(4)
        },
        before_idat=[(b"tRNS", b"\x00"), (b"tEXt", text_body("gentime", "2026-04-29T06:03:41Z"))],
        idat_pieces=3,
    ),
    "all_missing_no_gentime": _n0q(),
    "corner_cells_paeth_average": _n0q(
        rows={0: (4, {0: 100, WIDTH - 1: 150}), HEIGHT - 1: (3, {0: 200, WIDTH - 1: 255})},
        before_idat=[
            (b"tEXt", text_body("gentime", "2026-04-29T06:04:59Z")),
            (b"tEXt", text_body("Comment", "synthetic fixture: four corner cells")),
        ],
        after_idat=[(b"tIME", struct.pack(">HBBBBB", 2026, 4, 29, 6, 4, 59))],
    ),
}


def malformed() -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    small = {"width": 1220, "height": 540, "bit_depth": 8, "colour_type": 3, "palette": PALETTE}
    out["wrong_image_size.png"] = png(small, zlib_stream(scanlines(small)))
    rgb = {"width": WIDTH, "height": HEIGHT, "bit_depth": 8, "colour_type": 2, "palette": None}
    out["truecolour_colour_type_2.png"] = png(rgb, zlib_stream(scanlines(rgb)))
    four = {
        "width": WIDTH,
        "height": HEIGHT,
        "bit_depth": 4,
        "colour_type": 3,
        "palette": palette_ramp(16),
    }
    out["four_bit_indices.png"] = png(four, zlib_stream(scanlines(four)))
    empty = _n0q()
    stream = zlib_stream(scanlines(empty))
    good = png(empty, stream)
    # The IDAT chunk's CRC is the four octets before IEND's twelve: its last octet is flipped.
    crc_at = len(good) - 12 - 1
    out["idat_crc_failure.png"] = good[:crc_at] + bytes([good[crc_at] ^ 0xFF]) + good[crc_at + 1 :]
    out["truncated_idat_stream.png"] = png(empty, stream[: len(stream) // 2])
    past = scanlines(empty)
    _append(past, [(0, MAX_MATCH)])
    out["inflates_past_its_rows.png"] = png(empty, zlib_stream(past))
    short = _n0q(palette=palette_ramp(16), rows={2700: (0, {6100: 200})})
    out["index_past_the_palette.png"] = png(short, zlib_stream(scanlines(short)))
    twice = _n0q(
        before_idat=[
            (b"tEXt", text_body("gentime", "2026-04-29T06:03:24Z")),
            (b"tEXt", text_body("gentime", "2026-04-29T06:03:25Z")),
        ]
    )
    out["gentime_twice.png"] = png(twice, zlib_stream(scanlines(twice)))
    return out


def twin_text(document: dict) -> bytes:
    """Indented JSON, ASCII, with a final newline."""
    return (json.dumps(document, indent=2, ensure_ascii=True) + "\n").encode("ascii")


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
                "standard_ref": "iem_n0q/spec/iem_n0q_pin.json",
                "synthetic": True,
            }
            for name, origin in sorted(rows)
        ],
        "schema_id": "synapse.fixture-provenance/v1",
    }
    return (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def build() -> dict[pathlib.Path, bytes]:
    """path -> octets for every file this script writes."""
    out: dict[pathlib.Path, bytes] = {}
    rows: list[tuple[str, str]] = []
    for name, spec in FIXTURES_SPEC.items():
        runs = scanlines(spec)
        stream = zlib_stream(runs)
        if zlib.decompress(stream) != expand(runs):
            raise SystemExit(f"{name}: the DEFLATE writer's stream does not inflate to its rows")
        octets = png(spec, stream)
        out[FIXTURES / f"{name}.png"] = octets
        out[FIXTURES / f"{name}.parsed.json"] = twin_text(twin(spec, octets))
        rows += [(f"{name}.png", ORIGIN_PNG), (f"{name}.parsed.json", ORIGIN_TWIN)]
    out[FIXTURES / "PROVENANCE.json"] = provenance("iem_n0q", rows)
    bad = malformed()
    for name, octets in bad.items():
        out[MALFORMED_DIR / name] = octets
    out[MALFORMED_DIR / "PROVENANCE.json"] = provenance(
        "iem_n0q/malformed", [(name, MALFORMED_ORIGIN) for name in bad]
    )
    return out


def _generated_here(directory: pathlib.Path) -> set[pathlib.Path]:
    if not directory.is_dir():
        return set()
    return {
        p
        for p in directory.iterdir()
        if p.is_file()
        and (p.suffix == ".png" or p.name.endswith(".parsed.json") or p.name == "PROVENANCE.json")
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    args = parser.parse_args(argv)
    built = build()
    if args.check:
        on_disk = _generated_here(FIXTURES) | _generated_here(MALFORMED_DIR)
        stale = sorted(
            {
                str(p.relative_to(FIXTURES))
                for p in built
                if not p.is_file() or p.read_bytes() != built[p]
            }
            | {str(p.relative_to(FIXTURES)) for p in on_disk - set(built)}
        )
        if stale:
            print("STALE: " + ", ".join(stale))
            return 1
        print("CURRENT")
        return 0
    MALFORMED_DIR.mkdir(exist_ok=True)
    for path, octets in built.items():
        path.write_bytes(octets)
    print(f"wrote {len(built)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
