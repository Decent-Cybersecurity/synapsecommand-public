"""Write the SYNTHETIC STANAG 4545 fixture set: the 17 SC4545-CORE-1 engineering vectors of the
SC-4545-ENG-1.0 handoff kit, byte for byte, the parsed twins of the twelve that parse, and the
native NC vectors the decoder and the independent reading are tested on.

A port of the kit's generator (its `make_fixtures.py`), contributed by the maintainer: the helpers
`a`, `d`, `sec`, `image` and `container` keep the kit's names, signatures and byte layout, so the
tests can build mutated containers with them; the kit's one-line style is rewritten for this
repository's lint, the kit's digests are held by the tests instead of being computed here, and the
header-offset contract the kit also wrote is not written. Every vector is unclassified (CLAS `U`)
and none is an official NSIF test file. Edit this script and run it; never edit a fixture by hand:

    python -I -B spec/build_fixtures.py          # rewrite the set
    python -I -B spec/build_fixtures.py --check  # print CURRENT when the tree matches

It writes only the files `fixtures()` names: the eleven translatable vectors and their twins at
the top level, the five refused vectors under `malformed/`, `header_only` with its twin under
`context/`, and the native vectors under `vectors/`. Provenance records, the README, goldens and
the recorded independent readings are not its output.

THE NATIVE VECTORS
------------------
Each is one NC image in the kit's header layout (OSTAID, FDT and IID1 set), its samples given as
planes `[band][row][column]` of storage integers: a deterministic formula that never reaches the
pad value, or a table of literal values. `physical_payload` lays the planes out the way each
interleave mode's prose describes the order on the wire, by nested loops that only append; it
never computes where a sample goes, so it does not share the decoder's index formulas and its
output is an independent expectation for them. Pad pixels of partial edge blocks carry the
all-ones sentinel, which no formula value equals. Every vector that states corners puts them
inside the Baltic rectangle; the poles, the antimeridian and out-of-range corners are built in
memory by the tests and never written here.
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import struct
import sys

SEC = [
    ("CLAS", 1),
    ("CLSY", 2),
    ("CODE", 11),
    ("CTLH", 2),
    ("REL", 20),
    ("DCTP", 2),
    ("DCDT", 8),
    ("DCXM", 4),
    ("DG", 1),
    ("DGDT", 8),
    ("CLTX", 43),
    ("CAPT", 1),
    ("CAUT", 40),
    ("CRSN", 1),
    ("SRDT", 8),
    ("CTLN", 15),
]

TOP_LEVEL = (
    "mono_nsif101",
    "mono_nsif100",
    "mono_nitf210",
    "geo_dms",
    "unknown_duplicate_tre",
    "mode_B",
    "mode_P",
    "mode_R",
    "mode_S",
    "uint16",
    "image_and_text",
)
MALFORMED = ("bad_file_length", "truncated", "trailing", "bad_count", "unsupported_stype")
CONTEXT = ("header_only",)


def a(v, n):
    """An ASCII field of `n` octets, left-justified and space-padded."""
    b = str(v).encode("ascii")
    assert len(b) <= n
    return b.ljust(n, b" ")


def d(v, n):
    """A decimal field of exactly `n` digits, zero-padded."""
    b = f"{v:0{n}d}".encode()
    assert len(b) == n
    return b


def sec(clas="U"):
    """A security block with CLAS set and every other field blank."""
    return b"".join(a(clas if k == "CLAS" else "", n) for k, n in SEC)


def image(
    pixels=b"\x00\x40\x80\xff",
    geo="",
    mode="B",
    bands=1,
    rows=2,
    cols=2,
    bits=8,
    tre=b"",
    block_width=None,
    block_height=None,
):
    """One NC INT image segment as (subheader, data)."""
    block_width = cols if block_width is None else block_width
    block_height = rows if block_height is None else block_height
    band = b"M " + b" " * 6 + b"N" + b" " * 3 + b"0"
    sh = (
        b"IM"
        + a("SCFIX0001", 10)
        + b"20261004120000"
        + a("", 17)
        + a("SYNTHETIC TEST ONLY", 80)
        + sec()
        + b"0"
        + a("SYNTHETIC", 42)
        + d(rows, 8)
        + d(cols, 8)
        + b"INT"
        + a("MONO" if bands == 1 else "MULTI", 8)
        + a("VIS", 8)
        + d(bits, 2)
        + b"R"
        + (b"G" if geo else b" ")
        + geo.encode()
        + b"0"
        + b"NC"
        + (d(bands, 1) if bands < 10 else b"0" + d(bands, 5))
        + band * bands
        + b"0"
        + mode.encode()
        + d((cols + block_width - 1) // block_width, 4)
        + d((rows + block_height - 1) // block_height, 4)
        + d(block_width, 4)
        + d(block_height, 4)
        + d(bits, 2)
        + b"001000"
        + b"0000000000"
        + b"1.0 "
        + b"00000"
        + (d(3 + len(tre), 5) + b"000" + tre if tre else b"00000")
    )
    return sh, pixels


def container(images, magic=b"NSIF01.01", others=()):
    """A whole file: the header, the directory and the segments.

    `others` is (type, subheader, payload) in canonical segment order; type is S, T, D or R.
    """
    groups = {"S": [], "T": [], "D": [], "R": []}
    for typ, sh, data in others:
        groups[typ].append((sh, data))
    directory = d(len(images), 3) + b"".join(d(len(s), 6) + d(len(p), 10) for s, p in images)
    for typ, sw, pw in [("S", 4, 6), ("X", 0, 0), ("T", 4, 5), ("D", 4, 9), ("R", 4, 7)]:
        items = groups.get(typ, [])
        directory += d(len(items), 3) + b"".join(d(len(s), sw) + d(len(p), pw) for s, p in items)
    directory += b"0000000000"
    body = b"".join(s + p for s, p in images + sum((groups[t] for t in ["S", "T", "D", "R"]), []))
    head = (
        magic
        + b"03"
        + b"BF01"
        + a("SCFIX", 10)
        + b"20261004120000"
        + a("SYNTHETIC ENGINEERING VECTOR", 80)
        + sec()
        + b"0000000000"
        + b"0"
        + bytes(3)
        + a("SYNAPSECOMMAND TEST", 24)
        + a("", 18)
    )
    assert len(head) == 342
    hl = 360 + len(directory)
    out = head + d(hl + len(body), 12) + d(hl, 6) + directory + body
    assert len(out) == int(out[342:354])
    return out


def vectors() -> dict[str, bytes]:
    """The kit's 17 vectors by stem, built exactly as the kit's generator builds them."""
    geo = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
    out = {}
    base = container([image()])
    out["mono_nsif101"] = base
    out["mono_nsif100"] = container([image()], b"NSIF01.00")
    out["mono_nitf210"] = container([image()], b"NITF02.10")
    out["geo_dms"] = container([image(geo=geo)])
    out["unknown_duplicate_tre"] = container([image(tre=b"SCZZZZ00003abcSCZZZZ00003def")])
    # A 4x4 raster on a 2x2 block grid of 2x2-pixel blocks, three distinguishable bands, laid out
    # by each mode's own index formula.
    bands = [list(range(1, 17)), list(range(21, 37)), list(range(41, 57))]
    for mode in "BPRS":
        payload = bytearray(48)
        for y in range(4):
            for x in range(4):
                q = (y // 2) * 2 + x // 2
                iy = y % 2
                ix = x % 2
                for band in range(3):
                    j = {
                        "B": ((q * 3 + band) * 2 + iy) * 2 + ix,
                        "P": ((q * 2 + iy) * 2 + ix) * 3 + band,
                        "R": ((q * 2 + iy) * 3 + band) * 2 + ix,
                        "S": ((band * 4 + q) * 2 + iy) * 2 + ix,
                    }[mode]
                    payload[j] = bands[band][y * 4 + x]
        out[f"mode_{mode}"] = container(
            [
                image(
                    bytes(payload),
                    mode=mode,
                    bands=3,
                    rows=4,
                    cols=4,
                    block_width=2,
                    block_height=2,
                )
            ]
        )
    out["uint16"] = container([image(struct.pack(">4H", 0, 256, 4095, 65535), bits=16)])
    text = (
        b"TE"
        + a("TXT001", 7)
        + b"000"
        + b"20261004120000"
        + a("SYNTHETIC TEXT", 80)
        + sec()
        + b"0"
        + b"STA"
        + b"00000"
    )
    out["image_and_text"] = container(
        [image()], others=[("T", text, b"<script>must remain plain text</script>")]
    )
    out["header_only"] = container([])
    bad = bytearray(base)
    bad[342:354] = d(len(base) + 1, 12)
    out["bad_file_length"] = bytes(bad)
    out["truncated"] = base[:-1]
    out["trailing"] = base + b"X"
    bad = bytearray(base)
    bad[360:363] = b"A01"
    out["bad_count"] = bytes(bad)
    bad = bytearray(base)
    bad[11:15] = b"ZZZZ"
    out["unsupported_stype"] = bytes(bad)
    return out


def sample8(band: int, row: int, column: int) -> int:
    """The 8-bit native vectors' sample: never 255, the pad sentinel."""
    return (37 * band + 11 * row + 3 * column + 1) % 251


