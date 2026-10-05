"""Smoke tests of `Dis7Adapter`: the three vendored vectors on both input paths, byte-exact replay,
the constructor's context checks, `fixture_instance`, the coded guard and the declarations.

Expected values come from the vendored bundle files under `fixtures/dis7/vectors/` or from literals
of the frozen contract, never from the adapter itself.
"""
from __future__ import annotations

import array
import ast
import builtins
import collections
import copy
import dataclasses
import enum
import hashlib
import io
import json
import math
import os
import pathlib
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import jsonschema
import pytest

import synapse_cdm
from synapse_cdm import evidence, harness, suite, times
from synapse_cdm.adapter import InputTooDeep, InputTooLarge, is_shipped, load_adapter, shipped
from synapse_cdm.adapters import dis7
from synapse_cdm.adapters.dis7 import Dis7Adapter, Dis7Error, TimeContext
from synapse_cdm.models import Entity, SourceHash
from tests.dis7_support import (CONTRACT, FIXTURES, STEMS, VECTORS, fixture_adapter, geodetic_to_ecef,
                                patch, seed, vector_bytes, vector_json)

HEX64 = "0123456789abcdef" * 4


def _same(got, want, path="$"):
    """Type-strict, sign-strict equality with the bundle's JSON: 25 is not 25.0, -0.0 is not 0.0."""
    if isinstance(want, dict):
        assert isinstance(got, dict) and set(got) == set(want), path
        for key in want:
            _same(got[key], want[key], f"{path}.{key}")
    elif isinstance(want, list):
        assert isinstance(got, list) and len(got) == len(want), path
        for index, (g, w) in enumerate(zip(got, want)):
            _same(g, w, f"{path}[{index}]")
    elif isinstance(want, float):
        assert type(got) is float and got == want, (path, got, want)
        assert math.copysign(1.0, got) == math.copysign(1.0, want), (path, got, want)
    else:
        assert type(got) is type(want) and got == want, (path, got, want)


def _refused(call, code, path):
    with pytest.raises(Dis7Error) as raised:
        call()
    assert (raised.value.code, raised.value.path) == (code, path), str(raised.value)
    assert str(raised.value).startswith(f"{code} at {path}: ")
    return raised.value


def _raising_clock():
    raise AssertionError("the adapter read the clock")


def _nested(levels):
    node = {}
    for _ in range(levels - 1):
        node = {"k": node}
    return node


@pytest.mark.parametrize("stem", STEMS)
def test_t01_a01_vector_bytes_equal_expected(stem):
    out = fixture_adapter(clock=_raising_clock).to_cdm(vector_bytes(stem))
    assert isinstance(out, list) and len(out) == 1
    _same(out[0].model_dump(mode="json"), vector_json(stem, "expected")[0])


@pytest.mark.parametrize("stem", STEMS)
def test_t01_a01_vector_envelope_equals_expected(stem):
    envelope = vector_json(stem, "envelope")
    want = vector_json(stem, "expected")[0]
    for adapter in (fixture_adapter(clock=_raising_clock),
                    fixture_adapter(clock=_raising_clock, time_context=None)):
        out = adapter.to_cdm(envelope)
        assert isinstance(out, list) and len(out) == 1
        _same(out[0].model_dump(mode="json"), want)
    assert envelope == vector_json(stem, "envelope")


def test_t01_a01_vectors_replay_byte_exact():
    from synapse_cdm.adapters.dis7_codec import decode_pdu, encode_pdu

    adapter = fixture_adapter(clock=_raising_clock)
    for stem in STEMS:
        raw = vector_bytes(stem)
        assert adapter.from_cdm(adapter.to_cdm(raw)) == raw, stem
        assert adapter.from_cdm(adapter.to_cdm(vector_json(stem, "envelope"))) == raw, stem
        assert encode_pdu(decode_pdu(raw)) == raw, stem


# CR-15, CR-14
def test_replay_smoke_refuses_count_edit_and_foreign_session():
    adapter = fixture_adapter()
    entity = adapter.to_cdm(seed())[0]
    _refused(lambda: adapter.from_cdm([]), "E_REPLAY_SHAPE", "$")
    _refused(lambda: adapter.from_cdm([entity, entity]), "E_REPLAY_SHAPE", "$")
    edited = entity.model_copy(deep=True)
    edited.position.lat = 1.0
    _refused(lambda: adapter.from_cdm([edited]), "E_REPLAY_CHANGED", "[0].position")
    _refused(lambda: fixture_adapter(session="another").from_cdm([entity]),
             "E_REPLAY_PROVENANCE", "[0].residual.data.session")


class _MixinSession(str, enum.Enum):
    ALPHA = "alpha-1"


class _StrEnumSession(enum.StrEnum):
    ALPHA = "alpha-1"


class _PlainSubclass(str):
    pass


_DROP = object()
_DEFECTS = {
    "session_omitted": ("session", _DROP, "E_CONTEXT_SESSION", "session"),
    "session_empty": ("session", "", "E_CONTEXT_SESSION", "session"),
    "session_space": ("session", "bad session", "E_CONTEXT_SESSION", "session"),
    "session_129": ("session", "a" * 129, "E_CONTEXT_SESSION", "session"),
    "session_trailing_newline": ("session", "run-1\n", "E_CONTEXT_SESSION", "session"),
    "session_not_text": ("session", 42, "E_CONTEXT_SESSION", "session"),
    "session_str_enum_mixin": ("session", _MixinSession.ALPHA, "E_CONTEXT_SESSION", "session"),
    "session_str_enum": ("session", _StrEnumSession.ALPHA, "E_CONTEXT_SESSION", "session"),
    "session_str_subclass": ("session", _PlainSubclass("alpha-1"), "E_CONTEXT_SESSION", "session"),
    "synthetic_omitted": ("synthetic", _DROP, "E_CONTEXT_SYNTHETIC", "synthetic"),
    "synthetic_one": ("synthetic", 1, "E_CONTEXT_SYNTHETIC", "synthetic"),
    "synthetic_text": ("synthetic", "true", "E_CONTEXT_SYNTHETIC", "synthetic"),
    "time_context_dict": ("time_context", {"instant": "2026-04-29T06:15:00Z", "basis": "b"},
                          "E_CONTEXT_TIME", "time_context"),
    "hash_text": ("source_hash", HEX64, "E_CONTEXT_HASH", "source_hash"),
    "hash_model": ("source_hash", SourceHash(algorithm="sha256", value=HEX64),
                   "E_CONTEXT_HASH", "source_hash"),
    "hash_extra_key": ("source_hash", {"algorithm": "sha256", "value": HEX64, "x": 1},
                       "E_CONTEXT_HASH", "source_hash"),
    "hash_algorithm": ("source_hash", {"algorithm": "md5", "value": HEX64},
                       "E_CONTEXT_HASH", "source_hash.algorithm"),
    "hash_uppercase": ("source_hash", {"algorithm": "sha256", "value": HEX64.upper()},
                       "E_CONTEXT_HASH", "source_hash.value"),
    "hash_63": ("source_hash", {"algorithm": "sha256", "value": HEX64[:63]},
                "E_CONTEXT_HASH", "source_hash.value"),
}


# CR-08, CR-10, CR-29
@pytest.mark.parametrize("defect", list(_DEFECTS))
def test_constructor_refuses_each_context_defect(defect):
    key, value, code, path = _DEFECTS[defect]
    kwargs = {"session": "run-1", "synthetic": True, "time_context": None, "source_hash": None}
    if value is _DROP:
        del kwargs[key]
    else:
        kwargs[key] = value
    _refused(lambda: Dis7Adapter(clock=_raising_clock, **kwargs), code, path)


# CR-10
def test_constructor_checks_run_in_the_frozen_order():
    _refused(lambda: Dis7Adapter(), "E_CONTEXT_SESSION", "session")
    _refused(lambda: Dis7Adapter(session="run-1", time_context=1, source_hash=1),
             "E_CONTEXT_SYNTHETIC", "synthetic")
    _refused(lambda: Dis7Adapter(session="run-1", synthetic=False, time_context=1, source_hash=1),
             "E_CONTEXT_TIME", "time_context")


class _UncheckedContext(TimeContext):
    """A TimeContext whose fields never went through `TimeContext.__post_init__`."""

    def __post_init__(self):
        pass


def _setattr_context(instant):
    context = TimeContext("2026-04-29T06:15:00.000Z", "b")
    object.__setattr__(context, "instant", instant)
    return context


_BYPASSED_CONTEXTS = {
    "not_an_instant": (lambda: _UncheckedContext("not an instant", "b"), "time_context.instant"),
    "not_normalised": (lambda: _UncheckedContext("2026-04-29T06:15:00Z", "b"),
                       "time_context.instant"),
    "empty_basis": (lambda: _UncheckedContext("2026-04-29T06:15:00.000Z", ""),
                    "time_context.basis"),
    "no_fields": (lambda: TimeContext.__new__(TimeContext), "time_context.instant"),
    "setattr_after_init": (lambda: _setattr_context("garbage"), "time_context.instant"),
}


# R21: a time context that bypassed its own validation is refused by the constructor
@pytest.mark.parametrize("form", list(_BYPASSED_CONTEXTS))
def test_constructor_revalidates_a_time_context_that_bypassed_validation(form):
    make, path = _BYPASSED_CONTEXTS[form]
    _refused(lambda: Dis7Adapter(session="run-1", synthetic=True, time_context=make()),
             "E_CONTEXT_TIME", path)


class _InstantRaises(TimeContext):
    """A TimeContext whose `instant` raises when it is read."""

    @property
    def instant(self):
        raise RuntimeError("the instant raises")


class _BasisRaises(TimeContext):
    """A TimeContext whose `basis` raises when it is read."""

    @property
    def basis(self):
        raise RuntimeError("the basis raises")


def _raising_context(cls, name, value):
    context = cls.__new__(cls)
    object.__setattr__(context, name, value)
    return context


# R30: an attribute read of the caller's TimeContext that raises is a coded refusal
@pytest.mark.parametrize("cls, name, value, path", [
    (_InstantRaises, "basis", "b", "time_context.instant"),
    (_BasisRaises, "instant", "2026-04-29T06:15:00.000Z", "time_context.basis"),
])
def test_constructor_refuses_a_time_context_whose_read_raises(cls, name, value, path):
    context = _raising_context(cls, name, value)
    _refused(lambda: Dis7Adapter(session="run-1", synthetic=True, time_context=context),
             "E_CONTEXT_TIME", path)


def test_constructor_keeps_its_own_copy_of_the_time_context():
    context = TimeContext("2026-04-29T06:15:00.000Z", "b")
    adapter = Dis7Adapter(session="run-1", synthetic=True, time_context=context)
    object.__setattr__(context, "instant", "garbage")
    assert adapter.validate_source(seed()) == []
    assert adapter.time_context == TimeContext("2026-04-29T06:15:00.000Z", "b")


