"""The AEDP-4607 Annex C wire codec, tested against hand-computed byte patterns.

This suite exists BEFORE any segment logic sits on the codec, and it is separate from
`test_cdm_gmtif_adapter.py` on purpose. A binary format's decoding errors do not raise: a `B16`
read as two's complement returns a plausible number, an `SA32` scaled by `BAn`'s exponent returns
a plausible latitude, and both survive every structural check the adapter can make. So the layer
is judged on its own, against bytes worked out by hand from the standard's own definitions, and
the strongest two cases in here are the two worked examples the standard itself prints:

    Annex C-4.6:  BA16 0101100100011100  ==  125.31006 deg
    Annex C-4.7:  SA16 1100111001100110  == -34.876099 deg

Those two are not our arithmetic checked against our arithmetic. They are the document's own
numbers, and an implementation that reproduces both has the sign convention, the exponent and the
scale factor right in one shot — which is the whole hazard, because BA and SA differ in TWO ways
at once (signedness and a one-bit exponent shift) and a single shared helper gets one of them
wrong silently.

EXHAUSTION WHERE IT IS AFFORDABLE
---------------------------------
`encode(decode(b)) == b` is asserted over EVERY 16-bit pattern for the 16-bit forms and every
8-bit pattern for the 8-bit ones — 65 536 and 256 cases, which cost milliseconds and remove the
possibility that a boundary was missed. The 32-bit forms are sampled at their boundaries plus a
deterministic spread, because 4 billion is not affordable and the boundaries are where the bugs
are anyway.
"""
import pytest

from synapse_cdm.adapters import gmtif_codec as codec


# ============================================================ unsigned and signed integers


@pytest.mark.parametrize("data,width,expected", [
    (b"\x00", 1, 0),
    (b"\xff", 1, 255),
    (b"\x01\x00", 2, 256),
    (b"\xff\xff", 2, 65535),
    (b"\x00\x00\x01\x00", 4, 256),
    (b"\xff\xff\xff\xff", 4, 4294967295),
    # The byte-order case, and the reason `struct` with a native format is banned in this
    # package: on a little-endian host a native read of these four bytes is 1, not 16 777 216.
    (b"\x01\x00\x00\x00", 4, 16777216),
])
def test_unsigned_integers_are_big_endian(data, width, expected):
    assert codec.read_unsigned(data, 0, width) == expected
    assert codec.write_unsigned(expected, width) == data


@pytest.mark.parametrize("data,width,expected", [
    (b"\x00", 1, 0),
    (b"\x7f", 1, 127),
    (b"\x80", 1, -128),
    (b"\xff", 1, -1),
    (b"\x7f\xff", 2, 32767),
    (b"\x80\x00", 2, -32768),
    (b"\xff\xff", 2, -1),
    (b"\x7f\xff\xff\xff", 4, 2147483647),
    (b"\x80\x00\x00\x00", 4, -2147483648),
    # D9 Sensor Position Altitude is S32 in centimetres with a stated floor of -50 000 cm.
    (b"\xff\xff\x3c\xb0", 4, -50000),
])
def test_signed_integers_are_twos_complement(data, width, expected):
    """Annex C-4.4 states the rule in words: "complement all the bits … and then add 1"."""
    assert codec.read_signed(data, 0, width) == expected
    assert codec.write_signed(expected, width) == data


def test_a_signed_read_of_an_unsigned_field_is_the_error_this_split_prevents():
    """0xFFFF is 65 535 as I16 and -1 as S16, and the format uses both forms.

    D19 Sensor Speed Uncertainty is I16 with a range of 0 to 65 535; D32.7 Target Velocity
    Line-of-Sight is S16 with a range of -32 768 to +32 767. The same bytes, two answers, and
    nothing in the payload distinguishes them — only the layout does.
    """
    assert codec.read_unsigned(b"\xff\xff", 0, 2) == 65535
    assert codec.read_signed(b"\xff\xff", 0, 2) == -1


@pytest.mark.parametrize("width", [1, 2, 4])
def test_an_out_of_range_integer_is_a_refusal_not_a_truncation(width):
    with pytest.raises(codec.CodecError, match="outside"):
        codec.write_unsigned(1 << (8 * width), width)
    with pytest.raises(codec.CodecError, match="outside"):
        codec.write_signed(1 << (8 * width - 1), width)


