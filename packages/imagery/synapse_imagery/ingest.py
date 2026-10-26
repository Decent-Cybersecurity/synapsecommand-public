"""The ingest transaction, the catalog over its records, and the identifiers both use.

THE TRANSACTION
---------------
`IngestService.ingest` runs one journalled transaction per call, in this order: the octets are
copied into private staging under the size cap with a running SHA-256; a repeat of the dedup key
is answered from the stored record; the worker inventories the staged octets in an isolated child;
the policy decides on the adapter's own security assessment; the immutable original is stored
(in quarantine when policy blocks it); the worker translates with a context carrying the asset id
and the digest the host computed; the record is persisted and committed by linking it into place;
and only then is it published. The link is the commit point: before it nothing is visible and a
failure rolls everything back; after it the next repeat of the key or `recover()` completes it.
A failure returns `failed` with one diagnostic and publishes nothing.

THE OTHER OPERATIONS
--------------------
`preview` draws an 8-bit derivative of one image in the worker behind a THUMBNAIL ticket, checks
it, commits it beside its parent and delivers a copy; a derivative of the same recipe, labels and
software already stored is delivered again without a worker run. `replay_original` relays the
stored original octets unchanged behind an ORIGINAL ticket, after recomputing their digest and
length; a mismatch marks the object and relays nothing. `export_nc` runs the experimental writer
and commits the export's provenance before its output exists. Each output is written under a
temporary name in its directory, flushed, and linked into place, never over an existing file
unless the caller asked to replace it. `Catalog.presentation` and `inspect_source` build the
user-visible imagery record from the inventory and the policy's decisions.

IDENTIFIERS
-----------
Record, asset, tenant-directory, derivative and export identifiers are UUIDv5 values of the
request and its outcome, never of the job, so no result carries a random value; only job ids,
which are staging names and never output, are random. Every identifier read from a caller is
checked against its form before a path is built from it, and an identifier of another tenant is
answered exactly as one that does not exist.
"""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import tempfile
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from synapse_cdm import canonical
from synapse_cdm.adapters import nsif_codec
from synapse_cdm.adapters.nsif_codec import NsifError
from synapse_cdm.adapters.stanag4545 import (
    CORE1_LIMITS,
    PROFILE_REVISION,
    Stanag4545Context,
    parse_container,
)
from synapse_cdm.version import PACKAGE_VERSION

from synapse_imagery import export as _export
from synapse_imagery import presentation as _presentation
from synapse_imagery import preview as _preview
from synapse_imagery._version import __version__
from synapse_imagery.policy import (
    EMPTY_REGISTRY,
    Artefact,
    DefaultPolicy,
    ExtensionRegistry,
    PolicyRequest,
    Principal,
    SecurityDescriptor,
    TicketAuthority,
    decide,
    unidentified,
)
from synapse_imagery.result import (
    CORE_CODES,
    FAILED_CODES,
    PROFILE,
    HostError,
    PolicyDenied,
    ResultContractError,
    assessment_incomplete,
    build_result,
    diagnostic,
    from_error,
    ordered,
    original_not_retained,
    policy_refused,
    validate_result,
)
from synapse_imagery.worker import Window, WorkerPool, WorkerWindow

__all__ = [
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
]

_LOG = logging.getLogger("synapse_imagery")

RECORD_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:synapsecommand:imagery:record")
ASSET_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:synapsecommand:imagery:asset")
TENANT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:synapsecommand:imagery:tenant")
DERIVATIVE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:synapsecommand:imagery:derivative")
EXPORT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "urn:synapsecommand:imagery:export")

RECORD_FORMAT = "sc-imagery-record/1"
_JOB_ID = re.compile(r"[0-9a-f]{32}")
_CHUNK = 1_048_576


def cj(value: object) -> str:
    """The compact JSON every identifier is derived from."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("ascii")).hexdigest()


def tenant_directory(tenant: str) -> str:
    return str(uuid.uuid5(TENANT_NAMESPACE, tenant))


def record_id_for(
    tenant: str,
    dataset_namespace: str,
    synthetic: bool,
    sha256: str,
    profile_revision: int,
    state: str,
) -> str:
    """The id of a catalogued record: committed, policy_blocked or rejected."""
    parts = ["sc-imagery-record/1", tenant, dataset_namespace, synthetic, sha256]
    return str(uuid.uuid5(RECORD_NAMESPACE, cj(parts + [profile_revision, state])))


def attempt_id_for(
    tenant: str,
    dataset_namespace: str,
    synthetic: bool,
    sha256: str | None,
    source_bytes: int,
    profile_revision: int,
    state: str,
    code: str,
    stage: str,
    path: str,
) -> str:
    """The id of an outcome nothing catalogues (a failure, a request for context, a refusal
    before hashing): a function of the request and the outcome, never of the job."""
    parts = ["sc-imagery-attempt/1", tenant, dataset_namespace, synthetic, sha256, source_bytes]
    parts += [profile_revision, state, code, stage, path]
    return str(uuid.uuid5(RECORD_NAMESPACE, cj(parts)))


def asset_id_for(tenant: str, sha256: str) -> str:
    """One original per tenant and digest, never shared across tenants."""
    return str(uuid.uuid5(ASSET_NAMESPACE, cj(["sc-imagery-original/1", tenant, sha256])))


def derivative_id_for(
    tenant: str,
    parent_asset_id: str,
    parent_sha256: str,
    recipe_sha256: str,
    descriptor_sha256: str,
) -> str:
    parts = ["sc-imagery-derivative/1", tenant, parent_asset_id, parent_sha256]
    return str(uuid.uuid5(DERIVATIVE_NAMESPACE, cj(parts + [recipe_sha256, descriptor_sha256])))


def export_id_for(tenant: str, recipe_sha256: str, output_sha256: str) -> str:
    parts = ["sc-imagery-export/1", tenant, recipe_sha256, output_sha256]
    return str(uuid.uuid5(EXPORT_NAMESPACE, cj(parts)))


def dedup_id_for(
    tenant: str, dataset_namespace: str, synthetic: bool, sha256: str, profile_revision: int
) -> str:
    parts = ["sc-imagery-dedup/1", tenant, dataset_namespace, synthetic, sha256, profile_revision]
    return _sha(cj(parts))


def is_canonical_uuid(value: object) -> bool:
    """Lowercase canonical UUID text, the only form an identifier read from a caller may take."""
    if type(value) is not str:
        return False
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def is_job_id(value: object) -> bool:
    return type(value) is str and _JOB_ID.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Whether octets the adapter refused are kept (under `rejected/`); by default they are not."""

    retain_rejected: bool = False

    def __post_init__(self) -> None:
        if type(self.retain_rejected) is not bool:
            raise TypeError("retain_rejected must be a bool")


# --------------------------------------------------------------------------- single answers

