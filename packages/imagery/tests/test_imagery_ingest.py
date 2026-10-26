"""The ingest transaction: states per kit vector, configuration refusals, staging under the cap,
step order and visibility, identifiers, deduplication and revisions, quarantine, retention,
release from quarantine, the catalog and the closed public surface."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import stat

import pytest
from conftest import LOCAL
from helpers import (
    FTITLE,
    IID1,
    KIT_SAMPLES,
    ONAME,
    build_nsif,
    fifo,
    image,
    ruled_asset_id,
    ruled_attempt_id,
    ruled_dedup_id,
    ruled_record_id,
    ruled_tenant_dir,
    set_field,
    sha,
    store_files,
    vector,
)

from synapse_cdm.adapters.stanag4545 import Stanag4545Adapter, Stanag4545Context
from synapse_imagery import ingest as ingest_module
from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.ingest import Catalog, IngestService, RetentionPolicy
from synapse_imagery.policy import Artefact, Principal
from synapse_imagery.result import HostError, PolicyDenied
from synapse_imagery.worker import Window

GEO_DMS = vector("geo_dms.ntf")
SINGLE_PRODUCT = (
    "mono_nsif101.ntf",
    "mono_nsif100.ntf",
    "mono_nitf210.ntf",
    "mode_B.ntf",
    "mode_P.ntf",
    "mode_R.ntf",
    "mode_S.ntf",
    "uint16.ntf",
    "image_and_text.ntf",
)
REJECTED = {
    "bad_file_length.ntf": ("E_LENGTH", "header"),
    "truncated.ntf": ("E_LENGTH", "header"),
    "trailing.ntf": ("E_LENGTH", "header"),
    "bad_count.ntf": ("E_DIGITS", "header"),
    "unsupported_stype.ntf": ("E_PROFILE", "header"),
}


def run(service, octets, principal=LOCAL, **options):
    options.setdefault("dataset_namespace", "default")
    options.setdefault("synthetic", True)
    return service.ingest(octets, principal=principal, **options)


def tenant_root(tmp_path, tenant="local"):
    return tmp_path / "store" / "tenants" / ruled_tenant_dir(tenant)


def core_objects(octets, asset_id, **context):
    """A direct translation by the adapter under the context the host must have used."""
    ctx = Stanag4545Context(asset_ref=asset_id, verified_sha256=sha(octets), **context)
    objects = Stanag4545Adapter(synthetic=True, context=ctx).to_cdm(octets)
    return json.loads(
        json.dumps([item.model_dump(mode="json") for item in objects], sort_keys=True)
    )


# --------------------------------------------------------------------------- states


@pytest.mark.parametrize(
    "name",
    SINGLE_PRODUCT
    + ("geo_dms.ntf", "unknown_duplicate_tre.ntf", "header_only.ntf")
    + tuple(REJECTED),
)
def test_every_kit_vector_reaches_its_ruled_state_through_the_isolated_worker(
    services, store, name
):
    octets = vector(name)
    result = run(services(store), octets)
    assert result["sha256"] == hashlib.sha256(octets).hexdigest()
    assert result["source_bytes"] == len(octets)
    if name in SINGLE_PRODUCT or name == "geo_dms.ntf":
        assert result["state"] == "committed"
        record = store.read_record("local", result["record_id"], area="records")
        objects = record["objects"]
        assert record["host"]["worker"]["isolation"] == "subprocess"
        assert len(result["cdm_ids"]) == (2 if name == "geo_dms.ntf" else 1)
        expected = core_objects(octets, result["asset_id"])
        assert objects == expected
        assert result["cdm_ids"] == [expected[0]["entity_id"]] + [
            o["object_id"] for o in expected[1:]
        ]
        for item in objects:
            assert item["source"]["source_hash"] == {
                "algorithm": "sha256",
                "value": result["sha256"],
            }
        assert objects[0]["attributes"]["stanag4545"]["asset_ref"] == result["asset_id"]
    elif name == "unknown_duplicate_tre.ntf":
        assert result["state"] == "policy_blocked"
    elif name == "header_only.ntf":
        assert result["state"] == "rejected"
        assert [(d["code"], d["stage"], d["path"]) for d in result["diagnostics"]] == [
            ("E_CONTEXT", "cdm", "/context/product_key")
        ]
    else:
        code, stage = REJECTED[name]
        assert result["state"] == "rejected"
        fatal = [d for d in result["diagnostics"] if d["code"].startswith("E_")]
        assert [(d["code"], d["stage"]) for d in fatal] == [(code, stage)]


def test_a_header_only_container_commits_with_its_product_key(services, store):
    result = run(
        services(store), vector("header_only.ntf"), product_key="EXERCISE-HEADER-ONLY-0001"
    )
    assert result["state"] == "committed"
    assert len(result["cdm_ids"]) == 1 and result["images"] == []


def test_a_request_for_context_is_not_catalogued(services, store, tmp_path):
    service = services(store)
    octets = vector("header_only.ntf")
    result = run(service, octets)
    assert result["diagnostics"] == [
        {
            "code": "E_CONTEXT",
            "stage": "cdm",
            "offset": None,
            "path": "/context/product_key",
            "message": result["diagnostics"][0]["message"],
        }
    ]
    assert result["asset_id"] is None
    assert result["record_id"] == ruled_attempt_id(
        "local",
        "default",
        True,
        sha(octets),
        len(octets),
        1,
        "rejected",
        "E_CONTEXT",
        "cdm",
        "/context/product_key",
    )
    tenant = tenant_root(tmp_path)
    assert not [
        p
        for p in store_files(tenant)
        if "/originals/" in p.as_posix() or "/records/" in p.as_posix()
    ]
    assert not (tenant / "dedup").exists() or os.listdir(tenant / "dedup") == []
    # The same octets with context are a new attempt, not a repeat of the request for context.
    assert run(service, octets, product_key="EXERCISE-HEADER-ONLY-0001")["state"] == "committed"


@pytest.mark.parametrize("synthetic", [None, "true", 1, 0])
def test_the_synthetic_choice_has_no_default(services, store, tmp_path, synthetic):
    with pytest.raises(TypeError):
        run(services(store, worker=InProcessWorker()), GEO_DMS, synthetic=synthetic)
    assert os.listdir(tmp_path / "store" / "staging") == []


@pytest.mark.parametrize(
    "options, error",
    [
        ({"dataset_namespace": "a|b"}, ValueError),
        ({"dataset_namespace": ""}, ValueError),
        ({"product_key": "x" * 129}, ValueError),
        ({"as_of": {"instant": "2026-10-04T12:00:00Z"}}, TypeError),
    ],
)
def test_the_context_is_validated_before_any_job_exists(services, store, tmp_path, options, error):
    with pytest.raises(error):
        run(services(store, worker=InProcessWorker()), GEO_DMS, **options)
    assert os.listdir(tmp_path / "store" / "staging") == []


def test_a_source_is_bytes_or_a_path(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    for wrong in (bytearray(GEO_DMS), memoryview(GEO_DMS), 5):
        with pytest.raises(TypeError):
            run(service, wrong)
    path = tmp_path / "geo.ntf"
    path.write_bytes(GEO_DMS)
    from_path = run(service, path)
    assert from_path == run(service, GEO_DMS) == run(service, str(path))
    assert from_path["state"] == "committed"


@pytest.mark.parametrize("as_path", [False, True], ids=["bytes", "path"])
def test_an_input_over_the_cap_is_refused_before_it_is_hashed(services, store, tmp_path, as_path):
    octets = b"N" * 16_777_217
    source = octets
    if as_path:
        source = tmp_path / "big.ntf"
        source.write_bytes(octets)
    result = run(services(store, worker=InProcessWorker()), source)
    assert (result["state"], result["sha256"], result["source_bytes"]) == (
        "rejected",
        None,
        16_777_217,
    )
    assert [(d["code"], d["stage"], d["offset"], d["path"]) for d in result["diagnostics"]] == [
        ("E_LIMIT", "input", None, "/input")
    ]
    assert result["record_id"] == ruled_attempt_id(
        "local", "default", True, None, 16_777_217, 1, "rejected", "E_LIMIT", "input", "/input"
    )
    assert os.listdir(tmp_path / "store" / "staging") == []
    assert not (tmp_path / "store" / "tenants").exists() or not list(
        (tmp_path / "store" / "tenants").rglob("*.json")
    )


def test_a_fifo_fails_without_blocking(services, store, tmp_path):
    result = run(services(store, worker=InProcessWorker()), fifo(tmp_path / "pipe"))
    assert result["state"] == "failed"
    assert [(d["code"], d["stage"], d["path"]) for d in result["diagnostics"]] == [
        ("E_IO", "input", "/input")
    ]
    assert result["sha256"] is None and result["asset_id"] is None


@pytest.mark.parametrize("path", ["a\0b", "\ud800.ntf"], ids=["nul", "lone-surrogate"])
def test_a_path_no_file_can_have_fails_like_a_missing_file(services, store, tmp_path, path):
    service = services(store, worker=InProcessWorker())
    result = run(service, path)
    missing = run(service, str(tmp_path / "missing.ntf"))
    for outcome in (result, missing):
        assert outcome["state"] == "failed"
        assert [(d["code"], d["stage"], d["path"]) for d in outcome["diagnostics"]] == [
            ("E_IO", "input", "/input")
        ]
        assert outcome["sha256"] is None and outcome["asset_id"] is None
    assert result == missing
    assert os.listdir(tmp_path / "store" / "staging") == []


def test_the_steps_run_in_their_ruled_order(services, store):
    seen = []
    service = services(store, worker=InProcessWorker(), _fault=seen.append)
    assert run(service, GEO_DMS)["state"] == "committed"
    assert seen == [
        "received",
        "staged",
        "inventoried",
        "assessed",
        "stored",
        "translated",
        "persisted",
        "committed",
        "published",
    ]
    seen.clear()
    assert run(service, vector("unknown_duplicate_tre.ntf"))["state"] == "policy_blocked"
    assert seen == [
        "received",
        "staged",
        "inventoried",
        "assessed",
        "stored",
        "persisted",
        "committed",
    ]
    seen.clear()
    assert run(service, vector("bad_count.ntf"))["state"] == "rejected"
    assert seen == ["received", "staged", "persisted", "committed"]
    seen.clear()
    assert run(service, GEO_DMS)["state"] == "committed"
    assert seen == ["received", "staged"], "a repeat is answered at the dedup lookup"


def test_nothing_is_visible_before_the_commit(services, store, tmp_path):
    def stop_at_persisted(point):
        if point == "persisted":
            assert service.catalog.list_records(principal=LOCAL) == []
            assert not list(tenant_root(tmp_path).glob("records/*"))

    service = services(store, worker=InProcessWorker(), _fault=stop_at_persisted)
    result = run(service, GEO_DMS)
    assert service.catalog.list_records(principal=LOCAL) == [result["record_id"]]


def test_a_committed_record_holds_the_host_envelope(services, store):
    result = run(services(store, worker=InProcessWorker()), GEO_DMS)
    record = store.read_record("local", result["record_id"], area="records")
    assert set(record) == {
        "format",
        "result",
        "dedup",
        "entity_id",
        "descriptor",
        "decision",
        "inventory",
        "objects",
        "presentation",
        "host",
    }
    assert record["format"] == "sc-imagery-record/1"
    assert record["dedup"] == {
        "tenant": "local",
        "dataset_namespace": "default",
        "synthetic": True,
        "sha256": result["sha256"],
        "profile_revision": 1,
    }
    assert record["entity_id"] == result["cdm_ids"][0]
    assert record["decision"] == {
        "allowed": True,
        "completeness": "complete",
        "policy_id": "sc-imagery-default-clean-u",
        "policy_version": "1",
        "reason": "ADMITTED_DECLARED_UNCLASSIFIED",
    }
    # The canonical evidence stays inline: wire_b64 is never replaced by an asset reference.
    product = record["objects"][0]
    import base64

    assert base64.b64decode(product["residual"]["data"]["stanag4545"]["wire_b64"]) == GEO_DMS
    assert record["host"]["software"]["synapse_imagery"] == "1.0.0"
    assert record["host"]["released_from"] is None
    text = json.dumps(record)
    assert "job_id" not in text and str(store.root) not in text


# --------------------------------------------------------------------------- identifiers


def test_the_committed_record_id_is_the_ruled_formula(services, store):
    octets = vector("mono_nsif101.ntf")
    result = run(services(store, worker=InProcessWorker()), octets)
    digest = hashlib.sha256(octets).hexdigest()
    assert result["record_id"] == ruled_record_id("local", "default", True, digest, 1, "committed")
    assert result["asset_id"] == ruled_asset_id("local", digest)


def test_tenants_never_share_observable_state(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    one = run(service, GEO_DMS, principal=Principal("t1", "a"))
    two = run(service, GEO_DMS, principal=Principal("t2", "a"))
    assert one["record_id"] != two["record_id"] and one["asset_id"] != two["asset_id"]
    first, second = tenant_root(tmp_path, "t1"), tenant_root(tmp_path, "t2")
    assert first != second
    names_one = " ".join(p.name for p in store_files(first))
    names_two = " ".join(p.name for p in store_files(second))
    # The CDM identity of the product is the adapter's and the same in both; nothing the host
    # derives for one tenant (record, asset, dedup entry) appears in the other's directory.
    for mine, theirs, names in ((one, two, names_one), (two, one, names_two)):
        assert mine["record_id"] in names and mine["asset_id"] in names
        assert theirs["record_id"] not in names and theirs["asset_id"] not in names
    dedup_one = {p.name for p in (first / "dedup").iterdir()}
    assert dedup_one.isdisjoint({p.name for p in (second / "dedup").iterdir()})
    assert run(service, GEO_DMS, principal=Principal("t1", "b"))["record_id"] == one["record_id"]
    with pytest.raises(HostError) as foreign:
        service.catalog.get(one["record_id"], principal=Principal("t2", "a"))
    with pytest.raises(HostError) as unknown:
        service.catalog.get("00000000-0000-5000-8000-000000000000", principal=Principal("t2", "a"))
    with pytest.raises(HostError) as malformed:
        service.catalog.get("../" + one["record_id"], principal=Principal("t2", "a"))
    assert (
        str(foreign.value)
        == str(unknown.value)
        == str(malformed.value)
        == ("E_FIELD @byte - /record_id: no committed record with this id for this principal")
    )


def test_two_failures_of_the_same_kind_have_the_same_attempt_id(services, store):
    def fail_at_staged(point):
        if point == "staged":
            raise RuntimeError("injected")

    failing = services(store, worker=InProcessWorker(), _fault=fail_at_staged)
    first, second = run(failing, GEO_DMS), run(failing, GEO_DMS)
    assert first == second and first["state"] == "failed"
    digest = sha(GEO_DMS)
    assert first["record_id"] == ruled_attempt_id(
        "local",
        "default",
        True,
        digest,
        len(GEO_DMS),
        1,
        "failed",
        "E_INTERNAL",
        "input",
        "/staged",
    )
    committed = run(services(store, worker=InProcessWorker()), GEO_DMS)
    assert committed["record_id"] != first["record_id"]


def test_no_store_name_is_built_from_source_text(services, store, tmp_path):
    octets = set_field(GEO_DMS, FTITLE[0], b"SECRETXYZ")
    octets = set_field(octets, ONAME[0], b"SECRETXYZ")
    octets = set_field(octets, IID1[0], b"SECRETXYZ")
    result = run(services(store, worker=InProcessWorker()), octets)
    assert result["state"] == "committed"
    for path in (tmp_path / "store").rglob("*"):
        assert "SECRETXYZ" not in path.name


# --------------------------------------------------------------------------- dedup and revisions


def test_a_repeat_returns_the_stored_result_and_commits_nothing_new(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    first = run(service, vector("mono_nsif101.ntf"))
    second = run(service, vector("mono_nsif101.ntf"))
    assert first == second and list(first) == list(second)
    assert len(os.listdir(tenant_root(tmp_path) / "records")) == 1
    blocked = [run(service, vector("unknown_duplicate_tre.ntf")) for _ in range(2)]
    assert blocked[0] == blocked[1] and blocked[0]["state"] == "policy_blocked"


def test_another_digest_of_the_same_product_is_a_new_revision(services, store):
    service = services(store, worker=InProcessWorker())
    first = run(service, vector("mono_nsif101.ntf"))
    second = run(service, vector("mode_B.ntf"))
    assert first["cdm_ids"][0] == second["cdm_ids"][0]
    product = service.catalog.revisions(first["cdm_ids"][0], principal=LOCAL)
    assert [
        (e["revision"], e["record_id"], e["interpretation_of"]) for e in product["revisions"]
    ] == [
        (1, first["record_id"], None),
        (2, second["record_id"], None),
    ]
    assert product["selected_revision"] == 1


@pytest.mark.parametrize("order", ["later-first", "earlier-first"])
def test_no_newest_wins_selection(services, store, order):
    later = set_field(vector("mono_nsif101.ntf"), 25, b"20271231235959")
    earlier = set_field(vector("mono_nsif101.ntf"), 25, b"20200101000000")
    service = services(store, worker=InProcessWorker())
    sequence = (later, earlier) if order == "later-first" else (earlier, later)
    results = [run(service, octets, product_key="SCFIX-PRODUCT-0001") for octets in sequence]
    entity = results[0]["cdm_ids"][0]
    assert results[1]["cdm_ids"][0] == entity
    assert service.catalog.revisions(entity, principal=LOCAL)["selected_revision"] == 1
    service.catalog.select_revision(entity, 2, principal=LOCAL)
    assert service.catalog.revisions(entity, principal=LOCAL)["selected_revision"] == 2
    with pytest.raises(HostError) as caught:
        service.catalog.select_revision(entity, 3, principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_FIELD",
        "storage",
        "/revision",
    )


def test_another_parser_revision_adds_an_interpretation_revision(services, store, monkeypatch):
    service = services(store, worker=InProcessWorker())
    first = run(service, GEO_DMS)
    monkeypatch.setattr(ingest_module, "PROFILE_REVISION", 2)
    second = run(service, GEO_DMS)
    assert second["record_id"] != first["record_id"]
    assert second["asset_id"] == first["asset_id"]
    product = service.catalog.revisions(first["cdm_ids"][0], principal=LOCAL)
    assert [
        (e["revision"], e["profile_revision"], e["interpretation_of"]) for e in product["revisions"]
    ] == [
        (1, 1, None),
        (2, 2, first["record_id"]),
    ]


def test_synthetic_and_dataset_are_part_of_the_key(services, store):
    service = services(store)
    synthetic = run(service, GEO_DMS)
    live = run(service, GEO_DMS, synthetic=False)
    other = run(service, GEO_DMS, dataset_namespace="other")
    assert len({synthetic["record_id"], live["record_id"], other["record_id"]}) == 3
    assert live["synthetic"] is False and live["state"] == "committed"
    product = service.catalog.revisions(synthetic["cdm_ids"][0], principal=LOCAL)
    assert [entry["synthetic"] for entry in product["revisions"]] == [True, False]
    assert ruled_dedup_id("local", "default", False, sha(GEO_DMS), 1) != ruled_dedup_id(
        "local", "default", True, sha(GEO_DMS), 1
    )


# --------------------------------------------------------------------------- quarantine and retention


def test_a_blocked_product_is_kept_in_quarantine_and_published_nowhere(services, store, tmp_path):
    service = services(store, worker=InProcessWorker())
    octets = vector("unknown_duplicate_tre.ntf")
    result = run(service, octets)
    tenant = tenant_root(tmp_path)
    original = tenant / "quarantine" / "originals" / result["asset_id"]
    assert original.read_bytes() == octets
    assert stat.S_IMODE(original.stat().st_mode) == 0o400
    assert not (tenant / "records").exists() or os.listdir(tenant / "records") == []
    assert not (tenant / "published").exists() or os.listdir(tenant / "published") == []
    record = service.catalog.read_quarantined(result["record_id"], principal=LOCAL)
    assert json.loads(record["descriptor"])["extensions"] == [["tre", "SCZZZZ"], ["tre", "SCZZZZ"]]
    assert record["inventory"]["extension_counts"] == {"des": 0, "res": 0, "tre": 2}
    assert record["objects"] == [] and record["presentation"] is None
    with pytest.raises(HostError) as caught:
        service.catalog.read_quarantined(result["record_id"], principal=Principal("t2", "a"))
    assert (
        str(caught.value)
        == "E_FIELD @byte - /record_id: no quarantined record with this id for this principal"
    )
    with pytest.raises(HostError):
        service.catalog.get(result["record_id"], principal=LOCAL)


def test_rejected_octets_are_kept_only_under_a_retaining_policy(services, store, tmp_path):
    octets = vector("bad_count.ntf")
    result = run(services(store, worker=InProcessWorker()), octets)
    assert result["asset_id"] is None
    assert [d["code"] for d in result["diagnostics"]] == ["ORIGINAL_NOT_RETAINED", "E_DIGITS"]
    tenant = tenant_root(tmp_path)
    assert (
        not (tenant / "rejected" / "originals").exists()
        or os.listdir(tenant / "rejected" / "originals") == []
    )
    assert len(os.listdir(tenant / "rejected" / "records")) == 1
    assert run(services(store, worker=InProcessWorker()), octets) == result
    other = LocalAssetStore(tmp_path / "other")
    kept = run(
        services(other, worker=InProcessWorker(), retention=RetentionPolicy(retain_rejected=True)),
        octets,
    )
    assert kept["asset_id"] == ruled_asset_id("local", sha(octets))
    assert [d["code"] for d in kept["diagnostics"]] == ["E_DIGITS"]
    path = (
        tmp_path
        / "other"
        / "tenants"
        / ruled_tenant_dir("local")
        / "rejected"
        / "originals"
        / kept["asset_id"]
    )
    assert path.read_bytes() == octets and stat.S_IMODE(path.stat().st_mode) == 0o400
    with pytest.raises(TypeError):
        RetentionPolicy(retain_rejected="yes")


def test_reassessment_keeps_a_denial_and_releases_under_another_policy(services, store, tmp_path):
    octets = vector("unknown_duplicate_tre.ntf")
    blocked = run(services(store, worker=InProcessWorker()), octets)
    staying = services(store, worker=InProcessWorker())
    before = sorted(p.as_posix() for p in store_files(tmp_path / "store"))
    assert staying.reassess(blocked["record_id"], principal=LOCAL) == blocked
    assert sorted(p.as_posix() for p in store_files(tmp_path / "store")) == before
    releasing = services(
        store, policy=FakePolicy({Artefact.METADATA: True}), worker=InProcessWorker()
    )
    released = releasing.reassess(blocked["record_id"], principal=LOCAL)
    assert released["state"] == "committed" and len(released["cdm_ids"]) == 1
    assert released["record_id"] == ruled_record_id(
        "local", "default", True, sha(octets), 1, "committed"
    )
    product = releasing.catalog.revisions(released["cdm_ids"][0], principal=LOCAL)
    assert product["revisions"][0]["released_from"] == blocked["record_id"]
    assert (
        tenant_root(tmp_path) / "quarantine" / "records" / f"{blocked['record_id']}.json"
    ).is_file()
    assert (tenant_root(tmp_path) / "originals" / released["asset_id"]).is_file()
    with pytest.raises(HostError):
        releasing.reassess(released["record_id"], principal=LOCAL)
    with pytest.raises(HostError):
        releasing.reassess(blocked["record_id"], principal=Principal("t2", "a"))


# --------------------------------------------------------------------------- the catalog and surface


def test_the_public_surface_is_the_closed_list():
    service = {name for name in vars(IngestService) if not name.startswith("_")}
    assert service == {
        "catalog",
        "ingest",
        "reassess",
        "preview",
        "decode_window",
        "replay_original",
        "export_nc",
        "recover",
        "close",
    }
    catalog = {name for name in vars(Catalog) if not name.startswith("_")}
    assert catalog == {
        "get",
        "list_records",
        "objects",
        "revisions",
        "select_revision",
        "read_quarantined",
        "presentation",
    }
    signatures = {
        IngestService.__init__: "(self, store, *, policy=None, worker=None, retention: 'RetentionPolicy | None' = None, registry: 'ExtensionRegistry' = ExtensionRegistry(version='sc4545-core-1-empty', security_neutral=frozenset()), _fault: 'Callable[[str], None] | None' = None) -> 'None'",
        IngestService.ingest: "(self, source, *, principal: 'Principal', dataset_namespace: 'str', synthetic: 'bool', product_key: 'str | None' = None, as_of=None) -> 'dict'",
        IngestService.reassess: "(self, record_id: 'str', *, principal: 'Principal', product_key: 'str | None' = None, as_of=None) -> 'dict'",
        IngestService.decode_window: "(self, record_id: 'str', image_index: 'int', window: 'Window', bands: 'tuple[int, ...]', *, principal: 'Principal') -> 'WorkerWindow'",
        IngestService.preview: "(self, record_id: 'str', image_index: 'int', output, *, principal: 'Principal', bands: 'tuple[int, ...] | None' = None, replace: 'bool' = False) -> 'dict'",
        IngestService.replay_original: "(self, record_id: 'str', destination, *, principal: 'Principal', replace: 'bool' = False, mutations: 'tuple' = ()) -> 'dict'",
        IngestService.export_nc: "(self, recipe_path, output, *, principal: 'Principal', replace: 'bool' = False) -> 'dict'",
        IngestService.recover: "(self) -> 'dict'",
        IngestService.close: "(self) -> 'None'",
        Catalog.__init__: "(self, store, policy=None, *, authority: 'TicketAuthority | None' = None) -> 'None'",
        Catalog.get: "(self, record_id: 'str', *, principal: 'Principal') -> 'dict'",
        Catalog.list_records: "(self, *, principal: 'Principal') -> 'list[str]'",
        Catalog.objects: "(self, record_id: 'str', *, principal: 'Principal') -> 'list[dict]'",
        Catalog.revisions: "(self, entity_id: 'str', *, principal: 'Principal') -> 'dict'",
        Catalog.select_revision: "(self, entity_id: 'str', revision: 'int', *, principal: 'Principal') -> 'None'",
        Catalog.read_quarantined: "(self, record_id: 'str', *, principal: 'Principal') -> 'dict'",
        Catalog.presentation: "(self, record_id: 'str', *, principal: 'Principal') -> 'dict'",
        ingest_module.inspect_source: "(source, *, worker=None, policy=None, registry: 'ExtensionRegistry' = ExtensionRegistry(version='sc4545-core-1-empty', security_neutral=frozenset())) -> 'dict'",
    }
    for function, text in signatures.items():
        assert str(inspect.signature(function)) == text, function.__qualname__
    assert set(ingest_module.__all__) == {
        "IngestService",
        "Catalog",
        "RetentionPolicy",
        "inspect_source",
        "PROFILE_REVISION",
        "RECORD_NAMESPACE",
        "ASSET_NAMESPACE",
        "TENANT_NAMESPACE",
        "DERIVATIVE_NAMESPACE",
        "EXPORT_NAMESPACE",
        "cj",
        "tenant_directory",
        "record_id_for",
        "attempt_id_for",
        "asset_id_for",
        "derivative_id_for",
        "export_id_for",
        "dedup_id_for",
        "is_canonical_uuid",
        "is_job_id",
    }
    assert ingest_module.PROFILE_REVISION == 1


def test_the_catalog_lists_only_published_records(services, store):
    def stop(point):
        if point == "committed":
            raise RuntimeError("injected after the commit point")

    stopped = run(services(store, worker=InProcessWorker(), _fault=stop), GEO_DMS)
    assert stopped["state"] == "failed"
    service = services(store, worker=InProcessWorker())
    assert service.catalog.list_records(principal=LOCAL) == []
    counts = service.recover()
    assert counts["records_published"] == 1
    committed = ruled_record_id("local", "default", True, sha(GEO_DMS), 1, "committed")
    assert service.catalog.list_records(principal=LOCAL) == [committed]
    assert service.catalog.get(committed, principal=LOCAL)["state"] == "committed"


def test_objects_are_released_as_metadata_under_the_current_policy(services, store):
    service = services(store, worker=InProcessWorker())
    result = run(service, GEO_DMS)
    product, footprint = service.catalog.objects(result["record_id"], principal=LOCAL)
    assert (product["entity_id"], footprint["object_id"]) == tuple(result["cdm_ids"])
    with pytest.raises(PolicyDenied) as caught:
        Catalog(store, FakePolicy({})).objects(result["record_id"], principal=LOCAL)
    assert caught.value.path == "/policy/metadata"


@pytest.mark.parametrize(
    "name, bands, samples",
    [("mode_R.ntf", (0, 1, 2), KIT_SAMPLES["modes"]), ("uint16.ntf", (0,), KIT_SAMPLES["uint16"])],
)
def test_a_window_is_decoded_behind_a_pixels_ticket(services, store, name, bands, samples):
    service = services(store)
    result = run(service, vector(name))
    side = 4 if name.startswith("mode") else 2
    answer = service.decode_window(
        result["record_id"], 0, Window(0, 0, side, side), bands, principal=LOCAL
    )
    assert list(answer.window.values()) == samples
    assert answer.validity is None
    with pytest.raises(HostError) as caught:
        service.decode_window(
            result["record_id"], 0, Window(0, 0, side, side), bands, principal=Principal("t2", "a")
        )
    assert caught.value.path == "/record_id"


class ExtraObjects(InProcessWorker):
    """A worker whose translation answers two objects more than the container has images."""

    def translate(self, *args, **kwargs):
        objects = super().translate(*args, **kwargs)
        return objects + objects[-1:] * 2


class WiderSamples(InProcessWorker):
    """A worker that answers a window as 16-bit samples: self-consistent with its own request,
    so only the parent's record of the image can tell."""

    def _run(self, op, request, pass_fds):
        answer, payload = super()._run(op, request, pass_fds)
        if op == "decode_window":
            answer["window"]["dtype"] = "uint16"
            answer["payload_bytes"] = len(payload) * 2
            payload = payload * 2
        return answer, payload


