"""`grib2`, #29 in the ordinal table: one GRIB2 message -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
ONE GRIB edition 2 message: Section 0's sixteen octets ("GRIB", the discipline, the edition and an
eight-octet total length), Sections 1 to 7, and the "7777" of Section 8. A file is a concatenation
of messages and is never a payload here: the design record's largest single message on the replay
day is 3,810,470 octets, its files 17 MB to 713 MB (gap-grib2-wire-facts F02), and
`synapse-decode` cuts a file into its messages by their Section 0 lengths and hands each one over
with its 0-based ordinal and the octet it begins at. `to_cdm` takes the message's octets, or its
parsed twin (`<name>.parsed.json`: the octets as `wire_hex` and everything the message states),
which is held to be exactly what its own `wire_hex` decodes to.

The layouts are read against NCEP's WMO GRIB2 documentation (version 37.0.0, 2026-06-01) and
the WMO's FM 92 GRIB, both cited by reference in `fixtures/grib2/spec/grib2_pin.json` and never
carried; the few code-table rows this module states words or units for are listed there with the
file each was read from. Nothing here is ported from a decoder that exists elsewhere.

WHAT ONE MESSAGE BECOMES
------------------------
One `ENVIRONMENTAL_OBSERVATION` Event per FIELD, in the order the message holds them. A message
may repeat Sections 4 to 7 (the design record's RAP file holds 49 of 306 messages with two fields),
so the message ordinal alone does not locate a field: every Event's `grib` locator names the
message, the field and the octet the message begins at. Each Event carries `gridded-field/1`:

- the time is the reference time with its Table 1.2 significance, the forecast offset with its
  Table 4.4 unit, and for Product Definition Template 4.8 the statistical process; the forecast's
  own validity is `Event.validity.effective` (an instant for 4.0, the overall interval for 4.8),
  and `observed_at` is the REFERENCE time, never a future valid instant (design-consumer-and-time
  D3). There is no `analysis_at`: for an observation-time product the reference time is not an
  analysis (research-grib2 F05).
- the class follows Section 1's type of processed data (Table 1.4): an analysis product is
  `analysis`, a forecast product `forecast` when its validity ends after the reference time and
  `analysis` when it does not, processed radar observations `modelled_estimate`. Any other type is
  refused by name rather than given a class nobody ruled.
- the grid is the SOURCE's: the template number, the shape `[Nj, Ni]`, the scanning mode and
  every template octet verbatim under its own name. There is no `crs` field; the canonical
  geometry is a WGS84 footprint Polygon: a lat/lon grid's four corner points, a Lambert conformal
  grid's outline converted point by point with the spherical inverse and densified along each edge,
  because a projected rectangle's edges are curves in longitude and latitude.
- the values stay in the message, BY REFERENCE: the locator, the shape, the packing and a summary
  of the decoded field — count, missing count, minimum and maximum in the field's own units. A
  value is missing when the Section 6 bitmap leaves its point out, when complex packing's Table
  5.5 management marks it, or when a parameter's sentinel table names it (MRMS QPE writes -1
  "Missing" and -3 "No Coverage" as data; research-grib2 F06). Each mechanism is counted in its
  own quality flag and never merged.

Simple packing (template 5.0, including the zero-width form whose Section 7 holds no octet and
whose field is R / 10^D everywhere), complex packing with spatial differencing (5.3, orders 1 and
2, Table 5.5 management 0, 1 and 2) and PNG (5.41, 8- and 16-bit greyscale, inflated under
`max_decompressed_bytes`) are decoded. JPEG 2000 (5.40) is READ, NOT DECODED (DECISIONS U-02):
Sections 0 to 6 are read, Section 7 is checked to open with a bare codestream's SOC and SIZ
markers, and its octets are declared unsupported rather than lost.

No field is held whole while it is summarised. Complex packing states a run of equal values in no
octets at all, so a message of a few hundred octets can describe MAX_GRID_POINTS values; every
packing therefore hands its codes on at most CHUNK at a time, and what a decode holds is a few
copies of the message's octets, one chunk, and for PNG the inflated rows `max_decompressed_bytes`
bounds, whatever the number of points. Nor is a record kept per missing mark: complex packing walks
its codes once, holding nothing, for the present values its differencing needs before the summary
sees a code, and then hands every run of marks on as it ends.

WHAT IS REFUSED
---------------
Edition 1 by name; a total length that is not the payload's; a message without its "7777"; a
section that runs past the end or comes out of order; a grid template other than 3.0 and 3.30 (the
RAP wrfmsl's 32769 among them), a product template other than 4.0 and 4.8, a packing template other
than 5.0, 5.3, 5.40 and 5.41; a bitmap whose set points are not Section 5's count; a PNG whose CRC
fails or whose rows would inflate past the bound. A refusal is a `Grib2Refused` (`ValueError`)
whose code names the rule and whose text names the section and the field, never a value.
"""

from __future__ import annotations

import array
import dataclasses
import datetime as _dt
import itertools
import math
import re
import struct
import sys
import zlib
from typing import Any, Iterator

from synapse_cdm import times
from synapse_cdm.adapter import Adapter
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
    Residual,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.observation_contracts import (
    ArraySummary,
    CodedValue,
    GribLocator,
    GriddedField,
    Grid,
    Measurement,
    ProductVersion,
    QualityFlag,
    Quantity,
    TimeInputs,
    TimeSystem,
    UnitRef,
    ValuesByReference,
    VerticalLevel,
    by_reference_limitation,
    observation_event,
)

#: `source.system` on every object and the system of every identifier.
SYSTEM = "GRIB2"
#: The residual namespace and `SourceRef.format_name`, read from the declaration below.
FORMAT_NAME = "GRIB2 (WMO FM 92 GRIB edition 2)"
#: The documentation this module is written against.
FORMAT_VERSION = (
    "GRIB edition 2, read against NCEP's WMO GRIB2 Documentation version 37.0.0 (2026-06-01)"
)
NCEP = "NCEP GRIB2 documentation"

# -- bounds (DECISIONS U-07; each declared with its basis below) ---------------------------------

MAX_INPUT_BYTES = 8 * 1024 * 1024
#: The PNG rows of every 5.41 field of one message, inflated, at most.
MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024
#: The grid points the fields of one message describe, summed, at most.
MAX_GRID_POINTS = 1 << 25
#: One Event per field.
MAX_FIELDS = 16
#: The twin nests five containers deep; the bound is dis7's envelope bound.
MAX_DEPTH = 16

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_grib2_adapter.py::"

MAX_GRID_POINTS_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "The largest grid the design record measured is MRMS QPE's 7000 x 3500 lat/lon grid, "
        "24,500,000 points (gap-grib2-wire-facts F01/F04); HRRR's Lambert grid is 1799 x 1059, "
        "1,905,141 points, and RAP's grid 130 is 451 x 337. 2^25 = 33,554,432 points "
        "(`MAX_GRID_POINTS`, `adapters/grib2.py`) sits above the largest. A bound is needed "
        "besides the octet bound because complex packing states a run of equal values in no "
        "octets at all, so an 8 MiB message can describe billions of points. " + _CAP
    ),
    enforced_at=(
        "`grib2.decode_message`: each Section 3's Ni x Nj is added to the message's running "
        "total before any value of the field is read, and the total past MAX_GRID_POINTS is "
        "refused `grid-past-the-points-bound`"
    ),
    test=_TESTS + "test_the_grid_points_of_one_message_are_held_to_their_bound",
)

# -- the vocabulary ------------------------------------------------------------------------------

#: GRIB2 Code Table 1.2, the meanings the design record quotes (research-grib2 F05). Code 4 and up
#: are refused: a reference time that is not one of these four is a semantics nobody ruled on.
SIGNIFICANCE = {
    0: "Analysis",
    1: "Start of Forecast",
    2: "Verifying Time of Forecast",
    3: "Observation Time",
}
#: GRIB2 Code Table 4.4, the units the design record quotes, in seconds. A month or a year is a
#: calendar unit with no fixed length, and the others are not in the record; both are refused.
TIME_UNITS = {0: ("Minute", 60), 1: ("Hour", 3600), 13: ("Second", 1)}
#: GRIB2 Code Table 4.10, the one meaning the design record quotes; other codes are carried
#: without words.
STATISTICAL_PROCESSES = {1: "Accumulation"}
#: GRIB2 Code Table 5.0, the four templates read, in the table's own words (gap-grib2-wire-facts
#: F01 quotes them).
PACKINGS = {
    0: "Grid Point Data - Simple Packing",
    3: "Grid Point Data - Complex Packing and Spatial Differencing",
    40: "Grid point data - JPEG 2000 code stream format",
    41: "Grid point data - Portable Network Graphics (PNG)",
}
#: Code Table 1.4, type of processed data, and the product class each is: (meaning, class). `None`
#: means "by the validity": forecast when the validity ends after the reference time.
DATA_TYPES = {
    0: ("Analysis Products", "analysis"),
    1: ("Forecast Products", None),
    2: ("Analysis and Forecast Products", None),
    7: ("Processed Radar Observations", "modelled_estimate"),
}

_TABLES = "fixtures/grib2/spec/grib2_pin.json"
_GDAL_TABLES = "GDAL 3.13.3 GDAL_DATA, generated from wmo-im/GRIB2 at a9c4acc"
#: GDAL's NCEP local table carries no generation header of its own; it is named by its file.
_GDAL_NCEP = "GDAL 3.13.3 GDAL_DATA: grib2_table_4_2_local_NCEP"


@dataclasses.dataclass(frozen=True)
class Parameter:
    """One Table 4.2 row this module states a name and a unit for, and where it was read. `unit`
    is None where the row's unit column states a code's meanings instead of a unit (NCEP's
    categorical fields: GDAL writes "0=no; 1=yes"), which is not a unit a value is in."""

    short_name: str
    name: str
    unit: str | None
    source: str
    #: Values the source writes as data to mean "no value", each with its meaning.
    sentinels: tuple[tuple[float, str], ...] = ()


#: (discipline, category, number) -> the WMO Table 4.2 row, as GDAL's table files state it. A
#: parameter missing here keeps its code and states no unit: a unit nobody read is not stated.
#: Beside the fixtures' parameters, the WMO rows of the HRRR and RAP fields the design record
#: names (gap-grib2-wire-facts F01: TMP, PRES, HGT).
PARAMETERS: dict[tuple[int, int, int], Parameter] = {
    (0, 0, 0): Parameter("TMP", "Temperature", "K", f"{_GDAL_TABLES}: grib2_table_4_2_0_0"),
    (0, 1, 1): Parameter("RH", "Relative humidity", "%", f"{_GDAL_TABLES}: grib2_table_4_2_0_1"),
    (0, 1, 8): Parameter(
        "APCP", "Total precipitation", "kg/(m^2)", f"{_GDAL_TABLES}: grib2_table_4_2_0_1"
    ),
    (0, 2, 2): Parameter(
        "UGRD", "u-component of wind", "m/s", f"{_GDAL_TABLES}: grib2_table_4_2_0_2"
    ),
    (0, 2, 3): Parameter(
        "VGRD", "v-component of wind", "m/s", f"{_GDAL_TABLES}: grib2_table_4_2_0_2"
    ),
    (0, 3, 0): Parameter("PRES", "Pressure", "Pa", f"{_GDAL_TABLES}: grib2_table_4_2_0_3"),
    (0, 3, 5): Parameter(
        "HGT", "Geopotential height", "gpm", f"{_GDAL_TABLES}: grib2_table_4_2_0_3"
    ),
    (0, 19, 0): Parameter("VIS", "Visibility", "m", f"{_GDAL_TABLES}: grib2_table_4_2_0_19"),
}
#: (centre, subcentre, discipline, category, number) -> a centre's local row. Discipline 209 is
#: outside WMO Table 0.0, so the row belongs to the centre that wrote it and is keyed by it.
LOCAL_PARAMETERS: dict[tuple[int, int, int, int, int], Parameter] = {
    (161, 0, 209, 6, 37): Parameter(
        "MultiSensor_QPE_01H_Pass2",
        "Multi-sensor accumulation 1-hour (1-hour latency)",
        "mm",
        "NSSL Operational MRMS GRIB2 Tables, MRMS Version 12.2 (research-grib2 F04)",
        sentinels=((-1.0, "Missing"), (-3.0, "No Coverage")),
    ),
    # NCEP's local rows (category or number 192 and up) for the HRRR and RAP fields the design
    # record names, keyed by centre 7 and subcentre 0 as both models' Section 1 states them
    # (gap-grib2-wire-facts F01).
    (7, 0, 0, 1, 193): Parameter("CFRZR", "Categorical Freezing Rain", None, _GDAL_NCEP),
    (7, 0, 0, 3, 196): Parameter("HPBL", "Planetary Boundary Layer Height", "m", _GDAL_NCEP),
    (7, 0, 0, 16, 196): Parameter(
        "REFC", "Maximum / Composite radar reflectivity", "dB", _GDAL_NCEP
    ),
    (7, 0, 3, 192, 1): Parameter(
        "SBT123", "Simulated Brightness Temperature for GOES 12, Channel 3", "K", _GDAL_NCEP
    ),
    (7, 0, 3, 192, 2): Parameter(
        "SBT124", "Simulated Brightness Temperature for GOES 12, Channel 4", "K", _GDAL_NCEP
    ),
    (7, 0, 3, 192, 7): Parameter(
        "SBT113", "Simulated Brightness Temperature for GOES 11, Channel 3", "K", _GDAL_NCEP
    ),
    (7, 0, 3, 192, 8): Parameter(
        "SBT114", "Simulated Brightness Temperature for GOES 11, Channel 4", "K", _GDAL_NCEP
    ),
}
#: Code Table 4.5 -> (short name, name, unit); "-" is the table's own "no unit".
SURFACES = {
    1: ("SFC", "Ground or water surface", "-"),
    2: ("CBL", "Cloud base level", "-"),
    100: ("ISBL", "Isobaric surface", "Pa"),
    101: ("MSL", "Mean sea level", "-"),
    102: ("GPML", "Specific altitude above mean sea level", "m"),
    103: ("HTGL", "Specified height level above ground", "m"),
}
SURFACES_SOURCE = f"{_GDAL_TABLES}: grib2_table_4_5"

