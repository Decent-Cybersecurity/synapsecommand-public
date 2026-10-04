"""Pins and validates the vendored DIS 7 contract under `fixtures/dis7/`.

The bundle this contract was vendored from is a handoff document set identified by
`SC DIS7 SPEC 001 v1.0` and is not in this repository. This module reads one repository file
beyond the vendored tree, the published `schemas/entity.schema.json`, and nothing else.
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

import jsonschema
import pytest

from synapse_cdm import harness, schemas

from tests import dis7_support

REPO = pathlib.Path(__file__).resolve().parents[1]
ENTITY_SCHEMA = REPO / "schemas" / "entity.schema.json"

SCHEMA_NAMES = ("dis7-context", "dis7-entity", "dis7-envelope", "dis7-pdu", "dis7-residual")

# Copied from /Users/admin/Documents/cc/dis7-run/bundle/MANIFEST.json, never computed from the
# vendored files.
BUNDLE_MANIFEST = {
    "vectors/equator_eastbound.context.json": ("e0bbd2dae2e53a1b94227a1aff32e88a3ba3df4efee1be651b231c6da83b3271", 207),
    "vectors/equator_eastbound.dis": ("c958233bda22e82385788584e0297d0e264ee2a0db94dc32838141925155ef1a", 144),
    "vectors/equator_eastbound.envelope.json": ("9d2285c1795c0808afa29f69e54901970eb532276e2adefb6e58c3c8bdccf3a7", 1397),
    "vectors/equator_eastbound.expected.json": ("549c77275db756242dc7267890d365f6124e983a3b8efe73d44b17e906face37", 3430),
    "vectors/equator_eastbound.hex": ("fde02e45bee86726f8c64152ff10d77528566a785c8533a1ee9f26f081d32aa1", 289),
    "vectors/index.json": ("5a56eb57f9728e6790dfa58855392808c8cbe05d61ae59cc482b200b8ac9a53b", 1586),
    "vectors/north_pole_stationary.context.json": ("e0bbd2dae2e53a1b94227a1aff32e88a3ba3df4efee1be651b231c6da83b3271", 207),
    "vectors/north_pole_stationary.dis": ("e7354d35aab73b5e372c13dbf9c946ed57a53dadb1e11f3b218eadf402f00fc7", 144),
    "vectors/north_pole_stationary.envelope.json": ("3a74e3680be175c47e824b9db0832748ad43450df4edb17e0968742e2410f9be", 1405),
    "vectors/north_pole_stationary.expected.json": ("365ade90961e3267edb95b0ddcbf11ea047d6bd692f3ca93f55794e76b02c3c1", 3437),
    "vectors/north_pole_stationary.hex": ("ea84c9a7860b1266b2a2d99396593ad3890d5009a073806732d5d36b54ef9d6b", 289),
    "vectors/unprojectable_with_extensions.context.json": ("e0bbd2dae2e53a1b94227a1aff32e88a3ba3df4efee1be651b231c6da83b3271", 207),
    "vectors/unprojectable_with_extensions.dis": ("4397c9e4f90188a7eee7ceba7abad8a0a5c2c65c3108a3110e5157539507912d", 160),
    "vectors/unprojectable_with_extensions.envelope.json": ("f2bd85fbe7343cc8e74ee8ad9c2bfcec68f37839045262ba7ffddfa2a7cdbb3e", 1468),
    "vectors/unprojectable_with_extensions.expected.json": ("db37974223d8e425ae3f2dac38a58087cae76a72c396f2f1515095eb0e4d3eab", 3251),
    "vectors/unprojectable_with_extensions.hex": ("0f0b0c81868201dd7c01b8e3a5340fabde4a124a458c0fc3aba912bf65a855d2", 321),
    "contract/acceptance-cases.json": ("fc894f435ddb7c31fb8f22ecf001a50ebc668b8fc46b5df75305e35807d8881c", 13589),
    "contract/dis7-context.schema.json": ("1fd79b0128037d8c24fd7a508abe3c5b187671832194aff43d4e1df4dc3aa276", 1577),
    "contract/dis7-entity.schema.json": ("2df6487ef0e0354532c15c17adc2dc61d8fc59961e8deb985e871ff5852a2884", 48573),
    "contract/dis7-envelope.schema.json": ("c8deaf4aa54207207e61cb209c8e079b7eb936a040ecbe383dae99326450d0be", 6769),
    "contract/dis7-pdu.schema.json": ("a560a471f64e9b86deff44ef1ffc50cfe1114358f796ba877c93ea719fade71b", 4953),
    "contract/dis7-residual.schema.json": ("345f0ee5c5a0b68373b4281bdf8cb87eb89c3c0c5b974189ca13d9d4e7bae850", 7580),
}
CDM_ENTITY_SHA256 = "310d04623b4647e0f92abd384a48683df783495ec9e1ffd1bedf85ee18bf092a"


def _schema(name: str) -> dict:
    return json.loads((dis7_support.CONTRACT / f"{name}.schema.json").read_text())


def _errors(schema: dict, instance) -> list[str]:
    return sorted(e.message for e in schemas.validator_for(schema).iter_errors(instance))


def _pin() -> dict:
    return json.loads((dis7_support.FIXTURES / "spec" / "dis7_pin.json").read_text())


def _walk_no_local_path(node) -> None:
    pending = [node]
    while pending:
        current = pending.pop()
        if isinstance(current, dict):
            assert "local_path" not in current, (
                "a node pairing local_path with sha256 is what gates/pin_paths.py reads as a pin"
            )
            pending.extend(current.values())
        elif isinstance(current, list):
            pending.extend(current)


def test_pin_record_lists_exactly_the_vendored_files():
    vector_names = {f"vectors/{p.name}" for p in harness.select_fixtures(dis7_support.VECTORS)}
    contract_names = {f"contract/{p.name}" for p in harness.select_fixtures(dis7_support.CONTRACT)}
    found = vector_names | contract_names
    assert len(found) == 22
    pin = _pin()
    pinned = ({row["file"] for row in pin["vectors"]["files"]}
              | {row["file"] for row in pin["contract"]["files"]})
    assert found == pinned
    assert found == set(BUNDLE_MANIFEST)


@pytest.mark.parametrize("file", sorted(BUNDLE_MANIFEST))
def test_pin_every_vendored_file_matches_the_record_and_the_bundle_manifest(file):
    data = (dis7_support.FIXTURES / file).read_bytes()
    measured = (hashlib.sha256(data).hexdigest(), len(data))
    assert measured == BUNDLE_MANIFEST[file]
    pin = _pin()
    rows = {row["file"]: (row["sha256"], row["bytes"])
            for row in pin["vectors"]["files"] + pin["contract"]["files"]}
    assert rows[file] == BUNDLE_MANIFEST[file]


def test_pin_cdm_entity_schema_is_the_published_entity_schema():
    digest = hashlib.sha256(ENTITY_SCHEMA.read_bytes()).hexdigest()
    assert digest == CDM_ENTITY_SHA256
    pin = _pin()
    assert pin["cdm_entity_schema"]["sha256"] == CDM_ENTITY_SHA256
    assert not (dis7_support.CONTRACT / "cdm-entity.schema.json").exists()


def test_pin_record_names_the_reference_implementation_and_pairs_no_local_path():
    pin = _pin()
    ref = pin["reference_implementation"]
    assert ref["name"] == "open-dis-python"
    assert ref["url"] == "https://github.com/open-dis/open-dis-python"
    assert ref["commit"] == "732b6655bb47e34ccc73722eefe0f4706fd0032f"
    assert ref["license"] == "BSD-2-Clause"
    _walk_no_local_path(pin)


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_schema_each_contract_schema_is_a_valid_2020_12_schema(name):
    schema = _schema(name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_vector_envelope_validates_against_the_envelope_schema(stem):
    envelope = dis7_support.vector_json(stem, "envelope")
    assert set(envelope) == {"pdu", "wire_hex", "time_context"}
    assert _errors(_schema("dis7-envelope"), envelope) == []


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_vector_envelope_pdu_validates_against_the_pdu_schema(stem):
    envelope = dis7_support.vector_json(stem, "envelope")
    assert _errors(_schema("dis7-pdu"), envelope["pdu"]) == []


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_vector_context_validates_against_the_context_schema(stem):
    context = dis7_support.vector_json(stem, "context")
    assert _errors(_schema("dis7-context"), context) == []
    assert context["session"] == "unnamed"
    assert context["synthetic"] is True
    assert context["source_hash"] is None
    assert context["time_context"]["instant"] == "2026-04-29T06:15:00.000Z"
    assert context["time_context"]["basis"] == "Synthetic fixture scenario instant; not capture time"


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_vector_expected_validates_against_the_profile_and_the_published_entity_schema(stem):
    expected = dis7_support.vector_json(stem, "expected")
    assert isinstance(expected, list)
    assert len(expected) == 1
    entity = expected[0]
    assert _errors(_schema("dis7-entity"), entity) == []
    published = json.loads(ENTITY_SCHEMA.read_text())
    assert _errors(published, entity) == []


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_vector_expected_residual_data_validates_against_the_residual_schema(stem):
    entity = dis7_support.vector_json(stem, "expected")[0]
    residual = entity["residual"]
    assert residual["namespace"] == "DIS"
    data = residual["data"]
    assert set(data) == {"pdu", "wire_hex", "time_context", "session", "synthetic", "source_hash"}
    assert _errors(_schema("dis7-residual"), data) == []


def test_vector_index_agrees_with_the_files():
    index = json.loads((dis7_support.VECTORS / "index.json").read_text())
    assert [row["id"] for row in index] == list(dis7_support.STEMS)
    expected_bytes = {"equator_eastbound": 144, "north_pole_stationary": 144,
                       "unprojectable_with_extensions": 160}
    for row in index:
        stem = row["id"]
        assert row["wire_file"] == f"vectors/{stem}.dis"
        assert row["envelope_file"] == f"vectors/{stem}.envelope.json"
        assert row["context_file"] == f"vectors/{stem}.context.json"
        assert row["expected_file"] == f"vectors/{stem}.expected.json"
        assert row["bytes"] == expected_bytes[stem]
        raw = dis7_support.vector_bytes(stem)
        assert row["bytes"] == len(raw)
        digest = hashlib.sha256(raw).hexdigest()
        assert row["sha256"] == digest
        assert BUNDLE_MANIFEST[f"vectors/{stem}.dis"] == (digest, len(raw))
        assert row["expected_status"] == "ACCEPT"
        assert row["replay"] == "byte_exact"
        hex_text = (dis7_support.VECTORS / f"{stem}.hex").read_text()
        assert hex_text == raw.hex() + "\n"
        envelope = dis7_support.vector_json(stem, "envelope")
        assert envelope["wire_hex"] == raw.hex()
        expected_entity = dis7_support.vector_json(stem, "expected")[0]
        assert expected_entity["residual"]["data"]["wire_hex"] == raw.hex()


def test_schema_validation_can_fail():
    envelope = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope"))
    envelope["unknown"] = True
    assert _errors(_schema("dis7-envelope"), envelope) != []

    bad_version = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope"))["pdu"]
    bad_version["header"]["protocol_version"] = 6
    assert _errors(_schema("dis7-pdu"), bad_version) != []

    no_force_id = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope"))["pdu"]
    del no_force_id["force_id"]
    errors = _errors(_schema("dis7-pdu"), no_force_id)
    assert errors
    assert any("force_id" in message for message in errors)

    entity = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "expected"))[0]
    entity["source"]["adapter_version"] = "0.1.0"
    assert _errors(_schema("dis7-entity"), entity) != []

    data = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "expected"))[0]["residual"]["data"]
    del data["wire_hex"]
    assert _errors(_schema("dis7-residual"), data) != []


def test_support_helpers():
    raw = dis7_support.seed()
    assert raw == dis7_support.vector_bytes("equator_eastbound")
    assert len(raw) == 144
    assert raw[0] == 7

    patched = dis7_support.patch(raw, 0, b"\x06")
    assert patched[0] == 6
    assert patched[1:] == raw[1:]
    assert raw[0] == 7

    with pytest.raises(ValueError):
        dis7_support.patch(raw, 144, b"\x00")
    with pytest.raises(ValueError):
        dis7_support.vector_json("equator_eastbound", "golden")