# CR-21
def test_fixture_instance_is_the_vector_context_and_refuses_live():
    hooked = Dis7Adapter.fixture_instance(clock=_raising_clock)
    context = vector_json("equator_eastbound", "context")
    assert hooked.session == "unnamed" == context["session"]
    assert hooked.synthetic is True and context["synthetic"] is True
    assert hooked.time_context == TimeContext(**context["time_context"])
    assert hooked.source_hash is None and context["source_hash"] is None
    _refused(lambda: Dis7Adapter.fixture_instance(synthetic=False),
             "E_CONTEXT_SYNTHETIC", "synthetic")


# CR-28, CR-29
def test_t03_n09_guard_refuses_4225_octets_in_every_octet_form():
    adapter = fixture_adapter()
    big = b"\xff" * 4225
    for form in (big, bytearray(big), memoryview(big)):
        error = _refused(lambda: adapter.to_cdm(form), "E_INPUT_LIMIT", "$")
        assert isinstance(error, InputTooLarge)
        assert "4224" in str(error) and "4225" in str(error)
    error = _refused(lambda: adapter.to_cdm(b"\xff" * 4224), "E_HEADER_UNSUPPORTED", "byte[0]")
    assert not isinstance(error, InputTooLarge)
    headed = seed() + bytes(4081)
    assert len(headed) == 4225
    _refused(lambda: adapter.to_cdm(headed), "E_INPUT_LIMIT", "$")
    assert adapter.detect(headed) is False


# CR-12
def test_guard_measures_text_before_it_types_it():
    adapter = fixture_adapter()
    wide = "x" * 4223 + "é"
    assert len(wide) == 4224
    error = _refused(lambda: adapter.to_cdm(wide), "E_INPUT_LIMIT", "$")
    assert isinstance(error, InputTooLarge)
    assert "4225" in str(error) and "4224" in str(error)
    view = memoryview(seed())
    view.release()
    for value in ("x" * 4224, None, 42, 1.5, [], ("pdu",), "\ud800", view):
        error = _refused(lambda: adapter.to_cdm(value), "E_INPUT_TYPE", "$")
        assert not isinstance(error, InputTooLarge)
    assert adapter.detect(view) is False


class _RaisingBytes(bytes):
    def __bytes__(self):
        raise KeyError("x")


class _SelfBytes(bytes):
    def __bytes__(self):
        return self

    def __len__(self):
        raise KeyError("x")


# R21: the guard refuses a bytes subclass whose methods raise with a code, never a foreign error
def test_guard_refuses_a_bytes_subclass_that_raises_as_input_type():
    adapter = fixture_adapter()
    _refused(lambda: adapter.to_cdm(_RaisingBytes(seed())), "E_INPUT_TYPE", "$")
    for value in (_RaisingBytes(seed()), _SelfBytes(seed())):
        found = adapter.validate_source(value)
        assert len(found) == 1 and found[0].startswith("E_INPUT_TYPE at $: "), found


# R22: the guard measures a buffer before it copies it
@pytest.mark.parametrize("kind", ["bytearray", "memoryview"])
def test_guard_refuses_an_oversize_buffer_before_it_is_copied(kind):
    adapter = Dis7Adapter(session="run-1", synthetic=True)
    buffer = bytearray(1 << 24)
    raw = buffer if kind == "bytearray" else memoryview(buffer)
    tracemalloc.start()
    try:
        with pytest.raises(Dis7Error) as raised:
            adapter.to_cdm(raw)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert (raised.value.code, raised.value.path) == ("E_INPUT_LIMIT", "$")
    assert "16777216" in raised.value.message
    assert peak < 1024 * 1024, peak


def test_t03_n20_guard_refuses_seventeen_levels_and_admits_sixteen():
    adapter = fixture_adapter()
    error = _refused(lambda: adapter.to_cdm(_nested(17)), "E_INPUT_LIMIT", "$")
    assert isinstance(error, InputTooDeep)
    _refused(lambda: adapter.to_cdm(_nested(16)), "E_TWIN_SCHEMA", "$")


def test_t03_n20_guard_refuses_a_cycle():
    adapter = fixture_adapter()
    loop = {}
    loop["pdu"] = loop
    envelope = vector_json("equator_eastbound", "envelope")
    records = []
    records.append(records)
    envelope["pdu"]["variable_parameters_hex"] = records
    for value in (loop, envelope):
        error = _refused(lambda: adapter.to_cdm(value), "E_INPUT_LIMIT", "$")
        assert isinstance(error, InputTooDeep)
    assert adapter.detect(loop) is False
    assert adapter.validate_source(loop)[0].startswith("E_INPUT_LIMIT at $: ")


def test_t03_n20_guard_admits_a_shared_structure_that_is_not_a_cycle():
    adapter = fixture_adapter()
    node = {}
    for _ in range(15):
        node = {"a": node, "b": node, "c": node}
    started = time.perf_counter()
    _refused(lambda: adapter.to_cdm(node), "E_TWIN_SCHEMA", "$")
    assert time.perf_counter() - started < 1.0
    raw = patch(seed(), 28, seed()[20:28])
    envelope = vector_json("equator_eastbound", "envelope")
    envelope["wire_hex"] = raw.hex()
    envelope["pdu"]["alternative_entity_type"] = envelope["pdu"]["entity_type"]
    out = adapter.to_cdm(envelope)
    assert len(out) == 1
    assert adapter.from_cdm(out) == raw


def test_guard_is_outermost_and_keeps_the_sdk_markers():
    outer = Dis7Adapter.to_cdm
    sdk = outer.__wrapped__
    assert outer.__input_bounded__ is True
    assert sdk.__input_bounded__ is True
    with pytest.raises(InputTooLarge) as raised:
        sdk(fixture_adapter(), b"\xff" * 4225)
    assert not isinstance(raised.value, Dis7Error)
    assert not hasattr(sdk.__wrapped__, "__wrapped__")
    assert Dis7Adapter.metadata.capabilities.limits.max_depth is None


def test_adapter_version_is_1_0_0():
    assert Dis7Adapter.version == "1.0.0"
    assert Dis7Adapter.metadata.adapter_version == "1.0.0"
    assert fixture_adapter().to_cdm(seed())[0].source.adapter_version == "1.0.0"


def test_examples_is_never_imported():
    root = pathlib.Path(synapse_cdm.__file__).parent
    for relative in ("adapters/dis7.py", "adapters/dis7_codec.py", "dis7_host.py"):
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] != "examples", (relative, name)


def test_maturity_basis_cites_one_existing_test_and_the_bytes_tolerance():
    basis = Dis7Adapter.metadata.maturity.basis
    assert re.findall(r"`(bytes|values)` tolerance \(`ROUNDTRIP_TOLERANCE`\)", basis) == ["bytes"]
    assert "conformance run --adapter dis7" in basis
    cited = [token.rstrip(".,;") for token in basis.split() if token.startswith("tests/") and "::" in token]
    assert cited == ["tests/test_cdm_dis7_adapter.py::test_t01_a01_vectors_replay_byte_exact"]
    assert "def test_t01_a01_vectors_replay_byte_exact(" in pathlib.Path(__file__).read_text(encoding="utf-8")


SCHEMAS = pathlib.Path(__file__).resolve().parents[1] / "schemas"
MALFORMED = FIXTURES / "malformed"


