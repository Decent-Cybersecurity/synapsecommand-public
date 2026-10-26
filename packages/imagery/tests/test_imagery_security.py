"""Security tests of the host, one per clause of the engineering kit's security-test list (its
requirement REQ-081), with literal expectations: source-level U never releases unknown
restrictions, every derivative inherits its parent's labels, a footprint cannot bypass its
parent's policy, caches do not cross tenants, text never executes, paths cannot traverse the
store, sidecars and URLs are never fetched, policy is checked on every read, rejected inputs do
not leak coordinates or text into logs, and each label field changed in turn is preserved and
decided. The byte-range clause has no HTTP subject here; its local equivalent is the reader that
re-checks its ticket on every read (the eighth test)."""

from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys

import pytest
from helpers import (
    SECURITY_FIELDS,
    build_nsif,
    des,
    image,
    ruled_tenant_dir,
    security,
    store_files,
    text,
    tre,
    vector,
    with_security_field,
)

import synapse_imagery
from synapse_imagery import cli
from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.ingest import inspect_source
from synapse_imagery.policy import (
    Artefact,
    DefaultPolicy,
    PolicyDenied,
    PolicyRequest,
    Principal,
    SecurityDescriptor,
    TicketAuthority,
)
from synapse_imagery.result import HostError
from synapse_imagery.worker import Window, WorkerLimits, WorkerPool

ALLOW_ALL = FakePolicy({artefact: True for artefact in Artefact})
LOCAL = Principal("local", "local-operator")
GEO = "480000N0170000E480000N0180000E470000N0180000E470000N0170000E"
GEO_DMS = vector("geo_dms.ntf")
SLOW_CHILD = str(pathlib.Path(__file__).with_name("slow_child.py"))
DISTRIBUTION = pathlib.Path(synapse_imagery.__file__).resolve().parents[1]
BLOCKED_DECISION = {
    "allowed": False,
    "completeness": "complete",
    "policy_id": "sc-imagery-default-clean-u",
    "policy_version": "1",
    "reason": "STATUS_NOT_DECLARED_UNCLASSIFIED",
}
BLOCKED_DIAGNOSTIC = {
    "code": "E_POLICY",
    "stage": "security",
    "offset": None,
    "path": "/policy/metadata",
    "message": (
        "publication refused by policy sc-imagery-default-clean-u/1: "
        "STATUS_NOT_DECLARED_UNCLASSIFIED"
    ),
}
KIT_IMAGES = (
    "mono_nsif101.ntf",
    "mono_nsif100.ntf",
    "mono_nitf210.ntf",
    "geo_dms.ntf",
    "mode_B.ntf",
    "mode_P.ntf",
    "mode_R.ntf",
    "mode_S.ntf",
    "uint16.ntf",
    "image_and_text.ntf",
)


class Counting(InProcessWorker):
    def __init__(self) -> None:
        super().__init__()
        self.previews = 0

    def make_preview(self, *arguments, **options):
        self.previews += 1
        return super().make_preview(*arguments, **options)


@pytest.mark.parametrize("name", KIT_IMAGES)
def test_every_derivative_inherits_its_parents_labels(services, store, tmp_path, name):
    principal = Principal("local", "local-operator")
    service = services(store, worker=InProcessWorker())
    result = service.ingest(
        vector(name), principal=principal, dataset_namespace="default", synthetic=True
    )
    assert result["state"] == "committed"
    receipt = service.preview(result["record_id"], 0, tmp_path / "p.png", principal=principal)
    record = store.read_record("local", result["record_id"], area="records")
    stored = store.read_derivative(receipt["derivative_id"], tenant="local")
    assert stored["descriptor"] == record["descriptor"]
    assert stored["parent_id"] == result["asset_id"]
    # A PNG is not public because it is a PNG: its octets need a thumbnail ticket on the parent.
    descriptor = SecurityDescriptor.from_json(record["descriptor"])
    authority = service._authority
    for artefact in (Artefact.PIXELS, Artefact.ORIGINAL, Artefact.METADATA):
        ticket = authority.issue(
            PolicyRequest(principal, artefact, descriptor, True, None, result["asset_id"])
        )
        with pytest.raises(HostError) as caught:
            store.open_derivative(receipt["derivative_id"], ticket, tenant="local")
        assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/thumbnail")


