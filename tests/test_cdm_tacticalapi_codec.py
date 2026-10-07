"""`tacticalapi_codec`, tested against bytes worked out by hand and bytes protoc wrote. Moved here
from the adapter's out-of-tree project on 2026-10-06, when the adapter landed; the record it cites
is `docs/tacticalapi-implementation.md`, the adapter's specification.

The decoder is never its own oracle here. Three kinds of evidence are used:

* HAND VECTORS — byte literals whose every octet is derived in the comment beside it from the
  protobuf encoding's own rules (a tag is `number << 3 | wire type`; a varint is little-endian
  groups of seven bits with the high bit set on every group but the last; a negative int32 or
  int64 is its 64-bit two's complement, so ten octets).
* PROTOC VECTORS — the text source and the bytes `protoc --encode=google.protobuf.Any` (libprotoc
  36.2) wrote from it on 2026-10-04, both embedded as literals so the test needs no protoc; the
  expected twin is written by hand from the text source.
* PROTOC'S DESCRIPTOR — `test_embedded_table_matches_the_pinned_descriptor` regenerates the field
  table from the pinned files and holds the embedded one equal, or reports BLOCKED_EXTERNAL_EVIDENCE.

`tests/tacticalapi_protowire.py` writes the bulk inputs the limit tests need; it is itself held to
protoc's bytes below, and no refusal or value test depends on it alone.
"""
from __future__ import annotations

import enum
import json
import pathlib
import pickle
import signal
import uuid

import pytest
from synapse_cdm.adapter import container_depth
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked

from synapse_cdm.adapters import tacticalapi_codec as codec
from synapse_cdm.adapters.tacticalapi_codec import DecodeLimits, TacticalapiRefused

from gates import tacticalapi_field_table as gen_field_table
from tests import tacticalapi_protowire as pw

ROOT = pathlib.Path(__file__).resolve().parents[1]
CODEC_SOURCE = pathlib.Path(codec.__file__).resolve()
#: The adapter's specification in the repository.
RECORD = ROOT / "docs" / "tacticalapi-implementation.md"

#: 20 octets of `type.googleapis.com/` + 49 of the type name = 69 = 0x45.
GET_URL = b"type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse"
GET_URL_TEXT = GET_URL.decode("ascii")
#: 20 + 60 = 80 = 0x50.
SUBSCRIBE_URL_TEXT = pw.SUBSCRIBE_URL.decode("ascii")


def envelope(value: bytes) -> bytes:
    """An `Any` around a GetBlueForcesResponse whose value is under 128 octets, written out:
    0x0a = field 1 (`type_url`) << 3 | wire type 2; 0x45 = 69, the URL's length; the URL;
    0x12 = field 2 (`value`) << 3 | 2; one length octet; the value."""
    assert len(GET_URL) == 0x45 and len(value) < 0x80
    return b"\x0a\x45" + GET_URL + b"\x12" + bytes([len(value)]) + value


def refused(code: str, call, *args, **kwargs) -> TacticalapiRefused:
    """Run `call`, require a refusal with `code`, and hold the message to start with it."""
    with pytest.raises(TacticalapiRefused) as caught:
        call(*args, **kwargs)
    assert caught.value.code == code, str(caught.value)
    assert str(caught.value).startswith(f"{code}: ")
    return caught.value


def twin(**fields) -> dict:
    return {"@type": GET_URL_TEXT, **fields}


# =============================================================================== the refusal


def test_a_refusal_is_a_value_error_carrying_its_code_first():
    error = TacticalapiRefused("truncated-varint", "the varint at offset 3 ends early")
    assert isinstance(error, ValueError)
    assert error.code == "truncated-varint"
    assert str(error) == "truncated-varint: the varint at offset 3 ends early"


def test_a_refusal_survives_a_pickle_round_trip():
    """A refusal raised in a worker process has to arrive whole; an exception whose constructor
    takes two arguments does not unpickle without `__reduce__`."""
    error = pickle.loads(pickle.dumps(TacticalapiRefused("null-in-twin", "x is null")))
    assert (error.code, str(error)) == ("null-in-twin", "null-in-twin: x is null")


def test_a_code_mapping_does_not_name_is_itself_refused():
    with pytest.raises(ValueError, match="not a reason code"):
        TacticalapiRefused("something-else", "")


def test_every_code_of_mapping_section_3_2_is_a_decoder_code():
    section_3_2 = {
        "input-too-large", "truncated-varint", "varint-too-long", "length-exceeds-input",
        "unsupported-wire-type", "field-number-zero", "wire-type-mismatch", "invalid-utf8",
        "non-finite-number", "timestamp-out-of-range", "repeated-singular-field",
        "multiple-oneof-members", "nesting-too-deep", "too-many-objects", "malformed-type-url",
        "unsupported-message-type", "not-an-any-envelope",
    }
    assert section_3_2 <= set(codec.DECODER_CODES)
    mapping = RECORD.read_text(encoding="utf-8")
    for code in codec.DECODER_CODES + codec.ADAPTER_CODES:
        assert f"`{code}`" in mapping, f"{code} is raised and the record does not name it"


# ================================================================================ varints


@pytest.mark.parametrize("octets,value", [
    (b"\x00", 0),
    (b"\x01", 1),
    (b"\x7f", 127),                      # the largest one-octet varint: seven bits
    (b"\x80\x01", 128),                  # 0 | 1 << 7
    (b"\xac\x02", 300),                  # 0x2c | 0x02 << 7 = 44 + 256
    (b"\x80\x00", 0),                    # over-long, and still a varint: read, not refused
    # 2**64 - 1: nine groups of 0x7f and a tenth holding the 64th bit.
    (b"\xff" * 9 + b"\x01", (1 << 64) - 1),
])
def test_varints_read_little_endian_seven_bit_groups(octets, value):
    assert codec.read_varint(octets, 0, len(octets)) == (value, len(octets))


def test_a_varint_is_never_read_past_the_end_it_was_given():
    # 0x08 0x01 sit in the buffer, but the bound is offset 1: the varint at 0 is 0x80 then nothing.
    refused("truncated-varint", codec.read_varint, b"\x80\x08\x01", 0, 1)


def test_a_tenth_octet_that_sets_bits_past_the_64th_is_refused():
    # Nine 0xff groups are 63 bits; a tenth group of 0x7f adds bits 63..69. A lenient parser
    # drops bits 64..69, which is a repair.
    refused("varint-too-long", codec.read_varint, b"\xff" * 9 + b"\x7f", 0, 10)


def test_an_eleventh_octet_is_refused_before_it_is_read():
    refused("varint-too-long", codec.read_varint, b"\xff" * 10 + b"\x01", 0, 11)
    # Ten continuation octets and nothing after: still too long, not truncated.
    refused("varint-too-long", codec.read_varint, b"\xff" * 10, 0, 10)


# ======================================================================= the envelope (§2.1)


def test_the_smallest_successful_snapshot():
    # value = 0x0a 0x02 (field 1 `header`, wire type 2, two octets) 0x08 0x01 (field 1
    # `success`, wire type 0, true).
    assert codec.decode(envelope(b"\x0a\x02\x08\x01")) == twin(header={"success": True})


def test_the_type_url_prefix_is_carried_verbatim_and_not_checked():
    url = b"example.invalid/a/b/rheinmetall.tactical_api.v0.GetBlueForcesResponse"
    # 0x0a; len(url) = 15 ("example.invalid") + 5 ("/a/b/") + 49 = 69 = 0x45; url; 0x12 0x00
    # (an empty value).
    raw = b"\x0a\x45" + url + b"\x12\x00"
    assert codec.decode(raw) == {"@type": url.decode("ascii")}


def test_an_any_with_no_value_is_an_empty_response():
    # 0x0a 0x45 URL and no field 2: the response has no field on the wire, so no key.
    assert codec.decode(b"\x0a\x45" + GET_URL) == twin()


def test_the_subscribe_response_is_the_second_supported_type():
    # 0x0a 0x50 (80) URL, 0x12 0x04 value: 0x12 0x02 (field 2 `updated_blue_forces`, two
    # octets) 0x50 0x01 (field 10 `is_deleted` << 3 | 0 = 80 = 0x50, true).
    raw = b"\x0a\x50" + pw.SUBSCRIBE_URL + b"\x12\x04\x12\x02\x50\x01"
    assert codec.decode(raw) == {"@type": SUBSCRIBE_URL_TEXT,
                                 "updated_blue_forces": [{"is_deleted": True}]}


def test_the_envelope_type_url_is_read_without_decoding_the_response():
    # The value 0x12 0x01 0xff would be refused (a truncated varint inside an element).
    raw = envelope(b"\x12\x01\xff")
    assert codec.envelope_type_url(raw) == GET_URL_TEXT
    refused("truncated-varint", codec.decode, raw)


def test_bytearray_and_memoryview_decode_like_bytes():
    raw = envelope(b"\x0a\x02\x08\x01")
    assert codec.decode(bytearray(raw)) == codec.decode(memoryview(raw)) == codec.decode(raw)


# ===================================================================== presence rules (§2.2)


def test_a_default_valued_scalar_that_was_on_the_wire_stays_present():
    # header: 0x0a 0x02 0x08 0x00 — `success` written with its default, false.
    # element: 0x12 0x10, then 16 octets:
    #   0x0a 0x0a identity, 10 octets: 0x12 0x08 `string_identity`, "EXERCISE" (8 octets)
    #   0x30 0x00   field 6 `own_blue_force` << 3 | 0 = 48 = 0x30, false
    #   0x50 0x00   field 10 `is_deleted` << 3 | 0 = 80 = 0x50, false
    value = (b"\x0a\x02\x08\x00"
             b"\x12\x10" b"\x0a\x0a\x12\x08EXERCISE" b"\x30\x00" b"\x50\x00")
    assert codec.decode(envelope(value)) == twin(
        header={"success": False},
        blue_forces=[{"identity": {"string_identity": "EXERCISE"},
                      "own_blue_force": False, "is_deleted": False}])


@pytest.mark.parametrize("element,expected", [
    # 0x0a 0x02 0x18 0x00: identity holding `int32_identity` (field 3 << 3 | 0 = 0x18) = 0.
    (b"\x0a\x02\x18\x00", {"identity": {"int32_identity": 0}}),
    # 0x0a 0x02 0x20 0x00: `int64_identity` (field 4 << 3 | 0 = 0x20) = 0, as decimal text.
    (b"\x0a\x02\x20\x00", {"identity": {"int64_identity": "0"}}),
    # 0x0a 0x02 0x12 0x00: `string_identity` holding the empty string.
    (b"\x0a\x02\x12\x00", {"identity": {"string_identity": ""}}),
    # 0x22 0x02 0x08 0x00: `symbol` (field 4 << 3 | 2 = 0x22), `symbol_catalog` = 0, by name.
    (b"\x22\x02\x08\x00", {"symbol": {"symbol_catalog": "SYMBOL_CATALOG_UNSPECIFIED"}}),
    # 0x3a 0x0b 0x1a 0x09 0x09 + eight zero octets: `point_location` (7 << 3 | 2 = 0x3a) holding
    # `geo_point` (3 << 3 | 2 = 0x1a) holding `latitude_coordinate` (1 << 3 | 1 = 0x09) = 0.0.
    (b"\x3a\x0b\x1a\x09\x09" + bytes(8),
     {"point_location": {"geo_point": {"latitude_coordinate": 0.0}}}),
])
def test_a_zero_on_the_wire_is_a_present_zero(element, expected):
    raw = envelope(b"\x12" + bytes([len(element)]) + element)
    assert codec.decode(raw) == twin(blue_forces=[expected])


def test_a_field_absent_from_the_wire_has_no_key():
    # An element holding only `is_deleted` = true: no identity, no times, no point.
    decoded = codec.decode(envelope(b"\x12\x02\x50\x01"))
    assert decoded == twin(blue_forces=[{"is_deleted": True}])
    assert set(decoded["blue_forces"][0]) == {"is_deleted"}


def test_an_empty_message_on_the_wire_is_an_empty_object():
    # 0x0a 0x00: `header` with length 0. 0x12 0x00: an element with length 0.
    assert codec.decode(envelope(b"\x0a\x00\x12\x00")) == twin(header={}, blue_forces=[{}])


def test_an_empty_wrapper_is_its_default_value():
    # element: 0x1a 0x00 `callsign` (3 << 3 | 2) empty; 0x3a 0x04 `point_location` holding
    # 0x22 0x00 `course` (4 << 3 | 2) empty and 0x12 0x00 `location_time` (2 << 3 | 2) empty.
    element = b"\x1a\x00" b"\x3a\x04\x22\x00\x12\x00"
    raw = envelope(b"\x12" + bytes([len(element)]) + element)
    assert codec.decode(raw) == twin(blue_forces=[{
        "callsign": "",
        "point_location": {"location_time": "1970-01-01T00:00:00Z", "course": 0.0}}])


def test_fields_are_keyed_in_field_number_order_whatever_the_wire_order():
    # 0x12 0x00 (an element) before 0x0a 0x02 0x08 0x01 (the header).
    decoded = codec.decode(envelope(b"\x12\x00\x0a\x02\x08\x01"))
    assert list(decoded) == ["@type", "header", "blue_forces"]


# ======================================================================== integer extremes


@pytest.mark.parametrize("identity,expected", [
    # int32 -2**31: 64-bit two's complement 0xffffffff80000000, groups 0x00 0x00 0x00 0x00 0x78
    # 0x7f 0x7f 0x7f 0x7f 0x01 -> 80 80 80 80 f8 ff ff ff ff 01.
    (b"\x18\x80\x80\x80\x80\xf8\xff\xff\xff\xff\x01", {"int32_identity": -2147483648}),
    # int32 2**31 - 1 = 0x7fffffff: groups 0x7f 0x7f 0x7f 0x7f 0x07 -> ff ff ff ff 07.
    (b"\x18\xff\xff\xff\xff\x07", {"int32_identity": 2147483647}),
    # int32 -1: 0xffffffffffffffff, nine 0x7f groups and 0x01.
    (b"\x18" + b"\xff" * 9 + b"\x01", {"int32_identity": -1}),
    # int64 -2**63 = 0x8000000000000000: nine zero groups and 0x01 -> 80 x9, 01.
    (b"\x20" + b"\x80" * 9 + b"\x01", {"int64_identity": "-9223372036854775808"}),
    # int64 2**63 - 1: nine 0x7f groups -> ff x8, 7f.
    (b"\x20" + b"\xff" * 8 + b"\x7f", {"int64_identity": "9223372036854775807"}),
    # int64 -1: ten octets, as int32.
    (b"\x20" + b"\xff" * 9 + b"\x01", {"int64_identity": "-1"}),
])
def test_negative_and_extreme_integers(identity, expected):
    element = b"\x0a" + bytes([len(identity)]) + identity
    raw = envelope(b"\x12" + bytes([len(element)]) + element)
    assert codec.decode(raw) == twin(blue_forces=[{"identity": expected}])


def test_an_int32_written_as_32_bit_unsigned_is_refused_not_wrapped():
    # 0x18 then 2**31 = groups 0x00 0x00 0x00 0x00 0x08 -> 80 80 80 80 08. A lenient parser keeps
    # the low 32 bits and reads -2**31.
    refused("value-out-of-range", codec.decode_message, b"\x18\x80\x80\x80\x80\x08",
            f"{codec.PACKAGE}.Identity")


