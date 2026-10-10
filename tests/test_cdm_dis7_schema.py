"""Pins and validates the vendored DIS 7 contract under `fixtures/dis7/`.

The bundle this contract was vendored from is a handoff document set identified by
`SC DIS7 SPEC 001 v1.0` and is not in this repository. This module reads one repository file
beyond the vendored tree, the published `schemas/entity.schema.json`, and nothing else.
Since 2026-10-10 it reads two: the entity-schema pin also reads the frozen CDM 3.0.0 entity
schema, `tests/frozen/cdm/3.0.0/entity.schema.json` (the Link 16 gateway arc; see the pin test).
"""
from __future__ import annotations

import copy
import hashlib
import json
import pathlib

import jsonschema
import pytest

from synapse_cdm import evidence, harness, schemas
from synapse_cdm.adapter import json_nesting_depth
from synapse_cdm.adapters.dis7_codec import decode_pdu

from tests import dis7_support

REPO = pathlib.Path(__file__).resolve().parents[1]
ENTITY_SCHEMA = REPO / "schemas" / "entity.schema.json"
#: The frozen CDM 3.0.0 entity schema — the bytes the bundle's `cdm-entity.schema.json` equals.
#: Read only by the pin test below (2026-10-10); every validation here keeps using the published
#: `ENTITY_SCHEMA`.
FROZEN_3_0_0_ENTITY_SCHEMA = REPO / "tests" / "frozen" / "cdm" / "3.0.0" / "entity.schema.json"

SCHEMA_NAMES = ("dis7-context", "dis7-entity", "dis7-envelope", "dis7-pdu", "dis7-residual")

# Copied from the handoff bundle's MANIFEST.json (SC DIS7 SPEC 001 v1.0), never computed from the
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


# 2026-10-10, the Link 16 gateway arc: `schemas/entity.schema.json` gained two `PositionSource`
# members (SENSOR, UNKNOWN; CDM 3.1.0), so its digest no longer equals the bundle's. The bundle's
# `cdm-entity.schema.json` is byte-identical to the frozen 3.0.0 contract, which never moves, and
# that copy is what this pin now reads; the test was named
# `test_pin_cdm_entity_schema_is_the_published_entity_schema` until then. Mutation reading, the
# same day: one byte changed in a scratch copy of `tests/frozen/cdm/3.0.0/entity.schema.json`
# makes this test fail on the digest, and `tests/test_cdm_version_matrix.py` independently holds
# that file to `tests/frozen/cdm/MANIFEST.json`.
def test_pin_cdm_entity_schema_is_the_frozen_3_0_0_entity_schema():
    digest = hashlib.sha256(FROZEN_3_0_0_ENTITY_SCHEMA.read_bytes()).hexdigest()
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



def _a02_input() -> bytes:
    raw = dis7_support.patch(dis7_support.seed(), 8, bytes.fromhex("1080"))
    return dis7_support.patch(raw, 19, bytes([255])) + bytes(4080)


DECODED_INPUTS = [
    *[pytest.param(lambda stem=stem: dis7_support.vector_bytes(stem), id=stem)
      for stem in dis7_support.STEMS],
    pytest.param(dis7_support.walking_pdu, id="walking"),
    pytest.param(_a02_input, id="a02_255_records"),
]


@pytest.mark.parametrize("build", DECODED_INPUTS)
def test_schema_every_decoded_pdu_validates_against_dis7_pdu(build):
    schema = _schema("dis7-pdu")
    raw = build()
    pdu = decode_pdu(raw)
    assert _errors(schema, pdu) == []
    assert list(pdu) == schema["required"]
    assert list(pdu["header"]) == schema["properties"]["header"]["required"]


def test_schema_decoded_pdu_validation_can_fail():
    schema = _schema("dis7-pdu")
    extra_key = decode_pdu(dis7_support.seed())
    extra_key["unknown"] = True
    assert _errors(schema, extra_key) != []
    short_length = decode_pdu(dis7_support.seed())
    short_length["header"]["length"] = 143
    assert _errors(schema, short_length) != []

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