_NO_RECORD = "no committed record with this id for this principal"
_NO_QUARANTINED = "no quarantined record with this id for this principal"
_NO_PRODUCT = "no product with this id for this principal"


def _no_record() -> HostError:
    return HostError("E_FIELD", "storage", None, "/record_id", _NO_RECORD)


def _no_quarantined() -> HostError:
    return HostError("E_FIELD", "storage", None, "/record_id", _NO_QUARANTINED)


def _no_product() -> HostError:
    return HostError("E_FIELD", "storage", None, "/entity_id", _NO_PRODUCT)


def _principal(principal: object) -> Principal:
    if not isinstance(principal, Principal):
        raise TypeError("principal must be a Principal")
    return principal


def _int(value: object) -> bool:
    return type(value) is int


def _published_record(store, record_id: object, principal: Principal) -> dict:
    tenant = principal.tenant
    if not is_canonical_uuid(record_id):
        raise _no_record()
    record = store.read_record(tenant, record_id, area="records")
    if record is None or not store.is_published(tenant, record_id):
        raise _no_record()
    return record


# --------------------------------------------------------------------------- the catalog


class Catalog:
    """Reads over the committed, published records of one store, scoped to the principal's
    tenant. Thread-safe: the store's lock serialises what is shared."""

    def __init__(self, store, policy=None, *, authority: TicketAuthority | None = None) -> None:
        self._store = store
        self._policy = DefaultPolicy() if policy is None else policy
        self._authority = TicketAuthority(self._policy) if authority is None else authority

    def get(self, record_id: str, *, principal: Principal) -> dict:
        """The stored result document of a published committed record."""
        record = _published_record(self._store, record_id, _principal(principal))
        return ordered(record["result"])

    def list_records(self, *, principal: Principal) -> list[str]:
        return sorted(self._store.list_published(_principal(principal).tenant))

    def objects(self, record_id: str, *, principal: Principal) -> list[dict]:
        """The record's CDM objects verbatim, a footprint only with its product, released only
        when the current policy allows metadata on the record's descriptor."""
        principal = _principal(principal)
        record = _published_record(self._store, record_id, principal)
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        request = PolicyRequest(
            principal,
            Artefact.METADATA,
            descriptor,
            record["dedup"]["synthetic"],
            record_id,
            record["result"]["asset_id"],
        )
        decision = decide(self._policy, request)
        if not decision.allowed:
            raise PolicyDenied(
                Artefact.METADATA,
                f"refused by policy {decision.policy_id}/{decision.policy_version}: "
                f"{decision.reason}",
            )
        return copy.deepcopy(record["objects"])

    def revisions(self, entity_id: str, *, principal: Principal) -> dict:
        tenant = _principal(principal).tenant
        if not is_canonical_uuid(entity_id):
            raise _no_product()
        product = self._store.read_product(tenant, entity_id)
        if product is None:
            raise _no_product()
        return product

    def select_revision(self, entity_id: str, revision: int, *, principal: Principal) -> None:
        """The only way the selected revision changes: explicitly, never by a source date."""
        tenant = _principal(principal).tenant
        if not is_canonical_uuid(entity_id) or self._store.read_product(tenant, entity_id) is None:
            raise _no_product()
        if type(revision) is not int:
            raise TypeError("revision must be an int")
        self._store.select_revision(tenant, entity_id, revision)

    def read_quarantined(self, record_id: str, *, principal: Principal) -> dict:
        tenant = _principal(principal).tenant
        if not is_canonical_uuid(record_id):
            raise _no_quarantined()
        record = self._store.read_record(tenant, record_id, area="quarantine")
        if record is None:
            raise _no_quarantined()
        return record

    def presentation(self, record_id: str, *, principal: Principal) -> dict:
        """The record's user-visible imagery detail with this viewer's decisions: label values
        only under an allowed METADATA decision, previews and the derivatives only under an
        allowed THUMBNAIL decision."""
        principal = _principal(principal)
        record = _published_record(self._store, record_id, principal)
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        asset_id = record["result"]["asset_id"]

        def allowed(artefact: Artefact) -> bool:
            request = PolicyRequest(
                principal, artefact, descriptor, record["dedup"]["synthetic"], record_id, asset_id
            )
            return decide(self._policy, request).allowed

        labels_authorised = allowed(Artefact.METADATA)
        preview_allowed = allowed(Artefact.THUMBNAIL)
        derivatives = []
        if preview_allowed:
            for derivative_id in self._store.list_derivatives(asset_id, tenant=principal.tenant):
                stored = self._store.read_derivative(derivative_id, tenant=principal.tenant)
                index = stored["recipe"].get("image_index")
                if stored["descriptor"] == descriptor.json_text and _int(index):
                    derivatives.append({"derivative_id": derivative_id, "image_index": index})
            derivatives.sort(key=lambda entry: (entry["image_index"], entry["derivative_id"]))
        return _presentation.build(
            record["inventory"],
            product_entity_id=record["entity_id"],
            preview_allowed=preview_allowed,
            labels_authorised=labels_authorised,
            labels=descriptor.labels if labels_authorised else None,
            derivatives=derivatives,
        )


# --------------------------------------------------------------------------- the transaction

#: The stage a failure is reported under, by the step it happened in.
_STEP_STAGE = {
    "received": "input",
    "staged": "input",
    "dedup": "storage",
    "inventoried": "input",
    "assessed": "security",
    "stored": "storage",
    "translated": "cdm",
    "persisted": "storage",
    "committed": "storage",
    "published": "storage",
}


class _Job:
    __slots__ = (
        "principal",
        "dataset_namespace",
        "synthetic",
        "product_key",
        "as_of",
        "job_id",
        "step",
        "sha256",
        "size",
        "asset_id",
    )

    def __init__(self, principal, dataset_namespace, synthetic, product_key, as_of) -> None:
        self.principal = principal
        self.dataset_namespace = dataset_namespace
        self.synthetic = synthetic
        self.product_key = product_key
        self.as_of = as_of
        self.job_id = None
        self.step = "received"
        self.sha256 = None
        self.size = 0
        self.asset_id = None

    @property
    def tenant(self) -> str:
        return self.principal.tenant


class _Rejection(Exception):
    """Carries an early, already-validated result out of the step sequence."""

    def __init__(self, result: dict) -> None:
        super().__init__("early result")
        self.result = result


