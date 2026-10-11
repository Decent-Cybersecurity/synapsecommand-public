"""Transactional ingest of one batch, and the outbox's dispatch to a sink (REQ100, REQ101, REQ065,
REQ051, REQ162).

ONE BATCH, ONE TRANSACTION, IN REQ100's ORDER
---------------------------------------------
The batch is parsed (`jsonstrict.parse_batch`; a structurally invalid batch is refused whole and
nothing of it is consumed), then, in one `BEGIN IMMEDIATE` transaction that first checks the
lease's fence: the raw envelope's digest and size are recorded; each record in order is
deduplicated, checked for sequence contiguity and against the channel, validated and translated,
admitted to identity and state, and given its durable disposition and outbox events; the cursor
moves to the batch's `next_cursor`; the transaction commits. Only then does the caller acknowledge
the gateway, and only after that are outbox events delivered to the sink — at least once, keyed
`record_id:index`, for a consumer that upserts by key (REQ100: not an exactly-once claim).

A crash before the commit leaves nothing (no disposition, cursor unchanged, no acknowledgement)
and the batch is read again; a crash after the commit and before the acknowledgement makes the
gateway deliver the batch again, and every record is then a `DUPLICATE` with no second
publication (R01, R02).

PER RECORD
----------
- Deduplication by (configured `gateway_id`, `record_id`): the same canonical body is
  `DUPLICATE`; a different body is `DUPLICATE_CONFLICT`, quarantined, and the channel is
  degraded. A record whose body is not sound JSON (a duplicate key, a non-finite literal, a lone
  surrogate, a number no double holds) has no readable `record_id` and is keyed by its digest.
- Sequence contiguity per session: a jump is `STREAM_GAP` and the channel becomes INCOMPLETE; the
  record itself is still processed (REQ051). A new session must start at 0, except on a channel
  that has committed nothing yet. A `sequence` is read only when it has the contract's form
  (`0|[1-9][0-9]{0,19}`, at most 20 ASCII digits, checked before any conversion) and holds a
  uint64; any other is not a readable sequence, and the adapter judges the record (A2F,
  2026-10-11: 4 301 digits or more had escaped the pass as an exception).
- The channel check (`translate.Translator.channel_check`): a stop code rolls the whole
  transaction back, nothing is acknowledged, and the refusal is recorded in a separate audit-only
  transaction (D-32).
- Notices go to `lifecycle`; reports to scope, family, the adapter, identity and state. The
  channel's delivery epoch is read again after each notice, so a report after a `RESET_SCOPE` in
  the same batch belongs to the new epoch, as it would in a later batch (A2F, 2026-10-11).
- Every refusal is quarantined (or kept opaque) with its code, path and rule, never a value, and
  writes an audit row with the batch's digest as the raw evidence reference; the raw batch
  octets are kept as that evidence, within the quarantine cap.

ACCOUNTING (REQ162): after every batch `fed = accepted + refused + duplicate +
dropped_by_capacity`.

DISPATCH: `dispatch` delivers the outbox in order and stops at the first event the sink does not
take; it returns how many it delivered and the event key it could not deliver, and the bridge
records the failure (A2F, 2026-10-11).
"""
from __future__ import annotations

import dataclasses
import time
from typing import Callable, Protocol

from synapse_link16_bridge import (faults as _faults, freshness, identity, jsonstrict, lifecycle,
                                   limits, state)
from synapse_link16_bridge.clock import parse_ms
from synapse_link16_bridge.config import BridgeConfig
from synapse_link16_bridge.contract import DECIMAL, ContractError, validate_notice
from synapse_link16_bridge.lease import LeaseLost
from synapse_link16_bridge.observe import Auditor, Histograms, log_event
from synapse_link16_bridge.store import (CHANNEL, SQL_CHANNEL_CURSOR, SQL_CHANNEL_DEGRADE,
                                         SQL_CHANNEL_GAP, SQL_INGEST_GET, SQL_INGEST_INSERT,
                                         SQL_OPAQUE_INSERT, SQL_OUTBOX_MARK, SQL_OUTBOX_PENDING,
                                         SQL_QUARANTINE_INSERT, SQL_RAW_INSERT, SQL_RAW_KEEP,
                                         SQL_SESSION_ANY, SQL_SESSION_GET, SQL_SESSION_PUT,
                                         Store)
from synapse_link16_bridge.translate import ACCEPT, OPAQUE, QUARANTINE, STOP, Translator

UINT64_MAX = 2 ** 64 - 1


