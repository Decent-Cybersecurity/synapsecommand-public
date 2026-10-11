"""The exclusive channel-writer lease and its fencing token (REQ140, REQ141).

One row per channel: the holder, a monotonically increasing `fence`, and an expiry on the
injected clock. `acquire` takes the lease when it is free or expired, adding one to the fence;
`renew` extends it; `check` runs first inside every mutation transaction (installed as the store's
`on_begin`) and raises `LeaseLost` unless this instance still holds the lease at its own fence
and before expiry, so a holder that lost the lease can neither mutate nor send. Every mutated
row records the fence.

When a holder acquires the lease with a higher fence, every export job of a lower fence that was
queued (`PENDING` or `ACCEPTED`) moves to `REVALIDATE` and cannot be sent until policy, expiry,
freshness and allocation are checked again; a job whose POST may already have left (`in_flight`)
moves to `UNKNOWN` and is reconciled, never re-sent blindly (REQ097). Gateway idempotency by
`request_id` is still used for every send, because fencing cannot prove whether a remote write
already happened.
"""
from __future__ import annotations

import sqlite3

from synapse_link16_bridge.store import (CHANNEL, SQL_JOBS_INFLIGHT_UNKNOWN, SQL_JOBS_REVALIDATE,
                                         SQL_LEASE_EXPIRE, SQL_LEASE_GET, SQL_LEASE_INSERT,
                                         SQL_LEASE_UPDATE, Store)


class LeaseLost(RuntimeError):
    """This instance does not hold the channel-writer lease (any more)."""


class LeaseHeld(RuntimeError):
    """Another holder holds an unexpired lease."""


class Lease:
    def __init__(self, store: Store, holder: str, ttl_seconds: float) -> None:
        self.store = store
        self.holder = holder
        self.ttl_ms = int(ttl_seconds * 1000)
        self.fence = 0
        self.held = False

    def acquire(self) -> int:
        """Take the lease or raise `LeaseHeld`. Returns the new fence."""
        store = self.store
        with store.transaction(fenced=False) as db:
            now = store.now()
            row = db.execute(SQL_LEASE_GET, (CHANNEL,)).fetchone()
            if row is not None and row[0] != self.holder and row[2] > now:
                raise LeaseHeld("the channel-writer lease is held by another instance")
            fence = 1 if row is None else row[1] + 1
            if row is None:
                db.execute(SQL_LEASE_INSERT, (CHANNEL, self.holder, fence, now + self.ttl_ms))
            else:
                db.execute(SQL_LEASE_UPDATE, (self.holder, fence, now + self.ttl_ms, CHANNEL))
            db.execute(SQL_JOBS_INFLIGHT_UNKNOWN, (now, fence, fence))
            db.execute(SQL_JOBS_REVALIDATE, (now, fence, fence))
        self.fence = fence
        self.held = True
        store.fence = fence
        store.on_begin = self.check
        return fence

    def check(self, db: sqlite3.Connection) -> None:
        """Inside a transaction: this instance must hold the lease at its fence, unexpired."""
        if self.store.faults.flag("lease.expire_now"):
            self.held = False                   # a lease this instance can no longer prove
        row = db.execute(SQL_LEASE_GET, (CHANNEL,)).fetchone()
        if not self.held or row is None or row[0] != self.holder or row[1] != self.fence or \
                row[2] <= self.store.now():
            self.held = False
            raise LeaseLost("the channel-writer lease is lost; sends are disabled")

    def renew(self) -> None:
        with self.store.transaction() as db:
            db.execute(SQL_LEASE_UPDATE, (self.holder, self.fence,
                                          self.store.now() + self.ttl_ms, CHANNEL))

    def release(self) -> None:
        """Give the lease up (expire it now) if this instance still holds it."""
        if not self.held:
            return
        try:
            with self.store.transaction() as db:
                db.execute(SQL_LEASE_EXPIRE, (0, CHANNEL))
        except LeaseLost:
            pass
        self.held = False