# ============================================================================= Timestamp


@pytest.mark.parametrize("octets,text", [
    # Nothing on the wire: seconds 0 and nanos 0, the epoch.
    (b"", "1970-01-01T00:00:00Z"),
    # seconds 1767225600 = 2026-01-01T00:00:00Z = 0x6955b900: groups 0x00 0x72 0x56 0x4a 0x06.
    (b"\x08\x80\xf2\xd6\xca\x06", "2026-01-01T00:00:00Z"),
    # + nanos 500 000 000 = 0x1dcd6500: groups 0x00 0x4a 0x35 0x6e 0x01. Whole milliseconds: 3.
    (b"\x08\x80\xf2\xd6\xca\x06\x10\x80\xca\xb5\xee\x01", "2026-01-01T00:00:00.500Z"),
    # nanos 1 000 000 = 0xf4240: groups 0x40 0x04 0x3d -> c0 84 3d. One millisecond: 3 digits.
    (b"\x10\xc0\x84\x3d", "1970-01-01T00:00:00.001Z"),
    # nanos 7 000 = 0x1b58: groups 0x58 0x36 -> d8 36. Whole microseconds: 6 digits.
    (b"\x10\xd8\x36", "1970-01-01T00:00:00.000007Z"),
    # nanos 123 456 000: whole microseconds -> 80 94 ef 3a.
    (b"\x10\x80\x94\xef\x3a", "1970-01-01T00:00:00.123456Z"),
    # nanos 100 = 0x64: not whole microseconds, 9 digits.
    (b"\x10\x64", "1970-01-01T00:00:00.000000100Z"),
    # nanos 1: 9 digits.
    (b"\x10\x01", "1970-01-01T00:00:00.000000001Z"),
    # seconds -62 135 596 800 (0001-01-01T00:00:00Z, the first second Timestamp allows): two's
    # complement 0xfffffff1886e0900, groups 0x00 0x12 0x38 0x43 0x18 0x7e 0x7f 0x7f 0x7f 0x01.
    (b"\x08\x80\x92\xb8\xc3\x98\xfe\xff\xff\xff\x01", "0001-01-01T00:00:00Z"),
    # seconds 253 402 300 799 (9999-12-31T23:59:59Z) = 0x3afff4417f: groups 0x7f 0x02 0x51 0x7f
    # 0x2f 0x07; nanos 999 999 999 = 0x3b9ac9ff: groups 0x7f 0x13 0x6b 0x5c 0x03.
    (b"\x08\xff\x82\xd1\xff\xaf\x07\x10\xff\x93\xeb\xdc\x03", "9999-12-31T23:59:59.999999999Z"),
    # seconds -1: one second before the epoch, ten octets.
    (b"\x08" + b"\xff" * 9 + b"\x01", "1969-12-31T23:59:59Z"),
])
def test_timestamps_render_as_rfc3339_with_0_3_6_or_9_digits(octets, text):
    assert codec.decode_message(octets, codec.TIMESTAMP) == text


@pytest.mark.parametrize("octets", [
    # seconds -62 135 596 801: one before the first allowed second. Low group 0x7f, next 0x11.
    b"\x08\xff\x91\xb8\xc3\x98\xfe\xff\xff\xff\x01",
    # seconds 253 402 300 800: one past the last. Groups 0x00 0x03 0x51 0x7f 0x2f 0x07.
    b"\x08\x80\x83\xd1\xff\xaf\x07",
    # nanos 1 000 000 000 = 0x3b9aca00: groups 0x00 0x14 0x6b 0x5c 0x03.
    b"\x10\x80\x94\xeb\xdc\x03",
    # nanos -1: an int32 -1 is ten octets.
    b"\x10" + b"\xff" * 9 + b"\x01",
])
def test_a_timestamp_outside_its_range_is_refused(octets):
    refused("timestamp-out-of-range", codec.decode_message, octets, codec.TIMESTAMP)


# ==================================================================== doubles, strings, enums


def test_doubles_are_little_endian_ieee_754():
    # 0x09 = field 1 << 3 | 1. 52.52 = 0x404a428f5c28f5c3, stored least significant octet first.
    assert codec.decode_message(b"\x09\xc3\xf5\x28\x5c\x8f\x42\x4a\x40",
                                f"{codec.PACKAGE}.GeoPoint") == {"latitude_coordinate": 52.52}
    # -0.0 is the sign bit only (0x8000000000000000) and stays -0.0.
    decoded = codec.decode_message(b"\x11" + bytes(7) + b"\x80", f"{codec.PACKAGE}.GeoPoint")
    assert str(decoded["longitude_coordinate"]) == "-0.0"


def test_strings_are_utf8():
    # 0x0a 0x02 0xc3 0xa4: StringValue.value = U+00E4, two octets in UTF-8.
    assert codec.decode_message(b"\x0a\x02\xc3\xa4", codec.STRING_VALUE) == "ä"


def test_a_named_enum_value_is_its_name_and_an_unnamed_one_stays_a_number():
    # GeoPoint: 0x20 0x0b `vertical_distance_reference_code` (4 << 3 | 0) = 11; 0x28 0x09
    # `measurement_code` (5 << 3 | 0) = 9, which the contract does not name.
    assert codec.decode_message(b"\x20\x0b\x28\x09", f"{codec.PACKAGE}.GeoPoint") == {
        "vertical_distance_reference_code":
            "VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID",
        "measurement_code": 9}
    # A negative enum number (int32 -1, ten octets) is unnamed too, and kept.
    assert codec.decode_message(b"\x28" + b"\xff" * 9 + b"\x01",
                                f"{codec.PACKAGE}.GeoPoint") == {"measurement_code": -1}


# ======================================================================== protoc vectors

#: The `uuid_identity` of the snapshot's second blue force. It is the adapter's own value, the
#: uuid5 of an EXERCISE name (checked below), because every value in a vector is synthetic and of
#: the adapter's making; none is taken from the contract's text. SNAPSHOT_SOURCE spells it out
#: because that is the text protoc read.
EXERCISE_UNIT_UUID = "2c60c853-0dd4-5319-ba2a-16a6ab982821"

#: protoc 36.2, `--encode=google.protobuf.Any`, with the pinned blue_force_tracking_service.proto
#: and google/protobuf/any.proto, read this source and wrote SNAPSHOT_BYTES (405 octets).
SNAPSHOT_SOURCE = """\
[type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse] {
  header { success: true }
  blue_forces {
    identity { string_identity: "EXERCISE-BF-001" }
    last_contact_time { seconds: 1767225600 nanos: 500000000 }
    callsign { value: "EXERCISE ALPHA 1" }
    symbol {
      symbol_catalog: SYMBOL_CATALOG_MIL2525_D
      numeric_identifier { first_ten_digits: 1003100000 second_ten_digits: 1211000000 }
    }
    blue_force_type { is_vehicle: true is_leader: true }
    point_location {
      name { value: "EXERCISE POINT" }
      location_time { seconds: 1767225605 nanos: 123456000 }
      geo_point {
        latitude_coordinate: 52.52
        longitude_coordinate: -13.405
        vertical_distance { value: 34.5 }
        vertical_distance_reference_code: VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID
        measurement_code: MEASUREMENT_CODE_GPS
      }
      course { value: 90.25 }
      speed { value: 12.5 }
    }
  }
  blue_forces {
    identity { int64_identity: -9223372036854775808 }
    last_contact_time { seconds: -62135596800 }
    symbol { symbol_catalog: SYMBOL_CATALOG_MIL2525_C string_identifier: "SFGPUCI----D---" }
    mount_host { int32_identity: -2147483648 }
    associated_organization_unit_identity { uuid_identity: "2c60c853-0dd4-5319-ba2a-16a6ab982821" }
    is_deleted: true
  }
  blue_forces {
    identity { int32_identity: 2147483647 }
    last_contact_time { seconds: 253402300799 nanos: 999999999 }
    own_blue_force: true
    point_location {
      geo_point { latitude_coordinate: -90 longitude_coordinate: 180 measurement_code: 9 vertical_distance_reference_code: 42 }
    }
  }
}
"""
SNAPSHOT_BYTES = bytes.fromhex(
    "0a45747970652e676f6f676c65617069732e636f6d2f726865696e6d6574616c6c2e746163746963616c5f61"
    "70692e76302e476574426c7565466f72636573526573706f6e736512cb020a02080112a7010a11120f455845"
    "52434953452d42462d303031120c0880f2d6ca061080cab5ee011a120a10455845524349534520414c504841"
    "2031221008051a0c08e0aea8de0310c0c9b9c1042a04080118013a580a100a0e455845524349534520504f49"
    "4e54120b0885f2d6ca06108094ef3a1a2109c3f5285c8f424a40118fc2f5285ccf2ac01a0909000000000040"
    "4140200b280222090900000000009056402a0909000000000000294012660a0b208080808080808080800112"
    "0b088092b8c398feffffff0122130804120f534647505543492d2d2d2d442d2d2d420b1880808080f8ffffff"
    "ff014a260a2432633630633835332d306464342d353331392d626132612d3136613661623938323832315001"
    "12330a0618ffffffff07120d08ff82d1ffaf0710ff93ebdc0330013a181a160900000000008056c011000000"
    "0000806640202a2809")

#: Written by hand from SNAPSHOT_SOURCE, not from the decoder's output.
SNAPSHOT_TWIN = {
    "@type": GET_URL_TEXT,
    "header": {"success": True},
    "blue_forces": [
        {
            "identity": {"string_identity": "EXERCISE-BF-001"},
            "last_contact_time": "2026-01-01T00:00:00.500Z",
            "callsign": "EXERCISE ALPHA 1",
            "symbol": {"symbol_catalog": "SYMBOL_CATALOG_MIL2525_D",
                       "numeric_identifier": {"first_ten_digits": "1003100000",
                                              "second_ten_digits": "1211000000"}},
            "blue_force_type": {"is_vehicle": True, "is_leader": True},
            "point_location": {
                "name": "EXERCISE POINT",
                "location_time": "2026-01-01T00:00:05.123456Z",
                "geo_point": {
                    "latitude_coordinate": 52.52,
                    "longitude_coordinate": -13.405,
                    "vertical_distance": 34.5,
                    "vertical_distance_reference_code":
                        "VERTICAL_DISTANCE_REFERENCE_CODE_WGS84_REFERENCE_ELLIPSOID",
                    "measurement_code": "MEASUREMENT_CODE_GPS",
                },
                "course": 90.25,
                "speed": 12.5,
            },
        },
        {
            "identity": {"int64_identity": "-9223372036854775808"},
            "last_contact_time": "0001-01-01T00:00:00Z",
            "symbol": {"symbol_catalog": "SYMBOL_CATALOG_MIL2525_C",
                       "string_identifier": "SFGPUCI----D---"},
            "mount_host": {"int32_identity": -2147483648},
            "associated_organization_unit_identity": {"uuid_identity": EXERCISE_UNIT_UUID},
            "is_deleted": True,
        },
        {
            "identity": {"int32_identity": 2147483647},
            "last_contact_time": "9999-12-31T23:59:59.999999999Z",
            "own_blue_force": True,
            "point_location": {"geo_point": {
                "latitude_coordinate": -90.0,
                "longitude_coordinate": 180.0,
                "vertical_distance_reference_code": 42,
                "measurement_code": 9,
            }},
        },
    ],
}

#: protoc 36.2 as above, from this source; DELTA_BYTES is 163 octets. protoc writes no field
#: holding its proto3 default, so `success: false` and `seconds: 0` are not on the wire.
DELTA_SOURCE = """\
[type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse] {
  header { success: false error_message { value: "EXERCISE stream \\303\\244 closed" } }
  updated_blue_forces {
    identity { int64_identity: 9223372036854775807 }
    last_contact_time { seconds: 0 nanos: 1 }
    symbol { symbol_catalog: SYMBOL_CATALOG_RME numeric_identifier { first_ten_digits: -1 } }
    point_location { location_time { seconds: 1767225600 nanos: 7000 } }
  }
}
"""
DELTA_BYTES = bytes.fromhex(
    "0a50747970652e676f6f676c65617069732e636f6d2f726865696e6d6574616c6c2e746163746963616c5f61"
    "70692e76302e537562736372696265426c7565466f7263654576656e7473526573706f6e7365124f0a1d121b"
    "0a1945584552434953452073747265616d20c3a420636c6f736564122e0a0a20ffffffffffffffff7f120210"
    "01220f08011a0b08ffffffffffffffffff013a0b12090880f2d6ca0610d836")

DELTA_TWIN = {
    "@type": SUBSCRIBE_URL_TEXT,
    "header": {"error_message": "EXERCISE stream ä closed"},
    "updated_blue_forces": [{
        "identity": {"int64_identity": "9223372036854775807"},
        "last_contact_time": "1970-01-01T00:00:00.000000001Z",
        "symbol": {"symbol_catalog": "SYMBOL_CATALOG_RME",
                   "numeric_identifier": {"first_ten_digits": "-1"}},
        "point_location": {"location_time": "2026-01-01T00:00:00.000007Z"},
    }],
}


@pytest.mark.parametrize("raw,expected", [(SNAPSHOT_BYTES, SNAPSHOT_TWIN),
                                          (DELTA_BYTES, DELTA_TWIN)], ids=["snapshot", "delta"])
def test_protoc_written_payloads_decode_to_the_twin_their_source_states(raw, expected):
    decoded = codec.decode(raw)
    assert decoded == expected
    assert json.dumps(decoded, ensure_ascii=False) == json.dumps(expected, ensure_ascii=False)


def test_the_snapshot_uuid_is_the_adapters_own():
    """The vector's one UUID is recomputed from the EXERCISE name it was made from, so a value
    copied from elsewhere (an example in the contract's comments, say) cannot stand in for it.
    `tests/test_cdm_tacticalapi_contract_text.py` holds every file of the adapter free of the
    contract's comment-only literals; this test says where this value came from instead."""
    made = uuid.uuid5(uuid.NAMESPACE_URL, "urn:exercise:EXERCISE-UNIT-001")
    assert EXERCISE_UNIT_UUID == str(made)
    assert SNAPSHOT_SOURCE.count(f'uuid_identity: "{EXERCISE_UNIT_UUID}"') == 1
    # 0x0a 0x24: `uuid_identity` (1 << 3 | 2), 36 octets; then the text as written.
    assert SNAPSHOT_BYTES.count(b"\x0a\x24" + EXERCISE_UNIT_UUID.encode("ascii")) == 1


@pytest.mark.parametrize("raw", [SNAPSHOT_BYTES, DELTA_BYTES], ids=["snapshot", "delta"])
def test_both_forms_of_one_message_give_the_same_twin(raw):
    decoded = codec.decode(raw)
    from_json = codec.validate_twin(json.loads(json.dumps(decoded)))
    assert from_json == decoded
    assert json.dumps(from_json) == json.dumps(decoded)
    assert codec.twin_of(raw) == codec.twin_of(json.loads(json.dumps(decoded))) == decoded