class IngestService:
    """The host's ingest, reassessment, recovery and window operations over one store."""

    def __init__(
        self,
        store,
        *,
        policy=None,
        worker=None,
        retention: RetentionPolicy | None = None,
        registry: ExtensionRegistry = EMPTY_REGISTRY,
        _fault: Callable[[str], None] | None = None,
    ) -> None:
        if not isinstance(registry, ExtensionRegistry):
            raise TypeError("registry must be an ExtensionRegistry")
        if retention is not None and not isinstance(retention, RetentionPolicy):
            raise TypeError("retention must be a RetentionPolicy")
        self._store = store
        self._registry = registry
        self._policy = DefaultPolicy(registry) if policy is None else policy
        self._own_pool = worker is None
        self._worker = WorkerPool() if worker is None else worker
        self._retention = RetentionPolicy() if retention is None else retention
        self._fault = _fault
        self._authority = TicketAuthority(self._policy)
        self._closed = False

    # ----------------------------------------------------------------- the public surface

    @property
    def catalog(self) -> Catalog:
        return Catalog(self._store, self._policy, authority=self._authority)

    def ingest(
        self,
        source,
        *,
        principal: Principal,
        dataset_namespace: str,
        synthetic: bool,
        product_key: str | None = None,
        as_of=None,
    ) -> dict:
        """One transaction; returns the validated result document. A configuration error
        raises before any job exists."""
        if type(synthetic) is not bool:
            # The live/synthetic choice has no default: a missing choice is a configuration
            # error, never False.
            raise TypeError("synthetic must be True or False")
        _principal(principal)
        Stanag4545Context(dataset_namespace=dataset_namespace, product_key=product_key, as_of=as_of)
        if type(source) is not bytes and not isinstance(source, (str, os.PathLike)):
            raise TypeError("source must be bytes or a path")
        if isinstance(source, os.PathLike) and not isinstance(os.fspath(source), str):
            raise TypeError("source must be bytes or a path")
        if not synthetic:
            self._refuse_fakes()
        job = _Job(principal, dataset_namespace, synthetic, product_key, as_of)
        if type(source) is bytes:
            job.size = len(source)
        return self._run(job, lambda: self._stage_source(job, source), released_from=None)

    def reassess(
        self,
        record_id: str,
        *,
        principal: Principal,
        product_key: str | None = None,
        as_of=None,
    ) -> dict:
        """Run a quarantined product through inventory, policy and translation again under the
        current policy and registry; admitted, it becomes a new committed record that names the
        quarantined one. Still denied, the stored blocked result is returned and nothing is
        written."""
        principal = _principal(principal)
        tenant = principal.tenant
        if not is_canonical_uuid(record_id):
            raise _no_quarantined()
        blocked = self._store.read_record(tenant, record_id, area="quarantine")
        if blocked is None:
            raise _no_quarantined()
        dedup = blocked["dedup"]
        Stanag4545Context(
            dataset_namespace=dedup["dataset_namespace"], product_key=product_key, as_of=as_of
        )
        if not dedup["synthetic"]:
            self._refuse_fakes()
        job = _Job(principal, dedup["dataset_namespace"], dedup["synthetic"], product_key, as_of)
        asset_id = blocked["result"]["asset_id"]

        def stage() -> None:
            source = self._store.open_quarantined_fd(asset_id, tenant=tenant)
            try:
                self._copy_into_staging(job, source, os.fstat(source).st_size)
            finally:
                os.close(source)
            if job.sha256 != dedup["sha256"]:
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "stored original differs from its recorded digest or length",
                )

        return self._run(job, stage, released_from=(record_id, blocked["result"]))

    def decode_window(
        self,
        record_id: str,
        image_index: int,
        window: Window,
        bands: tuple[int, ...],
        *,
        principal: Principal,
    ) -> WorkerWindow:
        """Samples of one window of a committed record's image, behind a PIXELS ticket on the
        record's descriptor: only the native NC cell decodes."""
        principal = _principal(principal)
        record = _published_record(self._store, record_id, principal)
        if not isinstance(window, Window):
            raise TypeError("window must be a Window")
        result = record["result"]
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        request = PolicyRequest(
            principal,
            Artefact.PIXELS,
            descriptor,
            record["dedup"]["synthetic"],
            record_id,
            result["asset_id"],
        )
        ticket = self._authority.issue(request)
        try:
            source = self._store.open_source_fd(result["asset_id"], ticket)
            try:
                answer = self._worker.decode_window(
                    source,
                    image_index,
                    window,
                    bands,
                    ticket,
                    expected_sha256=result["sha256"],
                    byte_count=result["source_bytes"],
                )
            finally:
                os.close(source)
            # The length the parent expects comes from its own record of the image.
            image = record["inventory"]["images"][image_index]
            expected = window.width * window.height * len(bands) * (image["nbpp"] // 8)
            if len(answer.window.data) != expected:
                raise HostError(
                    "E_INTERNAL", "pixels", None, "/worker", "the window differs from its record"
                )
            ticket.verify(artefact=Artefact.PIXELS, asset_id=ticket.asset_id, tenant=ticket.tenant)
            return answer
        finally:
            self._authority.revoke(ticket)

    def preview(
        self,
        record_id: str,
        image_index: int,
        output,
        *,
        principal: Principal,
        bands: tuple[int, ...] | None = None,
        replace: bool = False,
    ) -> dict:
        """An 8-bit, segment-only display derivative of one image of a committed record, behind
        a THUMBNAIL ticket on the record's descriptor, committed beside its parent and written to
        `output`. A derivative of the same recipe, labels and software is reused without a
        worker run, after a fresh ticket check."""
        principal = _principal(principal)
        record = _published_record(self._store, record_id, principal)
        if not _int(image_index):
            raise TypeError("image_index must be an int")
        spec = _preview.RenderingSpec(bands=bands)
        target = _output_target(output, replace)
        tenant = principal.tenant
        asset_id = record["result"]["asset_id"]
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        request = PolicyRequest(
            principal,
            Artefact.THUMBNAIL,
            descriptor,
            record["dedup"]["synthetic"],
            record_id,
            asset_id,
        )
        ticket = self._authority.issue(request)

        def still_allowed() -> None:
            ticket.verify(artefact=Artefact.THUMBNAIL, asset_id=asset_id, tenant=tenant)

        try:
            derivative_id = self._reusable(tenant, asset_id, descriptor, image_index, spec)
            if derivative_id is None:
                derivative_id = self._new_derivative(record, image_index, spec, descriptor, ticket)
            stored = self._store.read_derivative(derivative_id, tenant=tenant)
            with self._store.open_derivative(derivative_id, ticket, tenant=tenant) as reader:
                octets = reader.read()
            if (len(octets), hashlib.sha256(octets).hexdigest()) != (
                stored["bytes"],
                stored["sha256"],
            ):
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "the derivative differs from its recorded digest or length",
                )
            _deliver(target, octets, replace=replace, before_link=still_allowed)
        finally:
            self._authority.revoke(ticket)
        provenance = stored["provenance"]
        _LOG.info("preview delivered: derivative %s", derivative_id)
        return {
            "schema": "sc-imagery-preview/1",
            "record_id": record_id,
            "derivative_id": derivative_id,
            "image_index": image_index,
            "sha256": stored["sha256"],
            "bytes": stored["bytes"],
            "size": provenance["size"],
            "channels": 3
            if len(provenance["bands"]) == 3 or provenance["selection"] == "lut"
            else 1,
            "algorithm": provenance["algorithm"],
            "selection": provenance["selection"],
            "composition": "segment_only",
        }

    def _reusable(self, tenant, asset_id, descriptor, image_index, spec) -> str | None:
        """A stored derivative this request would produce: same image, size cap, selection,
        labels and software (an automatic selection's outcome is a function of the parent's
        octets, which the derivative's parent digest already fixes)."""
        software = _preview.software()
        for derivative_id in self._store.list_derivatives(asset_id, tenant=tenant):
            stored = self._store.read_derivative(derivative_id, tenant=tenant)
            recipe = stored["recipe"]
            if (
                stored["descriptor"] != descriptor.json_text
                or recipe.get("image_index") != image_index
                or recipe.get("max_size") != spec.max_size
                or recipe.get("software") != software
            ):
                continue
            if spec.bands is None and recipe.get("selection") in ("automatic", "lut"):
                return derivative_id
            if spec.bands is not None and (recipe.get("selection"), recipe.get("bands")) == (
                "explicit",
                list(spec.bands),
            ):
                return derivative_id
        return None

    def _new_derivative(self, record, image_index, spec, descriptor, ticket) -> str:
        store = self._store
        tenant = ticket.tenant
        result = record["result"]
        job = store.new_job(tenant=tenant)
        try:
            store.write_journal(job, "received")
            temp = store.new_temp(job, ".png")
            out = store.open_temp(temp)
            try:
                source = store.open_source_fd(result["asset_id"], ticket)
                try:
                    derivative = self._worker.make_preview(
                        source,
                        image_index,
                        spec,
                        ticket,
                        expected_sha256=result["sha256"],
                        byte_count=result["source_bytes"],
                        output_fd=out,
                    )
                finally:
                    os.close(source)
                _sync(out)
            finally:
                os.close(out)
            if self._fault is not None:
                self._fault("derivative_temp_written")
            # The worker found the image in its own parse; the parent holds it to its own record.
            image = record["inventory"]["images"][image_index]
            provenance = derivative.provenance
            if provenance["source_window"] != [0, 0, image["ncols"], image["nrows"]] or (
                derivative.width,
                derivative.height,
            ) != _preview.preview_size(image["ncols"], image["nrows"], spec.max_size):
                raise HostError(
                    "E_INTERNAL", "pixels", None, "/worker", "the preview differs from its record"
                )
            if store.temp_digest(temp) != (derivative.byte_count, derivative.sha256):
                raise HostError(
                    "E_INTERNAL",
                    "pixels",
                    None,
                    "/worker",
                    "the preview file differs from its answer",
                )
            ticket.verify(artefact=Artefact.THUMBNAIL, asset_id=ticket.asset_id, tenant=tenant)
            recipe = {
                "algorithm": provenance["algorithm"],
                "image_index": image_index,
                "max_size": spec.max_size,
                "selection": provenance["selection"],
                "bands": provenance["bands"],
                "software": provenance["software"],
            }
            return store.commit_derivative(
                result["asset_id"],
                temp,
                derivative.sha256,
                recipe,
                descriptor,
                tenant=tenant,
                policy_ticket=ticket,
                provenance=provenance,
            )
        finally:
            try:
                store.delete_uncommitted(job)
            except (OSError, HostError):
                _LOG.warning("a staging directory could not be removed")

    def replay_original(
        self,
        record_id: str,
        destination,
        *,
        principal: Principal,
        replace: bool = False,
        mutations: tuple = (),
    ) -> dict:
        """The stored original octets of a committed record, unchanged, written to
        `destination`: the current policy is asked again, the octets are read and their digest
        and length recomputed, and only then written. No parameter edits anything."""
        principal = _principal(principal)
        tenant = principal.tenant
        if not is_canonical_uuid(record_id):
            raise _no_record()
        record = self._store.read_record(tenant, record_id, area="records")
        if record is None or not self._store.is_published(tenant, record_id):
            if self._store.read_record(tenant, record_id, area="quarantine") is not None:
                raise PolicyDenied(Artefact.ORIGINAL, "a quarantined original is never relayed")
            raise _no_record()
        if isinstance(mutations, (str, bytes)) or not isinstance(mutations, (tuple, list)):
            raise TypeError("mutations is a tuple")
        if mutations:
            raise HostError(
                "E_POLICY",
                "export",
                None,
                "/replay/mutations",
                "replay relays the unchanged original; any change needs a new authored product "
                "and a fresh policy review",
            )
        result = record["result"]
        asset_id = result["asset_id"]
        descriptor = SecurityDescriptor.from_json(record["descriptor"])
        request = PolicyRequest(
            principal,
            Artefact.ORIGINAL,
            descriptor,
            record["dedup"]["synthetic"],
            record_id,
            asset_id,
        )
        ticket = self._authority.issue(request)

        def still_allowed() -> None:
            if self._fault is not None:
                self._fault("replay_part_written")
            ticket.verify(artefact=Artefact.ORIGINAL, asset_id=asset_id, tenant=tenant)

        try:
            target = _output_target(destination, replace)
            with self._store.open_original(asset_id, ticket) as reader:
                octets = reader.read()
                recorded = (reader.size, reader.sha256)
            if (len(octets), hashlib.sha256(octets).hexdigest()) != recorded or recorded != (
                result["source_bytes"],
                result["sha256"],
            ):
                # Never relayed: every later open of this asset is refused too, and the object
                # stays in place for investigation.
                self._store.mark_integrity_failed(asset_id, tenant=tenant)
                _LOG.warning("replay refused: asset %s failed its integrity check", asset_id)
                raise HostError(
                    "E_INTEGRITY",
                    "storage",
                    None,
                    "/asset",
                    "stored original differs from its recorded digest or length",
                )
            _deliver(target, octets, replace=replace, before_link=still_allowed)
        finally:
            self._authority.revoke(ticket)
        inventory = record["inventory"]
        _LOG.info("replay delivered: record %s", record_id)
        return {
            "schema": "sc-imagery-replay/1",
            "record_id": record_id,
            "asset_id": asset_id,
            "sha256": result["sha256"],
            "bytes": result["source_bytes"],
            "wire_signature": inventory["signature"],
            "relay": "unchanged_original_octets",
            "authored": False,
            "retained_unsupported": _presentation.unsupported_content(inventory),
            "notice": REPLAY_NOTICE,
        }

    def export_nc(
        self, recipe_path, output, *, principal: Principal, replace: bool = False
    ) -> dict:
        """The experimental SC4545-WRITE-NC8-1 writer: the recipe validated, the file written and
        checked, the export's provenance committed, and only then the output delivered."""
        principal = _principal(principal)
        tenant = principal.tenant
        target = _output_target(output, replace)
        recipe = _export.read_recipe(_read_recipe_file(recipe_path))
        parent = None
        tickets = []
        synthetic = False
        try:
            if "parent" in recipe:
                parent_id = recipe["parent"]["record_id"]
                try:
                    record = _published_record(self._store, parent_id, principal)
                except HostError:
                    raise HostError(
                        "E_FIELD", "export", None, "/recipe/parent/record_id", _NO_RECORD
                    ) from None
                # An export inherits its parent's live or synthetic standing; without a parent it
                # is decided as live material, the stricter reading.
                synthetic = record["dedup"]["synthetic"]
                parent_asset = record["result"]["asset_id"]
                tickets.append(
                    self._authority.issue(
                        PolicyRequest(
                            principal,
                            Artefact.EXPORT,
                            SecurityDescriptor.from_json(record["descriptor"]),
                            synthetic,
                            parent_id,
                            parent_asset,
                        )
                    )
                )
                parent = {
                    "record_id": parent_id,
                    "asset_id": parent_asset,
                    "sha256": record["result"]["sha256"],
                }
            written = _export.write_nc8(recipe)
            container = parse_container(written.octets, CORE1_LIMITS)
            own = SecurityDescriptor.from_container(container, self._registry)
            software = {"synapse_imagery": __version__, "synapse_cdm": PACKAGE_VERSION}
            document = _export.export_record(recipe, written, parent, software)
            output_sha256 = written.provenance["output"]["sha256"]
            export_id = export_id_for(tenant, document["recipe_sha256"], output_sha256)
            tickets.append(
                self._authority.issue(
                    PolicyRequest(principal, Artefact.EXPORT, own, synthetic, None, export_id)
                )
            )

            def still_allowed() -> None:
                for ticket in tickets:
                    ticket.verify(artefact=Artefact.EXPORT, asset_id=ticket.asset_id, tenant=tenant)

            self._commit_export(tenant, export_id, document)
            _deliver(target, written.octets, replace=replace, before_link=still_allowed)
        finally:
            for ticket in tickets:
                self._authority.revoke(ticket)
        _LOG.info("export delivered: export %s", export_id)
        return {
            "schema": "sc-imagery-export/1",
            "export_id": export_id,
            "output_sha256": output_sha256,
            "bytes": len(written.octets),
            "magic": written.provenance["output"]["magic"],
            "writer": _export.WRITER,
            "status": _export.STATUS,
        }

    def _commit_export(self, tenant: str, export_id: str, document: dict) -> None:
        """The export's provenance, committed before any output exists: a delivery that fails
        afterwards leaves a record of an export that was not delivered, never the reverse."""
        store = self._store
        job = store.new_job(tenant=tenant)
        try:
            store.write_journal(job, "received")
            temp = store.new_temp(job, ".json")
            out = store.open_temp(temp)
            try:
                _write_all(out, canonical.serialise(document).encode("utf-8"))
                _sync(out)
            finally:
                os.close(out)
            if self._fault is not None:
                self._fault("export_temp_written")
            store.commit_export(job, temp, tenant=tenant, export_id=export_id)
            store.write_journal(job, "committed")
        finally:
            try:
                store.delete_uncommitted(job)
            except (OSError, HostError):
                _LOG.warning("a staging directory could not be removed")

    def recover(self) -> dict:
        return self._store.recover()

    def close(self) -> None:
        """Idempotent; kills the live children of a pool this service built itself."""
        if self._closed:
            return
        self._closed = True
        if self._own_pool:
            self._worker.shutdown(kill=True)

    def __enter__(self) -> IngestService:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ----------------------------------------------------------------- the steps

    def _refuse_fakes(self) -> None:
        from synapse_imagery import fakes

        if getattr(self._worker, "isolation", None) != "subprocess":
            raise ValueError("live material needs the isolated worker")
        if isinstance(self._policy, fakes.FakePolicy):
            raise ValueError("live material cannot be decided by the test fake policy")
        if isinstance(self._store, fakes.MemoryAssetStore):
            raise ValueError("live material cannot be kept in the test fake store")

    def _mark(self, job: _Job, state: str, **facts) -> None:
        self._store.write_journal(job.job_id, state, **facts)
        if self._fault is not None:
            self._fault(state)

    def _run(self, job: _Job, stage: Callable[[], None], released_from) -> dict:
        try:
            result = self._steps(job, stage, released_from)
        except _Rejection as early:
            result = early.result
            self._cleanup(job)
        except Exception as error:  # the rollback: nothing published, one diagnostic returned
            result = self._failed(job, error)
        except BaseException:
            # An interrupt ends the job as a failure would (a committed record stays, for the
            # next recover() to publish) and then goes on.
            self._undo(job)
            raise
        else:
            self._cleanup(job)
        validate_result(result)
        state = result["state"]
        _LOG.info("ingest ended in state %s", state)
        return result

    def _cleanup(self, job: _Job) -> None:
        if job.job_id is None:
            return
        try:
            self._store.delete_uncommitted(job.job_id)
        except (OSError, HostError):
            # The outcome is already decided; recover() removes what is left.
            _LOG.warning("a staging directory could not be removed")

    def _failed(self, job: _Job, error: Exception) -> dict:
        if isinstance(error, HostError) and error.code in FAILED_CODES:
            entry = from_error(error)
        elif isinstance(error, OSError):
            if job.step in ("received", "staged"):
                entry = diagnostic(
                    "E_IO", "input", None, "/input", "the source could not be staged"
                )
            else:
                entry = diagnostic("E_IO", "storage", None, "/store", "a storage operation failed")
        elif isinstance(error, ResultContractError):
            entry = diagnostic(
                "E_INTERNAL", "storage", None, "/result", "the result broke its contract"
            )
        else:
            entry = diagnostic(
                "E_INTERNAL",
                _STEP_STAGE[job.step],
                None,
                "/" + job.step,
                "an unexpected error ended the transaction",
            )
        self._undo(job)
        code = entry["code"]
        stage = entry["stage"]
        _LOG.warning("ingest failed with %s at stage %s", code, stage)
        return build_result(
            "failed",
            record_id=attempt_id_for(
                job.tenant,
                job.dataset_namespace,
                job.synthetic,
                job.sha256,
                job.size,
                PROFILE_REVISION,
                "failed",
                code,
                stage,
                entry["path"],
            ),
            sha256=job.sha256,
            source_bytes=job.size,
            synthetic=job.synthetic,
            asset_id=None,
            cdm_ids=[],
            images=[],
            diagnostics=[entry],
        )

    def _undo(self, job: _Job) -> None:
        if job.job_id is None:
            return
        for undo in (self._store.discard_job_asset, self._store.delete_uncommitted):
            try:
                undo(job.job_id)
            except (OSError, HostError):
                _LOG.warning("a rollback step could not complete")

    def _uncatalogued(self, job: _Job, error, asset_id: str | None = None) -> _Rejection:
        """A rejection nothing catalogues: a request for context, or a refusal before hashing."""
        entry = from_error(error)
        result = build_result(
            "rejected",
            record_id=attempt_id_for(
                job.tenant,
                job.dataset_namespace,
                job.synthetic,
                job.sha256,
                job.size,
                PROFILE_REVISION,
                "rejected",
                entry["code"],
                entry["stage"],
                entry["path"],
            ),
            sha256=job.sha256,
            source_bytes=job.size,
            synthetic=job.synthetic,
            asset_id=asset_id,
            cdm_ids=[],
            images=[],
            diagnostics=[entry],
        )
        self._check(result)
        return _Rejection(result)

    def _check(self, result: dict) -> None:
        try:
            validate_result(result)
        except ResultContractError:
            raise HostError(
                "E_INTERNAL", "storage", None, "/result", "the result broke its contract"
            ) from None

    def _stage_source(self, job: _Job, source) -> None:
        if type(source) is bytes:
            job.size = len(source)
            self._copy_into_staging(job, source, len(source))
            return
        try:
            descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
        except ValueError:
            # A path no file can have (an embedded NUL, a character the file system cannot
            # encode) is answered as a path that names no file.
            raise HostError(
                "E_IO", "input", None, "/input", "the source could not be staged"
            ) from None
        try:
            status = os.fstat(descriptor)
            job.size = status.st_size
            if not stat.S_ISREG(status.st_mode):
                raise HostError("E_IO", "input", None, "/input", "the source is not a regular file")
            self._copy_into_staging(job, descriptor, status.st_size)
        finally:
            os.close(descriptor)

    def _copy_into_staging(self, job: _Job, source, size: int) -> None:
        """Copy `source` (octets or a descriptor) into the job's private staging file under the
        size cap, hashing as it goes; the digest is of exactly the staged octets."""
        cap = nsif_codec.CORE1_LIMITS.input_bytes
        if size > cap:
            raise self._uncatalogued(
                job,
                NsifError(
                    "E_LIMIT", "input", None, "/input", f"the input is larger than {cap} octets"
                ),
            )
        temp = self._store.new_temp(job.job_id, ".source")
        out = self._store.open_temp(temp)
        digest = hashlib.sha256()
        count = 0
        try:
            if type(source) is bytes:
                for start in range(0, len(source), _CHUNK):
                    chunk = source[start : start + _CHUNK]
                    _write_all(out, chunk)
                    digest.update(chunk)
                    count += len(chunk)
            else:
                while True:
                    chunk = os.read(source, _CHUNK)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > size:
                        break
                    _write_all(out, chunk)
                    digest.update(chunk)
            if count != size:
                raise HostError(
                    "E_IO", "input", None, "/input", "the source changed while it was staged"
                )
            _sync(out)
        finally:
            os.close(out)
        job.sha256 = digest.hexdigest()
        job.size = count

    def _steps(self, job: _Job, stage: Callable[[], None], released_from) -> dict:
        store = self._store
        tenant = job.tenant
        job.job_id = store.new_job(tenant=tenant)
        self._mark(job, "received")
        job.step = "staged"
        stage()
        self._mark(job, "staged", sha256=job.sha256)

        job.step = "dedup"
        dedup_id = dedup_id_for(
            tenant, job.dataset_namespace, job.synthetic, job.sha256, PROFILE_REVISION
        )
        slots = store.lookup_dedup(tenant, dedup_id)
        repeat = (("committed", "records"),)
        if released_from is None:
            repeat += (("policy_blocked", "quarantine"), ("rejected", "rejected"))
        for slot, area in repeat:
            if slots[slot] is None:
                continue
            stored = store.read_record(tenant, slots[slot], area=area)
            if stored is None:
                continue
            if slot == "committed" and not store.is_published(tenant, slots[slot]):
                store.publish(tenant, slots[slot])
            raise _Rejection(ordered(stored["result"]))

        job.step = "inventoried"
        inventory = self._inventory(job)
        self._mark(job, "inventoried")

        job.step = "assessed"
        descriptor = SecurityDescriptor.from_json(inventory["descriptor"])
        request = PolicyRequest(
            job.principal, Artefact.METADATA, descriptor, job.synthetic, None, None
        )
        decision = decide(self._policy, request)
        self._mark(job, "assessed")
        if released_from is not None and not decision.allowed:
            raise _Rejection(ordered(released_from[1]))

        job.step = "stored"
        job.asset_id = self._put_original(job, descriptor, quarantine=not decision.allowed)
        self._mark(job, "stored")
        record_facts = {
            "dedup_id": dedup_id,
            "descriptor": descriptor,
            "decision": decision,
            "inventory": inventory,
            "released_from": None if released_from is None else released_from[0],
        }
        if not decision.allowed:
            count = unidentified(descriptor, self._registry)
            entries = [policy_refused(decision.policy_id, decision.policy_version, decision.reason)]
            if decision.completeness == "incomplete":
                entries.append(assessment_incomplete(count, descriptor.registry_version))
            images = [
                {
                    "index": image["index"],
                    "pixel_status": "policy_blocked",
                    "geometry_status": "policy_blocked",
                }
                for image in inventory["images"]
            ]
            result = self._result(job, "policy_blocked", job.asset_id, [], images, entries)
            return self._commit(job, result, "quarantine", None, [], record_facts)

        job.step = "translated"
        objects = self._translate(job, inventory, record_facts)
        self._mark(job, "translated")

        entity_id = objects[0]["entity_id"]
        cdm_ids = [entity_id] + [item["object_id"] for item in objects[1:]]
        images = [
            {
                "index": image["index"],
                "pixel_status": image["pixel_status"],
                "geometry_status": image["geometry_status"],
            }
            for image in inventory["images"]
        ]
        result = self._result(
            job, "committed", job.asset_id, cdm_ids, images, inventory["diagnostics"]
        )
        return self._commit(job, result, "records", entity_id, objects, record_facts)

    def _inventory(self, job: _Job) -> dict:
        source = self._store.open_staged(job.job_id)
        try:
            return self._worker.inventory(
                source,
                expected_sha256=job.sha256,
                byte_count=job.size,
                registry=self._registry,
            )
        except NsifError as error:
            if error.code in CORE_CODES:
                raise _Rejection(self._rejected(job, error, None)) from None
            raise
        finally:
            os.close(source)

    def _translate(self, job: _Job, inventory: dict, facts: dict) -> list[dict]:
        context = Stanag4545Context(
            dataset_namespace=job.dataset_namespace,
            product_key=job.product_key,
            as_of=job.as_of,
            asset_ref=job.asset_id,
            verified_sha256=job.sha256,
        )
        source = self._store.open_staged(job.job_id)
        try:
            objects = self._worker.translate(
                source,
                expected_sha256=job.sha256,
                byte_count=job.size,
                context=context,
                synthetic=job.synthetic,
            )
        except NsifError as error:
            if error.code not in CORE_CODES:
                raise
            # Translation refused the octets: the original stored a step ago goes again.
            self._store.discard_job_asset(job.job_id)
            job.asset_id = None
            if error.code == "E_CONTEXT":
                raise self._uncatalogued(job, error) from None
            raise _Rejection(self._rejected(job, error, facts)) from None
        finally:
            os.close(source)
        if len(objects) > 1 + len(inventory["images"]):
            raise HostError(
                "E_INTERNAL", "cdm", None, "/worker", "more objects than the record allows"
            )
        return objects

    def _put_original(self, job: _Job, descriptor, *, quarantine=False, rejected=False) -> str:
        with os.fdopen(self._store.open_staged(job.job_id), "rb") as stream:
            return self._store.put_original(
                stream,
                job.sha256,
                job.size,
                descriptor,
                tenant=job.tenant,
                quarantine=quarantine,
                rejected=rejected,
                job_id=job.job_id,
            )

    def _rejected(self, job: _Job, error: NsifError, facts: dict | None) -> dict:
        """A catalogued rejection of hashed octets; retention decides whether they are kept."""
        entries = [from_error(error)]
        descriptor = None if facts is None else facts["descriptor"]
        asset_id = None
        if self._retention.retain_rejected:
            asset_id = self._put_original(job, descriptor, rejected=True)
        else:
            entries.append(original_not_retained())
        result = self._result(job, "rejected", asset_id, [], [], entries)
        if facts is None:
            facts = {
                "dedup_id": dedup_id_for(
                    job.tenant, job.dataset_namespace, job.synthetic, job.sha256, PROFILE_REVISION
                ),
                "descriptor": None,
                "decision": None,
                "inventory": None,
                "released_from": None,
            }
        return self._commit(job, result, "rejected", None, [], facts)

    def _result(self, job: _Job, state: str, asset_id, cdm_ids, images, entries) -> dict:
        record_id = record_id_for(
            job.tenant, job.dataset_namespace, job.synthetic, job.sha256, PROFILE_REVISION, state
        )
        result = build_result(
            state,
            record_id=record_id,
            sha256=job.sha256,
            source_bytes=job.size,
            synthetic=job.synthetic,
            asset_id=asset_id,
            cdm_ids=cdm_ids,
            images=images,
            diagnostics=entries,
        )
        self._check(result)
        return result

    def _commit(self, job: _Job, result: dict, area: str, entity_id, objects, facts) -> dict:
        """Persist the record, link it into its area (the commit point) and, for a committed
        product, publish it."""
        store = self._store
        decision = facts["decision"]
        descriptor = facts["descriptor"]
        record = {
            "format": RECORD_FORMAT,
            "result": result,
            "dedup": {
                "tenant": job.tenant,
                "dataset_namespace": job.dataset_namespace,
                "synthetic": job.synthetic,
                "sha256": job.sha256,
                "profile_revision": PROFILE_REVISION,
            },
            "entity_id": entity_id,
            "descriptor": None if descriptor is None else descriptor.json_text,
            "decision": None
            if decision is None
            else {
                "policy_id": decision.policy_id,
                "policy_version": decision.policy_version,
                "allowed": decision.allowed,
                "reason": decision.reason,
                "completeness": decision.completeness,
            },
            "inventory": facts["inventory"],
            "objects": objects,
            # The viewer-neutral detail, fixed at commit: records are immutable once linked, and
            # a viewer's own decisions are added when it is read (Catalog.presentation).
            "presentation": None
            if area != "records"
            else _presentation.build(
                facts["inventory"],
                product_entity_id=entity_id,
                preview_allowed=False,
                labels_authorised=False,
                labels=None,
                derivatives=[],
            ),
            "host": {
                "worker": getattr(self._worker, "last_report", None),
                "software": {"synapse_imagery": __version__, "synapse_cdm": PACKAGE_VERSION},
                "released_from": facts["released_from"],
            },
        }
        job.step = "persisted"
        temp = store.new_temp(job.job_id, ".json")
        out = store.open_temp(temp)
        try:
            _write_all(out, canonical.serialise(record).encode("utf-8"))
            _sync(out)
        finally:
            os.close(out)
        self._mark(job, "persisted")

        job.step = "committed"
        record_id = result["record_id"]
        slot = {"records": "committed", "quarantine": "policy_blocked", "rejected": "rejected"}[
            area
        ]
        linked = store.commit_record(
            job.job_id,
            temp,
            tenant=job.tenant,
            area=area,
            record_id=record_id,
            dedup_id=facts["dedup_id"],
            dedup_slot=slot,
            entity_id=entity_id,
        )
        if not linked:
            # An identical concurrent ingest committed first; its record is the answer.
            result = ordered(store.read_record(job.tenant, record_id, area=area)["result"])
        self._mark(job, "committed")
        if area != "records":
            return result

        job.step = "published"
        store.publish(job.tenant, record_id)
        self._mark(job, "published")
        return result


