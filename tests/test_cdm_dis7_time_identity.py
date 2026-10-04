"""The `dis7` adapter's time context, session rule and identity derivation, at helper level.

Groups T08 (case A06) and T09 (cases N13 and A07). Every expected value is a literal typed here:
the UUIDs, the normalised instants and the whitespace code points were recomputed outside this
package, and none is taken from a function of `dis7`. The adapter-level halves of these cases
(through the constructor, the envelope and the dumped Entity) are tested elsewhere.
"""
from __future__ import annotations

import dataclasses
import datetime
import inspect
import struct
import uuid

import pydantic
import pytest

from synapse_cdm import models, times
from synapse_cdm.adapters import dis7
from synapse_cdm.adapters.dis7 import (
    TimeContext,
    entity_uuid,
    external_id,
    identity_system,
    validate_session,
)
from synapse_cdm.adapters.dis7_codec import Dis7Error
from tests import dis7_support

INSTANT = "2026-04-29T06:15:00.000Z"
BASIS = "Synthetic fixture scenario instant; not capture time"
NAMESPACE_LITERAL = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"
BASE_UUID = "d55bb6da-5e94-5583-a12b-249da222ab37"

MUTATIONS = [
    ("session", ("another-run", 42, [7, 11, 1]), "entity|DIS7:another-run:42|7:11:1", "d902dde1-c845-5e32-b9ab-2f63c45ac1a8"),
    ("exercise", ("unnamed", 43, [7, 11, 1]), "entity|DIS7:unnamed:43|7:11:1", "045ab575-d3cc-5ba3-a2ea-0d713e5b97d5"),
    ("site", ("unnamed", 42, [8, 11, 1]), "entity|DIS7:unnamed:42|8:11:1", "7f6c8662-dc0a-5482-a3eb-218e95961722"),
    ("application", ("unnamed", 42, [7, 12, 1]), "entity|DIS7:unnamed:42|7:12:1", "32b3e72c-35a3-5dd8-b0f8-cc36964c5f86"),
    ("entity", ("unnamed", 42, [7, 11, 2]), "entity|DIS7:unnamed:42|7:11:2", "e4343a4b-ef62-5f44-89b4-f8e69a0ce298"),
    ("zero components", ("unnamed", 42, [0, 0, 0]), "entity|DIS7:unnamed:42|0:0:0", "0dec07c5-479e-59dc-b5ce-79bb48de8434"),
    ("exercise zero", ("unnamed", 0, [7, 11, 1]), "entity|DIS7:unnamed:0|7:11:1", "e2be1d9c-0530-5568-9c76-ed72f7903ec8"),
]

N13 = [
    "2026-04-29T06:15:00", "2016-12-31T23:59:60Z", "2026-02-30T00:00:00Z", "not-a-time",
    "2026-04-29T06:15:00.0000Z", "2026-04-29T06:15:00.000001Z",
    "2026-04-29t06:15:00Z", "2026-04-29T06:15:00z", "2026-04-29 06:15:00Z", "2026-04-29T24:00:00Z",
    "2026-04-29T06:60:00Z", "2026-13-01T00:00:00Z", "2026-00-10T00:00:00Z", "2026-04-00T00:00:00Z",
    "2026-04-31T00:00:00Z", "2026-02-29T00:00:00Z", "1900-02-29T00:00:00Z", "0000-01-01T00:00:00Z",
    "2026-04-29T06:15:00+24:00", "2026-04-29T06:15:00+23:60", "2026-04-29T06:15:00+0200",
    "2026-04-29T06:15:00+02", "20260429T061500Z", "2026-04-29T06:15Z", "2026-04-29T06:15:00.Z",
    "2026-04-29T06:15:00,5Z", "0001-01-01T00:00:00+00:01", "9999-12-31T23:59:59-00:01",
    "0001-01-01T00:00:00+01:00",
]

N13_NOT_IDS = [
    "2026-04-29T06:15:00Z\n", " 2026-04-29T06:15:00Z", "2026-04-29T06:15:00Z ", "",
    "\u0662\u0660\u0662\u0666-04-29T06:15:00Z", "2026-04-29T06:15:00\uff3a",
    None, 0, 1.5, b"2026-04-29T06:15:00Z",
    datetime.datetime(2026, 4, 29, 6, 15, tzinfo=datetime.timezone.utc),
]

EQUIVALENT_SPELLINGS = [
    "2026-04-29T08:15:00+02:00", "2026-04-29T06:15:00Z", "2026-04-29T06:15:00.0Z",
    "2026-04-28T20:45:00-09:30",
]

