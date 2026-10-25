"""`stanag4559_stream` (#36): the STANAG 4559 stream translator, SC ISR gateway record -> one
STATUS_CHANGE Event (SC ISR 4559 001 sections 9 and 13).

REPO-BOUND: the acceptance oracle is the specification bundle's examples, carried verbatim under
`tests/stanag4559_bundle/` (not packaged), and the fixture builder this module runs reads them.
The record module's own rules (`synapse_cdm.isr_record`) are tested once, in
`tests/test_cdm_stanag4559_catalog_adapter.py`; this module replays the stream family's records,
payloads and malformed set through them. Each test that discharges a bundle acceptance case names
it in its docstring.
"""

import copy
import json

import jsonschema
import pytest

from synapse_cdm import canonical, evidence, harness, isr_record, lossless, projection, schemas
from synapse_cdm.adapter import (
    InputTooDeep,
    InputTooLarge,
    enforce_depth_bound,
    enforce_input_bound,
    json_nesting_depth,
    load_adapter,
)
from synapse_cdm.manifest import ClaimStatus, LimitKind, MaturityLevel, UnknownFields, WireBinding
from synapse_cdm.manifest import Residual as ResidualStance
from synapse_cdm.models import Event

from tests import observation_support
from tests import stanag4559_support as S

FAMILY = "stream"
ORDINAL = 36

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
    residual LEGACY, the format and its version, unknown keys refused, evidence not yet
    available, the two bounds with their basis, and ISR-ID-001 the one derivation."""
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
    assert meta.evidence.available is False
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


def test_cdm_007_a_stream_footprint_is_coverage_only():
    """CDM-007 for a stream: one Event, no related entity, the coverage polygon as its geometry."""
    objects = S.adapter(FAMILY).to_cdm(S.bundle_record(FAMILY, "basic"))
    assert [o.object_kind for o in objects] == ["event"]
    event = objects[0].model_dump(mode="json")
    assert event["related_entities"] == []
    assert event["geometry"] == {
        "type": "Polygon",
        "coordinates": [[[14.0, 50.0], [15.0, 50.0], [15.0, 51.0], [14.0, 51.0], [14.0, 50.0]]],
    }


def test_replay_capabilities_are_carried_verbatim_and_never_acted_on():
    """Section 13's controller is the gateway's: the open `replay_capabilities` object, nested
    content and all, reaches payload.record unchanged; a stream type unknown to anyone stays its
    own token; an open interval stays open."""
    capabilities = {
        "delivery": ["UNICAST", "MULTICAST"],
        "rates": [0.5, 1, 2.0],
        "vendor": {"urn:synthetic:x": {"y": [None, True, "z"]}},
    }
    record = S.mutated(
        S.authored_record(FAMILY, "basic"),
        lambda d: d["body"].update(
            {"replay_capabilities": capabilities, "stream_type": "SYNTHETIC_HYPERSPECTRAL"}
        ),
    )
    body = S.translate(record)["payload"]["record"]["body"]
    assert body["replay_capabilities"] == capabilities
    assert body["stream_type"] == "SYNTHETIC_HYPERSPECTRAL"
    assert body["temporal_end"] is None and body["live"] is True


def test_a_stream_interval_runs_forwards():
    """Section 28's interval rule on a stream body: a stated end before the start is refused."""
    record = S.mutated(
        S.authored_record(FAMILY, "basic"),
        lambda d: d["body"].update({"temporal_end": "2026-10-04T10:59:59.999Z"}),
    )
    assert S.refuse_record(record) == "interval-reversed"