FIXTURE_NAMES = sorted(f"{stem}{ext}" for stem in dis7_support.STEMS for ext in (".dis", ".parsed.json"))
GOLDEN_NAMES = sorted(f"{stem}{ext}" for stem in dis7_support.STEMS
                      for ext in (".cdm.json", ".parsed.cdm.json"))
MALFORMED_NAMES = sorted(["wrong_protocol_version.dis", "pdu_type_67.dis", "truncated_by_one_byte.dis",
                          "one_trailing_byte.dis", "envelope_unknown_key.json"])
# The `bytes` member of each entry in the bundle's `vectors/index.json`, in STEMS order.
DIS_LENGTHS = (144, 144, 160)


@pytest.mark.parametrize("stem", dis7_support.STEMS)
def test_top_level_fixtures_are_byte_identical_to_the_vendored_vectors(stem):
    fixtures = dis7_support.FIXTURES
    assert (fixtures / f"{stem}.dis").read_bytes() == dis7_support.vector_bytes(stem)
    assert ((fixtures / f"{stem}.parsed.json").read_bytes()
            == (dis7_support.VECTORS / f"{stem}.envelope.json").read_bytes())
    assert len((fixtures / f"{stem}.dis").read_bytes()) == DIS_LENGTHS[dis7_support.STEMS.index(stem)]


def test_the_fixture_directory_has_exactly_the_planned_layout():
    fixtures = dis7_support.FIXTURES
    selected = [p.name for p in harness.select_fixtures(fixtures)]
    assert selected == FIXTURE_NAMES
    assert not [name for name in selected if name.startswith(("truncated", "malformed"))]
    assert sorted(p.name for p in (fixtures / "golden").glob("*.cdm.json")) == GOLDEN_NAMES
    for directory in (fixtures, fixtures / "malformed"):
        assert (directory / "README.md").is_file()
        assert (directory / "PROVENANCE.json").is_file()


def test_no_json_under_the_fixture_directory_nests_deeper_than_sixteen():
    # 16 is harness.LOADER_MAX_DEPTH (64) divided by 4, the rule every fixture directory keeps.
    measured = 0
    for path in dis7_support.FIXTURES.rglob("*.json"):
        assert json_nesting_depth(path.read_text(encoding="utf-8")) <= 16, path.name
        measured += 1
    assert measured >= 25


def test_the_two_provenance_records_list_exactly_the_selected_files():
    fixtures = dis7_support.FIXTURES
    top = evidence.read_provenance(fixtures)
    assert top.directory == "dis7"
    assert [row.file for row in top.fixtures] == FIXTURE_NAMES
    malformed = evidence.read_provenance(fixtures / "malformed")
    assert malformed.directory == "dis7/malformed"
    assert [row.file for row in malformed.fixtures] == MALFORMED_NAMES
    for row in (*top.fixtures, *malformed.fixtures):
        assert row.synthetic is True
        assert row.classification == "PUBLIC"
        assert row.operational_data is False
        assert row.personal_data is False


# ---------------------------------------------------------------------------------------------
# Emitted output against the contract schemas, and the stage-2 differential (requirement R12)
# ---------------------------------------------------------------------------------------------

S = dis7_support.seed()
MAX = dis7_support.patch(dis7_support.patch(S, 19, b"\xff"), 8, b"\x10\x80") + bytes(4080)
HOST_HASH = "c958233bda22e82385788584e0297d0e264ee2a0db94dc32838141925155ef1a"


def _emitted_corpus():
    """(label, adapter, input) for every emitted shape the schemas must admit."""
    fa = dis7_support.fixture_adapter
    corpus = []
    for stem in dis7_support.STEMS:
        corpus.append((f"{stem}.dis", fa(), dis7_support.vector_bytes(stem)))
        corpus.append((f"{stem}.envelope", fa(),
                       copy.deepcopy(dis7_support.vector_json(stem, "envelope"))))
    corpus += [
        ("255 records", fa(), MAX),
        ("algorithm 9", fa(), dis7_support.patch(S, 88, b"\x09")),
        ("zero vector", fa(), dis7_support.patch(S, 48, bytes(24))),
        ("not synthetic", fa(synthetic=False), S),
        ("host hash", fa(source_hash={"algorithm": "sha256", "value": HOST_HASH}), S),
    ]
    return corpus


