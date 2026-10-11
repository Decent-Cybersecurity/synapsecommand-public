"""The synthetic provider: the gateway side of the API for the synthetic profile only.

It keeps its own SQLite file (the gateway and the bridge are separate components): a channel log
the report endpoint serves, per-channel cursors and acknowledgements, retention with explicit loss
accounting, and the transmission idempotency records and send log. It implements the REQ110
operations for the synthetic profile so that the native boundary's protocol has a structural
counterpart, and it never claims a native behaviour: `encode` is the canonical JSON of a report
the adapter accepts (no quantisation), `send` appends to a local log, and no state beyond `SENT`
is ever produced (no `DELIVERY_CONFIRMED`: the synthetic transport has no peer acknowledgement).

DELIVERY (REQ051, REQ063, REQ064)
---------------------------------
Each committed report or notice gets a `position` in its channel and, per session, a `sequence`
that adds one per record and never wraps: after 2^64-1 the next record opens a new session at 0.
A batch never spans a session change. The cursor is the opaque text `"{epoch}.{position}"`;
`after=c` returns the records strictly after `c` (the reading of the specification's "inclusive
contents after the opaque committed cursor": the committed record is not delivered twice). A
cursor of another epoch or not of this form is `CURSOR_FOREIGN`, one beyond the last delivered
position `CURSOR_FUTURE`, one below the earliest retained record `CURSOR_EXPIRED` (410) with the
earliest cursor. Unacknowledged records are kept 24 hours on the injected clock or until the
channel's byte bound (default 10 GiB); past either they are discarded with a loss row, never
silently.

TRANSMISSIONS (REQ062, REQ096, REQ097)
--------------------------------------
Idempotency by `request_id` for 24 hours (`replay_window_seconds` = 86400): the same id and the
same canonical body answer the current status and send nothing again; a different body is 409
`REQUEST_ID_CONFLICT`. A report whose `native_profile` this gateway does not offer is 409
`PROFILE_MISMATCH`; an expired request is 422 `REQUEST_EXPIRED` and is recorded `EXPIRED`, which can
never become `SENT`; a report the adapter refuses is 400 (schema or JSON) or 422 (semantic); a
report whose `synthetic` is false is 422 `SYNTHETIC_MISMATCH`.

FAULT KNOBS (constructor or attribute; tests only, no environment): `unavailable` (503),
`capacity_full` (429), `hold_response_seconds` (the server withholds the 202 after a send),
`hold_ack_response_seconds` (the server applies an acknowledgement and withholds its 200),
`retention_bytes`, `skip_sequence`, `inject_record`.
"""
from __future__ import annotations

import dataclasses
import re
import sqlite3
import threading
import uuid
from typing import Any, Callable

from synapse_cdm.adapter import InputTooDeep, InputTooLarge
from synapse_cdm.adapters.link16_gateway import Link16GatewayAdapter, Link16GatewayRefusal

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.clock import Clock, now_ms, parse_ms, render_ms
from synapse_link16_bridge.contract import (PROFILE, ContractError, validate_ack,
                                            validate_transmission)

UINT64_MAX = 2 ** 64 - 1
RETENTION_SECONDS = 24 * 3600
DEFAULT_RETENTION_BYTES = 10 * 1024 ** 3
REPLAY_WINDOW_SECONDS = 24 * 3600
_CURSOR = re.compile(r"([0-9]{1,18})\.([0-9]{1,18})")

#: The fixed error table: code -> (HTTP status, message). `retryable` is true for 429 and 503
#: only (REQ062). Messages are fixed text, never a payload value or an exception's words.
ERRORS = {
    "JSON_INVALID": (400, "The request body is not strict JSON."),
    "SCHEMA_INVALID": (400, "The request does not satisfy the API contract."),
    "UNAUTHENTICATED": (401, "Authentication is required."),
    "FORBIDDEN": (403, "The credential is not authorised for this channel or consumer."),
    "NOT_FOUND": (404, "No such resource."),
    "REQUEST_ID_CONFLICT": (409, "The request_id was used with a different body."),
    "PROFILE_MISMATCH": (409, "The native profile is not offered by this gateway."),
    "CURSOR_EXPIRED": (410, "The cursor is older than the earliest retained record."),
    "LIMIT_EXCEEDED": (413, "The body exceeds the size limit."),
    "CURSOR_FUTURE": (422, "The cursor is beyond the last cursor delivered."),
    "CURSOR_FOREIGN": (422, "The cursor belongs to another channel or epoch."),
    "REQUEST_EXPIRED": (422, "The request expired before it was accepted."),
    "SYNTHETIC_MISMATCH": (422, "The report's synthetic flag differs from this gateway's."),
    "TIME_UNRESOLVED": (422, "The report carries a time that cannot be resolved."),
    "VALUE_NOT_REPRESENTABLE": (422, "The report carries a value the profile cannot encode."),
    "CAPACITY": (429, "Capacity is exhausted; retry later."),
    "PROVIDER_UNAVAILABLE": (503, "The provider is unavailable; retry later."),
}