def test_the_test_writer_reproduces_protoc_bytes():
    """`tests/tacticalapi_protowire.py` writes DELTA_SOURCE field by field and must land on
    protoc's octets; only then is it fit to write the bulk inputs below."""
    header = pw.field_len(2, pw.field_len(1, "EXERCISE stream ä closed".encode("utf-8")))
    element = (pw.field_len(1, pw.field_varint(4, (1 << 63) - 1))
               + pw.field_len(2, pw.field_varint(2, 1))
               + pw.field_len(4, pw.field_varint(1, 1) + pw.field_len(3, pw.field_varint(1, -1)))
               + pw.field_len(7, pw.field_len(2, pw.field_varint(1, 1767225600)
                                              + pw.field_varint(2, 7000))))
    written = pw.any_of(pw.field_len(1, header) + pw.field_len(2, element), pw.SUBSCRIBE_URL)
    assert written == DELTA_BYTES


# ========================================================== unknown fields are carried (§3.3)

#: One unknown field per wire type, written out.
UNKNOWN = {
    # field 15 << 3 | 0 = 120 = 0x78; varint 7.
    0: (b"\x78\x07", {"number": 15, "wire_type": 0, "hex": "07"}),
    # field 16 << 3 | 1 = 129: groups 0x01 0x01 -> 81 01; eight octets.
    1: (b"\x81\x01\x01\x02\x03\x04\x05\x06\x07\x08",
        {"number": 16, "wire_type": 1, "hex": "0102030405060708"}),
    # field 99 << 3 | 2 = 794 = 6 * 128 + 26: groups 0x1a 0x06 -> 9a 06; length 3; "abc". The
    # hex is the value's octets, without the length prefix.
    2: (b"\x9a\x06\x03abc", {"number": 99, "wire_type": 2, "hex": "616263"}),
    # field 17 << 3 | 5 = 141: groups 0x0d 0x01 -> 8d 01; four octets.
    5: (b"\x8d\x01\xde\xad\xbe\xef", {"number": 17, "wire_type": 5, "hex": "deadbeef"}),
}

F = codec.PACKAGE


def _nest(keys: list, leaf: dict) -> dict:
    """{"a": {"b": leaf}} for ["a", "b"]; a key ending in "[]" is a one-element list."""
    for key in reversed(keys):
        leaf = {key[:-2]: [leaf]} if key.endswith("[]") else {key: leaf}
    return leaf


#: Every message the twin renders as an object: (url, how the unknown field is wrapped on the
#: wire, the keys down to it, the path `unknown_fields` reports).
LEVELS = {
    "GetBlueForcesResponse": (pw.GET_URL, lambda u: u, [], ""),
    "SubscribeBlueForceEventsResponse": (pw.SUBSCRIBE_URL, lambda u: u, [], ""),
    "ResponseHeader": (pw.GET_URL, lambda u: pw.field_len(1, u), ["header"], "header"),
    "BlueForce": (pw.GET_URL, lambda u: pw.field_len(2, u), ["blue_forces[]"], "blue_forces[0]"),
    "BlueForce (updated)": (pw.SUBSCRIBE_URL, lambda u: pw.field_len(2, u),
                            ["updated_blue_forces[]"], "updated_blue_forces[0]"),
    "Identity": (pw.GET_URL, lambda u: pw.field_len(2, pw.field_len(1, u)),
                 ["blue_forces[]", "identity"], "blue_forces[0].identity"),
    "SymbolIdentifier": (pw.GET_URL, lambda u: pw.field_len(2, pw.field_len(4, u)),
                         ["blue_forces[]", "symbol"], "blue_forces[0].symbol"),
    "NumericIdentifier": (pw.GET_URL,
                          lambda u: pw.field_len(2, pw.field_len(4, pw.field_len(3, u))),
                          ["blue_forces[]", "symbol", "numeric_identifier"],
                          "blue_forces[0].symbol.numeric_identifier"),
    "BlueForceType": (pw.GET_URL, lambda u: pw.field_len(2, pw.field_len(5, u)),
                      ["blue_forces[]", "blue_force_type"], "blue_forces[0].blue_force_type"),
    "Point": (pw.GET_URL, lambda u: pw.field_len(2, pw.field_len(7, u)),
              ["blue_forces[]", "point_location"], "blue_forces[0].point_location"),
    "GeoPoint": (pw.GET_URL, lambda u: pw.field_len(2, pw.field_len(7, pw.field_len(3, u))),
                 ["blue_forces[]", "point_location", "geo_point"],
                 "blue_forces[0].point_location.geo_point"),
}


@pytest.mark.parametrize("wire_type", sorted(UNKNOWN))
@pytest.mark.parametrize("level", sorted(LEVELS))
def test_an_unknown_field_is_carried_at_every_level_and_wire_type(level, wire_type):
    url, wrap, keys, path = LEVELS[level]
    octets, entry = UNKNOWN[wire_type]
    decoded = codec.decode(pw.any_of(wrap(octets), url))
    assert decoded == {"@type": url.decode("ascii"), **_nest(keys, {"@unknown": [entry]})}
    assert codec.unknown_fields(decoded) == [{"path": path, **entry}]
    assert codec.validate_twin(json.loads(json.dumps(decoded))) == decoded


def test_unknown_fields_keep_wire_order_and_raw_octets_beside_known_ones():
    # header: 0x78 0x87 0x00 (field 15, an over-long varint 7, kept as written), 0x08 0x01
    # (`success`), 0x9a 0x06 0x03 "abc" (field 99).
    header = b"\x78\x87\x00" b"\x08\x01" b"\x9a\x06\x03abc"
    decoded = codec.decode(envelope(b"\x0a" + bytes([len(header)]) + header))
    assert decoded == twin(header={"success": True, "@unknown": [
        {"number": 15, "wire_type": 0, "hex": "8700"},
        {"number": 99, "wire_type": 2, "hex": "616263"}]})


def test_the_largest_field_number_is_carried():
    # (2**29 - 1) << 3 | 0 = 0xfffffff8: groups 0x78 0x7f 0x7f 0x7f 0x0f -> f8 ff ff ff 0f.
    decoded = codec.decode(envelope(b"\xf8\xff\xff\xff\x0f\x00"))
    assert decoded == twin(**{"@unknown": [
        {"number": codec.MAX_FIELD_NUMBER, "wire_type": 0, "hex": "00"}]})


@pytest.mark.parametrize("type_name,octets", [
    # Timestamp field 3 (3 << 3 | 0 = 0x18).
    (codec.TIMESTAMP, b"\x18\x01"),
    # StringValue field 2 (2 << 3 | 0 = 0x10).
    (codec.STRING_VALUE, b"\x10\x01"),
    # DoubleValue field 2.
    (codec.DOUBLE_VALUE, b"\x10\x01"),
])
def test_an_unknown_field_inside_a_well_known_wrapper_is_refused(type_name, octets):
    refused("unknown-field-in-well-known-type", codec.decode_message, octets, type_name)


def test_an_unknown_field_on_the_any_envelope_is_refused():
    # After the envelope's two fields: 0x18 0x01, field 3 of google.protobuf.Any.
    refused("unknown-field-in-well-known-type", codec.decode, envelope(b"") + b"\x18\x01")


def test_an_unknown_field_in_a_nested_timestamp_is_refused_through_decode():
    # element: 0x12 0x02 `last_contact_time` holding 0x18 0x01.
    refused("unknown-field-in-well-known-type", codec.decode,
            envelope(b"\x12\x04\x12\x02\x18\x01"))


# ===================================================================== refusals, bytes form


@pytest.mark.parametrize("raw", [
    b"\x80",                         # a tag whose varint never ends
    b"\x0a",                         # a tag, and no length
    b"\x0a\x80",                     # a length whose varint never ends
    envelope(b"\x0a\x01\x08"),       # a one-octet header: `success` has a tag and no value
])
def test_truncated_varint(raw):
    refused("truncated-varint", codec.decode, raw)


@pytest.mark.parametrize("raw", [
    envelope(b"\x0a\x0c\x08" + b"\xff" * 10 + b"\x01"),   # eleven octets for `success`
    envelope(b"\x0a\x0b\x08" + b"\xff" * 9 + b"\x7f"),    # ten octets, 70 bits
])
def test_varint_too_long(raw):
    refused("varint-too-long", codec.decode, raw)


@pytest.mark.parametrize("raw", [
    b"\x0a\x05abc",                                   # type_url declares 5, 3 remain
    envelope(b"\x0a\x03\x08\x01"),                    # header declares 3, 2 remain
    # GeoPoint `latitude_coordinate` (wire type 1) with 7 of its 8 octets.
    envelope(b"\x12\x0c\x3a\x0a\x1a\x08\x09" + bytes(7)),
    # A fixed32 unknown field (17 << 3 | 5 -> 8d 01) with 3 of its 4 octets.
    envelope(b"\x8d\x01\x00\x00\x00"),
    # A length of 2**32 (groups 0 0 0 0 0x10), refused by comparison before any slice.
    envelope(b"\x0a\x80\x80\x80\x80\x10"),
])
def test_length_exceeds_input(raw):
    refused("length-exceeds-input", codec.decode, raw)


def test_a_length_is_bounded_by_its_enclosing_message_not_by_the_buffer():
    # An element of 4 octets (0x12 0x04) holding an identity that declares 3 (0x0a 0x03) where
    # 2 remain in the element; the buffer goes on with a header, which must not be borrowed.
    refused("length-exceeds-input", codec.decode,
            envelope(b"\x12\x04\x0a\x03\x12\x01" b"\x0a\x02\x08\x01"))


@pytest.mark.parametrize("tag", [
    b"\x0b",   # field 1 << 3 | 3, start group
    b"\x0c",   # field 1 << 3 | 4, end group
    b"\x0e",   # field 1 << 3 | 6
    b"\x0f",   # field 1 << 3 | 7
])
def test_unsupported_wire_type(tag):
    refused("unsupported-wire-type", codec.decode, envelope(tag + b"\x00"))


@pytest.mark.parametrize("tag", [b"\x00", b"\x02", b"\x05"])  # field 0, wire types 0, 2, 5
def test_field_number_zero(tag):
    refused("field-number-zero", codec.decode, envelope(tag + b"\x00\x00\x00\x00"))


def test_field_number_too_large():
    # Field 2**29: tag 2**32, groups 0x00 0x00 0x00 0x00 0x10 -> 80 80 80 80 10.
    refused("field-number-too-large", codec.decode, envelope(b"\x80\x80\x80\x80\x10\x00"))


@pytest.mark.parametrize("raw", [
    envelope(b"\x08\x01"),                          # `header` (a message) as a varint
    envelope(b"\x0a\x02\x0a\x00"),                  # `success` (a bool) as a length
    b"\x08\x01",                                    # `type_url` (a string) as a varint
    # `latitude_coordinate` (a double) as a fixed32: 0x0d = 1 << 3 | 5, four octets; geo_point
    # 0x1a 0x05, point 0x3a 0x07, element 0x12 0x09.
    envelope(b"\x12\x09\x3a\x07\x1a\x05\x0d\x00\x00\x00\x00"),
])
def test_wire_type_mismatch(raw):
    refused("wire-type-mismatch", codec.decode, raw)


@pytest.mark.parametrize("raw", [
    # callsign (0x1a, 3 << 3 | 2) holding StringValue 0x0a 0x01 0xff: 0xff never starts UTF-8.
    envelope(b"\x12\x05\x1a\x03\x0a\x01\xff"),
    # string_identity holding ed a0 80, the UTF-8 shape of the surrogate U+D800, which UTF-8
    # excludes.
    envelope(b"\x12\x07\x0a\x05\x12\x03\xed\xa0\x80"),
    # An overlong encoding of "/" (c0 af) in the type_url.
    b"\x0a\x02\xc0\xaf",
])
def test_invalid_utf8(raw):
    refused("invalid-utf8", codec.decode, raw)


@pytest.mark.parametrize("value", [
    b"\x00\x00\x00\x00\x00\x00\xf8\x7f",   # quiet NaN
    b"\x00\x00\x00\x00\x00\x00\xf0\x7f",   # +infinity
    b"\x00\x00\x00\x00\x00\x00\xf0\xff",   # -infinity
])
def test_non_finite_number(value):
    # latitude: element 0x12 0x0d > point 0x3a 0x0b > geo_point 0x1a 0x09 > 0x09 + 8 octets.
    refused("non-finite-number", codec.decode, envelope(b"\x12\x0d\x3a\x0b\x1a\x09\x09" + value))
    # speed: element 0x12 0x0d > point 0x3a 0x0b > speed (5 << 3 | 2 = 0x2a) 0x09 > 0x09 + 8.
    refused("non-finite-number", codec.decode, envelope(b"\x12\x0d\x3a\x0b\x2a\x09\x09" + value))


def test_timestamp_out_of_range_through_decode():
    # element 0x12 0x09 > last_contact_time 0x12 0x07 > seconds 253 402 300 800 (one past).
    refused("timestamp-out-of-range", codec.decode,
            envelope(b"\x12\x09\x12\x07\x08\x80\x83\xd1\xff\xaf\x07"))


@pytest.mark.parametrize("raw", [
    envelope(b"\x0a\x00\x0a\x00"),                  # `header` twice
    envelope(b"\x0a\x04\x08\x01\x08\x01"),          # `success` twice, both true
    envelope(b"\x12\x04\x30\x00\x30\x01"),          # `own_blue_force` false then true
    b"\x0a\x45" + GET_URL + b"\x0a\x45" + GET_URL,  # `type_url` twice
    envelope(b"") + b"\x12\x00",                    # `value` twice
])
def test_repeated_singular_field(raw):
    refused("repeated-singular-field", codec.decode, raw)


@pytest.mark.parametrize("raw", [
    # identity: string_identity "A" (0x12 0x01 0x41) and int32_identity 1 (0x18 0x01).
    envelope(b"\x12\x07\x0a\x05\x12\x01A\x18\x01"),
    # symbol: string_identifier (0x12 0x00) and numeric_identifier (0x1a 0x00).
    envelope(b"\x12\x06\x22\x04\x12\x00\x1a\x00"),
])
def test_multiple_oneof_members(raw):
    refused("multiple-oneof-members", codec.decode, raw)


def test_one_oneof_member_twice_is_a_repeated_singular_field():
    # string_identity twice: the same member, so it is the singular rule that refuses it.
    refused("repeated-singular-field", codec.decode,
            envelope(b"\x12\x08\x0a\x06\x12\x01A\x12\x01B"))


@pytest.mark.parametrize("raw", [
    b"\x0a\x08no-slash\x12\x00",
    b"\x0a\x00",                                     # an empty type_url
])
def test_malformed_type_url(raw):
    refused("malformed-type-url", codec.decode, raw)


@pytest.mark.parametrize("name", [
    b"rheinmetall.tactical_api.v0.AddOrUpdateBlueForcesResponse",   # the write side
    b"rheinmetall.tactical_api.v0.GetBlueForcesRequest",            # a request
    b"rheinmetall.tactical_api.v0.BlueForce",                       # an element, unwrapped
    b"google.protobuf.Timestamp",                                   # outside the contract
    b"",                                                            # nothing after the '/'
])
def test_unsupported_message_type_names_the_two_supported_types(name):
    url = b"type.googleapis.com/" + name
    error = refused("unsupported-message-type", codec.decode,
                    b"\x0a" + bytes([len(url)]) + url + b"\x12\x00")
    assert codec.GET_BLUE_FORCES_RESPONSE in str(error)
    assert codec.SUBSCRIBE_BLUE_FORCE_EVENTS_RESPONSE in str(error)


