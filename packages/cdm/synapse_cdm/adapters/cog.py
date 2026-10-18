"""`cog`, #30 in the ordinal table: one Cloud Optimized GeoTIFF (or GeoTIFF, or a VRT index) -> CDM,
ingest only.

WHAT A PAYLOAD IS
-----------------
ONE file: a classic GeoTIFF — a COG is one, laid out so its directories come first — of at most
256 MiB (DECISIONS U-07: a 3DEP 1/3 arc-second tile is 165,776,270 octets and the coastal
topobathy tiles 150 to 217 MB, research-raster F5/F6), or a GDAL VRT, which is an XML index of
other rasters. `to_cdm` takes the file's octets, or its parsed twin (`<name>.parsed.json`: the
octets as `wire_hex` and everything the file states), which is held to be exactly what its own
`wire_hex` decodes to. One band file is one object: an HLS or tiled ECOSTRESS granule is fifteen
to nineteen such files, each its own payload, and the caller's `granule_id` ties them together
(design-judge DJ-09).

HEADER, NOT PIXELS
------------------
The directories, the GeoKeys and the block index are read; the pixels are not. Every directory
of the chain is walked and every block it points at is checked to lie inside the file, so a file
that lies about its layout is refused, but the values are decoded for ONE block only: block 0 of
the full-resolution image (its north-west tile, or its first strip), held to
`max_decompressed_bytes` — one 512 x 512 tile of 32-bit floats, 1 MiB, the block of both
products the design record measured (research-raster F9, F16). That block, clipped to the image,
is the WINDOW: its summary (count, missing count, minimum, maximum, in the stored values) and,
when it holds at most `MAX_INLINE_VALUES` cells, its values. Every other value stays in the file,
by reference: the block index is the twin's `arrays`, declared unsupported rather than copied.

WHAT ONE FILE BECOMES
---------------------
- A file whose metadata states a sensing instant — the `SENSING_TIME` item HLS writes, or the
  `RangeBeginning`/`RangeEnding` date and time items of the ECOSTRESS standard metadata
  (research-satellite F05, F06), each read only when it carries its zone — or one the caller
  supplies with its basis (`sensing_time`), becomes one `ENVIRONMENTAL_OBSERVATION` `Event`
  carrying `imagery-product/1`: `validity.effective` is the sensing interval (an instant sets both
  ends), `observed_at` its end (design-consumer-and-time D5). Processing clocks —
  `HLS_PROCESSING_TIME`, `ProductionDateTime`, the TIFF `DateTime` — go to `product_version`
  only, never to a time field (DJ-18), and a file NAME is never read at all: its timestamp is an
  identifier. A file that names a sensed product's processing clock and states no sensing time is
  refused unless the caller supplies one (DECISIONS L-12): the stamp is never guessed.
- A file that states no instant — a DEM — becomes one `PlanObject` of type `ANNOTATION`, the
  `geo-object/1` pattern `geojson` set: a footprint and nothing promoted, with the caller's as-of
  (`as_of`, an instant and its basis) at `validity.observed_at` when one is given, and none when it
  is not. The structured limitation `no-source-time` says so for the conformance suite's check J.
- A VRT becomes one `PlanObject` too: its footprint, and its sources LISTED in the residual. A
  source is never opened; a `/vsicurl/` path, a URL, an `s3://` locator or a DAP locator is refused
  by name, because a VRT of remote sources would make a reader a network client.

GEOMETRY
--------
The footprint is the outline of the image's cells, from the one tiepoint, the pixel scale and the
image size (a `PixelIsPoint` raster's tiepoint names a cell centre, so its outline lies half a
cell further out, as GDAL reads it), converted to WGS84 for a closed set of coordinate systems:
EPSG:4326; EPSG:4269 (NAD83), stated as WGS84 without a datum shift, the null transformation PROJ
applies; and the WGS84 UTM zones (EPSG:32601-32660, 32701-32760), whose edges are converted point
by point with the transverse Mercator inverse (Kruger's series to third order in n) and densified
to at most 16 segments an edge. Any other system is refused by name; there is no `crs` field
anywhere. A height datum the GeoKeys state (NAVD88, EPSG:5703) is carried as `{name, namespace}`
in the residual and NEVER as `Position.alt_m`, which is ellipsoidal metres only (research-raster
F17).

HOSTED
------
`synapse-decode` serves this adapter since 2026-10-17 (the `iem_n0q` landing, which owned the host
module; until then the declared limitation `not-hosted` said it did not): the file is read whole
under the 256 MiB bound and its digest injected as `source_hash`; `--request band_file=NAME` and
`--request granule=ID` are the identifiers above; and `--at`/`--basis` comes with
`--request time=sensing_time` or `--request time=as_of`, the two injected instants, because which
one a file needs is known only once it is read.

WHAT IS REFUSED
---------------
BigTIFF; a directory, a value or a block outside the file; a directory chain that loops; JPEG,
LERC, ZSTD, LZMA, WebP or any other compression than none, LZW, Deflate and PackBits; more than
one sample a pixel; a block that would inflate past its size or past the bound; a rotation
(`ModelTransformationTag`) or more than one tiepoint; any coordinate system outside the closed
set; an outline that leaves -180 to 180 degrees of longitude or, in a UTM zone, reaches a pole
(transverse Mercator runs on over it); a VRT with a DTD, an entity, an element this module does not read or a remote source. A
refusal is a `CogRefused` (`ValueError`) whose code names the rule and whose text names the
structure, never a value from the payload.
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import math
import re
import struct
from typing import Any

from synapse_cdm import ids, secure_xml, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import raster_codec as codec
from synapse_cdm.enums import ObjectType
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
from synapse_cdm.models import (
    CDMBase,
    Period,
    PlanObject,
    Residual,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.observation_contracts import (
    MAX_INLINE_VALUES,
    ArraySummary,
    ImageryProduct,
    InjectedTime,
    Measurement,
    ProductVersion,
    QualityFlag,
    Quantity,
    RasterLocator,
    RasterWindow,
    TimeInputs,
    TimeSystem,
    UnitRef,
    ValuesByReference,
    ValuesInline,
    by_reference_limitation,
    decimal_float,
    decimal_integer,
    observation_event,
)
from synapse_cdm.observation_contracts import Grid as GridBlock

#: `source.system` on every object and the system of every identifier.
SYSTEM = "COG"
#: The residual namespace and `SourceRef.format_name`, read from the declaration below.
FORMAT_NAME = "GeoTIFF / Cloud Optimized GeoTIFF (OGC GeoTIFF 1.1, OGC COG 1.0)"
FORMAT_VERSION = (
    "OGC GeoTIFF Standard 1.1 (19-008r4) and OGC Cloud Optimized GeoTIFF Standard 1.0 (21-026), "
    "on classic TIFF Revision 6.0; GDAL VRT as GDAL's driver documentation describes it"
)

# -- bounds (DECISIONS U-07; each declared with its basis below) ---------------------------------

MAX_INPUT_BYTES = 256 * 1024 * 1024
#: One block decoded, at most: one 512 x 512 tile of 32-bit samples.
MAX_DECOMPRESSED_BYTES = 1024 * 1024
#: The twin nests seven containers deep; the bound is dis7's envelope bound.
MAX_DEPTH = 16
#: The directories of one file, the entries of one directory, the octets of one value.
MAX_IFDS = 64
MAX_ENTRIES = 128
MAX_VALUE_OCTETS = 1024 * 1024
#: The octets of every value of every directory together.
MAX_TOTAL_VALUE_OCTETS = 4 * 1024 * 1024
#: The elements of one VRT.
MAX_VRT_ELEMENTS = 65536

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_cog_adapter.py::"

STRUCTURE_BOUNDS_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "TIFF 6.0 bounds none of these. A COG holds its full-resolution image, its overviews "
        "and their masks: the design record's 3DEP tile has five overviews below 10812 x 10812 "
        "and its coastal topobathy tile five (research-raster F5/F6), so twelve directories at "
        "most; GDAL writes about twenty entries a directory. 64 directories (`MAX_IFDS`), 128 "
        "entries a directory (`MAX_ENTRIES`), 1 MiB for one value (`MAX_VALUE_OCTETS`, which "
        "holds 262 144 block offsets) and 4 MiB for every value of every directory together "
        "(`MAX_TOTAL_VALUE_OCTETS`, because entries may share octets) sit far above that, and a "
        "VRT is held to 65 536 elements "
        "(`MAX_VRT_ELEMENTS`): USGS's seamless index lists 1449 sources (F6), about ten "
        "elements each. " + _CAP
    ),
    enforced_at=(
        "`raster_codec.read_tiff` refuses the directory, the entry count, the value or the "
        "running total past its bound before reading it; `secure_xml.parse` refuses the VRT "
        "element that crosses the "
        "element bound"
    ),
    test=_TESTS + "test_the_structure_bounds_are_enforced_before_what_they_bound_is_read",
)

# -- the vocabulary ------------------------------------------------------------------------------

#: The horizontal systems a footprint is converted from, by EPSG code, and how.
GEOGRAPHIC = {4326: "WGS 84", 4269: "NAD83"}
#: The vertical systems read from VerticalGeoKey: code -> (name, axis unit), each as PROJ's EPSG
#: database (as installed with GDAL 3.13.3) states it; recorded in the pin.
VERTICAL = {5703: ("NAVD88 height", "metre")}
#: VerticalDatumGeoKey and VerticalUnitsGeoKey values that agree with the one vertical system.
VERTICAL_DATUMS = {5103: "North American Vertical Datum 1988"}
LINEAR_UNITS = {9001: "metre"}
ANGULAR_UNITS = {9102: "degree"}
#: A compound system a VRT names: code -> (horizontal code, vertical code).
COMPOUND = {5498: (4269, 5703)}

#: WGS 84's ellipsoid, for the UTM inverse.
WGS84_A = 6378137.0
WGS84_F = 1 / 298.257223563
UTM_K0 = 0.9996
UTM_FALSE_EASTING = 500000.0
UTM_FALSE_NORTHING_SOUTH = 10000000.0
EDGE_SEGMENTS = 16
#: Third flattening and rectifying radius of Kruger's series; the meridian quadrant is a quarter
#: turn of the latter, so the pole's UTM northing is k0 times it (9 997 964.943 m).
UTM_N = WGS84_F / (2 - WGS84_F)
UTM_RECTIFYING_RADIUS = WGS84_A / (1 + UTM_N) * (1 + UTM_N**2 / 4 + UTM_N**4 / 64)
UTM_POLE_NORTHING = UTM_K0 * UTM_RECTIFYING_RADIUS * math.pi / 2
#: The largest finite Float32.
FLOAT32_MAX = 3.4028234663852886e38

#: Dataset-level GDAL_METADATA items read as a sensing statement.
SENSING_TIME = "SENSING_TIME"
RANGE_KEYS = ("RangeBeginningDate", "RangeBeginningTime", "RangeEndingDate", "RangeEndingTime")
#: Processing clocks: product_version only, in this order of preference.
PROCESSING_CLOCKS = ("HLS_PROCESSING_TIME", "ProductionDateTime")
#: File-level quality summaries HLS publishes (research-satellite F14), read as quality flags.
QUALITY_ITEMS = ("CLOUD_COVERAGE", "SPATIAL_COVERAGE")

_RFC3339 = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?(Z|[+-]\d{2}:\d{2})")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_TIME_Z = re.compile(r"\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z")
_DECIMAL = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?")
_INTEGER = re.compile(r"[+-]?\d+")
_HEX = re.compile(r"[0-9a-f]*")
_NAME = re.compile(r"[^/\\\x00-\x1f]{1,255}")

#: Remote locators, by name, matched anywhere in a VRT source: the forms `synapse-decode` refuses
#: for an input (`decode_host.py`), because GDAL opens a remote source behind a driver prefix.
_REMOTE = (
    (re.compile(r"(?i)/vsicurl(_streaming)?/"), "a GDAL /vsicurl/ path"),
    (re.compile(r"(?i)/vsi[a-z0-9_]*/"), "a GDAL virtual file system path"),
    (re.compile(r"(?i)\[[^\[\]]*\][a-z][a-z0-9+.\-]*://"), "a DAP locator"),
    (re.compile(r"(?i)(?<![a-z0-9+.\-])s3://"), "an s3:// locator"),
    (re.compile(r"(?i)(?<![a-z0-9+.\-])https?://"), "an http(s):// URL"),
    (re.compile(r"(?i)(?<![a-z0-9+.\-])(dods|dap2|dap4)://"), "a DAP locator"),
    (re.compile(r"(?i)(?<![a-z0-9+.\-])[a-z][a-z0-9+.\-]*://"), "a URL"),
)

TIFF_TWIN_KEYS = (
    "wire_hex",
    "header",
    "ifds",
    "arrays",
    "geokeys",
    "gdal_metadata",
    "vertical",
    "window",
)
VRT_TWIN_KEYS = ("wire_hex", "vrt")

#: IFD 0's tags carried in their parsed form (`geokeys`, `gdal_metadata`), not as raw values.
_PARSED_TAGS = frozenset({34735, 34736, 34737, 42112})

# -- the transformations, by what they read ------------------------------------------------------

T_FOOTPRINT_GEOGRAPHIC = (
    "georeference: the footprint is the outline of the image's cells, from ModelTiepointTag, "
    "ModelPixelScaleTag and the image size in degrees of EPSG:4326, a PixelIsPoint tiepoint "
    "naming a cell centre"
)
T_FOOTPRINT_NAD83 = (
    "georeference: the footprint is the outline of the image's cells in degrees of EPSG:4269 "
    "(NAD83), stated as WGS84 coordinates without a datum shift: the null transformation PROJ "
    "applies between the two, which differ by about a metre"
)
T_FOOTPRINT_UTM = (
    "georeference: the footprint is the outline of the image's cells in a WGS84 UTM zone, each "
    "edge densified to at most 16 segments and every vertex converted with the transverse "
    "Mercator inverse (Kruger's series to third order in n), rounded to 10^-6 degree"
)
T_SENSING_STATED = (
    "gdal_metadata: the sensing instant is the SENSING_TIME item, RFC 3339 with its zone, read "
    "in UTC; it is validity.effective's two ends and observed_at"
)
T_SENSING_RANGE = (
    "gdal_metadata: the sensing interval runs from the RangeBeginningDate and RangeBeginningTime "
    "items to the RangeEndingDate and RangeEndingTime items, each time ending Z (UTC); "
    "observed_at is its end"
)
T_SENSING_INJECTED = "validity.effective: the caller's sensing_time, which the file does not state"
T_AS_OF = "validity.observed_at: the caller's as-of, which the file does not state"
T_WINDOW = (
    "window: the values of block 0 of the full-resolution image, clipped to the image, decoded "
    "and summarised in the stored values; a sample equal to GDAL_NODATA, or a NaN, is missing"
)
T_WIRE = (
    "derived: the twin's wire_hex is the file's octets; every object is decoded from them and "
    "they are not copied, the file being identified by source_hash"
)
T_ARRAYS = (
    "derived: the twin's arrays are each directory's block offsets and byte counts (and a colour "
    "table) as the file states them; they are read to locate and check the blocks and are not "
    "copied"
)


class CogRefused(ValueError):
    """A file this module will not translate. `code` names the rule; the text names the
    structure, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code
        self.text = text

    def __reduce__(self):
        return (CogRefused, (self.code, self.text))


