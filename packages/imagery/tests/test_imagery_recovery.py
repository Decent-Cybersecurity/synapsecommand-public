"""Failure and crash recovery: an exception at every step returns `failed` and publishes nothing,
a process killed at every service step and every store link point leaves a store that
`recover()` rolls back or forward with literal counts, and a live job in another process is never
disturbed."""

from __future__ import annotations

import fcntl
import json
import os
import pathlib
import subprocess
import sys
import threading

import pytest
from conftest import LOCAL
from helpers import ruled_attempt_id, ruled_dedup_id, ruled_record_id, ruled_tenant_dir, sha, vector

from synapse_imagery.assets import LocalAssetStore
from synapse_imagery.fakes import InProcessWorker
from synapse_imagery.ingest import IngestService, is_job_id

TESTS = pathlib.Path(__file__).resolve().parent
PACKAGE = TESTS.parent
GEO_DMS = vector("geo_dms.ntf")
BLOCKED = vector("unknown_duplicate_tre.ntf")
COMMITTED_ID = ruled_record_id("local", "default", True, sha(GEO_DMS), 1, "committed")
STEP_STAGE = {
    "received": "input",
    "staged": "input",
    "inventoried": "input",
    "assessed": "security",
    "stored": "storage",
    "translated": "cdm",
    "persisted": "storage",
    "committed": "storage",
    "published": "storage",
}
BEFORE_LINK = ("received", "staged", "inventoried", "assessed", "stored", "translated", "persisted")
AFTER_LINK = ("committed", "published", "after_link:record", "index_updated")


def tenant(root) -> pathlib.Path:
    return pathlib.Path(root) / "tenants" / ruled_tenant_dir("local")


def listing(path: pathlib.Path) -> list[str]:
    return sorted(os.listdir(path)) if path.is_dir() else []


def originals(root) -> list[str]:
    base = tenant(root)
    found = []
    for parts in (("originals",), ("quarantine", "originals"), ("rejected", "originals")):
        found += [name for name in listing(base.joinpath(*parts)) if not name.startswith(".")]
    return found


def temporaries(root) -> list[str]:
    return [p.name for p in pathlib.Path(root).rglob("*.tmp")]


def assert_one_committed(root, record_id=COMMITTED_ID):
    base = tenant(root)
    assert listing(base / "records") == [f"{record_id}.json"]
    assert listing(base / "published") == [record_id]
    assert len(originals(root)) == 1
    products = listing(base / "products")
    assert len(products) == 1
    product = json.loads((base / "products" / products[0]).read_text())
    assert [entry["record_id"] for entry in product["revisions"]] == [record_id]
    slots = json.loads(
        (
            base / "dedup" / f"{ruled_dedup_id('local', 'default', True, sha(GEO_DMS), 1)}.json"
        ).read_text()
    )
    assert slots == {"committed": record_id, "policy_blocked": None, "rejected": None}


# --------------------------------------------------------------------------- in-process faults


@pytest.mark.parametrize("point", BEFORE_LINK + AFTER_LINK)
def test_an_exception_at_any_step_fails_the_ingest_and_publishes_nothing_uncommitted(
    tmp_path, point
):
    root = tmp_path / "store"

    def fault(reached):
        if reached == point:
            raise RuntimeError("injected")

    store = LocalAssetStore(root, _fault=fault)
    service = IngestService(store, worker=InProcessWorker(), _fault=fault)
    result = service.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    step = point if point in STEP_STAGE else "committed"
    assert result["state"] == "failed"
    assert [(d["code"], d["stage"], d["path"]) for d in result["diagnostics"]] == [
        ("E_INTERNAL", STEP_STAGE[step], "/" + step)
    ]
    digest = None if point == "received" else sha(GEO_DMS)
    assert result["record_id"] == ruled_attempt_id(
        "local",
        "default",
        True,
        digest,
        len(GEO_DMS),
        1,
        "failed",
        "E_INTERNAL",
        STEP_STAGE[step],
        "/" + step,
    )
    assert listing(root / "staging") == []
    base = tenant(root)
    if point in BEFORE_LINK:
        assert listing(base / "records") == [] and listing(base / "published") == []
        assert originals(root) == []
    else:
        assert listing(base / "records") == [f"{COMMITTED_ID}.json"]
        again = IngestService(LocalAssetStore(root), worker=InProcessWorker())
        repeat = again.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
        assert (repeat["state"], repeat["record_id"]) == ("committed", COMMITTED_ID)
        assert_one_committed(root)


# --------------------------------------------------------------------------- process deaths


