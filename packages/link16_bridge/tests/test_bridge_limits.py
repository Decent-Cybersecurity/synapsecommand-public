"""Capacity (REQ120-122, REQ063, REQ162; acceptance row F02)."""
import pytest

from helpers import assert_accounting, report, uid
from synapse_link16_bridge import limits
from synapse_link16_bridge.store import SQL_QUARANTINE_ALL


def bad(n):
    body = report(n, track_number=f"BAD-{n}")
    body["position"]["lat_deg"] = 95
    return body


def test_quarantine_cap_switches_to_metadata_only_with_alarm(make_harness):
    h = make_harness(limits={"max_quarantine_bytes": 2000})
    h.publish(bad(1))
    first = h.run()
    h.publish(bad(2))
    second = h.run()
    rows = h.rows(SQL_QUARANTINE_ALL)
    assert [(r[1], r[3], r[7]) for r in rows] == [(uid(1), "SCHEMA_INVALID", 0),
                                                   (uid(2), "SCHEMA_INVALID", 1)]
    assert h.rows("SELECT body IS NULL, bytes FROM quarantine WHERE record_key = ?",
                  (uid(2),)) == [(1, 0)]
    assert h.counters()["quarantine_metadata_only"] == 1
    assert h.bridge.store.read_raw_evidence(first["batch_sha256"]) is not None
    assert h.bridge.store.read_raw_evidence(second["batch_sha256"]) is None
    assert "CAPACITY_QUARANTINE" in h.bridge.status_report()["warnings"]
    assert_accounting(h.counters())


def test_queue_cap_stops_fetching_without_loss(make_harness):
    h = make_harness(limits={"max_queued_reports": 2})
    h.sink.fail = True
    h.publish(report(1))
    h.run()
    assert limits.usage(h.bridge.store).queued_reports == 3     # Entity, Track, freshness
    h.publish(report(2, track_number="T-2"))
    assert h.run() == {"fetched": False, "reason": "CAPACITY_REPORTS"}
    assert h.bridge.store.channel()["state"] == "OVERLOADED"
    assert "CAPACITY_REPORTS" in h.bridge.health()["blocked_reasons"]
    assert h.provider.health_document("c1")["queue_depth"] == 1   # kept at the gateway
    h.sink.fail = False
    assert h.run() == {"fetched": False, "reason": "CAPACITY_REPORTS"}   # this pass drains
    assert limits.usage(h.bridge.store).queued_reports == 0
    result = h.run()
    assert result["dispositions"] == [(uid(2), "ACCEPTED", None)]
    assert h.bridge.store.channel()["state"] == "NORMAL"
    assert sorted(k for k, v in h.sink.events.items() if v[0] == "cdm") == [
        f"{uid(1)}:0", f"{uid(1)}:1", f"{uid(2)}:0", f"{uid(2)}:1"]
    assert h.counters()["fed"] == 2


def test_gateway_byte_bound_loss_is_accounted_at_resynchronisation(make_harness):
    h = make_harness(provider_kwargs={"retention_bytes": 2500})
    h.publish(report(1))
    h.run()
    for n in (2, 3, 4):
        h.publish(report(n, track_number=f"T-{n}"))
    losses = h.provider.losses("c1")
    lost = sum(loss["count"] for loss in losses)
    assert lost == 1 and losses[0]["reason"] == "RETENTION_BYTES"
    assert h.run()["reason"] == "CURSOR_EXPIRED"
    h.bridge.resync("the gateway's loss rows for the expired range", lost_count=lost)
    h.run()
    counters = h.counters()
    assert (counters["fed"], counters["accepted"], counters["dropped_by_capacity"]) == (4, 3, 1)
    assert_accounting(counters)
    assert h.bridge.store.channel()["state"] == "INCOMPLETE"


def test_warning_at_80_percent(make_harness):
    h = make_harness(limits={"max_queued_reports": 10})
    h.sink.fail = True
    for n in range(1, 4):
        h.publish(report(n, track_number=f"T-{n}"))
    h.run()
    used = limits.usage(h.bridge.store)
    assert used.queued_reports == 9
    assert limits.warnings(used, h.bridge.config.limits) == ["CAPACITY_REPORTS"]
    assert limits.full(used, h.bridge.config.limits) == []
    assert h.bridge.status_report()["warnings"] == ["CAPACITY_REPORTS"]


