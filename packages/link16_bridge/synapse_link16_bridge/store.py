"""The durable store: one SQLite file per channel, every mutation one fenced transaction.

`journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`. Every mutation runs inside
`Store.transaction()`, which opens `BEGIN IMMEDIATE` and checks the writer lease's fence before
anything else (REQ141); every mutated row records the fence it was written under. All instants
are integer UTC milliseconds.

SQL is written ONLY as the module-level `SQL_*` string constants below, with `?` placeholders:
no SQL text is built at run time from any value, and no other module defines one (a static test
holds both). No `RETURNING` (older SQLite builds lack it): a row id is read with a plain query.

Tables (REQ100-106, REQ120-122, REQ141, REQ150-151): `meta` (the channel binding the file was
created for), `lease`, `raw_batch` (the raw envelope as evidence, readable only through the
separately controlled evidence reader), `ingest` (one durable disposition per record),
`session_seq`, `identity`, `observation` (history, never deleted), `sample`, `sample_conflict`,
`current`, `conflict`, `relation`, `quarantine`, `opaque`, `outbox`, `channel`, `allocation`,
`export_job`, `audit`, `counter`.

The channel's `incomplete` column holds the code of the first gap or loss (`GAP`, `STREAM_GAP`,
`CURSOR_EXPIRED`) no operator has yet recorded as recovered, whatever state the channel is in
meanwhile: only `recover`, on an INCOMPLETE channel, clears it, and every other way back towards
NORMAL (`SQL_CHANNEL_SETTLE`) lands on INCOMPLETE while it is set (REQ106; A2F fix round 1,
2026-10-11).
"""
from __future__ import annotations

import contextlib
import sqlite3
from typing import Any, Iterator

from synapse_link16_bridge import faults as _faults
from synapse_link16_bridge.clock import Clock, now_ms

SCHEMA_VERSION = "1"
CHANNEL = "channel"

SQL_PRAGMA_WAL = "PRAGMA journal_mode=WAL"
SQL_PRAGMA_SYNC = "PRAGMA synchronous=FULL"
SQL_PRAGMA_FK = "PRAGMA foreign_keys=ON"
SQL_BEGIN = "BEGIN IMMEDIATE"
SQL_COMMIT = "COMMIT"
SQL_ROLLBACK = "ROLLBACK"

