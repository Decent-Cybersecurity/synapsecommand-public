"""IMAPB — MISB ST 1201.3's floating-point-to-integer mapping, both directions.

WHAT THIS IS FOR
----------------
ST 0601.14a states fourteen of its 141 items with a Format column reading `IMAPB` and gives each
one a range and no scale factor: the mapping is delegated whole to MISB ST 1201.3, which is
**park 5**. This module is that park's artefact. It is a VALUE codec — octets in, float out, and
back — and it knows nothing about packets, tags or Local Sets. `klv_codec` frames, `klv_uas_codec`
reads items, and this maps one item's value when that item's Format says to.

Both documents are held and pinned: ST 1201.3 at `fixtures/klv/spec/ST1201.3.pdf`, SHA-256
`c5d8cb2d…bff4a07e`, and ST 0601.14a at `fixtures/klv/spec/ST0601.14a.pdf`,
`3d5f1ca1…ab212ce4`. Every constant below is read from one of them and every one is checked
against a worked example the document prints itself.

**PARK 5 IS NOT CLOSED BY THIS FILE.** Its exit condition is the document *plus* the artefact that
document makes writable; the artefact is here and the fourteen rows it reaches still read `not
yet`, because **none of the fourteen is in the witnessed set**. The pinned stream carries 26 items
whose highest tag is 65. So this codec is checked against the documents' own examples and against
no held octet, which is a weaker footing than every other codec in this package has, and it is the
reason the rows do not move. See FORMAT_COVERAGE.md, *The IMAPB codec — ST 1201.3, and the fourteen
rows it reaches*.

THE ALGORITHM, AND WHY IT IS SHIFTS RATHER THAN A DIVISION
----------------------------------------------------------
ST 1201.3 §7.1.2 (Starting Point B) computes three constants from `(a, b, L)` — the range and the
KLV length in bytes::

    bPow    = ceil(log2(b - a))
    dPow    = 8 * L - 1                 # the -1 is the special-value bit, §7.2.3
    sF      = 2 ** (dPow - bPow)        # forward scale
    sR      = 2 ** (bPow - dPow)        # reverse scale
    Zoffset = sF*a - floor(sF*a)        # ONLY when a < 0 < b

and §7.2.1 / §7.2.2 map with them::

    y = floor(sF * (x - a) + Zoffset)   # forward
    x = sR * (y - Zoffset) + a          # reverse

Both scales are powers of two, which is the standard's own point: the mapping costs one multiply
and two adds, and the multiply is a shift. **`Zoffset` is the part that is easy to drop and
changes answers.** §8.5 exists for it: without the offset a range spanning zero maps 0.0 to the
same integer as some negative value, so "no motion" and "a little motion the wrong way" become
indistinguishable. It is computed only when `a < 0 < b` — that condition is the document's, at
step 6 of §7.1.2, and applying the offset unconditionally would shift every all-positive range by
a fraction of a step.

**THE LENGTH IS THE WIRE'S, NOT THE DOCUMENT'S.** §7.4: "The lengths computed or provided when
defining the mapping (IMAPA, IMAPB) are considered the recommended number of bytes to use ... When
using a different length, it is important to compute the constants needed to do the forward and
reverse mapping based on the KLV supplied length." Every one of the fourteen items has a `Length`
column reading `Variable`, so there is no fixed width to hard-code and the constants are recomputed
per call from the octets actually present. A codec that pinned each item's Max Length would decode
a conforming shorter item wrongly, and silently — the result is a plausible number, which is this
park's whole risk as its row states it.

SPECIAL VALUES ARE SIGNALS AND ARE NOT MAPPED
---------------------------------------------
§7.2.3 Table 1 reserves the top two bits. `Bit(MSB) & Bit(MSB-1)` set means the value is a signal,
not a measurement, and Table 2 assigns the patterns: ±infinity, ±quiet NaN, ±signalling NaN, a
reserved pattern and a user-defined one. **Running a signal through the reverse map yields a
number**, which is the defect class this repository's ellipsoid audit and the
`special_values_are_signals_and_not_measurements` fixture both exist for — so `decode` returns a
`Special` rather than a float and never both.

One row of Table 1 is a normal value with the MSB set: `1 0 0` is "the max value of the normal
mapping values; this is the only normal value that has the MSB=1", which happens only when `b - a`
is a power of two. It is decoded as a number, not a signal, and `test_the_msb_high_normal_value_is_
not_read_as_a_signal` is the check that the two-bit test is a conjunction rather than a test of the
MSB alone.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
------------------------------------------
**It does not implement IMAPA.** §7.1.1's Starting Point A derives `L` from a desired precision,
and not one of ST 0601.14a's fourteen rows uses that notation — all fourteen state
`IMAPB(a, b, Length, SoftVal)`. `length_for_precision` is provided because §7.1.1 step 3 says
Starting Point A then "follows steps in Starting Point B" and the derivation is two lines, but no
caller here uses it and it is tested against §10's own Example 3 rather than against a row.

**It does not fuse and it does not join.** Each mapping is one item's octets and one item's range.
Nothing here reads two items together, and `SDCC` uncertainties — which ST 0601.14a marks eligible
on seven of the fourteen — live in item 102, whose layout is ST 1010 and is not held.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

__all__ = [
    "IMAPB_ITEMS", "Constants", "Special", "SpecialKind",
    "constants", "forward", "reverse", "encode", "decode", "length_for_precision",
]


class SpecialKind(str):
    """A §7.2.3 Table 2 signal, by the document's own name."""
    __slots__ = ()


