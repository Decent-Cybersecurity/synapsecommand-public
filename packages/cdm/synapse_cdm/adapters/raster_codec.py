"""The standard-library raster codec: classic TIFF and GeoTIFF structure, TIFF block decoding,
and PNG. Shared by `cog` (#30) and the IEM N0Q adapter that follows it; not an adapter itself, so
it registers nothing and declares nothing.

WHY A CODEC OF ITS OWN
----------------------
The libraries that read these formats elsewhere — rasterio, tifffile, numpy — need Python 3.12
or newer while this package supports 3.11, and none may become a dependency in this arc
(DECISIONS U-02, design-judge DJ-21). The formats themselves need only `struct` and `zlib`: a
classic TIFF is a header, a chain of image file directories and the blocks they point at; a PNG
is a signature and a chain of checksummed chunks (research-raster F4, F9, whose probe this module
starts from and does not import). Nothing here is ported from a decoder that exists elsewhere.

WHAT IS READ, AND HOW FAR
-------------------------
- `read_tiff` walks a CLASSIC TIFF (version 42, either byte order): every IFD of the chain, every
  entry of every IFD, each value decoded by its TIFF type. BigTIFF (version 43) is refused by
  name. Entries must be in ascending tag order with no tag twice (TIFF 6.0, "Image File
  Directory"), every value must lie inside the file, an IFD chain that returns to an IFD it has
  already read is refused, and the bounds the caller states (IFDs, entries, octets of one value)
  are checked before anything they bound is read.
- `block_layout` reads one IFD's raster layout: strips (tags 273/278/279) or tiles (322-325),
  never both, with exactly the number of blocks the image's size implies, each inside the file.
- `decode_block` decodes ONE block: compression none, LZW (5), Deflate (8 and the older 32946)
  and PackBits (32773), then the horizontal-differencing (2) or floating-point (3) predictor.
  Every other compression — JPEG, LERC, ZSTD, LZMA, WebP, JPEG 2000 among them — is refused by
  name. The block's size in samples is compared with the caller's decompression bound BEFORE any
  octet is inflated, and the inflation itself stops one octet past the block: a stream that would
  write more than its block is refused, never truncated.
- `geokeys` reads the GeoKey directory (34735) with its double (34736) and ASCII (34737)
  parameters, by the OGC GeoTIFF 1.1 key names.
- `read_png` reads a PNG: IHDR, PLTE, IDAT and IEND, the five filters, every chunk's CRC; the
  rows are compared with the caller's bound before inflating and inflated into a buffer of
  exactly their size. A caller may also bound the ancillary chunks it is handed, by count and by
  their data octets in all, and the walk refuses the first chunk past either before anything is
  inflated (added 2026-10-18 for the IEM N0Q adapter, whose file bound alone admits hundreds of
  thousands of empty chunks).

Every refusal is a `RasterRefused` (a `ValueError`, the class the conformance suite reads as a
refusal rather than a crash) whose `code` names the rule and whose text names the structure — the
IFD, the tag, the block, the chunk — and never quotes a value from the payload.
"""

from __future__ import annotations

import dataclasses
import math
import re
import struct
import zlib
from typing import Any

# -- refusals ------------------------------------------------------------------------------------


