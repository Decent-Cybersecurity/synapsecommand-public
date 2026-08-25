"""The CAT023 wire codec: octets to numbers and back, the FSPEC, and nothing else.

WHY THIS IS ITS OWN MODULE, AND WHY IT SHARES NO CODE WITH THE OTHER THREE
--------------------------------------------------------------------------
The first reason is the one `cat048_codec.py` gives and it is unchanged: a byte-aligned binary
format with scaled numeric fields is a layer where a plausible-looking wrong answer costs
nautical miles rather than an exception, so it gets its own module with a test per form against
hand-computed byte patterns, and the item logic in `asterix_cat023.py` sits on top and never
touches a byte.

The second reason is the one to read carefully, because **this is the pair where the temptation is
strongest and the trap is best hidden.** Part 16's UAP and Part 2b's UAP have **the same octet
count**: both number fourteen FRNs, both interleave two `FX` rows, and both therefore have a
two-octet FSPEC maximum. So importing `cat034_codec.read_fspec` would get the ceiling RIGHT — by
coincidence — and a reader comparing the two modules would find nothing wrong with the arithmetic.

What it would get wrong is everything else. Part 2b defines **twelve** items in its fourteen FRNs
and Part 16 defines **nine**, in a different order, at different lengths. FRN 3 is `I034/030` Time
of Day in one and `I023/015` Service Type and Identification in the other; FRN 4 is `I034/020`
Sector Number and `I023/070` Time of Day. So a codec that shared the FRN table would decode a
three-octet time of day where a one-octet service identification is, **and the record would still
tile**: `I023/070`'s three octets and `I023/015`'s one plus `I023/070`'s three differ by one
octet, which the next item's length rule absorbs. The result is a plausible wrong ground station
status with no length error anywhere in the record. The FSPEC constant being right is what makes
the rest of the mistake invisible.

Part 16 also has three SPARE FRNs — 10, 11 and 12 — where Part 2b has none, and Part 9 has six
with a NOTE explaining one of them. A set bit for one of those is a refusal here and a
recognisable item there.

NO `struct` FORMAT SHORTCUTS
---------------------------
Every integer is assembled with `int.from_bytes(..., "big")` and emitted with
`int.to_bytes(..., "big")`, for the reason `cat048_codec.py` gives: `struct` with a native-order
format is silently wrong on the wrong machine and `struct` with an explicit `>` is one typo from
being the native one.

THE SNAP DISCIPLINE, INHERITED AS WRITTEN
-----------------------------------------
`snap(form, value)` returns the nearest value the field can carry and **refuses** a value outside
the field's range, naming the value and the range. Never a clamp to the boundary, never a mask to
the field width, never a wrap.

THE RANGE THAT IS NOT STATED, FOR THE THIRD TIME IN THIS REPOSITORY
--------------------------------------------------------------------
`tod` — I023/070 Time of Day — is three octets at 1/128 s, the same width and the same LSB as
CAT048's I048/140, CAT034's I034/030 and CAT062's I062/070. **CAT048 §5.2.17 prints a normative
structure block reading "Acceptable Range of values: 0<= Time-of-Day<=24 hrs" and the other three
print no range at all.** So this module does what `cat034_codec.py` and `cat062_codec.py` do:
`FORMS` records the field width — 131 071.992 187 5 s — as the bound, because that is what the
document supports, and `SECONDS_PER_DAY` is exported for `asterix_cat023.py` to apply the §5.2.4
Definition-and-NOTE bound at the ITEM level. Three categories now share one disposition and one
differs, and the difference is a single boundary value.

THE THREE PERIODS, AND WHY THEY ARE THREE FORMS RATHER THAN ONE
----------------------------------------------------------------
`GSSP`, `SSRP` and `RP` are all "a reporting period" and no two of them are the same field.

* `GSSP` (I023/100 First Extension) and `SSRP` (I023/101 First Extension) are **seven** bits at
  1 s — bit 1 is the FX — with a stated range of `1 <= x <= 127s`. Seven bits reach exactly 127,
  so the top of the stated range and the top of the field agree; the BOTTOM does not, because the
  stated minimum is 1 and the field can express 0.
* `RP` (I023/101 octet 1) is **eight** bits at 0.5 s, and its zero is a NAMED MODE — "= 0: Data
  driven mode" — not a period of zero seconds.

So the low bound differs, the LSB differs, and the meaning of zero differs. A shared form would be
wrong for one of the three whichever way it was written, and `asterix_cat023.py` is where the
zero-handling is decided per field, because the reasoning is item-level and not arithmetic.

NO GEODESY, AND NOT EVEN A COORDINATE
--------------------------------------
`cat048_codec.py` carries Vincenty and `cat034_codec.py` explains why it does not. This module has
less than either: **Part 16 carries no position of any kind.** Nine items and not one coordinate.
`I023/200` is an operational range in nautical miles with no centre, and §4.4.1 asserts that a
SAC/SIC is dedicated and unambiguous per ground station without saying where any station is. So
there is nothing here to convert and nothing to convert it with, which is why `Position` is `None`
on every object the adapter emits and why `METRES_PER_NM` below is exported for prose rather than
for arithmetic.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------------- refusals


class CodecError(ValueError):
    """A value or byte pattern this codec refuses. Every message quotes what and why."""


# --------------------------------------------------------------------------- the FSPEC
#
# §5.3.1 Table 3. Two groups of seven FRNs, each followed by an explicit `FX | N/A. | Field
# Extension Indicator | N/A` row. The second group's FX has no FRN 15 behind it, and it is a
# refusal for the reason every other category's terminal FX is.

#: FRNs per FSPEC octet, from Table 3's own interleaving of the FX rows.
FSPEC_GROUPS = 7

#: 14 slots + 2 FX bits = 16 bits = 2 octets. Derived from Table 3, and NOT imported from
#: `cat034_codec` even though that module's constant has the same VALUE — see the module docstring
#: for what sharing the FRN table alongside it would cost.
MAX_FSPEC_OCTETS = 2

#: The highest FRN Table 3 lists. FRN 15 and above do not exist.
MAX_FRN = 14

#: Bit 1 of an FSPEC octet.
FX = 0x01

#: The FRNs Table 3 marks `- spare -`. Part 2b has none of these and Part 9 has six, one of which
#: carries a NOTE explaining it. **These three have no explanation at all**: the document does not
#: say why the Reserved Expansion Field and the Special Purpose Field sit at 13 and 14 rather than
#: at 10 and 11. FORMAT_COVERAGE.md ambiguity 4's neighbourhood.
SPARE_FRNS = frozenset({10, 11, 12})

SPARE_FRN_REASON = (
    "Table 3 marks it '- spare -' and says nothing else about it. FRNs 10, 11 and 12 are three "
    "consecutive spare rows with no note — unlike Part 9's FRN 2, which has one — and the document "
    "does not explain why the Reserved Expansion Field and the Special Purpose Field sit at 13 and "
    "14 rather than at 10 and 11"
)


def read_fspec(data: bytes, offset: int) -> tuple[list[int], bytes, int]:
    """The set FRNs, the octets verbatim, and the offset of the first item.

    The octets are returned so the caller can park them: §4.6.2 says only that "items shall always
    be transmitted in a Record with the corresponding FSPEC bits set to one", which does not forbid
    a longer FSPEC than the highest set FRN needs, and the round trip is byte-exact only if what we
    emit is what we read.

    A spare FRN is NOT filtered out here. The caller has to see it, because refusing it is an
    item-level decision that wants the document's own words in the message.
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
                f"(0x{octet:02X}) sets its FX bit, but the category 023 UAP defines "
                f"{MAX_FRN} slots in exactly {MAX_FSPEC_OCTETS} octets and there is no FRN "
                f"{MAX_FRN + 1}. A third octet names nothing that can be decoded, so it cannot be "
                "skipped and guessing a length would desynchronise the record"
            )
    return frns, data[start:offset], offset


