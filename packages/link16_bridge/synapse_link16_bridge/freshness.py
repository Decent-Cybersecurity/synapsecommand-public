"""Host freshness of a source contribution (REQ103, REQ104).

Display policy, not a Link 16 timeout. Thresholds per domain from the configuration (defaults 30 s
AIR, 120 s SURFACE, SUBSURFACE, LAND and UNKNOWN); the domain is the report's, never inferred. Age
is measured on the injected clock from `position.observed_at` for a positioned state and from
`effective_at` for a positionless one; motion age, from `kinematics.observed_at`, is tracked
separately. At an age equal to the threshold the state is STALE, at four times the threshold
EXPIRED, and at a negative age below minus five seconds TIME_SKEW (egress blocked). A future
time is not fresher indefinitely: its age grows with the clock like any other. Freshness hides or
styles a contribution; it never deletes history, never advances an incarnation and never issues
a drop. Changes of status are published as `freshness` events.
"""
from __future__ import annotations

from synapse_link16_bridge import jsonstrict
from synapse_link16_bridge.store import (SQL_CURRENT_ALL, SQL_CURRENT_FRESHNESS,
                                         SQL_OUTBOX_INSERT, Store)

ACTIVE, STALE, EXPIRED, TIME_SKEW = "ACTIVE", "STALE", "EXPIRED", "TIME_SKEW"
SKEW_MS = 5000


def status(now: int, observed_at: int, threshold_seconds: float) -> str:
    age = now - observed_at
    if age < -SKEW_MS:
        return TIME_SKEW
    threshold = threshold_seconds * 1000.0
    if age >= 4 * threshold:
        return EXPIRED
    if age >= threshold:
        return STALE
    return ACTIVE


def of_current(row: tuple, now: int, thresholds: dict) -> tuple[str, str | None]:
    """(status, motion status) of one `current` row (SQL_CURRENT_GET's column order)."""
    _key, _record, effective_at, _sha, pos_at, kin_at, domain = row[:7]
    threshold = thresholds[domain]
    main = status(now, pos_at if pos_at is not None else effective_at, threshold)
    motion = None if kin_at is None else status(now, kin_at, threshold)
    return main, motion


def evaluate(store: Store, thresholds: dict) -> list[tuple[str, str, str | None]]:
    """Recompute every open contribution's status inside the open transaction; publish and
    store each change. Returns the changes as (identity key, status, motion status)."""
    now = store.now()
    changes = []
    for row in store.db.execute(SQL_CURRENT_ALL).fetchall():
        key, record_id, contribution, stored, stored_motion = row[0], row[1], row[7], row[9], \
            row[10]
        if contribution != "ACTIVE":
            continue
        main, motion = of_current(row, now, thresholds)
        if (main, motion) == (stored, stored_motion):
            continue
        store.db.execute(SQL_CURRENT_FRESHNESS, (main, motion, store.fence, key))
        if main == TIME_SKEW and stored != TIME_SKEW:
            store.counter_add("time_skew")
        payload = jsonstrict.canonical({"identity_key": key, "record_id": record_id,
                                        "status": main, "motion_status": motion})
        store.db.execute(SQL_OUTBOX_INSERT, (
            f"{record_id}:freshness:{main}:{motion or 'NONE'}", "freshness", payload, None,
            "[]", len(payload), now, store.fence))
        changes.append((key, main, motion))
    return changes