def drive(root, name, point, mode="exit", **options):
    environment = dict(os.environ, PYTHONPATH=str(PACKAGE), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.Popen(
        [sys.executable, "-B", str(TESTS / "crash_driver.py"), str(root), name, point, mode],
        cwd=TESTS,
        env=environment,
        stdout=subprocess.PIPE,
        stdin=subprocess.PIPE,
        text=True,
        **options,
    )


def crash(root, name, point, mode="exit"):
    process = drive(root, name, point, mode)
    out, _ = process.communicate(timeout=120)
    assert process.returncode == 97, (point, process.returncode, out)


def assert_no_partial_object(root):
    """Every immutable original the crash left has its recorded digest and length."""
    base = tenant(root)
    for name in originals(root):
        record = json.loads((base / "assets" / f"{name}.json").read_text())
        for parts in (("originals",), ("quarantine", "originals")):
            path = base.joinpath(*parts, name)
            if path.is_file():
                data = path.read_bytes()
                assert (sha(data), len(data)) == (record["sha256"], record["bytes"])


ROLLED_BACK = BEFORE_LINK + ("before_link:original", "after_link:original", "before_link:record")
ROLLED_FORWARD = {"after_link:record": 1, "index_updated": 0, "committed": 0}


@pytest.mark.parametrize("point", ROLLED_BACK + tuple(ROLLED_FORWARD) + ("published",))
def test_recovery_after_a_process_death_at_each_point(tmp_path, point):
    root = tmp_path / "store"
    crash(root, "geo_dms.ntf", point)
    assert_no_partial_object(root)
    counts = LocalAssetStore(root).recover()
    if point in ROLLED_BACK:
        assert counts["jobs_rolled_back"] == 1 and counts["records_published"] == 0
        assert (counts["jobs_rolled_forward"], counts["jobs_completed"]) == (0, 0)
        assert temporaries(root) == [] and listing(root / "staging") == [] and originals(root) == []
    elif point in ROLLED_FORWARD:
        assert (counts["jobs_rolled_forward"], counts["records_published"]) == (1, 1)
        assert counts["records_repaired"] == ROLLED_FORWARD[point]
        assert counts["jobs_rolled_back"] == 0
        service = IngestService(LocalAssetStore(root), worker=InProcessWorker())
        assert service.catalog.list_records(principal=LOCAL) == [COMMITTED_ID]
    else:
        assert counts == {
            "jobs_rolled_back": 0,
            "jobs_rolled_forward": 0,
            "jobs_completed": 1,
            "records_repaired": 0,
            "records_published": 0,
            "originals_removed": 0,
            "temporaries_removed": 0,
        }
    assert listing(root / "staging") == []
    fresh = IngestService(LocalAssetStore(root), worker=InProcessWorker())
    result = fresh.ingest(GEO_DMS, principal=LOCAL, dataset_namespace="default", synthetic=True)
    assert (result["state"], result["record_id"]) == ("committed", COMMITTED_ID)
    assert_one_committed(root)
    assert LocalAssetStore(root).recover() == dict.fromkeys(counts, 0)


QUARANTINE_BACK = (
    "received",
    "staged",
    "inventoried",
    "assessed",
    "stored",
    "persisted",
    "before_link:original",
    "after_link:original",
    "before_link:record",
)


@pytest.mark.parametrize(
    "point", QUARANTINE_BACK + ("after_link:record", "index_updated", "committed")
)
def test_recovery_of_a_quarantined_ingest(tmp_path, point):
    root = tmp_path / "store"
    crash(root, "unknown_duplicate_tre.ntf", point)
    counts = LocalAssetStore(root).recover()
    assert counts["records_published"] == 0
    blocked_id = ruled_record_id("local", "default", True, sha(BLOCKED), 1, "policy_blocked")
    if point in QUARANTINE_BACK:
        assert counts["jobs_rolled_back"] == 1 and originals(root) == []
    else:
        assert counts["jobs_rolled_forward"] == 1
        assert counts["records_repaired"] == (1 if point == "after_link:record" else 0)
        slots = json.loads(
            (
                tenant(root)
                / "dedup"
                / f"{ruled_dedup_id('local', 'default', True, sha(BLOCKED), 1)}.json"
            ).read_text()
        )
        assert slots == {"committed": None, "policy_blocked": blocked_id, "rejected": None}
    result = IngestService(LocalAssetStore(root)).ingest(
        BLOCKED, principal=LOCAL, dataset_namespace="default", synthetic=True
    )
    assert (result["state"], result["record_id"]) == ("policy_blocked", blocked_id)
    assert listing(tenant(root) / "quarantine" / "records") == [f"{blocked_id}.json"]
    assert len(originals(root)) == 1 and listing(tenant(root) / "published") == []


def test_a_live_job_in_another_process_is_left_alone(tmp_path):
    root = tmp_path / "store"
    process = drive(root, "geo_dms.ntf", "stored", "pause")
    try:
        assert process.stdout.readline() == "paused\n"
        staging = listing(root / "staging")
        assert len(staging) == 1
        journal = (root / "staging" / staging[0] / "journal.json").read_bytes()
        counts = LocalAssetStore(root).recover()
        assert set(counts.values()) == {0}
        assert listing(root / "staging") == staging
        assert (root / "staging" / staging[0] / "journal.json").read_bytes() == journal
        assert len(originals(root)) == 1
        process.stdin.write("go\n")
        process.stdin.flush()
        out, _ = process.communicate(timeout=120)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert (process.returncode, out) == (0, "committed\n")
    assert_one_committed(root)


def test_an_original_no_journal_names_is_removed_as_an_orphan(tmp_path):
    root = tmp_path / "store"
    crash(root, "geo_dms.ntf", "after_link:original")
    (job,) = listing(root / "staging")
    # As if the process had died between the link and its journal write.
    (root / "staging" / job / "journal.json").unlink()
    assert len(originals(root)) == 1
    counts = LocalAssetStore(root).recover()
    assert (counts["jobs_rolled_back"], counts["originals_removed"]) == (1, 1)
    assert originals(root) == [] and temporaries(root) == []


def test_a_derivative_image_without_its_record_is_removed(tmp_path):
    root = tmp_path / "store"
    crash(root, "geo_dms.ntf", "after_link:derivative", "derivative")
    derivatives = tenant(root) / "derivatives"
    assert [name for name in listing(derivatives) if name.endswith(".png")] and not [
        name for name in listing(derivatives) if name.endswith(".json")
    ]
    counts = LocalAssetStore(root).recover()
    assert counts["originals_removed"] == 1 and counts["jobs_rolled_back"] == 1
    assert listing(derivatives) == []
    assert listing(tenant(root) / "originals") != []
    assert_one_committed(root)


def test_recovery_never_touches_anything_outside_the_store(tmp_path):
    root = tmp_path / "store"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.tmp").write_text("keep")
    (outside / ("." + "0" * 32 + ".tmp")).write_text("keep")
    crash(root, "geo_dms.ntf", "after_link:original")
    LocalAssetStore(root).recover()
    assert sorted(os.listdir(outside)) == sorted(["a.tmp", "." + "0" * 32 + ".tmp"])


# --------------------------------------------------------------------------- concurrent recovery

# A command's start-up recovery may run while another command on the same store is creating or
# ending a job. The instants in between are reached with events, never with a clock: the live
# job's own operation is paused right after one file-system call, a recovery from a second store
# object starts in another thread, and the operation goes on once that recovery has ended or is
# waiting for the store lock.


class RecoveryAt:
    """Start `recover()` of a second store object on `root` the first time this thread's
    `os.<function>(path)` returns for a path `matches` accepts."""

    def __init__(self, monkeypatch, root, function, matches):
        self.other = LocalAssetStore(root)
        self.owner = threading.current_thread()
        self.thread = threading.Thread(target=self._recover)
        self.resume = threading.Event()
        self.outcome = {}
        real = getattr(os, function)
        real_flock = fcntl.flock

        def paused(path, *args, **kwargs):
            done = real(path, *args, **kwargs)
            if (
                threading.current_thread() is self.owner
                and self.thread.ident is None
                and matches(os.fspath(path))
            ):
                self.thread.start()
                assert self.resume.wait(120)
            return done

        def flock(descriptor, operation):
            # A blocking exclusive request from the recovery is its wait for the store lock.
            if threading.current_thread() is self.thread and operation == fcntl.LOCK_EX:
                self.resume.set()
            return real_flock(descriptor, operation)

        monkeypatch.setattr(os, function, paused)
        monkeypatch.setattr(fcntl, "flock", flock)

    def _recover(self):
        try:
            self.outcome["counts"] = self.other.recover()
        except BaseException as error:
            self.outcome["error"] = error
        finally:
            self.resume.set()

    def counts(self) -> dict:
        assert self.thread.ident is not None, "the instant was never reached"
        self.thread.join(120)
        assert not self.thread.is_alive()
        assert "error" not in self.outcome, repr(self.outcome.get("error"))
        return self.outcome["counts"]


def in_staging(root, name=None):
    staging = os.fspath(pathlib.Path(root) / "staging")

    def matches(path: str) -> bool:
        if name is None:
            return os.path.dirname(path) == staging and is_job_id(os.path.basename(path))
        job = os.path.dirname(path)
        return (
            os.path.basename(path) == name
            and os.path.dirname(job) == staging
            and is_job_id(os.path.basename(job))
        )

    return matches


@pytest.mark.parametrize(
    "function, name",
    [("mkdir", None), ("open", "lock")],
    ids=["directory-made", "lock-file-made"],
)
def test_a_recovery_while_a_job_is_created_leaves_it_alone(tmp_path, monkeypatch, function, name):
    root = tmp_path / "store"
    store = LocalAssetStore(root)
    recovery = RecoveryAt(monkeypatch, root, function, in_staging(root, name))
    job = store.new_job(tenant="local")
    counts = recovery.counts()
    monkeypatch.undo()
    assert set(counts.values()) == {0}
    assert listing(root / "staging") == [job]
    assert listing(root / "staging" / job) == ["journal.json", "lock"]
    store.write_journal(job, "staged")
    assert store.delete_uncommitted(job) == 2
    assert listing(root / "staging") == []


@pytest.mark.parametrize("state", ["staged", "published"])
@pytest.mark.parametrize("name", ["lock", "journal.json"])
def test_a_recovery_while_a_job_ends_leaves_it_alone(tmp_path, monkeypatch, state, name):
    root = tmp_path / "store"
    store = LocalAssetStore(root)
    job = store.new_job(tenant="local")
    store.new_temp(job, ".source")
    store.write_journal(job, state)
    recovery = RecoveryAt(monkeypatch, root, "unlink", in_staging(root, name))
    assert store.delete_uncommitted(job) == 3
    counts = recovery.counts()
    monkeypatch.undo()
    assert set(counts.values()) == {0}
    assert listing(root / "staging") == []
    assert set(LocalAssetStore(root).recover().values()) == {0}


def remover(directory: pathlib.Path):
    """What another remover leaves: the directory's entries and the directory itself gone."""
    for entry in list(directory.iterdir()):
        entry.unlink()
    directory.rmdir()


@pytest.mark.parametrize("function", ["scandir", "unlink"])
def test_a_job_that_vanishes_under_recovery_is_taken_as_finished_elsewhere(
    tmp_path, monkeypatch, function
):
    root = tmp_path / "store"
    crash(root, "geo_dms.ntf", "staged")
    (job,) = listing(root / "staging")
    directory = root / "staging" / job
    real = getattr(os, function)
    taken = []

    def vanishing(path, *args, **kwargs):
        target = pathlib.Path(os.fspath(path)) if isinstance(path, (str, os.PathLike)) else None
        inside = target is not None and (
            target == directory if function == "scandir" else target.parent == directory
        )
        if inside and not taken:
            taken.append(target.name)
            remover(directory)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, function, vanishing)
    counts = LocalAssetStore(root).recover()
    monkeypatch.undo()
    assert taken
    # Before it scans, the job is someone else's to count; once its rollback began, it is this one's.
    rolled_back = 0 if function == "scandir" else 1
    assert counts == dict.fromkeys(counts, 0) | {"jobs_rolled_back": rolled_back}
    assert listing(root / "staging") == [] and temporaries(root) == []


