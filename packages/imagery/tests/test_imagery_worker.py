"""The worker: the job protocol over both implementations, the child's own checks, isolation,
deadlines with the one supervised retry, the pool's bound and E_BUSY, and the memory report.
No test asserts a duration: deadline tests count child starts and read outcomes."""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import threading
import time

import pytest
from conftest import LOCAL
from helpers import KIT_SAMPLES, build_nsif, image, sha, text, tre, vector

from synapse_cdm import suite
from synapse_cdm.adapters.nsif_codec import Limits, NsifError
from synapse_cdm.adapters.stanag4545 import (
    CORE1_LIMITS,
    Stanag4545Context,
    parse_container,
    security_labels,
)
from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import FakePolicy, InProcessWorker
from synapse_imagery.ingest import IngestService
from synapse_imagery.policy import (
    EMPTY_REGISTRY,
    Artefact,
    PolicyRequest,
    SecurityDescriptor,
    TicketAuthority,
)
from synapse_imagery.preview import RenderingSpec
from synapse_imagery.result import HostError
from synapse_imagery.worker import MEMORY_EXIT_STATUS, Window, WorkerLimits, WorkerPool

SLOW_CHILD = str(pathlib.Path(__file__).with_name("slow_child.py"))
GEO_DMS = vector("geo_dms.ntf")


def source(tmp_path, octets, name="source.ntf"):
    path = tmp_path / name
    path.write_bytes(octets)
    return os.open(path, os.O_RDONLY)


@pytest.fixture(params=["pool", "in-process"])
def worker(request):
    made = WorkerPool() if request.param == "pool" else InProcessWorker()
    yield made
    if isinstance(made, WorkerPool):
        made.shutdown(kill=True)


def child(mode, aux, *extra, limits=WorkerLimits()):
    return WorkerPool(
        limits, _child_command=[sys.executable, "-I", "-B", SLOW_CHILD, mode, str(aux), *extra]
    )


def starts(aux) -> list[int]:
    return [int(line.split()[1]) for line in pathlib.Path(aux).read_text().splitlines()]


def pixels_ticket(asset="asset-1"):
    authority = TicketAuthority(FakePolicy({artefact: True for artefact in Artefact}))
    descriptor = SecurityDescriptor.from_container(
        parse_container(GEO_DMS, CORE1_LIMITS), EMPTY_REGISTRY
    )
    return authority.issue(PolicyRequest(LOCAL, Artefact.PIXELS, descriptor, True, None, asset))


# --------------------------------------------------------------------------- the protocol


def test_the_inventory_of_geo_dms_is_its_literal_record(worker, tmp_path):
    fd = source(tmp_path, GEO_DMS)
    try:
        inventory = worker.inventory(
            fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY
        )
    finally:
        os.close(fd)
    descriptor = inventory.pop("descriptor")
    assert inventory == {
        "format": "sc-imagery-inventory/1",
        "signature": "NSIF01.01",
        "clevel": 3,
        "file_size": 907,
        "header_length": 404,
        "file_date": {"status": "valid", "utc": "2026-10-04T12:00:00.000Z"},
        "segments": [
            {
                "kind": "image",
                "index": 0,
                "subheader": {"offset": 404, "length": 499},
                "data": {"offset": 903, "length": 4},
            }
        ],
        "images": [
            {
                "index": 0,
                "nrows": 2,
                "ncols": 2,
                "bands": 1,
                "nbpp": 8,
                "abpp": 8,
                "pvtype": "INT",
                "imode": "B",
                "ic": "NC",
                "irep": "MONO",
                "icat": "VIS",
                "masked": False,
                "pixel_status": "native_supported",
                "pixel_reason": None,
                "geometry_status": "available",
                "capture_date": {"status": "valid", "utc": "2026-10-04T12:00:00.000Z"},
            }
        ],
        "extension_counts": {"tre": 0, "des": 0, "res": 0},
        "composition_status": "segment_only",
        "diagnostics": [],
    }
    labels = SecurityDescriptor.from_json(descriptor).labels
    assert labels == security_labels(parse_container(GEO_DMS, CORE1_LIMITS))
    expected = "subprocess" if isinstance(worker, WorkerPool) else "none"
    assert worker.last_report["isolation"] == expected


