"""`nexrad2`, #25 in the ordinal table: one NEXRAD Level II volume -> CDM, ingest only.

WHAT A PAYLOAD IS
-----------------
One Archive II volume file as the archive stores it (`<SITE><yyyymmdd>_<hhmmss>_V06`): the
24-octet volume header, then LDM compressed records — a four-octet signed big-endian control
word whose ABSOLUTE value is the size of one bzip2 stream (ICD 2620010J 7.3.4: "the control word
contains a negative size under some circumstances") — the first of them the 134-segment metadata
record (7.3.5), the rest records of up to 120 message-31 radials and RDA status messages. `to_cdm`
takes the file's octets, or the parsed twin (`<name>.parsed.json`: the octets as `wire_hex` and
everything the volume states), which is held to be exactly what its own `wire_hex` decodes to.

The layouts are read from two public ICDs, pinned by SHA-256 in
`fixtures/nexrad2/spec/nexrad2_pin.json` and not carried: 2620010J (Archive II/User) for the
file and 2620002Y (RDA/RPG) for every message, both Build 23.0. Nothing here is ported from a
reader that exists elsewhere; the two the design record read (Py-ART, MetPy) disagree with the
ICD in places, merge the two coded values below, and are not dependencies.

WHAT ONE VOLUME BECOMES
-----------------------
One `ENVIRONMENTAL_OBSERVATION` Event per elevation NUMBER, in elevation-number order, then the
radar site's `Entity`:

- a sweep is the radials of one elevation number. Never one angle: SAILS and MRLE rescan the
  lowest angle inside one volume, so two sweeps can share an angle and never a number. Its
  `observed_at` is its LAST radial's collection time — the data header's, never the message
  header's second stamp and never a delivery time — and `validity.effective` runs from its first
  radial to its last. The ICD's +/-2000 ms accuracy is `Quality.uncertainty`.
- its contract is `radar-sweep/1`. Each moment's gate values stay in the volume, BY REFERENCE: a
  radar locator (LDM record, message, elevation number, moment), the shape `[radials, gates]`,
  the packing, and a summary whose minimum and maximum are converted with EACH RADIAL'S own scale
  and offset (Table XVII-I note 20: they may change from radial to radial). The coded values that
  are not measurements are COUNTED, each under its own name and never merged: 0 "below
  threshold" and 1 "range folded" for six moments (note 21), and CFP's own 0 to 7 (note 30).
- the radial status (with its 0x80 bad-data bit), spot blanking, the VOL, ELV and RAD constants
  (calibration, transmitter power, system ZDR, initial PHIDP, ZDR bias, noise, Nyquist velocity,
  unambiguous range, VCP) and each moment's TOVER, SNR threshold and control flags are typed
  quality flags. A flag every radial of the sweep states alike is stated once, `applies_to`
  "sweep" (or the moment's name); one that differs is stated per radial, `applies_to`
  "radial <azimuth number>" (or "<moment> radial <azimuth number>"). Every radial's header, raw,
  is the Event's structured residual.
- the site `Entity` (SENSOR, `site_entity`): its ICAO identifier, the VOL block's latitude and
  longitude, its height as stated (metres above mean sea level, so `alt_m` stays None), and the
  volume's start (the volume header's instant) as `valid_from`.

WHAT IS REFUSED
---------------
Every range ICD 2620002Y Tables XVII-A, -B, -E, -F and -H state for a field this module reads is
a validation rule (the stricter reading; Radial Length 9,360 to 14,296 and Azimuth Number 1 to 720
among them). Table XVII-I's data ranges are NOT (narrowed 2026-10-15, R3 review R3-r1-01): they are
the typical values of a moment (note 20), a moment's gate codes are counted and converted with each
radial's own scale and offset, and the summary that results is not range-checked. A refusal is
a `Nexrad2Refused` (`ValueError`) whose code names the rule and whose text names the field and
its position, never a value. Message 1 (the legacy radial) and message 29 (the model data of an
`_MDM` record) are refused by name, not decoded, and so is a radial whose Compression Indicator
says bzip2 or zlib. Every bzip2 stream is inflated with its output held to the bound left
(`max_decompressed_bytes`, and per record): the metadata record alone expands about 869 times.
"""

from __future__ import annotations

import array
import bz2
import dataclasses
import datetime as _dt
import math
import re
import struct
import sys
from typing import Any

from synapse_cdm import times
from synapse_cdm.enums import VerticalReference, VerticalUnit
from synapse_cdm.geo import Point, VerticalPosition
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
from synapse_cdm.adapter import Adapter
from synapse_cdm.models import (
    CDMBase,
    Period,
    Quality,
    Residual,
    SourceHash,
    SourceId,
    TemporalValidity,
)
from synapse_cdm.observation_contracts import (
    ArraySummary,
    CodedValue,
    Measurement,
    ProductVersion,
    QualityFlag,
    RadarLocator,
    RadarMoment,
    RadarSweep,
    TimeInputs,
    TimeSystem,
    UnitRef,
    ValuesByReference,
    by_reference_limitation,
    observation_event,
    site_entity,
)

#: `source.system` on every object and the system of every identifier: the radar network.
SYSTEM = "NEXRAD"
#: The residual namespace and `SourceRef.format_name`, read from the declaration below.
FORMAT_NAME = "NEXRAD Level II (Archive II)"
#: The two documents this module is written against, both revision in force at Build 23.0.
FORMAT_VERSION = "ICD 2620010J (Archive II/User) and ICD 2620002Y (RDA/RPG), Build 23.0"

ICD_FILE = "ICD 2620010J"
ICD = "ICD 2620002Y"

# -- bounds (DECISIONS U-07; each declared with its basis below) ---------------------------------

