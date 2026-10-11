"""Authorised export of one CDM Entity (and its one-sample Track) to a gateway (REQ091-097,
REQ131-133, REQ141).

`export(entity, track, peer_id)` checks, in this order, and each failure is an `EXPORT_DENIED`
with its reason, an audit row and the `export_denied` counter, and zero sends:

1. the configuration permits transmission (`mode` bidirectional; a replay realm never exports)
   and the startup enabled exports (`POLICY_DENIED`, `PROFILE_NOT_READY`); and the Entity was not
   published under the compatibility projection with its position left out: an Entity whose
   `source.transformations` carry the `POSITION_NOT_PROJECTED_CDM3` marker, or whose stored
   current snapshot does, is `PROFILE_NOT_READY`, because a report built from it would say
   `position: null` for a source that reported one, with no loss record. Exporting a positioned
   SENSOR or UNKNOWN source needs the FULL projection, which a sink accepting CDM 3.1.0 is served
   from the 3.4.0 release (A2F, 2026-10-11);
2. this instance holds the writer lease (`LEASE_LOST`);
3. the channel is NORMAL — not INCOMPLETE, awaiting resynchronisation, stopped or overloaded
   (`CHANNEL_INCOMPLETE`);
4. the source identity is one this channel ingested and is open (`POLICY_DENIED`); the Entity
   is, in canonical JSON, exactly the stored current snapshot of that identity, or exactly the
   Entity the bridge published for a record of that identity whose state equals the current one
   (same `effective_at`, same state hash, not late: the record of a `REFRESH` event; fix round 2,
   2026-10-11), and a Track, when given, exactly the one-sample Track the same record produced —
   an older snapshot, a `LATE` or `CONFLICT` record's, or one the caller changed is not the
   source's current state (`SOURCE_STALE`; fix round 1, 2026-10-11); what is exported is always
   the stored current snapshot, so the times and the provenance the report carries are always the
   stored record's own; and its freshness and the ages of its position and of its motion, each
   separately, are below `outbound_max_age_seconds` (`TIME_SKEW`, `SOURCE_STALE`);
5. the export policy resolves exactly this source label set to this peer, in the same synthetic
   layer, outside the ingress realm (`POLICY_DENIED`, `SYNTHETIC_MISMATCH`, `REALM_LOOP`);
6. a family the rule, the configuration and the gateway all allow (`FAMILY_NOT_ALLOWED`);
7. the configured native profile is exactly one the gateway offers (`PROFILE_NOT_READY`);
8. a destination number allocation recorded for (peer, destination realm, source identity)
   (`NUMBER_UNALLOCATED`) — the API carries no allocation call, so an allocation is recorded by an
   operator with the provider's evidence and never computed;
9. room in the export queue (`CAPACITY_EXPORTS`).

Then the adapter, in export mode under an `ExportContext` built from the allocation, the rule and
the source state, produces one report or refuses (`ALTITUDE_DATUM_UNSUPPORTED`,
`VALUE_NOT_REPRESENTABLE`, ...): a refusal is stored with its loss record and audited, and nothing
is sent. Otherwise the job is committed `PENDING` with the fence, its immutable body and its
expiry (now plus `outbound_max_age_seconds`), with the originating CDM objects' digest and the
transformation list in the audit row (REQ093). Immediately before the POST the expiry and the
lease are checked again, and the job is marked in flight durably; then:

- 202: the gateway's state (`ACCEPTED`, `ENCODED`, `SENT`); `DELIVERY_CONFIRMED` is never
  invented;
- 409: `REJECTED` with the gateway's code, and never a second send;
- 422 `REQUEST_EXPIRED`: `EXPIRED`, which can never become `SENT`;
- 429 or 503: back to `PENDING` for a later retry with the same request id and the same body;
- no answer to the POST: `UNKNOWN`, audit code `SEND_OUTCOME_UNKNOWN`, counter
  `unknown_send_outcome`, and no automatic re-send; `reconcile()` adopts the gateway's state, and a
  request the gateway does not know stays `UNKNOWN` until an operator records `resolve-send`.

OUTBOUND SESSION AND SEQUENCE (fix round 1, 2026-10-11): each Egress instance (each bridge start)
opens its own outbound `session_id`, and each committed job takes the next `sequence` of that
session from 0, so no two outbound reports share (session, sequence); a job retried after a 429 or
a 503 keeps its committed body, and with it its sequence. A job the adapter refuses or the store
does not commit takes no sequence.

History export is not offered: `export` takes the current snapshot only (REQ092's runtime half is
not claimed), and the adapter refuses a Track of more than one sample.
"""
from __future__ import annotations

