"""Lifecycle (REQ064, REQ104-106; L01, L02, L03)."""
import pytest

from helpers import DEST_TUPLE, bidirectional, notice, payload, report, uid
from synapse_cdm.models import Entity, Track
from synapse_link16_bridge.bridge import OperatorRefusal
from synapse_link16_bridge.store import SQL_IDENTITY_ALL

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
CONTRIBUTION = "SELECT contribution FROM current WHERE identity_key = ?"


def test_notices_never_reach_the_adapter(h):
    calls = []
    adapter = h.bridge.ingestor.translator.adapter
    original = adapter.to_cdm
    adapter.to_cdm = lambda raw: calls.append(raw) or original(raw)
    h.publish(report(1))
    h.publish_notice(notice(2, "GAP", track_number=None, incarnation=None))
    h.publish_notice(notice(3, "DROP_SOURCE", at_ms=1000))
    h.run()
    assert len(calls) == 1 and b'"record_id":"' + uid(1).encode() in calls[0]


def test_disconnect_heartbeat_loss_stale_and_expiry_drop_nothing(h):
    """L01: a stopped server, 503s, empty polls and the clock past 4T change no identity, no
    incarnation and no history, and issue no close and no send."""
    h.publish(report(1))
    h.run()
    h.server.stop()
    assert h.run()["reason"] == "TRANSPORT"
    from helpers import CREDENTIAL, CONSUMER
    from synapse_link16_bridge.gateway.server import GatewayServer
    h.server = GatewayServer(h.provider, {CREDENTIAL: (CONSUMER, "c1")}).start()
    h.bridge.client = h.client()
    h.provider.unavailable = True
    assert [h.run()["reason"] for _ in range(3)] == ["PROVIDER_UNAVAILABLE"] * 3
    h.provider.unavailable = False
    for _ in range(3):
        assert h.run()["dispositions"] == []
    h.clock.advance(30)
    h.run()
    h.clock.advance(90)
    h.run()
    assert [r[:3] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY, "LIVE", "0")]
    assert h.rows("SELECT COUNT(*) FROM observation") == [(1,)]
    assert h.rows("SELECT freshness FROM current") == [("EXPIRED",)]
    assert not [k for k, v in h.sink.events.items() if v[0] == "close"]
    assert h.provider.sent() == []
    assert len(h.sleeper.delays) == 4


def test_authorised_drop_closes_only_the_exact_tuple_at_the_notice_time(h):
    h.publish(report(1, at_ms=0))
    h.publish(report(2, at_ms=0, incarnation="1"))
    h.publish(report(3, at_ms=0, origin_scope="exercise-source-1", track_number="OTHER"))
    h.publish_notice(notice(4, "DROP_SOURCE", at_ms=7000))
    h.run()
    closed = payload(h.sink, f"{uid(4)}:0")
    assert h.sink.events[f"{uid(4)}:0"][0] == "close"
    assert closed["entity_id"] == payload(h.sink, f"{uid(1)}:0")["entity_id"]
    assert closed["valid_to"] == "2026-10-04T12:00:07.000Z"
    assert closed["valid_from"] == "2026-10-04T12:00:00.000Z"
    statuses = {r[0]: (r[1], r[4]) for r in h.rows(SQL_IDENTITY_ALL)}
    assert statuses[KEY] == ("TOMBSTONED", 1791115207000)
    assert statuses[KEY.replace('"0"]', '"1"]')] == ("LIVE", None)
    assert statuses[KEY.replace("TEST-0001", "OTHER")] == ("LIVE", None)
    assert h.rows(CONTRIBUTION, (KEY,)) == [("CLOSED",)]
    assert h.counters()["source_drop"] == 1


def test_late_drop_is_quarantined_as_contradiction(h):
    h.publish(report(1, at_ms=10_000))
    h.publish_notice(notice(2, "DROP_SOURCE", at_ms=5_000))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [
        ("ACCEPTED", None), ("QUARANTINED", "LIFECYCLE_CONTRADICTION")]
    assert h.rows(CONTRIBUTION, (KEY,)) == [("ACTIVE",)]
    assert h.rows(SQL_IDENTITY_ALL)[0][1] == "LIVE"


def test_a_drop_for_a_tuple_with_no_state_records_a_tombstone_and_publishes_nothing(h):
    h.publish_notice(notice(1, "DROP_SOURCE", track_number="NEVER-SEEN"))
    h.run()
    assert h.rows(SQL_IDENTITY_ALL)[0][1] == "TOMBSTONED"
    assert [k for k in h.sink.events if not k.endswith("NONE")] == []


