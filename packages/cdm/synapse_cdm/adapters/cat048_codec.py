"""The CAT048 wire codec: octets to numbers and back, the FSPEC, and the geodesy.

WHY THIS IS ITS OWN MODULE, AND WHY IT SHARES NO CODE WITH `asterix_cat021.py`
------------------------------------------------------------------------------
Two reasons, and the second is a finding rather than a preference.

The first is the GMTIF one: a byte-aligned binary format with scaled numeric fields is a layer
where a plausible-looking wrong answer costs nautical miles rather than an exception, so it gets
its own module with a test per form against hand-computed byte patterns, and the item logic in
`asterix_cat048.py` sits on top and never touches a byte.

The second is `FORMAT_COVERAGE.md`'s Part 1 finding. CAT048 §4.6.2 says only "FSPEC is the Field
Specification"; the octet-level encoding lives in ASTERIX Part 1, which **this repository has
never retrieved or hashed for either category**. `adapters/asterix_cat021.py` contains no
reference to Part 1 at all — its FSPEC handling was implemented from the CAT021 document's own
layout — so there is nothing shared to reuse, and importing it would create the appearance of a
common basis that does not exist. What CAT048 *can* check its own mechanics against is §5.3.1's
Table 2: 28 numbered FRNs with four explicit `FX` rows interleaved after FRN 7, 14, 21 and 28.
Four groups of seven plus four FX bits is exactly 32 bits, so **the UAP itself fixes the stride
and the four-octet maximum**, and `FSPEC_GROUPS` below is that table rather than an inheritance.

NO `struct` FORMAT SHORTCUTS
---------------------------
Every integer is assembled with `int.from_bytes(..., "big")` and emitted with
`int.to_bytes(..., "big")`. `struct` with a native-order format is silently wrong on the wrong
machine and `struct` with an explicit `>` is one typo from being the native one. ASTERIX is
big-endian throughout and the way to honour that is to say `"big"` at every call site.

THE SNAP DISCIPLINE, INHERITED FROM `gmtif_codec.py` AS WRITTEN
--------------------------------------------------------------
`snap(form, value)` returns the nearest value the field can carry, and **refuses** a value
outside the field's range with a `CodecError` naming the value and the range. Never a clamp to
the boundary, never a mask to the field width, never a wrap. Quantising INSIDE the range is the
format's own resolution and is not a loss the translator introduced; moving a value INTO range
is a fabrication, and clamping 400 NM to 255.996 NM would put a contact at the edge of coverage
and say nothing. Every form's bounds are computed from the standard's own stated LSB and width,
and `FORMS` records the section each came from so the arithmetic is checkable against the
document rather than against this file.

ONE FORM'S RANGE IS NOT ITS FIELD WIDTH, AND THAT IS THE INTERESTING ONE
------------------------------------------------------------------------
`tod` — I048/140 Time of Day — is 24 bits at 1/128 s, so the FIELD reaches 131 071.992 187 5 s.
§5.2.17's normative structure block states "Acceptable Range of values: 0<= Time-of-Day<=24 hrs",
so the ACCEPTED range tops out at 86 400.000 s **inclusive**. The bound in `FORMS` is the stated
one, not the width, which is what makes `raw = 11_059_200` (86 400.000 s exactly) legal and
`raw = 11_059_201` (one LSB past it) a refusal. See FORMAT_COVERAGE.md ambiguity 1, and
ambiguity 14 for the cross-adapter consequence: `asterix_cat021.py` refuses the value this
module accepts, on a different recorded basis, and neither was harmonised to the other.

THE GEODESY IS IMPORTED ARITHMETIC AND SAYS SO
----------------------------------------------
`direct` and `inverse` are Vincenty on WGS-84. **The pinned specification contains none of this**
— §4.3.2.1 gives only the radar-plane identities `X = RHO * SIN(THETA)` and
`Y = RHO * COS(THETA)`, and §4.3.2.2 names the WGS-84 ellipsoid and then defers the projection to
"a suitable projection technique … (e.g. a stereographical projection)". So two of the three
inputs are the document's own (the ellipsoid, and "local geographical north" per §4.3.1) and the
formulae are not. FORMAT_COVERAGE.md gap 24 records that, and the audit that keeps it honest is
`inverse(direct(...))` returning the original range and bearing — which
`tests/test_cdm_asterix_cat048_adapter.py` asserts to within the items' own LSBs.

**That audit proves less than it looks like it proves, and a mutation check is what established
the limit.** `direct` and `inverse` share these constants, so the round trip shows they are
mutual inverses and says NOTHING about whether the ellipsoid is the right one: replacing
`WGS84_A` with the semi-minor axis — a 21 km error — passed every inversion test. So the
ellipsoid is pinned separately, by its published constants and by three geodesic distances
computed independently of any implementation, in
`test_the_ellipsoid_is_wgs84_and_not_merely_self_consistent`. Self-consistency and correctness
are different properties and only one of them a round trip can measure.
"""
from __future__ import annotations

