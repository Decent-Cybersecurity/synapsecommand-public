"""Crash recovery in process (R01, R02, R03; REQ097, REQ100, REQ101, REQ141).

A crash is `SimulatedCrash`, a BaseException no `except Exception` swallows; the crashed
instance's connection is then closed explicitly, which rolls back an open transaction exactly as
a process death would (X14), and a new instance opens the same store file."""
import pytest

from helpers import DEST_TUPLE, assert_accounting, bidirectional, payload, report, uid
from synapse_cdm.models import Entity, Track
from synapse_link16_bridge import faults
from synapse_link16_bridge.store import SQL_JOB_GET

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
INGEST = "SELECT record_key, disposition FROM ingest ORDER BY rowid"


def crash(h, point):
    """Run the bridge into a crash at `point`, then close it as a dead process would leave it."""
    with pytest.raises(faults.SimulatedCrash) as caught:
        h.bridge.run_once()
    assert caught.value.point == point
    h.bridge.store.db.close()
    h.bridge.store = None


def cdm_keys(sink):
    return sorted(k for k, v in sink.events.items() if v[0] == "cdm")


def test_crash_after_commit_before_ack_redelivers_and_dedupes(make_harness):
    h = make_harness(faults=faults.CrashPoints({"ingest.after_commit_before_ack"}))
    h.publish(report(1))
    h.publish(report(2, track_number="T-2"))
    crash(h, "ingest.after_commit_before_ack")
    assert h.provider.health_document("c1")["queue_depth"] == 2      # never acknowledged
    assert h.sink.events == {}                                       # never dispatched
    h.clock.advance(31)                                              # the dead holder's lease
    restarted = h.new_bridge(holder="holder-b")
    assert restarted.store.query(INGEST) == [(uid(1), "ACCEPTED"), (uid(2), "ACCEPTED")]
    result = h.run(restarted)
    assert [d[1:] for d in result["dispositions"]] == [("DUPLICATE", None), ("DUPLICATE", None)]
    assert result["acked"] is True and h.provider.health_document("c1")["queue_depth"] == 0
    assert cdm_keys(h.sink) == [f"{uid(1)}:0", f"{uid(1)}:1", f"{uid(2)}:0", f"{uid(2)}:1"]
    assert sorted(d for d in h.sink.deliveries if not d.count("freshness")) == cdm_keys(h.sink)
    counters = restarted.store.counters()
    assert (counters["fed"], counters["accepted"], counters["duplicate"]) == (4, 2, 2)
    assert_accounting(counters)


def test_crash_before_commit_leaves_nothing_and_no_ack(make_harness):
    h = make_harness(faults=faults.CrashPoints({"ingest.before_commit"}))
    h.publish(report(1))
    h.publish(report(2, track_number="T-2"))
    crash(h, "ingest.before_commit")
    h.clock.advance(31)
    restarted = h.new_bridge(holder="holder-b")
    assert restarted.store.query(INGEST) == []
    assert restarted.store.channel()["cursor"] is None
    assert h.provider.health_document("c1")["queue_depth"] == 2
    result = h.run(restarted)
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None), ("ACCEPTED", None)]
    assert restarted.store.counters()["fed"] == 2


def test_crash_before_the_dispatch_mark_delivers_the_same_key_again(make_harness):
    h = make_harness(faults=faults.CrashPoints({"outbox.before_mark_dispatched"}))
    h.publish(report(1))
    crash(h, "outbox.before_mark_dispatched")
    assert h.sink.deliveries == [f"{uid(1)}:0"]                     # delivered, not yet marked
    restarted = h.new_bridge(holder="holder-a")
    h.run(restarted)
    assert h.sink.deliveries[:2] == [f"{uid(1)}:0", f"{uid(1)}:0"]  # at least once, same key
    assert cdm_keys(h.sink) == [f"{uid(1)}:0", f"{uid(1)}:1"]


