"""The vendored contract: pins, schema validity, fixture validity and the static cross-checks.

The handoff bundle of SC HLA SPEC 001 v1.0 (not in this repository) ships thirteen schemas, eight
fixtures, two example configurations and a pin list. This package carries byte copies, and these
tests hold them without the bundle: every copy to the digest the bundle's manifest records
(`tests/contract/vendored-pins.json`), every schema to Draft 2020-12, every fixture to the schema
that describes it, and the fixtures to each other through the cross-checks the bundle's own
verifier makes on schemas and fixtures. The verifier's checks that need the FOM XML or a decoder
(wire layouts, negative error classes, RPR field order) belong to the rounds that build the
decoder and load the FOM; they are not repeated here.

No expected value comes from product code: digests and sizes come from the bundle's manifest,
structure from the fixtures themselves, and the remaining literals from the specification text.
"""

import collections
import functools
import json
import uuid

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from hla_support import (
    EXAMPLES_DIR, PACKAGE_ROOT, canonical, case, check_utc_timestamp, contract_json, example_json,
    fixture_json, fixture_jsonl, package_bytes, package_dir_names, packaged_pins, registry,
    schemas, sha256_hex, strict_json, validator,
)
import synapse_hla
from synapse_hla import errors

#: The thirteen schemas and their `$id`s, as the bundle ships them.
SCHEMA_IDS = {
    "cdm-entity.schema.json": "urn:synapsecommand:cdm:3.0.0:entity",
    "config.schema.json": "urn:synapsecommand:hla:1:config",
    "decoded-attribute.schema.json": "urn:synapsecommand:hla:1:decoded-attribute",
    "diagnostic.schema.json": "urn:synapsecommand:hla:1:diagnostic",
    "event.schema.json": "urn:synapsecommand:hla:1:event",
    "footer.schema.json": "urn:synapsecommand:hla:1:footer",
    "frame.schema.json": "urn:synapsecommand:hla:1:frame",
    "header.schema.json": "urn:synapsecommand:hla:1:header",
    "hla-provenance.schema.json": "urn:synapsecommand:hla:1:hla-provenance",
    "output.schema.json": "urn:synapsecommand:hla:1:output",
    "snapshot.schema.json": "urn:synapsecommand:hla:1:snapshot",
    "worker-frame.schema.json": "urn:synapsecommand:hla:1:worker-frame",
    "worker-status.schema.json": "urn:synapsecommand:hla:1:worker-status",
}

FIXTURES = ("attributes-negative.json", "attributes-positive.json", "expected.observations.jsonl",
            "first-upsert.entity.json", "geodesy.json", "identity.json",
            "session-checkpoints.json", "session.capture.jsonl")

EXAMPLES = ("config-demo.json", "config-existing.json")

#: R26: the public CDM UUID namespace, as SPEC:130 prints it.
CDM_NAMESPACE = "6f8b5b1e-0d4a-5a7e-9c3f-2b6d1e4a8c50"

PINS = contract_json("vendored-pins.json")["files"]


def _read_vendored(path: str) -> bytes:
    if path.startswith("src/synapse_hla/"):
        return package_bytes(*path[len("src/synapse_hla/"):].split("/"))
    if path.startswith("examples/"):
        return (EXAMPLES_DIR / path[len("examples/"):]).read_bytes()
    if path.startswith("tools/reference/"):
        # Round R8: the bundle's two C++ reference tools of R47 and REFERENCE-CHECKS, vendored
        # byte for byte (C++, not in D-06's list) and built by the native project.
        return (PACKAGE_ROOT / path).read_bytes()
    raise AssertionError(f"unexpected vendored path {path}")


# ------------------------------------------------------------------------------------- pins

def test_the_pin_list_covers_exactly_the_vendored_files():
    listed = [entry["path"] for entry in PINS]
    assert len(listed) == len(set(listed)) == 26
    expected = ({f"src/synapse_hla/schemas/{n}" for n in SCHEMA_IDS}
                | {f"src/synapse_hla/fixtures/{n}" for n in FIXTURES}
                | {f"examples/{n}" for n in EXAMPLES} | {"src/synapse_hla/pins.json"}
                | {"tools/reference/reference_encode.cpp",
                   "tools/reference/reference_fom_check.cpp"})
    assert set(listed) == expected
    for entry in PINS:
        assert set(entry) == {"path", "bundle_path", "bytes", "sha256"}
        assert entry["path"].endswith(entry["bundle_path"].rsplit("/", 1)[1])


