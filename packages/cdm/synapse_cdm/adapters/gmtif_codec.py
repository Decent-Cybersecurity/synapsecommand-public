"""The AEDP-4607 Annex C wire codec: bytes to numbers and back, and nothing above that.

FIRST NON-TEXT WIRE FORMAT IN THE SET, WHICH IS WHY THIS IS ITS OWN MODULE
--------------------------------------------------------------------------
CoT and NITS are XML, AIS is armoured ASCII, ADS-B and CAT021 are binary but shallow — a frame
and a handful of items. GMTIF is a byte-aligned binary format with **seven numeric encodings**,
two of which are sign-magnitude and two of which are binary angles, and every one of them is a
place where a plausible-looking wrong answer costs metres or degrees rather than an exception.
So the codec is a layer of its own with a test per type against hand-computed byte patterns, and
the segment logic in `gmtif.py` sits on top of it and never touches a byte.

NO `struct` FORMAT SHORTCUTS. Every integer is assembled with `int.from_bytes(..., "big")` and
every one is emitted with `int.to_bytes(..., "big")`, because `struct` with a native-order format
is silently wrong on the wrong machine and `struct` with an explicit `>` is one typo away from
being the native one. §2.3 and Annex C-4.1 are unambiguous — "All data will be passed in a
'Big-Endian' manner, with the most-significant byte passed first", and "there are no half-bytes
included in the structure" — and the way to honour that is to say `"big"` at every call site.

THE SEVEN ENCODINGS, AND WHERE EACH ONE'S TRAP IS
-------------------------------------------------
`In`   Annex C-4.3. Unsigned, 8/16/32 bits. No trap.

`Sn`   Annex C-4.4. **Two's complement**, 8/16/32/64 bits. To negate, "complement all the bits
       in the word and then add 1".

`Bn`   Annex C-4.5. **SIGN-MAGNITUDE**, not two's complement, and this is the trap: "the first
       bit providing the sign, the next set of 8 bits providing the integer part, and the
       remaining bits providing the fractional part … The numbers are expressed in sign
       magnitude." Read as two's complement, every negative `B16` is wrong by 512. B16 is
       1 + 8 + 7 with a 2^-7 LSB, so its maximum is 256 - 1/128 = 255.9921875 — which the
       standard states, and which is how the layout can be checked against the document.

`H32`  Annex C-4.5's special case, added there by guide Annex M: 1 + 15 + 16, sign-magnitude,
       so a 32-bit field whose integer part reaches 32 767 and whose LSB is 2^-16. Decoding it
       as a `B32` shifts every value by a factor of 2^15.

`BAn`  Annex C-4.6. Unsigned, scaled `value × 1.40625 × 2^-(n-8)`, which is `value × 360/2^n`.
       Covers 0-360, so **longitudes arrive East-of-Greenwich in [0, 360)** and headings stay
       there. 1.40625 is 45/32, so the scale is `45/2^(n-3)`: a dyadic rational, which is why
       the conversion is EXACT in float64 and why this module claims so rather than hedging.
       A ≤32-bit integer times 45 needs 38 significand bits; float64 has 53.

`SAn`  Annex C-4.7. **Two's complement**, scaled `value × 1.40625 × 2^-(n-7)` = `value × 180/2^n`.
       Covers ±90 — latitude, pitch, roll. Note the two differences from `BAn` at once: the
       integer is signed AND the exponent differs by one. Using one function for both is how a
       latitude comes out double.

`A`    §2.3 and Annex A. STANAG 4545 **BCS**: 0x20-0x7E plus LF (0x0A), FF (0x0C) and CR (0x0D).
       "Alphanumeric fields shall be left-justified, with unused bytes filled with the ISO Basic
       Character Set (BCS) space character (hexadecimal 0x20)." So trailing 0x20 is padding and
       is stripped on ingest and restored on egress; a byte outside BCS is a **refusal quoting
       the offset**, never a lossy re-decode into Latin-1 or a replacement character. Annex A
       goes further than the range: "character codes ranging from 0xA0 to 0xFF should never be
       used. Therefore, the use of ECS characters in this standard shall be restricted to the
       BCS Subset" — a "shall", so the restriction is enforced rather than warned about.

EXACTNESS IS THE POINT OF THE ROUND TRIP
-----------------------------------------
Every decoder here has an encoder that is its exact inverse over the whole representable range,
and `test_cdm_gmtif_codec` asserts that by exhaustion for the 8- and 16-bit forms and by sampling
for the 32-bit ones. That property is what makes the adapter's byte-exact round trip a
consequence rather than a hope: the adapter parks the RAW wire integers and re-encodes from them,
so a float that did not survive a conversion could not silently corrupt an emitted packet — but
the round trip is only worth anything if `encode(decode(b)) == b` holds here first.
"""
from __future__ import annotations

