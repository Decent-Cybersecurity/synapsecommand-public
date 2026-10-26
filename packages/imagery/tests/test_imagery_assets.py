"""The AssetStore contract over both shipped stores, then the local store's own layout:
permissions, the marker, atomic links, refusals of foreign paths, and concurrent commits."""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
import threading

import pytest
from conftest import LOCAL
from helpers import ruled_asset_id, ruled_tenant_dir, sha, vector

from synapse_cdm.adapters.stanag4545 import CORE1_LIMITS, parse_container
from synapse_imagery.assets import LocalAssetStore, TempFile
from synapse_imagery.fakes import FakePolicy, InProcessWorker, MemoryAssetStore
from synapse_imagery.ingest import IngestService, RetentionPolicy
from synapse_imagery.policy import (
    EMPTY_REGISTRY,
    Artefact,
    ExtensionRegistry,
    PolicyRequest,
    Principal,
    SecurityDescriptor,
    TicketAuthority,
)
from synapse_imagery.result import HostError, PolicyDenied

GEO_DMS = vector("geo_dms.ntf")
GEO_SHA = sha(GEO_DMS)
DESCRIPTOR = SecurityDescriptor.from_container(
    parse_container(GEO_DMS, CORE1_LIMITS), EMPTY_REGISTRY
)
EVERYTHING = FakePolicy({artefact: True for artefact in Artefact})


@pytest.fixture(params=["local", "memory"])
def any_store(request, tmp_path):
    if request.param == "local":
        yield LocalAssetStore(tmp_path / "store")
    else:
        made = MemoryAssetStore()
        try:
            yield made
        finally:
            made.close()


def originals(store, location="originals", tenant="local") -> set[str]:
    """The asset ids a store holds in one location, read from its own state."""
    if isinstance(store, MemoryAssetStore):
        return set(store._state(tenant)["objects"][location])
    parts = {
        "originals": ("originals",),
        "quarantine": ("quarantine", "originals"),
        "rejected": ("rejected", "originals"),
    }
    folder = os.path.join(store.root, "tenants", ruled_tenant_dir(tenant), *parts[location])
    return (
        {name for name in os.listdir(folder) if not name.startswith(".")}
        if os.path.isdir(folder)
        else set()
    )


def ticket(authority, artefact, asset, principal=LOCAL, descriptor=DESCRIPTOR):
    return authority.issue(PolicyRequest(principal, artefact, descriptor, True, None, asset))


def put(store, octets=GEO_DMS, descriptor=DESCRIPTOR, **options):
    return store.put_original(
        io.BytesIO(octets), sha(octets), len(octets), descriptor, tenant="local", **options
    )


# --------------------------------------------------------------------------- the contract


def test_an_original_is_stored_once_under_its_ruled_id(any_store):
    asset = put(any_store)
    assert asset == ruled_asset_id("local", GEO_SHA)
    assert put(any_store) == asset
    assert originals(any_store) == {asset}


@pytest.mark.parametrize(
    "stream, digest, count",
    [
        (GEO_DMS, "0" * 64, len(GEO_DMS)),
        (GEO_DMS[:-1], GEO_SHA, len(GEO_DMS)),
        (GEO_DMS + b"X", GEO_SHA, len(GEO_DMS)),
    ],
    ids=["wrong-digest", "short-stream", "one-octet-more"],
)
def test_count_and_digest_are_verified_before_the_commit(any_store, stream, digest, count):
    with pytest.raises(HostError) as caught:
        any_store.put_original(io.BytesIO(stream), digest, count, DESCRIPTOR, tenant="local")
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_INTEGRITY",
        "storage",
        "/asset",
    )
    assert originals(any_store) == set()


def test_a_quarantined_and_rejected_original_is_a_configuration_error(any_store):
    with pytest.raises(ValueError):
        put(any_store, quarantine=True, rejected=True)