def test_an_inventory_carries_no_descriptive_text(worker, tmp_path):
    octets = vector("image_and_text.ntf")
    fd = source(tmp_path, octets)
    try:
        inventory = worker.inventory(
            fd, expected_sha256=sha(octets), byte_count=len(octets), registry=EMPTY_REGISTRY
        )
    finally:
        os.close(fd)
    shown = json.dumps(inventory)
    for absent in (
        "<script>",
        "must remain plain text",
        "SYNTHETIC ENGINEERING VECTOR",
        "SCFIX",
        "SYNTHETIC TEST ONLY",
    ):
        assert absent not in shown


def test_a_translation_runs_with_the_hosts_verified_context(worker, tmp_path):
    fd = source(tmp_path, GEO_DMS)
    context = Stanag4545Context(asset_ref="asset-1", verified_sha256=sha(GEO_DMS))
    try:
        objects = worker.translate(
            fd, expected_sha256=sha(GEO_DMS), byte_count=907, context=context, synthetic=True
        )
        forged = Stanag4545Context(asset_ref="asset-1", verified_sha256="0" * 64)
        with pytest.raises(HostError) as caught:
            worker.translate(
                fd, expected_sha256=sha(GEO_DMS), byte_count=907, context=forged, synthetic=True
            )
    finally:
        os.close(fd)
    assert len(objects) == 2
    assert objects[0]["source"]["source_hash"] == {"algorithm": "sha256", "value": sha(GEO_DMS)}
    assert (caught.value.code, caught.value.path) == ("E_INTEGRITY", "/asset")


def test_the_mode_r_window_equals_the_kits_samples(worker, tmp_path):
    octets = vector("mode_R.ntf")
    fd = source(tmp_path, octets)
    try:
        answer = worker.decode_window(
            fd,
            0,
            Window(0, 0, 4, 4),
            (0, 1, 2),
            pixels_ticket(),
            expected_sha256=sha(octets),
            byte_count=len(octets),
        )
    finally:
        os.close(fd)
    assert list(answer.window.values()) == KIT_SAMPLES["modes"]
    assert answer.validity is None
    assert (answer.window.dtype, answer.window.shape) == ("uint8", (3, 4, 4))


def test_a_window_needs_an_outstanding_pixels_ticket(worker, tmp_path):
    fd = source(tmp_path, GEO_DMS)
    ticket = pixels_ticket()
    ticket._authority.revoke(ticket)
    try:
        with pytest.raises(HostError) as caught:
            worker.decode_window(
                fd,
                0,
                Window(0, 0, 2, 2),
                (0,),
                ticket,
                expected_sha256=sha(GEO_DMS),
                byte_count=907,
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/pixels")


@pytest.mark.parametrize(
    "edit",
    [
        lambda r: r.update(unknown=1),
        lambda r: r.pop("fd"),
        lambda r: r.update(path="/etc/hosts"),
        lambda r: r.update(nrows=100000),
        lambda r: r.update(fd=True),
        lambda r: r.update(expected_sha256="AB" * 32),
        lambda r: r.update(protocol="other/1"),
        lambda r: r.update(op="shell"),
    ],
    ids=[
        "unknown-key",
        "missing-fd",
        "path-key",
        "forged-dimension",
        "bool-fd",
        "upper-digest",
        "protocol",
        "op",
    ],
)
def test_a_request_of_another_shape_is_refused_by_the_child(tmp_path, edit):
    pool = WorkerPool()
    fd = source(tmp_path, GEO_DMS)
    request = {
        "protocol": "sc-imagery-worker/1",
        "op": "inventory",
        "fd": fd,
        "expected_sha256": sha(GEO_DMS),
        "byte_count": 907,
        "registry": EMPTY_REGISTRY.wire(),
    }
    edit(request)
    try:
        answer, payload = pool._exchange(request, pass_fds=(fd,), stage="input", deadline=5.0)
    finally:
        os.close(fd)
    assert answer["ok"] is False and payload == b""
    assert (answer["code"], answer["stage"], answer["path"]) == ("E_FIELD", "input", "/request")


def test_the_parent_reports_a_refused_request_as_its_own_defect(tmp_path):
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            InProcessWorker()._answer("inventory", {"op": "inventory", "fd": fd}, (fd,))
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.path) == ("E_INTERNAL", "/worker")