# -- the TIFF document ---------------------------------------------------------------------------


def decode_tiff(octets: bytes) -> dict:
    """Everything a GeoTIFF states that this module reads, as its twin holds it (no `wire_hex`)."""
    try:
        tiff = codec.read_tiff(
            octets,
            max_ifds=MAX_IFDS,
            max_entries=MAX_ENTRIES,
            max_value_octets=MAX_VALUE_OCTETS,
            max_total_value_octets=MAX_TOTAL_VALUE_OCTETS,
        )
        layouts = [codec.block_layout(ifd, i, len(octets)) for i, ifd in enumerate(tiff.ifds)]
        first = tiff.ifds[0]
        keys = codec.geokeys(first)
    except codec.RasterRefused as refusal:
        raise CogRefused(refusal.code, refusal.text) from None
    if 254 in first.entries and first.entries[254].value[0] != 0:
        raise CogRefused(
            "first-ifd-not-full-resolution",
            "IFD 0 is marked as an overview or a mask; the full-resolution image comes first",
        )
    if 274 in first.entries and first.entries[274].value[0] != 1:
        raise CogRefused(
            "unsupported-orientation",
            "IFD 0 states an Orientation other than 1; GeoTIFF's raster space is row 0 at the top",
        )
    if 34264 in first.entries:
        raise CogRefused(
            "model-transformation",
            "IFD 0 states ModelTransformationTag; a rotated or sheared raster is not read",
        )
    if keys is None:
        raise CogRefused("no-geokeys", "IFD 0 states no GeoKey directory")
    metadata = _gdal_metadata(first)
    document = {
        "header": {"byte_order": tiff.byte_order, "first_ifd_offset": tiff.first_ifd_offset},
        "ifds": [_ifd_document(ifd, index) for index, ifd in enumerate(tiff.ifds)],
        "arrays": [
            {
                codec.TAG_NAMES[t]: list(ifd.entries[t].value)
                for t in sorted(ifd.entries)
                if t in codec.ARRAY_TAGS
            }
            for ifd in tiff.ifds
        ],
        "geokeys": {
            "version": keys.version,
            "revision": keys.revision,
            "minor_revision": keys.minor_revision,
            "keys": [
                {"id": k, "name": codec.GEOKEY_NAMES.get(k, f"GeoKey{k}"), "value": v}
                for k, v in keys.keys.items()
            ],
        },
        "gdal_metadata": metadata,
        "vertical": _vertical(keys.keys),
        "window": None,
    }
    georeference(document)  # every footprint rule is checked before a value is decoded
    document["window"] = _window(octets, tiff, layouts[0], document)
    return document


def _ifd_document(ifd: codec.Ifd, index: int) -> dict:
    tags = {}
    for tag, entry in ifd.entries.items():
        if tag in codec.ARRAY_TAGS or (index == 0 and tag in _PARSED_TAGS):
            continue
        tags[entry.name] = {"type": entry.type_name, "value": entry.value}
    return {"offset": ifd.offset, "next_ifd_offset": ifd.next_offset, "tags": tags}