def test_an_admitted_copy_is_stored_beside_a_quarantined_one(any_store):
    asset = put(any_store, quarantine=True)
    assert originals(any_store, "quarantine") == {asset} and originals(any_store) == set()
    assert put(any_store) == asset
    assert originals(any_store, "quarantine") == {asset} and originals(any_store) == {asset}
    # A quarantine request is satisfied by the admitted object.
    assert put(any_store, quarantine=True) == asset
    if isinstance(any_store, LocalAssetStore):
        assets = os.path.join(any_store.root, "tenants", ruled_tenant_dir("local"), "assets")
        assert os.listdir(assets) == [f"{asset}.json"]


def test_ticketed_reads_answer_every_missing_case_alike(any_store):
    asset = put(any_store)
    other_asset = put(any_store, vector("mono_nsif101.ntf"))
    authority = TicketAuthority(EVERYTHING)
    with pytest.raises(PolicyDenied):
        any_store.open_original(asset, ticket(authority, Artefact.PIXELS, asset))
    foreign = ticket(authority, Artefact.ORIGINAL, other_asset)
    other_tenant = ticket(authority, Artefact.ORIGINAL, asset, Principal("tenant-two", "someone"))
    revoked = ticket(authority, Artefact.ORIGINAL, asset)
    authority.revoke(revoked)
    unknown = "0b4f6c26-0b7e-5b8e-9c1d-4e5f6a7b8c9d"
    answers = set()
    for asset_id, given in (
        (asset, foreign),
        (asset, other_tenant),
        (unknown, foreign),
        (asset, revoked),
    ):
        with pytest.raises(HostError) as caught:
            any_store.open_original(asset_id, given)
        answers.add(str(caught.value))
    assert answers == {"E_POLICY @byte - /asset: no such asset for this ticket"}
    with any_store.open_original(asset, ticket(authority, Artefact.ORIGINAL, asset)) as reader:
        assert (reader.read(), reader.size, reader.sha256) == (GEO_DMS, len(GEO_DMS), GEO_SHA)


def test_each_read_accepts_its_own_ticket_kind_only(any_store):
    asset = put(any_store)
    authority = TicketAuthority(EVERYTHING)
    with pytest.raises(PolicyDenied):
        any_store.open_source_fd(asset, ticket(authority, Artefact.ORIGINAL, asset))
    with pytest.raises(PolicyDenied):
        any_store.open_original(asset, ticket(authority, Artefact.THUMBNAIL, asset))
    for kind in (Artefact.PIXELS, Artefact.THUMBNAIL):
        descriptor = any_store.open_source_fd(asset, ticket(authority, kind, asset))
        try:
            assert os.pread(descriptor, 9, 0) == b"NSIF01.01"
            with pytest.raises(OSError):
                os.write(descriptor, b"x")
        finally:
            os.close(descriptor)


def test_thumbnails_can_be_approved_while_originals_and_pixels_are_not(any_store):
    asset = put(any_store)
    authority = TicketAuthority(FakePolicy({Artefact.METADATA: True, Artefact.THUMBNAIL: True}))
    os.close(any_store.open_source_fd(asset, ticket(authority, Artefact.THUMBNAIL, asset)))
    for kind in (Artefact.ORIGINAL, Artefact.PIXELS):
        with pytest.raises(PolicyDenied):
            ticket(authority, kind, asset)


def _derivative_temp(store, payload=b"\x89PNG-derivative"):
    job = store.new_job(tenant="local")
    temp = store.new_temp(job, ".png")
    descriptor = store.open_temp(temp)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    return job, temp