REPLAY_NOTICE = (
    "Original octets relayed unchanged: not a newly authored NSIF file, not a CDM translation, "
    "and no unrecognised extension was interpreted."
)


# --------------------------------------------------------------------------- inspect


def inspect_source(
    source, *, worker=None, policy=None, registry: ExtensionRegistry = EMPTY_REGISTRY
) -> dict:
    """The inspect document of one source, with no store: the octets are staged in a private
    directory, inventoried in the worker and shown to the policy as local synthetic material.
    It carries structure, the adapter's assessment and the policy's decision, never a label
    value, title, comment, identifier or coordinate; a container the adapter refuses gives the
    `valid: false` document, not an exception."""
    if not isinstance(registry, ExtensionRegistry):
        raise TypeError("registry must be an ExtensionRegistry")
    if type(source) is not bytes and not isinstance(source, (str, os.PathLike)):
        raise TypeError("source must be bytes or a path")
    engine = DefaultPolicy(registry) if policy is None else policy
    own_pool = worker is None
    worker = WorkerPool() if own_pool else worker
    directory = tempfile.mkdtemp(prefix="sc-imagery-inspect-")
    staged = os.path.join(directory, "source")
    try:
        return _inspect(source, staged, worker, engine, registry)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(staged)
        os.rmdir(directory)
        if own_pool:
            worker.shutdown(kill=True)