class Refusing(InProcessWorker):
    """Answers every job with one fixed refusal, as a defective or forged child would."""

    def __init__(self, code, stage, offset, path):
        super().__init__()
        self._refusal = {"code": code, "stage": stage, "offset": offset, "path": path}

    def _run(self, op, request, pass_fds):
        answer, _ = super()._run(op, request, pass_fds)
        return {"ok": False, "worker": answer["worker"], **self._refusal, "message": "x"}, b""


@pytest.mark.parametrize(
    "code, path",
    [
        ("E_LIMIT", "/worker"),
        ("E_DIGITS", "/worker"),
        ("E_MAGIC", "/worker/answer"),
        ("E_FIELD", "/request"),
        ("E_TIMEOUT", "/worker"),
    ],
)
def test_a_child_refusal_at_a_path_of_the_hosts_is_the_hosts_own_defect(tmp_path, code, path):
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            Refusing(code, "input", None, path).inventory(
                fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_INTERNAL",
        "input",
        None,
        "/worker",
    )


def test_a_core_code_at_the_worker_path_fails_the_ingest_and_catalogues_nothing(tmp_path):
    root = tmp_path / "store"
    service = IngestService(
        LocalAssetStore(root), worker=Refusing("E_LIMIT", "input", None, "/worker")
    )
    result = service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert result["state"] == "failed" and result["asset_id"] is None
    assert [(d["code"], d["stage"], d["offset"], d["path"]) for d in result["diagnostics"]] == [
        ("E_INTERNAL", "input", None, "/worker")
    ]
    assert sorted(os.listdir(root)) == ["lock", "sc-imagery-store.json", "staging", "tenants"]
    assert os.listdir(root / "staging") == [] and os.listdir(root / "tenants") == []
    # The same refusal of the octets themselves is the adapter's, and is catalogued as rejected.
    octets = Refusing("E_MAGIC", "header", 0, "/file_header/FHDR")
    again = IngestService(LocalAssetStore(root), worker=octets)
    rejected = again.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert rejected["state"] == "rejected"
    assert [(d["code"], d["stage"], d["path"]) for d in rejected["diagnostics"]][-1] == (
        "E_MAGIC",
        "header",
        "/file_header/FHDR",
    )


# --------------------------------------------------------------------------- the child's checks


def test_the_child_verifies_digest_and_length_before_parsing(worker, tmp_path):
    fd = source(tmp_path, GEO_DMS)
    try:
        for digest, count in ((sha(vector("mono_nsif101.ntf")), 907), (sha(GEO_DMS), 908)):
            with pytest.raises(HostError) as caught:
                worker.inventory(
                    fd, expected_sha256=digest, byte_count=count, registry=EMPTY_REGISTRY
                )
            assert (caught.value.code, caught.value.stage, caught.value.path) == (
                "E_INTEGRITY",
                "input",
                "/asset",
            )
    finally:
        os.close(fd)


def test_an_input_over_the_cap_is_refused_before_it_is_read(worker, tmp_path):
    octets = b"N" * 16_777_217
    fd = source(tmp_path, octets)
    try:
        with pytest.raises(NsifError) as caught:
            worker.inventory(
                fd, expected_sha256=sha(octets), byte_count=len(octets), registry=EMPTY_REGISTRY
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_LIMIT",
        "input",
        "/input",
    )