def _gdal_metadata(ifd: codec.Ifd) -> list | None:
    """GDAL_METADATA (42112) as its items, in order: GDAL's own convention, outside OGC GeoTIFF
    1.1, honoured explicitly (research-raster Traps)."""
    entry = ifd.entries.get(42112)
    if entry is None:
        return None
    if not isinstance(entry.value, str):
        raise CogRefused("bad-gdal-metadata", "IFD 0: GDAL_METADATA holds more than one string")
    try:
        parsed = secure_xml.parse(
            entry.value,
            secure_xml.XmlLimits(max_bytes=MAX_VALUE_OCTETS, max_depth=2, max_elements=4096),
        )
    except secure_xml.XmlRefused as refusal:
        raise CogRefused(
            f"gdal-metadata-{refusal.kind}", f"IFD 0: GDAL_METADATA is refused ({refusal.kind})"
        ) from None
    root = parsed.root
    if root.tag != "GDALMetadata" or root.attrib or (root.text or "").strip():
        raise CogRefused("bad-gdal-metadata", "IFD 0: GDAL_METADATA is not a GDALMetadata element")
    items, seen = [], set()
    for element in root:
        attributes = dict(element.attrib)
        if element.tag != "Item" or len(element) or "name" not in attributes:
            raise CogRefused(
                "bad-gdal-metadata", "IFD 0: GDAL_METADATA holds an element other than a named Item"
            )
        if set(attributes) - {"name", "sample", "role", "domain"} or (element.tail or "").strip():
            raise CogRefused(
                "bad-gdal-metadata", "IFD 0: a GDAL_METADATA Item carries an attribute not read"
            )
        sample = attributes.get("sample")
        if sample is not None:
            if not sample.isdigit() or int(sample) != 0:
                raise CogRefused(
                    "bad-gdal-metadata",
                    "IFD 0: a GDAL_METADATA Item names a sample the image lacks",
                )
            sample = 0
        key = (attributes["name"], sample, attributes.get("domain"))
        if key in seen:
            raise CogRefused("repeated-metadata-item", "IFD 0: a GDAL_METADATA Item appears twice")
        seen.add(key)
        items.append(
            {
                "name": attributes["name"],
                "sample": sample,
                "role": attributes.get("role"),
                "domain": attributes.get("domain"),
                "value": element.text or "",
            }
        )
    return items


def _vertical(keys: dict) -> dict | None:
    """The vertical system the GeoKeys state, from the closed table, or `None`."""
    code = keys.get(4096)
    datum, units = keys.get(4098), keys.get(4099)
    if code is None:
        if datum is not None or units is not None:
            raise CogRefused(
                "unsupported-vertical-crs",
                "IFD 0 states a vertical datum or unit and no VerticalGeoKey",
            )
        return None
    if code not in VERTICAL:
        raise CogRefused(
            "unsupported-vertical-crs",
            "IFD 0: VerticalGeoKey names a vertical system outside the closed set (EPSG:5703)",
        )
    if datum is not None and datum not in VERTICAL_DATUMS:
        raise CogRefused("unsupported-vertical-crs", "IFD 0: VerticalDatumGeoKey disagrees")
    if units is not None and units not in LINEAR_UNITS:
        raise CogRefused("unsupported-vertical-crs", "IFD 0: VerticalUnitsGeoKey is not metres")
    name, unit = VERTICAL[code]
    return {
        "datum": {
            "name": name,
            "namespace": f"EPSG:{code}, read from OGC GeoTIFF 1.1 VerticalGeoKey (4096)",
        },
        "unit": unit,
        "unit_namespace": f"the axis unit of EPSG:{code} in PROJ's EPSG database",
        "orthometric": True,
    }


def _items(document: dict, sample: int | None) -> dict[str, dict]:
    """The GDAL_METADATA items of the default domain for the dataset (`None`) or a sample. An item
    whose value is blank states nothing and is read as absent; the residual keeps it as written."""
    return {
        item["name"]: item
        for item in document.get("gdal_metadata") or []
        if item["sample"] == sample and item["domain"] is None and item["value"].strip()
    }


def _stated_text(document: dict, tag: str) -> str | None:
    """IFD 0's text tag when it holds one non-blank string, else `None`."""
    entry = document["ifds"][0]["tags"].get(tag)
    value = entry["value"] if entry is not None else None
    return value if isinstance(value, str) and value.strip() else None


def _nodata(document: dict) -> str | None:
    tag = document["ifds"][0]["tags"].get("GDAL_NODATA")
    if tag is None:
        return None
    text = tag["value"]
    if not isinstance(text, str) or not (
        _DECIMAL.fullmatch(text.strip()) or text.strip().lower() == "nan"
    ):
        raise CogRefused("bad-nodata", "IFD 0: GDAL_NODATA is not a decimal number or nan")
    return text


def _window(octets: bytes, tiff: codec.Tiff, layout: codec.Layout, document: dict) -> dict:
    """Block 0 of IFD 0, clipped to the image: its summary and, when small, its values."""
    try:
        values = codec.decode_block(
            octets, layout, 0, tiff.byte_order, limit=MAX_DECOMPRESSED_BYTES, where="IFD 0"
        )
    except codec.RasterRefused as refusal:
        raise CogRefused(refusal.code, refusal.text) from None
    key = (layout.sample_format[0], layout.bits[0])
    code, dtype = codec.SAMPLE_TYPES[key]
    nodata_text = _nodata(document)
    column, row, width, height = layout.block_window(0)
    nodata = _nodata_value(nodata_text, code)
    if values is None:
        if nodata_text is None:
            raise CogRefused(
                "sparse-block-without-nodata",
                "IFD 0: block 0 is sparse and the file states no GDAL_NODATA to fill it with",
            )
        cells: list = [None] * (width * height)
        nan_count = 0
    else:
        cells, nan_count = [], 0
        for y in range(height):
            for x in range(width):
                value = values[y * layout.block_width + x]
                if isinstance(value, float) and math.isnan(value):
                    cells.append(None)
                    nan_count += 1
                elif isinstance(value, float) and math.isinf(value):
                    raise CogRefused("sample-not-finite", "IFD 0: block 0 holds an infinite sample")
                elif nodata is not None and value == nodata:
                    cells.append(None)
                else:
                    cells.append(value)
    present = [v for v in cells if v is not None]
    missing = len(cells) - len(present)
    mechanisms = []
    if missing - nan_count:
        mechanisms.append(f"GDAL_NODATA (TIFF tag 42113): {nodata_text}")
    if nan_count:
        mechanisms.append(
            f"GDAL_NODATA (TIFF tag 42113): {nodata_text}"
            if nodata_text is not None and nodata_text.strip().lower() == "nan"
            else "a NaN sample, which states no number"
        )
    return {
        "ifd": 0,
        "block": 0,
        "column": column,
        "row": row,
        "width": width,
        "height": height,
        "dtype": dtype,
        "encoding": _encoding(layout),
        "count": len(cells),
        "missing_count": missing,
        "min": min(present) if present else None,
        "max": max(present) if present else None,
        "values": cells if len(cells) <= MAX_INLINE_VALUES else None,
        "missing_mechanism": "; ".join(mechanisms) if mechanisms else None,
    }


def _nodata_value(text: str | None, code: str) -> float | int | None:
    """The sample value GDAL_NODATA names, compared as the sample type stores it."""
    if text is None or text.strip().lower() == "nan":
        return None
    stripped = text.strip()
    if code in "BHIbhi":
        if not _INTEGER.fullmatch(stripped):
            return None  # a fraction no integer sample can equal
        value = decimal_integer(stripped)
        if value is None:
            raise CogRefused("bad-nodata", "IFD 0: GDAL_NODATA names no number a double holds")
        return value
    value = decimal_float(stripped)
    if value is None:
        raise CogRefused("bad-nodata", "IFD 0: GDAL_NODATA names no number a double holds")
    if code == "f":
        # A Float32 sample equals the nodata value as Float32 stores it: GDAL writes the text of
        # the double, and -99999.0 and its Float32 rounding are compared as the file holds them.
        if abs(value) > FLOAT32_MAX:
            return None
        return struct.unpack("<f", struct.pack("<f", value))[0]
    return value


def _encoding(layout: codec.Layout) -> str:
    return (
        f"TIFF Compression {layout.compression} ({codec.COMPRESSIONS_READ[layout.compression]}), "
        f"Predictor {layout.predictor} ({codec.PREDICTORS[layout.predictor]})"
    )


# -- georeference --------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Georeference:
    system: str
    code: int
    utm: tuple[int, bool] | None
    west: float
    south: float
    east: float
    north: float
    width: int
    height: int
    cell_x: float
    cell_y: float
    unit: str
    template: str
    ring: list


def _keys(document: dict) -> dict[int, Any]:
    return {k["id"]: k["value"] for k in document["geokeys"]["keys"]}


