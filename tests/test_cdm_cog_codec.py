"""`adapters/raster_codec.py`: the standard-library TIFF, GeoTIFF and PNG codec `cog` (#30) and the
IEM N0Q adapter share.

Every expectation is a literal: the TIFF 6.0 PackBits example worked out by hand, LZW codes and
predictor rows written out bit by bit and octet by octet, two PNGs GDAL 3.13.3 wrote on 2026-10-17
from the grids written beside them (GDAL is an independent writer; its octets are carried here as
hexadecimal), and every refusal as its code and its whole text. Files are assembled octet by octet
in this module with `struct`, so a refusal is the input it names and nothing else.

Package-only: it imports the codec from the installed package and reads no file.
"""

import math
import pickle
import struct
import zlib

import pytest

from synapse_cdm.adapters import raster_codec as codec
from synapse_cdm.adapters.raster_codec import RasterRefused

# ================================================================== assembling TIFFs here

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}


def raw_tiff(entries, *, order=b"II", version=42, first=8, next_ifd=0, tail=b"", count=None):
    """A header and one directory of `(tag, type, count, value octets)` entries, written in the
    order given; a value longer than four octets goes after the directory."""
    e = "<" if order == b"II" else ">"
    head = order + struct.pack(e + "HI", version, first)
    n = len(entries) if count is None else count
    values_at = first + 2 + 12 * len(entries) + 4
    body = struct.pack(e + "H", n)
    extra = b""
    for tag, kind, number, value in entries:
        body += struct.pack(e + "HHI", tag, kind, number)
        if len(value) <= 4:
            body += value.ljust(4, b"\x00")
        else:
            body += struct.pack(e + "I", values_at + len(extra))
            extra += value
    body += struct.pack(e + "I", next_ifd)
    return head + b"\x00" * (first - 8) + body + extra + tail


def short(*values, e="<"):
    return struct.pack(e + "H" * len(values), *values)


def long_(*values, e="<"):
    return struct.pack(e + "I" * len(values), *values)


def refusal(call) -> RasterRefused:
    with pytest.raises(RasterRefused) as raised:
        call()
    return raised.value


def read(octets, **bounds):
    limits = {
        "max_ifds": 4,
        "max_entries": 32,
        "max_value_octets": 64,
        "max_total_value_octets": 256,
    }
    limits.update(bounds)
    return codec.read_tiff(octets, **limits)


#: One plain 2 x 1 Float32 strip, the directory every structural test below varies.
PLAIN = [
    (256, 3, 1, short(2)),
    (257, 3, 1, short(1)),
    (258, 3, 1, short(32)),
    (273, 4, 1, long_(0)),
    (279, 4, 1, long_(8)),
    (339, 3, 1, short(3)),
]


# ================================================================== the refusal class


def test_a_refusal_is_a_value_error_with_its_code_and_survives_pickling():
    err = RasterRefused("bigtiff", "the header states BigTIFF")
    assert isinstance(err, ValueError)
    assert (err.code, err.text, str(err)) == (
        "bigtiff",
        "the header states BigTIFF",
        "bigtiff: the header states BigTIFF",
    )
    back = pickle.loads(pickle.dumps(err))
    assert (type(back), back.code, str(back)) == (RasterRefused, "bigtiff", str(err))


# ================================================================== the header and the directory


def test_a_little_and_a_big_endian_directory_read_the_same_entries():
    little = raw_tiff(PLAIN)
    big = raw_tiff([(t, k, n, v[::-1]) for t, k, n, v in PLAIN], order=b"MM")
    for octets, order in ((little, "II"), (big, "MM")):
        tiff = read(octets)
        assert (tiff.byte_order, tiff.first_ifd_offset, len(tiff.ifds)) == (order, 8, 1)
        ifd = tiff.ifds[0]
        assert (ifd.offset, ifd.next_offset) == (8, 0)
        assert [(e.tag, e.name, e.type_name, e.count, e.value) for e in ifd.entries.values()] == [
            (256, "ImageWidth", "SHORT", 1, [2]),
            (257, "ImageLength", "SHORT", 1, [1]),
            (258, "BitsPerSample", "SHORT", 1, [32]),
            (273, "StripOffsets", "LONG", 1, [0]),
            (279, "StripByteCounts", "LONG", 1, [8]),
            (339, "SampleFormat", "SHORT", 1, [3]),
        ]


def test_each_type_is_decoded_by_its_own_rule():
    entries = [
        (270, 2, 6, b"abc\x00d\x00"),  # two NUL-separated strings
        (305, 2, 4, b"\xc3\xa9t\x00"),  # UTF-8 text in an ASCII field, as GDAL writes it
        (33550, 12, 1, struct.pack("<d", 0.25)),
        (40000, 1, 3, b"\x01\xab\xff"),
        (40001, 5, 1, long_(72, 1)),
        (40002, 8, 2, struct.pack("<hh", -2, 7)),
        (40003, 9, 1, struct.pack("<i", -70000)),
        (40004, 10, 1, struct.pack("<ii", -1, 3)),
        (40005, 11, 1, struct.pack("<f", 1.5)),
        (40006, 6, 2, b"\xfe\x02"),
        (40007, 7, 1, b"\x00"),
    ]
    values = {e.name: e.value for e in read(raw_tiff(entries)).ifds[0].entries.values()}
    assert values == {
        "ImageDescription": ["abc", "d"],
        "Software": "ét",
        "ModelPixelScaleTag": [0.25],
        "Tag40000": "01abff",
        "Tag40001": [[72, 1]],
        "Tag40002": [-2, 7],
        "Tag40003": [-70000],
        "Tag40004": [[-1, 3]],
        "Tag40005": [1.5],
        "Tag40006": "fe02",
        "Tag40007": "00",
    }


