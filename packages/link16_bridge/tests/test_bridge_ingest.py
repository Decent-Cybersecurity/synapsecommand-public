"""Transactional ingest (REQ001, REQ002, REQ031, REQ032, REQ041, REQ050, REQ051, REQ065,
REQ100, REQ101, REQ162; C01-C04 at the runtime, X12, X13, critic amendment 15)."""
import json

import pytest

from helpers import assert_accounting, payload, report, uid
from synapse_link16_bridge.store import SQL_QUARANTINE_ALL

DOMAINS = (("air_hae_metres_friendly.json", "AIR"), ("surface_zero.json", "SURFACE"),
           ("subsurface_unit_other_depth_unknown_reference.json", "SUBSURFACE"),
           ("land_agl_assumed_friend_earlier_components.json", "LAND"))
INGEST = "SELECT record_key, disposition, code FROM ingest ORDER BY rowid"


def dispositions(result):
    return [d[1:] for d in result["dispositions"]]


def test_four_domains_ingest_end_to_end(h):
    """C01 and REQ001: each domain's report becomes an Entity first and a Track when it carries
    a position, with identity, affiliation, position, motion, quality, times, security context
    and the whole report attributable."""
    for n, (base, _domain) in enumerate(DOMAINS, start=1):
        h.publish(report(n, base=base, track_number=f"D-{n}"))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None)] * 4 and result["acked"] is True
    for n, (base, domain) in enumerate(DOMAINS, start=1):
        entity = payload(h.sink, f"{uid(n)}:0")
        track = payload(h.sink, f"{uid(n)}:1")
        assert (entity["object_kind"], track["object_kind"]) == ("entity", "track")
        assert track["entity_id"] == entity["entity_id"]
        source = entity["residual"]["data"]["report"]
        assert source["domain"] == domain and source["record_id"] == uid(n)
        assert source["security_context"] == "SYNTHETIC-UNCLASSIFIED"
        assert entity["source"]["original_id"] == uid(n)
        assert entity["source"]["system"] == "SC_LINK16_GATEWAY"
        assert entity["source"]["synthetic"] is True
        assert entity["position"]["lat"] == source["position"]["lat_deg"]
    assert payload(h.sink, f"{uid(1)}:0")["affiliation"] == "FRIENDLY"
    assert payload(h.sink, f"{uid(4)}:0")["affiliation"] == "UNKNOWN"
    assert_accounting(h.counters())


def test_outbox_event_keys_are_record_id_and_index(h):
    h.publish(report(1))
    h.publish(report(2, base="land_unknown_position.json", track_number="L-2"))
    h.run()
    cdm = sorted(k for k, v in h.sink.events.items() if v[0] == "cdm")
    assert cdm == [f"{uid(1)}:0", f"{uid(1)}:1", f"{uid(2)}:0"]


def test_bridge_never_rewrites_affiliation(h):
    """REQ041: the published affiliation is the adapter's; the bridge touches nothing."""
    h.publish(report(1, base="air_hae_feet_gnss_hostile.json"))
    h.publish(report(2, base="land_unknown_position.json", track_number="SUSPECT-2"))
    h.run()
    assert payload(h.sink, f"{uid(1)}:0")["affiliation"] == "HOSTILE"
    second = payload(h.sink, f"{uid(2)}:0")
    assert (second["affiliation"], second["residual"]["data"]["report"]["identity"]) == (
        "UNKNOWN", "SUSPECT")


def test_null_components_survive_to_the_sink(h):
    """REQ050: nulls are published as nulls, never zeros."""
    h.publish(report(1, base="surface_baro_pending_null_quality.json"))
    h.publish(report(2, base="subsurface_unit_other_depth_unknown_reference.json",
                     track_number="SUB-2"))
    h.run()
    first, second = payload(h.sink, f"{uid(1)}:0"), payload(h.sink, f"{uid(2)}:0")
    assert first["kinematics"] is None and first["quality"] is None
    assert second["kinematics"] == {"speed_mps": None, "course_deg": None, "climb_mps": None}


