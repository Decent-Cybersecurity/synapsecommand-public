"""The bridge: startup in REQ140's order, the ingest loop, health, egress and operator records.

STARTUP (REQ140), in this order, each step recorded in `startup_steps`:
parse the configuration strictly (a `BridgeConfig` exists only if it parsed); verify versions and
policies; open the durable store; acquire the exclusive channel-writer lease; query the gateway's
capabilities; verify the gateway identity and the native profile evidence; negotiate the schema
with the sink; restore the cursor and the identity state; start ingest; then enable the allowed
exports. A gateway that is not the configured one, a lease another instance holds, or a failed
negotiation is `BLOCKED` (nothing ingested); a bidirectional channel whose native profile the
gateway does not offer, or a live channel (whose native provider is BLOCKED_EXTERNAL_EVIDENCE),
is `DEGRADED_INGEST_ONLY` — never an implicitly ready transmitter.

THE LOOP (`run_once`): renew the lease; skip fetching while the channel is STOPPED, awaiting
resynchronisation or at the report-queue cap; fetch one batch after the committed cursor; ingest it
in one transaction; acknowledge the gateway; evaluate freshness; deliver the outbox to the sink. A
429, a 503 or a lost connection waits for REQ114's backoff and records nothing as a gap; a 410
marks the channel RESYNC_REQUIRED (exports blocked) until an operator records `resync`; a 401 or
403 stops the channel. After a restart with an unacknowledged commit, the first fetch asks again
from the last acknowledged cursor, so the gateway's redelivery is deduplicated rather than assumed
away.

A lost lease at any fenced step of a pass — the record of the acknowledgement, a refusal's
audit-only transaction, the warning counter — ends the pass `BLOCKED` with `LEASE_LOST`; any
other exception the pass did not expect ends it `BLOCKED` with `INTERNAL_ERROR` and an audit row
naming only the exception's type, so no traceback ever leaves the loop (A2F, 2026-10-11). The
channel's `OVERLOADED` state and its audit rows change only on a transition: the report-queue cap
holds it until the queue is below the cap again, and the identity cap until a batch is consumed
(A2F, 2026-10-11).

A GAP NOTHING ERASES (REQ106; A2F fix round 1, 2026-10-11): a gap or loss (`GAP`, `STREAM_GAP`,
`CURSOR_EXPIRED`) is held in the channel's `incomplete` column until an operator records `recover`
on the INCOMPLETE channel. A cap reached while the channel is INCOMPLETE still holds (no fetch, or
the batch not consumed) but never replaces INCOMPLETE: OVERLOADED is entered only from NORMAL.
Every other way back — a cap that clears, `resync-identities`, a restart under a new configuration
revision — lands on INCOMPLETE, not NORMAL, while a gap is unrecovered; and `recover` on a channel
that is only degraded clears the flag and leaves a STOPPED, RESYNC_REQUIRED or OVERLOADED state as
it is.

HEALTH (REQ151): `ready` is false when the provider is unready, negotiation failed, the last
durable commit failed, the channel is INCOMPLETE, awaiting resynchronisation or STOPPED, or the
sink does not take the outbox's head (`SINK_FAILED`, logged and audited when the sink starts and
when it stops failing; A2F, 2026-10-11); the reasons are fixed codes, and health carries no
position, identifier or label.

OPERATOR RECORDS: `recover`, `resync`, `resync_identities`, `resolve_reuse`, `resolve_send` and
`allocate` each change state only with an audit row holding the operator's evidence text (at most
1024 characters).
"""
from __future__ import annotations

import os
import pathlib
import random
import sqlite3
import time
import uuid
from typing import Any, Callable, Mapping

from synapse_cdm.adapter import REGISTRY, discover
from synapse_cdm.enums import PositionSource
from synapse_cdm.models import Entity, Track
from synapse_cdm import times
from synapse_cdm.normative_binding import BLOCKED_STATUS, NormativeBindingBlocked
from synapse_cdm.version import SCHEMA_VERSION

from synapse_link16_bridge import (faults as _faults, freshness, identity, jsonstrict, limits,
                                   native, negotiate)
from synapse_link16_bridge.backoff import Backoff
from synapse_link16_bridge.clock import Clock, Sleeper, parse_ms, real_sleeper
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.contract import PROFILE
from synapse_link16_bridge.egress import Egress, ExportResult
from synapse_link16_bridge.gateway.client import (AuthFailure, CursorExpired, GatewayClient,
                                                  GatewayError, GatewayProtocolError,
                                                  SendOutcomeUnknown, TransportError)
from synapse_link16_bridge.ingest import (ChannelStop, Ingestor, StructuralRefusal, dispatch,
                                          evaluate_freshness)