TIFF_REFUSALS = [
    (b"II*\x00\x08\x00", "truncated-header", "the file is shorter than the TIFF header"),
    (b"XX*\x00\x08\x00\x00\x00", "not-a-tiff", "the file does not open with II or MM"),
    (
        b"II+\x00\x08\x00\x00\x00",
        "bigtiff",
        "the header states BigTIFF (version 43), which this codec does not read",
    ),
    (b"II\x2b\x01\x08\x00\x00\x00", "not-a-tiff", "the header's version is not 42 (classic TIFF)"),
    (
        b"MM\x00\x2b\x00\x00\x00\x08",
        "bigtiff",
        "the header states BigTIFF (version 43), which this codec does not read",
    ),
    (b"II*\x00\x00\x00\x00\x00", "no-ifd", "the header points at no image file directory"),
    (b"II*\x00\x07\x00\x00\x00", "ifd-past-the-end", "IFD 0 begins outside the file"),
    (b"II*\x00\x40\x00\x00\x00", "ifd-past-the-end", "IFD 0 begins outside the file"),
    (b"II*\x00\x08\x00\x00\x00\x00\x00\x00\x00\x00\x00", "empty-ifd", "IFD 0 holds no entry"),
    (raw_tiff(PLAIN)[:40], "ifd-past-the-end", "IFD 0's entries run past the end of the file"),
    (raw_tiff(PLAIN, count=33), "too-many-entries", "IFD 0 states more than 32 entries"),
    (
        raw_tiff([PLAIN[0], PLAIN[0]]),
        "repeated-tag",
        "IFD 0 states ImageWidth twice",
    ),
    (
        raw_tiff([PLAIN[1], PLAIN[0]]),
        "tags-out-of-order",
        "IFD 0: ImageWidth follows a higher tag (TIFF 6.0 sorts them)",
    ),
    (
        raw_tiff([(256, 13, 1, short(2))]),
        "unknown-tag-type",
        "IFD 0: ImageWidth has a type TIFF 6.0 lacks",
    ),
    (
        raw_tiff([(256, 5, 1, long_(2, 1))]),
        "bad-tag-type",
        "IFD 0: ImageWidth has the type RATIONAL, not its own",
    ),
    (raw_tiff([(256, 3, 0, b"")]), "empty-tag", "IFD 0: ImageWidth states no value"),
    (
        raw_tiff([(256, 3, 2, short(2, 3))]),
        "bad-tag-count",
        "IFD 0: ImageWidth states more than one value",
    ),
    (
        raw_tiff([(40000, 7, 65, b"\x00" * 65)]),
        "tag-past-its-bound",
        "IFD 0: Tag40000's value is longer than 64 octets",
    ),
    (
        raw_tiff([(40000, 7, 8, b"\x00" * 8)])[:-1],
        "tag-past-the-end",
        "IFD 0: Tag40000's value runs past the end of the file",
    ),
    (
        raw_tiff([(270, 2, 4, b"abcd")]),
        "ascii-not-terminated",
        "IFD 0: ImageDescription does not end with NUL (TIFF 6.0)",
    ),
    (
        raw_tiff([(270, 2, 4, b"\xff\xfe\x41\x00")]),
        "not-utf8-text",
        "IFD 0: ImageDescription is not UTF-8 text",
    ),
    (
        raw_tiff([(33550, 12, 1, struct.pack("<d", math.inf))]),
        "non-finite-tag-value",
        "IFD 0: ModelPixelScaleTag holds a non-finite number",
    ),
    (raw_tiff(PLAIN, next_ifd=8), "ifd-loop", "IFD 1 points back at an IFD already read"),
]


@pytest.mark.parametrize("octets,code,text", TIFF_REFUSALS)
def test_each_structural_rule_refuses_with_its_code_and_whole_text(octets, code, text):
    err = refusal(lambda: read(octets))
    assert (err.code, str(err)) == (code, f"{code}: {text}")


def test_a_chain_past_the_directory_bound_is_refused_at_the_directory_that_crosses_it():
    # Three directories chained 8 -> 30 -> 52; a bound of two refuses the third before reading it.
    one = raw_tiff([PLAIN[0]], next_ifd=26)
    two = struct.pack("<H", 1) + struct.pack("<HHI", 256, 3, 1) + short(2).ljust(4, b"\x00")
    chain = one + two + long_(44) + two + long_(0)
    assert [i.offset for i in read(chain).ifds] == [8, 26, 44]
    err = refusal(lambda: read(chain, max_ifds=2))
    assert str(err) == "too-many-ifds: the file chains more than 2 IFDs; refused there"


def test_the_values_of_all_directories_are_held_to_one_total():
    # Five 64-octet values (the per-value bound) are 320 octets, past a total of 256.
    entries = [(40000 + i, 7, 64, b"\x00" * 64) for i in range(5)]
    err = refusal(lambda: read(raw_tiff(entries)))
    assert str(err) == (
        "values-past-their-bound: IFD 0: Tag40004 takes the directories' values past their total "
        "bound"
    )
    assert len(read(raw_tiff(entries[:4])).ifds[0].entries) == 4


