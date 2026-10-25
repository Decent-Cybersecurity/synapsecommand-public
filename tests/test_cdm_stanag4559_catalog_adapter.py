"""`stanag4559_catalog` (#35): the STANAG 4559 catalogue translator, SC ISR gateway record -> one
STATUS_CHANGE Event, and — once, for all three translators — the record module it runs on,
`synapse_cdm.isr_record` (SC ISR 4559 001 sections 6, 7 and 28).

REPO-BOUND: the acceptance oracle is the specification bundle's examples, carried verbatim under
`tests/stanag4559_bundle/` (not packaged), and the fixture builder this module runs reads them.

Each test that discharges one of the bundle's acceptance cases (`verification/acceptance-tests.json`,
CDM-001 to CDM-012 and PARSE-001 to PARSE-010) names it in its docstring. Expectations come from
`tests/stanag4559_support.py`'s literal tables and from the bundle's own expected files, never from
the code under test (that module's docstring says how each literal was derived).
"""

import copy
import json
import pathlib
import time

import jsonschema
import pytest

import synapse_cdm
from synapse_cdm import canonical, evidence, harness, isr_record, lossless, projection, schemas
from synapse_cdm.adapter import (
    Adapter,
    InputTooDeep,
    InputTooLarge,
    container_depth,
    enforce_depth_bound,
    enforce_input_bound,
    json_nesting_depth,
    load_adapter,
)
from synapse_cdm.adapters.stanag4559_common import Stanag4559Adapter
from synapse_cdm.manifest import ClaimStatus, LimitKind, MaturityLevel, UnknownFields, WireBinding
from synapse_cdm.manifest import Residual as ResidualStance
from synapse_cdm.models import Event

from tests import observation_support
from tests import stanag4559_support as S

FAMILY = "catalog"
ORDINAL = 35

#: The published 3.2.0 event schema, and the frozen 3.0.0 one the bundle's expected files follow.
EVENT_SCHEMA = schemas.validator_for(
    json.loads((S.REPO / "schemas" / "event.schema.json").read_text(encoding="utf-8"))
)
FROZEN_EVENT_SCHEMA = schemas.validator_for(
    json.loads(
        (S.REPO / "tests" / "frozen" / "cdm" / "3.0.0" / "event.schema.json").read_text(
            encoding="utf-8"
        )
    )
)

# ================================================================ CDM-001: the bundle oracle


@pytest.mark.parametrize("entry", S.manifest_entries(FAMILY), ids=lambda e: e["name"])
def test_cdm_001_the_bundle_records_become_the_bundle_events_byte_for_byte(entry):
    """CDM-001 ("Exact golden output and CDM schema match"). Each of the family's three bundle
    records, as its octets and as the parsed object, under the manifest clock, becomes ONE Event
    whose rendering is the bundle's expected file byte for byte once projected to the CDM 3.0.0
    contract the bundle pinned (`S.render_as_bundle`: the null 3.2.0 `validity` removed by
    `projection.dump_for`, the stamp 3.0.0); the full Event validates against the published 3.2.0
    event schema and the projection against the frozen 3.0.0 one."""
    assert entry["clock"] == S.BUNDLE_CLOCK and entry["synthetic"] is True
    octets = (S.BUNDLE / entry["input"]).read_bytes()
    expected = (S.BUNDLE / entry["expected"]).read_bytes()
    assert json.loads(expected)[0]["schema_version"] == "3.0.0"
    for raw in (octets, json.loads(octets)):
        objects = S.adapter(FAMILY, clock=entry["clock"], synthetic=entry["synthetic"]).to_cdm(raw)
        assert len(objects) == 1 and isinstance(objects[0], Event)
        assert S.render_as_bundle(objects[0]) == expected
        dumped = objects[0].model_dump(mode="json")
        assert list(EVENT_SCHEMA.iter_errors(dumped)) == []
        assert list(FROZEN_EVENT_SCHEMA.iter_errors(projection.dump_for(objects[0], "3.0.0"))) == []
        assert Event.model_validate_json(json.dumps(dumped)) == objects[0]


@pytest.mark.parametrize("case", list(S.CASES))
def test_cdm_001_the_bundle_identities_are_the_literals(case):
    """CDM-001's identities, as literals (`S.BUNDLE_IDENTITY`: the bundle manifest's values,
    pinned by digest and not carried, and the revision key section 7 derives): the Event and the module functions both state them."""
    okey, rkey, record_id, event_id = S.BUNDLE_IDENTITY[f"{FAMILY}-{case}"]
    record = S.bundle_record(FAMILY, case)
    event = S.translate(record)
    assert event["source_ids"] == [{"external_id": okey, "system": "NSILI"}]
    assert event["payload"]["revision_key"] == rkey
    assert event["payload"]["record_id"] == record_id
    assert event["event_id"] == event_id
    assert isr_record.object_key(record) == okey and isr_record.revision_key(record) == rkey
    assert str(isr_record.record_id(record)) == record_id
    assert str(isr_record.event_id(record)) == event_id


# ============================================================ CDM-002 to CDM-006, CDM-008 to -011


@pytest.mark.parametrize("case", list(S.CASES))
def test_cdm_002_one_hundred_translations_are_identical(case):
    """CDM-002: the same input translated a hundred times gives one output and one identity."""
    record = S.bundle_record(FAMILY, case)
    outputs = {
        S.render_as_bundle(S.adapter(FAMILY).to_cdm(copy.deepcopy(record))[0]) for _ in range(100)
    }
    assert len(outputs) == 1
    assert json.loads(outputs.pop())[0]["event_id"] == S.BUNDLE_IDENTITY[f"{FAMILY}-{case}"][3]


@pytest.mark.parametrize("field", ["tenant_id", "security_domain"])
def test_cdm_003_another_tenant_or_domain_is_another_object_and_event(field):
    """CDM-003 ("Different object and event IDs" for another tenant, same upstream id), and the
    security domain, the other deployment-scoped component of K, the same way."""
    record = S.bundle_record(FAMILY, "basic")
    other = S.mutated(record, lambda d: d.update({field: "test-other"}))
    a, b = S.translate(record), S.translate(other)
    assert a["source_ids"][0]["external_id"] != b["source_ids"][0]["external_id"]
    assert a["payload"]["record_id"] != b["payload"]["record_id"]
    assert a["event_id"] != b["event_id"]
    assert b["source"]["original_id"] == a["source"]["original_id"] == record["origin"]["object_id"]


def test_cdm_004_another_origin_authority_is_another_object():
    """CDM-004: the same upstream object id under another issuing authority is another object."""
    record = S.bundle_record(FAMILY, "basic")
    other = S.mutated(record, lambda d: d["origin"].update({"authority": "test-origin-b"}))
    a, b = S.translate(record), S.translate(other)
    assert a["source_ids"][0]["external_id"] != b["source_ids"][0]["external_id"]
    assert a["payload"]["record_id"] != b["payload"]["record_id"]
    assert a["event_id"] != b["event_id"]


@pytest.mark.parametrize("case", list(S.CASES))
def test_cdm_005_a_replica_replay_keeps_the_event_id(case):
    """CDM-005, PARTIAL ("Same event ID; additional provenance"). Another replica's capture of the
    same origin, revision and content — another connector and library, another receipt time,
    another raw capture — has the same event id and record id. The provenance that differs is in
    the Event (its source hash, its record), so the two Events are different bytes under one id:
    folding them into one logical record with several provenance observations is the gateway's
    deduplication (section 7), which is not part of this distribution."""
    record = S.bundle_record(FAMILY, case)
    replica = S.mutated(
        record,
        lambda d: (
            d.update(
                {
                    "connector_id": "test-library-b",
                    "library_id": "test-library-b",
                    "captured_at": "2026-10-04T12:00:09.000Z",
                }
            ),
            d["raw_ref"].update({"uri": "fixture://raw/replica-b.json", "sha256": "ab" * 32}),
        ),
    )
    first, second = S.translate(record), S.translate(replica)
    assert first["event_id"] == second["event_id"] == S.BUNDLE_IDENTITY[f"{FAMILY}-{case}"][3]
    assert first["payload"]["record_id"] == second["payload"]["record_id"]
    assert second["source"]["source_hash"] == {"algorithm": "sha256", "value": "ab" * 32}
    assert second["payload"]["record"]["library_id"] == "test-library-b"
    if record["source_time"] is None:
        assert (first["observed_at"], second["observed_at"]) == (
            "2026-10-04T12:00:01.000Z",
            "2026-10-04T12:00:09.000Z",
        )
    else:
        assert first["observed_at"] == second["observed_at"] == "2026-10-04T12:00:00.000Z"


def test_cdm_006_no_source_time_is_the_gateway_receipt_observation():
    """CDM-006 ("Gateway observation time; source.observed_at null"), and section 9's golden case:
    `observed_at` is `captured_at`, `time_basis` GATEWAY_RECEIPT, `source.observed_at` null, the
    record's `source_time` stays null, `received_at` is the clock, and no body time is promoted."""
    record = S.bundle_record(FAMILY, "missing-source-time")
    assert record["source_time"] is None
    event = S.translate(record)
    assert event["observed_at"] == record["captured_at"] == "2026-10-04T12:00:01.000Z"
    assert event["source"]["observed_at"] is None
    assert event["payload"]["time_basis"] == "GATEWAY_RECEIPT"
    assert event["payload"]["record"]["source_time"] is None
    assert event["received_at"] == S.BUNDLE_CLOCK
    with_time = S.translate(S.bundle_record(FAMILY, "basic"))
    assert with_time["payload"]["time_basis"] == "SOURCE"
    assert (
        with_time["observed_at"] == with_time["source"]["observed_at"] == "2026-10-04T12:00:00.000Z"
    )