def test_the_published_defaults_are_the_specifications():
    from synapse_link16_bridge.config import DEFAULT_LIMITS
    assert {k: DEFAULT_LIMITS[k] for k in ("max_identities", "max_queued_reports",
                                           "max_queued_report_bytes", "max_queued_exports",
                                           "max_queued_export_bytes", "max_quarantine_bytes")} == {
        "max_identities": 100000, "max_queued_reports": 10000,
        "max_queued_report_bytes": 64 * 1024 * 1024, "max_queued_exports": 4096,
        "max_queued_export_bytes": 16 * 1024 * 1024, "max_quarantine_bytes": 1024 ** 3}
    assert limits.WARNING_FRACTION == 0.8


def test_the_80_percent_warning_is_counted_once_per_entry_into_the_band(make_harness):
    """R4-F8 (fix round 1, 2026-10-11): entering the band counts `capacity_warning` once and
    logs the cap's code; staying in it counts nothing more; leaving and re-entering counts
    again."""
    h = make_harness(limits={"max_queued_reports": 10})
    h.sink.fail = True
    for n in range(1, 4):
        h.publish(report(n, track_number=f"T-{n}"))
    h.run()                                         # 9 queued after this pass
    assert "capacity_warning" not in h.counters()
    h.run()
    h.run()
    assert h.counters()["capacity_warning"] == 1
    h.sink.fail = False
    h.run()                                         # drains: below the band
    h.sink.fail = True
    for n in range(4, 7):
        h.publish(report(n, track_number=f"T-{n}"))
    h.run()
    h.run()
    assert h.counters()["capacity_warning"] == 2


def test_past_the_quarantine_cap_a_batch_reads_the_quarantine_size_once(make_harness,
                                                                         monkeypatch):
    """R4-F10 (fix round 1, 2026-10-11): the quarantine's size is read once per batch, not once
    per refusal; past the cap each refusal is metadata only and counted."""
    h = make_harness(limits={"max_quarantine_bytes": 2000})
    h.publish(bad(1))
    h.run()
    for n in range(2, 7):
        h.publish(bad(n))
    reads = []
    real = limits.quarantine_bytes
    monkeypatch.setattr(limits, "quarantine_bytes", lambda store: reads.append(1) or real(store))
    result = h.run()
    assert [d[1:] for d in result["dispositions"]] == [("QUARANTINED", "SCHEMA_INVALID")] * 5
    assert len(reads) == 2                          # the pass's usage, then the batch's one read
    rows = h.rows(SQL_QUARANTINE_ALL)
    assert [r[7] for r in rows] == [0, 1, 1, 1, 1, 1]
    assert h.counters()["quarantine_metadata_only"] == 5
    assert h.bridge.store.read_raw_evidence(result["batch_sha256"]) is None
    assert_accounting(h.counters())


CAPS = {"max_queued_reports": 10, "max_queued_report_bytes": 1000, "max_queued_exports": 4,
        "max_queued_export_bytes": 400, "max_identities": 5, "max_quarantine_bytes": 2000}


def usage(**at):
    fields = {"queued_reports": 0, "queued_report_bytes": 0, "oldest_queued_at": None,
              "queued_exports": 0, "queued_export_bytes": 0, "identities": 0,
              "quarantine_bytes": 0}
    fields.update(at)
    return limits.Usage(**fields)


