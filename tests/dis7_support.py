"""Shared fixture-path and byte helpers for the DIS 7 test modules.

Not a test module: no `test_` function lives here. Paths are resolved from
`synapse_cdm.__file__` rather than from this module's own `__file__`, so they hold the same way
against an installed wheel and against a scratch copy of the package.
"""
from __future__ import annotations

import json
import pathlib

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