@pytest.mark.parametrize(
    "image_index, window, bands, path",
    [
        (0, Window(0, 0, 3, 2), (0,), "/window/width"),
        (0, Window(0, 0, 2, 2), (0, 0), "/window/bands"),
        (1, Window(0, 0, 2, 2), (0,), "/window/image_index"),
        (0, Window(-1, 0, 2, 2), (0,), "/window/x"),
    ],
)
def test_the_child_applies_the_adapters_window_checks_to_its_own_parse(
    worker, tmp_path, image_index, window, bands, path
):
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(NsifError) as caught:
            worker.decode_window(
                fd,
                image_index,
                window,
                bands,
                pixels_ticket(),
                expected_sha256=sha(GEO_DMS),
                byte_count=907,
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.stage, caught.value.path) == ("E_FIELD", "pixels", path)


def test_the_window_cap_is_the_injected_limits(tmp_path):
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(NsifError) as caught:
            InProcessWorker(limits=Limits(window_bytes=3)).decode_window(
                fd,
                0,
                Window(0, 0, 2, 2),
                (0,),
                pixels_ticket(),
                expected_sha256=sha(GEO_DMS),
                byte_count=907,
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_LIMIT",
        "pixels",
        "/window",
    )


def test_the_parent_refuses_arguments_that_are_not_a_window(tmp_path):
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            InProcessWorker().decode_window(
                fd,
                0,
                Window(0, 0, 2, 2),
                [0],
                pixels_ticket(),
                expected_sha256=sha(GEO_DMS),
                byte_count=907,
            )
        assert caught.value.path == "/window/bands"
        with pytest.raises(TypeError):
            Window(0, 0, True, 2)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- isolation


def test_the_child_refuses_network_sidecars_writes_and_spawning(tmp_path):
    aux = tmp_path / "starts"
    sidecar = tmp_path / "source.ntf.aux.xml"
    sidecar.write_text("<PAMDataset/>")
    pool = child("probe", aux, str(sidecar))
    before = {
        name for name in os.listdir(tempfile.gettempdir()) if name.startswith("sc-imagery-job-")
    }
    answer, _ = pool._exchange({"probe": True}, pass_fds=(), stage="input", deadline=5.0)
    probe = answer["probe"]
    assert {key: probe[key] for key in ("socket", "sidecar", "hosts", "write", "spawn")} == {
        "socket": "refused",
        "sidecar": "refused",
        "hosts": "refused",
        "write": "refused",
        "spawn": "refused",
    }
    expected = ["LC_ALL", "PATH", "PYTHONDONTWRITEBYTECODE"]
    if sys.platform == "darwin":
        expected = sorted(expected + ["__CF_USER_TEXT_ENCODING"])
    assert probe["environment"] == expected
    assert probe["threads"] == 1
    assert probe["cwd_entries"] == []
    after = {
        name for name in os.listdir(tempfile.gettempdir()) if name.startswith("sc-imagery-job-")
    }
    assert after == before, "the private job directory is removed after the job"


_EVENTS: list = []
_RECORDING = []


def _record(event, args):
    if _RECORDING and (event.startswith("socket.") or event == "open"):
        _EVENTS.append((event, args[0] if args else None))


sys.addaudithook(_record)


