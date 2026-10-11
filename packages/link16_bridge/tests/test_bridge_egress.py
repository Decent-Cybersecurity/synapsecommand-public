"""Authorised export (REQ001, REQ091-097, REQ131-133; E01-E05)."""
import json

import pytest

from helpers import DEST_TUPLE, bidirectional, notice, payload, report, uid
from synapse_cdm.models import Entity, Track
from synapse_link16_bridge import faults, jsonstrict
from synapse_link16_bridge.gateway.client import SendOutcomeUnknown
from synapse_link16_bridge.store import SQL_JOB_GET, SQL_JOBS_ALL

KEY = '["demo","test-only",true,"exercise-source-1","TEST-0001","0"]'


def ready(make_harness, *, report_changes=None, destination=None, **options):
    """A bidirectional harness with report 1 ingested and its allocation recorded."""
    changes = bidirectional(**(destination or {}))
    changes.update(options.pop("config", {}))
    h = make_harness(**changes, **options)
    h.publish(report(1, **(report_changes or {})))
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "provider allocation record 7")
    return h


def objects(h, n=1):
    entity = Entity.model_validate(payload(h.sink, f"{uid(n)}:0"))
    key = f"{uid(n)}:1"
    track = Track.model_validate(payload(h.sink, key)) if key in h.sink.events else None
    return entity, track


def test_an_authorised_export_is_sent_once_with_the_destination_identity(make_harness):
    h = ready(make_harness)
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(500))
    assert (result["request_id"], result["state"], result["reason"]) == (uid(500), "SENT", None)
    sent = h.provider.sent()
    assert [s["request_id"] for s in sent] == [uid(500)]
    emitted = json.loads(sent[0]["encoded"])
    assert {k: emitted[k] for k in ("tenant", "realm", "synthetic", "origin_scope",
                                    "track_number", "incarnation")} == DEST_TUPLE
    assert (emitted["security_context"], emitted["message_family"], emitted["reporter"],
            emitted["native_profile"], emitted["domain"], emitted["identity"]) == (
        "SYNTHETIC-DEST", "J3.2", "consumer-1", "SYNTHETIC-NO-NATIVE-CODEC", "AIR", "FRIENDLY")
    assert emitted["effective_at"] == "2026-10-04T12:00:00.000Z"
    assert emitted["position"]["observed_at"] == "2026-10-04T12:00:00.000Z"
    assert emitted["position"]["vertical"] == {"value": 1524.0, "unit": "m", "reference": "HAE"}
    assert emitted["extensions"]["sc-link16-export/1"]["provenance"] == {
        "source_entity_id": str(entity.entity_id), "source_record_id": uid(1),
        "policy_revision": "policy-1"}
    counters = h.counters()
    assert (counters["encoded"], counters["sent"]) == (1, 1)


def test_export_only_when_separately_enabled(h):
    """REQ001 and REQ004: an ingest-only configuration denies every export."""
    h.publish(report(1))
    h.run()
    entity, _track = objects(h)
    result = h.bridge.export(entity, None, peer_id="peer-1")
    assert (result["state"], result["reason"]) == ("DENIED", "POLICY_DENIED")
    assert h.provider.sent() == [] and h.counters()["export_denied"] == 1


def test_policy_without_a_resolving_rule_denies_with_zero_sends(make_harness):
    h = ready(make_harness)
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-2")
    assert (result["state"], result["reason"]) == ("DENIED", "POLICY_DENIED")
    audit = h.rows("SELECT kind, code, policy_result, correlation_id FROM audit "
                   "WHERE kind = 'export_denied'")
    assert [a[:3] for a in audit] == [("export_denied", "POLICY_DENIED", "DENIED")]
    assert len(audit[0][3]) == 36
    assert h.provider.sent() == []


def test_synthetic_source_to_live_destination_is_denied(make_harness):
    h = ready(make_harness, destination={"synthetic": False})
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "SYNTHETIC_MISMATCH"
    assert h.provider.sent() == []


def test_no_reexport_to_the_ingress_realm(make_harness):
    """REQ133: the destination realm equal to the ingress realm is a loop."""
    h = ready(make_harness, destination={"realm": "test-only"})
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "REALM_LOOP"
    assert h.provider.sent() == []


def test_unallocated_number_is_refused(make_harness):
    changes = bidirectional()
    h = make_harness(**changes)
    h.publish(report(1))
    h.run()
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "NUMBER_UNALLOCATED"
    assert h.provider.sent() == []


def test_family_not_allowed(make_harness):
    h = ready(make_harness, config={"transmit_families": ["J3.4"]})
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "FAMILY_NOT_ALLOWED"


