"""The CAT034 wire codec: octets to numbers and back, the FSPEC, and nothing else.

WHY THIS IS ITS OWN MODULE, AND WHY IT SHARES NO CODE WITH `cat048_codec.py`
----------------------------------------------------------------------------
The first reason is the one `cat048_codec.py` gives and it is unchanged: a byte-aligned binary
format with scaled numeric fields is a layer where a plausible-looking wrong answer costs
nautical miles rather than an exception, so it gets its own module with a test per form against
hand-computed byte patterns, and the item logic in `asterix_cat034.py` sits on top and never
touches a byte.

The second reason is specific to this pair and is worth stating because the temptation here is
much stronger than it was between CAT021 and CAT048. Part 2b and Part 4 are two parts of ONE
specification, and their FSPEC mechanics look identical at a glance. **They are not the same
table.** CAT048 §5.3.1 numbers 28 FRNs and interleaves four `FX` rows, so four groups of seven
plus four FX bits is 32 bits and the maximum is four octets. CAT034 §5.3 Table 3 numbers
**fourteen** FRNs and interleaves **two** `FX` rows, so the maximum is **two**. Importing
`cat048_codec.read_fspec` would have given this category a four-octet ceiling and a refusal
message quoting the wrong FRN count — a refusal that misidentifies its own cause is a refusal
nobody can act on, which is the finding `_len_variable` records on the other side.

The scaled forms do not overlap either. The one shape the two parts genuinely share is the
1/128 s time of day, and even there the ranges differ — see THE RANGE THAT IS NOT STATED below.

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

THE RANGE THAT IS NOT STATED, AND IT IS THIS CATEGORY'S INTERESTING ONE
-----------------------------------------------------------------------
`tod` — I034/030 Time of Day — is three octets at 1/128 s, the same width and the same LSB as
CAT048's I048/140. **CAT048 §5.2.17 prints a normative structure block reading "Acceptable Range
of values: 0<= Time-of-Day<=24 hrs" and CAT034 §5.2.4 prints no range at all.** So the two items
are the same shape with different authority behind their bounds, and this module does NOT copy
the other one's figure into a table as though the document had stated it. `FORMS` records the
field width — 131 071.992 187 5 s — as the bound, because that is what the document supports, and
`SECONDS_PER_DAY` is exported for `asterix_cat034.py` to apply the §5.2.4 Definition-and-NOTE-1
bound at the ITEM level, where the reasoning that produces it can be written down beside the
refusal. FORMAT_COVERAGE.md ambiguity 9 carries the finding.

Two forms carry a range the document states and the field exceeds, and both bounds here are the
DOCUMENT'S rather than the width: `latitude`, where §5.2.12 says "Range: -90<= latitude<= 90
degrees" and twenty-four bits at 180/2^23 reach ±180; and `rho`, where §5.2.10 prints
"Max. Range = 256 NM" and sixteen bits at 1/256 NM reach 255.996 093 75 — the CAT048 `cartesian`
shape, recorded the same way.

NO GEODESY, AND THAT IS A DELIBERATE ABSENCE
--------------------------------------------
`cat048_codec.py` carries Vincenty because CAT048 states a target's position as range and azimuth
from a station and something has to turn that into a coordinate. **Nothing in this module
converts anything into a coordinate.** I034/120 is already WGS-84 latitude, longitude and height,
so it needs scaling and no geodesy; and I034/100's polar window is NEVER turned into a geometry —
see `asterix_cat034.py`'s settlement 7 for the ruling, which rests on Table 2 rather than on
effort. An imported ellipsoid in this file would be arithmetic nothing calls, which is worse than
absent: it would read as a capability the adapter has.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------------- refusals


class CodecError(ValueError):
    """A value or byte pattern this codec refuses. Every message quotes what and why."""


# --------------------------------------------------------------------------- the FSPEC
#
# §5.3 Table 3. Two groups of seven FRNs, each followed by an explicit `FX | N/A. | Field
# Extension Indicator | N/A.` row. The second group's FX has no FRN 15 behind it, and it is a
# refusal for the reason CAT048's fourth-group FX is: a set bit names nothing that can be
# decoded and nothing whose length can be guessed.

#: FRNs per FSPEC octet, from Table 3's own interleaving of the FX rows.
FSPEC_GROUPS = 7

#: 14 defined FRNs + 2 FX bits = 16 bits = 2 octets. Derived from Table 3, NOT from Part 1 and
#: NOT from Part 4 — see the module docstring for why importing the other one would be wrong.
MAX_FSPEC_OCTETS = 2

#: The highest FRN Table 3 defines. FRN 15 and above do not exist.
MAX_FRN = 14

#: Bit 1 of an FSPEC octet.
FX = 0x01


def read_fspec(data: bytes, offset: int) -> tuple[list[int], bytes, int]:
    """The set FRNs, the octets verbatim, and the offset of the first item.

    The octets are returned so the caller can park them: §4.7 says only that "items shall always
    be transmitted in a Record with the corresponding FSPEC bits set to one", which does not
    forbid a longer FSPEC than the highest set FRN needs, and the round trip is byte-exact only
    if what we emit is what we read.
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
                f"(0x{octet:02X}) sets its FX bit, but the category 034 UAP defines "
                f"{MAX_FRN} FRNs in exactly {MAX_FSPEC_OCTETS} octets and there is no FRN "
                f"{MAX_FRN + 1}. A third octet names nothing that can be decoded, so it cannot "
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
            f"FRN(s) {bad} are outside the category 034 UAP's range 1..{MAX_FRN}"
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


