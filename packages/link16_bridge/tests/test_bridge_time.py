"""Time at the runtime: unresolved time (T01), clock skew (T02), freshness (REQ103, REQ104)."""
import pytest

from helpers import DEST_TUPLE, bidirectional, payload, report, uid
from synapse_link16_bridge import freshness
from synapse_link16_bridge.store import SQL_OPAQUE_ALL

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
STATUS = "SELECT freshness, motion_freshness FROM current WHERE identity_key = ?"


def test_time_unresolved_report_is_retained_opaque_with_no_canonical_track(h):
    hour_24 = report(1)
    hour_24["effective_at"] = "2026-10-04T24:00:00.000Z"
    impossible_day = report(2, track_number="T-2")
    impossible_day["position"]["observed_at"] = "2026-02-30T12:00:00.000Z"
    h.publish(hour_24)
    h.publish(impossible_day)
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("OPAQUE", "TIME_UNRESOLVED"),
                                                        ("OPAQUE", "TIME_UNRESOLVED")]
    assert result["acked"] is True
    assert [(r[0], r[1], r[2], r[4]) for r in h.rows(SQL_OPAQUE_ALL)] == [
        (uid(1), "report", "TIME_UNRESOLVED", 0), (uid(2), "report", "TIME_UNRESOLVED", 1)]
    assert {r[3] for r in h.rows(SQL_OPAQUE_ALL)} == {result["batch_sha256"]}
    assert h.sink.events == {}


@pytest.mark.parametrize("at_ms, expected", [(5001, "TIME_SKEW"), (5000, "ACTIVE"),
                                             (0, "ACTIVE")])
def test_future_effective_at_beyond_five_seconds_is_time_skew(h, at_ms, expected):
    h.publish(report(1, at_ms=at_ms))
    h.run()
    assert h.rows(STATUS, (KEY,)) == [(expected, expected)]
    assert h.counters().get("time_skew", 0) == (1 if expected == "TIME_SKEW" else 0)


def test_time_skew_denies_egress(make_harness):
    h = make_harness(**bidirectional())
    h.publish(report(1, at_ms=5001))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "provider allocation record 7")
    entity = payload(h.sink, f"{uid(1)}:0")
    from synapse_cdm.models import Entity
    result = h.bridge.export(Entity.model_validate(entity), None, peer_id="peer-1")
    assert (result["state"], result["reason"]) == ("DENIED", "TIME_SKEW")
    assert h.provider.sent() == []


def test_future_state_does_not_stay_fresh_indefinitely(h):
    h.publish(report(1, at_ms=4000))
    h.run()
    assert h.rows(STATUS, (KEY,)) == [("ACTIVE", "ACTIVE")]
    h.clock.advance(4 + 30)
    h.run()
    assert h.rows(STATUS, (KEY,)) == [("STALE", "STALE")]


@pytest.mark.parametrize("domain, threshold", [("AIR", 30), ("SURFACE", 120), ("SUBSURFACE", 120),
                                               ("LAND", 120), ("UNKNOWN", 120)])
@pytest.mark.parametrize("age_ms, expected", [
    (-5001, "TIME_SKEW"), (-5000, "ACTIVE"), (0, "ACTIVE"), ("T-1", "ACTIVE"), ("T", "STALE"),
    ("4T-1", "STALE"), ("4T", "EXPIRED")])
def test_stale_at_threshold_and_expired_at_four_times_per_domain(domain, threshold, age_ms,
                                                                 expected):
    from synapse_link16_bridge.config import DEFAULT_FRESHNESS
    assert DEFAULT_FRESHNESS[domain] == threshold
    age = {"T-1": threshold * 1000 - 1, "T": threshold * 1000, "4T-1": 4 * threshold * 1000 - 1,
           "4T": 4 * threshold * 1000}.get(age_ms, age_ms)
    assert freshness.status(1_000_000_000, 1_000_000_000 - age, threshold) == expected


def test_freshness_events_follow_the_clock_and_delete_nothing(h):
    h.publish(report(1))
    h.run()
    h.clock.advance(30)
    h.run()
    h.clock.advance(90)
    h.run()
    keys = sorted(k for k in h.sink.events if ":freshness:" in k)
    assert keys == [f"{uid(1)}:freshness:ACTIVE:ACTIVE", f"{uid(1)}:freshness:EXPIRED:EXPIRED",
                    f"{uid(1)}:freshness:STALE:STALE"]
    assert payload(h.sink, f"{uid(1)}:freshness:STALE:STALE") == {
        "identity_key": KEY, "record_id": uid(1), "status": "STALE", "motion_status": "STALE"}
    assert h.rows("SELECT COUNT(*) FROM observation") == [(1,)]


def test_positionless_age_uses_effective_at(h):
    h.publish(report(1, base="land_unknown_position.json"))
    h.run()
    land = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
    h.clock.advance(119.999)
    h.run()
    assert h.rows(STATUS, (land,)) == [("ACTIVE", None)]
    h.clock.advance(0.001)
    h.run()
    assert h.rows(STATUS, (land,)) == [("STALE", None)]


def test_motion_age_is_tracked_separately(h):
    older_motion = report(1, at_ms=20_000)
    older_motion["kinematics"]["observed_at"] = "2026-10-04T12:00:00.000Z"
    h.publish(older_motion)
    h.clock.advance(30)
    h.run()
    assert h.rows(STATUS, (KEY,)) == [("ACTIVE", "STALE")]


def test_retransmitted_old_report_does_not_refresh(h):
    h.publish(report(1))
    h.run()
    h.clock.advance(40)
    h.publish(report(2))                     # the same source time under a new record id
    h.run()
    assert h.rows(STATUS, (KEY,)) == [("STALE", "STALE")]


def test_fresh_report_returns_contribution_to_active(h):
    h.publish(report(1))
    h.run()
    h.clock.advance(40)
    h.run()
    h.publish(report(2, at_ms=40_000))
    h.run()
    assert h.rows(STATUS, (KEY,)) == [("ACTIVE", "ACTIVE")]
