"""The DIS 7 codec: the error model, `decode_pdu`, `encode_pdu` and the header predicate.

This module starts with the error model; it names the specification once, spelled exactly
`SC DIS7 SPEC 001 v1.0`, as a handoff document that is not in this repository. No acceptance
case covers the error model directly, so these tests are not named `test_t<gg>_<case>_...`;
they are the evidence of requirement R21. The decode tests that follow are named by their case
(`test_t01_a01_...`, `test_t02_n01_...`) and assert the layout from offsets typed here, never
from the codec's own output or constants. The encode tests take their input from the bundle's
twins and their expected octets from the vectors, from hex literals or from octets built here.
"""
from __future__ import annotations

import array
import copy
import json
import math
import pickle
import random
import re
import struct

import pytest

from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters import dis7_codec as codec
from synapse_cdm.adapters.dis7_codec import (
    Dis7Error,
    Dis7InputTooDeep,
    Dis7InputTooLarge,
    decode_pdu,
    encode_pdu,
    looks_like_entity_state,
)
from tests import dis7_support

EXPECTED_CODES = (
    "E_INPUT_TYPE",
    "E_INPUT_LIMIT",
    "E_CONTEXT_SESSION",
    "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME",
    "E_CONTEXT_CONFLICT",
    "E_CONTEXT_HASH",
    "E_HEADER_UNSUPPORTED",
    "E_LENGTH_MISMATCH",
    "E_NONFINITE",
    "E_TWIN_SCHEMA",
    "E_TWIN_WIRE_MISMATCH",
    "E_VALUE_RANGE",
    "E_POSITION_DOMAIN",
    "E_PROJECTION",
    "E_REPLAY_SHAPE",
    "E_REPLAY_PROVENANCE",
    "E_REPLAY_CHANGED",
)

EXPECTED_ACCEPTANCE_CODES = {
    "E_CONTEXT_CONFLICT",
    "E_CONTEXT_SESSION",
    "E_CONTEXT_SYNTHETIC",
    "E_CONTEXT_TIME",
    "E_HEADER_UNSUPPORTED",
    "E_INPUT_LIMIT",
    "E_LENGTH_MISMATCH",
    "E_NONFINITE",
    "E_POSITION_DOMAIN",
    "E_REPLAY_CHANGED",
    "E_REPLAY_PROVENANCE",
    "E_REPLAY_SHAPE",
    "E_TWIN_SCHEMA",
    "E_TWIN_WIRE_MISMATCH",
}


def test_r21_codes_are_the_contract_table_in_order():
    assert codec.CODES == EXPECTED_CODES
    assert len(codec.CODES) == 18
    assert len(set(codec.CODES)) == 18
    for name in EXPECTED_CODES:
        assert getattr(codec, name) == name


def test_r21_every_code_an_acceptance_case_expects_is_in_the_table():
    cases_path = dis7_support.CONTRACT / "acceptance-cases.json"
    cases = json.loads(cases_path.read_text(encoding="utf-8"))["cases"]
    found = set()
    for case in cases:
        found |= set(re.findall(r"E_[A-Z_]+", case["expected"]))
    assert found == EXPECTED_ACCEPTANCE_CODES
    assert found <= set(codec.CODES)


@pytest.mark.parametrize(
    "code, path, message",
    [
        ("E_LENGTH_MISMATCH", "byte[8]", "declared length 144, received 145"),
        ("E_TWIN_SCHEMA", "pdu.header", "unknown key"),
        ("E_CONTEXT_TIME", "time_context.instant", "50% {x} at y: z"),
    ],
)
def test_r21_error_exposes_code_path_message_and_prints_them(code, path, message):
    error = Dis7Error(code, path, message)
    assert error.code == code
    assert error.path == path
    assert error.message == message
    assert str(error) == f"{code} at {path}: {message}"
    assert error.args == (code, path, message)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooLarge)
    assert not isinstance(error, InputTooDeep)


def test_r21_too_large_carries_the_limit_code_and_both_base_classes():
    with pytest.raises(InputTooLarge) as raised:
        raise Dis7InputTooLarge("$", "input is 4225 octets; the limit is 4224")
    error = raised.value
    assert isinstance(error, Dis7Error)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooDeep)
    assert error.code == "E_INPUT_LIMIT"
    assert error.path == "$"
    assert str(error) == "E_INPUT_LIMIT at $: input is 4225 octets; the limit is 4224"
    assert "4224" in str(error) and "4225" in str(error)
    assert Dis7InputTooLarge.__mro__[:3] == (Dis7InputTooLarge, Dis7Error, InputTooLarge)


def test_r21_too_deep_carries_the_limit_code_and_both_base_classes():
    with pytest.raises(InputTooDeep) as raised:
        raise Dis7InputTooDeep("$", "envelope nests 17 containers deep; the limit is 16")
    error = raised.value
    assert isinstance(error, Dis7Error)
    assert isinstance(error, ValueError)
    assert not isinstance(error, InputTooLarge)
    assert str(error) == "E_INPUT_LIMIT at $: envelope nests 17 containers deep; the limit is 16"
    assert Dis7InputTooDeep.__mro__[:3] == (Dis7InputTooDeep, Dis7Error, InputTooDeep)


@pytest.mark.parametrize(
    "error",
    [
        Dis7Error("E_NONFINITE", "byte[36]", "velocity component is not finite"),
        Dis7InputTooLarge("$", "input is 4225 octets; the limit is 4224"),
        Dis7InputTooDeep("$", "envelope nests 17 containers deep; the limit is 16"),
    ],
)
def test_r21_errors_survive_copy_and_pickle(error):
    for clone in (copy.copy(error), copy.deepcopy(error), pickle.loads(pickle.dumps(error))):
        assert type(clone) is type(error)
        assert clone.code == error.code
        assert clone.path == error.path
        assert clone.message == error.message
        assert str(clone) == str(error)



# ---------------------------------------------------------------------------------------------
# decode_pdu: layout, framing, bounds and finiteness
# ---------------------------------------------------------------------------------------------

# (offset, struct format, accessor) for every fixed field, typed from the contract's offset table.
LAYOUT = (
    (0, ">B", lambda p: p["header"]["protocol_version"]),
    (1, ">B", lambda p: p["header"]["exercise_id"]),
    (2, ">B", lambda p: p["header"]["pdu_type"]),
    (3, ">B", lambda p: p["header"]["protocol_family"]),
    (4, ">I", lambda p: p["header"]["timestamp"]),
    (8, ">H", lambda p: p["header"]["length"]),
    (10, ">B", lambda p: p["header"]["status"]),
    (11, ">B", lambda p: p["header"]["padding"]),
    (12, ">H", lambda p: p["entity_id"][0]),
    (14, ">H", lambda p: p["entity_id"][1]),
    (16, ">H", lambda p: p["entity_id"][2]),
    (18, ">B", lambda p: p["force_id"]),
    (20, ">B", lambda p: p["entity_type"][0]),
    (21, ">B", lambda p: p["entity_type"][1]),
    (22, ">H", lambda p: p["entity_type"][2]),
    (24, ">B", lambda p: p["entity_type"][3]),
    (25, ">B", lambda p: p["entity_type"][4]),
    (26, ">B", lambda p: p["entity_type"][5]),
    (27, ">B", lambda p: p["entity_type"][6]),
    (28, ">B", lambda p: p["alternative_entity_type"][0]),
    (29, ">B", lambda p: p["alternative_entity_type"][1]),
    (30, ">H", lambda p: p["alternative_entity_type"][2]),
    (32, ">B", lambda p: p["alternative_entity_type"][3]),
    (33, ">B", lambda p: p["alternative_entity_type"][4]),
    (34, ">B", lambda p: p["alternative_entity_type"][5]),
    (35, ">B", lambda p: p["alternative_entity_type"][6]),
    (36, ">f", lambda p: p["velocity_mps"][0]),
    (40, ">f", lambda p: p["velocity_mps"][1]),
    (44, ">f", lambda p: p["velocity_mps"][2]),
    (48, ">d", lambda p: p["position_ecef_m"][0]),
    (56, ">d", lambda p: p["position_ecef_m"][1]),
    (64, ">d", lambda p: p["position_ecef_m"][2]),
    (72, ">f", lambda p: p["orientation_radians"][0]),
    (76, ">f", lambda p: p["orientation_radians"][1]),
    (80, ">f", lambda p: p["orientation_radians"][2]),
    (84, ">I", lambda p: p["appearance"]),
    (140, ">I", lambda p: p["capabilities"]),
)