@pytest.mark.parametrize("suffix", ("", ".parsed"))
@pytest.mark.parametrize("stem", STEMS)
def test_t01_a01_harness_goldens_equal_the_expected_vectors(stem, suffix):
    golden = json.loads((FIXTURES / "golden" / f"{stem}{suffix}.cdm.json").read_text(encoding="utf-8"))
    expected = vector_json(stem, "expected")
    assert isinstance(golden, list) and len(golden) == 1
    assert golden == expected
    # The dumped text also separates 25 from 25.0 and -0.0 from 0.0, which `==` does not.
    assert json.dumps(golden, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.parametrize("instant", (times.FROZEN_NOW, datetime(2031, 1, 2, 3, 4, 5, tzinfo=timezone.utc)))
def test_the_harness_passes_all_six_fixtures_under_two_clocks(instant):
    # FROZEN_NOW is the fixtures' own instant, so only the second clock can tell a state instant
    # taken from the context from one taken from the clock.
    report = harness.run(Dis7Adapter.fixture_instance(times.frozen_clock(instant)), FIXTURES,
                         schema_dir=SCHEMAS)
    assert report["passed"] == 6
    assert report["failed"] == 0
    assert report["preservation"]["basis"] == "ledger"
    assert len(report["results"]) == 6
    for result in report["results"]:
        checks = result["checks"]
        name = result["fixture"]
        assert result["objects"] == 1, name
        for column in ("translate", "schema", "provenance", "golden"):
            assert checks[column] == "PASS", (name, column)
        if name.endswith(".dis"):
            assert checks["lossless"] == "SKIP", name
            assert checks["roundtrip"] == "PASS", name
        else:
            assert name.endswith(".parsed.json"), name
            assert checks["lossless"] == "PASS", name
            assert checks["roundtrip"] == "SKIP", name
            assert result["preservation"]["counts"]["LOST"] == 0, name


REFUSALS = {
    "wrong_protocol_version.dis": ("E_HEADER_UNSUPPORTED", "byte[0]"),
    "pdu_type_67.dis": ("E_HEADER_UNSUPPORTED", "byte[2]"),
    "truncated_by_one_byte.dis": ("E_LENGTH_MISMATCH", "byte[143]"),
    "one_trailing_byte.dis": ("E_LENGTH_MISMATCH", "byte[8]"),
    "envelope_unknown_key.json": ("E_TWIN_SCHEMA", "$"),
}


def test_the_malformed_set_is_exactly_the_five_stated_payloads():
    assert sorted(p.name for p in harness.select_fixtures(MALFORMED)) == sorted(REFUSALS)


def _malformed_is_refused(name):
    code, path = REFUSALS[name]
    raw = harness.load_raw(MALFORMED / name)
    _refused(lambda: Dis7Adapter.fixture_instance().to_cdm(raw), code, path)
    problems = Dis7Adapter.fixture_instance().validate_source(raw)
    assert isinstance(problems, list) and len(problems) == 1
    assert isinstance(problems[0], str) and problems[0].startswith(f"{code} at {path}: ")


def test_t02_n01_malformed_wrong_protocol_version_is_refused():
    assert (MALFORMED / "wrong_protocol_version.dis").read_bytes() == patch(seed(), 0, b"\x06")
    _malformed_is_refused("wrong_protocol_version.dis")


def test_t02_n02_malformed_pdu_type_67_is_refused():
    assert (MALFORMED / "pdu_type_67.dis").read_bytes() == patch(seed(), 2, bytes([67]))
    _malformed_is_refused("pdu_type_67.dis")


def test_t02_n06_malformed_truncated_by_one_byte_is_refused():
    assert (MALFORMED / "truncated_by_one_byte.dis").read_bytes() == seed()[:143]
    _malformed_is_refused("truncated_by_one_byte.dis")


def test_t02_n07_malformed_one_trailing_byte_is_refused():
    assert (MALFORMED / "one_trailing_byte.dis").read_bytes() == seed() + b"\x00"
    _malformed_is_refused("one_trailing_byte.dis")


def test_malformed_envelope_with_an_unknown_member_is_refused():
    built = json.dumps({**vector_json("equator_eastbound", "envelope"), "unexpected_member": 0}, indent=2) + "\n"
    assert (MALFORMED / "envelope_unknown_key.json").read_text(encoding="utf-8") == built
    _malformed_is_refused("envelope_unknown_key.json")


# ---------------------------------------------------------------------------------------------
# The acceptance sweep: the adapter-level half of every case whose operation reaches `to_cdm`.
# ---------------------------------------------------------------------------------------------

BASIS = "Synthetic fixture scenario instant; not capture time"
BASE_UUID = "d55bb6da-5e94-5583-a12b-249da222ab37"
OTHER_RUN_UUID = "d902dde1-c845-5e32-b9ab-2f63c45ac1a8"
HOST_HASH = "c958233bda22e82385788584e0297d0e264ee2a0db94dc32838141925155ef1a"
INSTANT_X = "2031-07-08T09:10:11.250Z"
OTHER_CLOCK = times.frozen_clock(datetime(2040, 1, 2, 3, 4, 5, tzinfo=timezone.utc))
N1 = "DIS timestamp preserved; state instant supplied by caller: " + BASIS
N2 = "Force ID preserved; affiliation UNKNOWN without exercise viewpoint."
ECEF = "ECEF metres -> WGS84 degrees/HAE."
WORLD = "World-coordinate velocity -> local horizontal speed/course/up."
ZERO = "Zero ECEF vector has no geodetic projection; retained, position absent."
RETAINED = "Dead reckoning algorithm {}: velocity retained without projection."
POLE_Z = 6356752.314245179

S = seed()
P = patch
FA = fixture_adapter
MAX = P(P(S, 19, b"\xff"), 8, b"\x10\x80") + bytes(4080)

ENTITY_VALIDATOR = jsonschema.Draft202012Validator(
    json.loads((CONTRACT / "dis7-entity.schema.json").read_text(encoding="utf-8")))
_NOTHING = object()


def _h_view(octets):
    items = array.array("H")
    assert items.itemsize == 2
    items.frombytes(octets)
    return memoryview(items)


def _envelope(stem="equator_eastbound"):
    return copy.deepcopy(vector_json(stem, "envelope"))


def _pdu(entity):
    return entity.residual.data["pdu"]


def _notes(entity):
    return entity.source.transformations


def _near(got, want, tolerance):
    assert got is not None and abs(got - want) <= tolerance, (got, want)


def _course(got, want):
    if want is None:
        assert got is None, got
    else:
        assert got is not None
        assert abs((got - want + 180.0) % 360.0 - 180.0) <= 1e-7, (got, want)


def _kinematics(entity, speed, course, climb):
    moving = entity.kinematics
    assert moving is not None
    _near(moving.speed_mps, speed, 1e-6)
    _course(moving.course_deg, course)
    _near(moving.climb_mps, climb, 1e-6)


def _position(entity, lat, lon, alt):
    where = entity.position
    assert where is not None
    _near(where.lat, lat, 1e-9)
    _near(where.lon, lon, 1e-9)
    _near(where.alt_m, alt, 0.001)


def _matches(stem):
    def check(entity):
        _same(entity.model_dump(mode="json"), vector_json(stem, "expected")[0])
    return check


@dataclasses.dataclass
class Accept:              # to_cdm must return exactly one Entity
    label: str
    adapter: object
    raw: object            # octets or an envelope dict
    check: object          # check(entity) asserts the semantics


@dataclasses.dataclass
class Refuse:              # to_cdm must raise this code at this path
    label: str
    adapter: object
    raw: object
    code: str
    path: str


@dataclasses.dataclass
class RefuseConstruct:     # Dis7Adapter(**kwargs) must raise this code at this path
    label: str
    kwargs: dict
    code: str
    path: str


def _run(item):
    if isinstance(item, Accept):
        out = item.adapter.to_cdm(item.raw)
        assert type(out) is list
        assert len(out) == 1
        assert isinstance(out[0], Entity)
        item.check(out[0])
        problems = sorted(e.message for e in ENTITY_VALIDATOR.iter_errors(out[0].model_dump(mode="json")))
        assert problems == []
        if isinstance(item.raw, dict):
            wire = bytes.fromhex(item.raw["wire_hex"])
        else:
            wire = bytes(item.raw)
        assert item.adapter.from_cdm(out) == wire
        assert item.adapter.validate_source(item.raw) == []
    elif isinstance(item, Refuse):
        result = _NOTHING
        with pytest.raises(Dis7Error) as caught:
            result = item.adapter.to_cdm(item.raw)
        assert result is _NOTHING
        assert (caught.value.code, caught.value.path) == (item.code, item.path), str(caught.value)
        assert item.adapter.validate_source(item.raw) == [str(caught.value)]
        assert str(caught.value).startswith(f"{item.code} at {item.path}: ")
    elif isinstance(item, RefuseConstruct):
        with pytest.raises(Dis7Error) as caught:
            Dis7Adapter(**item.kwargs)
        assert (caught.value.code, caught.value.path) == (item.code, item.path), str(caught.value)
    else:
        raise AssertionError(f"not a sweep item: {item!r}")


def _refuse(label, raw, code, path):
    return [Refuse(label, FA(), raw, code, path)]


def _b_t01_a01():
    items = []
    for stem in STEMS:
        items.append(Accept(f"{stem}.dis", FA(), vector_bytes(stem), _matches(stem)))
        items.append(Accept(f"{stem}.envelope", FA(), _envelope(stem), _matches(stem)))
    return items


def _b_t02_n06():
    return [Refuse(f"first {n} octets", FA(), S[:n], "E_LENGTH_MISMATCH", f"byte[{n}]")
            for n in range(144)]


def _b_t03_n09():
    error = _refused(lambda: FA().to_cdm(bytes(4225)), "E_INPUT_LIMIT", "$")
    assert isinstance(error, InputTooLarge)
    assert "4224" in str(error) and "4225" in str(error)
    return [Refuse(label, FA(), raw, "E_INPUT_LIMIT", "$")
            for label, raw in (("4225 zero octets", bytes(4225)), ("MAX plus one octet", MAX + b"\x00"),
                               ("seed plus 4081 octets", S + bytes(4081)))]


def _check_a02(entity):
    pdu = _pdu(entity)
    assert pdu["variable_parameters_hex"] == ["00" * 16] * 255
    assert pdu["header"]["length"] == 4224
    assert len(entity.residual.data["wire_hex"]) == 8448
    _kinematics(entity, 25.0, 90.0, 0.0)


_F32 = ("7fc00000", "7f800000", "ff800000")
_F64 = ("7ff8000000000000", "7ff0000000000000", "fff0000000000000")


def _nonfinite(offsets, patterns):
    return [Refuse(f"byte[{offset}] = {pattern}", FA(), P(S, offset, bytes.fromhex(pattern)),
                   "E_NONFINITE", f"byte[{offset}]")
            for offset in offsets for pattern in patterns]


# CR-19
_A03 = ((0, 180, 35786000), (49, 16, 400), (-45, -179.5, 12000), (89.999, 34, -100), (-90, 0, 0))


def _check_geodetic(lat, lon, h):
    def check(entity):
        _position(entity, lat, lon, h)
    return check


def _check_pole(sign):
    def check(entity):
        where = entity.position
        assert where.lat == sign * 90.0
        assert where.lon == 0.0 and math.copysign(1.0, where.lon) == 1.0
        _near(where.alt_m, 0.0, 0.001)
    return check


# R15, R16: a negative zero reaching the projection from the wire comes out as positive zero
def _check_positive_zero_position(entity):
    assert math.copysign(1.0, entity.position.lat) == 1.0
    assert math.copysign(1.0, entity.position.lon) == 1.0
    _position(entity, 0.0, 0.0, 120.0)
    assert "-0.0" not in json.dumps(entity.model_dump(mode="json")["position"])


def _b_t05_a03():
    want = (4030279.376829747, 1155664.0146248138, 4790860.631304157)
    got = geodetic_to_ecef(49, 16, 400)
    assert all(abs(g - w) <= 1e-6 for g, w in zip(got, want)), got
    items = [Accept(f"lat {lat} lon {lon} h {h}", FA(),
                    P(S, 48, struct.pack(">3d", *geodetic_to_ecef(lat, lon, h))),
                    _check_geodetic(lat, lon, h))
             for lat, lon, h in _A03]
    for sign in (1.0, -1.0):
        items.append(Accept(f"pole z {sign * POLE_Z}", FA(),
                            P(S, 48, struct.pack(">3d", 0.0, 0.0, sign * POLE_Z)), _check_pole(sign)))
    items.append(Accept("negative-zero y and z", FA(), P(S, 48, struct.pack(">3d", 6378257.0, -0.0, -0.0)),
                        _check_positive_zero_position))
    return items


def _check_zero_vector(signed):
    def check(entity):
        assert entity.position is None
        assert entity.kinematics is None
        assert _notes(entity) == [N1, N2, ZERO]
        if signed:
            assert math.copysign(1.0, _pdu(entity)["position_ecef_m"][0]) == -1.0
    return check


# CR-35
def _b_t05_n11():
    items = [Refuse(f"position {xyz}", FA(), P(S, 48, struct.pack(">3d", *xyz)),
                    "E_POSITION_DOMAIN", "byte[48]")
             for xyz in ((1.0, 1.0, 1.0), (math.nextafter(1e9, math.inf), 0.0, 0.0),
                         (1.7e308, 1.7e308, 1.7e308))]
    items.append(Accept("position (0, 0, 0)", FA(), P(S, 48, struct.pack(">3d", 0.0, 0.0, 0.0)),
                        _check_zero_vector(False)))
    items.append(Accept("position (-0, 0, -0)", FA(), P(S, 48, struct.pack(">3d", -0.0, 0.0, -0.0)),
                        _check_zero_vector(True)))
    return items


def _check_algorithm(n):
    def check(entity):
        if n in (2, 3, 4, 5):
            _kinematics(entity, 25.0, 90.0, 0.0)
            assert _notes(entity) == [N1, N2, ECEF, WORLD]
        else:
            assert entity.kinematics is None
            _position(entity, 0.0, 0.0, 120.0)
            assert _pdu(entity)["velocity_mps"] == [0.0, 25.0, 0.0]
            assert _notes(entity) == [N1, N2, ECEF, RETAINED.format(n)]
    return check


# CR-30
def _b_t06_a04():
    return [Accept(f"algorithm {n}", FA(), P(S, 88, bytes([n])), _check_algorithm(n))
            for n in range(256)]


_A05_VELOCITIES = (
    ((0.0, 25.0, 0.0), (25.0, 90.0, 0.0)),
    ((0.0, 0.0, 25.0), (25.0, 0.0, 0.0)),
    ((0.0, -25.0, 0.0), (25.0, 270.0, 0.0)),
    ((0.0, 0.0, -25.0), (25.0, 180.0, 0.0)),
    ((25.0, 0.0, 0.0), (0.0, None, 25.0)),
    ((-25.0, 0.0, 0.0), (0.0, None, -25.0)),
    ((0.0, 0.0, 0.0), (0.0, None, 0.0)),
    ((3.0, 4.0, 4.0), (5.656854249492381, 45.0, 3.0)),
)
_A05_ORIENTATIONS = ((0.5, -0.25, 0.125), (0.0, 0.0, 0.0), (3.0, -1.5, 2.5))
# R16: the rotation uses the PDU's own latitude and longitude. Velocities are exact in binary32;
# the expected speed, course and climb are literals of the section 9 formulas.
_A05_ROTATED = (
    ((49.0, 16.0, 400.0), (3.0, 4.0, 12.0),
     (5.724457905405613, 31.818826372764903, 11.671785711245695)),
    ((49.0, 16.0, 400.0), (-7.5, 2.25, -1.5),
     (5.814228695178816, 46.68106137117068, -5.455020135632796)),
    ((-45.0, -179.5, 12000.0), (-5.0, -12.0, -2.0),
     (12.155773963643018, 79.59576892403885, 5.0236599551341605)),
)


def _check_motion(expected, orientation):
    def check(entity):
        _kinematics(entity, *expected)
        assert _pdu(entity)["orientation_radians"] == list(orientation)
    return check


def _check_rotated(where, expected):
    def check(entity):
        _position(entity, *where)
        _kinematics(entity, *expected)
        assert _notes(entity) == [N1, N2, ECEF, WORLD]
    return check


def _check_negative_zero_climb(entity):
    _kinematics(entity, 7.0710678118654755, 225.0, 0.0)
    assert math.copysign(1.0, entity.kinematics.climb_mps) == 1.0


def _check_moving_pole(sign):
    def check(entity):
        assert entity.position.lat == sign * 90.0
        moving = entity.kinematics
        assert moving is not None
        _near(moving.speed_mps, 10.0, 1e-6)
        assert moving.course_deg is None
        _near(moving.climb_mps, 0.0, 1e-6)
    return check


def _b_t07_a05():
    items = []
    for velocity, expected in _A05_VELOCITIES:
        for orientation in _A05_ORIENTATIONS:
            raw = P(P(S, 36, struct.pack(">3f", *velocity)), 72, struct.pack(">3f", *orientation))
            items.append(Accept(f"velocity {velocity} orientation {orientation}", FA(), raw,
                                _check_motion(expected, orientation)))
    for sign in (1.0, -1.0):
        raw = P(P(S, 48, struct.pack(">3d", 0.0, 0.0, sign * POLE_Z)), 36,
                struct.pack(">3f", 10.0, 0.0, 0.0))
        items.append(Accept(f"moving at pole {sign * 90.0}", FA(), raw, _check_moving_pole(sign)))
    items.append(Accept("negative-zero climb", FA(), P(S, 36, struct.pack(">3f", -0.0, -5.0, -5.0)),
                        _check_negative_zero_climb))
    for where, velocity, expected in _A05_ROTATED:
        assert struct.unpack(">3f", struct.pack(">3f", *velocity)) == velocity
        raw = P(P(S, 48, struct.pack(">3d", *geodetic_to_ecef(*where))), 36,
                struct.pack(">3f", *velocity))
        items.append(Accept(f"position {where} velocity {velocity}", FA(), raw,
                            _check_rotated(where, expected)))
    return items


def _check_identity(uuid_text, system=None, external=None):
    def check(entity):
        assert str(entity.entity_id) == uuid_text
        if system is not None:
            assert entity.source_ids[0].system == system
        if external is not None:
            assert entity.source_ids[0].external_id == external
    return check


def _b_t08_a06():
    same = _check_identity(BASE_UUID)
    return [
        Accept("position", FA(), P(S, 48, struct.pack(">d", 6378457.0)), same),
        Accept("timestamp", FA(), P(S, 4, bytes.fromhex("00000002")), same),
        Accept("caller instant", FA(time_context=TimeContext(INSTANT_X, BASIS)), S, same),
        Accept("force", FA(), P(S, 18, b"\x09"), same),
        Accept("orientation", FA(), P(S, 72, struct.pack(">3f", 1.0, 2.0, 3.0)), same),
        Accept("marking", FA(), P(S, 128, b"\x01OTHER-NAME1"), same),
        Accept("session", FA(session="another-run"), S,
               _check_identity(OTHER_RUN_UUID, system="DIS7:another-run:42")),
        Accept("exercise", FA(), P(S, 1, b"\x2b"),
               _check_identity("045ab575-d3cc-5ba3-a2ea-0d713e5b97d5", system="DIS7:unnamed:43")),
        Accept("site", FA(), P(S, 12, b"\x00\x08"),
               _check_identity("7f6c8662-dc0a-5482-a3eb-218e95961722", external="8:11:1")),
        Accept("application", FA(), P(S, 14, b"\x00\x0c"),
               _check_identity("32b3e72c-35a3-5dd8-b0f8-cc36964c5f86", external="7:12:1")),
        Accept("entity", FA(), P(S, 16, b"\x00\x02"),
               _check_identity("e4343a4b-ef62-5f44-89b4-f8e69a0ce298", external="7:11:2")),
    ]


def _envelope_instant(instant):
    envelope = _envelope()
    envelope["time_context"]["instant"] = instant
    return envelope


# CR-03
def _b_t09_n13():
    return [Refuse(instant, FA(time_context=None), _envelope_instant(instant),
                   "E_CONTEXT_TIME", "time_context.instant")
            for instant in ("2026-04-29T06:15:00", "2016-12-31T23:59:60Z", "2026-02-30T00:00:00Z",
                            "not-a-time", "2026-04-29T06:15:00.0000Z", "2026-04-29T06:15:00.000001Z")]


def _check_instant_x(entity):
    assert entity.valid_from == entity.source.observed_at == datetime(
        2031, 7, 8, 9, 10, 11, 250000, tzinfo=timezone.utc)
    dump = entity.model_dump(mode="json")
    assert dump["valid_from"] == INSTANT_X
    assert dump["source"]["observed_at"] == INSTANT_X
    assert dump["residual"]["data"]["time_context"]["instant"] == INSTANT_X
    assert str(entity.entity_id) == BASE_UUID


def _check_rollover(instant, timestamp):
    def check(entity):
        assert entity.model_dump(mode="json")["valid_from"] == instant
        assert _pdu(entity)["header"]["timestamp"] == timestamp
        assert str(entity.entity_id) == BASE_UUID
    return check


# CR-24
def _b_t09_a07():
    items = [Accept(spelling, FA(clock=OTHER_CLOCK, time_context=TimeContext(spelling, BASIS)), S,
                    _check_instant_x)
             for spelling in ("2031-07-08T09:10:11.25Z", "2031-07-08T11:10:11.250+02:00",
                              "2031-07-07T23:40:11.25-09:30", "2031-07-08T09:10:11.250-00:00")]
    for octets, instant, timestamp in ((b"\xff\xff\xff\xff", "2031-07-08T10:20:30.000Z", 4294967295),
                                       (bytes(4), "2031-07-08T09:08:07.000Z", 0)):
        items.append(Accept(f"timestamp {timestamp} at {instant}",
                            FA(clock=OTHER_CLOCK, time_context=TimeContext(instant, BASIS)),
                            P(S, 4, octets), _check_rollover(instant, timestamp)))
    return items


def _b_t09_n14():
    return [
        Refuse("other instant", FA(time_context=TimeContext("2026-04-29T07:15:00Z", BASIS)),
               _envelope(), "E_CONTEXT_CONFLICT", "time_context.instant"),
        Refuse("other basis", FA(time_context=TimeContext("2026-04-29T06:15:00.000Z", BASIS + " ")),
               _envelope(), "E_CONTEXT_CONFLICT", "time_context.basis"),
        Accept("same instant at +02:00", FA(time_context=TimeContext("2026-04-29T08:15:00+02:00", BASIS)),
               _envelope(), _matches("equator_eastbound")),
    ]


def _a08_raw():
    raw = S
    for offset, data in ((10, b"\xa5"), (11, b"\x5a"), (18, b"\xff"), (20, b"\xff" * 8),
                         (28, bytes.fromhex("fefdfcfbfaf9f8f7")), (84, bytes.fromhex("deadbeef")),
                         (89, b"\xc3" * 39), (128, bytes.fromhex("ff0001fe807f2f2e2e2f00ff")),
                         (140, b"\xff" * 4), (19, b"\x02"), (8, b"\x00\xb0")):
        raw = P(raw, offset, data)
    raw += b"\xff" + b"\x11" * 15 + b"\xee" * 16
    assert len(raw) == 176
    return raw


def _b_t10_a08():
    raw = _a08_raw()

    def check(entity):
        pdu = _pdu(entity)
        assert entity.affiliation.value == "UNKNOWN"
        assert entity.entity_type.value == "UNKNOWN"
        assert entity.attributes == {}
        _kinematics(entity, 25.0, 90.0, 0.0)
        assert pdu["header"]["status"] == 0xa5
        assert pdu["header"]["padding"] == 0x5a
        assert pdu["header"]["length"] == 176
        assert pdu["force_id"] == 255
        assert pdu["entity_type"] == [255, 255, 65535, 255, 255, 255, 255]
        assert pdu["alternative_entity_type"] == [254, 253, 64763, 250, 249, 248, 247]
        assert pdu["appearance"] == 0xdeadbeef
        assert pdu["dead_reckoning_hex"] == raw[88:128].hex()
        assert pdu["marking_hex"] == raw[128:140].hex()
        assert pdu["capabilities"] == 0xffffffff
        assert pdu["variable_parameters_hex"] == [raw[144:160].hex(), raw[160:176].hex()]
        assert entity.residual.data["wire_hex"] == raw.hex()
    return [Accept("every opaque field set", FA(), raw, check)]


def _check_a09(entity):
    _matches("north_pole_stationary")(entity)
    assert math.copysign(1.0, _pdu(entity)["velocity_mps"][1]) == -1.0


def _check_a09_antimeridian(entity):
    assert entity.position.lon == -180.0
    assert math.copysign(1.0, _pdu(entity)["position_ecef_m"][1]) == -1.0


# CR-20
def _b_t10_a09():
    wire = vector_bytes("north_pole_stationary")
    assert wire[40:44] == bytes.fromhex("80000000")
    twin = _envelope("north_pole_stationary")
    twin["pdu"]["velocity_mps"] = [0.0, 0.0, 0.0]
    west = P(S, 48, struct.pack(">3d", -6378257.0, -0.0, 0.0))
    west_twin = _envelope()
    west_twin["wire_hex"] = west.hex()
    west_twin["pdu"]["position_ecef_m"] = [-6378257.0, 0.0, 0.0]
    return [Accept("north pole octets", FA(), wire, _check_a09),
            Accept("north pole twin spelling +0", FA(), twin, _check_a09),
            Accept("antimeridian twin spelling +0", FA(), west_twin, _check_a09_antimeridian)]


def _check_null_hash(entity):
    assert entity.source.source_hash is None
    assert entity.residual.data["source_hash"] is None


def _check_host_hash(entity):
    assert entity.source.source_hash.algorithm == "sha256"
    assert entity.source.source_hash.value == HOST_HASH
    assert entity.residual.data["source_hash"] == {"algorithm": "sha256", "value": HOST_HASH}


def _b_t14_n21():
    items = []
    for label, session in (("session omitted", _DROP), ("session empty", ""),
                           ("session 129", "x" * 129), ("session space", "a b"),
                           ("session colon", "a:b"), ("session newline", "a\n"), ("session int", 42)):
        kwargs = {"synthetic": True}
        if session is not _DROP:
            kwargs["session"] = session
        items.append(RefuseConstruct(label, kwargs, "E_CONTEXT_SESSION", "session"))
    for label, synthetic in (("synthetic omitted", _DROP), ("synthetic None", None),
                             ("synthetic 0", 0), ("synthetic 1", 1), ("synthetic text", "true")):
        kwargs = {"session": "unnamed"}
        if synthetic is not _DROP:
            kwargs["synthetic"] = synthetic
        items.append(RefuseConstruct(label, kwargs, "E_CONTEXT_SYNTHETIC", "synthetic"))
    return items


SWEEP_BUILDERS = {
    "t01_a01": _b_t01_a01,
    "t02_n01": lambda: _refuse("octet 0 = 6", P(S, 0, b"\x06"), "E_HEADER_UNSUPPORTED", "byte[0]"),
    "t02_n02": lambda: _refuse("octet 2 = 67", P(S, 2, b"\x43"), "E_HEADER_UNSUPPORTED", "byte[2]"),
    "t02_n03": lambda: _refuse("octet 3 = 2", P(S, 3, b"\x02"), "E_HEADER_UNSUPPORTED", "byte[3]"),
    "t02_n04": lambda: _refuse("octet 19 = 1", P(S, 19, b"\x01"), "E_LENGTH_MISMATCH", "byte[19]"),
    "t02_n05": lambda: _refuse("octet 9 = 143", P(S, 9, b"\x8f"), "E_LENGTH_MISMATCH", "byte[8]"),
    "t02_n06": _b_t02_n06,
    "t02_n07": lambda: _refuse("one trailing octet", S + b"\x00", "E_LENGTH_MISMATCH", "byte[8]"),
    "t02_n08": lambda: _refuse("seed twice", S + S, "E_LENGTH_MISMATCH", "byte[8]"),
    "t03_n09": _b_t03_n09,
    "t03_a02": lambda: [Accept("255 zero records", FA(), MAX, _check_a02)],
    "t04_n36": lambda: _nonfinite((36, 40, 44), _F32),
    "t04_n48": lambda: _nonfinite((48, 56, 64), _F64),
    "t04_n72": lambda: _nonfinite((72, 76, 80), _F32),
    "t05_a03": _b_t05_a03,
    "t05_n11": _b_t05_n11,
    "t06_a04": _b_t06_a04,
    "t07_a05": _b_t07_a05,
    "t08_a06": _b_t08_a06,
    "t09_n12": lambda: [Refuse("raw octets", FA(time_context=None), S, "E_CONTEXT_TIME", "time_context")],
    "t09_n13": _b_t09_n13,
    "t09_a07": _b_t09_a07,
    "t09_n14": _b_t09_n14,
    "t10_a08": _b_t10_a08,
    "t10_a09": _b_t10_a09,
    "t13_a10": lambda: [Accept("raising clock", FA(clock=_raising_clock), S, _matches("equator_eastbound"))],
    "t14_a11": lambda: [Accept("no host hash", FA(), S, _check_null_hash),
                        Accept("host hash", FA(source_hash={"algorithm": "sha256", "value": HOST_HASH}), S,
                               _check_host_hash)],
    "t14_n21": _b_t14_n21,
}

SWEEP_COUNTS = {
    "t01_a01": 6, "t02_n01": 1, "t02_n02": 1, "t02_n03": 1, "t02_n04": 1, "t02_n05": 1,
    "t02_n06": 144, "t02_n07": 1, "t02_n08": 1, "t03_n09": 3, "t03_a02": 1, "t04_n36": 9,
    "t04_n48": 9, "t04_n72": 9, "t05_a03": 8, "t05_n11": 5, "t06_a04": 256, "t07_a05": 30,
    "t08_a06": 11, "t09_n12": 1, "t09_n13": 6, "t09_a07": 6, "t09_n14": 3, "t10_a08": 1,
    "t10_a09": 3, "t13_a10": 1, "t14_a11": 2, "t14_n21": 12,
}


# CR-13, CR-20
@pytest.mark.parametrize("key", sorted(SWEEP_BUILDERS))
def test_acceptance_sweep(key):
    items = SWEEP_BUILDERS[key]()
    assert len(items) == SWEEP_COUNTS[key]
    for item in items:
        print(key, item.label)
        _run(item)


def test_sweep_table_binds_exactly_the_cases_that_reach_the_adapter():
    cases = json.loads((CONTRACT / "acceptance-cases.json").read_text(encoding="utf-8"))["cases"]
    group = {case["id"]: case["group"] for case in cases}
    bound = set()
    for key in SWEEP_BUILDERS:
        match = re.fullmatch(r"t(\d\d)_([an]\d\d)", key)
        assert match, key
        case = match.group(2).upper()
        assert group.get(case) == f"T{match.group(1)}", key
        bound.add(case)
    assert set(SWEEP_COUNTS) == set(SWEEP_BUILDERS)
    assert len(bound) == len(SWEEP_BUILDERS) == 28
    assert set(group) - bound == {"N10", "N15", "N16", "N17", "N18", "N19", "N20", "A12", "A13", "A14"}


def test_sweep_items_agree_with_the_contract_expected_and_operation():
    cases = {case["id"]: case
             for case in json.loads((CONTRACT / "acceptance-cases.json").read_text(encoding="utf-8"))["cases"]}
    ieee = {"NaN": math.nan, "positive_infinity": math.inf, "negative_infinity": -math.inf}
    for key, build in SWEEP_BUILDERS.items():
        case = cases[key.split("_")[1].upper()]          # "t02_n01" -> "N01"
        items = build()
        if case["expected"] == "ACCEPT":
            assert all(isinstance(item, Accept) for item in items), key
        else:
            codes = {item.code for item in items if isinstance(item, (Refuse, RefuseConstruct))}
            assert codes == set(re.findall(r"E_[A-Z_]+", case["expected"])), key
        operation = case["operation"]
        if not isinstance(operation, dict):              # prose operations are checked by review only
            continue
        assert case["seed"] == "equator_eastbound", key  # S is seed() == the equator vector
        ((kind, arg),) = operation.items()
        raws = [item.raw for item in items]              # only dict-operation cases: all items are Refuse
        if kind == "replace_byte":
            assert raws == [P(S, arg["offset"], bytes([arg["value"]]))], key
        elif kind == "truncate_each_length":
            assert raws == [S[:n] for n in range(arg["start_inclusive"], arg["end_inclusive"] + 1)], key
        elif kind == "append_hex":
            assert raws == [S + bytes.fromhex(arg)], key
        elif kind == "replace_ieee":
            fmt = ">f" if arg["width"] == "binary32" else ">d"
            for name in arg["values"]:
                assert P(S, arg["offset"], struct.pack(fmt, ieee[name])) in raws, (key, name)
        else:
            raise AssertionError(f"{key}: unknown operation {kind}")


# ---------------------------------------------------------------------------------------------
# Vectors (R25)
# ---------------------------------------------------------------------------------------------

def test_r25_index_walk_translates_each_wire_file_under_its_context_file():
    index = json.loads((VECTORS / "index.json").read_text(encoding="utf-8"))
    assert {entry["id"] for entry in index} == set(STEMS)
    assert len(index) == len(STEMS)
    root = VECTORS.parent
    for entry in index:
        ctx = json.loads((root / entry["context_file"]).read_text(encoding="utf-8"))
        adapter = Dis7Adapter(session=ctx["session"], synthetic=ctx["synthetic"],
                              time_context=TimeContext(ctx["time_context"]["instant"],
                                                       ctx["time_context"]["basis"]),
                              source_hash=ctx["source_hash"])
        assert entry["expected_status"] == "ACCEPT", entry["id"]
        assert entry["replay"] == "byte_exact", entry["id"]
        wire = (root / entry["wire_file"]).read_bytes()
        expected = json.loads((root / entry["expected_file"]).read_text(encoding="utf-8"))
        out = adapter.to_cdm(wire)
        assert type(out) is list and len(out) == 1 and isinstance(out[0], Entity)
        _same(out[0].model_dump(mode="json"), expected[0])
        assert adapter.from_cdm(out) == wire
        envelope = json.loads((root / entry["envelope_file"]).read_text(encoding="utf-8"))
        twin = adapter.to_cdm(envelope)
        assert len(twin) == 1
        assert twin[0] == out[0]


# ---------------------------------------------------------------------------------------------
# T09
# ---------------------------------------------------------------------------------------------

def test_t09_n12_raw_bytes_without_time_context_never_fall_back_to_a_clock():
    calls = []

    def clock():
        calls.append("called")
        raise AssertionError("the adapter read the clock")

    for adapter in (FA(time_context=None, clock=clock), FA(time_context=None, clock=OTHER_CLOCK)):
        _refused(lambda: adapter.to_cdm(S), "E_CONTEXT_TIME", "time_context")
        problems = adapter.validate_source(S)
        assert type(problems) is list and len(problems) == 1
        assert problems[0].startswith("E_CONTEXT_TIME at time_context: ")
        # stage 4 before stage 8, stage 8 before stage 9
        _refused(lambda: adapter.to_cdm(P(S, 0, b"\x06")), "E_HEADER_UNSUPPORTED", "byte[0]")
        _refused(lambda: adapter.to_cdm(P(S, 48, struct.pack(">3d", 1.0, 1.0, 1.0))),
                 "E_CONTEXT_TIME", "time_context")
        out = adapter.to_cdm(_envelope())
        assert len(out) == 1
        _same(out[0].model_dump(mode="json"), vector_json("equator_eastbound", "expected")[0])
    assert calls == []


def test_t09_n14_equal_instants_agree_and_a_different_instant_or_basis_conflicts():
    entities = []
    for instant in ("2026-04-29T08:15:00+02:00", "2026-04-29T06:15:00Z", "2026-04-28T20:45:00-09:30"):
        out = FA(time_context=TimeContext(instant, BASIS)).to_cdm(_envelope())
        assert len(out) == 1
        entities.append(out[0])
    assert entities[0] == entities[1] == entities[2]
    assert entities[0].model_dump(mode="json")["valid_from"] == "2026-04-29T06:15:00.000Z"
    for instant in ("2026-04-29T07:15:00Z", "2026-04-29T06:15:00.001Z"):
        adapter = FA(time_context=TimeContext(instant, BASIS))
        _refused(lambda: adapter.to_cdm(_envelope()), "E_CONTEXT_CONFLICT", "time_context.instant")
    for basis in (BASIS + " ", BASIS[:-1]):
        adapter = FA(time_context=TimeContext("2026-04-29T06:15:00.000Z", basis))
        _refused(lambda: adapter.to_cdm(_envelope()), "E_CONTEXT_CONFLICT", "time_context.basis")
    adapter = FA(time_context=TimeContext("2026-04-29T07:15:00Z", BASIS + "x"))
    _refused(lambda: adapter.to_cdm(_envelope()), "E_CONTEXT_CONFLICT", "time_context.instant")


# R06, R10, R19: the envelope's own instant in another spelling is normalised
@pytest.mark.parametrize("own", ("no constructor context", "fixture context"))
@pytest.mark.parametrize("spelling", ("2026-04-29T08:15:00+02:00", "2026-04-29T06:15:00Z",
                                      "2026-04-28T20:45:00.0-09:30"))
def test_t09_n14_envelope_instant_in_another_spelling_is_normalised(spelling, own):
    adapter = FA(time_context=None) if own == "no constructor context" else FA()
    envelope = _envelope_instant(spelling)
    out = adapter.to_cdm(envelope)
    assert type(out) is list and len(out) == 1
    dump = out[0].model_dump(mode="json")
    _same(dump, vector_json("equator_eastbound", "expected")[0])
    assert dump["valid_from"] == dump["source"]["observed_at"] == "2026-04-29T06:15:00.000Z"
    assert out[0].residual.data["time_context"]["instant"] == "2026-04-29T06:15:00.000Z"
    assert adapter.from_cdm(out) == S
    assert adapter.validate_source(envelope) == []
    assert envelope["time_context"]["instant"] == spelling


# ---------------------------------------------------------------------------------------------
# T10
# ---------------------------------------------------------------------------------------------

def test_t10_a08_every_force_id_keeps_affiliation_unknown():
    adapter = FA()
    for force in range(256):
        raw = P(S, 18, bytes([force]))
        out = adapter.to_cdm(raw)
        assert out[0].affiliation.value == "UNKNOWN", force
        assert _pdu(out[0])["force_id"] == force
        assert adapter.from_cdm(out) == raw, force


def test_t10_a08_entity_kind_1_is_platform_and_every_other_kind_unknown():
    adapter = FA()
    for kind in range(256):
        raw = P(S, 20, bytes([kind]))
        out = adapter.to_cdm(raw)
        assert out[0].entity_type.value == ("PLATFORM" if kind == 1 else "UNKNOWN"), kind
        assert _pdu(out[0])["entity_type"][0] == kind
        assert adapter.from_cdm(out) == raw, kind


_OPAQUE_EDITS = (
    (84, bytes.fromhex("00000000")), (84, bytes.fromhex("ffffffff")), (84, bytes.fromhex("80000001")),
    (140, bytes.fromhex("00000000")), (140, bytes.fromhex("ffffffff")),
    (128, b"\x00" * 12), (128, b"\xff" * 12), (128, b"\x01DESTROYED  "),
    (104, b"\xff" * 24), (104, struct.pack(">6f", 9.5, -9.5, 1e30, -1e30, 0.25, -0.25)),
    (104, bytes.fromhex("7fc00000") * 6),
)


def test_r17_opaque_fields_never_become_status_confidence_or_quality():
    adapter = FA()
    for offset, data in _OPAQUE_EDITS:
        raw = P(S, offset, data)
        label = (offset, data.hex())
        out = adapter.to_cdm(raw)
        entity = out[0]
        assert entity.status is None, label
        assert entity.confidence is None, label
        assert entity.quality is None, label
        assert entity.symbol is None, label
        assert getattr(entity, "integrity") is None, label
        assert entity.attributes == {}, label
        assert entity.ontology_types == [], label
        assert entity.affiliation.value == "UNKNOWN", label
        _kinematics(entity, 25.0, 90.0, 0.0)
        _position(entity, 0.0, 0.0, 120.0)
        assert entity.residual.data["wire_hex"] == raw.hex(), label
        assert adapter.from_cdm(out) == raw, label


# ---------------------------------------------------------------------------------------------
# T13 (A10) and R22
# ---------------------------------------------------------------------------------------------

def test_t13_a10_no_socket_is_opened(monkeypatch, capsys):
    adapter = FA()
    load_adapter("dis7")            # before the sockets go, since import is not the subject

    def refuse(*args, **kwargs):
        raise AssertionError("the dis7 adapter opened a socket")

    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    for stem in STEMS:
        raw = vector_bytes(stem)
        assert adapter.from_cdm(adapter.to_cdm(raw)) == raw
        assert adapter.from_cdm(adapter.to_cdm(_envelope(stem))) == raw
    _refused(lambda: adapter.to_cdm(P(S, 0, b"\x06")), "E_HEADER_UNSUPPORTED", "byte[0]")
    assert harness.main(["--adapter", "dis7", "--json"]) == 0
    capsys.readouterr()


def test_t13_a10_the_clock_is_never_called():
    calls = []

    def clock():
        calls.append("called")
        raise AssertionError("the adapter read the clock")

    for adapter in (FA(clock=clock), Dis7Adapter.fixture_instance(clock=clock)):
        for stem in STEMS:
            raw = vector_bytes(stem)
            out = adapter.to_cdm(raw)
            assert adapter.from_cdm(out) == raw
            assert adapter.from_cdm(adapter.to_cdm(_envelope(stem))) == raw
            assert adapter.validate_source(raw) == []
            assert adapter.detect(raw) is True
            _refused(lambda: adapter.to_cdm(P(raw, 0, b"\x06")), "E_HEADER_UNSUPPORTED", "byte[0]")
    assert calls == []


def test_t13_a10_harness_report_is_unchanged_under_a_different_now(capsys):
    assert harness.main(["--adapter", "dis7", "--json"]) == 0
    first = capsys.readouterr().out
    assert harness.main(["--adapter", "dis7", "--now", "2031-07-08T09:10:11Z", "--json"]) == 0
    second = capsys.readouterr().out
    assert first == second
    report = json.loads(first)
    assert report["passed"] == 6
    assert report["failed"] == 0


_SEED_SCRIPT = (
    "import json, sys\n"
    "from synapse_cdm.adapters.dis7 import Dis7Adapter, TimeContext\n"
    "adapter = Dis7Adapter(session='unnamed', synthetic=True,\n"
    "                      time_context=TimeContext(sys.argv[1], sys.argv[2]))\n"
    "out = []\n"
    "for path in sys.argv[3:]:\n"
    "    with open(path, 'rb') as handle:\n"
    "        raw = handle.read()\n"
    "    objects = adapter.to_cdm(raw)\n"
    "    assert adapter.from_cdm(objects) == raw\n"
    "    out.append([o.model_dump(mode='json') for o in objects])\n"
    "print(json.dumps(out))\n"
)


def test_t13_a10_output_is_byte_identical_across_hash_seeds():
    package = pathlib.Path(synapse_cdm.__file__).resolve().parent
    repo = pathlib.Path(__file__).resolve().parents[1]
    paths = [str(VECTORS / f"{stem}.dis") for stem in STEMS]
    readings = []
    for hash_seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(package.parent)}
        result = subprocess.run([sys.executable, "-c", _SEED_SCRIPT, "2026-04-29T06:15:00.000Z", BASIS,
                                 *paths], capture_output=True, text=True, env=env, cwd=repo)
        assert result.returncode == 0, result.stderr
        readings.append(result.stdout)
    assert readings[0] == readings[1] == readings[2]
    _same(json.loads(readings[0]), [vector_json(stem, "expected") for stem in STEMS])