class RasterRefused(ValueError):
    """Octets this codec will not read. `code` names the rule; the text never quotes a value."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text

    def __reduce__(self):
        return (RasterRefused, (self.code, self.text))


# -- TIFF: types, tags, structure ----------------------------------------------------------------

#: TIFF 6.0 field types: number -> (name, octets per value, struct code or None).
TYPES: dict[int, tuple[str, int, str | None]] = {
    1: ("BYTE", 1, None),
    2: ("ASCII", 1, None),
    3: ("SHORT", 2, "H"),
    4: ("LONG", 4, "I"),
    5: ("RATIONAL", 8, "I"),
    6: ("SBYTE", 1, None),
    7: ("UNDEFINED", 1, None),
    8: ("SSHORT", 2, "h"),
    9: ("SLONG", 4, "i"),
    10: ("SRATIONAL", 8, "i"),
    11: ("FLOAT", 4, "f"),
    12: ("DOUBLE", 8, "d"),
}

#: The tags this codec names. A tag outside the table is read by its type all the same and kept
#: under `Tag<number>`: TIFF lets a writer add private tags, and a reader that refused every one
#: it does not use would refuse files for what they carry beside the image.
TAG_NAMES: dict[int, str] = {
    254: "NewSubfileType",
    256: "ImageWidth",
    257: "ImageLength",
    258: "BitsPerSample",
    259: "Compression",
    262: "PhotometricInterpretation",
    270: "ImageDescription",
    273: "StripOffsets",
    274: "Orientation",
    277: "SamplesPerPixel",
    278: "RowsPerStrip",
    279: "StripByteCounts",
    284: "PlanarConfiguration",
    305: "Software",
    306: "DateTime",
    317: "Predictor",
    320: "ColorMap",
    322: "TileWidth",
    323: "TileLength",
    324: "TileOffsets",
    325: "TileByteCounts",
    338: "ExtraSamples",
    339: "SampleFormat",
    33432: "Copyright",
    33550: "ModelPixelScaleTag",
    33922: "ModelTiepointTag",
    34264: "ModelTransformationTag",
    34735: "GeoKeyDirectoryTag",
    34736: "GeoDoubleParamsTag",
    34737: "GeoAsciiParamsTag",
    42112: "GDAL_METADATA",
    42113: "GDAL_NODATA",
}

#: The tags whose values are block positions or a colour table: arrays as long as the image has
#: blocks, read to locate and check the blocks and kept apart from the other values.
ARRAY_TAGS = frozenset({273, 279, 320, 324, 325})

#: The types each named tag may have. A named tag of another type is refused: a width stated as
#: a RATIONAL is not a width this codec can read without guessing.
_TAG_TYPES: dict[int, frozenset[int]] = {
    254: frozenset({4}),
    256: frozenset({3, 4}),
    257: frozenset({3, 4}),
    258: frozenset({3}),
    259: frozenset({3}),
    262: frozenset({3}),
    270: frozenset({2}),
    273: frozenset({3, 4}),
    274: frozenset({3}),
    277: frozenset({3}),
    278: frozenset({3, 4}),
    279: frozenset({3, 4}),
    284: frozenset({3}),
    305: frozenset({2}),
    306: frozenset({2}),
    317: frozenset({3}),
    320: frozenset({3}),
    322: frozenset({3, 4}),
    323: frozenset({3, 4}),
    324: frozenset({4}),
    325: frozenset({3, 4}),
    338: frozenset({3}),
    339: frozenset({3}),
    33432: frozenset({2}),
    33550: frozenset({12}),
    33922: frozenset({12}),
    34264: frozenset({12}),
    34735: frozenset({3}),
    34736: frozenset({12}),
    34737: frozenset({2}),
    42112: frozenset({2}),
    42113: frozenset({2}),
}

#: The named tags that hold exactly one value.
_SINGLE = frozenset({254, 256, 257, 259, 262, 274, 277, 278, 284, 317, 322, 323})

#: TIFF Compression codes, the four read and the ones refused by name.
COMPRESSIONS_READ = {1: "none", 5: "LZW", 8: "Deflate", 32946: "Deflate", 32773: "PackBits"}
COMPRESSIONS_REFUSED = {
    2: "CCITT modified Huffman RLE",
    3: "CCITT Group 3 fax",
    4: "CCITT Group 4 fax",
    6: "old-style JPEG",
    7: "JPEG",
    34712: "JPEG 2000",
    34887: "LERC",
    34925: "LZMA",
    50000: "ZSTD",
    50001: "WebP",
    50002: "JPEG XL",
}

#: (SampleFormat, BitsPerSample) -> (struct code, name). SampleFormat 1 unsigned, 2 signed,
#: 3 IEEE floating point (TIFF 6.0 Section 19).
SAMPLE_TYPES: dict[tuple[int, int], tuple[str, str]] = {
    (1, 8): ("B", "UInt8"),
    (1, 16): ("H", "UInt16"),
    (1, 32): ("I", "UInt32"),
    (2, 8): ("b", "Int8"),
    (2, 16): ("h", "Int16"),
    (2, 32): ("i", "Int32"),
    (3, 32): ("f", "Float32"),
    (3, 64): ("d", "Float64"),
}

PREDICTORS = {1: "none", 2: "horizontal differencing", 3: "floating point"}


@dataclasses.dataclass(frozen=True)
class Entry:
    """One IFD entry: its tag, its TIFF type, its count and its value decoded by type.

    ASCII is text (a list of texts when the field holds several NUL-separated strings); BYTE,
    SBYTE and UNDEFINED are lower-case hexadecimal; RATIONAL and SRATIONAL are [numerator,
    denominator] pairs; the other types are lists of numbers.
    """

    tag: int
    type: int
    count: int
    value: Any

    @property
    def name(self) -> str:
        return TAG_NAMES.get(self.tag, f"Tag{self.tag}")

    @property
    def type_name(self) -> str:
        return TYPES[self.type][0]


@dataclasses.dataclass(frozen=True)
class Ifd:
    offset: int
    next_offset: int
    entries: dict[int, Entry]


@dataclasses.dataclass(frozen=True)
class Tiff:
    byte_order: str
    first_ifd_offset: int
    ifds: list[Ifd]

    @property
    def endian(self) -> str:
        return "<" if self.byte_order == "II" else ">"


def read_tiff(
    octets: bytes,
    *,
    max_ifds: int,
    max_entries: int,
    max_value_octets: int,
    max_total_value_octets: int,
) -> Tiff:
    """Every IFD of a classic TIFF, each entry decoded by its type; nothing else is read.

    Two value bounds, because one is not enough: entries of many directories may all point at
    the same octets, so a file of a few hundred octets could ask for gigabytes of decoded values
    under a per-value bound alone. The total is counted before each value is decoded."""
    if len(octets) < 8:
        raise RasterRefused("truncated-header", "the file is shorter than the TIFF header")
    order = octets[:2]
    if order not in (b"II", b"MM"):
        raise RasterRefused("not-a-tiff", "the file does not open with II or MM")
    endian = "<" if order == b"II" else ">"
    (version,) = struct.unpack(endian + "H", octets[2:4])
    if version == 43:
        raise RasterRefused(
            "bigtiff", "the header states BigTIFF (version 43), which this codec does not read"
        )
    if version != 42:
        raise RasterRefused("not-a-tiff", "the header's version is not 42 (classic TIFF)")
    (first,) = struct.unpack(endian + "I", octets[4:8])
    if first == 0:
        raise RasterRefused("no-ifd", "the header points at no image file directory")
    ifds: list[Ifd] = []
    seen: set[int] = set()
    budget = [max_total_value_octets]
    offset = first
    while offset:
        if offset in seen:
            raise RasterRefused("ifd-loop", f"IFD {len(ifds)} points back at an IFD already read")
        if len(ifds) == max_ifds:
            raise RasterRefused(
                "too-many-ifds", f"the file chains more than {max_ifds} IFDs; refused there"
            )
        seen.add(offset)
        ifd = _read_ifd(octets, endian, offset, len(ifds), max_entries, max_value_octets, budget)
        ifds.append(ifd)
        offset = ifd.next_offset
    return Tiff(order.decode("ascii"), first, ifds)


def _read_ifd(
    octets: bytes,
    endian: str,
    offset: int,
    index: int,
    max_entries: int,
    max_value: int,
    budget: list[int],
) -> Ifd:
    where = f"IFD {index}"
    if offset < 8 or offset + 2 > len(octets):
        raise RasterRefused("ifd-past-the-end", f"{where} begins outside the file")
    (count,) = struct.unpack(endian + "H", octets[offset : offset + 2])
    if count == 0:
        raise RasterRefused("empty-ifd", f"{where} holds no entry")
    if count > max_entries:
        raise RasterRefused("too-many-entries", f"{where} states more than {max_entries} entries")
    end = offset + 2 + 12 * count
    if end + 4 > len(octets):
        raise RasterRefused("ifd-past-the-end", f"{where}'s entries run past the end of the file")
    entries: dict[int, Entry] = {}
    previous = -1
    for k in range(count):
        at = offset + 2 + 12 * k
        tag, kind, number = struct.unpack(endian + "HHI", octets[at : at + 8])
        label = TAG_NAMES.get(tag, f"Tag{tag}")
        if tag == previous:
            raise RasterRefused("repeated-tag", f"{where} states {label} twice")
        if tag < previous:
            raise RasterRefused(
                "tags-out-of-order", f"{where}: {label} follows a higher tag (TIFF 6.0 sorts them)"
            )
        previous = tag
        if kind not in TYPES:
            raise RasterRefused("unknown-tag-type", f"{where}: {label} has a type TIFF 6.0 lacks")
        if tag in _TAG_TYPES and kind not in _TAG_TYPES[tag]:
            raise RasterRefused(
                "bad-tag-type", f"{where}: {label} has the type {TYPES[kind][0]}, not its own"
            )
        if number == 0:
            raise RasterRefused("empty-tag", f"{where}: {label} states no value")
        if tag in _SINGLE and number != 1:
            raise RasterRefused("bad-tag-count", f"{where}: {label} states more than one value")
        size = TYPES[kind][1] * number
        if size > max_value:
            raise RasterRefused(
                "tag-past-its-bound",
                f"{where}: {label}'s value is longer than {max_value} octets",
            )
        budget[0] -= size
        if budget[0] < 0:
            raise RasterRefused(
                "values-past-their-bound",
                f"{where}: {label} takes the directories' values past their total bound",
            )
        if size <= 4:
            raw = octets[at + 8 : at + 8 + size]
        else:
            (start,) = struct.unpack(endian + "I", octets[at + 8 : at + 12])
            if start + size > len(octets):
                raise RasterRefused(
                    "tag-past-the-end", f"{where}: {label}'s value runs past the end of the file"
                )
            raw = octets[start : start + size]
        entries[tag] = Entry(tag, kind, number, _value(raw, kind, number, endian, where, label))
    (next_offset,) = struct.unpack(endian + "I", octets[end : end + 4])
    return Ifd(offset, next_offset, entries)


def _value(raw: bytes, kind: int, count: int, endian: str, where: str, label: str) -> Any:
    name, _, code = TYPES[kind]
    if name == "ASCII":
        if raw[-1:] != b"\x00":
            raise RasterRefused(
                "ascii-not-terminated", f"{where}: {label} does not end with NUL (TIFF 6.0)"
            )
        try:
            texts = raw[:-1].decode("utf-8").split("\x00")
        except UnicodeDecodeError:
            raise RasterRefused("not-utf8-text", f"{where}: {label} is not UTF-8 text") from None
        return texts[0] if len(texts) == 1 else texts
    if code is None:
        return raw.hex()
    if name in ("RATIONAL", "SRATIONAL"):
        flat = struct.unpack(endian + code * (2 * count), raw)
        return [[flat[i], flat[i + 1]] for i in range(0, len(flat), 2)]
    values = list(struct.unpack(endian + code * count, raw))
    if name in ("FLOAT", "DOUBLE") and not all(math.isfinite(v) for v in values):
        raise RasterRefused("non-finite-tag-value", f"{where}: {label} holds a non-finite number")
    return values


# -- TIFF: one IFD's raster layout ---------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Layout:
    """What decoding the blocks of one IFD needs, checked against the file."""

    width: int
    height: int
    samples: int
    planar: int
    bits: tuple[int, ...]
    sample_format: tuple[int, ...]
    compression: int
    predictor: int
    tiled: bool
    block_width: int
    block_height: int
    offsets: tuple[int, ...]
    counts: tuple[int, ...]

    @property
    def blocks_across(self) -> int:
        return -(-self.width // self.block_width)

    def block_window(self, index: int) -> tuple[int, int, int, int]:
        """(column, row, width, height) of the image a block covers, clipped to the image."""
        across = self.blocks_across
        column = (index % across) * self.block_width
        row = (index // across) * self.block_height
        return (
            column,
            row,
            min(self.block_width, self.width - column),
            min(self.block_height, self.height - row),
        )


def _one(ifd: Ifd, tag: int, default: int | None, where: str) -> int:
    entry = ifd.entries.get(tag)
    if entry is None:
        if default is None:
            raise RasterRefused("missing-tag", f"{where} states no {TAG_NAMES[tag]}")
        return default
    return entry.value[0]


def block_layout(ifd: Ifd, index: int, file_size: int) -> Layout:
    """The raster layout of IFD `index`, with every block inside the file."""
    where = f"IFD {index}"
    width = _one(ifd, 256, None, where)
    height = _one(ifd, 257, None, where)
    if width < 1 or height < 1:
        raise RasterRefused("empty-image", f"{where} states an image with no pixel")
    samples = _one(ifd, 277, 1, where)
    if samples < 1:
        raise RasterRefused("bad-samples", f"{where} states no sample per pixel")
    planar = _one(ifd, 284, 1, where)
    if planar not in (1, 2):
        raise RasterRefused(
            "bad-planar-configuration", f"{where}'s PlanarConfiguration is not 1 or 2"
        )
    bits = tuple(ifd.entries[258].value) if 258 in ifd.entries else (1,)
    formats = tuple(ifd.entries[339].value) if 339 in ifd.entries else (1,) * len(bits)
    if len(bits) != samples or len(formats) != samples:
        raise RasterRefused(
            "bad-tag-count", f"{where}: BitsPerSample and SampleFormat state one value a sample"
        )
    compression = _one(ifd, 259, 1, where)
    predictor = _one(ifd, 317, 1, where)
    strips = 273 in ifd.entries or 279 in ifd.entries
    tiles = any(tag in ifd.entries for tag in (322, 323, 324, 325))
    if strips and tiles:
        raise RasterRefused("strips-and-tiles", f"{where} states both strips and tiles")
    if tiles:
        block_width = _one(ifd, 322, None, where)
        block_height = _one(ifd, 323, None, where)
        if block_width < 16 or block_height < 16 or block_width % 16 or block_height % 16:
            raise RasterRefused(
                "bad-tile-size",
                f"{where}: TileWidth and TileLength are not multiples of 16 (TIFF 6.0 Section 15)",
            )
        offsets_tag, counts_tag = 324, 325
    else:
        block_width = width
        block_height = _one(ifd, 278, 2**32 - 1, where)
        if block_height < 1:
            raise RasterRefused("bad-rows-per-strip", f"{where}'s RowsPerStrip is 0")
        block_height = min(block_height, height)
        offsets_tag, counts_tag = 273, 279
    for tag in (offsets_tag, counts_tag):
        if tag not in ifd.entries:
            raise RasterRefused("missing-tag", f"{where} states no {TAG_NAMES[tag]}")
    offsets = tuple(ifd.entries[offsets_tag].value)
    counts = tuple(ifd.entries[counts_tag].value)
    blocks = -(-width // block_width) * -(-height // block_height) * (samples if planar == 2 else 1)
    if len(offsets) != blocks or len(counts) != blocks:
        raise RasterRefused(
            "block-count-disagrees",
            f"{where}: {TAG_NAMES[offsets_tag]} and {TAG_NAMES[counts_tag]} do not state one value "
            "for each block the image's size implies",
        )
    for number, (start, length) in enumerate(zip(offsets, counts)):
        if start == 0 and length == 0:
            continue  # a sparse block (GDAL's SPARSE_OK): no octet is written for it
        if start < 8 or length == 0 or start + length > file_size:
            raise RasterRefused(
                "block-past-the-end", f"{where}: block {number} does not lie inside the file"
            )
    return Layout(
        width,
        height,
        samples,
        planar,
        bits,
        formats,
        compression,
        predictor,
        tiles,
        block_width,
        block_height,
        offsets,
        counts,
    )


# -- TIFF: decoding one block --------------------------------------------------------------------


def block_octets(layout: Layout, index: int) -> int:
    """The decoded size of block `index` in octets: a tile is always whole (TIFF 6.0 Section 15
    pads the edge tiles), a strip is the rows it holds."""
    if layout.tiled:
        rows = layout.block_height
    else:
        rows = layout.block_window(index)[3]
    columns = layout.block_width
    per_pixel = sum(layout.bits) if layout.planar == 1 else layout.bits[0]
    return (columns * per_pixel + 7) // 8 * rows


def decode_block(
    octets: bytes, layout: Layout, index: int, byte_order: str, *, limit: int, where: str
) -> list:
    """Block `index` of a one-sample image as numbers, row by row, `block_width` per row.

    The decoded size is compared with `limit` before any octet is decompressed; the decompressor
    is then held to exactly that size. A sparse block (offset and count 0) is returned as `None`
    for the caller to fill, because only the caller knows its nodata value.
    """
    if layout.samples != 1:
        raise RasterRefused("more-than-one-sample", f"{where} states more than one sample a pixel")
    key = (layout.sample_format[0], layout.bits[0])
    if key not in SAMPLE_TYPES:
        raise RasterRefused(
            "unsupported-sample-format",
            f"{where}: SampleFormat and BitsPerSample are not one of the eight read",
        )
    if layout.compression not in COMPRESSIONS_READ:
        named = COMPRESSIONS_REFUSED.get(layout.compression)
        raise RasterRefused(
            "unsupported-compression",
            f"{where}: {named} compression is not read"
            if named
            else f"{where}: the Compression code is not one this codec reads",
        )
    if layout.predictor not in PREDICTORS:
        raise RasterRefused("unsupported-predictor", f"{where}: the Predictor is not 1, 2 or 3")
    code, _ = SAMPLE_TYPES[key]
    floating = layout.sample_format[0] == 3
    if layout.predictor == 2 and floating:
        raise RasterRefused(
            "unsupported-predictor",
            f"{where}: horizontal differencing is not read on floating-point samples",
        )
    if layout.predictor == 3 and not floating:
        raise RasterRefused(
            "unsupported-predictor",
            f"{where}: the floating-point predictor is stated for integer samples",
        )
    size = block_octets(layout, index)
    if size > limit:
        raise RasterRefused(
            "block-past-the-decompression-bound",
            f"{where}: block {index} decodes to more than {limit} octets; refused before "
            "anything is decompressed",
        )
    start, length = layout.offsets[index], layout.counts[index]
    if start == 0 and length == 0:
        return None
    data = octets[start : start + length]
    if layout.compression == 1:
        if len(data) != size:
            raise RasterRefused(
                "block-length-disagrees",
                f"{where}: uncompressed block {index} is not the octets its size implies",
            )
        raw = bytearray(data)
    elif layout.compression == 5:
        raw = lzw_decode(data, size, where=f"{where} block {index}")
    elif layout.compression in (8, 32946):
        raw = inflate(data, size, where=f"{where} block {index}")
    else:
        raw = packbits_decode(data, size, where=f"{where} block {index}")
    width = layout.block_width
    rows = size // ((width * layout.bits[0] + 7) // 8)
    step = layout.bits[0] // 8
    endian = "<" if byte_order == "II" else ">"
    if layout.predictor == 3:
        _undo_float_predictor(raw, width, rows, step)
        endian = ">"
    values = list(struct.unpack(f"{endian}{width * rows}{code}", bytes(raw)))
    if layout.predictor == 2:
        _undo_horizontal(values, width, rows, layout.bits[0], code)
    return values


def _undo_horizontal(values: list, width: int, rows: int, bits: int, code: str) -> None:
    """TIFF 6.0 Section 14: each sample is the difference from the one to its left, modulo the
    sample's width; a signed sample is accumulated as its unsigned bit pattern."""
    modulus = 1 << bits
    signed = code in "bhi"
    half = modulus >> 1
    for row in range(rows):
        base = row * width
        running = values[base] % modulus
        for i in range(base + 1, base + width):
            running = (running + values[i]) % modulus
            values[i] = running
        if signed:
            for i in range(base, base + width):
                value = values[i] % modulus
                values[i] = value - modulus if value >= half else value


