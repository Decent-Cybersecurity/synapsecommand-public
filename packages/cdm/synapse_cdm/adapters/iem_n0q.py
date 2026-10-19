"""`iem_n0q`, #31 in the ordinal table: one IEM NEXRAD N0Q composite PNG -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
ONE file: the PNG the Iowa Environmental Mesonet archives every five minutes as
`n0q_YYYYMMDDHHMM.png`, a 12200 x 5400 image of 8-bit palette indices (research-raster F1), of at
most 8 MiB (DECISIONS L-09: the archive's files are 1 to 4 MB, its listing of 2026-09-11 shows
2M). `to_cdm` takes the file's octets, or its parsed twin (`<name>.parsed.json`: the octets as
`wire_hex` and everything the file states), which is held to be exactly what its own `wire_hex`
decodes to. The archive's `.wld` beside each PNG is NEVER a payload and is never read: the grid is
a product constant (below), and a world file in a fixture directory would itself be replayed as a
payload (research-raster F11).

THE GRID IS A PRODUCT CONSTANT, CHECKED AGAINST THE HEADER
---------------------------------------------------------
A PNG states its size and nothing about where it lies. IEM's composite has had one grid since
2014-08-08: 12200 columns by 5400 rows of 0.005 degree in EPSG:4326, whose world file reads
`0.005 / 0.0 / 0.0 / -0.005 / -126.0 / 50.0` (F1, F11). This module declares that grid
(`WIDTH`, `HEIGHT`, `CELL_DEGREES`, `WORLD_FILE`, `GRID_BASIS`) and holds every file to it: IHDR
must state 12200 x 5400, bit depth 8 and colour type 3 (indexed colour), read and refused before a
single octet of image data is inflated. A world file's last two terms are the CENTRE of the
north-west cell (the world-file definition GDAL and Esri document, F11); IEM's pages do not say
which they mean, so the reading taken here is recorded in `GRID_BASIS`: the image's outline lies
half a cell further out, from 126.0025 W 50.0025 N to 65.0025 W 23.0025 N.

VALUES
------
Palette index 0 is "missing"; index i is (i - 65) / 2 dBZ (IEM's raster catalogue, product
`composite_n0q`: index 1 is -32 dBZ, 65 is 0, 66 is 0.5, 255 is 95). IEM's two pages disagree on the
top of the ramp — the documentation's caption says 90 dBZ, the catalogue's table ends at 95 — and
this module emits what the formula gives (index 255 -> 95.0), the disagreement recorded in the pin
and in a declared limitation. The colours of the palette are carried in the residual and read for
nothing; an index past the palette is refused, as the PNG specification requires. The 65,880,000
values stay in the file, BY REFERENCE: the locator (the whole image as one window), the shape,
the stored type, the encoding, the transform as `scale` 0.5 and `offset` -32.5, index 0 as the fill,
and a summary in dBZ — the cell count, the missing count, the least and greatest value. A grid of
65,880,000 cells is never inline (`MAX_INLINE_VALUES` is 4096).

TIME
----
A PNG states no observation time. The only time is the archive file name's slot (UTC, minutes
divisible by five, F3), which is not part of the payload: the caller supplies it as `slot`, an
`InjectedTime` whose basis is IEM's ("IEM archive filename slot, UTC, composite nominal time",
`SLOT_BASIS`), and a slot off the five-minute grid is refused when the adapter is constructed. It
is the composite's NOMINAL time — IEM builds it from the radars' products within fifteen minutes
of it, and no radar's scan time is recoverable from the image — so `observed_at`,
`validity.effective` (an instant: both ends) and `SourceRef.observed_at` are the slot, stated by
the caller. The `tEXt` chunk `gentime` is IEM's generation clock — 11:58:24Z for a 12:00 slot in the
file the design record read, before the slot it names — and goes to
`product_version.production_time_verbatim`, verbatim and unparsed, never to a key ending `_at`.

WHAT ONE FILE BECOMES
---------------------
One `ENVIRONMENTAL_OBSERVATION` `Event` carrying `gridded-field/1`, `product_class: observation`
(a composite of radar measurements, not a model product). Its geometry is the constant outline as
a WGS84 Polygon (the grid is latitude/longitude already, so nothing is transformed). No site
`Entity`: the composite is many radars, none of which the image names. Its identifier derives from
the slot, followed by the caller's `source_hash` digest when it gives one, because IEM re-publishes
a slot's file under the same name (gap report HM-07) and only the digest tells two apart.

WHAT IS REFUSED
---------------
A file that is not a PNG; an IHDR of any other size, depth or colour type; an interlaced image; a
chunk whose CRC fails, out of order or past the end; an unknown critical chunk; image data that
does not inflate to exactly its rows, or would inflate past them; an index past the palette; a
`tEXt` chunk whose keyword or text breaks the PNG rules; a `gentime` that is blank, longer than
1024 characters or stated twice; more than 64 ancillary chunks, or more than 1 MiB of data octets
in them all (`ANCILLARY_BOUNDS_BASIS`, added 2026-10-18 at the 3.6.0 release: the file bound alone
admits about 540 000 empty `tEXt` chunks, which a review measured at about 749 MB resident). A
refusal is an `IemN0qRefused` (`ValueError`) whose code names
the rule and whose text names the structure, never a value from the payload.
"""

