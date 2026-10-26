"""The preview: an 8-bit display derivative of one image segment, kept apart from the analytic
samples it is drawn from.

WHAT IT DRAWS
-------------
A preview never replaces, alters or shadows the source or a decoded window: it is a separate PNG
derivative, at most 1024 pixels on its longer side, of one image segment alone. No graphic or text
segment is ever composed onto it, so every preview is `segment_only`. Which bands it shows is
decided once, by the first rule that matches: an explicit selection of one or three bands made by
the caller; the one narrow lookup-table case (a single indexed band and three tables); any other
image carrying a lookup table, shown as a numeric band 0 with the colour interpretation reported
unresolved; a one-band MONO image; an RGB or MULTI image whose band descriptors name exactly one
R, one G and one B; and otherwise a numeric band 0, again reported unresolved. The first three
bands are never assumed to be red, green and blue.

THE ARITHMETIC
--------------
All of it is integer arithmetic. A sample v of ABPP significant bits is shown linearly over the
representable range, `((v - lo) * 255 + span // 2) // span` with `lo` the smallest representable
value (negative for signed samples) and `span = 2**ABPP - 1`: no histogram and no data-dependent
stretch. The size keeps the aspect ratio, rounds half up and never enlarges; each output pixel
takes the source sample at `min(src - 1, ((2 * dst + 1) * src) // (2 * dst_size))` on each axis,
the exact form of `floor((dst + 0.5) * src / dst_size)`.

THE FILE
--------
The PNG is written here with the standard library: the signature, one IHDR, one IDAT holding the
zlib stream of the filtered rows (filter 0 on every row), and IEND, with no ancillary chunk, so the
octets depend only on the pixels and on the zlib build, which the provenance names.
"""

from __future__ import annotations

import array
import struct
import sys
import zlib
from dataclasses import dataclass

MAX_SIZE = 1024
ALGORITHM_LINEAR = "sc-imagery-linear-nearest/1"
ALGORITHM_LUT = "sc-imagery-lut-nearest/1"
MAPPING_LINEAR = "linear over the representable significant-bit range"
MAPPING_LUT = "the index band's three lookup tables as red, green and blue"
DOWNSAMPLING = "nearest neighbour, source index floor((dst+0.5)*src/dst_size) capped at src-1"
UNRESOLVED = "COLOUR_INTERPRETATION_UNRESOLVED"
UNRESOLVED_MESSAGE = "colour interpretation is not resolved; a numeric band preview is shown"
LUT_INDEX_MESSAGE = "a sample index is not smaller than the number of LUT entries"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _int(value: object) -> bool:
    return type(value) is int


@dataclass(frozen=True, slots=True)
class RenderingSpec:
    """What a caller may choose: the longer side's cap (1 to 1024) and either no bands, for the
    automatic rules, or an explicit selection of one band or three distinct bands (shown as red,
    green and blue in the order given). Whether the bands exist is the window decoder's check."""

    max_size: int = MAX_SIZE
    bands: tuple[int, ...] | None = None

    def __post_init__(self) -> None:
        if not _int(self.max_size) or not 1 <= self.max_size <= MAX_SIZE:
            raise ValueError("max_size is an int from 1 to 1024")
        bands = self.bands
        if bands is None:
            return
        if (
            type(bands) is not tuple
            or len(bands) not in (1, 3)
            or not all(_int(band) and band >= 0 for band in bands)
            or len(set(bands)) != len(bands)
        ):
            raise ValueError("bands is None, one band index, or three distinct band indexes")


@dataclass(frozen=True, slots=True)
class Band:
    irepband: str
    nluts: int
    neluts: int


@dataclass(frozen=True, slots=True)
class ImageFacts:
    """What the selection rules read of one image, taken from the job's own parse."""

    index: int
    irep: str
    pvtype: str
    abpp: int
    ncols: int
    nrows: int
    native: bool
    bands: tuple[Band, ...]
    irep_offset: int
    lut_offset: int | None


@dataclass(frozen=True, slots=True)
class Selection:
    algorithm: str
    selection: str
    bands: tuple[int, ...]
    unresolved: bool


def facts_of(image) -> ImageFacts:
    """The facts of an adapter image record."""
    first = image.bands[0]
    return ImageFacts(
        index=image.index,
        irep=image.irep,
        pvtype=image.pvtype,
        abpp=image.abpp,
        ncols=image.ncols,
        nrows=image.nrows,
        native=image.pixel_status == "native_supported",
        bands=tuple(Band(band.irepband, band.nluts, band.neluts) for band in image.bands),
        irep_offset=image.fields["IREP"].offset,
        lut_offset=None if first.lut is None else first.lut.offset,
    )


def select(facts: ImageFacts, spec: RenderingSpec) -> Selection:
    """The first matching selection rule."""
    if spec.bands is not None:
        return Selection(ALGORITHM_LINEAR, "explicit", spec.bands, False)
    bands = facts.bands
    if (
        facts.irep == "RGB/LUT"
        and len(bands) == 1
        and bands[0].irepband == "LU"
        and bands[0].nluts == 3
        and facts.pvtype == "INT"
        and facts.native
    ):
        return Selection(ALGORITHM_LUT, "lut", (0,), False)
    if facts.irep == "RGB/LUT" or any(band.nluts > 0 for band in bands):
        return Selection(ALGORITHM_LINEAR, "automatic", (0,), True)
    if facts.irep == "MONO" and len(bands) == 1:
        return Selection(ALGORITHM_LINEAR, "automatic", (0,), False)
    if facts.irep in ("RGB", "MULTI"):
        found = [[i for i, band in enumerate(bands) if band.irepband == c] for c in "RGB"]
        if all(len(indexes) == 1 for indexes in found):
            return Selection(ALGORITHM_LINEAR, "automatic", tuple(i[0] for i in found), False)
    return Selection(ALGORITHM_LINEAR, "automatic", (0,), True)