#: Code Table 3.2's spheres and their radii in metres; shape 1 states its own radius. An
#: ellipsoid is refused for the Lambert grid: the footprint is converted with spherical formulas.
SPHERES = {0: 6367470.0, 6: 6371229.0}

# -- the section layouts -------------------------------------------------------------------------
#
# Each layout is (name, first octet as the documentation numbers it, octet count, signed). GRIB2's
# signed integers are sign and magnitude, the top bit the sign; a signed field whose octets are all
# ones is the documentation's "missing" and is read as None, there being no sign-and-magnitude
# reading of it that means anything. An unsigned field is the integer its octets state.

_S1 = (
    ("centre", 6, 2, False),
    ("subcentre", 8, 2, False),
    ("master_table_version", 10, 1, False),
    ("local_table_version", 11, 1, False),
    ("reference_time_significance", 12, 1, False),
    ("year", 13, 2, False),
    ("month", 15, 1, False),
    ("day", 16, 1, False),
    ("hour", 17, 1, False),
    ("minute", 18, 1, False),
    ("second", 19, 1, False),
    ("production_status", 20, 1, False),
    ("data_type", 21, 1, False),
)
_S3 = (
    ("source", 6, 1, False),
    ("points", 7, 4, False),
    ("optional_list_octets", 11, 1, False),
    ("optional_list_interpretation", 12, 1, False),
    ("template", 13, 2, False),
)
_EARTH = (
    ("earth_shape", 15, 1, False),
    ("radius_scale_factor", 16, 1, False),
    ("radius_scaled_value", 17, 4, False),
    ("major_axis_scale_factor", 21, 1, False),
    ("major_axis_scaled_value", 22, 4, False),
    ("minor_axis_scale_factor", 26, 1, False),
    ("minor_axis_scaled_value", 27, 4, False),
)
_GDT = {
    0: (
        72,
        _EARTH
        + (
            ("ni", 31, 4, False),
            ("nj", 35, 4, False),
            ("basic_angle", 39, 4, False),
            ("basic_angle_subdivisions", 43, 4, False),
            ("la1", 47, 4, True),
            ("lo1", 51, 4, False),
            ("resolution_flags", 55, 1, False),
            ("la2", 56, 4, True),
            ("lo2", 60, 4, False),
            ("di", 64, 4, False),
            ("dj", 68, 4, False),
            ("scanning_mode", 72, 1, False),
        ),
    ),
    30: (
        81,
        _EARTH
        + (
            ("nx", 31, 4, False),
            ("ny", 35, 4, False),
            ("la1", 39, 4, True),
            ("lo1", 43, 4, False),
            ("resolution_flags", 47, 1, False),
            ("lad", 48, 4, True),
            ("lov", 52, 4, False),
            ("dx", 56, 4, False),
            ("dy", 60, 4, False),
            ("projection_centre", 64, 1, False),
            ("scanning_mode", 65, 1, False),
            ("latin1", 66, 4, True),
            ("latin2", 70, 4, True),
            ("south_pole_lat", 74, 4, True),
            ("south_pole_lon", 78, 4, False),
        ),
    ),
}
_S4 = (("coordinate_values", 6, 2, False), ("template", 8, 2, False))
_PDT_0 = (
    ("category", 10, 1, False),
    ("number", 11, 1, False),
    ("generating_process", 12, 1, False),
    ("background_process", 13, 1, False),
    ("forecast_process", 14, 1, False),
    ("cutoff_hours", 15, 2, False),
    ("cutoff_minutes", 17, 1, False),
    ("time_unit", 18, 1, False),
    ("forecast_time", 19, 4, True),
    ("surface1_type", 23, 1, False),
    ("surface1_scale", 24, 1, True),
    ("surface1_value", 25, 4, True),
    ("surface2_type", 29, 1, False),
    ("surface2_scale", 30, 1, True),
    ("surface2_value", 31, 4, True),
)
_PDT = {
    0: (34, _PDT_0),
    8: (
        58,
        _PDT_0
        + (
            ("end_year", 35, 2, False),
            ("end_month", 37, 1, False),
            ("end_day", 38, 1, False),
            ("end_hour", 39, 1, False),
            ("end_minute", 40, 1, False),
            ("end_second", 41, 1, False),
            ("time_ranges", 42, 1, False),
            ("missing_in_statistical_process", 43, 4, False),
            ("statistical_process", 47, 1, False),
            ("increment_type", 48, 1, False),
            ("range_unit", 49, 1, False),
            ("range_length", 50, 4, False),
            ("increment_unit", 54, 1, False),
            ("increment", 55, 4, False),
        ),
    ),
}
_S5 = (("points", 6, 4, False), ("template", 10, 2, False))
_SCALING = (
    ("binary_scale", 16, 2, True),
    ("decimal_scale", 18, 2, True),
    ("bits", 20, 1, False),
    ("original_type", 21, 1, False),
)
_DRT = {
    0: (21, _SCALING),
    3: (
        49,
        _SCALING
        + (
            ("group_splitting", 22, 1, False),
            ("missing_management", 23, 1, False),
            ("groups", 32, 4, False),
            ("group_width_reference", 36, 1, False),
            ("group_width_bits", 37, 1, False),
            ("group_length_reference", 38, 4, False),
            ("group_length_increment", 42, 1, False),
            ("last_group_length", 43, 4, False),
            ("group_length_bits", 47, 1, False),
            ("spatial_differencing_order", 48, 1, False),
            ("spatial_differencing_octets", 49, 1, False),
        ),
    ),
    40: (
        23,
        _SCALING + (("compression_type", 22, 1, False), ("target_compression_ratio", 23, 1, False)),
    ),
    41: (21, _SCALING),
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_CODESTREAM = b"\xff\x4f\xff\x51"
_HEX = re.compile(r"[0-9a-f]*")
_CHUNK_TYPE = re.compile(rb"[A-Za-z]{4}")
_UTC = _dt.timezone.utc

TWIN_KEYS = (
    "wire_hex",
    "indicator",
    "identification",
    "local_use",
    "fields",
    "summaries",
    "arrays",
    "codestreams",
)

# -- the transformations, by what they read ------------------------------------------------------

T_REFERENCE = (
    "identification: the reference time is Section 1 octets 13-19 (year, month, day, hour, "
    "minute, second) in UTC; it is the contract's reference_time, SourceRef.observed_at and the "
    "Event's observed_at, which for every class this module emits is the reference time"
)
T_VALID = (
    "fields[*].product: Template 4.0's validity is the instant reference time + forecast time in "
    "its Table 4.4 unit; Template 4.8's is the overall interval from that instant (Note 2) to "
    "octets 35-41's end, held to equal its start plus the one time range's length"
)
T_LEVEL = (
    "fields[*].product.parameters.surface1_*: the level's value is the scaled value x "
    "10^-(scale factor), stated only where Table 4.5 gives the surface a unit"
)
T_FOOTPRINT_LATLON = (
    "fields[*].grid: the footprint is the Polygon through the four corner grid points, La1/Lo1 "
    "and La2/Lo2 in 10^-6 degree, longitudes past 180 degrees read west of Greenwich; a grid's "
    "edges are parallels and meridians, so the corners are its outline"
)
T_FOOTPRINT_LCC = (
    "fields[*].grid: the footprint is the outline of the Lambert conformal grid points, each "
    "converted to latitude and longitude by the spherical inverse (the earth's radius from "
    "Table 3.2 or the template), densified to at most 16 segments an edge and rounded to "
    "10^-6 degree; the sphere's coordinates are stated as WGS84 ones, without a datum shift"
)
T_SUMMARY = (
    "derived: the values stay in the message, by reference; the contract's summary decodes "
    "every value as Y = (R + X x 2^E) / 10^D, counts the points the bitmap leaves out, the "
    "values Table 5.5 marks missing and the sentinels a parameter's table names, and states the "
    "minimum and maximum of the rest"
)
T_WIRE = (
    "derived: the twin's wire_hex is the message's octets; every object is decoded from them and "
    "they are not copied, the file being identified by source_hash"
)
T_ARRAYS = (
    "derived: the twin's arrays are each field's bitmap and packed values as the message states "
    "them; the contract carries them by reference, with a summary"
)
T_CODESTREAM = (
    "derived: a Template 5.40 field's Section 7 is a JPEG 2000 codestream this module does not "
    "decode (DECISIONS U-02); the twin's codestreams hold it and the contract states no summary"
)


class Grib2Refused(ValueError):
    """A message this module will not translate. `code` names the rule; the text names the section
    and the field, never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> Grib2Refused:
    refusal = Grib2Refused("", "")
    refusal.code = code
    refusal.args = (message,)
    return refusal


# -- reading octets ------------------------------------------------------------------------------


def _read(section: bytes, layout: tuple) -> dict:
    """The fields of a layout, by name: unsigned as stated, signed as sign and magnitude."""
    out: dict[str, Any] = {}
    for name, first, size, signed in layout:
        raw = int.from_bytes(section[first - 1 : first - 1 + size], "big")
        if signed:
            top = 1 << (8 * size - 1)
            if raw == (1 << (8 * size)) - 1:
                out[name] = None
            else:
                out[name] = -(raw & (top - 1)) if raw & top else raw
        else:
            out[name] = raw
    return out


def _float32(section: bytes, first: int) -> float:
    return struct.unpack(">f", section[first - 1 : first + 3])[0]


def _missing_substitute(section: bytes, first: int, original_type: int) -> Any:
    """Template 5.3's missing-value substitute, as the type of the original values states it.
    All ones is "missing" (None); a float that is not finite is refused, JSON holding none."""
    octets = section[first - 1 : first + 3]
    if octets == b"\xff\xff\xff\xff":
        return None
    if original_type == 1:
        return int.from_bytes(octets, "big")
    value = struct.unpack(">f", octets)[0]
    if not math.isfinite(value):
        raise Grib2Refused(
            "missing-substitute-not-finite",
            "Section 5: a Template 5.3 missing-value substitute is not a finite number",
        )
    return value


def _bits(data: bytes, offset: int, width: int, count: int) -> Iterator[int]:
    """`count` unsigned integers of `width` bits from bit `offset`, most significant bit first.

    The caller has already held `data` to the length the values need, so the walk never reads
    past it. Eight- and sixteen-bit values on an octet boundary take the C path.
    """
    if count == 0:
        return iter(())
    if width == 0:
        return itertools.repeat(0, count)
    if offset % 8 == 0 and width == 8:
        start = offset // 8
        return iter(data[start : start + count])
    if offset % 8 == 0 and width == 16:
        start = offset // 8
        values = array.array("H")
        values.frombytes(data[start : start + 2 * count])
        if sys.byteorder == "little":
            values.byteswap()
        return iter(values)
    return _bit_walk(data, offset, width, count)


def _bit_walk(data: bytes, offset: int, width: int, count: int) -> Iterator[int]:
    mask = (1 << width) - 1
    index, skip = divmod(offset, 8)
    held, have = 0, 0
    if skip:
        held, have = data[index] & (0xFF >> skip), 8 - skip
        index += 1
    for _ in range(count):
        while have < width:
            held = (held << 8) | data[index]
            index += 1
            have += 8
        have -= width
        yield (held >> have) & mask
        held &= (1 << have) - 1


def _octets(bits: int) -> int:
    return (bits + 7) // 8


def _sign_magnitude(data: bytes, start: int, size: int) -> int:
    raw = int.from_bytes(data[start : start + size], "big")
    top = 1 << (8 * size - 1)
    return -(raw & (top - 1)) if raw & top else raw


# -- the decoded message -------------------------------------------------------------------------


@dataclasses.dataclass
class FieldStats:
    """What one field's values state, counted without keeping them."""

    decoded: bool
    count: int
    without_value: int
    primary_missing: int = 0
    secondary_missing: int = 0
    sentinels: dict[str, int] = dataclasses.field(default_factory=dict)
    low: float | None = None
    high: float | None = None

    @property
    def missing(self) -> int:
        return (
            self.without_value
            + self.primary_missing
            + self.secondary_missing
            + sum(self.sentinels.values())
        )


@dataclasses.dataclass
class Message:
    """A decoded message: the twin-shaped document (without `wire_hex`) and each field's
    statistics. No value is kept: `field_values` decodes a field again when a reader wants it."""

    document: dict
    stats: list[FieldStats]


@dataclasses.dataclass
class _Field:
    """One field while it is read: its sections and the octets they cut from the message."""

    grid: dict
    grid_octets: bytes
    product: dict | None = None
    product_octets: bytes = b""
    representation: dict | None = None
    representation_octets: bytes = b""
    bitmap: dict | None = None
    bitmap_octets: bytes | None = None
    data_octets: bytes = b""
    data_length: int = 0


def decode_message(octets: bytes, *, limit: int = MAX_DECOMPRESSED_BYTES) -> Message:
    """One GRIB2 message, walked section by section and every field decoded under its bounds.

    `limit` is the PNG decompression bound (`max_decompressed_bytes` unless a test lowers it).
    """
    octets = bytes(octets)
    indicator, identification, local_use, fields = _walk(octets)
    total_points = 0
    budget = [limit]
    document_fields, summaries, arrays, codestreams = [], [], [], []
    stats: list[FieldStats] = []
    for index, field in enumerate(fields):
        total_points += field.grid["points"]
        if total_points > MAX_GRID_POINTS:
            raise Grib2Refused(
                "grid-past-the-points-bound",
                f"field {index}: the message's grids describe more than MAX_GRID_POINTS = "
                f"{MAX_GRID_POINTS} points",
            )
        field_stats, packed = _decode_field(index, field, indicator, identification, budget)
        stats.append(field_stats)
        document_fields.append(
            {
                "grid": field.grid,
                "product": field.product,
                "representation": field.representation,
                "bitmap": field.bitmap,
                "data": {"section_length": field.data_length},
            }
        )
        template = field.representation["template"]
        bitmap_hex = (
            field.bitmap_octets.hex()
            if field.bitmap_octets is not None and field.bitmap["indicator"] == 0
            else None
        )
        arrays.append(
            {"bitmap_hex": bitmap_hex, "packed_hex": None if template == 40 else packed.hex()}
        )
        codestreams.append(packed.hex() if template == 40 else None)
        summaries.append(
            {
                "count": field_stats.count,
                "missing_count": field_stats.missing,
                "min": field_stats.low,
                "max": field_stats.high,
            }
            if field_stats.decoded
            else None
        )
    document = {
        "indicator": indicator,
        "identification": identification,
        "local_use": local_use,
        "fields": document_fields,
        "summaries": summaries,
        "arrays": arrays,
        "codestreams": codestreams,
    }
    return Message(document=document, stats=stats)


def _walk(octets: bytes) -> tuple[dict, dict | None, dict | None, list[_Field]]:
    """Sections 0 to 8 walked in order: the indicator, Section 1, Section 2 and each field's
    sections, every structural rule checked and no value read."""
    indicator = _indicator(octets)
    end = len(octets) - 4
    position = 16
    identification: dict | None = None
    local_use: dict | None = None
    grid: tuple[dict, bytes] | None = None
    fields: list[_Field] = []
    current: _Field | None = None
    expected = (1,)
    while position < end:
        if end - position < 5:
            raise Grib2Refused(
                "section-past-the-end",
                f"octet {position}: fewer than five octets remain before Section 8 for a "
                "section's length and number",
            )
        length = int.from_bytes(octets[position : position + 4], "big")
        number = octets[position + 4]
        where = f"Section {number} at octet {position}"
        if number < 1 or number > 7:
            raise Grib2Refused(
                "unknown-section",
                f"octet {position}: a section number outside 1 to 7 before Section 8",
            )
        if length < 5 or position + length > end:
            raise Grib2Refused(
                "section-past-the-end",
                f"{where}: its length is under five octets or runs past Section 8",
            )
        if number not in expected:
            raise _out_of_order(number, expected, where, grid is not None, bool(fields))
        section = octets[position : position + length]
        if number == 1:
            identification = _identification(section, where)
            expected = (2, 3)
        elif number == 2:
            local_use = {"section_length": length, "octets_hex": section[5:].hex()}
            expected = (3,)
        elif number == 3:
            grid = (_grid(section, where), section)
            expected = (4,)
        elif number == 4:
            if len(fields) == MAX_FIELDS:
                raise Grib2Refused(
                    "too-many-fields",
                    f"{where}: the message holds more than max_objects = {MAX_FIELDS} fields",
                )
            current = _Field(grid=grid[0], grid_octets=grid[1])
            current.product, current.product_octets = _product(section, where), section
            expected = (5,)
        elif number == 5:
            current.representation = _representation(section, where)
            current.representation_octets = section
            expected = (6,)
        elif number == 6:
            current.bitmap, current.bitmap_octets = _bitmap(section, where, fields, current)
            expected = (7,)
        else:
            current.data_octets = section[5:]
            current.data_length = length
            fields.append(current)
            current = None
            expected = (4,)
        position += length
    if not fields or current is not None:
        raise Grib2Refused(
            "incomplete-message",
            "the message ends before a field's Sections 4 to 7 are complete"
            if current is not None
            else "the message holds no field: Section 8 follows before any Section 7",
        )
    return indicator, identification, local_use, fields


def _out_of_order(number: int, expected: tuple, where: str, grid: bool, fields: bool):
    if number == 3 and grid:
        return Grib2Refused(
            "repeated-grid-section",
            f"{where}: a second Section 3; this module reads one grid per message and a repeat "
            "of Sections 4 to 7 under it",
        )
    if number == 2 and fields:
        return Grib2Refused(
            "repeated-local-section",
            f"{where}: a second Section 2; this module reads Sections 4 to 7 repeated, not 2 to 7",
        )
    names = " or ".join(str(n) for n in expected)
    return Grib2Refused(
        "section-out-of-order", f"{where}: Section {names} is required here (Section 0 order)"
    )


def _indicator(octets: bytes) -> dict:
    if len(octets) < 16 or octets[:4] != b"GRIB":
        raise Grib2Refused(
            "not-grib", "the octets do not begin with Section 0's sixteen octets and 'GRIB'"
        )
    edition = octets[7]
    if edition == 1:
        raise Grib2Refused(
            "grib-edition-1",
            "Section 0 octet 8 says edition 1; GRIB edition 1 (ERA5's archive among others) is "
            "not read",
        )
    if edition != 2:
        raise Grib2Refused("unsupported-edition", "Section 0 octet 8 is not edition 2")
    total = int.from_bytes(octets[8:16], "big")
    if total > len(octets):
        raise Grib2Refused(
            "truncated-message",
            "Section 0's total length runs past the payload: the message is cut short",
        )
    if total < len(octets):
        raise Grib2Refused(
            "octets-after-message",
            "the payload is longer than Section 0's total length: one message is one payload",
        )
    if total < 20 or octets[-4:] != b"7777":
        raise Grib2Refused(
            "no-end-section", "the message does not end with Section 8's four octets '7777'"
        )
    return {"discipline": octets[6], "edition": edition, "total_length": total}


def _identification(section: bytes, where: str) -> dict:
    if len(section) != 21:
        raise Grib2Refused(
            "section-1-length", f"{where}: Section 1 is not the 21 octets of its fixed layout"
        )
    return {"section_length": 21, **_read(section, _S1)}


def _grid(section: bytes, where: str) -> dict:
    if len(section) < 14:
        raise Grib2Refused("section-3-length", f"{where}: shorter than Section 3's header")
    header = _read(section, _S3)
    template = header["template"]
    if header["source"] != 0:
        raise Grib2Refused(
            "predefined-grid",
            f"{where}: the source of grid definition is not 0; a predefined grid is not read",
        )
    if header["optional_list_octets"] != 0 or header["optional_list_interpretation"] != 0:
        raise Grib2Refused(
            "quasi-regular-grid",
            f"{where}: an optional list of numbers follows the template; a quasi-regular grid "
            "is not read",
        )
    if template not in _GDT:
        raise Grib2Refused(
            "unsupported-grid-template",
            f"{where}: grid definition template 3.{template} is not 3.0 or 3.30",
        )
    length, layout = _GDT[template]
    if len(section) != length:
        raise Grib2Refused(
            "section-3-length",
            f"{where}: Template 3.{template}'s section is {length} octets and this one is not",
        )
    parameters = _read(section, layout)
    ni, nj = (
        (parameters["ni"], parameters["nj"])
        if template == 0
        else (
            parameters["nx"],
            parameters["ny"],
        )
    )
    if ni < 2 or nj < 2:
        raise Grib2Refused(
            "grid-too-small",
            f"{where}: a grid of fewer than two points along an axis has no footprint Polygon",
        )
    if ni * nj > MAX_GRID_POINTS:
        raise Grib2Refused(
            "grid-past-the-points-bound",
            f"{where}: Ni x Nj is more than MAX_GRID_POINTS = {MAX_GRID_POINTS}",
        )
    if header["points"] != ni * nj:
        raise Grib2Refused(
            "grid-points-disagree", f"{where}: the number of data points is not Ni x Nj"
        )
    mode = parameters["scanning_mode"]
    if mode & 0x3F:
        raise Grib2Refused(
            "unsupported-scanning-mode",
            f"{where}: Flag Table 3.4 bits 3 to 8 are set; only the i and j directions are read",
        )
    if template == 0:
        _check_latlon(parameters, where)
    else:
        _check_lambert(parameters, where)
    return {"section_length": len(section), **header, "parameters": parameters}


def _check_latlon(p: dict, where: str) -> None:
    if p["basic_angle"] not in (0, 0xFFFFFFFF) or p["basic_angle_subdivisions"] not in (
        0,
        0xFFFFFFFF,
    ):
        raise Grib2Refused(
            "unsupported-basic-angle",
            f"{where}: a basic angle is stated; only 10^-6 degree units are read",
        )
    if p["la1"] is None or p["la2"] is None:
        raise Grib2Refused("grid-corner-missing", f"{where}: La1 or La2 is missing")
    for name in ("la1", "la2"):
        if not -90_000_000 <= p[name] <= 90_000_000:
            raise Grib2Refused(
                "latitude-out-of-range", f"{where}: {name} is not within -90 to 90 degrees"
            )
    for name in ("lo1", "lo2"):
        if p[name] >= 360_000_000:
            raise Grib2Refused(
                "longitude-out-of-range", f"{where}: {name} is not within 0 to 360 degrees"
            )
    north = p["la2"] > p["la1"]
    if p["la2"] != p["la1"] and north != bool(p["scanning_mode"] & 0x40):
        raise Grib2Refused(
            "grid-disagrees",
            f"{where}: La2 lies the other way from La1 than the scanning mode's j direction",
        )
    span = _lon_span(p)
    if span == 0 or p["la1"] == p["la2"]:
        raise Grib2Refused("grid-disagrees", f"{where}: the corner points do not span an area")
    if p["di"] != 0xFFFFFFFF and span != (p["ni"] - 1) * p["di"]:
        raise Grib2Refused(
            "grid-disagrees", f"{where}: Lo1 to Lo2 is not (Ni - 1) x Di in the scanning direction"
        )
    if p["dj"] != 0xFFFFFFFF and abs(p["la2"] - p["la1"]) != (p["nj"] - 1) * p["dj"]:
        raise Grib2Refused("grid-disagrees", f"{where}: La1 to La2 is not (Nj - 1) x Dj")
    west = p["lo2"] if p["scanning_mode"] & 0x80 else p["lo1"]
    if _wrap(west) + span > 180_000_000:
        raise Grib2Refused(
            "footprint-crosses-antimeridian",
            f"{where}: the grid crosses 180 degrees; a footprint across the antimeridian is not "
            "stated",
        )


def _lon_span(p: dict) -> int:
    """Microdegrees from the western to the eastern column, in the scanning direction."""
    if p["scanning_mode"] & 0x80:
        return (p["lo1"] - p["lo2"]) % 360_000_000
    return (p["lo2"] - p["lo1"]) % 360_000_000


def _wrap(micro: int) -> int:
    """A longitude in microdegrees, 0 to 360, as -180 (inclusive) to 180 (exclusive)."""
    return (micro + 180_000_000) % 360_000_000 - 180_000_000


def _check_lambert(p: dict, where: str) -> None:
    shape = p["earth_shape"]
    if shape not in SPHERES and shape != 1:
        raise Grib2Refused(
            "unsupported-earth-shape",
            f"{where}: Code Table 3.2 shape {shape} is not one of the spheres 0, 1 and 6; the "
            "footprint is converted with spherical formulas",
        )
    if shape == 1 and (p["radius_scaled_value"] in (0, 0xFFFFFFFF) or p["radius_scale_factor"] > 9):
        raise Grib2Refused("earth-radius-missing", f"{where}: shape 1 states no usable radius")
    for name in ("la1", "lad", "latin1", "latin2"):
        if p[name] is None or not -90_000_000 < p[name] < 90_000_000:
            raise Grib2Refused(
                "latitude-out-of-range", f"{where}: {name} is missing or not within -90 to 90"
            )
    for name in ("lo1", "lov"):
        if p[name] >= 360_000_000:
            raise Grib2Refused(
                "longitude-out-of-range", f"{where}: {name} is not within 0 to 360 degrees"
            )
    if p["projection_centre"] != 0:
        raise Grib2Refused(
            "unsupported-projection-centre",
            f"{where}: Flag Table 3.5 is not 0; only a north-pole-centred, one-pole projection is "
            "read",
        )
    if not (0 < p["latin1"] < 90_000_000 and 0 < p["latin2"] < 90_000_000):
        raise Grib2Refused(
            "unsupported-standard-parallels",
            f"{where}: Latin1 and Latin2 are not both in the northern hemisphere",
        )
    if p["lad"] not in (p["latin1"], p["latin2"]):
        raise Grib2Refused(
            "lad-not-a-standard-parallel",
            f"{where}: LaD, where Dx and Dy are true, is neither Latin1 nor Latin2",
        )
    if p["dx"] in (0, 0xFFFFFFFF) or p["dy"] in (0, 0xFFFFFFFF):
        raise Grib2Refused("grid-length-missing", f"{where}: Dx or Dy is zero or missing")


def _product(section: bytes, where: str) -> dict:
    if len(section) < 9:
        raise Grib2Refused("section-4-length", f"{where}: shorter than Section 4's header")
    header = _read(section, _S4)
    template = header["template"]
    if header["coordinate_values"] != 0:
        raise Grib2Refused(
            "coordinate-values",
            f"{where}: coordinate values follow the template; they are not read",
        )
    if template not in _PDT:
        raise Grib2Refused(
            "unsupported-product-template",
            f"{where}: product definition template 4.{template} is not 4.0 or 4.8",
        )
    length, layout = _PDT[template]
    if len(section) != length:
        raise Grib2Refused(
            "section-4-length",
            f"{where}: Template 4.{template}'s section is {length} octets and this one is not "
            "(Template 4.8 is read with one time range)",
        )
    return {"section_length": length, **header, "parameters": _read(section, layout)}


def _representation(section: bytes, where: str) -> dict:
    if len(section) < 11:
        raise Grib2Refused("section-5-length", f"{where}: shorter than Section 5's header")
    header = _read(section, _S5)
    template = header["template"]
    if template not in _DRT:
        raise Grib2Refused(
            "unsupported-packing-template",
            f"{where}: data representation template 5.{template} is not 5.0, 5.3, 5.40 or 5.41",
        )
    length, layout = _DRT[template]
    if len(section) != length:
        raise Grib2Refused(
            "section-5-length",
            f"{where}: Template 5.{template}'s section is {length} octets and this one is not",
        )
    parameters = {"reference_value": _float32(section, 12), **_read(section, layout)}
    if not math.isfinite(parameters["reference_value"]):
        raise Grib2Refused(
            "reference-value-not-finite", f"{where}: the reference value R is not finite"
        )
    if parameters["binary_scale"] is None or parameters["decimal_scale"] is None:
        raise Grib2Refused("scale-missing", f"{where}: E or D is missing")
    if parameters["original_type"] not in (0, 1):
        raise Grib2Refused(
            "unsupported-original-type",
            f"{where}: Code Table 5.1's type of original field values is not 0 or 1",
        )
    if template in (0, 3, 40) and parameters["bits"] > 32:
        raise Grib2Refused("bits-out-of-range", f"{where}: more than 32 bits per packed value")
    if template == 41 and parameters["bits"] not in (8, 16):
        raise Grib2Refused(
            "unsupported-png-depth",
            f"{where}: Template 5.41's depth is not 8 or 16; only greyscale samples of 8 and 16 "
            "bits are read",
        )
    if template == 3:
        parameters["primary_missing"] = _missing_substitute(
            section, 24, parameters["original_type"]
        )
        parameters["secondary_missing"] = _missing_substitute(
            section, 28, parameters["original_type"]
        )
        if parameters["group_splitting"] not in (0, 1):
            raise Grib2Refused(
                "unsupported-group-splitting",
                f"{where}: Code Table 5.4's group splitting method is not 0 or 1",
            )
        if parameters["missing_management"] not in (0, 1, 2):
            raise Grib2Refused(
                "unsupported-missing-management",
                f"{where}: Code Table 5.5's missing value management is not 0, 1 or 2",
            )
        if parameters["spatial_differencing_order"] not in (1, 2):
            raise Grib2Refused(
                "unsupported-differencing-order",
                f"{where}: the order of spatial differencing is not 1 or 2",
            )
        if not 1 <= parameters["spatial_differencing_octets"] <= 4:
            raise Grib2Refused(
                "differencing-octets-out-of-range",
                f"{where}: the octets of each spatial differencing descriptor are not 1 to 4",
            )
        for name in ("group_width_bits", "group_length_bits"):
            if parameters[name] > 32:
                raise Grib2Refused("bits-out-of-range", f"{where}: {name} is more than 32")
    return {"section_length": length, **header, "parameters": parameters}


def _bitmap(section: bytes, where: str, fields: list, current: _Field) -> tuple[dict, bytes | None]:
    indicator = section[5] if len(section) > 5 else None
    if indicator is None:
        raise Grib2Refused("section-6-length", f"{where}: Section 6 states no indicator")
    stated = {"section_length": len(section), "indicator": indicator}
    points = current.grid["points"]
    if indicator == 255:
        if len(section) != 6:
            raise Grib2Refused("section-6-length", f"{where}: indicator 255 and a bitmap follows")
        return stated, None
    if indicator == 0:
        if len(section) != 6 + _octets(points):
            raise Grib2Refused(
                "section-6-length",
                f"{where}: the bitmap is not one bit per Section 3 point, padded to an octet",
            )
        return stated, section[6:]
    if indicator == 254:
        if len(section) != 6:
            raise Grib2Refused("section-6-length", f"{where}: indicator 254 and a bitmap follows")
        previous = next(
            (f.bitmap_octets for f in reversed(fields) if f.bitmap_octets is not None), None
        )
        if previous is None or len(previous) != _octets(points):
            raise Grib2Refused(
                "no-previous-bitmap",
                f"{where}: indicator 254 and no earlier field of this message defines a bitmap "
                "for this grid",
            )
        return stated, previous
    raise Grib2Refused(
        "predefined-bitmap",
        f"{where}: Code Table 6.0 indicator {indicator} names a predefined bitmap, which is not "
        "read",
    )


# -- the values ----------------------------------------------------------------------------------


def _scaler(parameters: dict, where: str):
    """Y = (R + X x 2^E) / 10^D, with each power exact: `ldexp` scales by two exactly and
    `10**|D|` is an integer read as a float exactly up to 10^22. A value no double holds is
    refused, never an `OverflowError` or an infinity."""
    reference = parameters["reference_value"]
    binary, decimal = parameters["binary_scale"], parameters["decimal_scale"]
    power = _power(decimal, where)

    def scale(code: int) -> float:
        try:
            value = reference + math.ldexp(code, binary)
            value = value / power if decimal >= 0 else value * power
        except OverflowError:
            value = math.inf
        if not math.isfinite(value):
            raise Grib2Refused(
                "value-out-of-range",
                f"{where}: a decoded value, (R + X x 2^E) / 10^D, is past what a double holds",
            )
        return value

    return scale


def _power(decimal: int, where: str) -> float:
    if abs(decimal) > 300:
        raise Grib2Refused(
            "scale-out-of-range", f"{where}: the decimal scale factor D is past 10^300"
        )
    return float(10 ** abs(decimal))


def scale_and_offset(parameters: dict, where: str = "Section 5") -> tuple[float, float]:
    """The packing as `values.scale` and `values.offset`: Y = X x scale + offset."""
    reference = parameters["reference_value"]
    binary, decimal = parameters["binary_scale"], parameters["decimal_scale"]
    power = _power(decimal, where)
    try:
        unit = math.ldexp(1.0, binary)
        pair = (
            (unit / power, reference / power) if decimal >= 0 else (unit * power, reference * power)
        )
    except OverflowError:
        pair = (math.inf, math.inf)
    if not all(math.isfinite(v) for v in pair):
        raise Grib2Refused(
            "scale-out-of-range", f"{where}: 2^E / 10^D or R / 10^D is past what a double holds"
        )
    return pair


def _present(bitmap: bytes | None, points: int) -> int:
    if bitmap is None:
        return points
    whole, rest = divmod(points, 8)
    count = int.from_bytes(bitmap[:whole], "big").bit_count() if whole else 0
    if rest:
        count += (bitmap[whole] >> (8 - rest)).bit_count()
    return count


def _decode_field(index, field: _Field, indicator, identification, budget, collect=None):
    """One field's values decoded and summarised, or, with `collect`, appended to it in order.

    No field is ever held whole: every packing hands its codes to the sink a chunk of at most
    CHUNK at a time, so the working set does not grow with the grid (R5 review F-01). PNG is the
    one exception the bound allows: its inflated rows, at most `max_decompressed_bytes`, are held
    while they are unfiltered in place.
    """
    where = f"field {index}"
    grid_points = field.grid["points"]
    representation = field.representation
    parameters = representation["parameters"]
    template = representation["template"]
    data_points = representation["points"]
    applies = field.bitmap["indicator"] in (0, 254)
    present = _present(field.bitmap_octets, grid_points) if applies else grid_points
    if present != data_points:
        raise Grib2Refused(
            "bitmap-count-disagrees" if applies else "point-count-disagrees",
            f"{where}: Section 5's number of data points is not "
            + ("the bitmap's set points" if applies else "Section 3's number of points"),
        )
    stats = FieldStats(
        decoded=template != 40, count=grid_points, without_value=grid_points - present
    )
    packed = field.data_octets
    if template == 40:
        if packed[:4] != _CODESTREAM:
            raise Grib2Refused(
                "not-a-jpeg2000-codestream",
                f"{where}: Section 7 does not open with a JPEG 2000 codestream's SOC and SIZ "
                "markers (FF 4F FF 51)",
            )
        return stats, packed
    sentinels = _sentinels(indicator, identification, field.product)
    sink = (
        _Tally(parameters, where, sentinels, stats)
        if collect is None
        else _Collect(parameters, where, collect)
    )
    if template == 0:
        _simple(packed, parameters, data_points, where, sink)
    elif template == 3:
        _complex(packed, parameters, data_points, where, sink)
    else:
        _png(packed, parameters, data_points, where, field, applies, budget, sink)
    sink.finish()
    return stats, packed


def _sentinels(indicator, identification, product) -> tuple[tuple[float, str], ...]:
    row = _parameter(indicator, identification, product)
    return row.sentinels if row is not None else ()


def _parameter(indicator, identification, product) -> Parameter | None:
    p = product["parameters"]
    key = (indicator["discipline"], p["category"], p["number"])
    local = LOCAL_PARAMETERS.get((identification["centre"], identification["subcentre"], *key))
    return local if local is not None else PARAMETERS.get(key)


#: The most codes a packing hands its sink at once: the decode's working set is this many codes,
#: never the field (R5 review F-01; `test_a_field_is_summarised_without_holding_its_values`).
CHUNK = 1 << 16


class _Sink:
    """Where a packing hands its codes, in the grid's data-point order: runs of present codes
    (`present`, a sequence; `run`, one code `count` times) and runs of Table 5.5's missing
    marks (`missing`, 1 primary, 2 secondary). The scaler is made on first use and always by
    `finish`, so a scale factor no double holds is refused after every structural rule, as the
    sections are read, and before any value is compared."""

    def __init__(self, parameters: dict, where: str) -> None:
        self._parameters, self._where, self._scale = parameters, where, None

    @property
    def scale(self):
        if self._scale is None:
            self._scale = _scaler(self._parameters, self._where)
        return self._scale

    def finish(self) -> None:
        self.scale


class _Tally(_Sink):
    """Counts what is missing and finds the extremes of the rest, without keeping a value.

    Y rises with X (2^E and 10^D are positive), so the extreme codes are the extreme values, and
    only those two are scaled - except where a parameter names sentinels, whose values must be
    compared code by code (each distinct code of a chunk is scaled once)."""

    def __init__(self, parameters, where, sentinels, stats: FieldStats) -> None:
        super().__init__(parameters, where)
        self._by_value = dict(sentinels)
        self._stats = stats
        stats.sentinels = {meaning: 0 for _, meaning in sentinels}
        self._low = self._high = None

    def _extremes(self, low, high) -> None:
        if self._low is None or low < self._low:
            self._low = low
        if self._high is None or high > self._high:
            self._high = high

    def present(self, codes) -> None:
        if not len(codes):
            return
        if not self._by_value:
            self._extremes(min(codes), max(codes))
            return
        kept = []
        for code in set(codes):
            meaning = self._by_value.get(self.scale(code))
            if meaning is None:
                kept.append(code)
            else:
                self._stats.sentinels[meaning] += codes.count(code)
        if kept:
            self._extremes(min(kept), max(kept))

    def run(self, code: int, count: int) -> None:
        if not count:
            return
        meaning = self._by_value.get(self.scale(code)) if self._by_value else None
        if meaning is None:
            self._extremes(code, code)
        else:
            self._stats.sentinels[meaning] += count

    def missing(self, mark: int, count: int) -> None:
        if mark == 1:
            self._stats.primary_missing += count
        else:
            self._stats.secondary_missing += count

    def finish(self) -> None:
        scale = self.scale
        if self._low is not None:
            self._stats.low, self._stats.high = scale(self._low), scale(self._high)


class _Collect(_Sink):
    """Every value in order, `None` for a Table 5.5 missing mark (`field_values`)."""

    def __init__(self, parameters, where, out: list) -> None:
        super().__init__(parameters, where)
        self._out = out

    def present(self, codes) -> None:
        scale = self.scale
        self._out.extend(scale(code) for code in codes)

    def run(self, code: int, count: int) -> None:
        self._out.extend(itertools.repeat(self.scale(code), count))

    def missing(self, mark: int, count: int) -> None:
        self._out.extend(itertools.repeat(None, count))


def _chunks(data, offset: int, width: int, count: int) -> Iterator:
    """`count` codes of `width` bits from bit `offset`, as sequences of at most CHUNK codes."""
    if offset % 8 == 0 and width == 8:
        start = offset // 8
        for at in range(0, count, CHUNK):
            yield data[start + at : start + min(at + CHUNK, count)]
    elif offset % 8 == 0 and width == 16:
        start = offset // 8
        for at in range(0, count, CHUNK):
            codes = array.array("H")
            codes.frombytes(data[start + 2 * at : start + 2 * min(at + CHUNK, count)])
            if sys.byteorder == "little":
                codes.byteswap()
            yield codes
    else:
        walk = _bit_walk(data, offset, width, count)
        for at in range(0, count, CHUNK):
            yield list(itertools.islice(walk, CHUNK))


def _simple(data: bytes, parameters: dict, count: int, where: str, sink: _Sink) -> None:
    bits = parameters["bits"]
    if len(data) != _octets(count * bits):
        raise Grib2Refused(
            "data-length-disagrees",
            f"{where}: Section 7 is not the octets {count} values of {bits} bits occupy",
        )
    if bits == 0:
        # The zero-width form: every value is code 0, summarised without walking it.
        sink.run(0, count)
        return
    for codes in _chunks(data, 0, bits, count):
        sink.present(codes)


def _complex(data: bytes, p: dict, count: int, where: str, sink: _Sink) -> None:
    """Template 5.3 / 7.3: complex packing and spatial differencing, Table 5.5 management.

    The group descriptors are read as streams (once to check them, once to find the first
    present values, once to decode) and the values are reconstructed point by point into the
    sink, so neither the groups, the field nor its missing marks are ever held: a few hundred
    octets can describe MAX_GRID_POINTS values."""
    groups, ref_bits = p["groups"], p["bits"]
    width_bits, length_bits = p["group_width_bits"], p["group_length_bits"]
    order, size = p["spatial_differencing_order"], p["spatial_differencing_octets"]
    management = p["missing_management"]
    if groups == 0 or groups > count:
        raise Grib2Refused(
            "group-count-out-of-range",
            f"{where}: the number of groups is zero or more than the data points",
        )
    head = size * (order + 1)
    widths_at = head + _octets(groups * ref_bits)
    lengths_at = widths_at + _octets(groups * width_bits)
    values_at = lengths_at + _octets(groups * length_bits)
    if len(data) < values_at:
        raise Grib2Refused(
            "data-length-disagrees",
            f"{where}: Section 7 ends inside the group descriptors",
        )
    first = _sign_magnitude(data, 0, size)
    second = _sign_magnitude(data, size, size) if order == 2 else 0
    minimum = _sign_magnitude(data, size * order, size)

    def descriptors() -> Iterator[tuple[int, int, int]]:
        width_reference, length_reference = p["group_width_reference"], p["group_length_reference"]
        increment, last = p["group_length_increment"], groups - 1
        streams = zip(
            _bits(data, head * 8, ref_bits, groups),
            _bits(data, widths_at * 8, width_bits, groups),
            _bits(data, lengths_at * 8, length_bits, groups),
        )
        for group, (reference, width, length) in enumerate(streams):
            yield (
                reference,
                width_reference + width,
                p["last_group_length"] if group == last else length_reference + length * increment,
            )

    empty = wide = False
    total = value_bits = 0
    for _, width, length in descriptors():
        empty = empty or length == 0
        wide = wide or width > 32
        total += length
        value_bits += width * length
    if empty:
        raise Grib2Refused("empty-group", f"{where}: a group of length 0")
    if total != count:
        raise Grib2Refused(
            "group-lengths-disagree",
            f"{where}: the group lengths do not add up to Section 5's number of data points",
        )
    if wide:
        raise Grib2Refused("group-width-too-large", f"{where}: a group width over 32 bits")
    if len(data) != values_at + _octets(value_bits):
        raise Grib2Refused(
            "data-length-disagrees",
            f"{where}: Section 7 is not the octets its descriptors, groups and values occupy",
        )
    reference_missing = (1 << ref_bits) - 1

    def group_mark(reference: int) -> int:
        # A group without a bit per value: its reference is every value, or marks the whole
        # group missing under management 1 and 2.
        if management and reference == reference_missing:
            return 1
        if management == 2 and reference == reference_missing - 1:
            return 2
        return 0

    def present_values(enough: int) -> int:
        """The field's present values, counted up to `enough`, holding nothing (R5 review 2,
        F-06: holding the sink's calls until they were known kept a record per mark change)."""
        found, offset = 0, values_at * 8
        for reference, width, length in descriptors():
            if width == 0:
                found += 0 if group_mark(reference) else length
            elif not management:
                found += length
            elif not (management == 2 and width == 1):
                # (At one bit under management 2 both codes are marks.) A code below the
                # marks, all ones and, under management 2, all ones less one, is present.
                below = (1 << width) - management
                for code in _bits(data, offset, width, length):
                    if code < below:
                        found += 1
                        if found == enough:
                            return found
            offset += width * length
            if found >= enough:
                return found
        return found

    # Fewer present values than the order is refused after every structural rule and before
    # the sink sees a code, so before any value is scaled.
    if 0 < present_values(order) < order:
        raise Grib2Refused(
            "too-few-values-to-difference",
            f"{where}: fewer present values than the order of spatial differencing",
        )
    buffer: list[int] = []
    run_mark = run_length = 0
    known = previous = before = 0
    offset = values_at * 8
    for reference, width, length in descriptors():
        if width == 0:
            mark = group_mark(reference)
            if mark:
                if buffer:
                    sink.present(buffer)
                    buffer = []
                if run_mark != mark and run_length:
                    sink.missing(run_mark, run_length)
                    run_length = 0
                run_mark, run_length = mark, run_length + length
                continue
            codes, top = itertools.repeat(0, length), -1
        else:
            codes, top = _bits(data, offset, width, length), (1 << width) - 1
            offset += width * length
        for code in codes:
            if management and (code == top or (management == 2 and code == top - 1)):
                mark = 1 if code == top else 2
                if buffer:
                    sink.present(buffer)
                    buffer = []
                if run_mark != mark and run_length:
                    sink.missing(run_mark, run_length)
                    run_length = 0
                run_mark, run_length = mark, run_length + 1
                continue
            if run_length:
                sink.missing(run_mark, run_length)
                run_length = 0
            if known == 0:
                value = first
            elif known == 1 and order == 2:
                value = second
            elif order == 1:
                value = reference + code + minimum + previous
            else:
                value = reference + code + minimum + 2 * previous - before
            before, previous = previous, value
            known += 1
            buffer.append(value)
            if len(buffer) == CHUNK:
                sink.present(buffer)
                buffer = []
    if buffer:
        sink.present(buffer)
    if run_length:
        sink.missing(run_mark, run_length)


#: The most octets one inflate step writes: the rows are inflated into their own buffer, so
#: nothing but that buffer grows with the image.
INFLATE_STEP = 1 << 20


def _png(data, p, count, where, field: _Field, applies: bool, budget: list, sink: _Sink) -> None:
    """Template 5.41 / 7.41: a PNG datastream of 8- or 16-bit greyscale samples, one per value."""
    if data[:8] != _PNG_SIGNATURE:
        raise Grib2Refused("not-png", f"{where}: Section 7 does not open with the PNG signature")
    position = 8
    header = None
    idat: list[bytes] = []
    ended = False
    state = "IHDR"
    while position < len(data):
        if ended:
            raise Grib2Refused(
                "octets-after-png", f"{where}: Section 7 holds octets after the PNG's IEND chunk"
            )
        if len(data) - position < 12:
            raise Grib2Refused("png-chunk-cut-short", f"{where}: a PNG chunk is cut short")
        length = int.from_bytes(data[position : position + 4], "big")
        kind = data[position + 4 : position + 8]
        if length > len(data) - position - 12 or _CHUNK_TYPE.fullmatch(kind) is None:
            raise Grib2Refused(
                "png-chunk-cut-short",
                f"{where}: a PNG chunk's length runs past Section 7 or its type is not four letters",
            )
        body = data[position + 8 : position + 8 + length]
        crc = int.from_bytes(data[position + 8 + length : position + 12 + length], "big")
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise Grib2Refused("png-crc", f"{where}: a PNG chunk fails its CRC")
        name = kind.decode("ascii")
        if name == "IHDR" and state == "IHDR" and length == 13:
            header = struct.unpack(">IIBBBBB", body)
            state = "IDAT"
        elif name == "IDAT" and state in ("IDAT", "MORE"):
            idat.append(body)
            state = "MORE"
        elif name == "IEND" and state == "MORE" and length == 0:
            ended = True
        else:
            raise Grib2Refused(
                "png-chunk-not-read",
                f"{where}: a PNG chunk other than IHDR, then IDAT, then IEND, or out of that "
                "order; no other chunk is read",
            )
        position += 12 + length
    if not ended:
        raise Grib2Refused("png-unterminated", f"{where}: the PNG has no IEND chunk")
    width, height, depth, colour, compression, filtering, interlace = header
    if (colour, compression, filtering, interlace) != (0, 0, 0, 0) or depth not in (8, 16):
        raise Grib2Refused(
            "unsupported-png-format",
            f"{where}: the PNG is not a non-interlaced 8- or 16-bit greyscale image",
        )
    if depth != p["bits"]:
        raise Grib2Refused(
            "png-depth-disagrees", f"{where}: the PNG's bit depth is not Template 5.41's"
        )
    grid = field.grid["parameters"]
    ni = grid.get("ni", grid.get("nx"))
    nj = grid.get("nj", grid.get("ny"))
    expected = (count, 1) if applies else (ni, nj)
    if (width, height) != expected:
        raise Grib2Refused(
            "png-geometry-disagrees",
            f"{where}: the PNG is not "
            + ("one row of the data points" if applies else "Ni samples wide and Nj rows high"),
        )
    step = depth // 8
    row = 1 + width * step
    rows = height * row
    if rows > budget[0]:
        raise Grib2Refused(
            "png-past-the-decompression-bound",
            f"{where}: the PNG's rows inflate to {rows} octets, past what max_decompressed_bytes "
            f"= {MAX_DECOMPRESSED_BYTES} leaves the message; refused before inflating",
        )
    budget[0] -= rows
    out = _inflate(idat, rows, where)
    _unfilter(out, height, row, step, where)
    del idat
    for y in range(height):
        start = y * row + 1
        for codes in _chunks(out, 8 * start, depth, width):
            sink.present(codes)


def _inflate(idat: list[bytes], rows: int, where: str) -> bytearray:
    """The IDAT chunks inflated into a buffer of exactly `rows` octets, at most INFLATE_STEP
    octets a step; one octet more than the rows is refused as soon as it appears."""
    inflater = zlib.decompressobj()
    out = bytearray(rows)
    filled = 0

    def take(piece: bytes) -> None:
        nonlocal filled
        if filled + len(piece) > rows:
            raise Grib2Refused(
                "png-data-past-its-rows",
                f"{where}: the PNG's image data inflates past its {rows} octets of rows",
            )
        out[filled : filled + len(piece)] = piece
        filled += len(piece)

    try:
        for chunk in idat:
            pending = chunk
            while pending:
                take(inflater.decompress(pending, min(INFLATE_STEP, rows + 1 - filled)))
                pending = inflater.unconsumed_tail
        # Output the last step held back once the input was consumed.
        while not inflater.eof:
            piece = inflater.decompress(b"", min(INFLATE_STEP, rows + 1 - filled))
            if not piece:
                break
            take(piece)
    except zlib.error:
        raise Grib2Refused(
            "png-inflate-corrupt", f"{where}: the PNG's image data is not a valid zlib stream"
        ) from None
    if filled != rows or not inflater.eof:
        raise Grib2Refused(
            "png-rows-short", f"{where}: the PNG's image data ends before its rows are complete"
        )
    if inflater.unused_data:
        raise Grib2Refused(
            "png-octets-after-stream", f"{where}: octets follow the PNG's zlib stream"
        )
    return out


def _unfilter(out: bytearray, height: int, row: int, step: int, where: str) -> None:
    """The five PNG filters reversed row by row in place (PNG 1.2 section 9): each row's filter
    octet stays where it is and its samples become the image's; a row reads only itself and the
    row above, already reversed."""
    width = row - 1
    for y in range(height):
        base = y * row + 1
        kind = out[base - 1]
        if kind == 1:
            for i in range(base + step, base + width):
                out[i] = (out[i] + out[i - step]) & 0xFF
        elif kind == 2:
            if y:
                for i in range(base, base + width):
                    out[i] = (out[i] + out[i - row]) & 0xFF
        elif kind == 3:
            for x in range(width):
                i = base + x
                left = out[i - step] if x >= step else 0
                up = out[i - row] if y else 0
                out[i] = (out[i] + ((left + up) >> 1)) & 0xFF
        elif kind == 4:
            for x in range(width):
                i = base + x
                a = out[i - step] if x >= step else 0
                b = out[i - row] if y else 0
                c = out[i - row - step] if y and x >= step else 0
                estimate = a + b - c
                pa, pb, pc = abs(estimate - a), abs(estimate - b), abs(estimate - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                out[i] = (out[i] + predictor) & 0xFF
        elif kind != 0:
            raise Grib2Refused(
                "png-bad-filter", f"{where}: a PNG row's filter type is not 0 to 4 (row {y})"
            )


def field_values(octets: bytes, index: int) -> list[float | None]:
    """Every value of field `index`, in the grid's own order, `None` where the bitmap leaves a
    point out or Table 5.5 marks it missing; a sentinel is its number. For reading a small
    message in full (the tests do); `to_cdm` never materialises a field."""
    decode_message(octets)
    indicator, identification, _, fields = _walk(bytes(octets))
    field = fields[index]
    if field.representation["template"] == 40:
        raise ValueError("a Template 5.40 field's values are not decoded")
    decoded: list[float | None] = []
    _decode_field(index, field, indicator, identification, [MAX_DECOMPRESSED_BYTES], decoded)
    if field.bitmap["indicator"] not in (0, 254):
        return decoded
    bitmap = field.bitmap_octets
    taken = iter(decoded)
    return [
        next(taken) if bitmap[i >> 3] >> (7 - (i & 7)) & 1 else None
        for i in range(field.grid["points"])
    ]


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


def _from_twin(document: dict) -> tuple[bytes, Message]:
    if set(document) != set(TWIN_KEYS):
        raise Grib2Refused(
            "not-a-twin", "a dict is the message's twin, exactly: " + ", ".join(TWIN_KEYS)
        )
    wire = document["wire_hex"]
    if (
        not isinstance(wire, str)
        or len(wire) > 2 * MAX_INPUT_BYTES
        or len(wire) % 2
        or _HEX.fullmatch(wire) is None
    ):
        raise Grib2Refused(
            "bad-wire-hex",
            f"wire_hex is not lower-case hexadecimal of at most {MAX_INPUT_BYTES} octets",
        )
    octets = bytes.fromhex(wire)
    message = decode_message(octets)
    for key in TWIN_KEYS[1:]:
        if not _same(document[key], message.document[key]):
            raise Grib2Refused(
                "twin-disagrees", f"the twin's {key} is not what its wire_hex decodes to"
            )
    return octets, message


def twin_of(octets: bytes) -> dict:
    """The parsed twin of a message: its octets as `wire_hex` and everything it states."""
    message = decode_message(bytes(octets))
    return {"wire_hex": bytes(octets).hex(), **message.document}


# -- the footprint -------------------------------------------------------------------------------

LCC_EDGE_SEGMENTS = 16


def footprint(grid: dict) -> list[list[float]]:
    """The footprint ring, closed and counter-clockwise, in [longitude, latitude]."""
    p = grid["parameters"]
    if grid["template"] == 0:
        span = _lon_span(p)
        west = _wrap(p["lo2"] if p["scanning_mode"] & 0x80 else p["lo1"])
        east = west + span
        south, north = sorted((p["la1"], p["la2"]))
        corners = [(west, south), (east, south), (east, north), (west, north), (west, south)]
        return [[lon / 1e6, lat / 1e6] for lon, lat in corners]
    return _lambert_ring(p)


def _lambert_ring(p: dict) -> list[list[float]]:
    shape = p["earth_shape"]
    radius = (
        p["radius_scaled_value"] / float(10 ** p["radius_scale_factor"])
        if shape == 1
        else SPHERES[shape]
    )
    phi1, phi2 = math.radians(p["latin1"] / 1e6), math.radians(p["latin2"] / 1e6)
    if p["latin1"] == p["latin2"]:
        n = math.sin(phi1)
    else:
        n = math.log(math.cos(phi1) / math.cos(phi2)) / math.log(
            math.tan(math.pi / 4 + phi2 / 2) / math.tan(math.pi / 4 + phi1 / 2)
        )
    big_f = math.cos(phi1) * math.tan(math.pi / 4 + phi1 / 2) ** n / n
    lov = math.radians(p["lov"] / 1e6)

    def forward(lat: float, lon: float) -> tuple[float, float]:
        rho = radius * big_f / math.tan(math.pi / 4 + lat / 2) ** n
        theta = n * _angle(lon - lov)
        return rho * math.sin(theta), -rho * math.cos(theta)

    def inverse(x: float, y: float) -> tuple[float, float]:
        rho = math.hypot(x, y)
        if rho == 0.0:
            return 90.0, math.degrees(lov)
        theta = math.atan2(x, -y)
        try:
            lat = 2 * math.atan((radius * big_f / rho) ** (1 / n)) - math.pi / 2
        except OverflowError:
            lat = math.pi / 2
        if not math.isfinite(lat):
            raise Grib2Refused(
                "footprint-out-of-range", "Section 3: a Lambert grid point has no latitude"
            )
        return math.degrees(lat), math.degrees(_angle(lov + theta / n))

    x1, y1 = forward(math.radians(p["la1"] / 1e6), math.radians(p["lo1"] / 1e6))
    si = -1.0 if p["scanning_mode"] & 0x80 else 1.0
    sj = 1.0 if p["scanning_mode"] & 0x40 else -1.0
    dx, dy = p["dx"] / 1000.0, p["dy"] / 1000.0
    last_i, last_j = p["nx"] - 1, p["ny"] - 1
    corners = [(0, 0), (last_i, 0), (last_i, last_j), (0, last_j)]
    if si * sj < 0:
        corners.reverse()
    ring: list[list[float]] = []
    for (ia, ja), (ib, jb) in zip(corners, corners[1:] + corners[:1]):
        cells = max(abs(ib - ia), abs(jb - ja))
        segments = min(cells, LCC_EDGE_SEGMENTS)
        for s in range(segments):
            i = ia + (ib - ia) * s / segments
            j = ja + (jb - ja) * s / segments
            lat, lon = inverse(x1 + i * dx * si, y1 + j * dy * sj)
            ring.append([round(lon, 6), round(lat, 6)])
    ring.append(list(ring[0]))
    for a, b in zip(ring, ring[1:]):
        if abs(a[0] - b[0]) > 180.0:
            raise Grib2Refused(
                "footprint-crosses-antimeridian",
                "Section 3: the Lambert grid's outline crosses 180 degrees; a footprint across "
                "the antimeridian is not stated",
            )
    return ring


def _angle(radians: float) -> float:
    """An angle in radians, as -pi (exclusive) to pi (inclusive)."""
    turned = math.fmod(radians + math.pi, 2 * math.pi)
    if turned <= 0:
        turned += 2 * math.pi
    return turned - math.pi


# -- the declaration -----------------------------------------------------------------------------


def _residual(path: str, target: str) -> Mapping:
    return Mapping(to=f"{target}:residual.data.{path}", kind="residual")


def _summary(member: str) -> Mapping:
    return Mapping(to=f"#[*]:payload.observation.values.summary.{member}")


class Grib2Adapter(Adapter):
    """One GRIB2 message in; one Event per field out."""

    name = "grib2"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration. `PUBLIC_GOVERNMENT`: the NCEP GRIB2 documentation the layouts
    #: are read against is a US Government agency's public page (research-grib2 F02); the WMO
    #: text is cited by reference and its class is the maintainer's to confirm (L-30).
    metadata = AdapterMetadata(
        id="grib2",
        name="GRIB2 message translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter grib2` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every section a structured residual, the packed arrays and the octets a declared "
            "limitation) with no LOST leaf on any parsed twin. L4 is NOT declared: this adapter "
            "is ingest-only, so the roundtrip check is inapplicable rather than passed "
            "(ARCHITECTURE.md §3.6, rule 4), and a rung passed vacuously is not a rung declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "GRIB edition 2 message: Sections 0 to 8 with Sections 4 to 7 repeated; grid "
                "templates 3.0 (latitude/longitude) and 3.30 (Lambert conformal), product "
                "templates 4.0 and 4.8, data representation templates 5.0, 5.3 and 5.41 "
                "decoded and 5.40 read in reference form; one ENVIRONMENTAL_OBSERVATION Event "
                "(gridded-field/1) per field",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=MAX_FIELDS,
                max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
                max_parse_seconds=None,
                absent_because={
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, every walk is linear in the octets read or in the grid points, which "
                    "MAX_GRID_POINTS bounds, and the PNG rows are inflated under a byte bound; "
                    "the conformance suite's parser worker kills a decode that overruns its "
                    "deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "largest message of 2026-09-11 12Z across HRRR sfc/prs/nat/subh and "
                            "RAP awp130pgrb is 3,810,470 B (wire-facts F02); NOT the format's "
                            "normative maximum. GRIB2's Section 0 states an eight-octet total "
                            "length, so no figure the format sets bounds a message. 8 MiB "
                            "(8 388 608 octets, `MAX_INPUT_BYTES`, `adapters/grib2.py`) is "
                            "DECISIONS U-07's bound for one message, 2.2 times the largest. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module reads Section 0"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_decompressed_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "MRMS QPE's Section 7 is a PNG whose image data inflates to 3500 x "
                            "(1 + 7000 x 2) = 49,003,500 octets of filtered 16-bit rows "
                            "(gap-grib2-wire-facts F04: MRMS inner IDAT 49,003,500 B). 64 MiB "
                            "(67 108 864 octets, `MAX_DECOMPRESSED_BYTES`, `adapters/grib2.py`) "
                            "sits above it for every PNG field of one message together. " + _CAP
                        ),
                        enforced_at=(
                            "`grib2._png`: a field's rows (Nj x (1 + Ni x octets per sample)) "
                            "are compared with what the bound leaves the message before any "
                            "octet is inflated and refused `png-past-the-decompression-bound`; "
                            "`grib2._inflate` then calls `zlib.decompressobj().decompress` with "
                            "`max_length` at most one octet past the rows (and at most "
                            "`INFLATE_STEP` = 1 MiB a step) into a buffer of exactly the rows, "
                            "and an octet past them is refused `png-data-past-its-rows` before "
                            "it is kept"
                        ),
                        test=_TESTS
                        + "test_png_rows_are_held_to_the_decompression_bound_before_inflating",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "One Event per field. The design record's most is two fields in one "
                            "message (RAP awp130pgrb: 49 of 306 messages repeat Sections 4 to 7, "
                            "gap-grib2-wire-facts F02/T8); 16 (`MAX_FIELDS`, "
                            "`adapters/grib2.py`) is eight times that. " + _CAP
                        ),
                        enforced_at=(
                            "`grib2.decode_message`: a Section 4 past the sixteenth field is "
                            "refused `too-many-fields` before it is read"
                        ),
                        test=_TESTS + "test_a_seventeenth_field_is_refused_before_it_is_read",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets are never JSON; the dict form, the parsed twin, nests "
                            "five containers (a template's parameters inside a section inside "
                            "a field). 16 (`MAX_DEPTH`, `adapters/grib2.py`) is the dis7 "
                            "envelope's bound, over three times that. " + _CAP
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
                "the message is binary with fixed templates: a section, a template or a PNG "
                "chunk this module does not name is refused rather than preserved, Section 2's "
                "local octets are carried whole, and the dict form is held to be exactly what "
                "its own wire_hex decodes to, so an injected key is refused `not-a-twin`"
            ),
        ),
        limitations=[
            by_reference_limitation(
                ["arrays"],
                notes=(
                    "the twin's `arrays` holds each field's bitmap and packed values as the "
                    "message states them; the contract states the locator, the shape, the packing "
                    "and a summary"
                ),
            ),
            Limitation(
                id="jpeg2000-values-unsupported",
                summary="a Template 5.40 field's values are a JPEG 2000 codestream this module "
                "does not decode (DECISIONS U-02: no decoder outside the standard library): "
                "Sections 0 to 6 are read, Section 7 is checked to open with a codestream's SOC "
                "and SIZ markers, and the contract states the field by reference with no summary",
                unsupported_paths=["codestreams"],
            ),
            Limitation(
                id="message-octets-by-reference",
                summary="the twin's wire_hex is the message's octets, the input its dict form "
                "is decoded from; they are identified by SourceRef.source_hash when the host "
                "injects it and are not copied into any object",
                unsupported_paths=["wire_hex"],
            ),
            Limitation(
                id="one-message-per-call",
                summary="exactly one GRIB2 message per call, as its octets or as its twin; a "
                "file of several messages, a gzip around one and an index file are not taken. "
                "synapse-decode unwraps a gzip and cuts a file into its messages, each with its "
                "ordinal and the octet it begins at",
            ),
            Limitation(
                id="templates-read",
                summary="grid templates 3.0 and 3.30 (north-pole-centred, LaD a standard "
                "parallel, a spherical earth), product templates 4.0 and 4.8 (one time range), "
                "data representation templates 5.0, 5.3 (orders 1 and 2) and 5.41 (8- and 16-bit "
                "greyscale) are read; every other template, a predefined grid or bitmap, a "
                "quasi-regular grid, coordinate values after Section 4, a second Section 2 or 3, "
                "a scanning mode other than the i and j directions and a grid across 180 degrees "
                "are refused by name, as is GRIB edition 1",
            ),
            Limitation(
                id="tables-read-by-row",
                summary="a parameter's name and unit and a surface's unit are stated only for the "
                "Code Table 4.2 and 4.5 rows this module lists, each with the file it was read "
                "from (GDAL's table files, its NCEP local table for NCEP's local rows, and NSSL's "
                "MRMS table for MRMS's); any other parameter keeps its discipline.category.number "
                "code with no unit, any other surface its code with no value, and a row whose unit "
                "column states a code's meanings (CFRZR) names the parameter and states no unit",
            ),
            Limitation(
                id="first-fixed-surface",
                summary="the contract's level is the first fixed surface; a layer's second "
                "surface stays in the Event's residual with every other Template 4.x octet",
            ),
            Limitation(
                id="footprint-outline",
                summary="Event.geometry is the outline of the grid POINTS, not of the cells "
                "around them: a lat/lon grid's corner points, a Lambert grid's edge points "
                "converted with the spherical inverse, at most 16 segments an edge and rounded "
                "to 10^-6 degree",
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

    TRANSFORMS: dict[str, str] = {
        "wire_hex": T_WIRE,
        "arrays": T_ARRAYS,
        "codestreams": T_CODESTREAM,
    }

    #: The ledger. Field i of the twin is object i (one Event per field, in order), so `#[*]`
    #: holds every field's leaves to its own Event. A specific key comes before the subtree it
    #: falls under, because the first declaration that matches a leaf is the one it is held to.
    MAPPINGS = {
        "indicator": _residual("indicator", "event"),
        "identification": _residual("identification", "event"),
        "local_use": _residual("local_use", "event"),
        "fields[*].grid.parameters": (
            Mapping(to="#[*]:residual.data.field.grid.parameters", kind="residual"),
            Mapping(to="#[*]:payload.observation.grid.parameters", kind="residual"),
        ),
        "fields[*]": Mapping(to="#[*]:residual.data.field", kind="residual"),
        "summaries[*].count": _summary("count"),
        "summaries[*].missing_count": _summary("missing_count"),
        "summaries[*].min": _summary("min"),
        "summaries[*].max": _summary("max"),
        "summaries[*]": Mapping(to="#[*]:payload.observation.values.summary"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
        message_ordinal: int = 0,
        byte_offset: int = 0,
    ) -> None:
        """`source_hash` is the SHA-256 of the file as the host read it and `frame_sha256` the
        digest of the message's own octets when they are not the whole file; `message_ordinal` is
        the message's 0-based ordinal in the file and `byte_offset` the octet it begins at, in the
        octets the host framed. All four are values the caller computed — this package digests
        nothing and frames nothing — and all four are constructor arguments, so all four are in
        the determinism tuple. A message handed over without them is the whole file: message 0,
        at octet 0."""
        super().__init__(clock, synthetic=synthetic)
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
        for name, value in (("message_ordinal", message_ordinal), ("byte_offset", byte_offset)):
            if type(value) is not int or value < 0:
                raise ValueError(f"{name} is a non-negative int")
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256
        self._ordinal = message_ordinal
        self._offset = byte_offset

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One message -> [one Event per field, in the message's order]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            message = decode_message(bytes(raw))
        elif isinstance(raw, dict):
            _, message = _from_twin(raw)
        else:
            raise Grib2Refused(
                "unsupported-input",
                "a message is handed over as its octets or as its twin in a dict; text and other "
                "types are not taken",
            )
        return self._translate(message)

    # -- translation -----------------------------------------------------------------------------

    def _translate(self, message: Message) -> list[CDMBase]:
        document = message.document
        identification = document["identification"]
        reference = _reference_time(identification)
        significance = identification["reference_time_significance"]
        if significance not in SIGNIFICANCE:
            raise Grib2Refused(
                "unsupported-reference-significance",
                "Section 1 octet 12: Code Table 1.2 significance is not 0 to 3",
            )
        if identification["data_type"] not in DATA_TYPES:
            raise Grib2Refused(
                "unsupported-data-type",
                "Section 1 octet 21: Code Table 1.4's type of processed data is not 0, 1, 2 or 7; "
                "no product class is ruled for it",
            )
        stamp = self.source_ref().model_copy(
            update={
                "record_index": self._ordinal,
                "observed_at": reference,
                "source_hash": self._source_hash,
            }
        )
        return [
            self._field_event(document, index, message.stats[index], stamp, reference)
            for index in range(len(document["fields"]))
        ]

    def _field_event(self, document, index, stats: FieldStats, stamp, reference):
        indicator, identification = document["indicator"], document["identification"]
        field = document["fields"][index]
        product = field["product"]
        p = product["parameters"]
        where = f"field {index}"
        start, end, offset, process = _validity(product, reference, where)
        data_meaning, product_class = DATA_TYPES[identification["data_type"]]
        if product_class is None:
            product_class = "forecast" if end > reference else "analysis"
        locator = {
            "kind": "grib",
            "message": self._ordinal,
            "field": index,
            "byte_offset": self._offset,
            "frame_sha256": self._frame_sha256,
        }
        row = _parameter(indicator, identification, product)
        code = f"{indicator['discipline']}.{p['category']}.{p['number']}"
        quantity = Quantity(
            name=row.short_name if row is not None else None,
            code=code,
            namespace=(
                f"GRIB2 Code Table 4.2 (discipline.category.number), {row.source}"
                if row is not None
                else "GRIB2 Code Table 4.2 (discipline.category.number)"
            ),
        )
        unit = (
            UnitRef(unit=row.unit, unit_namespace=row.source)
            if row is not None and row.unit is not None
            else None
        )
        level, level_transform = _level(p)
        grid = field["grid"]
        representation = field["representation"]
        template = representation["template"]
        rp = representation["parameters"]
        transformations = [T_REFERENCE, T_VALID]
        if level_transform:
            transformations.append(T_LEVEL)
        transformations.append(T_FOOTPRINT_LATLON if grid["template"] == 0 else T_FOOTPRINT_LCC)
        if stats.decoded:
            transformations.append(T_SUMMARY)
        scale, offset_value = scale_and_offset(rp, f"field {index}, Section 5")
        values = ValuesByReference(
            mode="reference",
            locator=GribLocator(**locator),
            shape=_shape(grid),
            dtype=_dtype(template, rp),
            encoding=_encoding(template, rp, field["bitmap"]["indicator"]),
            scale=scale,
            offset=offset_value,
            summary=(
                ArraySummary(
                    count=stats.count,
                    missing_count=stats.missing,
                    min=stats.low,
                    max=stats.high,
                )
                if stats.decoded
                else None
            ),
        )
        contract = GriddedField(
            contract="gridded-field/1",
            product_class=product_class,
            product_version=_version(identification, p),
            time=TimeInputs(
                source_time_system=TimeSystem(
                    name="UTC",
                    stated_by="source",
                    basis=(
                        "GRIB2 Section 1 octets 13-19, the reference time as year, month, day, "
                        "hour, minute and second; GRIB2 states its times in UTC"
                    ),
                ),
                reference_time=reference,
                reference_time_significance=CodedValue(
                    code=str(identification["reference_time_significance"]),
                    namespace="GRIB2 Code Table 1.2",
                    meaning=SIGNIFICANCE[identification["reference_time_significance"]],
                ),
                forecast_offset=offset,
                statistical_process=process,
            ),
            locator=GribLocator(**locator),
            quality_flags=_flags(field, stats, identification, p, row),
            quantity=quantity,
            unit=unit,
            level=level,
            grid=Grid(
                namespace="GRIB2 Code Table 3.1",
                template=f"3.{grid['template']}",
                shape=_shape(grid),
                scanning_mode=f"{grid['parameters']['scanning_mode']:08b}",
                cell_size=_cell_size(grid),
                parameters=dict(grid["parameters"]),
            ),
            values=values,
        )
        identity = _identity(indicator, identification, product, grid, reference)
        return observation_event(
            source=stamp.model_copy(update={"transformations": transformations}),
            source_ids=[SourceId(system=SYSTEM, external_id=identity)],
            observation=contract,
            observed_at=reference,
            received_at=self.now(),
            validity=TemporalValidity(effective=Period(start=start, end=end)),
            geometry=Polygon(coordinates=[footprint(grid)]),
            residual=Residual(
                namespace=self.metadata.format.name,
                data={
                    "indicator": indicator,
                    "identification": identification,
                    "local_use": document["local_use"],
                    "field": field,
                },
            ),
        )


def _reference_time(s1: dict) -> _dt.datetime:
    try:
        return _dt.datetime(
            s1["year"], s1["month"], s1["day"], s1["hour"], s1["minute"], s1["second"], tzinfo=_UTC
        )
    except ValueError:
        raise Grib2Refused(
            "bad-reference-time", "Section 1 octets 13-19 do not name a date and time"
        ) from None


def _seconds(unit: int, where: str, what: str) -> tuple[str, int]:
    if unit not in TIME_UNITS:
        raise Grib2Refused(
            "unsupported-time-unit",
            f"{where}: {what}'s Code Table 4.4 unit is not 0 (minute), 1 (hour) or 13 (second)",
        )
    return TIME_UNITS[unit]


def _validity(product: dict, reference: _dt.datetime, where: str):
    """(start, end, forecast offset, statistical process) of a field."""
    p = product["parameters"]
    if p["forecast_time"] is None:
        raise Grib2Refused("forecast-time-missing", f"{where}: the forecast time is missing")
    words, seconds = _seconds(p["time_unit"], where, "the forecast time")
    try:
        start = reference + _dt.timedelta(seconds=p["forecast_time"] * seconds)
    except OverflowError:
        raise Grib2Refused(
            "bad-validity", f"{where}: the forecast time puts the validity outside any date"
        ) from None
    offset = Measurement(
        value=p["forecast_time"], unit=words, unit_namespace="GRIB2 Code Table 4.4"
    )
    if product["template"] == 0:
        return start, start, offset, None
    if p["time_ranges"] != 1:
        raise Grib2Refused(
            "unsupported-time-ranges",
            f"{where}: Template 4.8 states other than one time range specification",
        )
    try:
        end = _dt.datetime(
            p["end_year"],
            p["end_month"],
            p["end_day"],
            p["end_hour"],
            p["end_minute"],
            p["end_second"],
            tzinfo=_UTC,
        )
    except ValueError:
        raise Grib2Refused(
            "bad-interval-end", f"{where}: Template 4.8 octets 35-41 do not name a date and time"
        ) from None
    _, range_seconds = _seconds(p["range_unit"], where, "the time range")
    try:
        length = _dt.timedelta(seconds=p["range_length"] * range_seconds)
    except OverflowError:
        length = None
    if end - start != length:
        raise Grib2Refused(
            "interval-disagrees",
            f"{where}: Template 4.8's end of the overall interval is not its start plus the "
            "length of its time range",
        )
    process = CodedValue(
        code=str(p["statistical_process"]),
        namespace="GRIB2 Code Table 4.10",
        meaning=STATISTICAL_PROCESSES.get(p["statistical_process"]),
    )
    return start, end, offset, process


def _level(p: dict) -> tuple[VerticalLevel | None, bool]:
    kind = p["surface1_type"]
    if kind == 255:
        return None, False
    known = SURFACES.get(kind)
    namespace = "GRIB2 Code Table 4.5"
    if known is None:
        return VerticalLevel(code=str(kind), namespace=namespace), False
    _, name, unit = known
    namespace = f"{namespace}, {SURFACES_SOURCE}"
    scale, value = p["surface1_scale"], p["surface1_value"]
    if unit == "-" or scale is None or value is None:
        return VerticalLevel(type=name, code=str(kind), namespace=namespace), False
    power = float(10 ** abs(scale))
    stated = value / power if scale >= 0 else value * power
    return (
        VerticalLevel(type=name, code=str(kind), value=stated, unit=unit, namespace=namespace),
        True,
    )


def _shape(grid: dict) -> list[int]:
    p = grid["parameters"]
    return [p["nj"], p["ni"]] if grid["template"] == 0 else [p["ny"], p["nx"]]


def _cell_size(grid: dict) -> list[Measurement] | None:
    p = grid["parameters"]
    if grid["template"] == 30:
        note = "GRIB2 Template 3.30 Note 1 (units of 10^-3 m)"
        return [
            Measurement(value=p["dy"], unit="10^-3 m", unit_namespace=note),
            Measurement(value=p["dx"], unit="10^-3 m", unit_namespace=note),
        ]
    if p["di"] == 0xFFFFFFFF or p["dj"] == 0xFFFFFFFF:
        return None
    note = "GRIB2 Template 3.0 Note 1 (units of 10^-6 degree)"
    return [
        Measurement(value=p["dj"], unit="10^-6 degree", unit_namespace=note),
        Measurement(value=p["di"], unit="10^-6 degree", unit_namespace=note),
    ]


def _dtype(template: int, p: dict) -> str:
    if template == 41:
        return f"PNG {p['bits']}-bit greyscale samples"
    if template == 40:
        return f"JPEG 2000 codestream of {p['bits']}-bit values"
    return f"{p['bits']}-bit unsigned integers"


def _encoding(template: int, p: dict, indicator: int) -> str:
    text = (
        f"GRIB2 Code Table 5.0 template {template}, {PACKINGS[template]}: Y = (R + X x 2^E) / "
        f"10^D with R = {p['reference_value']!r}, E = {p['binary_scale']}, D = "
        f"{p['decimal_scale']}"
    )
    if template == 3:
        text += (
            f"; spatial differencing of order {p['spatial_differencing_order']}, Code Table 5.5 "
            f"missing value management {p['missing_management']}"
        )
    if template == 40:
        text += "; the codestream is not decoded here"
    if indicator in (0, 254):
        text += "; a Section 6 bitmap applies"
    return text


def _version(s1: dict, p: dict) -> ProductVersion:
    return ProductVersion(
        version=(
            f"GRIB2 master tables version {s1['master_table_version']}, local tables version "
            f"{s1['local_table_version']}"
        ),
        producer=(
            f"originating centre {s1['centre']}, subcentre {s1['subcentre']}, generating "
            f"process {p['generating_process']}.{p['background_process']}."
            f"{p['forecast_process']}"
        ),
    )


def _flags(field, stats: FieldStats, s1: dict, p: dict, row: Parameter | None):
    flags = [
        QualityFlag(
            name="production_status",
            value=s1["production_status"],
            namespace="GRIB2 Code Table 1.3",
            applies_to="message",
        ),
        QualityFlag(
            name="bitmap_indicator",
            value=field["bitmap"]["indicator"],
            namespace="GRIB2 Code Table 6.0",
            applies_to="field",
        ),
        QualityFlag(
            name="points_without_value",
            value=stats.without_value,
            namespace="GRIB2 Section 6 bitmap",
            applies_to="field",
        ),
    ]
    representation = field["representation"]
    if representation["template"] == 3:
        management = representation["parameters"]["missing_management"]
        if management >= 1:
            flags.append(
                QualityFlag(
                    name="primary_missing_count",
                    value=stats.primary_missing,
                    namespace="GRIB2 Code Table 5.5",
                    applies_to="field",
                )
            )
        if management == 2:
            flags.append(
                QualityFlag(
                    name="secondary_missing_count",
                    value=stats.secondary_missing,
                    namespace="GRIB2 Code Table 5.5",
                    applies_to="field",
                )
            )
    if row is not None and stats.decoded:
        for value, meaning in row.sentinels:
            flags.append(
                QualityFlag(
                    name=f"sentinel_{re.sub(r'[^a-z0-9]+', '_', meaning.lower())}_count",
                    value=stats.sentinels.get(meaning, 0),
                    namespace=f"{row.source}: {meaning} = {value!r}",
                    applies_to="field",
                )
            )
    if field["product"]["template"] == 8:
        flags.append(
            QualityFlag(
                name="missing_in_statistical_process",
                value=p["missing_in_statistical_process"],
                namespace="GRIB2 Product Definition Template 4.8 octets 43-46",
                applies_to="field",
            )
        )
    return flags


def _identity(indicator, s1, product, grid, reference) -> str:
    """The field's identifier: who produced which parameter, at which level, for which time and on
    which grid. Two messages stating the same field share it, wherever they sit in a file."""
    p = product["parameters"]
    g = grid["parameters"]
    time = f"{p['time_unit']}:{p['forecast_time']}"
    if product["template"] == 8:
        time += (
            f" to {p['end_year']:04d}-{p['end_month']:02d}-{p['end_day']:02d}T"
            f"{p['end_hour']:02d}:{p['end_minute']:02d}:{p['end_second']:02d}Z "
            f"process {p['statistical_process']}"
        )
    shape = "x".join(str(n) for n in reversed(_shape(grid)))
    return (
        f"centre {s1['centre']}.{s1['subcentre']}/{times.render(reference)}/"
        f"parameter {indicator['discipline']}.{p['category']}.{p['number']}/"
        f"process {p['generating_process']}.{p['background_process']}.{p['forecast_process']}/"
        f"level {p['surface1_type']}:{p['surface1_scale']}:{p['surface1_value']},"
        f"{p['surface2_type']}:{p['surface2_scale']}:{p['surface2_value']}/"
        f"time {time}/grid 3.{grid['template']} {shape} at {g['la1']},{g['lo1']}"
    )