def test_recoveries_beside_live_ingests_disturb_none_of_them(tmp_path):
    root = tmp_path / "store"
    LocalAssetStore(root)
    octets = vector("mode_B.ntf")
    stores = [LocalAssetStore(root) for _ in range(3)]
    lanes = [IngestService(store, worker=InProcessWorker()) for store in stores]
    results, seen, raised = [], [], []
    ingests_done = threading.Event()

    def ingest(lane, service):
        for turn in range(12):
            results.append(
                service.ingest(
                    octets,
                    principal=LOCAL,
                    dataset_namespace=f"lane-{lane}-{turn}",
                    synthetic=True,
                )
            )

    def recover(store):
        while True:
            try:
                seen.append(store.recover())
            except Exception as error:
                raised.append(type(error).__name__)
            if ingests_done.is_set():
                return

    # Two recoveries on store objects of their own (another command), one on a lane's own object.
    recoverers = [
        threading.Thread(target=recover, args=(store,))
        for store in (LocalAssetStore(root), LocalAssetStore(root), stores[0])
    ]
    ingesters = [
        threading.Thread(target=ingest, args=(lane, service)) for lane, service in enumerate(lanes)
    ]
    for thread in recoverers + ingesters:
        thread.start()
    for thread in ingesters:
        thread.join(600)
    ingests_done.set()
    for thread in recoverers:
        thread.join(600)
    assert not [thread for thread in recoverers + ingesters if thread.is_alive()]
    assert raised == []
    assert len(results) == 36 and {result["state"] for result in results} == {"committed"}
    # Publishing a record a live job has linked but not yet marked is recovery's own repair.
    disturbed = [
        counts
        for counts in seen
        if {v for k, v in counts.items() if k != "records_published"} != {0}
    ]
    assert seen and disturbed == []
    assert set(LocalAssetStore(root).recover().values()) == {0}
    assert listing(root / "staging") == []
    assert len(listing(tenant(root) / "records")) == len(listing(tenant(root) / "published")) == 36