def _too_large(size: int) -> dict:
    cap = nsif_codec.CORE1_LIMITS.input_bytes
    error = NsifError("E_LIMIT", "input", None, "/input", f"the input is larger than {cap} octets")
    return _invalid(size, None, from_error(error), None)


def _inspect(source, staged: str, worker, engine, registry) -> dict:
    cap = nsif_codec.CORE1_LIMITS.input_bytes
    out = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    digest = hashlib.sha256()
    try:
        if type(source) is bytes:
            if len(source) > cap:
                return _too_large(len(source))
            _write_all(out, source)
            digest.update(source)
            count = len(source)
        else:
            count, size = _copy_path(source, out, digest, cap)
            if count is None:
                return _too_large(size)
    finally:
        os.close(out)
    sha256 = digest.hexdigest()
    descriptor_fd = os.open(staged, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        inventory = worker.inventory(
            descriptor_fd, expected_sha256=sha256, byte_count=count, registry=registry
        )
    except NsifError as error:
        if error.code not in CORE_CODES:
            raise
        return _invalid(count, sha256, from_error(error), getattr(worker, "last_report", None))
    finally:
        os.close(descriptor_fd)
    descriptor = SecurityDescriptor.from_json(inventory["descriptor"])
    local = Principal("local", "local-operator")
    decision = decide(engine, PolicyRequest(local, Artefact.METADATA, descriptor, True, None, None))
    thumbnails = decide(
        engine, PolicyRequest(local, Artefact.THUMBNAIL, descriptor, True, None, None)
    )
    kinds = [segment["kind"] for segment in inventory["segments"]]
    return {
        "schema": "sc-imagery-inspect/1",
        "profile": PROFILE,
        "valid": True,
        "source_bytes": count,
        "sha256": sha256,
        "wire_signature": inventory["signature"],
        "clevel": inventory["clevel"],
        "file_date": inventory["file_date"],
        "segments": {kind: kinds.count(kind) for kind in nsif_codec.KINDS},
        "images": inventory["images"],
        "extensions": inventory["extension_counts"],
        "composition_status": inventory["composition_status"],
        "security": {"assessment": descriptor.assessment},
        "policy": {
            "policy_id": decision.policy_id,
            "policy_version": decision.policy_version,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "completeness": decision.completeness,
        },
        "warnings": [] if decision.allowed else ["POLICY_UNRESOLVED"],
        # Pre-policy output: never a label value, whatever the policy would allow.
        "presentation": _presentation.build(
            inventory,
            product_entity_id=None,
            preview_allowed=thumbnails.allowed,
            labels_authorised=False,
            labels=None,
            derivatives=[],
        ),
        "diagnostics": inventory["diagnostics"],
        "worker": getattr(worker, "last_report", None),
    }


def _copy_path(source, out: int, digest, cap: int) -> tuple[int | None, int]:
    """Copy a regular file into the staged file, hashing: (octets copied, size), the count None
    when the file is over the cap and nothing was read."""
    try:
        descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError):
        raise HostError("E_IO", "input", None, "/input", "the source could not be staged") from None
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode):
            raise HostError("E_IO", "input", None, "/input", "the source is not a regular file")
        if status.st_size > cap:
            return None, status.st_size
        count = 0
        while chunk := os.read(descriptor, _CHUNK):
            count += len(chunk)
            if count > status.st_size:
                break
            _write_all(out, chunk)
            digest.update(chunk)
        if count != status.st_size:
            raise HostError(
                "E_IO", "input", None, "/input", "the source changed while it was staged"
            )
        return count, status.st_size
    finally:
        os.close(descriptor)