def test_urls_and_sidecars_in_the_source_are_never_fetched(tmp_path):
    hostile = build_nsif(
        [
            image(
                icords="G",
                igeolo="480000N0170000E480000N0180000E470000N0180000E470000N0170000E",
                tres=tre("SCURLX", b"http://127.0.0.1:9/x"),
            )
        ],
        texts=[text(payload=b"file:///etc/hosts")],
    )
    benign = build_nsif(
        [
            image(
                icords="G",
                igeolo="480000N0170000E480000N0180000E470000N0180000E470000N0170000E",
                tres=tre("SCURLX", b"a" * 20),
            )
        ],
        texts=[text(payload=b"b" * 17)],
    )
    from synapse_imagery.assets import LocalAssetStore

    outcomes = []
    for name, octets in (("hostile.ntf", hostile), ("benign.ntf", benign)):
        path = tmp_path / name
        path.write_bytes(octets)
        sidecar = tmp_path / (name + ".aux.xml")
        sidecar.write_text("<PAMDataset/>")
        for policy in (None, FakePolicy({Artefact.METADATA: True})):
            store = LocalAssetStore(tmp_path / f"store-{name}-{policy is None}")
            with IngestService(store, policy=policy) as service:
                _EVENTS.clear()
                _RECORDING.append(True)
                try:
                    result = service.ingest(
                        path, principal=LOCAL, dataset_namespace="default", synthetic=True
                    )
                finally:
                    _RECORDING.clear()
            outcomes.append((name, policy is None, result["state"]))
            assert not [event for event, _ in _EVENTS if event.startswith("socket.")]
            opened = [
                os.fsdecode(target)
                for event, target in _EVENTS
                if event == "open" and isinstance(target, (str, bytes, os.PathLike))
            ]
            assert str(sidecar) not in opened and "/etc/hosts" not in opened
    assert [state for *_, state in outcomes] == [
        "policy_blocked",
        "committed",
        "policy_blocked",
        "committed",
    ]


# --------------------------------------------------------------------------- deadlines and the pool


def test_a_timeout_kills_the_child_and_retries_once(tmp_path):
    aux = tmp_path / "starts"
    out_path = tmp_path / "output"
    out = os.open(out_path, os.O_RDWR | os.O_CREAT, 0o600)
    pool = child("write", aux, str(out), limits=WorkerLimits(parse_deadline=0.3))
    try:
        with pytest.raises(HostError) as caught:
            pool._exchange({"output_fd": out}, pass_fds=(out,), stage="input", deadline=0.3)
    finally:
        os.close(out)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_TIMEOUT",
        "input",
        "/worker",
    )
    pids = starts(aux)
    assert len(pids) == 2
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert out_path.read_bytes() == b"", "what a killed child wrote is deleted"


def test_a_deadline_bounds_every_parse_operation(tmp_path):
    aux = tmp_path / "starts"
    pool = child("sleep", aux, limits=WorkerLimits(parse_deadline=0.3))
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            pool.inventory(
                fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY
            )
    finally:
        os.close(fd)
    assert caught.value.code == "E_TIMEOUT"
    assert len(starts(aux)) == 2


def test_the_codec_deadline_bounds_a_window(tmp_path):
    aux = tmp_path / "starts"
    pool = child("sleep", aux, limits=WorkerLimits(codec_deadline=0.3))
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            pool.decode_window(
                fd,
                0,
                Window(0, 0, 2, 2),
                (0,),
                pixels_ticket(),
                expected_sha256=sha(GEO_DMS),
                byte_count=907,
            )
    finally:
        os.close(fd)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_TIMEOUT",
        "pixels",
        "/worker",
    )
    assert len(starts(aux)) == 2


def test_a_crashed_child_is_an_internal_error_without_retry(tmp_path):
    aux = tmp_path / "starts"
    with pytest.raises(HostError) as caught:
        child("exit3", aux)._exchange({}, pass_fds=(), stage="cdm", deadline=5.0)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_INTERNAL",
        "cdm",
        "/worker",
    )
    assert len(starts(aux)) == 1


@pytest.mark.parametrize("mode", ["big", "overrun"])
def test_an_answer_past_its_bound_is_refused(tmp_path, mode):
    aux = tmp_path / "starts"
    pool = child(mode, aux, limits=WorkerLimits(answer_bytes=1000))
    with pytest.raises(HostError) as caught:
        pool._exchange({}, pass_fds=(), stage="pixels", deadline=5.0)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_LIMIT",
        "pixels",
        "/worker",
    )


