"""decode_attribute against the vectors of the handoff and against vectors derived by hand.

Gates held here: G-R18 (SPEC:78 and its continuation paragraphs SPEC:80 and SPEC:281, the
latter for its decoder-precedence sentences) and G-R20 (SPEC:110). The acceptance vectors
V-* and N-* are bound one test id per case id.

WHERE THE EXPECTED VALUES COME FROM
-----------------------------------
- The 14 positive and 30 negative vectors: the packaged fixtures, which are byte copies of the
  handoff's. Their `path` (CR-L01) is not in the fixtures and is written here by hand.
- Everything else: literals written here, each derived from the layout tables at SPEC:80-108 by
  hand, with the arithmetic in a comment where it is not obvious. Byte strings are built by the
  tests' own encoder (`hla_support.encode_spatial`), which one fully hand-composed hex literal
  below anchors; nothing here reads an offset or a length from `synapse_hla.codec`.
- The fuzz compares the decoder with a reference decoder written in this file from the same
  tables; that reference is a second implementation, not a source of literals.
"""

import ast
import math
import pathlib
import random
import struct
import xml.etree.ElementTree as ElementTree

import pytest

import synapse_hla
from hla_support import (
    SPATIAL_TABLE, assert_strict_equal, canonical, case, encode_spatial, fixture_json, fom_modules,
    reencode_spatial, spatial_float_offsets, validator,
)
from synapse_hla import HlaError, decode_attribute

R = "\ufffd"
CODEC_SOURCE = pathlib.Path(synapse_hla.__file__).resolve().parent / "codec.py"

#: The codes a decode may raise, and nothing else (SPEC:193, COD-05).
DECODE_CODES = {"E_LIMIT", "E_UNSUBSCRIBED_ATTRIBUTE", "E_SPATIAL_VARIANT", "E_ATTRIBUTE_LENGTH",
                "E_BOOLEAN", "E_NONFINITE"}


def refusal(name, value):
    """(code, path) of the one HlaError decoding raises; anything else fails the test."""
    with pytest.raises(HlaError) as info:
        decode_attribute(name, value)
    error = info.value
    assert type(error) is HlaError
    assert error.code in DECODE_CODES
    return error.code, error.path


_VALIDATOR = None


def decoded_schema():
    global _VALIDATOR
    if _VALIDATOR is None:
        _VALIDATOR = validator("decoded-attribute.schema.json")
    return _VALIDATOR


def by_id(fixture, vector_id):
    matches = [v for v in fixture_json(fixture) if v["id"] == vector_id]
    assert len(matches) == 1, vector_id
    return matches[0]


# ============================================================ the handoff's 44 vectors (V-*, N-*)

#: The 14 positive vector ids, written out so that the parameters exist even if the fixture is
#: damaged (the damage then fails these tests instead of stopping collection).
POSITIVE_IDS = ("SPATIAL-1", "SPATIAL-2", "SPATIAL-3", "SPATIAL-4", "SPATIAL-5", "SPATIAL-6",
                "SPATIAL-7", "SPATIAL-8", "SPATIAL-9", "ID-123", "TYPE-PLATFORM", "FORCE-1",
                "FORCE-255", "SPATIAL-PADDING")


@pytest.mark.parametrize("vector_id", [pytest.param(i, marks=case(f"V-{i}"), id=i)
                                       for i in POSITIVE_IDS])
@case("G-R45", "G-R01")
def test_a_positive_vector_decodes_to_its_twin_exactly(vector_id):
    vector = by_id("attributes-positive.json", vector_id)
    data = bytes.fromhex(vector["hex"])
    # The handoff's own layout check (verify_bundle.py, "14 positive attribute fixtures match
    # their declared wire layouts"), done by the tests' encoder: the twin rebuilds the bytes.
    assert encode_twin(vector["name"], vector["expected"]) == data
    result = decode_attribute(vector["name"], data)
    assert list(result) == ["name", "value"]
    assert result["name"] == vector["name"]
    assert_strict_equal(result["value"], vector["expected"])
    assert canonical(result["value"]) == canonical(vector["expected"])
    decoded_schema().validate(result)


def encode_twin(name, value):
    """The wire bytes of a decoded value by the tests' own encoders (SPEC:81-84, SPEC:88-108)."""
    if name == "Spatial":
        return reencode_spatial(value)
    if name == "EntityIdentifier":
        return struct.pack(">HHH", value["site"], value["application"], value["entity"])
    if name == "EntityType":
        return struct.pack(">BBHBBBB", *(value[k] for k in (
            "kind", "domain", "country", "category", "subcategory", "specific", "extra")))
    return bytes([value["value"]])


