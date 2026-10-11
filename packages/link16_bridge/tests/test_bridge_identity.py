"""Source identity at the runtime (REQ070-074, I01-I04, REQ122's tombstones and cap)."""
import json

import pytest

from helpers import Harness, notice, payload, report, tuple_of, uid
from synapse_cdm.adapters.link16_gateway import Link16GatewayAdapter
from synapse_link16_bridge import identity
from synapse_link16_bridge.bridge import OperatorRefusal
from synapse_link16_bridge.store import (SQL_IDENTITY_ALL, SQL_QUARANTINE_ALL, SQL_RELATION_ALL)

KEY_0 = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'
KEY_1 = '["demo","test-only",true,"exercise-source-1","TEST-0001","1"]'


def quarantined(h):
    return [(r[1], r[3], r[6], r[9]) for r in h.rows(SQL_QUARANTINE_ALL)]


def test_the_identity_key_is_the_adapters_external_id_and_ids_match():
    body = report(1)
    objects = Link16GatewayAdapter(synthetic=True).to_cdm(body)
    assert identity.key_of(body) == objects[0].source_ids[0].external_id == KEY_0
    assert identity.entity_ids(KEY_0) == (str(objects[0].entity_id), str(objects[1].track_id))


def test_reconnect_and_new_session_do_not_renumber(h, tmp_path):
    """I01: the same tuple across a server restart, a new session and another reporter."""
    h.publish(report(1))
    h.run()
    h.provider.new_session("c1")
    h.publish(report(2, at_ms=1000, reporter="ANOTHER-RELAY", gateway_id="synthetic-gateway-1"))
    h.server.stop()
    from synapse_link16_bridge.gateway.server import GatewayServer
    from helpers import CREDENTIAL, CONSUMER
    h.server = GatewayServer(h.provider, {CREDENTIAL: (CONSUMER, "c1")}).start()
    h.bridge.client = h.client()
    h.bridge.egress.client = h.bridge.client
    h.run()
    ids = {payload(h.sink, f"{uid(n)}:0")["entity_id"] for n in (1, 2)}
    tracks = {payload(h.sink, f"{uid(n)}:1")["track_id"] for n in (1, 2)}
    assert len(ids) == 1 and len(tracks) == 1
    assert [row[0] for row in h.rows(SQL_IDENTITY_ALL)] == [KEY_0]


def test_report_after_drop_with_same_incarnation_is_quarantined_as_reuse_ambiguous(h):
    h.publish(report(1, at_ms=0))
    h.publish_notice(notice(2, "DROP_SOURCE", at_ms=1000))
    h.publish(report(3, at_ms=2000))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None),
                                                        ("ACCEPTED", "DROP_SOURCE"),
                                                        ("QUARANTINED", "REUSE_AMBIGUOUS")]
    assert result["acked"] is True
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, None)]
    assert f"{uid(3)}:0" not in h.sink.events
    assert h.rows(SQL_IDENTITY_ALL)[0][1] == "TOMBSTONED"


def test_resolve_reuse_continue_releases_the_report(h):
    test_report_after_drop_with_same_incarnation_is_quarantined_as_reuse_ambiguous(h)
    first_entity = payload(h.sink, f"{uid(1)}:0")["entity_id"]
    released = h.bridge.resolve_reuse(KEY_0, "continue", "provider confirmed continuation")
    assert released == 1
    h.run()
    assert payload(h.sink, f"{uid(3)}:0")["entity_id"] == first_entity
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, "CONTINUED_BY_OPERATOR")]
    assert h.rows(SQL_IDENTITY_ALL)[0][1] == "LIVE"
    counters = h.counters()
    assert (counters["fed"], counters["accepted"], counters["refused"]) == (3, 3, 0)


def test_resolve_reuse_reject_keeps_the_report_refused(h):
    test_report_after_drop_with_same_incarnation_is_quarantined_as_reuse_ambiguous(h)
    assert h.bridge.resolve_reuse(KEY_0, "reject", "provider says a new object") == 0
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, "REJECTED_BY_OPERATOR")]
    assert f"{uid(3)}:0" not in h.sink.events