def test_caches_do_not_cross_tenants(services, store, tmp_path):
    octets = vector("geo_dms.ntf")
    first, second = Principal("t1", "a"), Principal("t2", "a")
    worker = Counting()
    service = services(store, worker=worker)
    results = [
        service.ingest(octets, principal=who, dataset_namespace="default", synthetic=True)
        for who in (first, second)
    ]
    receipts = [
        service.preview(result["record_id"], 0, tmp_path / f"{index}.png", principal=who)
        for index, (result, who) in enumerate(zip(results, (first, second)))
    ]
    # The second tenant's preview ran its own job: no derivative is shared across tenants.
    assert worker.previews == 2
    for key in ("record_id", "asset_id"):
        assert results[0][key] != results[1][key]
    assert receipts[0]["derivative_id"] != receipts[1]["derivative_id"]
    assert (tmp_path / "0.png").read_bytes() == (tmp_path / "1.png").read_bytes()
    assert store.read_derivative(receipts[0]["derivative_id"], tenant="t2") is None
    assert store.list_derivatives(results[0]["asset_id"], tenant="t2") == []
    with pytest.raises(HostError) as caught:
        service.catalog.get(results[0]["record_id"], principal=second)
    assert str(caught.value) == (
        "E_FIELD @byte - /record_id: no committed record with this id for this principal"
    )
    with pytest.raises(HostError) as caught:
        service.preview(results[0]["record_id"], 0, tmp_path / "x.png", principal=second)
    assert caught.value.path == "/record_id"


PAYLOADS = (b"$(touch PWNED)", b"__import__('os').system('touch PWNED')", b"<script>x</script>")