def georeference(document: dict) -> Georeference:
    """The footprint and the grid facts a GeoTIFF states, or the refusal naming why not."""
    keys = _keys(document)
    tags = document["ifds"][0]["tags"]
    width = tags["ImageWidth"]["value"][0]
    height = tags["ImageLength"]["value"][0]
    model = keys.get(1024)
    raster = keys.get(1025)
    if raster not in (1, 2):
        raise CogRefused(
            "no-raster-type", "IFD 0: GTRasterTypeGeoKey is not PixelIsArea (1) or PixelIsPoint (2)"
        )
    if "ModelPixelScaleTag" not in tags or "ModelTiepointTag" not in tags:
        raise CogRefused(
            "no-georeference", "IFD 0 states no ModelPixelScaleTag and ModelTiepointTag pair"
        )
    scale = tags["ModelPixelScaleTag"]["value"]
    tie = tags["ModelTiepointTag"]["value"]
    if len(scale) != 3:
        raise CogRefused("no-georeference", "IFD 0: ModelPixelScaleTag is not three numbers")
    if len(tie) != 6:
        raise CogRefused(
            "multiple-tiepoints", "IFD 0: ModelTiepointTag states other than one tiepoint"
        )
    cell_x, cell_y = scale[0], scale[1]
    if cell_x <= 0 or cell_y <= 0:
        raise CogRefused(
            "unsupported-orientation", "IFD 0: the pixel scale is not positive on both axes"
        )
    shift = 0.5 if raster == 2 else 0.0
    west = tie[3] - (tie[0] + shift) * cell_x
    north = tie[4] + (tie[1] + shift) * cell_y
    east = west + width * cell_x
    south = north - height * cell_y
    if model == 2:
        code = keys.get(2048)
        if code not in GEOGRAPHIC:
            raise CogRefused(
                "unsupported-crs",
                "IFD 0: GeodeticCRSGeoKey names a system outside the closed set "
                "(EPSG:4326, EPSG:4269, the WGS84 UTM zones)",
            )
        if keys.get(2054, 9102) not in ANGULAR_UNITS:
            raise CogRefused(
                "unsupported-angular-unit", "IFD 0: GeogAngularUnitsGeoKey is not degrees"
            )
        return _geographic(
            code, west, south, east, north, width, height, cell_x, cell_y, "GeodeticCRSGeoKey"
        )
    if model == 1:
        code = keys.get(3072)
        if not isinstance(code, int) or not (32601 <= code <= 32660 or 32701 <= code <= 32760):
            raise CogRefused(
                "unsupported-crs",
                "IFD 0: ProjectedCRSGeoKey names a system outside the closed set "
                "(EPSG:4326, EPSG:4269, the WGS84 UTM zones)",
            )
        if keys.get(3076, 9001) not in LINEAR_UNITS:
            raise CogRefused(
                "unsupported-linear-unit", "IFD 0: ProjLinearUnitsGeoKey is not metres"
            )
        return _projected(
            code, west, south, east, north, width, height, cell_x, cell_y, "ProjectedCRSGeoKey"
        )
    raise CogRefused(
        "unsupported-crs", "IFD 0: GTModelTypeGeoKey is not projected (1) or geographic (2)"
    )


def _geographic(code, west, south, east, north, width, height, cell_x, cell_y, key) -> Georeference:
    if not (-180.0 <= west < east <= 180.0 and -90.0 <= south < north <= 90.0):
        raise CogRefused(
            "footprint-out-of-range",
            "the image's outline leaves -180 to 180 degrees of longitude or -90 to 90 of latitude",
        )
    ring = [[west, south], [east, south], [east, north], [west, north], [west, south]]
    return Georeference(
        "geographic",
        code,
        None,
        west,
        south,
        east,
        north,
        width,
        height,
        cell_x,
        cell_y,
        "degree",
        f"{key} {code}",
        ring,
    )


def _projected(code, west, south, east, north, width, height, cell_x, cell_y, key) -> Georeference:
    zone, northern = code % 100, code < 32700
    false_northing = 0.0 if northern else UTM_FALSE_NORTHING_SOUTH
    if not (0.0 <= west < east <= 1000000.0 and 0.0 <= south < north <= 10000000.0):
        raise CogRefused(
            "footprint-out-of-range", "the image's outline leaves the UTM zone's coordinate range"
        )
    # Past the pole's northing transverse Mercator carries on over the top onto the far side of
    # the globe (a vertex 180 degrees round from the zone), so an outline that reaches it has no
    # WGS84 ring. Short of it every vertex's latitude stays inside -90 to 90 and its longitude
    # within 90 degrees of the central meridian, so the one range left to hold is 180 degrees.
    if north >= UTM_POLE_NORTHING if northern else south <= false_northing - UTM_POLE_NORTHING:
        raise CogRefused(
            "footprint-reaches-pole",
            "the image's outline reaches a pole; a footprint over it is not stated",
        )
    corners = [
        (west, south, 0, width),
        (east, south, 1, height),
        (east, north, 0, width),
        (west, north, 1, height),
    ]
    # Counter-clockwise from the south-west corner: east along the bottom, north up the right,
    # west along the top, south down the left; transverse Mercator keeps the orientation.
    ring: list[list[float]] = []
    for k, (x0, y0, _, cells) in enumerate(corners):
        x1, y1 = corners[(k + 1) % 4][:2]
        segments = min(cells, EDGE_SEGMENTS)
        for s in range(segments):
            x = x0 + (x1 - x0) * s / segments
            y = y0 + (y1 - y0) * s / segments
            lat, lon = utm_inverse(x, y - false_northing, zone)
            ring.append([round(lon, 6), round(lat, 6)])
    ring.append(list(ring[0]))
    # The inverse does not wrap: zones 1 to 15 reach west of 180 W and zones 46 to 60 east of
    # 180 E at their outer edges or near the pole. Refused here, so the TIFF and the VRT share
    # it and the Polygon model never sees a longitude it would reject in its own words.
    if any(not -180.0 <= lon <= 180.0 for lon, _ in ring):
        raise CogRefused(
            "footprint-crosses-antimeridian",
            "the image's outline crosses 180 degrees; a footprint across it is not stated",
        )
    return Georeference(
        "utm",
        code,
        (zone, northern),
        west,
        south,
        east,
        north,
        width,
        height,
        cell_x,
        cell_y,
        "metre",
        f"{key} {code}",
        ring,
    )


def utm_inverse(easting: float, northing: float, zone: int) -> tuple[float, float]:
    """(latitude, longitude) in degrees of a WGS84 UTM coordinate, `northing` already freed of
    the southern false northing. Kruger's series to third order in n, the form the Wikipedia
    article "Universal Transverse Mercator coordinate system" gives; within a zone it agrees with
    PROJ far below the 10^-6 degree the footprint is rounded to."""
    n = UTM_N
    big_a = UTM_RECTIFYING_RADIUS
    beta = (
        n / 2 - 2 * n * n / 3 + 37 * n**3 / 96,
        n * n / 48 + n**3 / 15,
        17 * n**3 / 480,
    )
    delta = (
        2 * n - 2 * n * n / 3 - 2 * n**3,
        7 * n * n / 3 - 8 * n**3 / 5,
        56 * n**3 / 15,
    )
    xi = northing / (UTM_K0 * big_a)
    eta = (easting - UTM_FALSE_EASTING) / (UTM_K0 * big_a)
    xi_p = xi - sum(
        b * math.sin(2 * j * xi) * math.cosh(2 * j * eta) for j, b in enumerate(beta, 1)
    )
    eta_p = eta - sum(
        b * math.cos(2 * j * xi) * math.sinh(2 * j * eta) for j, b in enumerate(beta, 1)
    )
    chi = math.asin(math.sin(xi_p) / math.cosh(eta_p))
    phi = chi + sum(d * math.sin(2 * j * chi) for j, d in enumerate(delta, 1))
    central = math.radians(zone * 6 - 183)
    lam = central + math.atan2(math.sinh(eta_p), math.cos(xi_p))
    return math.degrees(phi), math.degrees(lam)


# -- the VRT document ----------------------------------------------------------------------------

#: The elements read, by parent. Anything else is refused by name: a VRT can carry derived bands
#: and pixel functions, and an index reader that kept what it did not read would hand a consumer
#: a recipe it never checked.
_VRT_CHILDREN = {
    "VRTDataset": {"SRS", "GeoTransform", "Metadata", "VRTRasterBand"},
    "Metadata": {"MDI"},
    "VRTRasterBand": {
        "NoDataValue",
        "ColorInterp",
        "Description",
        "UnitType",
        "Offset",
        "Scale",
        "Metadata",
        "SimpleSource",
        "ComplexSource",
    },
    "SimpleSource": {"SourceFilename", "SourceBand", "SourceProperties", "SrcRect", "DstRect"},
    "ComplexSource": {
        "SourceFilename",
        "SourceBand",
        "SourceProperties",
        "SrcRect",
        "DstRect",
        "NODATA",
        "ScaleOffset",
        "ScaleRatio",
    },
}
_VRT_ATTRIBUTES = {
    "VRTDataset": {"rasterXSize", "rasterYSize"},
    "SRS": {"dataAxisToSRSAxisMapping"},
    "Metadata": {"domain"},
    "MDI": {"key"},
    "VRTRasterBand": {"dataType", "band"},
    "SourceFilename": {"relativeToVRT", "shared"},
    "SourceProperties": {"RasterXSize", "RasterYSize", "DataType", "BlockXSize", "BlockYSize"},
    "SrcRect": {"xOff", "yOff", "xSize", "ySize"},
    "DstRect": {"xOff", "yOff", "xSize", "ySize"},
}
_TEXT_ELEMENTS = {
    "SRS",
    "GeoTransform",
    "MDI",
    "NoDataValue",
    "ColorInterp",
    "Description",
    "UnitType",
    "Offset",
    "Scale",
    "SourceFilename",
    "SourceBand",
    "NODATA",
    "ScaleOffset",
    "ScaleRatio",
}


def _remote(text: str) -> str | None:
    for pattern, name in _REMOTE:
        if pattern.search(text):
            return name
    return None