import math

# --------------------------------------------------------------------------- refusals


class CodecError(ValueError):
    """A value or byte pattern this codec refuses. Every message quotes what and why."""


# --------------------------------------------------------------------------- the FSPEC
#
# §5.3.1 Table 2. Four groups of seven FRNs, each followed by an explicit `FX | n.a. | Field
# Extension Indicator | n.a.` row. The fourth group's FX has no FRN 29 behind it, which is this
# category's counterpart to CAT021's "Not Used" FRNs and is a refusal for the same reason: a set
# bit names nothing that can be decoded and nothing whose length can be guessed.

#: FRNs per FSPEC octet, from Table 2's own interleaving of the FX rows.
FSPEC_GROUPS = 7

#: 28 defined FRNs + 4 FX bits = 32 bits = 4 octets. Derived from Table 2, not from Part 1.
MAX_FSPEC_OCTETS = 4

#: The highest FRN Table 2 defines. FRN 29 and above do not exist.
MAX_FRN = 28

#: Bit 1 of an FSPEC octet.
FX = 0x01


def read_fspec(data: bytes, offset: int) -> tuple[list[int], bytes, int]:
    """The set FRNs, the octets verbatim, and the offset of the first item.

    The octets are returned so the caller can park them: a conforming encoder emits the
    shortest FSPEC covering its highest set FRN, the specification does not forbid a longer
    one, and the round trip is byte-exact only if what we emit is what we read.
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
                f"(0x{octet:02X}) sets its FX bit, but the category 048 UAP defines "
                f"{MAX_FRN} FRNs in exactly {MAX_FSPEC_OCTETS} octets and there is no FRN "
                f"{MAX_FRN + 1}. A fifth octet names nothing that can be decoded, so it "
                "cannot be skipped and guessing a length would desynchronise the record"
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
            f"FRN(s) {bad} are outside the category 048 UAP's range 1..{MAX_FRN}"
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
# Every entry: (bits, signed, lsb, low, high, unit, locus). `low`/`high` are the DECODED
# bounds, computed from the standard's own stated LSB and width — except `tod`, whose bound is
# the range §5.2.17 states rather than the one 24 bits can express. Where the document also
# prints a maximum, the computed value is the same figure, which is what makes the arithmetic
# checkable against the document instead of against this table.

_LSB_1_256 = 1.0 / 256.0
_LSB_1_128 = 1.0 / 128.0
_LSB_ANGLE_16 = 360.0 / (1 << 16)
_LSB_ANGLE_14 = 360.0 / (1 << 14)
_LSB_ANGLE_13 = 360.0 / (1 << 13)
_LSB_ANGLE_12 = 360.0 / (1 << 12)
_LSB_SPEED = 2.0 ** -14

#: Exactly 1 NM in metres, ICAO/§3.2 ("NM Nautical Mile, unit of distance (1852 metres)").
METRES_PER_NM = 1852.0
FEET_PER_NM = 1852.0 / 0.3048
FEET_TO_METRES = 0.3048

#: Seconds in a day. §5.2.17's stated range tops out here, INCLUSIVE.
SECONDS_PER_DAY = 86400

FORMS: dict[str, tuple[int, bool, float, float, float, str, str]] = {
    # I048/040. §5.2.4 prints "Max. range = 256-(1/256) NM", which is 255.99609375.
    "rho": (16, False, _LSB_1_256, 0.0, 65535 * _LSB_1_256, "NM", "§5.2.4"),
    "theta": (16, False, _LSB_ANGLE_16, 0.0, 65535 * _LSB_ANGLE_16, "deg", "§5.2.4"),
    # I048/042. §5.2.5 prints "Max. range = 256 NM"; the field reaches 255.9921875.
    "cartesian": (16, True, _LSB_1_128, -32768 * _LSB_1_128, 32767 * _LSB_1_128, "NM", "§5.2.5"),
    # I048/090. 14 bits, LSB 1/4 FL, "in two's complement form" — Edition 1.32's clarification.
    "flight_level": (14, True, 0.25, -8192 * 0.25, 8191 * 0.25, "FL", "§5.2.12"),
    # I048/110. 14 bits, LSB 25 ft, two's complement, mean sea level zero reference.
    "height_3d": (14, True, 25.0, -8192 * 25.0, 8191 * 25.0, "ft", "§5.2.14"),
    # I048/120 subfield #1. 10 bits, LSB 1 m/s, two's complement.
    "doppler": (10, True, 1.0, -512.0, 511.0, "m/s", "§5.2.15"),
    # I048/120 subfield #2.
    "doppler_raw": (16, False, 1.0, 0.0, 65535.0, "m/s", "§5.2.15"),
    "frequency": (16, False, 1.0, 0.0, 65535.0, "MHz", "§5.2.15"),
    # I048/130 runlengths. §5.2.16 gives the span as "from 0 to 11.21 dg".
    "runlength": (8, False, _LSB_ANGLE_13, 0.0, 255 * _LSB_ANGLE_13, "deg", "§5.2.16"),
    "amplitude": (8, True, 1.0, -128.0, 127.0, "dBm", "§5.2.16"),
    # §5.2.16 gives "+/-0.5 NM"; the field reaches -0.5 .. 0.49609375.
    "range_difference": (8, True, _LSB_1_256, -128 * _LSB_1_256, 127 * _LSB_1_256, "NM",
                         "§5.2.16"),
    # §5.2.16 gives "+/-360/2^7 = +/-2.8125 dg".
    "azimuth_difference": (8, True, _LSB_ANGLE_14, -128 * _LSB_ANGLE_14, 127 * _LSB_ANGLE_14,
                           "deg", "§5.2.16"),
    # I048/140. THE BOUND IS THE STATED RANGE, NOT THE FIELD WIDTH. See the module docstring.
    "tod": (24, False, _LSB_1_128, 0.0, float(SECONDS_PER_DAY), "s", "§5.2.17"),
    # I048/161. §5.2.18 prints "(0..4095)".
    "track_number": (12, False, 1.0, 0.0, 4095.0, "", "§5.2.18"),
    # I048/200. The field is labelled "max. 2 NM/s" and reaches 3.99993896 — ambiguity 6.
    "groundspeed": (16, False, _LSB_SPEED, 0.0, 65535 * _LSB_SPEED, "NM/s", "§5.2.20"),
    "heading": (16, False, _LSB_ANGLE_16, 0.0, 65535 * _LSB_ANGLE_16, "deg", "§5.2.20"),
    # I048/210. §5.2.21 gives "0<= Sigma(X)<2 NM", "0<=Sigma (V)<56.25 Kt", "< 22.5 degrees".
    "sigma_position": (8, False, _LSB_1_128, 0.0, 255 * _LSB_1_128, "NM", "§5.2.21"),
    "sigma_speed": (8, False, _LSB_SPEED, 0.0, 255 * _LSB_SPEED, "NM/s", "§5.2.21"),
    "sigma_heading": (8, False, _LSB_ANGLE_12, 0.0, 255 * _LSB_ANGLE_12, "deg", "§5.2.21"),
}


def bounds(form: str) -> tuple[float, float, float]:
    """(low, high, lsb) for a form, as the standard's arithmetic gives them."""
    if form not in FORMS:
        raise CodecError(f"unknown form {form!r}; known: {', '.join(sorted(FORMS))}")
    bits, signed, lsb, low, high, _unit, _locus = FORMS[form]
    return low, high, lsb