def _undo_float_predictor(raw: bytearray, width: int, rows: int, step: int) -> None:
    """The floating-point predictor (Adobe Photoshop TIFF Technical Note 3): within a row the
    octets are differenced one from the next, and the octets of the samples are stored as
    planes, the most significant plane first. Undone in place; the samples come out big-endian
    whatever the file's byte order."""
    span = width * step
    for row in range(rows):
        base = row * span
        for i in range(base + 1, base + span):
            raw[i] = (raw[i] + raw[i - 1]) & 0xFF
        planes = bytes(raw[base : base + span])
        for plane in range(step):
            raw[base + plane : base + span : step] = planes[plane * width : (plane + 1) * width]


def inflate(data: bytes, size: int, *, where: str) -> bytearray:
    """A zlib stream (TIFF Deflate) inflated to exactly `size` octets, never one more."""
    stream = zlib.decompressobj()
    try:
        out = stream.decompress(data, size + 1)
    except zlib.error:
        raise RasterRefused("bad-deflate", f"{where} is not a zlib stream") from None
    if len(out) > size:
        raise RasterRefused(
            "block-inflates-past-its-size", f"{where} inflates past the octets its size implies"
        )
    if not stream.eof:
        raise RasterRefused("block-short", f"{where}'s zlib stream ends before it is complete")
    if stream.unused_data:
        raise RasterRefused("octets-after-the-stream", f"{where} holds octets after its stream")
    if len(out) < size:
        raise RasterRefused("block-short", f"{where} decodes to fewer octets than its size")
    return bytearray(out)