def test_cursor_expired_marks_resync_and_blocks_egress_until_recovery(make_harness):
    h = make_harness(**bidirectional())
    h.publish(report(1))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "allocation record 1")
    h.publish(report(2, at_ms=1000))
    h.clock.advance(24 * 3600)
    h.publish(report(3, at_ms=24 * 3600 * 1000, track_number="T-3"))
    assert h.run()["reason"] == "CURSOR_EXPIRED"
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"], channel["earliest_cursor"]) == (
        "RESYNC_REQUIRED", "CURSOR_EXPIRED", "1.2")
    assert h.bridge.health()["ready"] is False
    assert "RESYNC_REQUIRED" in h.bridge.health()["blocked_reasons"]
    assert h.run() == {"fetched": False, "reason": "RESYNC_REQUIRED"}
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    assert h.bridge.export(entity, None, peer_id="peer-1")["reason"] == "CHANNEL_INCOMPLETE"
    with pytest.raises(OperatorRefusal):
        h.bridge.recover("too early")
    h.bridge.resync("gateway loss record 2 shows one report", lost_count=1)
    assert h.bridge.store.channel()["state"] == "INCOMPLETE"
    assert h.run()["dispositions"] == [(uid(3), "ACCEPTED", None)]
    h.bridge.recover("snapshot verified by the operator")
    assert h.bridge.store.channel()["state"] == "NORMAL"
    counters = h.counters()
    assert (counters["fed"], counters["accepted"], counters["dropped_by_capacity"]) == (3, 2, 1)
    kinds = [r[0] for r in h.rows("SELECT kind, code FROM audit ORDER BY seq")]
    # the record lost to retention had sequence 1, so the first record after the resync is a
    # stream gap (expected 1, got 2) inside the same incomplete period
    assert kinds == ["allocation", "cursor_expired", "export_denied", "resync", "stream_gap",
                     "recover"]
    details = [r[0] for r in h.rows("SELECT detail FROM audit WHERE kind IN ('resync', 'recover')"
                                    " ORDER BY seq")]
    assert details == ["lost=1; gateway loss record 2 shows one report",
                       "gap 1..2; snapshot verified by the operator"]


def test_sequence_gap_marks_incomplete(h):
    h.publish(report(1))
    h.provider.skip_sequence("c1", 2)
    h.publish(report(2, at_ms=1000))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None), ("ACCEPTED", None)]
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"], channel["gap_from"], channel["gap_to"]) == (
        "INCOMPLETE", "STREAM_GAP", "1", "3")
    assert h.bridge.health()["ready"] is False


def test_gap_notice_marks_incomplete(h):
    h.publish_notice(notice(1, "GAP", track_number=None, incarnation=None))
    h.run()
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"]) == ("INCOMPLETE", "GAP")
    h.bridge.recover("operator checked the source")
    assert h.bridge.store.channel()["state"] == "NORMAL"


@pytest.mark.parametrize("decision, then", [("keep", ("ACCEPTED", None)),
                                            ("advance", ("QUARANTINED", "REUSE_AMBIGUOUS"))])
def test_reset_scope_requires_identity_resync(h, decision, then):
    h.publish(report(1))
    h.publish_notice(notice(2, "RESET_SCOPE", at_ms=1000, track_number=None, incarnation=None))
    h.run()
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"], channel["epoch"]) == (
        "RESYNC_REQUIRED", "RESET_SCOPE", 1)
    h.publish(report(3, at_ms=2000))
    assert h.run() == {"fetched": False, "reason": "RESYNC_REQUIRED"}
    with pytest.raises(OperatorRefusal):
        h.bridge.resync("wrong command", None)
    h.bridge.resync_identities(decision, "identity decision recorded by the operator")
    assert h.bridge.store.channel()["state"] == "NORMAL"
    assert [d[1:] for d in h.run()["dispositions"]] == [then]
    assert h.rows("SELECT COUNT(*) FROM observation") == [(1 if decision == "advance" else 2,)]