# ================================================================== layout


def ifd_of(entries, size=4096):
    return read(
        raw_tiff(entries) + b"\x00" * size, max_value_octets=1024, max_total_value_octets=8192
    ).ifds[0]


def test_a_strip_layout_and_a_tile_layout_are_read_with_their_block_windows():
    strips = ifd_of(
        [
            (256, 3, 1, short(5)),
            (257, 3, 1, short(5)),
            (273, 4, 3, long_(100, 200, 300)),
            (278, 3, 1, short(2)),
            (279, 4, 3, long_(10, 10, 10)),
        ]
    )
    layout = codec.block_layout(strips, 0, 4200)
    assert (layout.tiled, layout.block_width, layout.block_height, layout.offsets) == (
        False,
        5,
        2,
        (100, 200, 300),
    )
    assert [layout.block_window(i) for i in range(3)] == [(0, 0, 5, 2), (0, 2, 5, 2), (0, 4, 5, 1)]
    tiles = ifd_of(
        [
            (256, 3, 1, short(20)),
            (257, 3, 1, short(17)),
            (322, 3, 1, short(16)),
            (323, 3, 1, short(16)),
            (324, 4, 4, long_(100, 200, 300, 400)),
            (325, 4, 4, long_(5, 5, 5, 5)),
        ]
    )
    layout = codec.block_layout(tiles, 0, 4200)
    assert (layout.tiled, layout.blocks_across) == (True, 2)
    assert [layout.block_window(i) for i in range(4)] == [
        (0, 0, 16, 16),
        (16, 0, 4, 16),
        (0, 16, 16, 1),
        (16, 16, 4, 1),
    ]


def test_a_block_s_decoded_size_is_whole_for_a_tile_and_its_rows_for_a_strip():
    layout = codec.Layout(5, 5, 1, 1, (16,), (2,), 1, 1, False, 5, 2, (0, 0, 0), (0, 0, 0))
    assert [codec.block_octets(layout, i) for i in range(3)] == [20, 20, 10]
    tiled = codec.Layout(20, 17, 1, 1, (32,), (3,), 1, 1, True, 16, 16, (0,) * 4, (0,) * 4)
    assert [codec.block_octets(tiled, i) for i in range(4)] == [1024] * 4


LAYOUT_REFUSALS = [
    ([(257, 3, 1, short(1))], "missing-tag", "IFD 0 states no ImageWidth"),
    (
        [(256, 3, 1, short(0)), (257, 3, 1, short(1))],
        "empty-image",
        "IFD 0 states an image with no pixel",
    ),
    (
        [(256, 3, 1, short(1)), (257, 3, 1, short(1)), (284, 3, 1, short(3))],
        "bad-planar-configuration",
        "IFD 0's PlanarConfiguration is not 1 or 2",
    ),
    (
        [(256, 3, 1, short(1)), (257, 3, 1, short(1)), (258, 3, 2, short(8, 8))],
        "bad-tag-count",
        "IFD 0: BitsPerSample and SampleFormat state one value a sample",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (273, 4, 1, long_(100)),
            (322, 3, 1, short(16)),
        ],
        "strips-and-tiles",
        "IFD 0 states both strips and tiles",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (322, 3, 1, short(24)),
            (323, 3, 1, short(16)),
        ],
        "bad-tile-size",
        "IFD 0: TileWidth and TileLength are not multiples of 16 (TIFF 6.0 Section 15)",
    ),
    (
        [(256, 3, 1, short(1)), (257, 3, 1, short(1)), (278, 3, 1, short(0))],
        "bad-rows-per-strip",
        "IFD 0's RowsPerStrip is 0",
    ),
    (
        [(256, 3, 1, short(1)), (257, 3, 1, short(1)), (273, 4, 1, long_(100))],
        "missing-tag",
        "IFD 0 states no StripByteCounts",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(3)),
            (273, 4, 2, long_(100, 200)),
            (278, 3, 1, short(1)),
            (279, 4, 2, long_(4, 4)),
        ],
        "block-count-disagrees",
        "IFD 0: StripOffsets and StripByteCounts do not state one value for each block the "
        "image's size implies",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (273, 4, 1, long_(4190)),
            (279, 4, 1, long_(11)),
        ],
        "block-past-the-end",
        "IFD 0: block 0 does not lie inside the file",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (273, 4, 1, long_(4)),
            (279, 4, 1, long_(4)),
        ],
        "block-past-the-end",
        "IFD 0: block 0 does not lie inside the file",
    ),
    (
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (273, 4, 1, long_(100)),
            (279, 4, 1, long_(0)),
        ],
        "block-past-the-end",
        "IFD 0: block 0 does not lie inside the file",
    ),
]


@pytest.mark.parametrize("entries,code,text", LAYOUT_REFUSALS)
def test_each_layout_rule_refuses_with_its_code_and_whole_text(entries, code, text):
    err = refusal(lambda: codec.block_layout(ifd_of(entries), 0, 4200))
    assert (err.code, str(err)) == (code, f"{code}: {text}")


def test_a_sparse_block_is_accepted_by_the_layout_and_returned_as_none():
    ifd = ifd_of(
        [
            (256, 3, 1, short(1)),
            (257, 3, 1, short(1)),
            (258, 3, 1, short(8)),
            (273, 4, 1, long_(0)),
            (279, 4, 1, long_(0)),
        ]
    )
    layout = codec.block_layout(ifd, 0, 4200)
    assert codec.decode_block(b"", layout, 0, "II", limit=64, where="IFD 0") is None