def from_raw(form: str, raw: int) -> float:
    """The decoded value of a raw field, WITHOUT a range check.

    Reading is not the place to refuse: a raw pattern outside the stated range is what the
    wire said, and the item-level decoder is what decides whether that is a refusal (as it is
    for `tod`) or a value to park with a flag (as it is for `groundspeed`). Deciding here would
    hide the distinction inside the codec.
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
    bits, signed, lsb, low, high, unit, locus = FORMS[form]
    nearest = _nearest_raw(form, value)
    return twos_to_raw(nearest, bits) if signed else nearest


def snap(form: str, value: float) -> float:
    """The nearest value this form can carry — and a REFUSAL if it is out of range.

    Two different things, kept apart deliberately, on `gmtif_codec.snap`'s terms.

    QUANTISING inside the range is the FORMAT'S stated resolution, not a translator's loss:
    I048/040 states range in units of 1/256 NM and a value between two units is not
    representable by the standard rather than by this code. The result is exactly
    representable and never more than half an LSB from the input.

    Moving a value INTO range is something else entirely. Clamping 400 NM to 255.996 NM would
    put a contact at the edge of the coverage volume and report success; masking it to the
    field width would put it somewhere arbitrary. Both leave every length check passing. So a
    value outside the range is a `CodecError` quoting the value, the range and the LSB.
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
    adjacent half-LSB values would snap in opposite directions and a fixture built on one
    would disagree with a fixture built on the other. Half-up on the magnitude is symmetric
    about zero, which is what a two's-complement field needs.
    """
    bits, signed, lsb, *_rest = FORMS[form]
    scaled = value / lsb
    nearest = math.floor(abs(scaled) + 0.5)
    return int(-nearest if scaled < 0 else nearest)


# ---------------------------------------------------------------- the six-bit alphabet
#
# I048/240 Aircraft Identification is "Characters 1-8 (coded on 6 bits each)" and THIS DOCUMENT
# STATES NO CHARACTER TABLE. §5.2.25 Note 1 says "For the transmission of BDS Register 2,0, Data
# Item I048/240 is used", and BDS 2,0's coding is in [Ref. 2] ED-73F/DO-181F, which this
# repository does not pin. So the alphabet below is the ICAO Annex 10 Vol. IV Table 3-8 set that
# `adsb.py` and `asterix_cat021.py` both use for the same six bits — cited as their basis, not
# as this document's. `#` marks a code the alphabet does not define and is kept visible rather
# than cleaned away, for the reason `adsb.py` keeps it: a callsign with a `#` in it is a
# decodable record with an undefined character, which is different from a refusal.
SIX_BIT_ALPHABET = (
    "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####"
    " ###############0123456789######"
)


def decode_six_bit(raw: int, characters: int = 8) -> str:
    """`characters` six-bit codes, MSB first. Trailing spaces stripped, per the padding."""
    out = []
    for index in range(characters):
        shift = 6 * (characters - 1 - index)
        out.append(SIX_BIT_ALPHABET[(raw >> shift) & 0x3F])
    return "".join(out).rstrip()


def encode_six_bit(text: str, characters: int = 8) -> int:
    """The inverse. Space-padded to `characters`; refuses a character the alphabet lacks."""
    padded = text.ljust(characters)[:characters]
    raw = 0
    for index, char in enumerate(padded):
        code = SIX_BIT_ALPHABET.find(char.upper())
        if code < 0 or char == "#":
            raise CodecError(
                f"aircraft identification {text!r} contains {char!r}, which the six-bit "
                "alphabet does not define. Refusing rather than substituting — a substituted "
                "character is a different callsign"
            )
        raw |= code << (6 * (characters - 1 - index))
    return raw


# ------------------------------------------------------------------- octal Mode codes


def decode_octal(raw: int, digits: int = 4) -> str:
    """A Mode 1/2/3A code in the source's own octal representation, zero-padded."""
    return f"{raw:0{digits}o}"


