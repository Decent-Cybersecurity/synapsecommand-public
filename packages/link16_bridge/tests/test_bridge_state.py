"""History and current state (REQ102, T03, T04) and sample idempotency (REQ033, REQ122)."""
from helpers import report, uid
from synapse_link16_bridge.state import PROVENANCE_KEYS, state_sha256
from synapse_link16_bridge.store import (SQL_CONFLICT_ALL, SQL_OBSERVATION_COUNT,
                                         SQL_OBSERVATION_FOR, SQL_SAMPLE_CONFLICTS)

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
CURRENT = "SELECT record_id, effective_at, open_conflict_id FROM current WHERE identity_key = ?"
SAMPLE = "SELECT sample_sha256, first_record_id, refreshes FROM sample WHERE identity_key = ?"


def test_the_state_digest_ignores_delivery_and_provenance_only():
    base = report(1)
    assert PROVENANCE_KEYS == ("record_id", "gateway_id", "session_id", "sequence", "received_at",
                               "reporter", "time_evidence")
    moved = dict(base, record_id=uid(9), session_id=uid(8), sequence="7", reporter="R",
                 received_at="2026-10-04T13:00:00.000Z", time_evidence="other")
    assert state_sha256(moved) == state_sha256(base)
    assert state_sha256(dict(base, identity="HOSTILE")) != state_sha256(base)
    assert state_sha256(dict(base, quality_code=None)) != state_sha256(base)


def test_older_report_after_newer_is_late_history_and_current_does_not_move(h):
    h.publish(report(1, at_ms=10_000))
    h.publish(report(2, at_ms=5_000))
    h.run()
    assert h.rows(CURRENT, (KEY,)) == [(uid(1), 1791115210000, None)]
    assert h.rows(SQL_OBSERVATION_FOR, (KEY,)) == [(uid(1), 1791115210000, 0, None, None),
                                                   (uid(2), 1791115205000, 1, "LATE", None)]
    assert h.sink.events[f"{uid(2)}:0"][2] == ("LATE",)
    assert h.counters()["late"] == 1


def test_equal_time_conflicting_reports_keep_the_established_current(h):
    h.publish(report(1, at_ms=0))
    h.publish(report(2, at_ms=0, identity="HOSTILE"))
    h.run()
    assert h.rows(SQL_CONFLICT_ALL) == [(1, KEY, 1791115200000, uid(1), uid(2))]
    assert h.rows(CURRENT, (KEY,)) == [(uid(1), 1791115200000, 1)]
    assert h.rows(SQL_OBSERVATION_FOR, (KEY,))[1] == (uid(2), 1791115200000, 0, "CONFLICT", 1)
    assert h.sink.events[f"{uid(2)}:0"][2] == ("CONFLICT",)


def test_equal_time_identical_state_is_a_refresh(h):
    h.publish(report(1, at_ms=0))
    h.publish(report(2, at_ms=0, reporter="ANOTHER-RELAY"))
    h.run()
    assert h.rows(SQL_CONFLICT_ALL) == []
    assert h.rows(CURRENT, (KEY,)) == [(uid(1), 1791115200000, None)]
    assert h.sink.events[f"{uid(2)}:0"][2] == ("REFRESH",)


def test_a_newer_report_moves_current_state(h):
    h.publish(report(1, at_ms=0))
    h.publish(report(2, at_ms=1))
    h.run()
    assert h.rows(CURRENT, (KEY,)) == [(uid(2), 1791115200001, None)]


def test_repeated_sample_is_idempotent_at_the_history_sink(h):
    h.publish(report(1, at_ms=0))
    second = report(2, at_ms=0)
    second["effective_at"] = "2026-10-04T12:00:02.000Z"
    h.publish(second)
    h.run()
    assert [(r[1], r[2]) for r in h.rows(SAMPLE, (KEY,))] == [(uid(1), 1)]
    assert h.rows(SQL_SAMPLE_CONFLICTS) == []


def test_conflicting_sample_at_one_instant_is_retained(h):
    h.publish(report(1, at_ms=0))
    moved = report(2, at_ms=0)
    moved["effective_at"] = "2026-10-04T12:00:02.000Z"
    moved["position"]["lat_deg"] = 48.2
    h.publish(moved)
    h.run()
    assert [(r[1], r[2]) for r in h.rows(SAMPLE, (KEY,))] == [(uid(1), 0)]
    assert h.rows(SQL_SAMPLE_CONFLICTS) == [(KEY, 1791115200000, uid(2))]


def test_new_record_id_with_identical_position_is_a_new_observation(h):
    """REQ101's last sentence: equal content under a new record id is not a duplicate."""
    h.publish(report(1, at_ms=0))
    h.publish(report(2, at_ms=1000))
    h.run()
    assert h.rows(SQL_OBSERVATION_COUNT) == [(2,)]
    assert h.counters().get("duplicate", 0) == 0


def test_durable_history_keeps_every_observation(h):
    """REQ122's durable half. The bridge keeps no in-memory sample cache (removed in A2F,
    2026-10-11: nothing read it, and it grew with every identity ever accepted), so the
    in-memory bound of 100 samples per identity holds with none kept."""
    for n in range(1, 6):
        h.publish(report(n, at_ms=n * 1000))
    h.run()
    assert h.rows(SQL_OBSERVATION_COUNT) == [(5,)]
    assert not hasattr(h.bridge, "samples") and not hasattr(h.bridge.ingestor, "samples")