# ------------------------------------------------------------------------ scaled forms
#
# Every entry: (bits, signed, lsb, low, high, unit, locus). `low`/`high` are the DECODED bounds,
# computed from the standard's own stated LSB and width — except `rho` and `latitude`, whose
# bounds are the RANGES §5.2.10 and §5.2.12 state rather than the ones their widths express, and
# except `tod`, which is the reverse case and is the module docstring's subject: the width IS the
# bound here because §5.2.4 states no range, and the day bound is applied one level up.

_LSB_1_256 = 1.0 / 256.0
_LSB_1_128 = 1.0 / 128.0
_LSB_ANGLE_16 = 360.0 / (1 << 16)
_LSB_ANGLE_14 = 360.0 / (1 << 14)
_LSB_ANGLE_8 = 360.0 / (1 << 8)
#: §5.2.12: "Bit 25 (LSB) = 180/2^23 degrees = 2.145767*10-05 degrees".
_LSB_WGS84 = 180.0 / (1 << 23)

#: Exactly 1 NM in metres, ICAO/§3.2 ("NM Nautical Mile (1852 m)").
METRES_PER_NM = 1852.0

#: Seconds in a day. NOT a bound in `FORMS` — §5.2.4 states no acceptable range, so this is the
#: figure `asterix_cat034.py` derives its refusal from, out of the Definition ("a number of
#: 1/128 s elapsed since last midnight") and NOTE 1 ("reset to zero each day at midnight").
SECONDS_PER_DAY = 86400

#: §5.2.12's own words about the coordinate LSB, kept verbatim because the adapter parks it and
#: the row set turns on the difference between a QUANTISATION STEP and a measurement accuracy.
WGS84_QUANTISATION_NOTE = ("This corresponds to an accuracy of at least 2.3844 metres")