from __future__ import annotations

import datetime as _dt
import re
import struct
import zlib
from typing import Any

from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import raster_codec as codec
from synapse_cdm.geo import Polygon
from synapse_cdm.lossless import Mapping
from synapse_cdm.manifest import (
    AdapterMetadata,
    Capabilities,
    ClaimStatus,
    Direction,
    Evidence,
    FormatRef,
    LicenseClass,
    LimitBasis,
    Limitation,
    LimitKind,
    Limits,
    Maturity,
    MaturityLevel,
    Residual as ResidualStance,
    UnknownFields,
    WireBinding,
)
from synapse_cdm.models import CDMBase, Period, Residual, SourceHash, SourceId, TemporalValidity
from synapse_cdm.observation_contracts import (
    ArraySummary,
    GriddedField,
    InjectedTime,
    Measurement,
    ProductVersion,
    Quantity,
    RasterLocator,
    RasterWindow,
    TimeInputs,
    TimeSystem,
    UnitRef,
    ValuesByReference,
    by_reference_limitation,
    observation_event,
)
from synapse_cdm.observation_contracts import Grid as GridBlock

#: `source.system` on every object and the system of every identifier.
SYSTEM = "IEM_N0Q"
#: The residual namespace and `SourceRef.format_name`, read from the declaration below.
FORMAT_NAME = "IEM NEXRAD N0Q composite PNG (W3C PNG, IEM product composite_n0q)"
FORMAT_VERSION = (
    "Portable Network Graphics (PNG) Specification (Third Edition), W3C Recommendation 24 June "
    "2025; IEM composite_n0q at 12200 x 5400 cells, the grid IEM has published since 2014-08-08"
)

# -- the product constant (research-raster F1, F11) -----------------------------------------------

WIDTH = 12200
HEIGHT = 5400
BIT_DEPTH = 8
#: PNG colour type 3: each cell a palette index.
COLOUR_TYPE = 3
CELL_DEGREES = 0.005
#: The archive's world file, its six terms in the file's order: x cell size, the two rotation
#: terms, y cell size, then the x and y coordinates of the north-west cell's CENTRE.
WORLD_FILE = (0.005, 0.0, 0.0, -0.005, -126.0, 50.0)
#: The outline of the cells: the north-west cell's centre moved half a cell out, and 12200 and 5400
#: cells of 0.005 degree from there (-126.0025 + 61 = -65.0025; 50.0025 - 27 = 23.0025).
WEST, NORTH, EAST, SOUTH = -126.0025, 50.0025, -65.0025, 23.0025
GRID_BASIS = (
    "the IEM N0Q composite grid, a product constant: 12200 x 5400 cells of 0.005 degree in "
    "EPSG:4326 since 2014-08-08 (IEM's composite documentation, research-raster F1), the archive's "
    "world file 0.005 / 0.0 / 0.0 / -0.005 / -126.0 / 50.0 (F1, F11) read as the centre of the "
    "north-west cell, the world-file definition GDAL and Esri document; IEM's pages do not state "
    "the registration, so the half-cell reading is this module's and the outline runs from "
    "126.0025 W 50.0025 N to 65.0025 W 23.0025 N. The .wld is never read: the PNG's IHDR is held "
    "to the constant instead"
)

