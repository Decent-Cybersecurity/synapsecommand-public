"""The DIS 7 host loader `parse_json_text`: the text halves of cases N18 and N20.

The duplicate-key tests are named `test_t12_n18_text_...` and the bound tests
`test_t03_n20_text_...`: they bind those two cases. The other loader tests — tokens, encodings,
numbers and the host module's surface — are named `test_t12_text_...` and bind nothing.
Expected values come from codes and paths typed here, from the standard decoder called directly,
or from literals; never from `parse_json_text` itself.

The replay tests (`test_t11_...`) bind cases N15, N16 and N17 through `Dis7Adapter.from_cdm`; the
envelope structure tests (`test_t12_n18_...`, `test_t12_n19_...`) bind the dict half of N18 and
N19 through `to_cdm`; the native depth tests (`test_t03_n20_...`) bind the native half of N20.
Their codes and paths are typed from the implementation plan and its decisions, never read from
the adapter; expected octets come from the packaged vectors.
"""
from __future__ import annotations

import ast
import codecs
import copy
import datetime
import json
import math
import os
import pathlib
import struct
import subprocess
import sys
import threading
import uuid

import pytest

import synapse_cdm
from synapse_cdm import dis7_host
from synapse_cdm.adapters.dis7 import TimeContext
from synapse_cdm.adapters.dis7_codec import Dis7Error, Dis7InputTooDeep, Dis7InputTooLarge
from synapse_cdm.dis7_host import parse_json_text
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.geo import VerticalPosition, VerticalReference, VerticalUnit
from synapse_cdm.models import (
    Entity, Event, Integrity, Kinematics, OperationalStatus, Position, Quality, Residual,
    SourceHash, SourceId, SourceRef,
)
from tests import dis7_support

SEED = "equator_eastbound"
ENVELOPE_BYTES = (dis7_support.VECTORS / f"{SEED}.envelope.json").read_bytes()

E_INPUT_TYPE = "E_INPUT_TYPE"
E_INPUT_LIMIT = "E_INPUT_LIMIT"
E_TWIN_SCHEMA = "E_TWIN_SCHEMA"


def _envelope(stem=SEED):
    """A fresh copy of the parsed `vectors/<stem>.envelope.json`."""
    return copy.deepcopy(dis7_support.vector_json(stem, "envelope"))


def _expected(stem=SEED):
    """A fresh copy of the parsed `vectors/<stem>.expected.json`."""
    return copy.deepcopy(dis7_support.vector_json(stem, "expected"))


def _text_refusal(data, code, path, cls=Dis7Error):
    """Assert that the loader refuses `data` with `code` at `path` as a `cls`; return the error."""
    with pytest.raises(Dis7Error) as raised:
        parse_json_text(data)
    err = raised.value
    assert err.code == code
    assert err.path == path
    assert isinstance(err, cls)
    assert str(err) == f"{code} at {path}: {err.message}"
    assert err.__cause__ is None and (err.__context__ is None or err.__suppress_context__)
    return err


def _member(path, key):
    return key if path == "$" else f"{path}.{key}"


def _item(path, index):
    return f"[{index}]" if path == "$" else f"{path}[{index}]"


def _emit(node, path, target):
    if isinstance(node, dict):
        members = [json.dumps(key) + ":" + _emit(value, _member(path, key), target)
                   for key, value in node.items()]
        if path == target:
            members.insert(0, members[0])
        return "{" + ",".join(members) + "}"
    if isinstance(node, list):
        return "[" + ",".join(_emit(value, _item(path, index), target)
                              for index, value in enumerate(node)) + "]"
    return json.dumps(node)


def _dup_text(document, target):
    """Compact JSON bytes of `document` with the first member of the object at `target` twice."""
    text = _emit(document, "$", target)
    assert text != json.dumps(document, separators=(",", ":")), f"no object at {target}"
    return text.encode()


def _depth(document):
    """How many containers deep `document` nests, counted by walking it level by level.

    A `tuple` counts as a container too, as it does for the adapter's guard; JSON text never
    yields one, so the loader tests read the same depth either way."""
    depth = 0
    level = [document]
    while level:
        depth += 1
        level = [child for node in level
                 for child in (node.values() if isinstance(node, dict) else node)
                 if isinstance(child, (dict, list, tuple))]
    return depth


@pytest.mark.parametrize("kind", ("envelope", "expected"))
@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t12_text_packaged_documents_load_unchanged(stem, kind):
    data = (dis7_support.VECTORS / f"{stem}.{kind}.json").read_bytes()
    assert parse_json_text(data) == json.loads(data)


@pytest.mark.parametrize("path", ("$", "pdu", "pdu.header", "time_context"))
def test_t12_n18_text_duplicate_key_in_an_envelope(path):
    dup = _dup_text(_envelope(), path)
    assert json.loads(dup) == _envelope()
    _text_refusal(dup, E_TWIN_SCHEMA, path)


@pytest.mark.parametrize("path", (
    "[0]", "[0].source", "[0].source_ids[0]", "[0].position", "[0].residual",
    "[0].residual.data", "[0].residual.data.pdu", "[0].residual.data.pdu.header",
    "[0].residual.data.time_context",
))
def test_t12_n18_text_duplicate_key_in_an_entity_document(path):
    dup = _dup_text(_expected(), path)
    assert json.loads(dup) == _expected()
    _text_refusal(dup, E_TWIN_SCHEMA, path)


@pytest.mark.parametrize("text,path", (
    pytest.param('{"a": {"b": 1, "b": 2}, "a": 3}', "$", id="outer-first"),
    pytest.param('{"x": {"b": 1, "b": 2}, "y": {"c": 1, "c": 1}}', "x", id="first-in-order"),
    pytest.param('{"a": 1, "a": 1}', "$", id="equal-values"),
    pytest.param('{"Secret Key": {"a": 1, "a": 2}}', "$", id="foreign-key-root"),
    pytest.param('{"pdu": {"Secret-Key": [{"a": 1, "a": 2}]}}', "pdu", id="foreign-key-member"),
    pytest.param('{"k": "SECRETVALUE", "k": 2}', "$", id="value-not-echoed"),
    pytest.param('{"a": [1, {"b": [{"c": 1, "c": 2}]}]}', "a[1].b[0]", id="nested-arrays"),
    pytest.param('[[{"a": 1, "a": 2}]]', "[0][0]", id="root-array"),
))
def test_t12_n18_text_duplicate_key_order_and_foreign_keys(text, path):
    err = _text_refusal(text.encode(), E_TWIN_SCHEMA, path)
    assert "Secret" not in str(err)
    assert "SECRET" not in str(err)


@pytest.mark.parametrize("text", (
    pytest.param('{"a": NaN}', id="nan-member"),
    pytest.param("[Infinity]", id="infinity"),
    pytest.param("[-Infinity]", id="minus-infinity"),
    pytest.param("NaN", id="nan-root"),
))
def test_t12_text_nan_and_infinity_tokens(text):
    _text_refusal(text.encode(), E_TWIN_SCHEMA, "$")
    assert parse_json_text(b'["NaN", "Infinity"]') == ["NaN", "Infinity"]


_TEXT = ENVELOPE_BYTES.decode()
_WIDE = {
    "utf-8-bom": codecs.BOM_UTF8 + ENVELOPE_BYTES,
    "utf-16": _TEXT.encode("utf-16"),
    "utf-16-le": _TEXT.encode("utf-16-le"),
    "utf-16-be": _TEXT.encode("utf-16-be"),
    "utf-16-le-bom": codecs.BOM_UTF16_LE + _TEXT.encode("utf-16-le"),
    "utf-16-be-bom": codecs.BOM_UTF16_BE + _TEXT.encode("utf-16-be"),
    "utf-32": _TEXT.encode("utf-32"),
    "utf-32-le": _TEXT.encode("utf-32-le"),
    "utf-32-be": _TEXT.encode("utf-32-be"),
    "utf-32-le-bom": codecs.BOM_UTF32_LE + _TEXT.encode("utf-32-le"),
    "utf-32-be-bom": codecs.BOM_UTF32_BE + _TEXT.encode("utf-32-be"),
}
_BOMLESS_WIDE = ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be")