# ================================================= sign-magnitude binary decimals, C-4.5


@pytest.mark.parametrize("data,form,expected", [
    # B16 is 1 sign + 8 integer + 7 fraction, LSB 2^-7. The standard states all three of these:
    # "a maximum value of 256-1/128, a minimum value of -256+1/128, and a smallest non-zero
    # value of 0.0078125 (= 1/128 = 2^-7)".
    (b"\x00\x00", "B16", 0.0),
    (b"\x00\x01", "B16", 0.0078125),
    (b"\x7f\xff", "B16", 255.9921875),
    (b"\xff\xff", "B16", -255.9921875),
    (b"\x80\x01", "B16", -0.0078125),
    # 1.0 is integer part 1, fraction 0 -> the integer part starts at bit 7, so 1<<7 = 0x0080.
    (b"\x00\x80", "B16", 1.0),
    (b"\x80\x80", "B16", -1.0),
    # D26 Dwell Area Range Half Extent is B16 in kilometres: 12.5 km = 12 + 64/128.
    (b"\x06\x40", "B16", 12.5),
    # B32 is 1 + 8 + 23, LSB 2^-23.
    (b"\x00\x00\x00\x00", "B32", 0.0),
    (b"\x00\x00\x00\x01", "B32", 1.1920928955078125e-07),
    (b"\x7f\xff\xff\xff", "B32", 255.99999988079071),
    (b"\x00\x80\x00\x00", "B32", 1.0),
    (b"\x80\x80\x00\x00", "B32", -1.0),
    # H32 is 1 + 15 + 16, LSB 2^-16 — a DIFFERENT radix point in a field of the same width.
    (b"\x00\x00\x00\x00", "H32", 0.0),
    (b"\x00\x00\x00\x01", "H32", 1.52587890625e-05),
    (b"\x00\x01\x00\x00", "H32", 1.0),
    (b"\x80\x01\x00\x00", "H32", -1.0),
    (b"\x7f\xff\xff\xff", "H32", 32767.999984741211),
])
def test_sign_magnitude_decimals_have_the_radix_point_the_standard_states(data, form, expected):
    assert codec.read_sign_magnitude(data, 0, form) == pytest.approx(expected, rel=0, abs=1e-12)


def test_b32_and_h32_are_the_same_width_and_a_different_number():
    """The trap the H32 footnote creates: one 32-bit pattern, two radix points, 2^15 apart.

    Guide Annex M added H32 to Annex C-4.5 as "a special case of a Signed Binary Decimal which
    provides a higher range and less decimal precision". H13, H14 and H22 are H32; H15, H30 and
    H31 are B32. Reading one as the other is undetectable in the bytes.
    """
    pattern = b"\x00\x80\x00\x00"
    assert codec.read_sign_magnitude(pattern, 0, "B32") == 1.0
    assert codec.read_sign_magnitude(pattern, 0, "H32") == 128.0
    assert codec.read_sign_magnitude(pattern, 0, "H32") == 1.0 * (1 << 7)


def test_a_negative_b16_read_as_twos_complement_is_wrong_by_512():
    """Why C-4.5's "expressed in sign magnitude" is quoted in the module docstring.

    0xFFFF is -255.9921875 in sign-magnitude and -1/128 as a two's-complement fixed-point
    value with the same radix point. Both are plausible dwell-area extents.
    """
    assert codec.read_sign_magnitude(b"\xff\xff", 0, "B16") == -255.9921875
    twos_complement_reading = codec.read_signed(b"\xff\xff", 0, 2) / 128.0
    assert twos_complement_reading == -0.0078125
    assert twos_complement_reading != codec.read_sign_magnitude(b"\xff\xff", 0, "B16")


def test_sign_magnitude_has_two_zeros_and_the_codec_keeps_them_apart():
    """0x8000 and 0x0000 are different bytes that mean the same number.

    This is why the adapter parks the RAW wire integer and re-encodes from it rather than from
    the decoded float: a packet that arrived with a negative zero has to leave with one, and a
    float 0.0 cannot say which of the two it was.
    """
    assert codec.read_sign_magnitude(b"\x00\x00", 0, "B16") == 0.0
    assert codec.read_sign_magnitude(b"\x80\x00", 0, "B16") == 0.0
    assert codec.write_sign_magnitude(0.0, "B16") == b"\x00\x00"
    assert codec.write_sign_magnitude(-0.0, "B16") == b"\x80\x00"