SQL_P_CREATE = """
CREATE TABLE IF NOT EXISTS p_channel (channel TEXT PRIMARY KEY, epoch INTEGER NOT NULL,
    session_id TEXT NOT NULL, next_sequence TEXT NOT NULL, head INTEGER NOT NULL,
    floor INTEGER NOT NULL, delivered INTEGER NOT NULL, acked INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS p_log (channel TEXT NOT NULL, position INTEGER NOT NULL,
    session_id TEXT NOT NULL, kind TEXT NOT NULL, body BLOB NOT NULL, bytes INTEGER NOT NULL,
    committed_at INTEGER NOT NULL, PRIMARY KEY (channel, position));
CREATE TABLE IF NOT EXISTS p_loss (id INTEGER PRIMARY KEY AUTOINCREMENT, channel TEXT NOT NULL,
    from_position INTEGER NOT NULL, to_position INTEGER NOT NULL, count INTEGER NOT NULL,
    bytes INTEGER NOT NULL, reason TEXT NOT NULL, at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS p_idem (request_id TEXT PRIMARY KEY, channel TEXT NOT NULL,
    body_sha256 TEXT NOT NULL, received_at INTEGER NOT NULL, state TEXT NOT NULL, reason TEXT,
    changed_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS p_sent (id INTEGER PRIMARY KEY AUTOINCREMENT, request_id TEXT NOT NULL,
    peer_id TEXT NOT NULL, encoded BLOB NOT NULL, at INTEGER NOT NULL);
"""
SQL_P_CHANNEL_INIT = ("INSERT OR IGNORE INTO p_channel (channel, epoch, session_id, "
                      "next_sequence, head, floor, delivered, acked) VALUES (?, ?, ?, ?, 0, 0, 0, 0)")
SQL_P_CHANNEL_GET = ("SELECT epoch, session_id, next_sequence, head, floor, delivered, acked "
                     "FROM p_channel WHERE channel = ?")
SQL_P_CHANNEL_SEQ = ("UPDATE p_channel SET session_id = ?, next_sequence = ?, head = ? "
                     "WHERE channel = ?")