def test_a_report_after_reset_scope_in_the_same_batch_belongs_to_the_new_epoch(h):
    """RUNTIME-7 (A2F, 2026-10-11): the epoch is read again after each notice, so a first report
    after a RESET_SCOPE in the same batch is stamped with the new epoch, as it is when the report
    arrives in a later batch; `resync-identities --decision advance` then resets the identities of
    the closed epoch only, and the new identity's next report is accepted."""
    key_new = '["demo","test-only",true,"exercise-source-1","T-2","0"]'
    h.publish(report(1, at_ms=0))
    h.publish_notice(notice(2, "RESET_SCOPE", at_ms=1000, track_number=None, incarnation=None))
    h.publish(report(3, at_ms=2000, track_number="T-2"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [
        ("ACCEPTED", None), ("ACCEPTED", "RESET_SCOPE"), ("ACCEPTED", None)]
    assert h.rows("SELECT identity_key, epoch FROM identity ORDER BY identity_key") == [
        ('["demo","test-only",true,"exercise-source-1","T-2","0"]', 1),
        ('["demo","test-only",true,"exercise-source-1","TEST-0001","0"]', 0)]
    h.bridge.resync_identities("advance", "identity decision recorded by the operator")
    assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [
        (key_new, "LIVE"), ('["demo","test-only",true,"exercise-source-1","TEST-0001","0"]',
                            "RESET")]
    h.publish(report(4, at_ms=3000, track_number="T-2"))
    assert [d[1:] for d in h.run()["dispositions"]] == [("ACCEPTED", None)]


# -- A2F-F1 (fix round 1, 2026-10-11): a recorded gap ends only by `recover` (REQ106, L03) ------

GAP_TUPLE = {"track_number": None, "incarnation": None}
AUDIT_CAPACITY = "SELECT kind, code FROM audit WHERE kind LIKE 'capacity%' ORDER BY seq"


def state(bridge):
    channel = bridge.store.channel()
    return channel["state"], channel["state_reason"]


def export(h, bridge, n):
    """Export report 1's published Entity and Track to peer-1; (state, reason)."""
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    track = Track.model_validate(payload(h.sink, f"{uid(1)}:1"))
    result = bridge.export(entity, track, peer_id="peer-1", request_id=uid(n))
    return result["state"], result["reason"]


def gapped(make_harness, **options):
    """A bidirectional harness with report 1 ingested and its allocation recorded, then a GAP
    notice processed: the channel is INCOMPLETE (`GAP`)."""
    h = make_harness(**bidirectional(), **options)
    h.publish(report(1))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "provider allocation record 7")
    h.publish_notice(notice(2, "GAP", **GAP_TUPLE))
    h.run()
    assert state(h.bridge) == ("INCOMPLETE", "GAP")
    return h


def test_a_gap_outlives_the_report_queue_cap(make_harness):
    """The report-queue cap reached while a GAP holds the channel INCOMPLETE stops fetching and
    leaves INCOMPLETE in place, with no `capacity` row on any pass (nothing transitions). Once the
    queue drains the channel is still INCOMPLETE, health is not ready and an export is denied
    `CHANNEL_INCOMPLETE`, until `recover` makes it NORMAL and the same export is sent. Before, the
    cap wrote OVERLOADED over INCOMPLETE, the drained queue cleared it to NORMAL, and the export
    was SENT with no recovery recorded."""
    h = gapped(make_harness, limits={"max_queued_reports": 2})
    h.sink.fail = True
    h.publish(report(3, track_number="T-3"))
    h.run()                                     # ingested; the sink takes nothing
    for _ in range(50):
        assert h.run() == {"fetched": False, "reason": "CAPACITY_REPORTS"}
    assert state(h.bridge) == ("INCOMPLETE", "GAP")
    assert h.rows(AUDIT_CAPACITY) == []
    h.sink.fail = False
    h.run()                                     # this pass drains the queue
    h.run()
    assert state(h.bridge) == ("INCOMPLETE", "GAP")
    health = h.bridge.health()
    assert (health["ready"], health["blocked_reasons"]) == (False, ["CHANNEL_INCOMPLETE"])
    assert export(h, h.bridge, 600) == ("DENIED", "CHANNEL_INCOMPLETE")
    h.bridge.recover("operator checked the source")
    assert state(h.bridge) == ("NORMAL", None)
    assert export(h, h.bridge, 601) == ("SENT", None)


def test_recover_clears_the_recorded_gap_so_a_later_cap_clears_to_normal(make_harness):
    """A2F-F3 (2026-10-11): `recover` clears the channel's recorded gap (the `incomplete` column)
    with its INCOMPLETE state, so health is ready with no `CHANNEL_INCOMPLETE`, and a report-queue
    cap reached after the recovery clears, with one `capacity` and one `capacity_cleared` row, to
    NORMAL. A `recover` that left the column set would keep the channel unready, and the cap's
    clearing would return it to INCOMPLETE."""
    h = gapped(make_harness, limits={"max_queued_reports": 2})
    h.bridge.recover("operator checked the source")
    assert state(h.bridge) == ("NORMAL", None)
    assert h.bridge.store.channel()["incomplete"] is None
    health = h.bridge.health()
    assert (health["ready"], health["blocked_reasons"]) == (True, [])
    h.sink.fail = True
    h.publish(report(3, track_number="T-3"))
    h.run()                                     # ingested; the sink takes nothing
    assert h.run() == {"fetched": False, "reason": "CAPACITY_REPORTS"}
    assert state(h.bridge) == ("OVERLOADED", "CAPACITY_REPORTS")
    h.sink.fail = False
    h.run()                                     # this pass drains the queue
    h.run()
    assert state(h.bridge) == ("NORMAL", None)
    assert h.rows(AUDIT_CAPACITY) == [("capacity", "CAPACITY_REPORTS"),
                                      ("capacity_cleared", "CAPACITY_REPORTS")]
    health = h.bridge.health()
    assert (health["ready"], health["blocked_reasons"]) == (True, [])


def test_a_gap_outlives_the_identity_cap(make_harness):
    """A report of a new identity at the identity cap, after a GAP, is not consumed on any of 50
    passes, and the channel stays INCOMPLETE with no `capacity` row. The batch consumed under a
    new configuration revision with a higher cap leaves it INCOMPLETE: health names the gap, an
    export is denied `CHANNEL_INCOMPLETE`, and only `recover` makes it NORMAL. Before, the cap's
    OVERLOADED replaced INCOMPLETE and the consumed batch cleared it to NORMAL."""
    h = gapped(make_harness, limits={"max_identities": 1})
    h.publish(report(3, track_number="T-3"))
    for _ in range(50):
        assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
    assert state(h.bridge) == ("INCOMPLETE", "GAP")
    assert h.rows(AUDIT_CAPACITY) == []
    assert h.bridge.status_report()["full"] == ["CAPACITY_IDENTITIES"]
    h.bridge.close()
    raised = h.new_bridge(holder="holder-b", config=h.config(
        config_revision="rev-2", limits={"max_identities": 2}))
    assert [d[1:] for d in h.run(raised)["dispositions"]] == [("ACCEPTED", None)]
    assert state(raised) == ("INCOMPLETE", "GAP")
    assert raised.health()["blocked_reasons"] == ["CHANNEL_INCOMPLETE"]
    assert export(h, raised, 600) == ("DENIED", "CHANNEL_INCOMPLETE")
    raised.recover("operator checked the source")
    assert state(raised) == ("NORMAL", None)
    assert export(h, raised, 601) == ("SENT", None)


def test_a_gap_in_the_batch_the_identity_cap_held_survives_the_cap_clearing(make_harness):
    """The channel is OVERLOADED by the identity cap when a GAP arrives behind the held report.
    The batch consumed under a raised cap carries both; the cap clears with its one
    `capacity_cleared` row to INCOMPLETE (`GAP`), not to NORMAL. Before, the GAP left OVERLOADED in
    place and the clearing wrote NORMAL over it."""
    h = make_harness(**bidirectional(), limits={"max_identities": 1})
    h.publish(report(1))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "provider allocation record 7")
    h.publish(report(2, track_number="T-2"))
    assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
    assert state(h.bridge) == ("OVERLOADED", "CAPACITY_IDENTITIES")
    h.publish_notice(notice(3, "GAP", **GAP_TUPLE))
    h.bridge.close()
    raised = h.new_bridge(holder="holder-b", config=h.config(
        config_revision="rev-2", limits={"max_identities": 2}))
    assert [d[1:] for d in h.run(raised)["dispositions"]] == [("ACCEPTED", None),
                                                              ("ACCEPTED", "GAP")]
    assert state(raised) == ("INCOMPLETE", "GAP")
    assert raised.store.query(AUDIT_CAPACITY) == [("capacity", "CAPACITY_IDENTITIES"),
                                                  ("capacity_cleared", "CAPACITY_IDENTITIES")]
    assert export(h, raised, 600) == ("DENIED", "CHANNEL_INCOMPLETE")
    raised.recover("operator checked the source")
    assert state(raised) == ("NORMAL", None)
    assert export(h, raised, 601) == ("SENT", None)