def test_a_value_off_the_sign_magnitude_grid_is_a_refusal():
    """A measurement that does not fit the field is not rounded to fit it."""
    with pytest.raises(codec.CodecError, match="not a whole multiple"):
        codec.write_sign_magnitude(0.001, "B16")     # 1/1000 is not a multiple of 1/128
    with pytest.raises(codec.CodecError, match="exceeds"):
        codec.write_sign_magnitude(300.0, "B16")


# ==================================================== binary angles, C-4.6 and C-4.7
#
# The two worked examples in this block are the document's own, and they are the strongest
# assertions in this file for that reason.


def test_the_standards_own_ba16_worked_example():
    """Annex C-4.6: "the BA16-encoded value of 0101100100011100 equals an angle of 125.31006"."""
    pattern = int("0101100100011100", 2).to_bytes(2, "big")
    assert pattern == b"\x59\x1c"
    assert codec.read_binary_angle(pattern, 0, 2) == pytest.approx(125.31006, abs=5e-6)
    # And back, byte for byte.
    assert codec.write_binary_angle(codec.read_binary_angle(pattern, 0, 2), 2) == pattern


def test_the_standards_own_sa16_worked_example():
    """Annex C-4.7: "the angle of -34.876099 equals an SA16-encoded value of 1100111001100110"."""
    pattern = int("1100111001100110", 2).to_bytes(2, "big")
    assert pattern == b"\xce\x66"
    assert codec.read_signed_binary_angle(pattern, 0, 2) == pytest.approx(-34.876099, abs=5e-6)
    assert codec.write_signed_binary_angle(
        codec.read_signed_binary_angle(pattern, 0, 2), 2) == pattern


@pytest.mark.parametrize("data,width,expected", [
    # C-4.6's own bit-value table: "a 1 in the most significant bit shall represent 180 deg, a 1
    # in the next bit shall represent 90 deg, and so on".
    (b"\x80\x00", 2, 180.0),
    (b"\x40\x00", 2, 90.0),
    (b"\x20\x00", 2, 45.0),
    (b"\x10\x00", 2, 22.5),
    (b"\x00\x00", 2, 0.0),
    (b"\xff\xff", 2, 359.9945068359375),      # the table's stated BA16 maximum
    (b"\x00\x01", 2, 0.0054931640625),        # the BA16 LSB, 360/2^16
    (b"\x80\x00\x00\x00", 4, 180.0),
    (b"\xff\xff\xff\xff", 4, 359.99999991618097),
    (b"\x00\x00\x00\x01", 4, 8.381903171539307e-08),   # the BA32 LSB, 360/2^32
])
def test_unsigned_binary_angles_scale_by_360_over_two_to_the_n(data, width, expected):
    assert codec.read_binary_angle(data, 0, width) == pytest.approx(expected, rel=0, abs=1e-12)


@pytest.mark.parametrize("data,width,expected", [
    # C-4.7's own table: "a 1 in the second bit shall represent 45 deg, a 1 in the third
    # 22.5 deg". The msb is the SIGN, which is the whole difference from BAn.
    (b"\x40\x00", 2, 45.0),
    (b"\x20\x00", 2, 22.5),
    (b"\x00\x00", 2, 0.0),
    (b"\x7f\xff", 2, 89.99725341796875),      # the table's stated SA16 maximum for pitch/roll
    (b"\x80\x00", 2, -90.0),                  # the table's stated minimum, exactly -90
    (b"\xc0\x00", 2, -45.0),
    (b"\x00\x01", 2, 0.00274658203125),       # the SA16 LSB, 180/2^16
    (b"\x7f\xff\xff\xff", 4, 89.99999995809048),
    (b"\x80\x00\x00\x00", 4, -90.0),
    (b"\x00\x00\x00\x01", 4, 4.190951585769653e-08),   # the SA32 LSB, 180/2^32
])
def test_signed_binary_angles_scale_by_180_over_two_to_the_n(data, width, expected):
    assert codec.read_signed_binary_angle(data, 0, width) == pytest.approx(
        expected, rel=0, abs=1e-12)