@pytest.mark.parametrize("label", tuple(_WIDE))
def test_t12_text_byte_order_mark_and_wide_encodings(label):
    payload = _WIDE[label]
    assert json.loads(payload) == _envelope()
    if label in _BOMLESS_WIDE:
        payload.decode("utf-8")  # the trap: valid UTF-8 byte for byte
    _text_refusal(payload, E_TWIN_SCHEMA, "$")


@pytest.mark.parametrize("data", (
    pytest.param(b'{"a": "\xff"}', id="ff"),
    pytest.param(b'{"a": "\xc3"}', id="truncated"),
    pytest.param(b'"\xc0\xaf"', id="overlong"),
    pytest.param(b'"\xed\xa0\x80"', id="surrogate"),
    pytest.param(b'{"a": 1}\x00', id="trailing-nul"),
    pytest.param(b'{"a": "x\x00y"}', id="nul-in-string"),
))
def test_t12_text_invalid_utf8_and_nul(data):
    err = _text_refusal(data, E_TWIN_SCHEMA, "$")
    assert "0xff" not in str(err)
    assert "\\xff" not in str(err)


@pytest.mark.parametrize("text", (
    pytest.param("[1e400]", id="positive"),
    pytest.param("[-1e400]", id="negative"),
    pytest.param("[1E+400]", id="upper-e"),
    pytest.param('{"a": 1e400}', id="member"),
))
def test_t12_text_numbers_that_overflow(text):
    _text_refusal(text.encode(), E_TWIN_SCHEMA, "$")
    result = parse_json_text(b"[1e308, 1e-400, -0.0]")
    assert result == [1e308, 0.0, 0.0]
    assert math.copysign(1.0, result[2]) == -1.0


@pytest.mark.parametrize("data", (
    pytest.param(b"[" + b"9" * 5000 + b"]", id="positive"),
    pytest.param(b"[-" + b"9" * 5000 + b"]", id="negative"),
    pytest.param(b"9" * 5000, id="root"),
))
def test_t12_text_oversized_integer_literal(data):
    _text_refusal(data, E_TWIN_SCHEMA, "$")
    result = parse_json_text(b"[1234567890123456789]")
    assert result == [1234567890123456789]
    assert type(result[0]) is int


# CR-11
@pytest.mark.parametrize("data", (
    pytest.param(b"", id="empty"),
    pytest.param(b"   ", id="blank"),
    pytest.param(b"{", id="unclosed"),
    pytest.param(b'{"a": 1} x', id="trailing"),
    pytest.param(b"{'a': 1}", id="single-quotes"),
    pytest.param(b'{"a": 1,}', id="trailing-comma"),
    pytest.param(b"[1 2]", id="missing-comma"),
))
def test_t12_text_unparseable(data):
    _text_refusal(data, E_TWIN_SCHEMA, "$")


# CR-11
@pytest.mark.parametrize("data", (
    pytest.param("{}", id="str"),
    pytest.param(bytearray(b"{}"), id="bytearray"),
    pytest.param(memoryview(b"{}"), id="memoryview"),
    pytest.param(None, id="none"),
    pytest.param({}, id="dict"),
))
def test_t12_text_argument_must_be_bytes(data):
    _text_refusal(data, E_INPUT_TYPE, "$")


def test_t12_text_plain_document():
    assert parse_json_text(b' {"a": [1, 2.5, "x", null, true]} ') == {
        "a": [1, 2.5, "x", None, True]}


_FORBIDDEN_ROOTS = {"hashlib", "hmac", "secrets", "ssl", "socket", "signal", "resource",
                    "platform", "subprocess"}
_HEAVY = {"synapse_cdm.evidence", "synapse_cdm.suite", "synapse_cdm.harness"}


def _imported(node):
    """The dotted names an import statement brings in."""
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
    return []