@pytest.mark.parametrize("entry", PINS, ids=[e["path"].rsplit("/", 1)[1] for e in PINS])
@case("G-R45", "G-R46", "G-R01", paragraphs=("SPEC:259",))
def test_every_vendored_file_matches_its_pin(entry):
    data = _read_vendored(entry["path"])
    assert len(data) == entry["bytes"], entry["path"]
    assert sha256_hex(data) == entry["sha256"], entry["path"]


def test_the_schema_directory_holds_the_thirteen_schemas_and_nothing_else():
    """CR-L03: product-own schemas go to local_schemas/, never here."""
    assert package_dir_names("schemas") == sorted(SCHEMA_IDS)


def test_the_fixture_directory_holds_the_eight_fixtures_and_their_provenance():
    assert package_dir_names("fixtures") == sorted(FIXTURES + ("PROVENANCE.json",))


def test_the_examples_directory_holds_the_two_examples():
    assert sorted(p.name for p in EXAMPLES_DIR.iterdir()) == list(EXAMPLES)


def test_the_provenance_record_states_synthetic_origin_and_matches_the_bytes():
    record = fixture_json("PROVENANCE.json")
    assert set(record) == {"directory", "statement", "fixtures"}
    assert "hand-authored synthetic" in record["statement"]
    assert "not a recording of a real RTI exercise" in record["statement"]
    pins = {e["path"].rsplit("/", 1)[1]: e for e in PINS if "/fixtures/" in e["path"]}
    assert [f["file"] for f in record["fixtures"]] == sorted(FIXTURES)
    for f in record["fixtures"]:
        data = package_bytes("fixtures", f["file"])
        assert (f["bytes"], f["sha256"]) == (len(data), sha256_hex(data))
        assert (f["bytes"], f["sha256"]) == (pins[f["file"]]["bytes"], pins[f["file"]]["sha256"])
        assert f["synthetic"] is True and f["recorded_from_rti"] is False
        assert f["classification"] == "PUBLIC"
        assert f["operational_data"] is False and f["personal_data"] is False
        assert "not a recording of a real RTI exercise" in f["origin"]


# ---------------------------------------------------------------------------------- schemas

@pytest.mark.parametrize("name", sorted(SCHEMA_IDS))
def test_every_schema_is_a_valid_draft_2020_12_schema_with_its_id(name):
    schema = schemas()[name]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == SCHEMA_IDS[name]
    Draft202012Validator.check_schema(schema)