def test_next_incarnation_after_drop_is_a_new_identity_and_supersedes_the_quarantine(h):
    test_report_after_drop_with_same_incarnation_is_quarantined_as_reuse_ambiguous(h)
    h.publish(report(4, at_ms=3000, incarnation="1"))
    h.run()
    new_entity = payload(h.sink, f"{uid(4)}:0")["entity_id"]
    assert new_entity != payload(h.sink, f"{uid(1)}:0")["entity_id"]
    assert new_entity == identity.entity_ids(KEY_1)[0]
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, "SUPERSEDED_BY_INCARNATION")]


def test_lower_incarnation_after_newer_is_ambiguous(h):
    h.publish(report(1, at_ms=0, incarnation="1"))
    h.publish(report(2, at_ms=1000, incarnation="0"))
    h.publish(report(3, at_ms=-1000, incarnation="0", track_number="TEST-0001"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [
        ("ACCEPTED", None), ("QUARANTINED", "REUSE_AMBIGUOUS"), ("ACCEPTED", None)]


def test_a_tombstoned_tuple_accepts_late_history_at_or_before_the_drop(h):
    h.publish(report(1, at_ms=0))
    h.publish_notice(notice(2, "DROP_SOURCE", at_ms=5000))
    h.publish(report(3, at_ms=5000))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None),
                                                        ("ACCEPTED", "DROP_SOURCE"),
                                                        ("ACCEPTED", "LATE")]
    assert h.sink.events[f"{uid(3)}:0"][2] == ("LATE",)


def test_rekey_records_a_durable_relation_and_merges_nothing(h, tmp_path):
    old = tuple_of(report(1))
    new = dict(old, track_number="TEST-0002")
    h.publish(report(1, at_ms=0))
    h.publish_notice(notice(2, "REKEY", at_ms=1000, old_identity=old, new_identity=new))
    h.publish(report(3, at_ms=2000, track_number="TEST-0002"))
    h.run()
    key_new = json.dumps(["demo", "test-only", True, "exercise-source-1", "TEST-0002", "0"],
                         separators=(",", ":"))
    assert h.rows(SQL_RELATION_ALL) == [(KEY_0, key_new, uid(2), 1791115201000)]
    relation = payload(h.sink, f"{uid(2)}:0")
    assert relation == {"relation": "REKEY", "old_entity_id": identity.entity_ids(KEY_0)[0],
                        "new_entity_id": identity.entity_ids(key_new)[0],
                        "effective_at": "2026-10-04T12:00:01.000Z"}
    assert payload(h.sink, f"{uid(3)}:0")["entity_id"] == identity.entity_ids(key_new)[0]
    assert sorted(r[:2] for r in h.rows(SQL_IDENTITY_ALL)) == [(KEY_0, "LIVE"), (key_new, "LIVE")]
    assert h.rows("SELECT contribution FROM current WHERE identity_key = ?", (KEY_0,)) == \
        [("ACTIVE",)]
    h.bridge.close()
    reopened = h.new_bridge(holder="holder-b")
    assert reopened.store.query(SQL_RELATION_ALL) == [(KEY_0, key_new, uid(2), 1791115201000)]