def lease_harness(make_harness, point_faults=None):
    changes = bidirectional()
    # a 2 s lease needs a request deadline below it (A2F, 2026-10-11): 1.5 s exceeds a long poll
    # of 0 plus an allowance of 0.5 s, and the connect timeout of 1 s is below it
    h = make_harness(lease_ttl_seconds=2, request_deadline_seconds=1.5, long_poll_seconds=0,
                     transport_allowance_seconds=0.5, connect_timeout_seconds=1, **changes)
    h.publish(report(1))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "allocation")
    return h


class TakeOverBeforeSend(faults.CrashPoints):
    """Between the job's commit and its send, the lease expires and instance B takes it."""

    def __init__(self, harness):
        super().__init__()
        self.harness = harness
        self.other = None

    def hit(self, name):
        if name == "egress.after_job_commit_before_send":
            self.harness.clock.advance(3)
            self.other = self.harness.new_bridge(holder="holder-b")


def test_lease_loss_disables_send_and_old_fence_cannot_mutate(make_harness):
    h = lease_harness(make_harness)
    takeover = TakeOverBeforeSend(h)
    h.bridge.egress.faults = takeover
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    track = Track.model_validate(payload(h.sink, f"{uid(1)}:1"))
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(600))
    # A finds its job moved to REVALIDATE under B's fence and sends nothing
    assert (result["state"], result["reason"]) == ("REVALIDATE", None)
    assert h.provider.sent() == []
    from synapse_link16_bridge.lease import LeaseLost
    with pytest.raises(LeaseLost):
        with h.bridge.store.transaction():
            pass
    assert takeover.other.lease.fence == 2
    assert h.run() == {"fetched": False, "reason": "LEASE_LOST"}
    assert h.bridge.status == "BLOCKED"
    job = takeover.other.store.query(SQL_JOB_GET, (uid(600),))[0]
    assert (job[7], job[9]) == ("REVALIDATE", 2)


def test_new_holder_revalidates_jobs_of_the_old_fence(make_harness):
    h = lease_harness(make_harness)
    takeover = TakeOverBeforeSend(h)
    h.bridge.egress.faults = takeover
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    h.bridge.export(entity, None, peer_id="peer-1", request_id=uid(601))
    results = takeover.other.revalidate()
    assert [(r["request_id"], r["state"]) for r in results] == [(uid(601), "SENT")]
    assert [s["request_id"] for s in h.provider.sent()] == [uid(601)]
    assert takeover.other.store.query(SQL_JOB_GET, (uid(601),))[0][9] == 2


def test_a_send_that_may_have_left_becomes_unknown_under_the_new_fence(make_harness):
    h = lease_harness(make_harness)
    h.bridge.egress.faults = faults.CrashPoints({"egress.after_send_before_record"})
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    with pytest.raises(faults.SimulatedCrash):
        h.bridge.export(entity, None, peer_id="peer-1", request_id=uid(602))
    h.bridge.store.db.close()
    h.bridge.store = None
    assert len(h.provider.sent()) == 1
    h.clock.advance(3)
    other = h.new_bridge(holder="holder-b")
    job = other.store.query(SQL_JOB_GET, (uid(602),))[0]
    assert (job[7], job[8], job[11]) == ("UNKNOWN", "SEND_OUTCOME_UNKNOWN", 0)
    assert other.revalidate() == []
    assert other.reconcile() == [(uid(602), "SENT")]
    assert len(h.provider.sent()) == 1