# ================================================================== decoding one block


def layout(width=2, rows=1, *, bits=32, fmt=3, compression=1, predictor=1, count=None):
    size = (width * bits + 7) // 8 * rows
    return codec.Layout(
        width,
        rows,
        1,
        1,
        (bits,),
        (fmt,),
        compression,
        predictor,
        False,
        width,
        rows,
        (8,),
        (size if count is None else count,),
    )


def decode(data, lay, order="II", limit=1 << 20):
    return codec.decode_block(b"\x00" * 8 + data, lay, 0, order, limit=limit, where="IFD 0")


def test_uncompressed_samples_are_read_in_the_file_s_byte_order():
    assert decode(struct.pack("<ff", 1.5, -2.25), layout()) == [1.5, -2.25]
    assert decode(struct.pack(">ff", 1.5, -2.25), layout(), "MM") == [1.5, -2.25]
    assert decode(struct.pack("<hH", -2, 65535)[:2] * 2, layout(bits=16, fmt=2)) == [-2, -2]
    assert decode(struct.pack("<d", 0.1), layout(1, bits=64)) == [0.1]
    assert decode(b"\x07\xf9", layout(bits=8, fmt=2)) == [7, -7]


def test_horizontal_differencing_accumulates_each_row_modulo_the_sample_width():
    # Int16 rows [100, 97, 102] and [-1, -32768, 32767], stored as differences mod 2^16:
    # 100, 97 - 100 = -3 -> 65533, 102 - 97 = 5; -1 -> 65535, -32768 - (-1) = -32767 -> 32769,
    # 32767 - (-32768) = 65535.
    stored = struct.pack("<6H", 100, 65533, 5, 65535, 32769, 65535)
    assert decode(stored, layout(3, 2, bits=16, fmt=2, predictor=2)) == [
        100,
        97,
        102,
        -1,
        -32768,
        32767,
    ]
    # UInt8 [250, 3, 4]: 250, 3 - 250 = -247 -> 9, 4 - 3 = 1.
    assert decode(bytes([250, 9, 1]), layout(3, bits=8, fmt=1, predictor=2)) == [250, 3, 4]


def test_the_floating_point_predictor_reorders_planes_most_significant_first_in_any_order():
    # 1.0 = 3F 80 00 00 and 2.0 = 40 00 00 00. Planes, most significant first: 3F 40 | 80 00 |
    # 00 00 | 00 00; differenced octet by octet: 3F, 40-3F = 01, 80-40 = 40, 00-80 = 80, 00 ...
    stored = bytes.fromhex("3f01408000000000")
    for order in ("II", "MM"):
        assert decode(stored, layout(predictor=3), order) == [1.0, 2.0]


def test_packbits_decodes_the_tiff_6_example_worked_out_by_hand():
    # TIFF 6.0 Section 9's example: FE AA -> AA x3; 02 80 00 2A -> literal; FD AA -> AA x4;
    # 03 80 00 2A 22 -> literal; F7 AA -> AA x10. Twenty-four octets.
    packed = bytes.fromhex("feaa0280002afdaa0380002a22f7aa")
    unpacked = bytes.fromhex("aaaaaa80002aaaaaaaaa80002a22" + "aa" * 10)
    assert codec.packbits_decode(packed, 24, where="b") == bytearray(unpacked)
    assert codec.packbits_decode(b"\x80" + packed, 24, where="b") == bytearray(unpacked)


def test_lzw_decodes_codes_written_out_bit_by_bit():
    # 07 07 07 07: Clear 256, 7, 258 (07 07), 7, EndOfInformation 257, nine bits each, padded.
    bits = "100000000" + "000000111" + "100000010" + "000000111" + "100000001" + "000"
    stream = int(bits, 2).to_bytes(6, "big")
    assert stream == bytes.fromhex("8001e0407808")
    assert codec.lzw_decode(stream, 4, where="b") == bytearray(b"\x07" * 4)
    # The KwKwK case: 05 05 05 is Clear, 5, 258 (05 05) named before it is in the table, EOI.
    bits = "100000000" + "000000101" + "100000010" + "100000001" + "0000"
    assert codec.lzw_decode(int(bits, 2).to_bytes(5, "big"), 3, where="b") == bytearray(b"\x05" * 3)