@pytest.mark.parametrize("raw", [
    b"",                     # nothing at all
    b"\x12\x00",             # an Any with a value and no type_url
])
def test_not_an_any_envelope(raw):
    refused("not-an-any-envelope", codec.decode, raw)


@pytest.mark.parametrize("raw", [
    envelope(b"\x0a\x02\x08\x02"),                   # bool 2
    envelope(b"\x0a\x0b\x08" + b"\xff" * 9 + b"\x01"),  # bool 2**64 - 1
    # measurement_code 2**31 (80 80 80 80 08): outside int32, which an enum is. geo_point 0x1a
    # 0x06 (0x28 + five octets), point 0x3a 0x08, element 0x12 0x0a.
    envelope(b"\x12\x0a\x3a\x08\x1a\x06\x28\x80\x80\x80\x80\x08"),
    # Timestamp nanos 2**32 + 5 (85 80 80 80 10): a lenient parser would read 5. Timestamp 0x12
    # 0x06 (0x10 + five octets), element 0x12 0x08.
    envelope(b"\x12\x08\x12\x06\x10\x85\x80\x80\x80\x10"),
])
def test_value_out_of_range(raw):
    refused("value-out-of-range", codec.decode, raw)


def test_the_first_failing_tag_check_is_the_refusal():
    # Field 0 with wire type 3 (tag 0x03): the zero field number is reported, not the group.
    refused("field-number-zero", codec.decode, envelope(b"\x03"))


def test_a_string_is_not_handed_to_the_bytes_decoder():
    refused("not-an-any-envelope", codec.twin_of, "0a45")
    refused("not-an-any-envelope", codec.twin_of, ["@type"])


# ============================================================================== dict form


def test_a_dict_form_is_normalised_to_the_spelling_decode_writes():
    given = {
        "blue_forces": [{
            "point_location": {
                "geo_point": {"latitude_coordinate": 52, "longitude_coordinate": -13.405},
                "speed": 0,
                "location_time": "2026-01-01T00:00:05.123456000Z",
            },
            "last_contact_time": "2026-01-01T00:00:00.000Z",
            "identity": {"string_identity": "EXERCISE-BF-001"},
        }],
        "header": {"success": True},
        "@type": GET_URL_TEXT,
    }
    normalised = codec.validate_twin(given)
    assert normalised == twin(header={"success": True}, blue_forces=[{
        "identity": {"string_identity": "EXERCISE-BF-001"},
        "last_contact_time": "2026-01-01T00:00:00Z",
        "point_location": {
            "location_time": "2026-01-01T00:00:05.123456Z",
            "geo_point": {"latitude_coordinate": 52.0, "longitude_coordinate": -13.405},
            "speed": 0.0,
        },
    }])
    assert list(normalised) == ["@type", "header", "blue_forces"]
    assert list(normalised["blue_forces"][0]["point_location"]) == [
        "location_time", "geo_point", "speed"]
    assert isinstance(normalised["blue_forces"][0]["point_location"]["speed"], float)
    assert given["blue_forces"][0]["point_location"]["speed"] == 0   # the input is not changed


def test_a_hand_written_dict_and_its_bytes_give_one_twin():
    # Bytes, element 0x12 0x0e (14 octets): identity 0x0a 0x02 0x18 0x07 (int32 7); point 0x3a
    # 0x06 > geo_point 0x1a 0x04 > measurement_code 0x28 0x02 (GPS) and unknown field 15, 0x78
    # 0x07; is_deleted 0x50 0x01. 4 + 8 + 2 = 14.
    raw = envelope(b"\x12\x0e\x0a\x02\x18\x07\x3a\x06\x1a\x04\x28\x02\x78\x07\x50\x01")
    given = {"@type": GET_URL_TEXT, "blue_forces": [{
        "is_deleted": True,
        "point_location": {"geo_point": {
            "@unknown": [{"number": 15, "wire_type": 0, "hex": "07"}],
            "measurement_code": "MEASUREMENT_CODE_GPS"}},
        "identity": {"int32_identity": 7}}]}
    assert codec.validate_twin(given) == codec.decode(raw)
    assert json.dumps(codec.validate_twin(given)) == json.dumps(codec.decode(raw))


def test_an_empty_repeated_field_or_unknown_list_is_dropped():
    given = {"@type": GET_URL_TEXT, "blue_forces": [], "@unknown": []}
    assert codec.validate_twin(given) == codec.decode(envelope(b"")) == twin()


def test_a_dict_key_the_contract_does_not_name_is_carried_unchanged():
    value = {"a": [1, 2.5, "x", True, {"b": []}]}
    given = {"@type": GET_URL_TEXT, "futureField": value,
             "header": {"newFlag": False, "success": True}}
    normalised = codec.validate_twin(given)
    assert normalised == {"@type": GET_URL_TEXT,
                          "header": {"success": True, "newFlag": False},
                          "futureField": value}
    assert codec.unknown_fields(normalised) == [
        {"path": "header", "key": "newFlag", "value": False},
        {"path": "", "key": "futureField", "value": value},
    ]
    # lowerCamelCase is not the contract's naming: it is an unknown key, carried, never mapped.
    assert codec.validate_twin({"@type": GET_URL_TEXT, "blueForces": [{}]}) == {
        "@type": GET_URL_TEXT, "blueForces": [{}]}


def test_validation_is_idempotent_on_its_own_output():
    for raw in (SNAPSHOT_BYTES, DELTA_BYTES):
        decoded = codec.decode(raw)
        assert codec.validate_twin(codec.validate_twin(decoded)) == decoded


@pytest.mark.parametrize("document", [
    {"@type": None},
    twin(header=None),
    twin(header={"success": None}),
    twin(blue_forces=[None]),
    twin(blue_forces=[{"identity": {"string_identity": None}}]),
    twin(**{"@unknown": [None]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": None}]}),
    twin(futureField={"a": [1, None]}),
])
def test_null_in_twin(document):
    refused("null-in-twin", codec.validate_twin, document)


@pytest.mark.parametrize("document", [
    {"header": {"success": True}},                   # no @type
    {},
])
def test_not_an_any_envelope_dict_form(document):
    refused("not-an-any-envelope", codec.validate_twin, document)


def test_not_an_any_envelope_for_a_non_dict():
    refused("not-an-any-envelope", codec.validate_twin, [GET_URL_TEXT])


def test_malformed_type_url_and_unsupported_type_dict_form():
    refused("malformed-type-url", codec.validate_twin, {"@type": "GetBlueForcesResponse"})
    refused("unsupported-message-type", codec.validate_twin,
            {"@type": "type.googleapis.com/rheinmetall.tactical_api.v0.Point"})


@pytest.mark.parametrize("document", [
    {"@type": GET_URL_TEXT + "\ud800"},
    twin(blue_forces=[{"callsign": "EXERCISE \udc00"}]),
    twin(blue_forces=[{"identity": {"uuid_identity": "\ud83d"}}]),
    twin(futureField=["\udfff"]),
    twin(**{"future\ud800": 1}),
])
def test_invalid_utf8_dict_form(document):
    """A lone surrogate is the only `str` that cannot be written as UTF-8 — and it is what a
    lenient decoder makes of a string field whose octets were not UTF-8."""
    refused("invalid-utf8", codec.validate_twin, document)


@pytest.mark.parametrize("document", [
    twin(blue_forces=[{"point_location": {"geo_point": {"latitude_coordinate": float("nan")}}}]),
    twin(blue_forces=[{"point_location": {"speed": float("inf")}}]),
    twin(blue_forces=[{"point_location": {"geo_point": {"vertical_distance": 10 ** 400}}}]),
    twin(futureField=[float("-inf")]),
])
def test_non_finite_number_dict_form(document):
    refused("non-finite-number", codec.validate_twin, document)


@pytest.mark.parametrize("text", ["0000-12-31T23:59:59Z", "0000-01-01T00:00:00.000Z"])
def test_timestamp_out_of_range_dict_form(text):
    refused("timestamp-out-of-range", codec.validate_twin,
            twin(blue_forces=[{"last_contact_time": text}]))


@pytest.mark.parametrize("identity", [
    {"string_identity": "EXERCISE", "int32_identity": 1},
    {"uuid_identity": "a", "int64_identity": "1"},
])
def test_multiple_oneof_members_dict_form(identity):
    refused("multiple-oneof-members", codec.validate_twin,
            twin(blue_forces=[{"identity": identity}]))


@pytest.mark.parametrize("document", [
    twin(blue_forces=[{"identity": {"int32_identity": 2 ** 31}}]),
    twin(blue_forces=[{"identity": {"int32_identity": -(2 ** 31) - 1}}]),
    twin(blue_forces=[{"identity": {"int64_identity": "9223372036854775808"}}]),
    twin(blue_forces=[{"identity": {"int64_identity": "-9223372036854775809"}}]),
    twin(blue_forces=[{"identity": {"int64_identity": "1" * 5000}}]),
    twin(blue_forces=[{"symbol": {"symbol_catalog": 2 ** 31}}]),
])
def test_value_out_of_range_dict_form(document):
    refused("value-out-of-range", codec.validate_twin, document)


@pytest.mark.parametrize("document", [
    twin(header={"success": 1}),                                          # bool as a number
    twin(header={"success": "true"}),                                     # bool as text
    twin(blue_forces=[{"identity": {"int32_identity": "7"}}]),            # int32 as text
    twin(blue_forces=[{"identity": {"int32_identity": 7.0}}]),            # int32 as a float
    twin(blue_forces=[{"identity": {"int64_identity": 7}}]),              # int64 as a number
    twin(blue_forces=[{"identity": {"int64_identity": "007"}}]),          # leading zeros
    twin(blue_forces=[{"identity": {"int64_identity": "-0"}}]),
    twin(blue_forces=[{"identity": {"int64_identity": "١"}}]),       # a non-ASCII digit
    twin(blue_forces=[{"symbol": {"symbol_catalog": "SYMBOL_CATALOG_NOT_A_NAME"}}]),
    twin(blue_forces=[{"symbol": {"symbol_catalog": 5}}]),                # a named number
    twin(blue_forces=[{"symbol": {"symbol_catalog": True}}]),
    twin(blue_forces=[{"last_contact_time": "2026-01-01T00:00:00+00:00"}]),   # an offset
    twin(blue_forces=[{"last_contact_time": "2026-01-01T00:00:00.5Z"}]),      # one digit
    twin(blue_forces=[{"last_contact_time": "2026-01-01 00:00:00Z"}]),
    twin(blue_forces=[{"last_contact_time": "2026-02-30T00:00:00Z"}]),
    twin(blue_forces=[{"last_contact_time": "2026-12-31T23:59:60Z"}]),       # a leap second
    twin(blue_forces=[{"last_contact_time": 1767225600}]),
    twin(blue_forces=[{"callsign": 7}]),
    twin(blue_forces=[{"point_location": {"speed": "1.5"}}]),
    twin(blue_forces=[{"point_location": {"speed": True}}]),
    twin(blue_forces={}),                                                  # repeated not a list
    twin(header=[]),                                                       # message not a dict
    twin(header={1: True}),                                                # a key not text
    twin(futureField=(1, 2)),                                              # not a JSON value
    twin(**{"@unknown": {}}),
    twin(**{"@unknown": ["x"]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0}]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07", "extra": 1}]}),
    twin(**{"@unknown": [{"number": "15", "wire_type": 0, "hex": "07"}]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "0A"}]}),       # uppercase
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "070"}]}),      # half an octet
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "0707"}]}),     # two varints
    twin(**{"@unknown": [{"number": 15, "wire_type": 1, "hex": "00"}]}),       # fixed64 of 1
    twin(**{"@unknown": [{"number": 15, "wire_type": 5, "hex": "0000000000"}]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 8, "hex": ""}]}),
    twin(**{"@unknown": [{"number": -1, "wire_type": 0, "hex": "00"}]}),
    twin(**{"@unknown": [{"number": 1, "wire_type": 2, "hex": ""}]}),  # field 1 is `header`
])
def test_invalid_twin_value(document):
    refused("invalid-twin-value", codec.validate_twin, document)


@pytest.mark.parametrize("entry,code", [
    ({"number": 0, "wire_type": 0, "hex": "00"}, "field-number-zero"),
    ({"number": 2 ** 29, "wire_type": 0, "hex": "00"}, "field-number-too-large"),
    ({"number": 15, "wire_type": 3, "hex": ""}, "unsupported-wire-type"),
    ({"number": 15, "wire_type": 7, "hex": ""}, "unsupported-wire-type"),
    ({"number": 15, "wire_type": 0, "hex": ""}, "truncated-varint"),
    ({"number": 15, "wire_type": 0, "hex": "80"}, "truncated-varint"),
    ({"number": 15, "wire_type": 0, "hex": "ff" * 10 + "01"}, "varint-too-long"),
])
def test_an_unknown_entry_is_held_to_the_wire_rules(entry, code):
    refused(code, codec.validate_twin, twin(**{"@unknown": [entry]}))


def test_the_dict_form_codes_that_cannot_apply():
    """Five codes have no dict-form occasion, and this records why rather than leaving a gap:
    `input-too-large` (a parsed twin is not an input size, `synapse_cdm.adapter.wire_size`),
    `length-exceeds-input` (no lengths), `repeated-singular-field` (an object's keys are unique),
    `wire-type-mismatch` (no wire types; a value of the wrong JSON type is `invalid-twin-value`)
    and `unknown-field-in-well-known-type` (a well-known type is a bare value and has no keys).
    The last two have dict-form counterparts, shown here."""
    refused("invalid-twin-value", codec.validate_twin, twin(header=True))
    refused("invalid-twin-value", codec.validate_twin,
            twin(blue_forces=[{"last_contact_time": {"seconds": "0", "nanos": 1}}]))


# ================================================================================== limits


def test_the_declared_limits_are_the_module_constants():
    assert codec.DEFAULT_LIMITS == DecodeLimits(
        max_input_bytes=codec.MAX_INPUT_BYTES, max_depth=codec.MAX_DEPTH,
        max_objects=codec.MAX_OBJECTS, max_unknown_fields=codec.MAX_UNKNOWN_FIELDS)
    assert (codec.MAX_INPUT_BYTES, codec.MAX_DEPTH, codec.MAX_OBJECTS,
            codec.MAX_UNKNOWN_FIELDS) == (4 * 1024 * 1024 + 1024, 64, 10_000, 65_536)


def _input_of_size(size: int) -> bytes:
    """An Any of exactly `size` octets: a successful header and one element whose callsign is
    padding. Lengths are varints, so the overhead is re-measured until it settles."""
    padding = size
    for _ in range(8):
        callsign = pw.field_len(3, pw.field_len(1, b"E" * padding))
        raw = pw.any_of(b"\x0a\x02\x08\x01" + pw.field_len(2, callsign))
        if len(raw) == size:
            return raw
        padding -= len(raw) - size
    raise AssertionError(f"no padding gives {size} octets")


def test_max_input_bytes_admits_the_bound_and_refuses_one_past():
    at_bound = _input_of_size(codec.MAX_INPUT_BYTES)
    assert len(at_bound) == codec.MAX_INPUT_BYTES
    decoded = codec.decode(at_bound)
    assert decoded["header"] == {"success": True}
    past = _input_of_size(codec.MAX_INPUT_BYTES + 1)
    for form in (past, bytearray(past), memoryview(past)):
        error = refused("input-too-large", codec.decode, form)
        assert str(codec.MAX_INPUT_BYTES) in str(error)
    refused("input-too-large", codec.envelope_type_url, past)