#: (vector id, code, CR-L01 path). The codes are the fixture's (asserted equal below); the paths
#: are derived by hand: the attribute name, plus `/32` for the frozen octet and `/<offset>` of the
#: first non-finite float, which is the offset in the vector's own id.
NEGATIVE = (
    ("TRUNC-1", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-1", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-2", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-2", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-3", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-3", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-4", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-4", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-5", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-5", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-6", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-6", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-7", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-7", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-8", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-8", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("TRUNC-9", "E_ATTRIBUTE_LENGTH", "Spatial"), ("TRAIL-9", "E_ATTRIBUTE_LENGTH", "Spatial"),
    ("ALG-0", "E_SPATIAL_VARIANT", "Spatial"), ("ALG-10", "E_SPATIAL_VARIANT", "Spatial"),
    ("ALG-255", "E_SPATIAL_VARIANT", "Spatial"),
    ("NONFINITE-8", "E_NONFINITE", "Spatial/8"), ("NONFINITE-36", "E_NONFINITE", "Spatial/36"),
    ("NONFINITE-48", "E_NONFINITE", "Spatial/48"), ("NONFINITE-60", "E_NONFINITE", "Spatial/60"),
    ("NONFINITE-72", "E_NONFINITE", "Spatial/72"),
    ("BOOL-2", "E_BOOLEAN", "Spatial/32"),
    ("LENGTH-EntityIdentifier", "E_ATTRIBUTE_LENGTH", "EntityIdentifier"),
    ("LENGTH-EntityType", "E_ATTRIBUTE_LENGTH", "EntityType"),
    ("LENGTH-ForceIdentifier", "E_ATTRIBUTE_LENGTH", "ForceIdentifier"),
)


@pytest.mark.parametrize("vector_id,code,path", [
    pytest.param(i, c, p, marks=case(f"N-{i}"), id=i) for i, c, p in NEGATIVE])
def test_a_negative_vector_raises_its_code_at_its_path(vector_id, code, path):
    vector = by_id("attributes-negative.json", vector_id)
    assert vector["code"] == code
    data = bytes.fromhex(vector["hex"])
    # The handoff's own class check (verify_bundle.py, "30 negative attribute fixtures yield their
    # specified error class"), done by this file's reference decoder.
    assert reference_outcome(vector["name"], data) == ("err", code, path)
    assert refusal(vector["name"], data) == (code, path)


def test_the_handoff_has_exactly_these_44_vectors():
    assert [v["id"] for v in fixture_json("attributes-positive.json")] == list(POSITIVE_IDS)
    assert [v["id"] for v in fixture_json("attributes-negative.json")] == [n[0] for n in NEGATIVE]


# ========================================================= the three fixed-size attributes, SPEC:80

#: (hex, decoded value). Big-endian by hand: 12 34 -> 0x1234 = 4660, 56 78 -> 22136,
#: 9a bc -> 39612 (a little-endian reader would give 13330, 30806, 48282); 80 00 -> 32768 is
#: unsigned (a signed reader would give -32768).
ENTITY_IDENTIFIERS = (
    ("123456789abc", {"site": 4660, "application": 22136, "entity": 39612}),
    ("ffffffffffff", {"site": 65535, "application": 65535, "entity": 65535}),
    ("000000000000", {"site": 0, "application": 0, "entity": 0}),
    ("8000000100ff", {"site": 32768, "application": 1, "entity": 255}),
    ("000100020003", {"site": 1, "application": 2, "entity": 3}),
)

#: (hex, decoded value). Country is the only two-octet field: 03 04 -> 772, e1 00 -> 57600
#: (little-endian 225), 80 01 -> 32769. Unknown enumerations (kind 255, kind 9) are kept (R19).
ENTITY_TYPES = (
    ("0102030405060708", {"kind": 1, "domain": 2, "country": 772, "category": 5,
                          "subcategory": 6, "specific": 7, "extra": 8}),
    ("ffffffffffffffff", {"kind": 255, "domain": 255, "country": 65535, "category": 255,
                          "subcategory": 255, "specific": 255, "extra": 255}),
    ("0000000000000000", {"kind": 0, "domain": 0, "country": 0, "category": 0,
                          "subcategory": 0, "specific": 0, "extra": 0}),
    ("ff00e1000000ff00", {"kind": 255, "domain": 0, "country": 57600, "category": 0,
                          "subcategory": 0, "specific": 255, "extra": 0}),
    ("09ff800110203040", {"kind": 9, "domain": 255, "country": 32769, "category": 16,
                          "subcategory": 32, "specific": 48, "extra": 64}),
)


@case("G-R18", paragraphs=("SPEC:80",))
@pytest.mark.parametrize("hexvalue,expected", ENTITY_IDENTIFIERS)
def test_entity_identifier_is_three_big_endian_unsigned_16_bit_fields(hexvalue, expected):
    """SPEC:81: site at 0, application at 2, entity at 4. 0.0.0 decodes: null is R19's business."""
    result = decode_attribute("EntityIdentifier", bytes.fromhex(hexvalue))
    assert_strict_equal(result, {"name": "EntityIdentifier", "value": expected})
    decoded_schema().validate(result)


@case("G-R18", paragraphs=("SPEC:80",))
@pytest.mark.parametrize("hexvalue,expected", ENTITY_TYPES)
def test_entity_type_is_seven_fields_with_a_big_endian_country(hexvalue, expected):
    """SPEC:82: kind 0, domain 1, country uint16 at 2, category 4 ... extra 7."""
    result = decode_attribute("EntityType", bytes.fromhex(hexvalue))
    assert_strict_equal(result, {"name": "EntityType", "value": expected})
    decoded_schema().validate(result)


@case("G-R18", paragraphs=("SPEC:80",))
def test_force_identifier_preserves_every_octet_value():
    """SPEC:83: one unsigned octet, every value 0-255 preserved (the FOM names only 0-30)."""
    for octet in range(256):
        result = decode_attribute("ForceIdentifier", bytes([octet]))
        assert_strict_equal(result, {"name": "ForceIdentifier", "value": {"value": octet}})
    decoded_schema().validate(decode_attribute("ForceIdentifier", b"\xff"))


@case("G-R18")
@pytest.mark.parametrize("name,good", [("EntityIdentifier", 6), ("EntityType", 8),
                                       ("ForceIdentifier", 1)])
def test_a_fixed_size_attribute_must_have_its_exact_length(name, good):
    """R18 'Length must match exactly': every length from 0 to good+8 but the right one fails."""
    for length in range(good + 9):
        value = bytes(range(1, length + 1))
        if length == good:
            decode_attribute(name, value)
        else:
            assert refusal(name, value) == ("E_ATTRIBUTE_LENGTH", name), length


# ================================================= the Spatial layout, variant by variant (CDV-01)

#: Distinct non-zero values for every slot; all exactly representable (the binary32 ones as
#: binary32). No value repeats anywhere, so a decoder that swaps any two slots, or reads one
#: triple from another's offset, gets a different answer.
POSITION = (4194304.5, -1048576.25, 2097152.125)
ORIENTATION = (0.5, -1.25, 2.75)
VELOCITY = (-3.5, 7.25, 11.0625)
ACCELERATION = (0.125, -0.375, 1.5)
ANGULAR_VELOCITY = (-0.0625, 0.1875, -2.5)
PADDING = bytes.fromhex("01020304050607" "0a0b0c")


def full_variant(algorithm, frozen):
    """Bytes and the hand-expected decoded value of a variant with every slot distinct."""
    frame, _, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
    velocity = VELOCITY if v_at is not None else None
    acceleration = ACCELERATION if a_at is not None else None
    angular = ANGULAR_VELOCITY if w_at is not None else None
    data = encode_spatial(algorithm, POSITION, ORIENTATION, velocity, acceleration, angular,
                          frozen=frozen, padding=PADDING)
    expected = {
        "algorithm": algorithm,
        "frame": frame,
        "frozen": frozen == 1,
        "position_ecef_m": list(POSITION),
        "orientation_rad": list(ORIENTATION),
        "velocity_mps": None if velocity is None else list(velocity),
        "acceleration_mps2": None if acceleration is None else list(acceleration),
        "angular_velocity_radps": None if angular is None else list(angular),
        "padding_hex": "010203040506070a0b0c",
    }
    return data, expected


def test_the_test_encoder_is_anchored_by_a_hand_composed_value():
    """Algorithm 4 written out byte by byte, so that the encoder the other tests use is checked.

    binary64: 4194304.5 = 2^22 * (1 + 2^-23) -> exponent 1045 = 0x415, fraction bit 29
    -> 41500000 20000000; -1048576.25 = -2^20 * (1 + 2^-22) -> c1300000 40000000;
    2097152.125 = 2^21 * (1 + 2^-24) -> 41400000 10000000.
    binary32: 0.5 3f000000, -1.25 bfa00000, 2.75 40300000, -3.5 c0600000, 7.25 40e80000,
    11.0625 41310000, 0.125 3e000000, -0.375 bec00000, 1.5 3fc00000, -0.0625 bd800000,
    0.1875 3e400000, -2.5 c0200000.
    """
    by_hand = bytes.fromhex(
        "04" "01020304050607"
        "4150000020000000" "c130000040000000" "4140000010000000"
        "01" "0a0b0c"
        "3f000000" "bfa00000" "40300000"
        "c0600000" "40e80000" "41310000"
        "3e000000" "bec00000" "3fc00000"
        "bd800000" "3e400000" "c0200000")
    data, expected = full_variant(4, 1)
    assert len(by_hand) == 84 and data == by_hand
    assert_strict_equal(decode_attribute("Spatial", by_hand)["value"], expected)


@case("G-R18", paragraphs=("SPEC:80",))
@case("G-R20")
@pytest.mark.parametrize("frozen", [0, 1])
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_every_slot_of_every_variant_lands_where_the_table_puts_it(algorithm, frozen):
    """SPEC:84 and SPEC:88-108; R20's return keys, nulls and padding in wire order."""
    data, expected = full_variant(algorithm, frozen)
    result = decode_attribute("Spatial", data)
    assert_strict_equal(result, {"name": "Spatial", "value": expected})
    decoded_schema().validate(result)
    assert reencode_spatial(result["value"]) == data


@case("G-R20")
def test_the_spatial_shape_has_exactly_the_r20_keys_in_order():
    keys = ["algorithm", "frame", "frozen", "position_ecef_m", "orientation_rad", "velocity_mps",
            "acceleration_mps2", "angular_velocity_radps", "padding_hex"]
    nulls = {1: (True, True, True), 2: (False, True, True), 3: (False, True, False),
             4: (False, False, False), 5: (False, False, True), 6: (False, True, True),
             7: (False, True, False), 8: (False, False, False), 9: (False, False, True)}
    for algorithm, (no_v, no_a, no_w) in nulls.items():
        value = decode_attribute("Spatial", full_variant(algorithm, 0)[0])["value"]
        assert list(value) == keys
        assert (value["velocity_mps"] is None, value["acceleration_mps2"] is None,
                value["angular_velocity_radps"] is None) == (no_v, no_a, no_w)
        assert value["frame"] == ("WORLD" if algorithm <= 5 else "BODY")


@case("G-R18", paragraphs=("SPEC:80",))
def test_the_discriminator_is_octet_0_and_the_body_starts_at_8():
    """SPEC:84: the position is read at 8, not at 1 (the next octet) nor at 4."""
    data = bytearray(encode_spatial(1, (6378137.0, 0.0, 0.0)))
    data[1:8] = b"\xff" * 7
    value = decode_attribute("Spatial", bytes(data))["value"]
    assert value["algorithm"] == 1 and value["position_ecef_m"] == [6378137.0, 0.0, 0.0]
    assert value["padding_hex"] == "ffffffffffffff000000"


# ================================================================== the frozen octet (offset 32)

@case("G-R18", paragraphs=("SPEC:80",))
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_frozen_is_exactly_0_or_1(algorithm):
    """SPEC:92: 0 -> false, 1 -> true; 2, 3, 128 and 255 are E_BOOLEAN at Spatial/32."""
    assert decode_attribute("Spatial", full_variant(algorithm, 0)[0])["value"]["frozen"] is False
    assert decode_attribute("Spatial", full_variant(algorithm, 1)[0])["value"]["frozen"] is True
    for octet in (2, 3, 128, 255):
        data = encode_spatial(*full_variant_args(algorithm), frozen=octet, padding=PADDING)
        assert refusal("Spatial", data) == ("E_BOOLEAN", "Spatial/32"), octet


def full_variant_args(algorithm):
    _, _, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
    return (algorithm, POSITION, ORIENTATION, VELOCITY if v_at is not None else None,
            ACCELERATION if a_at is not None else None,
            ANGULAR_VELOCITY if w_at is not None else None)


# ======================================================= non-finite floats, every offset (CDV-01)

#: binary64 non-finite patterns: +inf, -inf, quiet NaN, signalling NaN, negative NaN with a
#: payload, all-ones NaN.
F64_NONFINITE = ("7ff0000000000000", "fff0000000000000", "7ff8000000000000", "7ff0000000000001",
                 "fff8000000000001", "7fffffffffffffff")
#: binary32 non-finite patterns: +inf, -inf, quiet NaN, the signalling NaN of COD-14
#: (7fa00000), the smallest signalling NaN, all-ones NaN.
F32_NONFINITE = ("7f800000", "ff800000", "7fc00000", "7fa00000", "7f800001", "ffffffff")

ALL_FLOAT_SLOTS = [(a, off) for a in range(1, 10) for off in spatial_float_offsets(a)]


def test_the_interpreted_offsets_are_the_tables():
    """The 15 interpreted offsets of the RV variants, and 102 (variant, offset) slots in all."""
    assert spatial_float_offsets(4) == [8, 16, 24, 36, 40, 44, 48, 52, 56, 60, 64, 68, 72, 76, 80]
    assert spatial_float_offsets(1) == [8, 16, 24, 36, 40, 44]
    assert spatial_float_offsets(3) == [8, 16, 24, 36, 40, 44, 48, 52, 56, 60, 64, 68]
    assert len(ALL_FLOAT_SLOTS) == 6 + 9 + 12 + 15 + 12 + 9 + 12 + 15 + 12 == 102


def put(data, offset, hexvalue):
    out = bytearray(data)
    raw = bytes.fromhex(hexvalue)
    out[offset:offset + len(raw)] = raw
    return bytes(out)


@case("G-R18")
@pytest.mark.parametrize("algorithm,offset", ALL_FLOAT_SLOTS,
                         ids=[f"alg{a}-at{o}" for a, o in ALL_FLOAT_SLOTS])
def test_a_non_finite_value_is_refused_in_every_interpreted_float(algorithm, offset):
    """R18: 'Reject nonfinite values in every interpreted float, including acceleration and
    angular velocity' — every pattern, at every offset of every variant."""
    data = full_variant(algorithm, 0)[0]
    patterns = F64_NONFINITE if offset < 32 else F32_NONFINITE
    for pattern in patterns:
        assert refusal("Spatial", put(data, offset, pattern)) == (
            "E_NONFINITE", f"Spatial/{offset}"), pattern


@case("G-R18", paragraphs=("SPEC:281",))
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_of_two_non_finite_floats_the_lower_offset_is_reported(algorithm):
    """SPEC:281: floats in ascending offset order, one error per attribute — for every pair."""
    data = full_variant(algorithm, 0)[0]
    offsets = spatial_float_offsets(algorithm)
    for i, first in enumerate(offsets):
        for second in offsets[i + 1:]:
            bad = put(data, first, "7ff8000000000000" if first < 32 else "7fc00000")
            bad = put(bad, second, "7ff0000000000000" if second < 32 else "7f800000")
            assert refusal("Spatial", bad) == ("E_NONFINITE", f"Spatial/{first}"), (first, second)


# =================================================================== precedence, SPEC:281, COD-14

@case("G-R18", paragraphs=("SPEC:281",))
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_the_precedence_ladder_reports_one_error_and_the_highest(algorithm):
    """All five defects at once, then one removed at a time: each step reports the next code.

    A value with an invalid discriminator, a wrong length, frozen 2 and a NaN at 8 is
    E_SPATIAL_VARIANT; with the discriminator mended, E_ATTRIBUTE_LENGTH; with the length
    mended, E_BOOLEAN; with frozen mended, E_NONFINITE at 8; with that mended, it decodes.
    """
    data, expected = full_variant(algorithm, 0)
    nan_at_8 = put(data, 8, "7ff8000000000000")
    all_but_variant = put(nan_at_8, 32, "02") + b"\x00"         # too long by one
    every_defect = bytes([0]) + all_but_variant[1:]
    assert refusal("Spatial", every_defect) == ("E_SPATIAL_VARIANT", "Spatial")
    assert refusal("Spatial", all_but_variant) == ("E_ATTRIBUTE_LENGTH", "Spatial")
    assert refusal("Spatial", all_but_variant[:-1]) == ("E_BOOLEAN", "Spatial/32")
    assert refusal("Spatial", nan_at_8) == ("E_NONFINITE", "Spatial/8")
    assert_strict_equal(decode_attribute("Spatial", data)["value"], expected)


#: COD-14's multi-defect vectors, each with what it must give (path by hand).
def _cod14():
    base1 = encode_spatial(1)
    base4 = encode_spatial(4, velocity=(0.0, 10.0, 0.0), acceleration=(1.0, 2.0, 3.0),
                           angular_velocity=(0.25, 0.5, 0.75))
    return (
        ("alg1-len47-frozen2", put(base1, 32, "02")[:47], ("E_ATTRIBUTE_LENGTH", "Spatial")),
        ("alg0-frozen2", bytes([0]) + put(base1, 32, "02")[1:], ("E_SPATIAL_VARIANT", "Spatial")),
        ("alg4-frozen2-nan8", put(put(base4, 32, "02"), 8, "7ff8000000000000"),
         ("E_BOOLEAN", "Spatial/32")),
        ("alg4-nan8-inf72", put(put(base4, 8, "7ff8000000000000"), 72, "7f800000"),
         ("E_NONFINITE", "Spatial/8")),
        ("alg4-inf72-nan36", put(put(base4, 72, "7f800000"), 36, "7fc00000"),
         ("E_NONFINITE", "Spatial/36")),
        ("alg10-len47", bytes([10]) + base1[1:47], ("E_SPATIAL_VARIANT", "Spatial")),
    )


@case("G-R18", paragraphs=("SPEC:281",))
@pytest.mark.parametrize("label,data,outcome", _cod14(), ids=[c[0] for c in _cod14()])
def test_cod14_multi_defect_vectors(label, data, outcome):
    assert refusal("Spatial", data) == outcome


@case("G-R18", paragraphs=("SPEC:281",))
def test_the_size_bound_comes_first_and_is_e_limit():
    """COD-05: more than 4096 bytes is E_LIMIT before any other check, the name check included;
    at exactly 4096 bytes the ordinary checks apply."""
    over = bytes([1]) + bytes(4096)                    # 4097 bytes, a valid discriminator
    for name in ("EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial", "Other", ""):
        assert refusal(name, over) == ("E_LIMIT", name), name
        assert refusal(name, bytes(1_000_000)) == ("E_LIMIT", name), name
    assert refusal("Spatial", bytes(4096)) == ("E_SPATIAL_VARIANT", "Spatial")
    assert refusal("Spatial", bytes([1]) + bytes(4095)) == ("E_ATTRIBUTE_LENGTH", "Spatial")
    assert refusal("EntityIdentifier", bytes(4096)) == ("E_ATTRIBUTE_LENGTH", "EntityIdentifier")
    assert refusal("ForceIdentifier", bytes(4096)) == ("E_ATTRIBUTE_LENGTH", "ForceIdentifier")
    assert refusal("Other", bytes(4096)) == ("E_UNSUBSCRIBED_ATTRIBUTE", "Other")


@case("G-R18", paragraphs=("SPEC:281",))
def test_the_name_comes_before_the_discriminator():
    """Bytes that would be E_SPATIAL_VARIANT under the right name are a name error under another."""
    assert refusal("spatial", bytes(48)) == ("E_UNSUBSCRIBED_ATTRIBUTE", "spatial")
    assert refusal("Spatial", bytes(48)) == ("E_SPATIAL_VARIANT", "Spatial")


@case("G-R18", paragraphs=("SPEC:281",))
def test_an_empty_or_short_spatial_follows_cod07():
    """No discriminator: E_ATTRIBUTE_LENGTH. One octet: the discriminator decides first."""
    assert refusal("Spatial", b"") == ("E_ATTRIBUTE_LENGTH", "Spatial")
    assert refusal("Spatial", b"\x01") == ("E_ATTRIBUTE_LENGTH", "Spatial")
    assert refusal("Spatial", b"\x00") == ("E_SPATIAL_VARIANT", "Spatial")
    assert refusal("Spatial", b"\x0a") == ("E_SPATIAL_VARIANT", "Spatial")
    for name in ("EntityIdentifier", "EntityType", "ForceIdentifier"):
        assert refusal(name, b"") == ("E_ATTRIBUTE_LENGTH", name)


# ================================================================ discriminator and length, R20

@case("G-R20")
def test_algorithm_0_and_10_to_255_are_e_spatial_variant_at_any_length():
    for algorithm in [0, *range(10, 256)]:
        for length in (1, 2, 32, 47, 48, 60, 72, 84, 100):
            data = bytes([algorithm]) + bytes(length - 1)
            assert refusal("Spatial", data) == ("E_SPATIAL_VARIANT", "Spatial"), (algorithm, length)


@case("G-R18")
@case("G-R20")
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_a_variant_must_have_its_exact_length_and_no_end_padding(algorithm):
    """R18 'Length must match exactly'; R20 'There is no end padding beyond those lengths':
    every length from 1 to 100 but the variant's own (48/60/72/84) fails."""
    data = full_variant(algorithm, 0)[0]
    total = SPATIAL_TABLE[algorithm][1]
    assert len(data) == total
    for length in range(1, 101):
        candidate = (data + bytes(100))[:length]
        if length == total:
            decode_attribute("Spatial", candidate)
        else:
            assert refusal("Spatial", candidate) == ("E_ATTRIBUTE_LENGTH", "Spatial"), length


# ============================================================ binary32 and binary64, bit for bit

#: (binary32 hex, the exact double it widens to). Derivations: 3dcccccd = 13421773 / 2^27
#: = 0.100000001490116119384765625 (COD-04; the shortest float32 spelling would be 0.1);
#: 00000001 = 2^-149, the smallest subnormal; 007fffff = (2^23 - 1) * 2^-149, the largest
#: subnormal; 00800000 = 2^-126; 7f7fffff = (2 - 2^-23) * 2^127, the largest finite.
BINARY32 = (
    ("3dcccccd", 0.10000000149011612),
    ("bdcccccd", -0.10000000149011612),
    ("00000001", 1.401298464324817e-45),
    ("80000001", -1.401298464324817e-45),
    ("007fffff", 1.1754942106924411e-38),
    ("00800000", 1.1754943508222875e-38),
    ("7f7fffff", 3.4028234663852886e+38),
    ("ff7fffff", -3.4028234663852886e+38),
    ("80000000", -0.0),
    ("00000000", 0.0),
)


@case("G-R18")
@pytest.mark.parametrize("algorithm", [3, 4, 8])
@pytest.mark.parametrize("hexvalue,expected", BINARY32, ids=[b[0] for b in BINARY32])
def test_binary32_fields_widen_exactly_in_every_slot(algorithm, hexvalue, expected):
    """R18 'IEEE 754 binary32 conversion', COD-04 exact widening, COD-14 subnormal, COD-15 -0.0."""
    base = full_variant(algorithm, 0)[0]
    for offset in [o for o in spatial_float_offsets(algorithm) if o >= 36]:
        value = decode_attribute("Spatial", put(base, offset, hexvalue))["value"]
        slots = (value["orientation_rad"] + (value["velocity_mps"] or [])
                 + (value["acceleration_mps2"] or []) + (value["angular_velocity_radps"] or []))
        got = slots[[o for o in spatial_float_offsets(algorithm) if o >= 36].index(offset)]
        assert_strict_equal(got, expected)


#: (binary64 hex, expected). The fraction is copied from the bytes by hand: 41584bf0c1d2e3f4 is
#: sign 0, exponent 0x415 = 2^22, fraction 0x84bf0c1d2e3f4. 0000000000000001 is 2^-1074.
BINARY64 = (
    ("41584bf0c1d2e3f4", float.fromhex("0x1.84bf0c1d2e3f4p+22")),
    ("c1584bf0c1d2e3f5", float.fromhex("-0x1.84bf0c1d2e3f5p+22")),
    ("3fb999999999999a", 0.1),
    ("0000000000000001", 5e-324),
    ("7fefffffffffffff", 1.7976931348623157e+308),
    ("8000000000000000", -0.0),
)


@case("G-R18")
@pytest.mark.parametrize("hexvalue,expected", BINARY64, ids=[b[0] for b in BINARY64])
def test_binary64_position_is_read_bit_for_bit(hexvalue, expected):
    for index, offset in enumerate((8, 16, 24)):
        value = decode_attribute("Spatial", put(encode_spatial(1), offset, hexvalue))["value"]
        assert_strict_equal(value["position_ecef_m"][index], expected)


@case("G-R18")
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_negative_zero_is_kept_by_the_decoder_in_every_float(algorithm):
    """R18: negative zero is permitted, and normalised only in projected output (COD-15)."""
    data = full_variant(algorithm, 0)[0]
    for offset in spatial_float_offsets(algorithm):
        data = put(data, offset, "8000000000000000" if offset < 32 else "80000000")
    value = decode_attribute("Spatial", data)["value"]
    for key in ("position_ecef_m", "orientation_rad", "velocity_mps", "acceleration_mps2",
                "angular_velocity_radps"):
        for number in value[key] or []:
            assert_strict_equal(number, -0.0)
    assert reencode_spatial(value) == data


@case("G-R18")
def test_explicit_big_endian_readers_differ_from_little_endian_ones():
    """A value whose bytes read differently in the two orders: only the big-endian answer passes."""
    data = put(encode_spatial(2, velocity=(0.0, 10.0, 0.0)), 8, "415854a640000000")  # 6378137.0
    data = put(data, 48, "3f800000")                                                    # 1.0
    value = decode_attribute("Spatial", data)["value"]
    assert value["position_ecef_m"][0] == 6378137.0          # little-endian: 1.37186443273e-312
    assert value["velocity_mps"] == [1.0, 10.0, 0.0]          # little-endian: 4.600602988224807e-41


# ===================================================================== padding, R18 and SPEC:90

@case("G-R18")
@pytest.mark.parametrize("algorithm", range(1, 10))
def test_padding_is_preserved_in_wire_order_and_never_interpreted(algorithm):
    """Each of the ten padding bytes, set to each of several values, appears in padding_hex at
    its position and changes nothing else (NaN-shaped and 0xff padding included, COD-14)."""
    data, expected = full_variant(algorithm, 0)
    positions = [1, 2, 3, 4, 5, 6, 7, 33, 34, 35]
    for index, position in enumerate(positions):
        for octet in (0x00, 0x7f, 0x80, 0xa5, 0xf8, 0xff):
            changed = bytearray(data)
            changed[position] = octet
            value = decode_attribute("Spatial", bytes(changed))["value"]
            want = bytearray(PADDING)
            want[index] = octet
            assert value["padding_hex"] == want.hex()
            assert_strict_equal({k: v for k, v in value.items() if k != "padding_hex"},
                                {k: v for k, v in expected.items() if k != "padding_hex"})
    nan_shaped = encode_spatial(1, frozen=1, padding=bytes.fromhex("7ff80000000001ffffff"))
    assert decode_attribute("Spatial", nan_shaped)["value"]["padding_hex"] == "7ff80000000001ffffff"


# ====================================================================== the four names, R18

@case("G-R18")
def test_the_four_decoders_and_only_they_decode():
    """R18 'The four decoders below are complete for this profile': exactly these four names,
    compared case-sensitively; anything else, including other RPR attributes, is refused."""
    assert decode_attribute("EntityIdentifier", bytes(6))["name"] == "EntityIdentifier"
    assert decode_attribute("EntityType", bytes(8))["name"] == "EntityType"
    assert decode_attribute("ForceIdentifier", bytes(1))["name"] == "ForceIdentifier"
    assert decode_attribute("Spatial", encode_spatial(1))["name"] == "Spatial"
    others = ("Other", "spatial", "SPATIAL", "Spatial ", " Spatial", "Spatial\x00",
              "entityidentifier", "Entity Identifier", "EntityIdentifierStruct", "RelativeSpatial",
              "ForceID", "Marking", "HLAprivilegeToDeleteObject", "")
    expected_paths = ("Other", "spatial", "SPATIAL", "Spatial ", " Spatial", f"Spatial{R}",
                      "entityidentifier", "Entity Identifier", "EntityIdentifierStruct",
                      "RelativeSpatial", "ForceID", "Marking", "HLAprivilegeToDeleteObject", "")
    for name, path in zip(others, expected_paths):
        for value in (b"", bytes(1), bytes(6), bytes(8), encode_spatial(1)):
            assert refusal(name, value) == ("E_UNSUBSCRIBED_ATTRIBUTE", path), name


@case("G-R18")
def test_a_dis_entity_state_pdu_is_not_an_attribute_value():
    """R18: values are HLA encodings, not DIS PDU bodies. A DIS Entity State PDU (header:
    protocol version 7, exercise 1, PDU type 1, family 1; 144 octets) is refused under every
    name; under Spatial its first octet reads as algorithm 7, whose value is 72 octets."""
    pdu = bytearray(144)
    pdu[0:4] = bytes([7, 1, 1, 1])
    pdu[8:10] = (144).to_bytes(2, "big")
    pdu = bytes(pdu)
    assert refusal("Spatial", pdu) == ("E_ATTRIBUTE_LENGTH", "Spatial")
    for name in ("EntityIdentifier", "EntityType", "ForceIdentifier"):
        assert refusal(name, pdu) == ("E_ATTRIBUTE_LENGTH", name)


#: Hostile attribute names and the path each must come out with (CR-R0-04), by hand: every
#: refused code point becomes U+FFFD and the path is cut to 64 characters.
HOSTILE = (
    ("\x00", R),
    ("Spatial\n", f"Spatial{R}"),
    ("\x1b[2J\x1b[H", f"{R}[2J{R}[H"),
    ("\r\nSpatial", f"{R}{R}Spatial"),
    ("\u202eSpatial", f"{R}Spatial"),
    ("\u061cSpatial", f"{R}Spatial"),
    ("\u2066Spatial\u2069", f"{R}Spatial{R}"),
    ("\u200fSpatial\u200e", f"{R}Spatial{R}"),
    ("\ud800", R),
    ("Spa\udfffial", f"Spa{R}ial"),
    ("\u2028\u2029", R * 2),
    ("\x7f\x85\x9f", R * 3),
    ("x" * 10_000, "x" * 64),
    ("\n" * 10_000, R * 64),
    ("\U0001f600" * 10_000, "\U0001f600" * 64),
    ("Spatial" + "\u202e" * 9_993, "Spatial" + R * 57),
)


@pytest.mark.parametrize("name,path", HOSTILE, ids=[f"hostile{i}" for i in range(len(HOSTILE))])
def test_a_hostile_name_is_refused_with_a_safe_path_on_every_refusal_path(name, path):
    """The two refusals that carry a caller's name: an unknown name and an oversize value.
    (Every other refusal is for one of the four known names, whose path is that fixed name.)
    The result must be the catalogue HlaError, never the constructor's ValueError."""
    for value, code in ((b"\x01", "E_UNSUBSCRIBED_ATTRIBUTE"), (bytes(4097), "E_LIMIT")):
        with pytest.raises(HlaError) as info:
            decode_attribute(name, value)
        error = info.value
        assert (error.code, error.path) == (code, path)
        assert 1 <= len(error.message) <= 256
        # CR-L01: a message never carries more than 64 characters of input.
        assert name[:65] not in error.message


class _Bytes(bytes):
    pass


class _Str(str):
    pass


@pytest.mark.parametrize("value", [bytearray(b"\x01"), memoryview(b"\x01"), "01", [1], None, 1,
                                   _Bytes(b"\x01")], ids=["bytearray", "memoryview", "str", "list",
                                                          "None", "int", "bytes-subclass"])
def test_a_value_that_is_not_bytes_is_a_caller_bug(value):
    with pytest.raises(TypeError):
        decode_attribute("ForceIdentifier", value)


@pytest.mark.parametrize("name", [b"Spatial", None, 1, ["Spatial"], _Str("Spatial")],
                         ids=["bytes", "None", "int", "list", "str-subclass"])
def test_a_name_that_is_not_a_str_is_a_caller_bug(name):
    with pytest.raises(TypeError):
        decode_attribute(name, encode_spatial(1))


def test_every_call_returns_new_objects():
    """Pure: changing one result does not change the next."""
    data = full_variant(4, 1)[0]
    first = decode_attribute("Spatial", data)
    first["value"]["position_ecef_m"][0] = 1.0
    first["value"]["velocity_mps"].append(9.0)
    second = decode_attribute("Spatial", data)
    assert_strict_equal(second["value"], full_variant(4, 1)[1])


def test_decode_attribute_is_exported_and_is_the_codec_function():
    from synapse_hla import codec
    assert synapse_hla.decode_attribute is codec.decode_attribute
    assert "decode_attribute" in synapse_hla.__all__


# ============================================================ the FOM governs the layout, R20

NS = "{http://standards.ieee.org/IEEE1516-2010}"
#: IEEE 1516.2-2010 predefined representations the RPR modules use without defining them:
#: name -> octets. Each is its own octet boundary.
PREDEFINED = {"HLAoctet": 1, "HLAinteger16BE": 2, "HLAinteger32BE": 4, "HLAinteger64BE": 8,
              "HLAfloat32BE": 4, "HLAfloat64BE": 8}
#: FOM field of the Spatial records -> decoded key.
FOM_GROUPS = {"WorldLocation": "position_ecef_m", "Orientation": "orientation_rad",
              "VelocityVector": "velocity_mps", "AccelerationVector": "acceleration_mps2",
              "AngularVelocity": "angular_velocity_radps"}


def fom_types():
    simple, enums, fixed, variants, basic = {}, {}, {}, {}, {}
    semantics = {}

    def text(element, tag):
        return element.findtext(f"{NS}{tag}")

    for path in fom_modules():
        root = ElementTree.parse(path).getroot()
        for e in root.iter(f"{NS}basicData"):
            basic[text(e, "name")] = int(text(e, "size")) // 8
        for e in root.iter(f"{NS}simpleData"):
            simple[text(e, "name")] = text(e, "representation")
        for e in root.iter(f"{NS}enumeratedData"):
            enums[text(e, "name")] = (text(e, "representation"),
                                      {text(x, "name"): int(text(x, "value"))
                                       for x in e.findall(f"{NS}enumerator")})
        for e in root.iter(f"{NS}fixedRecordData"):
            fixed[text(e, "name")] = [(text(f, "name"), text(f, "dataType"))
                                      for f in e.findall(f"{NS}field")]
            semantics[text(e, "name")] = text(e, "semantics") or ""
        for e in root.iter(f"{NS}variantRecordData"):
            variants[text(e, "name")] = (text(e, "dataType"),
                                         [(text(a, "enumerator"), text(a, "name"),
                                           text(a, "dataType"))
                                          for a in e.findall(f"{NS}alternative")])
    return simple, enums, fixed, variants, basic, semantics


def fom_layout():
    """algorithm -> (alternative name, record name, total, [(group, field, offset, octets)]),
    derived from the FOM with the IEEE 1516.2 rule: each field of a fixed record starts at the
    next multiple of its octet boundary, a record's boundary is its largest field's, and a
    variant's alternative starts after the discriminator at the largest alternative boundary."""
    simple, enums, fixed, variants, basic, semantics = fom_types()

    def primitive(dt):
        while dt in simple:
            dt = simple[dt]
        if dt in enums:
            return primitive(enums[dt][0])
        if dt in PREDEFINED:
            return PREDEFINED[dt]
        if dt in basic:
            return basic[dt]
        return None

    def boundary(dt):
        size = primitive(dt)
        return size if size is not None else max(boundary(t) for _, t in fixed[dt])

    def align(offset, unit):
        return (offset + unit - 1) // unit * unit

    def walk(dt, offset, group):
        size = primitive(dt)
        if size is not None:
            return [(group, offset, size)], offset + size
        out = []
        for name, field_type in fixed[dt]:
            offset = align(offset, boundary(field_type))
            sub, offset = walk(field_type, offset, group or name)
            out += [(g, o, s) for g, o, s in sub]
        return out, offset

    discriminant, alternatives = variants["SpatialVariantStruct"]
    values = enums[discriminant][1]
    body = align(primitive(discriminant), max(boundary(t) for _, _, t in alternatives))
    layout = {}
    for enumerator, alt_name, record in alternatives:
        fields, end = walk(record, body, None)
        layout[values[enumerator]] = (alt_name, record, end, fields)
    return layout, values, body, semantics


@case("G-R20")
def test_the_fom_alternatives_and_field_order_give_the_decoders_layout():
    """R20: the FOM's alternative names and field order govern, and the typo in the FV record's
    semantics text ('FVW (5) and RVB (9)') does not. Each field is filled with a distinct value
    at the offset the FOM puts it; the decoder must return each value under the right key."""
    layout, values, body, semantics = fom_layout()
    assert body == 8
    assert values == {"Other": 0, "Static": 1, "DRM_FPW": 2, "DRM_RPW": 3, "DRM_RVW": 4,
                      "DRM_FVW": 5, "DRM_FPB": 6, "DRM_RPB": 7, "DRM_RVB": 8, "DRM_FVB": 9}
    assert "FVW (5) and RVB (9)" in semantics["SpatialFVStruct"]
    assert layout[8][1] == "SpatialRVStruct" and layout[9][1] == "SpatialFVStruct"
    assert sorted(layout) == list(range(1, 10))
    for algorithm, (alt_name, record, total, fields) in layout.items():
        frame, spec_total, v_at, a_at, w_at = SPATIAL_TABLE[algorithm]
        assert total == spec_total, algorithm
        assert frame == ("BODY" if alt_name.endswith("B") else "WORLD"), alt_name
        starts = {g: min(o for gg, o, _ in fields if gg == g) for g, _, _ in fields}
        assert starts.get("VelocityVector") == v_at and starts.get("AccelerationVector") == a_at
        assert starts.get("AngularVelocity") == w_at and starts["IsFrozen"] == 32
        data = bytearray(total)
        data[0] = algorithm
        expected = {key: [] for key in FOM_GROUPS.values()}
        for index, (group, offset, size) in enumerate(fields):
            if group == "IsFrozen":
                assert (offset, size) == (32, 1)
                data[offset] = 1
                continue
            number = float(index + 1) * (-1.0 if index % 2 else 1.0) + 0.25
            struct.pack_into(">d" if size == 8 else ">f", data, offset, number)
            expected[FOM_GROUPS[group]].append(number)
        value = decode_attribute("Spatial", bytes(data))["value"]
        assert value["frozen"] is True
        for key, numbers in expected.items():
            assert_strict_equal(value[key], numbers or None)


# ===================================================================== source rules, R18

def _codec_tree():
    return ast.parse(CODEC_SOURCE.read_text(encoding="utf-8"))


@case("G-R18")
def test_every_struct_format_in_the_codec_is_explicitly_big_endian():
    """R18: explicit big-endian readers; no native struct packing (no '@', '=', '<' or bare
    format), checked on every struct call of the module's source."""
    formats = []
    for node in ast.walk(_codec_tree()):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "struct"):
            first = node.args[0]
            assert isinstance(first, ast.Constant) and type(first.value) is str, ast.dump(node)
            formats.append(first.value)
    assert formats and all(f.startswith(">") for f in formats), formats