def test_wrong_native_profile_is_refused_before_send(make_harness):
    h = ready(make_harness, config={"native_profile": "ANOTHER-EDITION"})
    entity, track = objects(h)
    assert h.bridge.status == "DEGRADED_INGEST_ONLY"
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "PROFILE_NOT_READY"
    assert h.provider.sent() == []


class ExpireBeforeSend(faults.CrashPoints):
    """Moves the clock past the job's expiry between its commit and its send."""

    def __init__(self, clock):
        super().__init__()
        self.clock = clock

    def hit(self, name):
        if name == "egress.after_job_commit_before_send":
            self.clock.advance(10)


def test_expired_request_is_refused_and_never_sent(make_harness):
    h = ready(make_harness)
    h.bridge.egress.faults = ExpireBeforeSend(h.clock)
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(501))
    assert (result["state"], result["reason"]) == ("EXPIRED", "REQUEST_EXPIRED")
    assert h.provider.sent() == []
    assert h.bridge.egress.send(uid(501))["state"] == "EXPIRED"
    assert h.rows(SQL_JOBS_ALL) == [(uid(501), "EXPIRED", "REQUEST_EXPIRED", 0, 0, 1)]


def test_motion_age_is_checked_separately_from_position_age(make_harness):
    stale_motion = report(1, at_ms=10_000)
    stale_motion["kinematics"]["observed_at"] = "2026-10-04T12:00:00.000Z"
    h = make_harness(**bidirectional())
    h.publish(stale_motion)
    h.clock.advance(10)
    h.run()
    h.bridge.allocate("peer-1", "dest-realm", KEY, DEST_TUPLE, "allocation")
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "SOURCE_STALE"
    h.clock.advance(-0.001)
    assert h.bridge.export(entity, track, peer_id="peer-1")["state"] == "SENT"


def test_unsupported_datum_refusal_is_audited_with_loss_report_and_zero_sends(make_harness):
    """E03: the destination carries MSL only and needs a height; the source has HAE metres."""
    h = ready(make_harness, destination={"vertical_forms": [["ft", "MSL"]],
                                         "vertical_required": True})
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(502))
    assert (result["state"], result["reason"], result["path"]) == (
        "DENIED", "ALTITUDE_DATUM_UNSUPPORTED", "entity.position.vertical")
    assert result["losses"] == [{"path": "entity.position.vertical",
                                 "code": "ALTITUDE_DATUM_UNSUPPORTED", "disposition": "REFUSED",
                                 "rule": "the destination form does not carry this datum"}]
    job = h.rows(SQL_JOB_GET, (uid(502),))[0]
    assert (job[7], job[8], json.loads(job[12])) == ("DENIED", "ALTITUDE_DATUM_UNSUPPORTED",
                                                    result["losses"])
    assert h.provider.sent() == []


def test_an_optional_unsupported_height_is_omitted_with_a_loss(make_harness):
    h = ready(make_harness, destination={"vertical_forms": [["ft", "MSL"]]})
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["state"] == "SENT"
    emitted = json.loads(h.provider.sent()[0]["encoded"])
    assert emitted["position"]["vertical"] is None
    assert emitted["extensions"]["sc-link16-export/1"]["losses"] == [
        {"path": "entity.position.vertical", "code": "ALTITUDE_DATUM_UNSUPPORTED",
         "disposition": "OMITTED", "rule": "the destination form does not carry this datum"}]


def test_a_closed_state_is_never_exported(make_harness):
    """A closed state never reaches the adapter (whose own refusal of one,
    VALUE_NOT_REPRESENTABLE at `entity.valid_to`, is the host test
    `test_cdm_link16_gateway_adapter.py::test_export_value_not_representable_cases`): a
    caller's closed copy of the current snapshot is not the stored snapshot (fix round 1,
    2026-10-11), and after an authorised drop neither the last snapshot nor the close event's
    Entity is exported. Zero sends throughout."""
    h = ready(make_harness)
    entity, _track = objects(h)
    closed = Entity.model_validate(dict(entity.model_dump(), valid_to=entity.valid_from))
    result = h.bridge.export(closed, None, peer_id="peer-1")
    assert (result["state"], result["reason"]) == ("DENIED", "SOURCE_STALE")
    h.publish_notice(notice(2, "DROP_SOURCE", at_ms=1000))
    h.run()
    dropped = Entity.model_validate(payload(h.sink, f"{uid(2)}:0"))
    assert dropped.valid_to is not None
    for candidate in (entity, dropped):
        result = h.bridge.export(candidate, None, peer_id="peer-1")
        assert (result["state"], result["reason"]) == ("DENIED", "POLICY_DENIED")
    assert h.provider.sent() == []
    assert h.counters()["export_denied"] == 3