# --------------------------------------------------------------------------- new_job's error branches


def _descriptors() -> set[int]:
    return {int(name) for name in os.listdir("/dev/fd") if name.isdigit()}


def _staging(root) -> list[str]:
    return listing(pathlib.Path(root) / "staging")


def test_a_failed_journal_write_removes_the_new_job(tmp_path, monkeypatch):
    store = LocalAssetStore(tmp_path / "store")
    before = _descriptors()

    def full(self, job_id, journal):
        raise OSError(28, "no space left on device")

    monkeypatch.setattr(LocalAssetStore, "_write_journal_file", full)
    with pytest.raises(OSError) as caught:
        store.new_job(tenant="local")
    assert caught.value.errno == 28
    # Nobody learns the job's id, so the store ends it itself: no directory, no registered job,
    # no descriptor left open.
    assert _staging(store.root) == []
    assert store._jobs == {}
    assert _descriptors() == before


def test_a_failed_lock_closes_its_descriptor_and_leaves_a_dead_job_recovery_removes(
    tmp_path, monkeypatch
):
    store = LocalAssetStore(tmp_path / "store")
    before = _descriptors()
    real = fcntl.flock

    def contended(descriptor, operation):
        if operation == fcntl.LOCK_EX | fcntl.LOCK_NB:
            raise BlockingIOError(35, "resource temporarily unavailable")
        return real(descriptor, operation)

    monkeypatch.setattr(fcntl, "flock", contended)
    with pytest.raises(BlockingIOError):
        store.new_job(tenant="local")
    monkeypatch.setattr(fcntl, "flock", real)
    assert store._jobs == {}
    assert _descriptors() == before
    # The directory and its lock file were made under the store lock; with no journal and no
    # holder it is a dead job, which the next recovery takes away.
    (left,) = _staging(store.root)
    assert is_job_id(left) and listing(pathlib.Path(store.root) / "staging" / left) == ["lock"]
    counts = LocalAssetStore(tmp_path / "store").recover()
    assert counts["jobs_rolled_back"] == 1
    assert _staging(store.root) == []