def test_two_run_thirty_two_wait_and_the_next_is_busy(tmp_path):
    aux = tmp_path / "starts"
    pool = child("block", aux)
    fd = source(tmp_path, GEO_DMS)
    results, errors = [], []

    def submit():
        try:
            results.append(
                pool.inventory(
                    fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY
                )
            )
        except Exception as error:  # the test records every outcome
            errors.append(error)

    threads = [threading.Thread(target=submit) for _ in range(34)]
    for thread in threads:
        thread.start()
    for _ in range(5000):
        if pool.counts() == (2, 32):
            break
        time.sleep(0.005)
    assert pool.counts() == (2, 32)
    with pytest.raises(HostError) as caught:
        pool.inventory(fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY)
    assert (caught.value.code, caught.value.stage, caught.value.path) == (
        "E_BUSY",
        "input",
        "/worker",
    )
    (tmp_path / "starts.release").write_text("go")
    for thread in threads:
        thread.join()
    os.close(fd)
    assert errors == []
    assert len(results) == 34 and all(result["file_size"] == 907 for result in results)
    assert pool.counts() == (0, 0)


@pytest.mark.parametrize(
    "options, error",
    [
        ({"workers": 3}, ValueError),
        ({"queue": 33}, ValueError),
        ({"parse_deadline": 6}, ValueError),
        ({"codec_deadline": 30.5}, ValueError),
        ({"memory_bytes": 536_870_913}, ValueError),
        ({"answer_bytes": 68_157_441}, ValueError),
        ({"workers": 0}, ValueError),
        ({"workers": True}, TypeError),
        ({"require_memory_enforcement": "yes"}, TypeError),
    ],
)
def test_limits_can_be_lowered_and_never_raised(options, error):
    with pytest.raises(error):
        WorkerLimits(**options)
    assert WorkerLimits(workers=1, queue=1, parse_deadline=0.5).workers == 1


def test_a_shut_down_pool_takes_no_job(tmp_path):
    pool = WorkerPool()
    pool.shutdown(kill=True)
    fd = source(tmp_path, GEO_DMS)
    try:
        with pytest.raises(HostError) as caught:
            pool.inventory(
                fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY
            )
    finally:
        os.close(fd)
    assert caught.value.code == "E_INTERNAL"


def test_the_child_command_is_an_argument_list():
    with pytest.raises(TypeError):
        WorkerPool(_child_command="python -c x")
    with pytest.raises(TypeError):
        WorkerPool(_child_command=["python", 5])


# --------------------------------------------------------------------------- memory


def test_the_worker_reports_its_memory_enforcement(tmp_path):
    pool = WorkerPool()
    fd = source(tmp_path, GEO_DMS)
    try:
        pool.inventory(fd, expected_sha256=sha(GEO_DMS), byte_count=907, registry=EMPTY_REGISTRY)
    finally:
        os.close(fd)
    report = pool.last_report
    expected = "rlimit_as" if sys.platform.startswith("linux") else "not_enforced"
    assert report["memory_enforcement"] == expected
    claimed = "rlimit_as" if suite.resource_limit_support()["memory_bytes"][0] else "not_enforced"
    assert report["memory_enforcement"] == claimed
    assert report == {
        "isolation": "subprocess",
        "memory_limit_bytes": 536_870_912,
        "memory_enforcement": expected,
        "cpu_affinity": "two_cpus" if hasattr(os, "sched_setaffinity") else "not_enforced",
        "deadline_enforcement": "parent_kill",
        "platform": sys.platform,
    }


def test_require_memory_enforcement_is_refused_where_the_platform_cannot_give_it():
    enforced, reason = suite.resource_limit_support()["memory_bytes"]
    if enforced:
        WorkerPool(WorkerLimits(require_memory_enforcement=True)).shutdown()
    else:
        with pytest.raises(ValueError) as caught:
            WorkerPool(WorkerLimits(require_memory_enforcement=True))
        assert str(caught.value) == reason