@pytest.mark.parametrize("at, expected", [
    ({}, []),
    ({"queued_reports": 9, "queued_report_bytes": 999, "queued_exports": 3,
      "queued_export_bytes": 399, "identities": 4, "quarantine_bytes": 1999}, []),
    ({"queued_reports": 10}, ["CAPACITY_REPORTS"]),
    ({"queued_report_bytes": 1000}, ["CAPACITY_REPORTS"]),
    ({"queued_exports": 4}, ["CAPACITY_EXPORTS"]),
    ({"queued_export_bytes": 400}, ["CAPACITY_EXPORTS"]),
    ({"identities": 5}, ["CAPACITY_IDENTITIES"]),
    ({"quarantine_bytes": 2000}, ["CAPACITY_QUARANTINE"]),
    ({"queued_reports": 11, "queued_report_bytes": 1001, "queued_exports": 4,
      "queued_export_bytes": 400, "identities": 6, "quarantine_bytes": 2001},
     ["CAPACITY_REPORTS", "CAPACITY_EXPORTS", "CAPACITY_IDENTITIES", "CAPACITY_QUARANTINE"]),
], ids=["empty", "below-every-cap", "report-count", "report-bytes", "export-count", "export-bytes",
        "identities", "quarantine", "every-cap"])
def test_full_names_every_cap_of_every_kind(at, expected):
    """RUNTIME-8 (A2F, 2026-10-11): `full` covers every capacity kind, each code once, in a fixed
    order; below every cap it is empty."""
    assert limits.full(usage(**at), CAPS) == expected


def test_only_the_report_queue_stops_fetching():
    """RUNTIME-8 (A2F, 2026-10-11): the one kind of cap at which the bridge stops fetching."""
    assert limits.STOPS_FETCHING == ("CAPACITY_REPORTS",)


def test_two_hundred_idle_passes_at_the_identity_cap_write_no_audit_row(make_harness):
    """RUNTIME-8 (A2F, 2026-10-11): a batch that would add an identity past the cap is not
    consumed, and the channel is OVERLOADED with one `capacity` audit row; every later pass that
    meets the same batch finds the channel held by the same cap and writes nothing (it had
    cleared and re-set the state with two audit rows a pass). A batch consumed after the cap is
    raised clears it with one `capacity_cleared` row."""
    h = make_harness(limits={"max_identities": 1})
    h.publish(report(1))
    h.run()
    h.publish(report(2, track_number="T-2"))
    assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
    audit = "SELECT kind, code FROM audit ORDER BY seq"
    assert h.rows(audit) == [("capacity", "CAPACITY_IDENTITIES")]
    for _ in range(200):
        assert h.run() == {"fetched": True, "reason": "CAPACITY_IDENTITIES"}
    assert h.rows(audit) == [("capacity", "CAPACITY_IDENTITIES")]
    channel = h.bridge.store.channel()
    assert (channel["state"], channel["state_reason"]) == ("OVERLOADED", "CAPACITY_IDENTITIES")
    assert h.bridge.status_report()["full"] == ["CAPACITY_IDENTITIES"]
    h.bridge.close()
    raised = h.new_bridge(holder="holder-b", config=h.config(
        config_revision="rev-2", limits={"max_identities": 2}))
    assert [d[1:] for d in h.run(raised)["dispositions"]] == [("ACCEPTED", None)]
    assert raised.store.query(audit) == [("capacity", "CAPACITY_IDENTITIES"),
                                         ("capacity_cleared", "CAPACITY_IDENTITIES")]
    assert raised.store.channel()["state"] == "NORMAL"


def test_two_hundred_idle_passes_at_the_report_queue_cap_write_no_audit_row(make_harness):
    """RUNTIME-8 (A2F, 2026-10-11): the report-queue cap holds the channel with one `capacity` row
    however many passes meet it, and clears with one `capacity_cleared` row once the queue drains."""
    h = make_harness(limits={"max_queued_reports": 2})
    h.sink.fail = True
    h.publish(report(1))
    h.run()
    audit = "SELECT kind, code FROM audit WHERE kind LIKE 'capacity%' ORDER BY seq"
    for _ in range(200):
        assert h.run() == {"fetched": False, "reason": "CAPACITY_REPORTS"}
    assert h.rows(audit) == [("capacity", "CAPACITY_REPORTS")]
    h.sink.fail = False
    h.run()                                             # drains under the cap
    h.run()
    assert h.rows(audit) == [("capacity", "CAPACITY_REPORTS"),
                             ("capacity_cleared", "CAPACITY_REPORTS")]
