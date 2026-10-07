"""A protobuf wire WRITER for tests that need inputs too large or too many to write by hand: the
limit tests (ten thousand elements, sixty-five thousand unknown fields, four mebibytes) and the
unknown-field matrix. Test-only; the adapter has no encoder and imports nothing from here.

It is not trusted on its word: `test_the_test_writer_reproduces_protoc_bytes` holds its output to
bytes protoc wrote, and every vector a refusal or a value test depends on is a hand-written
literal, not this module's output.
"""
from __future__ import annotations

import struct

GET_URL = b"type.googleapis.com/rheinmetall.tactical_api.v0.GetBlueForcesResponse"
SUBSCRIBE_URL = b"type.googleapis.com/rheinmetall.tactical_api.v0.SubscribeBlueForceEventsResponse"


def varint(value: int) -> bytes:
    """Base-128, least significant group first; a negative value as its 64-bit two's complement
    (ten octets), which is how protobuf writes a negative int32 or int64."""
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        group = value & 0x7F
        value >>= 7
        if value:
            out.append(group | 0x80)
        else:
            out.append(group)
            return bytes(out)


def tag(number: int, wire_type: int) -> bytes:
    return varint(number << 3 | wire_type)


def field_varint(number: int, value: int) -> bytes:
    return tag(number, 0) + varint(value)


def field_len(number: int, payload: bytes) -> bytes:
    return tag(number, 2) + varint(len(payload)) + payload


def field_double(number: int, value: float) -> bytes:
    return tag(number, 1) + struct.pack("<d", value)


def field_fixed32(number: int, payload: bytes) -> bytes:
    assert len(payload) == 4
    return tag(number, 5) + payload


def field_fixed64(number: int, payload: bytes) -> bytes:
    assert len(payload) == 8
    return tag(number, 1) + payload


def any_of(value: bytes, url: bytes = GET_URL) -> bytes:
    """`google.protobuf.Any`: field 1 `type_url`, field 2 `value`."""
    return field_len(1, url) + field_len(2, value)