def test_r12_emitted_entities_validate_against_the_profile_and_base_schemas():
    profile = _schema("dis7-entity")
    published = json.loads(ENTITY_SCHEMA.read_text())
    corpus = _emitted_corpus()
    assert len(corpus) == 11
    for label, adapter, raw in corpus:
        dump = adapter.to_cdm(raw)[0].model_dump(mode="json")
        assert _errors(profile, dump) == [], label
        assert _errors(published, dump) == [], label


def test_r12_emitted_residuals_validate_and_rebuild_a_valid_envelope():
    residual_schema = _schema("dis7-residual")
    envelope_schema = _schema("dis7-envelope")
    for label, adapter, raw in _emitted_corpus():
        entity = adapter.to_cdm(raw)[0]
        data = entity.model_dump(mode="json")["residual"]["data"]
        assert _errors(residual_schema, data) == [], label
        envelope = {"pdu": data["pdu"], "wire_hex": data["wire_hex"], "time_context": data["time_context"]}
        assert _errors(envelope_schema, envelope) == [], label
        assert adapter.to_cdm(envelope)[0] == entity, label


def test_r12_schema_oracles_can_fail():
    dump = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "expected"))[0]
    dump["affiliation"] = "FRIENDLY"
    assert _errors(_schema("dis7-entity"), dump) != []
    data = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "expected"))[0]["residual"]["data"]
    data["extra"] = 1
    assert _errors(_schema("dis7-residual"), data) != []
    envelope = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope"))
    envelope["extra"] = 1
    assert _errors(_schema("dis7-envelope"), envelope) != []


_ENVELOPE_KEYS = ("pdu", "wire_hex", "time_context")
_PDU_KEYS = ("header", "entity_id", "force_id", "entity_type", "alternative_entity_type",
             "velocity_mps", "position_ecef_m", "orientation_radians", "appearance",
             "dead_reckoning_hex", "marking_hex", "capabilities", "variable_parameters_hex")
_HEADER_KEYS = ("protocol_version", "exercise_id", "pdu_type", "protocol_family", "timestamp",
                "length", "status", "padding")
_ARRAYS = ("entity_id", "entity_type", "alternative_entity_type", "velocity_mps", "position_ecef_m",
           "orientation_radians")


def _node(envelope, dotted):
    *parents, last = dotted.split(".")
    node = envelope
    for name in parents:
        node = node[name]
    return node, last


def _set(dotted, value):
    def edit(envelope):
        node, last = _node(envelope, dotted)
        node[last] = copy.deepcopy(value)
    return edit


def _drop(dotted):
    def edit(envelope):
        node, last = _node(envelope, dotted)
        del node[last]
    return edit


def _apply(dotted, change):
    def edit(envelope):
        node, last = _node(envelope, dotted)
        node[last] = change(node[last])
    return edit