from synapse_link16_bridge.lease import Lease, LeaseHeld, LeaseLost
from synapse_link16_bridge.observe import Auditor, Histograms, log_event
from synapse_link16_bridge.store import (CHANNEL, SQL_CHANNEL_ACKED, SQL_CHANNEL_EXPIRED,
                                         SQL_CHANNEL_RECOVER, SQL_CHANNEL_RESYNC,
                                         SQL_CHANNEL_RETRY, SQL_CHANNEL_SETTLE,
                                         SQL_CHANNEL_STATE, SQL_CHANNEL_STOP, SQL_CURRENT_ALL,
                                         SQL_IDENTITY_COUNT_LIVE, SQL_IDENTITY_EPOCH_KEEP,
                                         SQL_IDENTITY_EPOCH_RESET, SQL_IDENTITY_GET,
                                         SQL_IDENTITY_SCOPE, SQL_IDENTITY_STATUS,
                                         SQL_INGEST_SET, SQL_QUARANTINE_RESOLVE,
                                         SQL_QUARANTINE_REUSE, SQL_RAW_INSERT, Store)
from synapse_link16_bridge.translate import ACCEPT, Translator

STEPS = ("parse_configuration", "verify_versions_and_policies", "open_store",
         "acquire_lease", "query_capabilities", "verify_gateway_identity_and_native_profile",
         "negotiate_schema", "restore_state", "start_ingest", "enable_exports")
READY, DEGRADED, BLOCKED = "READY", "DEGRADED_INGEST_ONLY", "BLOCKED"


class OperatorRefusal(ValueError):
    """An operator command that does not apply to the channel's state."""


class MemorySink:
    """A sink that keeps the latest payload per event key (an upsert) and every delivery."""

    def __init__(self, accepts: tuple[str, ...] = (SCHEMA_VERSION,)) -> None:
        self.accepts = tuple(accepts)
        self.events: dict[str, tuple[str, bytes, tuple[str, ...]]] = {}
        self.deliveries: list[str] = []
        self.fail = False

    def deliver(self, event_key: str, kind: str, payload: bytes, flags: tuple[str, ...]) -> None:
        if self.fail:
            raise RuntimeError("sink unavailable")
        self.deliveries.append(event_key)
        self.events[event_key] = (kind, payload, flags)


class JsonlSink:
    """A directory sink: one JSON file per event key (an atomic upsert by key). The line is the
    canonical JSON object `{"event_key", "flags", "kind", "payload"}` built around the canonical
    octets the outbox hands over, which are written as they are and never parsed again (A2F,
    2026-10-11: re-parsing them under the report's depth bound refused a legal depth-32 report's
    Entity)."""

    def __init__(self, directory: str | pathlib.Path, accepts: tuple[str, ...]) -> None:
        self.directory = pathlib.Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.accepts = tuple(accepts)

    def deliver(self, event_key: str, kind: str, payload: bytes, flags: tuple[str, ...]) -> None:
        name = jsonstrict.sha256_hex(event_key.encode("utf-8")) + ".json"
        line = (b'{"event_key":' + jsonstrict.canonical(event_key) +
                b',"flags":' + jsonstrict.canonical(list(flags)) +
                b',"kind":' + jsonstrict.canonical(kind) +
                b',"payload":' + bytes(payload) + b"}")
        temporary = self.directory / (name + ".partial")
        temporary.write_bytes(line + b"\n")
        os.replace(temporary, self.directory / name)


def binding_of(config: BridgeConfig) -> str:
    return jsonstrict.canonical([config.gateway_id, config.tenant, config.realm,
                                 config.synthetic, config.security_context,
                                 config.consumer_id]).decode("utf-8")


