"""Shared fixture-path and byte helpers for the DIS 7 test modules.

Not a test module: no `test_` function lives here. Paths are resolved from
`synapse_cdm.__file__` rather than from this module's own `__file__`, so they hold the same way
against an installed wheel and against a scratch copy of the package.
"""
from __future__ import annotations

import json
import pathlib
import struct

import synapse_cdm

FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "dis7"
VECTORS = FIXTURES / "vectors"
CONTRACT = FIXTURES / "contract"

STEMS = ("equator_eastbound", "north_pole_stationary", "unprojectable_with_extensions")

_KINDS = ("envelope", "context", "expected")


def vector_bytes(stem: str) -> bytes:
    """The raw PDU bytes of `vectors/<stem>.dis`."""
    if stem not in STEMS:
        raise ValueError(f"{stem!r} is not a vector stem; expected one of {STEMS}")
    return (VECTORS / f"{stem}.dis").read_bytes()


def vector_json(stem: str, kind: str):
    """The parsed `vectors/<stem>.<kind>.json`, `kind` one of 'envelope', 'context', 'expected'."""
    if stem not in STEMS:
        raise ValueError(f"{stem!r} is not a vector stem; expected one of {STEMS}")
    if kind not in _KINDS:
        raise ValueError(f"{kind!r} is not a vector kind; expected one of {_KINDS}")
    return json.loads((VECTORS / f"{stem}.{kind}.json").read_text())


def seed() -> bytes:
    """The equator vector's raw bytes, used wherever a test needs one representative PDU."""
    return vector_bytes("equator_eastbound")


def patch(raw: bytes, offset: int, data: bytes) -> bytes:
    """`raw` with `data` written over the octets starting at `offset`. Length never changes."""
    if offset < 0 or offset + len(data) > len(raw):
        raise ValueError(f"offset {offset} and {len(data)} byte(s) do not fit inside "
                          f"{len(raw)} byte(s)")
    return raw[:offset] + data + raw[offset + len(data):]


def walking_pdu() -> bytes:
    """A 176-octet PDU with two records where octet i is 0x10 + i for i < 144 and the records are
    0xC0 to 0xDF, except the forced octets 0, 2, 3 (7, 1, 1), 8-9 (00 b0) and 19 (2).

    Built from `struct` and literals only, so a field read at a wrong offset, width or byte
    order yields a different value.
    """
    raw = b"".join((
        struct.pack(">BBBBIHBB", 7, 0x11, 1, 1, 0x14151617, 176, 0x1A, 0x1B),
        struct.pack(">HHHBB", 0x1C1D, 0x1E1F, 0x2021, 0x22, 2),
        struct.pack(">BBHBBBB", 0x24, 0x25, 0x2627, 0x28, 0x29, 0x2A, 0x2B),
        struct.pack(">BBHBBBB", 0x2C, 0x2D, 0x2E2F, 0x30, 0x31, 0x32, 0x33),
        bytes(range(0x34, 0x40)),   # velocity: three binary32
        bytes(range(0x40, 0x58)),   # position: three binary64
        bytes(range(0x58, 0x64)),   # orientation: three binary32
        struct.pack(">I", 0x64656667),
        bytes(range(0x68, 0x90)),   # dead reckoning, 40 octets
        bytes(range(0x90, 0x9C)),   # marking, 12 octets
        struct.pack(">I", 0x9C9D9E9F),
        bytes(range(0xC0, 0xE0)),   # two records
    ))
    assert len(raw) == 176
    return raw