def test_an_export_of_a_changed_or_older_snapshot_is_denied(make_harness):
    """R4-F5 (fix round 1, 2026-10-11): `export` takes the stored current snapshot only. An
    Entity whose latitude the caller moved, a Track the caller changed, and the Entity of an
    older record are each SOURCE_STALE, audited, with zero sends; the stored snapshot itself is
    then sent with the stored record's time and provenance."""
    h = ready(make_harness)
    h.publish(report(2, at_ms=1000))
    h.run()
    entity, track = objects(h, 2)
    moved = entity.model_dump()
    moved["position"]["lat"] += 1.0
    changed_track = track.model_dump()
    changed_track["samples"][0]["position"]["lat"] += 1.0
    older, older_track = objects(h, 1)
    for candidate, candidate_track in ((Entity.model_validate(moved), track),
                                       (entity, Track.model_validate(changed_track)),
                                       (older, older_track), (older, None)):
        result = h.bridge.export(candidate, candidate_track, peer_id="peer-1")
        assert (result["state"], result["reason"]) == ("DENIED", "SOURCE_STALE")
    assert h.provider.sent() == []
    assert [r[0] for r in h.rows("SELECT code FROM audit WHERE kind = 'export_denied'")] == \
        ["SOURCE_STALE"] * 4
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(510))
    assert (result["state"], result["reason"]) == ("SENT", None)
    emitted = json.loads(h.provider.sent()[0]["encoded"])
    assert (emitted["position"]["lat_deg"], emitted["position"]["observed_at"]) == (
        entity.position.lat, "2026-10-04T12:00:01.000Z")
    assert emitted["extensions"]["sc-link16-export/1"]["provenance"]["source_record_id"] == uid(2)


def test_the_entity_of_a_refresh_is_exported_as_the_stored_snapshot(make_harness):
    """R4-F12 (fix round 2, 2026-10-11; D-51): a REFRESH record (equal `effective_at`, equal
    state) does not move current state, but its Entity is the latest one the sink received and
    its source is not stale: export accepts it and sends the stored current snapshot, with the
    stored record's times and provenance (record 1). The Entity of a LATE record and of a
    CONFLICT record (equal time, different state) are still SOURCE_STALE, with zero sends."""
    h = ready(make_harness)
    conflicting = report(4)
    conflicting["position"]["lat_deg"] = 48.5
    for body in (report(2), report(3, at_ms=-500), conflicting):
        h.publish(body)
    h.run()
    assert [h.sink.events[f"{uid(n)}:0"][2] for n in (2, 3, 4)] == [
        ("REFRESH",), ("LATE",), ("CONFLICT",)]
    stored, stored_track = objects(h, 1)
    refresh, refresh_track = objects(h, 2)
    assert refresh != stored                    # its own provenance: another record
    for n in (3, 4):
        entity, track = objects(h, n)
        result = h.bridge.export(entity, track, peer_id="peer-1")
        assert (result["state"], result["reason"]) == ("DENIED", "SOURCE_STALE")
    assert h.provider.sent() == []
    result = h.bridge.export(refresh, refresh_track, peer_id="peer-1", request_id=uid(511))
    assert (result["state"], result["reason"]) == ("SENT", None)
    emitted = json.loads(h.provider.sent()[0]["encoded"])
    assert (emitted["effective_at"], emitted["position"]["observed_at"]) == (
        "2026-10-04T12:00:00.000Z", "2026-10-04T12:00:00.000Z")
    assert emitted["position"]["lat_deg"] == 48.15
    assert emitted["extensions"]["sc-link16-export/1"]["provenance"]["source_record_id"] == uid(1)
    job = h.rows(SQL_JOB_GET, (uid(511),))[0]
    assert bytes(job[14]) == jsonstrict.canonical(stored.model_dump(mode="json"))
    assert bytes(job[15]) == jsonstrict.canonical(stored_track.model_dump(mode="json"))
    assert [r[0] for r in h.rows("SELECT code FROM audit WHERE kind = 'export_denied'")] == \
        ["SOURCE_STALE"] * 2


def test_the_cdm_object_digest_and_transformations_are_audited(make_harness):
    """REQ093: the originating objects' digest and the transformation record."""
    h = ready(make_harness)
    entity, track = objects(h)
    h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(503))
    digest = jsonstrict.sha256_hex(jsonstrict.canonical([entity.model_dump(mode="json"),
                                                         track.model_dump(mode="json")]))
    row = h.rows("SELECT transformations, detail FROM audit WHERE kind = 'export_queued'")[0]
    assert json.loads(row[0]) == ["identity: UUID5 over scoped track instance"]
    assert row[1] == "cdm_sha256=" + digest
    assert h.rows(SQL_JOB_GET, (uid(503),))[0][13] == digest