def _reversed_members(node):
    if isinstance(node, dict):
        return {key: _reversed_members(node[key]) for key in reversed(list(node))}
    if isinstance(node, list):
        return [_reversed_members(value) for value in node]
    return node


def test_t13_a10_member_order_changes_neither_output_nor_diagnostics():
    adapter = FA()
    for stem in STEMS:
        reordered = _reversed_members(_envelope(stem))
        assert list(reordered) == list(reversed(list(_envelope(stem))))
        entity = adapter.to_cdm(reordered)[0]
        assert entity == adapter.to_cdm(_envelope(stem))[0]
        _same(entity.model_dump(mode="json"), vector_json(stem, "expected")[0])
    broken = _envelope()
    broken["pdu"]["force_id"] = "x"
    broken["pdu"]["capabilities"] = "y"
    texts = []
    for envelope in (broken, _reversed_members(broken)):
        error = _refused(lambda: adapter.to_cdm(envelope), "E_TWIN_SCHEMA", "pdu.force_id")
        texts.append(str(error))
    assert texts[0] == texts[1]


def test_t13_a10_parallel_instances_share_no_state():
    raws = {stem: vector_bytes(stem) for stem in STEMS}
    expected = {stem: vector_json(stem, "expected")[0] for stem in STEMS}

    def work(index):
        adapter = FA() if index % 2 == 0 else FA(session="another-run")
        dumps = []
        for _ in range(20):
            for stem in STEMS:
                out = adapter.to_cdm(raws[stem])
                assert adapter.from_cdm(out) == raws[stem]
                dumps.append((stem, out[0].model_dump(mode="json")))
        return index, dumps

    with ThreadPoolExecutor(max_workers=8) as pool:
        finished = list(pool.map(work, range(8)))
    assert [index for index, _ in finished] == list(range(8))
    for index, dumps in finished:
        assert len(dumps) == 60
        for stem, dump in dumps:
            if index % 2 == 0:
                if stem == "equator_eastbound":
                    assert dump["entity_id"] == BASE_UUID
                _same(dump, expected[stem])
            elif stem == "equator_eastbound":
                assert dump["entity_id"] == OTHER_RUN_UUID