#: Table 2, by `(bn-2 sign, bn-3 NaN, bn-4)` once the two-bit special indicator is established.
#: Read from ST 1201.3 §7.2.3 Table 2 rather than from IEEE 754 directly — the bit ORDER here is
#: this document's and the patterns are three bits wide, which IEEE's own encoding is not.
_TABLE_2: Final[dict[tuple[int, int, int], str]] = {
    (0, 0, 1): "+Inf",
    (1, 0, 1): "-Inf",
    (0, 1, 0): "+QNaN",
    (1, 1, 0): "-QNaN",
    (0, 1, 1): "+SNaN",
    (1, 1, 1): "-SNaN",
    (1, 0, 0): "Reserved",
    (0, 0, 0): "UserDefined",
}


@dataclass(frozen=True, slots=True)
class Special:
    """A signal read off the wire. NOT a number, and deliberately not convertible to one.

    `payload` is the `bn-5 … b0` remainder, which Table 2 gives a meaning to for the two SNaN rows
    ("Remaining bits are used as the signal value") and for `UserDefined`. It is carried for every
    kind so that a caller re-emitting the octets has them, which is what `encode_special` needs.
    """
    kind: str
    payload: int
    length: int

    def __str__(self) -> str:  # pragma: no cover - a convenience for messages
        return f"{self.kind}({self.payload})" if self.payload else self.kind


@dataclass(frozen=True, slots=True)
class Constants:
    """§7.1.2's one-time computation, for one `(a, b, L)`."""
    a: float
    b: float
    length: int
    b_pow: int
    d_pow: int
    s_f: float
    s_r: float
    z_offset: float


def constants(a: float, b: float, length: int) -> Constants:
    """§7.1.2 Starting Point B, verbatim.

    `a < b` is the document's own precondition ("Note: a<b") and is checked rather than assumed:
    `log2` of a non-positive number raises, and a caller that passed the range backwards would get
    a domain error naming nothing.
    """
    if not (a < b):
        raise ValueError(f"IMAPB requires a < b; got a={a!r}, b={b!r} (ST 1201.3 §7.1.2)")
    if length < 1:
        raise ValueError(f"IMAPB length must be at least one octet; got {length!r}")
    b_pow = math.ceil(math.log2(b - a))
    d_pow = 8 * length - 1
    s_f = 2.0 ** (d_pow - b_pow)
    s_r = 2.0 ** (b_pow - d_pow)
    # Step 6, and the condition is the document's: `if (a<0 and b>0)`. Not `a <= 0`, and not
    # unconditional — see the module docstring.
    z_offset = s_f * a - math.floor(s_f * a) if (a < 0 and b > 0) else 0.0
    return Constants(a, b, length, b_pow, d_pow, s_f, s_r, z_offset)