# ------------------------------------------------------------------ BCS, per Annex A
#
# The three control characters are in the set: Annex A lists LINE FEED, FORM FEED and CARRIAGE
# RETURN alongside the printable range, and a Free Text Segment carrying a multi-line message is
# exactly what they are there for.
BCS_PRINTABLE = range(0x20, 0x7F)
BCS_CONTROL = (0x0A, 0x0C, 0x0D)
PAD = 0x20


class CodecError(ValueError):
    """A byte pattern this codec refuses to interpret. Every message quotes the offset."""


def is_bcs(byte: int) -> bool:
    return byte in BCS_PRINTABLE or byte in BCS_CONTROL


# ------------------------------------------------------------------ unsigned integers, C-4.3

def read_unsigned(data: bytes, offset: int, width: int) -> int:
    """`I8`, `I16`, `I32`. Big-endian, per §2.3 and Annex C-4.1."""
    _require(data, offset, width, "In")
    return int.from_bytes(data[offset:offset + width], "big", signed=False)


def write_unsigned(value: int, width: int) -> bytes:
    limit = 1 << (8 * width)
    if not 0 <= value < limit:
        raise CodecError(f"I{8 * width} value {value} is outside 0..{limit - 1}")
    return int(value).to_bytes(width, "big", signed=False)


# ------------------------------------------------------------------ signed integers, C-4.4

def read_signed(data: bytes, offset: int, width: int) -> int:
    """`S8`, `S16`, `S32`, `S64`. Two's complement, and the standard says so explicitly."""
    _require(data, offset, width, "Sn")
    return int.from_bytes(data[offset:offset + width], "big", signed=True)


def write_signed(value: int, width: int) -> bytes:
    bound = 1 << (8 * width - 1)
    if not -bound <= value < bound:
        raise CodecError(f"S{8 * width} value {value} is outside {-bound}..{bound - 1}")
    return int(value).to_bytes(width, "big", signed=True)


# ------------------------------------------------- sign-magnitude binary decimals, C-4.5
#
# One implementation for B16, B32 and H32, parameterised by how many bits are fraction. The
# integer part is whatever sits between the sign bit and the fraction, which the standard states
# per form: B16 is 1+8+7, B32 is 1+8+23, H32 is 1+15+16.

#: form -> (total bits, fraction bits). The integer width falls out as total - 1 - fraction.
SIGN_MAGNITUDE: dict[str, tuple[int, int]] = {"B16": (16, 7), "B32": (32, 23), "H32": (32, 16)}


def read_sign_magnitude(data: bytes, offset: int, form: str) -> float:
    """`B16`, `B32`, `H32`. **Sign-magnitude** — the single most likely decoding error here.

    Returns a float because that is what the value IS: an integer part plus a dyadic fraction.
    The division is by a power of two, so no rounding is introduced.
    """
    bits, fraction_bits = SIGN_MAGNITUDE[form]
    width = bits // 8
    raw = read_unsigned(data, offset, width)
    magnitude = raw & ((1 << (bits - 1)) - 1)
    value = magnitude / float(1 << fraction_bits)
    return -value if raw >> (bits - 1) else value