def test_rekey_across_realm_is_refused(h):
    old = tuple_of(report(1))
    new = dict(old, realm="another-realm")
    h.publish_notice(notice(1, "REKEY", old_identity=old, new_identity=new))
    h.publish_notice(notice(2, "REKEY", old_identity=old, new_identity=dict(old, track_number="X"),
                            track_number="NOT-THE-OLD-ONE"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [
        ("QUARANTINED", "IDENTITY_SCOPE_UNRESOLVED"), ("QUARANTINED", "SCHEMA_INVALID")]
    assert h.rows(SQL_RELATION_ALL) == []


def test_unapproved_origin_scope_is_identity_scope_unresolved(h):
    h.publish(report(1, origin_scope="unapproved-scope"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("QUARANTINED",
                                                        "IDENTITY_SCOPE_UNRESOLVED")]
    assert [(r[3], r[4], r[5]) for r in h.rows(SQL_QUARANTINE_ALL)] == [
        ("IDENTITY_SCOPE_UNRESOLVED", "origin_scope", "scope not approved for this channel")]


def test_timeout_alone_never_advances_incarnation(h):
    h.publish(report(1))
    h.run()
    h.clock.advance(4 * 30 + 3600)
    h.run()
    assert [(r[0], r[1], r[2]) for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "LIVE", "0")]


def test_identical_numbers_in_two_realms_or_layers_never_collide(make_harness):
    entity_ids = set()
    for realm, synthetic in (("test-only", True), ("realm-two", True), ("test-only", False)):
        h = make_harness(realm=realm, synthetic=synthetic,
                         realm_kind="exercise" if synthetic else "live",
                         provider_kwargs={"synthetic": synthetic})
        h.publish(report(1, realm=realm, synthetic=synthetic))
        h.run()
        if not synthetic:
            assert h.bridge.status == "READY"
        entity_ids.add(payload(h.sink, f"{uid(1)}:0")["entity_id"])
    assert len(entity_ids) == 3


def test_identity_cap_refuses_new_identities_and_keeps_tombstones(tmp_path):
    h = Harness(tmp_path, limits={"max_identities": 2})
    try:
        h.publish(report(1, track_number="A"))
        h.publish_notice(notice(2, "DROP_SOURCE", track_number="A"))
        h.publish(report(3, track_number="B"))
        h.run()
        assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [
            ('["demo","test-only",true,"exercise-source-1","A","0"]', "TOMBSTONED"),
            ('["demo","test-only",true,"exercise-source-1","B","0"]', "LIVE")]
        h.publish(report(4, track_number="C"))
        h.publish(report(5, track_number="D"))
        result = h.run()
        assert result == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
        assert h.bridge.store.channel()["state"] == "OVERLOADED"
        assert "CAPACITY_IDENTITIES" in h.bridge.health()["blocked_reasons"]
        assert len(h.rows(SQL_IDENTITY_ALL)) == 2       # the whole batch was not consumed
        assert h.provider.health_document("c1")["queue_depth"] == 2     # C and D kept, unacked
        assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}  # still not consumed
        h.bridge.close()
        raised = h.new_bridge(holder="holder-b", config=h.config(
            config_revision="rev-2", limits={"max_identities": 4}))
        result = h.run(raised)
        assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", None), ("ACCEPTED", None)]
        assert [r[1] for r in raised.store.query(SQL_IDENTITY_ALL)] == ["TOMBSTONED", "LIVE",
                                                                         "LIVE", "LIVE"]
    finally:
        h.close()


def test_a_known_lower_incarnation_later_than_a_newer_ones_first_report_is_ambiguous(h):
    """R4-F2 (fix round 1, 2026-10-11): rule (b) holds for a lower incarnation already LIVE.
    Incarnation 0 at t, 1 at t+1 s, then 0 at t+2 s is ambiguous; 0 at t+0.5 s (before
    incarnation 1's first report) is still accepted as the old identity's history."""
    h.publish(report(1, at_ms=0, incarnation="0"))
    h.publish(report(2, at_ms=1000, incarnation="1"))
    h.publish(report(3, at_ms=2000, incarnation="0"))
    h.publish(report(4, at_ms=500, incarnation="0"))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [
        ("ACCEPTED", None), ("ACCEPTED", None), ("QUARANTINED", "REUSE_AMBIGUOUS"),
        ("ACCEPTED", None)]
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, None)]
    assert f"{uid(3)}:0" not in h.sink.events
    assert h.rows("SELECT record_id FROM current WHERE identity_key = ?", (KEY_0,)) == \
        [(uid(4),)]


def test_a_continue_is_scoped_to_the_incarnations_known_when_it_was_recorded(h):
    """R4-F13 (fix round 2, 2026-10-11; D-51): `continue` for incarnation 0 against incarnation 1
    holds against incarnation 1 only. Incarnation 2 appears afterwards, and a later report of
    incarnation 0 is quarantined again; a second `continue` then covers incarnation 2 too."""
    scope = "SELECT reuse_decision, reuse_scope FROM identity WHERE identity_key = ?"
    h.publish(report(1, at_ms=0, incarnation="0"))
    h.publish(report(2, at_ms=1000, incarnation="1"))
    h.publish(report(3, at_ms=2000, incarnation="0"))
    assert [d[1:] for d in h.run()["dispositions"]][2] == ("QUARANTINED", "REUSE_AMBIGUOUS")
    assert h.bridge.resolve_reuse(KEY_0, "continue", "provider confirmed incarnation 0") == 1
    assert h.rows(scope, (KEY_0,)) == [("continue", 1)]
    h.publish(report(4, at_ms=2500, incarnation="0"))     # the decision holds against 1
    h.publish(report(5, at_ms=3000, incarnation="2"))
    h.publish(report(6, at_ms=4000, incarnation="0"))     # later than incarnation 2's first
    assert [d[1:] for d in h.run()["dispositions"]] == [
        ("ACCEPTED", None), ("ACCEPTED", None), ("QUARANTINED", "REUSE_AMBIGUOUS")]
    assert quarantined(h)[-1] == (uid(6), "REUSE_AMBIGUOUS", KEY_0, None)
    assert f"{uid(6)}:0" not in h.sink.events
    assert h.bridge.resolve_reuse(KEY_0, "continue", "provider confirmed incarnation 0 again") == 1
    assert h.rows(scope, (KEY_0,)) == [("continue", 2)]
    h.publish(report(7, at_ms=5000, incarnation="0"))
    assert [d[1:] for d in h.run()["dispositions"]] == [("ACCEPTED", None)]