def forward(a: float, b: float, length: int, x: float) -> int:
    """§7.2.1: a floating-point value to its mapped integer.

    Out-of-range values are REFUSED rather than clamped. The document does not define the mapping
    outside `[a, b]`, and `floor(sF*(x-a)+Z)` runs happily past the end of the integer range —
    producing an integer that will not fit the declared length, or that collides with the special
    value space. A clamp would be this repository inventing a rule; a refusal says the caller has a
    value the item cannot carry, which is a fact worth surfacing.
    """
    if not (a <= x <= b):
        raise ValueError(
            f"{x!r} is outside IMAPB({a}, {b}) — ST 1201.3 defines the mapping on [a, b] only, and "
            f"neither clamping nor extrapolating is stated. The caller has a value this item "
            f"cannot carry"
        )
    c = constants(a, b, length)
    return math.floor(c.s_f * (x - c.a) + c.z_offset)


def reverse(a: float, b: float, length: int, y: int) -> float:
    """§7.2.2 step 3: a mapped integer back to a float. The caller has established it is normal."""
    c = constants(a, b, length)
    return c.s_r * (y - c.z_offset) + c.a


def _is_special(y: int, length: int) -> bool:
    """§7.2.2 step 1: `Bit(MSB, y) & Bit(MSB-1, y)`. A CONJUNCTION, not an MSB test.

    Table 1's second row is `1 0 0` — a normal value, and the only normal one with the MSB set. A
    test on the MSB alone would read the top of a power-of-two range as a signal.
    """
    bits = 8 * length
    return bool((y >> (bits - 1)) & 1) and bool((y >> (bits - 2)) & 1)


def decode(a: float, b: float, octets: bytes) -> float | Special:
    """Octets to a value. Returns a `Special` for a §7.2.3 signal and a float otherwise.

    The length is taken from the octets, per §7.4 — see the module docstring. Big-endian, which is
    `ST 0107.2-02` in ST 0107.3 §6.1: "Byte order shall be big-endian or MSB".
    """
    if not octets:
        raise ValueError("IMAPB has no zero-length form; a zero-length item is ST 0601.14a §6.5's "
                         "explicit unknown and is the caller's to handle")
    length = len(octets)
    y = int.from_bytes(octets, "big")
    if _is_special(y, length):
        bits = 8 * length
        sign = (y >> (bits - 3)) & 1
        nan = (y >> (bits - 4)) & 1
        b4 = (y >> (bits - 5)) & 1
        kind = _TABLE_2[(sign, nan, b4)]
        payload = y & ((1 << (bits - 5)) - 1)
        return Special(kind, payload, length)
    return reverse(a, b, length, y)


def encode(a: float, b: float, length: int, x: float) -> bytes:
    """A value to `length` octets, big-endian. The inverse of `decode` for every normal value.

    The result is checked to fit the declared width before it is returned. It cannot overflow for
    an in-range `x` — `forward` refuses out-of-range values and `d_pow` is one bit short of the
    width — but the check is here rather than argued, because the one thing this park's row says
    about a wrong answer is that it looks like a right one.
    """
    y = forward(a, b, length, x)
    if not (0 <= y < (1 << (8 * length))):
        raise ValueError(f"IMAPB({a}, {b}, {length}) mapped {x!r} to {y}, which does not fit "
                         f"{length} octets")
    return y.to_bytes(length, "big")


def encode_special(special: Special) -> bytes:
    """A signal back to its octets, so a round trip through `decode` is byte-exact."""
    bits = 8 * special.length
    for (sign, nan, b4), name in _TABLE_2.items():
        if name == special.kind:
            break
    else:  # pragma: no cover - Special is only built by `decode`
        raise ValueError(f"{special.kind!r} is not a ST 1201.3 Table 2 pattern")
    y = (0b11 << (bits - 2)) | (sign << (bits - 3)) | (nan << (bits - 4)) | (b4 << (bits - 5))
    return (y | special.payload).to_bytes(special.length, "big")