import json
import uuid
from typing import Callable

from synapse_cdm.adapters.link16_gateway import ExportContext, Link16GatewayAdapter, \
    Link16GatewayRefusal
from synapse_cdm.models import Entity, Track

from synapse_link16_bridge import contract, freshness, jsonstrict, limits, policy
from synapse_link16_bridge import faults as _faults
from synapse_link16_bridge.clock import Clock, render_ms
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.gateway.client import (Capacity, Conflict, GatewayClient, GatewayError,
                                                  GatewayProtocolError, NotFound,
                                                  SendOutcomeUnknown, TransportError, Unavailable)
from synapse_link16_bridge.lease import Lease, LeaseLost
from synapse_link16_bridge.observe import Auditor
from synapse_link16_bridge.store import (SQL_ALLOCATION_GET, SQL_ALLOCATION_PUT, SQL_CURRENT_GET,
                                         SQL_IDENTITY_GET, SQL_JOB_GET, SQL_JOB_INFLIGHT,
                                         SQL_JOB_INSERT, SQL_JOB_REBODY, SQL_JOB_STATE,
                                         SQL_JOBS_BY_STATE, SQL_OBSERVATION_STATE,
                                         SQL_OUTBOX_PAYLOAD, Store)
from synapse_link16_bridge.translate import COMPAT_FLAG

SOURCE_FIELD_PROFILE = "sc-link16-bridge/export-1"
FINAL_STATES = ("REJECTED", "SENT", "DELIVERY_CONFIRMED", "EXPIRED", "FAILED", "DENIED")


def _not_projected(entity: Entity) -> bool:
    """The Entity carries the compatibility projection's marker: its source reported a position
    that the projection left out (`POSITION_NOT_PROJECTED_CDM3`)."""
    return any(step.startswith(COMPAT_FLAG) for step in entity.source.transformations)


class ExportResult(dict):
    """`request_id`, `state` and `reason` of one export attempt."""