ACCEPTED = {
    "2026-04-29T20:15:00+14:00": "2026-04-29T06:15:00.000Z",
    "2026-04-28T18:15:00-12:00": "2026-04-29T06:15:00.000Z",
    "2026-04-29T11:45:00+05:30": "2026-04-29T06:15:00.000Z",
    "2026-04-29T06:15:00-00:00": "2026-04-29T06:15:00.000Z",
    "2026-04-29T06:15:00+00:00": "2026-04-29T06:15:00.000Z",
    "2026-04-29T06:15:00+23:59": "2026-04-28T06:16:00.000Z",
    "2026-04-29T06:15:00-23:59": "2026-04-30T06:14:00.000Z",
    "2024-02-29T12:00:00Z": "2024-02-29T12:00:00.000Z",
    "2000-02-29T12:00:00Z": "2000-02-29T12:00:00.000Z",
    "2024-03-01T00:30:00+01:00": "2024-02-29T23:30:00.000Z",
    "2026-04-29T06:15:00.5Z": "2026-04-29T06:15:00.500Z",
    "2026-04-29T06:15:00.05Z": "2026-04-29T06:15:00.050Z",
    "2026-04-29T06:15:00.123Z": "2026-04-29T06:15:00.123Z",
    "0001-01-01T00:00:00Z": "0001-01-01T00:00:00.000Z",
    "0999-12-31T23:59:59.999Z": "0999-12-31T23:59:59.999Z",
    "1000-01-01T00:30:00+01:00": "0999-12-31T23:30:00.000Z",
    "9999-12-31T23:59:59.999Z": "9999-12-31T23:59:59.999Z",
    "0001-01-01T00:00:00-00:01": "0001-01-01T00:01:00.000Z",
    "9999-12-31T23:59:59+00:01": "9999-12-31T23:58:59.000Z",
}

FOUR_DIGIT_YEARS = [
    (datetime.datetime(1, 1, 1, tzinfo=datetime.timezone.utc), "0001-01-01T00:00:00.000Z"),
    (
        datetime.datetime(999, 12, 31, 23, 59, 59, 999000, tzinfo=datetime.timezone.utc),
        "0999-12-31T23:59:59.999Z",
    ),
]

WHITESPACE = [
    "\u0009", "\u000a", "\u000b", "\u000c", "\u000d",
    "\u001c", "\u001d", "\u001e", "\u001f", " ",
    "\u0085", "\u00a0", "\u1680",
    "\u2000", "\u2001", "\u2002", "\u2003", "\u2004", "\u2005",
    "\u2006", "\u2007", "\u2008", "\u2009", "\u200a",
    "\u2028", "\u2029", "\u202f", "\u205f", "\u3000", "\ufeff",
]


def _refused(code: str, path: str, build, *args, **kwargs) -> Dis7Error:
    with pytest.raises(Dis7Error) as caught:
        build(*args, **kwargs)
    assert caught.value.code == code
    assert caught.value.path == path
    return caught.value


def _instant_refused(instant) -> Dis7Error:
    return _refused("E_CONTEXT_TIME", "time_context.instant", TimeContext, instant, BASIS)


def _basis_refused(basis) -> Dis7Error:
    return _refused("E_CONTEXT_TIME", "time_context.basis", TimeContext, INSTANT, basis)


def _session_refused(value) -> Dis7Error:
    return _refused("E_CONTEXT_SESSION", "session", validate_session, value)


# T08, case A06


def test_t08_a06_identity_strings():
    assert external_id([7, 11, 1]) == "7:11:1"
    assert external_id((7, 11, 1)) == "7:11:1"
    assert external_id([0, 0, 0]) == "0:0:0"
    assert external_id([65535, 65535, 65535]) == "65535:65535:65535"
    assert identity_system("unnamed", 42) == "DIS7:unnamed:42"
    assert identity_system("unnamed", 7) == "DIS7:unnamed:7"
    assert identity_system("s", 0) == "DIS7:s:0"
    assert identity_system("unnamed", 255) == "DIS7:unnamed:255"


def test_t08_a06_base_uuid_is_the_published_literal():
    derived = entity_uuid("unnamed", 42, [7, 11, 1])
    assert derived == uuid.UUID(BASE_UUID)
    assert type(derived) is uuid.UUID
    assert derived.version == 5


@pytest.mark.parametrize(
    ("label", "arguments", "name", "literal"), MUTATIONS, ids=[row[0] for row in MUTATIONS],
)
def test_t08_a06_each_identity_mutation_changes_the_uuid(label, arguments, name, literal):
    assert uuid.uuid5(uuid.UUID(NAMESPACE_LITERAL), name) == uuid.UUID(literal)
    assert dis7.entity_uuid(*arguments) == uuid.UUID(literal)
    literals = [BASE_UUID] + [row[3] for row in MUTATIONS]
    assert len(set(literals)) == 8


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t08_a06_vector_identities_match_the_bundle(stem):
    raw = dis7_support.vector_bytes(stem)
    expected = dis7_support.vector_json(stem, "expected")[0]
    exercise = raw[1]
    entity_id = struct.unpack_from(">HHH", raw, 12)
    assert str(entity_uuid("unnamed", exercise, entity_id)) == expected["entity_id"]
    assert external_id(entity_id) == expected["source_ids"][0]["external_id"]
    assert identity_system("unnamed", exercise) == expected["source_ids"][0]["system"]