def test_unsupported_family_is_opaque_and_never_a_track(h):
    h.publish(report(1, message_family="J7.0"))
    result = h.run()
    assert dispositions(result) == [("OPAQUE", "UNSUPPORTED_MESSAGE")]
    assert [k for k, v in h.sink.events.items() if v[0] == "cdm"] == []
    counters = h.counters()
    assert (counters["refused"], counters["unsupported"]) == (1, 1)


def test_report_missing_a_required_key_is_quarantined_not_treated_as_unchanged(h):
    """REQ031: an omitted required key is malformed, never "unchanged"."""
    h.publish(report(1, at_ms=0))
    missing = report(2, at_ms=1000)
    del missing["kinematics"]
    h.publish(missing)
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("QUARANTINED", "SCHEMA_INVALID")]
    assert [(r[1], r[3], r[4], r[5]) for r in h.rows(SQL_QUARANTINE_ALL)] == [
        (uid(2), "SCHEMA_INVALID", "kinematics", "required")]
    assert h.rows("SELECT record_id FROM current") == [(uid(1),)]


def test_malformed_report_is_quarantined_and_the_rest_continue(h):
    h.publish(report(1))
    bad = report(2, track_number="T-2")
    bad["position"]["lat_deg"] = 91
    h.publish(bad)
    h.publish(report(3, track_number="T-3"))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("QUARANTINED", "SCHEMA_INVALID"),
                                    ("ACCEPTED", None)]
    assert result["acked"] is True and h.provider.health_document("c1")["queue_depth"] == 0
    assert h.rows("SELECT COUNT(*) FROM audit WHERE kind = 'refusal'") == [(1,)]
    assert_accounting(h.counters())


@pytest.mark.parametrize("fault, rule", [
    (b'{"record_id":"x","a":1,"a":2}', "duplicate object key"),
    (b'{"a":NaN}', "non-finite number literal"),
    (b'{"a":"\\ud834"}', "lone surrogate"),
    (b'{"a":12345678901234567890}', "integer not exactly representable as a double"),
])
def test_a_json_fault_inside_one_report_is_json_invalid_and_the_rest_continue(h, fault, rule):
    h.publish(report(1))
    h.provider.inject_record("c1", "report", fault)
    h.publish(report(3, track_number="T-3"))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("QUARANTINED", "JSON_INVALID"),
                                    ("ACCEPTED", None)]
    assert [(r[3], r[5]) for r in h.rows(SQL_QUARANTINE_ALL)] == [("JSON_INVALID", rule)]
    assert result["acked"] is True
    raw = h.bridge.store.read_raw_evidence(result["batch_sha256"])
    assert raw is not None and fault in raw


def test_structurally_invalid_batch_is_not_partially_consumed(h):
    h.publish(report(1))
    h.provider.inject_record("c1", "report", b'{"broken":')
    for attempt in (1, 2):
        result = h.run()
        assert result == {"fetched": True, "reason": "JSON_INVALID"}
        assert h.bridge.store.channel()["retry_count"] == attempt
    assert h.rows(INGEST) == [] and h.sink.events == {}
    assert h.provider.health_document("c1")["queue_depth"] == 2
    assert h.run() == {"fetched": True, "reason": "STRUCTURAL_BATCH"}
    assert h.bridge.store.channel()["state"] == "STOPPED"
    assert h.run() == {"fetched": False, "reason": "STOPPED"}
    assert h.counters().get("fed", 0) == 0


def nested(depth: int) -> dict:
    """A JSON object of `depth` containers (the object itself counts one)."""
    node: dict = {}
    for _ in range(depth - 1):
        node = {"x": node}
    return node


def test_a_legal_depth_32_report_is_accepted_and_33_is_limit_exceeded_per_record(h):
    deepest = report(1, source_fields=nested(31))
    too_deep = report(2, track_number="T-2", source_fields=nested(32))
    h.publish(deepest)
    h.publish(too_deep)
    h.publish(report(3, track_number="T-3"))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("QUARANTINED", "LIMIT_EXCEEDED"),
                                    ("ACCEPTED", None)]