def encode_octal(text: str, digits: int = 4) -> int:
    try:
        value = int(text, 8)
    except (TypeError, ValueError) as exc:
        raise CodecError(f"{text!r} is not an octal Mode code") from exc
    if not 0 <= value < (1 << (3 * digits)):
        raise CodecError(
            f"octal Mode code {text!r} does not fit {3 * digits} bits"
        )
    return value


# --------------------------------------------------------------------------- geodesy
#
# Vincenty on WGS-84. See the module docstring: the ellipsoid is §4.3.2.2's own and the
# formulae are not in the pinned document at all.

#: WGS-84, the ellipsoid §4.3.2.2 names ("a plane tangential to the WGS-84 Ellipsoid at the
#: location of the radar head").
WGS84_A = 6378137.0
WGS84_F = 1.0 / 298.257223563
WGS84_B = WGS84_A * (1.0 - WGS84_F)

EARTH_MODEL = "WGS-84"


def direct(lat_deg: float, lon_deg: float, azimuth_deg: float,
           distance_m: float) -> tuple[float, float]:
    """Vincenty direct: the point `distance_m` from (lat, lon) on bearing `azimuth_deg`.

    Azimuth is measured from TRUE north, which is what §4.3.1 states for `THETA` — "The
    reference for the azimuth shall be local geographical north" — so no declination enters.
    """
    if distance_m < 0:
        raise CodecError(f"a geodesic distance cannot be negative, got {distance_m!r} m")
    if distance_m == 0.0:
        return lat_deg, lon_deg
    phi1 = math.radians(lat_deg)
    alpha1 = math.radians(azimuth_deg)
    tan_u1 = (1 - WGS84_F) * math.tan(phi1)
    cos_u1 = 1 / math.sqrt(1 + tan_u1 * tan_u1)
    sin_u1 = tan_u1 * cos_u1
    sigma1 = math.atan2(tan_u1, math.cos(alpha1))
    sin_alpha = cos_u1 * math.sin(alpha1)
    cos_sq_alpha = 1 - sin_alpha * sin_alpha
    u_sq = cos_sq_alpha * (WGS84_A ** 2 - WGS84_B ** 2) / (WGS84_B ** 2)
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))

    sigma = distance_m / (WGS84_B * big_a)
    for _ in range(200):
        cos2_sigma_m = math.cos(2 * sigma1 + sigma)
        sin_sigma = math.sin(sigma)
        cos_sigma = math.cos(sigma)
        delta = big_b * sin_sigma * (
            cos2_sigma_m + big_b / 4 * (
                cos_sigma * (-1 + 2 * cos2_sigma_m ** 2)
                - big_b / 6 * cos2_sigma_m * (-3 + 4 * sin_sigma ** 2)
                * (-3 + 4 * cos2_sigma_m ** 2)
            )
        )
        previous = sigma
        sigma = distance_m / (WGS84_B * big_a) + delta
        if abs(sigma - previous) < 1e-14:
            break
    else:  # pragma: no cover - 200 iterations is far past convergence for any earthly range
        raise CodecError(
            f"the geodesic direct solution did not converge for {distance_m!r} m on bearing "
            f"{azimuth_deg!r} from ({lat_deg!r}, {lon_deg!r})"
        )

    sin_sigma = math.sin(sigma)
    cos_sigma = math.cos(sigma)
    cos2_sigma_m = math.cos(2 * sigma1 + sigma)
    tmp = sin_u1 * sin_sigma - cos_u1 * cos_sigma * math.cos(alpha1)
    phi2 = math.atan2(
        sin_u1 * cos_sigma + cos_u1 * sin_sigma * math.cos(alpha1),
        (1 - WGS84_F) * math.sqrt(sin_alpha * sin_alpha + tmp * tmp),
    )
    lam = math.atan2(sin_sigma * math.sin(alpha1),
                     cos_u1 * cos_sigma - sin_u1 * sin_sigma * math.cos(alpha1))
    big_c = WGS84_F / 16 * cos_sq_alpha * (4 + WGS84_F * (4 - 3 * cos_sq_alpha))
    big_l = lam - (1 - big_c) * WGS84_F * sin_alpha * (
        sigma + big_c * sin_sigma * (
            cos2_sigma_m + big_c * cos_sigma * (-1 + 2 * cos2_sigma_m ** 2)
        )
    )
    lon2 = math.degrees(math.radians(lon_deg) + big_l)
    # Normalise into [-180, 180) so the result is a legal CDM longitude rather than 181.4.
    lon2 = (lon2 + 180.0) % 360.0 - 180.0
    return math.degrees(phi2), lon2