def write_sign_magnitude(value: float, form: str) -> bytes:
    """The exact inverse. Negative zero encodes as the SIGN BIT SET and a zero magnitude.

    Which is a real distinction on this wire and not a curiosity: sign-magnitude has two
    representations of zero, so `0x8000` and `0x0000` are different bytes that mean the same
    number. Round-tripping a packet has to preserve which one arrived, so the raw integer is what
    the adapter parks and this function is only used where a magnitude was computed rather than
    read. `math.copysign` is what distinguishes -0.0 from 0.0 here.
    """
    import math
    bits, fraction_bits = SIGN_MAGNITUDE[form]
    scale = 1 << fraction_bits
    magnitude = abs(value) * scale
    rounded = int(round(magnitude))
    if abs(magnitude - rounded) > 1e-9:
        raise CodecError(
            f"{form} value {value!r} is not a whole multiple of 2^-{fraction_bits}; encoding it "
            "would move the value, and this codec does not round a measurement to fit a field"
        )
    limit = (1 << (bits - 1)) - 1
    if rounded > limit:
        raise CodecError(f"{form} magnitude {value!r} exceeds {limit / scale}")
    sign = 1 if (value < 0 or math.copysign(1.0, value) < 0) else 0
    return write_unsigned((sign << (bits - 1)) | rounded, bits // 8)


# ------------------------------------------------------------- binary angles, C-4.6 / C-4.7
#
# The scale the standard writes as `value × 1.40625 × 1/2^(n-8)` for BA and `× 1/2^(n-7)` for SA.
# 1.40625 is 45/32, so BA is `value × 45/2^(n-3)` = `value × 360/2^n` and SA is
# `value × 45/2^(n-2)` = `value × 180/2^n`. Both are dyadic multiples of 45, so both are exact in
# float64 for every representable input, which is the claim FORMAT_COVERAGE.md's settlement 6
# makes and this is where it is kept.

BA_NUMERATOR = 45
SA_NUMERATOR = 45


def read_binary_angle(data: bytes, offset: int, width: int) -> float:
    """`BA16`, `BA32`. Unsigned, [0, 360). Longitudes arrive East-of-Greenwich."""
    raw = read_unsigned(data, offset, width)
    return raw * BA_NUMERATOR / float(1 << (8 * width - 3))


def write_binary_angle(value: float, width: int) -> bytes:
    bits = 8 * width
    raw = value * (1 << (bits - 3)) / BA_NUMERATOR
    rounded = int(round(raw))
    if abs(raw - rounded) > 1e-6:
        raise CodecError(
            f"BA{bits} value {value!r} deg is not on the {BA_NUMERATOR / (1 << (bits - 3))} deg "
            "grid; rounding it would move the angle"
        )
    if not 0 <= rounded < (1 << bits):
        raise CodecError(f"BA{bits} value {value!r} deg is outside [0, 360)")
    return write_unsigned(rounded, width)


def read_signed_binary_angle(data: bytes, offset: int, width: int) -> float:
    """`SA16`, `SA32`. **Two's complement** and a different exponent from `BAn`. Both differ."""
    raw = read_signed(data, offset, width)
    return raw * SA_NUMERATOR / float(1 << (8 * width - 2))


def write_signed_binary_angle(value: float, width: int) -> bytes:
    bits = 8 * width
    raw = value * (1 << (bits - 2)) / SA_NUMERATOR
    rounded = int(round(raw))
    if abs(raw - rounded) > 1e-6:
        raise CodecError(
            f"SA{bits} value {value!r} deg is not on the {SA_NUMERATOR / (1 << (bits - 2))} deg "
            "grid; rounding it would move the angle"
        )
    return write_signed(rounded, width)


# ------------------------------------------------------------------ alphanumerics, §2.3

def read_bcs(data: bytes, offset: int, width: int, *, field: str,
             strip: bool = True) -> str:
    """A fixed-width BCS field. Trailing 0x20 is padding; a non-BCS byte is a refusal.

    `strip=False` is for `F3` Free Text, whose width is the remainder of the segment rather
    than a declared number — there is no "unused" there, so its trailing spaces are data and
    stripping them would change the field's length and break the round trip.
    """
    _require(data, offset, width, f"A ({field})")
    chunk = data[offset:offset + width]
    for index, byte in enumerate(chunk):
        if not is_bcs(byte):
            raise CodecError(
                f"{field}: byte 0x{byte:02X} at offset {offset + index} is outside the STANAG "
                "4545 Basic Character Set (0x20-0x7E plus LF, FF, CR). Annex A says the use of "
                "ECS characters \"shall be restricted to the BCS Subset\", so this is a packet "
                "with an error rather than a value to re-decode; re-decoding it into Latin-1 or "
                "a replacement character would put bytes nobody sent into an operator's view"
            )
    text = chunk.decode("ascii")
    return text.rstrip(" ") if strip else text


def write_bcs(value: str, width: int, *, field: str) -> bytes:
    """Left-justified, 0x20-padded to the declared width, per §2.3."""
    encoded = value.encode("ascii", errors="strict") if value.isascii() else None
    if encoded is None:
        raise CodecError(f"{field}: {value!r} is not ASCII, so it cannot be BCS")
    for byte in encoded:
        if not is_bcs(byte):
            raise CodecError(f"{field}: 0x{byte:02X} in {value!r} is outside the BCS")
    if len(encoded) > width:
        raise CodecError(
            f"{field}: {value!r} is {len(encoded)} bytes and the field is {width}. Truncating "
            "would emit a different identifier from the one the CDM holds"
        )
    return encoded + bytes([PAD]) * (width - len(encoded))


# ------------------------------------------------------------------ flags, C-4.9

def set_bits(value: int, width: int) -> list[int]:
    """The bit positions set in a flag field, most significant first.

    Positions are numbered the standard's way — bit 7 is the msb of a byte (Annex C-4.1) — so a
    one-byte flag whose only set bit is `Antenna Status` (T5 bit a) reports `[7]`, which is what
    §3.12.5's own diagram calls it.
    """
    bits = 8 * width
    return [bit for bit in range(bits - 1, -1, -1) if value >> bit & 1]


# ------------------------------------------------------------------ shared

def _require(data: bytes, offset: int, width: int, form: str) -> None:
    if offset < 0 or offset + width > len(data):
        raise CodecError(
            f"truncated {form} field: {width} byte(s) needed at offset {offset} but the payload "
            f"holds {len(data)}. A partial parse of a byte-aligned format reads the next field "
            "from the wrong offset, so this is a refusal rather than a best effort"
        )


#: The seven forms, and the pair of functions each one is read and written with. `gmtif.py`
#: drives every field through this table so a layout entry cannot name a form nothing implements
#: — and `test_every_form_the_layouts_use_is_implemented` checks the two agree.
READERS = {
    "I8": lambda d, o: read_unsigned(d, o, 1),
    "I16": lambda d, o: read_unsigned(d, o, 2),
    "I32": lambda d, o: read_unsigned(d, o, 4),
    "S8": lambda d, o: read_signed(d, o, 1),
    "S16": lambda d, o: read_signed(d, o, 2),
    "S32": lambda d, o: read_signed(d, o, 4),
    "S64": lambda d, o: read_signed(d, o, 8),
    "B16": lambda d, o: read_sign_magnitude(d, o, "B16"),
    "B32": lambda d, o: read_sign_magnitude(d, o, "B32"),
    "H32": lambda d, o: read_sign_magnitude(d, o, "H32"),
    "BA16": lambda d, o: read_binary_angle(d, o, 2),
    "BA32": lambda d, o: read_binary_angle(d, o, 4),
    "SA16": lambda d, o: read_signed_binary_angle(d, o, 2),
    "SA32": lambda d, o: read_signed_binary_angle(d, o, 4),
}

WRITERS = {
    "I8": lambda v: write_unsigned(v, 1),
    "I16": lambda v: write_unsigned(v, 2),
    "I32": lambda v: write_unsigned(v, 4),
    "S8": lambda v: write_signed(v, 1),
    "S16": lambda v: write_signed(v, 2),
    "S32": lambda v: write_signed(v, 4),
    "S64": lambda v: write_signed(v, 8),
    "B16": lambda v: write_sign_magnitude(v, "B16"),
    "B32": lambda v: write_sign_magnitude(v, "B32"),
    "H32": lambda v: write_sign_magnitude(v, "H32"),
    "BA16": lambda v: write_binary_angle(v, 2),
    "BA32": lambda v: write_binary_angle(v, 4),
    "SA16": lambda v: write_signed_binary_angle(v, 2),
    "SA32": lambda v: write_signed_binary_angle(v, 4),
}

#: Byte width per form, so a layout table does not have to restate it and cannot disagree.
WIDTHS = {"I8": 1, "I16": 2, "I32": 4, "S8": 1, "S16": 2, "S32": 4, "S64": 8,
          "B16": 2, "B32": 4, "H32": 4, "BA16": 2, "BA32": 4, "SA16": 2, "SA32": 4,
          "E8": 1, "FL8": 1, "FL16": 2, "FL40": 5, "FL64": 8}

# `En` and `FL` are unsigned integers on the wire — Annex C-4.8 and C-4.9 give them a meaning,
# not an encoding — so they read and write as `In` of the same width. They are kept as separate
# form names because a row set that called an enumeration `I8` would lose the fact that its value
# space is a table, and that fact is what makes a reserved value `unresolved_raw` rather than a
# number.
for _form, _width in (("E8", 1), ("FL8", 1), ("FL16", 2), ("FL40", 5), ("FL64", 8)):
    READERS[_form] = (lambda w: (lambda d, o: read_unsigned(d, o, w)))(_width)
    WRITERS[_form] = (lambda w: (lambda v: write_unsigned(v, w)))(_width)
del _form, _width


def read(form: str, data: bytes, offset: int) -> int | float:
    return READERS[form](data, offset)


def write(form: str, value: int | float) -> bytes:
    return WRITERS[form](value)


# ------------------------------------------------------------------ raw <-> value
#
# The adapter holds DECODED values, not wire bytes, and re-encodes from them — which is only safe
# because `test_cdm_gmtif_codec` asserts `write(read(b)) == b` exhaustively for the 8- and 16-bit
# forms and by boundary sampling for the 32-bit ones. These two helpers exist for the one place
# that genuinely needs the integer rather than the value: guide §E.7 requires the delta-position
# reconstruction to be done on the ENCODED integers, in signed 32-bit arithmetic for latitude and
# unsigned 32-bit arithmetic for longitude, with the longitude case wrapping mod 2^32.

def from_raw(form: str, raw: int) -> int | float:
    """The value a wire integer decodes to, without going through a buffer."""
    return read(form, int(raw).to_bytes(WIDTHS[form], "big", signed=False), 0)


def to_raw(form: str, value: int | float) -> int:
    """The wire integer a value encodes to, as an UNSIGNED integer of the field's width."""
    return int.from_bytes(write(form, value), "big", signed=False)


#: The value a form can hold, as (minimum, maximum, LSB). Stated once here rather than derived at
#: each call site, because `snap` needs the bounds to refuse and the egress row set quotes the LSBs
#: as properties of the format. Every one of these is the standard's own: Annex C-4.6's 360/2^n,
#: C-4.7's 180/2^n and C-4.5's magnitude-over-2^fraction.
def _bounds(form: str) -> tuple[float, float, float]:
    bits = 8 * WIDTHS[form]
    if form.startswith("BA"):
        lsb = BA_NUMERATOR / float(1 << (bits - 3))
        return 0.0, lsb * ((1 << bits) - 1), lsb
    if form.startswith("SA"):
        lsb = SA_NUMERATOR / float(1 << (bits - 2))
        return -lsb * (1 << (bits - 1)), lsb * ((1 << (bits - 1)) - 1), lsb
    if form in SIGN_MAGNITUDE:
        _bits, fraction = SIGN_MAGNITUDE[form]
        lsb = 1.0 / float(1 << fraction)
        limit = ((1 << (bits - 1)) - 1) * lsb
        return -limit, limit, lsb
    if form.startswith("S"):
        return float(-(1 << (bits - 1))), float((1 << (bits - 1)) - 1), 1.0
    return 0.0, float((1 << bits) - 1), 1.0


def snap(form: str, value: int | float) -> int | float:
    """The nearest value this form can carry — and a REFUSAL if the value is not in its range.

    The writers above refuse a value off their grid, and that is right for the round-trip path: a
    parked wire value re-encodes exactly or something has gone wrong. It is wrong for the
    CDM-native egress path, where the input is a `Position` in decimal degrees that has no reason
    to sit on a binary-angle grid — and refusing every such position would make CDM-native egress
    impossible rather than careful.

    QUANTISING IS LEGITIMATE AND CLAMPING IS NOT, AND NEITHER IS WRAPPING. Rounding to a field's
    own LSB is the format's stated resolution being applied, not a translator losing something:
    `SA32` resolves 4.7 mm, `BA32` 9.3 mm, `L4` a centimetre, `L6` a millimetre per second. A value
    OUTSIDE the field's range is a different thing entirely, and the first version of this function
    got it wrong in the worst available way — it masked the encoded integer to the field's width,
    so a latitude of 95 deg came back as **-85 deg**, on the other side of the equator, and a `B16`
    of 300 came back as -44. Clamping to the boundary would have been less bad and still wrong: it
    would put a contact at exactly 90 deg and say nothing. So the range is checked and a value
    outside it is a refusal quoting the value and the range, which is what a caller handing an
    impossible coordinate to an encoder needs to be told.
    """
    low, high, lsb = _bounds(form)
    if not low <= value <= high:
        raise CodecError(
            f"{form} cannot carry {value!r}: the field's range is [{low!r}, {high!r}] with an LSB "
            f"of {lsb!r}. Quantising a value to a field's own resolution is what encoding is; "
            "moving a value INTO range is not, and neither masking it to the field width nor "
            "clamping it to the boundary would tell you that the value was impossible"
        )
    return from_raw(form, _nearest_raw(form, value))


def _nearest_raw(form: str, value: int | float) -> int:
    """The encoded integer nearest to `value`. Callers check the range first; this does not."""
    bits = 8 * WIDTHS[form]
    if form.startswith("BA"):
        raw = int(round(value * (1 << (bits - 3)) / BA_NUMERATOR))
    elif form.startswith("SA"):
        raw = int(round(value * (1 << (bits - 2)) / SA_NUMERATOR))
    elif form in SIGN_MAGNITUDE:
        _bits, fraction = SIGN_MAGNITUDE[form]
        magnitude = int(round(abs(value) * (1 << fraction)))
        sign = 1 if value < 0 else 0
        raw = (sign << (bits - 1)) | magnitude
    else:
        raw = int(round(value))
        if form.startswith("S"):
            raw &= (1 << bits) - 1
    return raw & ((1 << bits) - 1)