def _invalid(source_bytes: int, sha256: str | None, entry: dict, report) -> dict:
    return {
        "schema": "sc-imagery-inspect/1",
        "profile": PROFILE,
        "valid": False,
        "source_bytes": source_bytes,
        "sha256": sha256,
        "wire_signature": None,
        "clevel": None,
        "file_date": None,
        "segments": None,
        "images": None,
        "extensions": None,
        "composition_status": None,
        "security": None,
        "policy": None,
        "warnings": [],
        "presentation": None,
        "diagnostics": [entry],
        "worker": report,
    }


# --------------------------------------------------------------------------- outputs

#: Every temporary output name this process has open, so an interrupt can remove what an
#: unwinding stack did not.
_LIVE_PARTS: set[str] = set()
_PARTS_LOCK = threading.Lock()


def _output_target(output, replace: bool) -> str:
    """The absolute output path, refused before any work: its directory must exist, and an
    existing entry is replaced only on request and only when it is a file or a symlink."""
    if type(replace) is not bool:
        raise TypeError("replace must be a bool")
    if not isinstance(output, (str, os.PathLike)) or not isinstance(os.fspath(output), str):
        raise TypeError("output must be a str path")
    path = os.path.abspath(os.fspath(output))
    directory = os.path.dirname(path)
    try:
        if not stat.S_ISDIR(os.stat(directory).st_mode):
            raise NotADirectoryError("the output's directory is not a directory")
    except FileNotFoundError:
        raise FileNotFoundError("the output's directory does not exist") from None
    try:
        status = os.lstat(path)
    except FileNotFoundError:
        return path
    if not replace:
        raise FileExistsError("the output exists and is not replaced without replace=True")
    if not (stat.S_ISREG(status.st_mode) or stat.S_ISLNK(status.st_mode)):
        raise IsADirectoryError("only a regular file or a symlink is replaced")
    return path