def test_timeout_after_possible_send_is_unknown_and_reconciled_without_resend(make_harness):
    """E05: the gateway sends, then withholds its answer past the client's deadline."""
    h = ready(make_harness, provider_kwargs={"hold_response_seconds": 3.0}, deadline=0.3)
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(504))
    h.provider.release_hold.set()
    assert (result["state"], result["reason"]) == ("UNKNOWN", "SEND_OUTCOME_UNKNOWN")
    assert h.counters()["unknown_send_outcome"] == 1
    assert h.rows("SELECT code FROM audit WHERE kind = 'transmission'") == [
        ("SEND_OUTCOME_UNKNOWN",)]
    assert len(h.provider.sent()) == 1
    assert h.bridge.reconcile() == [(uid(504), "SENT")]
    assert len(h.provider.sent()) == 1
    assert h.rows(SQL_JOB_GET, (uid(504),))[0][7] == "SENT"


def test_unknown_request_stays_unknown_until_resolved(make_harness):
    h = ready(make_harness)
    entity, track = objects(h)

    def lost(_body):
        raise SendOutcomeUnknown("the answer did not arrive")

    h.bridge.client.transmit = lost
    assert h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(505))["state"] == \
        "UNKNOWN"
    assert h.bridge.reconcile() == []
    assert h.rows(SQL_JOB_GET, (uid(505),))[0][7] == "UNKNOWN"
    assert h.bridge.resolve_send(uid(505), "abandon", "gateway never received it") == "FAILED"
    assert h.rows(SQL_JOB_GET, (uid(505),))[0][7:9] == ("FAILED", "ABANDONED_BY_OPERATOR")
    assert h.provider.sent() == []


def test_a_409_is_rejected_and_never_sent_again(make_harness):
    h = ready(make_harness)
    entity, track = objects(h)
    other = jsonstrict.canonical({"request_id": uid(506), "peer_id": "peer-1",
                                  "expires_at": "2026-10-04T12:00:10.000Z",
                                  "policy_revision": "x", "report": report(9)})
    h.client().transmit(other)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(506))
    assert (result["state"], result["reason"]) == ("REJECTED", "REQUEST_ID_CONFLICT")
    assert h.bridge.egress.send(uid(506))["state"] == "REJECTED"
    assert len(h.provider.sent()) == 1
    again = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(506))
    assert again["state"] == "REJECTED" and len(h.provider.sent()) == 1


def test_capacity_at_the_gateway_keeps_the_job_pending_for_the_same_request(make_harness):
    h = ready(make_harness, provider_kwargs={"capacity_full": True})
    entity, track = objects(h)
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(507))
    assert (result["state"], result["reason"]) == ("PENDING", "CAPACITY")
    h.provider.capacity_full = False
    assert h.bridge.egress.send(uid(507))["state"] == "SENT"
    assert [s["request_id"] for s in h.provider.sent()] == [uid(507)]


def test_queued_exports_stop_at_the_cap(make_harness):
    h = ready(make_harness, provider_kwargs={"capacity_full": True},
              config={"limits": {"max_queued_exports": 1}})
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["state"] == "PENDING"
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "CAPACITY_EXPORTS"


def test_delivery_confirmed_is_never_invented(make_harness):
    h = ready(make_harness)
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["state"] == "SENT"
    assert h.bridge.reconcile() == []


def test_a_channel_that_is_not_normal_denies_exports(make_harness):
    h = ready(make_harness)
    from helpers import notice
    h.publish_notice(notice(2, "GAP", track_number=None, incarnation=None))
    h.run()
    entity, track = objects(h)
    assert h.bridge.export(entity, track, peer_id="peer-1")["reason"] == "CHANNEL_INCOMPLETE"


@pytest.mark.parametrize("dest, message", [
    (dict(DEST_TUPLE, realm="other"), "the destination tuple's realm is the allocation's realm"),
    ({"tenant": "demo"}, "the destination tuple holds exactly the six identity keys"),
    (dict(DEST_TUPLE, incarnation="01"), "decimal uint64"),
])
def test_an_allocation_is_validated(make_harness, dest, message):
    from synapse_link16_bridge.bridge import OperatorRefusal
    h = ready(make_harness)
    with pytest.raises(OperatorRefusal) as caught:
        h.bridge.allocate("peer-1", "dest-realm", KEY, dest, "evidence")
    assert message in str(caught.value)