def _differential_corpus():
    """(class, label, edit) for the 106 envelopes of the stage-2 differential."""
    nan, inf = float("nan"), float("inf")
    rows = []
    for where in ("", "pdu.", "pdu.header.", "time_context."):
        rows.append(("extra", f"{where}extra", _set(f"{where}extra", 1)))
    for dotted in (*_ENVELOPE_KEYS, *(f"pdu.{key}" for key in _PDU_KEYS),
                   *(f"pdu.header.{key}" for key in _HEADER_KEYS), "time_context.instant",
                   "time_context.basis"):
        rows.append(("omit", dotted, _drop(dotted)))
    for dotted, value in (("pdu.force_id", "1"), ("pdu.header.exercise_id", None),
                          ("pdu.entity_id", "7:11:1"), ("pdu.velocity_mps", [0.0, None, 0.0]),
                          ("pdu.velocity_mps", ["0.0", 25.0, 0.0]), ("time_context.instant", 5),
                          ("time_context.basis", 5), ("time_context", []), ("pdu", []),
                          ("wire_hex", 5), ("pdu.marking_hex", 5)):
        rows.append(("type", f"{dotted}={value!r}", _set(dotted, value)))
    for dotted, value in (("pdu.force_id", True), ("pdu.header.pdu_type", True),
                          ("pdu.velocity_mps", [False, 25.0, 0.0])):
        rows.append(("bool", f"{dotted}={value!r}", _set(dotted, value)))
    for dotted, value in (("pdu.force_id", 256), ("pdu.force_id", -1), ("pdu.header.exercise_id", 256),
                          ("pdu.entity_id", [65536, 11, 1]), ("pdu.appearance", 4294967296),
                          ("pdu.header.length", 143), ("pdu.header.length", 4225),
                          ("pdu.header.timestamp", -1)):
        rows.append(("range", f"{dotted}={value!r}", _set(dotted, value)))
    for dotted, value in (("pdu.header.protocol_version", 6), ("pdu.header.pdu_type", 67),
                          ("pdu.header.protocol_family", 2)):
        rows.append(("const", f"{dotted}={value!r}", _set(dotted, value)))
    for key in _ARRAYS:
        rows.append(("width", f"{key} short", _apply(f"pdu.{key}", lambda items: items[:-1])))
        rows.append(("width", f"{key} long", _apply(f"pdu.{key}", lambda items: items + [items[-1]])))
    for key in ("dead_reckoning_hex", "marking_hex"):
        rows.append(("width", f"{key} short", _apply(f"pdu.{key}", lambda text: text[:-1])))
        rows.append(("width", f"{key} long", _apply(f"pdu.{key}", lambda text: text + "0")))
    for label, value in (("one record of 31", ["0" * 31]), ("one record of 33", ["0" * 33]),
                         ("256 records", ["00" * 16] * 256)):
        rows.append(("width", label, _set("pdu.variable_parameters_hex", value)))
    rows.append(("hex", "marking_hex upper", _apply("pdu.marking_hex", str.upper)))
    rows.append(("hex", "wire_hex upper", _apply("wire_hex", str.upper)))
    rows.append(("hex", "wire_hex odd", _apply("wire_hex", lambda text: text + "0")))
    rows.append(("hex", "wire_hex space", _apply("wire_hex", lambda text: text[:-2] + " 0")))
    rows.append(("hex", "wire_hex 286", _apply("wire_hex", lambda text: text[:286])))
    rows.append(("hex", "wire_hex 8450", _apply("wire_hex", lambda text: text + "00" * 4081)))
    rows.append(("accept", "unchanged", _apply("wire_hex", lambda text: text)))
    rows.append(("accept", "integral velocity", _set("pdu.velocity_mps", [0, 25, 0])))
    rows.append(("accept", "negative zero velocity", _set("pdu.velocity_mps", [-0.0, 25.0, 0.0])))
    rows.append(("later", "force_id 2", _set("pdu.force_id", 2)))
    rows.append(("later", "wire octet 2 = 43",
                 _apply("wire_hex", lambda text: text[:4] + "43" + text[6:])))
    for instant in ("not-a-time", "2026-04-29T06:15:00", "2026-04-29T06:15:00.0000Z",
                    "2026-04-29t06:15:00z", "2026-04-29 06:15:00Z"):
        rows.append(("CR-03", f"instant {instant}", _set("time_context.instant", instant)))
    for basis in ("", " ", "x" * 1025):
        rows.append(("CR-03", f"basis of {len(basis)}", _set("time_context.basis", basis)))
    rows.append(("CR-05", "velocity NaN", _set("pdu.velocity_mps", [nan, 25.0, 0.0])))
    rows.append(("CR-05", "position inf", _set("pdu.position_ecef_m", [6378257.0, inf, 0.0])))
    rows.append(("CR-05", "orientation -inf", _set("pdu.orientation_radians", [0.5, -0.25, -inf])))
    for instant in ("2016-12-31T23:59:60Z", "2026-02-30T00:00:00Z", "2026-04-29T24:00:00Z",
                    "0000-01-01T00:00:00Z", "2026-04-29T06:15:00+24:00"):
        rows.append(("CR-01", f"instant {instant}", _set("time_context.instant", instant)))
    for dotted, value in (("pdu.header.protocol_version", 7.0), ("pdu.header.exercise_id", 42.0),
                          ("pdu.force_id", 1.0), ("pdu.entity_id", [7.0, 11.0, 1.0]),
                          ("pdu.appearance", 305419896.0)):
        rows.append(("CR-06", f"{dotted}={value!r}", _set(dotted, value)))
    return rows