TOP_KEYS = (
    "header", "entity_id", "force_id", "entity_type", "alternative_entity_type", "velocity_mps",
    "position_ecef_m", "orientation_radians", "appearance", "dead_reckoning_hex", "marking_hex",
    "capabilities", "variable_parameters_hex",
)
HEADER_KEYS = (
    "protocol_version", "exercise_id", "pdu_type", "protocol_family", "timestamp", "length",
    "status", "padding",
)
INT_ARRAYS = ("entity_id", "entity_type", "alternative_entity_type")
FLOAT_ARRAYS = ("velocity_mps", "position_ecef_m", "orientation_radians")
INT_SCALARS = ("force_id", "appearance", "capabilities")

WALKING_EXPECTED = {
    "header": {"protocol_version": 7, "exercise_id": 0x11, "pdu_type": 1, "protocol_family": 1,
               "timestamp": 0x14151617, "length": 176, "status": 0x1A, "padding": 0x1B},
    "entity_id": [0x1C1D, 0x1E1F, 0x2021],
    "force_id": 0x22,
    "entity_type": [0x24, 0x25, 0x2627, 0x28, 0x29, 0x2A, 0x2B],
    "alternative_entity_type": [0x2C, 0x2D, 0x2E2F, 0x30, 0x31, 0x32, 0x33],
    "velocity_mps": [1.687666184579939e-07, 4.416166848386638e-05, 0.011550485156476498],
    "position_ecef_m": [34.51767781622453, 1.7211626029127738e+40, 8.022809603887844e+78],
    "orientation_radians": [955928388042752.0, 2.4923892787183616e+17, 6.496260823161032e+19],
    "appearance": 0x64656667,
    "dead_reckoning_hex": "68696a6b6c6d6e6f707172737475767778797a7b7c7d7e7f"
                          "808182838485868788898a8b8c8d8e8f",
    "marking_hex": "909192939495969798999a9b",
    "capabilities": 0x9C9D9E9F,
    "variable_parameters_hex": ["c0c1c2c3c4c5c6c7c8c9cacbcccdcecf",
                                "d0d1d2d3d4d5d6d7d8d9dadbdcdddedf"],
}

NAN32 = bytes.fromhex("7fc00000")
NAN64 = bytes.fromhex("7ff8000000000000")
BINARY32_NONFINITE = ("7fc00000", "7f800000", "ff800000")
BINARY64_NONFINITE = ("7ff8000000000000", "7ff0000000000000", "fff0000000000000")


def _refusal(raw) -> Dis7Error:
    with pytest.raises(Dis7Error) as raised:
        decode_pdu(raw)
    return raised.value


def _assert_refused(raw, code, path) -> Dis7Error:
    error = _refusal(raw)
    assert (error.code, error.path) == (code, path)
    if code == "E_INPUT_LIMIT":
        assert type(error) is Dis7InputTooLarge
    else:
        assert type(error) is Dis7Error
    return error


def _with(raw: bytes, *edits: tuple[int, bytes]) -> bytes:
    for offset, data in edits:
        raw = dis7_support.patch(raw, offset, data)
    return raw


def _a02_input() -> bytes:
    """The seed with 255 zero-filled records: octet 19 = 255, octets 8-9 = 10 80, 4224 octets."""
    return _with(dis7_support.seed(), (8, bytes.fromhex("1080")), (19, bytes([255]))) + bytes(4080)


def _equator_twin_with(length: int, records: list[str]) -> dict:
    twin = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope")["pdu"])
    twin["header"]["length"] = length
    twin["variable_parameters_hex"] = records
    return twin


# T01 -- layout

@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t01_a01_every_fixed_field_sits_at_its_offset(stem):
    raw = dis7_support.vector_bytes(stem)
    pdu = decode_pdu(raw)
    for offset, fmt, accessor in LAYOUT:
        assert accessor(pdu) == struct.unpack_from(fmt, raw, offset)[0], (offset, fmt)
    assert pdu["dead_reckoning_hex"] == raw[88:128].hex()
    assert pdu["marking_hex"] == raw[128:140].hex()
    records = pdu["variable_parameters_hex"]
    assert len(records) == raw[19]
    for k, record in enumerate(records):
        assert record == raw[144 + 16 * k:160 + 16 * k].hex()


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t01_a01_each_vector_decodes_to_its_envelope_twin(stem):
    twin = dis7_support.vector_json(stem, "envelope")["pdu"]
    pdu = decode_pdu(dis7_support.vector_bytes(stem))
    assert pdu == twin
    assert list(pdu) == list(twin)
    assert list(pdu["header"]) == list(twin["header"])
    for key in HEADER_KEYS:
        assert type(pdu["header"][key]) is int, key
    for key in INT_SCALARS:
        assert type(pdu[key]) is int, key
    for key in INT_ARRAYS:
        assert all(type(value) is int for value in pdu[key]), key
    for key in FLOAT_ARRAYS:
        assert all(type(value) is float for value in pdu[key]), key


def test_t01_a01_literal_values_of_the_three_vectors():
    equator = decode_pdu(dis7_support.vector_bytes("equator_eastbound"))
    assert equator["header"]["timestamp"] == 0x40000001
    assert equator["header"]["exercise_id"] == 42
    assert equator["entity_id"] == [7, 11, 1]
    assert equator["force_id"] == 1
    assert equator["velocity_mps"] == [0.0, 25.0, 0.0]
    assert equator["position_ecef_m"] == [6378257.0, 0.0, 0.0]
    assert equator["orientation_radians"] == [0.5, -0.25, 0.125]
    assert equator["appearance"] == 0x12345678
    assert equator["dead_reckoning_hex"] == "02" + "00" * 39
    assert equator["marking_hex"] == "0145584552434953452d3031"
    assert equator["capabilities"] == 0xAABBCCDD
    assert equator["variable_parameters_hex"] == []

    pole = decode_pdu(dis7_support.vector_bytes("north_pole_stationary"))
    assert pole["entity_id"] == [7, 11, 2]
    assert pole["position_ecef_m"] == [0.0, 0.0, 6356792.314245179]
    assert [math.copysign(1.0, v) for v in pole["velocity_mps"]] == [1.0, -1.0, 1.0]

    third = decode_pdu(dis7_support.vector_bytes("unprojectable_with_extensions"))
    assert third["header"]["length"] == 160
    assert third["force_id"] == 9
    assert third["entity_type"][0] == 0
    assert third["velocity_mps"] == [1.0, 2.0, 3.0]
    assert third["variable_parameters_hex"] == ["ff3ff400000000000012345678abcdef"]