def test_the_two_angle_forms_differ_in_both_ways_at_once():
    """One pattern, two readings, and the difference is not a factor of two.

    0x8000 is 180 deg as BA16 (the msb IS 180) and -90 deg as SA16 (the msb is the sign and the
    magnitude is zero). A codec that shared one helper and only fixed the exponent would read
    -90 as +90; one that only fixed the signedness would read 180 as 360.
    """
    assert codec.read_binary_angle(b"\x80\x00", 0, 2) == 180.0
    assert codec.read_signed_binary_angle(b"\x80\x00", 0, 2) == -90.0


def test_binary_angle_conversion_is_exact_in_float64_and_that_is_a_claim():
    """The scale is 45/2^k, a dyadic rational, so no rounding is introduced.

    FORMAT_COVERAGE.md's settlement 6 claims the conversion is exact rather than hedging, and
    this is where the claim is kept: the decoded value multiplied back by the inverse scale
    returns the original integer with no residue at all, for every sampled pattern including the
    largest.
    """
    for raw in (0, 1, 2, 45, 32768, 2 ** 31 - 1, 2 ** 32 - 1):
        data = raw.to_bytes(4, "big")
        degrees = codec.read_binary_angle(data, 0, 4)
        assert degrees * (1 << 29) / 45 == float(raw)
        assert codec.write_binary_angle(degrees, 4) == data


# ================================================================== exhaustive round trips


@pytest.mark.parametrize("form", ["I8", "S8", "E8", "FL8"])
def test_every_eight_bit_pattern_round_trips(form):
    for raw in range(256):
        data = bytes([raw])
        assert codec.write(form, codec.read(form, data, 0)) == data


@pytest.mark.parametrize("form", ["I16", "S16", "B16", "BA16", "SA16", "FL16"])
def test_every_sixteen_bit_pattern_round_trips(form):
    """65 536 cases. Exhaustion is affordable here, so there is no boundary left to miss."""
    for raw in range(1 << 16):
        data = raw.to_bytes(2, "big")
        assert codec.write(form, codec.read(form, data, 0)) == data, f"{form} {raw:#06x}"


@pytest.mark.parametrize("form", ["I32", "S32", "B32", "H32", "BA32", "SA32"])
def test_the_thirty_two_bit_forms_round_trip_at_their_boundaries_and_across_a_spread(form):
    """Boundaries plus a deterministic spread — never `random`, which makes a failure unrepeatable."""
    samples = {0, 1, 2, 0x7F, 0x80, 0xFF, 0x7FFF, 0x8000, 0xFFFF,
               0x007FFFFF, 0x00800000, 0x7FFFFFFF, 0x80000000, 0x80000001, 0xFFFFFFFF}
    samples |= {(i * 2654435761) & 0xFFFFFFFF for i in range(1, 400)}
    for raw in sorted(samples):
        data = raw.to_bytes(4, "big")
        assert codec.write(form, codec.read(form, data, 0)) == data, f"{form} {raw:#010x}"


# ============================================================== alphanumerics, §2.3 / Annex A


def test_a_fixed_width_alphanumeric_strips_trailing_pad_and_restores_it():
    """§2.3: "left-justified, with unused bytes filled with the … space character"."""
    assert codec.read_bcs(b"AB12345678", 0, 10, field="P8") == "AB12345678"
    assert codec.read_bcs(b"TAIL7     ", 0, 10, field="P8") == "TAIL7"
    assert codec.write_bcs("TAIL7", 10, field="P8") == b"TAIL7     "
    # An all-pad field is a STATED ABSENCE — M1 says so in its own text — and comes back as "".
    assert codec.read_bcs(b"            ", 0, 12, field="M1") == ""
    assert codec.write_bcs("", 12, field="M1") == b" " * 12