def _deliver(path: str, data: bytes, *, replace: bool, before_link=None) -> None:
    """Write `data` to `path` atomically: a new temporary name in the same directory, flushed,
    then linked into place (an entry that appeared meanwhile is never overwritten) or, when
    asked, renamed over it, and the directory flushed. The temporary name never outlives the
    call."""
    from synapse_imagery.assets import _fsync_dir

    directory, name = os.path.split(path)
    part = os.path.join(directory, f".{name}.{secrets.token_hex(16)}.part")
    descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with _PARTS_LOCK:
        _LIVE_PARTS.add(part)
    try:
        try:
            _write_all(descriptor, data)
            _sync(descriptor)
        finally:
            os.close(descriptor)
        if before_link is not None:
            before_link()
        if replace:
            os.replace(part, path)
        else:
            os.link(part, path)
        _fsync_dir(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(part)
        with _PARTS_LOCK:
            _LIVE_PARTS.discard(part)


def _remove_live_parts() -> int:
    """Remove every temporary output name still open (the interrupt path)."""
    with _PARTS_LOCK:
        parts = sorted(_LIVE_PARTS)
        _LIVE_PARTS.clear()
    removed = 0
    for part in parts:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(part)
            removed += 1
    return removed


def _read_recipe_file(path) -> bytes:
    """A recipe file's octets, read from a regular file under the recipe cap plus one, so an
    oversized recipe is refused by the reader without being read whole."""
    if not isinstance(path, (str, os.PathLike)):
        raise TypeError("recipe_path must be a path")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except (OSError, ValueError):
        raise HostError("E_IO", "input", None, "/recipe", "the recipe could not be read") from None
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise HostError("E_IO", "input", None, "/recipe", "the recipe is not a regular file")
        chunks, count = [], 0
        while count <= _export.RECIPE_BYTES and (chunk := os.read(descriptor, _CHUNK)):
            chunks.append(chunk)
            count += len(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        view = view[written:]


def _sync(descriptor: int) -> None:
    from synapse_imagery.assets import _fsync

    _fsync(descriptor)
