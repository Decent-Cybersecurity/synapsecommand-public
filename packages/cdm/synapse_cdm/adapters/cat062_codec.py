"""The CAT062 wire codec: octets to numbers and back, the FSPEC, and nothing else.

WHY THIS IS ITS OWN MODULE, AND WHY IT SHARES NO CODE WITH THE OTHER TWO
------------------------------------------------------------------------
The first reason is the one `cat048_codec.py` gives and it is unchanged: a byte-aligned binary
format with scaled numeric fields is a layer where a plausible-looking wrong answer costs nautical
miles rather than an exception, so it gets its own module with a test per form against
hand-computed byte patterns, and the item logic in `asterix_cat062.py` sits on top and never
touches a byte.

The second reason is arithmetical and it is stronger here than for either sibling. **Three parts,
three FSPEC ceilings, and none of them is a multiple of another.** Part 4 §5.3.1 numbers 28 FRNs
and interleaves four `FX` rows, so four groups of seven plus four FX bits is 32 bits and the
maximum is four octets. Part 2b §5.3 Table 3 numbers fourteen and interleaves two, so the maximum
is two. Part 9 §5.3 Table 1 numbers **thirty-five** and interleaves **five**, so the maximum is
**five**. Importing `cat048_codec.read_fspec` would give this category a four-octet ceiling and
refuse every record whose FSPEC reaches FRN 29 or above — which is every record carrying a
Reserved Expansion Field or a Special Purpose Field, since those are FRNs 34 and 35. The refusal
would quote 28 FRNs at a reader looking at a legal record.

The third reason has no analogue in the other two modules and is why the form table below is four
times the size of either sibling's. **Part 9 states more scaled quantities than the rest of this
repository's ASTERIX coverage combined**, at LSBs that are nearly-but-not-quite shared: 180/2^25
in I062/105 and 180/2^23 in I062/380 SF#22, 6.25 ft in I062/130 and 25 ft in I062/340 SF#3 and
1/4 FL in three other places, 0.25 m/s for velocity and 0.25 m/s^2 for acceleration and 1/4 s for
forty-one different ages. A shared table would make every one of those a candidate for the wrong
neighbour, and the failure mode is a position off by a factor of four rather than an exception.

NO `struct` FORMAT SHORTCUTS
---------------------------
Every integer is assembled with `int.from_bytes(..., "big")` and emitted with
`int.to_bytes(..., "big")`, for the reason `cat048_codec.py` gives: `struct` with a native-order
format is silently wrong on the wrong machine and `struct` with an explicit `>` is one typo from
being the native one. ASTERIX is big-endian throughout and the way to honour that is to say
`"big"` at every call site.

THE SNAP DISCIPLINE, INHERITED AS WRITTEN
-----------------------------------------
`snap(form, value)` returns the nearest value the field can carry and **refuses** a value outside
the field's range, naming the value and the range. Never a clamp to the boundary, never a mask to
the field width, never a wrap. Quantising INSIDE the range is the format's own resolution and is
not a loss the translator introduced; moving a value INTO range is a fabrication.

WHICH BOUND IS THE BOUND, AND THERE ARE THREE ANSWERS IN THIS DOCUMENT
----------------------------------------------------------------------
The rule is FORMAT_COVERAGE.md's and is applied per form rather than per module, because Part 9
does all three things:

1. **The document prints a range and the field is wider.** The DOCUMENT'S range is the bound and a
   pattern outside it is refused at the item level. Twenty-two forms below are in this class —
   `latitude_105`, `geometric_altitude`, `barometric_altitude`, `measured_flight_level`,
   `selected_altitude`, `tid_altitude`, `roll_angle`, `rate_of_turn`, `true_airspeed`,
   `indicated_airspeed`, `mach_number`, `wind_speed`, `wind_direction`, `temperature`,
   `cleared_flight_level`, `measured_mode_c` and the rest.
2. **The document prints a figure the field cannot carry.** The WIDTH is the bound and the printed
   figure is recorded beside it, because a bound the encoder cannot honour is not a bound. Two
   forms: `rho` (§5.2.23 prints "Maximum value = 256 NM" and sixteen bits at 1/256 NM reach
   255.996 093 75) and `covariance` (§5.2.26 SF#2 NOTE 2 prints 16.383 km and the field reaches
   16 383.5 m). This is `cat034_codec.py`'s `rho` disposition and `cat048_codec.py`'s `cartesian`
   disposition, reached a third and fourth time.
3. **The document prints no range at all.** The WIDTH is the bound and any narrower bound is
   applied one level up, where the reasoning that produces it can be written beside the refusal.
   `tod` is the important one and is the subject of the next paragraph.

THE RANGE THAT IS NOT STATED, FOR THE SECOND TIME IN THIS REPOSITORY
---------------------------------------------------------------------
`tod` — I062/070 Time Of Track Information — is three octets at 1/128 s, the same width and the
same LSB as CAT048's I048/140 and CAT034's I034/030. **CAT048 §5.2.17 prints a normative structure
block reading "Acceptable Range of values: 0<= Time-of-Day<=24 hrs"; CAT034 §5.2.4 prints no range
at all; CAT062 §5.2.5 prints no range either.** So this module does what `cat034_codec.py` does and
NOT what `cat048_codec.py` does: `FORMS` records the field width — 131 071.992 187 5 s — as the
bound, because that is what the document supports, and `SECONDS_PER_DAY` is exported for
`asterix_cat062.py` to apply the §5.2.5 Definition-and-NOTE-2 bound at the ITEM level. The
consequence is a boundary one value tighter than Part 4's: Part 4's inclusive inequality accepts
86 400 s and Part 9's Definition ("elapsed time since last midnight") plus NOTE 2 ("reset to zero
at every midnight") makes 86 400 s unreachable.

A SECOND TIME-OF-DAY-SHAPED FIELD, AT A DIFFERENT LSB
------------------------------------------------------
`tov` — I062/380 Subfield #9's Time Over Point — is 24 bits at **1 s**, and NOTE 5 says it "is
defined as the absolute time from midnight". So the category carries two absolute times of day with
different resolutions and one of them is conditional on a flag in the same record (NOTE 6: "TOV is
meaningful only if TOA is set to 0"). Both are day-bounded at the item level and neither is bounded
here, for the same reason.

NO GEODESY, AND THAT IS A DELIBERATE ABSENCE WITH TWO CAUSES
-------------------------------------------------------------
`cat048_codec.py` carries Vincenty because CAT048 states a target's position as range and azimuth
from a station and something has to turn that into a coordinate. **Nothing in this module converts
anything into a coordinate**, and the two items that look as though they should are declined for
different reasons FORMAT_COVERAGE.md's settlement 6 argues in full: I062/105 is already WGS-84 and
needs scaling and no geodesy, while I062/100's Cartesian pair needs a reference point that lives in
another CATEGORY and a projection this document names only by example. An imported ellipsoid here
would be arithmetic nothing calls, which is worse than absent: it would read as a capability the
adapter has.

ONE PIECE OF ARITHMETIC THAT IS NOT A SCALING, AND IT IS HERE RATHER THAN IN THE ADAPTER
-----------------------------------------------------------------------------------------
`degrees_to_metres` turns I062/500 Subfield #3's two angular standard-deviation components into
one scalar for `Position.accuracy_m`. It is the only canonical value in this row set computed from
more than one wire field, it is declared in the adapter's `TRANSFORMS`, and it lives here because
it is arithmetic over scaled numbers and this is the module that owns those. The constant, the
independence assumption and the existence of a Cartesian-frame covariance in Subfield #2 are all
stated at the function.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------------- refusals


class CodecError(ValueError):
    """A value or byte pattern this codec refuses. Every message quotes what and why."""


# --------------------------------------------------------------------------- the FSPEC
#
# §5.3 Table 1. Five groups of seven FRNs, each followed by an `FX` row. The fifth group's FX has
# no FRN 36 behind it, and it is a refusal for the reason CAT048's fourth-group FX and CAT034's
# second-group FX are: a set bit names nothing that can be decoded and nothing whose length can be
# guessed.

#: FRNs per FSPEC octet, from Table 1's own interleaving of the FX rows.
FSPEC_GROUPS = 7

#: 35 defined slots + 5 FX bits = 40 bits = 5 octets. Derived from Table 1, NOT from Part 4 and NOT
#: from Part 2b — see the module docstring for what importing either would cost.
MAX_FSPEC_OCTETS = 5

#: The highest FRN Table 1 lists. FRN 36 and above do not exist.
MAX_FRN = 35

#: Bit 1 of an FSPEC octet.
FX = 0x01

#: The FRNs Table 1 marks `- Spare -`. A set bit for one of these is a refusal and it is a
#: DIFFERENT refusal from a set bit above `MAX_FRN`: above 35 the bit names nothing the UAP has
#: ever defined, while at 2 it names a slot the UAP defines AS EMPTY and whose NOTE says why —
#: "The Field Reference Number #2 is kept free in order to prevent a full incompatibility with
#: previous releases of ASTERIX Cat. 062 already implemented." So a set FRN 2 may well mean
#: something to a pre-0.25 encoder, which is exactly why it cannot be guessed at here.
#:
#: FRNs 29 to 33 are five consecutive Spare rows with NO note. The document does not say why RE and
#: SP sit at 34 and 35 rather than at 29 and 30. FORMAT_COVERAGE.md ambiguity 4.
SPARE_FRNS = frozenset({2, 29, 30, 31, 32, 33})

#: The reason each Spare FRN is spare, for the refusal message. A refusal that says "FRN 2 is
#: spare" and stops has told the reader less than the document does.
SPARE_FRN_REASON: dict[int, str] = {
    2: ("Table 1's own NOTE: 'The Field Reference Number #2 is kept free in order to prevent a "
        "full incompatibility with previous releases of ASTERIX Cat. 062 already implemented.' "
        "The change record says what happened — edition 0.25 deleted I062/000 and editions 0.26 "
        "and 0.27 shuffled I062/100/101 and I062/105/106 — so this is a hole left by a deletion "
        "and an encoder written against a pre-0.25 edition may mean something by it"),
}
_SPARE_FRN_UNEXPLAINED = (
    "Table 1 marks it '- Spare -' and says nothing else about it. FRNs 29 to 33 are five "
    "consecutive Spare rows with no note, and the document does not explain why the Reserved "
    "Expansion Field and the Special Purpose Field sit at 34 and 35 rather than at 29 and 30"
)


def spare_frn_reason(frn: int) -> str:
    """Why this FRN is spare, in the document's own terms where it gives them."""
    return SPARE_FRN_REASON.get(frn, _SPARE_FRN_UNEXPLAINED)