def inverse(lat1_deg: float, lon1_deg: float,
            lat2_deg: float, lon2_deg: float) -> tuple[float, float]:
    """Vincenty inverse: (distance_m, initial azimuth in degrees from TRUE north, [0, 360)).

    Exists for the audit rather than for the adapter: `inverse(direct(...))` returning the
    original range and bearing is the only check available on arithmetic the pinned document
    does not supply.
    """
    phi1, phi2 = math.radians(lat1_deg), math.radians(lat2_deg)
    big_l = math.radians(lon2_deg - lon1_deg)
    tan_u1 = (1 - WGS84_F) * math.tan(phi1)
    cos_u1 = 1 / math.sqrt(1 + tan_u1 * tan_u1)
    sin_u1 = tan_u1 * cos_u1
    tan_u2 = (1 - WGS84_F) * math.tan(phi2)
    cos_u2 = 1 / math.sqrt(1 + tan_u2 * tan_u2)
    sin_u2 = tan_u2 * cos_u2

    lam = big_l
    sin_sigma = cos_sigma = sigma = sin_alpha = cos_sq_alpha = cos2_sigma_m = 0.0
    for _ in range(200):
        sin_lam, cos_lam = math.sin(lam), math.cos(lam)
        sin_sigma = math.sqrt((cos_u2 * sin_lam) ** 2
                              + (cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam) ** 2)
        if sin_sigma == 0.0:
            return 0.0, 0.0
        cos_sigma = sin_u1 * sin_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sin_sigma, cos_sigma)
        sin_alpha = cos_u1 * cos_u2 * sin_lam / sin_sigma
        cos_sq_alpha = 1 - sin_alpha * sin_alpha
        cos2_sigma_m = 0.0 if cos_sq_alpha == 0.0 else \
            cos_sigma - 2 * sin_u1 * sin_u2 / cos_sq_alpha
        big_c = WGS84_F / 16 * cos_sq_alpha * (4 + WGS84_F * (4 - 3 * cos_sq_alpha))
        previous = lam
        lam = big_l + (1 - big_c) * WGS84_F * sin_alpha * (
            sigma + big_c * sin_sigma * (
                cos2_sigma_m + big_c * cos_sigma * (-1 + 2 * cos2_sigma_m ** 2)
            )
        )
        if abs(lam - previous) < 1e-14:
            break
    else:  # pragma: no cover - non-convergence needs near-antipodal points
        raise CodecError(
            f"the geodesic inverse solution did not converge between "
            f"({lat1_deg!r}, {lon1_deg!r}) and ({lat2_deg!r}, {lon2_deg!r})"
        )

    u_sq = cos_sq_alpha * (WGS84_A ** 2 - WGS84_B ** 2) / (WGS84_B ** 2)
    big_a = 1 + u_sq / 16384 * (4096 + u_sq * (-768 + u_sq * (320 - 175 * u_sq)))
    big_b = u_sq / 1024 * (256 + u_sq * (-128 + u_sq * (74 - 47 * u_sq)))
    delta = big_b * sin_sigma * (
        cos2_sigma_m + big_b / 4 * (
            cos_sigma * (-1 + 2 * cos2_sigma_m ** 2)
            - big_b / 6 * cos2_sigma_m * (-3 + 4 * sin_sigma ** 2)
            * (-3 + 4 * cos2_sigma_m ** 2)
        )
    )
    distance = WGS84_B * big_a * (sigma - delta)
    sin_lam, cos_lam = math.sin(lam), math.cos(lam)
    azimuth = math.degrees(math.atan2(cos_u2 * sin_lam,
                                      cos_u1 * sin_u2 - sin_u1 * cos_u2 * cos_lam))
    return distance, _wrap_azimuth(azimuth)


