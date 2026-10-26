"""The asset store: the interface the transaction runs on, and the local filesystem store.

THE INTERFACE
-------------
`AssetStore` is a closed list of methods that take identifiers, never paths: the four the
engineering kit names (`put_original`, `open_original`, `commit_derivative`, `delete_uncommitted`)
with their positional parameters in its order, and the transaction's own staging, journal,
record, index and publication operations, so that `IngestService` can run on any store that
implements them. Tenant scoping is the `tenant` keyword; an identifier of another tenant is
answered exactly as an unknown one. Reads of original octets, pixels and derivatives need a policy
ticket of the right artefact, checked on every read.

THE LOCAL STORE
---------------
`LocalAssetStore` keeps everything under one configured directory: 0o700 directories, 0o600
files, and every immutable object read-only (0o400) once linked. An object is written under a
generated temporary name in its destination directory, flushed to the device, and linked into
place, which fails rather than overwrites; the count and SHA-256 are verified before the link.
Every commit and index update holds an exclusive lock on the store, every live job a lock on its
staging directory. A staging directory appears with its held lock and goes with it, both under
the store lock, and recovery examines staging under that lock, so a recovery in another command
never disturbs a live job. No name is derived
from a title or any other source text, no symlink the store did not create is followed, and
nothing is deleted recursively: a staging directory is emptied file by file, by name pattern.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import BinaryIO, Protocol

from synapse_imagery.ingest import (
    asset_id_for,
    dedup_id_for,
    derivative_id_for,
    is_canonical_uuid,
    is_job_id,
    tenant_directory,
)
from synapse_imagery.policy import Artefact, PolicyTicket, SecurityDescriptor
from synapse_imagery.result import HostError, PolicyDenied

MARKER_NAME = "sc-imagery-store.json"
MARKER = b'{"format":"sc-imagery-store/1"}'
TEMP_SUFFIXES = (".source", ".png", ".ntf", ".json")
_STAGING_NAME = re.compile(r"\.?[0-9a-f]{32}\.(source|png|ntf|json|tmp)")
_TMP_NAME = re.compile(r"\.[0-9a-f]{32}\.tmp")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CHUNK = 1_048_576

#: Where an original lies decides what it is; no field of its record says so.
LOCATIONS = {
    "originals": ("originals",),
    "quarantine": ("quarantine", "originals"),
    "rejected": ("rejected", "originals"),
}
RECORD_AREAS = {
    "records": ("records",),
    "quarantine": ("quarantine", "records"),
    "rejected": ("rejected", "records"),
}
DEDUP_SLOTS = ("committed", "policy_blocked", "rejected")
_AREA_SLOT = {"records": "committed", "quarantine": "policy_blocked", "rejected": "rejected"}
_RECORD_KINDS = ("original", "record", "derivative", "export")


def _fsync(descriptor: int) -> None:
    """Flush to the device: F_FULLFSYNC where it exists (macOS, where fsync does not flush the
    drive's cache), else fsync."""
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        try:
            fcntl.fcntl(descriptor, full)
            return
        except OSError:
            pass
    os.fsync(descriptor)


def _fsync_dir(path: str) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        _fsync(descriptor)
    finally:
        os.close(descriptor)


def _no_asset() -> HostError:
    # One answer for every ticketed read that finds nothing: an unknown id, another tenant's id,
    # a revoked or foreign ticket; existence is never an oracle.
    return HostError("E_POLICY", "storage", None, "/asset", "no such asset for this ticket")


def _bad_temp() -> HostError:
    return HostError(
        "E_IO",
        "storage",
        None,
        "/temp_file",
        "the temporary file is not one this store issued for a live job",
    )


def _store_error(message: str) -> HostError:
    return HostError("E_IO", "storage", None, "/store", message)


def _tenant(tenant: object) -> str:
    if type(tenant) is not str or not tenant:
        raise TypeError("tenant must be a non-empty str")
    return tenant_directory(tenant)


def _compact(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


@dataclass(frozen=True, slots=True)
class TempFile:
    """A file inside one job's staging directory, named by the store; callers never pass paths."""

    job_id: str
    name: str


class OriginalReader:
    """A ticketed reader of an immutable object; the ticket is verified again on every read, so
    a revocation stops a reader mid-stream."""

    def __init__(self, descriptor: int, size: int, sha256: str, check) -> None:
        self._descriptor = descriptor
        self._check = check
        self.size = size
        self.sha256 = sha256

    def read(self, n: int = -1) -> bytes:
        self._check()
        if self._descriptor is None:
            raise ValueError("read of a closed reader")
        if n is None or n < 0:
            chunks = []
            while chunk := os.read(self._descriptor, _CHUNK):
                chunks.append(chunk)
            return b"".join(chunks)
        return os.read(self._descriptor, n)

    def close(self) -> None:
        if self._descriptor is not None:
            os.close(self._descriptor)
            self._descriptor = None

    def __enter__(self) -> OriginalReader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class AssetStore(Protocol):
    """The closed list of operations `IngestService` runs on."""

    def put_original(
        self,
        stream: BinaryIO,
        expected_sha256: str,
        byte_count: int,
        security: SecurityDescriptor | None,
        *,
        tenant: str,
        quarantine: bool = False,
        rejected: bool = False,
        job_id: str | None = None,
    ) -> str: ...

    def open_original(self, asset_id: str, policy_ticket: PolicyTicket) -> OriginalReader: ...

    def open_source_fd(self, asset_id: str, policy_ticket: PolicyTicket) -> int: ...

    def commit_derivative(
        self,
        parent_id: str,
        temp_file: TempFile,
        sha256: str,
        recipe: Mapping,
        security: SecurityDescriptor,
        *,
        tenant: str,
        policy_ticket: PolicyTicket,
        provenance: Mapping,
    ) -> str: ...

    def open_derivative(
        self, derivative_id: str, policy_ticket: PolicyTicket, *, tenant: str
    ) -> OriginalReader: ...

    def read_derivative(self, derivative_id: str, *, tenant: str) -> dict | None: ...

    def list_derivatives(self, parent_id: str, *, tenant: str) -> list[str]: ...

    def delete_uncommitted(self, job_id: str) -> int: ...

    def new_job(self, *, tenant: str) -> str: ...

    def new_temp(self, job_id: str, suffix: str) -> TempFile: ...

    def open_temp(self, temp: TempFile) -> int: ...

    def temp_digest(self, temp: TempFile) -> tuple[int, str]: ...

    def open_staged(self, job_id: str) -> int: ...

    def write_journal(self, job_id: str, state: str, **facts) -> None: ...

    def read_journal(self, job_id: str) -> dict | None: ...

    def commit_record(
        self,
        job_id: str,
        record_temp: TempFile,
        *,
        tenant: str,
        area: str,
        record_id: str,
        dedup_id: str,
        dedup_slot: str,
        entity_id: str | None,
    ) -> bool: ...

    def read_record(self, tenant: str, record_id: str, *, area: str) -> dict | None: ...

    def lookup_dedup(self, tenant: str, dedup_id: str) -> dict: ...

    def publish(self, tenant: str, record_id: str) -> None: ...

    def is_published(self, tenant: str, record_id: str) -> bool: ...

    def list_published(self, tenant: str) -> list[str]: ...

    def read_product(self, tenant: str, entity_id: str) -> dict | None: ...

    def select_revision(self, tenant: str, entity_id: str, revision: int) -> None: ...

    def commit_export(
        self, job_id: str, record_temp: TempFile, *, tenant: str, export_id: str
    ) -> None: ...

    def open_quarantined_fd(self, asset_id: str, *, tenant: str) -> int: ...

    def mark_integrity_failed(self, asset_id: str, *, tenant: str) -> None: ...

    def discard_job_asset(self, job_id: str) -> bool: ...

    def recover(self) -> dict: ...


# --------------------------------------------------------------------------- shared rules


def new_journal(job_id: str, tenant_dir: str) -> dict:
    return {
        "job_id": job_id,
        "tenant_dir": tenant_dir,
        "state": None,
        "sha256": None,
        "asset_id": None,
        "asset_created": False,
        "record_id": None,
        "area": None,
        "temps": [],
    }


_JOURNAL_FACTS = ("sha256", "asset_id", "asset_created", "record_id", "area")


def check_put(expected_sha256, byte_count, security, quarantine, rejected) -> None:
    if type(quarantine) is not bool or type(rejected) is not bool:
        raise TypeError("quarantine and rejected must be bool")
    if quarantine and rejected:
        raise ValueError("an original is quarantined or rejected, not both")
    if type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256):
        raise ValueError("expected_sha256 must be 64 lowercase hexadecimal digits")
    if type(byte_count) is not int or byte_count < 0:
        raise TypeError("byte_count must be an int >= 0")
    if security is None:
        if not rejected:
            raise TypeError("an admitted or quarantined original needs its security descriptor")
    elif not isinstance(security, SecurityDescriptor):
        raise TypeError("security must be a SecurityDescriptor")


def location_of(quarantine: bool, rejected: bool) -> str:
    return "quarantine" if quarantine else "rejected" if rejected else "originals"


def read_exactly(stream: BinaryIO, byte_count: int, sink) -> str:
    """Read exactly `byte_count` octets into `sink`, refusing a short stream and one octet more;
    returns the SHA-256 of what was read."""
    digest = hashlib.sha256()
    remaining = byte_count
    while remaining:
        chunk = stream.read(min(remaining, _CHUNK))
        if not chunk:
            raise HostError(
                "E_INTEGRITY", "storage", None, "/asset", "the stream is shorter than stated"
            )
        digest.update(chunk)
        sink(chunk)
        remaining -= len(chunk)
    if stream.read(1):
        raise HostError(
            "E_INTEGRITY", "storage", None, "/asset", "the stream is longer than stated"
        )
    return digest.hexdigest()


def add_revision(product: dict | None, record_id: str, record: dict) -> tuple[dict, bool]:
    """The product file after `record` is listed: appended, never overwritten. A digest the
    product already lists at another profile revision becomes an interpretation revision of the
    earliest revision of that digest."""
    if product is None:
        product = {"entity_id": record["entity_id"], "revisions": [], "selected_revision": 1}
    revisions = product["revisions"]
    if any(entry["record_id"] == record_id for entry in revisions):
        return product, False
    dedup = record["dedup"]
    same_digest = [entry for entry in revisions if entry["sha256"] == dedup["sha256"]]
    interpreted = any(
        entry["profile_revision"] != dedup["profile_revision"] for entry in same_digest
    )
    revisions.append(
        {
            "revision": len(revisions) + 1,
            "record_id": record_id,
            "sha256": dedup["sha256"],
            "profile_revision": dedup["profile_revision"],
            "synthetic": dedup["synthetic"],
            "interpretation_of": same_digest[0]["record_id"] if interpreted else None,
            "released_from": record["host"]["released_from"],
        }
    )
    return product, True


def record_dedup_id(record: dict) -> str:
    dedup = record["dedup"]
    return dedup_id_for(
        dedup["tenant"],
        dedup["dataset_namespace"],
        dedup["synthetic"],
        dedup["sha256"],
        dedup["profile_revision"],
    )


def check_ticket(
    ticket: object, accepted: tuple[Artefact, ...], asset_id: str, tenant: str
) -> None:
    """A ticket of an accepted kind for this asset and tenant, still outstanding."""
    if not isinstance(ticket, PolicyTicket):
        raise TypeError("policy_ticket must be a PolicyTicket")
    if ticket.artefact not in accepted:
        raise PolicyDenied(accepted[0], "this operation does not accept that ticket kind")
    try:
        ticket.verify(artefact=ticket.artefact, asset_id=asset_id, tenant=tenant)
    except HostError:
        raise _no_asset() from None


def recover_counts() -> dict:
    return {
        "jobs_rolled_back": 0,
        "jobs_rolled_forward": 0,
        "jobs_completed": 0,
        "records_repaired": 0,
        "records_published": 0,
        "originals_removed": 0,
        "temporaries_removed": 0,
    }


# --------------------------------------------------------------------------- the local store


class LocalAssetStore:
    """The runnable local filesystem store."""

    def __init__(self, root, *, _fault=None) -> None:
        if not isinstance(root, (str, os.PathLike)):
            raise TypeError("root must be a path")
        root = os.fspath(root)
        if not isinstance(root, str):
            raise TypeError("root must be a str path")
        self._root = os.path.abspath(root)
        self._fault = _fault
        self._mutex = threading.RLock()
        self._depth = 0
        self._lock_fd = None
        self._jobs_lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._initialise()

    @property
    def root(self) -> str:
        return self._root

    # ----------------------------------------------------------------- layout

    def _initialise(self) -> None:
        root = self._root
        try:
            status = os.lstat(root)
        except FileNotFoundError:
            parent = os.path.dirname(root)
            try:
                if not stat.S_ISDIR(os.lstat(parent).st_mode):
                    raise ValueError("the store's parent is not a directory")
            except FileNotFoundError:
                raise ValueError("the store's parent directory does not exist") from None
            os.mkdir(root, 0o700)
            fresh = True
        else:
            if not stat.S_ISDIR(status.st_mode):
                raise ValueError("the store root is not a directory (a symlink is refused)")
            entries = os.listdir(root)
            if not entries:
                fresh = True
            elif MARKER_NAME in entries and self._read_marker() == MARKER:
                fresh = False
            else:
                raise ValueError("the store root is a non-empty directory without the store marker")
        if fresh:
            os.chmod(root, 0o700)
            descriptor = os.open(
                self._path(MARKER_NAME), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            try:
                os.write(descriptor, MARKER)
                os.fchmod(descriptor, 0o400)
                _fsync(descriptor)
            finally:
                os.close(descriptor)
        lock = os.open(self._path("lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.close(lock)
        self._ensure_dir(self._path("staging"))
        self._ensure_dir(self._path("tenants"))
        _fsync_dir(root)

    def _read_marker(self) -> bytes | None:
        try:
            descriptor = os.open(self._path(MARKER_NAME), os.O_RDONLY | os.O_NOFOLLOW)
        except OSError:
            return None
        try:
            return os.read(descriptor, len(MARKER) + 1)
        finally:
            os.close(descriptor)

    def _path(self, *parts: str) -> str:
        return os.path.join(self._root, *parts)

    def _ensure_dir(self, path: str) -> str:
        try:
            status = os.lstat(path)
        except FileNotFoundError:
            os.mkdir(path, 0o700)
            os.chmod(path, 0o700)
            _fsync_dir(os.path.dirname(path))
            return path
        if not stat.S_ISDIR(status.st_mode):
            raise _store_error("the store layout holds an entry that is not a directory")
        return path

    def _tenant_path(self, tenant_dir: str, *parts: str, create: bool = False) -> str:
        if create:
            path = self._ensure_dir(self._path("tenants", tenant_dir))
            for part in parts:
                path = self._ensure_dir(os.path.join(path, part))
            return path
        return self._path("tenants", tenant_dir, *parts)

    @contextlib.contextmanager
    def _locked(self):
        """The store lock: one flock on `root/lock` per process, re-entrant within a thread
        (flock on two descriptors of one process excludes, so nesting must not take it twice)."""
        with self._mutex:
            if self._depth == 0:
                descriptor = os.open(self._path("lock"), os.O_RDWR | os.O_NOFOLLOW)
                fcntl.flock(descriptor, fcntl.LOCK_EX)
                self._lock_fd = descriptor
            self._depth += 1
            try:
                yield
            finally:
                self._depth -= 1
                if self._depth == 0:
                    fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                    os.close(self._lock_fd)
                    self._lock_fd = None

    def _point(self, name: str) -> None:
        if self._fault is not None:
            self._fault(name)

    # ----------------------------------------------------------------- file primitives

    def _write_temp(self, directory: str, data: bytes) -> str:
        path = os.path.join(directory, f".{secrets.token_hex(16)}.tmp")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            _write_all(descriptor, data)
            _fsync(descriptor)
        finally:
            os.close(descriptor)
        return path

    def _link_immutable(self, source: str, final: str, kind: str | None) -> bool:
        """Link `source` to `final`, read-only. An existing `final` is never overwritten: equal
        content is the idempotent case, other content is an integrity failure."""
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            os.fchmod(descriptor, 0o400)
        finally:
            os.close(descriptor)
        if kind:
            self._point(f"before_link:{kind}")
        try:
            os.link(source, final, follow_symlinks=False)
        except FileExistsError:
            same = _digest_file(source) == _digest_file(final)
            os.unlink(source)
            if not same:
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "an immutable object exists with other content",
                ) from None
            return False
        except OSError:
            raise _store_error("an immutable object could not be linked into place") from None
        if kind:
            self._point(f"after_link:{kind}")
        _fsync_dir(os.path.dirname(final))
        return True

    def _write_immutable(self, final: str, data: bytes, kind: str | None = None) -> bool:
        temp = self._write_temp(os.path.dirname(final), data)
        linked = self._link_immutable(temp, final, kind)
        if linked:
            os.unlink(temp)
            _fsync_dir(os.path.dirname(final))
        return linked

    def _write_index(self, final: str, value: object) -> None:
        temp = self._write_temp(os.path.dirname(final), _compact(value))
        os.replace(temp, final)
        _fsync_dir(os.path.dirname(final))

    def _read_json(self, path: str):
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        try:
            chunks = []
            while chunk := os.read(descriptor, _CHUNK):
                chunks.append(chunk)
        finally:
            os.close(descriptor)
        return json.loads(b"".join(chunks))

    def _exists(self, path: str) -> bool:
        try:
            return stat.S_ISREG(os.lstat(path).st_mode)
        except FileNotFoundError:
            return False

    # ----------------------------------------------------------------- jobs and temporaries

    def _job(self, job_id: object) -> dict:
        if not is_job_id(job_id):
            raise _store_error("no live job with this id")
        with self._jobs_lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise _store_error("no live job with this id")
        return job

    def new_job(self, *, tenant: str) -> str:
        tenant_dir = _tenant(tenant)
        job_id = secrets.token_hex(16)
        directory = self._path("staging", job_id)
        # The directory and its held lock appear under the store lock, so a recovery never meets
        # a new job's directory before its owner holds the lock.
        with self._locked():
            os.mkdir(directory, 0o700)
            os.chmod(directory, 0o700)
            lock = os.open(
                os.path.join(directory, "lock"),
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
            )
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(lock)
                raise
        journal = new_journal(job_id, tenant_dir)
        with self._jobs_lock:
            self._jobs[job_id] = {"tenant_dir": tenant_dir, "lock_fd": lock, "journal": journal}
        try:
            self._write_journal_file(job_id, journal)
            _fsync_dir(self._path("staging"))
        except BaseException:
            # No caller learns this job's id, so nobody else would ever end it.
            with contextlib.suppress(OSError, HostError):
                self.delete_uncommitted(job_id)
            raise
        return job_id

    def _write_journal_file(self, job_id: str, journal: dict) -> None:
        directory = self._path("staging", job_id)
        temp = self._write_temp(directory, _compact(journal))
        os.replace(temp, os.path.join(directory, "journal.json"))
        _fsync_dir(directory)

    def write_journal(self, job_id: str, state: str, **facts) -> None:
        job = self._job(job_id)
        if type(state) is not str or set(facts) - set(_JOURNAL_FACTS):
            raise ValueError("a journal entry is a state and the journal's own facts")
        job["journal"].update(facts, state=state)
        self._write_journal_file(job_id, job["journal"])

    def read_journal(self, job_id: str) -> dict | None:
        if not is_job_id(job_id):
            return None
        try:
            return self._read_json(self._path("staging", job_id, "journal.json"))
        except ValueError:
            return None

    def new_temp(self, job_id: str, suffix: str) -> TempFile:
        job = self._job(job_id)
        if suffix not in TEMP_SUFFIXES:
            raise ValueError("a temporary file's suffix is .source, .png, .ntf or .json")
        name = secrets.token_hex(16) + suffix
        path = self._path("staging", job_id, name)
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
        job["journal"]["temps"].append(name)
        self._write_journal_file(job_id, job["journal"])
        return TempFile(job_id, name)

    def _temp_path(self, temp: object) -> str:
        if not isinstance(temp, TempFile) or not is_job_id(temp.job_id):
            raise _bad_temp()
        with self._jobs_lock:
            job = self._jobs.get(temp.job_id)
        if job is None or temp.name not in job["journal"]["temps"]:
            raise _bad_temp()
        path = self._path("staging", temp.job_id, temp.name)
        if not self._exists(path):
            raise _bad_temp()
        return path

    def open_temp(self, temp: TempFile) -> int:
        return os.open(self._temp_path(temp), os.O_WRONLY | os.O_NOFOLLOW)

    def temp_digest(self, temp: TempFile) -> tuple[int, str]:
        return _digest_file(self._temp_path(temp))

    def open_staged(self, job_id: str) -> int:
        job = self._job(job_id)
        sources = [name for name in job["journal"]["temps"] if name.endswith(".source")]
        if len(sources) != 1:
            raise _store_error("the job has no staged source")
        return os.open(self._path("staging", job_id, sources[0]), os.O_RDONLY | os.O_NOFOLLOW)

    def delete_uncommitted(self, job_id: str) -> int:
        """Remove a job's staging directory: its own files by name, then the directory. Anything
        else inside it (a subdirectory, a symlink, an unknown name) refuses and stays."""
        if not is_job_id(job_id):
            raise _store_error("a job id is 32 lowercase hexadecimal digits")
        directory = self._path("staging", job_id)
        try:
            status = os.lstat(directory)
        except FileNotFoundError:
            self._forget_job(job_id)
            return 0
        if not stat.S_ISDIR(status.st_mode):
            raise _store_error("a staging entry is not a directory")
        removed = self._empty_job_directory(directory)
        self._forget_job(job_id)
        return removed

    def _forget_job(self, job_id: str) -> None:
        with self._jobs_lock:
            job = self._jobs.pop(job_id, None)
        if job is not None:
            os.close(job["lock_fd"])

    def _empty_job_directory(self, directory: str) -> int:
        """Unlink a job directory's own files and remove it; refuse (and leave everything) when it
        holds anything else. The lock file goes last, with the directory, under the store lock:
        until then a recovery finds the lock held. An entry already gone is not counted."""
        try:
            names = _job_entries(directory)
        except FileNotFoundError:
            return 0
        if names is None:
            raise _store_error("a staging directory holds an entry the store did not create")
        removed = sum(
            _unlink_if_present(os.path.join(directory, name)) for name in names if name != "lock"
        )
        with self._locked():
            if "lock" in names:
                removed += _unlink_if_present(os.path.join(directory, "lock"))
            with contextlib.suppress(FileNotFoundError):
                os.rmdir(directory)
        _fsync_dir(os.path.dirname(directory))
        return removed

    # ----------------------------------------------------------------- originals

    def put_original(
        self,
        stream,
        expected_sha256,
        byte_count,
        security,
        *,
        tenant,
        quarantine=False,
        rejected=False,
        job_id=None,
    ) -> str:
        check_put(expected_sha256, byte_count, security, quarantine, rejected)
        tenant_dir = _tenant(tenant)
        job = None if job_id is None else self._job(job_id)
        asset_id = asset_id_for(tenant, expected_sha256)
        location = location_of(quarantine, rejected)
        with self._locked():
            folder = self._tenant_path(tenant_dir, *LOCATIONS[location], create=True)
            final = os.path.join(folder, asset_id)
            assets = self._tenant_path(tenant_dir, "assets", create=True)
            record_path = os.path.join(assets, f"{asset_id}.json")
            known = self._read_json(record_path)
            if known is not None and (known["sha256"], known["bytes"]) != (
                expected_sha256,
                byte_count,
            ):
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "the recorded digest or length differs",
                )
            reuse = self._exists(final) or (
                location != "originals"
                and self._exists(self._tenant_path(tenant_dir, *LOCATIONS["originals"], asset_id))
            )
            if reuse:
                if known is None:
                    raise HostError(
                        "E_INTEGRITY", "storage", None, "/asset", "an original has no asset record"
                    )
                self._register(tenant_dir, asset_id, security)
                if job is not None:
                    self._journal_asset(job_id, job, asset_id, False)
                return asset_id
            temp = os.path.join(folder, f".{secrets.token_hex(16)}.tmp")
            descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    digest = read_exactly(
                        stream, byte_count, lambda chunk: _write_all(descriptor, chunk)
                    )
                    if digest != expected_sha256:
                        raise HostError(
                            "E_INTEGRITY",
                            "storage",
                            None,
                            "/asset",
                            "the stream differs from its stated digest",
                        )
                    _fsync(descriptor)
                finally:
                    os.close(descriptor)
            except BaseException:
                os.unlink(temp)
                raise
            if known is None:
                self._write_immutable(
                    record_path,
                    _compact(
                        {"asset_id": asset_id, "sha256": expected_sha256, "bytes": byte_count}
                    ),
                )
            self._register(tenant_dir, asset_id, security)
            if job is not None:
                # Named before the link, so a rollback of another job can see the reuse.
                self._journal_asset(job_id, job, asset_id, True)
            linked = self._link_immutable(temp, final, "original")
            if linked:
                os.unlink(temp)
                _fsync_dir(folder)
            return asset_id

    def _journal_asset(self, job_id: str, job: dict, asset_id: str, created: bool) -> None:
        journal = job["journal"]
        # Once this job has created the object it stays the creator until the object is
        # discarded; a later reuse by the same job does not hand the object to nobody.
        journal["asset_created"] = created or (
            journal["asset_created"] and journal["asset_id"] == asset_id
        )
        journal["asset_id"] = asset_id
        self._write_journal_file(job_id, journal)

    def _register(self, tenant_dir: str, asset_id: str, security) -> None:
        if security is None:
            return
        folder = self._tenant_path(tenant_dir, "descriptors", create=True)
        path = os.path.join(folder, f"{asset_id}.{security.sha256}.json")
        if not self._exists(path):
            self._write_immutable(path, _compact({"descriptor": security.json_text}))

    def _asset_record(self, tenant_dir: str, asset_id: str) -> dict | None:
        return self._read_json(self._tenant_path(tenant_dir, "assets", f"{asset_id}.json"))

    def _open_admitted(self, asset_id: str, ticket: PolicyTicket, accepted) -> tuple[int, dict]:
        if not is_canonical_uuid(asset_id):
            if not isinstance(ticket, PolicyTicket):
                raise TypeError("policy_ticket must be a PolicyTicket")
            raise _no_asset()
        check_ticket(ticket, accepted, asset_id, getattr(ticket, "tenant", ""))
        tenant_dir = tenant_directory(ticket.tenant)
        path = self._tenant_path(tenant_dir, "originals", asset_id)
        record = self._asset_record(tenant_dir, asset_id)
        if record is None or not self._exists(path):
            raise _no_asset()
        if self._exists(self._tenant_path(tenant_dir, "integrity-failed", asset_id)):
            raise HostError(
                "E_INTEGRITY", "storage", None, "/asset", "this original failed its integrity check"
            )
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW), record

    def open_original(self, asset_id: str, policy_ticket: PolicyTicket) -> OriginalReader:
        descriptor, record = self._open_admitted(asset_id, policy_ticket, (Artefact.ORIGINAL,))

        def check() -> None:
            check_ticket(policy_ticket, (Artefact.ORIGINAL,), asset_id, policy_ticket.tenant)

        return OriginalReader(descriptor, record["bytes"], record["sha256"], check)

    def open_source_fd(self, asset_id: str, policy_ticket: PolicyTicket) -> int:
        accepted = (Artefact.PIXELS, Artefact.THUMBNAIL)
        descriptor, _ = self._open_admitted(asset_id, policy_ticket, accepted)
        return descriptor

    def open_quarantined_fd(self, asset_id: str, *, tenant: str) -> int:
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(asset_id):
            raise _store_error("no quarantined original with this id")
        path = self._tenant_path(tenant_dir, "quarantine", "originals", asset_id)
        if not self._exists(path):
            raise _store_error("no quarantined original with this id")
        return os.open(path, os.O_RDONLY | os.O_NOFOLLOW)

    def mark_integrity_failed(self, asset_id: str, *, tenant: str) -> None:
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(asset_id):
            raise _store_error("no original with this id")
        with self._locked():
            folder = self._tenant_path(tenant_dir, "integrity-failed", create=True)
            path = os.path.join(folder, asset_id)
            try:
                descriptor = os.open(
                    path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
                )
            except FileExistsError:
                return
            try:
                os.fchmod(descriptor, 0o400)
                _fsync(descriptor)
            finally:
                os.close(descriptor)
            _fsync_dir(folder)

    def discard_job_asset(self, job_id: str) -> bool:
        """Remove the original this job created, unless a record of any area or another job's
        journal names its asset id."""
        with self._jobs_lock:
            job = self._jobs.get(job_id) if is_job_id(job_id) else None
        journal = job["journal"] if job is not None else self.read_journal(job_id)
        if not journal or not journal.get("asset_created") or not journal.get("asset_id"):
            return False
        asset_id, tenant_dir = journal["asset_id"], journal["tenant_dir"]
        with self._locked():
            if asset_id in self._named_assets(tenant_dir, exclude_job=job_id):
                return False
            removed = self._remove_asset(tenant_dir, asset_id)
        journal["asset_created"] = False
        if job is not None:
            self._write_journal_file(job_id, journal)
        return removed > 0

    def _named_assets(self, tenant_dir: str, exclude_job: str | None) -> set[str]:
        named = set()
        for area in RECORD_AREAS:
            for record_id in self._listing(tenant_dir, *RECORD_AREAS[area], suffix=".json"):
                record = self._read_json(
                    self._tenant_path(tenant_dir, *RECORD_AREAS[area], f"{record_id}.json")
                )
                if record is not None and record["result"]["asset_id"] is not None:
                    named.add(record["result"]["asset_id"])
        for name in self._staging_jobs():
            if name == exclude_job:
                continue
            journal = self.read_journal(name)
            if journal and journal.get("tenant_dir") == tenant_dir and journal.get("asset_id"):
                named.add(journal["asset_id"])
        return named

    def _staging_jobs(self) -> list[str]:
        try:
            return sorted(name for name in os.listdir(self._path("staging")) if is_job_id(name))
        except FileNotFoundError:
            return []

    def _listing(self, tenant_dir: str, *parts: str, suffix: str = "") -> list[str]:
        """The ids of one directory's entries (regular files named `<uuid><suffix>`)."""
        folder = self._tenant_path(tenant_dir, *parts)
        try:
            names = os.listdir(folder)
        except FileNotFoundError:
            return []
        found = []
        for name in names:
            if suffix and not name.endswith(suffix):
                continue
            stem = name[: len(name) - len(suffix)] if suffix else name
            if is_canonical_uuid(stem) and self._exists(os.path.join(folder, name)):
                found.append(stem)
        return sorted(found)

    def _remove_asset(self, tenant_dir: str, asset_id: str) -> int:
        removed = 0
        for location in LOCATIONS.values():
            path = self._tenant_path(tenant_dir, *location, asset_id)
            if self._exists(path):
                os.unlink(path)
                _fsync_dir(os.path.dirname(path))
                removed += 1
        for path in (
            self._tenant_path(tenant_dir, "assets", f"{asset_id}.json"),
            self._tenant_path(tenant_dir, "integrity-failed", asset_id),
        ):
            if self._exists(path):
                os.unlink(path)
        folder = self._tenant_path(tenant_dir, "descriptors")
        pattern = re.compile(re.escape(asset_id) + r"\.[0-9a-f]{64}\.json")
        try:
            names = os.listdir(folder)
        except FileNotFoundError:
            names = []
        for name in names:
            if pattern.fullmatch(name) and self._exists(os.path.join(folder, name)):
                os.unlink(os.path.join(folder, name))
        return removed

    # ----------------------------------------------------------------- records and indexes

    def commit_record(
        self,
        job_id,
        record_temp,
        *,
        tenant,
        area,
        record_id,
        dedup_id,
        dedup_slot,
        entity_id,
    ) -> bool:
        tenant_dir = _tenant(tenant)
        job = self._job(job_id)
        if area not in RECORD_AREAS or dedup_slot != _AREA_SLOT[area]:
            raise ValueError("area and dedup slot must be one of the three pairs")
        if not is_canonical_uuid(record_id) or (
            entity_id is not None and not is_canonical_uuid(entity_id)
        ):
            raise ValueError("record and entity ids are canonical UUID text")
        source = self._temp_path(record_temp)
        record = self._read_json(source)
        if (
            record_dedup_id(record) != dedup_id
            or record["entity_id"] != entity_id
            or record["result"]["record_id"] != record_id
        ):
            raise HostError(
                "E_INTERNAL", "storage", None, "/store", "the record differs from its commit"
            )
        with self._locked():
            folder = self._tenant_path(tenant_dir, *RECORD_AREAS[area], create=True)
            journal = job["journal"]
            journal.update(record_id=record_id, area=area)
            self._write_journal_file(job_id, journal)
            final = os.path.join(folder, f"{record_id}.json")
            if self._exists(final):
                # An identical ingest committed first: this one's record is discarded.
                linked = False
            else:
                linked = self._link_immutable(source, final, "record")
            stored = record if linked else self._read_json(final)
            self._repair(tenant_dir, area, record_id, stored)
            self._point("index_updated")
        return linked

    def _repair(self, tenant_dir: str, area: str, record_id: str, record: dict) -> bool:
        """Make the dedup slot and, for a committed record, the product file list this record; a
        pure function of the record, so recovery and a repeat complete a crashed commit alike."""
        changed = False
        dedup_folder = self._tenant_path(tenant_dir, "dedup", create=True)
        dedup_path = os.path.join(dedup_folder, f"{record_dedup_id(record)}.json")
        slots = self._read_json(dedup_path) or dict.fromkeys(DEDUP_SLOTS)
        slot = _AREA_SLOT[area]
        if slots[slot] is None:
            slots[slot] = record_id
            self._write_index(dedup_path, slots)
            changed = True
        if area == "records":
            products = self._tenant_path(tenant_dir, "products", create=True)
            path = os.path.join(products, f"{record['entity_id']}.json")
            product, added = add_revision(self._read_json(path), record_id, record)
            if added:
                self._write_index(path, product)
                changed = True
        return changed

    def read_record(self, tenant: str, record_id: str, *, area: str) -> dict | None:
        tenant_dir = _tenant(tenant)
        if area not in RECORD_AREAS:
            raise ValueError("area is records, quarantine or rejected")
        if not is_canonical_uuid(record_id):
            return None
        return self._read_json(
            self._tenant_path(tenant_dir, *RECORD_AREAS[area], f"{record_id}.json")
        )

    def lookup_dedup(self, tenant: str, dedup_id: str) -> dict:
        tenant_dir = _tenant(tenant)
        if type(dedup_id) is not str or not _SHA256.fullmatch(dedup_id):
            raise ValueError("a dedup id is 64 lowercase hexadecimal digits")
        slots = self._read_json(self._tenant_path(tenant_dir, "dedup", f"{dedup_id}.json"))
        return dict(slots) if slots else dict.fromkeys(DEDUP_SLOTS)

    def publish(self, tenant: str, record_id: str) -> None:
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(record_id) or not self._exists(
            self._tenant_path(tenant_dir, "records", f"{record_id}.json")
        ):
            raise HostError(
                "E_INTERNAL", "storage", None, "/store", "only a committed record is published"
            )
        with self._locked():
            folder = self._tenant_path(tenant_dir, "published", create=True)
            self._mark_published(folder, record_id)

    def _mark_published(self, folder: str, record_id: str) -> bool:
        path = os.path.join(folder, record_id)
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            return False
        try:
            _fsync(descriptor)
        finally:
            os.close(descriptor)
        _fsync_dir(folder)
        return True

    def is_published(self, tenant: str, record_id: str) -> bool:
        tenant_dir = _tenant(tenant)
        return is_canonical_uuid(record_id) and self._exists(
            self._tenant_path(tenant_dir, "published", record_id)
        )

    def list_published(self, tenant: str) -> list[str]:
        tenant_dir = _tenant(tenant)
        return [
            record_id
            for record_id in self._listing(tenant_dir, "published")
            if self._exists(self._tenant_path(tenant_dir, "records", f"{record_id}.json"))
        ]

    def read_product(self, tenant: str, entity_id: str) -> dict | None:
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(entity_id):
            return None
        return self._read_json(self._tenant_path(tenant_dir, "products", f"{entity_id}.json"))

    def select_revision(self, tenant: str, entity_id: str, revision: int) -> None:
        tenant_dir = _tenant(tenant)
        with self._locked():
            product = self.read_product(tenant, entity_id)
            if (
                product is None
                or type(revision) is not int
                or not any(entry["revision"] == revision for entry in product["revisions"])
            ):
                raise HostError("E_FIELD", "storage", None, "/revision", "no such revision")
            product["selected_revision"] = revision
            self._write_index(
                self._tenant_path(tenant_dir, "products", f"{entity_id}.json"), product
            )

    # ----------------------------------------------------------------- derivatives and exports

    def commit_derivative(
        self,
        parent_id,
        temp_file,
        sha256,
        recipe,
        security,
        *,
        tenant,
        policy_ticket,
        provenance,
    ) -> str:
        tenant_dir = _tenant(tenant)
        source = self._temp_path(temp_file)
        if not is_canonical_uuid(parent_id):
            raise _no_asset()
        check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent_id, tenant)
        if not isinstance(security, SecurityDescriptor):
            raise TypeError("security must be a SecurityDescriptor")
        registered = self._tenant_path(
            tenant_dir, "descriptors", f"{parent_id}.{security.sha256}.json"
        )
        if not self._exists(registered):
            raise HostError(
                "E_POLICY",
                "storage",
                None,
                "/derivative/security",
                "a derivative inherits a descriptor registered for its parent, never its own",
            )
        parent = self._asset_record(tenant_dir, parent_id)
        if parent is None:
            raise _no_asset()
        count, digest = _digest_file(source)
        if digest != sha256:
            raise HostError(
                "E_INTEGRITY",
                "storage",
                None,
                "/asset",
                "the derivative differs from its stated digest",
            )
        recipe_sha = hashlib.sha256(_canonical(recipe)).hexdigest()
        derivative_id = derivative_id_for(
            tenant, parent_id, parent["sha256"], recipe_sha, security.sha256
        )
        with self._locked():
            folder = self._tenant_path(tenant_dir, "derivatives", create=True)
            record_path = os.path.join(folder, f"{derivative_id}.json")
            existing = self._read_json(record_path)
            if existing is not None:
                if existing["sha256"] != digest:
                    raise HostError(
                        "E_INTEGRITY",
                        "storage",
                        None,
                        "/asset",
                        "the derivative exists with other content",
                    )
                return derivative_id
            self._link_immutable(source, os.path.join(folder, f"{derivative_id}.png"), "derivative")
            # The record is what makes the derivative exist; recovery removes an image without one.
            self._write_immutable(
                record_path,
                _compact(
                    {
                        "derivative_id": derivative_id,
                        "parent_id": parent_id,
                        "parent_sha256": parent["sha256"],
                        "recipe": recipe,
                        "recipe_sha256": recipe_sha,
                        "descriptor": security.json_text,
                        "sha256": digest,
                        "bytes": count,
                        "provenance": provenance,
                    }
                ),
            )
        return derivative_id

    def read_derivative(self, derivative_id: str, *, tenant: str) -> dict | None:
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(derivative_id):
            return None
        return self._read_json(
            self._tenant_path(tenant_dir, "derivatives", f"{derivative_id}.json")
        )

    def list_derivatives(self, parent_id: str, *, tenant: str) -> list[str]:
        """The sorted ids of the committed derivatives of one parent asset, in this tenant only
        (ids, no pixel data: the octets still need a THUMBNAIL ticket)."""
        tenant_dir = _tenant(tenant)
        if not is_canonical_uuid(parent_id):
            return []
        found = []
        for derivative_id in self._listing(tenant_dir, "derivatives", suffix=".json"):
            record = self.read_derivative(derivative_id, tenant=tenant)
            if record is not None and record["parent_id"] == parent_id:
                found.append(derivative_id)
        return found

    def open_derivative(
        self, derivative_id: str, policy_ticket: PolicyTicket, *, tenant: str
    ) -> OriginalReader:
        record = self.read_derivative(derivative_id, tenant=tenant)
        if record is None:
            if not isinstance(policy_ticket, PolicyTicket):
                raise TypeError("policy_ticket must be a PolicyTicket")
            raise _no_asset()
        parent = record["parent_id"]
        check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent, tenant)
        path = self._tenant_path(_tenant(tenant), "derivatives", f"{derivative_id}.png")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)

        def check() -> None:
            check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent, tenant)

        return OriginalReader(descriptor, record["bytes"], record["sha256"], check)

    def commit_export(
        self, job_id: str, record_temp: TempFile, *, tenant: str, export_id: str
    ) -> None:
        tenant_dir = _tenant(tenant)
        self._job(job_id)
        if not is_canonical_uuid(export_id):
            raise ValueError("an export id is canonical UUID text")
        source = self._temp_path(record_temp)
        with self._locked():
            folder = self._tenant_path(tenant_dir, "exports", create=True)
            self._link_immutable(source, os.path.join(folder, f"{export_id}.json"), "export")

    # ----------------------------------------------------------------- recovery

    def recover(self) -> dict:
        """Four ordered passes: jobs, record repair and publication, orphan originals and
        derivative images, then stray temporaries. A job whose lock is held is live and left
        alone; nothing outside the store and no record or named original is ever touched."""
        counts = recover_counts()
        for job_id in self._staging_jobs():
            self._recover_job(job_id, counts)
        with self._locked():
            for tenant_dir in self._tenant_dirs():
                self._repair_tenant(tenant_dir, counts)
            for tenant_dir in self._tenant_dirs():
                self._remove_orphans(tenant_dir, counts)
            tenants = self._path("tenants")
            for directory, folders, files in os.walk(tenants, followlinks=False):
                for name in files:
                    path = os.path.join(directory, name)
                    if _TMP_NAME.fullmatch(name) and self._exists(path):
                        os.unlink(path)
                        counts["temporaries_removed"] += 1
        return counts

    def _tenant_dirs(self) -> list[str]:
        try:
            names = os.listdir(self._path("tenants"))
        except FileNotFoundError:
            return []
        return sorted(
            name
            for name in names
            if is_canonical_uuid(name)
            and stat.S_ISDIR(os.lstat(self._path("tenants", name)).st_mode)
        )

    def _recover_job(self, job_id: str, counts: dict) -> None:
        # Under the store lock a job directory exists only together with its owner's held lock,
        # from `new_job` to the end of `delete_uncommitted`: a lock this pass can take, or none at
        # all, means the owner is gone. A directory that vanishes was ended by someone else.
        with self._locked():
            with self._jobs_lock:
                if job_id in self._jobs:
                    return
            directory = self._path("staging", job_id)
            try:
                if not stat.S_ISDIR(os.lstat(directory).st_mode) or _job_entries(directory) is None:
                    return
            except FileNotFoundError:
                return
            try:
                lock = os.open(os.path.join(directory, "lock"), os.O_RDWR | os.O_NOFOLLOW)
            except FileNotFoundError:
                lock = None
            try:
                if lock is not None:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        return
                self._end_dead_job(job_id, directory, counts)
            finally:
                if lock is not None:
                    os.close(lock)

    def _end_dead_job(self, job_id: str, directory: str, counts: dict) -> None:
        journal = self.read_journal(job_id)
        if not isinstance(journal, dict):
            self._empty_job_directory(directory)
            counts["jobs_rolled_back"] += 1
            return
        state = journal.get("state")
        record_id, area = journal.get("record_id"), journal.get("area")
        linked = (
            is_canonical_uuid(record_id)
            and area in RECORD_AREAS
            and self._exists(
                self._tenant_path(journal["tenant_dir"], *RECORD_AREAS[area], f"{record_id}.json")
            )
        )
        if state == "published":
            counts["jobs_completed"] += 1
        elif state == "committed" or linked:
            counts["jobs_rolled_forward"] += 1
        else:
            self.discard_job_asset(job_id)
            counts["jobs_rolled_back"] += 1
        self._empty_job_directory(directory)

    def _repair_tenant(self, tenant_dir: str, counts: dict) -> None:
        for area in RECORD_AREAS:
            for record_id in self._listing(tenant_dir, *RECORD_AREAS[area], suffix=".json"):
                record = self._read_json(
                    self._tenant_path(tenant_dir, *RECORD_AREAS[area], f"{record_id}.json")
                )
                if self._repair(tenant_dir, area, record_id, record):
                    counts["records_repaired"] += 1
                if area == "records":
                    folder = self._tenant_path(tenant_dir, "published", create=True)
                    if self._mark_published(folder, record_id):
                        counts["records_published"] += 1

    def _remove_orphans(self, tenant_dir: str, counts: dict) -> None:
        named = self._named_assets(tenant_dir, exclude_job=None)
        for location in LOCATIONS.values():
            for asset_id in self._listing(tenant_dir, *location):
                if asset_id not in named:
                    counts["originals_removed"] += self._remove_asset(tenant_dir, asset_id)
        derivatives = self._tenant_path(tenant_dir, "derivatives")
        for derivative_id in self._listing(tenant_dir, "derivatives", suffix=".png"):
            if not self._exists(os.path.join(derivatives, f"{derivative_id}.json")):
                os.unlink(os.path.join(derivatives, f"{derivative_id}.png"))
                counts["originals_removed"] += 1


# --------------------------------------------------------------------------- helpers


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _digest_file(path: str) -> tuple[int, str]:
    digest = hashlib.sha256()
    count = 0
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        while chunk := os.read(descriptor, _CHUNK):
            digest.update(chunk)
            count += len(chunk)
    finally:
        os.close(descriptor)
    return count, digest.hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _job_entries(directory: str) -> list[str] | None:
    """The names inside a job directory, or None when it holds an entry the store did not create
    (FileNotFoundError when the directory is gone)."""
    names = []
    with os.scandir(directory) as entries:
        for entry in entries:
            if not entry.is_file(follow_symlinks=False):
                return None
            if entry.name not in ("lock", "journal.json") and not _STAGING_NAME.fullmatch(
                entry.name
            ):
                return None
            names.append(entry.name)
    return names


def _unlink_if_present(path: str) -> int:
    try:
        os.unlink(path)
    except FileNotFoundError:
        return 0
    return 1