def decode_vrt(octets: bytes) -> dict:
    """Everything a VRT states that this module reads, as its twin holds it (no `wire_hex`)."""
    try:
        parsed = secure_xml.parse(
            octets,
            secure_xml.XmlLimits(
                max_bytes=MAX_INPUT_BYTES, max_depth=MAX_DEPTH, max_elements=MAX_VRT_ELEMENTS
            ),
        )
    except secure_xml.XmlRefused as refusal:
        raise CogRefused(
            f"vrt-{refusal.kind}", f"the VRT is refused by the XML guard ({refusal.kind})"
        ) from None
    root = parsed.root
    if root.tag != "VRTDataset":
        raise CogRefused("not-a-vrt", "the XML document's root is not VRTDataset")
    _check_element(root)
    width = _vrt_int(root.attrib.get("rasterXSize"), "VRTDataset rasterXSize")
    height = _vrt_int(root.attrib.get("rasterYSize"), "VRTDataset rasterYSize")
    srs = transform = None
    metadata, bands = [], []
    for child in root:
        if child.tag == "SRS":
            if srs is not None:
                raise CogRefused("bad-vrt", "the VRT states SRS twice")
            srs = {
                "text": (child.text or "").strip(),
                "data_axis_to_srs_axis_mapping": child.attrib.get("dataAxisToSRSAxisMapping"),
            }
        elif child.tag == "GeoTransform":
            if transform is not None:
                raise CogRefused("bad-vrt", "the VRT states GeoTransform twice")
            transform = _geotransform(child.text or "")
        elif child.tag == "Metadata":
            metadata.append(_vrt_metadata(child))
        else:
            bands.append(_vrt_band(child, len(bands)))
    if srs is None or transform is None:
        raise CogRefused("no-georeference", "the VRT states no SRS and GeoTransform pair")
    if not bands:
        raise CogRefused("bad-vrt", "the VRT states no VRTRasterBand")
    return {
        "vrt": {
            "raster_x_size": width,
            "raster_y_size": height,
            "srs": srs,
            "geo_transform": transform,
            "metadata": metadata,
            "bands": bands,
        }
    }


def _check_element(element) -> None:
    """The closed vocabulary, element by element, before anything is read from it."""
    tag = element.tag
    allowed = _VRT_CHILDREN.get(tag, set())
    if set(element.attrib) - _VRT_ATTRIBUTES.get(tag, set()):
        raise CogRefused(
            "unsupported-vrt-attribute", f"the VRT's {tag} carries an attribute not read"
        )
    if tag not in _TEXT_ELEMENTS and (element.text or "").strip():
        raise CogRefused("bad-vrt", f"the VRT's {tag} holds text where elements belong")
    for child in element:
        if child.tag not in allowed:
            raise CogRefused(
                "unsupported-vrt-element",
                f"the VRT's {tag} holds an element this module does not read",
            )
        if (child.tail or "").strip():
            raise CogRefused("bad-vrt", f"the VRT holds text after a {child.tag}")
        _check_element(child)


def _vrt_int(text: str | None, where: str) -> int:
    if text is None or not text.isdigit() or int(text) < 1:
        raise CogRefused("bad-vrt", f"the VRT's {where} is not a positive integer")
    return int(text)


def _vrt_number(text: str | None, where: str) -> float:
    stripped = (text or "").strip()
    value = decimal_float(stripped) if _DECIMAL.fullmatch(stripped) else None
    if value is None:
        raise CogRefused("bad-vrt", f"the VRT's {where} is not a finite decimal number")
    return value


def _geotransform(text: str) -> list[float]:
    parts = text.split(",")
    if len(parts) != 6:
        raise CogRefused("bad-vrt", "the VRT's GeoTransform is not six numbers")
    return [_vrt_number(part, "GeoTransform") for part in parts]


def _vrt_metadata(element) -> dict:
    items, seen = [], set()
    for mdi in element:
        key = mdi.attrib.get("key")
        if key is None or key in seen:
            raise CogRefused(
                "bad-vrt", "the VRT's Metadata holds an MDI with no key or a key twice"
            )
        seen.add(key)
        items.append({"key": key, "value": mdi.text or ""})
    return {"domain": element.attrib.get("domain"), "items": items}


def _vrt_band(element, index: int) -> dict:
    band = {
        "band": _vrt_int(element.attrib.get("band"), f"band {index + 1}'s band"),
        "data_type": element.attrib.get("dataType"),
        "fields": {},
        "metadata": [],
        "sources": [],
    }
    if band["data_type"] is None:
        raise CogRefused("bad-vrt", f"the VRT's band {index + 1} states no dataType")
    for child in element:
        if child.tag in ("SimpleSource", "ComplexSource"):
            band["sources"].append(_vrt_source(child, index, len(band["sources"])))
        elif child.tag == "Metadata":
            band["metadata"].append(_vrt_metadata(child))
        else:
            if child.tag in band["fields"]:
                raise CogRefused("bad-vrt", f"the VRT's band {index + 1} states {child.tag} twice")
            band["fields"][child.tag] = (child.text or "").strip()
    return band


def _vrt_source(element, band: int, index: int) -> dict:
    where = f"band {band + 1} source {index}"
    source: dict[str, Any] = {"element": element.tag}
    seen = set()
    for child in element:
        if child.tag in seen:
            raise CogRefused("bad-vrt", f"the VRT's {where} states {child.tag} twice")
        seen.add(child.tag)
        if child.tag == "SourceFilename":
            name = (child.text or "").strip()
            remote = _remote(name)
            if remote is not None:
                raise CogRefused(
                    "remote-source",
                    f"the VRT's {where} names {remote}; a source is never opened, and a remote "
                    "one would make a reader a network client",
                )
            if not name:
                raise CogRefused("bad-vrt", f"the VRT's {where} names no file")
            relative = child.attrib.get("relativeToVRT", "0")
            if relative not in ("0", "1"):
                raise CogRefused("bad-vrt", f"the VRT's {where}: relativeToVRT is not 0 or 1")
            source["source_filename"] = name
            source["relative_to_vrt"] = relative == "1"
            source["shared"] = child.attrib.get("shared")
        elif child.tag in ("SourceProperties", "SrcRect", "DstRect"):
            source[child.tag] = dict(sorted(child.attrib.items()))
        else:
            source[child.tag] = (child.text or "").strip()
    if "source_filename" not in source:
        raise CogRefused("bad-vrt", f"the VRT's {where} names no SourceFilename")
    return source


#: The longest SRS text read, and the deepest WKT nesting: GDAL's WKT1 for EPSG:5498 is 600
#: characters nested five deep.
MAX_SRS_TEXT = 65536
MAX_WKT_DEPTH = 16


def _wkt(text: str) -> list:
    """WKT1 as nested [keyword, children...] lists: quoted strings, numbers, bare words, nodes."""
    if len(text) > MAX_SRS_TEXT:
        raise ValueError
    tokens = re.findall(r'"(?:[^"]|"")*"|[A-Za-z_][A-Za-z0-9_]*|[-+0-9.eE]+|[\[\](),]|\S', text)
    position = 0

    def node(depth: int) -> list:
        nonlocal position
        if depth > MAX_WKT_DEPTH:
            raise ValueError
        if position >= len(tokens) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", tokens[position]):
            raise ValueError
        keyword = tokens[position]
        position += 1
        if position >= len(tokens) or tokens[position] not in "[(":
            raise ValueError
        close = "]" if tokens[position] == "[" else ")"
        position += 1
        children: list = [keyword]
        while True:
            if position >= len(tokens):
                raise ValueError
            token = tokens[position]
            if token.startswith('"'):
                children.append(token[1:-1].replace('""', '"'))
                position += 1
            elif (
                re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", token)
                and position + 1 < len(tokens)
                and tokens[position + 1] in ("[", "(")
            ):
                children.append(node(depth + 1))
            else:
                children.append(token)
                position += 1
            if position >= len(tokens):
                raise ValueError
            if tokens[position] == ",":
                position += 1
                continue
            if tokens[position] == close:
                position += 1
                return children
            raise ValueError

    tree = node(1)
    if position != len(tokens):
        raise ValueError
    return tree


def vrt_system(srs: dict) -> tuple[int, int | None]:
    """(horizontal EPSG code, vertical EPSG code or None) of a VRT's SRS, from the closed set:
    the `EPSG:<code>` form, or WKT1 whose root GEOGCS, PROJCS or COMPD_CS names its EPSG
    authority."""
    text = srs["text"]
    short = re.fullmatch(r"EPSG:(\d{4,5})", text)
    if short:
        code = int(short.group(1))
    else:
        try:
            tree = _wkt(text)
        except ValueError:
            raise CogRefused(
                "unsupported-crs", "the VRT's SRS is neither EPSG:<code> nor WKT1 this module reads"
            ) from None
        if tree[0] not in ("GEOGCS", "PROJCS", "COMPD_CS"):
            raise CogRefused(
                "unsupported-crs", "the VRT's SRS is not WKT1 GEOGCS, PROJCS or COMPD_CS"
            )
        authority = [c for c in tree[1:] if isinstance(c, list) and c[0] == "AUTHORITY"]
        if (
            len(authority) != 1
            or len(authority[0]) != 3
            or authority[0][1] != "EPSG"
            or not str(authority[0][2]).isdigit()
        ):
            raise CogRefused("unsupported-crs", "the VRT's SRS names no single EPSG authority")
        code = int(authority[0][2])
    vertical = None
    if code in COMPOUND:
        code, vertical = COMPOUND[code]
    if not (code in GEOGRAPHIC or 32601 <= code <= 32660 or 32701 <= code <= 32760):
        raise CogRefused(
            "unsupported-crs",
            "the VRT's SRS names a system outside the closed set "
            "(EPSG:4326, EPSG:4269, EPSG:5498, the WGS84 UTM zones)",
        )
    mapping = srs["data_axis_to_srs_axis_mapping"]
    expected = "2,1,3" if vertical is not None else "2,1" if code in GEOGRAPHIC else "1,2"
    if mapping is not None and mapping.replace(" ", "") != expected:
        raise CogRefused(
            "unsupported-axis-mapping",
            "the VRT's dataAxisToSRSAxisMapping is not GDAL's traditional GIS order",
        )
    return code, vertical