# -- values ----------------------------------------------------------------------------------------

#: Palette index 0 marks a missing cell.
MISSING_INDEX = 0
#: Index i is (i - ZERO_INDEX) * DBZ_STEP dBZ: 0.5 * i - 32.5.
ZERO_INDEX = 65
DBZ_STEP = 0.5
SCALE = 0.5
OFFSET = -32.5
SLOT_BASIS = "IEM archive filename slot, UTC, composite nominal time"
#: The longest `gentime` text carried: a stamp is twenty characters; 1024 is the tree's cap for a
#: caller's text (`InjectedTime.basis`).
MAX_GENTIME = 1024

# -- bounds (DECISIONS L-09; each declared with its basis below) ---------------------------------

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_DECOMPRESSED_BYTES = 80 * 1024 * 1024
#: The rows the constant grid inflates to: one filter octet and 12200 index octets a row.
FILTERED_OCTETS = HEIGHT * (1 + WIDTH)
#: The twin nests four containers deep (a palette entry inside the palette); dis7's bound.
MAX_DEPTH = 16

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_iem_n0q_adapter.py::"

#: The most ancillary chunks, and the most data octets in them all, one file may carry (the 3.6.0
#: release round, 2026-10-18, R7 review F-01). `Limits` has no field for either, so the two bounds
#: and their basis are declared here, in the form a declared limit takes (readsb_trace's
#: MAX_POINTS, grib2's MAX_GRID_POINTS).
MAX_ANCILLARY_CHUNKS = 64
MAX_ANCILLARY_OCTETS = 1024 * 1024
ANCILLARY_BOUNDS_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "Every ancillary chunk is kept in the residual, a tEXt chunk as its keyword and text and "
        "any other as its octets in hexadecimal, and the 8 MiB file bound alone does not bound "
        "them: an in-bound file of about 540 000 empty tEXt chunks was accepted and cost about "
        "749 MB resident through synapse-decode (R7 review F-01, 2026-10-18). The design record "
        "knows one ancillary chunk in an archive file, the tEXt gentime (its N0Q row), and PNG "
        "states no limit on their number. 64 chunks (`MAX_ANCILLARY_CHUNKS`) and 1 MiB "
        "(1 048 576 data octets in them all, `MAX_ANCILLARY_OCTETS`, `adapters/iem_n0q.py`) sit "
        "far above one chunk of at most 1024 characters, in the measure of cog's structure "
        "bounds (128 entries a directory, 4 MiB of values in all, D-R6-13). " + _CAP
    ),
    enforced_at=(
        "`raster_codec.read_png`, handed both bounds by this module's `decode`: the chunk walk "
        "refuses the chunk that would be the 65th ancillary one (`too-many-ancillary-chunks`) or "
        "take their data octets past 1 MiB (`ancillary-past-the-bound`) as it meets it, before "
        "anything is inflated and before the residual's list of chunks is built"
    ),
    test=_TESTS + "test_the_ancillary_chunks_are_held_to_their_count_and_octet_bounds",
)

TWIN_KEYS = ("wire_hex", "header", "palette", "ancillary", "index_summary")
_HEX = re.compile(r"[0-9a-f]*")

# -- the transformations, by what they read ------------------------------------------------------

T_SLOT = (
    "slot: observed_at, validity.effective's two ends and SourceRef.observed_at are the caller's "
    "archive file-name slot, the composite's nominal time, which the PNG does not state"
)
T_GRID = (
    "grid: the footprint and the grid block are the IEM N0Q product constant, IHDR checked against "
    "it, the outline half a cell outside the world file's cell centres; no transformation, the grid "
    "being latitude/longitude"
)
T_VALUES = (
    "index_summary: palette index 0 is missing and index i is (i - 65) / 2 dBZ; the summary's "
    "least and greatest values are the least and greatest non-zero index so transformed"
)
T_WIRE = (
    "derived: the twin's wire_hex is the file's octets; the object is decoded from them and they "
    "are not copied, the file being identified by source_hash"
)