def read_fspec(data: bytes, offset: int) -> tuple[list[int], bytes, int]:
    """The set FRNs, the octets verbatim, and the offset of the first item.

    The octets are returned so the caller can park them: §4.7 says only that "items shall always
    be transmitted in a Record with the corresponding FSPEC bits set to one", which does not
    forbid a longer FSPEC than the highest set FRN needs, and the round trip is byte-exact only
    if what we emit is what we read.

    A Spare FRN is NOT filtered out here. The caller has to see it, because refusing it is an item
    -level decision that wants the FRN's own reason in the message — see `spare_frn_reason`.
    """
    start = offset
    frns: list[int] = []
    while True:
        if offset >= len(data):
            raise CodecError(
                f"FSPEC starting at octet {start} runs past the end of the block "
                f"({len(data)} octets): an FSPEC octet has its FX bit set and no octet follows"
            )
        octet = data[offset]
        base = (offset - start) * FSPEC_GROUPS
        for bit in range(7, 0, -1):
            if octet & (1 << bit):
                frns.append(base + (8 - bit))
        offset += 1
        if not octet & FX:
            break
        if offset - start >= MAX_FSPEC_OCTETS:
            raise CodecError(
                f"FSPEC octet {MAX_FSPEC_OCTETS} at offset {offset - 1} "
                f"(0x{octet:02X}) sets its FX bit, but the category 062 UAP defines "
                f"{MAX_FRN} slots in exactly {MAX_FSPEC_OCTETS} octets and there is no FRN "
                f"{MAX_FRN + 1}. A sixth octet names nothing that can be decoded, so it cannot "
                "be skipped and guessing a length would desynchronise the record"
            )
    return frns, data[start:offset], offset