def test_max_objects_admits_the_bound_and_refuses_one_past():
    # 0x12 0x00: an empty element, two octets each.
    at_bound = pw.any_of(b"\x12\x00" * codec.MAX_OBJECTS)
    assert len(codec.decode(at_bound)["blue_forces"]) == codec.MAX_OBJECTS
    refused("too-many-objects", codec.decode, pw.any_of(b"\x12\x00" * (codec.MAX_OBJECTS + 1)))
    subscribe = pw.any_of(b"\x12\x00" * (codec.MAX_OBJECTS + 1), pw.SUBSCRIBE_URL)
    refused("too-many-objects", codec.decode, subscribe)


def test_max_objects_is_counted_before_any_element_is_decoded():
    # The first element is malformed (0x12 0x01 0xff: a truncated varint inside it); with one
    # element too many, the count refuses first, so no element was read.
    raw = pw.any_of(b"\x12\x01\xff" + b"\x12\x00" * codec.MAX_OBJECTS)
    refused("too-many-objects", codec.decode, raw)
    refused("truncated-varint", codec.decode, pw.any_of(b"\x12\x01\xff"))


def test_max_objects_dict_form():
    assert len(codec.validate_twin(twin(blue_forces=[{}] * codec.MAX_OBJECTS))["blue_forces"]) \
        == codec.MAX_OBJECTS
    # One past, with a null first element: refused for the count, before any element is read.
    refused("too-many-objects", codec.validate_twin,
            twin(blue_forces=[None] + [{}] * codec.MAX_OBJECTS))


def test_max_unknown_fields_admits_the_bound_and_refuses_one_past():
    at_bound = pw.any_of(b"\x78\x07" * codec.MAX_UNKNOWN_FIELDS)
    assert len(codec.decode(at_bound)["@unknown"]) == codec.MAX_UNKNOWN_FIELDS
    # The count is per input: the one past sits in the header, a different message.
    past = pw.any_of(b"\x78\x07" * codec.MAX_UNKNOWN_FIELDS + b"\x0a\x02\x78\x07")
    refused("too-many-unknown-fields", codec.decode, past)


def test_max_unknown_fields_dict_form():
    entries = [{"number": 15, "wire_type": 0, "hex": "07"}] * codec.MAX_UNKNOWN_FIELDS
    assert len(codec.validate_twin(twin(**{"@unknown": entries}))["@unknown"]) \
        == codec.MAX_UNKNOWN_FIELDS
    refused("too-many-unknown-fields", codec.validate_twin,
            twin(**{"@unknown": entries, "futureField": 1}))


def _twin_of_depth(depth: int) -> dict:
    """A twin `depth` containers deep: the top object (1), the header (2), and an unknown key's
    value nesting lists for the rest."""
    value: list = []
    for _ in range(depth - 3):
        value = [value]
    return twin(header={"futureField": value})


def test_max_depth_dict_form_admits_the_bound_and_refuses_one_past():
    at_bound = _twin_of_depth(codec.MAX_DEPTH)
    assert codec.twin_depth(at_bound) == container_depth(at_bound) == codec.MAX_DEPTH
    assert codec.validate_twin(at_bound) == at_bound
    past = _twin_of_depth(codec.MAX_DEPTH + 1)
    assert container_depth(past) == codec.MAX_DEPTH + 1
    refused("nesting-too-deep", codec.validate_twin, past)


def test_the_bytes_form_cannot_reach_the_declared_depth():
    """The closure has no recursive message and an unknown field is carried as octets, so the
    deepest twin the bytes form can produce is fixed by the table. Computed from the table here
    (2 per repeated element, 1 per nested object, 2 for `@unknown` and its entry) and shown on
    a payload that reaches it."""
    def deepest(type_name: str) -> int:
        below = [(2 if field.repeated else 1) + deepest(field.type)
                 for field in codec.MESSAGES[type_name].values()
                 if field.kind == "message" and field.type not in codec.WELL_KNOWN_TYPES]
        return max(below + [2])   # 2: an `@unknown` list and its entry
    table_bound = 1 + max(deepest(name) for name in codec.SUPPORTED_TYPES)
    assert table_bound == 7 < codec.MAX_DEPTH
    deepest_payload = codec.decode(pw.any_of(
        pw.field_len(2, pw.field_len(7, pw.field_len(3, b"\x78\x07")))))
    assert codec.twin_depth(deepest_payload) == container_depth(deepest_payload) == table_bound


def test_the_bytes_form_depth_guard_at_a_lowered_bound():
    """The guard the declared bound leaves out of reach, exercised at a bound the payload does
    reach: a `geo_point` is an object 5 deep and its unknown field's entry is 7 deep."""
    geo_point = pw.any_of(pw.field_len(2, pw.field_len(7, pw.field_len(3, b"\x09" + bytes(8)))))
    assert codec.decode(geo_point, limits=DecodeLimits(max_depth=5))
    refused("nesting-too-deep", codec.decode, geo_point, limits=DecodeLimits(max_depth=4))
    with_unknown = pw.any_of(pw.field_len(2, pw.field_len(7, pw.field_len(3, b"\x78\x07"))))
    assert codec.decode(with_unknown, limits=DecodeLimits(max_depth=7))
    refused("nesting-too-deep", codec.decode, with_unknown, limits=DecodeLimits(max_depth=6))


# ============================================================================ the field table


def test_the_table_is_exactly_the_closure_mapping_names():
    assert set(codec.MESSAGES) == set(gen_field_table.EXPECTED_MESSAGES)
    assert set(codec.ENUMS) == set(gen_field_table.EXPECTED_ENUMS)


def test_every_reference_in_the_table_resolves_and_every_kind_has_a_wire_type():
    for message, fields in codec.MESSAGES.items():
        for number, field in fields.items():
            assert 1 <= number <= codec.MAX_FIELD_NUMBER
            assert field.kind in codec.WIRE_TYPE_OF_KIND, (message, field)
            if field.kind == "message":
                assert field.type in codec.MESSAGES
            elif field.kind == "enum":
                assert field.type in codec.ENUMS
            else:
                assert field.type is None
            assert not field.repeated or field.kind == "message"


def embedded_block() -> str:
    """The codec's table block, from its BEGIN line through its END line, as written on disk."""
    text = CODEC_SOURCE.read_text(encoding="utf-8")
    start = text.index(gen_field_table.BEGIN + "\n")
    end = text.index(gen_field_table.END + "\n") + len(gen_field_table.END + "\n")
    return text[start:end]


def test_embedded_table_matches_the_pinned_descriptor():
    """protoc's reading of the pinned files, regenerated now, against the block in the codec.

    Skipped — never passed — with a reason beginning BLOCKED_EXTERNAL_EVIDENCE when
    `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` is unset or empty, the directory does not verify against
    its record, or protoc is absent.
    """
    try:
        generated = gen_field_table.generate()
    except NormativeBindingBlocked as blocked:
        pytest.skip(f"{BLOCKED_STATUS} at step {blocked.step!r}: {blocked.reason}")
    except gen_field_table.ProtocUnavailable as blocked:
        pytest.skip(f"{BLOCKED_STATUS} at step 'protoc': {blocked}")
    assert generated == embedded_block()


def test_the_generator_refuses_an_unset_pin_rather_than_reading_anything(tmp_path):
    with pytest.raises(NormativeBindingBlocked) as blocked:
        gen_field_table.resolve_pin(environ={})
    assert blocked.value.step == "hook"
    # A directory that holds no record (an empty one pytest made; the out-of-tree project's
    # `tests/` served until the move, 2026-10-06): the record step refuses it.
    with pytest.raises(NormativeBindingBlocked) as blocked:
        gen_field_table.resolve_pin(environ={gen_field_table.ENV_VAR: str(tmp_path)})
    assert blocked.value.step == "record"


# ===================================================== final verification, 2026-10-04: the wire
#
# The tests below close the findings the build pipeline's reviewers left open (the record
# "Changes", final verification). Each says which; every vector is still worked out by hand.


def test_a_tag_written_in_more_than_five_octets_is_refused():
    """A tag is a 32-bit value, so its varint is at most five octets; protoc refuses a longer one
    and a lenient parser reads it, which is a repair (the record §3.2, `varint-too-long`)."""
    # Inside the response: 8a 80 80 80 80 00 is field 1 (`header`) << 3 | 2 = 10 = 0x0a, padded
    # to six octets with five continuation groups of 0; then 0x02 and 0x08 0x01 (success true).
    refused("varint-too-long", codec.decode, envelope(b"\x8a\x80\x80\x80\x80\x00\x02\x08\x01"))
    # The envelope's own tag: field 1 (`type_url`) << 3 | 2 in ten octets, then 0x45 and the URL.
    refused("varint-too-long", codec.decode, b"\x8a" + b"\x80" * 8 + b"\x00\x45" + GET_URL)
    # The length is checked before the field number: 80 80 80 80 80 00 is field 0 in six octets.
    refused("varint-too-long", codec.decode, envelope(b"\x80\x80\x80\x80\x80\x00\x00"))


def test_a_tag_padded_to_exactly_five_octets_is_still_read():
    # 8a 80 80 80 00: the same tag 0x0a in five octets, which protoc reads too.
    assert codec.decode(envelope(b"\x8a\x80\x80\x80\x00\x02\x08\x01")) == twin(
        header={"success": True})


@pytest.mark.parametrize("type_name,octets", [
    # int32_identity (3 << 3 | 0 = 0x18) = -2**31 - 1 = 0xffffffff7fffffff as 64-bit two's
    # complement: groups 7f 7f 7f 7f 77 7f 7f 7f 7f 01 -> ff ff ff ff f7 ff ff ff ff 01.
    (f"{F}.Identity", b"\x18\xff\xff\xff\xff\xf7\xff\xff\xff\xff\x01"),
    # measurement_code (5 << 3 | 0 = 0x28), the same ten octets: an enum is 32 bits wide too.
    (f"{F}.GeoPoint", b"\x28\xff\xff\xff\xff\xf7\xff\xff\xff\xff\x01"),
])
def test_a_32_bit_value_below_its_range_is_refused(type_name, octets):
    """Mutation survivor 1: only the upper end of the range was exercised on the wire."""
    refused("value-out-of-range", codec.decode_message, octets, type_name)


@pytest.mark.parametrize("type_name,octets", [
    (codec.TIMESTAMP, b"\x08\x01\x08\x02"),                       # seconds (0x08) twice
    (codec.STRING_VALUE, b"\x0a\x01A\x0a\x01B"),                  # value (1 << 3 | 2) twice
    (codec.DOUBLE_VALUE, b"\x09" + bytes(8) + b"\x09" + bytes(8)),  # value (1 << 3 | 1) twice
])
def test_a_field_twice_inside_a_well_known_type_is_refused(type_name, octets):
    """Mutation survivor 4: the singular rule holds inside the bare-value types too; a lenient
    parser keeps the last."""
    refused("repeated-singular-field", codec.decode_message, octets, type_name)
    # The same inside a message: element 0x12 0x06 > last_contact_time 0x12 0x04 > 08 01 08 02.
    refused("repeated-singular-field", codec.decode, envelope(b"\x12\x06\x12\x04\x08\x01\x08\x02"))


def test_unknown_fields_reports_each_elements_own_path():
    """Mutation survivors 2 and 3: the adapter carries an element's unknown fields on that
    element's Entity by the index in this path, so every element is walked and named."""
    # Three elements: 0x12 0x00 (empty); 0x12 0x02 0x78 0x07 (field 15 << 3 | 0 = 0x78, value
    # 7); 0x12 0x04 0x3a 0x02 0x78 0x08 (point_location (7 << 3 | 2 = 0x3a) holding field 15 = 8).
    decoded = codec.decode(envelope(b"\x12\x00" b"\x12\x02\x78\x07" b"\x12\x04\x3a\x02\x78\x08"))
    assert codec.unknown_fields(decoded) == [
        {"path": "blue_forces[1]", "number": 15, "wire_type": 0, "hex": "07"},
        {"path": "blue_forces[2].point_location", "number": 15, "wire_type": 0, "hex": "08"}]


@pytest.mark.parametrize("octets,expected", [
    # GeoPoint: 0x20 0x03 vertical_distance_reference_code 3, 0x28 0x03 measurement_code 3. The
    # number 3 is named in all three enums, differently in each.
    (b"\x20\x03\x28\x03", {"vertical_distance_reference_code":
                           "VERTICAL_DISTANCE_REFERENCE_CODE_LOCAL_DATUM",
                           "measurement_code": "MEASUREMENT_CODE_INS"}),
])
def test_a_named_enum_number_is_named_from_its_own_enum(octets, expected):
    """Mutation survivor 17: only the skippable descriptor test held the names; here a number
    three enums share is named by the field's own enum."""
    assert codec.decode_message(octets, f"{F}.GeoPoint") == expected
    # SymbolIdentifier: 0x08 0x03 symbol_catalog 3.
    assert codec.decode_message(b"\x08\x03", f"{F}.SymbolIdentifier") == {
        "symbol_catalog": "SYMBOL_CATALOG_APP6_D"}


def test_envelope_type_url_refuses_what_decode_refuses_in_the_envelope():
    """Mutation survivor 16: reading the envelope only is not reading it leniently."""
    # After the envelope's two fields: 0x18 0x01, field 3 of google.protobuf.Any.
    refused("unknown-field-in-well-known-type", codec.envelope_type_url,
            envelope(b"") + b"\x18\x01")
    # The type_url's tag in six octets.
    refused("varint-too-long", codec.envelope_type_url,
            b"\x8a\x80\x80\x80\x80\x00\x45" + GET_URL)


def test_twin_of_applies_the_limits_it_is_given_to_both_forms():
    """Mutation survivors 14 and 15."""
    two = envelope(b"\x12\x00\x12\x00")       # two empty elements
    small = DecodeLimits(max_objects=1)
    assert codec.twin_of(two) == twin(blue_forces=[{}, {}])
    refused("too-many-objects", codec.twin_of, two, limits=small)
    refused("too-many-objects", codec.twin_of, twin(blue_forces=[{}, {}]), limits=small)


# ================================================ final verification: what the bytes readers take


def _string_value_of_size(size: int) -> bytes:
    """A StringValue of exactly `size` octets: 0x0a, a four-octet length (2**21 <= n < 2**28),
    and n octets of text."""
    length = size - 5
    octets = b"\x0a" + pw.varint(length) + b"E" * length
    assert len(octets) == size
    return octets


#: The three functions that read octets, each as a one-argument reader.
BYTES_READERS = {
    "decode": codec.decode,
    "envelope_type_url": codec.envelope_type_url,
    "decode_message": lambda raw, **kwargs: codec.decode_message(raw, codec.STRING_VALUE,
                                                                 **kwargs),
}


@pytest.mark.parametrize("value", ["0a45", None, [10, 0], 7], ids=["str", "None", "list", "int"])
@pytest.mark.parametrize("reader", sorted(BYTES_READERS))
def test_the_bytes_readers_refuse_anything_but_octets(reader, value):
    """A `str` and `None` raised a `TypeError` and a list of small integers was read as octets;
    each is now refused as `twin_of` refuses it (the record §3.2, `not-an-any-envelope`)."""
    error = refused("not-an-any-envelope", BYTES_READERS[reader], value)
    assert "bytes, bytearray or memoryview" in str(error)