class Sink(Protocol):
    """Where outbox events go: an idempotent upsert by `event_key`, at least once."""

    accepts: tuple[str, ...]

    def deliver(self, event_key: str, kind: str, payload: bytes, flags: tuple[str, ...]) -> None:
        ...


class StructuralRefusal(Exception):
    """The batch is structurally invalid: nothing of it is consumed."""

    def __init__(self, code: str, path: str, rule: str, digest: str) -> None:
        self.code, self.path, self.rule, self.digest = code, path, rule, digest
        super().__init__(f"{code}: {path or '(batch)'} — {rule}")


class ChannelStop(Exception):
    """A stop code: the whole batch is rolled back and the channel stops (D-32)."""

    def __init__(self, code: str, path: str, record_key: str) -> None:
        self.code, self.path, self.record_key = code, path, record_key
        super().__init__(f"{code}: {path}")


@dataclasses.dataclass
class BatchOutcome:
    batch_sha256: str
    next_cursor: str
    has_more: bool
    records: int
    dispositions: list[tuple[str, str, str | None]]


class Ingestor:
    def __init__(self, store: Store, config: BridgeConfig, translator: Translator,
                 auditor: Auditor, *, faults: _faults.CrashPoints = _faults.NO_FAULTS,
                 histograms: Histograms | None = None,
                 monotonic: Callable[[], float] = time.perf_counter) -> None:
        self.store = store
        self.config = config
        self.translator = translator
        self.auditor = auditor
        self.faults = faults
        self.histograms = histograms or Histograms()
        self.monotonic = monotonic
        self._evidence = False
        self._quarantine_used: int | None = None     # the quarantine's bytes, inside a batch

    # ------------------------------------------------------------------ one batch

    def parse(self, octets: bytes) -> jsonstrict.Batch:
        started = self.monotonic()
        try:
            return jsonstrict.parse_batch(octets)
        except jsonstrict.ContractError as error:
            raise StructuralRefusal(error.code, error.path, error.rule,
                                    jsonstrict.sha256_hex(bytes(octets))) from None
        finally:
            self.histograms.observe("parse", self.monotonic() - started)

    def process(self, octets: bytes, cursor_before: str | None) -> BatchOutcome:
        batch = self.parse(octets)
        store = self.store
        outcome = BatchOutcome(batch.sha256, batch.next_cursor, batch.has_more,
                               len(batch.records), [])
        started = self.monotonic()
        try:
            with store.transaction() as db:
                db.execute(SQL_RAW_INSERT, (batch.sha256, store.now(), cursor_before, batch.size,
                                            None, store.fence))
                self.faults.hit("ingest.after_raw_store")
                self._evidence = False
                self._quarantine_used = limits.quarantine_bytes(store)     # once per batch
                epoch = store.channel()["epoch"]
                for record in batch.records:
                    disposition, code = self._record(record, batch, epoch)
                    if record.kind == "notice":         # a RESET_SCOPE closes the epoch
                        epoch = store.channel()["epoch"]
                    outcome.dispositions.append((record.record_id or record.digest, disposition,
                                                 code))
                if self._evidence and \
                        self._quarantine_used < self.config.limits["max_quarantine_bytes"]:
                    db.execute(SQL_RAW_KEEP, (bytes(octets), batch.sha256))
                db.execute(SQL_CHANNEL_CURSOR, (batch.next_cursor, batch.session_id, store.fence,
                                                CHANNEL))
                self.faults.hit("ingest.before_commit")
        finally:
            self._quarantine_used = None
        self.histograms.observe("outbox_commit", self.monotonic() - started)
        return outcome

    # ------------------------------------------------------------------ one record

    def _record(self, record: jsonstrict.RawRecord, batch: jsonstrict.Batch,
                epoch: int) -> tuple[str, str | None]:
        store, config = self.store, self.config
        key = record.record_id if record.record_id is not None else "raw:" + record.digest
        store.counter_add("fed")
        self._contiguity(record.body, batch)
        known = store.db.execute(SQL_INGEST_GET, (config.gateway_id, key)).fetchone()
        if known is not None:
            if known[0] == record.digest:
                store.counter_add("duplicate")
                return "DUPLICATE", None
            store.db.execute(SQL_CHANNEL_DEGRADE, (store.fence, CHANNEL))
            store.counter_add("duplicate_conflict")
            self._quarantine(record, batch, key, "DUPLICATE_CONFLICT", "record_id",
                             "same record_id, different content", record_row=False)
            return "QUARANTINED", "DUPLICATE_CONFLICT"
        if record.fault is not None:
            self._quarantine(record, batch, key, "JSON_INVALID", "", record.fault)
            return "QUARANTINED", "JSON_INVALID"
        body = record.body
        stop = self.translator.channel_check(record.kind, body)
        if stop is not None:
            raise ChannelStop(stop.code, stop.path, key)
        if record.kind == "notice":
            return self._notice(record, batch, key, body, epoch)
        verdict = self.translator.scope_check(body) or self.translator.family_check(body)
        if verdict is None:
            started = self.monotonic()
            verdict = self.translator.translate(body)
            self.histograms.observe("mapping", self.monotonic() - started)
        if verdict.action == STOP:
            raise ChannelStop(verdict.code, verdict.path or "", key)
        if verdict.action == OPAQUE:
            self._opaque(record, batch, key, verdict.code)
            return "OPAQUE", verdict.code
        if verdict.action == QUARANTINE:
            self._quarantine(record, batch, key, verdict.code, verdict.path, verdict.rule)
            return "QUARANTINED", verdict.code
        assert verdict.action == ACCEPT
        return self.accept(record, batch, key, body, verdict, epoch)

    def accept(self, record, batch, key: str, body: dict, verdict, epoch: int,
               *, insert_row: bool = True) -> tuple[str, str | None]:
        store = self.store
        effective_at = parse_ms(body["effective_at"], "effective_at")
        decision = identity.resolve(store, body, effective_at, epoch=epoch,
                                    max_identities=self.config.limits["max_identities"],
                                    now=store.now())
        identity_key = identity.key_of(body)
        if not decision.accept:
            self._quarantine(record, batch, key, decision.code, "incarnation",
                             "ambiguous reuse of a source track number",
                             identity_key=identity_key, body=jsonstrict.canonical(body),
                             record_row=insert_row)
            return "QUARANTINED", decision.code
        flag = state.apply(store, identity_key, body, list(verdict.objects),
                           force_late=decision.late, flags=list(verdict.flags))
        if insert_row:
            self._row(record, batch, key, "ACCEPTED", flag, identity_key)
        return "ACCEPTED", flag

    def _notice(self, record, batch, key: str, body: dict, epoch: int) -> tuple[str, str | None]:
        try:
            validate_notice(body)
        except ContractError as error:
            if error.code == "TIME_UNRESOLVED":
                self._opaque(record, batch, key, error.code)
                return "OPAQUE", error.code
            self._quarantine(record, batch, key, error.code, error.path, error.rule)
            return "QUARANTINED", error.code
        scope = self.translator.scope_check(body)
        if scope is not None:
            self._quarantine(record, batch, key, scope.code, scope.path, scope.rule)
            return "QUARANTINED", scope.code
        outcome = lifecycle.apply(self.store, body, channel_epoch=epoch,
                                  tenant=self.config.tenant, realm=self.config.realm,
                                  synthetic=self.config.synthetic,
                                  max_identities=self.config.limits["max_identities"])
        if not outcome.accept:
            self._quarantine(record, batch, key, outcome.code, outcome.path,
                             "lifecycle notice refused")
            return "QUARANTINED", outcome.code
        self.store.counter_add("accepted")
        self._row(record, batch, key, "ACCEPTED", body["operation"], None)
        return "ACCEPTED", body["operation"]

    def _contiguity(self, body: dict | None, batch: jsonstrict.Batch) -> None:
        """REQ051 per session: each committed record is the previous one's sequence plus one.
        A record at or below the last seen sequence is a redelivery or a reordering (the
        deduplication judges it); one beyond the next is a gap. A body that is not sound JSON
        has no readable sequence and is taken to hold the next one of the batch's session. A
        sequence outside the contract's form is not read (no conversion of an unbounded digit
        string): the adapter refuses the record."""
        store = self.store
        if body is None:
            session, value = batch.session_id, None
        else:
            session, sequence = body.get("session_id"), body.get("sequence")
            if type(session) is not str or type(sequence) is not str or \
                    DECIMAL.fullmatch(sequence) is None or int(sequence) > UINT64_MAX:
                return
            value = int(sequence)
        row = store.db.execute(SQL_SESSION_GET, (session,)).fetchone()
        last = None if row is None else int(row[0])
        if value is None:
            if last is not None:
                store.db.execute(SQL_SESSION_PUT, (session, str(last + 1)))
            return
        if last is None:
            first_ever = not store.channel()["committed_any"] and \
                store.db.execute(SQL_SESSION_ANY).fetchone()[0] == 0
            expected, gap = 0, value != 0 and not first_ever
        else:
            expected, gap = last + 1, value > last + 1
        if gap:
            store.db.execute(SQL_CHANNEL_GAP, ("STREAM_GAP", str(expected), str(value),
                                               store.fence, CHANNEL))
            record_id = body.get("record_id")
            self.auditor.record("stream_gap",
                                subject_id=record_id if type(record_id) is str else None,
                                code="STREAM_GAP", raw_ref=batch.sha256)
        store.db.execute(SQL_SESSION_PUT, (session, str(value if last is None
                                                        else max(value, last))))

    # ------------------------------------------------------------------ dispositions

    def _row(self, record, batch, key: str, disposition: str, code: str | None,
             identity_key: str | None) -> None:
        body = record.body or {}
        session = body.get("session_id") if type(body.get("session_id")) is str else None
        sequence = body.get("sequence") if type(body.get("sequence")) is str else None
        self.store.db.execute(SQL_INGEST_INSERT, (
            self.config.gateway_id, key, record.kind, record.digest, session, sequence,
            batch.sha256, record.index, disposition, code, identity_key, self.store.fence,
            self.store.now()))

    def _quarantine(self, record, batch, key: str, code: str, path: str | None,
                    rule: str | None, *, identity_key: str | None = None,
                    body: bytes | None = None, record_row: bool = True) -> None:
        store = self.store
        if body is None and record.body is not None:
            body = jsonstrict.canonical(record.body)
        used = self._quarantine_used if self._quarantine_used is not None else \
            limits.quarantine_bytes(store)
        metadata_only = used >= self.config.limits["max_quarantine_bytes"]
        size = len(body) if body is not None else 0
        if metadata_only:
            store.counter_add("quarantine_metadata_only")
            log_event("quarantine full: metadata only", "CAPACITY_QUARANTINE")
        elif self._quarantine_used is not None:
            self._quarantine_used += size
        store.db.execute(SQL_QUARANTINE_INSERT, (
            self.config.gateway_id, key, record.kind, code, path, rule, identity_key,
            batch.sha256, record.index, None if metadata_only else body,
            0 if metadata_only else size, int(metadata_only), store.now(), store.fence))
        if record_row:
            self._row(record, batch, key, "QUARANTINED", code, identity_key)
        store.counter_add("refused")
        self._evidence = True
        self.auditor.record("refusal", subject_id=key, code=code, raw_ref=batch.sha256,
                            policy_result="QUARANTINED")

    def _opaque(self, record, batch, key: str, code: str) -> None:
        store = self.store
        body = jsonstrict.canonical(record.body) if record.body is not None else None
        store.db.execute(SQL_OPAQUE_INSERT, (self.config.gateway_id, key, record.kind, code,
                                             batch.sha256, record.index, body, store.now(),
                                             store.fence))
        self._row(record, batch, key, "OPAQUE", code, None)
        store.counter_add("refused")
        if code == "UNSUPPORTED_MESSAGE":
            store.counter_add("unsupported")
        self._evidence = True
        self.auditor.record("refusal", subject_id=key, code=code, raw_ref=batch.sha256,
                            policy_result="OPAQUE")