def test_t01_walking_pattern_decodes_to_hand_written_values():
    raw = dis7_support.walking_pdu()
    pattern = bytearray(0x10 + i for i in range(144)) + bytes(range(0xC0, 0xE0))
    pattern[0], pattern[2], pattern[3] = 7, 1, 1
    pattern[8], pattern[9] = 0x00, 0xB0
    pattern[19] = 2
    assert raw == bytes(pattern)
    assert len(raw) == 176
    assert len(set(raw)) == 175
    assert decode_pdu(raw) == WALKING_EXPECTED


def test_t01_exact_key_sets_and_container_types():
    raw = dis7_support.vector_bytes("unprojectable_with_extensions")
    pdu = decode_pdu(raw)
    assert tuple(pdu) == TOP_KEYS
    assert tuple(pdu["header"]) == HEADER_KEYS
    assert type(pdu) is dict and type(pdu["header"]) is dict
    lengths = {"entity_id": 3, "entity_type": 7, "alternative_entity_type": 7,
               "velocity_mps": 3, "position_ecef_m": 3, "orientation_radians": 3}
    for key, length in lengths.items():
        assert type(pdu[key]) is list and len(pdu[key]) == length, key
    assert type(pdu["variable_parameters_hex"]) is list
    assert re.fullmatch(r"[0-9a-f]{80}", pdu["dead_reckoning_hex"])
    assert re.fullmatch(r"[0-9a-f]{24}", pdu["marking_hex"])
    for record in pdu["variable_parameters_hex"]:
        assert re.fullmatch(r"[0-9a-f]{32}", record)

    again = decode_pdu(raw)
    assert again == pdu
    assert again is not pdu
    assert again["header"] is not pdu["header"]
    for key in (*lengths, "variable_parameters_hex"):
        assert again[key] is not pdu[key], key
    pdu["header"]["length"] = 0
    pdu["velocity_mps"].append(9.0)
    pdu["variable_parameters_hex"].clear()
    third = decode_pdu(raw)
    assert third["header"]["length"] == 160
    assert third["velocity_mps"] == [1.0, 2.0, 3.0]
    assert third["variable_parameters_hex"] == ["ff3ff400000000000012345678abcdef"]


def test_t01_record_k_sits_at_144_plus_16k():
    raw = _with(dis7_support.seed(), (8, bytes.fromhex("00c0")), (19, bytes([3])))
    raw += b"".join(bytes([0xA0 + k]) * 16 for k in range(3))
    assert decode_pdu(raw)["variable_parameters_hex"] == ["a0" * 16, "a1" * 16, "a2" * 16]


# T02 -- framing

def test_t02_n01_protocol_version_6_is_refused_at_octet_0():
    _assert_refused(_with(dis7_support.seed(), (0, bytes([6]))), "E_HEADER_UNSUPPORTED", "byte[0]")


def test_t02_n02_pdu_type_67_is_refused_at_octet_2():
    _assert_refused(_with(dis7_support.seed(), (2, bytes([67]))), "E_HEADER_UNSUPPORTED", "byte[2]")


def test_t02_n03_protocol_family_2_is_refused_at_octet_3():
    _assert_refused(_with(dis7_support.seed(), (3, bytes([2]))), "E_HEADER_UNSUPPORTED", "byte[3]")


def test_t02_n04_a_count_the_length_does_not_hold_is_refused_at_octet_19():
    _assert_refused(_with(dis7_support.seed(), (19, bytes([1]))), "E_LENGTH_MISMATCH", "byte[19]")


def test_t02_n05_a_declared_length_of_143_is_refused_at_octet_8():
    _assert_refused(_with(dis7_support.seed(), (9, bytes([143]))), "E_LENGTH_MISMATCH", "byte[8]")


@pytest.mark.parametrize("n", range(144))
def test_t02_n06_every_truncation_is_refused_at_its_length(n):
    _assert_refused(dis7_support.seed()[:n], "E_LENGTH_MISMATCH", f"byte[{n}]")


def test_t02_n07_one_trailing_octet_is_refused_at_octet_8():
    _assert_refused(dis7_support.seed() + b"\x00", "E_LENGTH_MISMATCH", "byte[8]")


def test_t02_n08_two_concatenated_pdus_are_refused_at_octet_8():
    _assert_refused(dis7_support.seed() + dis7_support.seed(), "E_LENGTH_MISMATCH", "byte[8]")


def _type_family(pdu_type: int, family: int) -> bytes:
    return _with(dis7_support.seed(), (2, bytes([pdu_type, family])))


PCAP_HEADER = bytes.fromhex("d4c3b2a1020004000000000000000000ffff000001000000")


def _xml_sample(element: str) -> bytes:
    text = '<?xml version="1.0" encoding="UTF-8"?>' + element
    return text.encode("ascii").ljust(200, b" ")