def vrt_georeference(document: dict) -> Georeference:
    vrt = document["vrt"]
    code, _ = vrt_system(vrt["srs"])
    x0, dx, rx, y0, ry, dy = vrt["geo_transform"]
    if rx != 0.0 or ry != 0.0:
        raise CogRefused("model-transformation", "the VRT's GeoTransform rotates the raster")
    if dx <= 0.0 or dy >= 0.0:
        raise CogRefused(
            "unsupported-orientation", "the VRT's GeoTransform is not north-up with positive steps"
        )
    width, height = vrt["raster_x_size"], vrt["raster_y_size"]
    west, north = x0, y0
    east, south = x0 + width * dx, y0 + height * dy
    if code in GEOGRAPHIC:
        return _geographic(code, west, south, east, north, width, height, dx, -dy, "SRS EPSG")
    return _projected(code, west, south, east, north, width, height, dx, -dy, "SRS EPSG")


# -- the twin ------------------------------------------------------------------------------------


def _same(a: Any, b: Any) -> bool:
    """Equal, and of the same JSON type at every level: 1, 1.0 and True are three values."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


def decode(octets: bytes) -> dict:
    """The document of a GeoTIFF or a VRT, told apart by their first octets."""
    if octets[:2] in (b"II", b"MM"):
        return decode_tiff(octets)
    head = octets[:256].lstrip(b" \t\r\n")
    if head.startswith(b"<"):
        return decode_vrt(octets)
    raise CogRefused(
        "not-a-tiff-or-vrt", "the payload opens neither with a TIFF header nor with XML"
    )


def twin_of(octets: bytes) -> dict:
    """The parsed twin of a file: its octets as `wire_hex` and everything it states."""
    return {"wire_hex": bytes(octets).hex(), **decode(bytes(octets))}


def _from_twin(document: dict) -> dict:
    keys = set(document)
    if keys not in (set(TIFF_TWIN_KEYS), set(VRT_TWIN_KEYS)):
        raise CogRefused(
            "not-a-twin",
            "a dict is the file's twin, exactly: "
            + ", ".join(TIFF_TWIN_KEYS)
            + "; or "
            + ", ".join(VRT_TWIN_KEYS),
        )
    wire = document["wire_hex"]
    if (
        not isinstance(wire, str)
        or len(wire) > 2 * MAX_INPUT_BYTES
        or len(wire) % 2
        or _HEX.fullmatch(wire) is None
    ):
        raise CogRefused(
            "bad-wire-hex",
            f"wire_hex is not lower-case hexadecimal of at most {MAX_INPUT_BYTES} octets",
        )
    decoded = decode(bytes.fromhex(wire))
    if set(decoded) | {"wire_hex"} != keys:
        raise CogRefused("twin-disagrees", "the twin's form is not what its wire_hex decodes to")
    for key in decoded:
        if not _same(document[key], decoded[key]):
            raise CogRefused(
                "twin-disagrees", f"the twin's {key} is not what its wire_hex decodes to"
            )
    return decoded


# -- time ----------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class Sensing:
    start: _dt.datetime
    end: _dt.datetime
    system: TimeSystem
    transformation: str
    stamp: _dt.datetime


def _utc(text: str) -> _dt.datetime:
    stamp = _dt.datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    return stamp.astimezone(_dt.timezone.utc)


def stated_sensing(document: dict) -> Sensing | None:
    """The sensing instant or interval the file's dataset metadata states, or `None`."""
    items = _items(document, None)
    has_instant = SENSING_TIME in items
    present = [key for key in RANGE_KEYS if key in items]
    if has_instant and present:
        raise CogRefused(
            "two-sensing-statements",
            "GDAL_METADATA states both SENSING_TIME and a RangeBeginning/RangeEnding interval",
        )
    if has_instant:
        text = items[SENSING_TIME]["value"]
        if _RFC3339.fullmatch(text) is None:
            raise CogRefused(
                "unreadable-sensing-time",
                "GDAL_METADATA's SENSING_TIME is not one RFC 3339 instant with seconds and its "
                "zone; a stamp without a zone is never read as UTC",
            )
        try:
            instant = _utc(text)
        except (ValueError, OverflowError):
            raise CogRefused(
                "unreadable-sensing-time", "GDAL_METADATA's SENSING_TIME names no instant in UTC"
            ) from None
        zone = "UTC" if text.endswith("Z") else f"UTC{text[-6:]}"
        return Sensing(
            instant,
            instant,
            TimeSystem(
                name=zone,
                stated_by="source",
                basis="GDAL_METADATA (TIFF tag 42112) item SENSING_TIME, an RFC 3339 instant "
                "with its zone",
            ),
            T_SENSING_STATED,
            instant,
        )
    if not present:
        return None
    if len(present) != len(RANGE_KEYS):
        raise CogRefused(
            "partial-sensing-range",
            "GDAL_METADATA states some of RangeBeginningDate, RangeBeginningTime, RangeEndingDate "
            "and RangeEndingTime and not all four",
        )
    bounds = []
    for date_key, time_key in (RANGE_KEYS[:2], RANGE_KEYS[2:]):
        date, clock = items[date_key]["value"], items[time_key]["value"]
        if _DATE.fullmatch(date) is None or _TIME_Z.fullmatch(clock) is None:
            raise CogRefused(
                "unreadable-sensing-range",
                f"GDAL_METADATA's {date_key} and {time_key} are not YYYY-MM-DD and HH:MM:SS "
                "ending Z; a time without its zone is never read as UTC",
            )
        try:
            bounds.append(_utc(f"{date}T{clock}"))
        except (ValueError, OverflowError):
            raise CogRefused(
                "unreadable-sensing-range", f"GDAL_METADATA's {date_key} names no date"
            ) from None
    start, end = bounds
    if end < start:
        raise CogRefused(
            "sensing-range-reversed", "GDAL_METADATA's sensing interval ends before it begins"
        )
    return Sensing(
        start,
        end,
        TimeSystem(
            name="UTC",
            stated_by="source",
            basis="GDAL_METADATA (TIFF tag 42112) items RangeBeginningDate, RangeBeginningTime, "
            "RangeEndingDate and RangeEndingTime, each time ending Z",
        ),
        T_SENSING_RANGE,
        start,
    )


def processing_clock(document: dict) -> str | None:
    """The first processing clock the file states, verbatim: product_version only."""
    items = _items(document, None)
    for key in PROCESSING_CLOCKS:
        if key in items:
            return items[key]["value"]
    return _stated_text(document, "DateTime")


# -- the declaration -----------------------------------------------------------------------------


def _residual(key: str) -> Mapping:
    return Mapping(to=f"#0:residual.data.{key}", kind="residual")


def _text(value: Any, name: str) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip() or len(value) > 1024 or "\x00" in value:
        raise ValueError(f"{name} is a non-blank text of at most 1024 characters, or None")
    return value