@dataclasses.dataclass(frozen=True)
class DispatchOutcome:
    delivered: int
    failed_event: str | None = None     # the outbox head the sink did not take, if any


def dispatch(store: Store, sink: Sink,
             faults: _faults.CrashPoints = _faults.NO_FAULTS) -> DispatchOutcome:
    """Deliver every undelivered outbox event in order; mark each after the sink took it. A sink
    that raises stops the pass and the rest stay queued (at least once, never lost); the outcome
    names the event it did not take, and the caller logs and audits the failure (`SINK_FAILED`)."""
    delivered = 0
    for event_key, kind, payload, flags in store.db.execute(SQL_OUTBOX_PENDING).fetchall():
        marks = tuple(jsonstrict.loads(flags.encode("utf-8")))
        try:
            sink.deliver(event_key, kind, bytes(payload), marks)
        except Exception:                               # noqa: BLE001 - the sink's own failure
            return DispatchOutcome(delivered, event_key)
        faults.hit("outbox.before_mark_dispatched")
        try:
            with store.transaction() as db:
                db.execute(SQL_OUTBOX_MARK, (store.now(), event_key))
        except LeaseLost:
            break
        delivered += 1
    return DispatchOutcome(delivered)


def evaluate_freshness(store: Store, config: BridgeConfig) -> list:
    with store.transaction():
        return freshness.evaluate(store, config.freshness_seconds)