REFUSED_CATEGORIES = [
    ("fire_type_2", lambda: _type_family(2, 2), "E_HEADER_UNSUPPORTED", "byte[2]"),
    ("detonation_type_3", lambda: _type_family(3, 2), "E_HEADER_UNSUPPORTED", "byte[2]"),
    ("collision_type_4", lambda: _type_family(4, 1), "E_HEADER_UNSUPPORTED", "byte[2]"),
    ("entity_state_update_type_67", lambda: _type_family(67, 1), "E_HEADER_UNSUPPORTED",
     "byte[2]"),
    *[(f"radio_type_{t}", (lambda t=t: _type_family(t, 4)), "E_HEADER_UNSUPPORTED", "byte[2]")
      for t in (25, 26, 27)],
    *[(f"simulation_management_type_{t}", (lambda t=t: _type_family(t, 5)),
       "E_HEADER_UNSUPPORTED", "byte[2]") for t in range(11, 23)],
    ("dis6_version_6", lambda: _with(dis7_support.seed(), (0, bytes([6]))),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("pcap_file_header_only", lambda: PCAP_HEADER, "E_LENGTH_MISMATCH", "byte[24]"),
    ("pcap_file_holding_the_seed",
     lambda: PCAP_HEADER + bytes.fromhex("00000000000000009000000090000000") + dis7_support.seed(),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("zip_empty_archive", lambda: b"PK\x05\x06" + bytes(18), "E_LENGTH_MISMATCH", "byte[22]"),
    ("kmz_zip_local_header", lambda: b"PK\x03\x04" + bytes(196), "E_HEADER_UNSUPPORTED",
     "byte[0]"),
    ("kml_xml", lambda: _xml_sample('<kml xmlns="http://www.opengis.net/kml/2.2"/>'),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("c2sim_xml",
     lambda: _xml_sample('<MessageBody xmlns="http://www.sisostds.org/schemas/C2SIM/1.1"/>'),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("hla_xml", lambda: _xml_sample('<objectModel xmlns="http://standards.ieee.org/IEEE1516-2010"/>'),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
]


@pytest.mark.parametrize(
    "build, code, path",
    [pytest.param(build, code, path, id=name) for name, build, code, path in REFUSED_CATEGORIES],
)
def test_r02_every_refused_category_is_refused_with_its_code_and_path(build, code, path):
    raw = build()
    error = _assert_refused(raw, code, path)
    assert str(error).startswith(f"{code} at {path}: ")


def test_r02_the_byte_samples_have_their_stated_lengths():
    lengths = {name: len(build()) for name, build, _, _ in REFUSED_CATEGORIES}
    assert lengths["pcap_file_header_only"] == 24
    assert lengths["pcap_file_holding_the_seed"] == 184
    assert lengths["zip_empty_archive"] == 22
    assert lengths["kmz_zip_local_header"] == 200
    assert lengths["kml_xml"] == lengths["c2sim_xml"] == lengths["hla_xml"] == 200
    assert len(REFUSED_CATEGORIES) == 27


def _bracketed_dead_reckoning() -> bytes:
    return _with(dis7_support.seed(), (88, b"[" * 40))


BRACKET_REFUSALS = [
    ("open_bracket_144", lambda: b"[" * 144, "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("open_brace_144", lambda: b"{" * 144, "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("open_bracket_4224", lambda: b"[" * 4224, "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("open_brace_4224", lambda: b"{" * 4224, "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("utf16_be_brackets", lambda: ("[" * 72).encode("utf-16-be"), "E_HEADER_UNSUPPORTED",
     "byte[0]"),
    ("utf16_le_brackets", lambda: ("[" * 72).encode("utf-16-le"), "E_HEADER_UNSUPPORTED",
     "byte[0]"),
    ("open_bracket_143", lambda: b"[" * 143, "E_LENGTH_MISMATCH", "byte[143]"),
    ("open_bracket_4225", lambda: b"[" * 4225, "E_INPUT_LIMIT", "$"),
    ("bracketed_dead_reckoning_is_accepted", _bracketed_dead_reckoning, None, None),
    ("bracketed_dead_reckoning_with_bracket_octet_0",
     lambda: _with(_bracketed_dead_reckoning(), (0, b"\x5b")), "E_HEADER_UNSUPPORTED", "byte[0]"),
]


@pytest.mark.parametrize(
    "build, code, path",
    [pytest.param(build, code, path, id=name) for name, build, code, path in BRACKET_REFUSALS],
)
def test_t02_bracket_leading_octets_get_the_coded_refusal(build, code, path):
    raw = build()
    if code is None:
        assert decode_pdu(raw)["dead_reckoning_hex"] == "5b" * 40
        return
    error = _assert_refused(raw, code, path)
    assert not isinstance(error, InputTooDeep)


DEFECT_ORDER = [
    ("version_type_family", lambda s: _with(s, (0, bytes([6])), (2, bytes([67, 2]))),
     "E_HEADER_UNSUPPORTED", "byte[0]"),
    ("type_family", lambda s: _with(s, (2, bytes([67, 2]))), "E_HEADER_UNSUPPORTED", "byte[2]"),
    ("family_count", lambda s: _with(s, (3, bytes([2])), (19, bytes([1]))),
     "E_HEADER_UNSUPPORTED", "byte[3]"),
    ("family_nonfinite", lambda s: _with(s, (3, bytes([2])), (36, NAN32)),
     "E_HEADER_UNSUPPORTED", "byte[3]"),
    ("version_truncated", lambda s: _with(s, (0, bytes([6])))[:100], "E_LENGTH_MISMATCH",
     "byte[100]"),
    ("version_oversize", lambda s: _with(s, (0, bytes([6]))).ljust(4225, b"\x00"), "E_INPUT_LIMIT",
     "$"),
    ("length_143_count", lambda s: _with(s, (9, bytes([143])), (19, bytes([1]))),
     "E_LENGTH_MISMATCH", "byte[8]"),
    ("length_160_count_short", lambda s: _with(s, (9, bytes([160])), (19, bytes([1]))),
     "E_LENGTH_MISMATCH", "byte[8]"),
    ("length_145_appended", lambda s: _with(s, (9, bytes([145]))) + b"\x00", "E_LENGTH_MISMATCH",
     "byte[19]"),
    ("count_nonfinite", lambda s: _with(s, (19, bytes([1])), (36, NAN32)), "E_LENGTH_MISMATCH",
     "byte[19]"),
    ("velocity_then_position", lambda s: _with(s, (44, NAN32), (48, NAN64)), "E_NONFINITE",
     "byte[44]"),
    ("position_then_orientation", lambda s: _with(s, (64, NAN64), (72, NAN32)), "E_NONFINITE",
     "byte[64]"),
]


@pytest.mark.parametrize(
    "build, code, path",
    [pytest.param(build, code, path, id=name) for name, build, code, path in DEFECT_ORDER],
)
def test_t02_several_defects_report_the_earliest_stage(build, code, path):
    _assert_refused(build(dis7_support.seed()), code, path)


def _h_view(raw: bytes) -> memoryview:
    items = array.array("H")
    items.frombytes(raw)
    return memoryview(items)


PREDICATE_CASES = [
    ("seed", lambda: dis7_support.seed(), True),
    ("north_pole", lambda: dis7_support.vector_bytes("north_pole_stationary"), True),
    ("third_vector", lambda: dis7_support.vector_bytes("unprojectable_with_extensions"), True),
    ("walking", lambda: dis7_support.walking_pdu(), True),
    ("seed_first_12", lambda: dis7_support.seed()[:12], True),
    ("bare_triplet_12", lambda: bytes.fromhex("07000101") + bytes(8), True),
    ("count_mismatch", lambda: _with(dis7_support.seed(), (19, bytes([1]))), True),
    ("length_mismatch", lambda: _with(dis7_support.seed(), (9, bytes([143]))), True),
    ("triplet_5000", lambda: bytes.fromhex("07000101") + bytes(4996), True),
    ("bytearray", lambda: bytearray(dis7_support.seed()), True),
    ("memoryview", lambda: memoryview(dis7_support.seed()), True),
    ("two_octet_items", lambda: _h_view(dis7_support.seed()), True),
    ("seed_first_11", lambda: dis7_support.seed()[:11], False),
    ("empty", lambda: b"", False),
    ("version_6", lambda: _with(dis7_support.seed(), (0, bytes([6]))), False),
    ("type_67", lambda: _with(dis7_support.seed(), (2, bytes([67]))), False),
    ("family_2", lambda: _with(dis7_support.seed(), (3, bytes([2]))), False),
    ("two_octet_items_of_10", lambda: _h_view(dis7_support.seed()[:10]), False),
    ("text", lambda: "\x07\x00\x01\x01" + "0" * 8, False),
    ("none", lambda: None, False),
    ("integer", lambda: 7, False),
    ("list", lambda: [7, 0, 1, 1] + [0] * 8, False),
    ("dict", lambda: {"pdu": {"header": {"protocol_version": 7}}}, False),
    ("released_memoryview", lambda: _released_view(), False),
]


def _released_view() -> memoryview:
    view = memoryview(dis7_support.seed())
    view.release()
    return view


# CR-29
@pytest.mark.parametrize(
    "build, expected",
    [pytest.param(build, expected, id=name) for name, build, expected in PREDICATE_CASES],
)
def test_r07_header_predicate_matrix(build, expected):
    assert looks_like_entity_state(build()) is expected


def test_r07_the_two_octet_view_has_72_items():
    view = _h_view(dis7_support.seed())
    assert (view.itemsize, len(view), view.nbytes) == (2, 72, 144)


# T03 -- bounds

@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: bytes(4225), id="zeros"),
        pytest.param(lambda: _a02_input() + b"\x00", id="a02_plus_one"),
        pytest.param(lambda: dis7_support.seed() + bytes(4081), id="seed_plus_4081"),
        pytest.param(lambda: _with(dis7_support.seed(), (0, bytes([6]))) + bytes(4081),
                     id="version_6_plus_4081"),
    ],
)
def test_t03_n09_4225_octets_are_refused_before_any_field_is_read(build):
    raw = build()
    assert len(raw) == 4225
    error = _refusal(raw)
    assert type(error) is Dis7InputTooLarge
    assert isinstance(error, InputTooLarge)
    assert (error.code, error.path) == ("E_INPUT_LIMIT", "$")
    assert "4225" in error.message and "4224" in error.message


def test_t03_a02_255_records_decode_to_255_opaque_records():
    raw = _a02_input()
    assert len(raw) == 4224
    pdu = decode_pdu(raw)
    assert pdu["variable_parameters_hex"] == ["00" * 16] * 255
    assert pdu == _equator_twin_with(4224, ["00" * 16] * 255)

    numbered = raw[:144] + b"".join(bytes([k]) * 16 for k in range(255))
    assert len(numbered) == 4224
    assert decode_pdu(numbered)["variable_parameters_hex"] == [f"{k:02x}" * 16 for k in range(255)]


# T04 -- finiteness

def _nonfinite_cases(offsets, patterns):
    return [pytest.param(offset, pattern, id=f"byte{offset}_{pattern}")
            for offset in offsets for pattern in patterns]


@pytest.mark.parametrize("offset, pattern", _nonfinite_cases((36, 40, 44), BINARY32_NONFINITE))
def test_t04_n36_nonfinite_velocity_is_refused_at_its_offset(offset, pattern):
    raw = _with(dis7_support.seed(), (offset, bytes.fromhex(pattern)))
    _assert_refused(raw, "E_NONFINITE", f"byte[{offset}]")


@pytest.mark.parametrize("offset, pattern", _nonfinite_cases((48, 56, 64), BINARY64_NONFINITE))
def test_t04_n48_nonfinite_position_is_refused_at_its_offset(offset, pattern):
    raw = _with(dis7_support.seed(), (offset, bytes.fromhex(pattern)))
    _assert_refused(raw, "E_NONFINITE", f"byte[{offset}]")


@pytest.mark.parametrize("offset, pattern", _nonfinite_cases((72, 76, 80), BINARY32_NONFINITE))
def test_t04_n72_nonfinite_orientation_is_refused_at_its_offset(offset, pattern):
    raw = _with(dis7_support.seed(), (offset, bytes.fromhex(pattern)))
    _assert_refused(raw, "E_NONFINITE", f"byte[{offset}]")


def test_t04_nonfinite_octets_inside_the_dead_reckoning_record_are_preserved():
    raw = _with(dis7_support.seed(), (104, bytes.fromhex("7fc00000")),
                (116, bytes.fromhex("ff800000")))
    pdu = decode_pdu(raw)
    assert pdu["dead_reckoning_hex"][32:40] == "7fc00000"
    assert pdu["dead_reckoning_hex"][56:64] == "ff800000"


@pytest.mark.parametrize(
    "offset, pattern, key, expected",
    [
        pytest.param(36, "7f7fffff", "velocity_mps", 3.4028234663852886e+38, id="flt_max"),
        pytest.param(36, "ff7fffff", "velocity_mps", -3.4028234663852886e+38, id="minus_flt_max"),
        pytest.param(36, "00000001", "velocity_mps", 1.401298464324817e-45, id="flt_min_subnormal"),
        pytest.param(36, "007fffff", "velocity_mps", 1.1754942106924411e-38,
                     id="flt_max_subnormal"),
        pytest.param(36, "80000001", "velocity_mps", -1.401298464324817e-45,
                     id="minus_flt_min_subnormal"),
        pytest.param(48, "7fefffffffffffff", "position_ecef_m", 1.7976931348623157e+308,
                     id="dbl_max"),
        pytest.param(48, "0000000000000001", "position_ecef_m", 5e-324, id="dbl_min_subnormal"),
    ],
)
def test_t04_finite_extremes_decode_to_their_exact_values(offset, pattern, key, expected):
    raw = _with(dis7_support.seed(), (offset, bytes.fromhex(pattern)))
    value = decode_pdu(raw)[key][0]
    assert type(value) is float
    assert value == expected
    assert math.copysign(1.0, value) == math.copysign(1.0, expected)


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("x", id="short_text"),
        pytest.param("x" * 5000, id="long_text"),
        pytest.param(None, id="none"),
        pytest.param(7, id="integer"),
        pytest.param(3.5, id="float"),
        pytest.param(True, id="boolean"),
        pytest.param([7, 1, 1], id="list"),
        pytest.param({"pdu": 1}, id="dict"),
    ],
)
def test_non_bytes_input_is_e_input_type_at_the_root(value):
    _assert_refused(value, "E_INPUT_TYPE", "$")


def test_released_memoryview_is_e_input_type_at_the_root():
    view = memoryview(dis7_support.seed())
    view.release()
    _assert_refused(view, "E_INPUT_TYPE", "$")
    assert looks_like_entity_state(view) is False


# CR-29
def test_bytearray_and_memoryview_decode_like_bytes():
    seed = dis7_support.seed()
    twin = dis7_support.vector_json("equator_eastbound", "envelope")["pdu"]
    assert decode_pdu(bytearray(seed)) == twin
    assert decode_pdu(memoryview(seed)) == twin


# No foreign exception (R21)

FUZZ_LENGTHS = (0, 1, 11, 12, 143, 144, 145, 160, 176, 200)
FUZZ_CODES = {"E_INPUT_LIMIT", "E_LENGTH_MISMATCH", "E_HEADER_UNSUPPORTED", "E_NONFINITE"}


def _fuzz_input(rng: random.Random, i: int) -> bytes:
    kind = i % 4
    if kind == 0:
        return rng.randbytes(rng.choice(FUZZ_LENGTHS))
    if kind == 1:
        n = rng.randrange(4)
        size = 144 + 16 * n
        raw = bytearray(rng.randbytes(size))
        raw[0], raw[2], raw[3] = 7, 1, 1
        raw[8:10] = size.to_bytes(2, "big")
        raw[19] = n
        return bytes(raw)
    raw = bytearray(dis7_support.vector_bytes(rng.choice(dis7_support.STEMS)))
    if kind == 2:
        for _ in range(rng.randint(1, 4)):
            raw[rng.randrange(len(raw))] = rng.randrange(256)
        return bytes(raw)
    raw += rng.randbytes(40)
    return bytes(raw[:rng.randrange(len(raw) + 1)])


def test_r21_no_foreign_exception_escapes_decode_pdu():
    rng = random.Random(0xD157)
    accepted = 0
    seen = set()
    for i in range(4000):
        raw = _fuzz_input(rng, i)
        try:
            pdu = decode_pdu(raw)
        except Dis7Error as error:
            assert type(error) in (Dis7Error, Dis7InputTooLarge), (i, type(error))
            assert error.code in FUZZ_CODES, (i, error.code)
            assert re.fullmatch(r"\$|byte\[\d+\]", error.path), (i, error.path)
            assert len(str(error)) < 200, i
            seen.add(error.code)
        else:
            assert tuple(pdu) == TOP_KEYS, i
            assert encode_pdu(pdu) == raw, i
            accepted += 1
    assert accepted >= 100
    assert {"E_LENGTH_MISMATCH", "E_HEADER_UNSUPPORTED", "E_NONFINITE"} <= seen


# Encode -- helpers

EQUATOR = "equator_eastbound"


def _twin(stem: str = EQUATOR) -> dict:
    """A fresh copy of the bundle's twin for `stem`, safe to edit in place."""
    return dis7_support.vector_json(stem, "envelope")["pdu"]


def _set(pdu: dict, path: str, value) -> dict:
    """`pdu` with the member at `path` (`name`, `name.member` or `name[i]`) set to `value`."""
    name, member, index = re.fullmatch(r"([a-z_]+)(?:\.([a-z_]+)|\[(\d+)\])?", path).groups()
    if member is not None:
        pdu[name][member] = value
    elif index is not None:
        pdu[name][int(index)] = value
    else:
        pdu[name] = value
    return pdu


def _edit(*pairs) -> object:
    """An edit of the equator twin: `(path, value)` pairs applied in order."""
    def build():
        pdu = _twin()
        for path, value in pairs:
            _set(pdu, path, value)
        return pdu
    return build


def _without(name: str, member: str | None = None, extra: bool = False):
    def build():
        pdu = _twin()
        if member is None:
            del pdu[name]
        else:
            del pdu[name][member]
        if extra:
            pdu["extra"] = 1
        return pdu
    return build


def _assert_encode_refused(pdu, code, path) -> Dis7Error:
    with pytest.raises(Dis7Error) as raised:
        encode_pdu(pdu)
    error = raised.value
    assert type(error) is Dis7Error
    assert (error.code, error.path) == (code, path)
    return error


def _counted(n: int) -> bytes:
    """The seed declaring `n` records, followed by records `bytes([k]) * 16` for k < n."""
    raw = _with(dis7_support.seed(), (8, (144 + 16 * n).to_bytes(2, "big")), (19, bytes([n])))
    return raw + b"".join(bytes([k]) * 16 for k in range(n))


# Encode -- round trips and counts

@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t01_a01_each_twin_encodes_to_its_vector_octets(stem):
    raw = dis7_support.vector_bytes(stem)
    assert encode_pdu(_twin(stem)) == raw
    assert encode_pdu(decode_pdu(raw)) == raw


def test_t01_walking_pattern_encodes_from_hand_written_values():
    assert encode_pdu(copy.deepcopy(WALKING_EXPECTED)) == dis7_support.walking_pdu()


@pytest.mark.parametrize("length", [144, 4240])
def test_t03_n10_256_records_are_refused_as_twin_schema(length):
    pdu = _equator_twin_with(length, ["00" * 16] * 256)
    _assert_encode_refused(pdu, "E_TWIN_SCHEMA", "variable_parameters_hex")


@pytest.mark.parametrize("n", [0, 1, 254, 255])
def test_t03_record_counts_0_1_254_255_round_trip(n):
    raw = _counted(n)
    assert len(raw) == 144 + 16 * n
    records = [f"{k:02x}" * 16 for k in range(n)]
    pdu = decode_pdu(raw)
    assert pdu["variable_parameters_hex"] == records
    assert encode_pdu(pdu) == raw
    assert encode_pdu(_equator_twin_with(144 + 16 * n, records)) == raw


def test_t03_a02_the_maximal_pdu_round_trips_byte_exact():
    raw = _a02_input()
    assert len(raw) == 4224
    assert encode_pdu(decode_pdu(raw)) == raw
    assert encode_pdu(_equator_twin_with(4224, ["00" * 16] * 255)) == raw


# Encode -- stage 1, structure

STRUCTURE_DEFECTS = (
    [pytest.param(_without(name), name, id=f"missing_{name}") for name in TOP_KEYS]
    + [pytest.param(_without("header", name), f"header.{name}", id=f"missing_header_{name}")
       for name in HEADER_KEYS]
    + [
        pytest.param(_edit(("extra", 1)), "$", id="extra_top_key"),
        pytest.param(_without("force_id", extra=True), "force_id", id="missing_before_extra"),
        pytest.param(_edit(("header.extra", 1)), "header", id="extra_header_key"),
        pytest.param(_edit(("header", [])), "header", id="header_list"),
        pytest.param(lambda: None, "$", id="argument_none"),
        pytest.param(lambda: [], "$", id="argument_list"),
        pytest.param(dis7_support.seed, "$", id="argument_octets"),
        pytest.param(_edit(("entity_id", [7, 11])), "entity_id", id="entity_id_2"),
        pytest.param(_edit(("entity_id", [7, 11, 1, 0])), "entity_id", id="entity_id_4"),
        pytest.param(_edit(("entity_id", {})), "entity_id", id="entity_id_object"),
        pytest.param(_edit(("entity_type", [1] * 6)), "entity_type", id="entity_type_6"),
        pytest.param(_edit(("alternative_entity_type", [0] * 8)), "alternative_entity_type",
                     id="alternative_entity_type_8"),
        pytest.param(_edit(("velocity_mps", [0.0, 25.0])), "velocity_mps", id="velocity_2"),
        pytest.param(_edit(("position_ecef_m", [0.0] * 4)), "position_ecef_m", id="position_4"),
        pytest.param(_edit(("orientation_radians", "abc")), "orientation_radians",
                     id="orientation_string"),
        pytest.param(_edit(("variable_parameters_hex", {})), "variable_parameters_hex",
                     id="records_object"),
        pytest.param(_edit(("variable_parameters_hex", "")), "variable_parameters_hex",
                     id="records_string"),
        pytest.param(_edit(("dead_reckoning_hex", "0" * 78)), "dead_reckoning_hex",
                     id="dead_reckoning_78"),
        pytest.param(_edit(("dead_reckoning_hex", "0" * 82)), "dead_reckoning_hex",
                     id="dead_reckoning_82"),
        pytest.param(_edit(("dead_reckoning_hex", bytes(40))), "dead_reckoning_hex",
                     id="dead_reckoning_octets"),
        pytest.param(_edit(("marking_hex", "0" * 22)), "marking_hex", id="marking_22"),
        pytest.param(_edit(("marking_hex", "0" * 26)), "marking_hex", id="marking_26"),
        pytest.param(_edit(("header.length", 160), ("variable_parameters_hex", ["0" * 30])),
                     "variable_parameters_hex[0]", id="record_30"),
        pytest.param(_edit(("header.length", 176),
                           ("variable_parameters_hex", ["0" * 32, "0" * 34])),
                     "variable_parameters_hex[1]", id="second_record_34"),
        pytest.param(_edit(("header.length", 160), ("variable_parameters_hex", [None])),
                     "variable_parameters_hex[0]", id="record_none"),
        pytest.param(_edit(("force_id", "1")), "force_id", id="force_id_string"),
        pytest.param(_edit(("force_id", None)), "force_id", id="force_id_none"),
        pytest.param(_edit(("force_id", 1.5)), "force_id", id="force_id_fraction"),
        pytest.param(_edit(("force_id", float("nan"))), "force_id", id="force_id_nan"),
        pytest.param(_edit(("header.exercise_id", 42.5)), "header.exercise_id",
                     id="exercise_id_fraction"),
        pytest.param(_edit(("velocity_mps[1]", None)), "velocity_mps[1]", id="velocity_none"),
        pytest.param(_edit(("velocity_mps[1]", "25")), "velocity_mps[1]", id="velocity_string"),
        pytest.param(_edit(("entity_type[2]", "0")), "entity_type[2]", id="entity_type_string"),
    ]
)


# CR-04
@pytest.mark.parametrize("build, path", STRUCTURE_DEFECTS)
def test_encode_structure_defects_are_twin_schema_at_the_member(build, path):
    error = _assert_encode_refused(build(), "E_TWIN_SCHEMA", path)
    assert "extra" not in error.message


BOOLEAN_PATHS = (
    "force_id", "header.exercise_id", "header.protocol_version", "header.length", "entity_id[2]",
    "entity_type[2]", "alternative_entity_type[0]", "appearance", "capabilities",
    "velocity_mps[1]", "position_ecef_m[0]", "orientation_radians[2]",
)


# CR-06
@pytest.mark.parametrize("value", [True, False])
@pytest.mark.parametrize("path", BOOLEAN_PATHS)
def test_t04_booleans_are_refused_for_integers_and_vector_components(path, value):
    _assert_encode_refused(_set(_twin(), path, value), "E_TWIN_SCHEMA", path)


# Encode -- stages 2 to 4

HEADER_CONSTANT_DEFECTS = [
    pytest.param(_edit(("header.protocol_version", 6)), "header.protocol_version", id="version_6"),
    pytest.param(_edit(("header.protocol_version", 256)), "header.protocol_version",
                 id="version_256"),
    pytest.param(_edit(("header.protocol_version", -1)), "header.protocol_version",
                 id="version_minus_1"),
    pytest.param(_edit(("header.pdu_type", 67)), "header.pdu_type", id="type_67"),
    pytest.param(_edit(("header.protocol_family", 2)), "header.protocol_family", id="family_2"),
    pytest.param(_edit(("header.protocol_version", 6), ("header.pdu_type", 67),
                       ("header.protocol_family", 2)), "header.protocol_version", id="all_three"),
    pytest.param(_edit(("header.pdu_type", 67), ("header.protocol_family", 2)),
                 "header.pdu_type", id="type_and_family"),
]


# CR-04
@pytest.mark.parametrize("build, path", HEADER_CONSTANT_DEFECTS)
def test_encode_header_constants_are_header_unsupported(build, path):
    _assert_encode_refused(build(), "E_HEADER_UNSUPPORTED", path)


ONE_RECORD = ["01" * 16]

LENGTH_CASES = [
    pytest.param(_edit(("header.length", 145)), None, id="145"),
    pytest.param(_edit(("header.length", 143)), None, id="143"),
    pytest.param(_edit(("header.length", 160)), None, id="160_no_record"),
    pytest.param(_edit(("header.length", 65536)), None, id="65536"),
    pytest.param(_edit(("header.length", -1)), None, id="minus_1"),
    pytest.param(_edit(("variable_parameters_hex", ONE_RECORD)), None, id="one_record_144"),
    pytest.param(_edit(("header.length", 160), ("variable_parameters_hex", ONE_RECORD)), 160,
                 id="one_record_160"),
]


# CR-04
@pytest.mark.parametrize("build, accepted_length", LENGTH_CASES)
def test_encode_length_must_equal_144_plus_16_per_record(build, accepted_length):
    if accepted_length is None:
        _assert_encode_refused(build(), "E_LENGTH_MISMATCH", "header.length")
    else:
        raw = encode_pdu(build())
        assert len(raw) == accepted_length
        assert raw[8:10] == bytes.fromhex("00a0") and raw[19] == 1
        assert raw[144:] == bytes([1]) * 16


# CR-04
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")],
                         ids=["nan", "inf", "minus_inf"])
@pytest.mark.parametrize("field", FLOAT_ARRAYS)
@pytest.mark.parametrize("i", [0, 1, 2])
def test_t04_nonfinite_vector_components_are_refused_by_the_encoder(field, i, value):
    path = f"{field}[{i}]"
    _assert_encode_refused(_set(_twin(), path, value), "E_NONFINITE", path)


# Encode -- stage 5

WIDTH_DEFECTS = [
    ("velocity_mps[1]", 0.1, "v_0_1"),
    ("velocity_mps[1]", 16777217.0, "v_16777217_float"),
    ("velocity_mps[1]", 1e39, "v_1e39"),
    ("velocity_mps[1]", -1e39, "v_minus_1e39"),
    ("velocity_mps[1]", 3.4028235e38, "v_above_flt_max"),
    ("velocity_mps[1]", 1e-46, "v_below_subnormal"),
    ("velocity_mps[1]", 16777217, "v_16777217_int"),
    ("velocity_mps[1]", 10 ** 400, "v_10_pow_400_int"),
    ("orientation_radians[2]", 0.1, "o2_0_1"),
    ("orientation_radians[0]", 1e39, "o0_1e39"),
    ("position_ecef_m[0]", 2 ** 53 + 1, "p0_2_pow_53_plus_1_int"),
    ("position_ecef_m[0]", 10 ** 400, "p0_10_pow_400_int"),
]


# CR-04
@pytest.mark.parametrize("path, value", [pytest.param(p, v, id=i) for p, v, i in WIDTH_DEFECTS])
def test_t04_values_that_do_not_survive_the_wire_width_are_value_range(path, value):
    _assert_encode_refused(_set(_twin(), path, value), "E_VALUE_RANGE", path)


EXACT_ENCODINGS = [
    ("velocity_mps[1]", 3.4028234663852886e+38, 40, "7f7fffff", "flt_max"),
    ("velocity_mps[1]", -3.4028234663852886e+38, 40, "ff7fffff", "minus_flt_max"),
    ("velocity_mps[1]", 1.401298464324817e-45, 40, "00000001", "smallest_subnormal"),
    ("velocity_mps[1]", 1.1754942106924411e-38, 40, "007fffff", "largest_subnormal"),
    ("velocity_mps[1]", -1.401298464324817e-45, 40, "80000001", "minus_smallest_subnormal"),
    ("velocity_mps[1]", 25, 40, "41c80000", "int_25"),
    ("velocity_mps[1]", 16777216, 40, "4b800000", "int_16777216"),
    ("velocity_mps[1]", -0.0, 40, "80000000", "minus_zero"),
    ("velocity_mps[1]", 0.0, 40, "00000000", "zero"),
    ("velocity_mps[1]", 0, 40, "00000000", "int_zero"),
    ("orientation_radians[0]", -0.0, 72, "80000000", "orientation_minus_zero"),
    ("position_ecef_m[1]", -0.0, 56, "8000000000000000", "position_minus_zero"),
    ("position_ecef_m[0]", 0.1, 48, "3fb999999999999a", "position_0_1"),
    ("position_ecef_m[0]", 6378257, 48, "415854c440000000", "position_int_6378257"),
]


@pytest.mark.parametrize(
    "path, value, offset, hex_octets",
    [pytest.param(p, v, o, h, id=i) for p, v, o, h, i in EXACT_ENCODINGS],
)
def test_t04_exact_values_and_signed_zero_encode_to_their_octets(path, value, offset,
                                                                 hex_octets):
    raw = encode_pdu(_set(_twin(), path, value))
    expected = bytes.fromhex(hex_octets)
    assert raw[offset:offset + len(expected)] == expected


def test_t04_signed_zero_of_the_north_pole_vector_survives_a_round_trip():
    raw = dis7_support.vector_bytes("north_pole_stationary")
    assert raw[40:44].hex() == "80000000"
    assert encode_pdu(_twin("north_pole_stationary"))[40:44].hex() == "80000000"
    assert encode_pdu(decode_pdu(raw)) == raw


U8, U16, U32 = 255, 65535, 4294967295
INTEGER_WIDTHS = (
    [(path, U8) for path in ("header.exercise_id", "header.status", "header.padding", "force_id")]
    + [(f"{name}[{i}]", U8) for name in ("entity_type", "alternative_entity_type")
       for i in (0, 1, 3, 4, 5, 6)]
    + [(path, U16) for path in ("entity_id[0]", "entity_id[1]", "entity_id[2]", "entity_type[2]",
                                "alternative_entity_type[2]")]
    + [(path, U32) for path in ("header.timestamp", "appearance", "capabilities")]
)


@pytest.mark.parametrize("path, top", INTEGER_WIDTHS)
def test_t04_out_of_range_integers_are_refused_per_field_width(path, top):
    for value in (-1, top + 1, 1e300):
        _assert_encode_refused(_set(_twin(), path, value), "E_VALUE_RANGE", path)
    for value in (0, top, float(top)):
        decoded = decode_pdu(encode_pdu(_set(_twin(), path, value)))
        assert decoded == _set(_twin(), path, int(value)), value


# CR-06
def test_t04_integral_floats_are_accepted_for_integer_fields():
    pdu = _twin()
    pdu["header"] = {name: float(value) for name, value in pdu["header"].items()}
    for name in INT_ARRAYS:
        pdu[name] = [float(value) for value in pdu[name]]
    for name in INT_SCALARS:
        pdu[name] = float(pdu[name])
    assert encode_pdu(pdu) == dis7_support.seed()


HEX_DEFECTS = [
    pytest.param(_edit(("dead_reckoning_hex", "0g" + "00" * 39)), "dead_reckoning_hex",
                 id="dead_reckoning_g"),
    pytest.param(_edit(("dead_reckoning_hex", "AB" + "00" * 39)), "dead_reckoning_hex",
                 id="dead_reckoning_upper"),
    pytest.param(_edit(("marking_hex", " 1" + "00" * 11)), "marking_hex", id="marking_space"),
    pytest.param(_edit(("marking_hex", "０" + "0" * 23)), "marking_hex",
                 id="marking_fullwidth_digit"),
    pytest.param(_edit(("header.length", 160), ("variable_parameters_hex", ["FF" + "00" * 15])),
                 "variable_parameters_hex[0]", id="record_upper"),
    pytest.param(_edit(("header.length", 176),
                       ("variable_parameters_hex", ["00" * 16, "zz" + "00" * 15])),
                 "variable_parameters_hex[1]", id="second_record_z"),
]


@pytest.mark.parametrize("build, path", HEX_DEFECTS)
def test_encode_hex_characters_are_value_range(build, path):
    _assert_encode_refused(build(), "E_VALUE_RANGE", path)


# Encode -- order across stages

NAN, INF = float("nan"), float("inf")
STAGE_ORDER = [
    pytest.param(lambda: _set(_without("capabilities")(), "header.protocol_version", 6),
                 "E_TWIN_SCHEMA", "capabilities", id="missing_before_header"),
    pytest.param(_edit(("marking_hex", "0" * 22), ("header.protocol_version", 6)),
                 "E_TWIN_SCHEMA", "marking_hex", id="width_before_header"),
    pytest.param(_edit(("header.pdu_type", 67), ("header.length", 145)),
                 "E_HEADER_UNSUPPORTED", "header.pdu_type", id="header_before_length"),
    pytest.param(_edit(("header.length", 145), ("velocity_mps[0]", NAN)),
                 "E_LENGTH_MISMATCH", "header.length", id="length_before_nonfinite"),
    pytest.param(_edit(("orientation_radians[2]", INF), ("header.exercise_id", 256)),
                 "E_NONFINITE", "orientation_radians[2]", id="nonfinite_before_range"),
    pytest.param(_edit(("marking_hex", "ZZ" + "00" * 11), ("velocity_mps[1]", NAN)),
                 "E_NONFINITE", "velocity_mps[1]", id="nonfinite_before_hex"),
    pytest.param(_edit(("header.exercise_id", 256), ("force_id", 256)),
                 "E_VALUE_RANGE", "header.exercise_id", id="header_range_first"),
    pytest.param(_edit(("velocity_mps[1]", 0.1), ("force_id", 256)),
                 "E_VALUE_RANGE", "force_id", id="force_id_before_vector"),
    pytest.param(_edit(("velocity_mps[1]", 0.1), ("marking_hex", "ZZ" + "00" * 11)),
                 "E_VALUE_RANGE", "velocity_mps[1]", id="vector_before_hex"),
    pytest.param(_edit(("capabilities", 2 ** 32), ("dead_reckoning_hex", "AB" + "00" * 39)),
                 "E_VALUE_RANGE", "dead_reckoning_hex", id="hex_before_capabilities"),
]


# CR-04
@pytest.mark.parametrize("build, code, path", STAGE_ORDER)
def test_encode_reports_defects_in_the_frozen_stage_order(build, code, path):
    _assert_encode_refused(build(), code, path)


# Encode -- native types (CR-29)

# CR-29
def test_encode_accepts_tuples_and_does_not_mutate_its_argument():
    pdu = _twin()
    for name in INT_ARRAYS + FLOAT_ARRAYS + ("variable_parameters_hex",):
        pdu[name] = tuple(pdu[name])
    before = copy.deepcopy(pdu)
    assert encode_pdu(pdu) == dis7_support.seed()
    assert pdu == before
    assert type(pdu["entity_id"]) is tuple


# CR-29
def test_t04_a_memoryview_of_2200_two_octet_items_is_refused_as_input_limit():
    view = memoryview(array.array("H", [0]) * 2200)
    assert (len(view), view.nbytes) == (2200, 4400)
    error = _refusal(view)
    assert type(error) is Dis7InputTooLarge
    assert isinstance(error, InputTooLarge)
    assert (error.code, error.path) == ("E_INPUT_LIMIT", "$")
    assert "4400" in error.message and "4224" in error.message


# CR-29
def test_t04_a_memoryview_of_72_two_octet_items_decodes_as_its_144_octets():
    items = array.array("H")
    items.frombytes(dis7_support.seed())
    view = memoryview(items)
    assert (len(view), view.nbytes) == (72, 144)
    assert decode_pdu(view) == _twin()


# Encode -- no foreign exception (R21)

NASTY = (None, True, False, -1, 256, 65536, 2 ** 32, 10 ** 400, 0.1, 1.5, 1e39, float("nan"),
         float("inf"), "", "zz", "00" * 16, b"\x00", [], [0], {}, (1, 2, 3), 7.0)
ENCODE_CODES = {"E_TWIN_SCHEMA", "E_HEADER_UNSUPPORTED", "E_LENGTH_MISMATCH", "E_NONFINITE",
                "E_VALUE_RANGE"}


def _fuzz_edit(rng: random.Random, pdu: dict) -> None:
    nasty = copy.deepcopy(rng.choice(NASTY))
    action = rng.randrange(4)
    header = pdu.get("header")
    arrays = [name for name, value in pdu.items() if type(value) is list and value]
    if action == 1 and type(header) is dict and header:
        header[rng.choice(sorted(header))] = nasty
    elif action == 2 and arrays:
        values = pdu[rng.choice(sorted(arrays))]
        values[rng.randrange(len(values))] = nasty
    elif action == 3 and pdu:
        del pdu[rng.choice(sorted(pdu))]
    elif pdu:
        pdu[rng.choice(sorted(pdu))] = nasty


def test_r21_no_foreign_exception_escapes_encode_pdu():
    rng = random.Random(0xD157)
    seen = set()
    for i in range(3000):
        pdu = _twin(rng.choice(dis7_support.STEMS))
        for _ in range(rng.randint(1, 3)):
            _fuzz_edit(rng, pdu)
        try:
            out = encode_pdu(pdu)
        except Dis7Error as error:
            assert type(error) is Dis7Error, (i, type(error))
            assert error.code in ENCODE_CODES, (i, error.code)
            assert re.fullmatch(r"\$|[a-z_]+(\.[a-z_]+|\[\d+\])?", error.path), (i, error.path)
            seen.add(error.code)
        else:
            assert type(out) is bytes, i
            assert encode_pdu(decode_pdu(out)) == out, i
    assert seen == ENCODE_CODES