class Bridge:
    def __init__(self, config: BridgeConfig, *, sink: Any, client: GatewayClient | None = None,
                 clock: Clock | None = None, sleeper: Sleeper = real_sleeper,
                 rng: random.Random | None = None,
                 faults: _faults.CrashPoints = _faults.NO_FAULTS, holder: str | None = None,
                 uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
                 native_provider: Any = None, environ: Mapping[str, str] | None = None,
                 store_factory: Callable[..., Store] = Store,
                 installed_schema: str = SCHEMA_VERSION,
                 monotonic: Callable[[], float] = time.perf_counter) -> None:
        if not isinstance(config, BridgeConfig):
            raise TypeError("a Bridge is built from a parsed BridgeConfig only")
        self.config = config
        self.sink = sink
        self.client = client
        self.clock = clock or times.utc_now
        self.sleeper = sleeper
        self.rng = rng or random.Random()
        self.faults = faults
        self.holder = holder or str(uuid_factory())
        self.uuid_factory = uuid_factory
        self.native_provider = native_provider
        self.environ = environ
        self.store_factory = store_factory
        self.installed_schema = installed_schema
        self.monotonic = monotonic
        self.backoff = Backoff(self.clock, self.rng)
        self.histograms = Histograms()
        self.sink_failed: str | None = None     # the outbox head the sink did not take
        self.startup_steps: list[str] = []
        self.status = BLOCKED
        self.blocked_reasons: list[str] = []
        self.provider_ready = False
        self.projection: negotiate.Projection | None = None
        self.capabilities = None
        self.store: Store | None = None
        self.lease: Lease | None = None
        self.auditor: Auditor | None = None
        self.ingestor: Ingestor | None = None
        self.egress: Egress | None = None
        self.exports_enabled = False
        self.native_status = BLOCKED_STATUS
        self._refetch_from: tuple[bool, str | None] = (False, None)
        self._waited = False
        self._warned: set[str] = set()

    # ------------------------------------------------------------------ startup

    def _step(self, name: str) -> None:
        self.startup_steps.append(name)

    def _block(self, reason: str) -> str:
        self.status = BLOCKED
        if reason not in self.blocked_reasons:
            self.blocked_reasons.append(reason)
        log_event("startup blocked", reason)
        return self.status

    def start(self) -> str:
        config = self.config
        self._step("parse_configuration")
        self._step("verify_versions_and_policies")
        discover()
        if "link16_gateway" not in REGISTRY or not hasattr(PositionSource, "SENSOR") or \
                not hasattr(PositionSource, "UNKNOWN"):
            return self._block("SCHEMA_NEGOTIATION_FAILED")
        self._step("open_store")
        self.store = self.store_factory(config.store_path, self.clock, self.faults)
        self.store.bind(binding_of(config))
        self.auditor = Auditor(self.store, config.config_revision, PROFILE, self.uuid_factory)
        self._step("acquire_lease")
        self.lease = Lease(self.store, self.holder, config.lease_ttl_seconds)
        try:
            self.lease.acquire()
        except LeaseHeld:
            return self._block("LEASE_LOST")
        self._step("query_capabilities")
        try:
            self.capabilities = self.client.capabilities()
            self.provider_ready = True
        except (GatewayError, TransportError, GatewayProtocolError):
            self.provider_ready = False
            return self._block("PROVIDER_UNAVAILABLE")
        self._step("verify_gateway_identity_and_native_profile")
        if self.capabilities.gateway_id != config.gateway_id:
            return self._block("GATEWAY_IDENTITY_MISMATCH")
        exports_ready = config.mode == "bidirectional" and \
            config.native_profile in self.capabilities.native_profiles
        if not config.synthetic:
            try:
                native.activate_native(self.native_provider, config.native_profile,
                                       self.environ)
                self.native_status = "ACTIVE"
            except (NormativeBindingBlocked, native.NativeProfileIncomplete) as refusal:
                self.native_status = getattr(refusal, "status", native.INCOMPLETE)
                exports_ready = False
        self._step("negotiate_schema")
        self.projection = negotiate.choose(tuple(self.sink.accepts), self.installed_schema)
        if self.projection is negotiate.Projection.NEGOTIATION_FAILED:
            return self._block("SCHEMA_NEGOTIATION_FAILED")
        self._step("restore_state")
        channel = self.store.channel()
        if channel["state"] == "STOPPED" and channel["stopped_revision"] != config.config_revision:
            with self.store.transaction() as db:
                db.execute(SQL_CHANNEL_SETTLE, (self.store.fence, CHANNEL))
                self.auditor.record("channel_restart", code="CONFIG_REVISION_RESTART",
                                    detail="new configuration revision")
        if channel["committed_any"] and channel["acked_cursor"] != channel["cursor"]:
            self._refetch_from = (True, channel["acked_cursor"])
        translator = Translator(config, self.projection, self.clock,
                                self.capabilities.receive_families)
        self.ingestor = Ingestor(self.store, config, translator, self.auditor,
                                 faults=self.faults, histograms=self.histograms,
                                 monotonic=self.monotonic)
        self._step("start_ingest")
        self._step("enable_exports")
        self.exports_enabled = exports_ready
        self.egress = Egress(self.store, config, self.client, self.auditor, self.lease,
                             self.clock, capabilities=self.capabilities,
                             exports_ready=exports_ready, faults=self.faults,
                             uuid_factory=self.uuid_factory)
        if config.mode == "bidirectional" and not exports_ready:
            self.status = DEGRADED
        else:
            self.status = READY
        return self.status

    def open_for_operator(self) -> None:
        """Open the store and take the lease for an operator record, without a gateway: the
        translator reads the configured families and the configured schema versions."""
        config = self.config
        self.store = self.store_factory(config.store_path, self.clock, self.faults)
        self.store.bind(binding_of(config))
        self.auditor = Auditor(self.store, config.config_revision, PROFILE, self.uuid_factory)
        self.lease = Lease(self.store, self.holder, config.lease_ttl_seconds)
        try:
            self.lease.acquire()
        except LeaseHeld:
            raise OperatorRefusal("the channel-writer lease is held by another instance") \
                from None
        self.projection = negotiate.choose(tuple(self.sink.accepts), self.installed_schema)
        if self.projection is negotiate.Projection.NEGOTIATION_FAILED:
            raise OperatorRefusal("no CDM schema version is shared with the sink")
        translator = Translator(config, self.projection, self.clock, config.receive_families)
        self.ingestor = Ingestor(self.store, config, translator, self.auditor,
                                 faults=self.faults, histograms=self.histograms,
                                 monotonic=self.monotonic)
        self.egress = Egress(self.store, config, None, self.auditor, self.lease, self.clock,
                             capabilities=None, exports_ready=False, faults=self.faults,
                             uuid_factory=self.uuid_factory)

    def read_evidence(self, batch_sha256: str, evidence: str) -> bytes | None:
        """The raw batch octets kept as evidence, read with an audit row. The CLI's `evidence`
        command is the only caller (REQ151)."""
        self._operator("evidence", evidence)
        octets = self.store.read_raw_evidence(batch_sha256)
        with self.store.transaction():
            self.auditor.record("evidence_read", subject_id=batch_sha256, detail=evidence)
        return octets

    def close(self) -> None:
        """Give the lease up when it can be written, and always close the store."""
        if self.store is None:
            return
        try:
            if self.lease is not None:
                self.lease.release()
        except (LeaseLost, sqlite3.Error):
            pass
        finally:
            self.store.close()
            self.store = None

    # ------------------------------------------------------------------ the loop

    def _audit_only(self, change: str, params: tuple, kind: str, code: str, *,
                    subject: str | None = None, raw: tuple | None = None) -> None:
        """A separate transaction that records a refusal (and its raw evidence) and one channel
        change: `stop`, `state`, `settle`, `expired` or `retry`."""
        with self.store.transaction() as db:
            if raw is not None:
                db.execute(SQL_RAW_INSERT, raw)
            if change == "stop":
                db.execute(SQL_CHANNEL_STOP, params)
            elif change == "state":
                db.execute(SQL_CHANNEL_STATE, params)
            elif change == "settle":
                db.execute(SQL_CHANNEL_SETTLE, params)
            elif change == "expired":
                db.execute(SQL_CHANNEL_EXPIRED, params)
            elif change == "retry":
                db.execute(SQL_CHANNEL_RETRY, params)
            else:
                raise ValueError("unknown channel change")
            self.auditor.record(kind, subject_id=subject, code=code,
                                raw_ref=None if raw is None else raw[0])
        log_event("channel refusal recorded", code)

    def _stop(self, code: str, *, subject: str | None = None, raw: tuple | None = None) -> None:
        self._audit_only("stop", (code, self.config.config_revision, self.store.fence,
                                            CHANNEL), "channel_stop", code, subject=subject,
                         raw=raw)

    def run_once(self) -> dict:
        """One pass. Returns what happened, for the caller and the tests. A durable commit that
        fails anywhere in the pass ends it with nothing acknowledged (REQ151); a lease lost at any
        fenced step ends it `BLOCKED` (`LEASE_LOST`); any other exception ends it `BLOCKED`
        (`INTERNAL_ERROR`, audited), never a traceback out of the loop (A2F, 2026-10-11)."""
        try:
            return self._run_once()
        except sqlite3.OperationalError:
            self._rollback()
            log_event("durable commit failed", "DURABLE_COMMIT_FAILED")
            return {"fetched": False, "reason": "DURABLE_COMMIT_FAILED"}
        except LeaseLost:
            self._rollback()
            self._block("LEASE_LOST")
            return {"fetched": False, "reason": "LEASE_LOST"}
        except Exception as error:      # noqa: BLE001 - the last resort: the loop never raises
            self._rollback()
            self._internal_error(error)
            return {"fetched": False, "reason": "INTERNAL_ERROR"}

    def _rollback(self) -> None:
        if self.store is not None and self.store.db.in_transaction:
            self.store.db.rollback()

    def _internal_error(self, error: Exception) -> None:
        """BLOCKED with `INTERNAL_ERROR`, and an audit row that names the exception's type only
        (its text may quote a payload), written when the store and the lease still allow it."""
        log_event("unexpected failure", "INTERNAL_ERROR")
        try:
            with self.store.transaction():
                self.auditor.record("internal_error", code="INTERNAL_ERROR",
                                    policy_result="BLOCKED", detail=type(error).__name__)
        except Exception:               # noqa: BLE001 - the block below stands without the row
            self._rollback()
        self._block("INTERNAL_ERROR")

    def _run_once(self) -> dict:
        if self.status == BLOCKED or self.ingestor is None:
            return {"fetched": False, "reason": "BLOCKED"}
        store, config = self.store, self.config
        try:
            self.lease.renew()
        except LeaseLost:
            try:                                # expired and free: take it again, new fence
                self.lease.acquire()
                log_event("lease re-acquired", "LEASE_LOST")
            except LeaseHeld:
                self._block("LEASE_LOST")
                return {"fetched": False, "reason": "LEASE_LOST"}
        channel = store.channel()
        if channel["state"] in ("STOPPED", "RESYNC_REQUIRED"):
            self._housekeeping()
            return {"fetched": False, "reason": channel["state"]}
        used = limits.usage(store)
        self._count_warnings(used)
        stopping = [code for code in limits.full(used, config.limits)
                    if code in limits.STOPS_FETCHING]
        if stopping:
            self._overloaded(channel, stopping[0])
            self._housekeeping()
            return {"fetched": False, "reason": stopping[0]}
        if channel["state"] == "OVERLOADED" and channel["state_reason"] != "CAPACITY_IDENTITIES":
            self._cleared(channel)          # the queue is below its cap again
        refetch, acked = self._refetch_from
        after = acked if refetch else channel["cursor"]
        try:
            octets = self.client.reports(after, config.limits["fetch_limit"])
        except CursorExpired as expired:
            self._audit_only("expired", (expired.earliest_cursor, store.fence,
                                                   CHANNEL), "cursor_expired", "CURSOR_EXPIRED")
            return {"fetched": False, "reason": "CURSOR_EXPIRED"}
        except AuthFailure as failure:
            self._stop(failure.code)
            return {"fetched": False, "reason": failure.code}
        except GatewayError as error:
            if error.retryable:
                self._backoff_wait()
                return {"fetched": False, "reason": error.code}
            self._stop(error.code)
            return {"fetched": False, "reason": error.code}
        except (TransportError, GatewayProtocolError):
            self.provider_ready = False
            self._backoff_wait()
            return {"fetched": False, "reason": "TRANSPORT"}
        self.provider_ready = True
        self.backoff.success()
        cursor_before = after
        try:
            outcome = self.ingestor.process(octets, cursor_before)
        except StructuralRefusal as refusal:
            return self._structural(refusal, octets, cursor_before)
        except ChannelStop as stop:
            self._stop(stop.code, subject=stop.record_key,
                       raw=(jsonstrict.sha256_hex(octets), store.now(), cursor_before,
                            len(octets), octets, store.fence))
            return {"fetched": True, "reason": stop.code}
        except identity.CapacityStop as capacity:
            self._overloaded(store.channel(), capacity.code)
            return {"fetched": True, "reason": capacity.code}
        except sqlite3.OperationalError:
            if store.db.in_transaction:
                store.db.rollback()
            log_event("durable commit failed", "DURABLE_COMMIT_FAILED")
            return {"fetched": True, "reason": "DURABLE_COMMIT_FAILED"}
        except LeaseLost:
            self._block("LEASE_LOST")
            return {"fetched": True, "reason": "LEASE_LOST"}
        self._refetch_from = (False, None)
        after_commit = store.channel()
        if after_commit["state"] == "OVERLOADED" and \
                after_commit["state_reason"] == "CAPACITY_IDENTITIES":
            self._cleared(after_commit)     # a batch was consumed: the identity cap let it in
        self.faults.hit("ingest.after_commit_before_ack")
        acked = False
        try:
            self.client.ack(config.consumer_id, outcome.next_cursor)
            acked = True
        except (GatewayError, TransportError, GatewayProtocolError,
                SendOutcomeUnknown) as failure:
            # The acknowledgement is idempotent and the batch is committed: an ack refused, or
            # one whose answer never arrived, is repeated by the next pass, which reads after
            # the committed cursor and acknowledges that batch's `next_cursor`.
            log_event("acknowledgement not confirmed",
                      getattr(failure, "code", "SEND_OUTCOME_UNKNOWN"))
        if acked:
            try:
                with store.transaction() as db:
                    db.execute(SQL_CHANNEL_ACKED, (outcome.next_cursor, store.fence, CHANNEL))
            except LeaseLost:
                # the batch is committed and the gateway acknowledged; the acknowledgement is not
                # recorded under a lease this instance no longer holds (A2F, 2026-10-11)
                self._block("LEASE_LOST")
                return {"fetched": True, "reason": "LEASE_LOST", "acked": True,
                        "has_more": outcome.has_more, "dispositions": outcome.dispositions,
                        "batch_sha256": outcome.batch_sha256}
            self.faults.hit("ingest.after_ack")
        self._housekeeping()
        return {"fetched": True, "reason": None, "acked": acked, "has_more": outcome.has_more,
                "dispositions": outcome.dispositions, "batch_sha256": outcome.batch_sha256}

    def _overloaded(self, channel: dict, code: str) -> None:
        """The channel held by cap `code`: written and audited (`capacity`) only on a transition
        from NORMAL or from another cap. An INCOMPLETE channel stays INCOMPLETE: the cap still
        holds (the caller fetches nothing or consumes nothing), but the gap it records is never
        overwritten (REQ106; A2F fix round 1, 2026-10-11)."""
        if channel["state"] not in ("NORMAL", "OVERLOADED"):
            return
        if (channel["state"], channel["state_reason"]) != ("OVERLOADED", code):
            self._audit_only("state", ("OVERLOADED", code, self.store.fence, CHANNEL),
                             "capacity", code)

    def _cleared(self, channel: dict) -> None:
        """OVERLOADED -> NORMAL, or -> INCOMPLETE while a gap is unrecovered (`SQL_CHANNEL_SETTLE`),
        audited (`capacity_cleared`) with the cap that held it."""
        self._audit_only("settle", (self.store.fence, CHANNEL),
                         "capacity_cleared", channel["state_reason"] or "CAPACITY_REPORTS")

    def _count_warnings(self, used: limits.Usage) -> None:
        """Count (`capacity_warning`) and log each cap that enters its 80 percent band; one
        that leaves the band is counted again when it re-enters."""
        current = set(limits.warnings(used, self.config.limits))
        entered = sorted(current - self._warned)
        if entered:
            with self.store.transaction():
                self.store.counter_add("capacity_warning", len(entered))
            for code in entered:
                log_event("capacity warning", code)
        self._warned = current

    def _structural(self, refusal: StructuralRefusal, octets: bytes,
                    cursor_before: str | None) -> dict:
        store = self.store
        channel = store.channel()
        count = channel["retry_count"] + 1 if channel["retry_sha"] == refusal.digest else 1
        raw = (refusal.digest, store.now(), cursor_before, len(octets),
               None if limits.quarantine_full(store, self.config.limits) else octets,
               store.fence)
        self._audit_only("retry", (refusal.digest, count, store.fence, CHANNEL),
                         "structural_batch", refusal.code, raw=raw)
        if count >= self.config.limits["batch_retry_max"]:
            self._stop("STRUCTURAL_BATCH")
            return {"fetched": True, "reason": "STRUCTURAL_BATCH"}
        self._backoff_wait()
        return {"fetched": True, "reason": refusal.code}

    def _housekeeping(self) -> None:
        try:
            evaluate_freshness(self.store, self.config)
        except LeaseLost:
            self._block("LEASE_LOST")
            return
        except sqlite3.OperationalError:
            return
        self._sink_state(dispatch(self.store, self.sink, self.faults).failed_event)

    def _sink_state(self, failed: str | None) -> None:
        """Log and audit the sink's failure when it starts (`sink_failed`, naming the outbox
        event it did not take) and when it ends (`sink_recovered`), each with code
        `SINK_FAILED`; a pass that finds the same state writes nothing."""
        was = self.sink_failed
        if (failed is None) == (was is None):
            self.sink_failed = failed
            return
        if failed is not None:
            log_event("sink delivery failed", "SINK_FAILED")
        else:
            log_event("sink delivery recovered", "SINK_FAILED")
        with self.store.transaction():
            self.auditor.record("sink_failed" if failed is not None else "sink_recovered",
                                subject_id=failed if failed is not None else was,
                                code="SINK_FAILED",
                                policy_result="FAILED" if failed is not None else "DELIVERED")
        self.sink_failed = failed

    def _backoff_wait(self) -> None:
        self._waited = True
        self.sleeper(self.backoff.failure())

    def run(self, *, once: bool = False, should_stop: Callable[[], bool] = lambda: False) -> None:
        """Pass after pass until `should_stop()` or BLOCKED. The next pass starts at once after a
        pass that ingested records or left more to fetch; after one that fetched nothing (a
        stopped, resynchronising or capped channel, or an empty batch) the loop waits
        `idle_poll_seconds`, unless the pass already waited for the backoff."""
        while True:
            self._waited = False
            result = self.run_once()
            if once or should_stop() or self.status == BLOCKED:
                return
            if result.get("has_more") or result.get("dispositions") or self._waited:
                continue
            self.sleeper(self.config.idle_poll_seconds)

    # ------------------------------------------------------------------ health and status

    def health(self) -> dict:
        reasons = list(self.blocked_reasons)
        queue_depth, oldest = 0, None
        if self.store is not None:
            channel = self.store.channel()
            state = channel["state"]
            if state == "INCOMPLETE" or channel["incomplete"] is not None:
                reasons.append("CHANNEL_INCOMPLETE")    # a gap not yet recovered, in any state
            if state == "RESYNC_REQUIRED":
                reasons.append("RESYNC_REQUIRED")
            elif state == "STOPPED":
                reasons.append("CHANNEL_STOPPED")
            elif state == "OVERLOADED":
                reasons.append(channel["state_reason"] or "CAPACITY_REPORTS")
            if self.store.commit_failed:
                reasons.append("DURABLE_COMMIT_FAILED")
            if self.sink_failed is not None:
                reasons.append("SINK_FAILED")
            used = limits.usage(self.store)
            queue_depth = used.queued_reports
            if used.oldest_queued_at is not None:
                oldest = max(0, self.store.now() - used.oldest_queued_at)
        if not self.provider_ready and "PROVIDER_UNAVAILABLE" not in reasons:
            reasons.append("PROVIDER_UNAVAILABLE")
        if self.projection is negotiate.Projection.NEGOTIATION_FAILED and \
                "SCHEMA_NEGOTIATION_FAILED" not in reasons:
            reasons.append("SCHEMA_NEGOTIATION_FAILED")
        unready = {"PROVIDER_UNAVAILABLE", "SCHEMA_NEGOTIATION_FAILED", "DURABLE_COMMIT_FAILED",
                   "CHANNEL_INCOMPLETE", "RESYNC_REQUIRED", "CHANNEL_STOPPED",
                   "GATEWAY_IDENTITY_MISMATCH", "LEASE_LOST", "SINK_FAILED", "INTERNAL_ERROR"}
        return {"ready": not (unready & set(reasons)) and self.status != BLOCKED,
                "provider_ready": self.provider_ready, "blocked_reasons": reasons,
                "queue_depth": queue_depth, "oldest_unacked_ms": oldest}

    def gauges(self) -> dict:
        used = limits.usage(self.store)
        now = self.store.now()
        stale = 0
        for row in self.store.db.execute(SQL_CURRENT_ALL).fetchall():
            if row[7] == "ACTIVE" and freshness.of_current(row, now, self.config.freshness_seconds
                                                           )[0] != freshness.ACTIVE:
                stale += 1
        return {"native_readiness": 1 if self.native_status == "ACTIVE" else 0,
                "queue_depth": used.queued_reports, "queue_bytes": used.queued_report_bytes,
                "oldest_unacked_age_ms": None if used.oldest_queued_at is None
                else now - used.oldest_queued_at,
                "active_identities": used.identities, "stale_identities": stale,
                "last_accepted_report_age_ms": None}

    def status_report(self) -> dict:
        channel = self.store.channel()
        used = limits.usage(self.store)
        return {"status": self.status, "channel_state": channel["state"],
                "state_reason": channel["state_reason"], "degraded": bool(channel["degraded"]),
                "counters": self.store.counters(),
                "warnings": limits.warnings(used, self.config.limits),
                "full": limits.full(used, self.config.limits),
                "sink_failed": self.sink_failed is not None,
                "release_stages": native.release_stages(self.required_families_ready())}

    def required_families_ready(self) -> bool:
        if self.capabilities is None:
            return False
        return all(f in self.capabilities.receive_families for f in self.config.required_families)

    # ------------------------------------------------------------------ egress

    def export(self, entity: Entity, track: Track | None, *, peer_id: str,
               request_id: str | None = None) -> ExportResult:
        if self.egress is None:
            return ExportResult(request_id=request_id, state="DENIED", reason="PROFILE_NOT_READY")
        return self.egress.export(entity, track, peer_id=peer_id, request_id=request_id)

    def reconcile(self) -> list:
        return self.egress.reconcile()

    def revalidate(self) -> list:
        return self.egress.revalidate()

    # ------------------------------------------------------------------ operator records

    def _operator(self, kind: str, evidence: str) -> None:
        if type(evidence) is not str or not evidence.strip():
            raise OperatorRefusal("operator evidence text is required")

    def recover(self, evidence: str) -> None:
        """INCOMPLETE (a gap) -> NORMAL, only while the channel fetches normally again; the
        degraded flag is cleared too. On a channel that is only degraded the flag alone is
        cleared: a STOPPED, RESYNC_REQUIRED or OVERLOADED state, and a gap recorded under it, stay
        as they are (A2F fix round 1, 2026-10-11)."""
        self._operator("recover", evidence)
        channel = self.store.channel()
        if channel["state"] != "INCOMPLETE" and not channel["degraded"]:
            raise OperatorRefusal("recover applies to an INCOMPLETE or degraded channel")
        with self.store.transaction() as db:
            db.execute(SQL_CHANNEL_RECOVER, (self.store.fence, CHANNEL))
            self.auditor.record("recover", code=channel["state_reason"]
                                if channel["state"] == "INCOMPLETE" else None,
                                detail=f"gap {channel['gap_from']}..{channel['gap_to']}; "
                                       + evidence)

    def resync(self, evidence: str, lost_count: int | None = None) -> None:
        """RESYNC_REQUIRED after a 410 -> INCOMPLETE at the earliest cursor, the loss recorded."""
        self._operator("resync", evidence)
        channel = self.store.channel()
        if channel["state"] != "RESYNC_REQUIRED" or channel["state_reason"] != "CURSOR_EXPIRED":
            raise OperatorRefusal("resync applies after an expired cursor")
        with self.store.transaction() as db:
            db.execute(SQL_CHANNEL_RESYNC, (channel["earliest_cursor"], self.store.fence,
                                            CHANNEL))
            db.execute(SQL_CHANNEL_ACKED, (channel["earliest_cursor"], self.store.fence, CHANNEL))
            if lost_count:
                self.store.counter_add("fed", lost_count)
                self.store.counter_add("dropped_by_capacity", lost_count)
            self.auditor.record("resync", code="CURSOR_EXPIRED",
                                detail=f"lost={lost_count if lost_count is not None else 'unknown'}"
                                       f"; {evidence}")
        self._refetch_from = (False, None)

    def resync_identities(self, decision: str, evidence: str) -> None:
        """RESYNC_REQUIRED after RESET_SCOPE -> NORMAL with a recorded identity decision, or ->
        INCOMPLETE while a gap recorded before the RESET_SCOPE is unrecovered."""
        self._operator("resync_identities", evidence)
        if decision not in ("keep", "advance"):
            raise OperatorRefusal("decision is keep or advance")
        channel = self.store.channel()
        if channel["state"] != "RESYNC_REQUIRED" or channel["state_reason"] != "RESET_SCOPE":
            raise OperatorRefusal("resync-identities applies after RESET_SCOPE")
        with self.store.transaction() as db:
            if decision == "advance":
                db.execute(SQL_IDENTITY_EPOCH_RESET, (self.store.fence, channel["epoch"]))
            else:
                db.execute(SQL_IDENTITY_EPOCH_KEEP, (channel["epoch"], self.store.fence,
                                                     channel["epoch"]))
            db.execute(SQL_CHANNEL_SETTLE, (self.store.fence, CHANNEL))
            self.auditor.record("resync_identities", code="RESET_SCOPE",
                                policy_result=decision, detail=evidence)

    def resolve_reuse(self, identity_key: str, decision: str, evidence: str) -> int:
        """Release (`continue`) or keep refused (`reject`) the quarantined ambiguous reuse of one
        identity tuple, under any of the three rules. `continue` records the decision on the
        tuple, admitting it as a LIVE identity when rule (b) quarantined it before it was ever
        admitted, scoped to the highest incarnation of its (scope, track number) known now: a
        higher incarnation seen later re-arms rule (b) (fix round 2, 2026-10-11). Returns how
        many reports were released."""
        self._operator("resolve_reuse", evidence)
        if decision not in ("continue", "reject"):
            raise OperatorRefusal("decision is continue or reject")
        store = self.store
        released = 0
        with store.transaction() as db:
            pending = db.execute(SQL_QUARANTINE_REUSE, (identity_key,)).fetchall()
            if not pending:
                raise OperatorRefusal("no quarantined reuse for this identity")
            if decision == "reject":
                for quarantine_id, *_rest in pending:
                    db.execute(SQL_QUARANTINE_RESOLVE, (store.now(), "REJECTED_BY_OPERATOR",
                                                        store.fence, quarantine_id))
            else:
                epoch = store.channel()["epoch"]
                bodies = [jsonstrict.loads(body) for _q, _k, body, _b, _i in pending
                          if body is not None]
                if db.execute(SQL_IDENTITY_GET, (identity_key,)).fetchone() is None:
                    if db.execute(SQL_IDENTITY_COUNT_LIVE).fetchone()[0] >= \
                            self.config.limits["max_identities"]:
                        raise OperatorRefusal("the identity cap is reached")
                    first = min((parse_ms(body["effective_at"], "effective_at")
                                 for body in bodies), default=None)
                    identity.insert(store, identity_key, identity.fields_of(identity_key),
                                    "LIVE", epoch, first)
                fields = identity.fields_of(identity_key)
                scope = identity.highest_incarnation(db.execute(SQL_IDENTITY_SCOPE, (
                    fields["tenant"], fields["realm"], int(fields["synthetic"]),
                    fields["origin_scope"], fields["track_number"])).fetchall())
                db.execute(SQL_IDENTITY_STATUS, ("LIVE", "continue", scope, store.fence,
                                                 identity_key))
                for quarantine_id, record_key, body, _batch, _index in pending:
                    if body is None:
                        continue
                    report = jsonstrict.loads(body)
                    verdict = self.ingestor.translator.translate(report)
                    if verdict.action != ACCEPT:
                        continue
                    outcome, _flag = self.ingestor.accept(_Released(report), _Batch(_batch),
                                                          record_key, report, verdict, epoch,
                                                          insert_row=False)
                    if outcome == "ACCEPTED":
                        db.execute(SQL_QUARANTINE_RESOLVE, (store.now(), "CONTINUED_BY_OPERATOR",
                                                            store.fence, quarantine_id))
                        db.execute(SQL_INGEST_SET, ("ACCEPTED", "RELEASED", store.fence,
                                                    self.config.gateway_id, record_key))
                        store.counter_add("refused", -1)
                        released += 1
            self.auditor.record("resolve_reuse", subject_id=None, code="REUSE_AMBIGUOUS",
                                policy_result=decision, detail=evidence)
        return released

    def resolve_send(self, request_id: str, decision: str, evidence: str) -> str:
        self._operator("resolve_send", evidence)
        try:
            return self.egress.resolve_send(request_id, decision, evidence)
        except ValueError as error:
            raise OperatorRefusal(str(error)) from None

    def allocate(self, peer_id: str, realm: str, source_key: str, dest_tuple: dict,
                 evidence: str) -> None:
        self._operator("allocate", evidence)
        try:
            self.egress.allocate(peer_id, realm, source_key, dest_tuple, evidence)
        except ValueError as error:
            raise OperatorRefusal(str(error)) from None


class _Released:
    """A quarantined report released by an operator, in the shape `Ingestor.accept` reads."""

    def __init__(self, body: dict) -> None:
        self.body = body
        self.kind = "report"
        self.index = 0
        self.digest = jsonstrict.sha256_hex(jsonstrict.canonical(body))
        self.record_id = body["record_id"]


class _Batch:
    def __init__(self, sha256: str) -> None:
        self.sha256 = sha256