def test_an_ack_whose_answer_never_arrives_leaves_the_pass_unacked_and_the_loop_running(
        make_harness):
    """R4-F1 (fix round 1, 2026-10-11): the gateway applies the acknowledgement and withholds its
    answer past the client's deadline. The pass ends `acked: False` (the batch is committed), the
    loop keeps running, and the next pass acknowledges from the committed cursor."""
    h = make_harness(deadline=0.5, provider_kwargs={"hold_ack_response_seconds": 30.0})
    h.publish(report(1))
    results = []

    def stop_after_two():
        if len(results) == 1:                       # the gateway answers again from now on
            h.provider.hold_ack_response_seconds = 0.0
            h.provider.release_hold.set()
        return len(results) >= 2

    real_run_once = h.bridge.run_once
    h.bridge.run_once = lambda: results.append(real_run_once()) or results[-1]
    h.bridge.run(should_stop=stop_after_two)
    first, second = results
    assert (first["fetched"], first["reason"], first["acked"]) == (True, None, False)
    assert [d[1:] for d in first["dispositions"]] == [("ACCEPTED", None)]
    assert (second["fetched"], second["reason"], second["acked"]) == (True, None, True)
    assert second["dispositions"] == []
    channel = h.bridge.store.channel()
    assert channel["acked_cursor"] == channel["cursor"] == "1.1"
    assert h.provider.health_document("c1")["queue_depth"] == 0
    assert cdm_keys(h.sink) == [f"{uid(1)}:0", f"{uid(1)}:1"]
    assert_accounting(h.bridge.store.counters())


def test_a_lease_lost_between_ingest_and_the_ack_record_ends_the_pass_blocked(h):
    """RUNTIME-3 (A2F, 2026-10-11): the gateway answers the acknowledgement after the lease's
    30 s lifetime has passed. The batch is committed and acknowledged, the acknowledgement is not
    recorded under a lease this instance no longer holds, and the pass ends BLOCKED with
    `LEASE_LOST` instead of raising."""
    real_ack = h.bridge.client.ack

    def slow_ack(consumer, cursor):
        h.clock.advance(31)
        return real_ack(consumer, cursor)

    h.bridge.client.ack = slow_ack
    h.publish(report(1))
    result = h.run()
    assert (result["fetched"], result["reason"], result["acked"]) == (True, "LEASE_LOST", True)
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None)]
    assert (h.bridge.status, h.bridge.blocked_reasons) == ("BLOCKED", ["LEASE_LOST"])
    channel = h.bridge.store.channel()
    assert (channel["acked_cursor"], channel["cursor"] is not None) == (None, True)
    assert h.bridge.health()["ready"] is False
    assert h.run() == {"fetched": False, "reason": "BLOCKED"}


class _ExpireDuring:
    """Calls through, then moves the clock past the lease's lifetime."""

    def __init__(self, h, real):
        self.h, self.real = h, real

    def __call__(self, *args):
        try:
            return self.real(*args)
        finally:
            self.h.clock.advance(31)


@pytest.mark.parametrize("step", ["audit_only", "count_warnings"])
def test_a_lease_lost_at_any_fenced_step_of_a_pass_ends_it_blocked(make_harness, monkeypatch,
                                                                   step):
    """RUNTIME-3 (A2F, 2026-10-11): the audit-only transaction of a channel stop and the
    warning counter's transaction are fenced steps too; a lease lost before either ends the pass
    BLOCKED with `LEASE_LOST`, never an exception out of `run_once`."""
    from synapse_link16_bridge import limits
    if step == "audit_only":
        h = make_harness()
        h.publish(report(1, tenant="another-tenant"))       # a channel stop: audited alone
        monkeypatch.setattr(h.bridge.ingestor, "process",
                            _ExpireDuring(h, h.bridge.ingestor.process))
    else:
        h = make_harness(limits={"max_queued_reports": 10})
        h.sink.fail = True
        for n in range(1, 4):
            h.publish(report(n, track_number=f"T-{n}"))
        h.run()                                             # 9 queued: the band is entered next
        monkeypatch.setattr(limits, "usage", _ExpireDuring(h, limits.usage))
    assert h.run() == {"fetched": False, "reason": "LEASE_LOST"}
    assert (h.bridge.status, h.bridge.blocked_reasons) == ("BLOCKED", ["LEASE_LOST"])
    assert h.rows("SELECT COUNT(*) FROM audit WHERE kind = 'channel_stop'") == [(0,)]