def _wrap_azimuth(degrees: float) -> float:
    """Into [0, 360), with a due-north geodesic coming back as 0 rather than as 359.999…

    Needed because `atan2` on an exactly-northward geodesic gets a numerically tiny NEGATIVE
    first argument, so a plain `% 360.0` returns something a hair under 360. Left alone, the
    inversion audit reports a 360-degree error on the one bearing most likely to appear in a
    fixture, and the check that exists to catch real arithmetic faults fails on none.
    """
    wrapped = degrees % 360.0
    return 0.0 if wrapped > 360.0 - 1e-9 else wrapped


def ground_range_m(slant_range_nm: float, height_difference_m: float) -> float | None:
    """The ground range under a slant range, or None when the geometry is impossible.

    `RHO` is a SLANT range: §4.3.1 calls I048/040 "slant polar co-ordinates". So the distance
    along the ellipsoid is `sqrt(RHO² - Δh²)`, and the correction is largest at SHORT range
    with a high target rather than at long range — which is the opposite of the usual
    intuition, and the reason a `Δh = 0` assumption is refused rather than accepted as a small
    error. A target at FL350 is 5.76 NM above the site; directly overhead its slant range is
    5.76 NM and its ground range is ~0, so treating slant as ground paints it 10.7 km out.

    `None` when |Δh| exceeds the slant range, which is geometrically impossible and happens in
    practice when a PRESSURE altitude stands in for a geometric height. NO ROW OF THE RULING
    DOCUMENT COVERS THIS CASE; the choice made here is to derive no position and say so, on
    the same terms as the no-height case, rather than to refuse the record (which would be
    filtering a translatable report) or to clamp the ground range to zero (which would put the
    contact at the antenna).
    """
    slant_m = slant_range_nm * METRES_PER_NM
    if abs(height_difference_m) > slant_m:
        return None
    return math.sqrt(slant_m * slant_m - height_difference_m * height_difference_m)