def test_a_body_deeper_than_the_batch_bound_makes_the_batch_structurally_invalid(h):
    """Amendment 15: a body nested deeper than 64 below the envelope is a batch fault: nothing
    consumed, no ack, the channel degraded and LIMIT_EXCEEDED in the audit."""
    h.publish(report(1))
    h.publish(report(2, track_number="T-2", source_fields=nested(65)))
    assert h.run() == {"fetched": True, "reason": "LIMIT_EXCEEDED"}
    channel = h.bridge.store.channel()
    assert (channel["degraded"], channel["retry_count"]) == (1, 1)
    assert h.rows("SELECT kind, code FROM audit") == [("structural_batch", "LIMIT_EXCEEDED")]
    assert h.rows(INGEST) == []


def test_dedupe_key_and_state_key_are_independent(h):
    """REQ032 and REQ101: deduplication by (gateway, record id); state by identity tuple."""
    h.publish(report(1, at_ms=0))
    h.publish(report(1, at_ms=0, track_number="ANOTHER-TRACK"))
    h.publish(report(2, at_ms=1000))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("QUARANTINED", "DUPLICATE_CONFLICT"),
                                    ("ACCEPTED", None)]
    assert h.bridge.store.channel()["degraded"] == 1
    counters = h.counters()
    assert (counters["duplicate_conflict"], counters["refused"], counters["accepted"]) == (1, 1, 2)
    assert_accounting(counters)


def test_identical_redelivery_yields_no_second_publication(h):
    h.publish(report(1))
    h.publish(report(2, track_number="T-2"))
    octets = h.client().reports(None, 100)
    h.run()
    published = dict(h.sink.events)
    outcome = h.bridge.ingestor.process(octets, None)
    assert [d[1:] for d in outcome.dispositions] == [("DUPLICATE", None), ("DUPLICATE", None)]
    h.bridge.run_once()
    assert h.sink.events.keys() == published.keys()
    counters = h.counters()
    assert (counters["fed"], counters["duplicate"], counters["accepted"]) == (4, 2, 2)
    assert_accounting(counters)


def test_sequence_gap_within_a_session_is_stream_gap_and_the_record_is_processed(h):
    h.publish(report(1))
    h.provider.skip_sequence("c1")
    h.publish(report(2, at_ms=1000))
    result = h.run()
    assert dispositions(result) == [("ACCEPTED", None), ("ACCEPTED", None)]
    assert h.bridge.store.channel()["state_reason"] == "STREAM_GAP"
    assert h.rows("SELECT code FROM audit WHERE kind = 'stream_gap'") == [("STREAM_GAP",)]


def test_new_session_restarts_sequence(h):
    h.publish(report(1))
    h.run()
    h.provider.new_session("c1")
    h.publish(report(2, at_ms=1000))
    h.run()
    assert h.bridge.store.channel()["state"] == "NORMAL"


def test_accounting_holds_after_every_batch(h):
    batches = [[report(1)], [report(1), report(2, track_number="T-2", message_family="J9.9")],
               [report(3, base="land_unknown_position.json", origin_scope="unapproved")]]
    for batch in batches:
        for body in batch:
            h.publish(body)
        h.run()
        assert_accounting(h.counters())
    counters = h.counters()
    # report 1 published again is stamped with a new sequence, so its body differs: a conflict
    assert (counters["fed"], counters["accepted"], counters["refused"],
            counters.get("duplicate", 0), counters["duplicate_conflict"]) == (4, 1, 3, 0, 1)


def test_records_reach_the_sink_only_after_commit_and_ack(h):
    """REQ100: commit, then acknowledge the gateway, then deliver the outbox."""
    order = []

    class Spy:
        accepts = h.sink.accepts

        def deliver(self, key, kind, data, flags):
            committed = h.bridge.store.query("SELECT COUNT(*) FROM ingest")[0][0]
            order.append(("deliver", key, committed))

    h.bridge.sink = Spy()
    real_ack = h.bridge.client.ack

    def ack(consumer, cursor):
        order.append(("ack", cursor, h.bridge.store.query("SELECT COUNT(*) FROM ingest")[0][0]))
        return real_ack(consumer, cursor)

    h.bridge.client.ack = ack
    h.publish(report(1))
    h.run()
    assert order[0] == ("ack", "1.1", 1)
    assert [entry[0] for entry in order[1:]] == ["deliver"] * 3