def rule_b_quarantine(h):
    """Incarnation 1 first, then a never-seen incarnation 0 later: rule (b), no identity row."""
    h.publish(report(1, at_ms=0, incarnation="1"))
    h.publish(report(2, at_ms=1000, incarnation="0"))
    assert [d[1:] for d in h.run()["dispositions"]] == [
        ("ACCEPTED", None), ("QUARANTINED", "REUSE_AMBIGUOUS")]
    assert [r[0] for r in h.rows(SQL_IDENTITY_ALL)] == [KEY_1]


def test_resolve_reuse_continue_releases_a_rule_b_quarantine(h):
    """R4-F3 (fix round 1, 2026-10-11): `continue` admits a tuple that rule (b) never let in."""
    rule_b_quarantine(h)
    assert h.bridge.resolve_reuse(KEY_0, "continue", "provider confirmed incarnation 0") == 1
    h.run()
    assert payload(h.sink, f"{uid(2)}:0")["entity_id"] == identity.entity_ids(KEY_0)[0]
    assert quarantined(h) == [(uid(2), "REUSE_AMBIGUOUS", KEY_0, "CONTINUED_BY_OPERATOR")]
    assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "LIVE"), (KEY_1, "LIVE")]
    h.publish(report(3, at_ms=3000, incarnation="0"))     # the recorded decision holds
    assert [d[1:] for d in h.run()["dispositions"]] == [("ACCEPTED", None)]
    counters = h.counters()
    assert (counters["fed"], counters["accepted"], counters["refused"]) == (3, 3, 0)


def test_resolve_reuse_reject_closes_a_rule_b_quarantine(h):
    rule_b_quarantine(h)
    assert h.bridge.resolve_reuse(KEY_0, "reject", "provider says incarnation 0 is stale") == 0
    assert quarantined(h) == [(uid(2), "REUSE_AMBIGUOUS", KEY_0, "REJECTED_BY_OPERATOR")]
    assert [r[0] for r in h.rows(SQL_IDENTITY_ALL)] == [KEY_1]
    assert f"{uid(2)}:0" not in h.sink.events
    with pytest.raises(OperatorRefusal):              # nothing left to decide
        h.bridge.resolve_reuse(KEY_0, "reject", "again")


def rule_c_quarantine(h):
    """An epoch closed with `resync-identities --decision advance`, then the same tuple again."""
    h.publish(report(1))
    h.publish_notice(notice(2, "RESET_SCOPE", at_ms=1000, track_number=None, incarnation=None))
    h.run()
    h.bridge.resync_identities("advance", "identity decision recorded by the operator")
    h.publish(report(3, at_ms=2000))
    assert [d[1:] for d in h.run()["dispositions"]] == [("QUARANTINED", "REUSE_AMBIGUOUS")]
    assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "RESET")]


def test_resolve_reuse_continue_releases_a_rule_c_quarantine(h):
    rule_c_quarantine(h)
    assert h.bridge.resolve_reuse(KEY_0, "continue", "provider confirmed continuation") == 1
    h.run()
    assert payload(h.sink, f"{uid(3)}:0")["entity_id"] == payload(h.sink, f"{uid(1)}:0")[
        "entity_id"]
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, "CONTINUED_BY_OPERATOR")]
    assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "LIVE")]


