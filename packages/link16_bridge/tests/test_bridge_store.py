"""The durable store: pragmas, the channel binding, transactions, the commit-failure fault and
the fence on every mutated row (REQ100, REQ141, REQ151)."""
import sqlite3

import pytest

from helpers import report
from synapse_link16_bridge import faults
from synapse_link16_bridge.clock import ManualClock
from synapse_link16_bridge.store import (SQL_COUNTER_GET, SQL_META_GET, SQL_META_PUT, Store,
                                         StoreBindingMismatch)


@pytest.fixture
def store(tmp_path):
    opened = Store(str(tmp_path / "s.sqlite"), ManualClock())
    yield opened
    opened.close()


def test_wal_full_sync_and_foreign_keys(store):
    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.db.execute("PRAGMA synchronous").fetchone()[0] == 2
    assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_the_file_is_bound_to_one_channel(store, tmp_path):
    store.bind('["gw","t","r",true,"ctx","consumer"]')
    store.bind('["gw","t","r",true,"ctx","consumer"]')
    with pytest.raises(StoreBindingMismatch):
        store.bind('["gw","t","OTHER",true,"ctx","consumer"]')
    assert store.channel()["state"] == "NORMAL" and store.channel()["epoch"] == 0


def test_an_exception_rolls_the_transaction_back(store):
    with pytest.raises(ValueError):
        with store.transaction(fenced=False) as db:
            db.execute(SQL_META_PUT, ("k", "v"))
            raise ValueError("abort")
    assert store.db.execute(SQL_META_GET, ("k",)).fetchone() is None
    assert not store.db.in_transaction


def test_a_failed_durable_commit_keeps_nothing_and_is_reported(tmp_path):
    fault = faults.CrashPoints(flags={"store.commit_fails"})
    opened = Store(str(tmp_path / "f.sqlite"), ManualClock(), fault)
    try:
        with pytest.raises(sqlite3.OperationalError):
            with opened.transaction(fenced=False) as db:
                db.execute(SQL_META_PUT, ("k", "v"))
        assert opened.commit_failed
        assert opened.db.execute(SQL_META_GET, ("k",)).fetchone() is None
        fault.clear("store.commit_fails")
        with opened.transaction(fenced=False) as db:
            db.execute(SQL_META_PUT, ("k", "v"))
        assert not opened.commit_failed
    finally:
        opened.close()


def test_a_simulated_crash_leaves_the_transaction_open_and_closing_rolls_it_back(tmp_path):
    path = str(tmp_path / "c.sqlite")
    first = Store(path, ManualClock())
    with pytest.raises(faults.SimulatedCrash):
        with first.transaction(fenced=False) as db:
            db.execute(SQL_META_PUT, ("k", "v"))
            raise faults.SimulatedCrash("ingest.before_commit")
    assert first.db.in_transaction
    first.close()
    second = Store(path, ManualClock())
    try:
        assert second.db.execute(SQL_META_GET, ("k",)).fetchone() is None
    finally:
        second.close()


def test_counters_add(store):
    with store.transaction(fenced=False):
        store.counter_add("accepted")
        store.counter_add("accepted", 2)
    assert store.db.execute(SQL_COUNTER_GET, ("accepted",)).fetchone()[0] == 3
    assert store.counters() == {"accepted": 3}


FENCES = {
    "raw_batch": "SELECT DISTINCT fence FROM raw_batch",
    "ingest": "SELECT DISTINCT fence FROM ingest",
    "identity": "SELECT DISTINCT fence FROM identity",
    "observation": "SELECT DISTINCT fence FROM observation",
    "current": "SELECT DISTINCT fence FROM current",
    "outbox": "SELECT DISTINCT fence FROM outbox",
    "channel": "SELECT DISTINCT fence FROM channel",
}


def test_every_mutated_row_records_the_fence(h):
    h.publish(report(1))
    h.publish(report(2, base="land_unknown_position.json", track_number="L-2"))
    h.run()
    assert h.bridge.lease.fence == 1
    for table, query in FENCES.items():
        assert {row[0] for row in h.bridge.store.db.execute(query)} == {1}, table