def lzw_encode(data: bytes, written: list | None = None) -> bytes:
    """A TIFF LZW encoder written here after libtiff's `LZWEncode`: nine to twelve bits, the
    width growing once the next free code passes the width's largest, a Clear when the next free
    code reaches 4094, and the same step once more after the last code."""

    def fresh():
        return {bytes((i,)): i for i in range(256)}, 258, 9

    table, free, width = fresh()
    codes = [(256, 9)]

    def added():
        nonlocal table, free, width
        free += 1
        if free == 4094:
            codes.append((256, width))
            table, free, width = fresh()
        elif free > (1 << width) - 1:
            width += 1

    w = b""
    for octet in data:
        wc = w + bytes((octet,))
        if wc in table:
            w = wc
            continue
        codes.append((table[w], width))
        table[wc] = free
        added()
        w = bytes((octet,))
    if w:
        codes.append((table[w], width))
        added()
    codes.append((257, width))
    if written is not None:
        written.extend(codes)
    joined = "".join(format(code, f"0{size}b") for code, size in codes)
    joined += "0" * (-len(joined) % 8)
    return int(joined, 2).to_bytes(len(joined) // 8, "big")


def pseudo_random(size: int) -> bytes:
    """Octets from a linear congruential generator: few repeats, so nearly every code adds an
    entry and the table fills."""
    x, out = 12345, bytearray()
    for _ in range(size):
        x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((x >> 16) & 0xFF)
    return bytes(out)


@pytest.mark.parametrize(
    "size,widths,clears",
    [
        (1, {9}, 1),
        (300, {9, 10}, 1),
        (1000, {9, 10, 11}, 1),
        (3000, {9, 10, 11, 12}, 1),
        (9000, {9, 10, 11, 12}, 3),
    ],
)
def test_lzw_reads_widths_nine_to_twelve_and_a_table_reset(size, widths, clears):
    data = pseudo_random(size)
    codes: list = []
    stream = lzw_encode(data, codes)
    assert {width for _, width in codes} == widths
    assert sum(1 for code, _ in codes if code == 256) == clears
    assert codec.lzw_decode(stream, size, where="b") == bytearray(data)


LZW_REFUSALS = [
    (b"\x00\x01\x02", 3, "old-style-lzw", "b is pre-TIFF 6.0 LZW, which is not read"),
    (
        int("100000000" + "100000011" + "000000", 2).to_bytes(3, "big"),
        3,
        "bad-lzw-code",
        "b names a code no table holds",
    ),
    (
        lzw_encode(b"\x01\x02\x03"),
        2,
        "block-inflates-past-its-size",
        "b decodes past the octets its size implies",
    ),
    (lzw_encode(b"\x01\x02\x03"), 4, "block-short", "b's LZW codes end before its size"),
    (
        lzw_encode(b"\x01\x02\x03") + b"\x00",
        3,
        "octets-after-the-stream",
        "b holds octets after its EndOfInformation",
    ),
    (lzw_encode(b"\x01\x02\x03")[:2], 3, "block-short", "b's LZW codes end before its size"),
]


@pytest.mark.parametrize("data,size,code,text", LZW_REFUSALS)
def test_each_lzw_rule_refuses_with_its_code_and_whole_text(data, size, code, text):
    err = refusal(lambda: codec.lzw_decode(data, size, where="b"))
    assert str(err) == f"{code}: {text}"


PACKBITS_REFUSALS = [
    (b"\x03\x01\x02", 4, "packbits-truncated", "b's literal run is cut short"),
    (b"\xfe", 3, "packbits-truncated", "b's repeat run is cut short"),
    (b"\xfe\x07", 2, "block-inflates-past-its-size", "b decodes past the octets its size implies"),
    (b"\xfe\x07", 4, "block-short", "b decodes to fewer octets than its size"),
    (b"\xfe\x07\x00\x01", 3, "octets-after-the-stream", "b holds octets past its size"),
]


@pytest.mark.parametrize("data,size,code,text", PACKBITS_REFUSALS)
def test_each_packbits_rule_refuses_with_its_code_and_whole_text(data, size, code, text):
    err = refusal(lambda: codec.packbits_decode(data, size, where="b"))
    assert str(err) == f"{code}: {text}"


DEFLATE_REFUSALS = [
    (b"not a zlib stream", 4, "bad-deflate", "b is not a zlib stream"),
    (
        zlib.compress(b"\x00" * 5),
        4,
        "block-inflates-past-its-size",
        "b inflates past the octets its size implies",
    ),
    (
        zlib.compress(b"\x00" * 5)[:-3],
        5,
        "block-short",
        "b's zlib stream ends before it is complete",
    ),
    (
        zlib.compress(b"\x00" * 5) + b"\x00",
        5,
        "octets-after-the-stream",
        "b holds octets after its stream",
    ),
    (zlib.compress(b"\x00" * 3), 5, "block-short", "b decodes to fewer octets than its size"),
]


@pytest.mark.parametrize("data,size,code,text", DEFLATE_REFUSALS)
def test_each_deflate_rule_refuses_with_its_code_and_whole_text(data, size, code, text):
    err = refusal(lambda: codec.inflate(data, size, where="b"))
    assert str(err) == f"{code}: {text}"
    assert codec.inflate(zlib.compress(b"\x01\x02\x03\x04\x05"), 5, where="b") == bytearray(
        b"\x01\x02\x03\x04\x05"
    )


BLOCK_REFUSALS = [
    (
        codec.Layout(1, 1, 2, 1, (8, 8), (1, 1), 1, 1, False, 1, 1, (8,), (2,)),
        "more-than-one-sample",
        "IFD 0 states more than one sample a pixel",
    ),
    (
        layout(bits=16, fmt=3),
        "unsupported-sample-format",
        "IFD 0: SampleFormat and BitsPerSample are not one of the eight read",
    ),
    (
        layout(bits=1, fmt=1),
        "unsupported-sample-format",
        "IFD 0: SampleFormat and BitsPerSample are not one of the eight read",
    ),
    (layout(compression=7), "unsupported-compression", "IFD 0: JPEG compression is not read"),
    (layout(compression=50000), "unsupported-compression", "IFD 0: ZSTD compression is not read"),
    (layout(compression=34887), "unsupported-compression", "IFD 0: LERC compression is not read"),
    (
        layout(compression=99),
        "unsupported-compression",
        "IFD 0: the Compression code is not one this codec reads",
    ),
    (layout(predictor=4), "unsupported-predictor", "IFD 0: the Predictor is not 1, 2 or 3"),
    (
        layout(predictor=2),
        "unsupported-predictor",
        "IFD 0: horizontal differencing is not read on floating-point samples",
    ),
    (
        layout(bits=16, fmt=1, predictor=3),
        "unsupported-predictor",
        "IFD 0: the floating-point predictor is stated for integer samples",
    ),
    (
        layout(count=7),
        "block-length-disagrees",
        "IFD 0: uncompressed block 0 is not the octets its size implies",
    ),
]


@pytest.mark.parametrize("lay,code,text", BLOCK_REFUSALS)
def test_each_block_rule_refuses_with_its_code_and_whole_text(lay, code, text):
    err = refusal(lambda: decode(b"\x00" * 64, lay))
    assert str(err) == f"{code}: {text}"


def test_a_block_past_the_limit_is_refused_before_anything_is_decompressed():
    lay = layout(width=64, rows=64, compression=8)  # 16 384 octets decoded
    err = refusal(lambda: decode(b"not deflate at all", lay, limit=16383))
    assert str(err) == (
        "block-past-the-decompression-bound: IFD 0: block 0 decodes to more than 16383 octets; "
        "refused before anything is decompressed"
    )
    assert decode(zlib.compress(b"\x00" * 16384), lay, limit=16384) == [0.0] * 4096


# ================================================================== GeoKeys


def geo_ifd(directory, doubles=None, text=None):
    entries = [(34735, 3, len(directory), short(*directory))]
    if doubles is not None:
        entries.append((34736, 12, len(doubles), struct.pack(f"<{len(doubles)}d", *doubles)))
    if text is not None:
        raw = text.encode() + b"\x00"
        entries.append((34737, 2, len(raw), raw))
    return read(raw_tiff(entries), max_value_octets=1024, max_total_value_octets=4096).ifds[0]


def test_geokeys_are_read_inline_from_the_doubles_and_from_the_ascii_parameters():
    ifd = geo_ifd(
        [1, 1, 1, 4, 1024, 0, 1, 1, 1026, 34737, 22, 0, 2057, 34736, 1, 1, 3072, 0, 1, 32634],
        doubles=[298.257223563, 6378137.0],
        text="WGS 84 / UTM zone 34N|",
    )
    keys = codec.geokeys(ifd)
    assert (keys.version, keys.revision, keys.minor_revision) == (1, 1, 1)
    assert keys.keys == {1024: 1, 1026: "WGS 84 / UTM zone 34N", 2057: [6378137.0], 3072: 32634}
    assert codec.geokeys(read(raw_tiff(PLAIN)).ifds[0]) is None
    assert [codec.GEOKEY_NAMES[k] for k in (2048, 3072, 4096)] == [
        "GeodeticCRSGeoKey",
        "ProjectedCRSGeoKey",
        "VerticalGeoKey",
    ]


GEOKEY_REFUSALS = [
    (
        [1, 1, 0, 2, 1024, 0, 1, 1],
        None,
        None,
        "bad-geokey-directory",
        "IFD 0: the GeoKey directory's length is not its key count's",
    ),
    (
        [2, 1, 0, 1, 1024, 0, 1, 1],
        None,
        None,
        "unsupported-geokey-version",
        "IFD 0: the GeoKey directory is not version 1, revision 1.0 or 1.1",
    ),
    (
        [1, 1, 2, 1, 1024, 0, 1, 1],
        None,
        None,
        "unsupported-geokey-version",
        "IFD 0: the GeoKey directory is not version 1, revision 1.0 or 1.1",
    ),
    (
        [1, 1, 0, 2, 1025, 0, 1, 1, 1024, 0, 1, 1],
        None,
        None,
        "geokeys-out-of-order",
        "IFD 0: GTModelTypeGeoKey is not in ascending key order",
    ),
    (
        [1, 1, 0, 1, 1024, 0, 2, 1],
        None,
        None,
        "bad-geokey",
        "IFD 0: GTModelTypeGeoKey is inline with a count not 1",
    ),
    (
        [1, 1, 0, 1, 1026, 34737, 5, 0],
        None,
        "WGS 84|",
        "bad-geokey-ascii",
        "IFD 0: GTCitationGeoKey's text is not a |-terminated slice of GeoAsciiParamsTag",
    ),
    (
        [1, 1, 0, 1, 2057, 34736, 1, 3],
        [1.0],
        None,
        "bad-geokey",
        "IFD 0: EllipsoidSemiMajorAxisGeoKey's doubles lie outside GeoDoubleParamsTag",
    ),
    (
        [1, 1, 0, 1, 1024, 33550, 1, 0],
        None,
        None,
        "bad-geokey",
        "IFD 0: GTModelTypeGeoKey points at a tag the GeoKey directory does not name",
    ),
]


@pytest.mark.parametrize("directory,doubles,text,code,message", GEOKEY_REFUSALS)
def test_each_geokey_rule_refuses_with_its_code_and_whole_text(
    directory, doubles, text, code, message
):
    err = refusal(lambda: codec.geokeys(geo_ifd(directory, doubles, text)))
    assert str(err) == f"{code}: {message}"


# ================================================================== PNG

#: Written by GDAL 3.13.3 on 2026-10-17 (`gdal_translate -of PNG`, GDAL_PAM_ENABLED=NO): a 5 x 3
#: indexed image of the grid [[0, 1, 2, 3, 0], [3, 2, 1, 0, 1], [1, 1, 2, 2, 3]] under a four-entry
#: palette (black, blue, green, red), and a 4 x 2 16-bit greyscale image of
#: [[0, 256, 65535, 1000], [40000, 7, 300, 65280]].
GDAL_PALETTE_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000050000000308030000006ce835ca0000000c504c5445000000"
    "0000ff00ff00ff0000d3238ec70000001849444154089963606064626660606662640042462626660000c500"
    "17fd0a601a0000000049454e44ae426082"
)
GDAL_GREY16_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000040000000210000000000a53fefc0000001a49444154089963"
    "60606064f8ff9ff905c31c070676469dff0c002b8204faf9c75b240000000049454e44ae426082"
)