def test_t08_a06_identity_takes_only_session_exercise_and_entity():
    parameters = list(inspect.signature(dis7.entity_uuid).parameters)
    assert parameters == ["session", "exercise_id", "entity_id"]
    assert entity_uuid("unnamed", 42, [7, 11, 1]) == entity_uuid("unnamed", 42, (7, 11, 1))


# T09, case N13


# CR-01, CR-23
@pytest.mark.parametrize("instant", N13, ids=N13)
def test_t09_n13_refused_instant(instant):
    error = _instant_refused(instant)
    assert instant not in error.message


@pytest.mark.parametrize("instant", N13_NOT_IDS, ids=[f"case{i}" for i in range(len(N13_NOT_IDS))])
def test_t09_n13_refused_instants_that_cannot_be_test_ids(instant):
    error = _instant_refused(instant)
    if isinstance(instant, str) and instant:
        assert instant not in error.message


def test_t09_n13_instant_is_checked_before_basis():
    _refused("E_CONTEXT_TIME", "time_context.instant", TimeContext, "not-a-time", "")


# T09, case A07


@pytest.mark.parametrize("spelling", EQUIVALENT_SPELLINGS, ids=EQUIVALENT_SPELLINGS)
def test_t09_a07_equivalent_spellings_normalise_to_one_instant(spelling):
    context = TimeContext(spelling, BASIS)
    reference = TimeContext(INSTANT, BASIS)
    assert context.instant == INSTANT
    assert context == reference
    assert hash(context) == hash(reference)


# CR-24
@pytest.mark.parametrize(("instant", "normalised"), list(ACCEPTED.items()), ids=list(ACCEPTED))
def test_t09_a07_accepted_instant_is_normalised(instant, normalised):
    context = TimeContext(instant, BASIS)
    assert context.instant == normalised
    assert TimeContext(normalised, BASIS) == context


# CR-32
@pytest.mark.parametrize(("stamp", "literal"), FOUR_DIGIT_YEARS, ids=["0001", "0999"])
def test_t09_a07_years_0001_and_0999_serialise_with_four_digits_through_the_sdk(stamp, literal):
    assert TimeContext(literal, BASIS).instant == literal
    assert times.render(stamp) == literal
    assert pydantic.TypeAdapter(models.Timestamp).dump_python(stamp) == literal
    assert times.render(times.parse_wire(literal)) == literal


# T09, basis, time context and session


def test_t09_basis_bounds_in_code_points():
    for basis in ("x", "x" * 1024, "\U0001F600" * 1024):
        assert TimeContext(INSTANT, basis).basis == basis
    for basis in ("", "x" * 1025, "\U0001F600" * 1025, None, 5, b"x"):
        _basis_refused(basis)
    error = _basis_refused("q" * 1025)
    assert "qqqq" not in error.message


# CR-07
def test_t09_basis_whitespace_is_the_enumerated_set():
    assert dis7.BASIS_WHITESPACE == frozenset(WHITESPACE)
    assert len(dis7.BASIS_WHITESPACE) == 30
    for character in WHITESPACE:
        _basis_refused(character)
        _basis_refused(character * 3)
        assert TimeContext(INSTANT, character + "x").basis == character + "x"
    _basis_refused(" \ufeff\u0085\u00a0\u001c\t")
    for basis in ("\u200b", "\u180e", "\u001b"):
        assert TimeContext(INSTANT, basis).basis == basis


def test_t09_basis_must_be_utf8_encodable_and_is_kept_verbatim():
    _basis_refused("\ud800")
    _basis_refused("ok\udfff")
    for basis in ("  padded  ", "e\u0301", "line one\nline two", BASIS):
        assert TimeContext(INSTANT, basis).basis == basis


def test_t09_time_context_is_frozen_and_equal_by_value():
    context = TimeContext(INSTANT, BASIS)
    assert [field.name for field in dataclasses.fields(TimeContext)] == ["instant", "basis"]
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.instant = "2026-04-29T06:15:01.000Z"
    with pytest.raises(dataclasses.FrozenInstanceError):
        context.basis = "other"
    assert TimeContext("2026-04-29T08:15:00+02:00", BASIS) != TimeContext(INSTANT, BASIS + " ")
    assert TimeContext("2026-04-29T08:15:00+02:00", BASIS) != TimeContext("2026-04-29T07:15:00Z", BASIS)
    assert TimeContext(instant=INSTANT, basis=BASIS) == context


def test_t09_session_bounds_and_alphabet():
    for value in ("a", "unnamed", "another-run", "A-Z_a.z-09", "x" * 128, ".", "-", "_"):
        assert validate_session(value) is value
    for value in (
        "", "x" * 129, "a b", "a:b", "a\n", "a/b", "\u00e9", "\uff41", "a\u0661",
        None, 5, True, b"unnamed", ["a"],
    ):
        _session_refused(value)
    error = _session_refused("a:b")
    assert "a:b" not in error.message