class IemN0qRefused(ValueError):
    """A file this module will not translate. `code` names the rule; the text names the
    structure, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text

    def __reduce__(self):
        return (IemN0qRefused, (self.code, self.text))


def dbz(index: int) -> float | None:
    """The reflectivity a palette index stands for, or `None` for index 0 (missing)."""
    if type(index) is not int or not 0 <= index <= 255:
        raise ValueError("a palette index is an int from 0 to 255")
    if index == MISSING_INDEX:
        return None
    return (index - ZERO_INDEX) * DBZ_STEP


def checked_slot(slot: Any) -> InjectedTime:
    """The caller's slot, refused unless it is an `InjectedTime` on IEM's five-minute grid."""
    if not isinstance(slot, InjectedTime):
        raise TypeError("slot is an InjectedTime(instant, basis)")
    instant = slot.instant
    if instant.minute % 5 or instant.second or instant.microsecond:
        raise IemN0qRefused(
            "slot-off-the-five-minute-grid",
            "an archive slot is a whole minute divisible by five (YYYYMMDDHHMM, minutes modulo 5); "
            "the instant supplied is not one",
        )
    return slot


# -- the PNG ---------------------------------------------------------------------------------------


def _product_header(octets: bytes) -> dict | None:
    """IHDR held to the product constant before anything is inflated, or `None` when the file
    does not open with a well-formed IHDR — the codec then refuses it, by its own rule, before it
    inflates anything."""
    if octets[:8] != codec.PNG_SIGNATURE or len(octets) < 33:
        return None
    length, kind = struct.unpack(">I4s", octets[8:16])
    body = octets[16:29]
    if (
        length != 13
        or kind != b"IHDR"
        or zlib.crc32(kind + body) != int.from_bytes(octets[29:33], "big")
    ):
        return None
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", body
    )
    if (width, height) != (WIDTH, HEIGHT):
        raise IemN0qRefused(
            "not-the-n0q-grid",
            f"IHDR states an image size other than the product's {WIDTH} x {HEIGHT}",
        )
    if (depth, colour) != (BIT_DEPTH, COLOUR_TYPE):
        raise IemN0qRefused(
            "not-the-n0q-grid",
            "IHDR states a bit depth or colour type other than the product's 8-bit indexed colour "
            "(colour type 3)",
        )
    return {
        "width": width,
        "height": height,
        "bit_depth": depth,
        "colour_type": colour,
        "compression_method": compression,
        "filter_method": filtering,
        "interlace_method": interlace,
    }


def _keyword_octet(octet: int) -> bool:
    return 32 <= octet <= 126 or 161 <= octet <= 255


def _ancillary(name: str, body: bytes) -> dict:
    """An ancillary chunk as the twin holds it: a `tEXt` chunk as its keyword and text, read as
    PNG Third Edition 11.3.3 defines them; any other as its octets in hexadecimal, read for
    nothing (a `tIME` chunk included: a modification clock is no observation time)."""
    if name != "tEXt":
        return {"chunk": name, "octets_hex": body.hex()}
    keyword, sep, text = body.partition(b"\x00")
    if (
        not sep
        or not 1 <= len(keyword) <= 79
        or not all(_keyword_octet(o) for o in keyword)
        or keyword[:1] == b" "
        or keyword[-1:] == b" "
        or b"  " in keyword
    ):
        raise IemN0qRefused(
            "bad-text-chunk",
            "a tEXt chunk's keyword is not 1 to 79 printable Latin-1 characters, without leading, "
            "trailing or doubled spaces, followed by a NUL",
        )
    if b"\x00" in text:
        raise IemN0qRefused("bad-text-chunk", "a tEXt chunk's text holds a NUL")
    return {"chunk": "tEXt", "keyword": keyword.decode("latin-1"), "text": text.decode("latin-1")}


def decode(octets: bytes) -> dict:
    """Everything an N0Q PNG states that this module reads, as its twin holds it (no `wire_hex`)."""
    header = _product_header(octets)
    try:
        image = codec.read_png(
            octets,
            max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
            max_ancillary_chunks=MAX_ANCILLARY_CHUNKS,
            max_ancillary_octets=MAX_ANCILLARY_OCTETS,
        )
    except codec.RasterRefused as refusal:
        raise IemN0qRefused(refusal.code, refusal.text) from None
    if header is None:
        # `_product_header` returns None only for an opening the codec refuses; reaching here
        # would mean the two readings of IHDR disagree, which is a defect, not a payload's fault.
        raise RuntimeError("iem_n0q: the codec read a PNG whose IHDR this module could not read")
    ancillary = [_ancillary(name, body) for name, body in image.ancillary]
    gentimes = [a["text"] for a in ancillary if a.get("keyword") == "gentime"]
    if len(gentimes) > 1:
        raise IemN0qRefused("gentime-twice", "the file states more than one tEXt gentime chunk")
    if gentimes and (not gentimes[0].strip() or len(gentimes[0]) > MAX_GENTIME):
        raise IemN0qRefused(
            "bad-gentime",
            f"the tEXt gentime chunk's text is blank or longer than {MAX_GENTIME} characters",
        )
    # The rows are WIDTH octets each (8-bit indices): every cell is one octet. Deleting the
    # index-0 octets in C leaves only the cells that state a value.
    present = image.rows.translate(None, bytes([MISSING_INDEX]))
    count = WIDTH * HEIGHT
    least = min(present) if present else None
    greatest = max(present) if present else None
    if greatest is not None and greatest >= len(image.palette):
        raise IemN0qRefused(
            "index-past-the-palette",
            "a cell's index lies past the last entry of PLTE, which the PNG specification makes "
            "an error",
        )
    return {
        "header": header,
        "palette": [list(entry) for entry in image.palette],
        "ancillary": ancillary,
        "index_summary": {
            "count": count,
            "missing_count": count - len(present),
            "min": least,
            "max": greatest,
        },
    }


def twin_of(octets: bytes) -> dict:
    """The parsed twin of a file: its octets as `wire_hex` and everything it states."""
    return {"wire_hex": bytes(octets).hex(), **decode(bytes(octets))}


def _same(a: Any, b: Any) -> bool:
    """Equal, and of the same JSON type at every level: 1, 1.0 and True are three values."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def _from_twin(document: dict) -> dict:
    if set(document) != set(TWIN_KEYS):
        raise IemN0qRefused(
            "not-a-twin", "a dict is the file's twin, exactly: " + ", ".join(TWIN_KEYS)
        )
    wire = document["wire_hex"]
    if (
        not isinstance(wire, str)
        or len(wire) > 2 * MAX_INPUT_BYTES
        or len(wire) % 2
        or _HEX.fullmatch(wire) is None
    ):
        raise IemN0qRefused(
            "bad-wire-hex",
            f"wire_hex is not lower-case hexadecimal of at most {MAX_INPUT_BYTES} octets",
        )
    decoded = decode(bytes.fromhex(wire))
    for key in decoded:
        if not _same(document[key], decoded[key]):
            raise IemN0qRefused(
                "twin-disagrees", f"the twin's {key} is not what its wire_hex decodes to"
            )
    return decoded