def test_each_outbound_report_has_its_own_session_sequence(make_harness):
    """R4-F7 (fix round 1, 2026-10-11): two exports queued while the gateway answers 429 carry
    sequences 0 and 1 of one session; a retried job keeps its body; a new instance opens a new
    outbound session at sequence 0."""
    h = ready(make_harness, provider_kwargs={"capacity_full": True})
    entity, track = objects(h)

    def envelope(request_id, bridge=None):
        body = json.loads(bytes(h.rows(SQL_JOB_GET, (request_id,), bridge)[0][1]))
        return body["report"]["session_id"], body["report"]["sequence"]

    for n in (700, 701):
        assert h.bridge.export(entity, track, peer_id="peer-1",
                               request_id=uid(n))["state"] == "PENDING"
    first, second = envelope(uid(700)), envelope(uid(701))
    assert first[0] == second[0] and (first[1], second[1]) == ("0", "1")
    h.provider.capacity_full = False
    assert h.bridge.egress.send(uid(700))["state"] == "SENT"
    assert envelope(uid(700)) == first
    h.bridge.close()
    h.clock.advance(1)
    other = h.new_bridge(holder="holder-b")
    assert other.export(entity, track, peer_id="peer-1", request_id=uid(702))["state"] == "SENT"
    third = envelope(uid(702), other)
    assert third[0] != first[0] and third[1] == "0"
    assert [json.loads(s["encoded"])["sequence"] for s in h.provider.sent()] == ["0", "0"]


@pytest.mark.parametrize("base, expected", [
    ("air_sensor.json", ("DENIED", "PROFILE_NOT_READY")),
    ("subsurface_unknown_method.json", ("DENIED", "PROFILE_NOT_READY")),
    ("air_hae_metres_friendly.json", ("SENT", None))])
def test_an_entity_whose_position_the_compatibility_projection_left_out_is_not_exported(
        make_harness, base, expected):
    """RUNTIME-2 (A2F, 2026-10-11; D-52): under the 3.0.0 compatibility projection a SENSOR or
    UNKNOWN position is left out of the Entity, which carries the `POSITION_NOT_PROJECTED_CDM3`
    marker. Exporting it would send `position: null` for a source that reported a position, with
    no loss record, so it is denied `PROFILE_NOT_READY`, audited with the marker among the
    transformations, and nothing is sent. A GNSS source under the same projection is exported."""
    from synapse_cdm.adapters.link16_gateway import T_COMPAT
    h = ready(make_harness, report_changes={"base": base})
    assert h.bridge.projection.value == "COMPAT_3_0"
    entity, track = objects(h)
    assert (T_COMPAT in entity.source.transformations) is (expected[0] == "DENIED")
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(700))
    assert (result["state"], result["reason"]) == expected
    if expected[0] == "SENT":
        assert [s["request_id"] for s in h.provider.sent()] == [uid(700)]
        return
    assert h.provider.sent() == [] and h.counters()["export_denied"] == 1
    audit = h.rows("SELECT kind, subject_id, code, policy_result, transformations FROM audit "
                   "WHERE kind = 'export_denied'")
    assert [a[:4] for a in audit] == [("export_denied", uid(700), "PROFILE_NOT_READY", "DENIED")]
    assert T_COMPAT in json.loads(audit[0][4])
    assert h.rows("SELECT state, reason FROM export_job WHERE request_id = ?", (uid(700),)) == [
        ("DENIED", "PROFILE_NOT_READY")]


def test_a_stored_snapshot_carrying_the_marker_is_not_exported(make_harness, monkeypatch):
    """RUNTIME-2 (A2F, 2026-10-11): the second half of the check reads the stored current
    snapshot, which is what an export translates; a snapshot carrying the marker is denied
    `PROFILE_NOT_READY` whatever object the caller presented."""
    from synapse_cdm.adapters.link16_gateway import T_COMPAT
    h = ready(make_harness)
    entity, track = objects(h)
    marked = entity.model_copy(update={"source": entity.source.model_copy(update={
        "transformations": [*entity.source.transformations, T_COMPAT]})})
    egress = h.bridge.egress
    real = egress._current_snapshot
    monkeypatch.setattr(egress, "_current_snapshot",
                        lambda *args: (marked, real(*args)[1]))
    result = h.bridge.export(entity, track, peer_id="peer-1", request_id=uid(701))
    assert (result["state"], result["reason"]) == ("DENIED", "PROFILE_NOT_READY")
    assert h.provider.sent() == []