def test_two_pngs_gdal_wrote_decode_to_the_grids_they_were_written_from():
    image = codec.read_png(GDAL_PALETTE_PNG, max_decompressed_bytes=1 << 20)
    assert (image.width, image.height, image.bit_depth, image.colour_type, image.stride) == (
        5,
        3,
        8,
        3,
        5,
    )
    assert image.palette == ((0, 0, 0), (0, 0, 255), (0, 255, 0), (255, 0, 0))
    assert [image.samples(y) for y in range(3)] == [
        [0, 1, 2, 3, 0],
        [3, 2, 1, 0, 1],
        [1, 1, 2, 2, 3],
    ]
    grey = codec.read_png(GDAL_GREY16_PNG, max_decompressed_bytes=1 << 20)
    assert (grey.bit_depth, grey.colour_type, grey.palette, grey.ancillary) == (16, 0, None, ())
    assert [grey.samples(y) for y in range(2)] == [[0, 256, 65535, 1000], [40000, 7, 300, 65280]]


def chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def ihdr(width, height, depth=8, colour=0, interlace=0):
    return chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace))


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else b if pb <= pc else c


def filtered(rows: list[bytes], kinds: list[int], step: int) -> bytes:
    """The rows filtered by the given PNG filter types, written here from the PNG specification."""
    out = b""
    previous = bytes(len(rows[0]))
    for row, kind in zip(rows, kinds):
        line = bytearray([kind])
        for x, value in enumerate(row):
            a = row[x - step] if x >= step else 0
            b = previous[x]
            c = previous[x - step] if x >= step else 0
            predictor = (0, a, b, (a + b) >> 1, paeth(a, b, c))[kind]
            line.append((value - predictor) & 0xFF)
        out += bytes(line)
        previous = row
    return out


