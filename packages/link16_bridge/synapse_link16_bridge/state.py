"""History and current state per source identity (REQ033, REQ101, REQ102).

Every accepted report is an observation in history, and history is never deleted. The current
state of an identity moves only to a strictly newer `effective_at`:

- an older `effective_at` is late history (`late`, outbox flag `LATE`) and never rolls current
  state back;
- an equal `effective_at` with an identical state is a refresh (flag `REFRESH`), and current
  state does not move;
- an equal `effective_at` with a different state is a conflict: a `conflict` row, the conflicting
  observation kept and published with flag `CONFLICT`, and the established current state kept.

The identical state of two reports (the bridge's definition) is the SHA-256 of the canonical JSON
of the report without its delivery and provenance keys (`record_id`, `gateway_id`, `session_id`,
`sequence`, `received_at`, `reporter`, `time_evidence`). Report order, receive time and source
time are independent: only `effective_at` orders state.

Samples (REQ033): a repeated position sample of one identity at one `position.observed_at` is
idempotent (one `sample` row, its refresh count raised); a different position at the same instant
is kept as a `sample_conflict`. Outbox events are keyed `record_id:index` (0 the Entity, 1 the
Track), so a redelivered record never publishes a second time (REQ100).
"""
from __future__ import annotations

import json

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.clock import parse_ms
from synapse_link16_bridge.store import (SQL_CONFLICT_INSERT, SQL_CURRENT_CONFLICT,
                                         SQL_CURRENT_GET, SQL_CURRENT_PUT, SQL_LAST_ROWID,
                                         SQL_OBSERVATION_INSERT, SQL_OUTBOX_INSERT,
                                         SQL_SAMPLE_CONFLICT, SQL_SAMPLE_GET, SQL_SAMPLE_INSERT,
                                         SQL_SAMPLE_REFRESH, Store)

PROVENANCE_KEYS = ("record_id", "gateway_id", "session_id", "sequence", "received_at",
                   "reporter", "time_evidence")


def state_sha256(report: dict) -> str:
    stripped = {key: value for key, value in report.items() if key not in PROVENANCE_KEYS}
    return jsonstrict.sha256_hex(jsonstrict.canonical(stripped))


def publish(store: Store, event_key: str, kind: str, payload: bytes, schema_version: str | None,
            flags: list[str]) -> None:
    store.db.execute(SQL_OUTBOX_INSERT, (event_key, kind, payload, schema_version,
                                         json.dumps(sorted(set(flags))), len(payload),
                                         store.now(), store.fence))


def apply(store: Store, key: str, report: dict, objects: list, *, force_late: bool,
          flags: list[str]) -> str | None:
    """Record one accepted report inside the open transaction. Returns its state flag (`LATE`,
    `REFRESH`, `CONFLICT`) or None when current state moved to it."""
    record_id = report["record_id"]
    effective_at = parse_ms(report["effective_at"], "effective_at")
    position, motion = report["position"], report["kinematics"]
    pos_at = None if position is None else parse_ms(position["observed_at"], "position")
    kin_at = None if motion is None else parse_ms(motion["observed_at"], "kinematics")
    digest = state_sha256(report)
    entity_payload = jsonstrict.canonical(objects[0].model_dump(mode="json"))
    current = store.db.execute(SQL_CURRENT_GET, (key,)).fetchone()
    flag, conflict_id, late = None, None, 0
    if current is None and not force_late:
        store.db.execute(SQL_CURRENT_PUT, (key, record_id, effective_at, digest, pos_at, kin_at,
                                           report["domain"], entity_payload, store.fence))
    elif force_late or effective_at < current[2]:
        flag, late = "LATE", 1
    elif effective_at == current[2]:
        if digest == current[3]:
            flag = "REFRESH"
        else:
            flag = "CONFLICT"
            store.db.execute(SQL_CONFLICT_INSERT, (key, effective_at, current[1], record_id))
            conflict_id = store.db.execute(SQL_LAST_ROWID).fetchone()[0]
            store.db.execute(SQL_CURRENT_CONFLICT, (conflict_id, store.fence, key))
    else:
        store.db.execute(SQL_CURRENT_PUT, (key, record_id, effective_at, digest, pos_at, kin_at,
                                           report["domain"], entity_payload, store.fence))
    store.db.execute(SQL_OBSERVATION_INSERT, (key, record_id, effective_at, pos_at, kin_at,
                                              digest, late, flag, conflict_id, store.now(),
                                              store.fence))
    if position is not None:
        sample = jsonstrict.sha256_hex(jsonstrict.canonical(position))
        known = store.db.execute(SQL_SAMPLE_GET, (key, pos_at)).fetchone()
        if known is None:
            store.db.execute(SQL_SAMPLE_INSERT, (key, pos_at, sample, record_id))
        elif known[0] == sample:
            store.db.execute(SQL_SAMPLE_REFRESH, (key, pos_at))
        else:
            store.db.execute(SQL_SAMPLE_CONFLICT, (key, pos_at, record_id, sample))
    event_flags = list(flags) + ([flag] if flag else [])
    for index, obj in enumerate(objects):
        payload = jsonstrict.canonical(obj.model_dump(mode="json"))
        publish(store, f"{record_id}:{index}", "cdm", payload, obj.schema_version, event_flags)
    store.counter_add("accepted")
    if late:
        store.counter_add("late")
    return flag