def test_t13_a10_inputs_and_constructor_arguments_are_neither_mutated_nor_aliased():
    buffer = bytearray(S)
    out = FA().to_cdm(buffer)
    assert len(out) == 1
    assert bytes(buffer) == S
    envelope = _envelope("north_pole_stationary")
    before = json.dumps(envelope, sort_keys=True)
    entity = FA().to_cdm(envelope)[0]
    assert json.dumps(envelope, sort_keys=True) == before
    entity.residual.data["pdu"]["entity_id"].append(99)
    assert json.dumps(envelope, sort_keys=True) == before
    host = {"algorithm": "sha256", "value": HOST_HASH}
    adapter = FA(source_hash=host)
    assert host == {"algorithm": "sha256", "value": HOST_HASH}
    assert adapter.to_cdm(S)[0].source.source_hash.value == HOST_HASH
    host["value"] = "0" * 64
    again = adapter.to_cdm(S)[0]
    assert again.source.source_hash.value == HOST_HASH
    assert again.residual.data["source_hash"] == {"algorithm": "sha256", "value": HOST_HASH}


_REFUSED_ROOTS = {"socket", "ssl", "urllib", "http", "asyncio", "subprocess", "hashlib", "hmac",
                  "secrets", "platform", "time", "random", "os", "pathlib", "io", "tempfile", "shutil"}