SQL_CREATE = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lease (channel TEXT PRIMARY KEY, holder TEXT NOT NULL,
    fence INTEGER NOT NULL, expires_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS raw_batch (batch_sha256 TEXT PRIMARY KEY, received_at INTEGER NOT NULL,
    cursor_before TEXT, bytes INTEGER NOT NULL, body BLOB, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ingest (gateway_id TEXT NOT NULL, record_key TEXT NOT NULL,
    kind TEXT NOT NULL, body_sha256 TEXT NOT NULL, session_id TEXT, sequence TEXT,
    batch_sha256 TEXT NOT NULL, idx INTEGER NOT NULL, disposition TEXT NOT NULL, code TEXT,
    identity_key TEXT, fence INTEGER NOT NULL, committed_at INTEGER NOT NULL,
    PRIMARY KEY (gateway_id, record_key));
CREATE TABLE IF NOT EXISTS session_seq (session_id TEXT PRIMARY KEY, last_sequence TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS identity (identity_key TEXT PRIMARY KEY, tenant TEXT NOT NULL,
    realm TEXT NOT NULL, synthetic INTEGER NOT NULL, origin_scope TEXT NOT NULL,
    track_number TEXT NOT NULL, incarnation TEXT NOT NULL, entity_id TEXT NOT NULL,
    track_id TEXT NOT NULL, status TEXT NOT NULL, epoch INTEGER NOT NULL, tombstone_at INTEGER,
    tombstone_record_id TEXT, first_effective_at INTEGER, reuse_decision TEXT,
    fence INTEGER NOT NULL, reuse_scope INTEGER);
CREATE INDEX IF NOT EXISTS identity_scope ON identity (tenant, realm, synthetic, origin_scope,
    track_number);
CREATE TABLE IF NOT EXISTS observation (identity_key TEXT NOT NULL, record_id TEXT NOT NULL,
    effective_at INTEGER NOT NULL, pos_observed_at INTEGER, kin_observed_at INTEGER,
    state_sha256 TEXT NOT NULL, late INTEGER NOT NULL, flag TEXT, conflict_id INTEGER,
    ingested_at INTEGER NOT NULL, fence INTEGER NOT NULL, PRIMARY KEY (identity_key, record_id));
CREATE TABLE IF NOT EXISTS sample (identity_key TEXT NOT NULL, pos_observed_at INTEGER NOT NULL,
    sample_sha256 TEXT NOT NULL, first_record_id TEXT NOT NULL, refreshes INTEGER NOT NULL,
    PRIMARY KEY (identity_key, pos_observed_at));
CREATE TABLE IF NOT EXISTS sample_conflict (id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL, pos_observed_at INTEGER NOT NULL, record_id TEXT NOT NULL,
    sample_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS current (identity_key TEXT PRIMARY KEY, record_id TEXT NOT NULL,
    effective_at INTEGER NOT NULL, state_sha256 TEXT NOT NULL, pos_observed_at INTEGER,
    kin_observed_at INTEGER, domain TEXT NOT NULL, contribution TEXT NOT NULL,
    open_conflict_id INTEGER, freshness TEXT, motion_freshness TEXT, entity_payload BLOB NOT NULL,
    fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS conflict (id INTEGER PRIMARY KEY AUTOINCREMENT,
    identity_key TEXT NOT NULL, effective_at INTEGER NOT NULL,
    established_record_id TEXT NOT NULL, conflicting_record_id TEXT NOT NULL,
    resolved_at INTEGER, resolution TEXT);
CREATE TABLE IF NOT EXISTS relation (id INTEGER PRIMARY KEY AUTOINCREMENT, old_key TEXT NOT NULL,
    new_key TEXT NOT NULL, notice_record_id TEXT NOT NULL, effective_at INTEGER NOT NULL,
    reason TEXT NOT NULL, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS quarantine (id INTEGER PRIMARY KEY AUTOINCREMENT,
    gateway_id TEXT NOT NULL, record_key TEXT NOT NULL, kind TEXT NOT NULL, code TEXT NOT NULL,
    path TEXT, rule TEXT, identity_key TEXT, batch_sha256 TEXT NOT NULL, idx INTEGER NOT NULL,
    body BLOB, bytes INTEGER NOT NULL, metadata_only INTEGER NOT NULL, created_at INTEGER NOT NULL,
    resolved_at INTEGER, resolution TEXT, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS opaque (gateway_id TEXT NOT NULL, record_key TEXT NOT NULL,
    kind TEXT NOT NULL, code TEXT NOT NULL, batch_sha256 TEXT NOT NULL, idx INTEGER NOT NULL,
    body BLOB, created_at INTEGER NOT NULL, fence INTEGER NOT NULL,
    PRIMARY KEY (gateway_id, record_key));
CREATE TABLE IF NOT EXISTS outbox (event_key TEXT PRIMARY KEY, kind TEXT NOT NULL,
    payload BLOB NOT NULL, schema_version TEXT, flags TEXT NOT NULL, bytes INTEGER NOT NULL,
    created_at INTEGER NOT NULL, dispatched_at INTEGER, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS channel (channel TEXT PRIMARY KEY, cursor TEXT, acked_cursor TEXT,
    session_id TEXT, state TEXT NOT NULL, state_reason TEXT, degraded INTEGER NOT NULL,
    epoch INTEGER NOT NULL, earliest_cursor TEXT, stopped_revision TEXT, retry_sha TEXT,
    retry_count INTEGER NOT NULL, committed_any INTEGER NOT NULL, gap_from TEXT, gap_to TEXT,
    incomplete TEXT, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS allocation (peer_id TEXT NOT NULL, dest_realm TEXT NOT NULL,
    source_identity_key TEXT NOT NULL, dest_identity TEXT NOT NULL, allocated_by TEXT NOT NULL,
    evidence TEXT NOT NULL, recorded_at INTEGER NOT NULL, fence INTEGER NOT NULL,
    PRIMARY KEY (peer_id, dest_realm, source_identity_key));
CREATE TABLE IF NOT EXISTS export_job (request_id TEXT PRIMARY KEY, body BLOB,
    body_sha256 TEXT, peer_id TEXT NOT NULL, source_identity_key TEXT, expires_at INTEGER,
    policy_revision TEXT, state TEXT NOT NULL, reason TEXT, fence INTEGER NOT NULL,
    created_at INTEGER NOT NULL, changed_at INTEGER NOT NULL, attempts INTEGER NOT NULL,
    in_flight INTEGER NOT NULL, loss_report TEXT, cdm_digest TEXT, entity_payload BLOB,
    track_payload BLOB);
CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER NOT NULL,
    correlation_id TEXT NOT NULL, kind TEXT NOT NULL, subject_id TEXT, code TEXT,
    profile_version TEXT NOT NULL, config_revision TEXT NOT NULL, policy_result TEXT,
    transformations TEXT, raw_ref TEXT, detail TEXT, fence INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS counter (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""

# -- meta, counters, audit
SQL_META_GET = "SELECT value FROM meta WHERE key = ?"
SQL_META_PUT = "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)"
SQL_COUNTER_ADD = ("INSERT INTO counter (name, value) VALUES (?, ?) "
                   "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value")
SQL_COUNTER_GET = "SELECT value FROM counter WHERE name = ?"
SQL_COUNTERS = "SELECT name, value FROM counter ORDER BY name"
SQL_AUDIT_INSERT = ("INSERT INTO audit (at, correlation_id, kind, subject_id, code, "
                    "profile_version, config_revision, policy_result, transformations, raw_ref, "
                    "detail, fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
SQL_AUDIT_ALL = ("SELECT seq, at, correlation_id, kind, subject_id, code, profile_version, "
                 "config_revision, policy_result, transformations, raw_ref, detail, fence "
                 "FROM audit ORDER BY seq")

# -- lease
SQL_LEASE_GET = "SELECT holder, fence, expires_at FROM lease WHERE channel = ?"
SQL_LEASE_INSERT = "INSERT INTO lease (channel, holder, fence, expires_at) VALUES (?, ?, ?, ?)"
SQL_LEASE_UPDATE = "UPDATE lease SET holder = ?, fence = ?, expires_at = ? WHERE channel = ?"
SQL_LEASE_EXPIRE = "UPDATE lease SET expires_at = ? WHERE channel = ?"
SQL_JOBS_REVALIDATE = ("UPDATE export_job SET state = 'REVALIDATE', changed_at = ?, fence = ? "
                       "WHERE state IN ('PENDING', 'ACCEPTED') AND in_flight = 0 AND fence < ?")
SQL_JOBS_INFLIGHT_UNKNOWN = ("UPDATE export_job SET state = 'UNKNOWN', in_flight = 0, "
                             "reason = 'SEND_OUTCOME_UNKNOWN', changed_at = ?, fence = ? "
                             "WHERE in_flight = 1 AND fence < ?")

# -- channel
SQL_CHANNEL_GET = ("SELECT cursor, acked_cursor, session_id, state, state_reason, degraded, epoch, "
                   "earliest_cursor, stopped_revision, retry_sha, retry_count, committed_any, "
                   "gap_from, gap_to, incomplete FROM channel WHERE channel = ?")
SQL_CHANNEL_INIT = ("INSERT OR IGNORE INTO channel (channel, state, degraded, epoch, retry_count, "
                    "committed_any, fence) VALUES (?, 'NORMAL', 0, 0, 0, 0, ?)")
SQL_CHANNEL_CURSOR = ("UPDATE channel SET cursor = ?, session_id = ?, committed_any = 1, "
                      "retry_sha = NULL, retry_count = 0, fence = ? WHERE channel = ?")
SQL_CHANNEL_ACKED = "UPDATE channel SET acked_cursor = ?, fence = ? WHERE channel = ?"
SQL_CHANNEL_STATE = ("UPDATE channel SET state = ?, state_reason = ?, fence = ? "
                     "WHERE channel = ?")
SQL_CHANNEL_SETTLE = ("UPDATE channel SET state = CASE WHEN incomplete IS NULL THEN 'NORMAL' "
                      "ELSE 'INCOMPLETE' END, state_reason = incomplete, fence = ? "
                      "WHERE channel = ?")
SQL_CHANNEL_STOP = ("UPDATE channel SET state = 'STOPPED', state_reason = ?, "
                    "stopped_revision = ?, fence = ? WHERE channel = ?")
SQL_CHANNEL_DEGRADE = "UPDATE channel SET degraded = 1, fence = ? WHERE channel = ?"
SQL_CHANNEL_UNDEGRADE = "UPDATE channel SET degraded = 0, fence = ? WHERE channel = ?"
SQL_CHANNEL_EXPIRED = ("UPDATE channel SET state = 'RESYNC_REQUIRED', "
                       "state_reason = 'CURSOR_EXPIRED', earliest_cursor = ?, fence = ? "
                       "WHERE channel = ?")
SQL_CHANNEL_RESYNC = ("UPDATE channel SET cursor = ?, state = 'INCOMPLETE', "
                      "state_reason = 'CURSOR_EXPIRED', "
                      "incomplete = COALESCE(incomplete, 'CURSOR_EXPIRED'), "
                      "earliest_cursor = NULL, fence = ? WHERE channel = ?")
SQL_CHANNEL_EPOCH = ("UPDATE channel SET epoch = epoch + 1, state = 'RESYNC_REQUIRED', "
                     "state_reason = 'RESET_SCOPE', fence = ? WHERE channel = ?")
SQL_CHANNEL_GAP = ("UPDATE channel SET state = CASE WHEN state = 'NORMAL' THEN 'INCOMPLETE' "
                   "ELSE state END, state_reason = CASE WHEN state = 'NORMAL' THEN ?1 "
                   "ELSE state_reason END, incomplete = COALESCE(incomplete, ?1), "
                   "gap_from = COALESCE(gap_from, ?2), gap_to = ?3, fence = ?4 "
                   "WHERE channel = ?5")
SQL_CHANNEL_RECOVER = ("UPDATE channel SET "
                       "state = CASE WHEN state = 'INCOMPLETE' THEN 'NORMAL' ELSE state END, "
                       "state_reason = CASE WHEN state = 'INCOMPLETE' THEN NULL "
                       "ELSE state_reason END, "
                       "incomplete = CASE WHEN state = 'INCOMPLETE' THEN NULL ELSE incomplete END, "
                       "gap_from = CASE WHEN state = 'INCOMPLETE' THEN NULL ELSE gap_from END, "
                       "gap_to = CASE WHEN state = 'INCOMPLETE' THEN NULL ELSE gap_to END, "
                       "degraded = 0, fence = ? WHERE channel = ?")
SQL_CHANNEL_RETRY = ("UPDATE channel SET retry_sha = ?, retry_count = ?, degraded = 1, fence = ? "
                     "WHERE channel = ?")

# -- raw batches and dispositions
SQL_RAW_INSERT = ("INSERT OR IGNORE INTO raw_batch (batch_sha256, received_at, cursor_before, "
                  "bytes, body, fence) VALUES (?, ?, ?, ?, ?, ?)")
SQL_RAW_GET = "SELECT body, bytes, received_at FROM raw_batch WHERE batch_sha256 = ?"
SQL_RAW_KEEP = "UPDATE raw_batch SET body = ? WHERE batch_sha256 = ? AND body IS NULL"
SQL_RAW_BYTES = "SELECT COALESCE(SUM(bytes), 0) FROM raw_batch WHERE body IS NOT NULL"
SQL_INGEST_GET = ("SELECT body_sha256, disposition, code FROM ingest "
                  "WHERE gateway_id = ? AND record_key = ?")
SQL_INGEST_INSERT = ("INSERT INTO ingest (gateway_id, record_key, kind, body_sha256, session_id, "
                     "sequence, batch_sha256, idx, disposition, code, identity_key, fence, "
                     "committed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
SQL_INGEST_SET = ("UPDATE ingest SET disposition = ?, code = ?, fence = ? "
                  "WHERE gateway_id = ? AND record_key = ?")
SQL_INGEST_COUNT = "SELECT COUNT(*) FROM ingest"
SQL_INGEST_BY_DISPOSITION = "SELECT record_key, code FROM ingest WHERE disposition = ? ORDER BY rowid"
SQL_SESSION_GET = "SELECT last_sequence FROM session_seq WHERE session_id = ?"
SQL_SESSION_PUT = "INSERT OR REPLACE INTO session_seq (session_id, last_sequence) VALUES (?, ?)"
SQL_SESSION_ANY = "SELECT COUNT(*) FROM session_seq"
SQL_QUARANTINE_INSERT = ("INSERT INTO quarantine (gateway_id, record_key, kind, code, path, rule, "
                         "identity_key, batch_sha256, idx, body, bytes, metadata_only, "
                         "created_at, fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
SQL_QUARANTINE_BYTES = "SELECT COALESCE(SUM(bytes), 0) FROM quarantine WHERE metadata_only = 0"
SQL_QUARANTINE_ALL = ("SELECT id, record_key, kind, code, path, rule, identity_key, "
                      "metadata_only, resolved_at, resolution FROM quarantine ORDER BY id")
SQL_QUARANTINE_REUSE = ("SELECT id, record_key, body, batch_sha256, idx FROM quarantine "
                        "WHERE code = 'REUSE_AMBIGUOUS' AND identity_key = ? "
                        "AND resolved_at IS NULL ORDER BY id")
SQL_QUARANTINE_REUSE_SCOPE = ("SELECT q.id, q.identity_key FROM quarantine q "
                              "WHERE q.code = 'REUSE_AMBIGUOUS' AND q.resolved_at IS NULL")
SQL_QUARANTINE_RESOLVE = "UPDATE quarantine SET resolved_at = ?, resolution = ?, fence = ? WHERE id = ?"
SQL_OPAQUE_INSERT = ("INSERT OR IGNORE INTO opaque (gateway_id, record_key, kind, code, "
                     "batch_sha256, idx, body, created_at, fence) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
SQL_OPAQUE_ALL = "SELECT record_key, kind, code, batch_sha256, idx FROM opaque ORDER BY rowid"

# -- identity, history, current state
SQL_IDENTITY_GET = ("SELECT identity_key, tenant, realm, synthetic, origin_scope, track_number, "
                    "incarnation, entity_id, track_id, status, epoch, tombstone_at, "
                    "tombstone_record_id, first_effective_at, reuse_decision, reuse_scope "
                    "FROM identity WHERE identity_key = ?")
SQL_IDENTITY_INSERT = ("INSERT INTO identity (identity_key, tenant, realm, synthetic, "
                       "origin_scope, track_number, incarnation, entity_id, track_id, status, "
                       "epoch, tombstone_at, tombstone_record_id, first_effective_at, "
                       "reuse_decision, fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                       "?, ?)")
SQL_IDENTITY_STATUS = ("UPDATE identity SET status = ?, reuse_decision = ?, reuse_scope = ?, "
                       "fence = ? WHERE identity_key = ?")
SQL_IDENTITY_TOMBSTONE = ("UPDATE identity SET status = 'TOMBSTONED', tombstone_at = ?, "
                          "tombstone_record_id = ?, fence = ? WHERE identity_key = ?")
SQL_IDENTITY_SCOPE = ("SELECT identity_key, incarnation, first_effective_at, status "
                      "FROM identity WHERE tenant = ? AND realm = ? AND synthetic = ? "
                      "AND origin_scope = ? AND track_number = ?")
SQL_IDENTITY_COUNT_LIVE = "SELECT COUNT(*) FROM identity WHERE status = 'LIVE'"
SQL_IDENTITY_COUNT = "SELECT COUNT(*) FROM identity"
SQL_IDENTITY_EPOCH_RESET = ("UPDATE identity SET status = 'RESET', fence = ? "
                            "WHERE status = 'LIVE' AND epoch < ?")
SQL_IDENTITY_EPOCH_KEEP = "UPDATE identity SET epoch = ?, fence = ? WHERE epoch < ?"
SQL_IDENTITY_ALL = ("SELECT identity_key, status, incarnation, entity_id, tombstone_at "
                    "FROM identity ORDER BY identity_key")
SQL_OBSERVATION_INSERT = ("INSERT INTO observation (identity_key, record_id, effective_at, "
                          "pos_observed_at, kin_observed_at, state_sha256, late, flag, "
                          "conflict_id, ingested_at, fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, "
                          "?, ?)")
SQL_OBSERVATION_FOR = ("SELECT record_id, effective_at, late, flag, conflict_id FROM observation "
                       "WHERE identity_key = ? ORDER BY ingested_at, rowid")
SQL_OBSERVATION_COUNT = "SELECT COUNT(*) FROM observation"
SQL_OBSERVATION_STATE = ("SELECT effective_at, state_sha256, late FROM observation "
                         "WHERE identity_key = ? AND record_id = ?")
SQL_SAMPLE_GET = ("SELECT sample_sha256, refreshes FROM sample "
                  "WHERE identity_key = ? AND pos_observed_at = ?")
SQL_SAMPLE_INSERT = ("INSERT INTO sample (identity_key, pos_observed_at, sample_sha256, "
                     "first_record_id, refreshes) VALUES (?, ?, ?, ?, 0)")
SQL_SAMPLE_REFRESH = ("UPDATE sample SET refreshes = refreshes + 1 "
                      "WHERE identity_key = ? AND pos_observed_at = ?")
SQL_SAMPLE_CONFLICT = ("INSERT INTO sample_conflict (identity_key, pos_observed_at, record_id, "
                       "sample_sha256) VALUES (?, ?, ?, ?)")
SQL_SAMPLE_CONFLICTS = ("SELECT identity_key, pos_observed_at, record_id FROM sample_conflict "
                        "ORDER BY id")
SQL_CURRENT_GET = ("SELECT identity_key, record_id, effective_at, state_sha256, pos_observed_at, "
                   "kin_observed_at, domain, contribution, open_conflict_id, freshness, "
                   "motion_freshness, entity_payload FROM current WHERE identity_key = ?")
SQL_CURRENT_PUT = ("INSERT OR REPLACE INTO current (identity_key, record_id, effective_at, "
                   "state_sha256, pos_observed_at, kin_observed_at, domain, contribution, "
                   "open_conflict_id, freshness, motion_freshness, entity_payload, fence) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', NULL, NULL, NULL, ?, ?)")
SQL_CURRENT_CONFLICT = ("UPDATE current SET open_conflict_id = ?, fence = ? "
                        "WHERE identity_key = ?")
SQL_CURRENT_CLOSE = ("UPDATE current SET contribution = 'CLOSED', fence = ? "
                     "WHERE identity_key = ?")
SQL_CURRENT_FRESHNESS = ("UPDATE current SET freshness = ?, motion_freshness = ?, fence = ? "
                         "WHERE identity_key = ?")
SQL_CURRENT_ALL = ("SELECT identity_key, record_id, effective_at, state_sha256, pos_observed_at, "
                   "kin_observed_at, domain, contribution, open_conflict_id, freshness, "
                   "motion_freshness, entity_payload FROM current ORDER BY identity_key")
SQL_CONFLICT_INSERT = ("INSERT INTO conflict (identity_key, effective_at, established_record_id, "
                       "conflicting_record_id) VALUES (?, ?, ?, ?)")
SQL_LAST_ROWID = "SELECT last_insert_rowid()"
SQL_CONFLICT_ALL = ("SELECT id, identity_key, effective_at, established_record_id, "
                    "conflicting_record_id FROM conflict ORDER BY id")
SQL_RELATION_INSERT = ("INSERT INTO relation (old_key, new_key, notice_record_id, effective_at, "
                       "reason, fence) VALUES (?, ?, ?, ?, ?, ?)")
SQL_RELATION_ALL = ("SELECT old_key, new_key, notice_record_id, effective_at FROM relation "
                    "ORDER BY id")

# -- outbox
SQL_OUTBOX_INSERT = ("INSERT OR IGNORE INTO outbox (event_key, kind, payload, schema_version, "
                     "flags, bytes, created_at, fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
SQL_OUTBOX_PENDING = ("SELECT event_key, kind, payload, flags FROM outbox "
                      "WHERE dispatched_at IS NULL ORDER BY created_at, event_key")
SQL_OUTBOX_MARK = "UPDATE outbox SET dispatched_at = ? WHERE event_key = ?"
SQL_OUTBOX_PAYLOAD = "SELECT payload FROM outbox WHERE event_key = ?"
SQL_OUTBOX_QUEUE = ("SELECT COUNT(*), COALESCE(SUM(bytes), 0), MIN(created_at) FROM outbox "
                    "WHERE dispatched_at IS NULL")
SQL_OUTBOX_ALL = ("SELECT event_key, kind, payload, schema_version, flags, dispatched_at "
                  "FROM outbox ORDER BY created_at, event_key")

# -- egress
SQL_ALLOCATION_GET = ("SELECT dest_identity, allocated_by, evidence FROM allocation "
                      "WHERE peer_id = ? AND dest_realm = ? AND source_identity_key = ?")
SQL_ALLOCATION_PUT = ("INSERT OR REPLACE INTO allocation (peer_id, dest_realm, "
                      "source_identity_key, dest_identity, allocated_by, evidence, recorded_at, "
                      "fence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
SQL_JOB_INSERT = ("INSERT INTO export_job (request_id, body, body_sha256, peer_id, "
                  "source_identity_key, expires_at, policy_revision, state, reason, fence, "
                  "created_at, changed_at, attempts, in_flight, loss_report, cdm_digest, "
                  "entity_payload, track_payload) "
                  "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?, ?)")
SQL_JOB_GET = ("SELECT request_id, body, body_sha256, peer_id, source_identity_key, expires_at, "
               "policy_revision, state, reason, fence, attempts, in_flight, loss_report, "
               "cdm_digest, entity_payload, track_payload FROM export_job WHERE request_id = ?")
SQL_JOB_STATE = ("UPDATE export_job SET state = ?, reason = ?, changed_at = ?, in_flight = 0, "
                 "fence = ? WHERE request_id = ?")
SQL_JOB_INFLIGHT = ("UPDATE export_job SET in_flight = 1, attempts = attempts + 1, "
                    "changed_at = ?, fence = ? WHERE request_id = ?")
SQL_JOB_REBODY = ("UPDATE export_job SET state = 'PENDING', reason = NULL, changed_at = ?, "
                  "fence = ? WHERE request_id = ?")
SQL_JOBS_BY_STATE = "SELECT request_id FROM export_job WHERE state = ? ORDER BY created_at"
SQL_JOBS_QUEUE = ("SELECT COUNT(*), COALESCE(SUM(LENGTH(body)), 0) FROM export_job "
                  "WHERE state IN ('PENDING', 'REVALIDATE', 'ACCEPTED', 'ENCODED', 'UNKNOWN')")
SQL_JOBS_ALL = ("SELECT request_id, state, reason, attempts, in_flight, fence FROM export_job "
                "ORDER BY created_at")


class StoreBindingMismatch(RuntimeError):
    """The store file was created for another channel binding."""


class Store:
    """One SQLite connection to one channel's file.

    `transaction()` is the only way to mutate: `BEGIN IMMEDIATE`, then `on_begin` (the lease's
    fence check, installed by `Lease`), then the body, then COMMIT. An `Exception` rolls back; a
    `BaseException` (a simulated crash) leaves the transaction open, as a process death would, and
    the caller closes the connection, which rolls it back.
    """

    def __init__(self, path: str, clock: Clock, faults: _faults.CrashPoints = _faults.NO_FAULTS,
                 *, busy_timeout: float = 2.0) -> None:
        self.path = path
        self.clock = clock
        self.faults = faults
        self.db = sqlite3.connect(path, isolation_level=None, timeout=busy_timeout)
        self.db.execute(SQL_PRAGMA_WAL)
        self.db.execute(SQL_PRAGMA_SYNC)
        self.db.execute(SQL_PRAGMA_FK)
        self.db.executescript(SQL_CREATE)
        self.on_begin = None
        self.fence = 0
        self.commit_failed = False

    def close(self) -> None:
        self.db.close()

    def bind(self, binding: str) -> None:
        """Record (first open) or check (every later open) the channel binding of this file."""
        with self.transaction(fenced=False):
            row = self.db.execute(SQL_META_GET, ("binding",)).fetchone()
            if row is None:
                self.db.execute(SQL_META_PUT, ("binding", binding))
                self.db.execute(SQL_META_PUT, ("store_schema", SCHEMA_VERSION))
                self.db.execute(SQL_CHANNEL_INIT, (CHANNEL, 0))
            elif row[0] != binding:
                raise StoreBindingMismatch("the store file belongs to another channel binding")

    @contextlib.contextmanager
    def transaction(self, *, fenced: bool = True) -> Iterator[sqlite3.Connection]:
        self.db.execute(SQL_BEGIN)
        try:
            if fenced and self.on_begin is not None:
                self.on_begin(self.db)
            yield self.db
        except Exception:
            self.db.execute(SQL_ROLLBACK)
            raise
        if self.faults.flag("store.commit_fails"):
            self.db.execute(SQL_ROLLBACK)
            self.commit_failed = True
            raise sqlite3.OperationalError("simulated durable commit failure")
        self.db.execute(SQL_COMMIT)
        self.commit_failed = False

    def now(self) -> int:
        return now_ms(self.clock)

    def counter_add(self, name: str, value: int = 1) -> None:
        self.db.execute(SQL_COUNTER_ADD, (name, value))

    def counters(self) -> dict[str, int]:
        return dict(self.db.execute(SQL_COUNTERS).fetchall())

    def query(self, sql: str, params: tuple = ()) -> list[tuple]:
        return self.db.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple = ()) -> Any:
        return self.db.execute(sql, params).fetchone()

    def channel(self) -> dict:
        row = self.db.execute(SQL_CHANNEL_GET, (CHANNEL,)).fetchone()
        keys = ("cursor", "acked_cursor", "session_id", "state", "state_reason", "degraded",
                "epoch", "earliest_cursor", "stopped_revision", "retry_sha", "retry_count",
                "committed_any", "gap_from", "gap_to", "incomplete")
        return dict(zip(keys, row))

    def read_raw_evidence(self, batch_sha256: str) -> bytes | None:
        """The raw batch octets. Called ONLY by the CLI's `evidence` command (REQ151: raw evidence
        access is controlled separately from the application's logs and outputs)."""
        row = self.db.execute(SQL_RAW_GET, (batch_sha256,)).fetchone()
        return None if row is None else row[0]