def write_fspec(frns: list[int]) -> bytes:
    """The shortest FSPEC covering the highest FRN in `frns`.

    Used only when building a record from scratch. Egress of an INGESTED record re-emits the
    parked octets instead, because a longer-than-necessary FSPEC is legal and re-deriving one
    would silently rewrite it.
    """
    if not frns:
        raise CodecError("an ASTERIX record with no items has no FSPEC to write")
    bad = [f for f in frns if not 1 <= f <= MAX_FRN]
    if bad:
        raise CodecError(
            f"FRN(s) {bad} are outside the category 062 UAP's range 1..{MAX_FRN}"
        )
    spare = sorted(f for f in frns if f in SPARE_FRNS)
    if spare:
        raise CodecError(
            f"FRN(s) {spare} are marked '- Spare -' in Table 1, so there is no item to encode "
            "for them. Writing a presence bit for a spare slot would announce content the "
            "record does not carry"
        )
    octets = bytearray((max(frns) - 1) // FSPEC_GROUPS + 1)
    for frn in frns:
        index = (frn - 1) // FSPEC_GROUPS
        bit = 8 - ((frn - 1) % FSPEC_GROUPS + 1)
        octets[index] |= 1 << bit
    for index in range(len(octets) - 1):
        octets[index] |= FX
    return bytes(octets)


# ------------------------------------------------------------------- integers, big-endian


def read_unsigned(data: bytes, offset: int, width: int) -> int:
    _require(data, offset, width)
    return int.from_bytes(data[offset:offset + width], "big")


def write_unsigned(value: int, width: int) -> bytes:
    limit = 1 << (8 * width)
    if not 0 <= value < limit:
        raise CodecError(f"unsigned {8 * width}-bit value {value} is outside 0..{limit - 1}")
    return int(value).to_bytes(width, "big")


def twos_from_raw(raw: int, bits: int) -> int:
    """A `bits`-wide two's-complement field's signed value, from its unsigned bit pattern."""
    sign = 1 << (bits - 1)
    return raw - (1 << bits) if raw & sign else raw


def twos_to_raw(value: int, bits: int) -> int:
    """The unsigned bit pattern for a signed value. Refuses rather than wrapping."""
    low, high = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if not low <= value <= high:
        raise CodecError(
            f"two's-complement {bits}-bit value {value} is outside {low}..{high}. Refusing "
            "rather than wrapping — a wrap changes the sign and leaves every length check "
            "passing"
        )
    return value & ((1 << bits) - 1)


def _require(data: bytes, offset: int, width: int) -> None:
    if offset < 0 or offset + width > len(data):
        raise CodecError(
            f"reading {width} octet(s) at offset {offset} runs past the end of a "
            f"{len(data)}-octet buffer"
        )


def bits(value: int, high: int, low: int) -> int:
    """Bits `high`..`low` of `value`, numbered as the document numbers them (1 = LSB)."""
    return (value >> (low - 1)) & ((1 << (high - low + 1)) - 1)


# ------------------------------------------------------------------------ scaled forms
#
# Every entry: (bits, signed, lsb, low, high, unit, locus). `low`/`high` are the bounds the module
# docstring's three-way rule selects, and every one of the three cases occurs. Where the entry uses
# the WIDTH against a printed figure, the comment says so and quotes the figure.

_LSB_1_128 = 1.0 / 128.0
_LSB_1_256 = 1.0 / 256.0
_LSB_QUARTER = 0.25
_LSB_ANGLE_16 = 360.0 / (1 << 16)
_LSB_ANGLE_7 = 360.0 / (1 << 7)
#: §5.2.8: "(LSB) = 180/2^25 degrees". The finest coordinate quantum in this repository.
_LSB_WGS84_25 = 180.0 / (1 << 25)
#: §5.2.24 SF#22: "LSB = 180/2^23 degrees = 2.145767 * 10-05 degrees".
_LSB_WGS84_23 = 180.0 / (1 << 23)
#: §5.2.24 SF#4 and SF#18: "2-14 NM/s".
_LSB_NM_PER_S = 2.0 ** -14

#: Exactly 1 NM in metres, ICAO/§3.2 ("NM Nautical Mile (1852 metres)").
METRES_PER_NM = 1852.0

#: Seconds in a day. NOT a bound in `FORMS` — §5.2.5 states no acceptable range, so this is the
#: figure `asterix_cat062.py` derives its refusal from, out of the Definition ("elapsed time since
#: last midnight") and NOTE 2 ("The time is reset to zero at every midnight").
SECONDS_PER_DAY = 86400

#: §5.2.8's own words about the coordinate LSB, kept verbatim because the adapter parks it and the
#: row set turns on the difference between a QUANTISATION STEP and a measurement accuracy.
WGS84_25_QUANTISATION_NOTE = "The LSB provides a resolution at least better than 0.6m"

#: §5.2.24 SF#22's equivalent, at a coarser LSB, for the aircraft-reported position.
WGS84_23_QUANTISATION_NOTE = "This corresponds to a resolution of at least 2.4 meters"

FORMS: dict[str, tuple[int, bool, float, float, float, str, str]] = {
    # I062/070. THE BOUND IS THE FIELD WIDTH, because §5.2.5 states no range. See the docstring.
    "tod": (24, False, _LSB_1_128, 0.0, 16777215 * _LSB_1_128, "s", "§5.2.5"),

    # I062/105 bits-64/33 and bits-32/1. THE BOUND IS THE STATED RANGE for latitude — "Range -90
    # <= latitude <= 90 deg" — and thirty-two bits at 180/2^25 reach +/-180. Longitude's stated
    # range and the field's own extremes agree exactly, so neither had to be preferred.
    "latitude_105": (32, True, _LSB_WGS84_25, -90.0, 90.0, "deg", "§5.2.8"),
    "longitude_105": (32, True, _LSB_WGS84_25, -180.0, 2147483647 * _LSB_WGS84_25, "deg",
                      "§5.2.8"),

    # I062/100 bits-48/25 and bits-24/1. §5.2.7, "a resolution of 0.5m, in two's complement form",
    # and NO range is printed, so the bound is the width. Parked as metres and never converted —
    # settlement 6.
    "cartesian_m": (24, True, 0.5, -8388608 * 0.5, 8388607 * 0.5, "m", "§5.2.7"),

    # I062/185. §5.2.14, "-8192m/s <= Vx <= 8191.75m/s"; the field's own extremes are exactly
    # that, so the stated range and the width agree.
    "velocity_mps": (16, True, _LSB_QUARTER, -8192.0, 8191.75, "m/s", "§5.2.14"),

    # I062/210. §5.2.16 prints no range; NOTE 2 says "Maximum value means maximum value or above",
    # which is a reading of the maximum and not a bound. The width is the bound.
    "acceleration_mps2": (8, True, _LSB_QUARTER, -32.0, 31.75, "m/s²", "§5.2.16"),

    # I062/130. THE BOUND IS THE STATED RANGE: "Vmin = -1500 ft, Vmax = 150000 ft", and sixteen
    # bits at 6.25 ft reach +/-204800.
    "geometric_altitude": (16, True, 6.25, -1500.0, 150000.0, "ft", "§5.2.11"),

    # I062/135 bits-15/1. THE BOUND IS THE STATED RANGE: "-15 FL <= CTBA <= 1500 FL", and fifteen
    # bits at 1/4 FL reach -4096..4095.75.
    "barometric_altitude": (15, True, _LSB_QUARTER, -15.0, 1500.0, "FL", "§5.2.12"),

    # I062/136. THE BOUND IS THE STATED RANGE: "Vmin = -15 FL, Vmax = 1500 FL", and sixteen bits
    # at 1/4 FL reach -8192..8191.75.
    "measured_flight_level": (16, True, _LSB_QUARTER, -15.0, 1500.0, "FL", "§5.2.13"),

    # I062/220. §5.2.17 prints no range at all. The width is the bound.
    "rate_of_climb": (16, True, 6.25, -204800.0, 204793.75, "ft/min", "§5.2.17"),

    # I062/270 first part and second extent, bits 8/2 — SEVEN bits, because bit 1 is the FX.
    "target_length_m": (7, False, 1.0, 0.0, 127.0, "m", "§5.2.19"),
    # I062/270 first extent, bits 8/2. "(LSB) = 360 deg / 128 = approx. 2.81 deg" over seven bits,
    # so the LSB the document prints and the field's width agree: 128 = 2^7.
    "target_orientation": (7, False, _LSB_ANGLE_7, 0.0, 127 * _LSB_ANGLE_7, "deg", "§5.2.19"),

    # I062/290 SF#1..#4 and #6..#10, and I062/295 SF#1..#31. §5.2.20 and §5.2.21, "bit-1 (LSB) =
    # 1/4 s, Maximum value = 63.75s". The field's extremes and the printed maximum agree, and
    # NOTE 6's "Maximum value means maximum value or above" makes 63.75 a FLOOR the item level
    # flags rather than a bound this level narrows.
    "age_quarter_s": (8, False, _LSB_QUARTER, 0.0, 63.75, "s", "§5.2.20"),
    # I062/290 SF#5 ADS-C Age. TWO octets, "Max. value = 16383.75s (> 4 hours)". The one
    # non-uniform subfield in the item, and a decoder that read it as one octet would
    # desynchronise the record with no length error anywhere.
    "age_quarter_s_16": (16, False, _LSB_QUARTER, 0.0, 16383.75, "s", "§5.2.20"),

    # I062/340 SF#2 RHO. §5.2.23 prints "Maximum value = 256 NM" and sixteen bits at 1/256 NM
    # reach 255.996 093 75, so the printed figure is one LSB above anything the field can carry.
    # THE BOUND IS THE WIDTH — `cat034_codec`'s `rho` disposition and `cat048_codec`'s `cartesian`
    # disposition, applied unchanged: preferring the printed figure would make `snap(256.0)`
    # return a value with no representable raw, and a bound the encoder cannot honour is not a
    # bound.
    "rho": (16, False, _LSB_1_256, 0.0, 65535 * _LSB_1_256, "NM", "§5.2.23"),
    # I062/340 SF#2 THETA. §5.2.23, "360 deg / 2^16 = 0.0055 deg".
    "theta": (16, False, _LSB_ANGLE_16, 0.0, 65535 * _LSB_ANGLE_16, "deg", "§5.2.23"),
    # I062/340 SF#3. §5.2.23 prints no range and its NOTE says the reference level is the
    # contributing sensor's. The width is the bound.
    "measured_height": (16, True, 25.0, -819200.0, 819175.0, "ft", "§5.2.23"),
    # I062/340 SF#4 bits-14/1. THE BOUND IS THE STATED RANGE: "Vmin = -12 FL, Vmax = 1270 FL".
    "measured_mode_c": (14, True, _LSB_QUARTER, -12.0, 1270.0, "FL", "§5.2.23"),

    # I062/110 SF#3. §5.2.9, "Range -90 <= latitude <= 90 deg" at 180/2^23 over 24 bits, which
    # reach +/-180. The stated range is the bound; longitude's agrees with its width.
    "latitude_23": (24, True, _LSB_WGS84_23, -90.0, 90.0, "deg", "§5.2.9"),
    "longitude_23": (24, True, _LSB_WGS84_23, -180.0, 8388607 * _LSB_WGS84_23, "deg", "§5.2.9"),
    # I062/110 SF#4 bits-14/1. NOTE 1: "GA is coded as a 14-bit two's complement binary number
    # with an LSB of 25 ft IRRESPECTIVE OF THE SETTING OF RES", so `RES` selects the reporting
    # granularity and never the arithmetic — getting that backwards would scale every
    # 100-ft-granularity altitude by four. NOTE 2's "The minimum value of GA that can be reported
    # is -1000 ft" is a statement about the TRANSPONDER and not a range on the field, so the WIDTH
    # is the bound and the -1000 ft figure is parked as a floor at the item level. Refusing a
    # pattern below it would refuse wire data on the authority of a note about equipment.
    "gnss_altitude": (14, True, 25.0, -204800.0, 204775.0, "ft", "§5.2.9"),
    # I062/110 SF#6. §5.2.9, "coded as a twos complement number with an LSB of 1/128 s", no range.
    "time_offset": (8, True, _LSB_1_128, -128 * _LSB_1_128, 127 * _LSB_1_128, "s", "§5.2.9"),

    # I062/380 SF#3 and SF#17. §5.2.24, "360 deg / 2^16 = approx. 0.0055 deg".
    "heading_16": (16, False, _LSB_ANGLE_16, 0.0, 65535 * _LSB_ANGLE_16, "deg", "§5.2.24"),
    # I062/380 SF#4 bits-15/1, under IM = 0. "Air Speed = IAS, LSB (Bit-1) = 2-14 NM/s".
    "airspeed_nm_s": (15, False, _LSB_NM_PER_S, 0.0, 32767 * _LSB_NM_PER_S, "NM/s", "§5.2.24"),
    # I062/380 SF#4 bits-15/1, under IM = 1. "Air Speed = Mach, LSB (Bit-1) = 0.001".
    "airspeed_mach": (15, False, 0.001, 0.0, 32.767, "Mach", "§5.2.24"),
    # I062/380 SF#5. THE BOUND IS THE STATED RANGE: "0 <= True Air Speed <= 2046 knots".
    "true_airspeed": (16, False, 1.0, 0.0, 2046.0, "kt", "§5.2.24"),
    # I062/380 SF#6 and SF#7 bits-13/1. THE BOUND IS THE STATED RANGE: "-1300ft <= Altitude <=
    # 100000ft", and thirteen bits at 25 ft reach -102400..102375.
    "selected_altitude": (13, True, 25.0, -1300.0, 100000.0, "ft", "§5.2.24"),
    # I062/380 SF#9 bits-112/97. THE BOUND IS THE STATED RANGE: "-1500 ft <= altitude <= 150000
    # ft" at 10 ft over sixteen bits, which reach -327680..327670.
    "tid_altitude": (16, True, 10.0, -1500.0, 150000.0, "ft", "§5.2.24"),
    # I062/380 SF#9 bits-40/17. "TOV Time Over Point, LSB = 1 second", and NOTE 5 makes it "the
    # absolute time from midnight". No range printed; the width is the bound and the day bound is
    # applied at the item level, as `tod`'s is.
    "tov": (24, False, 1.0, 0.0, 16777215.0, "s", "§5.2.24"),
    # I062/380 SF#9 bits-16/1. "0 <= TTR <= 655.35 Nm" at 0.01 NM over sixteen bits, which reach
    # exactly that.
    "turn_radius": (16, False, 0.01, 0.0, 655.35, "NM", "§5.2.24"),
    # I062/380 SF#13 and SF#14. §5.2.24, 6.25 ft/min two's complement, no range printed.
    "vertical_rate": (16, True, 6.25, -204800.0, 204793.75, "ft/min", "§5.2.24"),
    # I062/380 SF#15. THE BOUND IS THE STATED RANGE: "-180 <= Roll Angle <= 180" at 0.01 degree
    # over sixteen bits, which reach -327.68..327.67.
    "roll_angle": (16, True, 0.01, -180.0, 180.0, "deg", "§5.2.24"),
    # I062/380 SF#16 bits-8/2 — SEVEN bits, because bit 1 is a spare. THE BOUND IS THE STATED
    # RANGE: "-15 deg/s <= Rate of Turn <= 15 deg/s" and seven bits at 1/4 deg/s reach -16..15.75.
    # NOTE 2's "Value 15 means 15 deg/s or above" makes the maximum a floor the item level flags.
    "rate_of_turn": (7, True, _LSB_QUARTER, -15.0, 15.0, "deg/s", "§5.2.24"),
    # I062/380 SF#18. "-2 NM/s <= Ground Speed < 2 NM/s" at 2^-14 NM/s over sixteen bits, whose
    # own extremes are exactly -2 and 1.999938964843750 — so the stated range and the width agree
    # and the strict upper inequality is the field's, not an extra rule.
    "ground_speed": (16, True, _LSB_NM_PER_S, -2.0, 32767 * _LSB_NM_PER_S, "NM/s", "§5.2.24"),
    # I062/380 SF#20. Four stated ranges, all narrower than their fields.
    "wind_speed": (16, False, 1.0, 0.0, 300.0, "kt", "§5.2.24"),
    # AND ITS LOW BOUND IS 1, NOT 0: "1 <= Wind Direction <= 360". So a zero is outside the stated
    # range and is refused rather than read as north — the one place in this category where zero is
    # excluded from an angle.
    "wind_direction": (16, False, 1.0, 1.0, 360.0, "deg", "§5.2.24"),
    "temperature": (16, True, _LSB_QUARTER, -100.0, 100.0, "°C", "§5.2.24"),
    "turbulence": (8, False, 1.0, 0.0, 15.0, "", "§5.2.24"),
    # I062/380 SF#26 and SF#27. Stated ranges, both narrower than their fields.
    "indicated_airspeed": (16, False, 1.0, 0.0, 1100.0, "kt", "§5.2.24"),
    "mach_number": (16, False, 0.008, 0.0, 4.096, "Mach", "§5.2.24"),
    # I062/380 SF#28 bits-12/1. "-0mb <= BPS <= 409.5 mb" at 0.1 mb over twelve bits, which reach
    # exactly 409.5. The printed '-0mb' is a typographic minus on a zero and is read as 0.
    "barometric_pressure": (12, False, 0.1, 0.0, 409.5, "mb", "§5.2.24"),

    # I062/390 SF#10. THE BOUND IS THE STATED RANGE: "Range: 0 <= CFL <= 1500FL" at 1/4 FL over
    # sixteen bits, which reach 16383.75.
    "cleared_flight_level": (16, False, _LSB_QUARTER, 0.0, 1500.0, "FL", "§5.2.25"),

    # I062/500. Eight subfields, and every one of them carries "Maximum value means maximum value
    # or above", so none of the printed figures is a range and every bound here is a width.
    "accuracy_position_m": (16, False, 0.5, 0.0, 65535 * 0.5, "m", "§5.2.26"),
    # SF#2, and it is the one SIGNED accuracy field: "XY Covariance Component in two's complement
    # form". NOTE 2 prints "The maximum value for the (unsigned) XY covariance component is 16.383
    # km" and sixteen bits at 0.5 m reach 16383.5, so the printed figure is the field's positive
    # extreme minus one LSB. THE BOUND IS THE WIDTH and the figure is recorded beside it.
    "accuracy_covariance_m": (16, True, 0.5, -16384.0, 16383.5, "m", "§5.2.26"),
    "accuracy_position_deg": (16, False, _LSB_WGS84_25, 0.0, 65535 * _LSB_WGS84_25, "deg",
                              "§5.2.26"),
    "accuracy_geometric_altitude": (8, False, 6.25, 0.0, 255 * 6.25, "ft", "§5.2.26"),
    "accuracy_barometric_altitude": (8, False, _LSB_QUARTER, 0.0, 63.75, "FL", "§5.2.26"),
    "accuracy_velocity_mps": (8, False, _LSB_QUARTER, 0.0, 63.75, "m/s", "§5.2.26"),
    "accuracy_acceleration_mps2": (8, False, _LSB_QUARTER, 0.0, 63.75, "m/s²", "§5.2.26"),
    "accuracy_rate_of_climb": (8, False, 6.25, 0.0, 255 * 6.25, "ft/min", "§5.2.26"),

    # I062/REF §2.5. The same shape as I062/185 and a DIFFERENT FRAME — its NOTE puts the y-axis
    # at the system reference point rather than at the target — so it is a separate form under a
    # separate name, and the adapter never converts it to speed and course.
    "ref_velocity_mps": (16, True, _LSB_QUARTER, -8192.0, 8191.75, "m/s", "Appendix A §2.5"),
}


def bounds(form: str) -> tuple[float, float, float]:
    """(low, high, lsb) for a form, as the standard's arithmetic gives them."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    _bits, _signed, lsb, low, high, _unit, _locus = FORMS[form]
    return low, high, lsb


def width(form: str) -> tuple[float, float]:
    """The bounds the FIELD's own width expresses, whatever `bounds()` returns.

    Exported because eighteen forms in this table use a narrower STATED range than their field
    can carry, and the adapter has to be able to say so in a refusal: "the item's own range
    excludes this and the field can express it" is a different sentence from "the field cannot
    express this", and a reader debugging a non-conformant encoder needs the first one.
    """
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    nbits, signed, lsb, *_rest = FORMS[form]
    if signed:
        return -(1 << (nbits - 1)) * lsb, ((1 << (nbits - 1)) - 1) * lsb
    return 0.0, ((1 << nbits) - 1) * lsb


def from_raw(form: str, raw: int) -> float:
    """The decoded value of a raw field, WITHOUT a range check.

    Reading is not the place to refuse: a raw pattern outside the stated range is what the wire
    said, and the item-level decoder is what decides whether that is a refusal (as it is for
    `latitude_105`) or a value to park with a flag. Deciding here would hide the distinction
    inside the codec.
    """
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    nbits, signed, lsb, *_rest = FORMS[form]
    value = twos_from_raw(raw, nbits) if signed else raw
    return value * lsb


def to_raw(form: str, value: float) -> int:
    """The raw field for a value already known to be in range. Callers snap first."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    nbits, signed, *_rest = FORMS[form]
    nearest = _nearest_raw(form, value)
    return twos_to_raw(nearest, nbits) if signed else nearest


def snap(form: str, value: float) -> float:
    """The nearest value this form can carry — and a REFUSAL if it is out of range.

    Two different things, kept apart deliberately, on `cat048_codec.snap`'s terms.

    QUANTISING inside the range is the FORMAT'S stated resolution, not a translator's loss:
    §5.2.8 states a coordinate in units of 180/2^25 degrees and a value between two units is not
    representable by the standard rather than by this code. The result is exactly representable
    and never more than half an LSB from the input.

    Moving a value INTO range is something else entirely. Clamping a latitude of 95 degrees to 90
    would put an aircraft somewhere real and report success; masking it to the field width would
    put it somewhere arbitrary. Both leave every length check passing. So a value outside the
    range is a `CodecError` quoting the value, the range and the LSB — and, where the range is
    narrower than the field, quoting that too, because "the item's own range excludes this" and
    "the field cannot express this" are different findings.
    """
    low, high, lsb = bounds(form)
    if not low <= value <= high:
        nbits, _signed, _lsb, _low, _high, unit, locus = FORMS[form]
        field_low, field_high = width(form)
        extra = ""
        if (field_low, field_high) != (low, high):
            extra = (f" The FIELD is {nbits} bits and reaches [{field_low!r}, {field_high!r}] "
                     f"{unit}, so this value is one the item's own range excludes rather than one "
                     "the field cannot express")
        raise CodecError(
            f"{form} cannot carry {value!r} {unit}: the range is [{low!r}, {high!r}] {unit} "
            f"with an LSB of {lsb!r} ({locus}).{extra} Quantising inside the range is the "
            "format's own resolution; moving a value INTO range is not, and neither clamping to "
            "the boundary nor masking to the field width would tell you the value was impossible"
        )
    nearest = _nearest_raw(form, value)
    return from_raw(form, twos_to_raw(nearest, FORMS[form][0]) if FORMS[form][1] else nearest)


def _nearest_raw(form: str, value: float) -> int:
    """The integer nearest to `value / lsb`. Callers check the range; this does not.

    Banker's rounding is deliberately NOT used: `round()` in Python rounds .5 to even, so two
    adjacent half-LSB values would snap in opposite directions and a fixture built on one would
    disagree with a fixture built on the other. Half-up on the magnitude is symmetric about zero,
    which is what a two's-complement field needs.
    """
    _bits, _signed, lsb, *_rest = FORMS[form]
    scaled = value / lsb
    nearest = math.floor(abs(scaled) + 0.5)
    return int(-nearest if scaled < 0 else nearest)


# --------------------------------------------------------- the one non-scaling arithmetic

#: Metres per degree of latitude, from ICAO's own nautical mile: 1 degree = 60 NM = 111 120 m.
#:
#: A SPHERICAL figure on an ellipsoidal datum, and that is a declared approximation rather than an
#: oversight. The true metres-per-degree of latitude varies from about 110 574 at the equator to
#: about 111 694 at the pole, so this constant is within 0.5 % everywhere — and the quantity it
#: scales is a STANDARD DEVIATION the source has already rounded to 180/2^25 degrees. Carrying a
#: Vincenty-grade figure into an uncertainty estimate would be precision the input does not have,
#: and `cat048_codec.py`'s ellipsoid is not imported here for the reason the module docstring
#: gives: an ellipsoid in this file would read as a geodesy capability this adapter does not have.
METRES_PER_DEGREE = 60.0 * METRES_PER_NM


def degrees_to_metres(latitude_deg_sigma: float, longitude_deg_sigma: float,
                      at_latitude_deg: float) -> float:
    """I062/500 Subfield #3's two angular components as one metric standard deviation.

    THE ONLY CANONICAL VALUE IN THIS ROW SET COMPUTED FROM MORE THAN ONE WIRE FIELD, and it is
    declared in `asterix_cat062.py`'s `TRANSFORMS` for exactly that reason.

    §5.2.26 Subfield #3 states "Estimated accuracy (i.e. standard deviation) of the calculated
    position of a target expressed in WGS-84" as a latitude component and a longitude component,
    each sixteen bits at 180/2^25 degrees. `Position.accuracy_m` is ONE scalar in metres, so two
    things have to happen and both are visible here rather than buried in the adapter.

    **The longitude component is scaled by cos(latitude).** A degree of longitude is a degree of
    latitude times the cosine of the latitude, and the latitude used is the one I062/105 states in
    the same record — never a default, and the adapter does not call this function at all when
    I062/105 is absent, because there would be nothing to take the cosine of.

    **The two are combined as sqrt(a^2 + b^2), which assumes independence, AND THE ASSUMPTION IS
    THE SPECIFICATION'S SILENCE rather than a modelling choice.** §5.2.26 states two component
    standard deviations and states a covariance in a SEPARATE subfield, Subfield #2 — in the
    CARTESIAN frame, which FORMAT_COVERAGE.md's settlement 6 declines to invert. So there is no
    stated WGS-84 covariance to use, and the alternatives are worse: taking the larger component
    would discard half the information, and taking their sum would overstate the uncertainty by up
    to 41 %. `attributes.accuracy_basis` carries this paragraph's substance into the object, so a
    consumer differentiating accuracies across sources can see what was assumed.
    """
    lat_m = latitude_deg_sigma * METRES_PER_DEGREE
    lon_m = longitude_deg_sigma * METRES_PER_DEGREE * math.cos(math.radians(at_latitude_deg))
    return math.hypot(lat_m, lon_m)