def _residual(key: str) -> Mapping:
    return Mapping(to=f"#0:residual.data.{key}", kind="residual")


FIXTURE_SLOT = InjectedTime("2026-04-29T06:05:00Z", SLOT_BASIS)


class IemN0qAdapter(Adapter):
    """One IEM N0Q composite PNG in; one Event out."""

    name = "iem_n0q"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration. `OPEN`: the PNG Third Edition is published under the W3C
    #: Software and Document License 2023, which permits copying, modifying and distributing for
    #: any purpose (research-raster F4); IEM's pages, which define the product's grid and values,
    #: are cited by URL and never carried, and IEM states its data public domain (F2).
    metadata = AdapterMetadata(
        id="iem_n0q",
        name="IEM NEXRAD N0Q composite reader",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter iem_n0q` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "the header, the palette, every ancillary chunk and the index summary a structured "
            "residual, the octets that hold the values a declared limitation) with no LOST leaf on "
            "any parsed twin. L4 is NOT declared: this adapter is ingest-only, so the roundtrip "
            "check is inapplicable rather than passed (ARCHITECTURE.md §3.6, rule 4), and a rung "
            "passed vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "IEM NEXRAD N0Q composite PNG (n0q_YYYYMMDDHHMM.png), 12200 x 5400 8-bit palette "
                "indices, IHDR held to the product constant, every chunk's CRC checked, the image "
                "data inflated and the five filter types undone, index 0 missing and index i "
                "(i - 65) / 2 dBZ; one ENVIRONMENTAL_OBSERVATION Event (gridded-field/1) at the "
                "caller's archive slot, the values by reference with a dBZ summary",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=1,
                max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
                max_parse_seconds=None,
                absent_because={
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, the chunk walk is linear in the octets read, the image data inflates "
                    "into exactly the 65,885,400 octets of its rows and each filter is undone in "
                    "one pass, and the conformance suite's parser worker kills a decode that "
                    "overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "the 2026-09-11 archive listing shows 2M PNGs (HM-01 N0Q row), and "
                            "research-raster F1 reads the archive's files as 1 to 4 MB; PNG states "
                            "no file size beyond a chunk's 2^31 - 1 octets. 8 MiB (8 388 608 "
                            "octets, `MAX_INPUT_BYTES`, `adapters/iem_n0q.py`) is DECISIONS L-09's "
                            "bound for one PNG, twice the largest. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module reads the signature"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_decompressed_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "IHDR 12200 x 5400 paletted = 65,880,000 B of indices plus 5400 "
                            "filter octets, 65,885,400 B of filtered rows (research-raster F4), "
                            "the most the product constant admits. 80 MiB (83 886 080 octets, "
                            "`MAX_DECOMPRESSED_BYTES`, `adapters/iem_n0q.py`) is DECISIONS L-09's "
                            "bound above it. " + _CAP
                        ),
                        enforced_at=(
                            "`IemN0qAdapter`'s `decode` holds IHDR to 12200 x 5400 x 8-bit "
                            "indexed before anything is inflated, so the rows are exactly "
                            "65,885,400 octets; `raster_codec.read_png` compares them with the "
                            "bound, inflates into a buffer of exactly that size with "
                            "`zlib.decompressobj` and `max_length`, and refuses the first octet "
                            "past it (`png-data-past-its-rows`) before it is kept"
                        ),
                        test=_TESTS + "test_the_image_data_is_held_to_its_rows_and_the_bound",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "One object a file: one composite at one slot is one field "
                            "(design-judge DJ-09's one product object a file). " + _CAP
                        ),
                        enforced_at="`IemN0qAdapter.to_cdm` returns exactly one object",
                        test=_TESTS + "test_every_fixture_becomes_exactly_one_event",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets are never JSON; the dict form, the parsed twin, nests "
                            "three containers (a palette entry inside the palette). 16 "
                            "(`MAX_DEPTH`, `adapters/iem_n0q.py`) is the dis7 envelope's bound. "
                            + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on a dict before this class's "
                            "`to_cdm` runs"
                        ),
                        test=_TESTS + "test_a_twin_past_the_depth_bound_is_refused_before_decode",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the dict form is held to be exactly what its own wire_hex decodes to, so a key "
                "injected into a twin is refused `not-a-twin` or `twin-disagrees`; on the wire, an "
                "ancillary chunk this module does not read is kept in the residual (a tEXt chunk "
                "as its keyword and text, any other as its octets), at most 64 of them and 1 MiB "
                "of their data octets in all (`too-many-ancillary-chunks` and "
                "`ancillary-past-the-bound` past either; ANCILLARY_BOUNDS_BASIS, since "
                "2026-10-18), and an unknown critical chunk is refused"
            ),
        ),
        limitations=[
            by_reference_limitation(
                ["wire_hex"],
                notes=(
                    "the 65,880,000 palette indices are the PNG's image data inside the file's "
                    "octets, which the twin holds as wire_hex; they are decoded for the summary "
                    "and stay in the file, identified by SourceRef.source_hash when the caller "
                    "gives it"
                ),
            ),
            Limitation(
                id="product-constant-grid",
                summary="the grid is the IEM N0Q product constant — 12200 x 5400 cells of 0.005 "
                "degree in EPSG:4326, the archive's world file read as the centre of the "
                "north-west cell, so the outline runs from 126.0025 W 50.0025 N to 65.0025 W "
                "23.0025 N — and the .wld beside an archive PNG is not read: a PNG of any other "
                "size, bit depth or colour type is refused. Which registration IEM means is not "
                "stated on its pages; the half-cell reading is this module's",
                unsupported_paths=[],
            ),
            Limitation(
                id="time-is-the-caller-slot",
                summary="a PNG states no observation time: observed_at is the archive file "
                "name's slot (UTC, minutes divisible by five), the composite's nominal time, "
                "which the caller supplies with its basis (`IemN0qAdapter(slot=InjectedTime("
                "instant, basis))`); no radar's scan time is recoverable from the image. The tEXt "
                "gentime chunk is IEM's generation clock and is carried verbatim as "
                "product_version.production_time_verbatim, never as a time",
                unsupported_paths=[],
            ),
            Limitation(
                id="ramp-top-disagreement",
                summary="index i is read as (i - 65) / 2 dBZ, so index 255 is 95.0 dBZ; IEM's "
                "composite documentation captions the ramp as -32 to 90 dBZ while its raster "
                "catalogue's table ends at 95, and the formula's value is emitted, not either "
                "page's ceiling",
                unsupported_paths=[],
            ),
            Limitation(
                id="identity-from-the-slot",
                summary="an object's id derives from the slot, followed by the caller's "
                "`source_hash` digest when it gives one: IEM re-publishes a slot's file under "
                "the same name, and without the digest two files of one slot share an id",
                unsupported_paths=[],
            ),
            Limitation(
                id="evidence-availability",
                summary="the evidence RECORD for this adapter is not IN the distribution: "
                "`evidence/` is untracked and unpackaged, CI generates the set on every "
                "run, and the release pipeline generates the records for every shipped "
                "adapter and attaches them to the GitHub Release of the version it "
                "publishes. `evidence.available` is true because every published "
                "distribution that carries this adapter has that Release, so its records "
                "are retrievable by a third party; it says nothing about what the wheel "
                "contains",
            ),
        ],
        limitations_empty_reason=None,
        residual=ResidualStance.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=True),
    )

    TRANSFORMS: dict[str, str] = {"wire_hex": T_WIRE}

    #: The ledger. One object a file, so `#0` is the object. Every key of the twin but the octets
    #: is parked whole in the object's residual, at its own path.
    MAPPINGS = {
        "header": _residual("header"),
        "palette": _residual("palette"),
        "ancillary": _residual("ancillary"),
        "index_summary": _residual("index_summary"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        slot: InjectedTime,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
    ) -> None:
        """`slot` is the archive file name's slot (`n0q_YYYYMMDDHHMM`), parsed by the caller and
        handed in with its basis, because a file name is not a payload; `source_hash` the SHA-256
        of the file as the caller read it, and `frame_sha256` that of the octets handed over when
        they are not the file (a container was unwrapped). All are values the caller computed and
        constructor arguments, so all are in the determinism tuple."""
        super().__init__(clock, synthetic=synthetic)
        self._slot = checked_slot(slot)
        if source_hash is not None:
            source_hash = SourceHash.model_validate(source_hash)
            if source_hash.algorithm != "sha256" or not re.fullmatch(
                "[0-9a-f]{64}", source_hash.value
            ):
                raise ValueError("source_hash is a sha256 digest of 64 lower-case hex digits")
        if frame_sha256 is not None and (
            type(frame_sha256) is not str or not re.fullmatch("[0-9a-f]{64}", frame_sha256)
        ):
            raise ValueError("frame_sha256 is 64 lower-case hexadecimal digits")
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256

    @classmethod
    def fixture_instance(cls, clock=None, *, synthetic=True):
        """The packaged fixtures' context: the slot 2026-04-29T06:05:00Z with IEM's basis. It is
        the context of those fixtures only (`Adapter.fixture_instance`)."""
        return cls(clock=clock, synthetic=synthetic, slot=FIXTURE_SLOT)

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One file -> [one Event]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = decode(bytes(raw))
        elif isinstance(raw, dict):
            document = _from_twin(raw)
        else:
            raise IemN0qRefused(
                "unsupported-input",
                "a file is handed over as its octets or as its twin in a dict; text and other "
                "types are not taken",
            )
        return [self._event(document)]

    # -- translation -----------------------------------------------------------------------------

    def _identity(self) -> str:
        text = f"N0Q composite {self._slot.rendered}"
        if self._source_hash is not None:
            text += f" sha256 {self._source_hash.value}"
        return text

    def _event(self, document: dict) -> CDMBase:
        slot: _dt.datetime = self._slot.instant
        indices = document["index_summary"]
        least, greatest = indices["min"], indices["max"]
        locator = RasterLocator(
            kind="raster",
            frame_sha256=self._frame_sha256,
            window=RasterWindow(column=0, row=0, width=WIDTH, height=HEIGHT),
        )
        gentime = next(
            (a["text"] for a in document["ancillary"] if a.get("keyword") == "gentime"), None
        )
        contract = GriddedField(
            contract="gridded-field/1",
            product_class="observation",
            product_version=(
                ProductVersion(production_time_verbatim=gentime) if gentime is not None else None
            ),
            time=TimeInputs(
                source_time_system=TimeSystem(
                    name="UTC", stated_by="caller", basis=self._slot.basis
                )
            ),
            locator=locator,
            quality_flags=[],
            quality_flags_basis=(
                "the PNG states no quality flag; palette index 0 marks a missing cell, counted in "
                "the summary's missing_count"
            ),
            quantity=Quantity(
                name="composite reflectivity (N0Q)",
                code="composite_n0q",
                namespace="IEM raster catalogue (rasters.php?rid=2)",
            ),
            unit=UnitRef(unit="dBZ", unit_namespace="IEM raster catalogue (rasters.php?rid=2)"),
            grid=GridBlock(
                namespace="IEM N0Q composite product constant (research-raster F1, F11)",
                template="EPSG:4326",
                shape=[HEIGHT, WIDTH],
                scanning_mode="row 0 is the northernmost, column 0 the westernmost",
                cell_size=[
                    Measurement(value=CELL_DEGREES, unit="degree", unit_namespace="EPSG:4326"),
                    Measurement(value=CELL_DEGREES, unit="degree", unit_namespace="EPSG:4326"),
                ],
                parameters={
                    "world_file": {
                        "x_cell_size": WORLD_FILE[0],
                        "rotation_y": WORLD_FILE[1],
                        "rotation_x": WORLD_FILE[2],
                        "y_cell_size": WORLD_FILE[3],
                        "north_west_cell_centre_x": WORLD_FILE[4],
                        "north_west_cell_centre_y": WORLD_FILE[5],
                    },
                    "registration": "the world file's last two terms are the centre of the "
                    "north-west cell; the outline lies half a cell outside them",
                },
            ),
            values=ValuesByReference(
                mode="reference",
                locator=locator,
                shape=[HEIGHT, WIDTH],
                dtype="8-bit palette index (PNG colour type 3)",
                encoding="PNG image data: zlib deflate, filter method 0 (filter types 0 to 4 a row)",
                scale=SCALE,
                offset=OFFSET,
                fill=MISSING_INDEX,
                summary=ArraySummary(
                    count=indices["count"],
                    missing_count=indices["missing_count"],
                    min=dbz(least) if least is not None else None,
                    max=dbz(greatest) if greatest is not None else None,
                ),
            ),
        )
        source = self.source_ref().model_copy(
            update={
                "observed_at": slot,
                "source_hash": self._source_hash,
                "transformations": [f"{T_SLOT} — {self._slot.basis}", T_GRID, T_VALUES],
            }
        )
        return observation_event(
            source=source,
            source_ids=[SourceId(system=SYSTEM, external_id=self._identity())],
            observation=contract,
            observed_at=slot,
            received_at=self.now(),
            validity=TemporalValidity(effective=Period(start=slot, end=slot)),
            geometry=Polygon(
                coordinates=[
                    [[WEST, SOUTH], [EAST, SOUTH], [EAST, NORTH], [WEST, NORTH], [WEST, SOUTH]]
                ]
            ),
            residual=Residual(
                namespace=self.metadata.format.name,
                data={key: document[key] for key in TWIN_KEYS if key != "wire_hex"},
            ),
        )