def sample16(band: int, row: int, column: int) -> int:
    """The 16-bit native vectors' sample: never 65535, the pad sentinel."""
    return (1009 * band + 257 * row + 31 * column + 1) % 65521


def literal_sample(band: int, row: int, column: int) -> int:
    """The asymmetric literal vector's sample: band, row and column each readable in it."""
    return 10 + 100 * band + 20 * row + column


def planes(count: int, rows: int, cols: int, sample) -> list[list[list[int]]]:
    """`count` bands of `rows` x `cols` samples, `sample(band, row, column)` each."""
    return [[[sample(b, y, x) for x in range(cols)] for y in range(rows)] for b in range(count)]


def physical_payload(
    samples: list[list[list[int]]],
    block_width: int,
    block_height: int,
    mode: str,
    nbpp: int,
    pad: int,
) -> bytes:
    """The NC payload of `samples[band][row][column]` in interleave `mode`, written in wire order.

    Blocks run left to right, then top to bottom; a position past the raster's last row or
    column inside a block is a pad pixel and carries `pad`. B: per block, each band's whole
    block in turn. P: per block, per pixel, every band's sample. R: per block, per block row,
    each band's row in turn. S: per band, every block of that band. Samples are `nbpp` bits,
    big-endian. Nothing here computes a position; each sample is appended where the walk is.
    """
    rows = len(samples[0])
    cols = len(samples[0][0])
    across = (cols + block_width - 1) // block_width
    down = (rows + block_height - 1) // block_height
    out = bytearray()

    def put(band: int, row: int, column: int) -> None:
        inside = row < rows and column < cols
        value = samples[band][row][column] if inside else pad
        out.extend(value.to_bytes(nbpp // 8, "big"))

    blocks = [(r * block_height, c * block_width) for r in range(down) for c in range(across)]
    bands = range(len(samples))
    if mode == "B":
        for top, left in blocks:
            for band in bands:
                for iy in range(block_height):
                    for ix in range(block_width):
                        put(band, top + iy, left + ix)
    elif mode == "P":
        for top, left in blocks:
            for iy in range(block_height):
                for ix in range(block_width):
                    for band in bands:
                        put(band, top + iy, left + ix)
    elif mode == "R":
        for top, left in blocks:
            for iy in range(block_height):
                for band in bands:
                    for ix in range(block_width):
                        put(band, top + iy, left + ix)
    elif mode == "S":
        for band in bands:
            for top, left in blocks:
                for iy in range(block_height):
                    for ix in range(block_width):
                        put(band, top + iy, left + ix)
    else:
        raise ValueError(f"no interleave mode {mode!r}")
    return bytes(out)


def native_band(irepband: str = "M", luts: tuple[bytes, ...] = ()) -> bytes:
    """One band record of the image subheader; LUTs are written in file order after NELUTS."""
    record = a(irepband, 2) + b" " * 6 + b"N" + b" " * 3 + d(len(luts), 1)
    if luts:
        assert len({len(table) for table in luts}) == 1
        record += d(len(luts[0]), 5) + b"".join(luts)
    return record


def native_image(
    samples: list[list[list[int]]],
    block_width: int,
    block_height: int,
    mode: str = "B",
    *,
    nbpp: int = 8,
    abpp: int | None = None,
    pjust: str = "R",
    pvtype: str = "INT",
    irep: str | None = None,
    bands: list[bytes] | None = None,
    icords: str = " ",
    igeolo: str = "",
    nppbh: int | None = None,
    nppbv: int | None = None,
) -> tuple[bytes, bytes]:
    """One native NC image segment as (subheader, data), in the kit image's layout.

    `block_width` and `block_height` are the effective block size; `nppbh`/`nppbv` override what
    the subheader states (0 for one block spanning the axis). The pad sentinel is all ones.
    """
    rows = len(samples[0])
    cols = len(samples[0][0])
    count = len(samples)
    abpp = nbpp if abpp is None else abpp
    bands = [native_band() for _ in range(count)] if bands is None else bands
    assert len(bands) == count
    payload = physical_payload(samples, block_width, block_height, mode, nbpp, (1 << nbpp) - 1)
    sh = (
        b"IM"
        + a("SCFIX0001", 10)
        + b"20261004120000"
        + a("", 17)
        + a("SYNTHETIC TEST ONLY", 80)
        + sec()
        + b"0"
        + a("SYNTHETIC", 42)
        + d(rows, 8)
        + d(cols, 8)
        + a(pvtype, 3)
        + a(irep or ("MONO" if count == 1 else "MULTI"), 8)
        + a("VIS", 8)
        + d(abpp, 2)
        + pjust.encode("ascii")
        + icords.encode("ascii")
        + igeolo.encode("ascii")
        + b"0"
        + b"NC"
        + (d(count, 1) if count < 10 else b"0" + d(count, 5))
        + b"".join(bands)
        + b"0"
        + mode.encode("ascii")
        + d((cols + block_width - 1) // block_width, 4)
        + d((rows + block_height - 1) // block_height, 4)
        + d(block_width if nppbh is None else nppbh, 4)
        + d(block_height if nppbv is None else nppbv, 4)
        + d(nbpp, 2)
        + b"001000"
        + b"0000000000"
        + b"1.0 "
        + b"00000"
        + b"00000"
    )
    return sh, payload


#: The fifteen interpretation vectors, one band of 2 rows x 3 columns in one block: (label, NBPP,
#: ABPP, PJUST, PVTYPE, the six storage integers in row order). They cover every PVTYPE x PJUST x
#: NBPP cell, with dirty fill bits, zero and sign-extended fill, and ABPP below NBPP.
INTERPRETATION = (
    ("pjust_r_12in16_dirty", 16, 12, "R", "INT", (0x0000, 0x0001, 0x07FF, 0x0800, 0x0FFE, 0xFFFF)),
    ("pjust_l_12in16", 16, 12, "L", "INT", (0x0000, 0x0010, 0x7FF0, 0x8000, 0xFFE0, 0xFFF0)),
    ("pjust_l_12in16_dirty", 16, 12, "L", "INT", (0x0000, 0x0010, 0x7FF5, 0x8000, 0xFFE0, 0xFFF0)),
    ("pjust_l_5in8", 8, 5, "L", "INT", (0x00, 0x08, 0x78, 0x80, 0xF0, 0xF8)),
    ("si8", 8, 8, "R", "SI", (0x80, 0xFF, 0x00, 0x7F, 0x01, 0xFE)),
    ("si16", 16, 16, "R", "SI", (0x8000, 0xFFFF, 0x0000, 0x7FFF, 0xFFFE, 0x0001)),
    ("si12_r_zerofill", 16, 12, "R", "SI", (0x0800, 0x0FFF, 0x0000, 0x07FF, 0x0001, 0x0FFE)),
    ("si12_r_signext", 16, 12, "R", "SI", (0xF800, 0xFFFF, 0x0000, 0x07FF, 0x0001, 0xFFFE)),
    ("si12_r_mixed", 16, 12, "R", "SI", (0xF800, 0x0FFF, 0x1000, 0x17FF, 0xF7FF, 0x8800)),
    ("si12_l", 16, 12, "L", "SI", (0x8000, 0xFFF0, 0x0000, 0x7FF0, 0x0010, 0xFFE0)),
    ("si12_l_dirty", 16, 12, "L", "SI", (0x800F, 0xFFF0, 0x0000, 0x7FF0, 0x0010, 0xFFE1)),
    ("si1in8_r", 8, 1, "R", "SI", (0x00, 0x01, 0xFF, 0xFE, 0x80, 0x7F)),
    ("int8in16_r", 16, 8, "R", "INT", (0x0000, 0x00FF, 0x0100, 0x01FF, 0xFF00, 0x0080)),
    ("int5in8_r_dirty", 8, 5, "R", "INT", (0x00, 0x01, 0x1F, 0x20, 0xE0, 0xFF)),
    ("si5in8_l_dirty", 8, 5, "L", "SI", (0x80, 0xF8, 0x00, 0x78, 0x08, 0xF1)),
)

#: The three-table LUT vector's tables, in file order.
LUT3_TABLES = (b"\x00\x55\xaa\xff", b"\xff\xaa\x55\x00", b"\x0a\x14\x1e\x28")

#: The axis-aligned rectangles, inside the Baltic rectangle, stated north-up and south-up.
RECTANGLES = (
    ("geo_g_northup", "G", "580000N0210000E580000N0233000E570000N0233000E570000N0210000E"),
    ("geo_g_southup", "G", "570000N0210000E570000N0233000E580000N0233000E580000N0210000E"),
    ("geo_d_northup", "D", "+58.250+020.500+58.250+024.250+56.750+024.250+56.750+020.500"),
    ("geo_d_southup", "D", "+56.750+020.500+56.750+024.250+58.250+024.250+58.250+020.500"),
)


def native_vectors() -> dict[str, bytes]:
    """The native NC vectors by stem (`native_<label>`), each a one-image container."""
    out = {}

    def add(label: str, segment: tuple[bytes, bytes]) -> None:
        out[f"native_{label}"] = container([segment])

    # The asymmetric literal vector: W != H, NBPR != NBPC, partial edge blocks both ways.
    literal = planes(2, 4, 5, literal_sample)
    for mode in "BPRS":
        add(f"lit_{mode.lower()}", native_image(literal, 2, 3, mode))
    for mode in "BPRS":
        add(f"edge8_{mode.lower()}", native_image(planes(3, 5, 7, sample8), 4, 4, mode))
        add(
            f"edge16_{mode.lower()}",
            native_image(planes(3, 5, 7, sample16), 3, 2, mode, nbpp=16),
        )
    one = planes(1, 3, 5, sample8)
    add("nppb_zero", native_image(one, 5, 3, nppbh=0, nppbv=0))
    add("nppbh_zero_only", native_image(one, 5, 2, nppbh=0))
    add("one_block_padded", native_image(one, 8, 4))
    for label, nbpp, abpp, pjust, pvtype, values in INTERPRETATION:
        samples = [[list(values[:3]), list(values[3:])]]
        add(
            label,
            native_image(samples, 3, 2, nbpp=nbpp, abpp=abpp, pjust=pjust, pvtype=pvtype),
        )
    for prefix, count in (("nbands9", 9), ("xbands10", 10), ("xbands256", 256)):
        for mode in "BPRS":
            add(f"{prefix}_{mode.lower()}", native_image(planes(count, 3, 5, sample8), 3, 2, mode))
    add(
        "lut3",
        native_image(
            [[[0, 1], [2, 3]]],
            2,
            2,
            irep="RGB/LUT",
            bands=[native_band("LU", LUT3_TABLES)],
        ),
    )
    for label, icords, igeolo in RECTANGLES:
        add(label, native_image(one, 5, 3, icords=icords, igeolo=igeolo))
    return out


def twin(octets: bytes) -> bytes:
    """The parsed twin of a vector: the closed envelope holding the same octets as canonical
    base64. A wire envelope, not a decoded form."""
    document = {"profile": "SC4545-CORE-1", "wire_b64": base64.b64encode(octets).decode("ascii")}
    return (json.dumps(document, indent=2) + "\n").encode("ascii")


def fixtures() -> dict[str, bytes]:
    """Every file this script owns, by its path relative to the fixture directory."""
    built = vectors()
    files = {}
    for stem in TOP_LEVEL:
        files[f"{stem}.ntf"] = built[stem]
        files[f"{stem}.parsed.json"] = twin(built[stem])
    for stem in MALFORMED:
        files[f"malformed/{stem}.ntf"] = built[stem]
    for stem in CONTEXT:
        files[f"context/{stem}.ntf"] = built[stem]
        files[f"context/{stem}.parsed.json"] = twin(built[stem])
    for stem, octets in native_vectors().items():
        files[f"vectors/{stem}.ntf"] = octets
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write or check the stanag4545 fixtures.")
    parser.add_argument("--check", action="store_true", help="compare only; write nothing")
    args = parser.parse_args(argv)
    root = pathlib.Path(__file__).resolve().parent.parent
    files = fixtures()
    if args.check:
        stale = [
            name
            for name, data in files.items()
            if not (root / name).is_file() or (root / name).read_bytes() != data
        ]
        print("CURRENT" if not stale else "STALE: " + ", ".join(stale))
        return 1 if stale else 0
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    print(f"wrote {len(files)} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