FORMS: dict[str, tuple[int, bool, float, float, float, str, str]] = {
    # I034/020. §5.2.3, "bit-1 (LSB) = 360/(2^8) = approx. 1.41".
    "sector": (8, False, _LSB_ANGLE_8, 0.0, 255 * _LSB_ANGLE_8, "deg", "§5.2.3"),
    # I034/030. THE BOUND IS THE FIELD WIDTH, because §5.2.4 states no range. See the docstring.
    "tod": (24, False, _LSB_1_128, 0.0, 16777215 * _LSB_1_128, "s", "§5.2.4"),
    # I034/041. §5.2.5, "bit-1 (LSB) = (2-7) s = 1/128 s". A PERIOD, whatever the heading says.
    "rotation_period": (16, False, _LSB_1_128, 0.0, 65535 * _LSB_1_128, "s", "§5.2.5"),
    # I034/090 octet 1. §5.2.9, "bit-9 (LSB) = 1/128 NM", two's complement per its NOTE.
    "range_error": (8, True, _LSB_1_128, -128 * _LSB_1_128, 127 * _LSB_1_128, "NM", "§5.2.9"),
    # I034/090 octet 2. §5.2.9, "bit-1 (LSB) = 360/(2^14) = approx. 0.022".
    "azimuth_error": (8, True, _LSB_ANGLE_14, -128 * _LSB_ANGLE_14, 127 * _LSB_ANGLE_14,
                      "deg", "§5.2.9"),
    # I034/100 RHO-START / RHO-END. §5.2.10 prints "Max. Range = 256 NM" TWICE and sixteen bits
    # at 1/256 NM reach 255.996 093 75, so the printed figure is one LSB above anything the field
    # can carry. THE BOUND IS THE WIDTH, which is `cat048_codec`'s `cartesian` disposition applied
    # unchanged: preferring the printed figure would make `snap(256.0)` return a value with no
    # representable raw, and a bound the encoder cannot honour is not a bound. Ambiguity 10.
    "rho": (16, False, _LSB_1_256, 0.0, 65535 * _LSB_1_256, "NM", "§5.2.10"),
    # I034/100 THETA-START / THETA-END. §5.2.10, "360/(2^16) = approx. 0.0055".
    "theta": (16, False, _LSB_ANGLE_16, 0.0, 65535 * _LSB_ANGLE_16, "deg", "§5.2.10"),
    # I034/120 bits-64/49. §5.2.12, "Signed Height ... Bit-49 (LSB) = 1 metre".
    "height": (16, True, 1.0, -32768.0, 32767.0, "m", "§5.2.12"),
    # I034/120 bits-48/25. THE BOUND IS THE STATED RANGE: "-90<= latitude<= 90 degrees", and
    # twenty-four bits at 180/2^23 reach ±180. A pattern outside it is refused at the item level.
    "latitude": (24, True, _LSB_WGS84, -90.0, 90.0, "deg", "§5.2.12"),
    # I034/120 bits-24/1. "-180 <= longitude<180"; the field's own extremes are exactly that,
    # so here the width and the stated range agree and neither had to be preferred.
    "longitude": (24, True, _LSB_WGS84, -180.0, 8388607 * _LSB_WGS84, "deg", "§5.2.12"),
}


def bounds(form: str) -> tuple[float, float, float]:
    """(low, high, lsb) for a form, as the standard's arithmetic gives them."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    bits, signed, lsb, low, high, _unit, _locus = FORMS[form]
    return low, high, lsb


def from_raw(form: str, raw: int) -> float:
    """The decoded value of a raw field, WITHOUT a range check.

    Reading is not the place to refuse: a raw pattern outside the stated range is what the wire
    said, and the item-level decoder is what decides whether that is a refusal (as it is for
    `latitude`) or a value to park with a flag. Deciding here would hide the distinction inside
    the codec.
    """
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    bits, signed, lsb, *_rest = FORMS[form]
    value = twos_from_raw(raw, bits) if signed else raw
    return value * lsb


def to_raw(form: str, value: float) -> int:
    """The raw field for a value already known to be in range. Callers snap first."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    bits, signed, *_rest = FORMS[form]
    nearest = _nearest_raw(form, value)
    return twos_to_raw(nearest, bits) if signed else nearest


def snap(form: str, value: float) -> float:
    """The nearest value this form can carry — and a REFUSAL if it is out of range.

    Two different things, kept apart deliberately, on `cat048_codec.snap`'s terms.

    QUANTISING inside the range is the FORMAT'S stated resolution, not a translator's loss:
    §5.2.12 states a coordinate in units of 180/2^23 degrees and a value between two units is not
    representable by the standard rather than by this code. The result is exactly representable
    and never more than half an LSB from the input.

    Moving a value INTO range is something else entirely. Clamping a latitude of 95 degrees to 90
    would put a radar station somewhere real and report success; masking it to the field width
    would put it somewhere arbitrary. Both leave every length check passing. So a value outside
    the range is a `CodecError` quoting the value, the range and the LSB.
    """
    low, high, lsb = bounds(form)
    if not low <= value <= high:
        _bits, _signed, _lsb, _low, _high, unit, locus = FORMS[form]
        raise CodecError(
            f"{form} cannot carry {value!r} {unit}: the field's range is "
            f"[{low!r}, {high!r}] {unit} with an LSB of {lsb!r} ({locus}). Quantising inside "
            "the range is the format's own resolution; moving a value INTO range is not, and "
            "neither clamping to the boundary nor masking to the field width would tell you "
            "the value was impossible"
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
    bits, signed, lsb, *_rest = FORMS[form]
    scaled = value / lsb
    nearest = math.floor(abs(scaled) + 0.5)
    return int(-nearest if scaled < 0 else nearest)