def lzw_decode(data: bytes, size: int, *, where: str) -> bytearray:
    """TIFF LZW (TIFF 6.0 Section 13): codes of 9 to 12 bits, most significant bit first, the
    width growing one code early; Clear 256, EndOfInformation 257. The pre-6.0 variant, whose
    first octets are 0x00 and an odd octet, is refused by name."""
    if len(data) >= 2 and data[0] == 0 and data[1] & 1:
        raise RasterRefused("old-style-lzw", f"{where} is pre-TIFF 6.0 LZW, which is not read")
    out = bytearray()
    table = [bytes((i,)) for i in range(256)] + [b"", b""]
    width, buffer, held, position, previous = 9, 0, 0, 0, None
    while True:
        while held < width:
            if position == len(data):
                if len(out) == size:
                    return out
                raise RasterRefused("block-short", f"{where}'s LZW codes end before its size")
            buffer = (buffer << 8) | data[position]
            position += 1
            held += 8
        held -= width
        code = (buffer >> held) & ((1 << width) - 1)
        buffer &= (1 << held) - 1
        if code == 256:
            del table[258:]
            width, previous = 9, None
            continue
        if code == 257:
            if position < len(data):
                raise RasterRefused(
                    "octets-after-the-stream", f"{where} holds octets after its EndOfInformation"
                )
            break
        if previous is None:
            if code > 255:
                raise RasterRefused("bad-lzw-code", f"{where} names a code no table holds")
            entry = table[code]
        else:
            if code < len(table):
                entry = table[code]
                table.append(previous + entry[:1])
            elif code == len(table):
                entry = previous + previous[:1]
                table.append(entry)
            else:
                raise RasterRefused("bad-lzw-code", f"{where} names a code no table holds")
            if len(table) > 4096:
                raise RasterRefused("lzw-table-full", f"{where} grows its table past 4096 codes")
        if len(out) + len(entry) > size:
            raise RasterRefused(
                "block-inflates-past-its-size", f"{where} decodes past the octets its size implies"
            )
        out += entry
        previous = entry
        if len(table) >= (1 << width) - 1 and width < 12:
            width += 1
    if len(out) < size:
        raise RasterRefused("block-short", f"{where}'s LZW codes end before its size")
    return out