def test_a_gap_outlives_a_channel_stop_and_the_restart_under_a_new_revision(make_harness):
    """A channel stop after a GAP is STOPPED, and health names both; the restart under a new
    configuration revision returns it to INCOMPLETE (`GAP`), not NORMAL. Before, the restart wrote
    NORMAL and the export was SENT."""
    h = gapped(make_harness)
    h.publish(report(3, tenant="another-tenant"))
    assert h.run()["reason"] == "SECURITY_CONTEXT_MISMATCH"
    assert state(h.bridge) == ("STOPPED", "SECURITY_CONTEXT_MISMATCH")
    assert h.bridge.health()["blocked_reasons"] == ["CHANNEL_INCOMPLETE", "CHANNEL_STOPPED"]
    h.bridge.close()
    renewed = h.new_bridge(holder="holder-b", config=h.config(config_revision="rev-2"))
    assert state(renewed) == ("INCOMPLETE", "GAP")
    assert renewed.store.query("SELECT kind, code FROM audit ORDER BY seq")[-1] == (
        "channel_restart", "CONFIG_REVISION_RESTART")
    assert export(h, renewed, 600) == ("DENIED", "CHANNEL_INCOMPLETE")
    renewed.recover("operator checked the source")
    assert state(renewed) == ("NORMAL", None)