def test_a_derivative_inherits_a_registered_descriptor_and_its_digest_is_checked(any_store):
    asset = put(any_store)
    second = SecurityDescriptor.from_container(
        parse_container(GEO_DMS, CORE1_LIMITS), ExtensionRegistry("test-neutral-1", frozenset())
    )
    assert put(any_store, descriptor=second) == asset
    third = SecurityDescriptor.from_container(
        parse_container(vector("image_and_text.ntf"), CORE1_LIMITS), EMPTY_REGISTRY
    )
    authority = TicketAuthority(EVERYTHING)
    thumb = ticket(authority, Artefact.THUMBNAIL, asset)
    payload = b"\x89PNG-derivative"
    job, temp = _derivative_temp(any_store, payload)
    digest = hashlib.sha256(payload).hexdigest()
    with pytest.raises(HostError) as caught:
        any_store.commit_derivative(
            asset, temp, digest, {"a": 1}, third, tenant="local", policy_ticket=thumb, provenance={}
        )
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/derivative/security")
    with pytest.raises(HostError) as caught:
        any_store.commit_derivative(
            asset,
            temp,
            "0" * 64,
            {"a": 1},
            DESCRIPTOR,
            tenant="local",
            policy_ticket=thumb,
            provenance={},
        )
    assert caught.value.code == "E_INTEGRITY"
    first_id = any_store.commit_derivative(
        asset,
        temp,
        digest,
        {"a": 1},
        DESCRIPTOR,
        tenant="local",
        policy_ticket=thumb,
        provenance={"p": 1},
    )
    _, temp_two = _derivative_temp(any_store, payload)
    second_id = any_store.commit_derivative(
        asset,
        temp_two,
        digest,
        {"a": 1},
        second,
        tenant="local",
        policy_ticket=thumb,
        provenance={},
    )
    assert first_id != second_id
    record = any_store.read_derivative(first_id, tenant="local")
    assert (record["parent_id"], record["descriptor"], record["sha256"], record["bytes"]) == (
        asset,
        DESCRIPTOR.json_text,
        digest,
        len(payload),
    )
    with any_store.open_derivative(first_id, thumb, tenant="local") as reader:
        assert reader.read() == payload
    authority.revoke_asset(asset)
    with pytest.raises(HostError) as caught:
        any_store.open_derivative(first_id, thumb, tenant="local")
    assert caught.value.code == "E_POLICY"


def test_the_derivatives_of_a_parent_are_listed_by_id_in_its_tenant_only(any_store):
    asset = put(any_store)
    other = put(any_store, vector("mono_nsif101.ntf"))
    authority = TicketAuthority(EVERYTHING)
    made = []
    for parent, recipe in ((asset, {"a": 1}), (asset, {"a": 2}), (other, {"a": 1})):
        _, temp = _derivative_temp(any_store, b"\x89PNG-" + recipe["a"].to_bytes(1, "big"))
        made.append(
            any_store.commit_derivative(
                parent,
                temp,
                any_store.temp_digest(temp)[1],
                recipe,
                DESCRIPTOR,
                tenant="local",
                policy_ticket=ticket(authority, Artefact.THUMBNAIL, parent),
                provenance={},
            )
        )
    assert any_store.list_derivatives(asset, tenant="local") == sorted(made[:2])
    assert any_store.list_derivatives(other, tenant="local") == [made[2]]
    assert any_store.list_derivatives(asset, tenant="tenant-two") == []
    assert any_store.list_derivatives("../x", tenant="local") == []
    assert any_store.list_derivatives(ruled_asset_id("local", "0" * 64), tenant="local") == []


def test_a_derivative_needs_a_live_temporary_of_its_own_job(any_store):
    asset = put(any_store)
    thumb = ticket(TicketAuthority(EVERYTHING), Artefact.THUMBNAIL, asset)
    job, temp = _derivative_temp(any_store)
    other_job, _ = _derivative_temp(any_store)
    digest = any_store.temp_digest(temp)[1]
    cases = [TempFile(other_job, temp.name), TempFile(job, "f" * 32 + ".png")]
    any_store.delete_uncommitted(job)
    cases.append(temp)
    for case in cases:
        with pytest.raises(HostError) as caught:
            any_store.commit_derivative(
                asset,
                case,
                digest,
                {},
                DESCRIPTOR,
                tenant="local",
                policy_ticket=thumb,
                provenance={},
            )
        assert (caught.value.code, caught.value.stage, caught.value.path) == (
            "E_IO",
            "storage",
            "/temp_file",
        )