def packbits_decode(data: bytes, size: int, *, where: str) -> bytearray:
    """PackBits (TIFF 6.0 Section 9): a header octet n then n + 1 literal octets (n < 128), one
    octet repeated 257 - n times (n > 128), or nothing (n = 128)."""
    out = bytearray()
    i = 0
    while i < len(data):
        if len(out) == size:
            raise RasterRefused("octets-after-the-stream", f"{where} holds octets past its size")
        n = data[i]
        i += 1
        if n < 128:
            if i + n + 1 > len(data):
                raise RasterRefused("packbits-truncated", f"{where}'s literal run is cut short")
            out += data[i : i + n + 1]
            i += n + 1
        elif n > 128:
            if i == len(data):
                raise RasterRefused("packbits-truncated", f"{where}'s repeat run is cut short")
            out += data[i : i + 1] * (257 - n)
            i += 1
        if len(out) > size:
            raise RasterRefused(
                "block-inflates-past-its-size", f"{where} decodes past the octets its size implies"
            )
    if len(out) < size:
        raise RasterRefused("block-short", f"{where} decodes to fewer octets than its size")
    return out


# -- GeoTIFF: the key directory -----------------------------------------------------------------

#: OGC GeoTIFF 1.1 key names (19-008r4, Annex). 2048, 3072 and 4096 are spelled as 1.1 spells
#: them; 1.0 called them GeographicTypeGeoKey, ProjectedCSTypeGeoKey and VerticalCSTypeGeoKey.
GEOKEY_NAMES: dict[int, str] = {
    1024: "GTModelTypeGeoKey",
    1025: "GTRasterTypeGeoKey",
    1026: "GTCitationGeoKey",
    2048: "GeodeticCRSGeoKey",
    2049: "GeodeticCitationGeoKey",
    2050: "GeodeticDatumGeoKey",
    2051: "PrimeMeridianGeoKey",
    2052: "GeogLinearUnitsGeoKey",
    2053: "GeogLinearUnitSizeGeoKey",
    2054: "GeogAngularUnitsGeoKey",
    2055: "GeogAngularUnitSizeGeoKey",
    2056: "EllipsoidGeoKey",
    2057: "EllipsoidSemiMajorAxisGeoKey",
    2058: "EllipsoidSemiMinorAxisGeoKey",
    2059: "EllipsoidInvFlatteningGeoKey",
    2060: "GeogAzimuthUnitsGeoKey",
    2061: "PrimeMeridianLongitudeGeoKey",
    2062: "GeogTOWGS84GeoKey",
    3072: "ProjectedCRSGeoKey",
    3073: "ProjectedCitationGeoKey",
    3074: "ProjectionGeoKey",
    3075: "ProjMethodGeoKey",
    3076: "ProjLinearUnitsGeoKey",
    3077: "ProjLinearUnitSizeGeoKey",
    3078: "ProjStdParallel1GeoKey",
    3079: "ProjStdParallel2GeoKey",
    3080: "ProjNatOriginLongGeoKey",
    3081: "ProjNatOriginLatGeoKey",
    3082: "ProjFalseEastingGeoKey",
    3083: "ProjFalseNorthingGeoKey",
    3084: "ProjFalseOriginLongGeoKey",
    3085: "ProjFalseOriginLatGeoKey",
    3086: "ProjFalseOriginEastingGeoKey",
    3087: "ProjFalseOriginNorthingGeoKey",
    3088: "ProjCenterLongGeoKey",
    3089: "ProjCenterLatGeoKey",
    3090: "ProjCenterEastingGeoKey",
    3091: "ProjCenterNorthingGeoKey",
    3092: "ProjScaleAtNatOriginGeoKey",
    3093: "ProjScaleAtCenterGeoKey",
    3094: "ProjAzimuthAngleGeoKey",
    3095: "ProjStraightVertPoleLongGeoKey",
    3096: "ProjRectifiedGridAngleGeoKey",
    4096: "VerticalGeoKey",
    4097: "VerticalCitationGeoKey",
    4098: "VerticalDatumGeoKey",
    4099: "VerticalUnitsGeoKey",
}