def test_cdm_008_009_the_wide_integer_extension_survives_unrounded():
    """CDM-008 ("Exact source lexical value survives") and CDM-009 ("No numeric rounding" of
    18446744073709551615): the vendor attribute arrives and leaves as two strings, verbatim."""
    rendered = S.render_as_bundle(
        S.adapter(FAMILY).to_cdm(S.bundle_record(FAMILY, "unknown-extension"))[0]
    ).decode()
    record = json.loads(rendered)[0]["payload"]["record"]
    assert S.graph_of(record)["nodes"] == [
        {
            "attributes": [
                {
                    "lexical": "18446744073709551615",
                    "name": "urn:synthetic:vendor:largeCounter",
                    "nil": False,
                    "occurrence": 0,
                    "source_type": "unsignedLong",
                    "value": "18446744073709551615",
                }
            ],
            "entity": "urn:synthetic:vendor:Extension",
            "id": "n1",
        }
    ]
    assert rendered.count('"18446744073709551615"') == 2
    assert "1.8446744073709552e+19" not in rendered and "18446744073709552000" not in rendered


@pytest.mark.parametrize("case", list(S.CASES))
def test_cdm_010_an_unknown_top_level_key_is_refused(case):
    """CDM-010 ("Schema rejection" of an unknown top-level key), on each record and both paths;
    and a key the contract does not define one level down is refused the same way."""
    record = S.bundle_record(FAMILY, case)
    extra = S.mutated(record, lambda d: d.update({"unexpected": 1}))
    assert S.refuse_record(extra) == "unknown-key"
    assert S.refuse_record(json.dumps(extra).encode(), FAMILY) == "unknown-key"
    nested = S.mutated(record, lambda d: d["body"].update({"vendor_note": "x"}))
    with pytest.raises(isr_record.IsrRecordRefused, match="unknown-key: /body/vendor_note:"):
        S.adapter(FAMILY).to_cdm(nested)


def test_cdm_011_a_kind_of_another_family_is_refused():
    """CDM-011 ("Schema rejection" of family catalog with a stream.record kind), for this family
    with each other family's kind; the bundle's own stock validator refuses it as well."""
    record = S.bundle_record(FAMILY, "basic")
    for kind in sorted(set(isr_record.FAMILY_KIND.values()) - {record["kind"]}):
        wrong = S.mutated(record, lambda d: d.update({"kind": kind}))
        assert S.refuse_record(wrong) == "kind-family-mismatch"
        stock = jsonschema.Draft202012Validator(isr_record.schema())
        assert list(stock.iter_errors(wrong)), "the bundle's validator lets it through"


def test_a_record_of_another_family_is_refused_by_this_translator():
    """One translator per family (section 5): a valid record of another family is refused
    `wrong-family` before any output."""
    for other in sorted(set(S.FAMILIES) - {FAMILY}):
        record = S.bundle_record(other, "basic")
        assert S.refusal(S.adapter(FAMILY).to_cdm, record) == "wrong-family"


@pytest.mark.parametrize("field", ["family", "kind"])
@pytest.mark.parametrize("value", S.UNJUDGED, ids=json.dumps)
def test_a_family_or_kind_that_is_not_a_string_is_refused_by_the_schema(field, value):
    """`family` and `kind` are read before the schema pass (the kind/family rule and the geometry
    cap), where they can hold any JSON value. One that is not a string, a list or an object among
    them, reaches the schema and is refused `schema-violation` naming its path, as a parsed object
    and as octets, by this translator and by `isr_record.validate` (the review of 2026-10-24 found
    a list or an object `family` escaping as `TypeError`)."""
    record = S.mutated(S.bundle_record(FAMILY, "basic"), lambda d: d.update({field: value}))
    octets = json.dumps(record).encode("utf-8")
    calls = {
        "translator, object": lambda: S.adapter(FAMILY).to_cdm(record),
        "translator, octets": lambda: S.adapter(FAMILY).to_cdm(octets),
        "validate, object": lambda: isr_record.validate(record),
        "validate, parsed octets": lambda: isr_record.validate(isr_record.parse(octets)),
    }
    for label, call in calls.items():
        with pytest.raises(isr_record.IsrRecordRefused) as refused:
            call()
        assert str(refused.value).startswith(f"schema-violation: /{field}:"), (
            label,
            str(refused.value),
        )


@pytest.mark.parametrize("case", list(S.CASES))
def test_every_single_field_substitution_translates_or_is_refused_typed(case):
    """No exception but the typed refusal escapes this translator: every record that differs from
    a bundle record at one path, the member replaced by a value of each JSON shape or deleted, as
    a parsed object and as octets, either translates to one Event or is refused with
    `IsrRecordRefused`. The class the review of 2026-10-24 found one member of (`family`), held
    shut for every member."""
    tried, problems = S.untyped_outcomes(FAMILY, S.bundle_record(FAMILY, case))
    assert tried > 50 * len(S.SUBSTITUTES), tried
    assert problems == []


# ======================================================== the packaged fixtures and their goldens


@pytest.mark.parametrize("stem", list(S.CASES.values()))
def test_the_packaged_golden_states_the_literal_identity_times_and_geometry(stem):
    """The regression goldens `harness --update-golden` wrote under `times.FROZEN_NOW`: every
    field that matters is held to a literal, and the golden is what the adapter renders today."""
    want = S.AUTHORED[FAMILY][stem]
    okey = S.BUNDLE_IDENTITY[f"{FAMILY}-{stem.replace('_', '-')}"][0]
    record_id = S.BUNDLE_IDENTITY[f"{FAMILY}-{stem.replace('_', '-')}"][2]
    golden_path = S.fixture_dir(FAMILY) / "golden" / f"{stem}.cdm.json"
    (event,) = json.loads(golden_path.read_text(encoding="utf-8"))
    payload = S.authored_record(FAMILY, stem)
    assert payload["revision"]["semantic_sha256"] == want["semantic"]
    assert event["event_id"] == want["event_id"]
    assert event["payload"]["revision_key"] == want["revision_key"]
    assert event["payload"]["record_id"] == record_id
    assert event["source_ids"] == [{"external_id": okey, "system": "NSILI"}]
    assert event["payload"]["kind"] == f"{FAMILY}.record"
    assert event["payload"]["time_basis"] == want["basis"]
    assert event["payload"]["record"] == payload
    assert event["observed_at"] == want["observed_at"]
    assert event["received_at"] == S.FROZEN_TEXT
    assert event["source"]["source_hash"] == {"algorithm": "sha256", "value": want["raw"]}
    assert event["source"]["observed_at"] == (
        None if want["basis"] == "GATEWAY_RECEIPT" else want["observed_at"]
    )
    assert event["source"]["transformations"] == ["ISR-ID-001"]
    assert event["source"]["original_id"] == payload["origin"]["object_id"]
    assert (
        event["source"]["system"],
        event["source"]["adapter"],
        event["source"]["adapter_version"],
        event["source"]["format_name"],
        event["source"]["format_version"],
        event["source"]["record_index"],
        event["source"]["synthetic"],
    ) == ("NSILI", f"stanag4559_{FAMILY}", "1.0.0", "SC ISR gateway record", "1.0.0", 0, True)
    assert (event["event_type"], event["severity"], event["related_entities"]) == (
        "STATUS_CHANGE",
        "INFO",
        [],
    )
    assert (
        event["integrity"],
        event["oes"],
        event["quality"],
        event["status"],
        event["residual"],
        event["validity"],
        event["schema_version"],
    ) == (None, None, None, None, None, None, "3.2.0")
    assert event["geometry"] == (None if FAMILY == "workflow" else S.MOVED_GEOMETRY)
    rendered = S.adapter(FAMILY, clock=S.FROZEN_TEXT).to_cdm(payload)
    assert canonical.serialise(
        [o.model_dump(mode="json") for o in rendered]
    ) == golden_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("stem", list(S.CASES.values()))
def test_a_packaged_payload_translates_alike_as_octets_and_as_object(stem):
    """`to_cdm` takes the octets or the parsed object (L-09); the two give one Event."""
    path = S.fixture_dir(FAMILY) / f"{stem}.json"
    a = S.adapter(FAMILY).to_cdm(path.read_bytes())
    b = S.adapter(FAMILY).to_cdm(json.loads(path.read_text(encoding="utf-8")))
    assert a == b


@pytest.mark.parametrize("case", list(S.CASES))
def test_the_payloads_are_the_bundle_records_moved_and_redigested(case):
    """The authored payloads differ from the bundle's records in exactly what the builder states:
    the coverage moved by (+7, +7) degrees and the semantic digest recomputed (catalogue and
    stream), or nothing at all (workflow, byte for byte)."""
    source, stem = S.bundle_record(FAMILY, case), S.CASES[case]
    payload = S.authored_record(FAMILY, stem)
    if FAMILY == "workflow":
        assert (S.fixture_dir(FAMILY) / f"{stem}.json").read_bytes() == (
            S.BUNDLE / f"{FAMILY}-{case}.record.json"
        ).read_bytes()
        return
    assert source["body"]["coverage"]["coordinates"] == [
        [[14, 50], [15, 50], [15, 51], [14, 51], [14, 50]]
    ]
    assert payload["body"]["coverage"]["coordinates"] == [S.MOVED_RING]
    assert payload["revision"]["semantic_sha256"] == S.AUTHORED[FAMILY][stem]["semantic"]
    assert payload["revision"]["semantic_sha256"] != source["revision"]["semantic_sha256"]
    restored = S.mutated(
        payload,
        lambda d: (
            d["body"]["coverage"].update(
                {"coordinates": source["body"]["coverage"]["coordinates"]}
            ),
            d["revision"].update({"semantic_sha256": source["revision"]["semantic_sha256"]}),
        ),
    )
    assert restored == source


