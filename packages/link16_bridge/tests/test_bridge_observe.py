"""Observability (REQ150, REQ151): names, closed labels, audit rows and readiness."""
import json
import logging
import re

import pytest

from helpers import DEST_TUPLE, bidirectional, notice, payload, report, uid
from synapse_cdm.models import Entity
from synapse_link16_bridge import faults, observe


def test_counter_gauge_histogram_names_are_the_required_set():
    assert observe.COUNTERS == ("accepted", "refused", "unsupported", "duplicate",
                                "duplicate_conflict", "late", "time_skew", "dropped_by_capacity",
                                "source_drop", "export_denied", "encoded", "sent",
                                "unknown_send_outcome")
    assert observe.GAUGES == ("native_readiness", "queue_depth", "queue_bytes",
                              "oldest_unacked_age_ms", "active_identities", "stale_identities",
                              "last_accepted_report_age_ms")
    assert observe.HISTOGRAMS == ("parse", "mapping", "outbox_commit", "export")


def test_every_counter_the_bridge_writes_is_a_documented_name(make_harness):
    h = make_harness(**bidirectional())
    h.publish(report(1))
    h.publish(report(1, track_number="X"))
    h.publish(report(2, message_family="J9.9"))
    h.publish(report(3, at_ms=-1000))
    h.publish_notice(notice(4, "DROP_SOURCE", track_number="NONE"))
    h.run()
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    h.bridge.export(entity, None, peer_id="peer-1")
    h.bridge.allocate("peer-1", "dest-realm",
                      '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]',
                      DEST_TUPLE, "allocation")
    h.bridge.export(entity, None, peer_id="peer-1")
    names = set(h.counters())
    assert names <= set(observe.COUNTERS) | {"fed", "quarantine_metadata_only"}
    assert {"accepted", "refused", "unsupported", "duplicate_conflict", "late", "source_drop",
            "export_denied", "encoded", "sent", "fed"} <= names


def test_labels_are_closed_enums():
    for label in observe.LABELS:
        assert re.fullmatch(r"[A-Z][A-Z0-9_]*|J[0-9]\.[0-9]", label), label
    assert not {"48.15", "TEST-0001", "SIMULATED-REPORTER"} & observe.LABELS


def test_the_log_carries_fixed_text_and_closed_codes_only(caplog):
    with caplog.at_level(logging.INFO, logger="synapse_link16_bridge"):
        observe.log_event("channel stopped", "SECURITY_CONTEXT_MISMATCH")
        observe.log_event("channel stopped", "TEST-0001 at 48.15")
    assert [r.getMessage() for r in caplog.records] == [
        "channel stopped: SECURITY_CONTEXT_MISMATCH", "channel stopped: OTHER"]


def test_histograms_count_into_fixed_buckets():
    histograms = observe.Histograms()
    histograms.observe("mapping", 0.0005)
    histograms.observe("mapping", 0.004)
    histograms.observe("mapping", 99.0)
    snapshot = histograms.snapshot()["mapping"]
    assert snapshot["buckets_ms"] == [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 5000]
    assert snapshot["counts"] == [1, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 1]


def test_every_refusal_and_transmission_has_a_full_audit_row(make_harness):
    h = make_harness(**bidirectional())
    h.publish(report(1))
    h.publish(report(2, track_number="T-2", origin_scope="unapproved"))
    result = h.run()
    h.bridge.allocate("peer-1", "dest-realm",
                      '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]',
                      DEST_TUPLE, "allocation record 9")
    entity = Entity.model_validate(payload(h.sink, f"{uid(1)}:0"))
    h.bridge.export(entity, None, peer_id="peer-1", request_id=uid(700))
    rows = h.rows("SELECT kind, subject_id, code, profile_version, config_revision, "
                  "policy_result, transformations, raw_ref, correlation_id FROM audit "
                  "WHERE kind IN ('refusal', 'transmission') ORDER BY seq")
    assert [r[:8] for r in rows] == [
        ("refusal", uid(2), "IDENTITY_SCOPE_UNRESOLVED", "sc-link16-gateway/1.0.0", "rev-1",
         "QUARANTINED", "[]", result["batch_sha256"]),
        ("transmission", uid(700), None, "sc-link16-gateway/1.0.0", "rev-1", "SENT", "[]", None)]
    assert all(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
                            r[8]) for r in rows)
    queued = h.rows("SELECT transformations FROM audit WHERE kind = 'export_queued'")
    assert json.loads(queued[0][0]) == ["identity: UUID5 over scoped track instance"]


