"""The unit-test fakes of the policy, store, worker and lattice interfaces.

Each is a test fake and is fenced to synthetic material: `FakePolicy` refuses every request for
live material, `IngestService` refuses a live ingest with any of these, and the command line never
constructs one. They exist so that a deployment can test against the interfaces without a store
on disk, a child process or a policy engine of its own.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import secrets
import tempfile
import threading
from collections.abc import Mapping, Sequence

from synapse_cdm.adapters.nsif_codec import Limits

from synapse_imagery import assets as _assets
from synapse_imagery.assets import (
    DEDUP_SLOTS,
    LOCATIONS,
    RECORD_AREAS,
    TEMP_SUFFIXES,
    OriginalReader,
    TempFile,
    add_revision,
    check_put,
    check_ticket,
    location_of,
    new_journal,
    read_exactly,
    record_dedup_id,
    recover_counts,
)
from synapse_imagery.ingest import asset_id_for, derivative_id_for, is_canonical_uuid, is_job_id
from synapse_imagery.policy import (
    Artefact,
    LabelCombinationRefused,
    PolicyDecision,
    PolicyRequest,
    SecurityDescriptor,
    combined,
    screen,
)
from synapse_imagery.result import HostError
from synapse_imagery.worker import _serve, _WorkerBase


class FakePolicy:
    """Test fake: scripted decisions per artefact, for synthetic material only. It assesses
    nothing, so its completeness is always `complete` (the one value under which a scripted allow
    can be returned); live material is refused whatever the table says."""

    def __init__(
        self,
        table: Mapping[Artefact, bool],
        *,
        policy_id: str = "fake-scripted",
        policy_version: str = "1",
    ) -> None:
        if not isinstance(table, Mapping) or not all(
            isinstance(key, Artefact) and type(value) is bool for key, value in table.items()
        ):
            raise TypeError("table maps Artefact to bool")
        self._table = dict(table)
        self.policy_id = policy_id
        self.policy_version = policy_version

    def decide(self, request: PolicyRequest) -> PolicyDecision:
        if request.synthetic is not True:
            return PolicyDecision(
                False, "FAKE_LIVE_REFUSED", self.policy_id, self.policy_version, "complete"
            )
        allowed = self._table.get(request.artefact, False)
        reason = "FAKE_SCRIPTED_ALLOW" if allowed else "FAKE_SCRIPTED_DENY"
        return PolicyDecision(allowed, reason, self.policy_id, self.policy_version, "complete")


_IN_PROCESS_REPORT = {
    "isolation": "none",
    "memory_limit_bytes": None,
    "memory_enforcement": "not_enforced",
    "cpu_affinity": "not_enforced",
    "deadline_enforcement": "none",
    "platform": None,
}


class InProcessWorker(_WorkerBase):
    """Test fake: the Worker protocol by direct calls into the adapter in the calling process,
    through the same request, the same job function and the same answer checks as the isolated
    pool, with no isolation, no deadline and no memory cap."""

    isolation = "none"

    def __init__(self, limits: Limits | None = None) -> None:
        super().__init__()
        if limits is not None and not isinstance(limits, Limits):
            raise TypeError("limits must be a Limits")
        self._limits = limits

    def _run(self, op: str, request: dict, pass_fds: tuple[int, ...]) -> tuple[dict, bytes]:
        import sys

        report = dict(_IN_PROCESS_REPORT, platform=sys.platform)
        answer, payload = _serve(request, report, self._limits)
        # The same JSON types the pool's answer has after its line is parsed.
        return json.loads(json.dumps(answer)), payload


class FakeSchemeLattice:
    """Test fake: a toy lattice over one classification system with levels ordered as given;
    handling words (CODE, CTLH) are united, recipients (REL) intersected, and anything outside
    that is refused. It is for testing the lattice contract, never for deciding release."""

    def __init__(self, clsy: str, levels: tuple[str, ...]) -> None:
        if type(clsy) is not str or type(levels) is not tuple or not levels:
            raise TypeError("clsy is a str and levels a non-empty tuple")
        self.clsy = clsy
        self.levels = levels
        self.lattice_id = "sc-imagery-fake-scheme/1"

    def combine(self, labels: Sequence[Mapping[str, object]]) -> dict:
        labels = screen(labels)
        fields = [label["fields"] for label in labels]
        if any(entry["CLSY"] != self.clsy for entry in fields):
            raise LabelCombinationRefused("DIFFERENT_SYSTEM")
        if any(entry["CLAS"] not in self.levels for entry in fields):
            raise LabelCombinationRefused("UNRECOGNISED_LEVEL")
        if any(not entry["REL"].strip() for entry in fields):
            # An empty releasability is not "every recipient".
            raise LabelCombinationRefused("EMPTY_RELEASABILITY")
        recipients = set(fields[0]["REL"].split())
        for entry in fields[1:]:
            recipients &= set(entry["REL"].split())
        if not recipients:
            raise LabelCombinationRefused("NO_COMMON_RECIPIENT")
        fixed = ("CLAS", "CODE", "CTLH", "REL")
        rest = [{k: v for k, v in entry.items() if k not in fixed} for entry in fields]
        if any(entry != rest[0] for entry in rest):
            raise LabelCombinationRefused("DIFFERENT_CAVEATS")
        code = " ".join(sorted(set().union(*(entry["CODE"].split() for entry in fields))))
        ctlh = " ".join(sorted(set().union(*(entry["CTLH"].split() for entry in fields))))
        rel = " ".join(sorted(recipients))
        if len(code) > 11 or len(ctlh) > 2 or len(rel) > 20:
            raise LabelCombinationRefused("FIELD_OVERFLOW")
        level = max((entry["CLAS"] for entry in fields), key=self.levels.index)
        result = dict(fields[0])
        result.update(CLAS=level, CODE=code, CTLH=ctlh, REL=rel)
        return combined(result)


# --------------------------------------------------------------------------- the memory store


class MemoryAssetStore:
    """Test fake: the AssetStore protocol in memory, with the local store's digest, count,
    tenant-scoping, derivative-inheritance and ticket checks and no durability. Temporary files
    and the descriptors handed to a worker are files in a private scratch directory, because a
    worker reads through a descriptor; `close()` removes them."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._scratch = tempfile.mkdtemp(prefix="sc-imagery-memory-")
        self._jobs: dict[str, dict] = {}
        self._tenants: dict[str, dict] = {}

    # ----------------------------------------------------------------- housekeeping

    def close(self) -> None:
        with self._lock:
            for job_id in list(self._jobs):
                self.delete_uncommitted(job_id)
            if self._scratch is not None:
                os.rmdir(self._scratch)
                self._scratch = None

    def __enter__(self) -> MemoryAssetStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _state(self, tenant: str) -> dict:
        tenant_dir = _assets._tenant(tenant)
        return self._state_of(tenant_dir)

    def _state_of(self, tenant_dir: str) -> dict:
        state = self._tenants.get(tenant_dir)
        if state is None:
            state = {
                "objects": {location: {} for location in LOCATIONS},
                "assets": {},
                "descriptors": {},
                "integrity_failed": set(),
                "records": {area: {} for area in RECORD_AREAS},
                "published": set(),
                "dedup": {},
                "products": {},
                "derivatives": {},
                "exports": {},
            }
            self._tenants[tenant_dir] = state
        return state

    def _descriptor_of(self, data: bytes) -> int:
        """A read-only descriptor of `data`, through a scratch file unlinked at once."""
        path = os.path.join(self._scratch, f".{secrets.token_hex(16)}.tmp")
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            _assets._write_all(descriptor, data)
        finally:
            os.close(descriptor)
        try:
            return os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        finally:
            os.unlink(path)

    # ----------------------------------------------------------------- jobs and temporaries

    def _job(self, job_id: object) -> dict:
        job = self._jobs.get(job_id) if is_job_id(job_id) else None
        if job is None:
            raise _assets._store_error("no live job with this id")
        return job

    def new_job(self, *, tenant: str) -> str:
        tenant_dir = _assets._tenant(tenant)
        with self._lock:
            job_id = secrets.token_hex(16)
            directory = os.path.join(self._scratch, job_id)
            os.mkdir(directory, 0o700)
            self._jobs[job_id] = {
                "tenant_dir": tenant_dir,
                "dir": directory,
                "journal": new_journal(job_id, tenant_dir),
            }
            return job_id

    def write_journal(self, job_id: str, state: str, **facts) -> None:
        with self._lock:
            job = self._job(job_id)
            if type(state) is not str or set(facts) - set(_assets._JOURNAL_FACTS):
                raise ValueError("a journal entry is a state and the journal's own facts")
            job["journal"].update(facts, state=state)

    def read_journal(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id) if is_job_id(job_id) else None
            return None if job is None else copy.deepcopy(job["journal"])

    def new_temp(self, job_id: str, suffix: str) -> TempFile:
        with self._lock:
            job = self._job(job_id)
            if suffix not in TEMP_SUFFIXES:
                raise ValueError("a temporary file's suffix is .source, .png, .ntf or .json")
            name = secrets.token_hex(16) + suffix
            path = os.path.join(job["dir"], name)
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600))
            job["journal"]["temps"].append(name)
            return TempFile(job_id, name)

    def _temp_path(self, temp: object) -> str:
        with self._lock:
            if not isinstance(temp, TempFile):
                raise _assets._bad_temp()
            job = self._jobs.get(temp.job_id) if is_job_id(temp.job_id) else None
            if job is None or temp.name not in job["journal"]["temps"]:
                raise _assets._bad_temp()
            return os.path.join(job["dir"], temp.name)

    def open_temp(self, temp: TempFile) -> int:
        return os.open(self._temp_path(temp), os.O_WRONLY | os.O_NOFOLLOW)

    def temp_digest(self, temp: TempFile) -> tuple[int, str]:
        return _assets._digest_file(self._temp_path(temp))

    def _temp_bytes(self, temp: TempFile) -> bytes:
        descriptor = os.open(self._temp_path(temp), os.O_RDONLY | os.O_NOFOLLOW)
        try:
            chunks = []
            while chunk := os.read(descriptor, 1_048_576):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    def open_staged(self, job_id: str) -> int:
        with self._lock:
            job = self._job(job_id)
            sources = [name for name in job["journal"]["temps"] if name.endswith(".source")]
            if len(sources) != 1:
                raise _assets._store_error("the job has no staged source")
            return os.open(os.path.join(job["dir"], sources[0]), os.O_RDONLY | os.O_NOFOLLOW)

    def delete_uncommitted(self, job_id: str) -> int:
        if not is_job_id(job_id):
            raise _assets._store_error("a job id is 32 lowercase hexadecimal digits")
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if job is None:
                return 0
            removed = 0
            for name in job["journal"]["temps"]:
                path = os.path.join(job["dir"], name)
                if os.path.lexists(path):
                    os.unlink(path)
                    removed += 1
            os.rmdir(job["dir"])
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
        with self._lock:
            state = self._state(tenant)
            job = None if job_id is None else self._job(job_id)
            asset_id = asset_id_for(tenant, expected_sha256)
            location = location_of(quarantine, rejected)
            known = state["assets"].get(asset_id)
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
            objects = state["objects"]
            reuse = asset_id in objects[location] or (
                location != "originals" and asset_id in objects["originals"]
            )
            if not reuse:
                parts: list[bytes] = []
                digest = read_exactly(stream, byte_count, parts.append)
                if digest != expected_sha256:
                    raise HostError(
                        "E_INTEGRITY",
                        "storage",
                        None,
                        "/asset",
                        "the stream differs from its stated digest",
                    )
                objects[location][asset_id] = b"".join(parts)
                state["assets"][asset_id] = {
                    "asset_id": asset_id,
                    "sha256": expected_sha256,
                    "bytes": byte_count,
                }
            if security is not None:
                state["descriptors"].setdefault(asset_id, set()).add(security.sha256)
            if job is not None:
                journal = job["journal"]
                journal["asset_created"] = (not reuse) or (
                    journal["asset_created"] and journal["asset_id"] == asset_id
                )
                journal["asset_id"] = asset_id
            return asset_id

    def _admitted(self, asset_id: str, ticket, accepted) -> tuple[bytes, dict]:
        if not is_canonical_uuid(asset_id):
            check_ticket(ticket, accepted, "", getattr(ticket, "tenant", ""))
        check_ticket(ticket, accepted, asset_id, getattr(ticket, "tenant", ""))
        with self._lock:
            state = self._state(ticket.tenant)
            data = state["objects"]["originals"].get(asset_id)
            record = state["assets"].get(asset_id)
            if data is None or record is None:
                raise _assets._no_asset()
            if asset_id in state["integrity_failed"]:
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "this original failed its integrity check",
                )
            return data, record

    def open_original(self, asset_id: str, policy_ticket) -> OriginalReader:
        data, record = self._admitted(asset_id, policy_ticket, (Artefact.ORIGINAL,))

        def check() -> None:
            check_ticket(policy_ticket, (Artefact.ORIGINAL,), asset_id, policy_ticket.tenant)

        return OriginalReader(self._descriptor_of(data), record["bytes"], record["sha256"], check)

    def open_source_fd(self, asset_id: str, policy_ticket) -> int:
        data, _ = self._admitted(asset_id, policy_ticket, (Artefact.PIXELS, Artefact.THUMBNAIL))
        return self._descriptor_of(data)

    def open_quarantined_fd(self, asset_id: str, *, tenant: str) -> int:
        with self._lock:
            data = self._state(tenant)["objects"]["quarantine"].get(asset_id)
            if data is None:
                raise _assets._store_error("no quarantined original with this id")
            return self._descriptor_of(data)

    def mark_integrity_failed(self, asset_id: str, *, tenant: str) -> None:
        with self._lock:
            self._state(tenant)["integrity_failed"].add(asset_id)

    def discard_job_asset(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id) if is_job_id(job_id) else None
            if job is None:
                return False
            journal = job["journal"]
            asset_id = journal["asset_id"]
            if not journal["asset_created"] or asset_id is None:
                return False
            state = self._state_of(job["tenant_dir"])
            named = {
                record["result"]["asset_id"]
                for records in state["records"].values()
                for record in records.values()
            }
            named |= {
                other["journal"]["asset_id"]
                for other_id, other in self._jobs.items()
                if other_id != job_id and other["tenant_dir"] == job["tenant_dir"]
            }
            if asset_id in named:
                return False
            removed = sum(1 for objects in state["objects"].values() if objects.pop(asset_id, None))
            state["assets"].pop(asset_id, None)
            state["descriptors"].pop(asset_id, None)
            state["integrity_failed"].discard(asset_id)
            journal["asset_created"] = False
            return removed > 0

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
        if area not in RECORD_AREAS or dedup_slot != _assets._AREA_SLOT[area]:
            raise ValueError("area and dedup slot must be one of the three pairs")
        if not is_canonical_uuid(record_id) or (
            entity_id is not None and not is_canonical_uuid(entity_id)
        ):
            raise ValueError("record and entity ids are canonical UUID text")
        record = json.loads(self._temp_bytes(record_temp))
        if (
            record_dedup_id(record) != dedup_id
            or record["entity_id"] != entity_id
            or record["result"]["record_id"] != record_id
        ):
            raise HostError(
                "E_INTERNAL", "storage", None, "/store", "the record differs from its commit"
            )
        with self._lock:
            job = self._job(job_id)
            job["journal"].update(record_id=record_id, area=area)
            state = self._state(tenant)
            records = state["records"][area]
            linked = record_id not in records
            if linked:
                records[record_id] = record
            stored = records[record_id]
            slots = state["dedup"].setdefault(dedup_id, dict.fromkeys(DEDUP_SLOTS))
            if slots[dedup_slot] is None:
                slots[dedup_slot] = record_id
            if area == "records":
                product, _ = add_revision(state["products"].get(entity_id), record_id, stored)
                state["products"][entity_id] = product
            return linked

    def read_record(self, tenant: str, record_id: str, *, area: str) -> dict | None:
        if area not in RECORD_AREAS:
            raise ValueError("area is records, quarantine or rejected")
        with self._lock:
            record = self._state(tenant)["records"][area].get(record_id)
            return None if record is None else copy.deepcopy(record)

    def lookup_dedup(self, tenant: str, dedup_id: str) -> dict:
        with self._lock:
            slots = self._state(tenant)["dedup"].get(dedup_id)
            return dict(slots) if slots else dict.fromkeys(DEDUP_SLOTS)

    def publish(self, tenant: str, record_id: str) -> None:
        with self._lock:
            state = self._state(tenant)
            if record_id not in state["records"]["records"]:
                raise HostError(
                    "E_INTERNAL", "storage", None, "/store", "only a committed record is published"
                )
            state["published"].add(record_id)

    def is_published(self, tenant: str, record_id: str) -> bool:
        with self._lock:
            return record_id in self._state(tenant)["published"]

    def list_published(self, tenant: str) -> list[str]:
        with self._lock:
            return sorted(self._state(tenant)["published"])

    def read_product(self, tenant: str, entity_id: str) -> dict | None:
        with self._lock:
            product = self._state(tenant)["products"].get(entity_id)
            return None if product is None else copy.deepcopy(product)

    def select_revision(self, tenant: str, entity_id: str, revision: int) -> None:
        with self._lock:
            product = self._state(tenant)["products"].get(entity_id)
            if (
                product is None
                or type(revision) is not int
                or not any(entry["revision"] == revision for entry in product["revisions"])
            ):
                raise HostError("E_FIELD", "storage", None, "/revision", "no such revision")
            product["selected_revision"] = revision

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
        data = self._temp_bytes(temp_file)
        if not is_canonical_uuid(parent_id):
            raise _assets._no_asset()
        check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent_id, tenant)
        if not isinstance(security, SecurityDescriptor):
            raise TypeError("security must be a SecurityDescriptor")
        with self._lock:
            state = self._state(tenant)
            if security.sha256 not in state["descriptors"].get(parent_id, set()):
                raise HostError(
                    "E_POLICY",
                    "storage",
                    None,
                    "/derivative/security",
                    "a derivative inherits a descriptor registered for its parent, never its own",
                )
            parent = state["assets"].get(parent_id)
            if parent is None:
                raise _assets._no_asset()
            digest = hashlib.sha256(data).hexdigest()
            if digest != sha256:
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "the derivative differs from its stated digest",
                )
            recipe_sha = hashlib.sha256(_assets._canonical(recipe)).hexdigest()
            derivative_id = derivative_id_for(
                tenant, parent_id, parent["sha256"], recipe_sha, security.sha256
            )
            existing = state["derivatives"].get(derivative_id)
            if existing is not None:
                if existing[1]["sha256"] != digest:
                    raise HostError(
                        "E_INTEGRITY",
                        "storage",
                        None,
                        "/asset",
                        "the derivative exists with other content",
                    )
                return derivative_id
            state["derivatives"][derivative_id] = (
                data,
                {
                    "derivative_id": derivative_id,
                    "parent_id": parent_id,
                    "parent_sha256": parent["sha256"],
                    "recipe": copy.deepcopy(dict(recipe)),
                    "recipe_sha256": recipe_sha,
                    "descriptor": security.json_text,
                    "sha256": digest,
                    "bytes": len(data),
                    "provenance": copy.deepcopy(dict(provenance)),
                },
            )
            return derivative_id

    def read_derivative(self, derivative_id: str, *, tenant: str) -> dict | None:
        with self._lock:
            entry = self._state(tenant)["derivatives"].get(derivative_id)
            return None if entry is None else copy.deepcopy(entry[1])

    def list_derivatives(self, parent_id: str, *, tenant: str) -> list[str]:
        with self._lock:
            return sorted(
                derivative_id
                for derivative_id, (_, record) in self._state(tenant)["derivatives"].items()
                if record["parent_id"] == parent_id
            )

    def open_derivative(self, derivative_id: str, policy_ticket, *, tenant: str) -> OriginalReader:
        with self._lock:
            entry = self._state(tenant)["derivatives"].get(derivative_id)
        if entry is None:
            check_ticket(policy_ticket, (Artefact.THUMBNAIL,), "", tenant)
            raise _assets._no_asset()
        data, record = entry
        parent = record["parent_id"]
        check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent, tenant)

        def check() -> None:
            check_ticket(policy_ticket, (Artefact.THUMBNAIL,), parent, tenant)

        return OriginalReader(self._descriptor_of(data), record["bytes"], record["sha256"], check)

    def commit_export(
        self, job_id: str, record_temp: TempFile, *, tenant: str, export_id: str
    ) -> None:
        if not is_canonical_uuid(export_id):
            raise ValueError("an export id is canonical UUID text")
        record = json.loads(self._temp_bytes(record_temp))
        with self._lock:
            self._job(job_id)
            self._state(tenant)["exports"].setdefault(export_id, record)

    def recover(self) -> dict:
        """Nothing in memory survives a crash, so there is nothing to recover."""
        return recover_counts()