def test_the_memory_status_is_mapped_to_e_limit(tmp_path):
    from synapse_imagery import worker as worker_module

    assert MEMORY_EXIT_STATUS == 86
    assert worker_module._run_guarded(lambda: 0) == 0

    def exhausted():
        raise MemoryError

    assert worker_module._run_guarded(exhausted) == 86


# --------------------------------------------------------------------------- the preview operation


def thumbnail_ticket(asset="asset-1", artefact=Artefact.THUMBNAIL):
    authority = TicketAuthority(FakePolicy({each: True for each in Artefact}))
    descriptor = SecurityDescriptor.from_container(
        parse_container(GEO_DMS, CORE1_LIMITS), EMPTY_REGISTRY
    )
    return authority.issue(PolicyRequest(LOCAL, artefact, descriptor, True, None, asset))


def run_preview(worker, tmp_path, ticket, spec=None, octets=GEO_DMS):
    fd = source(tmp_path, octets)
    out_path = tmp_path / "out.png"
    out_path.write_bytes(b"")
    out = os.open(out_path, os.O_WRONLY)
    try:
        return worker.make_preview(
            fd,
            0,
            spec or RenderingSpec(),
            ticket,
            expected_sha256=sha(octets),
            byte_count=len(octets),
            output_fd=out,
        )
    finally:
        os.close(fd)
        os.close(out)


def test_a_preview_is_written_only_through_the_descriptor_it_was_handed(worker, tmp_path):
    derivative = run_preview(worker, tmp_path, thumbnail_ticket())
    written = (tmp_path / "out.png").read_bytes()
    assert (derivative.width, derivative.height, derivative.channels) == (2, 2, 1)
    assert (derivative.sha256, derivative.byte_count) == (sha(written), len(written))
    assert written[:8] == b"\x89PNG\r\n\x1a\n"
    provenance = derivative.provenance
    assert (provenance["parent_id"], provenance["parent_sha256"]) == ("asset-1", sha(GEO_DMS))
    assert provenance["worker"] == worker.last_report
    assert sorted(os.listdir(tmp_path)) == ["out.png", "source.ntf"]


@pytest.mark.parametrize("artefact", [Artefact.PIXELS, Artefact.ORIGINAL])
def test_a_preview_needs_a_thumbnail_ticket(worker, tmp_path, artefact):
    with pytest.raises(HostError) as caught:
        run_preview(worker, tmp_path, thumbnail_ticket(artefact=artefact))
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/thumbnail")
    assert (tmp_path / "out.png").read_bytes() == b""


def test_a_revoked_thumbnail_ticket_runs_no_job(tmp_path):
    starts = tmp_path / "starts"
    pathlib.Path(str(starts) + ".release").write_text("go")
    pool = child("block", starts)
    ticket = thumbnail_ticket()
    ticket._authority.revoke(ticket)
    try:
        with pytest.raises(HostError) as caught:
            run_preview(pool, tmp_path, ticket)
    finally:
        pool.shutdown(kill=True)
    assert (caught.value.code, caught.value.path) == ("E_POLICY", "/policy/thumbnail")
    assert not starts.exists()


def preview_request(fd, out, **changes):
    request = {
        "protocol": "sc-imagery-worker/1",
        "op": "make_preview",
        "fd": fd,
        "expected_sha256": sha(GEO_DMS),
        "byte_count": 907,
        "image_index": 0,
        "rendering": {"max_size": 1024, "bands": None},
        "ticket": {"artefact": "thumbnail", "asset_id": "asset-1"},
        "output_fd": out,
    }
    request.update(changes)
    return request