def test_resolve_reuse_reject_closes_a_rule_c_quarantine(h):
    rule_c_quarantine(h)
    assert h.bridge.resolve_reuse(KEY_0, "reject", "provider says a new object") == 0
    assert quarantined(h) == [(uid(3), "REUSE_AMBIGUOUS", KEY_0, "REJECTED_BY_OPERATOR")]
    assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "RESET")]
    assert f"{uid(3)}:0" not in h.sink.events


def test_resolve_reuse_refuses_a_tuple_with_nothing_quarantined(h):
    h.publish(report(1))
    h.run()
    for key in (KEY_0, KEY_1):
        with pytest.raises(OperatorRefusal):
            h.bridge.resolve_reuse(key, "continue", "nothing to release")


def test_a_rekey_to_a_new_tuple_is_held_to_the_identity_cap(tmp_path):
    """RUNTIME-5 (A2F, 2026-10-11; D-52): a REKEY's new tuple is a new LIVE identity, so at the
    identity cap the batch that carries the notice is not consumed (`CAPACITY_IDENTITIES`), no
    relation is recorded and the notice stays at the gateway; with the cap raised it is accepted."""
    h = Harness(tmp_path, limits={"max_identities": 1})
    try:
        old = tuple_of(report(1))
        new = dict(old, track_number="TEST-0002")
        h.publish(report(1))
        assert [d[1:] for d in h.run()["dispositions"]] == [("ACCEPTED", None)]
        h.publish_notice(notice(2, "REKEY", at_ms=1000, old_identity=old, new_identity=new))
        assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
        channel = h.bridge.store.channel()
        assert (channel["state"], channel["state_reason"]) == ("OVERLOADED", "CAPACITY_IDENTITIES")
        assert [r[:2] for r in h.rows(SQL_IDENTITY_ALL)] == [(KEY_0, "LIVE")]
        assert h.rows(SQL_RELATION_ALL) == []
        assert h.provider.health_document("c1")["queue_depth"] == 1
        h.bridge.close()
        raised = h.new_bridge(holder="holder-b", config=h.config(
            config_revision="rev-2", limits={"max_identities": 2}))
        result = h.run(raised)
        assert [d[1:] for d in result["dispositions"]] == [("ACCEPTED", "REKEY")]
        assert [r[1] for r in raised.store.query(SQL_IDENTITY_ALL)] == ["LIVE", "LIVE"]
        assert len(raised.store.query(SQL_RELATION_ALL)) == 1
        assert raised.store.channel()["state"] == "NORMAL"
    finally:
        h.close()


@pytest.mark.parametrize("max_identities, expected", [
    (2, ("ACCEPTED", "REKEY")), (1, None)])
def test_a_rekey_from_an_unknown_old_tuple_records_its_relation_within_the_cap(
        tmp_path, max_identities, expected):
    """RUNTIME-5 (A2F, 2026-10-11): a REKEY whose old tuple this channel never saw is accepted and
    its relation recorded (REQ073: the relation is the record, nothing to merge); only the new
    tuple becomes an identity, and it is held to the cap like any other."""
    h = Harness(tmp_path, limits={"max_identities": max_identities})
    try:
        h.publish(report(1, track_number="OTHER"))      # one LIVE identity already
        h.run()
        old = dict(tuple_of(report(2)), track_number="NEVER-SEEN")
        new = dict(old, track_number="TEST-0002")
        h.publish_notice(notice(3, "REKEY", at_ms=1000, track_number="NEVER-SEEN",
                                old_identity=old, new_identity=new))
        result = h.run()
        key_old = json.dumps(list(old.values()), separators=(",", ":"))
        key_new = json.dumps(list(new.values()), separators=(",", ":"))
        if expected is None:
            assert result == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
            assert h.rows(SQL_RELATION_ALL) == []
            assert len(h.rows(SQL_IDENTITY_ALL)) == 1
            return
        assert [d[1:] for d in result["dispositions"]] == [expected]
        assert h.rows(SQL_RELATION_ALL) == [(key_old, key_new, uid(3), 1791115201000)]
        assert sorted(r[0] for r in h.rows(SQL_IDENTITY_ALL)) == sorted(
            [key_new, json.dumps(["demo", "test-only", True, "exercise-source-1", "OTHER", "0"],
                                 separators=(",", ":"))])
    finally:
        h.close()