def test_the_fixture_set_is_listed_synthetic_and_inside_the_rectangle():
    """CONTRIBUTING.md's fixture rules: every payload listed synthetic in its PROVENANCE.json (the
    top level and `malformed/`), every position a payload or golden states inside the Baltic
    rectangle, the bundle's `test-` placeholders and `TEST_ONLY` labels, and the set exactly the
    three payloads and their goldens."""
    directory = S.fixture_dir(FAMILY)
    assert observation_support.provenance_problems(directory) == []
    stems = sorted(S.CASES.values())
    assert sorted(p.stem for p in directory.glob("*.json") if p.name != "PROVENANCE.json") == stems
    assert sorted(p.name for p in (directory / "golden").iterdir()) == [
        f"{s}.cdm.json" for s in stems
    ]
    for path in sorted(directory.glob("*.json")) + sorted((directory / "golden").glob("*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert observation_support.positions_outside_the_rectangle(document) == [], path.name
    for stem in stems:
        assert S.placeholder_problems(S.authored_record(FAMILY, stem)) == [], stem


def test_the_builder_check_is_current_and_the_three_builders_are_one(tmp_path):
    """CONTRIBUTING.md's builder rule, run as check.sh runs it (`python -I -B ... --check` from
    outside the tree): CURRENT, exit 0, nothing written. The three directories carry one builder,
    byte for byte, and its digest literals are the pin record's."""
    directory = S.fixture_dir(FAMILY)
    assert observation_support.builder_problems(directory, tmp_path) == []
    script = (directory / "spec" / "build_fixtures.py").read_bytes()
    for family in S.FAMILIES:
        assert (S.fixture_dir(family) / "spec" / "build_fixtures.py").read_bytes() == script
    pin = json.loads((directory / "spec" / "stanag4559_pin.json").read_text(encoding="utf-8"))
    assert pin["adapter"]["name"] == f"stanag4559_{FAMILY}"
    assert pin["adapter"]["ordinal"] == ORDINAL
    assert pin["standard"]["identifier"] == "SC ISR 4559 001"
    assert pin["standard"]["revision"] == "1.0" and pin["standard"]["carried_here"] is False
    assert pin["derivation"]["semantic_sha256"] == {
        f"{stem}.json": S.AUTHORED[FAMILY][stem]["semantic"] for stem in S.CASES.values()
    }
    readme = (S.BUNDLE / "README.md").read_text(encoding="utf-8")
    for entry in pin["bundle_files"]:
        if entry["carried_here"] is False:
            # The bundle's fixture manifest: pinned by digest, not carried (its object_key lines trip
            # the repository's secret scanner, and the repository admits no allowlist). Its content
            # is the literal tables of tests/stanag4559_support.py.
            assert entry["bundle_path"] == "examples/fixture-manifest.json"
            assert entry["sha256"] == S.BUNDLE_MANIFEST_SHA256
            assert "secret scanner" in entry["not_carried_because"] and "carried_at" not in entry
            assert "`fixture-manifest.json` (not carried, see above)" in readme
            assert entry["sha256"] in readme
            continue
        assert entry["carried_here"] is True
        carried = S.REPO / entry["carried_at"]
        assert carried.is_file(), entry["carried_at"]
        assert evidence.digest(carried)[0] == entry["sha256"], entry["carried_at"]
        if entry["carried_at"].startswith("tests/stanag4559_bundle/"):
            assert f"| `{carried.name}` | `{entry['sha256']}` |" in readme


# ============================================================== refusals: the malformed set


@pytest.mark.parametrize("name", S.malformed_names(FAMILY))
def test_every_malformed_payload_is_refused_by_its_rule(name):
    """Each file of `malformed/` breaks one rule and is refused by it, before any output, as the
    harness's loader hands it over (a `.json` parsed, an `.isr` as octets). Covers PARSE-001
    (duplicate key), PARSE-002 (NaN), PARSE-006's JSON counterpart (one container past the depth
    bound), CDM-010 and CDM-011."""
    raw = harness.load_raw(S.fixture_dir(FAMILY) / "malformed" / name)
    assert S.refusal(S.adapter(FAMILY).to_cdm, raw) == S.MALFORMED[name]


def test_the_malformed_set_is_the_table():
    """The directory holds exactly the cases the table names, and the octet ones are octets."""
    directory = S.fixture_dir(FAMILY) / "malformed"
    assert sorted(
        p.name for p in directory.iterdir() if p.name != "PROVENANCE.json"
    ) == S.malformed_names(FAMILY)
    assert json_nesting_depth((directory / "depth_over_cap.isr").read_text(encoding="utf-8")) == 97


def test_parse_001_a_duplicate_key_is_refused_on_octets_and_lost_in_a_parsed_twin():
    """PARSE-001 ("Reject before normalization"): the octets are refused `duplicate-key`. The
    limit the manifests state: a decoder that already parsed them kept the LAST value and said
    nothing, so the twin is a record of another tenant and cannot be told apart."""
    octets = (S.fixture_dir(FAMILY) / "malformed" / "duplicate_key.isr").read_bytes()
    assert S.refusal(S.adapter(FAMILY).to_cdm, octets) == "duplicate-key"
    collapsed = json.loads(octets)
    assert S.translate(collapsed)["payload"]["record"]["tenant_id"] == "test-tenant-b"


# ============================================================================ the declaration


def test_the_declaration_is_the_ruled_one():
    """L-01, L-03 to L-05 and L-09: provisional internal profile, claim PROVISIONAL, maturity L3,
    residual LEGACY, the format and its version, unknown keys refused, evidence available
    from the release that attaches the records, the two bounds with their basis, and ISR-ID-001
    the one derivation."""
    cls = load_adapter(f"stanag4559_{FAMILY}")
    meta = cls.metadata
    assert (cls.name, cls.version, cls.direction, cls.system, cls.FAMILY) == (
        f"stanag4559_{FAMILY}",
        "1.0.0",
        "ingest",
        "NSILI",
        FAMILY,
    )
    assert (meta.format.name, meta.format.version) == ("SC ISR gateway record", "1.0.0")
    assert meta.binding is WireBinding.PROVISIONAL_INTERNAL_PROFILE
    assert meta.claim_status is ClaimStatus.PROVISIONAL
    assert meta.maturity.level is MaturityLevel.L3 and meta.maturity.external_exercise is None
    assert meta.residual is ResidualStance.LEGACY
    assert meta.capabilities.unknown_fields is UnknownFields.NONE
    # The 3.9.0 release commit (2026-10-25) flips the evidence declaration they landed with.
    assert meta.evidence.available is True
    limits = meta.capabilities.limits
    assert (limits.max_input_bytes, limits.max_depth, limits.max_objects) == (16_777_216, 96, None)
    assert {k: v.kind for k, v in limits.declared_because.items()} == {
        "max_input_bytes": LimitKind.IMPLEMENTATION_CAP,
        "max_depth": LimitKind.IMPLEMENTATION_CAP,
    }
    assert "section 20" in limits.declared_because["max_input_bytes"].source
    assert "PROJECT" in limits.declared_because["max_input_bytes"].source
    ids = [entry.id for entry in meta.limitations]
    for required in (
        "provisional-internal-profile",
        "no-gateway",
        "transport-rules-on-octets",
        "dictionary-cardinality",
        "evidence-availability",
        "residual-legacy",
    ):
        assert required in ids
    text = {entry.id: entry.summary for entry in meta.limitations}
    assert text["evidence-availability"] == (
        "the evidence RECORD for this adapter is not IN the distribution: `evidence/` is "
        "untracked and unpackaged, CI generates the set on every run, and the release pipeline "
        "generates the records for every shipped adapter and attaches them to the GitHub "
        "Release of the version it publishes. `evidence.available` is true because every "
        "published distribution that carries this adapter has that Release, so its records "
        "are retrievable by a third party; it says nothing about what the wheel contains"
    )
    assert set(cls.TRANSFORMS) == {
        "tenant_id",
        "security_domain",
        "origin.authority",
        "family",
        "origin.object_id",
        "revision.token",
        "revision.semantic_sha256",
    }
    assert all(reason.startswith("derived: ISR-ID-001") for reason in cls.TRANSFORMS.values())
    assert getattr(cls.to_cdm, "__input_bounded__", False) and "to_cdm" in vars(cls)


def test_from_cdm_is_the_ingest_only_refusal():
    """Section 5: `from_cdm` stays unimplemented for these ingest-only classes."""
    event = S.adapter(FAMILY).to_cdm(S.bundle_record(FAMILY, "basic"))
    with pytest.raises(NotImplementedError, match="ingest-only"):
        S.adapter(FAMILY).from_cdm(event)


def test_the_bounds_refuse_one_octet_and_one_container_past_them():
    """PARSE-005 ("Abort at configured byte bound", the 16 MiB of section 20) and the depth bound,
    each before the decoder. Since L-11 (amended 2026-10-25) the size case is fed in memory, never
    shipped as a file: the basic payload padded with spaces to exactly `max_input_bytes`
    (16 777 216 octets) passes the bound and translates, and one octet more is refused
    `InputTooLarge`; 16 777 217 spaces refused, 17 MiB refused, a parsed object nesting 97
    refused, and 96 passes the depth check."""
    cls = load_adapter(f"stanag4559_{FAMILY}")
    record = (S.fixture_dir(FAMILY) / "basic.json").read_bytes()
    at_bound = record + b" " * (cls.metadata.capabilities.limits.max_input_bytes - len(record))
    assert len(at_bound) == 16_777_216
    assert enforce_input_bound(cls, at_bound) is None
    assert S.translate(at_bound, FAMILY)["event_id"] == S.AUTHORED[FAMILY]["basic"]["event_id"]
    with pytest.raises(InputTooLarge, match="handed 16777217 octets"):
        cls().to_cdm(at_bound + b" ")
    with pytest.raises(InputTooLarge):
        cls().to_cdm(b" " * 16_777_217)
    with pytest.raises(InputTooLarge):
        cls().to_cdm(b"{" + b" " * (17 * 1024 * 1024) + b"}")
    deep: dict = {}
    for _ in range(96):
        deep = {"n": deep}
    with pytest.raises(InputTooDeep, match="nesting 97 containers deep"):
        cls().to_cdm(deep)
    assert enforce_depth_bound(cls, deep["n"]) is None


def test_the_ledger_reads_no_loss():
    """The lossless ledger over each payload: no LOST leaf, the projections MAPPED (catalogue and
    stream: origin.object_id, raw_ref.sha256, kind, source_time, coverage.type and the ten
    coordinates, fifteen; workflow: the first four), every other leaf RESIDUAL under
    payload.record."""
    cls = load_adapter(f"stanag4559_{FAMILY}")
    for stem in S.CASES.values():
        payload = S.authored_record(FAMILY, stem)
        objects = [o.model_dump(mode="json") for o in S.adapter(FAMILY).to_cdm(payload)]
        entries = lossless.ledger(payload, objects, cls.MAPPINGS).entries
        categories = [entry.category for entry in entries]
        assert "LOST" not in categories
        assert set(categories) == {"MAPPED", "RESIDUAL"}
        assert categories.count("MAPPED") == (4 if FAMILY == "workflow" else 15)


# ================================================================ CDM-007: a footprint, nothing more


def test_cdm_007_a_footprint_is_coverage_only():
    """CDM-007 ("Coverage only; no invented Entity"): one Event, no related entity, the polygon
    as the Event's geometry and nothing else — no Entity, no point at the box's centre — while the
    record keeps the integers it stated."""
    record = S.bundle_record(FAMILY, "basic")
    objects = S.adapter(FAMILY).to_cdm(record)
    assert [o.object_kind for o in objects] == ["event"]
    event = objects[0].model_dump(mode="json")
    assert event["related_entities"] == []
    assert event["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[14.0, 50.0], [15.0, 50.0], [15.0, 51.0], [14.0, 51.0], [14.0, 50.0]]],
    }
    assert event["payload"]["record"]["body"]["coverage"]["coordinates"] == [
        [[14, 50], [15, 50], [15, 51], [14, 51], [14, 50]]
    ]


def test_a_multipolygon_coverage_and_a_null_coverage_translate():
    """Section 8 admits a MultiPolygon footprint and a null one ("If ambiguous, leave normalized
    coverage null"): the first is the Event's geometry, the second leaves it null."""
    record = S.authored_record(FAMILY, "basic")
    multi = S.mutated(
        record,
        lambda d: d["body"].update(
            {
                "coverage": {
                    "type": "MultiPolygon",
                    "coordinates": [[S.MOVED_RING], [[[23, 57], [24, 57], [24, 58], [23, 57]]]],
                }
            }
        ),
    )
    assert S.translate(multi)["geometry"] == {
        "type": "MultiPolygon",
        "coordinates": [
            [[[21.0, 57.0], [22.0, 57.0], [22.0, 58.0], [21.0, 58.0], [21.0, 57.0]]],
            [[[23.0, 57.0], [24.0, 57.0], [24.0, 58.0], [23.0, 57.0]]],
        ],
    }
    empty = S.mutated(record, lambda d: d["body"].update({"coverage": None}))
    assert S.translate(empty)["geometry"] is None


def test_product_files_are_references_carried_and_never_opened(monkeypatch):
    """Section 12 is the gateway's: a record naming a product, a thumbnail and a related file is
    translated without a file being opened or a socket being made, and the references are
    carried verbatim."""
    record = S.mutated(
        S.authored_record(FAMILY, "basic"),
        lambda d: d["body"].update(
            {
                "files": [
                    {
                        "checksum": {"algorithm": "sha256", "value": "00" * 32},
                        "file_id": "f-1",
                        "locator": "file:///etc/passwd",
                        "media_type": "image/tiff",
                        "name": "product",
                        "role": "PRODUCT",
                        "security_override": None,
                        "size_bytes": "1048576",
                    },
                    {
                        "checksum": None,
                        "file_id": "f-2",
                        "locator": "https://example.invalid/thumb.png",
                        "media_type": None,
                        "name": None,
                        "role": "THUMBNAIL",
                        "security_override": None,
                        "size_bytes": None,
                    },
                ]
            }
        ),
    )
    isr_record.schema()
    _forbid_io(monkeypatch)
    event = S.translate(record)
    assert event["payload"]["record"]["body"]["files"] == record["body"]["files"]


def _forbid_io(monkeypatch):
    """No file and no socket from here on: `open` and `socket.socket` raise."""
    import builtins
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError("the translator opened a file or a socket")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(socket, "socket", refuse)


# ====================================================== the record contract, family by family
#
# What follows tests `synapse_cdm.isr_record` itself: section 6's transport rules, section 7's
# identity and section 28's second pass. They do not depend on the family, so they are here once;
# each family's module replays its own bundle records and malformed set through them.

BASIC = S.bundle_record("catalog", "basic")
TEXT = (S.BUNDLE / "catalog-basic.record.json").read_text(encoding="utf-8")


def _refuse_text(text: str | bytes) -> str:
    raw = text if isinstance(text, bytes) else text.encode("utf-8")
    return S.refusal(S.adapter("catalog").to_cdm, raw)


@pytest.mark.parametrize(
    "label, octets, code",
    [
        ("byte-order mark", b"\xef\xbb\xbf" + TEXT.encode(), "byte-order-mark"),
        (
            "invalid utf-8",
            TEXT.replace("Synthetic ISR", "Synthetic \udcff ISR", 1).encode(
                "utf-8", "surrogateescape"
            ),
            "not-utf8",
        ),
        ("utf-16 with its byte-order mark", TEXT.encode("utf-16"), "not-utf8"),
        ("utf-16 without a mark", TEXT.encode("utf-16-le"), "not-json"),
        ("trailing document", (TEXT + TEXT).encode(), "trailing-document"),
        ("trailing text", (TEXT + "x").encode(), "trailing-document"),
        ("non-JSON whitespace after the value", (TEXT + "\u3000").encode(), "trailing-document"),
        ("NaN", TEXT.replace('"ordinal": 1', '"ordinal": NaN').encode(), "non-finite-number"),
        (
            "Infinity",
            TEXT.replace('"ordinal": 1', '"ordinal": Infinity').encode(),
            "non-finite-number",
        ),
        (
            "-Infinity",
            TEXT.replace('"ordinal": 1', '"ordinal": -Infinity').encode(),
            "non-finite-number",
        ),
        (
            "an overflowing number",
            TEXT.replace('"ordinal": 1', '"ordinal": 1e999').encode(),
            "non-finite-number",
        ),
        (
            "2**53",
            TEXT.replace('"ordinal": 1', '"ordinal": 9007199254740992').encode(),
            "integer-out-of-range",
        ),
        (
            "a 400-digit integer",
            TEXT.replace('"ordinal": 1', '"ordinal": ' + "9" * 400).encode(),
            "integer-out-of-range",
        ),
        (
            "duplicate key",
            TEXT.replace(
                '"tenant_id": "test-tenant"', '"tenant_id": "a", "tenant_id": "test-tenant"'
            ).encode(),
            "duplicate-key",
        ),
        (
            "duplicate nested key",
            TEXT.replace('"ordinal": 1,', '"ordinal": 1, "ordinal": 2,').encode(),
            "duplicate-key",
        ),
        (
            "lone surrogate escape",
            TEXT.replace("Synthetic ISR", "Synthetic \\udc00 ISR").encode(),
            "lone-surrogate",
        ),
        ("an array", b"[]", "not-an-object"),
        ("a string", b'"record"', "not-an-object"),
        ("truncated", TEXT[:200].encode(), "not-json"),
        (
            "a raw control character",
            TEXT.replace("Synthetic ISR", "Synthetic\x01ISR").encode(),
            "not-json",
        ),
        ("empty", b"", "not-json"),
    ],
)
def test_parse_section_6_transport_rules_on_octets(label, octets, code):
    """Section 6's transport rules, each refused on octets with its own code before any output:
    PARSE-001 (duplicate keys) and PARSE-002 (NaN, the infinities) among them."""
    assert _refuse_text(octets) == code, label


def test_parse_whitespace_around_the_value_is_not_a_trailing_document():
    """JSON's own whitespace before and after the value is not a second document."""
    assert (
        S.translate((" \t\r\n" + TEXT + "\n\n  ").encode(), "catalog")["event_id"]
        == S.BUNDLE_IDENTITY["catalog-basic"][3]
    )


def test_parse_text_is_held_to_the_same_rules_and_other_inputs_are_refused():
    """Text is octets already decoded: a leading U+FEFF is refused, and the same record as text
    translates. Anything that is neither octets, text nor an object is refused."""
    assert S.refusal(isr_record.parse, "\ufeff" + TEXT) == "byte-order-mark"
    assert S.translate(TEXT, "catalog")["event_id"] == S.BUNDLE_IDENTITY["catalog-basic"][3]
    assert S.refusal(isr_record.parse, 42) == "unsupported-input"
    for value in (42, None, [BASIC], ("tuple",)):
        assert S.refusal(S.adapter("catalog").to_cdm, value) == "not-an-object"


def _nested_value_record(levels: int) -> tuple[dict, str]:
    """The unknown-extension record with its first graph attribute's free-form `value` replaced by
    `levels` nested empty arrays, as an object and as text. Built without recursion (neither
    `copy.deepcopy` nor `json.dumps` can take the deepest case on every interpreter)."""
    record = S.bundle_record("catalog", "unknown-extension")
    value: list = []
    for _ in range(levels - 1):
        value = [value]
    _attribute(record)["value"] = "@@VALUE@@"
    text = json.dumps(record).replace('"@@VALUE@@"', "[" * levels + "]" * levels, 1)
    _attribute(record)["value"] = value
    return record, text


def test_the_record_module_holds_its_own_depth_bound_on_both_paths():
    """`isr_record.parse` and `isr_record.validate` are this module's entries, and a direct caller
    has no adapter base class in front of them (the review of 2026-10-24 found `parse` raising
    `RecursionError` at 1 000 containers on 3.11 and 100 000 on 3.12, and accepting both on 3.14).
    Each refuses a record nesting past `isr_record.MAX_DEPTH` itself, `depth-over-cap`, with one
    verdict on every interpreter: `parse` reads the depth off the characters before the decoder
    recurses, `validate` walks without recursing. A record nesting exactly the cap passes both and
    translates; and behind a translator the base class refuses one container more at the same
    number first (`InputTooDeep`)."""
    cls = load_adapter("stanag4559_catalog")
    assert isr_record.MAX_DEPTH == 96 == cls.metadata.capabilities.limits.max_depth
    # The attribute's object is the seventh container, so `levels` arrays nest 7 + levels.
    at_cap, at_cap_text = _nested_value_record(89)
    assert container_depth(at_cap) == json_nesting_depth(at_cap_text) == 96
    assert isr_record.validate(isr_record.parse(at_cap_text)) == at_cap
    assert isr_record.validate(at_cap) is at_cap
    assert S.translate(at_cap_text, "catalog")["payload"]["record"] == at_cap

    past, past_text = _nested_value_record(90)
    assert container_depth(past) == json_nesting_depth(past_text) == 97
    assert S.refusal(isr_record.parse, past_text) == "depth-over-cap"
    assert S.refusal(isr_record.parse, past_text.encode("utf-8")) == "depth-over-cap"
    assert S.refusal(isr_record.validate, past) == "depth-over-cap"
    assert S.refusal(cls().to_cdm, past_text.encode("utf-8")) == "InputTooDeep"
    assert S.refusal(cls().to_cdm, past) == "InputTooDeep"

    for levels in (1_000, 100_000):
        _, text = _nested_value_record(levels)
        assert S.refusal(isr_record.parse, text) == "depth-over-cap", levels
        assert S.refusal(isr_record.parse, text.encode("utf-8")) == "depth-over-cap", levels
    deep, _ = _nested_value_record(1_000)
    with pytest.raises(isr_record.IsrRecordRefused) as refused:
        isr_record.validate(deep)
    assert refused.value.code == "depth-over-cap"
    assert str(refused.value).startswith("depth-over-cap: /body/graph/nodes/0/attributes/0/value/")


@pytest.mark.parametrize(
    "label, mutate, code",
    [
        (
            "NaN in the free-form graph value",
            lambda d: _attribute(d).update({"value": float("nan")}),
            "non-finite-number",
        ),
        (
            "an infinity in the free-form graph value",
            lambda d: _attribute(d).update({"value": float("inf")}),
            "non-finite-number",
        ),
        (
            "an integer past 2**53-1",
            lambda d: _attribute(d).update({"value": 2**64 - 1}),
            "integer-out-of-range",
        ),
        ("a tuple", lambda d: _attribute(d).update({"value": ("a", "b")}), "not-a-json-value"),
        ("bytes", lambda d: _attribute(d).update({"value": b"octets"}), "not-a-json-value"),
        (
            "a key that is not a string",
            lambda d: _attribute(d).update({"value": {1: "one"}}),
            "non-string-key",
        ),
        (
            "a lone surrogate in a key",
            lambda d: _attribute(d).update({"value": {"k\ud800": 1}}),
            "lone-surrogate",
        ),
        (
            "a dict subclass",
            lambda d: _attribute(d).update({"value": _Sub(a=1)}),
            "not-a-json-value",
        ),
    ],
)
def test_values_a_parsed_record_can_still_break(label, mutate, code):
    """What survives a parse and is still refused on the dict path: the stock JSON Schema validator
    accepts every one of these in the free-form graph `value` (`{}`)."""
    record = S.mutated(S.bundle_record("catalog", "unknown-extension"), mutate)
    assert S.refuse_record(record) == code, label


class _Sub(dict):
    """A mapping that is not plain JSON: it could redefine what it holds."""


def _attribute(record: dict) -> dict:
    return S.graph_of(record)["nodes"][0]["attributes"][0]


def test_a_non_finite_graph_value_passes_the_stock_schema_and_not_this_module():
    """Why the value scan exists: the bundle's own validator accepts NaN where `value` is `{}`."""
    record = S.mutated(
        S.bundle_record("catalog", "unknown-extension"),
        lambda d: _attribute(d).update({"value": float("nan")}),
    )
    assert list(jsonschema.Draft202012Validator(isr_record.schema()).iter_errors(record)) == []
    assert S.refuse_record(record) == "non-finite-number"


# -- the contract ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label, mutate, code, where",
    [
        ("unknown body key", lambda d: d["body"].update({"x": 1}), "unknown-key", "/body/x"),
        ("unknown origin key", lambda d: d["origin"].update({"x": 1}), "unknown-key", "/origin/x"),
        ("missing body member", lambda d: d["body"].pop("title"), "missing-field", "/body/title"),
        ("missing revision", lambda d: d.pop("revision"), "missing-field", "/revision"),
        (
            "wrong schema id",
            lambda d: d.update({"schema": "urn:other"}),
            "schema-violation",
            "/schema",
        ),
        (
            "change not in the vocabulary",
            lambda d: d.update({"change": "DELETE"}),
            "schema-violation",
            "/change",
        ),
        (
            "ordinal negative",
            lambda d: d["revision"].update({"ordinal": -1}),
            "schema-violation",
            "/revision/ordinal",
        ),
        (
            "raw digest with a final newline",
            lambda d: d["raw_ref"].update({"sha256": d["raw_ref"]["sha256"] + "\n"}),
            "schema-violation",
            "/raw_ref/sha256",
        ),
        ("empty tenant", lambda d: d.update({"tenant_id": ""}), "schema-violation", "/tenant_id"),
        (
            "DECLARED label without classification",
            lambda d: d["security"]["content"].update({"classification": ""}),
            "schema-violation",
            "/security/content/classification",
        ),
        (
            "longitude past 180",
            lambda d: d["body"]["coverage"]["coordinates"][0][1].__setitem__(0, 181),
            "schema-violation",
            "/body/coverage/coordinates/0/1/0",
        ),
        (
            "a three-position ring",
            lambda d: d["body"]["coverage"].update(
                {"coordinates": [[[14, 50], [15, 50], [14, 50]]]}
            ),
            "schema-violation",
            "/body/coverage/coordinates/0",
        ),
    ],
)
def test_the_contract_refuses_by_path_and_keyword(label, mutate, code, where):
    """The published schema, each failure named by its path and code, never by its value."""
    record = S.mutated(BASIC, mutate)
    with pytest.raises(isr_record.IsrRecordRefused) as refused:
        S.adapter("catalog").to_cdm(record)
    assert refused.value.code == code, label
    assert str(refused.value).startswith(f"{code}: {where}:"), str(refused.value)


def test_refusals_name_paths_and_never_quote_the_record():
    """A diagnostic is published and a record carries labels: no refusal text repeats a value."""
    secret = "SECRET-LABEL-VALUE"
    cases = [
        lambda d: d.update({"tenant_id": secret, "change": "DELETE"}),
        lambda d: d["security"]["content"].update({"scheme": secret, "marking_state": "NEW"}),
        lambda d: d.update({"source_time": "2026-02-30T00:00:00.000Z", "tenant_id": secret}),
        lambda d: d["origin"].update({"object_id": secret + "\ud800"}),
        lambda d: d["body"].update({"title": secret, "temporal_end": "2026-10-04T09:00:00.000Z"}),
    ]
    for mutate in cases:
        with pytest.raises(isr_record.IsrRecordRefused) as refused:
            S.adapter("catalog").to_cdm(S.mutated(BASIC, mutate))
        assert secret not in str(refused.value) and "2026-02-30" not in str(refused.value)


def test_a_refusal_survives_a_pickle_with_its_code():
    """The conformance suite refuses payloads in a worker process and ships the exception back."""
    import pickle

    with pytest.raises(isr_record.IsrRecordRefused) as refused:
        S.adapter("catalog").to_cdm(S.mutated(BASIC, lambda d: d.update({"x": 1})))
    again = pickle.loads(pickle.dumps(refused.value))
    assert (type(again), again.code, str(again)) == (
        isr_record.IsrRecordRefused,
        "unknown-key",
        str(refused.value),
    )


def test_the_contract_is_the_bundle_s_file_read_from_package_data():
    """L-08: the schema is package data, byte for byte the bundle's contract, read through
    `importlib.resources`."""
    import importlib.resources

    resource = (
        importlib.resources.files("synapse_cdm") / "registry" / "isr" / "isr-record.schema.json"
    )
    data = resource.read_bytes()
    assert (
        evidence.digest_bytes(data)[0]
        == "881f9cbfd8c564a1d4e6b7d820d3b1a27a8bcfdc9676825a10e105d2dc17d621"
    )
    assert isr_record.schema() == json.loads(data)
    assert isr_record.schema()["$id"] == isr_record.RECORD_SCHEMA_ID


# -- section 28: timestamps, the interval, the identity scope -------------------------------------


@pytest.mark.parametrize(
    "value, code",
    [
        ("\u0662\u0660\u0662\u0666-10-04T12:00:00.000Z", "bad-timestamp"),
        ("2026-10-04T12:00:00.000Z\n", "schema-violation"),
        ("2026-10-04T12:00:00Z", "schema-violation"),
        ("2026-10-04T12:00:00.000+00:00", "schema-violation"),
        ("2026-10-04T12:00:00.000z", "schema-violation"),
        ("2026-10-04 12:00:00.000Z", "schema-violation"),
        ("2026-02-30T00:00:00.000Z", "impossible-instant"),
        ("2026-12-31T23:59:60.000Z", "impossible-instant"),
        ("2026-13-01T00:00:00.000Z", "impossible-instant"),
        ("0000-01-01T00:00:00.000Z", "impossible-instant"),
        ("2026-10-04T24:00:00.000Z", "impossible-instant"),
        ("2026-10-04T23:60:00.000Z", "impossible-instant"),
    ],
)
def test_section_28_timestamps_are_one_form_and_real_instants(value, code):
    """Section 6: one lexical form, impossible dates refused, a literal second 60 never changed to
    59. A form the contract's own pattern refuses (read as ECMA-262 reads it) is a
    `schema-violation` of that pattern; the second pass refuses what the pattern lets through in
    Python, which reads `\\d` as any script's digit (`bad-timestamp`), and every date or time that
    does not exist (`impossible-instant`) — `T24:00` included, which 3.14's `fromisoformat` would
    read as the next midnight. Each is refused in source_time, captured_at and every body
    timestamp field, at its own path."""
    fields = [
        ("source_time",),
        ("captured_at",),
        ("body", "created_at"),
        ("body", "modified_at"),
        ("body", "temporal_start"),
        ("body", "temporal_end"),
    ]
    for path in fields:

        def put(d, path=path):
            (d if len(path) == 1 else d[path[0]]).update({path[-1]: value})

        with pytest.raises(isr_record.IsrRecordRefused) as refused:
            S.adapter("catalog").to_cdm(S.mutated(BASIC, put))
        assert refused.value.code == code
        assert str(refused.value).startswith(f"{code}: /{'/'.join(path)}:")


def test_section_28_the_stock_validator_lets_impossible_dates_through():
    """Why the timestamps are checked here: the bundle's validator (format checking on) accepts
    each of these, and this module refuses each — the trailing newline by the contract's pattern
    read as ECMA-262 reads `$`, the rest by the second pass."""
    stock = jsonschema.Draft202012Validator(
        isr_record.schema(), format_checker=jsonschema.FormatChecker()
    )
    want = {
        "2026-02-30T00:00:00.000Z": "impossible-instant",
        "2026-12-31T23:59:60.000Z": "impossible-instant",
        "2026-10-04T12:00:00.000Z\n": "schema-violation",
        "\u0662\u0660\u0662\u0666-10-04T12:00:00.000Z": "bad-timestamp",
    }
    for value in want:
        record = S.mutated(BASIC, lambda d: d.update({"source_time": value}))
        assert list(stock.iter_errors(record)) == [], value
        assert S.refuse_record(record) == want[value], value


def test_section_28_a_source_interval_runs_forwards():
    """Every source interval with two bounds has start <= end: reversed is refused, equal bounds
    and an open end are accepted."""
    reversed_ = S.mutated(
        BASIC,
        lambda d: d["body"].update(
            {
                "temporal_start": "2026-10-04T11:00:00.001Z",
                "temporal_end": "2026-10-04T11:00:00.000Z",
            }
        ),
    )
    assert S.refuse_record(reversed_) == "interval-reversed"
    equal = S.mutated(
        BASIC, lambda d: d["body"].update({"temporal_start": "2026-10-04T11:00:00.000Z"})
    )
    assert S.translate(equal)["event_id"]
    open_end = S.mutated(BASIC, lambda d: d["body"].update({"temporal_end": None}))
    assert S.translate(open_end)["event_id"]


def test_section_28_local_library_scope_binds_the_authority_to_the_library():
    """`identity_scope=LOCAL_LIBRARY requires origin.authority=library_id` (sections 7 and 28)."""
    local = S.mutated(BASIC, lambda d: d["body"].update({"identity_scope": "LOCAL_LIBRARY"}))
    assert S.refuse_record(local) == "local-library-authority"
    local["origin"]["authority"] = local["library_id"]
    event = S.translate(local)
    assert isr_record.canonical_array(
        ["test-tenant", "test-domain", "test-library-a", "catalog", "catalog-basic"]
    ) in _decoded(event["source_ids"][0]["external_id"])


def _decoded(key: str) -> str:
    import base64

    return base64.urlsafe_b64decode(key + "=" * (-len(key) % 4)).decode("utf-8")


# -- section 28: the geometry ----------------------------------------------------------------------


def _with_geometry(geometry) -> dict:
    return S.mutated(
        S.authored_record("catalog", "basic"), lambda d: d["body"].update({"coverage": geometry})
    )


def _poly(*rings) -> dict:
    return {"type": "Polygon", "coordinates": [list(map(list, ring)) for ring in rings]}


def _multi(*polygons) -> dict:
    return {
        "type": "MultiPolygon",
        "coordinates": [[list(map(list, ring)) for ring in polygon] for polygon in polygons],
    }


SQUARE = [(21, 57), (23, 57), (23, 58), (21, 58), (21, 57)]
INNER = [(21.5, 57.25), (22, 57.25), (22, 57.5), (21.5, 57.25)]


@pytest.mark.parametrize(
    "label, geometry, code",
    [
        (
            "ring not closed",
            _poly([(21, 57), (22, 57), (22, 58), (21, 58), (21, 57.5)]),
            "ring-not-closed",
        ),
        (
            "repeated vertex",
            _poly([(21, 57), (22, 57), (22, 58), (22, 57), (21, 58), (21, 57)]),
            "ring-repeated-vertex",
        ),
        ("collinear, no area", _poly([(21, 57), (22, 57), (23, 57), (21, 57)]), "ring-degenerate"),
        (
            "bowtie",
            _poly([(21, 57), (24, 58), (24, 56), (21, 58), (21, 57)]),
            "ring-self-intersects",
        ),
        (
            "a vertex on a non-adjacent edge",
            _poly([(21, 57), (23, 57), (23, 58), (22, 57), (21, 58), (21, 57)]),
            "ring-self-intersects",
        ),
        (
            "a spike folding back",
            _poly([(21, 57), (23, 57), (22, 57), (22, 58), (21, 57)]),
            "ring-self-intersects",
        ),
        (
            "hole crossing the exterior",
            _poly(SQUARE, [(22, 57.5), (24, 57.5), (24, 57.75), (22, 57.5)]),
            "rings-cross",
        ),
        (
            "hole sharing an edge with the exterior",
            _poly(SQUARE, [(21, 57), (22, 57), (21.5, 57.5), (21, 57)]),
            "rings-cross",
        ),
        (
            "hole outside the exterior",
            _poly(SQUARE, [(23.5, 57.25), (24, 57.25), (24, 57.5), (23.5, 57.25)]),
            "hole-outside-exterior",
        ),
        (
            "hole inside another hole",
            _poly(
                SQUARE,
                [(21.2, 57.1), (22.8, 57.1), (22.8, 57.9), (21.2, 57.9), (21.2, 57.1)],
                INNER,
            ),
            "holes-nested",
        ),
        (
            "parts overlapping",
            _multi([SQUARE], [[(22, 57.5), (24, 57.5), (24, 58.2), (22, 57.5)]]),
            "rings-cross",
        ),
        ("a part inside another part", _multi([SQUARE], [INNER]), "parts-overlap"),
        ("duplicate parts", _multi([SQUARE], [SQUARE]), "rings-cross"),
    ],
)
def test_section_28_polygon_topology_is_refused_by_rule(label, geometry, code):
    """Section 28: closed rings, distinct nondegenerate vertices and valid polygon topology, read
    as the module docstring states (OGC rules decided at edges and vertices, exactly)."""
    assert S.refuse_record(_with_geometry(geometry)) == code, label


@pytest.mark.parametrize(
    "label, geometry",
    [
        ("square", _poly(SQUARE)),
        ("square with a hole", _poly(SQUARE, INNER)),
        (
            "hole touching the exterior at one point",
            _poly(SQUARE, [(21, 57.5), (21.5, 57.25), (21.5, 57.75), (21, 57.5)]),
        ),
        (
            "collinear vertex on a straight edge",
            _poly([(21, 57), (22, 57), (23, 57), (23, 58), (21, 57)]),
        ),
        ("disjoint parts", _multi([SQUARE], [[(23.5, 57), (24, 57), (24, 58), (23.5, 57)]])),
        (
            "parts touching at a point",
            _multi([SQUARE], [[(23, 58), (24, 58), (24, 58.4), (23, 58)]]),
        ),
        (
            "a part inside another part's hole",
            _multi(
                [SQUARE, [(21.2, 57.1), (22.8, 57.1), (22.8, 57.9), (21.2, 57.9), (21.2, 57.1)]],
                [INNER],
            ),
        ),
        ("clockwise exterior", _poly(list(reversed(SQUARE)))),
    ],
)
def test_section_28_valid_polygons_are_accepted(label, geometry):
    """The same rules accept what OGC calls valid: holes, touching at a point, collinear vertices,
    disjoint and nested-in-a-hole parts, either orientation."""
    event = S.translate(_with_geometry(geometry))
    assert event["geometry"]["type"] == geometry["type"]


def test_section_28_the_polygon_tests_are_exact():
    """Every orientation is decided in exact integer arithmetic over the coordinates' common
    binary denominator. A triangle 1e-300 degrees across has a non-zero area that a float cross
    product underflows to 0.0, and is accepted; the same triangle with its third vertex on the
    first edge's line is refused as degenerate."""
    assert 1e-300 * 1e-300 == 0.0
    tiny = _poly([(0, 0), (1e-300, 0), (0, 1e-300), (0, 0)])
    assert S.translate(_with_geometry(tiny))["geometry"]["type"] == "Polygon"
    flat = _poly([(0, 0), (1e-300, 0), (2e-300, 0), (0, 0)])
    assert S.refuse_record(_with_geometry(flat)) == "ring-degenerate"


def test_section_28_a_geometry_past_the_cap_is_refused_before_it_is_examined():
    """PARSE-008's counterpart in a pure translator: section 28's polygon pass is the one that is
    not linear, so a geometry of more than `MAX_GEOMETRY_POSITIONS` positions is refused
    (`geometry-over-cap`) before any ring is examined, and the cap's own size is accepted."""
    assert isr_record.MAX_GEOMETRY_POSITIONS == 2048
    over = [(21 + i * 1e-4, 57) for i in range(2047)] + [(22, 58), (21, 57)]
    assert len(over) == 2049
    assert S.refuse_record(_with_geometry(_poly(over))) == "geometry-over-cap"
    at = [(21 + i * 1e-4, 57) for i in range(2046)] + [(22, 58), (21, 57)]
    assert S.translate(_with_geometry(_poly(at)))["geometry"]["type"] == "Polygon"


def test_a_huge_invalid_geometry_is_refused_before_the_schema_builds_an_error_per_position():
    """The cap is held BEFORE the schema: the contract states a geometry as `anyOf`, and a validator
    judging `anyOf` collects every error of every branch, so 100 000 out-of-range positions would
    otherwise build hundreds of thousands of error objects inside the size bound. Refused
    `geometry-over-cap`, at once, on both paths."""
    ring = [[181, 91]] * 100_000
    record = _with_geometry({"type": "Polygon", "coordinates": [ring]})
    started = time.perf_counter()
    assert S.refuse_record(record) == "geometry-over-cap"
    assert S.refuse_record(json.dumps(record).encode(), "catalog") == "geometry-over-cap"
    assert time.perf_counter() - started < 30.0


def test_section_28_the_polygon_pass_is_bounded_at_the_cap():
    """The worst arrangement measured when the cap was chosen — a sawtooth ring of 2 047 positions
    whose edges' boxes nearly all overlap — is checked in well under the bound asserted here; a
    regression to a slower algorithm would not be."""
    ring = []
    for i in range(1022):
        ring += [(21.0, 57.0 + i * 1e-4), (24.0, 57.5 + i * 1e-4)]
    ring += [(20.5, ring[-1][1] + 0.01), (20.5, 56.9), (21.0, 56.9), (21.0, 57.0)]
    assert len(ring) <= 2048
    started = time.perf_counter()
    assert S.translate(_with_geometry(_poly(ring)))["geometry"]["type"] == "Polygon"
    assert time.perf_counter() - started < 30.0


# -- section 28: the graph -------------------------------------------------------------------------


def _with_graph(nodes, edges=()) -> dict:
    return S.mutated(
        S.authored_record("catalog", "basic"),
        lambda d: d["body"].update({"graph": {"nodes": nodes, "edges": list(edges)}}),
    )


def _node(node_id, *attributes, entity="urn:synthetic:NSIL_PART") -> dict:
    return {"attributes": list(attributes), "entity": entity, "id": node_id}


def _attr(name, occurrence, value="v", nil=False, lexical="v", source_type="string") -> dict:
    return {
        "lexical": lexical,
        "name": name,
        "nil": nil,
        "occurrence": occurrence,
        "source_type": source_type,
        "value": value,
    }


@pytest.mark.parametrize(
    "label, nodes, edges, code",
    [
        ("duplicate node id", [_node("n1"), _node("n1")], [], "graph-duplicate-node"),
        (
            "edge to no node",
            [_node("n1")],
            [{"relation": "r", "source": "n1", "target": "n2"}],
            "graph-dangling-edge",
        ),
        (
            "edge from no node",
            [_node("n1")],
            [{"relation": "r", "source": "n0", "target": "n1"}],
            "graph-dangling-edge",
        ),
        (
            "occurrences 0 and 2",
            [_node("n1", _attr("a", 0), _attr("a", 2))],
            [],
            "graph-occurrence-gap",
        ),
        (
            "occurrences out of order",
            [_node("n1", _attr("a", 1), _attr("a", 0))],
            [],
            "graph-occurrence-gap",
        ),
        ("occurrence starting at 1", [_node("n1", _attr("a", 1))], [], "graph-occurrence-gap"),
        ("nil with a value", [_node("n1", _attr("a", 0, nil=True))], [], "graph-nil-with-value"),
        (
            "no value and no lexical form",
            [_node("n1", _attr("a", 0, value=None, lexical=None))],
            [],
            "graph-value-unretained",
        ),
    ],
)
def test_section_28_graph_rules_are_refused_by_rule(label, nodes, edges, code):
    """Section 28: every edge resolves to a node, node ids are unique, occurrence indices of a
    repeated attribute run from zero, nil=true requires value=null, and (the proposed reading of
    "lexical then retain[s] the complete source value") a value that is not nil keeps a value or
    its lexical form."""
    assert S.refuse_record(_with_graph(nodes, edges)) == code, label


def test_parse_009_repeated_part_entities_and_their_edges_are_all_retained():
    """PARSE-009 ("All instances and edges retained"): three instances of one part entity, a
    repeated attribute occurring three times, a nil attribute, an attribute whose conversion is
    unknown (value null, lexical kept) and the edges between them all reach payload.record in
    order, unchanged."""
    nodes = [
        _node(
            "p1",
            _attr("urn:synthetic:partNumber", 0, "1"),
            _attr("urn:synthetic:alias", 0),
            _attr("urn:synthetic:alias", 1, "w", lexical="w"),
            _attr("urn:synthetic:alias", 2, "x", lexical="x"),
        ),
        _node(
            "p2",
            _attr("urn:synthetic:partNumber", 0, "2"),
            _attr("urn:synthetic:note", 0, value=None, nil=True, lexical=None),
        ),
        _node(
            "p3",
            _attr("urn:synthetic:partNumber", 0, "3"),
            _attr("urn:synthetic:odd", 0, value=None, lexical="0x1F", source_type="hexBinary"),
        ),
    ]
    edges = [
        {"relation": "urn:synthetic:hasPart", "source": "p1", "target": "p2"},
        {"relation": "urn:synthetic:hasPart", "source": "p1", "target": "p3"},
        {"relation": "urn:synthetic:hasPart", "source": "p1", "target": "p2"},
    ]
    event = S.translate(_with_graph(nodes, edges))
    assert event["payload"]["record"]["body"]["graph"] == {"edges": edges, "nodes": nodes}


def test_parse_010_a_conflicting_scalar_duplicate_is_refused_as_far_as_the_contract_can_see():
    """PARSE-010, PARTIAL ("Quarantine with source preserved"). Which attributes may repeat is the
    versioned NATO metadata dictionary's to say, and none is held (limitation
    dictionary-cardinality). What the contract itself states is refused: two values of one
    attribute both claiming occurrence 0. A second occurrence numbered 1 is legitimate repetition
    as far as the contract can tell, and is retained. Quarantine and keeping the raw source are the
    gateway's."""
    clash = [
        _node(
            "n1",
            _attr("urn:synthetic:title", 0, "a", lexical="a"),
            _attr("urn:synthetic:title", 0, "b", lexical="b"),
        )
    ]
    assert S.refuse_record(_with_graph(clash)) == "graph-occurrence-gap"
    repeated = [
        _node(
            "n1",
            _attr("urn:synthetic:title", 0, "a", lexical="a"),
            _attr("urn:synthetic:title", 1, "b", lexical="b"),
        )
    ]
    assert (
        S.translate(_with_graph(repeated))["payload"]["record"]["body"]["graph"]["nodes"]
        == repeated
    )


def test_parse_007_the_record_s_own_node_bound_is_the_contract_s():
    """PARSE-007, PARTIAL ("100001 nodes" against the gateway's XML node limit): no XML is parsed
    here. The record's typed graph carries the contract's own bound, 10 000 nodes, and the 10 001st
    is refused."""
    nodes = [_node(f"n{i}") for i in range(10_001)]
    with pytest.raises(isr_record.IsrRecordRefused, match="schema-violation: /body/graph/nodes:"):
        S.adapter("catalog").to_cdm(_with_graph(nodes))


@pytest.mark.parametrize(
    "case, content",
    [
        (
            "PARSE-003",
            '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY e SYSTEM "file:///etc/passwd">]><r>&e;</r>',
        ),
        (
            "PARSE-004",
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"><xs:import '
            'schemaLocation="https://example.invalid/remote.xsd"/></xs:schema>',
        ),
    ],
)
def test_parse_003_004_xml_in_a_record_is_carried_as_text_and_never_parsed(
    case, content, monkeypatch
):
    """PARSE-003 ("Reject; no file read") and PARSE-004 ("Reject; no outbound network"), PARTIAL:
    the gateway's XML decoder is not built. A translator handed a record whose graph carries XML
    text, an external entity or a remote schema import, parses no XML, opens no file and makes no
    socket: the text is carried verbatim."""
    record = _with_graph(
        [
            _node(
                "n1",
                _attr("urn:synthetic:raw", 0, content, lexical=content, source_type="xs:anyType"),
            )
        ]
    )
    isr_record.schema()
    _forbid_io(monkeypatch)
    event = S.translate(record)
    assert S.graph_of(event["payload"]["record"])["nodes"][0]["attributes"][0]["lexical"] == content


# -- section 7: the identity, against RFC 8785 ------------------------------------------------------


def test_json_dumps_with_ensure_ascii_false_is_rfc8785_for_every_scalar_value():
    """L-06, measured: for every Unicode scalar value, `json.dumps(ch, ensure_ascii=False)` is the
    RFC 8785 string `S.jcs_string` writes from the RFC's sentences; the DEFAULT `json.dumps` is
    not, for every non-ASCII value and for U+007F."""
    differ, differ_default_ascii, differ_default = [], [], 0
    for cp in range(0x110000):
        if 0xD800 <= cp <= 0xDFFF:
            continue
        ch = chr(cp)
        want = S.jcs_string(ch)
        if json.dumps(ch, ensure_ascii=False) != want:
            differ.append(cp)
        if json.dumps(ch) != want:
            differ_default += 1
            if cp < 0x80:
                differ_default_ascii.append(cp)
    assert differ == []
    assert differ_default_ascii == [0x7F]
    assert differ_default == 0x110000 - 0x800 - 0x80 + 1


HOSTILE = {
    "non-ascii": "Ténänt-テナント-\U0001f6f0-ß",
    "quote": 'a"b"',
    "backslash": "a\\b\\\\c",
    "control-01": "a\x01b",
    "control-1f": "x\x1fy",
    "named-controls": "\b\t\n\x0c\r",
    "del-7f": "a\x7fb",
    "u2028-u2029": "a\u2028b\u2029c",
    "solidus": "a/b</script>",
    "nbsp-bom-mid": "a\u00a0b\ufeffc",
    "noncharacters": "a\uffffb\U0010ffff",
    "combo": 'é"\\\x00 \U0001f600',
}


@pytest.mark.parametrize("label", sorted(HOSTILE))
@pytest.mark.parametrize("token", ["1", None, ""])
def test_the_identity_is_rfc8785_on_a_hostile_sample(label, token):
    """L-06's property, sampled: hostile text in the tenant, the authority and the object id, and a
    null, empty or ordinary revision token. The keys equal the base64url of S.jcs_array's text,
    on the dict path and on the octet path (where every non-ASCII character arrives escaped)."""
    import base64

    value = HOSTILE[label]
    record = S.mutated(
        BASIC,
        lambda d: (
            d.update({"tenant_id": "t-" + value}),
            d["origin"].update({"authority": "auth-" + value, "object_id": "obj-" + value}),
            d["revision"].update({"token": token}),
        ),
    )

    def b64(text):
        return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")

    okey = b64(
        S.jcs_array(["t-" + value, "test-domain", "auth-" + value, "catalog", "obj-" + value])
    )
    rkey = b64(S.jcs_array([okey, token, record["revision"]["semantic_sha256"]]))
    for raw in (record, json.dumps(record, ensure_ascii=True).encode("ascii")):
        event = S.translate(raw, "catalog")
        assert event["source_ids"][0]["external_id"] == okey
        assert event["payload"]["revision_key"] == rkey


@pytest.mark.parametrize(
    "path",
    [
        ("tenant_id",),
        ("security_domain",),
        ("origin", "authority"),
        ("origin", "object_id"),
        ("revision", "token"),
    ],
)
def test_a_lone_surrogate_in_an_identity_component_is_refused_by_name(path):
    """L-06: a lone surrogate has no RFC 8785 form, so no key is built; it is refused naming the
    field, on the dict path and as a `\\ud800` escape on the octet path. The DEFAULT json.dumps
    would have keyed it."""

    def put(d, value):
        (d if len(path) == 1 else d[path[0]]).update({path[-1]: value})

    record = S.mutated(BASIC, lambda d: put(d, "bad\ud800id"))
    assert json.dumps(["bad\ud800id"]) == '["bad\\ud800id"]'
    for raw in (record, json.dumps(record).encode("ascii")):
        with pytest.raises(isr_record.IsrRecordRefused) as refused:
            S.adapter("catalog").to_cdm(raw)
        assert refused.value.code == "lone-surrogate"
        assert str(refused.value).startswith(f"lone-surrogate: /{'/'.join(path)}:")
    with pytest.raises(isr_record.IsrRecordRefused, match="lone-surrogate"):
        isr_record.object_key(S.mutated(BASIC, lambda d: d.update({"tenant_id": "x\udfff"})))


def test_the_two_keys_are_base64url_of_compact_arrays():
    """Section 7, decoded: K is the compact array of the five components, K' of the object key,
    the token and the digest; a null token is `null` and an empty one `""` (two different keys)."""
    okey = isr_record.object_key(BASIC)
    assert (
        _decoded(okey) == '["test-tenant","test-domain","test-origin-a","catalog","catalog-basic"]'
    )
    assert _decoded(isr_record.revision_key(BASIC)) == (
        f'["{okey}","1","94c506ae0e682f653dd1a691d292f6b9797253897d2584390fbd314691268718"]'
    )
    null = S.mutated(BASIC, lambda d: d["revision"].update({"token": None}))
    empty = S.mutated(BASIC, lambda d: d["revision"].update({"token": ""}))
    assert _decoded(isr_record.revision_key(null)).split(",")[1] == "null"
    assert _decoded(isr_record.revision_key(empty)).split(",")[1] == '""'
    assert isr_record.revision_key(null) != isr_record.revision_key(empty)
    assert "=" not in okey and "+" not in okey and "/" not in okey


def test_non_ascii_components_are_keyed_as_utf8_and_not_as_escapes():
    """RFC 8785 writes non-ASCII as itself, so the key holds UTF-8 octets, not `\\u` escapes."""
    import base64

    record = S.mutated(BASIC, lambda d: d.update({"tenant_id": "nájomca-中"}))
    key = isr_record.object_key(record)
    octets = base64.urlsafe_b64decode(key + "=" * (-len(key) % 4))
    assert "nájomca-中".encode("utf-8") in octets and b"\\u" not in octets


def test_canonical_array_takes_strings_and_null_only():
    assert isr_record.canonical_array(["a", None, ""]) == '["a",null,""]'
    for bad in ([1], [True], [["a"]], [{"a": 1}]):
        assert S.refusal(isr_record.canonical_array, bad) == "not-a-json-value"


# -- the input is the caller's ----------------------------------------------------------------------


def test_the_caller_s_dict_is_neither_changed_nor_aliased():
    """The Event carries a copy: translating leaves the caller's record as it was, and changing
    the caller's record afterwards does not change the Event."""
    record = S.bundle_record("catalog", "unknown-extension")
    before = copy.deepcopy(record)
    event = S.adapter("catalog").to_cdm(record)[0]
    assert record == before
    record["body"]["title"] = "changed"
    _attribute(record)["value"] = "changed"
    assert event.payload["record"]["body"]["title"] == "Synthetic ISR test product"
    assert _attribute(event.payload["record"])["value"] == "18446744073709551615"


# -- CDM-012 and the bounds' enforcement point --------------------------------------------------------


MODULES = (
    "isr_record.py",
    "adapters/stanag4559_common.py",
    "adapters/stanag4559_catalog.py",
    "adapters/stanag4559_stream.py",
    "adapters/stanag4559_workflow.py",
)


def test_cdm_012_the_translators_import_no_hashing_and_no_network_and_the_gates_see_them(tmp_path):
    """CDM-012 ("Boundary test fails" on a hashlib or network import). The five modules import
    neither, they are in the sweep of both repository gates, and the gates' own reading of a
    module that did import `hashlib` or `socket` reports it."""
    from tests import test_cdm_boundary as boundary
    from tests import test_cdm_no_network as no_network

    package = pathlib.Path(synapse_cdm.__file__).parent
    for name in MODULES:
        path = package / name
        assert path in boundary.SOURCES and path in no_network.SOURCES, name
        roots = boundary._imported_roots(path)
        assert not roots & boundary.FORBIDDEN_CRYPTO, (name, roots)
        assert not roots & no_network.NETWORKING, (name, roots)
    mutant = tmp_path / "stanag4559_catalog.py"
    mutant.write_text((package / MODULES[2]).read_text() + "\nimport hashlib\nimport socket\n")
    roots = boundary._imported_roots(mutant)
    assert "hashlib" in roots & boundary.FORBIDDEN_CRYPTO
    assert "socket" in roots & no_network.NETWORKING


def test_a_decoder_inherited_from_an_abstract_base_is_not_bounded():
    """The trap the three thin classes avoid by each defining `to_cdm`: `abstract` returns before
    `_bind_input_bound`, so a decoder inherited from an abstract base runs unbounded."""
    from tests import probe_metadata

    class _Base(Adapter):
        abstract = True

        def to_cdm(self, raw):
            return []

    class _Leaf(_Base):
        name = "stanag4559_test_unbounded_leaf"
        version = "0.1.0"
        direction = "ingest"
        system = "TEST"
        metadata = probe_metadata("stanag4559_test_unbounded_leaf", max_input_bytes=8)

    assert not getattr(_Leaf.to_cdm, "__input_bounded__", False)
    assert _Leaf().to_cdm(b"x" * 100) == []
    for family in S.FAMILIES:
        cls = load_adapter(f"stanag4559_{family}")
        assert getattr(cls.to_cdm, "__input_bounded__", False)
        assert issubclass(cls, Stanag4559Adapter) and "to_cdm" in vars(cls)