_CLASS_COUNTS = {"extra": 4, "omit": 26, "type": 11, "bool": 3, "range": 8, "const": 3, "width": 19,
                 "hex": 6, "accept": 3, "later": 2, "CR-03": 8, "CR-05": 3, "CR-01": 5, "CR-06": 5}


# CR-01, CR-03, CR-05, CR-06
def test_r12_stage2_verdict_equals_the_envelope_schema_except_enumerated_divergences():
    """The adapter's stage-2 verdict against `dis7-envelope.schema.json`, envelope by envelope.

    This test alone builds `jsonschema.Draft202012Validator(schema)` with no `format_checker`:
    `format` then stays an annotation, so the verdict cannot depend on optional packages. The
    corpus holds JSON-shaped values only (no tuples, CR-29) and no basis made only of the
    engine-dependent white-space code points (CR-07).
    """
    from synapse_cdm.adapters.dis7 import Dis7Error

    validator = jsonschema.Draft202012Validator(_schema("dis7-envelope"))
    adapter = dis7_support.fixture_adapter(time_context=None)
    rows = _differential_corpus()
    assert len(rows) == 106
    counts = {}
    for kind, _, _ in rows:
        counts[kind] = counts.get(kind, 0) + 1
    assert counts == _CLASS_COUNTS
    assert len({(kind, label) for kind, label, _ in rows}) == 106

    schema_ok, outcome = {}, {}
    for kind, label, edit in rows:
        envelope = copy.deepcopy(dis7_support.vector_json("equator_eastbound", "envelope"))
        edit(envelope)
        key = (kind, label)
        schema_ok[key] = not any(True for _ in validator.iter_errors(envelope))
        try:
            adapter.to_cdm(copy.deepcopy(envelope))
        except Dis7Error as error:
            outcome[key] = (error.code, error.path)
        else:
            outcome[key] = ("ACCEPT", None)

    expected_pairs = {
        ("later", "force_id 2"): ("E_TWIN_WIRE_MISMATCH", "pdu.force_id"),
        ("later", "wire octet 2 = 43"): ("E_HEADER_UNSUPPORTED", "byte[2]"),
        ("CR-05", "velocity NaN"): ("E_TWIN_SCHEMA", "pdu.velocity_mps[0]"),
        ("CR-05", "position inf"): ("E_TWIN_SCHEMA", "pdu.position_ecef_m[1]"),
        ("CR-05", "orientation -inf"): ("E_TWIN_SCHEMA", "pdu.orientation_radians[2]"),
    }
    for key in schema_ok:
        kind, label = key
        if kind in ("extra", "omit", "type", "bool", "range", "const", "width", "hex"):
            assert schema_ok[key] is False, key
            assert outcome[key][0] == "E_TWIN_SCHEMA", (key, outcome[key])
        elif kind in ("accept", "CR-06"):
            assert schema_ok[key] is True, key
            assert outcome[key] == ("ACCEPT", None), (key, outcome[key])
        elif kind == "CR-03":
            assert schema_ok[key] is False, key
            want = "time_context.instant" if label.startswith("instant") else "time_context.basis"
            assert outcome[key] == ("E_CONTEXT_TIME", want), (key, outcome[key])
        elif kind == "CR-01":
            assert schema_ok[key] is True, key
            assert outcome[key] == ("E_CONTEXT_TIME", "time_context.instant"), (key, outcome[key])
        else:
            assert schema_ok[key] is True, key
            assert outcome[key] == expected_pairs[key], (key, outcome[key])

    divergent = {key for key in schema_ok if schema_ok[key] != (outcome[key][0] != "E_TWIN_SCHEMA")}
    assert divergent == {key for key in schema_ok if key[0] in ("CR-03", "CR-05")}