def png(width, height, rows, kinds, *, depth=8, colour=0, step=1, extra=b"", idat=None):
    data = zlib.compress(filtered(rows, kinds, step)) if idat is None else idat
    return (
        codec.PNG_SIGNATURE
        + ihdr(width, height, depth, colour)
        + extra
        + chunk(b"IDAT", data)
        + chunk(b"IEND", b"")
    )


ROWS = [bytes((x * 37 + y * 91) & 0xFF for x in range(6)) for y in range(5)]


def test_each_of_the_five_filters_is_undone_on_every_row():
    for kinds in ([0, 1, 2, 3, 4], [4, 3, 2, 1, 0], [2, 2, 2, 2, 2], [3, 4, 3, 4, 3]):
        image = codec.read_png(png(6, 5, ROWS, kinds), max_decompressed_bytes=1024)
        assert [bytes(image.samples(y)) for y in range(5)] == ROWS, kinds
    # Two octets a pixel (16-bit greyscale): the filters step over whole pixels.
    image = codec.read_png(
        png(3, 5, ROWS, [1, 3, 4, 1, 3], depth=16, step=2), max_decompressed_bytes=1024
    )
    assert image.samples(0) == list(struct.unpack(">3H", ROWS[0]))


def test_sub_octet_samples_and_ancillary_chunks_are_read():
    # 2-bit greyscale, five pixels a row: 0b00011011 0b10000000 -> 0, 1, 2, 3, 2.
    rows = [bytes([0b00011011, 0b10000000])]
    image = codec.read_png(
        png(5, 1, rows, [0], depth=2, extra=chunk(b"tEXt", b"k\x00v")), max_decompressed_bytes=64
    )
    assert image.samples(0) == [0, 1, 2, 3, 2]
    assert image.ancillary == (("tEXt", b"k\x00v"),)
    palette = chunk(b"PLTE", bytes([1, 2, 3, 4, 5, 6]))
    image = codec.read_png(
        png(8, 1, [bytes([0b01010101])], [0], depth=1, colour=3, extra=palette),
        max_decompressed_bytes=64,
    )
    assert (image.samples(0), image.palette) == ([0, 1, 0, 1, 0, 1, 0, 1], ((1, 2, 3), (4, 5, 6)))


GOOD = png(6, 5, ROWS, [0] * 5)


def flip_crc(octets: bytes, at: int) -> bytes:
    return octets[:at] + bytes([octets[at] ^ 0xFF]) + octets[at + 1 :]