def test_more_objects_than_the_container_allows_fail_and_store_nothing(services, store, tmp_path):
    result = run(services(store, worker=ExtraObjects()), GEO_DMS)
    assert (result["state"], result["asset_id"], result["cdm_ids"]) == ("failed", None, [])
    assert [(d["code"], d["stage"], d["offset"], d["path"]) for d in result["diagnostics"]] == [
        ("E_INTERNAL", "cdm", None, "/worker")
    ]
    assert [d["message"] for d in result["diagnostics"]] == ["more objects than the record allows"]
    base = tenant_root(tmp_path)
    for folder in ("records", "published", "originals", "products", "dedup"):
        assert not (base / folder).exists() or os.listdir(base / folder) == [], folder
    assert os.listdir(tmp_path / "store" / "staging") == []


def test_a_window_longer_than_the_record_of_its_image_is_refused(services, store):
    committed = run(services(store, worker=InProcessWorker()), GEO_DMS)
    service = services(store, worker=WiderSamples())
    with pytest.raises(HostError) as caught:
        service.decode_window(committed["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_INTERNAL",
        "pixels",
        None,
        "/worker",
    )
    assert caught.value.message == "the window differs from its record"
    # The same window through an honest worker is the image's 8-bit samples.
    honest = services(store, worker=InProcessWorker())
    answer = honest.decode_window(
        committed["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL
    )
    assert (answer.window.dtype, len(answer.window.data)) == ("uint8", 4)


def test_a_not_published_or_blocked_record_has_no_window(services, store):
    service = services(store, worker=InProcessWorker())
    blocked = run(service, vector("unknown_duplicate_tre.ntf"))
    with pytest.raises(HostError) as caught:
        service.decode_window(blocked["record_id"], 0, Window(0, 0, 2, 2), (0,), principal=LOCAL)
    assert caught.value.path == "/record_id"


def test_the_service_closes_its_own_pool_once(store):
    service = IngestService(store)
    service.close()
    service.close()
    with IngestService(store, worker=InProcessWorker()) as other:
        assert run(other, build_nsif([image()]))["state"] == "committed"