def length_for_precision(a: float, b: float, precision: float) -> int:
    """§7.1.1 / Eq 20-21: the octet count a desired precision needs. IMAPA's half of the door.

    Not used by any row here — all fourteen state IMAPB — and provided because §7.1.1 step 3 hands
    control straight to Starting Point B, so leaving it out would make the module's coverage of the
    document look like a judgement rather than the absence of a caller.
    """
    if not (a < b):
        raise ValueError(f"IMAPB requires a < b; got a={a!r}, b={b!r}")
    if not (0 < precision < b - a):
        raise ValueError(f"ST 1201.3 §7.1.1 requires 0 < g < b-a; got g={precision!r}")
    l_bits = math.ceil(math.log2((b - a) / precision) + 1)  # the +1 is the special-value bit
    return math.ceil(l_bits / 8)


#: The fourteen ST 0601.14a items whose Format column reads `IMAPB`, each with the range its own
#: §8.x block states and the Max Length that block's Length row gives.
#:
#: RE-DERIVED FROM THE PINNED COPY, not transcribed from the ledger — see FORMAT_COVERAGE.md, *The
#: IMAPB codec*. The set agrees with park 5's enumeration exactly. `max_length` is recorded and is
#: NOT enforced: §7.4 makes the wire's length authoritative, and every one of these rows has a
#: `Length` column reading `Variable`, so the Max Length is a bound on what a conforming emitter
#: sends rather than a fact a decoder may rely on.
#:
#: NONE OF THESE FOURTEEN IS IN THE WITNESSED SET. The pinned stream's 26 items stop at tag 65, so
#: every entry here is checked against its own §8.x worked example and against no held octet.
IMAPB_ITEMS: Final[dict[int, tuple[str, str, float, float, int]]] = {
    96:  ("Target Width Extended",                        "m",   0.0,     1_500_000.0, 8),
    103: ("Density Altitude Extended",                    "m",   -900.0,  40_000.0,    8),
    104: ("Sensor Ellipsoid Height Extended",             "m",   -900.0,  40_000.0,    8),
    105: ("Alternate Platform Ellipsoid Height Extended", "m",   -900.0,  40_000.0,    8),
    109: ("Range To Recovery Location",                   "km",  0.0,     21_000.0,    4),
    112: ("Platform Course Angle",                        "deg", 0.0,     360.0,       8),
    113: ("Altitude AGL",                                 "m",   -900.0,  40_000.0,    4),
    114: ("Radar Altimeter",                              "m",   -900.0,  40_000.0,    4),
    117: ("Sensor Azimuth Rate",                          "dps", -1000.0, 1000.0,      4),
    118: ("Sensor Elevation Rate",                        "dps", -1000.0, 1000.0,      4),
    119: ("Sensor Roll Rate",                             "dps", -1000.0, 1000.0,      4),
    120: ("On-board MI Storage Percent Full",             "%",   0.0,     100.0,       3),
    132: ("Transmission Frequency",                       "MHz", 1.0,     99_999.0,    4),
    134: ("Zoom Percentage",                              "%",   0.0,     100.0,       4),
}


def decode_item(tag: int, octets: bytes) -> float | Special:
    """Decode one ST 0601.14a item by its tag, using the range its own section states."""
    try:
        _name, _units, a, b, _max_len = IMAPB_ITEMS[tag]
    except KeyError:
        raise KeyError(
            f"tag {tag} is not one of the fourteen ST 0601.14a items whose Format is IMAPB "
            f"({sorted(IMAPB_ITEMS)})"
        ) from None
    return decode(a, b, octets)


def encode_item(tag: int, length: int, x: float) -> bytes:
    """Encode one ST 0601.14a item by its tag, at a caller-chosen length. §7.4's variable width."""
    _name, _units, a, b, _max_len = IMAPB_ITEMS[tag]
    return encode(a, b, length, x)