MAX_INPUT_BYTES = 32 * 1024 * 1024
#: 2620010J 7.3.5: "The size of the uncompressed metadata is fixed at 134 messages, ie. 325888".
METADATA_SEGMENTS = 134
SEGMENT_BYTES = 2432
METADATA_RECORD_BYTES = METADATA_SEGMENTS * SEGMENT_BYTES
#: 7.3.4: a radial record holds 120 radial messages "plus 0 or more" RDA status messages.
MAX_RADIALS_PER_RECORD = 120
#: The most one radial record may decompress to. Table XVII-A's largest Radial Length is 14,296
#: octets, so a message 31 occupies at most 12 + 2 x 7,156 = 14,324 octets and 120 of them
#: 1,718,880 (the design record's "<= 1.72 MB per 120-radial record"); 2 MiB leaves room for
#: 155 status segments beside them.
MAX_RECORD_BYTES = 2 * 1024 * 1024
#: Table XVII-A: Elevation Number 1 to 32, Azimuth Number 1 to 720.
MAX_ELEVATIONS = 32
MAX_AZIMUTHS = 720
#: The most a volume may decompress to: the metadata record and 192 full radial records, which
#: hold the 32 x 720 radials a volume can number.
MAX_DECOMPRESSED_BYTES = (
    METADATA_RECORD_BYTES
    + (MAX_ELEVATIONS * MAX_AZIMUTHS // MAX_RADIALS_PER_RECORD) * MAX_RECORD_BYTES
)
#: One Event per elevation number and the site's Entity.
MAX_OBJECTS = MAX_ELEVATIONS + 1
#: The dict form nests seven containers deep; the bound is dis7's envelope bound.
MAX_DEPTH = 16

_CAP = "This is an IMPLEMENTATION CAP and is NOT the format's normative maximum."
_TESTS = "tests/test_cdm_nexrad2_adapter.py::"

MAX_RECORD_BYTES_BASIS = LimitBasis(
    kind=LimitKind.IMPLEMENTATION_CAP,
    source=(
        "ICD 2620010J 7.3.4 puts 120 radial messages in a record and 2620002Y Table XVII-A "
        "bounds a radial at 14,296 octets, so 120 radials framed as messages occupy at most "
        "1,718,880 octets (research-nexrad-level2 F03/F12: <= 1.72 MB per 120-radial record). "
        "2 MiB (2,097,152 octets, `MAX_RECORD_BYTES`, `adapters/nexrad2.py`) sits above it with "
        "room for RDA status messages. " + _CAP
    ),
    enforced_at=(
        "`nexrad2.decode_volume`: each radial record's bzip2 stream is inflated with its output "
        "held to MAX_RECORD_BYTES and the octet past it refused `record-past-its-bound`; the "
        "metadata record is held to exactly 325,888 octets the same way"
    ),
    test=_TESTS + "test_a_record_is_held_to_its_own_bound_and_the_metadata_record_to_its_size",
)

# -- the vocabulary ------------------------------------------------------------------------------

#: The moments Table XVII-I names, as the three octets the block states ("SW " is padded).
MOMENTS = ("REF", "VEL", "SW ", "ZDR", "PHI", "RHO", "CFP")
#: Table XVII-I's unit of each moment, verbatim ("N/A" is the table's entry for RHO).
UNITS = {
    "REF": "dBZ",
    "VEL": "m/s",
    "SW ": "m/s",
    "ZDR": "dB",
    "PHI": "deg",
    "RHO": "N/A",
    "CFP": "dB",
}
#: The coded values below each moment's data range, by name: note 21 for six moments (data
#: begins at N = 2), note 30 for CFP (data begins at N = 8; 3 to 7 are reserved).
CODED = {
    "CFP": (
        ("filter_not_applied_count", (0,)),
        ("point_clutter_filter_count", (1,)),
        ("dual_pol_only_filtered_count", (2,)),
        ("reserved_code_count", (3, 4, 5, 6, 7)),
    ),
}
_NOTE_21 = (("below_threshold_count", (0,)), ("range_folded_count", (1,)))
DATA_BEGINS = {"CFP": 8}

#: Table III-C: the six radial statuses, each with and without the 0x80 bad-data bit.
RADIAL_STATUSES = frozenset(range(0, 6)) | frozenset(range(0x80, 0x86))
BAD_DATA = 0x80

#: The message types the metadata record holds (7.3.5), 0 for an unused segment.
METADATA_TYPES = frozenset({0, 2, 3, 5, 13, 15, 18, 32})

_VOLUME_HEADER = struct.Struct(">9s3sII4s")
_MESSAGE_HEADER = struct.Struct(">HBBHHIHH")
_DATA_HEADER = struct.Struct(">4sIHHfBBHBBBBfBBH")
_VOL = struct.Struct(">HBBffhHfffffHHH")
_ELV = struct.Struct(">Hhf")
_RAD = struct.Struct(">HHffHHff")
_MOMENT = struct.Struct(">IHHHHhBBff")
_CONSTANT_SIZES = {b"VOL": 52, b"ELV": 12, b"RAD": 28}
_ICAO = re.compile(rb"[A-Z]{4}")
_HEX = re.compile(r"[0-9a-f]*")

_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def _f32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


#: The ranges the ICD states, each a validation rule: (twin key, the ICD's name, low, high).
#: A Real*4 field's bounds are compared as the single-precision values a writer of them stores.
#: Where the ICD contradicts itself the union is taken: Table III-C defines 0x85, beyond the
#: Radial Status range column's 132; RHO's typical offset (-60.5) is outside Table XVII-B's
#: offset range of 2.0 to 65535.0, so an offset is held only to being finite.
DATA_HEADER_RANGES = (
    ("collection_time", "Collection Time", 0, 86_399_999),
    ("julian_date", "Modified Julian Date", 1, 65_535),
    ("azimuth_number", "Azimuth Number", 1, MAX_AZIMUTHS),
    ("azimuth_angle", "Azimuth Angle", 0.0, _f32(359.956055)),
    ("radial_length", "Radial Length", 9_360, 14_296),
    ("azimuth_spacing", "Azimuth Resolution Spacing", 1, 2),
    ("elevation_number", "Elevation Number", 1, MAX_ELEVATIONS),
    ("cut_sector", "Cut Sector Number", 0, 3),
    ("elevation_angle", "Elevation Angle", -7.0, 70.0),
    ("spot_blanking", "Radial Spot Blanking Status", 0, 7),
    ("azimuth_indexing", "Azimuth Indexing Mode", 0, 100),
    ("block_count", "Data Block Count", 4, 10),
)
SITE_RANGES = (
    ("latitude", "Lat", 0.0, 90.0),
    ("longitude", "Long", -180.0, 180.0),
    ("site_height", "Site Height", -100, 12_000),
    ("tower_height", "Tower Height", 0, 1_000),
)
VOL_RANGES = (
    ("version_major", "Version Number (major)", 1, 255),
    ("dbz0", "Calibration Constant (dBZ0)", -99.0, 99.0),
    ("horizontal_tx_power", "Horizontal SHV Tx Power", 0.0, _f32(999.9)),
    ("vertical_tx_power", "Vertical SHV Tx Power", 0.0, _f32(999.9)),
    ("system_zdr", "System Differential Reflectivity", -7.875, 7.75),
    ("initial_system_phidp", "Initial System Differential Phase", 0.0, 360.0),
    ("vcp", "Volume Coverage Pattern Number", 1, 767),
)
ELV_RANGES = (
    ("atmospheric_attenuation", "ATMOS", -20, -2),
    ("dbz0", "Calibration Constant (dBZ0)", -99.0, 99.0),
)
RAD_RANGES = (
    ("unambiguous_range", "Unambiguous Range", 1_150, 5_110),
    ("noise_level_h", "Noise Level (horizontal)", -100.0, -50.0),
    ("noise_level_v", "Noise Level (vertical)", -100.0, -50.0),
    ("nyquist_velocity", "Nyquist Velocity", 800, 3_561),
    ("calibration_h", "Calibration Constant (horizontal)", -99.0, 99.0),
    ("calibration_v", "Calibration Constant (vertical)", -99.0, 99.0),
)
MOMENT_RANGES = (
    ("gates", "Number of Data Moment Gates", 1, 1_840),
    ("first_gate_range", "Data Moment Range", 0, 32_768),
    ("gate_interval", "Data Moment Range Sample Interval", 250, 4_000),
    ("tover", "TOVER", 0, 200),
    ("snr_threshold", "SNR Threshold", -96, 160),
    ("control_flags", "Control Flags", 0, 3),
)

# -- the transformations, by what they read ------------------------------------------------------

T_VOLUME_INSTANT = (
    "volume header: the start of the volume is the header's NEXRAD-modified Julian date "
    "(1970-01-01 = day 1) plus its milliseconds past midnight (ICD 2620010J Figure 1), rendered "
    "to the CDM's millisecond form; it is SourceRef.observed_at and the site's valid_from"
)
T_COLLECTION_INSTANT = (
    "sweeps[*].radials[*].collection_time: a radial's instant is its Modified Julian Date plus "
    "its Collection Time, milliseconds past midnight GMT (ICD 2620002Y Table XVII-A); a sweep's "
    "observed_at is its last radial's and validity.effective runs from its first to its last"
)
T_SCALED = (
    "scaled integers: first-gate range and gate interval (thousandths of a km), TOVER (tenths of "
    "a dB), SNR threshold (eighths of a dB), ATMOS (thousandths of a dB/km), unambiguous range "
    "(tenths of a km) and Nyquist velocity (hundredths of m/s) are stated in their units in the "
    "contract; the residual keeps the integers the radial states"
)
T_GATES = (
    "derived: the gate codes of every moment of every radial stay in the volume, by reference; "
    "the contract states the shape, the packing, a summary whose minimum and maximum are each "
    "radial's codes converted with that radial's own scale and offset, and the count of every "
    "coded value that is not a measurement, each under its own name"
)
T_WIRE = (
    "derived: the twin's wire_hex is the volume's octets; every object is decoded from them and "
    "they are not copied, the file being identified by source_hash"
)
T_NAME = (
    "sweeps[*].radials[*].moments[*].name: a moment name the ICD pads to three characters "
    "('SW ') is stated without its trailing space in the contract and in applies_to; the "
    "residual keeps the three characters"
)

TWIN_KEYS = ("wire_hex", "volume_header", "site", "records", "sweeps", "gates")


class Nexrad2Refused(ValueError):
    """A volume this module will not translate. `code` names the rule; the text names the field
    and its position (LDM record, message), never a value from the payload."""

    def __init__(self, code: str, text: str) -> None:
        super().__init__(f"{code}: {text}")
        self.code = code

    def __reduce__(self):
        return (_rebuild_refusal, (self.code, str(self)))


def _rebuild_refusal(code: str, message: str) -> Nexrad2Refused:
    refusal = Nexrad2Refused(code, "")
    refusal.args = (message,)
    return refusal


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _in_range(where: str, table: tuple, fields: dict) -> None:
    for key, name, low, high in table:
        value = fields[key]
        finite = not isinstance(value, float) or math.isfinite(value)
        if not (finite and low <= value <= high):
            raise Nexrad2Refused(
                f"{_slug(name)}-out-of-range",
                f"{where}: {name} is not a finite value in {low} to {high} ({ICD})",
            )


def instant(julian_date: int, milliseconds: int) -> _dt.datetime:
    """A NEXRAD-modified Julian date (1970-01-01 = 1) and milliseconds past midnight, in UTC."""
    return _EPOCH + _dt.timedelta(days=julian_date - 1, milliseconds=milliseconds)


# -- octets to a parsed volume -------------------------------------------------------------------


@dataclasses.dataclass
class _Stats:
    """What one moment of one radial states in its gates, counted without copying them."""

    coded: dict[int, int]
    data_count: int
    min_code: int | None
    max_code: int | None


@dataclasses.dataclass
class Volume:
    """A decoded volume: the twin-shaped document (without `wire_hex`) and, per radial, the gate
    statistics the translation summarises. `stats[(elevation, azimuth)][name]`."""

    document: dict
    stats: dict[tuple[int, int], dict[str, _Stats]]


def _inflate(stream: bytes, where: str, cap: int, remaining: int, limit: int) -> bytes:
    """One record's bzip2 stream, its output held to `min(cap, remaining)`."""
    if stream[:3] != b"BZh":
        raise Nexrad2Refused("not-bzip2", f"{where} does not begin with the bzip2 magic BZh")
    allowed = min(cap, remaining)
    inflater = bz2.BZ2Decompressor()
    try:
        out = inflater.decompress(stream, allowed + 1)
    except OSError:
        raise Nexrad2Refused(
            "bzip2-corrupt", f"{where}: the bzip2 stream is corrupt or fails its CRC"
        ) from None
    if len(out) > allowed:
        # The volume's budget is what ran out whenever it was no larger than the record's own
        # bound, the equal case included (R3 review R3-r1-03): the volume code, not the record's.
        if remaining <= cap:
            raise Nexrad2Refused(
                "decompresses-past-the-bound",
                f"the volume decompresses past max_decompressed_bytes = {limit} octets in "
                f"{where}; refused before the octet past the bound was kept",
            )
        if cap == METADATA_RECORD_BYTES:
            raise Nexrad2Refused(
                "metadata-record-size",
                f"{where}, the metadata record, decompresses past {METADATA_RECORD_BYTES} "
                f"octets; {ICD_FILE} 7.3.5 fixes it at {METADATA_SEGMENTS} segments",
            )
        raise Nexrad2Refused(
            "record-past-its-bound",
            f"{where} decompresses past {cap} octets, the bound on one radial record",
        )
    if not inflater.eof:
        raise Nexrad2Refused(
            "truncated-bzip2", f"{where}: the bzip2 stream ends before its end-of-stream marker"
        )
    if inflater.unused_data:
        raise Nexrad2Refused(
            "octets-after-bzip2",
            f"{where}: octets follow the bzip2 stream inside the size the control word states",
        )
    return out


def _gate_stats(name: str, data: bytes, word_size: int) -> tuple[_Stats, Any]:
    """Counts of the coded values and the extreme data codes, read without a per-gate loop."""
    if word_size == 8:
        codes: Any = data
        count = data.count
        coded = {c: count(bytes((c,))) for c in _coded_values(name)}
    else:
        codes = array.array("H")
        codes.frombytes(data)
        if sys.byteorder == "little":
            codes.byteswap()
        coded = {c: codes.count(c) for c in _coded_values(name)}
    # `coded` counts every code below the data range, so what is left is measurement.
    begins = DATA_BEGINS.get(name, 2)
    present = [c for c in set(codes) if c >= begins]
    return (
        _Stats(
            coded=coded,
            data_count=len(codes) - sum(coded.values()),
            min_code=min(present) if present else None,
            max_code=max(present) if present else None,
        ),
        codes,
    )


def _coded_values(name: str) -> tuple[int, ...]:
    begins = DATA_BEGINS.get(name, 2)
    return tuple(range(begins))


def _runs(codes: Any) -> list[list[int]]:
    runs: list[list[int]] = []
    for code in codes:
        if runs and runs[-1][0] == code:
            runs[-1][1] += 1
        else:
            runs.append([code, 1])
    return runs


def _radial(
    data: bytes,
    icao: bytes,
    record: int,
    message: int,
    header: dict,
    with_gates: bool,
) -> tuple[dict, dict[str, _Stats], list[dict], dict]:
    """(stated radial, gate statistics per moment, gate runs per moment, site fields)."""
    where = f"LDM record {record}, message {message}"
    if len(data) < _DATA_HEADER.size:
        raise Nexrad2Refused("truncated-radial", f"{where}: the data header is cut short")
    (
        radar,
        collection,
        julian,
        azimuth_number,
        azimuth_angle,
        compression,
        _spare,
        radial_length,
        spacing,
        status,
        elevation_number,
        cut_sector,
        elevation_angle,
        spot,
        indexing,
        block_count,
    ) = _DATA_HEADER.unpack_from(data, 0)
    if radar != icao:
        raise Nexrad2Refused(
            "site-mismatch",
            f"{where}: the Radar Identifier is not the volume header's ICAO identifier",
        )
    if compression == 1:
        raise Nexrad2Refused(
            "radial-bzip2-compressed",
            f"{where}: the Compression Indicator says the radial is compressed with bzip2, which "
            "this module does not read",
        )
    if compression == 2:
        raise Nexrad2Refused(
            "radial-zlib-compressed",
            f"{where}: the Compression Indicator says the radial is compressed with zlib, which "
            "this module does not read",
        )
    if compression != 0:
        raise Nexrad2Refused(
            "radial-compression-unknown",
            f"{where}: the Compression Indicator is not 0, 1 or 2 ({ICD} Table XVII-A)",
        )
    stated = {
        "ldm_record": record,
        "message": message,
        "message_header": header,
        "collection_time": collection,
        "julian_date": julian,
        "azimuth_number": azimuth_number,
        "azimuth_angle": azimuth_angle,
        "compression": compression,
        "radial_length": radial_length,
        "azimuth_spacing": spacing,
        "radial_status": status,
        "elevation_number": elevation_number,
        "cut_sector": cut_sector,
        "elevation_angle": elevation_angle,
        "spot_blanking": spot,
        "azimuth_indexing": indexing,
        "block_count": block_count,
    }
    _in_range(where, DATA_HEADER_RANGES, stated)
    if status not in RADIAL_STATUSES:
        raise Nexrad2Refused(
            "radial-status-out-of-range",
            f"{where}: the Radial Status is none of Table III-C's twelve values",
        )
    if not radial_length <= len(data) <= radial_length + 1:
        raise Nexrad2Refused(
            "radial-length-disagrees",
            f"{where}: the Radial Length is not the length of the message's radial",
        )
    data = data[:radial_length]
    header_end = _DATA_HEADER.size + 4 * block_count
    if header_end > radial_length:
        raise Nexrad2Refused(
            "block-past-the-radial", f"{where}: the data block pointers run past the radial"
        )
    pointers = struct.unpack_from(f">{block_count}I", data, _DATA_HEADER.size)
    spans: list[tuple[int, int]] = []
    constants: dict[bytes, tuple] = {}
    moments: list[dict] = []
    stats: dict[str, _Stats] = {}
    gates: list[dict] = []
    for slot, pointer in enumerate(pointers):
        if pointer == 0:
            continue  # note 11: a zero pointer references no block
        at = f"{where}, data block pointer {slot}"
        if pointer < header_end or pointer + 4 > radial_length:
            raise Nexrad2Refused("block-past-the-radial", f"{at} points outside the radial")
        kind, name = data[pointer : pointer + 1], data[pointer + 1 : pointer + 4]
        if kind == b"R" and name in _CONSTANT_SIZES:
            size = _CONSTANT_SIZES[name]
            if pointer + size > radial_length:
                raise Nexrad2Refused("block-past-the-radial", f"{at}: the block runs past it")
            if name in constants:
                raise Nexrad2Refused("block-stated-twice", f"{at}: a second {name.decode()}")
            layout = {b"VOL": _VOL, b"ELV": _ELV, b"RAD": _RAD}[name]
            fields = layout.unpack_from(data, pointer + 4)
            if fields[0] != size:
                raise Nexrad2Refused(
                    "block-size",
                    f"{at}: the {name.decode()} block's LRTUP is not {size} ({ICD} Table XVII)",
                )
            constants[name] = fields
            spans.append((pointer, pointer + size))
        elif kind == b"D" and name.decode("latin-1") in MOMENTS:
            text = name.decode("latin-1")
            if pointer + 4 + _MOMENT.size > radial_length:
                raise Nexrad2Refused("block-past-the-radial", f"{at}: the block runs past it")
            if text in stats:
                raise Nexrad2Refused("block-stated-twice", f"{at}: a second {text.strip()}")
            (reserved, count, first, interval, tover, snr, control, word, scale, offset) = (
                _MOMENT.unpack_from(data, pointer + 4)
            )
            block = {
                "name": text,
                "reserved": reserved,
                "gates": count,
                "first_gate_range": first,
                "gate_interval": interval,
                "tover": tover,
                "snr_threshold": snr,
                "control_flags": control,
                "word_size": word,
                "scale": scale,
                "offset": offset,
            }
            _in_range(f"{at} ({text.strip()})", MOMENT_RANGES, block)
            if word not in (8, 16):
                raise Nexrad2Refused(
                    "data-word-size-out-of-range",
                    f"{at} ({text.strip()}): the Data Word Size is not 8 or 16 ({ICD} XVII-B)",
                )
            if not math.isfinite(scale) or scale < 0 or scale > 65_535.0:
                raise Nexrad2Refused(
                    "scale-out-of-range",
                    f"{at} ({text.strip()}): the Scale is not a finite value in 0 to 65535",
                )
            if scale == 0:
                raise Nexrad2Refused(
                    "floating-point-moment",
                    f"{at} ({text.strip()}): a Scale of 0 marks floating-point gates (note 15), "
                    "which this module does not read",
                )
            if not math.isfinite(offset):
                raise Nexrad2Refused(
                    "offset-out-of-range", f"{at} ({text.strip()}): the Offset is not finite"
                )
            start = pointer + 4 + _MOMENT.size
            end = start + count * word // 8
            if end > radial_length:
                raise Nexrad2Refused(
                    "block-past-the-radial", f"{at} ({text.strip()}): the gates run past it"
                )
            stats[text], codes = _gate_stats(text, data[start:end], word)
            if with_gates:
                gates.append({"moment": text, "runs": _runs(codes)})
            moments.append(block)
            spans.append((pointer, end))
        elif kind == b"D":
            raise Nexrad2Refused(
                "unknown-moment", f"{at}: a data moment Table XVII-I does not name"
            )
        else:
            raise Nexrad2Refused(
                "unknown-block", f"{at}: a block that is not VOL, ELV, RAD or a data moment"
            )
    spans.sort()
    for (_, end), (start, _) in zip(spans, spans[1:]):
        if end > start:
            raise Nexrad2Refused("blocks-overlap", f"{where}: two data blocks overlap")
    for name in (b"VOL", b"ELV", b"RAD"):
        if name not in constants:
            raise Nexrad2Refused(
                "constant-block-missing",
                f"{where}: no {name.decode()} block ({ICD} Table XVII-A note 10: always present)",
            )
    if "REF" not in stats:
        raise Nexrad2Refused(
            "reflectivity-missing",
            f"{where}: no REF moment ({ICD} Table XVII-A note 9: always present)",
        )
    (
        _,
        major,
        minor,
        lat,
        lon,
        height,
        tower,
        dbz0,
        power_h,
        power_v,
        zdr,
        phidp,
        vcp,
        processing,
        zdr_bias,
    ) = constants[b"VOL"]
    site = {"latitude": lat, "longitude": lon, "site_height": height, "tower_height": tower}
    stated["vol"] = {
        "version_major": major,
        "version_minor": minor,
        "dbz0": dbz0,
        "horizontal_tx_power": power_h,
        "vertical_tx_power": power_v,
        "system_zdr": zdr,
        "initial_system_phidp": phidp,
        "vcp": vcp,
        "processing_status": processing,
        "zdr_bias": zdr_bias,
    }
    _, atmos, elv_dbz0 = constants[b"ELV"]
    stated["elv"] = {"atmospheric_attenuation": atmos, "dbz0": elv_dbz0}
    _, unambiguous, noise_h, noise_v, nyquist, flags, cal_h, cal_v = constants[b"RAD"]
    stated["rad"] = {
        "unambiguous_range": unambiguous,
        "noise_level_h": noise_h,
        "noise_level_v": noise_v,
        "nyquist_velocity": nyquist,
        "radial_flags": flags,
        "calibration_h": cal_h,
        "calibration_v": cal_v,
    }
    stated["moments"] = moments
    _in_range(f"{where}, VOL", SITE_RANGES, site)
    _in_range(f"{where}, VOL", VOL_RANGES, stated["vol"])
    _in_range(f"{where}, ELV", ELV_RANGES, stated["elv"])
    _in_range(f"{where}, RAD", RAD_RANGES, stated["rad"])
    return stated, stats, gates, site


def _volume_header(octets: bytes) -> dict:
    if len(octets) < _VOLUME_HEADER.size:
        raise Nexrad2Refused(
            "short-volume-header",
            f"the volume is shorter than the {_VOLUME_HEADER.size}-octet volume header "
            f"({ICD_FILE} Figure 1)",
        )
    tape, extension, julian, milliseconds, icao = _VOLUME_HEADER.unpack_from(octets, 0)
    if tape[:6] != b"AR2V00":
        raise Nexrad2Refused(
            "not-archive-ii", "the octets do not begin with an Archive II tape name, AR2V00"
        )
    if not (tape[6:8].isdigit() and tape[8:9] == b"."):
        raise Nexrad2Refused("bad-volume-header", "the tape name is not AR2V00, two digits, '.'")
    if tape[6:8] not in (b"06", b"07"):
        raise Nexrad2Refused(
            "unsupported-archive-version",
            f"the tape name's version is not 06 or 07, the two {ICD_FILE} Figure 1 says the RPG "
            "supports as of Build 17.0",
        )
    if not extension.isdigit() or extension == b"000":
        raise Nexrad2Refused("bad-volume-header", "the extension number is not 001 to 999")
    if not 1 <= julian <= 65_535 or milliseconds > 86_399_999:
        raise Nexrad2Refused(
            "bad-volume-header",
            "the volume header's date or time is outside a day 1 to 65535 and 0 to 86399999 ms",
        )
    if _ICAO.fullmatch(icao) is None:
        raise Nexrad2Refused(
            "bad-volume-header", "the volume header's ICAO identifier is not four letters"
        )
    return {
        "tape": tape.decode("ascii"),
        "extension": extension.decode("ascii"),
        "julian_date": julian,
        "milliseconds": milliseconds,
        "icao": icao.decode("ascii"),
    }


def decode_volume(
    octets: bytes, *, limit: int = MAX_DECOMPRESSED_BYTES, with_gates: bool = False
) -> Volume:
    """One Archive II volume, framed, inflated in bounded steps and checked against the ICDs.

    `limit` is the volume's decompression bound (`max_decompressed_bytes` unless a test lowers
    it). `with_gates` also states every moment's gate codes as runs, which only the twin needs:
    the translation counts codes without walking them one by one.
    """
    header = _volume_header(octets)
    icao = header["icao"].encode("ascii")
    records: list[dict] = []
    radials: list[dict] = []
    stats: dict[tuple[int, int], dict[str, _Stats]] = {}
    gates: list[dict] = []
    sites: list[tuple[str, dict]] = []
    position, index, total = _VOLUME_HEADER.size, 0, 0
    while position < len(octets):
        where = f"LDM record {index}"
        if len(octets) - position < 4:
            raise Nexrad2Refused(
                "truncated-record", f"{where}: fewer than four octets remain for a control word"
            )
        (word,) = struct.unpack_from(">i", octets, position)
        size = abs(word)
        if size == 0:
            raise Nexrad2Refused("empty-record", f"{where}: the control word states no octets")
        if position + 4 + size > len(octets):
            raise Nexrad2Refused(
                "record-past-the-end",
                f"{where}: the control word's absolute value runs past the end of the volume",
            )
        cap = METADATA_RECORD_BYTES if index == 0 else MAX_RECORD_BYTES
        blob = _inflate(
            octets[position + 4 : position + 4 + size], where, cap, limit - total, limit
        )
        total += len(blob)
        if index == 0:
            records.append(_metadata_record(blob, word, size))
        else:
            records.append(
                _radial_record(
                    blob, word, size, index, icao, radials, stats, gates, sites, with_gates
                )
            )
        position += 4 + size
        index += 1
    if not radials:
        raise Nexrad2Refused("no-radial", "the volume holds no message-31 radial")
    first_site = sites[0][1]
    for where, site in sites[1:]:
        if site != first_site:
            raise Nexrad2Refused(
                "site-varies",
                f"{where}: the VOL block's latitude, longitude or heights differ from the first "
                "radial's; a volume is one site",
            )
    document = {
        "volume_header": header,
        "site": dict(first_site),
        "records": records,
        "sweeps": _sweeps(radials),
        "gates": gates,
    }
    return Volume(document=document, stats=stats)


def _metadata_record(blob: bytes, word: int, size: int) -> dict:
    if len(blob) != METADATA_RECORD_BYTES:
        raise Nexrad2Refused(
            "metadata-record-size",
            f"LDM record 0, the metadata record, is not {METADATA_RECORD_BYTES} octets "
            f"({ICD_FILE} 7.3.5: {METADATA_SEGMENTS} segments of {SEGMENT_BYTES})",
        )
    counts: dict[int, int] = {}
    for segment in range(METADATA_SEGMENTS):
        message_type = blob[segment * SEGMENT_BYTES + 15]
        _refuse_by_name(message_type, f"LDM record 0, message {segment}")
        if message_type not in METADATA_TYPES:
            raise Nexrad2Refused(
                "unexpected-message-type",
                f"LDM record 0, message {segment}: a message type the metadata record does not "
                f"hold ({ICD_FILE} 7.3.5)",
            )
        counts[message_type] = counts.get(message_type, 0) + 1
    return _record_entry(word, size, len(blob), METADATA_SEGMENTS, counts)


def _record_entry(word: int, size: int, length: int, messages: int, counts: dict) -> dict:
    return {
        "control_word": word,
        "compressed_bytes": size,
        "decompressed_bytes": length,
        "messages": messages,
        "message_types": {str(k): counts[k] for k in sorted(counts)},
    }


def _refuse_by_name(message_type: int, where: str) -> None:
    if message_type == 1:
        raise Nexrad2Refused(
            "message-1",
            f"{where}: message 1, the legacy digital radar data message, replaced by message 31 "
            "as of Build 10; this module does not decode it",
        )
    if message_type == 29:
        raise Nexrad2Refused(
            "message-29",
            f"{where}: message 29, the model data of an _MDM record ({ICD_FILE} 7.3.4); this "
            "module does not decode it",
        )


def _radial_record(
    blob: bytes,
    word: int,
    size: int,
    record: int,
    icao: bytes,
    radials: list,
    stats: dict,
    gates: list,
    sites: list,
    with_gates: bool,
) -> dict:
    position, message, count = 0, 0, 0
    counts: dict[int, int] = {}
    while position < len(blob):
        where = f"LDM record {record}, message {message}"
        if len(blob) - position < 12 + _MESSAGE_HEADER.size:
            raise Nexrad2Refused("truncated-message", f"{where}: the message header is cut short")
        (length, channel, message_type, sequence, julian, milliseconds, segments, number) = (
            _MESSAGE_HEADER.unpack_from(blob, position + 12)
        )
        _refuse_by_name(message_type, where)
        if message_type == 31:
            end = position + 12 + 2 * length
            if length <= _MESSAGE_HEADER.size // 2 or end > len(blob):
                raise Nexrad2Refused(
                    "truncated-message",
                    f"{where}: the message size runs past the record or holds no radial",
                )
            if (segments, number) != (1, 1):
                raise Nexrad2Refused(
                    "message-segments",
                    f"{where}: a message 31 states one segment, number 1 ({ICD} Table II)",
                )
            count += 1
            if count > MAX_RADIALS_PER_RECORD:
                raise Nexrad2Refused(
                    "too-many-radials",
                    f"LDM record {record} holds more than {MAX_RADIALS_PER_RECORD} radials "
                    f"({ICD_FILE} 7.3.4)",
                )
            header = {
                "size": length,
                "channel": channel,
                "sequence": sequence,
                "julian_date": julian,
                "milliseconds": milliseconds,
                "segments": segments,
                "segment_number": number,
            }
            stated, moment_stats, moment_gates, site = _radial(
                blob[position + 12 + _MESSAGE_HEADER.size : end],
                icao,
                record,
                message,
                header,
                with_gates,
            )
            key = (stated["elevation_number"], stated["azimuth_number"])
            if key in stats:
                raise Nexrad2Refused(
                    "radial-stated-twice",
                    f"{where}: elevation {key[0]} already holds a radial with this azimuth number",
                )
            stats[key] = moment_stats
            radials.append(stated)
            sites.append((where, site))
            gates.extend(
                {
                    "elevation_number": key[0],
                    "azimuth_number": key[1],
                    "moment": entry["moment"],
                    "runs": entry["runs"],
                }
                for entry in moment_gates
            )
            position = end
        elif message_type == 2:
            if position + SEGMENT_BYTES > len(blob):
                raise Nexrad2Refused(
                    "truncated-message", f"{where}: the RDA status segment is cut short"
                )
            position += SEGMENT_BYTES
        else:
            raise Nexrad2Refused(
                "unexpected-message-type",
                f"{where}: a message type where a radial (31) or an RDA status message (2) is "
                f"required ({ICD_FILE} 7.3.4)",
            )
        counts[message_type] = counts.get(message_type, 0) + 1
        message += 1
    return _record_entry(word, size, len(blob), message, counts)


def _sweeps(radials: list[dict]) -> list[dict]:
    """The radials grouped by elevation NUMBER, in number order, each in file order, with the
    rules a sweep's contract states: one gate geometry per moment, every moment on every radial,
    and collection times that do not run backwards."""
    grouped: dict[int, list[dict]] = {}
    for stated in radials:
        grouped.setdefault(stated["elevation_number"], []).append(stated)
    sweeps = []
    for number in sorted(grouped):
        members = grouped[number]
        first = members[0]
        names = [m["name"] for m in first["moments"]]
        geometry = {m["name"]: _geometry(m) for m in first["moments"]}
        previous = None
        for stated in members:
            where = f"LDM record {stated['ldm_record']}, message {stated['message']}"
            if sorted(m["name"] for m in stated["moments"]) != sorted(names):
                raise Nexrad2Refused(
                    "moment-not-on-every-radial",
                    f"{where}: elevation {number}'s radials do not all state the same moments",
                )
            for m in stated["moments"]:
                if _geometry(m) != geometry[m["name"]]:
                    raise Nexrad2Refused(
                        "moment-geometry-varies",
                        f"{where}: {m['name'].strip()}'s gate count, first-gate range, gate "
                        f"interval or word size differs within elevation {number}",
                    )
            when = instant(stated["julian_date"], stated["collection_time"])
            if previous is not None and when < previous:
                raise Nexrad2Refused(
                    "radial-times-out-of-order",
                    f"{where}: the collection time precedes the previous radial's in elevation "
                    f"{number}",
                )
            previous = when
        sweeps.append({"elevation_number": number, "radials": members})
    return sweeps


def _geometry(block: dict) -> tuple:
    return (block["gates"], block["first_gate_range"], block["gate_interval"], block["word_size"])


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


def _from_twin(document: dict) -> tuple[bytes, Volume]:
    if set(document) != set(TWIN_KEYS):
        raise Nexrad2Refused(
            "not-a-twin",
            "a dict is the volume's twin, exactly: " + ", ".join(TWIN_KEYS),
        )
    wire = document["wire_hex"]
    if (
        not isinstance(wire, str)
        or len(wire) > 2 * MAX_INPUT_BYTES
        or len(wire) % 2
        or _HEX.fullmatch(wire) is None
    ):
        raise Nexrad2Refused(
            "bad-wire-hex",
            f"wire_hex is not lower-case hexadecimal of at most {MAX_INPUT_BYTES} octets",
        )
    octets = bytes.fromhex(wire)
    volume = decode_volume(octets, with_gates=True)
    for key in TWIN_KEYS[1:]:
        if not _same(document[key], volume.document[key]):
            raise Nexrad2Refused(
                "twin-disagrees", f"the twin's {key} is not what its wire_hex decodes to"
            )
    return octets, volume


def twin_of(octets: bytes) -> dict:
    """The parsed twin of a volume: its octets as `wire_hex` and everything it states."""
    volume = decode_volume(bytes(octets), with_gates=True)
    return {"wire_hex": bytes(octets).hex(), **volume.document}


# -- the declaration -----------------------------------------------------------------------------


def _residual(path: str, target: str) -> Mapping:
    return Mapping(to=f"{target}:residual.data.{path}", kind="residual")


class Nexrad2Adapter(Adapter):
    """One NEXRAD Level II volume in; one Event per sweep and the radar site's Entity out."""

    name = "nexrad2"
    version = "1.0.0"
    direction = "ingest"
    system = SYSTEM

    #: Adapter API v2's declaration. `PUBLIC_GOVERNMENT`: both ICDs carry "DISTRIBUTION STATEMENT
    #: A: Approved for public release; distribution unlimited" and are a US Government agency's
    #: free public downloads (research-nexrad-level2 F01, F08).
    metadata = AdapterMetadata(
        id="nexrad2",
        name="NEXRAD Level II (Archive II) volume translator",
        adapter_version="1.0.0",
        format=FormatRef(name=FORMAT_NAME, version=FORMAT_VERSION),
        binding=WireBinding.STANDARD,
        direction=Direction.INGEST,
        license_class=LicenseClass.PUBLIC_GOVERNMENT,
        maturity=Maturity(
            level=MaturityLevel.L3,
            basis="L3 PROVENANCE VERIFIED, from evidence that runs today in this package: "
            "`synapse_cdm.harness --adapter nexrad2` over the packaged fixture set reports "
            "`translate`, `schema` and `provenance` PASS on every fixture, which carries L1 to "
            "L3, and its `lossless` column rests on the path-bound ledger (`MAPPINGS` declared, "
            "every radial header a structured residual, the gate codes and the octets a "
            "declared limitation) with no LOST leaf on any parsed twin. L4 is NOT declared: "
            "this adapter is ingest-only, so the roundtrip check is inapplicable rather than "
            "passed (ARCHITECTURE.md §3.6, rule 4), and a rung passed vacuously is not a rung "
            "declared.",
            external_exercise=None,
        ),
        claim_status=ClaimStatus.VERIFIED,
        claim_external_system=None,
        profiles=[],
        capabilities=Capabilities(
            wire=True,
            directions_exercised=["ingest"],
            message_types=[
                "NEXRAD Level II Archive II volume (ICD 2620010J, Build 23.0): the volume "
                "header, the bzip2 LDM records, the 134-segment metadata record (framed and "
                "counted) and message 31 radials (ICD 2620002Y Table XVII); one "
                "ENVIRONMENTAL_OBSERVATION Event per elevation number and the radar site's "
                "Entity per volume",
            ],
            limits=Limits(
                max_input_bytes=MAX_INPUT_BYTES,
                max_depth=MAX_DEPTH,
                max_objects=MAX_OBJECTS,
                max_decompressed_bytes=MAX_DECOMPRESSED_BYTES,
                max_parse_seconds=None,
                absent_because={
                    "max_parse_seconds": "no wall-clock bound is enforced: this module reads no "
                    "clock, every record is inflated under a byte bound and every walk is "
                    "linear in what was inflated; the conformance suite's parser worker kills "
                    "a decode that overruns its deadline",
                },
                declared_because={
                    "max_input_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "No ICD states a maximum size for a volume file. The design "
                            "record's figure is the archive's own listing for one site and day: "
                            "KOKX on 2026-09-11, 248 volumes of 3,601,535 to 8,908,516 octets "
                            "(research-nexrad-level2 F03). 32 MiB (33 554 432 octets, "
                            "`MAX_INPUT_BYTES`, `adapters/nexrad2.py`) is DECISIONS U-07's "
                            "bound for one volume, over three times the largest. " + _CAP
                        ),
                        enforced_at=(
                            "`Adapter.__init_subclass__` wraps this class's own `to_cdm` with "
                            "`enforce_input_bound` at class-definition time (`adapter.py`, "
                            "`_bind_input_bound`), so the octets are measured and refused before "
                            "this module reads a header or inflates a record"
                        ),
                        test="tests/test_cdm_input_bounds.py::test_every_adapter_refuses_one_octet_over_its_declared_bound",
                    ),
                    "max_decompressed_bytes": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The ICDs' ceilings: the metadata record is fixed at 325,888 octets "
                            "(ICD 2620010J 7.3.5) and a radial record at 120 radials of at most "
                            "14,296 octets (7.3.4, ICD 2620002Y Table XVII-A), <= 1.72 MB "
                            "(research-nexrad-level2 F03/F12); with each radial record held to "
                            "2 MiB (`MAX_RECORD_BYTES_BASIS`) and the 32 x 720 radials a volume "
                            "can number filling 192 of them, a volume decompresses to at most "
                            "325,888 + 192 x 2,097,152 = 402,979,072 octets "
                            "(`MAX_DECOMPRESSED_BYTES`, `adapters/nexrad2.py`). " + _CAP
                        ),
                        enforced_at=(
                            "`nexrad2.decode_volume`: every record's bzip2 stream is inflated "
                            "by `bz2.BZ2Decompressor.decompress` with `max_length` set to one "
                            "octet past what the volume may still decompress to, and that octet "
                            "is refused `decompresses-past-the-bound` before it is kept"
                        ),
                        test=_TESTS
                        + "test_the_volume_is_held_to_its_decompression_bound_at_the_octet",
                    ),
                    "max_objects": LimitBasis(
                        kind=LimitKind.NORMATIVE,
                        source=(
                            "NORMATIVE, from ICD 2620002Y §3.2.4.17.1 Table XVII-A: Elevation "
                            "Number, 'Elevation number within volume scan', range 1 to 32. One "
                            "Event per elevation number and the site's Entity make at most 33 "
                            "objects (`MAX_OBJECTS`, `adapters/nexrad2.py`)."
                        ),
                        enforced_at=(
                            "`nexrad2._radial`: an Elevation Number outside 1 to 32 is refused "
                            "`elevation-number-out-of-range`, so a volume groups into at most "
                            "32 sweeps"
                        ),
                        test=_TESTS + "test_thirty_two_elevations_are_thirty_three_objects",
                    ),
                    "max_depth": LimitBasis(
                        kind=LimitKind.IMPLEMENTATION_CAP,
                        source=(
                            "The octets are never JSON; the dict form, the parsed twin, nests "
                            "seven containers (a radial's moment inside the sweep's radials). "
                            "16 (`MAX_DEPTH`, `adapters/nexrad2.py`) is the dis7 envelope's "
                            "bound, over twice that. " + _CAP
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
                "the volume is binary with fixed tables: a data block, a data moment or a "
                "message type the ICDs do not name is refused rather than preserved (the "
                "stricter reading of ICD 2620002Y Table XVII-A note 9), and the dict form is "
                "held to be exactly what its own wire_hex decodes to, so an injected key is "
                "refused `not-a-twin`"
            ),
        ),
        limitations=[
            by_reference_limitation(
                ["gates"],
                notes=(
                    "the twin's `gates` holds every moment's gate codes as runs; the contract "
                    "states each moment's locator, shape [radials, gates], packing and a summary"
                ),
            ),
            Limitation(
                id="volume-octets-by-reference",
                summary="the twin's wire_hex is the volume's octets, the input its dict form "
                "is decoded from; they are identified by SourceRef.source_hash when the host "
                "injects it and are not copied into any object",
                unsupported_paths=["wire_hex"],
            ),
            Limitation(
                id="one-volume-per-call",
                summary="exactly one Archive II volume file per call, as its octets or as its "
                "twin; a real-time chunk (the _chunks bucket's records), a gzip or tar around "
                "the volume and an _MDM sidecar are not taken. synapse-decode unwraps a gzip or "
                "a named tar member before the adapter sees the volume",
            ),
            Limitation(
                id="messages-refused-by-name",
                summary="message 1 (the legacy radial, pre-Build 10), message 29 (model data, "
                "the _MDM record) and a radial whose Compression Indicator is 1 (bzip2) or 2 "
                "(zlib) are refused by name and not decoded; an archive version other than 06 "
                "or 07 is refused",
            ),
            Limitation(
                id="metadata-not-decoded",
                summary="the metadata record's messages (15, 32, 13, 18, 3, 5, 2) and the RDA "
                "status messages (2) among the radials are framed and counted by type in the "
                "site Entity's residual, not decoded; the VCP is read from each radial's VOL "
                "block, not from message 5",
            ),
            Limitation(
                id="geometry-is-the-site",
                summary="Event.geometry is the radar site's point, not the area a sweep covers: "
                "no gate or beam geometry is computed, and the gates' ranges are the contract's "
                "first_gate_range and gate_interval",
            ),
            Limitation(
                id="strict-icd-ranges",
                summary="every range ICD 2620002Y Tables XVII-A, -B, -E, -F and -H state for a "
                "field this module reads is a validation rule, so a volume a lenient reader "
                "would take can be refused; Table XVII-I's data ranges are not rules (they are "
                "a moment's typical values, note 20), so a moment's gate codes are converted "
                "with each radial's own scale and offset and the summary is not range-checked "
                "(narrowed 2026-10-16, the 3.5.0 release); a data block or moment the ICD does "
                "not name is refused, not skipped (note 9 recommends skipping it); spare and "
                "reserved octets are not read except the moment block's Reserved word, which "
                "is carried",
            ),
            Limitation(
                id="zdr-bias-unscaled",
                summary="the VOL block's ZDR Bias Estimate Weighted Mean is carried as the "
                "Integer*2 it is stated as: the ICD's note 33 on its scaling is not in the "
                "design record, so no unit is stated for it",
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

    TRANSFORMS: dict[str, str] = {
        "wire_hex": T_WIRE,
        "gates": T_GATES,
    }

    #: The ledger. The site Entity is the LAST object, so sweep i of the twin is object i and
    #: `#[*]` holds every sweep's leaves to its own Event. A specific key comes before the
    #: subtree it falls under, because the first declaration that matches a leaf is the one it
    #: is held to.
    MAPPINGS = {
        "volume_header.icao": (
            _residual("volume_header.icao", "entity"),
            Mapping(to="entity:source_ids[0].external_id"),
        ),
        "volume_header": _residual("volume_header", "entity"),
        "site.latitude": (
            _residual("site.latitude", "entity"),
            Mapping(to="entity:position.lat", rule="number"),
        ),
        "site.longitude": (
            _residual("site.longitude", "entity"),
            Mapping(to="entity:position.lon", rule="number"),
        ),
        "site.site_height": (
            _residual("site.site_height", "entity"),
            Mapping(to="entity:position.vertical.value", rule="number"),
        ),
        "site": _residual("site", "entity"),
        "records": _residual("records", "entity"),
        "sweeps[*].elevation_number": (
            Mapping(to="#[*]:residual.data.elevation_number", kind="residual"),
            Mapping(to="#[*]:payload.observation.elevation_number"),
        ),
        "sweeps[*]": Mapping(to="#[*]:residual.data", kind="residual"),
    }

    def __init__(
        self,
        clock=None,
        *,
        synthetic: bool = True,
        source_hash: SourceHash | dict | None = None,
        frame_sha256: str | None = None,
    ) -> None:
        """`source_hash` is the SHA-256 of the file as the host read it, and `frame_sha256` the
        digest of the octets the host handed over when they are not the whole file (a volume
        inside a gzip or a tar). Both are values the caller computed — this package digests
        nothing — and both are constructor arguments, so both are in the determinism tuple."""
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
        self._source_hash = source_hash
        self._frame_sha256 = frame_sha256

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One volume -> [one Event per sweep, in elevation-number order, then the Entity]."""
        if isinstance(raw, (bytes, bytearray, memoryview)):
            volume = decode_volume(bytes(raw))
        elif isinstance(raw, dict):
            _, volume = _from_twin(raw)
        else:
            raise Nexrad2Refused(
                "unsupported-input",
                "a volume is handed over as its octets or as its twin in a dict; text and other "
                "types are not taken",
            )
        return self._translate(volume)

    # -- translation -----------------------------------------------------------------------------

    def _stamp(self, header: dict, start: _dt.datetime) -> Any:
        return self.source_ref().model_copy(
            update={
                "original_id": header["tape"] + header["extension"],
                "observed_at": start,
                "source_hash": self._source_hash,
            }
        )

    def _translate(self, volume: Volume) -> list[CDMBase]:
        document = volume.document
        header, site = document["volume_header"], document["site"]
        icao = header["icao"]
        start = instant(header["julian_date"], header["milliseconds"])
        stamp = self._stamp(header, start)
        namespace = self.metadata.format.name
        entity = site_entity(
            source=stamp.model_copy(update={"transformations": [T_VOLUME_INSTANT]}),
            system=SYSTEM,
            station_id=icao,
            site_class="radar_site",
            valid_from=start,
            stated_position=(site["latitude"], site["longitude"]),
            stated_position_basis=(
                f"the VOL data block ({ICD} Table XVII-E) every radial of the volume states "
                "alike: latitude and longitude in degrees"
            ),
            stated_vertical=VerticalPosition(
                value=float(site["site_height"]),
                unit=VerticalUnit.METRES,
                reference=VerticalReference.MSL,
            ),
            stated_vertical_basis=(
                f"the VOL block's Site Height, the height of the site base above mean sea level "
                f"in metres ({ICD} Table XVII-E); alt_m is metres above the ellipsoid and this "
                "is not one, and the tower height stays in the residual"
            ),
        )
        entity = entity.model_copy(
            update={
                "attributes": {
                    **entity.attributes,
                    "valid_from_basis": (
                        f"the volume header's start of the volume ({ICD_FILE} Figure 1: the "
                        "date and time of the start volume radial, from the RDA)"
                    ),
                },
                "residual": Residual(
                    namespace=namespace,
                    data={
                        "volume_header": dict(header),
                        "site": dict(site),
                        "records": [dict(r) for r in document["records"]],
                    },
                ),
            }
        )
        geometry = Point(coordinates=[site["longitude"], site["latitude"]])
        events = [
            self._sweep_event(sweep, volume, stamp, icao, start, entity.entity_id, geometry)
            for sweep in document["sweeps"]
        ]
        return [*events, entity]

    def _sweep_event(self, sweep, volume, stamp, icao, start, site_id, geometry):
        radials = sweep["radials"]
        number = sweep["elevation_number"]
        first, last = radials[0], radials[-1]
        began = instant(first["julian_date"], first["collection_time"])
        ended = instant(last["julian_date"], last["collection_time"])
        locator = {
            "kind": "radar",
            "ldm_record": first["ldm_record"],
            "message": first["message"],
            "elevation_number": number,
            "frame_sha256": self._frame_sha256,
        }
        moments, flags = [], []
        padded = False
        for block in first["moments"]:
            name = block["name"]
            padded = padded or name != name.strip()
            moment, moment_flags = self._moment(name, radials, volume, number, locator)
            moments.append(moment)
            flags += moment_flags
        flags += _radial_flags(radials)
        angles = {r["elevation_angle"] for r in radials}
        patterns = {r["vol"]["vcp"] for r in radials}
        contract = RadarSweep(
            contract="radar-sweep/1",
            product_class="observation",
            product_version=ProductVersion(version=volume.document["volume_header"]["tape"]),
            time=TimeInputs(
                source_time_system=TimeSystem(
                    name="GMT",
                    stated_by="source",
                    basis=(
                        f"{ICD} Table XVII-A: Collection Time is milliseconds past midnight "
                        "GMT, with the Modified Julian Date (1 = 1970-01-01)"
                    ),
                )
            ),
            locator=RadarLocator(**locator),
            quality_flags=flags,
            site_id=icao,
            elevation_number=number,
            elevation_angle=(
                Measurement(value=angles.pop(), unit="deg", unit_namespace=f"{ICD} Table XVII-A")
                if len(angles) == 1
                else None
            ),
            radial_count=len(radials),
            coverage_pattern=(
                CodedValue(
                    code=str(patterns.pop()),
                    namespace=f"{ICD} Table XVII-E, Volume Coverage Pattern Number",
                )
                if len(patterns) == 1
                else None
            ),
            moments=moments,
        )
        transformations = [T_VOLUME_INSTANT, T_COLLECTION_INSTANT, T_SCALED, T_GATES]
        if padded:
            transformations.append(T_NAME)
        external = f"{icao}/{times.render(start)}/elevation {number}"
        return observation_event(
            source=stamp.model_copy(
                update={"record_index": first["ldm_record"], "transformations": transformations}
            ),
            source_ids=[SourceId(system=SYSTEM, external_id=external)],
            observation=contract,
            observed_at=ended,
            received_at=self.now(),
            validity=TemporalValidity(effective=Period(start=began, end=ended)),
            related_entities=[site_id],
            geometry=geometry,
            quality=Quality(uncertainty={"collection_time_accuracy_s": 2.0}),
            residual=Residual(namespace=self.metadata.format.name, data=sweep),
        )

    def _moment(self, name, radials, volume, number, locator):
        """One moment of a sweep: its block, its values by reference and its quality flags."""
        label = name.strip()
        blocks = [next(m for m in r["moments"] if m["name"] == name) for r in radials]
        stats = [volume.stats[(number, r["azimuth_number"])][name] for r in radials]
        first = blocks[0]
        word = first["word_size"]
        scales = {b["scale"] for b in blocks}
        offsets = {b["offset"] for b in blocks}
        lows = [
            (s.min_code - b["offset"]) / b["scale"]
            for s, b in zip(stats, blocks)
            if s.min_code is not None
        ]
        highs = [
            (s.max_code - b["offset"]) / b["scale"]
            for s, b in zip(stats, blocks)
            if s.max_code is not None
        ]
        count = len(radials) * first["gates"]
        measured = sum(s.data_count for s in stats)
        coded_names = CODED.get(name, _NOTE_21)
        values = ValuesByReference(
            mode="reference",
            locator=RadarLocator(**locator, moment=label),
            shape=[len(radials), first["gates"]],
            dtype=f"Integer*{word // 8}",
            encoding=(
                f"{ICD} Table XVII-B: each radial's {first['gates']} gate words of {word} bits in "
                "its data moment block, inside the volume's bzip2 LDM records; "
                "F = (N - OFFSET) / SCALE with the block's own scale and offset (note 15, 20); "
                f"N below {DATA_BEGINS.get(name, 2)} is a coded value, not a measurement; the "
                "summary's min and max are F in the moment's unit and missing_count counts the "
                "coded gates"
            ),
            scale=scales.pop() if len(scales) == 1 else None,
            offset=offsets.pop() if len(offsets) == 1 else None,
            summary=ArraySummary(
                count=count,
                missing_count=count - measured,
                min=min(lows) if lows else None,
                max=max(highs) if highs else None,
            ),
        )
        moment = RadarMoment(
            name=label,
            namespace=f"{ICD} Table XVII-I",
            unit=UnitRef(unit=UNITS[name], unit_namespace=f"{ICD} Table XVII-I"),
            gate_count=first["gates"],
            first_gate_range=Measurement(
                value=first["first_gate_range"] / 1000,
                unit="km",
                unit_namespace=f"{ICD} Table XVII-B",
            ),
            gate_interval=Measurement(
                value=first["gate_interval"] / 1000,
                unit="km",
                unit_namespace=f"{ICD} Table XVII-B",
            ),
            values=values,
        )
        note = "note 30" if name in CODED else "note 21"
        flags = [
            QualityFlag(
                name=flag,
                value=sum(s.coded.get(code, 0) for s in stats for code in codes),
                namespace=f"{ICD} Table XVII-I {note}",
                applies_to=label,
            )
            for flag, codes in coded_names
        ]
        pairs = [(r["azimuth_number"], b) for r, b in zip(radials, blocks)]
        flags += _stated(pairs, "tover_db", lambda b: b["tover"], 10, f"{ICD} Table XVII-B", label)
        flags += _stated(
            pairs, "snr_threshold_db", lambda b: b["snr_threshold"], 8, f"{ICD} Table XVII-B", label
        )
        flags += _stated(
            pairs, "control_flags", lambda b: b["control_flags"], None, f"{ICD} Table XVII-B", label
        )
        return moment, flags


def _stated(pairs, flag, read, divisor, namespace, subject=None) -> list[QualityFlag]:
    """One flag for a value every radial states alike, else one per radial, in file order.

    `read` takes the raw value; `divisor` scales an integer to its unit (None keeps it)."""
    raw = [(azimuth, read(item)) for azimuth, item in pairs]

    def value(v):
        return v / divisor if divisor is not None else v

    if all(v == raw[0][1] and type(v) is type(raw[0][1]) for _, v in raw):
        return [
            QualityFlag(
                name=flag,
                value=value(raw[0][1]),
                namespace=namespace,
                applies_to=subject or "sweep",
            )
        ]
    prefix = f"{subject} " if subject else ""
    return [
        QualityFlag(
            name=flag, value=value(v), namespace=namespace, applies_to=f"{prefix}radial {azimuth}"
        )
        for azimuth, v in raw
    ]


#: The radial-level flags: (flag name, block, key, divisor, table).
_RADIAL_FLAGS = (
    ("radial_status", None, "radial_status", None, "Table III-C"),
    ("spot_blanking", None, "spot_blanking", None, "Table XVII-A"),
    ("vol_dbz0_db", "vol", "dbz0", None, "Table XVII-E"),
    ("horizontal_tx_power_kw", "vol", "horizontal_tx_power", None, "Table XVII-E"),
    ("vertical_tx_power_kw", "vol", "vertical_tx_power", None, "Table XVII-E"),
    ("system_zdr_db", "vol", "system_zdr", None, "Table XVII-E"),
    ("initial_system_phidp_deg", "vol", "initial_system_phidp", None, "Table XVII-E"),
    ("vcp_number", "vol", "vcp", None, "Table XVII-E"),
    ("processing_status", "vol", "processing_status", None, "Table XVII-E"),
    ("zdr_bias_estimate_raw", "vol", "zdr_bias", None, "Table XVII-E"),
    ("atmospheric_attenuation_db_per_km", "elv", "atmospheric_attenuation", 1000, "Table XVII-F"),
    ("elv_dbz0_db", "elv", "dbz0", None, "Table XVII-F"),
    ("unambiguous_range_km", "rad", "unambiguous_range", 10, "Table XVII-H"),
    ("noise_level_h_dbm", "rad", "noise_level_h", None, "Table XVII-H"),
    ("noise_level_v_dbm", "rad", "noise_level_v", None, "Table XVII-H"),
    ("nyquist_velocity_mps", "rad", "nyquist_velocity", 100, "Table XVII-H"),
    ("radial_flags", "rad", "radial_flags", None, "Table XVII-H"),
    ("calibration_dbz0_h_dbz", "rad", "calibration_h", None, "Table XVII-H"),
    ("calibration_dbz0_v_dbz", "rad", "calibration_v", None, "Table XVII-H"),
)


def _radial_flags(radials: list[dict]) -> list[QualityFlag]:
    bad = sum(1 for r in radials if r["radial_status"] & BAD_DATA)
    flags = [
        QualityFlag(
            name="bad_data_radial_count",
            value=bad,
            namespace=f"{ICD} Table III-C",
            applies_to="sweep",
        )
    ]
    for flag, block, key, divisor, table in _RADIAL_FLAGS:
        pairs = [(r["azimuth_number"], r[block] if block else r) for r in radials]
        flags += _stated(pairs, flag, lambda item, key=key: item[key], divisor, f"{ICD} {table}")
    return flags