def test_the_raw_batch_is_kept_as_evidence_only_for_a_refusal(h):
    h.publish(report(1))
    clean = h.run()
    h.publish(report(2, track_number="T-2", message_family="J7.0"))
    refused = h.run()
    assert h.bridge.store.read_raw_evidence(clean["batch_sha256"]) is None
    kept = h.bridge.store.read_raw_evidence(refused["batch_sha256"])
    assert json.loads(kept)["records"][0]["body"]["message_family"] == "J7.0"


def run_passes(h, passes):
    """`run()` for exactly `passes` passes; returns each pass's result."""
    results = []
    real_run_once = h.bridge.run_once
    h.bridge.run_once = lambda: results.append(real_run_once()) or results[-1]
    h.bridge.run(should_stop=lambda: len(results) >= passes)
    return results


def test_the_loop_waits_the_idle_interval_after_a_pass_that_fetched_nothing(h):
    """R4-F6 (fix round 1, 2026-10-11): a pass on a STOPPED channel contacts no gateway; `run()`
    then waits `idle_poll_seconds` (default 1) before the next pass instead of spinning."""
    h.publish(report(1, tenant="another-tenant"))
    h.run()
    assert h.bridge.store.channel()["state"] == "STOPPED"
    before = list(h.sleeper.delays)
    results = run_passes(h, 5)
    assert [r["reason"] for r in results] == ["STOPPED"] * 5
    assert h.sleeper.delays[len(before):] == [1.0] * 4


def test_the_loop_fetches_again_at_once_after_records_and_idles_after_an_empty_batch(make_harness):
    h = make_harness(idle_poll_seconds=0.5)
    h.publish(report(1))
    results = run_passes(h, 3)
    assert [len(r["dispositions"]) for r in results] == [1, 0, 0]
    assert h.sleeper.delays == [0.5]                # after the 2nd (empty) pass; none after the 1st
    h.provider.unavailable = True                   # a backoff wait is not followed by an idle one
    results = run_passes(h, 3)
    assert [r["reason"] for r in results] == ["PROVIDER_UNAVAILABLE"] * 3
    assert len(h.sleeper.delays) == 1 + 3 and 0.5 not in h.sleeper.delays[1:]


@pytest.mark.parametrize("sequence, rule", [
    ("1" * 4301, "pattern"), ("9" * 5000, "pattern"), ("1" * 21, "pattern"),
    ("18446744073709551616", "uint64"), ("01", "pattern"), ("-1", "pattern"), ("１", "pattern")],
    ids=["4301-digits", "5000-digits", "21-digits", "uint64-plus-1", "leading-zero", "minus-one",
         "fullwidth-digit"])
def test_a_sequence_outside_the_contract_form_is_judged_by_the_adapter_and_the_batch_continues(
        h, sequence, rule):
    """RUNTIME-1 (A2F, 2026-10-11): the contiguity check reads a `sequence` only in the contract's
    form, `0|[1-9][0-9]{0,19}` holding a uint64, and never converts a longer digit string (4 301
    digits or more raised out of the pass and poisoned the channel). Such a record is the
    adapter's to judge: quarantined `SCHEMA_INVALID` at `sequence`, and the record after it is
    accepted, acknowledged and on a NORMAL channel."""
    session, slot = h.provider.session("c1")
    assert slot == 0
    h.publish(report(1, session_id=session, sequence=sequence), stamp_delivery=False)
    h.publish(report(2, track_number="T-2"))                       # stamped: sequence "1"
    result = h.run()
    assert dispositions(result) == [("QUARANTINED", "SCHEMA_INVALID"), ("ACCEPTED", None)]
    assert result["acked"] is True and h.bridge.status == "READY"
    assert [r[3:6] for r in h.rows(SQL_QUARANTINE_ALL)] == [("SCHEMA_INVALID", "sequence", rule)]
    assert h.bridge.store.channel()["state"] == "NORMAL"
    assert h.rows("SELECT session_id, last_sequence FROM session_seq") == [(session, "1")]
    assert h.provider.health_document("c1")["queue_depth"] == 0
    assert_accounting(h.counters())