@case("G-R18")
def test_the_codec_casts_nothing_and_borrows_no_dis_layout():
    """R18: never cast input to a structure, use native packing or copy DIS offsets. In Python
    terms: no ctypes, array, mmap or numpy, no memoryview cast, no host byte order, no
    `int.from_bytes` with a byte order other than big, no import from any DIS code."""
    tree = _codec_tree()
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert imports <= {"__future__", "math", "struct", "collections", "dataclasses", "types",
                       "synapse_hla"}, imports
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not ({"memoryview", "ctypes", "array"} & names)
    assert not ({"cast", "byteorder", "from_bytes", "frombuffer"} & attributes)


# ============================================================================ deterministic fuzz

def reference_outcome(name, data):
    """A second decoder, written here from SPEC:80-108 and SPEC:281: ('ok', value) or
    ('err', code, path). Used only to compare with the product on generated inputs."""
    if len(data) > 4096:
        return ("err", "E_LIMIT", name[:64])
    sizes = {"EntityIdentifier": 6, "EntityType": 8, "ForceIdentifier": 1}
    if name in sizes:
        if len(data) != sizes[name]:
            return ("err", "E_ATTRIBUTE_LENGTH", name)
        if name == "EntityIdentifier":
            return ("ok", dict(zip(("site", "application", "entity"),
                                   (int.from_bytes(data[i:i + 2], "big") for i in (0, 2, 4)))))
        if name == "EntityType":
            return ("ok", {"kind": data[0], "domain": data[1],
                           "country": int.from_bytes(data[2:4], "big"), "category": data[4],
                           "subcategory": data[5], "specific": data[6], "extra": data[7]})
        return ("ok", {"value": data[0]})
    if name != "Spatial":
        return ("err", "E_UNSUBSCRIBED_ATTRIBUTE", name[:64])
    if not data:
        return ("err", "E_ATTRIBUTE_LENGTH", "Spatial")
    if data[0] not in SPATIAL_TABLE:
        return ("err", "E_SPATIAL_VARIANT", "Spatial")
    frame, total, v_at, a_at, w_at = SPATIAL_TABLE[data[0]]
    if len(data) != total:
        return ("err", "E_ATTRIBUTE_LENGTH", "Spatial")
    if data[32] not in (0, 1):
        return ("err", "E_BOOLEAN", "Spatial/32")
    numbers = {}
    for offset in spatial_float_offsets(data[0]):
        (number,) = struct.unpack(">d" if offset < 32 else ">f",
                                  data[offset:offset + (8 if offset < 32 else 4)])
        if math.isnan(number) or math.isinf(number):
            return ("err", "E_NONFINITE", f"Spatial/{offset}")
        numbers[offset] = number

    def triple(start):
        return None if start is None else [numbers[start + 4 * i] for i in range(3)]

    return ("ok", {"algorithm": data[0], "frame": frame, "frozen": data[32] == 1,
                   "position_ecef_m": [numbers[8], numbers[16], numbers[24]],
                   "orientation_rad": [numbers[36], numbers[40], numbers[44]],
                   "velocity_mps": triple(v_at), "acceleration_mps2": triple(a_at),
                   "angular_velocity_radps": triple(w_at),
                   "padding_hex": (data[1:8] + data[33:36]).hex()})