SQL_P_CHANNEL_SESSION = "UPDATE p_channel SET session_id = ?, next_sequence = ? WHERE channel = ?"
SQL_P_CHANNEL_FLOOR = "UPDATE p_channel SET floor = ? WHERE channel = ?"
SQL_P_CHANNEL_DELIVERED = "UPDATE p_channel SET delivered = ? WHERE channel = ?"
SQL_P_CHANNEL_ACKED = "UPDATE p_channel SET acked = ? WHERE channel = ?"
SQL_P_LOG_INSERT = ("INSERT INTO p_log (channel, position, session_id, kind, body, bytes, "
                    "committed_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
SQL_P_LOG_AFTER = ("SELECT position, session_id, kind, body FROM p_log WHERE channel = ? "
                   "AND position > ? ORDER BY position LIMIT ?")
SQL_P_LOG_MORE = "SELECT COUNT(*) FROM p_log WHERE channel = ? AND position > ?"
SQL_P_LOG_UNACKED = ("SELECT position, bytes, committed_at FROM p_log WHERE channel = ? "
                     "AND position > ? ORDER BY position")
SQL_P_LOG_DROP_UPTO = "DELETE FROM p_log WHERE channel = ? AND position <= ?"
SQL_P_LOG_OLDEST = ("SELECT MIN(committed_at), COUNT(*) FROM p_log WHERE channel = ? "
                    "AND position > ?")
SQL_P_LOSS_INSERT = ("INSERT INTO p_loss (channel, from_position, to_position, count, bytes, "
                     "reason, at) VALUES (?, ?, ?, ?, ?, ?, ?)")
SQL_P_LOSS_ALL = ("SELECT channel, from_position, to_position, count, bytes, reason FROM p_loss "
                  "ORDER BY id")
SQL_P_IDEM_GET = ("SELECT channel, body_sha256, state, reason, changed_at FROM p_idem "
                  "WHERE request_id = ?")
SQL_P_IDEM_PUT = ("INSERT OR REPLACE INTO p_idem (request_id, channel, body_sha256, received_at, "
                  "state, reason, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)")
SQL_P_IDEM_STATE = "UPDATE p_idem SET state = ?, reason = ?, changed_at = ? WHERE request_id = ?"
SQL_P_IDEM_PRUNE = "DELETE FROM p_idem WHERE received_at < ?"
SQL_P_SENT_INSERT = "INSERT INTO p_sent (request_id, peer_id, encoded, at) VALUES (?, ?, ?, ?)"
SQL_P_SENT_ALL = "SELECT request_id, peer_id, encoded FROM p_sent ORDER BY id"


class ApiError(Exception):
    """A refusal the API answers with an error body; `code` is a key of `ERRORS`."""

    def __init__(self, code: str, earliest_cursor: str | None = None) -> None:
        self.code = code
        self.status = ERRORS[code][0]
        self.earliest_cursor = earliest_cursor
        super().__init__(code)


@dataclasses.dataclass(frozen=True)
class Reply:
    """A successful answer: the HTTP status and the JSON body as octets."""

    status: int
    body: bytes


class SyntheticProvider:
    """The synthetic gateway. Thread-safe: one lock around the provider's own connection."""

    def __init__(self, clock: Clock, *, gateway_id: str = "synthetic-gateway-1",
                 native_profiles: tuple[str, ...] = ("SYNTHETIC-NO-NATIVE-CODEC",),
                 receive_families: tuple[str, ...] = ("J3.2", "J3.3", "J3.4", "J3.5"),
                 transmit_families: tuple[str, ...] = ("J3.2", "J3.3", "J3.4", "J3.5"),
                 max_batch: int = 1000, path: str = ":memory:", synthetic: bool = True,
                 retention_bytes: int = DEFAULT_RETENTION_BYTES, start_sequence: int = 0,
                 uuid_factory: Callable[[], uuid.UUID] = uuid.uuid4,
                 unavailable: bool = False, capacity_full: bool = False,
                 hold_response_seconds: float = 0.0,
                 hold_ack_response_seconds: float = 0.0) -> None:
        self.clock = clock
        self.gateway_id = gateway_id
        self.native_profiles = tuple(native_profiles)
        self.receive_families = tuple(receive_families)
        self.transmit_families = tuple(transmit_families)
        self.max_batch = max_batch
        self.synthetic = synthetic
        self.retention_bytes = retention_bytes
        self.start_sequence = start_sequence
        self.uuid_factory = uuid_factory
        self.unavailable = unavailable
        self.capacity_full = capacity_full
        self.hold_response_seconds = hold_response_seconds
        self.hold_ack_response_seconds = hold_ack_response_seconds
        self.release_hold = threading.Event()
        self.lock = threading.RLock()
        self.arrived = threading.Condition(self.lock)
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.executescript(SQL_P_CREATE)
        self.adapter = Link16GatewayAdapter(clock, synthetic=synthetic)
        self.started_profile: Any = None
        self.stopped = False

    # ------------------------------------------------------------------ channels and feeding

    def add_channel(self, channel: str, *, epoch: int = 1) -> None:
        with self.lock:
            self.db.execute(SQL_P_CHANNEL_INIT, (channel, epoch, str(self.uuid_factory()),
                                                 str(self.start_sequence)))

    def _channel(self, channel: str) -> tuple:
        row = self.db.execute(SQL_P_CHANNEL_GET, (channel,)).fetchone()
        if row is None:
            raise ApiError("NOT_FOUND")
        return row

    def session(self, channel: str) -> tuple[str, int]:
        """The channel's current session id and the sequence its next record gets."""
        with self.lock:
            _epoch, session, next_sequence, *_ = self._channel(channel)
            return session, int(next_sequence)

    def new_session(self, channel: str) -> str:
        with self.lock:
            session = str(self.uuid_factory())
            self.db.execute(SQL_P_CHANNEL_SESSION, (session, "0", channel))
            return session

    def skip_sequence(self, channel: str, count: int = 1) -> None:
        """A delivery discontinuity: the next `count` sequence numbers are never published."""
        with self.lock:
            _epoch, session, next_sequence, head, *_ = self._channel(channel)
            self.db.execute(SQL_P_CHANNEL_SEQ, (session, str(int(next_sequence) + count), head,
                                                channel))

    def publish(self, channel: str, kind: str, body: dict, *, stamp: bool = True) -> int:
        """Commit one report or notice to the channel log. With `stamp`, the record's
        `session_id` and `sequence` are the channel's (a new session opens instead of a wrap)."""
        with self.lock:
            _epoch, session, next_sequence, head, *_ = self._channel(channel)
            sequence = int(next_sequence)
            if sequence > UINT64_MAX:
                session, sequence = str(self.uuid_factory()), 0
            if stamp:
                body = dict(body, session_id=session, sequence=str(sequence))
            octets = jsonstrict.canonical(body)
            return self._append(channel, kind, octets, session, sequence + 1, head)

    def inject_record(self, channel: str, kind: str, octets: bytes, *,
                      session_id: str | None = None) -> int:
        """Commit raw body octets as they are (a malformed or hostile body). The sequence
        counter does not move."""
        with self.lock:
            _epoch, session, next_sequence, head, *_ = self._channel(channel)
            return self._append(channel, kind, bytes(octets), session_id or session,
                                int(next_sequence), head, keep_session=session)

    def _append(self, channel: str, kind: str, octets: bytes, session: str, next_sequence: int,
                head: int, keep_session: str | None = None) -> int:
        position = head + 1
        now = now_ms(self.clock)
        self.db.execute(SQL_P_LOG_INSERT, (channel, position, session, kind, octets, len(octets),
                                           now))
        self.db.execute(SQL_P_CHANNEL_SEQ, (keep_session or session, str(next_sequence),
                                            position, channel))
        self._retain(channel)
        self.arrived.notify_all()
        return position

    # ------------------------------------------------------------------ retention

    def _retain(self, channel: str) -> None:
        """Drop acknowledged records; drop unacknowledged ones past 24 hours or past the byte
        bound, oldest first, each with a loss row. Never a silent skip."""
        now = now_ms(self.clock)
        _epoch, _session, _seq, _head, floor, _delivered, acked = self._channel(channel)
        before = floor
        if acked > floor:
            self.db.execute(SQL_P_LOG_DROP_UPTO, (channel, acked))
            floor = acked
        rows = self.db.execute(SQL_P_LOG_UNACKED, (channel, floor)).fetchall()
        total = sum(row[1] for row in rows)
        lost: dict[str, list] = {}
        new_floor = floor
        for position, size, committed_at in rows:
            if now - committed_at >= RETENTION_SECONDS * 1000:
                reason = "RETENTION_TIME"
            elif total > self.retention_bytes:
                reason = "RETENTION_BYTES"
            else:
                break
            total -= size
            entry = lost.setdefault(reason, [position, position, 0, 0])
            entry[1], entry[2], entry[3] = position, entry[2] + 1, entry[3] + size
            new_floor = position
        if new_floor > floor:
            self.db.execute(SQL_P_LOG_DROP_UPTO, (channel, new_floor))
            for reason, (first, last, count, size) in lost.items():
                self.db.execute(SQL_P_LOSS_INSERT, (channel, first, last, count, size, reason,
                                                    now))
            floor = new_floor
        if floor != before:
            self.db.execute(SQL_P_CHANNEL_FLOOR, (floor, channel))

    def losses(self, channel: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute(SQL_P_LOSS_ALL).fetchall()
        keys = ("channel", "from_position", "to_position", "count", "bytes", "reason")
        return [dict(zip(keys, row)) for row in rows if channel is None or row[0] == channel]

    # ------------------------------------------------------------------ the API operations

    def _gate(self) -> None:
        if self.unavailable:
            raise ApiError("PROVIDER_UNAVAILABLE")

    def capabilities_document(self) -> dict:
        self._gate()
        return {"profile": PROFILE, "gateway_id": self.gateway_id,
                "native_profiles": list(self.native_profiles),
                "receive_families": list(self.receive_families),
                "transmit_families": list(self.transmit_families),
                "max_batch": self.max_batch, "replay_window_seconds": REPLAY_WINDOW_SECONDS}

    def _cursor(self, channel: str, text: str) -> int:
        epoch, _s, _n, head, floor, delivered, _a = self._channel(channel)
        match = _CURSOR.fullmatch(text)
        if match is None or int(match.group(1)) != epoch:
            raise ApiError("CURSOR_FOREIGN")
        return int(match.group(2))

    def reports(self, channel: str, after: str | None, limit: int) -> Reply | None:
        """A batch, or None when nothing is there to deliver (the server may wait and ask
        again)."""
        with self.lock:
            self._gate()
            self._retain(channel)
            epoch, session, _n, head, floor, delivered, _acked = self._channel(channel)
            start = floor if after is None else self._cursor(channel, after)
            if start > head:
                raise ApiError("CURSOR_FUTURE")
            if start < floor:
                raise ApiError("CURSOR_EXPIRED", earliest_cursor=f"{epoch}.{floor}")
            rows = self.db.execute(SQL_P_LOG_AFTER, (channel, start, limit)).fetchall()
            if rows:
                first_session = rows[0][1]
                rows = [row for row in _same_session(rows, first_session)]
                session = first_session
            last = rows[-1][0] if rows else start
            more = self.db.execute(SQL_P_LOG_MORE, (channel, last)).fetchone()[0] > 0
            if last > delivered:
                self.db.execute(SQL_P_CHANNEL_DELIVERED, (last, channel))
            if not rows and after is not None:
                return None
            records = b",".join(b'{"kind":"' + row[2].encode("ascii") + b'","body":' + row[3] + b"}"
                                for row in rows)
            body = (b'{"session_id":"' + session.encode("ascii") + b'","records":[' + records +
                    b'],"next_cursor":"' + f"{epoch}.{last}".encode("ascii") +
                    b'","has_more":' + (b"true" if more else b"false") + b"}")
            return Reply(200, body)

    def empty_batch(self, channel: str, after: str | None) -> Reply:
        with self.lock:
            epoch, session, _n, head, floor, _d, _a = self._channel(channel)
            cursor = after if after is not None else f"{epoch}.{floor}"
            body = jsonstrict.canonical({"session_id": session, "records": [],
                                         "next_cursor": cursor, "has_more": False})
            return Reply(200, body)

    def ack(self, channel: str, bound_consumer: str, octets: bytes) -> Reply:
        with self.lock:
            self._gate()
            document = _strict(octets)
            try:
                validate_ack(document)
            except ContractError:
                raise ApiError("SCHEMA_INVALID") from None
            if document["consumer_id"] != bound_consumer:
                raise ApiError("FORBIDDEN")
            position = self._cursor(channel, document["cursor"])
            _e, _s, _n, _h, _f, delivered, acked = self._channel(channel)
            if position > delivered:
                raise ApiError("CURSOR_FUTURE")
            if position > acked:
                self.db.execute(SQL_P_CHANNEL_ACKED, (position, channel))
                self._retain(channel)
            return Reply(200, jsonstrict.canonical(document))

    def transmit(self, channel: str, octets: bytes) -> Reply:
        with self.lock:
            self._gate()
            if self.capacity_full:
                raise ApiError("CAPACITY")
            document = _strict(octets)
            try:
                validate_transmission(document)
            except ContractError as error:
                raise ApiError("JSON_INVALID" if error.code == "JSON_INVALID"
                               else "SCHEMA_INVALID") from None
            now = now_ms(self.clock)
            self.db.execute(SQL_P_IDEM_PRUNE, (now - REPLAY_WINDOW_SECONDS * 1000,))
            request_id = document["request_id"]
            digest = jsonstrict.sha256_hex(jsonstrict.canonical(document))
            known = self.db.execute(SQL_P_IDEM_GET, (request_id,)).fetchone()
            if known is not None:
                if known[0] != channel or known[1] != digest:
                    raise ApiError("REQUEST_ID_CONFLICT")
                return Reply(202, self._status_body(request_id))
            report = document["report"]
            if parse_ms(document["expires_at"], "expires_at") <= now:
                self.db.execute(SQL_P_IDEM_PUT, (request_id, channel, digest, now, "EXPIRED",
                                                 "REQUEST_EXPIRED", now))
                raise ApiError("REQUEST_EXPIRED")
            refusal = self._judge(report)
            if refusal is not None:
                self.db.execute(SQL_P_IDEM_PUT, (request_id, channel, digest, now, "REJECTED",
                                                 refusal, now))
                raise ApiError(refusal)
            self.db.execute(SQL_P_IDEM_PUT, (request_id, channel, digest, now, "ACCEPTED", None,
                                             now))
            encoded = self.encode(report, None)
            self.db.execute(SQL_P_IDEM_STATE, ("ENCODED", None, now, request_id))
            if parse_ms(document["expires_at"], "expires_at") <= now_ms(self.clock):
                self.db.execute(SQL_P_IDEM_STATE, ("EXPIRED", "REQUEST_EXPIRED",
                                                   now_ms(self.clock), request_id))
            else:
                self.db.execute(SQL_P_SENT_INSERT, (request_id, document["peer_id"], encoded,
                                                    now))
                self.db.execute(SQL_P_IDEM_STATE, ("SENT", None, now, request_id))
            return Reply(202, self._status_body(request_id))

    def _judge(self, report: dict) -> str | None:
        """The code a report is refused with, or None. Order: profile, then the contract."""
        profile = report.get("native_profile")
        if type(profile) is str and profile not in self.native_profiles:
            return "PROFILE_MISMATCH"
        try:
            self.adapter.to_cdm(jsonstrict.canonical(report))
        except Link16GatewayRefusal as refusal:
            if refusal.code in ("SCHEMA_INVALID", "JSON_INVALID"):
                return refusal.code
            return refusal.code if refusal.code in ERRORS else "SCHEMA_INVALID"
        except (InputTooLarge, InputTooDeep):
            return "LIMIT_EXCEEDED"
        if type(profile) is not str:
            return "SCHEMA_INVALID"
        return None

    def _status_body(self, request_id: str) -> bytes:
        _channel, _digest, state, reason, changed_at = self.db.execute(
            SQL_P_IDEM_GET, (request_id,)).fetchone()
        return jsonstrict.canonical({"request_id": request_id, "state": state, "reason": reason,
                                     "changed_at": render_ms(changed_at)})

    def transmission_status(self, channel: str, request_id: str) -> Reply:
        with self.lock:
            self._gate()
            row = self.db.execute(SQL_P_IDEM_GET, (request_id,)).fetchone()
            if row is None or row[0] != channel:
                raise ApiError("NOT_FOUND")
            return Reply(200, self._status_body(request_id))

    def health_document(self, channel: str) -> dict:
        with self.lock:
            ready = not self.unavailable and not self.stopped
            _e, _s, _n, _h, floor, _d, acked = self._channel(channel)
            oldest, depth = self.db.execute(SQL_P_LOG_OLDEST, (channel, max(acked, floor))
                                            ).fetchone()
            return {"ready": ready, "provider_ready": ready,
                    "blocked_reasons": [] if ready else ["PROVIDER_UNAVAILABLE"],
                    "queue_depth": depth,
                    "oldest_unacked_ms": None if oldest is None
                    else max(0, now_ms(self.clock) - oldest)}

    def sent(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(SQL_P_SENT_ALL).fetchall()
        return [{"request_id": r, "peer_id": p, "encoded": e} for r, p, e in rows]

    # ------------------------------------------------------------------ REQ110, synthetic

    def capabilities(self) -> dict:
        return self.capabilities_document()

    def start(self, peer_profile: Any) -> None:
        """The synthetic profile has no peer: only `None` is accepted."""
        if peer_profile is not None:
            raise ValueError("the synthetic provider takes no peer profile")
        self.started_profile = peer_profile
        self.stopped = False

    def receive(self, channel: str = "default", after: str | None = None) -> list[tuple]:
        """Complete decoded records of the synthetic profile: (kind, body octets)."""
        with self.lock:
            start = 0 if after is None else self._cursor(channel, after)
            rows = self.db.execute(SQL_P_LOG_AFTER, (channel, start, self.max_batch)).fetchall()
            return [(row[2], bytes(row[3])) for row in rows]

    def encode(self, report: dict, destination_context: Any) -> bytes:
        """The synthetic profile's encoding: the canonical JSON of an accepted report."""
        return jsonstrict.canonical(report)

    def send(self, encoded: bytes) -> str:
        with self.lock:
            self.db.execute(SQL_P_SENT_INSERT, ("(direct)", "(direct)", bytes(encoded),
                                                now_ms(self.clock)))
            return "SENT"

    def status(self, request_id: str) -> str | None:
        with self.lock:
            row = self.db.execute(SQL_P_IDEM_GET, (request_id,)).fetchone()
            return None if row is None else row[2]

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.release_hold.set()
        with self.lock:
            self.db.close()


def _same_session(rows: list, session: str):
    for row in rows:
        if row[1] != session:
            return
        yield row


def _strict(octets: bytes) -> Any:
    try:
        return jsonstrict.loads(octets)
    except ContractError as error:
        raise ApiError("LIMIT_EXCEEDED" if error.code == "LIMIT_EXCEEDED"
                       else "JSON_INVALID") from None