def _record_temp(store, octets=GEO_DMS):
    """A committed product's record, through the service, then its id and record re-committed."""
    service = IngestService(store, worker=InProcessWorker())
    result = service.ingest(octets, principal=LOCAL, dataset_namespace="default", synthetic=True)
    record = store.read_record("local", result["record_id"], area="records")
    return result, record


def test_a_record_is_committed_once_with_one_revision_and_one_slot(any_store):
    result, record = _record_temp(any_store)
    job = any_store.new_job(tenant="local")
    temp = any_store.new_temp(job, ".json")
    descriptor = any_store.open_temp(temp)
    try:
        os.write(descriptor, json.dumps(record).encode())
    finally:
        os.close(descriptor)
    from helpers import ruled_dedup_id

    dedup = ruled_dedup_id("local", "default", True, result["sha256"], 1)
    linked = any_store.commit_record(
        job,
        temp,
        tenant="local",
        area="records",
        record_id=result["record_id"],
        dedup_id=dedup,
        dedup_slot="committed",
        entity_id=record["entity_id"],
    )
    assert linked is False
    product = any_store.read_product("local", record["entity_id"])
    assert [entry["record_id"] for entry in product["revisions"]] == [result["record_id"]]
    assert any_store.lookup_dedup("local", dedup) == {
        "committed": result["record_id"],
        "policy_blocked": None,
        "rejected": None,
    }
    any_store.delete_uncommitted(job)