def _random_base(rng, name):
    if name == "EntityIdentifier":
        return bytes(rng.getrandbits(8) for _ in range(6))
    if name == "EntityType":
        return bytes(rng.getrandbits(8) for _ in range(8))
    if name == "ForceIdentifier":
        return bytes([rng.getrandbits(8)])
    if name != "Spatial":
        return bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 90)))
    algorithm = rng.randrange(1, 10)
    total = SPATIAL_TABLE[algorithm][1]
    data = bytearray(rng.getrandbits(8) for _ in range(total))
    data[0] = algorithm
    data[32] = rng.choice((0, 1))
    return bytes(data)


def _mutate(rng, data):
    kind = rng.randrange(8)
    if kind == 0 and data:
        return data[:rng.randrange(len(data))]                                 # truncation
    if kind == 1:
        return data + bytes(rng.getrandbits(8) for _ in range(rng.randrange(1, 17)))  # trailing
    if kind in (2, 3) and data:
        out = bytearray(data)
        for _ in range(rng.randrange(1, 5)):                                   # bit flips
            bit = rng.randrange(len(out) * 8)
            out[bit // 8] ^= 1 << (bit % 8)
        return bytes(out)
    if kind == 4:
        return bytes(rng.getrandbits(8) for _ in range(rng.randrange(0, 100)))  # random bytes
    if kind == 5 and len(data) > 36:
        offset = rng.choice([o for o in spatial_float_offsets(data[0]) if o + 4 <= len(data)]
                            if data[0] in SPATIAL_TABLE else [36])
        return put(data, offset, rng.choice(F64_NONFINITE if offset < 32 else F32_NONFINITE))
    if kind == 6:
        target = rng.choice((4095, 4096, 4097))                                # size bound
        return (data + bytes(target))[:target]
    return data                                                                # unchanged


@case("G-R18", paragraphs=("SPEC:281",))
@pytest.mark.parametrize("seed", [20261004, 1516, 281])
def test_deterministic_fuzz_gives_a_valid_shape_or_one_catalogue_error(seed):
    """Truncations, trailing bytes, bit flips, random bytes, injected non-finite floats and the
    size bound, for the four names and three unknown ones. Each outcome must be either a decoded
    shape that validates against the schema, has finite numbers and re-encodes to the input, or
    an HlaError with a decode code; and it must equal the reference decoder's outcome exactly."""
    rng = random.Random(seed)
    names = ("EntityIdentifier", "EntityType", "ForceIdentifier", "Spatial", "Other",
             "spatial", "Spatial\u202e")
    schema = decoded_schema()
    outcomes = {"ok": 0, "err": 0}
    for _ in range(3000):
        name = rng.choice(names)
        data = _mutate(rng, _random_base(rng, name))
        expected = reference_outcome(name, data)
        try:
            result = decode_attribute(name, data)
        except HlaError as error:
            got = ("err", error.code, error.path)
            if name == "Spatial\u202e":
                expected = ("err", expected[1], f"Spatial{R}")
            assert got == expected, (name, data.hex())
            outcomes["err"] += 1
            continue
        assert expected[0] == "ok", (name, data.hex(), expected)
        schema.validate(result)
        assert_strict_equal(result, {"name": name, "value": expected[1]})
        if name == "Spatial":
            assert reencode_spatial(result["value"]) == data
        outcomes["ok"] += 1
    # Both branches were exercised in volume; the counts are not otherwise expectations.
    assert outcomes["ok"] > 300 and outcomes["err"] > 300, outcomes