def test_t12_text_host_module_surface_and_imports(tmp_path):
    assert dis7_host.MAX_JSON_BYTES == 65536
    assert dis7_host.MAX_JSON_DEPTH == 16
    tree = ast.parse(pathlib.Path(dis7_host.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        for name in _imported(node):
            assert name.split(".")[0] not in _FORBIDDEN_ROOTS, name
    for node in tree.body:
        for name in _imported(node):
            assert not any(name == heavy or name.startswith(heavy + ".") for heavy in _HEAVY), name
    code = ("import sys, synapse_cdm.dis7_host; "
            f"print(sorted(m for m in {sorted(_HEAVY)!r} if m in sys.modules))")
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=tmp_path,
        env={**os.environ,
             "PYTHONPATH": str(pathlib.Path(synapse_cdm.__file__).resolve().parents[1])})
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "[]"


def test_t03_n20_text_65536_bytes_accepted_and_65537_refused():
    padded = ENVELOPE_BYTES + b" " * (65536 - len(ENVELOPE_BYTES))
    assert len(padded) == 65536
    assert parse_json_text(padded) == _envelope()
    err = _text_refusal(padded + b" ", E_INPUT_LIMIT, "$", Dis7InputTooLarge)
    assert "65536" in str(err)
    assert "65537" in str(err)


@pytest.mark.parametrize("data", (
    pytest.param(b"\xff" * 65537, id="invalid-utf8"),
    pytest.param(codecs.BOM_UTF8 + b" " * 65535, id="byte-order-mark"),
    pytest.param(b"[" * 100000, id="deep"),
    pytest.param(b"\x00" * 65537, id="nul"),
))
def test_t03_n20_text_size_is_checked_before_everything_else(data):
    assert len(data) > 65536
    _text_refusal(data, E_INPUT_LIMIT, "$", Dis7InputTooLarge)


def test_t03_n20_text_depth_16_accepted_and_17_refused():
    arrays = parse_json_text(b"[" * 16 + b"]" * 16)
    assert _depth(arrays) == 16
    _text_refusal(b"[" * 17 + b"]" * 17, E_INPUT_LIMIT, "$", Dis7InputTooDeep)
    objects = parse_json_text(b'{"a":' * 16 + b"1" + b"}" * 16)
    assert _depth(objects) == 16
    _text_refusal(b'{"a":' * 17 + b"1" + b"}" * 17, E_INPUT_LIMIT, "$", Dis7InputTooDeep)
    mixed = parse_json_text(b'[{"a":' * 8 + b"1" + b"}]" * 8)
    assert _depth(mixed) == 16
    leaf = mixed
    for _ in range(8):
        leaf = leaf[0]["a"]
    assert leaf == 1
    _text_refusal(b'[{"a":' * 8 + b"[1]" + b"}]" * 8, E_INPUT_LIMIT, "$", Dis7InputTooDeep)
    assert parse_json_text(b'["' + b"[" * 40 + b'"]') == ["[" * 40]


@pytest.mark.parametrize("data,cls", (
    pytest.param(b"[" * 32768 + b"]" * 32768, Dis7InputTooDeep, id="closed-arrays"),
    pytest.param(b"[" * 65536, Dis7InputTooDeep, id="open-arrays"),
    pytest.param(b'{"a":' * 10000, Dis7InputTooDeep, id="open-objects"),
    pytest.param(b"[" * 100000, Dis7InputTooLarge, id="over-size"),
))
def test_t03_n20_text_very_deep_text_raises_no_recursion_error(data, cls):
    _text_refusal(data, E_INPUT_LIMIT, "$", cls)


@pytest.mark.parametrize("inner", (
    pytest.param(b"NaN", id="nan"),
    pytest.param(b'{"a": 1, "a": 2}', id="duplicate-key"),
))
def test_t03_n20_text_depth_is_checked_before_the_decoder(inner):
    _text_refusal(b"[" * 17 + inner + b"]" * 17, E_INPUT_LIMIT, "$", Dis7InputTooDeep)


# ----------------------------------------------------------------------------------------------
# Replay, envelope structure and native depth: helpers.

E_REPLAY_CHANGED = "E_REPLAY_CHANGED"
E_REPLAY_PROVENANCE = "E_REPLAY_PROVENANCE"
E_REPLAY_SHAPE = "E_REPLAY_SHAPE"
E_TWIN_WIRE_MISMATCH = "E_TWIN_WIRE_MISMATCH"

_TIME = dis7_support.vector_json(SEED, "context")["time_context"]
INSTANT = _TIME["instant"]
BASIS = _TIME["basis"]
HASH_RECORD = {"algorithm": "sha256",
               "value": "c958233bda22e82385788584e0297d0e264ee2a0db94dc32838141925155ef1a"}
OTHER_HASH = {"algorithm": "sha256", "value": "0" * 64}
LATER = "2026-04-29T07:15:00.000Z"
SEED_ID = uuid.UUID("d55bb6da-5e94-5583-a12b-249da222ab37")
OTHER_ID = uuid.UUID("045ab575-d3cc-5ba3-a2ea-0d713e5b97d5")
SECOND = datetime.timedelta(seconds=1)
SUB_MS = datetime.timedelta(microseconds=999)
EXT = "unprojectable_with_extensions"
POLE = "north_pole_stationary"


def _adapter(**overrides):
    return dis7_support.fixture_adapter(**overrides)


def _entity(stem=SEED, **overrides):
    """A fresh Entity translated from the vector's octets on every call."""
    return _adapter(**overrides).to_cdm(dis7_support.vector_bytes(stem))[0]


def _replay_refused(objects, code, path, adapter=None):
    with pytest.raises(Dis7Error) as raised:
        (adapter or _adapter()).from_cdm(objects)
    err = raised.value
    assert (err.code, err.path) == (code, path)
    return err


# CR-31
def _refused(envelope, code, path):
    with pytest.raises(Dis7Error) as raised:
        _adapter().to_cdm(envelope)
    err = raised.value
    assert (err.code, err.path) == (code, path)
    lines = _adapter().validate_source(envelope)
    assert len(lines) == 1
    assert lines[0].startswith(f"{code} at {path}: ")
    return err


def _set_wire(entity, offset, octets):
    """Write `octets` over the stored `wire_hex` from octet `offset` on."""
    data = entity.residual.data
    text = data["wire_hex"]
    data["wire_hex"] = text[:2 * offset] + octets.hex() + text[2 * (offset + len(octets)):]


def _reversed_members(node):
    """A copy of `node` in which every dict lists its members in reverse order."""
    if isinstance(node, dict):
        return {key: _reversed_members(node[key]) for key in reversed(list(node))}
    if isinstance(node, list):
        return [_reversed_members(value) for value in node]
    if isinstance(node, tuple):
        return tuple(_reversed_members(value) for value in node)
    return node


def _chain(levels, kind, leaf=0.0):
    """`levels` nested containers around `leaf`; `mixed` alternates dict (outermost) and list."""
    node = leaf
    for level in range(levels):
        wrap = kind
        if kind == "mixed":
            wrap = "dict" if (levels - 1 - level) % 2 == 0 else "list"
        if wrap == "dict":
            node = {"a": node}
        elif wrap == "list":
            node = [node]
        else:
            node = (node,)
    return node


def _within(seconds, call):
    """The result of `call()` run in a daemon thread; fails when no answer comes in time."""
    outcome = {}

    def run():
        try:
            outcome["value"] = call()
        except BaseException as error:  # handed back to the test thread below
            outcome["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        pytest.fail(f"no answer within {seconds} s")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


def _too_deep(envelope):
    with pytest.raises(Dis7InputTooDeep) as raised:
        _within(10, lambda: _adapter().to_cdm(envelope))
    assert (raised.value.code, raised.value.path) == (E_INPUT_LIMIT, "$")


def _locate(node, path):
    """The container holding the member at the dotted `path` and that member's key or index."""
    steps = []
    for part in path.split("."):
        name, _, index = part.partition("[")
        steps.append(name)
        if index:
            steps.append(int(index.rstrip("]")))
    for step in steps[:-1]:
        node = node[step]
    return node, steps[-1]


def _with(envelope, path, value):
    container, key = _locate(envelope, path)
    container[key] = value
    return envelope


def _without(envelope, path):
    container, key = _locate(envelope, path)
    del container[key]
    return envelope


def _other_digit(text):
    """`text` with its last hex digit replaced by another."""
    return text[:-1] + ("1" if text[-1] == "0" else "0")


# ----------------------------------------------------------------------------------------------
# T11 — replay.

@pytest.mark.parametrize("route", ("bytes", "envelope"))
@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_t11_unchanged_replay_is_byte_exact(stem, route):
    envelope = _envelope(stem)
    adapter = _adapter()
    raw = dis7_support.vector_bytes(stem) if route == "bytes" else envelope
    entity = adapter.to_cdm(raw)[0]
    out = adapter.from_cdm([entity])
    assert type(out) is bytes
    assert out == dis7_support.vector_bytes(stem)
    assert out == bytes.fromhex(envelope["wire_hex"])
    assert adapter.encode([entity]) == out


def _set(name, value):
    return lambda entity: setattr(entity, name, value)


def _set_in(owner, name, value):
    return lambda entity: setattr(getattr(entity, owner), name, value)


_N15_ROWS = (
    ("entity_id", "entity_id", SEED, _set("entity_id", OTHER_ID)),
    ("entity_type", "entity_type", SEED, _set("entity_type", EntityType.UNIT)),
    ("affiliation", "affiliation", SEED, _set("affiliation", Affiliation.FRIENDLY)),
    ("position-none", "position", SEED, _set("position", None)),
    ("position-lat", "position", SEED, _set_in("position", "lat", 1.0)),
    ("position-lon", "position", SEED, _set_in("position", "lon", 1.0)),
    ("position-alt", "position", SEED, _set_in("position", "alt_m", 121.0)),
    ("position-source", "position", SEED,
     _set_in("position", "position_source", PositionSource.GNSS)),
    ("position-accuracy", "position", SEED, _set_in("position", "accuracy_m", 5.0)),
    ("position-vertical", "position", SEED, _set_in("position", "vertical", VerticalPosition(
        value=120.0, unit=VerticalUnit.METRES, reference=VerticalReference.HAE))),
    ("position-added", "position", EXT, _set("position", Position(
        lat=0.0, lon=0.0, position_source=PositionSource.ESTIMATED))),
    ("kinematics-none", "kinematics", SEED, _set("kinematics", None)),
    ("kinematics-speed", "kinematics", SEED, _set_in("kinematics", "speed_mps", 26.0)),
    ("kinematics-course", "kinematics", SEED, _set_in("kinematics", "course_deg", 91.0)),
    ("kinematics-climb", "kinematics", SEED, _set_in("kinematics", "climb_mps", 1.0)),
    ("kinematics-added", "kinematics", EXT, _set("kinematics", Kinematics(speed_mps=1.0))),
    ("valid-from-second", "valid_from", SEED,
     lambda entity: setattr(entity, "valid_from", entity.valid_from + SECOND)),
    ("valid-from-sub-ms", "valid_from", SEED,
     lambda entity: setattr(entity, "valid_from", entity.valid_from + SUB_MS)),
    ("valid-to", "valid_to", SEED, lambda entity: setattr(
        entity, "valid_to", entity.valid_from + datetime.timedelta(hours=1))),
    ("attributes", "attributes", SEED, _set("attributes", {"k": 1})),
    ("ontology-types", "ontology_types", SEED, _set("ontology_types", ["urn:example:dis7-test"])),
    ("confidence", "confidence", SEED, _set("confidence", 0.5)),
    ("quality", "quality", SEED, _set("quality", Quality(confidence=0.5))),
    ("status", "status", SEED, _set("status", OperationalStatus(state="ACTIVE", namespace="DIS"))),
    ("symbol", "symbol", SEED, _set("symbol", "10030100001101000000")),
    ("integrity", "integrity", SEED, _set("integrity", Integrity(
        signature="c2lnbmF0dXJl", algorithm="ML-DSA-87", chain_hash="00" * 32))),
)


# CR-14
@pytest.mark.parametrize("field,stem,edit", [
    pytest.param(field, stem, edit, id=label) for label, field, stem, edit in _N15_ROWS])
def test_t11_n15_canonical_edit_is_refused(field, stem, edit):
    entity = _entity(stem)
    edit(entity)
    _replay_refused([entity], E_REPLAY_CHANGED, f"[0].{field}")


def test_t11_n15_edit_table_covers_every_canonical_field():
    assert {field for _, field, _, _ in _N15_ROWS} == set(Entity.model_fields) - {
        "schema_version", "object_kind", "source", "source_ids", "residual"}


def test_t11_n15_sub_millisecond_edit_is_invisible_in_a_dump():
    entity = _entity()
    entity.valid_from = entity.valid_from + SUB_MS
    assert entity.model_dump(mode="json")["valid_from"] == "2026-04-29T06:15:00.000Z"
    _replay_refused([entity], E_REPLAY_CHANGED, "[0].valid_from")


def test_t11_n15_signed_zero_is_not_an_edit():
    entity = _entity()
    entity.position.lat = -0.0
    entity.kinematics.climb_mps = -0.0
    assert _adapter().from_cdm([entity]) == dis7_support.seed()


_N16_ROWS = (
    ("system", "system", "DIS6"),
    ("adapter", "adapter", "dis"),
    ("adapter-version", "adapter_version", "0.1.0"),
    ("synthetic", "synthetic", False),
    ("format-name", "format_name", "DIS6"),
    ("format-version", "format_version", "6"),
    ("original-id", "original_id", "7:11:2"),
    ("source-hash", "source_hash", SourceHash(**HASH_RECORD)),
    ("record-index", "record_index", 1),
    ("observed-at-second", "observed_at", SECOND),
    ("observed-at-sub-ms", "observed_at", SUB_MS),
    ("transformations", "transformations", None),
)


@pytest.mark.parametrize("field,value", [
    pytest.param(field, value, id=label) for label, field, value in _N16_ROWS])
def test_t11_n16_source_edit_is_refused(field, value):
    entity = _entity()
    source = entity.source
    if field == "observed_at":
        value = source.observed_at + value
    elif field == "transformations":
        value = source.transformations[:-1]
    setattr(source, field, value)
    _replay_refused([entity], E_REPLAY_PROVENANCE, f"[0].source.{field}")
    assert entity.residual.data == _expected()[0]["residual"]["data"]


def test_t11_n16_source_table_covers_every_source_field():
    assert {field for _, field, _ in _N16_ROWS} == set(SourceRef.model_fields)


def _second_source_id(entity):
    entity.source_ids = [entity.source_ids[0],
                         SourceId(system="DIS7:unnamed:42", external_id="7:11:9")]


# CR-25
@pytest.mark.parametrize("edit", (
    pytest.param(lambda entity: setattr(entity.source_ids[0], "system", "DIS7:another-run:42"),
                 id="system"),
    pytest.param(lambda entity: setattr(entity.source_ids[0], "external_id", "7:11:2"),
                 id="external-id"),
    pytest.param(_second_source_id, id="second-id"),
))
def test_t11_n16_source_ids_edit_is_refused(edit):
    entity = _entity()
    edit(entity)
    _replay_refused([entity], E_REPLAY_PROVENANCE, "[0].source_ids")


def _stored(name, value):
    return lambda data: data.__setitem__(name, value)


def _stored_time(name, value):
    return lambda data: data["time_context"].__setitem__(name, value)


_STORED = "[0].residual.data."
_STORED_CONTEXT_ROWS = (
    ("session", _stored("session", "another-run"), "session", "session"),
    ("synthetic", _stored("synthetic", False), "synthetic", "synthetic"),
    ("instant", _stored_time("instant", LATER), "time_context.instant", "[0].source.observed_at"),
    ("basis", _stored_time("basis", BASIS + "x"), "time_context.basis",
     "[0].source.transformations"),
    ("instant-offset", _stored_time("instant", "2026-04-29T08:15:00+02:00"),
     "time_context.instant", "time_context.instant"),
    ("instant-no-fraction", _stored_time("instant", "2026-04-29T06:15:00Z"),
     "time_context.instant", "time_context.instant"),
    ("instant-no-such-day", _stored_time("instant", "2026-02-30T06:15:00.000Z"),
     "time_context.instant", "time_context.instant"),
    ("basis-lone-surrogate", _stored_time("basis", "\ud800"),
     "time_context.basis", "time_context.basis"),
    ("source-hash", _stored("source_hash", dict(HASH_RECORD)),
     "[0].source.source_hash", "[0].source.source_hash"),
)


def _replay_path(path):
    return path if path.startswith("[0]") else _STORED + path


# CR-02
@pytest.mark.parametrize("egress", ("context", "no-context"))
@pytest.mark.parametrize("edit,with_context,without_context", [
    pytest.param(edit, with_context, without_context, id=label)
    for label, edit, with_context, without_context in _STORED_CONTEXT_ROWS])
def test_t11_n16_stored_context_edit_is_refused(edit, with_context, without_context, egress):
    entity = _entity()
    edit(entity.residual.data)
    if egress == "context":
        _replay_refused([entity], E_REPLAY_PROVENANCE, _replay_path(with_context))
    else:
        _replay_refused([entity], E_REPLAY_PROVENANCE, _replay_path(without_context),
                        _adapter(time_context=None))


@pytest.mark.parametrize("overrides,path", (
    pytest.param({"session": "another-run"}, "session", id="session"),
    pytest.param({"synthetic": False}, "synthetic", id="synthetic"),
    pytest.param({"time_context": TimeContext("2026-04-29T07:15:00Z", BASIS)},
                 "time_context.instant", id="instant"),
    pytest.param({"time_context": TimeContext(INSTANT, BASIS + "x")},
                 "time_context.basis", id="basis"),
    pytest.param({"source_hash": dict(HASH_RECORD)}, "source_hash", id="source-hash"),
))
def test_t11_n16_adapter_context_mismatch_is_refused(overrides, path):
    _replay_refused([_entity()], E_REPLAY_PROVENANCE, _STORED + path, _adapter(**overrides))


@pytest.mark.parametrize("route", ("adapter-hash", "stored-hash"))
def test_t11_n16_another_hash_is_refused(route):
    entity = _entity(source_hash=dict(HASH_RECORD))
    if route == "adapter-hash":
        adapter = _adapter(source_hash=dict(OTHER_HASH))
    else:
        entity.residual.data["source_hash"] = dict(OTHER_HASH)
        adapter = _adapter(source_hash=dict(HASH_RECORD))
    _replay_refused([entity], E_REPLAY_PROVENANCE, _STORED + "source_hash", adapter)


@pytest.mark.parametrize("ingress,egress", (
    pytest.param({}, {"time_context": None}, id="no-time-context"),
    pytest.param({}, {"time_context": TimeContext("2026-04-29T08:15:00+02:00", BASIS)},
                 id="offset-instant"),
    pytest.param({"source_hash": dict(HASH_RECORD)}, {}, id="hashed-no-hash"),
    pytest.param({"source_hash": dict(HASH_RECORD)}, {"source_hash": dict(HASH_RECORD)},
                 id="hashed-same-hash"),
    pytest.param({"synthetic": False}, {"synthetic": False}, id="not-synthetic"),
))
def test_t11_n16_agreeing_or_absent_optional_context_is_accepted(ingress, egress):
    entity = _entity(**ingress)
    if "synthetic" in ingress:
        assert entity.source.synthetic is False
        assert entity.residual.data["synthetic"] is False
    assert _adapter(**egress).from_cdm([entity]) == dis7_support.seed()


def _event(entity):
    return Event(event_id=uuid.UUID(int=1), event_type=EventType.DETECTION,
                 severity=Severity.INFO, observed_at=entity.valid_from,
                 received_at=entity.valid_from, source=entity.source,
                 source_ids=entity.source_ids, residual=entity.residual)


class _Extended(Entity):
    operator_note: str = "x"


def _without_residual(entity):
    entity.residual = None
    return [entity]


# CR-15
@pytest.mark.parametrize("build,path", (
    pytest.param(lambda entity: [], "$", id="empty"),
    pytest.param(lambda entity: [entity, _entity()], "$", id="two"),
    pytest.param(lambda entity: [_event(entity)], "$", id="event"),
    pytest.param(lambda entity: _expected(), "$", id="dict-document"),
    pytest.param(lambda entity: entity, "$", id="bare"),
    pytest.param(lambda entity: (entity,), "$", id="tuple"),
    pytest.param(lambda entity: None, "$", id="none"),
    pytest.param(lambda entity: iter([entity]), "$", id="iterator"),
    pytest.param(_without_residual, "[0].residual", id="no-residual"),
    pytest.param(lambda entity: [_Extended.model_validate(entity.model_dump())], "$",
                 id="entity-subclass"),
))
def test_t11_n17_wrong_shape_is_refused(build, path):
    _replay_refused(build(_entity()), E_REPLAY_SHAPE, path)


def _without_attribute(entity, name):
    edited = copy.deepcopy(entity)
    vars(edited).pop(name)
    return edited


# Instances that bypassed validation (model_copy(update=...), model_construct): refused as shape
# before any attribute is read, never an AttributeError.
@pytest.mark.parametrize("build,path", (
    pytest.param(lambda e: e.model_copy(update={"source": None}), "[0].source",
                 id="source-none"),
    pytest.param(lambda e: e.model_copy(update={"source": e.source.model_dump()}), "[0].source",
                 id="source-dict"),
    pytest.param(lambda e: Entity.model_construct(
        **{k: v for k, v in vars(e).items() if k != "valid_from"}), "[0].valid_from",
                 id="no-valid-from"),
    pytest.param(lambda e: e.model_copy(update={"source": SourceRef.model_construct(
        **{k: v for k, v in vars(e.source).items() if k != "system"})}), "[0].source",
                 id="source-no-system"),
    pytest.param(lambda e: e.model_copy(update={"residual": Residual.model_construct(
        data=e.residual.data)}), "[0].residual", id="residual-no-namespace"),
    pytest.param(lambda e: _without_attribute(e, "residual"), "[0].residual",
                 id="no-residual-attribute"),
))
def test_t11_n17_unvalidated_entity_is_refused(build, path):
    adapter = _adapter()
    for call in (adapter.from_cdm, adapter.encode):
        with pytest.raises(Exception) as raised:
            call([build(_entity())])
        error = raised.value
        assert type(error) is Dis7Error
        assert (error.code, error.path) == (E_REPLAY_SHAPE, path)


def _data_edit(edit):
    return lambda entity: edit(entity.residual.data)


def _drop(name):
    return _data_edit(lambda data: data.pop(name))


_RESIDUAL_KEYS = ("pdu", "wire_hex", "time_context", "session", "synthetic", "source_hash")
_SHAPE_ROWS = (
    ("namespace", lambda entity: setattr(entity.residual, "namespace", "DIS7"), "[0].residual"),
    ("extra", _data_edit(_stored("extra", 1)), "[0].residual.data"),
    *((f"no-{key}", _drop(key), f"[0].residual.data.{key}") for key in _RESIDUAL_KEYS),
    ("pdu-extra", _data_edit(lambda data: data["pdu"].__setitem__("extra", 1)),
     "[0].residual.data.pdu"),
    ("header-extra", _data_edit(lambda data: data["pdu"]["header"].__setitem__("extra", 1)),
     "[0].residual.data.pdu.header"),
    ("time-context-extra", _data_edit(_stored_time("extra", 1)), "[0].residual.data.time_context"),
    ("no-force-id", _data_edit(lambda data: data["pdu"].pop("force_id")),
     "[0].residual.data.pdu.force_id"),
    ("force-id-true", _data_edit(lambda data: data["pdu"].__setitem__("force_id", True)),
     "[0].residual.data.pdu.force_id"),
    ("session-int", _data_edit(_stored("session", 5)), "[0].residual.data.session"),
    ("session-space", _data_edit(_stored("session", "a b")), "[0].residual.data.session"),
    ("synthetic-int", _data_edit(_stored("synthetic", 1)), "[0].residual.data.synthetic"),
    ("instant-space", _data_edit(_stored_time("instant", "2026-04-29 06:15:00Z")),
     "[0].residual.data.time_context.instant"),
    ("basis-empty", _data_edit(_stored_time("basis", "")), "[0].residual.data.time_context.basis"),
    ("basis-long", _data_edit(_stored_time("basis", "x" * 1025)),
     "[0].residual.data.time_context.basis"),
    ("basis-white-space", _data_edit(_stored_time("basis", " \t ")),
     "[0].residual.data.time_context.basis"),
    ("wire-upper", _data_edit(lambda data: data.__setitem__("wire_hex", data["wire_hex"].upper())),
     "[0].residual.data.wire_hex"),
    ("wire-short", _data_edit(lambda data: data.__setitem__("wire_hex", data["wire_hex"][:286])),
     "[0].residual.data.wire_hex"),
)


# CR-25, CR-26
@pytest.mark.parametrize("edit,path", [
    pytest.param(edit, path, id=label) for label, edit, path in _SHAPE_ROWS])
def test_t11_residual_shape_defect_is_refused(edit, path):
    entity = _entity()
    edit(entity)
    _replay_refused([entity], E_REPLAY_SHAPE, path)


@pytest.mark.parametrize("kind", ("self-loop", "deep-list", "header-loop", "velocity-ring"))
def test_t11_cyclic_or_very_deep_residual_is_refused(kind):
    entity = _entity()
    data = entity.residual.data
    installed = None
    if kind == "self-loop":
        installed, key, path = data, "loop", "[0].residual.data"
        data["loop"] = data
    elif kind == "deep-list":
        installed = []
        for _ in range(99999):
            installed = [installed]
        key, path = "deep", "[0].residual.data"
        data["deep"] = installed
    elif kind == "header-loop":
        path = "[0].residual.data.pdu.header"
        data["pdu"]["header"]["loop"] = data["pdu"]
    else:
        ring = [0.0, 25.0, 0.0]
        ring[0] = ring
        data["pdu"]["velocity_mps"] = ring
        path = "[0].residual.data.pdu.velocity_mps[0]"
    err = _replay_refused([entity], E_REPLAY_SHAPE, path)
    assert type(err) is Dis7Error
    if installed is not None:
        still_there = entity.residual.data[key] is installed
        assert still_there, "the installed object was replaced"


# CR-15
@pytest.mark.parametrize("edit,path", (
    pytest.param(lambda entity: _set_wire(entity, 18, bytes.fromhex("02")),
                 "[0].residual.data.pdu.force_id", id="wire-force-id"),
    pytest.param(_data_edit(lambda data: data["pdu"].__setitem__("force_id", 2)),
                 "[0].residual.data.pdu.force_id", id="view-force-id"),
    pytest.param(lambda entity: _set_wire(entity, 0, bytes.fromhex("06")),
                 "[0].residual.data.wire_hex", id="wire-version"),
    pytest.param(lambda entity: _set_wire(entity, 19, bytes.fromhex("01")),
                 "[0].residual.data.wire_hex", id="wire-record-count"),
    pytest.param(lambda entity: _set_wire(entity, 36, bytes.fromhex("7fc00000")),
                 "[0].residual.data.wire_hex", id="wire-nan"),
))
def test_t11_single_view_edit_is_refused(edit, path):
    entity = _entity()
    edit(entity)
    _replay_refused([entity], E_REPLAY_CHANGED, path)


def _view_exercise(pdu):
    pdu["header"]["exercise_id"] = 43


def _view_entity_id(pdu):
    pdu["entity_id"] = [7, 11, 2]


def _view_dead_reckoning(pdu):
    pdu["dead_reckoning_hex"] = "01" + pdu["dead_reckoning_hex"][2:]


# CR-22
@pytest.mark.parametrize("offset,octet,view,path", (
    pytest.param(1, "2b", _view_exercise, "[0].source_ids", id="octet-1"),
    pytest.param(17, "02", _view_entity_id, "[0].source.original_id", id="octet-17"),
    pytest.param(88, "01", _view_dead_reckoning, "[0].source.transformations", id="octet-88"),
))
def test_t11_consistent_wire_and_view_edit_is_provenance(offset, octet, view, path):
    entity = _entity()
    _set_wire(entity, offset, bytes.fromhex(octet))
    view(entity.residual.data["pdu"])
    _replay_refused([entity], E_REPLAY_PROVENANCE, path)


def test_t11_consistent_rewrite_to_position_1_1_1_is_changed():
    entity = _entity()
    _set_wire(entity, 48, struct.pack(">ddd", 1.0, 1.0, 1.0))
    entity.residual.data["pdu"]["position_ecef_m"] = [1.0, 1.0, 1.0]
    _replay_refused([entity], E_REPLAY_CHANGED, "[0].residual.data.wire_hex")


@pytest.mark.parametrize("case", ("reversed-members", "negative-zero", "pole-positive-zero"))
def test_t11_member_order_and_signed_zero_in_the_stored_view(case):
    stem = POLE if case == "pole-positive-zero" else SEED
    entity = _entity(stem)
    if case == "reversed-members":
        entity.residual.data = _reversed_members(entity.residual.data)
    elif case == "negative-zero":
        entity.residual.data["pdu"]["velocity_mps"] = [-0.0, 25.0, -0.0]
    else:
        entity.residual.data["pdu"]["velocity_mps"][1] = 0.0
    out = _adapter().from_cdm([entity])
    assert out == dis7_support.vector_bytes(stem)
    if stem == POLE:
        assert out[40:44] == bytes.fromhex("80000000")


def _both(*edits):
    def edit(entity):
        for one in edits:
            one(entity)
    return edit


def _NAMESPACE(entity):
    entity.residual.namespace = "DIS7"


def _LATER_START(entity):
    entity.valid_from = entity.valid_from + SECOND


_SESSION = _data_edit(_stored("session", "another-run"))
_ADAPTER_VERSION = _set_in("source", "adapter_version", "0.1.0")
_FORCE = _data_edit(lambda data: data["pdu"].__setitem__("force_id", 2))
_NOT_SYNTHETIC = _set_in("source", "synthetic", False)
_FRIENDLY = _set("affiliation", Affiliation.FRIENDLY)


def _EXTERNAL(entity):
    entity.source_ids[0].external_id = "7:11:2"


_OTHER_ID = _set("entity_id", OTHER_ID)


# CR-22
@pytest.mark.parametrize("edit,code,path", (
    pytest.param(_both(_NAMESPACE, _LATER_START), E_REPLAY_SHAPE, "[0].residual",
                 id="shape-before-changed"),
    pytest.param(_both(_SESSION, _ADAPTER_VERSION), E_REPLAY_PROVENANCE,
                 "[0].residual.data.session", id="stored-before-source"),
    pytest.param(_both(_SESSION, _FORCE), E_REPLAY_PROVENANCE, "[0].residual.data.session",
                 id="stored-before-consistency"),
    pytest.param(_both(_FORCE, _NOT_SYNTHETIC), E_REPLAY_CHANGED,
                 "[0].residual.data.pdu.force_id", id="consistency-before-source"),
    pytest.param(_both(_NOT_SYNTHETIC, _FRIENDLY), E_REPLAY_PROVENANCE, "[0].source.synthetic",
                 id="source-before-canonical"),
    pytest.param(_both(_EXTERNAL, _OTHER_ID), E_REPLAY_PROVENANCE, "[0].source_ids",
                 id="source-ids-before-canonical"),
    pytest.param(_both(_ADAPTER_VERSION, _EXTERNAL), E_REPLAY_PROVENANCE,
                 "[0].source.adapter_version", id="source-before-source-ids"),
))
def test_t11_check_order_with_two_defects(edit, code, path):
    entity = _entity()
    edit(entity)
    _replay_refused([entity], code, path)


def test_t11_argument_is_unchanged():
    entity = _entity()
    objects = [entity]
    before = copy.deepcopy(entity)
    assert _adapter().from_cdm(objects) == dis7_support.seed()
    assert objects[0] is entity
    assert entity == before
    assert entity.model_dump() == before.model_dump()
    entity.affiliation = Affiliation.FRIENDLY
    data = entity.residual.data
    data["pdu"] = _reversed_members(data["pdu"])
    order = list(data["pdu"])
    before = copy.deepcopy(entity)
    _replay_refused(objects, E_REPLAY_CHANGED, "[0].affiliation")
    assert objects[0] is entity
    assert entity == before
    assert entity.model_dump() == before.model_dump()
    assert list(entity.residual.data["pdu"]) == order


# ----------------------------------------------------------------------------------------------
# T12 — envelope structure through `to_cdm(dict)`.

FOREIGN = "zz_foreign_member"


@pytest.mark.parametrize("path", ("$", "pdu", "pdu.header", "time_context"))
def test_t12_n18_unknown_key_at_each_level(path):
    envelope = _envelope()
    target = envelope
    for step in () if path == "$" else path.split("."):
        target = target[step]
    target[FOREIGN] = 1
    err = _refused(envelope, E_TWIN_SCHEMA, path)
    assert FOREIGN not in str(err)


def _required_paths():
    schema = json.loads((dis7_support.CONTRACT / "dis7-envelope.schema.json").read_text())
    pdu = schema["properties"]["pdu"]
    return (tuple(schema["required"])
            + tuple(f"pdu.{name}" for name in pdu["required"])
            + tuple(f"pdu.header.{name}" for name in pdu["properties"]["header"]["required"])
            + tuple(f"time_context.{name}"
                    for name in schema["properties"]["time_context"]["required"]))


REQUIRED_PATHS = _required_paths()


def test_t12_n18_the_schema_requires_twenty_six_keys():
    assert len(REQUIRED_PATHS) == 26 == 3 + 13 + 8 + 2
    assert len(set(REQUIRED_PATHS)) == 26
    assert {"wire_hex", "pdu.force_id", "pdu.header.length", "time_context.basis"} <= set(
        REQUIRED_PATHS)


# CR-03
@pytest.mark.parametrize("path", REQUIRED_PATHS)
def test_t12_n18_each_required_key_omitted(path):
    _refused(_without(_envelope(), path), E_TWIN_SCHEMA, path)


_ARRAY_FILL = {"entity_id": 0, "entity_type": 0, "alternative_entity_type": 0,
               "velocity_mps": 0.0, "position_ecef_m": 0.0, "orientation_radians": 0.0}


def _width_rows():
    for name, fill in _ARRAY_FILL.items():
        yield (f"{name}-short", SEED, lambda pdu, n=name: pdu[n].pop(), f"pdu.{name}")
        yield (f"{name}-long", SEED, lambda pdu, n=name, f=fill: pdu[n].append(f), f"pdu.{name}")
    for name in ("dead_reckoning_hex", "marking_hex"):
        for count in (1, 2):
            yield (f"{name}-minus-{count}", SEED,
                   lambda pdu, n=name, c=count: pdu.__setitem__(n, pdu[n][:-c]), f"pdu.{name}")
            yield (f"{name}-plus-{count}", SEED,
                   lambda pdu, n=name, c=count: pdu.__setitem__(n, pdu[n] + "0" * c),
                   f"pdu.{name}")
    yield ("records-256", SEED,
           lambda pdu: pdu.__setitem__("variable_parameters_hex", ["00" * 16] * 256),
           "pdu.variable_parameters_hex")
    yield ("velocity-10000", SEED, lambda pdu: pdu.__setitem__("velocity_mps", [0.0] * 10000),
           "pdu.velocity_mps")
    yield ("record-minus-1", EXT, lambda pdu: pdu["variable_parameters_hex"].__setitem__(
        0, pdu["variable_parameters_hex"][0][:-1]), "pdu.variable_parameters_hex[0]")
    yield ("record-plus-1", EXT, lambda pdu: pdu["variable_parameters_hex"].__setitem__(
        0, pdu["variable_parameters_hex"][0] + "0"), "pdu.variable_parameters_hex[0]")


@pytest.mark.parametrize("stem,edit,path", [
    pytest.param(stem, edit, path, id=label) for label, stem, edit, path in _width_rows()])
def test_t12_n18_width_one_short_or_one_long(stem, edit, path):
    envelope = _envelope(stem)
    edit(envelope["pdu"])
    _refused(envelope, E_TWIN_SCHEMA, path)


_WRONG_TYPE_ROWS = (
    ("pdu-list", "pdu", [], "pdu"),
    ("header-list", "pdu.header", [], "pdu.header"),
    ("entity-id-str", "pdu.entity_id", "7:11:1", "pdu.entity_id"),
    ("entity-id-item-str", "pdu.entity_id[0]", "7", "pdu.entity_id[0]"),
    ("force-id-str", "pdu.force_id", "1", "pdu.force_id"),
    ("force-id-none", "pdu.force_id", None, "pdu.force_id"),
    ("force-id-fraction", "pdu.force_id", 1.5, "pdu.force_id"),
    ("force-id-true", "pdu.force_id", True, "pdu.force_id"),
    ("velocity-str", "pdu.velocity_mps[1]", "25.0", "pdu.velocity_mps[1]"),
    ("velocity-none", "pdu.velocity_mps[1]", None, "pdu.velocity_mps[1]"),
    ("position-object", "pdu.position_ecef_m", {"x": 1.0}, "pdu.position_ecef_m"),
    ("dead-reckoning-int", "pdu.dead_reckoning_hex", 2, "pdu.dead_reckoning_hex"),
    ("marking-bytes", "pdu.marking_hex", b"0145584552434953452d3031", "pdu.marking_hex"),
    ("records-str", "pdu.variable_parameters_hex", "", "pdu.variable_parameters_hex"),
    ("records-int-item", "pdu.variable_parameters_hex", [5], "pdu.variable_parameters_hex[0]"),
    ("wire-int", "wire_hex", 5, "wire_hex"),
    ("wire-bytes", "wire_hex", b"07", "wire_hex"),
    ("time-context-str", "time_context", "2026-04-29T06:15:00.000Z", "time_context"),
    ("instant-int", "time_context.instant", 5, "time_context.instant"),
    ("basis-none", "time_context.basis", None, "time_context.basis"),
    ("padding-false", "pdu.header.padding", False, "pdu.header.padding"),
    ("entity-id-true", "pdu.entity_id[2]", True, "pdu.entity_id[2]"),
    ("entity-type-true", "pdu.entity_type[0]", True, "pdu.entity_type[0]"),
    ("velocity-false", "pdu.velocity_mps[0]", False, "pdu.velocity_mps[0]"),
    ("position-false", "pdu.position_ecef_m[1]", False, "pdu.position_ecef_m[1]"),
)


# CR-06, CR-29
@pytest.mark.parametrize("member,value,path", [
    pytest.param(member, value, path, id=label) for label, member, value, path in _WRONG_TYPE_ROWS])
def test_t12_n18_wrong_type_or_boolean(member, value, path):
    _refused(_with(_envelope(), member, value), E_TWIN_SCHEMA, path)


_RANGE_ROWS = (
    ("protocol-version", "pdu.header.protocol_version", 6),
    ("pdu-type", "pdu.header.pdu_type", 2),
    ("protocol-family", "pdu.header.protocol_family", 2),
    ("exercise-high", "pdu.header.exercise_id", 256),
    ("exercise-negative", "pdu.header.exercise_id", -1),
    ("timestamp-high", "pdu.header.timestamp", 4294967296),
    ("length-low", "pdu.header.length", 143),
    ("length-high", "pdu.header.length", 4225),
    ("status-high", "pdu.header.status", 256),
    ("entity-id-high", "pdu.entity_id[0]", 65536),
    ("force-id-high", "pdu.force_id", 256),
    ("force-id-negative", "pdu.force_id", -1),
    ("kind-high", "pdu.entity_type[0]", 256),
    ("country-high", "pdu.entity_type[2]", 65536),
    ("alternative-extra-high", "pdu.alternative_entity_type[6]", 256),
    ("appearance-high", "pdu.appearance", 4294967296),
    ("capabilities-negative", "pdu.capabilities", -1),
    ("velocity-nan", "pdu.velocity_mps[0]", math.nan),
    ("position-inf", "pdu.position_ecef_m[2]", math.inf),
    ("orientation-minus-inf", "pdu.orientation_radians[1]", -math.inf),
)


# CR-05
@pytest.mark.parametrize("member,value", [
    pytest.param(member, value, id=label) for label, member, value in _RANGE_ROWS])
def test_t12_n18_range_constant_and_non_finite(member, value):
    _refused(_with(_envelope(), member, value), E_TWIN_SCHEMA, member)


def _rewrite(member, change):
    def edit(envelope):
        container, key = _locate(envelope, member)
        container[key] = change(container[key])
    return edit


_HEX_ROWS = (
    ("marking-upper", _rewrite("pdu.marking_hex", str.upper), "pdu.marking_hex"),
    ("marking-0x", _rewrite("pdu.marking_hex", lambda text: "0x" + text[2:]), "pdu.marking_hex"),
    ("dead-reckoning-space", _rewrite("pdu.dead_reckoning_hex", lambda text: " " + text[1:]),
     "pdu.dead_reckoning_hex"),
    ("dead-reckoning-newline", _rewrite("pdu.dead_reckoning_hex", lambda text: text + "\n"),
     "pdu.dead_reckoning_hex"),
    ("wire-upper", _rewrite("wire_hex", str.upper), "wire_hex"),
    ("wire-odd", _rewrite("wire_hex", lambda text: text + "0"), "wire_hex"),
    ("wire-newline", _rewrite("wire_hex", lambda text: text + "\n"), "wire_hex"),
    ("wire-g", _rewrite("wire_hex", lambda text: "g" + text[1:]), "wire_hex"),
    ("wire-286", _rewrite("wire_hex", lambda text: text[:286]), "wire_hex"),
    ("wire-8450", _rewrite("wire_hex", lambda text: "00" * 4225), "wire_hex"),
    ("wire-empty", _rewrite("wire_hex", lambda text: ""), "wire_hex"),
)


# CR-05
@pytest.mark.parametrize("edit,path", [
    pytest.param(edit, path, id=label) for label, edit, path in _HEX_ROWS])
def test_t12_n18_hex_syntax_and_wire_hex_length(edit, path):
    envelope = _envelope()
    edit(envelope)
    _refused(envelope, E_TWIN_SCHEMA, path)


def _prototype_envelope():
    envelope = _envelope()
    return {"pdu": envelope["pdu"], "time_context": envelope["time_context"]}


@pytest.mark.parametrize("build,path", (
    pytest.param(lambda: _with(_envelope(), "session", "unnamed"), "$", id="session"),
    pytest.param(lambda: _with(_envelope(), "synthetic", True), "$", id="synthetic"),
    pytest.param(lambda: _with(_envelope(), "source_hash", None), "$", id="source-hash"),
    pytest.param(lambda: copy.deepcopy(_entity().residual.data), "$", id="residual-object"),
    pytest.param(_prototype_envelope, "wire_hex", id="prototype"),
    pytest.param(dict, "pdu", id="empty"),
))
def test_t12_n18_foreign_envelope_shapes(build, path):
    _refused(build(), E_TWIN_SCHEMA, path)


def _floats(node):
    if isinstance(node, dict):
        return {key: _floats(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_floats(value) for value in node]
    return float(node) if type(node) is int else node


def _tuples(node):
    if isinstance(node, dict):
        return {key: _tuples(value) for key, value in node.items()}
    if isinstance(node, list):
        return tuple(_tuples(value) for value in node)
    return node


def _integer_components(pdu):
    pdu["velocity_mps"] = [0, 25, 0]
    pdu["position_ecef_m"] = [6378257, 0, 0]
    return pdu


# CR-06, CR-29
@pytest.mark.parametrize("change", (
    pytest.param(_floats, id="integral-floats"),
    pytest.param(_integer_components, id="integer-components"),
    pytest.param(_tuples, id="tuples"),
))
def test_t12_n18_integral_floats_and_integer_components_are_accepted(change):
    envelope = _envelope()
    envelope["pdu"] = change(envelope["pdu"])
    adapter = _adapter()
    objects = adapter.to_cdm(envelope)
    assert len(objects) == 1
    assert objects[0].entity_id == SEED_ID
    assert adapter.from_cdm(objects) == dis7_support.seed()


def _bump(member, delta):
    return _rewrite(member, lambda value: value + delta)


def _twin_rows():
    for name, value in (("exercise_id", 43), ("timestamp", 1073741826), ("length", 160),
                        ("status", 1), ("padding", 1)):
        member = f"pdu.header.{name}"
        yield (f"header-{name}", SEED, lambda e, m=member, v=value: _with(e, m, v), member)
    for name, size, delta in (("entity_id", 3, 1), ("entity_type", 7, 1),
                              ("alternative_entity_type", 7, 1), ("velocity_mps", 3, 1.0),
                              ("position_ecef_m", 3, 1.0), ("orientation_radians", 3, 0.5)):
        for index in range(size):
            member = f"pdu.{name}[{index}]"
            yield (f"{name}-{index}", SEED, _bump(member, delta), member)
    yield ("force_id", SEED, lambda e: _with(e, "pdu.force_id", 2), "pdu.force_id")
    yield ("appearance", SEED, _bump("pdu.appearance", 1), "pdu.appearance")
    yield ("capabilities", SEED, _bump("pdu.capabilities", -1), "pdu.capabilities")
    for name in ("dead_reckoning_hex", "marking_hex"):
        yield (name, SEED, _rewrite(f"pdu.{name}", _other_digit), f"pdu.{name}")
    yield ("record-digit", EXT, _rewrite("pdu.variable_parameters_hex[0]", _other_digit),
           "pdu.variable_parameters_hex[0]")
    yield ("records-dropped", EXT, lambda e: _with(e, "pdu.variable_parameters_hex", []),
           "pdu.variable_parameters_hex")
    yield ("records-added", SEED, lambda e: _with(e, "pdu.variable_parameters_hex", ["00" * 16]),
           "pdu.variable_parameters_hex")


_TWIN_ROWS = tuple(_twin_rows())


@pytest.mark.parametrize("stem,edit,path", [
    pytest.param(stem, edit, path, id=label) for label, stem, edit, path in _TWIN_ROWS])
def test_t12_n19_twin_field_disagrees_with_the_wire(stem, edit, path):
    envelope = _envelope(stem)
    wire = envelope["wire_hex"]
    edit(envelope)
    assert envelope["wire_hex"] == wire
    _refused(envelope, E_TWIN_WIRE_MISMATCH, path)


def test_t12_n19_table_covers_every_twin_member():
    schema = json.loads((dis7_support.CONTRACT / "dis7-envelope.schema.json").read_text())
    pdu = schema["properties"]["pdu"]
    pdu_members, header_members = set(), set()
    for _, _, _, path in _TWIN_ROWS:
        parts = path.split(".")
        if parts[1] == "header":
            header_members.add(parts[2])
        else:
            pdu_members.add(parts[1].partition("[")[0])
    assert pdu_members == set(pdu["required"]) - {"header"}
    assert header_members == set(pdu["properties"]["header"]["required"]) - {
        "protocol_version", "pdu_type", "protocol_family"}


@pytest.mark.parametrize("stem,index,value", (
    pytest.param(SEED, 0, -0.0, id="seed-negative-zero"),
    pytest.param(POLE, 1, 0.0, id="pole-positive-zero"),
))
def test_t12_n19_signed_zero_is_not_a_mismatch(stem, index, value):
    envelope = _envelope(stem)
    envelope["pdu"]["velocity_mps"][index] = value
    adapter = _adapter()
    objects = adapter.to_cdm(envelope)
    out = adapter.from_cdm(objects)
    assert out == dis7_support.vector_bytes(stem)
    if stem == POLE:
        assert out[40:44] == bytes.fromhex("80000000")


def _foreign_in_pdu(envelope):
    envelope["pdu"][FOREIGN] = 1


def _two(*edits):
    def edit(envelope):
        for one in edits:
            one(envelope)
    return edit


@pytest.mark.parametrize("edit,code,path", (
    pytest.param(_foreign_in_pdu, E_TWIN_SCHEMA, "pdu", id="foreign-key"),
    pytest.param(_two(lambda e: _without(e, "pdu.appearance"), lambda e: _without(
        e, "pdu.force_id")), E_TWIN_SCHEMA, "pdu.force_id", id="two-missing"),
    pytest.param(_two(lambda e: _with(e, "pdu.capabilities", 1), lambda e: _with(
        e, "pdu.force_id", 2)), E_TWIN_WIRE_MISMATCH, "pdu.force_id", id="two-mismatches"),
    pytest.param(_two(lambda e: _with(e, "pdu.header.status", 256), lambda e: _with(
        e, "pdu.force_id", 256)), E_TWIN_SCHEMA, "pdu.header.status", id="two-ranges"),
))
def test_t12_member_order_does_not_change_the_diagnostic(edit, code, path):
    adapter = _adapter()
    assert adapter.to_cdm(_reversed_members(_envelope()))[0] == adapter.to_cdm(_envelope())[0]
    envelope = _envelope()
    edit(envelope)
    _refused(envelope, code, path)
    _refused(_reversed_members(envelope), code, path)


@pytest.mark.parametrize("edit,code,path", (
    pytest.param(_two(_foreign_in_pdu, _rewrite("wire_hex", lambda text: "06" + text[2:])),
                 E_TWIN_SCHEMA, "pdu", id="structure-before-header"),
    pytest.param(_two(lambda e: _with(e, "pdu.force_id", 2),
                      lambda e: _with(e, "time_context.instant", "2026-02-30T00:00:00Z")),
                 E_TWIN_WIRE_MISMATCH, "pdu.force_id", id="twin-before-time"),
))
def test_t12_structure_is_refused_before_the_wire_is_read(edit, code, path):
    envelope = _envelope()
    edit(envelope)
    _refused(envelope, code, path)


# ----------------------------------------------------------------------------------------------
# T03 — native N20 through `to_cdm(dict)`. The envelope is level 1, `pdu` level 2 and
# `velocity_mps` level 3.

KINDS = ("dict", "list", "tuple", "mixed")


@pytest.mark.parametrize("kind", KINDS)
def test_t03_n20_seventeen_native_levels_are_refused(kind):
    envelope = _envelope()
    envelope["pdu"]["velocity_mps"][0] = _chain(14, kind)
    assert _depth(envelope) == 17
    _too_deep(envelope)
    alone = _chain(17, "dict")
    assert _depth(alone) == 17
    _too_deep(alone)


@pytest.mark.parametrize("kind", KINDS)
def test_t03_n20_sixteen_native_levels_pass_the_guard(kind):
    envelope = _envelope()
    envelope["pdu"]["velocity_mps"][0] = _chain(13, kind)
    assert _depth(envelope) == 16
    _within(10, lambda: _refused(envelope, E_TWIN_SCHEMA, "pdu.velocity_mps[0]"))


def _cycle_through_envelope(envelope):
    envelope["pdu"]["velocity_mps"][0] = envelope


def _cycle_through_ring(envelope):
    ring = [0.0, 25.0, 0.0]
    ring[0] = ring
    envelope["pdu"]["velocity_mps"] = ring


def _cycle_through_dict(envelope):
    ring = {}
    ring["a"] = ring
    envelope["pdu"]["velocity_mps"][0] = ring


def _cycle_through_tuple(envelope):
    holder = []
    holder.append((holder,))
    envelope["pdu"]["velocity_mps"][0] = holder


@pytest.mark.parametrize("make", (
    pytest.param(_cycle_through_envelope, id="envelope"),
    pytest.param(_cycle_through_ring, id="list"),
    pytest.param(_cycle_through_dict, id="dict"),
    pytest.param(_cycle_through_tuple, id="tuple"),
))
def test_t03_n20_native_cycle_is_refused(make):
    envelope = _envelope()
    make(envelope)
    _too_deep(envelope)


def _fan_out(levels):
    node = 0.0
    for _ in range(levels):
        node = [node] * 16
    return node


def test_t03_n20_shared_references_are_accepted():
    patched = dis7_support.patch(dis7_support.seed(), 20, bytes(8))
    envelope = _envelope()
    shared = [0] * 7
    envelope["pdu"]["entity_type"] = shared
    envelope["pdu"]["alternative_entity_type"] = shared
    envelope["wire_hex"] = patched.hex()
    adapter = _adapter()
    objects = _within(10, lambda: adapter.to_cdm(envelope))
    assert len(objects) == 1
    assert adapter.from_cdm(objects) == patched
    fan = _envelope()
    fan["pdu"]["velocity_mps"][0] = _fan_out(13)
    _within(10, lambda: _refused(fan, E_TWIN_SCHEMA, "pdu.velocity_mps[0]"))
    deeper = _envelope()
    deeper["pdu"]["velocity_mps"][0] = _fan_out(14)
    _too_deep(deeper)


@pytest.mark.parametrize("order", ("shallow-first", "deep-first"))
def test_t03_n20_shared_container_is_measured_at_its_deepest_use(order):
    for levels, depth in ((10, 17), (9, 16)):
        shared = [[[0.0]]]
        deep = _chain(levels, "list", shared)
        envelope = _envelope()
        envelope["pdu"]["velocity_mps"][0] = [shared, deep] if order == "shallow-first" \
            else [deep, shared]
        assert _depth(envelope) == depth
        if depth == 17:
            _too_deep(envelope)
        else:
            _within(10, lambda env=envelope: _refused(env, E_TWIN_SCHEMA, "pdu.velocity_mps[0]"))