def test_an_unexpected_exception_ends_the_pass_blocked_with_an_audited_internal_error(
        h, monkeypatch, caplog):
    """RUNTIME-1 (A2F, 2026-10-11): the last resort. An exception the pass does not expect ends
    it BLOCKED with `INTERNAL_ERROR`: one audit row naming the exception's type and never its
    text, nothing acknowledged, health not ready, and `run()` returns instead of raising."""
    marker = "payload-marker-" + "q" * 8
    h.publish(report(1))

    def explode(octets, cursor_before):
        raise KeyError(marker)

    monkeypatch.setattr(h.bridge.ingestor, "process", explode)
    with caplog.at_level("INFO", logger="synapse_link16_bridge"):
        assert h.run() == {"fetched": False, "reason": "INTERNAL_ERROR"}
    assert (h.bridge.status, h.bridge.blocked_reasons) == ("BLOCKED", ["INTERNAL_ERROR"])
    assert h.rows("SELECT kind, code, policy_result, detail FROM audit") == [
        ("internal_error", "INTERNAL_ERROR", "BLOCKED", "KeyError")]
    assert marker not in json.dumps(h.rows("SELECT * FROM audit")) and marker not in caplog.text
    assert "unexpected failure: INTERNAL_ERROR" in caplog.text
    health = h.bridge.health()
    assert health["ready"] is False and "INTERNAL_ERROR" in health["blocked_reasons"]
    assert h.provider.health_document("c1")["queue_depth"] == 1     # nothing acknowledged
    h.bridge.run()                                  # returns at once: the bridge is BLOCKED
    assert h.run() == {"fetched": False, "reason": "BLOCKED"}


def test_a_legal_depth_32_report_reaches_a_jsonl_sink_file(h, tmp_path):
    """RUNTIME-4 (A2F, 2026-10-11): a report at the contract's depth 32 is accepted, and its
    Entity (deeper than 32 once wrapped) reaches the directory sink: the sink writes the canonical
    octets it was handed and never parses them again."""
    from synapse_link16_bridge.bridge import JsonlSink
    from synapse_link16_bridge.jsonstrict import sha256_hex
    sink = JsonlSink(tmp_path / "sink", ("3.0.0",))
    h.bridge.close()
    bridge = h.new_bridge(holder="holder-jsonl", sink=sink)
    h.publish(report(1, source_fields=nested(31)))
    result = h.run(bridge)
    assert dispositions(result) == [("ACCEPTED", None)]
    key = f"{uid(1)}:0"
    entity = bridge.store.one("SELECT payload FROM outbox WHERE event_key = ?", (key,))[0]
    written = (tmp_path / "sink" / (sha256_hex(key.encode("utf-8")) + ".json")).read_bytes()
    assert written == (b'{"event_key":"' + key.encode("ascii") +
                       b'","flags":[],"kind":"cdm","payload":' + bytes(entity) + b"}\n")
    assert bridge.store.one("SELECT COUNT(*) FROM outbox WHERE dispatched_at IS NULL") == (0,)
    assert bridge.health()["ready"] is True and bridge.sink_failed is None


def test_the_jsonl_line_is_the_canonical_object_around_the_handed_octets(tmp_path):
    """RUNTIME-4 (A2F, 2026-10-11): the line's bytes, written without a parse of the payload."""
    from synapse_link16_bridge.bridge import JsonlSink
    sink = JsonlSink(tmp_path, ("3.0.0",))
    sink.deliver("k:0", "cdm", b'{"a":[1,{"b":"\xc3\xa9"}]}', ("LATE", "CONFLICT"))
    (written,) = tmp_path.glob("*.json")
    assert written.name == "741d7d6f653e4d092980f84b4bcec44f36584ab6ea59cd409833a42c553a6ed5.json"
    assert written.read_bytes() == (b'{"event_key":"k:0","flags":["LATE","CONFLICT"],'
                                    b'"kind":"cdm","payload":{"a":[1,{"b":"\xc3\xa9"}]}}\n')