def _refs(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref":
                yield value
            yield from _refs(value)
    elif isinstance(node, list):
        for value in node:
            yield from _refs(value)


def test_every_external_ref_resolves_to_a_packaged_schema():
    reg = registry()
    seen = set()
    for name, schema in schemas().items():
        for ref in _refs(schema):
            if not ref.startswith("#"):
                assert ref in SCHEMA_IDS, f"{name} refers to {ref}, which is not packaged"
                reg.get_or_retrieve(ref)
                seen.add(ref)
    # The five cross-file references the bundle's schemas make, and no more.
    assert seen == {"event.schema.json", "config.schema.json", "cdm-entity.schema.json",
                    "diagnostic.schema.json", "snapshot.schema.json"}


def test_the_format_checker_checks_uuid_and_dates_are_checked_explicitly():
    """OPS-03. `uuid` is checked by the format checker and the tests rely on it; `date-time` is
    NOT relied on, whatever the installed checker does: every date in the fixtures is checked by
    `hla_support.check_utc_timestamp`, and the product's own date checks are explicit code
    (config epoch and header record_created_at in round R2, snapshot and provenance times in
    round R4)."""
    assert "uuid" in FormatChecker().checkers
    record = json.loads(package_bytes("fixtures", "expected.observations.jsonl").splitlines()[0])
    record["entity_id"] = "not-a-uuid"
    assert list(validator("output.schema.json").iter_errors(record))


# ------------------------------------------------------------------------ fixtures vs schemas

# Loaded inside the tests, never at import: a damaged fixture must fail its own tests (and its
# pin), not stop the whole module from being collected.
@functools.cache
def capture():
    return fixture_jsonl("session.capture.jsonl")


@functools.cache
def observations():
    return fixture_jsonl("expected.observations.jsonl")


def test_the_capture_is_one_header_frames_and_one_footer_each_valid():
    kinds = [obj["type"] for _, obj in capture()]
    assert kinds == ["header"] + ["frame"] * 8 + ["footer"]
    for _, obj in capture():
        validator(f"{obj['type']}.schema.json").validate(obj)


def test_the_capture_is_canonical_and_its_hash_chain_holds():
    """R15, recomputed here with the standard library: canonical lines, seq from 1 without gaps,
    seq 1 chained to the header bytes, each digest over the record without its sha256."""
    previous = None
    for i, (raw, obj) in enumerate(capture()):
        assert canonical(obj) == raw, f"line {i + 1} is not canonical"
        if i == 0:
            previous = sha256_hex(raw)
            continue
        assert obj["seq"] == i
        assert obj["prev_sha256"] == previous
        body = dict(obj)
        digest = body.pop("sha256")
        assert digest == sha256_hex(canonical(body))
        previous = digest


def test_the_capture_times_and_generations_are_consistent():
    header = capture()[0][1]
    check_utc_timestamp(header["record_created_at"], digits=6)
    check_utc_timestamp(header["config"]["time_policy"]["epoch"], digits=6)
    frames = [obj for _, obj in capture()[1:-1]]
    elapsed = [int(f["elapsed_ns"]) for f in frames]
    assert elapsed == sorted(elapsed), "elapsed_ns decreases (R16)"
    footer = capture()[-1][1]
    assert footer["status"] == "COMPLETE" and footer["reason_code"] is None
    assert footer["last_generation"] == max(f["generation"] for f in frames)


def test_the_header_pins_are_the_packaged_pin_list():
    """OPS-11 and RED-V-03: header.pins is exactly the {path: sha256} map of pins.json."""
    pins = packaged_pins()
    assert len(pins) == 9
    assert capture()[0][1]["pins"] == {path: e["sha256"] for path, e in pins.items()}


@pytest.mark.parametrize("name", EXAMPLES)
def test_both_example_configurations_validate(name):
    config = example_json(name)
    validator("config.schema.json").validate(config)
    if config["time_policy"]["mode"] == "external_elapsed":
        check_utc_timestamp(config["time_policy"]["epoch"], digits=6)


def test_the_expected_observation_stream_validates_and_is_canonical():
    assert len(observations()) == 7
    check = validator("output.schema.json")
    for raw, obj in observations():
        check.validate(obj)
        assert canonical(obj) == raw
        if obj["kind"] == "snapshot":
            for state in obj["payload"]["attributes"].values():
                if state["effective_at"] is not None:
                    check_utc_timestamp(state["effective_at"], digits=6)


def test_the_first_upsert_entity_validates_against_cdm_entity_and_provenance():
    entity = fixture_json("first-upsert.entity.json")
    validator("cdm-entity.schema.json").validate(entity)
    validator("hla-provenance.schema.json").validate(entity["attributes"]["hla"])
    check_utc_timestamp(entity["valid_from"], digits=3)
    check_utc_timestamp(entity["attributes"]["hla"]["time"]["effective_at"], digits=6)


def test_the_first_upsert_entity_is_the_payload_of_the_first_upsert_record():
    entity = fixture_json("first-upsert.entity.json")
    upserts = [obj for _, obj in observations() if obj["kind"] == "upsert"]
    assert canonical(entity) == canonical(upserts[0]["payload"])


def test_the_identity_vector_is_uuid5_of_the_cdm_namespace():
    """R26: entity_id = UUIDv5(namespace, UTF-8("entity|hla-rpr2|" + external_id))."""
    vector = fixture_json("identity.json")
    assert vector["uuid_namespace"] == CDM_NAMESPACE
    parts = json.loads(vector["external_id"])
    assert len(parts) == 6 and all(type(p) is str for p in parts)
    assert json.dumps(parts, separators=(",", ":"), ensure_ascii=True) == vector["external_id"]
    derived = uuid.uuid5(uuid.UUID(CDM_NAMESPACE), "entity|hla-rpr2|" + vector["external_id"])
    assert str(derived) == vector["entity_id"]
    assert fixture_json("first-upsert.entity.json")["entity_id"] == vector["entity_id"]


#: The positive vector ids, in the file's order: the nine Spatial variants, the three scalar
#: attributes at their edge values, and the padding vector.
POSITIVE_IDS = ("SPATIAL-1", "SPATIAL-2", "SPATIAL-3", "SPATIAL-4", "SPATIAL-5", "SPATIAL-6",
                "SPATIAL-7", "SPATIAL-8", "SPATIAL-9", "ID-123", "TYPE-PLATFORM", "FORCE-1",
                "FORCE-255", "SPATIAL-PADDING")


def test_the_positive_vectors_are_the_fourteen_named_ones():
    assert tuple(v["id"] for v in fixture_json("attributes-positive.json")) == POSITIVE_IDS


@pytest.mark.parametrize("vector_id", POSITIVE_IDS)
def test_every_decoded_twin_validates_against_decoded_attribute(vector_id):
    vector = next(v for v in fixture_json("attributes-positive.json") if v["id"] == vector_id)
    validator("decoded-attribute.schema.json").validate(
        {"name": vector["name"], "value": vector["expected"]})


def test_the_vector_files_hold_the_counts_the_cases_name():
    """14 positive vectors (V- cases) and 30 negative ones (N- cases), each id once."""
    positive = fixture_json("attributes-positive.json")
    negative = fixture_json("attributes-negative.json")
    assert len(positive) == 14 and len({v["id"] for v in positive}) == 14
    assert len(negative) == 30 and len({v["id"] for v in negative}) == 30
    index = {c["id"] for c in contract_json("case-index.json")}
    assert {f"V-{v['id']}" for v in positive} <= index
    assert {f"N-{v['id']}" for v in negative} <= index


def test_every_error_code_in_the_fixtures_is_a_catalogue_error_code():
    codes = [v["code"] for v in fixture_json("attributes-negative.json")]
    codes += [g["error"] for g in fixture_json("geodesy.json") if "error" in g]
    for code in codes:
        assert errors.is_code(code) and code.startswith("E_"), code


def test_the_checkpoints_agree_with_the_expected_observation_stream():
    points = fixture_json("session-checkpoints.json")
    by_kind = collections.defaultdict(list)
    for _, obj in observations():
        by_kind[obj["kind"]].append(obj)
    assert [o["seq"] for o in by_kind["snapshot"]] == points["snapshots_at"]
    assert [o["seq"] for o in by_kind["removed"]] == [points["removed_at"]]
    assert len(by_kind["invalidated"]) == points["invalidations"]
    assert len(by_kind["diagnostic"]) == points["diagnostics"]
    assert len(by_kind["upsert"]) == len(points["upserts"])
    for record, point in zip(by_kind["upsert"], points["upserts"]):
        entity = record["payload"]
        assert (record["seq"], record["revision"], record["entity_id"]) == (
            point["seq"], point["revision"], point["entity_id"])
        assert (entity["position"]["lat"], entity["position"]["lon"],
                entity["position"]["alt_m"]) == (point["lat"], point["lon"], point["alt_m"])
        kin = entity["kinematics"]
        assert (kin["speed_mps"], kin["course_deg"], kin["climb_mps"]) == (
            point["speed_mps"], point["course_deg"], point["climb_mps"])
        assert entity["valid_from"] == point["valid_from"]


#: SPEC:285's suppression vocabulary, verbatim.
SUPPRESSION_REASONS = {
    "MISSING_ENTITY_IDENTIFIER", "MISSING_ENTITY_TYPE", "MISSING_SPATIAL",
    "INVALID_ENTITY_IDENTIFIER", "INVALID_ENTITY_TYPE", "INVALID_SPATIAL",
    "INVALID_FORCE_IDENTIFIER", "NULL_ID", "QUARANTINED", "TIME_UNRESOLVED",
    "GEOGRAPHY_UNPROJECTABLE",
}

#: R33: within one frame, diagnostics first, then invalidations, then the snapshot, then the
#: optional upsert. Removal notices are lifecycle records like invalidations.
KIND_ORDER = {"diagnostic": 0, "invalidated": 1, "removed": 1, "snapshot": 2, "upsert": 3}


def test_the_expected_observation_stream_holds_the_rules_its_schema_is_too_loose_for():
    """RED-16 and R33 on the fixture itself: the schema admits records these rules refuse, so the
    expected stream is checked against the rules directly, before any product reproduces it."""
    records = [obj for _, obj in observations()]
    session_id = capture()[0][1]["config"]["session_id"]
    generation_of = {obj["seq"]: obj["generation"] for _, obj in capture()[1:-1]}
    by_seq = collections.defaultdict(list)
    for r in records:
        by_seq[r["seq"]].append(r)
        assert r["session_id"] == session_id
        assert r["generation"] == generation_of[r["seq"]]
        assert r["capture_complete"] is True, "a complete replay marks every record complete"
        assert (r["revision"] is not None) == (r["kind"] == "upsert"), r
        if r["kind"] == "upsert":
            assert r["entity_id"] == r["payload"]["entity_id"]
            assert r["payload"]["attributes"]["hla"]["capture_complete"] is True
        if r["kind"] == "removed":
            assert r["payload"]["reason"] == "removed"
        if r["kind"] == "invalidated":
            assert r["payload"]["reason"] != "removed"
        if r["kind"] == "snapshot":
            reasons = r["payload"]["suppression_reasons"]
            assert reasons == sorted(set(reasons)) and set(reasons) <= SUPPRESSION_REASONS
            changed = r["payload"]["changed_attributes"]
            assert changed and changed == sorted(set(changed))
    for seq, group in by_seq.items():
        assert [r["ordinal"] for r in group] == list(range(len(group))), seq
        ranks = [KIND_ORDER[r["kind"]] for r in group]
        assert ranks == sorted(ranks), seq
        snapshots = [r for r in group if r["kind"] == "snapshot"]
        for upsert in (r for r in group if r["kind"] == "upsert"):
            # SPEC:287: the snapshot carries the revision before this frame's upsert.
            assert len(snapshots) == 1
            assert snapshots[0]["payload"]["last_revision"] == upsert["revision"] - 1
    revisions = [r["revision"] for r in records if r["kind"] == "upsert"]
    assert revisions == list(range(1, len(revisions) + 1))
    removed = [r for r in records if r["kind"] == "removed"]
    assert [r["payload"]["last_revision"] for r in removed] == [revisions[-1]]


def test_the_profile_and_version_are_the_contracts():
    """The strings the package declares are the ones the vendored contract fixes."""
    s = schemas()
    assert s["config.schema.json"]["properties"]["profile"]["const"] == synapse_hla.PROFILE
    assert s["header.schema.json"]["properties"]["profile"]["const"] == synapse_hla.PROFILE
    assert s["header.schema.json"]["properties"]["adapter_version"]["const"] == (
        synapse_hla.__version__)
    assert strict_json(package_bytes("pins.json"))["profile"] == synapse_hla.PROFILE


# ------------------------------------------------------------------------------ case index

INDEX = contract_json("case-index.json")


def test_the_case_index_is_the_147_cases_with_three_fields_each():
    assert len(INDEX) == 147
    assert all(set(c) == {"id", "requirement", "layer"} for c in INDEX)
    assert len({c["id"] for c in INDEX}) == 147
    assert collections.Counter(c["layer"] for c in INDEX) == {
        "release": 50, "codec": 44, "behavior": 40, "integration": 13}
    assert collections.Counter(c["id"][0] for c in INDEX) == {"G": 50, "A": 53, "V": 14, "N": 30}


def test_every_requirement_has_its_gate_and_every_case_names_a_requirement():
    """The bundle verifier's traceability check, on the index: R01..R50, a G gate each."""
    requirements = {f"R{i:02d}" for i in range(1, 51)}
    assert {c["requirement"] for c in INDEX} == requirements
    gates = {c["id"]: c["requirement"] for c in INDEX if c["id"].startswith("G-")}
    assert gates == {f"G-{r}": r for r in requirements}
    assert all(c["layer"] == "release" for c in INDEX if c["id"].startswith("G-"))