def test_a_gap_outlives_reset_scope_and_the_identity_resynchronisation(make_harness):
    """A RESET_SCOPE after a GAP makes the channel RESYNC_REQUIRED, and health names both;
    `resync-identities` returns it to INCOMPLETE (`GAP`), not NORMAL. Before, it wrote NORMAL and
    the export was SENT."""
    h = gapped(make_harness)
    h.publish_notice(notice(3, "RESET_SCOPE", at_ms=1000, **GAP_TUPLE))
    h.run()
    assert state(h.bridge) == ("RESYNC_REQUIRED", "RESET_SCOPE")
    assert h.bridge.health()["blocked_reasons"] == ["CHANNEL_INCOMPLETE", "RESYNC_REQUIRED"]
    h.bridge.resync_identities("keep", "identity decision recorded by the operator")
    assert state(h.bridge) == ("INCOMPLETE", "GAP")
    assert export(h, h.bridge, 600) == ("DENIED", "CHANNEL_INCOMPLETE")
    h.bridge.recover("operator checked the source")
    assert state(h.bridge) == ("NORMAL", None)


def test_recover_on_a_degraded_stopped_channel_clears_the_flag_and_keeps_the_stop(h):
    """A structurally invalid batch refused three times leaves the channel STOPPED and degraded;
    `recover` clears the flag only, so the channel stays STOPPED until a new configuration
    revision. Before, `recover` wrote NORMAL over the stop and the next pass fetched."""
    h.publish(report(1))
    h.provider.inject_record("c1", "report", b'{"broken":')
    h.run()
    h.run()
    assert h.run() == {"fetched": True, "reason": "STRUCTURAL_BATCH"}
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"], channel["degraded"]) == (
        "STOPPED", "STRUCTURAL_BATCH", 1)
    h.bridge.recover("operator checked the source")
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"], channel["degraded"]) == (
        "STOPPED", "STRUCTURAL_BATCH", 0)
    assert h.run() == {"fetched": False, "reason": "STOPPED"}
    assert h.rows("SELECT kind, code FROM audit WHERE kind = 'recover'") == [("recover", None)]


def test_a_loss_accepted_at_resync_outlives_reset_scope(make_harness):
    """The loss `resync --accept-earliest` records (INCOMPLETE, `CURSOR_EXPIRED`) is held as the
    channel's unrecovered gap: a RESET_SCOPE after it, and `resync-identities`, return the channel
    to INCOMPLETE with that first reason (the stream gap behind it does not replace it), and only
    `recover` makes it NORMAL."""
    h = make_harness(**bidirectional())
    h.publish(report(1))
    h.run()
    h.publish(report(2, at_ms=1000))
    h.clock.advance(24 * 3600)
    h.publish(report(3, at_ms=24 * 3600 * 1000, track_number="T-3"))
    assert h.run()["reason"] == "CURSOR_EXPIRED"
    h.bridge.resync("gateway loss record 2 shows one report", lost_count=1)
    assert state(h.bridge) == ("INCOMPLETE", "CURSOR_EXPIRED")
    h.publish_notice(notice(4, "RESET_SCOPE", at_ms=24 * 3600 * 1000, **GAP_TUPLE))
    assert [d[1:] for d in h.run()["dispositions"]] == [("ACCEPTED", None),
                                                        ("ACCEPTED", "RESET_SCOPE")]
    assert state(h.bridge) == ("RESYNC_REQUIRED", "RESET_SCOPE")
    h.bridge.resync_identities("keep", "identity decision recorded by the operator")
    assert state(h.bridge) == ("INCOMPLETE", "CURSOR_EXPIRED")
    h.bridge.recover("snapshot verified by the operator")
    assert state(h.bridge) == ("NORMAL", None)