_REFUSED_CALLS = {"open", "now", "utcnow", "today", "fromtimestamp"}


def _import_and_call_scan(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots, calls = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                name = target.id
            elif isinstance(target, ast.Attribute):
                name = target.attr
            else:
                continue
            if name in _REFUSED_CALLS:
                calls.add(name)
    return roots & _REFUSED_ROOTS, calls


def test_t13_a10_adapter_modules_import_no_file_network_clock_or_hash_module(tmp_path):
    folder = pathlib.Path(dis7.__file__).resolve().parent
    for name in ("dis7.py", "dis7_codec.py"):
        assert _import_and_call_scan(folder / name) == (set(), set()), name
    planted = tmp_path / "planted.py"
    planted.write_text("import socket\nfrom datetime import datetime\nstamp = datetime.now()\n",
                       encoding="utf-8")
    assert _import_and_call_scan(planted) == ({"socket"}, {"now"})


def test_r22_duplicate_input_gives_duplicate_output_with_one_identity():
    adapter = FA()
    first, second = adapter.to_cdm(S), adapter.to_cdm(S)
    assert type(first) is list and type(second) is list
    assert len(first) == len(second) == 1
    assert first[0] == second[0]
    assert first[0] is not second[0]
    assert str(first[0].entity_id) == str(second[0].entity_id) == BASE_UUID
    assert first[0].object_kind == "entity"


def test_r22_an_earlier_instant_after_a_later_one_keeps_its_own_instant():
    adapter = FA(time_context=None)
    for instant in ("2031-07-08T10:20:30.000Z", "2031-07-08T09:08:07.000Z"):
        entity = adapter.to_cdm(_envelope_instant(instant))[0]
        dump = entity.model_dump(mode="json")
        assert dump["valid_from"] == instant
        assert dump["source"]["observed_at"] == instant
        assert str(entity.entity_id) == BASE_UUID


def test_r22_marking_bytes_spelling_a_path_open_no_file(monkeypatch):
    raw = P(S, 128, b"\x01/etc/passwd")
    adapter = FA()

    def refuse(*args, **kwargs):
        raise AssertionError("the dis7 adapter opened a file")

    with monkeypatch.context() as m:
        m.setattr(builtins, "open", refuse)
        m.setattr(io, "open", refuse)
        m.setattr(os, "open", refuse)
        out = adapter.to_cdm(raw)
        replayed = adapter.from_cdm(out)
        problems = adapter.validate_source(raw)
    assert _pdu(out[0])["marking_hex"] == "012f6574632f706173737764"
    assert replayed == raw
    assert problems == []


# ---------------------------------------------------------------------------------------------
# T14
# ---------------------------------------------------------------------------------------------

def test_t14_a11_null_host_and_wrong_digests_are_carried_unchanged():
    assert hashlib.sha256(S).hexdigest() == HOST_HASH
    index = json.loads((VECTORS / "index.json").read_text(encoding="utf-8"))
    assert {entry["id"]: entry["sha256"] for entry in index}["equator_eastbound"] == HOST_HASH
    for value in (HOST_HASH, "0" * 64):
        adapter = FA(source_hash={"algorithm": "sha256", "value": value})
        out = adapter.to_cdm(S)
        assert out[0].source.source_hash.algorithm == "sha256"
        assert out[0].source.source_hash.value == value
        assert out[0].residual.data["source_hash"] == {"algorithm": "sha256", "value": value}
        assert adapter.from_cdm(out) == S
    plain = FA()
    out = plain.to_cdm(S)
    assert out[0].source.source_hash is None
    assert plain.from_cdm(out) == S


def test_t14_a11_malformed_hash_records_are_refused():
    for record, path in (({"algorithm": "sha1", "value": HOST_HASH}, "source_hash.algorithm"),
                         ({"algorithm": "sha256", "value": HOST_HASH.upper()}, "source_hash.value"),
                         ({"algorithm": "sha256", "value": HOST_HASH[:63]}, "source_hash.value"),
                         ({"algorithm": "sha256", "value": HOST_HASH + "0"}, "source_hash.value")):
        _refused(lambda: FA(source_hash=record), "E_CONTEXT_HASH", path)
    error = _refused(lambda: FA(source_hash={"algorithm": "sha256", "value": HOST_HASH, "extra": 1}),
                     "E_CONTEXT_HASH", "source_hash")
    assert "extra" not in str(error)


def test_r21_hash_and_twin_messages_echo_nothing():
    error = _refused(lambda: FA(source_hash={"algorithm": "sha256", "value": "Zz-not-a-digest"}),
                     "E_CONTEXT_HASH", "source_hash.value")
    assert "Zz-not-a-digest" not in str(error)
    error = _refused(lambda: FA(source_hash={"algorithm": "Zz-not-an-algorithm", "value": HOST_HASH}),
                     "E_CONTEXT_HASH", "source_hash.algorithm")
    assert "Zz-not-an-algorithm" not in str(error)
    envelope = _envelope()
    envelope["pdu"]["marking_hex"] = "ab" * 12
    error = _refused(lambda: FA().to_cdm(envelope), "E_TWIN_WIRE_MISMATCH", "pdu.marking_hex")
    text = str(error)
    assert "abab" not in text and envelope["wire_hex"][:32] not in text
    assert envelope["pdu"]["dead_reckoning_hex"] not in text and len(text) < 200


class _Int(int):
    pass


class _Float(float):
    pass


class _Dict(dict):
    pass


# CR-29
def test_cr29_subclass_instances_are_not_the_plain_types():
    envelope = _envelope()
    envelope["pdu"]["force_id"] = _Int(1)
    _refused(lambda: FA().to_cdm(envelope), "E_TWIN_SCHEMA", "pdu.force_id")
    envelope = _envelope()
    envelope["pdu"]["velocity_mps"][0] = _Float(envelope["pdu"]["velocity_mps"][0])
    _refused(lambda: FA().to_cdm(envelope), "E_TWIN_SCHEMA", "pdu.velocity_mps[0]")
    _refused(lambda: FA(source_hash=_Dict(algorithm="sha256", value=HOST_HASH)), "E_CONTEXT_HASH",
             "source_hash")
    envelope = _envelope()
    envelope["pdu"] = collections.UserDict(envelope["pdu"])
    _refused(lambda: FA().to_cdm(envelope), "E_TWIN_SCHEMA", "pdu")


def test_t14_n21_synthetic_false_is_carried_to_source_and_residual():
    adapter = FA(synthetic=False)
    out = adapter.to_cdm(S)
    assert out[0].source.synthetic is False
    assert out[0].residual.data["synthetic"] is False
    assert adapter.from_cdm(out) == S


# CR-21
def test_t14_n21_fixture_instance_output_matches_the_vector_context_files():
    adapter = Dis7Adapter.fixture_instance()
    for stem in STEMS:
        entity = adapter.to_cdm(vector_bytes(stem))[0]
        context = vector_json(stem, "context")
        data = entity.residual.data
        for key in ("session", "synthetic", "time_context", "source_hash"):
            _same(data[key], context[key])
        assert data["session"] == "unnamed"
        assert data["synthetic"] is True
        assert data["time_context"] == {"instant": "2026-04-29T06:15:00.000Z", "basis": BASIS}
        assert data["source_hash"] is None
        _same(entity.model_dump(mode="json"), vector_json(stem, "expected")[0])


# CR-21
@pytest.mark.parametrize("command", ("harness", "conformance", "evidence", "harness_live",
                                     "conformance_live"))
def test_t14_n21_sdk_clis_refuse_live_and_a_caller_supplied_fixture_directory(command, tmp_path, capsys):
    tmp = tmp_path / "fixtures"
    tmp.mkdir()
    (tmp / "equator_eastbound.dis").write_bytes(vector_bytes("equator_eastbound"))
    out = tmp_path / "out"
    if command == "harness":
        status = harness.main(["--adapter", "dis7", "--fixtures", str(tmp), "--update-golden"])
    elif command == "conformance":
        status = suite.main(["conformance", "run", "--adapter", "dis7", "--fixtures", str(tmp)])
    elif command == "evidence":
        status = evidence.main(["generate", "--adapter", "dis7", "--fixtures", str(tmp),
                                "--out", str(out)])
    elif command == "harness_live":
        status = harness.main(["--adapter", "dis7", "--synthetic", "false"])
    else:
        status = suite.main(["conformance", "run", "--adapter", "dis7", "--synthetic", "false"])
    captured = capsys.readouterr()
    assert status == 2
    assert captured.out == ""
    if command.endswith("_live"):
        assert "E_CONTEXT_SYNTHETIC at synthetic: " in captured.err, captured.err
        return
    prefix = {"harness": "harness: ", "conformance": "synapse conformance: ",
              "evidence": "synapse evidence: "}[command]
    assert captured.err.startswith(prefix + "--fixtures is refused for "), captured.err
    assert sorted(p.name for p in tmp.iterdir()) == ["equator_eastbound.dis"]
    assert not out.exists() or not any(out.iterdir())


# CR-30
def test_t14_a11_note_sequences_for_all_four_shapes():
    adapter = FA()
    assert _notes(adapter.to_cdm(S)[0]) == [N1, N2, ECEF, WORLD]
    for n in (0, 1, 6, 9, 255):
        assert _notes(adapter.to_cdm(P(S, 88, bytes([n])))[0]) == [N1, N2, ECEF, RETAINED.format(n)], n
    assert _notes(adapter.to_cdm(P(S, 48, bytes(24)))[0]) == [N1, N2, ZERO]
    assert _notes(adapter.to_cdm(vector_bytes("unprojectable_with_extensions"))[0]) == [N1, N2, ZERO]


def test_t14_a11_first_note_carries_a_1024_character_non_ascii_basis_verbatim():
    basis = ("Čas cvičenia №7 · 時刻 · " * 64)[:1024]
    assert len(basis) == 1024
    adapter = FA(time_context=TimeContext(INSTANT_X, basis))
    out = adapter.to_cdm(S)
    assert _notes(out[0])[0] == "DIS timestamp preserved; state instant supplied by caller: " + basis
    assert out[0].residual.data["time_context"] == {"instant": INSTANT_X, "basis": basis}
    assert adapter.from_cdm(out) == S


# CR-32
def test_t09_a07_years_0001_and_0999_are_dumped_with_four_digits():
    for instant in ("0001-02-03T04:05:06.789Z", "0999-02-03T04:05:06.789Z"):
        adapter = FA(time_context=TimeContext(instant, BASIS))
        entity = adapter.to_cdm(S)[0]
        dump = entity.model_dump(mode="json")
        assert dump["valid_from"] == instant
        assert dump["source"]["observed_at"] == instant
        assert dump["residual"]["data"]["time_context"]["instant"] == instant
        assert adapter.from_cdm([entity]) == S


def test_t14_a11_optional_fields_are_dumped_as_explicit_nulls_and_empties():
    adapter = FA()
    for number, stem in enumerate(STEMS):
        dump = adapter.to_cdm(vector_bytes(stem))[0].model_dump(mode="json")
        expected = vector_json(stem, "expected")[0]
        assert set(dump) == set(expected)
        for key in ("valid_to", "confidence", "quality", "integrity", "status", "symbol"):
            assert key in dump and dump[key] is None, (stem, key)
        assert dump["attributes"] == {}
        assert dump["ontology_types"] == []
        assert "source_hash" in dump["source"] and dump["source"]["source_hash"] is None
        data = dump["residual"]["data"]
        assert "source_hash" in data and data["source_hash"] is None
        if number < 2:
            assert set(dump["position"]) == {"lat", "lon", "alt_m", "position_source", "accuracy_m",
                                             "vertical"}
            assert dump["position"]["position_source"] == "ESTIMATED"
            assert dump["position"]["accuracy_m"] is None
            assert dump["position"]["vertical"] is None
        else:
            assert "position" in dump and dump["position"] is None
            assert "kinematics" in dump and dump["kinematics"] is None


# ---------------------------------------------------------------------------------------------
# T15 (SDK half), R07 and stage 10
# ---------------------------------------------------------------------------------------------

def test_t15_decode_and_encode_are_the_sdk_aliases():
    adapter = FA()
    assert adapter.decode(S) == adapter.to_cdm(S)
    assert adapter.encode(adapter.decode(S)) == S
    _refused(lambda: adapter.decode(P(S, 0, b"\x06")), "E_HEADER_UNSUPPORTED", "byte[0]")
    _refused(lambda: adapter.encode([]), "E_REPLAY_SHAPE", "$")


def test_t15_load_adapter_resolves_dis7_to_the_shipped_class():
    assert load_adapter("dis7") is Dis7Adapter
    assert shipped()["dis7"] is Dis7Adapter
    assert is_shipped(Dis7Adapter) is True
    assert Dis7Adapter.name == "dis7"
    assert Dis7Adapter.version == "1.0.0"
    assert Dis7Adapter.direction == "bidirectional"
    assert Dis7Adapter.system == "DIS7"
    source = FA().to_cdm(S)[0].source
    assert source.adapter == "dis7"
    assert source.adapter_version == "1.0.0"
    assert source.format_name == "DIS"
    assert source.format_version == "7 / IEEE 1278.1-2012 Entity State subset"


def _released_view():
    view = memoryview(S)
    view.release()
    return view


def _cyclic():
    loop = {}
    loop["pdu"] = loop
    return loop


def _envelope_edit(edit):
    envelope = _envelope()
    edit(envelope)
    return envelope


# CR-12, CR-29, CR-31
def test_r07_validate_source_matrix():
    adapter = FA()
    for stem in STEMS:
        assert adapter.validate_source(vector_bytes(stem)) == [], stem
        assert adapter.validate_source(_envelope(stem)) == [], stem
    view = _h_view(S)
    assert len(view) == 72 and view.nbytes == 144
    assert adapter.validate_source(view) == []
    out = adapter.to_cdm(_h_view(S))
    _same(out[0].model_dump(mode="json"), vector_json("equator_eastbound", "expected")[0])
    assert adapter.from_cdm(out) == S

    wide = _h_view(S + bytes(4082))
    assert len(wide) == 2113 and wide.nbytes == 4226
    cases = [(FA(time_context=None), S, "E_CONTEXT_TIME at time_context: ")]
    cases += [(adapter, P(S, 2, bytes([t])), "E_HEADER_UNSUPPORTED at byte[2]: ") for t in (2, 3, 4, 67)]
    cases.append((adapter, b"\xd4\xc3\xb2\xa1" + bytes(196), "E_HEADER_UNSUPPORTED at byte[0]: "))
    cases += [(adapter, value, "E_INPUT_TYPE at $: ")
              for value in (None, 5, "x", [], object(), _released_view())]
    cases += [(adapter, value, "E_INPUT_LIMIT at $: ")
              for value in ("x" * 4225, bytes(4225), _cyclic(), wide)]
    cases.append((adapter, _envelope_edit(lambda e: e["pdu"].__setitem__("force_id", 2)),
                   "E_TWIN_WIRE_MISMATCH at pdu.force_id: "))
    cases.append((adapter, _envelope_edit(lambda e: e.__setitem__("extra", 1)), "E_TWIN_SCHEMA at $: "))
    for instance, value, prefix in cases:
        problems = instance.validate_source(value)
        assert type(problems) is list and len(problems) == 1, (prefix, problems)
        assert problems[0].startswith(prefix), (prefix, problems)
        assert re.fullmatch(r"E_[A-Z_]+ at \S+: .+", problems[0]), problems
    problems = adapter.validate_source(wide)
    assert "4226" in problems[0] and "4224" in problems[0]


def _finishes_within(call, seconds=5.0):
    result = []
    thread = threading.Thread(target=lambda: result.append(call()), daemon=True)
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive()
    assert len(result) == 1
    return result[0]


# CR-28
def test_r07_detect_matrix():
    adapter = FA()
    true_inputs = [vector_bytes(stem) for stem in STEMS] + [_envelope(stem) for stem in STEMS]
    true_inputs += [S[:12], S + b"\x00", bytearray(S), memoryview(S), _h_view(S),
                    _envelope_edit(lambda e: e["pdu"]["header"].__setitem__("protocol_version", 7.0))]
    for value in true_inputs:
        assert adapter.detect(value) is True, repr(value)[:80]

    def other_type(envelope):
        envelope["pdu"]["header"]["pdu_type"] = 67
        envelope["wire_hex"] = envelope["wire_hex"][:4] + "43" + envelope["wire_hex"][6:]

    def without_time_context(envelope):
        del envelope["time_context"]

    false_inputs = [b"", S[:11], P(S, 0, b"\x06"), P(S, 2, b"\x43"), P(S, 3, b"\x02"),
                    S + bytes(4081), _h_view(S + bytes(4082)), _released_view(), None, 5, "text",
                    [], {}, {"a": 1},
                    _envelope_edit(lambda e: e.__setitem__("extra", 1)),
                    _envelope_edit(without_time_context),
                    {"pdu": 5, "wire_hex": "", "time_context": {}},
                    _envelope_edit(other_type),
                    _envelope_edit(lambda e: e["pdu"]["header"].__setitem__("pdu_type", True))]
    for value in false_inputs:
        assert adapter.detect(value) is False, repr(value)[:80]
    assert len(S + bytes(4081)) == 4225

    deep = {}
    node = deep
    for _ in range(100000):
        child = {}
        node["k"] = child
        node = child
    three = {"pdu": deep, "wire_hex": "", "time_context": {}}
    assert _finishes_within(lambda: adapter.detect(_cyclic())) is False
    assert _finishes_within(lambda: adapter.detect(three)) is False
    # CR-28, D-12: a three-key envelope with a 7/1/1 header is still False when the depth and
    # cycle walk fails, so these inputs reach the guard itself.
    assert adapter.detect(_envelope()) is True
    cyclic = _envelope()
    cyclic["time_context"]["loop"] = cyclic
    assert _finishes_within(lambda: adapter.detect(cyclic)) is False
    ring = _envelope()
    ring["pdu"]["velocity_mps"][0] = ring["pdu"]["velocity_mps"]
    assert _finishes_within(lambda: adapter.detect(ring)) is False
    over_deep = _envelope()
    node = over_deep["time_context"]
    for _ in range(20):
        node["k"] = {}
        node = node["k"]
    assert adapter.detect(over_deep) is False


# CR-09
def test_cr09_final_cdm_validity_failure_is_e_projection_at_the_root(monkeypatch):
    entity = FA().to_cdm(S)[0]
    monkeypatch.setattr(dis7, "_affiliation", lambda force_id: "NOT-A-MEMBER")
    error = _refused(lambda: FA().to_cdm(S), "E_PROJECTION", "$")
    assert "NOT-A-MEMBER" not in str(error)
    problems = FA().validate_source(S)
    assert len(problems) == 1 and problems[0].startswith("E_PROJECTION at $: ")
    _refused(lambda: FA().from_cdm([entity]), "E_REPLAY_CHANGED", "[0].residual.data.wire_hex")


_PADDED_FORMATS = (b'<?xml version="1.0"?><objectModel', b'<?xml version="1.0"?><MessageBody',
                   b'<?xml version="1.0"?><kml', b"PK\x03\x04", b"\xd4\xc3\xb2\xa1")


def test_t15_bracket_leading_and_refused_format_samples_get_coded_errors():
    adapter = FA()
    samples = [(raw, "E_HEADER_UNSUPPORTED", "byte[0]", True) for raw in (
        b"[" * 144, b"{" * 144, b"[" * 4224, b"{" * 4224, ("[" * 72).encode("utf-16-le"),
        ("[" * 100).encode("utf-16"), b" " + b"[" * 199, P(P(S, 0, b"["), 88, b"[" * 40),
        P(S, 0, b"\x06"), *(head.ljust(200, b" ") for head in _PADDED_FORMATS))]
    samples += [(P(S, 2, bytes([t])), "E_HEADER_UNSUPPORTED", "byte[2]", True)
                for t in (2, 3, 4, 67, 25, 26, 27, *range(11, 23))]
    samples.append((b"PK\x03\x04", "E_LENGTH_MISMATCH", "byte[4]", False))
    samples.append((b"[" * 4225, "E_INPUT_LIMIT", "$", False))
    assert len(samples) == 14 + 19 + 2
    for raw, code, path, plain in samples:
        error = _refused(lambda: adapter.to_cdm(raw), code, path)
        assert isinstance(error, Dis7Error)
        if plain:
            assert not isinstance(error, (InputTooLarge, InputTooDeep)), raw[:8]
        assert adapter.validate_source(raw) == [str(error)]
        assert adapter.detect(raw) is False, raw[:8]
    error = _refused(lambda: adapter.to_cdm(b"[" * 4225), "E_INPUT_LIMIT", "$")
    assert isinstance(error, InputTooLarge)


def test_t15_max_depth_is_declared_absent():
    limits = Dis7Adapter.metadata.capabilities.limits
    assert limits.max_depth is None
    assert "max_depth" in limits.absent_because
    assert limits.max_input_bytes == 4224