@pytest.mark.parametrize(
    "changes",
    [
        {"rendering": {"max_size": 5000, "bands": None}},
        {"rendering": {"max_size": 1024, "bands": [0, 1]}},
        {"rendering": {"max_size": 1024, "bands": [0, 0, 1]}},
        {"rendering": {"max_size": 1024}},
        {"ticket": {"artefact": "pixels", "asset_id": "asset-1"}},
        {"output_fd": -1},
        {"output_fd": True},
        {"nrows": 100000},
        {"path": "/tmp/preview.png"},
    ],
    ids=[
        "max-size",
        "two-bands",
        "duplicate-bands",
        "rendering-shape",
        "pixels-ticket",
        "negative-fd",
        "bool-fd",
        "forged-dimension",
        "path-key",
    ],
)
def test_a_preview_request_of_another_shape_is_refused_by_the_child(tmp_path, changes):
    pool = WorkerPool()
    fd = source(tmp_path, GEO_DMS)
    out_path = tmp_path / "out.png"
    out_path.write_bytes(b"")
    out = os.open(out_path, os.O_WRONLY)
    try:
        answer, _ = pool._exchange(
            preview_request(fd, out, **changes), pass_fds=(fd, out), stage="pixels", deadline=30.0
        )
    finally:
        os.close(fd)
        os.close(out)
        pool.shutdown(kill=True)
    assert (answer["ok"], answer["code"], answer["stage"], answer["path"]) == (
        False,
        "E_FIELD",
        "input",
        "/request",
    )
    assert out_path.read_bytes() == b""


class Lying(InProcessWorker):
    """Runs the real job, then alters one fact of the preview answer, as a forged child would."""

    def __init__(self, alter):
        super().__init__()
        self._alter = alter

    def _run(self, op, request, pass_fds):
        answer, payload = super()._run(op, request, pass_fds)
        self._alter(answer["derivative"])
        return answer, payload


@pytest.mark.parametrize(
    "alter",
    [
        lambda d: d.update(width=3),
        lambda d: d.update(channels=3),
        lambda d: d.update(sha256="0" * 64) or d.update(sha256="Z"),
        lambda d: d["provenance"].update(parent_sha256="0" * 64),
        lambda d: d["provenance"].update(parent_id="asset-2"),
        lambda d: d["provenance"].update(selection="explicit"),
        lambda d: d["provenance"].update(algorithm="sc-imagery-lut-nearest/1"),
        lambda d: d["provenance"]["software"].update(zlib="0"),
        lambda d: d["provenance"].update(size=[1, 1]),
        lambda d: d["provenance"].update(composition="composed"),
        lambda d: d["provenance"].update(image_index=1),
        lambda d: d["provenance"].update(graphic_segments=1),
        lambda d: d["provenance"].update(diagnostics=[{"code": "FILL_BITS_NONZERO"}]),
        lambda d: d["provenance"]["parameters"].update(max_size=2),
        lambda d: d["provenance"].pop("worker"),
    ],
    ids=[
        "width",
        "channels",
        "digest-form",
        "parent-digest",
        "parent-id",
        "selection",
        "algorithm",
        "software",
        "size",
        "composition",
        "image",
        "graphics-half",
        "diagnostic",
        "parameters",
        "worker-report",
    ],
)
def test_the_parent_refuses_a_forged_preview_answer_and_empties_the_output(tmp_path, alter):
    with pytest.raises(HostError) as caught:
        run_preview(Lying(alter), tmp_path, thumbnail_ticket())
    assert (caught.value.code, caught.value.stage, caught.value.path, caught.value.message) == (
        "E_INTERNAL",
        "pixels",
        "/worker",
        "the worker's preview answer is malformed",
    )
    assert (tmp_path / "out.png").read_bytes() == b""


def test_a_preview_of_an_image_outside_the_native_cell_is_the_adapters_refusal(worker, tmp_path):
    from helpers import with_ic

    octets = with_ic(vector("mono_nsif101.ntf"), "C8")
    with pytest.raises(NsifError) as caught:
        run_preview(worker, tmp_path, thumbnail_ticket(), octets=octets)
    assert (caught.value.code, caught.value.stage, caught.value.offset, caught.value.path) == (
        "E_CODEC",
        "pixels",
        777,
        "/segments/image[0]/IC",
    )
    assert (tmp_path / "out.png").read_bytes() == b""