def test_a_memoryview_is_read_like_bytes_by_each_bytes_reader():
    assert codec.decode(memoryview(SNAPSHOT_BYTES)) == SNAPSHOT_TWIN
    assert codec.envelope_type_url(memoryview(SNAPSHOT_BYTES)) == GET_URL_TEXT
    # 0x12 0x08 "EXERCISE": Identity.string_identity. A string field read from a memoryview
    # raised AttributeError before the input was copied to bytes.
    assert codec.decode_message(memoryview(b"\x12\x08EXERCISE"), f"{F}.Identity") == {
        "string_identity": "EXERCISE"}
    # 0x0a 0x02 0xc3 0xa4, StringValue "ä", seen as two two-octet items.
    assert codec.decode_message(memoryview(b"\x0a\x02\xc3\xa4").cast("H"),
                                codec.STRING_VALUE) == "ä"


def test_a_memoryview_is_measured_in_octets_not_in_items():
    """Mutation survivor 18: a memoryview whose items are two octets wide has half as many
    items as octets; the bound is in octets."""
    at_bound = _input_of_size(codec.MAX_INPUT_BYTES)
    wide = memoryview(at_bound).cast("H")
    assert (len(wide), wide.nbytes) == (codec.MAX_INPUT_BYTES // 2, codec.MAX_INPUT_BYTES)
    assert codec.decode(wide) == codec.decode(at_bound)
    past = memoryview(_input_of_size(codec.MAX_INPUT_BYTES + 2)).cast("H")
    for reader in sorted(BYTES_READERS):
        error = refused("input-too-large", BYTES_READERS[reader], past)
        assert f"the input is {codec.MAX_INPUT_BYTES + 2} octets" in str(error)


def test_decode_message_admits_the_bound_and_refuses_one_past():
    """Mutation survivor 13: the part reader is bounded as the envelope reader is."""
    at_bound = _string_value_of_size(codec.MAX_INPUT_BYTES)
    assert codec.decode_message(at_bound, codec.STRING_VALUE) == "E" * (codec.MAX_INPUT_BYTES - 5)
    past = _string_value_of_size(codec.MAX_INPUT_BYTES + 1)
    for form in (past, bytearray(past), memoryview(past)):
        refused("input-too-large", codec.decode_message, form, codec.STRING_VALUE)


# ================================================ final verification: the dict form's values


@pytest.mark.parametrize("document", [
    # A trailing character after the Z, and a lowercase z (mutation survivors 6 and 7).
    twin(blue_forces=[{"last_contact_time": "2026-01-01T00:00:00Zx"}]),
    twin(blue_forces=[{"last_contact_time": "2026-01-01T00:00:00z"}]),
    twin(blue_forces=[{"point_location": {"location_time": "2026-01-01T00:00:00.500z"}}]),
    # JSON true for an int32 (mutation survivor 8; the codec round verifier's first gap). True is
    # 1 to Python, and `symbol_catalog: True` is refused anyway because 1 is a named number, so
    # only an int32 shows the bool guard.
    twin(blue_forces=[{"identity": {"int32_identity": True}}]),
    twin(blue_forces=[{"identity": {"int32_identity": False}}]),
    # A value name of another enum (mutation survivor 9).
    twin(blue_forces=[{"symbol": {"symbol_catalog": "MEASUREMENT_CODE_GPS"}}]),
    twin(blue_forces=[{"point_location": {"geo_point": {
        "measurement_code": "SYMBOL_CATALOG_APP6_D"}}}]),
    # @type that is not text: it raised AttributeError where the check was missing (survivor 10).
    {"@type": 5},
    {"@type": [GET_URL_TEXT]},
    # A malformed @unknown entry below the top level (mutation survivor 5): every earlier case
    # was at the top level.
    twin(blue_forces=[{"identity": {"@unknown": [{"number": 15, "wire_type": 0}]}}]),
    twin(blue_forces=[{"point_location": {"geo_point": {
        "@unknown": [{"number": 15, "wire_type": 0, "hex": "0A"}]}}}]),
    twin(blue_forces=[{"point_location": {"geo_point": {
        "@unknown": [{"number": 1, "wire_type": 1, "hex": "00" * 8}]}}}]),   # 1 is the latitude
    twin(header={"@unknown": {"number": 15}}),
])
def test_invalid_twin_value_left_open_by_the_build(document):
    refused("invalid-twin-value", codec.validate_twin, document)


@pytest.mark.parametrize("document", [
    twin(**{"@unknown": None}),                                       # the second gap
    twin(blue_forces=[{"identity": {"@unknown": None}}]),
    twin(blue_forces=[{"identity": {"@unknown": [None]}}]),
])
def test_an_unknown_list_or_entry_given_as_null_is_null_in_twin(document):
    """The codec round verifier's second gap: `@unknown: null` is refused for the null, before
    its type is looked at."""
    refused("null-in-twin", codec.validate_twin, document)


def test_a_surrogate_in_a_key_inside_an_unknown_keys_value_is_refused():
    """Mutation survivor 11: the existing case had the surrogate in the unknown key itself."""
    refused("invalid-utf8", codec.validate_twin, twin(futureField={"a\ud800": 1}))
    refused("invalid-utf8", codec.validate_twin, twin(futureField=[{"b": {"\udfff": 1}}]))


def test_an_unknown_keys_value_is_copied_not_returned_by_reference():
    """Mutation survivor 12: the twin is the caller's to keep and the adapter's to carry; neither
    may reach into the other's containers."""
    value = {"a": [1, {"b": []}]}
    normalised = codec.validate_twin(twin(futureField=value))
    assert normalised["futureField"] == value
    assert normalised["futureField"] is not value
    assert normalised["futureField"]["a"] is not value["a"]
    assert normalised["futureField"]["a"][1] is not value["a"][1]
    normalised["futureField"]["a"][1]["b"].append(2)
    assert value == {"a": [1, {"b": []}]}


@pytest.mark.parametrize("field,value", [
    ("latitude_coordinate", 2 ** 53 + 1),
    ("longitude_coordinate", -(2 ** 53 + 1)),
    ("latitude_coordinate", 10 ** 300 + 1),
    ("vertical_distance", 2 ** 60 + 1),          # a DoubleValue wrapper, read the same way
])
def test_an_integer_a_double_cannot_hold_exactly_is_refused_not_rounded(field, value):
    """The record §2.2: float(2**53 + 1) is 2**53, another value; converting it would round it
    without a word, which is a repair."""
    error = refused("invalid-twin-value", codec.validate_twin,
                    twin(blue_forces=[{"point_location": {"geo_point": {field: value}}}]))
    assert "cannot hold exactly" in str(error)


def test_an_integer_a_double_holds_exactly_still_becomes_a_float():
    normalised = codec.validate_twin(twin(blue_forces=[{"point_location": {
        "geo_point": {"latitude_coordinate": 2 ** 53, "longitude_coordinate": -7},
        "speed": 0}}]))
    point = normalised["blue_forces"][0]["point_location"]
    assert point == {"geo_point": {"latitude_coordinate": 9007199254740992.0,
                                   "longitude_coordinate": -7.0}, "speed": 0.0}
    assert [type(value) for value in (*point["geo_point"].values(), point["speed"])] == [float] * 3


class Number(enum.IntEnum):
    """An int subclass a caller holding decoded data might pass; JSON never produces one."""

    ZERO = 0
    NINE = 9
    SEVEN = 7
    FIFTEEN = 15


class Text(str):
    """A str subclass, likewise."""


class Real(float):
    """A float subclass, likewise."""


def _scalars_and_keys(node, found: list) -> list:
    """Every key and every scalar of a JSON-shaped value, depth first."""
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(key)
            _scalars_and_keys(value, found)
    elif isinstance(node, list):
        for value in node:
            _scalars_and_keys(value, found)
    else:
        found.append(node)
    return found


def test_accepted_values_come_back_as_plain_json_types():
    """The record §2.2: subclasses of int, str and float come back as the plain type (an IntEnum
    member as its number), and a bool stays a bool where it is accepted."""
    given = {
        "@type": Text(GET_URL_TEXT),
        "header": {"success": True, "error_message": Text("EXERCISE")},
        "blue_forces": [{
            "identity": {"int32_identity": Number.SEVEN},
            "callsign": Text("EXERCISE ALPHA"),
            "symbol": {"symbol_catalog": Number.NINE,
                       "numeric_identifier": {"first_ten_digits": Text("1003100000")}},
            "point_location": {
                "location_time": Text("2026-01-01T00:00:00.500Z"),
                "geo_point": {"latitude_coordinate": Real(52.5),
                              "longitude_coordinate": Number.SEVEN,
                              "measurement_code": Text("MEASUREMENT_CODE_GPS")},
                "speed": Real(1.5)},
            "futureField": [Number.SEVEN, Real(1.5), Text("EXERCISE"), True,
                            {Text("key"): Number.NINE}],
        }],
        "@unknown": [{"number": Number.FIFTEEN, "wire_type": Number.ZERO, "hex": Text("07")}],
    }
    normalised = codec.validate_twin(given)
    assert normalised == twin(
        header={"success": True, "error_message": "EXERCISE"},
        blue_forces=[{
            "identity": {"int32_identity": 7},
            "callsign": "EXERCISE ALPHA",
            "symbol": {"symbol_catalog": 9,
                       "numeric_identifier": {"first_ten_digits": "1003100000"}},
            "point_location": {
                "location_time": "2026-01-01T00:00:00.500Z",
                "geo_point": {"latitude_coordinate": 52.5, "longitude_coordinate": 7.0,
                              "measurement_code": "MEASUREMENT_CODE_GPS"},
                "speed": 1.5},
            "futureField": [7, 1.5, "EXERCISE", True, {"key": 9}],
        }],
        **{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07"}]})
    found = _scalars_and_keys(normalised, [])
    assert {type(item) for item in found} == {bool, int, float, str}
    assert [item for item in found if type(item) is bool] == [True, True]


@pytest.mark.parametrize("document", [
    twin(blue_forces=[{"identity": {"int32_identity": float("nan")}}]),
    twin(header={"success": float("nan")}),
    twin(blue_forces=[{"callsign": float("inf")}]),
    twin(blue_forces=[{"last_contact_time": float("nan")}]),
    twin(blue_forces=[{"symbol": {"symbol_catalog": float("nan")}}]),
    twin(blue_forces=[{"identity": {"int64_identity": float("-inf")}}]),
    twin(header=float("nan")),
    twin(**{"@unknown": [{"number": float("nan"), "wire_type": 0, "hex": "07"}]}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": float("inf")}]}),
])
def test_a_nan_outside_a_double_or_an_unknown_keys_value_is_invalid_twin_value(document):
    """The record §3.2's `non-finite-number` row as the code reads it: NaN or an infinity is
    that code only in a double and in the value of a key the contract does not name; given for
    any other field, or inside an `@unknown` entry, it is a value of the wrong JSON type."""
    refused("invalid-twin-value", codec.validate_twin, document)


# ======================================================== final verification: the refusal text


#: Every parametrized test of this file that refuses a dict-form input, with how one of its
#: parameters becomes that input. The refusal-text test below reads each test's own parametrize
#: mark, so a case added to one of these lists is checked there too.
DICT_FORM_TESTS = {
    test_null_in_twin: lambda document: document,
    test_not_an_any_envelope_dict_form: lambda document: document,
    test_invalid_utf8_dict_form: lambda document: document,
    test_non_finite_number_dict_form: lambda document: document,
    test_timestamp_out_of_range_dict_form:
        lambda text: twin(blue_forces=[{"last_contact_time": text}]),
    test_multiple_oneof_members_dict_form:
        lambda identity: twin(blue_forces=[{"identity": identity}]),
    test_value_out_of_range_dict_form: lambda document: document,
    test_invalid_twin_value: lambda document: document,
    test_an_unknown_entry_is_held_to_the_wire_rules: lambda case: twin(**{"@unknown": [case[0]]}),
    test_invalid_twin_value_left_open_by_the_build: lambda document: document,
    test_an_unknown_list_or_entry_given_as_null_is_null_in_twin: lambda document: document,
    test_an_integer_a_double_cannot_hold_exactly_is_refused_not_rounded:
        lambda case: twin(blue_forces=[{"point_location": {"geo_point": {case[0]: case[1]}}}]),
    test_a_nan_outside_a_double_or_an_unknown_keys_value_is_invalid_twin_value:
        lambda document: document,
}

#: The inputs the unparametrized dict-form tests of this file refuse inline.
DICT_FORM_INLINE = [
    [GET_URL_TEXT], {"@type": "GetBlueForcesResponse"},
    {"@type": "type.googleapis.com/rheinmetall.tactical_api.v0.Point"},
    twin(header=True), twin(blue_forces=[{"last_contact_time": {"seconds": "0", "nanos": 1}}]),
    twin(futureField={"a\ud800": 1}), twin(futureField=[{"b": {"\udfff": 1}}]),
    "0a45", ["@type"],
]


def _parameters(test) -> list:
    [mark] = [mark for mark in test.pytestmark if mark.name == "parametrize"]
    return list(mark.args[1])


DICT_FORM_REFUSALS = [to_document(value) for test, to_document in DICT_FORM_TESTS.items()
                      for value in _parameters(test)] + DICT_FORM_INLINE


def test_the_dict_form_refusals_are_all_collected():
    """Every parametrized `*_dict_form` test of this file is read, and each contributes all of
    its cases."""
    named = {function for name, function in globals().items()
             if name.startswith("test_") and name.endswith("_dict_form")
             and hasattr(function, "pytestmark")}
    assert named <= set(DICT_FORM_TESTS)
    assert len(DICT_FORM_REFUSALS) == sum(len(_parameters(test)) for test in DICT_FORM_TESTS) \
        + len(DICT_FORM_INLINE) > 100


@pytest.mark.parametrize("document", DICT_FORM_REFUSALS)
def test_every_dict_form_refusal_is_one_printable_line_of_utf8(document):
    with pytest.raises(TacticalapiRefused) as caught:
        codec.twin_of(document)
    text = str(caught.value)
    text.encode("utf-8")
    assert text.isprintable(), text
    assert len(text) <= 400, len(text)


#: A key holding a lone surrogate (which `json.loads` makes of a `\ud800` escape) and one holding
#: a line break that would otherwise forge a second refusal line.
AWKWARD_KEYS = ["x\ud800", "a\nnull-in-twin: forged"]

#: Every place a dict key enters a refusal text: a document with the key there, and the part of
#: the refusal that must name it, contract names bare and the key as its repr. The surrogate key
#: is refused `invalid-utf8` at some of these sites and the line-break key for the value beside
#: it; both are named at the same place in the text.
KEY_SITES = {
    "message level, null": (lambda key: twin(**{key: None}),
                            lambda key: f"null-in-twin: {key!r} is null"),
    "header, null": (lambda key: twin(header={"success": True, key: None}),
                     lambda key: f"null-in-twin: header.{key!r} is null"),
    "nested message, NaN": (
        lambda key: twin(blue_forces=[{"point_location": {key: float("nan")}}]),
        lambda key: f"blue_forces[0].point_location.{key!r}"),
    "unknown value, null inside": (lambda key: twin(futureField={key: None}),
                                   lambda key: f"'futureField'.{key!r}"),
    "unknown value, not JSON inside": (lambda key: twin(futureField={"a": {key: (1,)}}),
                                       lambda key: f"'futureField'.'a'.{key!r}"),
    "unknown key, a key not text inside": (lambda key: twin(**{key: {1: 2}}),
                                           lambda key: f"{key!r}"),
    "@unknown entry, null member": (
        lambda key: twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07", key: None}]}),
        lambda key: f"null-in-twin: @unknown[0].{key!r} is null"),
    "@unknown entry, extra key": (
        lambda key: twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07", key: 1}]}),
        lambda key: "invalid-twin-value: @unknown[0] has the keys ["),
    "nested @unknown entry, extra key": (
        lambda key: twin(blue_forces=[{"identity": {"@unknown": [{key: 1}]}}]),
        lambda key: f"invalid-twin-value: blue_forces[0].identity.@unknown[0] has the keys "
                    f"[{key!r}]"),
}


@pytest.mark.parametrize("key", AWKWARD_KEYS, ids=["surrogate", "newline"])
@pytest.mark.parametrize("site", sorted(KEY_SITES))
def test_a_key_enters_a_refusal_escaped_and_a_contract_name_as_itself(site, key):
    """The record §3.2: a dict key enters a refusal only through one helper. A key the contract
    does not name arrives as its repr, so the text encodes as UTF-8 and stays one line; a field
    name of the table, and `@unknown`, arrive as themselves."""
    document, named = KEY_SITES[site]
    with pytest.raises(TacticalapiRefused) as caught:
        codec.validate_twin(document(key))
    text = str(caught.value)
    text.encode("utf-8")
    assert text.isprintable(), text
    assert repr(key) in text and key not in text
    assert named(key) in text, text


def test_a_refusal_quotes_at_most_quote_limit_characters_and_counts_the_rest():
    assert codec.QUOTE_LIMIT == 120
    assert codec.quote("EXERCISE") == "'EXERCISE'"
    assert codec.quote(2 ** 31) == "2147483648"
    long = "x" * 2 ** 20
    assert codec.quote(long) == "'" + "x" * 119 + f"... ({2 ** 20 + 2 - 120} more characters)"
    # An integer Python will not write as text is described, not written (a plain ValueError
    # from repr would have escaped the refusal it was meant for).
    assert codec.quote(10 ** 5000) == "an integer of 16610 bits, too long to write as text"
    assert codec.quote([10 ** 5000]) == "a list holding an integer too long to write as text"

    class Odd:
        def __repr__(self) -> str:
            return "two\nlines"
    assert codec.quote(Odd()) == "two\\nlines"


def _type_url_filling(size: int, text: bytes) -> bytes:
    """An Any of exactly `size` octets holding only its type_url, `text` repeated to fill it:
    0x0a, a four-octet length, and the URL."""
    length = size - 5
    raw = b"\x0a" + pw.varint(length) + (text * length)[:length]
    assert len(raw) == size
    return raw


@pytest.mark.parametrize("call,raw,code", [
    # A type_url at the size bound, quoted once (it was quoted twice, URL and name, 8 MiB).
    (codec.decode, _type_url_filling(codec.MAX_INPUT_BYTES, b"a/" + b"b" * 64),
     "unsupported-message-type"),
    (codec.decode, _type_url_filling(codec.MAX_INPUT_BYTES, b"a"), "malformed-type-url"),
    (codec.validate_twin, {"@type": "a/" + "b" * codec.MAX_INPUT_BYTES},
     "unsupported-message-type"),
    # A mebibyte given as a value, in each place the dict form quotes one.
    (codec.validate_twin, twin(header={"success": "x" * 2 ** 20}), "invalid-twin-value"),
    (codec.validate_twin, twin(blue_forces=[{"last_contact_time": "x" * 2 ** 20}]),
     "invalid-twin-value"),
    (codec.validate_twin, twin(blue_forces=[{"identity": {"int64_identity": "1" * 2 ** 20}}]),
     "value-out-of-range"),
    (codec.validate_twin, twin(blue_forces=[{"symbol": {"symbol_catalog": "X" * 2 ** 20}}]),
     "invalid-twin-value"),
    (codec.validate_twin, twin(blue_forces=[{"callsign": "\ud800" * 2 ** 20}]), "invalid-utf8"),
    (codec.validate_twin, twin(**{"k" * 2 ** 20: None}), "null-in-twin"),
    (codec.validate_twin, twin(**{"@unknown": [{"number": 15, "wire_type": 2,
                                                "hex": "X" * 2 ** 20}]}), "invalid-twin-value"),
    (codec.validate_twin, twin(**{"@unknown": [{"number": 2 ** 2 ** 20, "wire_type": 2,
                                                "hex": ""}]}), "field-number-too-large"),
    (codec.validate_twin, twin(blue_forces=[{"identity": {"int32_identity": 10 ** 5000}}]),
     "value-out-of-range"),
], ids=["type_url at the bound", "type_url without a slash", "dict type_url", "bool", "timestamp",
        "int64", "enum", "surrogates", "key", "hex", "field number", "int32 past text"])
def test_a_refusal_for_a_huge_value_is_a_few_hundred_characters(call, raw, code):
    error = refused(code, call, raw)
    assert len(str(error)) <= 400, len(str(error))
    assert str(error).isprintable()


# ================================ final verification, 2026-10-04: the second review's findings


class Mute:
    """An in-process value whose repr raises something other than ValueError."""

    def __repr__(self) -> str:
        raise RuntimeError("EXERCISE no repr")


class Garbled:
    """One whose repr raises a ValueError of its own, which is not the digit limit."""

    def __repr__(self) -> str:
        raise ValueError("EXERCISE garbled")


def test_quote_describes_any_value_whose_repr_raises():
    """robustness-9 (the record "Changes", final verification, item 20): only ValueError was
    caught, so a RuntimeError from a caller's `__repr__` escaped the refusal it was quoted for,
    and any other ValueError was described as an over-long integer."""
    assert codec.quote(Mute()) == "a Mute whose repr raised RuntimeError"
    assert codec.quote([Mute()]) == "a list whose repr raised RuntimeError"
    assert codec.quote(Garbled()) == "a Garbled whose repr raised ValueError"
    # The digit limit keeps its own descriptions.
    assert codec.quote(10 ** 5000) == "an integer of 16610 bits, too long to write as text"
    assert codec.quote({"k": 10 ** 5000}) == "a dict holding an integer too long to write as text"
    odd = type("two\nlines", (), {"__repr__": lambda self: 1 / 0})
    assert codec.quote(odd()) == "a two\\nlines whose repr raised ZeroDivisionError"
    error = refused("invalid-twin-value", codec.validate_twin, twin(header={"success": Mute()}))
    assert "a Mute whose repr raised RuntimeError" in str(error)


class Formatted(str):
    """A str subclass that writes itself as two long lines wherever it is formatted."""

    def __str__(self) -> str:
        return "line one\nline two " + "z" * 5000


class ReprFormatted:
    """An in-process value whose `__repr__` returns such a subclass, which `repr` accepts."""

    def __repr__(self) -> str:
        return Formatted("short")


class Nameless(type):
    """A metaclass whose own `__name__` raises, so `type(value).__name__` would."""

    @property
    def __name__(cls) -> str:
        raise RuntimeError("EXERCISE no name")


def test_quote_takes_a_repr_as_plain_text_and_quote_type_bounds_a_type_name():
    """N3 (the record "Changes", final verification, item 34): `quote` returned the repr as
    `repr` gave it, so a subclass formatted itself into the refusal as two long lines, and the
    type names the refusals wrote were raw. Both are plain text now, escaped and cut."""
    quoted = codec.quote(ReprFormatted())
    assert type(quoted) is str and f"{quoted}" == "short"
    long_name = type("N" * 100_000, (), {})
    assert codec.quote_type(long_name()) == "N" * 120 + f"... ({100_000 - 120} more characters)"
    assert codec.quote_type(type("a\nb", (), {})()) == "a\\nb"
    plain = codec.quote_type(type(Formatted("Plain"), (), {})())
    assert type(plain) is str and f"{plain}" == "Plain"
    assert codec.quote_type(Nameless("Named", (), {})()) == "Named"
    assert (codec.quote_type(7), codec.quote_type(None), codec.quote_type(b"")) == (
        "int", "NoneType", "bytes")
    # A value whose repr raises is described with its type name cut (to 145 characters), and
    # the description, 183 characters, cut in turn.
    odd = type("x" * 500, (), {"__repr__": lambda self: 1 / 0})
    assert codec.quote(odd()) == "a " + "x" * 118 + "... (63 more characters)"
    # Through a refusal: one printable line of bounded length.
    for document, code in ((twin(header={"success": ReprFormatted()}), "invalid-twin-value"),
                           (twin(blue_forces=[{"callsign": long_name()}]), "invalid-twin-value"),
                           (long_name(), "not-an-any-envelope")):
        error = refused(code, codec.twin_of, document)
        assert str(error).isprintable() and len(str(error)) <= 400, str(error)[:200]


class _Alarm(Exception):
    pass


def _within(seconds: int, call, *args):
    """`call(*args)` under an alarm, so a walk that never ends fails the test rather than
    hanging it."""
    def ring(signum, frame):
        raise _Alarm(f"still running after {seconds} s")
    previous = signal.signal(signal.SIGALRM, ring)
    signal.alarm(seconds)
    try:
        return call(*args)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def test_a_dict_that_contains_itself_is_refused_as_too_deep_by_the_codec():
    """robustness-10 (item 21): the codec's own depth walk had no early exit, so a dict holding
    itself never returned from `validate_twin`. The walk stops past the bound; the host's walk
    on the `to_cdm` path is the host's (the record, opening paragraph)."""
    cyclic = twin(header={"success": True})
    cyclic["future"] = cyclic
    cyclic["header"]["back"] = cyclic
    for call in (codec.validate_twin, codec.twin_of):
        with pytest.raises(TacticalapiRefused) as caught:
            _within(5, call, cyclic)
        assert caught.value.code == "nesting-too-deep"
        assert f"{codec.MAX_DEPTH + 1} or more containers deep" in str(caught.value)
    assert _within(5, codec.twin_depth, cyclic, 64) == 65
    assert _within(5, codec.twin_depth, cyclic, 3) == 4
    # Without a limit the full depth is still counted, as `container_depth` counts it.
    deep = _twin_of_depth(20)
    assert codec.twin_depth(deep) == codec.twin_depth(deep, 64) == container_depth(deep) == 20
    assert codec.twin_depth(deep, 10) == 11


@pytest.mark.parametrize("value,accepted", [
    (2 ** 64 - 1, True), (2 ** 64, False), (-(2 ** 63), True), (-(2 ** 63) - 1, False),
    (10 ** 5000, False), ([0, {"deep": [2 ** 64]}], False), ({"a": [-(2 ** 63) - 1]}, False),
    ([2 ** 63, -(2 ** 62)], True),
], ids=["2^64-1", "2^64", "-2^63", "-2^63-1", "5001 digits", "nested 2^64", "nested -2^63-1",
        "nested within"])
def test_an_unknown_keys_integer_is_held_to_the_64_bit_range(value, accepted):
    """robustness-4 (a) / robustness-11 (item 14): ProtoJSON writes no wider integer, and past
    some 4 300 digits Python can neither write the number as JSON nor read it back."""
    document = twin(header={"success": True}, futureKey=value)
    if accepted:
        normalised = codec.validate_twin(document)
        assert normalised["futureKey"] == value
        assert json.loads(json.dumps(normalised)) == normalised
    else:
        error = refused("invalid-twin-value", codec.validate_twin, document)
        assert "outside -2^63 … 2^64 - 1" in str(error)
        assert len(str(error)) <= 400 and str(error).isprintable()


def test_carried_size_is_the_compact_json_text_with_ascii_escaping():
    """Item 14: the measure is what `json.dumps(value, separators=(",", ":"))` writes."""
    for value in ({"a": [1, 2.5, True, "xyz", {}]}, [], "", 0, -(2 ** 63), 2 ** 64 - 1, 1e-300,
                  "\x00\x1f\x7f\"\\/", "é\U0001f600", {"k\n퟿": [None or 0, False]}):
        assert codec.carried_size(value) == len(json.dumps(value, separators=(",", ":")))
    assert codec.carried_size({"a": "\x01"}) == len('{"a":"\\u0001"}') == 14


def test_unknown_only_keeps_a_nested_type_key_at_its_path():
    """robustness-2 / mapping-4 (item 12): `@type` is left out on the response alone."""
    document = codec.validate_twin(twin(
        header={"success": True, "@type": "EXERCISE header"},
        blue_forces=[{"@type": "EXERCISE element", "point_location": {
            "geo_point": {"@type": "EXERCISE geo"}}}]))
    assert codec.unknown_only(document, codec.GET_BLUE_FORCES_RESPONSE) == {
        "header": {"@type": "EXERCISE header"}}
    assert codec.unknown_only(document["blue_forces"][0], f"{codec.PACKAGE}.BlueForce") == {
        "point_location": {"geo_point": {"@type": "EXERCISE geo"}}, "@type": "EXERCISE element"}
    assert [(entry["path"], entry["key"]) for entry in codec.unknown_fields(document)] == [
        ("header", "@type"), ("blue_forces[0].point_location.geo_point", "@type"),
        ("blue_forces[0]", "@type")]


class Member(str, enum.Enum):
    URL = GET_URL_TEXT
    NAME = "MEASUREMENT_CODE_GPS"
    STAMP = "2026-01-01T00:00:00.500000Z"
    TEXT = "EXERCISE"
    HEX = "07"
    KEY = "note"
    NUMBER = "number"


def test_str_enum_members_are_read_as_the_text_they_hold():
    """robustness-3 (item 13): `str()` of a `(str, Enum)` member is `Member.NAME`; the base
    type's own conversion is the member's text, wherever the dict form reads text."""
    given = {"@type": Member.URL, "header": {"success": True, "error_message": Member.TEXT},
             "blue_forces": [{"callsign": Member.TEXT, "point_location": {
                 "location_time": Member.STAMP,
                 "geo_point": {"measurement_code": Member.NAME}}, Member.KEY: [Member.TEXT]}],
             "@unknown": [{Member.NUMBER: 15, "wire_type": 0, "hex": Member.HEX}]}
    expected = {"@type": GET_URL_TEXT, "header": {"success": True, "error_message": "EXERCISE"},
                "blue_forces": [{"callsign": "EXERCISE", "point_location": {
                    "location_time": "2026-01-01T00:00:00.500Z",
                    "geo_point": {"measurement_code": "MEASUREMENT_CODE_GPS"}},
                    "note": ["EXERCISE"]}],
                "@unknown": [{"number": 15, "wire_type": 0, "hex": "07"}]}
    normalised = codec.validate_twin(given)
    assert normalised == expected
    assert json.dumps(normalised) == json.dumps(expected)
    assert {type(item) for item in _scalars_and_keys(normalised, [])} == {bool, int, str}


class Hashed(str):
    def __hash__(self) -> int:
        return 7

    def __eq__(self, other) -> bool:
        return self is other


@pytest.mark.parametrize("document", [
    twin(header={"success": True, Hashed("success"): False}),
    twin(futureKey=1, **{}) | {Hashed("futureKey"): 2},
    twin(futureKey={"a": 1, Hashed("a"): 2}),
    twin(**{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07", Hashed("hex"): "07"}]}),
    twin() | {Hashed("@type"): GET_URL_TEXT},
])
def test_two_keys_that_hold_one_text_are_refused(document):
    """Item 13: made plain, they would be one key; neither is dropped for the other."""
    error = refused("invalid-twin-value", codec.validate_twin, document)
    assert str(error).isprintable() and len(str(error)) <= 400


# ================================= final verification, 2026-10-04: the fourth review (item 37)


#: The two class names every type-name site is tested with, each beside the text `quote_type`
#: must write for it, spelled out here rather than taken from the helper under test: one holding
#: a line break, which written raw forges a second line, and one of 100 000 characters.
ODD_NAMES = {
    "line break": ("EXERCISE\nclass", "EXERCISE\\nclass"),
    "long": ("N" * 100_000, "N" * 120 + f"... ({100_000 - 120} more characters)"),
}


def claiming(name: str, claimed: type) -> object:
    """An object of a class called `name` whose `__class__` names `claimed`, which it is not:
    `isinstance(obj, claimed)` is true and `type(obj)` is the class itself."""
    return type(name, (), {"__class__": property(lambda self: claimed)})()


#: Every place the codec writes a type name, with an input that puts the object there and the
#: text around the name. Each object also claims the type its site tests for (R1-1), so a site
#: that went back to `isinstance` lets it through to a conversion or a container method that
#: raises something other than a refusal, and a site that writes `type(x).__name__` raw (R1-2)
#: writes a line break or 100 000 characters.
TYPE_NAME_SITES = {
    "decode, the input": (bytes, codec.decode, lambda obj: (obj,), "not-an-any-envelope",
                          "the input is a ", "; decode reads octets"),
    "envelope_type_url, the input": (memoryview, codec.envelope_type_url, lambda obj: (obj,),
                                     "not-an-any-envelope", "the input is a ",
                                     "; envelope_type_url reads octets"),
    "decode_message, the input": (bytearray, codec.decode_message,
                                  lambda obj: (obj, codec.TIMESTAMP), "not-an-any-envelope",
                                  "the input is a ", "; decode_message reads octets"),
    "validate_twin, the input": (dict, codec.validate_twin, lambda obj: (obj,),
                                 "not-an-any-envelope", "the input is a ",
                                 "; the dict form is an object holding @type"),
    "twin_of, the input claiming octets": (bytes, codec.twin_of, lambda obj: (obj,),
                                           "not-an-any-envelope", "the input is a ",
                                           "; the adapter reads the serialized Any"),
    "twin_of, the input claiming a dict": (dict, codec.twin_of, lambda obj: (obj,),
                                           "not-an-any-envelope", "the input is a ",
                                           "; the adapter reads the serialized Any"),
    "@type": (str, codec.validate_twin, lambda obj: ({"@type": obj},), "invalid-twin-value",
              "@type is a ", ", not text"),
    "a message": (dict, codec.validate_twin, lambda obj: (twin(header=obj),),
                  "invalid-twin-value", "header is a ",
                  "; a rheinmetall.tactical_api.v0.ResponseHeader is an object"),
    "a repeated field": (list, codec.validate_twin, lambda obj: (twin(blue_forces=obj),),
                         "invalid-twin-value", "blue_forces is a ", "; a repeated field is a list"),
    "a Timestamp": (str, codec.validate_twin,
                    lambda obj: (twin(blue_forces=[{"last_contact_time": obj}]),),
                    "invalid-twin-value", "blue_forces[0].last_contact_time is a ",
                    "; a twin Timestamp is RFC 3339 text"),
    "a string": (str, codec.validate_twin, lambda obj: (twin(blue_forces=[{"callsign": obj}]),),
                 "invalid-twin-value", "blue_forces[0].callsign is a ", "; a string is text"),
    "@unknown": (list, codec.validate_twin, lambda obj: (twin(**{"@unknown": obj}),),
                 "invalid-twin-value", "@unknown is a ", "; @unknown is a list"),
    "an @unknown entry": (dict, codec.validate_twin, lambda obj: (twin(**{"@unknown": [obj]}),),
                          "invalid-twin-value", "@unknown[0] is a ",
                          "; an @unknown entry is an object"),
    **{f"an unknown key's value claiming {claimed.__name__}": (
        claimed, codec.validate_twin, lambda obj: (twin(futureKey=obj),), "invalid-twin-value",
        "'futureKey' is a ", ", which is not a JSON value")
       for claimed in (bool, int, float, str, list, dict)},
}


@pytest.mark.parametrize("name,written", list(ODD_NAMES.values()), ids=list(ODD_NAMES))
@pytest.mark.parametrize("site", sorted(TYPE_NAME_SITES))
def test_every_site_that_writes_a_type_name_reads_the_own_type_and_bounds_its_name(
        site, name, written):
    """R1-1 and R1-2 (the record "Changes", final verification, items 34 and 37): at every place
    a refusal names a type, an object whose `__class__` claims the type the site wants is refused
    by its own type's name, escaped and cut, in one printable line. Seven of these sites, and
    the type test at each, were held by no test."""
    claimed, call, arguments, code, before, after = TYPE_NAME_SITES[site]
    obj = claiming(name, claimed)
    assert isinstance(obj, claimed) and not issubclass(type(obj), claimed)
    text = str(refused(code, call, *arguments(obj)))
    assert f"{before}{written}{after}" in text, text[:300]
    assert text.isprintable() and len(text) <= 400, text[:300]


#: Every other type test the dict form applies, each with an object claiming the type it tests
#: for and the text around the object's quoted repr in the refusal.
CLAIMED_VALUE_SITES = {
    "int32": (int, lambda obj: twin(blue_forces=[{"identity": {"int32_identity": obj}}]),
              "blue_forces[0].identity.int32_identity is <", "; a twin int32 is a JSON integer"),
    "int64": (str, lambda obj: twin(blue_forces=[{"identity": {"int64_identity": obj}}]),
              "blue_forces[0].identity.int64_identity is <", "; a twin int64 is decimal text"),
    "enum claiming a name": (
        str, lambda obj: twin(blue_forces=[{"symbol": {"symbol_catalog": obj}}]),
        "blue_forces[0].symbol.symbol_catalog is <", "; a twin enum is a value name or a number"),
    "enum claiming a number": (
        int, lambda obj: twin(blue_forces=[{"symbol": {"symbol_catalog": obj}}]),
        "blue_forces[0].symbol.symbol_catalog is <", "; a twin enum is a value name or a number"),
    "bool": (bool, lambda obj: twin(header={"success": obj}), "header.success is <",
             "; a bool is true or false"),
    "double claiming a float": (
        float, lambda obj: twin(blue_forces=[{"point_location": {"speed": obj}}]),
        "blue_forces[0].point_location.speed is <", "; a double is a JSON number"),
    "double claiming an integer": (
        int, lambda obj: twin(blue_forces=[{"point_location": {"speed": obj}}]),
        "blue_forces[0].point_location.speed is <", "; a double is a JSON number"),
    "@unknown number": (int, lambda obj: twin(**{"@unknown": [
        {"number": obj, "wire_type": 0, "hex": "07"}]}), "@unknown[0].number is <",
        ", not an integer"),
    "@unknown hex": (str, lambda obj: twin(**{"@unknown": [
        {"number": 15, "wire_type": 0, "hex": obj}]}), "@unknown[0].hex is <",
        "; it is lowercase hexadecimal"),
    "a key of the response": (str, lambda obj: twin() | {obj: 1}, "the response has the key <",
                              "; twin keys are text"),
    "a key of a message": (str, lambda obj: twin(header={"success": True, obj: 1}),
                           "header has the key <", "; twin keys are text"),
    "a key of an @unknown entry": (str, lambda obj: twin(**{"@unknown": [
        {"number": 15, "wire_type": 0, "hex": "07", obj: 1}]}), "@unknown[0] has the keys [",
        "; an @unknown entry has exactly number, wire_type and hex"),
    "a key inside an unknown key's value": (str, lambda obj: twin(futureKey={obj: 1}),
                                            "'futureKey' has the key <", "; JSON keys are text"),
}


@pytest.mark.parametrize("site", sorted(CLAIMED_VALUE_SITES))
def test_a_value_or_key_whose_class_claims_the_type_due_is_refused_by_name(site):
    """R1-1 (item 37): `isinstance` asks `__class__`, so each of these passed the type test and
    left `validate_twin` as a TypeError or an AttributeError, or, claiming a bool, was returned
    as given. The codec reads `type(value)` now: the object is refused `invalid-twin-value`, its
    repr quoted, in one printable line."""
    claimed, build, before, after = CLAIMED_VALUE_SITES[site]
    for name, written in ODD_NAMES.values():
        text = str(refused("invalid-twin-value", codec.validate_twin,
                           build(claiming(name, claimed))))
        assert before in text and after in text, text[:300]
        assert text.isprintable() and len(text) <= 400, text[:300]
        assert ("EXERCISE" if "\n" in name else "N" * 60) in text, text[:300]


class ClassRaises:
    """An in-process object whose `__class__` raises, which `isinstance` asks for."""

    @property
    def __class__(self):
        raise RuntimeError("EXERCISE class raised")


def test_an_object_whose_class_raises_is_refused_and_octets_claiming_a_view_are_read():
    """R1-1 (item 37): a `__class__` that raises made `isinstance` raise it; the codec never asks
    for it. And octets are measured by their own type: a `bytes` subclass whose `__class__`
    names `memoryview` is read as the bytes it is."""
    for document in (twin(blue_forces=[{"callsign": ClassRaises()}]), twin() | {ClassRaises(): 1},
                     twin(futureKey=ClassRaises()), twin(header=ClassRaises())):
        error = refused("invalid-twin-value", codec.validate_twin, document)
        assert "ClassRaises" in str(error), str(error)
    octets = type("EXERCISE", (bytes,), {"__class__": property(lambda self: memoryview)})(
        envelope(pw.field_len(1, pw.field_varint(1, 1))))
    assert codec.decode(octets) == {"@type": GET_URL_TEXT, "header": {"success": True}}
    assert codec.envelope_type_url(octets) == GET_URL_TEXT


@pytest.mark.parametrize("name,written", list(ODD_NAMES.values()), ids=list(ODD_NAMES))
def test_quotes_own_descriptions_bound_every_type_name_they_write(name, written):
    """R1-2 (item 34): the two type names `quote` writes besides the value's own, the class of
    what a repr raised and the class of a container holding an integer too long to write, are
    bounded like the value's; and the digit-limit description reads the value's own type, so an
    object that claims to be an integer is described as what it is (item 37)."""
    raised = type(name, (RuntimeError,), {})

    class Rep:
        def __repr__(self) -> str:
            raise raised("EXERCISE")
    expected = f"a Rep whose repr raised {written}"
    if len(expected) > codec.QUOTE_LIMIT:
        expected = expected[:120] + f"... ({len(expected) - 120} more characters)"
    assert codec.quote(Rep()) == expected

    holder = type(name, (list,), {})
    expected = f"a {written} holding an integer too long to write as text"
    if len(expected) > codec.QUOTE_LIMIT:
        expected = expected[:120] + f"... ({len(expected) - 120} more characters)"
    assert codec.quote(holder([10 ** 5000])) == expected

    def digits(self):
        raise ValueError("Exceeds the limit (4300 digits) for integer string conversion")
    claims_int = type(name, (), {"__class__": property(lambda self: int), "__repr__": digits})()
    expected = f"a {written} holding an integer too long to write as text"
    if len(expected) > codec.QUOTE_LIMIT:
        expected = expected[:120] + f"... ({len(expected) - 120} more characters)"
    assert codec.quote(claims_int) == expected


def test_quote_error_takes_an_exceptions_text_as_bounded_plain_text():
    """R1-1 (item 37): the text of an exception that is not a refusal, as `validate_source`
    writes it: escaped, cut, taken as plain text, and described when the text itself raises."""
    assert codec.quote_error(RuntimeError("EXERCISE")) == "EXERCISE"
    assert codec.quote_error(RuntimeError("line one\nline two")) == "line one\\nline two"
    assert codec.quote_error(RuntimeError("x" * 500)) == "x" * 120 + "... (380 more characters)"

    class Loud(Exception):
        def __str__(self) -> str:
            return Formatted("short")
    quoted = codec.quote_error(Loud())
    assert type(quoted) is str and f"{quoted}" == "short"

    class Mum(Exception):
        def __str__(self) -> str:
            raise KeyError("EXERCISE")
    assert codec.quote_error(Mum()) == "a Mum whose text raised KeyError"
    odd = type("Odd\nerror", (Exception,), {"__str__": lambda self: 1 / 0})
    assert codec.quote_error(odd()) == "a Odd\\nerror whose text raised ZeroDivisionError"
    # Both type names of the description are cut before the description is: a name of 100 000
    # characters is written as `quote_type` writes it (147 characters), then the whole is cut.
    named = "N" * 100_000
    written = "N" * 120 + f"... ({100_000 - 120} more characters)"
    long_error = type(named, (Exception,), {"__str__": lambda self: 1 / 0})
    expected = f"a {written} whose text raised ZeroDivisionError"
    assert codec.quote_error(long_error()) == (
        expected[:120] + f"... ({len(expected) - 120} more characters)")
    long_failure = type(named, (RuntimeError,), {})

    class Quiet(Exception):
        def __str__(self) -> str:
            raise long_failure("EXERCISE")
    expected = f"a Quiet whose text raised {written}"
    assert codec.quote_error(Quiet()) == (
        expected[:120] + f"... ({len(expected) - 120} more characters)")


def own(base: type, claimed: type) -> type:
    """A subclass of `base` whose instances' `__class__` names `claimed`, a type they are not."""
    return type(f"EXERCISE{base.__name__.title()}", (base,),
                {"__class__": property(lambda self: claimed)})


def test_a_value_is_read_as_its_own_type_when_its_class_claims_one_the_codec_refuses():
    """R1-1 (item 37), the other direction: the value's own type decides, so an integer whose
    `__class__` says `bool` is still an integer where one is due, a float that says `int` is a
    double, and a list that says `dict` is walked and copied as a list. Each comes back plain.
    Read through `isinstance`, the first was refused as a bool, the second raised a TypeError
    from `int.__int__`, and the third an AttributeError from the depth walk."""
    claims_bool, claims_int, claims_dict = own(int, bool), own(float, int), own(list, dict)
    given = twin(blue_forces=[{"identity": {"int32_identity": claims_bool(7)},
                               "point_location": {"speed": claims_bool(3)}},
                              {"identity": {"int32_identity": 8},
                               "point_location": {"speed": claims_int(2.5)}}],
                 futureKey=claims_dict([1, 2]),
                 **{"@unknown": [{"number": claims_bool(15), "wire_type": 0, "hex": "07"}]})
    normalised = codec.validate_twin(given)
    assert normalised == twin(blue_forces=[{"identity": {"int32_identity": 7},
                                            "point_location": {"speed": 3.0}},
                                           {"identity": {"int32_identity": 8},
                                            "point_location": {"speed": 2.5}}],
                              futureKey=[1, 2],
                              **{"@unknown": [{"number": 15, "wire_type": 0, "hex": "07"}]})
    assert {type(item) for item in _scalars_and_keys(normalised, [])} == {int, float, str}
    assert type(normalised["futureKey"]) is list