def test_text_never_executes(services, store, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    octets = build_nsif(
        [image(tres=b"".join(tre("SCZZZZ", payload) for payload in PAYLOADS))],
        texts=[text(payload=payload) for payload in PAYLOADS],
        ftitle="$(touch PWNED)",
    )
    service = services(store, worker=InProcessWorker(), policy=ALLOW_ALL)
    principal = Principal("local", "local-operator")
    result = service.ingest(
        octets, principal=principal, dataset_namespace="default", synthetic=True
    )
    assert result["state"] == "committed"
    inspect_source(octets, worker=InProcessWorker())
    service.replay_original(result["record_id"], tmp_path / "r.ntf", principal=principal)
    service.preview(result["record_id"], 0, tmp_path / "p.png", principal=principal)
    service.catalog.presentation(result["record_id"], principal=principal)
    assert (tmp_path / "r.ntf").read_bytes() == octets
    found = [path for path in pathlib.Path(tmp_path).rglob("*") if "PWNED" in path.name]
    assert found == [] and not os.path.exists("PWNED")


def ingest_as(service, octets, principal=LOCAL):
    return service.ingest(octets, principal=principal, dataset_namespace="default", synthetic=True)


def cdm_files(root) -> list[pathlib.Path]:
    """Every stored file that holds a CDM object (each object names its kind)."""
    return [
        path for path in store_files(pathlib.Path(root)) if b'"object_kind"' in path.read_bytes()
    ]


# --------------------------------------------------------------------------- clause 1


def test_source_level_U_does_not_release_unknown_restrictions(services, store):
    """Every label says U, yet two unknown TREs, or one DES, leave semantics core cannot know:
    the default gate blocks the product, nothing is published, and inspect warns."""
    with_des = build_nsif([image(icords="G", igeolo=GEO)], des_segments=[des()])
    service = services(store, worker=InProcessWorker())
    cases = (
        (vector("unknown_duplicate_tre.ntf"), {"tre": 2, "des": 0, "res": 0}, 2),
        (with_des, {"tre": 0, "des": 1, "res": 0}, 1),
    )
    for octets, counts, unidentified in cases:
        result = ingest_as(service, octets)
        assert (result["state"], result["cdm_ids"]) == ("policy_blocked", [])
        # No extension is registered as security-neutral, so the assessment is also incomplete.
        assert result["diagnostics"] == [
            BLOCKED_DIAGNOSTIC,
            {
                "code": "POLICY_ASSESSMENT_INCOMPLETE",
                "stage": "security",
                "offset": None,
                "path": "/security/extensions",
                "message": f"{unidentified} extension record(s) not identified as "
                "security-neutral by registry sc4545-core-1-empty",
            },
        ]
        record = service.catalog.read_quarantined(result["record_id"], principal=LOCAL)
        decision = {**BLOCKED_DECISION, "completeness": "incomplete"}
        assert (record["decision"], record["objects"]) == (decision, [])
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        assert [label["fields"]["CLAS"] for label in descriptor.labels] == ["U"] * (
            len(descriptor.labels)
        )
        assessment = descriptor.assessment
        assert (assessment["status"], assessment["reasons"]) == (
            "unresolved",
            ["UNKNOWN_EXTENSION"],
        )
        assert (assessment["clas_values"], assessment["unknown_extensions"]) == (["U"], counts)
        with pytest.raises(HostError) as caught:
            service.catalog.get(result["record_id"], principal=LOCAL)
        assert (caught.value.code, caught.value.path) == ("E_FIELD", "/record_id")
        document = inspect_source(octets, worker=InProcessWorker())
        assert document["warnings"] == ["POLICY_UNRESOLVED"]
        assert (document["policy"]["allowed"], document["policy"]["reason"]) == (
            False,
            "STATUS_NOT_DECLARED_UNCLASSIFIED",
        )
    assert service.catalog.list_records(principal=LOCAL) == []
    assert cdm_files(store.root) == []
    # The same U image without the DES is released, and inspect does not warn.
    plain = build_nsif([image(icords="G", igeolo=GEO)])
    assert ingest_as(service, plain)["state"] == "committed"
    assert inspect_source(plain, worker=InProcessWorker())["warnings"] == []


# --------------------------------------------------------------------------- clause 3


def test_a_footprint_cannot_bypass_its_parents_policy(services, store):
    service = services(store, worker=InProcessWorker())
    committed = ingest_as(service, GEO_DMS)
    product, footprint = service.catalog.objects(committed["record_id"], principal=LOCAL)
    on_product = product["residual"]["data"]["stanag4545"]["security"]
    on_footprint = footprint["residual"]["data"]["stanag4545"]["security"]
    # The footprint carries the file label, its image's label and the product-wide assessment,
    # so a gate that reads only the footprint decides as it does on the product.
    assert on_footprint["assessment"] == on_product["assessment"]
    assert on_footprint["labels"] == on_product["labels"][:2]
    record_text = store.read_record("local", committed["record_id"], area="records")["descriptor"]
    stored = json.loads(record_text)
    names = [name for name, _, _ in SECURITY_FIELDS]
    keys = ["scope", "index", "offset", "length", "fields", "uninterpreted"]
    assembled = SecurityDescriptor(
        json.dumps(
            {
                "labels": [
                    {
                        **{key: label[key] for key in keys},
                        "fields": {n: label["fields"][n] for n in names},
                    }
                    for label in on_footprint["labels"]
                ],
                "assessment": {
                    **{key: on_footprint["assessment"][key] for key in stored["assessment"]},
                    "unknown_extensions": {
                        key: on_footprint["assessment"]["unknown_extensions"][key]
                        for key in ("tre", "des", "res")
                    },
                },
                "extensions": [],
                "registry_version": stored["registry_version"],
            },
            ensure_ascii=True,
            separators=(",", ":"),
        )
    )
    gate = DefaultPolicy()
    for artefact in Artefact:
        from_footprint = gate.decide(PolicyRequest(LOCAL, artefact, assembled, True, None, None))
        recorded = SecurityDescriptor.from_json(record_text)
        from_record = gate.decide(PolicyRequest(LOCAL, artefact, recorded, True, None, None))
        assert from_footprint == from_record and from_footprint.allowed is True
    # An image labelled R: the product is blocked, and no footprint exists anywhere in the store.
    restricted = ingest_as(service, with_security_field(GEO_DMS, "image", "CLAS", "R"))
    assert (restricted["state"], restricted["cdm_ids"]) == ("policy_blocked", [])
    assert [image["geometry_status"] for image in restricted["images"]] == ["policy_blocked"]
    quarantined = service.catalog.read_quarantined(restricted["record_id"], principal=LOCAL)
    assert quarantined["objects"] == []
    for call in (service.catalog.objects, service.catalog.presentation, service.catalog.get):
        with pytest.raises(HostError) as caught:
            call(restricted["record_id"], principal=LOCAL)
        assert (caught.value.code, caught.value.path) == ("E_FIELD", "/record_id")
    holding = cdm_files(store.root)
    assert len(holding) == 1 and committed["record_id"] in holding[0].name
    assert service.catalog.list_records(principal=LOCAL) == [committed["record_id"]]


# --------------------------------------------------------------------------- clause 6


def test_paths_cannot_traverse_the_store(services, tmp_path):
    root = tmp_path / "store"
    store = LocalAssetStore(root)
    service = services(store, worker=InProcessWorker())
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep").write_bytes(b"keep")
    titled = build_nsif([image()], ftitle="../../etc/passwd", oname="../outside/keep")
    for tenant in ("../x", "..", "/abs", "%2e%2e"):
        principal = Principal(tenant, "local-operator")
        for octets in (GEO_DMS, titled):
            assert ingest_as(service, octets, principal)["state"] == "committed"
    # Tenants become derived directory names, never path text.
    tenants = sorted(os.listdir(root / "tenants"))
    assert tenants == sorted(ruled_tenant_dir(t) for t in ("../x", "..", "/abs", "%2e%2e"))
    for path in store_files(tmp_path):
        assert path.resolve().is_relative_to(root.resolve()) or path.parent == outside, path
    assert sorted(os.listdir(outside)) == ["keep"] and (outside / "keep").read_bytes() == b"keep"
    # A record id that is path text is no id: the catalog's single answer, the command's exit 2.
    for record_id in ("../../x", "%2e%2e", "/etc/passwd", ".."):
        with pytest.raises(HostError) as caught:
            service.catalog.get(record_id, principal=LOCAL)
        assert (caught.value.code, caught.value.path) == ("E_FIELD", "/record_id")
    environment = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(DISTRIBUTION),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    for record_id in ("../../x", "%2e%2e"):
        done = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "synapse_imagery",
                "replay",
                record_id,
                "--store",
                str(root),
                "--output",
                str(tmp_path / "r.ntf"),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert (done.returncode, done.stdout, done.stderr) == (
            2,
            "",
            "sc-imagery: replay E_FIELD\n",
        )
    assert not (tmp_path / "r.ntf").exists()
    # A job id that is path text is refused before any name is built from it.
    for job in ("../x", "..", "/abs", "%2e%2e", "0" * 31, "G" * 32):
        with pytest.raises(HostError) as caught:
            store.delete_uncommitted(job)
        assert (caught.value.code, caught.value.stage, caught.value.path) == (
            "E_IO",
            "storage",
            "/store",
        )
    assert sorted(os.listdir(outside)) == ["keep"] and os.listdir(root / "staging") == []


# --------------------------------------------------------------------------- clause 7

_EVENTS: list = []
_RECORDING: list = []


def _record(event, args):
    if _RECORDING and (event.startswith("socket.") or event == "open"):
        _EVENTS.append((event, args[0] if args else None))


sys.addaudithook(_record)


def test_sidecars_and_urls_are_never_fetched(services, tmp_path):
    hostile = build_nsif(
        [image(icords="G", igeolo=GEO, tres=tre("SCURLX", b"http://127.0.0.1:9/x"))],
        texts=[text(payload=b"file:///etc/hosts")],
    )
    source = tmp_path / "hostile.ntf"
    source.write_bytes(hostile)
    sidecar = tmp_path / "hostile.ntf.aux.xml"
    sidecar.write_text("<PAMDataset/>")
    store = LocalAssetStore(tmp_path / "store")
    # The isolated worker (the service's own pool), with this process's hook recording.
    service = services(store, policy=ALLOW_ALL)
    _EVENTS.clear()
    _RECORDING.append(True)
    try:
        result = service.ingest(
            source, principal=LOCAL, dataset_namespace="default", synthetic=True
        )
        receipt = service.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
        service.replay_original(result["record_id"], tmp_path / "r.ntf", principal=LOCAL)
    finally:
        _RECORDING.clear()
    assert result["state"] == "committed" and receipt["derivative_id"]
    assert [event for event, _ in _EVENTS if event.startswith("socket.")] == []
    opened = [
        os.fsdecode(target)
        for event, target in _EVENTS
        if event == "open" and isinstance(target, (str, bytes, os.PathLike))
    ]
    assert str(sidecar) not in opened and "/etc/hosts" not in opened
    # The child itself refuses what a hostile reader would try: a connection, the sidecar, a file
    # outside its source, a write in its private directory and a spawned process.
    aux = tmp_path / "starts"
    pool = WorkerPool(
        WorkerLimits(),
        _child_command=[sys.executable, "-I", "-B", SLOW_CHILD, "probe", str(aux), str(sidecar)],
    )
    answer, _ = pool._exchange({"probe": True}, pass_fds=(), stage="input", deadline=5.0)
    probe = answer["probe"]
    assert {key: probe[key] for key in ("socket", "sidecar", "hosts", "write", "spawn")} == {
        "socket": "refused",
        "sidecar": "refused",
        "hosts": "refused",
        "write": "refused",
        "spawn": "refused",
    }


# --------------------------------------------------------------------------- clause 8


def test_policy_is_checked_on_every_read(services, store, tmp_path):
    allow = services(store, worker=InProcessWorker(), policy=ALLOW_ALL)
    result = ingest_as(allow, GEO_DMS)
    receipt = allow.preview(result["record_id"], 0, tmp_path / "p.png", principal=LOCAL)
    descriptor = SecurityDescriptor.from_json(
        store.read_record("local", result["record_id"], area="records")["descriptor"]
    )
    asset = result["asset_id"]
    # The original's reader checks its ticket on every read: a revocation stops it mid-stream.
    authority = TicketAuthority(ALLOW_ALL)
    ticket = authority.issue(PolicyRequest(LOCAL, Artefact.ORIGINAL, descriptor, True, None, asset))
    reader = store.open_original(asset, ticket)
    assert reader.read(100) == GEO_DMS[:100]
    authority.revoke(ticket)
    with pytest.raises(HostError) as caught:
        reader.read(100)
    assert caught.value.code == "E_POLICY"
    reader.close()
    # A derivative is read under a thumbnail ticket on its parent; revoking the parent's tickets
    # stops the next read.
    thumbnail = authority.issue(
        PolicyRequest(LOCAL, Artefact.THUMBNAIL, descriptor, True, None, asset)
    )
    store.open_derivative(receipt["derivative_id"], thumbnail, tenant="local").close()
    authority.revoke_asset(asset)
    with pytest.raises(HostError) as caught:
        store.open_derivative(receipt["derivative_id"], thumbnail, tenant="local")
    assert caught.value.code == "E_POLICY"
    # Each read operation of the service asks the current policy for its own artefact.
    record_id = result["record_id"]
    reads = (
        (Artefact.METADATA, lambda s: s.catalog.objects(record_id, principal=LOCAL)),
        (
            Artefact.PIXELS,
            lambda s: s.decode_window(record_id, 0, Window(0, 0, 2, 2), (0,), principal=LOCAL),
        ),
        (
            Artefact.ORIGINAL,
            lambda s: s.replay_original(record_id, tmp_path / "r.ntf", principal=LOCAL),
        ),
        (
            Artefact.THUMBNAIL,
            lambda s: s.preview(record_id, 0, tmp_path / "q.png", principal=LOCAL),
        ),
    )
    for artefact, read in reads:
        denying = FakePolicy({each: each is not artefact for each in Artefact})
        service = services(store, worker=InProcessWorker(), policy=denying)
        with pytest.raises(PolicyDenied) as caught:
            read(service)
        assert (caught.value.code, caught.value.path) == ("E_POLICY", f"/policy/{artefact.value}")
    assert not (tmp_path / "r.ntf").exists() and not (tmp_path / "q.png").exists()


# --------------------------------------------------------------------------- clause 9

NEEDLES = ("SECRETXYZ", "480000N", "0170000E")


def test_rejected_inputs_do_not_leak_coordinates_or_text_in_logs(
    services, store, tmp_path, caplog, capsys, monkeypatch
):
    planted = build_nsif(
        [
            image(
                iid1="SECRETXYZ",
                icords="G",
                igeolo=GEO,
                comments=(b"SECRETXYZ",),
                sec=security(CLTX="SECRETXYZ"),
                tres=tre("SCZZZZ", b"SECRETXYZ"),
            )
        ],
        ftitle="SECRETXYZ",
    )
    rejected = [vector(name) for name in MALFORMED_NAMES] + [planted[:-1], GEO_DMS[:-1]]
    created: list = []
    for cls in (SecurityDescriptor, PolicyRequest):
        original = cls.__post_init__

        def keep(self, _original=original):
            _original(self)
            created.append(self)

        monkeypatch.setattr(cls, "__post_init__", keep)
    caplog.set_level(logging.DEBUG, logger="synapse_imagery")
    service = services(store, worker=InProcessWorker())
    for octets in rejected:
        assert ingest_as(service, octets)["state"] == "rejected"
        assert inspect_source(octets, worker=InProcessWorker())["valid"] is False
    # The intact planted file is blocked (it holds a TRE): descriptors and requests are built.
    assert ingest_as(service, planted)["state"] == "policy_blocked"
    inspect_source(planted, worker=InProcessWorker())
    for index, octets in enumerate((planted[:-1], GEO_DMS[:-1])):
        path = tmp_path / f"cut{index}.ntf"
        path.write_bytes(octets)
        status = cli.main(
            [
                "ingest",
                str(path),
                "--store",
                str(tmp_path / "cli"),
                "--dataset",
                "default",
                "--synthetic",
                "true",
            ]
        )
        assert status == 3
        assert cli.main(["inspect", str(path), "--json", str(tmp_path / f"i{index}.json")]) == 3
    captured = capsys.readouterr()
    assert created, "the blocked file built descriptors and requests"
    # The host did log (at least one line per ingest), so the scan below reads real records.
    assert "ingest ended in state rejected" in caplog.text
    assert "ingest ended in state policy_blocked" in caplog.text
    for needle in NEEDLES:
        assert needle not in caplog.text
        assert needle not in captured.err
        for made in created:
            assert needle not in repr(made)


MALFORMED_NAMES = (
    "bad_file_length.ntf",
    "truncated.ntf",
    "trailing.ntf",
    "bad_count.ntf",
    "unsupported_stype.ntf",
)


# --------------------------------------------------------------------------- clause 10

#: The fields whose populated printable value leaves the labels declared unclassified.
ADMITTED_WHEN_POPULATED = {
    "DCTP",
    "DCDT",
    "DCXM",
    "DG",
    "DGDT",
    "CLTX",
    "CAPT",
    "CAUT",
    "CRSN",
    "SRDT",
    "CTLN",
}


@pytest.mark.parametrize("scope", ["file", "image"])
def test_each_label_field_change_is_preserved_and_decided(services, store, scope):
    """Each of the sixteen fields of the file or the image block of geo_dms changed in turn (CLAS
    to R, every other field filled with Z): the stored record, committed or quarantined, carries
    the value in its descriptor's label for that scope, and the decision is the default gate's."""
    service = services(store, worker=InProcessWorker())
    index = None if scope == "file" else 0
    for name, _, width in SECURITY_FIELDS:
        value = "R" if name == "CLAS" else "Z" * width
        result = ingest_as(service, with_security_field(GEO_DMS, scope, name, value))
        admitted = name in ADMITTED_WHEN_POPULATED
        assert result["state"] == ("committed" if admitted else "policy_blocked"), name
        area = "records" if admitted else "quarantine"
        record = store.read_record("local", result["record_id"], area=area)
        labels = SecurityDescriptor.from_json(record["descriptor"]).labels
        (label,) = [item for item in labels if (item["scope"], item["index"]) == (scope, index)]
        assert label["fields"][name] == value, name
        assert label["uninterpreted"] == []
        assert record["decision"]["allowed"] is admitted
        assert record["decision"]["reason"] == (
            "ADMITTED_DECLARED_UNCLASSIFIED" if admitted else "STATUS_NOT_DECLARED_UNCLASSIFIED"
        )