@dataclasses.dataclass(frozen=True)
class GeoKeys:
    version: int
    revision: int
    minor_revision: int
    keys: dict[int, Any]


def geokeys(ifd: Ifd, where: str = "IFD 0") -> GeoKeys | None:
    """The GeoKey directory of an IFD, or `None` when it states none."""
    directory = ifd.entries.get(34735)
    if directory is None:
        return None
    shorts = directory.value
    if len(shorts) < 4 or len(shorts) != 4 + 4 * shorts[3]:
        raise RasterRefused(
            "bad-geokey-directory", f"{where}: the GeoKey directory's length is not its key count's"
        )
    version, revision, minor = shorts[0], shorts[1], shorts[2]
    if version != 1 or revision != 1 or minor not in (0, 1):
        raise RasterRefused(
            "unsupported-geokey-version",
            f"{where}: the GeoKey directory is not version 1, revision 1.0 or 1.1",
        )
    doubles = ifd.entries[34736].value if 34736 in ifd.entries else []
    ascii_entry = ifd.entries.get(34737)
    text = ascii_entry.value if ascii_entry is not None else ""
    if isinstance(text, list):
        raise RasterRefused(
            "bad-geokey-ascii", f"{where}: GeoAsciiParamsTag holds more than one string"
        )
    keys: dict[int, Any] = {}
    previous = -1
    for k in range(shorts[3]):
        key, location, count, value = shorts[4 + 4 * k : 8 + 4 * k]
        label = GEOKEY_NAMES.get(key, f"GeoKey{key}")
        if key <= previous:
            raise RasterRefused(
                "geokeys-out-of-order", f"{where}: {label} is not in ascending key order"
            )
        previous = key
        if location == 0:
            if count != 1:
                raise RasterRefused("bad-geokey", f"{where}: {label} is inline with a count not 1")
            keys[key] = value
        elif location == 34737:
            piece = text[value : value + count]
            if len(piece) != count or not piece.endswith("|"):
                raise RasterRefused(
                    "bad-geokey-ascii",
                    f"{where}: {label}'s text is not a |-terminated slice of GeoAsciiParamsTag",
                )
            keys[key] = piece[:-1]
        elif location == 34736:
            piece = doubles[value : value + count]
            if len(piece) != count:
                raise RasterRefused(
                    "bad-geokey", f"{where}: {label}'s doubles lie outside GeoDoubleParamsTag"
                )
            keys[key] = list(piece)
        else:
            raise RasterRefused(
                "bad-geokey", f"{where}: {label} points at a tag the GeoKey directory does not name"
            )
    return GeoKeys(version, revision, minor, keys)