def test_internal_and_leading_spaces_survive_because_only_trailing_pad_is_padding():
    """A non-conformant right-justified value still round-trips byte for byte.

    Stripping both ends would be tidier and would silently rewrite a producer's field. The
    padding rule is about UNUSED bytes at the end, so that is the only thing removed.
    """
    for text in ("A B", "  AB", "A  B  "):
        raw = codec.write_bcs(text.rstrip(" "), 8, field="F1")
        assert codec.read_bcs(raw, 0, 8, field="F1") == text.rstrip(" ")
    assert codec.read_bcs(b"  AB    ", 0, 8, field="F1") == "  AB"
    assert codec.write_bcs("  AB", 8, field="F1") == b"  AB    "


def test_free_text_is_not_stripped_because_its_width_is_the_remainder():
    """F3 has no declared width — "nn=1 to 65515" — so its trailing spaces are its length."""
    assert codec.read_bcs(b"MSG   ", 0, 6, field="F3", strip=False) == "MSG   "
    assert codec.read_bcs(b"MSG   ", 0, 6, field="F3", strip=True) == "MSG"


@pytest.mark.parametrize("byte", [0x00, 0x01, 0x09, 0x1F, 0x7F, 0x80, 0xA0, 0xFF])
def test_a_byte_outside_the_bcs_is_a_refusal_quoting_the_offset(byte):
    """Annex A: "the use of ECS characters in this standard shall be restricted to the BCS Subset".

    A "shall", so a 0xE9 in a Platform ID is a packet with an error. Re-decoding it as Latin-1
    would put an "e-acute" into an operator's platform list that nobody transmitted, and a
    replacement character would put a question mark there — both are invented bytes.
    """
    payload = b"AB" + bytes([byte]) + b"CD"
    with pytest.raises(codec.CodecError, match=r"offset 2"):
        codec.read_bcs(payload, 0, 5, field="P8")


@pytest.mark.parametrize("byte", [0x0A, 0x0C, 0x0D])
def test_the_three_bcs_control_characters_are_in_the_set(byte):
    """Annex A lists LF, FF and CR beside the printable range, and F3 is what they are for."""
    payload = b"L1" + bytes([byte]) + b"L2"
    assert codec.read_bcs(payload, 0, 5, field="F3", strip=False) == \
        "L1" + chr(byte) + "L2"


def test_an_overlong_alphanumeric_is_a_refusal_not_a_truncation():
    with pytest.raises(codec.CodecError, match="Truncating"):
        codec.write_bcs("AB123456789", 10, field="P8")


# ============================================================================ flags


def test_flag_bit_positions_are_numbered_the_standards_way():
    """Annex C-4.1: bit 7 is the msb of a byte. T5's "a = Antenna Status" is bit 7."""
    assert codec.set_bits(0b10000000, 1) == [7]
    assert codec.set_bits(0b00000001, 1) == [0]
    assert codec.set_bits(0b10010001, 1) == [7, 4, 0]
    assert codec.set_bits(0, 1) == []
    # P6 Packet Security Code is a 16-bit flag field, and 0x0001 is its lowest codeword bit.
    assert codec.set_bits(0x0001, 2) == [0]
    assert codec.set_bits(0x8000, 2) == [15]


# ======================================================================= truncation


@pytest.mark.parametrize("form,width", [("I32", 4), ("SA32", 4), ("B16", 2), ("H32", 4)])
def test_reading_past_the_end_is_a_refusal_quoting_what_was_needed(form, width):
    """A partial parse of a byte-aligned format reads the NEXT field from the wrong offset."""
    with pytest.raises(codec.CodecError, match="truncated"):
        codec.read(form, b"\x00" * (width - 1), 0)


def test_every_form_the_layouts_use_is_implemented():
    """The table `gmtif.py` drives its fields through, checked against the codec's own tables.

    A layout entry naming a form nothing implements would fail at parse time on the one fixture
    that used it, which for a rarely-populated Optional field could be a long time later.
    """
    from synapse_cdm.adapters import gmtif
    forms = {form for layout in gmtif.LAYOUTS.values() for _, _, form, *_ in layout}
    forms |= {form for layout in gmtif.SUBRECORDS.values() for _, _, form, *_ in layout}
    unimplemented = sorted(f for f in forms
                           if f not in ("A", "REST") and
                           (f not in codec.READERS or f not in codec.WRITERS
                            or f not in codec.WIDTHS))
    assert not unimplemented, f"layouts name forms the codec does not implement: {unimplemented}"