class CogAdapter(Adapter):
    """One GeoTIFF, COG or VRT in; one Event or one PlanObject out."""

    name = "cog"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration. `OPEN`: OGC GeoTIFF 1.1 and OGC COG 1.0 are published under
    #: the OGC licence (free use, copy and distribution with notices, research-raster F7); TIFF
    #: 6.0's Aldus notice permits copies only verbatim and not for direct commercial advantage,
    #: so it is pinned by reference and never carried (DECISIONS L-10, L-30).
    metadata = AdapterMetadata(
        id="cog",
        name="Cloud Optimized GeoTIFF header reader",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.OPEN,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter cog` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every directory, GeoKey, metadata item and the decoded window a structured residual, "
            "the block index and the octets a declared limitation) with no LOST leaf on any "
            "parsed twin. L4 is NOT declared: this adapter is ingest-only, so the roundtrip check "
            "is inapplicable rather than passed (ARCHITECTURE.md §3.6, rule 4), and a rung passed "
            "vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "classic GeoTIFF / Cloud Optimized GeoTIFF, one band a file: every directory, the "
                "GeoKeys, GDAL_METADATA and GDAL_NODATA read, block 0 of the full-resolution "
                "image decoded (none, LZW, Deflate, PackBits; predictors 1, 2 and 3); one "
                "ENVIRONMENTAL_OBSERVATION Event (imagery-product/1) when a sensing time is "
                "stated or supplied, else one ANNOTATION PlanObject",
                "GDAL VRT, as an index: its footprint and its sources listed, never opened; one "
                "ANNOTATION PlanObject",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=1,
                max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
                max_parse_seconds=None,
                absent_because={
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, every walk is linear in the octets read, one block of at most "
                    "max_decompressed_bytes is decoded, and the conformance suite's parser worker "
                    "kills a decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "3DEP n41w074 165,776,270 B and CUDEM tiles 150-217 MB (research-raster "
                            "F5/F6): the largest files of the two products the design record "
                            "measured. TIFF 6.0 states no maximum below the 4 GiB its 32-bit "
                            "offsets reach. 256 MiB (268 435 456 octets, `MAX_INPUT_BYTES`, "
                            "`adapters/cog.py`) is DECISIONS U-07's bound, above the largest; "
                            "the conformance suite allocates bound + 1 three times a run, about "
                            "768 MiB, a cost U-07 accepted. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module reads the header"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_decompressed_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "One 512 x 512 tile of 32-bit floats is 1,048,576 octets "
                            "(research-raster F9, F16): the block of the 3DEP and CUDEM COGs. "
                            "1 MiB (`MAX_DECOMPRESSED_BYTES`, `adapters/cog.py`) is that block, "
                            "the one block this module decodes. " + _CAP
                        ),
                        enforced_at=(
                            "`raster_codec.decode_block`: block 0's decoded size is compared with "
                            "the bound before any octet is decompressed and refused "
                            "`block-past-the-decompression-bound`; LZW, Deflate and PackBits are "
                            "then held to exactly the block's size, and an octet past it is "
                            "refused `block-inflates-past-its-size` before it is kept"
                        ),
                        test=_TESTS
                        + "test_a_block_is_held_to_the_bound_before_and_while_it_inflates",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "One object a file: one band file is one product object "
                            "(design-judge DJ-09), and a VRT is one index. " + _CAP
                        ),
                        enforced_at="`CogAdapter.to_cdm` returns exactly one object",
                        test=_TESTS + "test_every_fixture_becomes_exactly_one_object",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets are never JSON; the dict form, the parsed twin, nests "
                            "seven containers (a rational inside a tag inside a directory). 16 "
                            "(`MAX_DEPTH`, `adapters/cog.py`) is the dis7 envelope's bound, and "
                            "the VRT's XML is held to the same depth. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__`'s wrapper calls "
                            "`adapter.enforce_depth_bound` on a dict before this class's "
                            "`to_cdm` runs; `secure_xml.parse` refuses a VRT element past it"
                        ),
                        test=_TESTS + "test_a_twin_past_the_depth_bound_is_refused_before_decode",
                    ),
                },
            ),
            unknown_fields=UnknownFields.NONE,
            unknown_fields_basis=(
                "the dict form is held to be exactly what its own wire_hex decodes to, so a key "
                "injected into a twin is refused `not-a-twin` or `twin-disagrees`; on the wire, a "
                "TIFF tag, a GeoKey or a GDAL_METADATA item this module does not name is read by "
                "its type and kept in the residual, and a VRT element it does not read is refused"
            ),
        ),
        limitations=[
            by_reference_limitation(
                ["arrays"],
                notes=(
                    "the twin's `arrays` holds each directory's block offsets and byte counts as "
                    "the file states them; they are read to locate and check every block, and the "
                    "values stay in the file but for the one window"
                ),
            ),
            Limitation(
                id="payload-octets-by-reference",
                summary="the twin's wire_hex is the file's octets, the input its dict form is "
                "decoded from; they are identified by SourceRef.source_hash when the caller gives "
                "it and are not copied into any object",
                unsupported_paths=["wire_hex"],
            ),
            Limitation(
                id="no-source-time",
                summary="a DEM and a VRT state no instant, so the PlanObject carries no "
                "timestamp unless the caller supplies an as-of "
                "(`CogAdapter(as_of=InjectedTime(instant, basis))`), which lands at "
                "`validity.observed_at` with its basis in `source.transformations`. A band file "
                "whose metadata states a sensing time becomes an Event and is judged on it. The "
                "conformance suite's check J reads this id as the declared reason it may find no "
                "timestamp to judge",
                unsupported_paths=[],
            ),
            Limitation(
                id="header-and-one-window",
                summary="the values are read for one window only: block 0 of the full-resolution "
                "image (its north-west tile or first strip), clipped to the image, at most 1 MiB "
                "decoded; it is summarised in the stored values and carried inline when it holds "
                "at most 4096 cells (and, in an Event, when the file states its unit and no scale "
                "or offset). Every other block is checked to lie in the file and is not decoded; "
                "overview and mask directories are read as structure",
                unsupported_paths=[],
            ),
            Limitation(
                id="coordinate-systems-read",
                summary="a footprint is converted from EPSG:4326, EPSG:4269 (NAD83, stated as "
                "WGS84 without a datum shift) and the WGS84 UTM zones only, and a vertical system "
                "only from EPSG:5703 (NAVD88 height); every other system, a user-defined one, a "
                "rotation and more than one tiepoint are refused by name. A height is never "
                "converted to the ellipsoid: the datum stays beside it in the residual",
                unsupported_paths=[],
            ),
            Limitation(
                id="tiff-forms-read",
                summary="classic TIFF only (BigTIFF refused by name); one sample a pixel; "
                "compression none, LZW, Deflate and PackBits (JPEG, LERC, ZSTD, LZMA, WebP and "
                "JPEG 2000 refused by name); predictors 1, 2 (integer samples) and 3 (Float32 and "
                "Float64); samples of 8, 16 or 32 bits signed or unsigned, Float32 and Float64",
                unsupported_paths=[],
            ),
            Limitation(
                id="vrt-index-only",
                summary="a VRT is read as an index: its size, SRS, GeoTransform, metadata and "
                "simple or complex sources, listed and never opened; a remote source, a DTD, an "
                "entity and any other element (a derived band, a pixel function, an overview) are "
                "refused by name",
                unsupported_paths=[],
            ),
            Limitation(
                id="identity-from-what-the-file-states",
                summary="without `band_file` an object's id derives from what the file states: "
                "its coordinate system, size, north-west corner, cell, sample type and sensing "
                "interval (a VRT's: its system, size, corner, cell and source count), followed by "
                "the caller's `source_hash` digest when it gives one. With neither `band_file` nor "
                "`source_hash`, two band files of one granule that share a grid and a sensing time "
                "share an id; a caller that holds several bands of a granule passes `band_file` "
                "(and `granule_id`) or `source_hash`",
                unsupported_paths=[],
            ),
            Limitation(
                id="evidence-availability",
                summary="`evidence.available` is false because no published Release carries "
                "this adapter's records yet; it becomes true at the first release that "
                "attaches them",
            ),
        ],
        limitations_empty_reason=None,
        residual=ResidualStance.STRUCTURED,
        payload_adapter=None,
        constituents=[],
        evidence=Evidence(available=False),
    )

    TRANSFORMS: dict[str, str] = {"wire_hex": T_WIRE, "arrays": T_ARRAYS}

    #: The ledger. One object a file, so `#0` is the object. Every key of the twin but the octets
    #: and the block index is parked whole in the object's residual, at its own path.
    MAPPINGS = {
        "header": _residual("header"),
        "ifds": _residual("ifds"),
        "geokeys": _residual("geokeys"),
        "gdal_metadata": _residual("gdal_metadata"),
        "vertical": _residual("vertical"),
        "window": _residual("window"),
        "vrt": _residual("vrt"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        source_hash: SourceHash | dict | None = None,
        sensing_time: InjectedTime | None = None,
        as_of: InjectedTime | None = None,
        band_file: str | None = None,
        granule_id: str | None = None,
    ) -> None:
        """`source_hash` is the SHA-256 of the file as the caller read it; `sensing_time` the
        sensing instant of a band file whose metadata states none, with its basis; `as_of` the
        instant a timeless product (a DEM, a VRT) is a snapshot of, with its basis; `band_file`
        the file's name and `granule_id` the granule its band files share, used only as
        identifiers — a file name's timestamp is never read as a time. All are values the caller
        computed and constructor arguments, so all are in the determinism tuple."""
        super().__init__(clock, synthetic=synthetic)
        if source_hash is not None:
            source_hash = SourceHash.model_validate(source_hash)
            if source_hash.algorithm != "sha256" or not re.fullmatch(
                "[0-9a-f]{64}", source_hash.value
            ):
                raise ValueError("source_hash is a sha256 digest of 64 lower-case hex digits")
        for name, value in (("sensing_time", sensing_time), ("as_of", as_of)):
            if value is not None and not isinstance(value, InjectedTime):
                raise TypeError(f"{name} is an InjectedTime(instant, basis)")
        if sensing_time is not None and as_of is not None:
            raise ValueError(
                "sensing_time is for a sensed product and as_of for a timeless one; not both"
            )
        band_file = _text(band_file, "band_file")
        if band_file is not None and _NAME.fullmatch(band_file) is None:
            raise ValueError("band_file is a file name, without a directory")
        self._source_hash = source_hash
        self._sensing = sensing_time
        self._as_of = as_of
        self._band_file = band_file
        self._granule = _text(granule_id, "granule_id")

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One file -> [one Event or one PlanObject]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            document = decode(bytes(raw))
        elif isinstance(raw, dict):
            document = _from_twin(raw)
        else:
            raise CogRefused(
                "unsupported-input",
                "a file is handed over as its octets or as its twin in a dict; text and other "
                "types are not taken",
            )
        if "vrt" in document:
            return [self._vrt(document)]
        return [self._tiff(document)]

    # -- translation -----------------------------------------------------------------------------

    def _identity(self, georef: Georeference, dtype: str, sensing: Sensing | None) -> str:
        if self._band_file is not None:
            return f"{self._granule}/{self._band_file}" if self._granule else self._band_file
        text = (
            f"EPSG:{georef.code} {georef.width}x{georef.height} at {georef.west!r},"
            f"{georef.north!r} cell {georef.cell_x!r}x{georef.cell_y!r} {dtype}"
        )
        if sensing is not None:
            text += f" sensed {times.render(sensing.start)} to {times.render(sensing.end)}"
        return text + self._digest_suffix()

    def _digest_suffix(self) -> str:
        # The band files of one granule share a grid, a sample type and a sensing time, so a
        # descriptor of those alone gives two bands one id; the caller's digest of the file, when
        # it gives one, tells them apart (D-R6-14 as amended in fix round 1).
        return f" sha256 {self._source_hash.value}" if self._source_hash is not None else ""

    def _locator(self, window: dict, tiled: bool) -> RasterLocator:
        return RasterLocator(
            kind="raster",
            band_file=self._band_file,
            granule_id=self._granule,
            ifd=0,
            tile=0 if tiled else None,
            window=RasterWindow(
                column=window["column"],
                row=window["row"],
                width=window["width"],
                height=window["height"],
            ),
        )

    def _footprint_note(self, georef: Georeference) -> str:
        if georef.system == "utm":
            return T_FOOTPRINT_UTM
        return T_FOOTPRINT_NAD83 if georef.code == 4269 else T_FOOTPRINT_GEOGRAPHIC

    def _tiff(self, document: dict) -> CDMBase:
        georef = georeference(document)
        stated = stated_sensing(document)
        items = _items(document, None)
        if stated is not None and self._sensing is not None:
            raise CogRefused(
                "sensing-time-stated-twice",
                "the file's metadata states its sensing time and the caller supplied one too",
            )
        sensing = stated
        if sensing is None and self._sensing is not None:
            instant = self._sensing.instant
            sensing = Sensing(
                instant,
                instant,
                TimeSystem(name="UTC", stated_by="caller", basis=self._sensing.basis),
                f"{T_SENSING_INJECTED} — {self._sensing.basis}",
                instant,
            )
        if sensing is None and any(key in items for key in PROCESSING_CLOCKS):
            raise CogRefused(
                "sensing-time-required",
                "the file names a sensed product's processing clock and states no sensing time; "
                "the caller supplies it as sensing_time with its basis (DECISIONS L-12), and it "
                "is never taken from the file name or guessed",
            )
        window = document["window"]
        tiled = "TileWidth" in document["ifds"][0]["tags"]
        notes = [self._footprint_note(georef), T_WINDOW]
        residual = Residual(
            namespace=self.metadata.format.name,
            data={
                key: document[key] for key in TIFF_TWIN_KEYS if key not in ("wire_hex", "arrays")
            },
        )
        identity = self._identity(georef, window["dtype"], sensing)
        geometry = Polygon(coordinates=[georef.ring])
        if sensing is None:
            return self._plan_object(identity, geometry, notes, residual)
        if self._as_of is not None:
            raise CogRefused(
                "as-of-for-a-sensed-product",
                "the caller supplied an as-of for a file that states its sensing time",
            )
        return self._event(
            document, georef, sensing, window, tiled, identity, geometry, notes, residual
        )

    def _plan_object(self, identity, geometry, notes, residual) -> PlanObject:
        validity = None
        stamp = None
        if self._as_of is not None:
            validity = TemporalValidity(observed_at=self._as_of.instant)
            stamp = self._as_of.instant
            notes = notes + [f"{T_AS_OF} — {self._as_of.basis}"]
        source = self.source_ref().model_copy(
            update={
                "observed_at": stamp,
                "source_hash": self._source_hash,
                "original_id": self._band_file,
                "transformations": notes,
            }
        )
        return PlanObject(
            source=source,
            source_ids=[SourceId(system=SYSTEM, external_id=identity)],
            object_id=ids.derive(SYSTEM, identity, kind="plan_object"),
            object_type=ObjectType.ANNOTATION,
            label=None,
            geometry=geometry,
            style={},
            validity=validity,
            residual=residual,
        )

    def _event(self, document, georef, sensing, window, tiled, identity, geometry, notes, residual):
        band = _items(document, 0)
        unit = None
        if "UNITTYPE" in band:
            unit = UnitRef(
                unit=band["UNITTYPE"]["value"],
                unit_namespace="GDAL_METADATA (TIFF tag 42112) item UNITTYPE, band 1",
            )
        elif document["vertical"] is not None:
            unit = UnitRef(
                unit=document["vertical"]["unit"],
                unit_namespace=document["vertical"]["unit_namespace"],
            )
        scale = _band_number(band, "SCALE")
        offset = _band_number(band, "OFFSET")
        unscaled = scale in (None, 1.0) and offset in (None, 0.0)
        locator = self._locator(window, tiled)
        nodata = document["ifds"][0]["tags"].get("GDAL_NODATA")
        if window["values"] is not None and unit is not None and unscaled:
            values = ValuesInline(
                mode="inline",
                shape=[window["height"], window["width"]],
                values=window["values"],
                missing_mechanism=window["missing_mechanism"],
            )
        else:
            values = ValuesByReference(
                mode="reference",
                locator=locator,
                shape=[window["height"], window["width"]],
                dtype=window["dtype"],
                encoding=window["encoding"],
                scale=scale,
                offset=offset,
                fill=nodata["value"] if nodata is not None else None,
                summary=ArraySummary(
                    count=window["count"],
                    missing_count=window["missing_count"],
                    min=window["min"],
                    max=window["max"],
                ),
            )
        flags = [
            QualityFlag(
                name=key,
                value=items_value,
                namespace="GDAL_METADATA (TIFF tag 42112) dataset item, HLS v2.0 User Guide "
                "Table 11",
                applies_to="granule",
            )
            for key in QUALITY_ITEMS
            if (items_value := _items(document, None).get(key, {}).get("value"))
        ]
        clock = processing_clock(document)
        software = _stated_text(document, "Software")
        version = None
        if clock is not None or software is not None:
            version = ProductVersion(production_time_verbatim=clock, producer=software)
        description = band.get("DESCRIPTION", {}).get("value")
        image = _stated_text(document, "ImageDescription")
        contract = ImageryProduct(
            contract="imagery-product/1",
            product_class="observation",
            product_version=version,
            time=TimeInputs(source_time_system=sensing.system),
            locator=locator,
            quality_flags=flags,
            quality_flags_basis=None
            if flags
            else "the file states no quality summary; a product's quality layers (HLS Fmask, "
            "ECOSTRESS QC) are band files of their own, each its own object",
            product=Quantity(
                name=image,
                code="IFD 0",
                namespace="TIFF 6.0: the file's first image file directory, named by its "
                "ImageDescription (tag 270) where it states one",
            ),
            band=Quantity(
                name=description or None,
                code="sample 0",
                namespace="GDAL_METADATA (TIFF tag 42112) item DESCRIPTION of band 1, where stated",
            ),
            unit=unit,
            grid=GridBlock(
                namespace="OGC GeoTIFF 1.1",
                template=georef.template,
                shape=[georef.height, georef.width],
                cell_size=[
                    Measurement(
                        value=georef.cell_y,
                        unit=georef.unit,
                        unit_namespace="OGC GeoTIFF 1.1 ModelPixelScaleTag",
                    ),
                    Measurement(
                        value=georef.cell_x,
                        unit=georef.unit,
                        unit_namespace="OGC GeoTIFF 1.1 ModelPixelScaleTag",
                    ),
                ],
                parameters={
                    "geokeys": {k["name"]: k["value"] for k in document["geokeys"]["keys"]},
                    "ModelPixelScaleTag": document["ifds"][0]["tags"]["ModelPixelScaleTag"][
                        "value"
                    ],
                    "ModelTiepointTag": document["ifds"][0]["tags"]["ModelTiepointTag"]["value"],
                },
            ),
            values=values,
        )
        source = self.source_ref().model_copy(
            update={
                "observed_at": sensing.stamp,
                "source_hash": self._source_hash,
                "original_id": self._band_file,
                "transformations": notes + [sensing.transformation],
            }
        )
        return observation_event(
            source=source,
            source_ids=[SourceId(system=SYSTEM, external_id=identity)],
            observation=contract,
            observed_at=sensing.end,
            received_at=self.now(),
            validity=TemporalValidity(effective=Period(start=sensing.start, end=sensing.end)),
            geometry=geometry,
            residual=residual,
        )

    def _vrt(self, document: dict) -> PlanObject:
        if self._sensing is not None:
            raise CogRefused(
                "sensing-time-for-an-index", "the caller supplied a sensing time for a VRT index"
            )
        georef = vrt_georeference(document)
        vrt = document["vrt"]
        identity = self._band_file or (
            f"VRT EPSG:{georef.code} {georef.width}x{georef.height} at {georef.west!r},"
            f"{georef.north!r} cell {georef.cell_x!r}x{georef.cell_y!r} "
            f"{sum(len(b['sources']) for b in vrt['bands'])} sources{self._digest_suffix()}"
        )
        residual = Residual(namespace=self.metadata.format.name, data={"vrt": vrt})
        return self._plan_object(
            identity, Polygon(coordinates=[georef.ring]), [self._footprint_note(georef)], residual
        )


def _band_number(band: dict, name: str) -> float | None:
    item = band.get(name)
    if item is None:
        return None
    text = item["value"].strip()
    value = decimal_float(text) if _DECIMAL.fullmatch(text) else None
    if value is None:
        raise CogRefused(
            "bad-scale", f"GDAL_METADATA's {name} for band 1 is not a finite decimal number"
        )
    return value