# -- PNG -----------------------------------------------------------------------------------------

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Colour type -> (channels, bit depths allowed), PNG Third Edition, IHDR.
PNG_COLOUR_TYPES: dict[int, tuple[int, tuple[int, ...]]] = {
    0: (1, (1, 2, 4, 8, 16)),
    2: (3, (8, 16)),
    3: (1, (1, 2, 4, 8)),
    4: (2, (8, 16)),
    6: (4, (8, 16)),
}

_CHUNK_TYPE = re.compile(rb"[A-Za-z]{4}")

#: The most octets one inflate step may write: the rows are inflated into their own buffer, so
#: nothing but that buffer grows with the image.
PNG_INFLATE_STEP = 1 << 20


@dataclasses.dataclass(frozen=True)
class PngImage:
    """A decoded PNG: the header, the palette and the unfiltered rows, `stride` octets each."""

    width: int
    height: int
    bit_depth: int
    colour_type: int
    palette: tuple[tuple[int, int, int], ...] | None
    ancillary: tuple[tuple[str, bytes], ...]
    stride: int
    rows: bytearray

    def samples(self, y: int) -> list[int]:
        """Row `y` as samples (channel values or palette indices) at the image's bit depth."""
        row = self.rows[y * self.stride : (y + 1) * self.stride]
        channels = PNG_COLOUR_TYPES[self.colour_type][0]
        count = self.width * channels
        if self.bit_depth == 8:
            return list(row[:count])
        if self.bit_depth == 16:
            return list(struct.unpack(f">{count}H", bytes(row[: 2 * count])))
        per_octet = 8 // self.bit_depth
        mask = (1 << self.bit_depth) - 1
        out = []
        for i in range(count):
            octet = row[i // per_octet]
            shift = 8 - self.bit_depth * (i % per_octet + 1)
            out.append((octet >> shift) & mask)
        return out


def read_png(
    octets: bytes,
    *,
    max_decompressed_bytes: int,
    max_ancillary_chunks: int | None = None,
    max_ancillary_octets: int | None = None,
) -> PngImage:
    """A PNG's header, palette and unfiltered rows. Interlaced images are refused by name.

    `max_ancillary_chunks` and `max_ancillary_octets`, when given, bound the ancillary chunks kept
    for the caller: the chunk that would make one more than the count, or more data octets in all
    than the total, is refused in the walk (`too-many-ancillary-chunks`,
    `ancillary-past-the-bound`), so nothing is inflated and no list longer than the bound is
    built. None leaves that count or total unbounded, as it was before the bounds existed."""
    if octets[:8] != PNG_SIGNATURE:
        raise RasterRefused("not-a-png", "the payload does not open with the PNG signature")
    position = 8
    header = None
    palette = None
    ancillary: list[tuple[str, bytes]] = []
    ancillary_octets = 0
    idat: list[bytes] = []
    idat_closed = False
    ended = False
    while position < len(octets):
        if ended:
            raise RasterRefused("octets-after-iend", "octets follow the IEND chunk")
        if position + 8 > len(octets):
            raise RasterRefused("png-truncated", "a chunk header runs past the end of the file")
        (length,) = struct.unpack(">I", octets[position : position + 4])
        kind = octets[position + 4 : position + 8]
        if _CHUNK_TYPE.fullmatch(kind) is None:
            raise RasterRefused("bad-chunk-type", "a chunk type is not four ASCII letters")
        name = kind.decode("ascii")
        if length > 0x7FFFFFFF or position + 12 + length > len(octets):
            raise RasterRefused("png-truncated", f"the {name} chunk runs past the end of the file")
        body = octets[position + 8 : position + 8 + length]
        (crc,) = struct.unpack(">I", octets[position + 8 + length : position + 12 + length])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise RasterRefused("png-crc", f"the {name} chunk's CRC does not match")
        position += 12 + length
        if header is None and name != "IHDR":
            raise RasterRefused("png-chunk-order", "the first chunk is not IHDR")
        if name == "IHDR":
            if header is not None:
                raise RasterRefused("png-chunk-order", "IHDR appears twice")
            header = _ihdr(body)
        elif name == "PLTE":
            if palette is not None or idat:
                raise RasterRefused("png-chunk-order", "PLTE appears twice or after IDAT")
            if length % 3 or not 3 <= length <= 768:
                raise RasterRefused("bad-palette", "PLTE does not hold 1 to 256 RGB entries")
            palette = tuple(tuple(body[i : i + 3]) for i in range(0, length, 3))
        elif name == "IDAT":
            if idat_closed:
                raise RasterRefused("png-chunk-order", "the IDAT chunks are not consecutive")
            idat.append(body)
        elif name == "IEND":
            if length:
                raise RasterRefused("bad-iend", "IEND carries data")
            ended = True
        elif kind[0:1].isupper():
            raise RasterRefused(
                "unknown-critical-chunk", f"the critical chunk {name} is not one this codec reads"
            )
        else:
            if max_ancillary_chunks is not None and len(ancillary) >= max_ancillary_chunks:
                raise RasterRefused(
                    "too-many-ancillary-chunks",
                    f"the file holds more than {max_ancillary_chunks} ancillary chunks",
                )
            ancillary_octets += length
            if max_ancillary_octets is not None and ancillary_octets > max_ancillary_octets:
                raise RasterRefused(
                    "ancillary-past-the-bound",
                    f"the ancillary chunks hold more than {max_ancillary_octets} data octets in "
                    "all",
                )
            ancillary.append((name, bytes(body)))
        if idat and name != "IDAT":
            idat_closed = True
    if not ended:
        raise RasterRefused("png-truncated", "the file ends before IEND")
    if not idat:
        raise RasterRefused("no-idat", "the file holds no IDAT chunk")
    width, height, depth, colour = header
    if colour == 3 and palette is None:
        raise RasterRefused("bad-palette", "an indexed-colour image has no PLTE")
    if colour in (0, 4) and palette is not None:
        raise RasterRefused("bad-palette", "a greyscale image carries a PLTE")
    if palette is not None and colour == 3 and len(palette) < 1:
        raise RasterRefused("bad-palette", "the palette is empty")
    channels = PNG_COLOUR_TYPES[colour][0]
    stride = (width * channels * depth + 7) // 8
    filtered = height * (1 + stride)
    if filtered > max_decompressed_bytes:
        raise RasterRefused(
            "png-past-the-decompression-bound",
            f"the image's rows inflate to more than {max_decompressed_bytes} octets; refused "
            "before anything is inflated",
        )
    rows = _png_inflate(idat, filtered)
    _png_unfilter(rows, height, stride, max(1, channels * depth // 8))
    out = bytearray(height * stride)
    for y in range(height):
        out[y * stride : (y + 1) * stride] = rows[y * (stride + 1) + 1 : (y + 1) * (stride + 1)]
    return PngImage(width, height, depth, colour, palette, tuple(ancillary), stride, out)


def _ihdr(body: bytes) -> tuple[int, int, int, int]:
    if len(body) != 13:
        raise RasterRefused("bad-ihdr", "IHDR is not 13 octets")
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if not (1 <= width <= 0x7FFFFFFF and 1 <= height <= 0x7FFFFFFF):
        raise RasterRefused("bad-ihdr", "IHDR states a width or height outside 1 to 2^31 - 1")
    if colour not in PNG_COLOUR_TYPES or depth not in PNG_COLOUR_TYPES[colour][1]:
        raise RasterRefused("bad-ihdr", "IHDR's colour type and bit depth are not a PNG pair")
    if compression != 0 or filtering != 0:
        raise RasterRefused("bad-ihdr", "IHDR's compression or filter method is not 0")
    if interlace == 1:
        raise RasterRefused("interlaced", "an Adam7-interlaced image is not read")
    if interlace != 0:
        raise RasterRefused("bad-ihdr", "IHDR's interlace method is not 0 or 1")
    return width, height, depth, colour


def _png_inflate(idat: list[bytes], size: int) -> bytearray:
    """The IDAT stream inflated into a buffer of exactly `size` octets, never one more."""
    out = bytearray(size)
    filled = 0
    stream = zlib.decompressobj()

    def take(piece: bytes) -> None:
        nonlocal filled
        if filled + len(piece) > size:
            raise RasterRefused("png-data-past-its-rows", "the image data inflates past its rows")
        out[filled : filled + len(piece)] = piece
        filled += len(piece)

    try:
        for chunk in idat:
            pending = chunk
            while pending:
                take(stream.decompress(pending, min(PNG_INFLATE_STEP, size - filled + 1)))
                pending = stream.unconsumed_tail
                if stream.eof and (pending or stream.unused_data):
                    raise RasterRefused(
                        "octets-after-the-stream", "the image data holds octets after its stream"
                    )
        while not stream.eof:
            piece = stream.decompress(b"", min(PNG_INFLATE_STEP, size - filled + 1))
            if not piece:
                break
            take(piece)
    except zlib.error:
        raise RasterRefused("bad-deflate", "the image data is not a zlib stream") from None
    if not stream.eof:
        raise RasterRefused("png-truncated", "the image data's zlib stream is not complete")
    if filled != size:
        raise RasterRefused("png-short", "the image data inflates to fewer octets than its rows")
    return out


def _png_unfilter(rows: bytearray, height: int, stride: int, step: int) -> None:
    """The five filter types of PNG's filter method 0, undone in place, row by row."""
    for y in range(height):
        base = y * (stride + 1)
        kind = rows[base]
        start = base + 1
        above = start - (stride + 1)
        if kind == 0:
            continue
        if kind == 1:
            for i in range(start + step, start + stride):
                rows[i] = (rows[i] + rows[i - step]) & 0xFF
        elif kind == 2:
            if y:
                for i in range(start, start + stride):
                    rows[i] = (rows[i] + rows[i - stride - 1]) & 0xFF
        elif kind == 3:
            for x in range(stride):
                left = rows[start + x - step] if x >= step else 0
                up = rows[above + x] if y else 0
                rows[start + x] = (rows[start + x] + ((left + up) >> 1)) & 0xFF
        elif kind == 4:
            for x in range(stride):
                left = rows[start + x - step] if x >= step else 0
                up = rows[above + x] if y else 0
                corner = rows[above + x - step] if y and x >= step else 0
                estimate = left + up - corner
                pa, pb, pc = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
                predictor = left if pa <= pb and pa <= pc else up if pb <= pc else corner
                rows[start + x] = (rows[start + x] + predictor) & 0xFF
        else:
            raise RasterRefused("bad-filter", f"row {y} names filter type {kind}, not 0 to 4")