class Egress:
    def __init__(self, store: Store, config: BridgeConfig, client: GatewayClient | None,
                 auditor: Auditor, lease: Lease, clock: Clock, *,
                 capabilities: contract.Capabilities | None, exports_ready: bool,
                 faults: _faults.CrashPoints = _faults.NO_FAULTS,
                 uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4) -> None:
        self.store = store
        self.config = config
        self.client = client
        self.auditor = auditor
        self.lease = lease
        self.clock = clock
        self.capabilities = capabilities
        self.exports_ready = exports_ready
        self.faults = faults
        self.uuid_factory = uuid_factory
        self.session_id = str(uuid_factory())
        self.next_sequence = 0

    # ------------------------------------------------------------------ the checks

    def _source(self, entity: Entity) -> tuple[str | None, tuple | None]:
        for source_id in entity.source_ids:
            if source_id.system == "Link16Track":
                key = source_id.external_id
                identity = self.store.db.execute(SQL_IDENTITY_GET, (key,)).fetchone()
                current = self.store.db.execute(SQL_CURRENT_GET, (key,)).fetchone()
                if identity is None or current is None or identity[9] != "LIVE" or \
                        current[7] != "ACTIVE":
                    return key, None
                return key, current
        return None, None

    def _published(self, event_key: str) -> bytes | None:
        row = self.store.db.execute(SQL_OUTBOX_PAYLOAD, (event_key,)).fetchone()
        return None if row is None else bytes(row[0])

    def _current_snapshot(self, key: str, entity: Entity, track: Track | None,
                          current: tuple) -> tuple[Entity, Track | None] | None:
        """The objects to export when the Entity (and the Track) are the source identity's
        current state, else None. Compared in canonical JSON: the Entity is the `current` row's
        payload, or (fix round 2, 2026-10-11) the Entity the bridge published at index 0 for a
        record of this identity whose observation has the current `effective_at` and state hash
        and is not late (a `REFRESH` record); a Track is the one the same record published at
        index 1. What is returned is always the stored current snapshot (the `current` row's
        Entity, the current record's Track), so the export carries the stored record's times and
        provenance whichever equal-state record the caller holds."""
        payload = jsonstrict.canonical(entity.model_dump(mode="json"))
        if payload == bytes(current[11]):
            record_id = current[1]
        else:
            record_id = entity.source.original_id
            if not isinstance(record_id, str) or record_id == current[1]:
                return None
            row = self.store.db.execute(SQL_OBSERVATION_STATE, (key, record_id)).fetchone()
            if row is None or row[0] != current[2] or row[1] != current[3] or row[2] != 0:
                return None
            if self._published(f"{record_id}:0") != payload:
                return None
        stored_entity = Entity.model_validate_json(bytes(current[11]))
        if track is None:
            return stored_entity, None
        if self._published(f"{record_id}:1") != jsonstrict.canonical(track.model_dump(mode="json")):
            return None
        stored_track = self._published(f"{current[1]}:1")
        if stored_track is None:
            return None
        return stored_entity, Track.model_validate_json(stored_track)

    def _permission(self) -> str | None:
        config = self.config
        if config.mode != "bidirectional" or config.realm_kind == "replay":
            return "POLICY_DENIED"
        if not self.exports_ready or self.capabilities is None or self.client is None:
            return "PROFILE_NOT_READY"
        return None

    def check(self, entity: Entity, track: Track | None, peer_id: str):
        """The ordered checks. Returns (reason, context parts) with reason None when allowed."""
        config, store = self.config, self.store
        early = self._permission()
        if early is not None:
            return early, None
        if _not_projected(entity):
            return "PROFILE_NOT_READY", None
        try:
            with store.transaction():
                pass
        except LeaseLost:
            return "LEASE_LOST", None
        channel = store.channel()
        if channel["state"] != "NORMAL":
            return "CHANNEL_INCOMPLETE", None
        key, current = self._source(entity)
        if current is None:
            return "POLICY_DENIED", None
        snapshot = self._current_snapshot(key, entity, track, current)
        if snapshot is None:
            return "SOURCE_STALE", None
        if _not_projected(snapshot[0]):
            return "PROFILE_NOT_READY", None
        now = store.now()
        status, motion = freshness.of_current(current, now, config.freshness_seconds)
        if status == freshness.TIME_SKEW or motion == freshness.TIME_SKEW:
            return "TIME_SKEW", None
        if status != freshness.ACTIVE or motion not in (None, freshness.ACTIVE):
            return "SOURCE_STALE", None
        max_age = config.outbound_max_age_seconds * 1000
        pos_at, kin_at = current[4], current[5]
        if now - (pos_at if pos_at is not None else current[2]) >= max_age:
            return "SOURCE_STALE", None
        if kin_at is not None and now - kin_at >= max_age:
            return "SOURCE_STALE", None
        match = policy.resolve(config, peer_id, entity.source.synthetic)
        if match.rule is None:
            return match.reason, None
        rule = match.rule
        family = policy.family(rule, config, self.capabilities.transmit_families)
        if family is None:
            return "FAMILY_NOT_ALLOWED", None
        if config.native_profile not in self.capabilities.native_profiles:
            return "PROFILE_NOT_READY", None
        allocation = store.db.execute(SQL_ALLOCATION_GET, (peer_id, rule.destination.realm,
                                                           key)).fetchone()
        if allocation is None:
            return "NUMBER_UNALLOCATED", None
        if limits.exports_full(limits.usage(store), config.limits):
            return "CAPACITY_EXPORTS", None
        return None, (key, current, rule, family, json.loads(allocation[0]), snapshot)

    # ------------------------------------------------------------------ export

    def export(self, entity: Entity, track: Track | None, *, peer_id: str,
               request_id: str | None = None) -> ExportResult:
        objects = [entity] + ([track] if track is not None else [])
        digest = jsonstrict.sha256_hex(jsonstrict.canonical(
            [o.model_dump(mode="json") for o in objects]))
        request_id = request_id or str(self.uuid_factory())
        known = self._job(request_id)
        if known is not None:                   # a request id is immutable: never a second job
            return ExportResult(request_id=request_id, state=known[7], reason=known[8])
        transformations = tuple(entity.source.transformations)
        reason, parts = self.check(entity, track, peer_id)
        if reason is not None:
            return self._deny(request_id, peer_id, reason, digest, transformations)
        key, current, rule, family, allocation, (entity, track) = parts
        # the stored current snapshot is what is translated; its digest is the audit's
        objects = [entity] + ([track] if track is not None else [])
        digest = jsonstrict.sha256_hex(jsonstrict.canonical(
            [o.model_dump(mode="json") for o in objects]))
        transformations = tuple(entity.source.transformations)
        store, config = self.store, self.config
        now = store.now()
        try:
            context = ExportContext(
                record_id=str(self.uuid_factory()), gateway_id=config.gateway_id,
                session_id=self.session_id, sequence=str(self.next_sequence),
                received_at=render_ms(now), time_basis="SOURCE",
                time_evidence="the source state's effective time, exported by the runtime",
                tenant=allocation["tenant"], realm=allocation["realm"],
                synthetic=allocation["synthetic"], origin_scope=allocation["origin_scope"],
                track_number=allocation["track_number"], incarnation=allocation["incarnation"],
                reporter=config.consumer_id, message_family=family,
                native_profile=config.native_profile, domain=current[6],
                security_context=rule.destination.security_context,
                source_field_profile=SOURCE_FIELD_PROFILE, source_fields={},
                provenance={"source_entity_id": str(entity.entity_id),
                            "source_record_id": current[1],
                            "policy_revision": rule.policy_revision},
                position_observed_at=None if entity.position is None or current[4] is None
                else render_ms(current[4]),
                kinematics_observed_at=None if entity.kinematics is None or current[5] is None
                else render_ms(current[5]),
                vertical_forms=rule.destination.vertical_forms,
                vertical_required=rule.destination.vertical_required)
        except (ValueError, TypeError):
            return self._deny(request_id, peer_id, "NUMBER_UNALLOCATED", digest, transformations)
        adapter = Link16GatewayAdapter(self.clock, synthetic=config.synthetic, mode="export",
                                       export_context=context)
        try:
            report = adapter.from_cdm(objects)
        except Link16GatewayRefusal as refusal:
            return self._deny(request_id, peer_id, refusal.code, digest, transformations,
                              losses=list(refusal.losses), path=refusal.path)
        expires_at = now + int(config.outbound_max_age_seconds * 1000)
        body = jsonstrict.canonical({"request_id": request_id, "peer_id": peer_id,
                                     "expires_at": render_ms(expires_at),
                                     "policy_revision": rule.policy_revision, "report": report})
        losses = report["extensions"]["sc-link16-export/1"]["losses"]
        try:
            with store.transaction() as db:
                db.execute(SQL_JOB_INSERT, (
                    request_id, body, jsonstrict.sha256_hex(body), peer_id, key, expires_at,
                    rule.policy_revision, "PENDING", None, store.fence, now, now,
                    json.dumps(losses), digest,
                    jsonstrict.canonical(entity.model_dump(mode="json")),
                    None if track is None else jsonstrict.canonical(track.model_dump(mode="json"))))
                self.auditor.record("export_queued", subject_id=request_id,
                                    policy_result="ALLOWED", transformations=transformations,
                                    detail="cdm_sha256=" + digest)
        except LeaseLost:
            return ExportResult(request_id=request_id, state="DENIED", reason="LEASE_LOST")
        self.next_sequence += 1
        self.faults.hit("egress.after_job_commit_before_send")
        return self.send(request_id)

    def _deny(self, request_id: str, peer_id: str, reason: str, digest: str,
              transformations: tuple, *, losses: list | None = None,
              path: str | None = None) -> ExportResult:
        store = self.store
        try:
            with store.transaction() as db:
                now = store.now()
                db.execute(SQL_JOB_INSERT, (request_id, None, None, peer_id, None, None, None,
                                            "DENIED", reason, store.fence, now, now,
                                            json.dumps(losses or []), digest, None, None))
                store.counter_add("export_denied")
                self.auditor.record("export_denied", subject_id=request_id, code=reason,
                                    policy_result="DENIED", transformations=transformations,
                                    detail="cdm_sha256=" + digest)
        except LeaseLost:
            pass
        return ExportResult(request_id=request_id, state="DENIED", reason=reason,
                            losses=losses or [], path=path)

    # ------------------------------------------------------------------ sending

    def _job(self, request_id: str) -> tuple | None:
        return self.store.db.execute(SQL_JOB_GET, (request_id,)).fetchone()

    def _set(self, request_id: str, state: str, reason: str | None, *, audit: str,
             code: str | None = None) -> None:
        store = self.store
        with store.transaction() as db:
            db.execute(SQL_JOB_STATE, (state, reason, store.now(), store.fence, request_id))
            self.auditor.record(audit, subject_id=request_id, code=code,
                                policy_result=state)

    def send(self, request_id: str) -> ExportResult:
        """Send one PENDING job once, re-checking expiry and the lease immediately before."""
        store = self.store
        job = self._job(request_id)
        if job is None:
            raise KeyError("no such export job")
        state = job[7]
        if state != "PENDING":
            return ExportResult(request_id=request_id, state=state, reason=job[8])
        try:
            if store.now() >= job[5]:
                self._set(request_id, "EXPIRED", "REQUEST_EXPIRED", audit="export_expired",
                          code="REQUEST_EXPIRED")
                return ExportResult(request_id=request_id, state="EXPIRED",
                                    reason="REQUEST_EXPIRED")
            with store.transaction() as db:
                db.execute(SQL_JOB_INFLIGHT, (store.now(), store.fence, request_id))
        except LeaseLost:
            return ExportResult(request_id=request_id, state="PENDING", reason="LEASE_LOST")
        try:
            status = self.client.transmit(bytes(job[1]))
        except SendOutcomeUnknown:
            self.faults.hit("egress.after_send_before_record")
            self._unknown(request_id)
            return ExportResult(request_id=request_id, state="UNKNOWN",
                                reason="SEND_OUTCOME_UNKNOWN")
        except Conflict as error:
            self._set(request_id, "REJECTED", error.code, audit="transmission", code=error.code)
            return ExportResult(request_id=request_id, state="REJECTED", reason=error.code)
        except (Capacity, Unavailable, TransportError) as error:
            code = getattr(error, "code", "TRANSPORT")
            self._set(request_id, "PENDING", code, audit="transmission_retry", code=code)
            return ExportResult(request_id=request_id, state="PENDING", reason=code)
        except GatewayError as error:
            state = "EXPIRED" if error.code == "REQUEST_EXPIRED" else "REJECTED"
            self._set(request_id, state, error.code, audit="transmission", code=error.code)
            return ExportResult(request_id=request_id, state=state, reason=error.code)
        except GatewayProtocolError:
            self.faults.hit("egress.after_send_before_record")
            self._unknown(request_id)
            return ExportResult(request_id=request_id, state="UNKNOWN",
                                reason="SEND_OUTCOME_UNKNOWN")
        self.faults.hit("egress.after_send_before_record")
        state = status["state"]
        with store.transaction() as db:
            db.execute(SQL_JOB_STATE, (state, status["reason"], store.now(), store.fence,
                                       request_id))
            if state in ("ENCODED", "SENT", "DELIVERY_CONFIRMED"):
                store.counter_add("encoded")
            if state in ("SENT", "DELIVERY_CONFIRMED"):
                store.counter_add("sent")
            self.auditor.record("transmission", subject_id=request_id, policy_result=state)
        return ExportResult(request_id=request_id, state=state, reason=status["reason"])

    def _unknown(self, request_id: str) -> None:
        store = self.store
        with store.transaction() as db:
            db.execute(SQL_JOB_STATE, ("UNKNOWN", "SEND_OUTCOME_UNKNOWN", store.now(),
                                       store.fence, request_id))
            store.counter_add("unknown_send_outcome")
            self.auditor.record("transmission", subject_id=request_id,
                                code="SEND_OUTCOME_UNKNOWN", policy_result="UNKNOWN")

    def reconcile(self) -> list[tuple[str, str]]:
        """Ask the gateway for the state of every job whose outcome is open; adopt it."""
        changes = []
        for state in ("UNKNOWN", "ACCEPTED", "ENCODED"):
            for (request_id,) in self.store.db.execute(SQL_JOBS_BY_STATE, (state,)).fetchall():
                try:
                    status = self.client.transmission_status(request_id)
                except NotFound:
                    continue
                except (GatewayError, TransportError, GatewayProtocolError):
                    continue
                if status["state"] != state:
                    self._set(request_id, status["state"], status["reason"],
                              audit="reconciled")
                    changes.append((request_id, status["state"]))
        return changes

    def revalidate(self) -> list[ExportResult]:
        """Jobs of an older fence: checked again, then sent with their own request id and body
        (the gateway's idempotency makes a second POST of one already received harmless)."""
        results = []
        for (request_id,) in self.store.db.execute(SQL_JOBS_BY_STATE, ("REVALIDATE",)).fetchall():
            job = self._job(request_id)
            entity = Entity.model_validate_json(job[14])
            track = None if job[15] is None else Track.model_validate_json(job[15])
            if self.store.now() >= job[5]:
                self._set(request_id, "EXPIRED", "REQUEST_EXPIRED", audit="export_expired",
                          code="REQUEST_EXPIRED")
                results.append(ExportResult(request_id=request_id, state="EXPIRED",
                                            reason="REQUEST_EXPIRED"))
                continue
            reason, _parts = self.check(entity, track, job[3])
            if reason is not None:
                self._set(request_id, "DENIED", reason, audit="export_denied", code=reason)
                with self.store.transaction():
                    self.store.counter_add("export_denied")
                results.append(ExportResult(request_id=request_id, state="DENIED",
                                            reason=reason))
                continue
            with self.store.transaction() as db:
                db.execute(SQL_JOB_REBODY, (self.store.now(), self.store.fence, request_id))
                self.auditor.record("export_revalidated", subject_id=request_id,
                                    policy_result="ALLOWED")
            results.append(self.send(request_id))
        return results

    def resolve_send(self, request_id: str, decision: str, evidence: str) -> str:
        job = self._job(request_id)
        if job is None or job[7] != "UNKNOWN" or decision != "abandon":
            raise ValueError("resolve-send applies to an UNKNOWN job with --decision abandon")
        with self.store.transaction() as db:
            db.execute(SQL_JOB_STATE, ("FAILED", "ABANDONED_BY_OPERATOR", self.store.now(),
                                       self.store.fence, request_id))
            self.auditor.record("resolve_send", subject_id=request_id, policy_result="FAILED",
                                detail=evidence)
        return "FAILED"

    def allocate(self, peer_id: str, realm: str, source_key: str, dest_tuple: dict,
                 evidence: str) -> None:
        """Record a provider's destination allocation (REQ074, REQ096) with operator evidence."""
        expected = {"tenant", "realm", "synthetic", "origin_scope", "track_number", "incarnation"}
        if type(dest_tuple) is not dict or set(dest_tuple) != expected:
            raise ValueError("the destination tuple holds exactly the six identity keys")
        contract.identifier(dest_tuple["tenant"], "tenant")
        contract.identifier(dest_tuple["realm"], "realm")
        contract.identifier(dest_tuple["origin_scope"], "origin_scope")
        contract.decimal_u64(dest_tuple["incarnation"], "incarnation")
        if type(dest_tuple["synthetic"]) is not bool or type(dest_tuple["track_number"]) is not \
                str or not 1 <= len(dest_tuple["track_number"]) <= 64:
            raise ValueError("the destination tuple's synthetic or track_number is malformed")
        if dest_tuple["realm"] != realm:
            raise ValueError("the destination tuple's realm is the allocation's realm")
        store = self.store
        with store.transaction() as db:
            db.execute(SQL_ALLOCATION_PUT, (peer_id, realm, source_key, json.dumps(dest_tuple),
                                            self.config.number_allocations_ref or "operator",
                                            evidence[:1024], store.now(), store.fence))
            self.auditor.record("allocation", subject_id=peer_id, detail=evidence)