def write_fspec(frns: list[int]) -> bytes:
    """The shortest FSPEC covering the highest FRN in `frns`.

    Used only when building a record from scratch. Egress of an INGESTED record re-emits the parked
    octets instead, because a longer-than-necessary FSPEC is legal and re-deriving one would
    silently rewrite it.
    """
    if not frns:
        raise CodecError("an ASTERIX record with no items has no FSPEC to write")
    bad = [f for f in frns if not 1 <= f <= MAX_FRN]
    if bad:
        raise CodecError(
            f"FRN(s) {bad} are outside the category 023 UAP's range 1..{MAX_FRN}"
        )
    spare = sorted(f for f in frns if f in SPARE_FRNS)
    if spare:
        raise CodecError(
            f"FRN(s) {spare} are marked '- spare -' in Table 3, so there is no item to encode for "
            "them. Writing a presence bit for a spare slot would announce content the record does "
            "not carry"
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
# Every entry: (bits, signed, lsb, low, high, unit, locus). NOTHING IN THIS CATEGORY IS SIGNED —
# nine items, four scaled fields, and not one two's-complement value among them, which is the
# opposite of Part 9 and worth stating because a reader arriving from that module will look for it.

_LSB_1_128 = 1.0 / 128.0

#: Exactly 1 NM in metres, ICAO/§3.2 ("NM Nautical Mile (1852 metres)"). Exported for the row set's
#: prose and used in no arithmetic: `I023/200` is a range with no centre, so there is nothing to
#: convert it into. See the module docstring's last paragraph.
METRES_PER_NM = 1852.0

#: Seconds in a day. NOT a bound in `FORMS` — §5.2.4 states no acceptable range, so this is the
#: figure `asterix_cat023.py` derives its refusal from, out of the Definition ("Absolute time
#: stamping expressed as UTC time") and the NOTE ("The time of day value is reset to zero each day
#: at midnight").
SECONDS_PER_DAY = 86400

FORMS: dict[str, tuple[int, bool, float, float, float, str, str]] = {
    # I023/070. THE BOUND IS THE FIELD WIDTH, because §5.2.4 states no range. See the docstring.
    "tod": (24, False, _LSB_1_128, 0.0, 16777215 * _LSB_1_128, "s", "§5.2.4"),

    # I023/100 First Extension, bits 8/2 — SEVEN bits, because bit 1 is the FX. THE BOUND IS THE
    # STATED RANGE, "Valid range: 1 <= GSSP <= 127s", and the interesting half is the BOTTOM: seven
    # bits reach exactly 127 so the top agrees, and the field can express 0 while the item cannot.
    "gssp": (7, False, 1.0, 1.0, 127.0, "s", "§5.2.5"),
    # I023/101 First Extension, bits 8/2. Identical shape and identical bounds, in a different item
    # for a different obligation (§4.5.1.2). A separate form because it is a separate field, and
    # sharing one would make the two indistinguishable in a refusal message.
    "ssrp": (7, False, 1.0, 1.0, 127.0, "s", "§5.2.6"),
    # I023/101 octet 1 — EIGHT bits at 0.5 s, and its zero is a NAMED MODE rather than a period.
    # The bound therefore INCLUDES zero, because zero is a legal encoding; what it is not is a
    # duration, and `asterix_cat023.py` is where that is honoured.
    "rp": (8, False, 0.5, 0.0, 127.5, "s", "§5.2.6"),

    # I023/200. §5.2.9, one octet at 1 NM, and no range is printed — its NOTE says only "Maximum
    # value indicates 'maximum value or above'", which is a reading of the maximum and not a bound.
    # The width is the bound and the at-or-above reading is applied at the item level.
    "operational_range": (8, False, 1.0, 0.0, 255.0, "NM", "§5.2.9"),
}


def bounds(form: str) -> tuple[float, float, float]:
    """(low, high, lsb) for a form, as the standard's arithmetic gives them."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    _bits, _signed, lsb, low, high, _unit, _locus = FORMS[form]
    return low, high, lsb


def width(form: str) -> tuple[float, float]:
    """The bounds the FIELD's own width expresses, whatever `bounds()` returns.

    Exported because `gssp` and `ssrp` use a narrower STATED range than their field can carry at
    the bottom, and the adapter has to be able to say so: "the item's own range excludes 0 and the
    field can express it" is a different sentence from "the field cannot express 0", and a reader
    debugging a non-conformant encoder needs the first one.
    """
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    nbits, _signed, lsb, *_rest = FORMS[form]
    return 0.0, ((1 << nbits) - 1) * lsb


def from_raw(form: str, raw: int) -> float:
    """The decoded value of a raw field, WITHOUT a range check.

    Reading is not the place to refuse: a raw pattern outside the stated range is what the wire
    said, and the item-level decoder is what decides whether that is a refusal (as it is for
    `gssp` and `ssrp` at zero) or a value to park with a flag.
    """
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    _bits, _signed, lsb, *_rest = FORMS[form]
    return raw * lsb


def to_raw(form: str, value: float) -> int:
    """The raw field for a value already known to be in range. Callers snap first."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    return _nearest_raw(form, value)


def snap(form: str, value: float) -> float:
    """The nearest value this form can carry — and a REFUSAL if it is out of range.

    Two different things, kept apart deliberately, on `cat048_codec.snap`'s terms. Quantising
    inside the range is the FORMAT'S stated resolution; moving a value INTO range is a fabrication
    that leaves every length check passing.
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
            f"{form} cannot carry {value!r} {unit}: the range is [{low!r}, {high!r}] {unit} with "
            f"an LSB of {lsb!r} ({locus}).{extra} Quantising inside the range is the format's own "
            "resolution; moving a value INTO range is not, and neither clamping to the boundary "
            "nor masking to the field width would tell you the value was impossible"
        )
    return from_raw(form, _nearest_raw(form, value))


def _nearest_raw(form: str, value: float) -> int:
    """The integer nearest to `value / lsb`. Callers check the range; this does not.

    Banker's rounding is deliberately NOT used, for the reason the sibling codecs give: `round()`
    in Python rounds .5 to even, so two adjacent half-LSB values would snap in opposite directions
    and a fixture built on one would disagree with a fixture built on the other. Nothing in this
    category is signed, so half-up on the magnitude and half-up are the same rule here — kept in
    the symmetric form anyway, because the four codecs are read against each other.
    """
    _bits, _signed, lsb, *_rest = FORMS[form]
    scaled = value / lsb
    nearest = math.floor(abs(scaled) + 0.5)
    return int(-nearest if scaled < 0 else nearest)