PNG_REFUSALS = [
    (
        b"\x89PNG\r\n\x1a\x0b" + GOOD[8:],
        "not-a-png",
        "the payload does not open with the PNG signature",
    ),
    (flip_crc(GOOD, 32), "png-crc", "the IHDR chunk's CRC does not match"),
    (GOOD[:40], "png-truncated", "a chunk header runs past the end of the file"),
    (GOOD[:50], "png-truncated", "the IDAT chunk runs past the end of the file"),
    (GOOD[:-12], "png-truncated", "the file ends before IEND"),
    (GOOD + b"\x00", "octets-after-iend", "octets follow the IEND chunk"),
    (
        codec.PNG_SIGNATURE + chunk(b"IDAT", b"") + GOOD[8:],
        "png-chunk-order",
        "the first chunk is not IHDR",
    ),
    (GOOD[:33] + ihdr(6, 5) + GOOD[33:], "png-chunk-order", "IHDR appears twice"),
    (
        codec.PNG_SIGNATURE + ihdr(6, 5, interlace=1) + GOOD[33:],
        "interlaced",
        "an Adam7-interlaced image is not read",
    ),
    (
        codec.PNG_SIGNATURE + ihdr(6, 5, depth=3) + GOOD[33:],
        "bad-ihdr",
        "IHDR's colour type and bit depth are not a PNG pair",
    ),
    (
        codec.PNG_SIGNATURE + ihdr(0, 5) + GOOD[33:],
        "bad-ihdr",
        "IHDR states a width or height outside 1 to 2^31 - 1",
    ),
    (png(6, 5, ROWS, [0] * 5, colour=3), "bad-palette", "an indexed-colour image has no PLTE"),
    (
        png(6, 5, ROWS, [0] * 5, extra=chunk(b"PLTE", b"\x00\x00\x00")),
        "bad-palette",
        "a greyscale image carries a PLTE",
    ),
    (
        png(6, 5, ROWS, [0] * 5, colour=3, extra=chunk(b"PLTE", b"\x00\x00")),
        "bad-palette",
        "PLTE does not hold 1 to 256 RGB entries",
    ),
    (
        png(6, 5, ROWS, [0] * 5, extra=chunk(b"ABCD", b"")),
        "unknown-critical-chunk",
        "the critical chunk ABCD is not one this codec reads",
    ),
    (
        png(6, 5, ROWS, [0] * 5, extra=chunk(b"ab1d", b"")),
        "bad-chunk-type",
        "a chunk type is not four ASCII letters",
    ),
    (
        codec.PNG_SIGNATURE + ihdr(6, 5) + chunk(b"IEND", b""),
        "no-idat",
        "the file holds no IDAT chunk",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=zlib.compress(filtered(ROWS, [0] * 5, 1)) + b"\x00"),
        "octets-after-the-stream",
        "the image data holds octets after its stream",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=zlib.compress(filtered(ROWS, [0] * 5, 1) + b"\x00")),
        "png-data-past-its-rows",
        "the image data inflates past its rows",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=zlib.compress(filtered(ROWS, [0] * 5, 1)[:-1])),
        "png-short",
        "the image data inflates to fewer octets than its rows",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=zlib.compress(filtered(ROWS, [0] * 5, 1))[:-6]),
        "png-truncated",
        "the image data's zlib stream is not complete",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=b"no zlib here"),
        "bad-deflate",
        "the image data is not a zlib stream",
    ),
    (
        png(6, 5, ROWS, [0] * 5, idat=zlib.compress(b"\x05" + filtered(ROWS, [0] * 5, 1)[1:])),
        "bad-filter",
        "row 0 names filter type 5, not 0 to 4",
    ),
]


@pytest.mark.parametrize("octets,code,text", PNG_REFUSALS)
def test_each_png_rule_refuses_with_its_code_and_whole_text(octets, code, text):
    err = refusal(lambda: codec.read_png(octets, max_decompressed_bytes=1024))
    assert str(err) == f"{code}: {text}"


def test_png_rows_are_held_to_the_bound_before_any_octet_is_inflated():
    # 6 x 5 at 8 bits is 5 x (1 + 6) = 35 octets of filtered rows; a bound of 34 refuses them
    # with an IDAT that is not even a zlib stream, so nothing was inflated.
    octets = png(6, 5, ROWS, [0] * 5, idat=b"never inflated")
    err = refusal(lambda: codec.read_png(octets, max_decompressed_bytes=34))
    assert str(err) == (
        "png-past-the-decompression-bound: the image's rows inflate to more than 34 octets; "
        "refused before anything is inflated"
    )
    assert codec.read_png(GOOD, max_decompressed_bytes=35).height == 5


def test_idat_split_across_chunks_and_inflated_in_small_steps_is_one_stream(monkeypatch):
    data = zlib.compress(filtered(ROWS, [4, 3, 2, 1, 0], 1))
    split = b"".join(chunk(b"IDAT", data[i : i + 3]) for i in range(0, len(data), 3))
    octets = codec.PNG_SIGNATURE + ihdr(6, 5) + split + chunk(b"IEND", b"")
    monkeypatch.setattr(codec, "PNG_INFLATE_STEP", 2)
    image = codec.read_png(octets, max_decompressed_bytes=35)
    assert [bytes(image.samples(y)) for y in range(5)] == ROWS
    gap = codec.PNG_SIGNATURE + ihdr(6, 5) + chunk(b"IDAT", data[:5]) + chunk(b"tEXt", b"a\x00b")
    gap += chunk(b"IDAT", data[5:]) + chunk(b"IEND", b"")
    err = refusal(lambda: codec.read_png(gap, max_decompressed_bytes=35))
    assert str(err) == "png-chunk-order: the IDAT chunks are not consecutive"