def test_a_failed_chmod_leaves_only_an_empty_directory_recovery_removes(tmp_path, monkeypatch):
    from synapse_imagery import assets

    store = LocalAssetStore(tmp_path / "store")
    before = _descriptors()
    staging = os.path.join(store.root, "staging")
    real = os.chmod

    def refused(path, mode, *arguments, **options):
        if os.path.dirname(path) == staging:
            raise PermissionError(1, "operation not permitted")
        return real(path, mode, *arguments, **options)

    monkeypatch.setattr(assets.os, "chmod", refused)
    with pytest.raises(PermissionError):
        store.new_job(tenant="local")
    monkeypatch.setattr(assets.os, "chmod", real)
    assert store._jobs == {}
    assert _descriptors() == before
    (left,) = _staging(store.root)
    assert listing(pathlib.Path(staging) / left) == []
    counts = LocalAssetStore(tmp_path / "store").recover()
    assert counts["jobs_rolled_back"] == 1
    assert _staging(store.root) == []


def test_ending_a_job_whose_directory_vanished_forgets_it_and_closes_its_lock(tmp_path):
    store = LocalAssetStore(tmp_path / "store")
    before = _descriptors()
    job = store.new_job(tenant="local")
    assert len(_descriptors() - before) == 1
    directory = pathlib.Path(store.root) / "staging" / job
    for name in os.listdir(directory):
        os.unlink(directory / name)
    os.rmdir(directory)
    assert store.delete_uncommitted(job) == 0
    assert store._jobs == {}
    assert _descriptors() == before