def test_no_audit_detail_carries_a_payload_value(make_harness):
    h = make_harness()
    marker = "PAYLOAD-MARKER-" + "p" * 8
    body = report(1, origin_scope="unapproved", track_number=marker)
    h.publish(body)
    h.run()
    text = json.dumps(h.rows("SELECT kind, subject_id, code, policy_result, transformations, "
                             "detail FROM audit"))
    assert marker not in text


@pytest.mark.parametrize("cause, reason", [
    ("provider", "PROVIDER_UNAVAILABLE"), ("commit", "DURABLE_COMMIT_FAILED"),
    ("gap", "CHANNEL_INCOMPLETE")])
def test_readiness_false_for_each_listed_cause(make_harness, cause, reason):
    h = make_harness()
    assert h.bridge.health()["ready"] is True
    if cause == "provider":
        h.server.stop()
        assert h.run()["reason"] == "TRANSPORT"
        from helpers import CONSUMER, CREDENTIAL
        from synapse_link16_bridge.gateway.server import GatewayServer
        h.server = GatewayServer(h.provider, {CREDENTIAL: (CONSUMER, "c1")}).start()
    elif cause == "commit":
        h.bridge.store.faults = faults.CrashPoints(flags={"store.commit_fails"})
        h.publish(report(1))
        assert h.run()["reason"] == "DURABLE_COMMIT_FAILED"
        assert h.provider.health_document("c1")["queue_depth"] == 1   # nothing acknowledged
    else:
        h.publish(report(1))
        h.provider.skip_sequence("c1")
        h.publish(report(2, at_ms=1000))
        h.run()
    health = h.bridge.health()
    assert health["ready"] is False and reason in health["blocked_reasons"]
    assert sorted(health) == ["blocked_reasons", "oldest_unacked_ms", "provider_ready",
                              "queue_depth", "ready"]


def test_gauges_are_the_required_names_with_counts(h):
    h.publish(report(1))
    h.run()
    h.clock.advance(31)
    gauges = h.bridge.gauges()
    assert tuple(gauges) == observe.GAUGES
    assert (gauges["native_readiness"], gauges["active_identities"],
            gauges["stale_identities"]) == (0, 1, 1)


def test_a_sink_failure_is_audited_once_and_health_is_unready_until_the_head_is_delivered(h,
                                                                                          caplog):
    """RUNTIME-4 (A2F, 2026-10-11): a sink that does not take the outbox's head is logged and
    audited with `SINK_FAILED` when it starts failing (one row however many passes it fails),
    health is not ready and `status` says so while the head is undelivered, and its recovery is
    audited once too."""
    h.sink.fail = True
    h.publish(report(1))
    with caplog.at_level("INFO", logger="synapse_link16_bridge"):
        for _ in range(3):
            h.run()
    audit = "SELECT kind, subject_id, code, policy_result FROM audit ORDER BY seq"
    assert h.rows(audit) == [("sink_failed", f"{uid(1)}:0", "SINK_FAILED", "FAILED")]
    assert caplog.text.count("sink delivery failed: SINK_FAILED") == 1
    health = h.bridge.health()
    assert health["ready"] is False and health["blocked_reasons"] == ["SINK_FAILED"]
    assert h.bridge.status_report()["sink_failed"] is True
    h.sink.fail = False
    h.run()
    assert h.rows(audit) == [("sink_failed", f"{uid(1)}:0", "SINK_FAILED", "FAILED"),
                             ("sink_recovered", f"{uid(1)}:0", "SINK_FAILED", "DELIVERED")]
    assert h.bridge.health()["ready"] is True
    assert h.bridge.status_report()["sink_failed"] is False
    assert sorted(h.sink.events) == [f"{uid(1)}:0", f"{uid(1)}:1",
                                     f"{uid(1)}:freshness:ACTIVE:ACTIVE"]