# --------------------------------------------------------------------------- the arithmetic


def display_value(value: int, abpp: int, signed: bool) -> int:
    """The 8-bit display value of one interpreted sample, linear over its representable range."""
    low = -(1 << (abpp - 1)) if signed else 0
    span = (1 << abpp) - 1
    return ((value - low) * 255 + span // 2) // span


def preview_size(ncols: int, nrows: int, cap: int = MAX_SIZE) -> tuple[int, int]:
    """The preview's width and height: unchanged up to the cap, else the longer side at the cap
    and the other rounded half up, never below 1."""
    longer = max(ncols, nrows)
    if longer <= cap:
        return ncols, nrows
    width = max(1, (2 * ncols * cap + longer) // (2 * longer))
    height = max(1, (2 * nrows * cap + longer) // (2 * longer))
    return width, height


def source_index(dst: int, src: int, dst_size: int) -> int:
    return min(src - 1, ((2 * dst + 1) * src) // (2 * dst_size))


def lut_tables(raw: bytes, image) -> tuple[bytes, ...]:
    """Band 0's lookup tables, in file order."""
    band = image.bands[0]
    data = raw[band.lut.offset : band.lut.offset + band.lut.length]
    return tuple(data[k * band.neluts : (k + 1) * band.neluts] for k in range(band.nluts))


def _elements(window) -> array.array | bytes:
    """The window's elements as numbers: the bytes themselves for 8 bits, else 16-bit values."""
    if window.itemsize == 1:
        if window.dtype == "uint8":
            return window.data
        return array.array("b", window.data)
    values = array.array("h" if window.dtype == "int16" else "H")
    values.frombytes(window.data)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def lut_index_ok(window, neluts: int) -> bool:
    """Whether every sample of the window is an index below the table length: checked over the
    whole band before anything is drawn, not only over the samples the size picks."""
    return max(_elements(window)) < neluts


def render(window, facts: ImageFacts, chosen: Selection, max_size: int, tables=()):
    """(width, height, channels, rows) of the preview of a whole-image window decoded with the
    chosen bands, each row `width * channels` octets."""
    width, height = preview_size(facts.ncols, facts.nrows, max_size)
    columns = [source_index(x, facts.ncols, width) for x in range(width)]
    elements = _elements(window)
    plane = facts.nrows * facts.ncols
    signed = window.dtype in ("int8", "int16")
    if chosen.selection == "lut":
        channels = 3
        maps = [table.__getitem__ for table in tables]
        planes = [0, 0, 0]
    else:
        channels = len(chosen.bands)
        maps = [lambda v: display_value(v, facts.abpp, signed)] * channels
        planes = list(range(channels))
    # One 256-entry table per channel turns an 8-bit row into display octets in C.
    small = window.itemsize == 1
    if small and chosen.selection == "lut":
        # Every index was checked below the table length, so the padding is never read.
        translations = [(bytes(table) + bytes(256))[:256] for table in tables]
    elif small:
        # The mapping is defined only over what ABPP bits represent, and only those values occur
        # in an interpreted window: a table entry for any other octet would lie outside 0..255.
        # The bounds are checked first, so the zero entries left for those octets are never read.
        low = -(1 << (facts.abpp - 1)) if signed else 0
        high = low + (1 << facts.abpp) - 1
        if min(elements) < low or max(elements) > high:
            raise ValueError("a sample lies outside the range its significant bits represent")
        stored = range(256) if not signed else [b - 256 if b >= 128 else b for b in range(256)]
        translations = [
            bytes(maps[k](v) if low <= v <= high else 0 for v in stored) for k in range(channels)
        ]
    rows = []
    for y in range(height):
        row_start = source_index(y, facts.nrows, height) * facts.ncols
        parts = []
        for k in range(channels):
            base = planes[k] * plane + row_start
            if small:
                picked = bytes(window.data[base + x] for x in columns)
                parts.append(picked.translate(translations[k]))
            else:
                parts.append(bytes(maps[k](elements[base + x]) for x in columns))
        if channels == 1:
            rows.append(parts[0])
        else:
            row = bytearray(width * 3)
            for k in range(3):
                row[k::3] = parts[k]
            rows.append(bytes(row))
    return width, height, channels, rows


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def png_bytes(width: int, height: int, channels: int, rows) -> bytes:
    """An 8-bit greyscale (one channel) or RGB (three channels) PNG of the given rows."""
    if channels not in (1, 3) or len(rows) != height:
        raise ValueError("a preview has one or three channels and one row per line")
    if any(len(row) != width * channels for row in rows):
        raise ValueError("every row holds width times channels octets")
    header = struct.pack(">IIBBBBB", width, height, 8, 0 if channels == 1 else 2, 0, 0, 0)
    stream = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", stream) + _chunk(b"IEND", b"")


def software() -> dict:
    """The versions a derivative's identity folds in: a different zlib build is a different
    derivative, because its octets may differ."""
    from synapse_cdm.version import PACKAGE_VERSION

    from synapse_imagery._version import __version__

    return {
        "synapse_imagery": __version__,
        "synapse_cdm": PACKAGE_VERSION,
        "zlib": zlib.ZLIB_RUNTIME_VERSION,
    }


def parameters(algorithm: str, max_size: int) -> dict:
    mapping = MAPPING_LUT if algorithm == ALGORITHM_LUT else MAPPING_LINEAR
    return {"mapping": mapping, "downsampling": DOWNSAMPLING, "max_size": max_size}