def test_a_record_commit_is_first_true_then_false(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    calls = []

    class Recording(LocalAssetStore):
        def commit_record(self, *args, **kwargs):
            outcome = super().commit_record(*args, **kwargs)
            calls.append(outcome)
            return outcome

    recording = Recording(tmp_path / "store")
    service = IngestService(recording, worker=InProcessWorker())
    first = service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    _, record = first, store.read_record("local", first["record_id"], area="records")
    job = recording.new_job(tenant="local")
    temp = recording.new_temp(job, ".json")
    descriptor = recording.open_temp(temp)
    os.write(descriptor, json.dumps(record).encode())
    os.close(descriptor)
    from helpers import ruled_dedup_id

    recording.commit_record(
        job,
        temp,
        tenant="local",
        area="records",
        record_id=first["record_id"],
        dedup_id=ruled_dedup_id("local", "default", True, first["sha256"], 1),
        dedup_slot="committed",
        entity_id=record["entity_id"],
    )
    assert calls == [True, False]
    tenant = tmp_path / "store" / "tenants" / ruled_tenant_dir("local")
    assert os.listdir(tenant / "records") == [f"{first['record_id']}.json"]
    assert len(os.listdir(tenant / "dedup")) == 1


# --------------------------------------------------------------------------- the local layout

WRITABLE = ("dedup", "products", "published")


def _modes(root):
    seen = {}
    for directory, folders, files in os.walk(root):
        seen[directory] = stat.S_IMODE(os.lstat(directory).st_mode)
        for name in files:
            path = os.path.join(directory, name)
            seen[path] = stat.S_IMODE(os.lstat(path).st_mode)
    return seen


def _expected_mode(root, path):
    if os.path.isdir(path):
        return 0o700
    relative = os.path.relpath(path, root).split(os.sep)
    if relative == ["lock"] or relative[-1] == "journal.json":
        return 0o600
    if relative[0] == "tenants" and relative[2] in WRITABLE:
        return 0o600
    return 0o400


def test_every_directory_and_file_has_its_ruled_mode(tmp_path):
    root = tmp_path / "store"
    store = LocalAssetStore(root)
    service = IngestService(
        store, worker=InProcessWorker(), retention=RetentionPolicy(retain_rejected=True)
    )
    assert (
        service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)[
            "state"
        ]
        == "committed"
    )
    assert (
        service.ingest(
            vector("unknown_duplicate_tre.ntf"),
            principal=LOCAL,
            dataset_namespace="default",
            synthetic=True,
        )["state"]
        == "policy_blocked"
    )
    rejected = service.ingest(
        vector("bad_count.ntf"), principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    assert rejected["state"] == "rejected" and rejected["asset_id"] is not None
    modes = _modes(str(root))
    assert len(modes) > 20
    wrong = {
        path: oct(mode) for path, mode in modes.items() if mode != _expected_mode(str(root), path)
    }
    assert wrong == {}
    names = {os.path.relpath(path, root) for path in modes}
    tenant = os.path.join("tenants", ruled_tenant_dir("local"))
    for expected in (
        "originals",
        "quarantine/originals",
        "rejected/originals",
        "records",
        "quarantine/records",
        "rejected/records",
        "assets",
        "descriptors",
        "dedup",
        "products",
        "published",
    ):
        assert os.path.join(tenant, expected) in names
    assert not [name for name in names if name.endswith(".tmp")]
    assert os.listdir(root / "staging") == []


def test_the_store_root_is_initialised_or_recognised_and_nothing_else(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir(mode=0o755)
    LocalAssetStore(empty)
    assert stat.S_IMODE(empty.stat().st_mode) == 0o700
    assert (empty / "sc-imagery-store.json").read_bytes() == b'{"format":"sc-imagery-store/1"}'
    LocalAssetStore(empty)
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "something").write_text("x")
    with pytest.raises(ValueError):
        LocalAssetStore(busy)
    a_file = tmp_path / "file"
    a_file.write_text("x")
    with pytest.raises(ValueError):
        LocalAssetStore(a_file)
    link = tmp_path / "link"
    link.symlink_to(empty)
    with pytest.raises(ValueError):
        LocalAssetStore(link)
    forged = tmp_path / "forged"
    forged.mkdir()
    (forged / "sc-imagery-store.json").write_text('{"format":"other"}')
    with pytest.raises(ValueError):
        LocalAssetStore(forged)
    with pytest.raises(ValueError):
        LocalAssetStore(tmp_path / "missing" / "store")


def test_a_staging_directory_is_emptied_by_name_and_nothing_else_is_deleted(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_text("keep")
    for bad in ("../x", "0" * 31, "../../" + "0" * 26):
        with pytest.raises(HostError):
            store.delete_uncommitted(bad)
    linked = "a" * 32
    (tmp_path / "store" / "staging" / linked).symlink_to(outside)
    with pytest.raises(HostError):
        store.delete_uncommitted(linked)
    job = store.new_job(tenant="local")
    (tmp_path / "store" / "staging" / job / "nested").mkdir()
    with pytest.raises(HostError):
        store.delete_uncommitted(job)
    assert (tmp_path / "store" / "staging" / job / "nested").is_dir()
    assert sentinel.read_text() == "keep"
    assert sorted(os.listdir(outside)) == ["sentinel"]
    (tmp_path / "store" / "staging" / job / "nested").rmdir()
    store.new_temp(job, ".source")
    assert store.delete_uncommitted(job) == 3
    assert not (tmp_path / "store" / "staging" / job).exists()


def test_no_symlink_inside_the_store_is_followed(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    outside = tmp_path / "outside"
    outside.mkdir()
    tenant = tmp_path / "store" / "tenants" / ruled_tenant_dir("local")
    tenant.mkdir(parents=True)
    (tenant / "originals").symlink_to(outside)
    with pytest.raises(HostError) as caught:
        put(store)
    assert caught.value.code == "E_IO"
    assert os.listdir(outside) == []


def test_two_threads_ingesting_the_same_octets_commit_one_record(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    service = IngestService(store, worker=InProcessWorker())
    results = []
    barrier = threading.Barrier(2)

    def run():
        barrier.wait()
        results.append(
            service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
        )

    threads = [threading.Thread(target=run) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(results) == 2 and results[0] == results[1]
    assert results[0]["state"] == "committed"
    tenant = tmp_path / "store" / "tenants" / ruled_tenant_dir("local")
    assert os.listdir(tenant / "records") == [f"{results[0]['record_id']}.json"]
    assert os.listdir(tenant / "originals") == [results[0]["asset_id"]]
    product = json.loads(next((tenant / "products").iterdir()).read_text())
    assert len(product["revisions"]) == 1
    assert not [path for path in (tmp_path / "store").rglob("*.tmp")]
