"""The AIXM temporality resolver (`synapse_cdm.aixm_resolve`) — adapter expansion phase 5
(2026-09-21).

What is proved here, over the `fixtures/aixm511/dnotam/` documents: the effective windows per
scenario (a runway closure, an airspace activation with and without a schedule, a navaid and
its equipment) at instants on both sides of each boundary under the begin-included /
end-excluded convention; corrections received out of order resolve to the highest correction
whatever the document or arrival order; a cancellation keeps the record, leaves the baseline in
force and never turns an unknown baseline into an asserted availability; missing baseline state
is UNRESOLVED and an unknown feature a typed failure; overlapping temporary changes to one
property are AMBIGUOUS (TS_011) and to different properties are not; the schema layer and the
rule layer are separate from the resolver; the resolver is a pure function (same input, same
output, under different hash seeds and orders; no file, socket or clock); and the three
targeted negatives — a dropped effective end and a correction applied out of sequence here,
the wrong scenario-code mapping in `test_cdm_aixm511_dnotam.py`.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import pathlib
import subprocess
import sys

import pytest

import synapse_cdm
from synapse_cdm import aixm_resolve as resolver
from synapse_cdm.adapters.aixm511 import Aixm511Adapter, AsOf
from synapse_cdm.models import Entity

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
DNOTAM = PKG / "fixtures" / "aixm511" / "dnotam"
RWY_CLS = DNOTAM / "rwy_cls_baseline_and_closure.xml"
ATSA = DNOTAM / "atsa_act_baseline_and_activation.xml"
SAA = DNOTAM / "saa_act_activation_with_schedule.xml"
NAV_UNS = DNOTAM / "nav_uns_baseline_and_outage.xml"
FUTURE = DNOTAM / "future_effective_change.xml"
OVERLAP = DNOTAM / "overlapping_tempdeltas.xml"
NILS = DNOTAM / "explicit_nil_values.xml"
UNRESOLVED = DNOTAM / "unresolved_references.xml"
OUT_OF_ORDER = DNOTAM / "corrections_out_of_order.xml"
EXPIRY = DNOTAM / "expiry.xml"
CANCELLATION = DNOTAM / "cases" / "cancellation.xml"
RWY_DIR = "a1a40000-00d0-4000-8000-000000000002"
TMA = "a1a40000-00d0-4000-8000-000000000003"
TSA = "a1a40000-00d0-4000-8000-000000000004"
NAVAID = "a1a40000-00d0-4000-8000-000000000005"
VOR = "a1a40000-00d0-4000-8000-000000000006"
EVENT_1 = "a1a40000-00e0-4000-8000-000000000001"
AS_OF = AsOf("2026-03-25T12:00:00Z", "the synthetic issue instant of the cancellation, stated by the fixture's author")


def _objects(path: pathlib.Path, **kwargs) -> list[Entity]:
    return [o for o in Aixm511Adapter(**kwargs).to_cdm(path.read_bytes()) if isinstance(o, Entity)]


def _twin(path: pathlib.Path) -> dict:
    return json.loads((path.parent / (path.stem + ".parsed.json")).read_text())


def _view(objects, feature, instant):
    r = resolver.resolve(objects, feature, instant)
    return r.outcome, r.source_of_status, r.status_state, r.asserted_status


def _dispositions(r: resolver.Resolution) -> list[tuple[str, int | None, str]]:
    return [(h.interpretation, h.sequence_number, h.disposition) for h in r.history]


# ------------------------------------------------------------ effective windows per scenario

def test_a_runway_closure_applies_from_its_begin_included_to_its_end_excluded():
    objects = _objects(RWY_CLS)
    assert _view(objects, RWY_DIR, "2026-03-10T05:59:59Z") == ("resolved", "BASELINE", "asserted", "NORMAL")
    assert _view(objects, RWY_DIR, "2026-03-10T06:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    assert _view(objects, RWY_DIR, "2026-03-10T09:59:59Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    assert _view(objects, RWY_DIR, "2026-03-10T10:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL")
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T08:00:00Z")
    assert r.feature_element == "aixm:RunwayDirection" and r.status_property == "aixm:ManoeuvringAreaAvailability.operationalStatus"
    assert [s.code for s in r.statuses] == ["NORMAL", "CLOSED"] and [s.code for s in r.operative] == ["CLOSED"]
    assert r.baseline.identity == f"{RWY_DIR}/BASELINE/1/0" and [a.identity for a in r.applied] == [
        f"{RWY_DIR}/BASELINE/1/0", f"{RWY_DIR}/TEMPDELTA/1/0"]
    assert r.applied[1].event == EVENT_1 and r.applied[1].scenario == "RWY.CLS" and r.applied[1].assertion_kind == "initial"
    assert _dispositions(r) == [("BASELINE", 1, "applied"), ("TEMPDELTA", 1, "applied")]
    assert any("CLOSED branch is operative" in reason for reason in r.reasons)
    assert any("Usage limitation and closure scenarios" in rule for rule in r.rules_applied)
    assert any("§4.4.6.3" in rule for rule in r.rules_applied) and r.findings == []
    before = resolver.resolve(objects, RWY_DIR, "2026-03-10T05:00:00Z")
    assert _dispositions(before) == [("BASELINE", 1, "applied"), ("TEMPDELTA", 1, "future")]
    after = resolver.resolve(objects, RWY_DIR, "2026-03-11T00:00:00Z")
    assert _dispositions(after) == [("BASELINE", 1, "applied"), ("TEMPDELTA", 1, "expired")]
    assert "end excluded" in after.history[1].reason


def test_an_airspace_activation_replaces_the_scheduled_baseline_and_a_scheduled_change_stays_scheduled():
    tma = _objects(ATSA)
    baseline = resolver.resolve(tma, TMA, "2026-03-12T04:00:00Z")
    assert (baseline.outcome, baseline.source_of_status, baseline.status_state, baseline.asserted_status) == (
        "resolved", "BASELINE", "scheduled", None)
    assert [(s.code, s.scheduled, s.timesheets) for s in baseline.statuses] == [("ACTIVE", True, 1), ("INACTIVE", True, 1)]
    active = resolver.resolve(tma, TMA, "2026-03-12T06:00:00Z")
    assert (active.source_of_status, active.status_state, active.asserted_status) == ("TEMPDELTA", "asserted", "ACTIVE")
    assert len(active.statuses) == 1, "the TEMPDELTA's one structure replaces the baseline's two (ER-04)"
    assert _view(tma, TMA, "2026-03-12T09:00:00Z") == ("resolved", "BASELINE", "scheduled", None)
    tsa = _objects(SAA)
    assert _view(tsa, TSA, "2026-03-15T00:00:00Z") == ("resolved", "BASELINE", "asserted", "INACTIVE")
    scheduled = resolver.resolve(tsa, TSA, "2026-03-17T10:00:00Z")
    assert (scheduled.source_of_status, scheduled.status_state, scheduled.asserted_status) == ("TEMPDELTA", "scheduled", None)
    assert [(s.code, s.scheduled) for s in scheduled.statuses] == [("ACTIVE", True), ("INACTIVE", True)]
    assert scheduled.applied[1].scenario == "SAA.ACT"
    assert _view(tsa, TSA, "2026-03-20T00:00:00Z") == ("resolved", "BASELINE", "asserted", "INACTIVE")


def test_a_navaid_outage_resolves_on_the_navaid_and_on_its_equipment():
    objects = _objects(NAV_UNS)
    assert _view(objects, NAVAID, "2026-03-14T07:59:59Z") == ("resolved", "BASELINE", "asserted", "OPERATIONAL")
    assert _view(objects, NAVAID, "2026-03-14T08:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "PARTIAL")
    assert _view(objects, VOR, "2026-03-14T07:59:59Z") == ("resolved", "BASELINE", "asserted", "OPERATIONAL")
    assert _view(objects, VOR, "2026-03-14T08:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "UNSERVICEABLE")
    assert _view(objects, VOR, "2026-03-14T12:00:00Z") == ("resolved", "BASELINE", "asserted", "OPERATIONAL")
    r = resolver.resolve(objects, VOR, "2026-03-14T09:00:00Z")
    assert r.feature_element == "aixm:VOR" and r.status_property == "aixm:NavaidOperationalStatus.operationalStatus"
    assert r.applied[1].scenario == "NAV.UNS" and r.statuses[0].element == "aixm:NavaidOperationalStatus"


def test_a_tacan_states_one_status_per_signal_and_neither_is_a_conflict():
    twin = copy.deepcopy(_twin(NAV_UNS))
    slice_ = twin["message:hasMember"][4]["aixm:timeSlice"][1]
    slice_["aixm:availability"] = [
        {"$": "aixm:NavaidOperationalStatus", "@gml:id": "S1", "aixm:operationalStatus": "UNSERVICEABLE", "aixm:signalType": "DISTANCE"},
        {"$": "aixm:NavaidOperationalStatus", "@gml:id": "S2", "aixm:operationalStatus": "OPERATIONAL", "aixm:signalType": "AZIMUTH"}]
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, VOR, "2026-03-14T09:00:00Z")
    assert r.status_state == "asserted-per-signal" and r.asserted_status is None
    assert r.asserted_by_signal == {"DISTANCE": "UNSERVICEABLE", "AZIMUTH": "OPERATIONAL"}
    assert any("NAV.UNS.02" in rule for rule in r.rules_applied)


def test_a_future_change_is_recorded_and_not_applied_until_its_begin():
    objects = _objects(FUTURE)
    r = resolver.resolve(objects, RWY_DIR, "2026-05-01T00:00:00Z")
    assert (r.outcome, r.asserted_status) == ("resolved", "NORMAL") and _dispositions(r)[1] == ("TEMPDELTA", 1, "future")
    assert "begins at 2026-06-01T06:00:00.000Z" in r.history[1].reason
    assert _view(objects, RWY_DIR, "2026-06-01T06:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")


def test_expiry_is_the_stated_end_and_the_estimate_is_carried_on_the_slice():
    objects = _objects(EXPIRY)
    assert _view(objects, RWY_DIR, "2026-03-10T09:59:59Z")[3] == "CLOSED"
    expired = resolver.resolve(objects, RWY_DIR, "2026-03-10T10:00:00Z")
    assert expired.asserted_status == "NORMAL" and _dispositions(expired)[1] == ("TEMPDELTA", 1, "expired")
    event = resolver.event_state(objects, EVENT_1, "2026-03-10T10:00:00Z")
    assert event.state == "ended" and event.scenario == "RWY.CLS" and event.scenario_version == "2.0"
    assert event.history[0].disposition == "expired"
    active = resolver.event_state(objects, EVENT_1, "2026-03-10T07:00:00Z")
    assert active.state == "active" and active.in_force.identity == f"{EVENT_1}/BASELINE/1/0"
    assert [o for o in objects if "dnotam" in o.attributes and o.attributes["dnotam"]["role"] == "event"][0] \
        .attributes["dnotam"]["assertion"]["estimated_end"] is True


# -------------------------------------------------------------- corrections, out of order

def test_corrections_received_out_of_order_resolve_to_the_highest_correction():
    objects = _objects(OUT_OF_ORDER)
    identities = [o.source_ids[1].external_id for o in objects if o.source_ids[0].external_id == RWY_DIR]
    assert identities == [f"{RWY_DIR}/BASELINE/1/0", f"{RWY_DIR}/TEMPDELTA/1/1", f"{RWY_DIR}/TEMPDELTA/1/0"], "document order kept"
    assert _view(objects, RWY_DIR, "2026-03-10T07:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    assert _view(objects, RWY_DIR, "2026-03-10T08:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL"), \
        "the correction ended the closure at 08:00; the 1.0 end of 10:00 is superseded"
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T09:00:00Z")
    history = [h for h in r.history if h.interpretation == "TEMPDELTA"][0]
    assert history.valid.identity == f"{RWY_DIR}/TEMPDELTA/1/1" and [s.identity for s in history.superseded] == [f"{RWY_DIR}/TEMPDELTA/1/0"]
    assert history.disposition == "expired" and r.findings == []
    for order in (list(reversed(objects)), sorted(objects, key=lambda o: o.source_ids[1].external_id)):
        assert _view(order, RWY_DIR, "2026-03-10T09:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL")
    without_original = [o for o in objects if o.source_ids[1].external_id != f"{RWY_DIR}/TEMPDELTA/1/0"]
    assert _view(without_original, RWY_DIR, "2026-03-10T09:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL"), \
        "a correction is a complete slice: it resolves without the slice it corrects"
    event = resolver.event_state(objects, EVENT_1, "2026-03-10T09:00:00Z")
    assert event.state == "ended" and event.history[0].valid.assertion_kind == "termination"
    assert resolver.event_state(objects, EVENT_1, "2026-03-10T07:00:00Z").in_force.identity == f"{EVENT_1}/BASELINE/1/1"


def test_a_correction_applied_out_of_sequence_is_caught():
    """Targeted negative: swap the correction numbers so the end-08:00 slice is 1.0 and the
    end-10:00 slice is 1.1 — the document order is unchanged, and a resolver that read order
    instead of correction numbers would give the same answer as before. It does not."""
    twin = copy.deepcopy(_twin(OUT_OF_ORDER))
    slices = twin["message:hasMember"][1]["aixm:timeSlice"]
    slices[1]["aixm:correctionNumber"], slices[2]["aixm:correctionNumber"] = "0", "1"
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    assert _view(objects, RWY_DIR, "2026-03-10T09:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED"), \
        "now the 10:00 slice is the higher correction, and the closure is in force at 09:00"
    assert _view(_objects(OUT_OF_ORDER), RWY_DIR, "2026-03-10T09:00:00Z")[3] == "NORMAL"
    # A correction that moves the BEGIN of an active slice is reported (TS_017) and still wins (§3.6).
    twin = copy.deepcopy(_twin(OUT_OF_ORDER))
    twin["message:hasMember"][1]["aixm:timeSlice"][1]["gml:validTime"]["gml:beginPosition"] = "2026-03-10T05:00:00Z"
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T05:30:00Z")
    assert r.asserted_status == "CLOSED" and any("TS_017" in f for f in r.findings)
    # Two slices claiming the same correction (TS_005): the sequence is a conflict and nothing of it applies.
    twin = copy.deepcopy(_twin(OUT_OF_ORDER))
    twin["message:hasMember"][1]["aixm:timeSlice"][2]["aixm:correctionNumber"] = "1"
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T07:00:00Z")
    assert r.asserted_status == "NORMAL" and any("TS_005" in f for f in r.findings)
    assert [h.disposition for h in r.history if h.interpretation == "TEMPDELTA"] == ["conflict"]


def test_a_dropped_effective_end_is_caught():
    """Targeted negative: a reading that lost the TEMPDELTA's end (an open period) would keep
    the closure in force for ever; the resolver reads the end the slice states."""
    twin = copy.deepcopy(_twin(RWY_CLS))
    twin["message:hasMember"][3]["aixm:timeSlice"][1]["gml:validTime"]["gml:endPosition"] = {"@indeterminatePosition": "unknown"}
    dropped = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    assert _view(dropped, RWY_DIR, "2026-03-11T00:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    assert _view(_objects(RWY_CLS), RWY_DIR, "2026-03-11T00:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL")
    r = resolver.resolve(dropped, RWY_DIR, "2026-03-11T00:00:00Z")
    assert r.applied[1].end_open is True and r.applied[1].effective_to is None
    # And a mutated OBJECT (the adapter's output edited behind its back) is read as edited, not repaired.
    edited = [copy.deepcopy(o) for o in _objects(RWY_CLS)]
    td = [o for o in edited if o.source_ids[1].external_id == f"{RWY_DIR}/TEMPDELTA/1/0"][0]
    td.attributes["aixm"]["time_slice"]["valid_time"]["end"]["instant"] = "2026-03-10T08:00:00.000Z"
    assert _view(edited, RWY_DIR, "2026-03-10T09:00:00Z")[3] == "NORMAL" and _view(_objects(RWY_CLS), RWY_DIR, "2026-03-10T09:00:00Z")[3] == "CLOSED"


# ----------------------------------------------------------------- cancellation semantics

def test_a_cancellation_keeps_the_record_and_leaves_the_baseline_in_force():
    objects = _objects(CANCELLATION, as_of=AS_OF)
    identities = sorted(o.source_ids[1].external_id for o in objects)
    assert f"{RWY_DIR}/TEMPDELTA/1/0" in identities and f"{RWY_DIR}/TEMPDELTA/1/1" in identities, "both slices are translated"
    r = resolver.resolve(objects, RWY_DIR, "2026-06-01T07:00:00Z")
    assert (r.outcome, r.source_of_status, r.status_state, r.asserted_status) == ("resolved", "BASELINE", "asserted", "NORMAL")
    history = [h for h in r.history if h.interpretation == "TEMPDELTA"][0]
    assert history.disposition == "cancelled" and history.valid.identity == f"{RWY_DIR}/TEMPDELTA/1/1"
    assert [s.identity for s in history.superseded] == [f"{RWY_DIR}/TEMPDELTA/1/0"] and "§4.4.8" in history.reason
    assert history.valid.assertion_kind == "cancellation" and history.valid.valid_time_form == "nil"
    assert any("§4.4.8" in rule for rule in r.rules_applied)
    event = resolver.event_state(objects, EVENT_1, "2026-06-01T07:00:00Z")
    assert event.state == "cancelled" and event.in_force is None and event.history[0].disposition == "cancelled"
    assert event.history[0].valid.assertion_kind == "cancellation"


def test_a_cancellation_never_turns_an_unknown_baseline_into_an_asserted_availability():
    objects = [o for o in _objects(CANCELLATION, as_of=AS_OF) if o.attributes["aixm"]["time_slice"]["interpretation"] != "BASELINE"
               or o.attributes["aixm"]["feature"]["element"] == "event:Event"]
    r = resolver.resolve(objects, RWY_DIR, "2026-06-01T07:00:00Z")
    assert r.outcome == "unresolved" and r.asserted_status is None and r.statuses == [] and r.status_state == "not stated"
    assert r.baseline is None and any("nothing is invented" in reason for reason in r.reasons)
    assert [h.disposition for h in r.history] == ["cancelled"], "the cancelled sequence is still the record"
    # Reinstating an abandoned sequence with a higher correction is TS_019's forbidden case: reported.
    twin = copy.deepcopy(_twin(RWY_CLS))
    slices = twin["message:hasMember"][3]["aixm:timeSlice"]
    cancelled = copy.deepcopy(slices[1])
    cancelled.update({"@gml:id": "TD_1_1", "aixm:correctionNumber": "1", "gml:validTime": {"@nilReason": "inapplicable"}})
    del cancelled["aixm:availability"]
    reinstated = copy.deepcopy(slices[1])
    reinstated.update({"@gml:id": "TD_1_2", "aixm:correctionNumber": "2"})
    slices.extend([cancelled, reinstated])
    objects = [o for o in Aixm511Adapter(as_of=AS_OF).to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T07:00:00Z")
    assert any("TS_019" in f for f in r.findings) and r.asserted_status == "CLOSED", "§3.6 still names the valid slice; TS_019 is reported"


def test_a_withdrawn_availability_is_withdrawn_and_nothing_is_asserted():
    objects = _objects(NILS)
    assert _view(objects, NAVAID, "2026-03-14T07:00:00Z") == ("resolved", "BASELINE", "asserted", "OPERATIONAL")
    r = resolver.resolve(objects, NAVAID, "2026-03-14T09:00:00Z")
    assert (r.outcome, r.source_of_status, r.status_state, r.asserted_status) == ("resolved", "TEMPDELTA", "withdrawn", None)
    assert [s.nil for s in r.statuses] == [True] and r.operative == []
    assert any("§4.4.6.3" in rule for rule in r.rules_applied)


# ------------------------------------------------------------- unresolved state reporting

def test_missing_baseline_state_is_unresolved_and_an_unknown_feature_a_typed_failure():
    objects = _objects(UNRESOLVED)
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T07:00:00Z")
    assert r.outcome == "unresolved" and r.baseline is None
    assert (r.source_of_status, r.status_state, r.asserted_status) == ("TEMPDELTA", "asserted", "CLOSED"), \
        "what the TEMPDELTA states is known; the feature is still unresolved"
    assert any("passed 0 BASELINE sequence(s)" in reason for reason in r.reasons)
    assert any("UNRESOLVED baseline" in reason for reason in r.reasons)
    assert r.applied[0].event == "a1a40000-00e0-4000-8000-000000000099" and r.applied[0].scenario is None
    outside = resolver.resolve(objects, RWY_DIR, "2026-03-11T00:00:00Z")
    assert outside.outcome == "unresolved" and outside.status_state == "not stated" and outside.asserted_status is None
    with pytest.raises(resolver.ResolverError, match="nothing is invented"):
        resolver.resolve(objects, "a1a40000-00d0-4000-8000-0000000000ff", "2026-03-10T07:00:00Z")
    with pytest.raises(resolver.ResolverError, match="event_state"):
        resolver.resolve(objects, EVENT_1, "2026-03-10T07:00:00Z")
    with pytest.raises(resolver.ResolverError, match="not an event:Event"):
        resolver.event_state(objects, RWY_DIR, "2026-03-10T07:00:00Z")
    with pytest.raises(resolver.ResolverError, match="as_of"):
        resolver.resolve(objects, RWY_DIR, "not an instant")
    import datetime as _dt
    with pytest.raises(resolver.ResolverError, match="aware"):
        resolver.resolve(objects, RWY_DIR, _dt.datetime(2026, 3, 10, 7))
    with pytest.raises(resolver.ResolverError, match="attributes"):
        resolver.resolve([{"attributes": {}}], RWY_DIR, "2026-03-10T07:00:00Z")
    assert resolver.features_of(objects) == {EVENT_1: "event:Event", RWY_DIR: "aixm:RunwayDirection"}


def test_two_valid_baselines_at_one_instant_are_ambiguous_not_chosen():
    twin = copy.deepcopy(_twin(RWY_CLS))
    slices = twin["message:hasMember"][3]["aixm:timeSlice"]
    second = copy.deepcopy(slices[0])
    second.update({"@gml:id": "BL_2_0", "aixm:sequenceNumber": "2"})
    second["gml:validTime"]["gml:beginPosition"] = "2026-02-01T00:00:00Z"
    slices.insert(1, second)
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-01T00:00:00Z")
    assert r.outcome == "ambiguous" and r.status_state == "ambiguous" and r.asserted_status is None and r.applied == []
    assert any("TS_009" in f for f in r.findings)


# ------------------------------------------------------------- overlapping temporary changes

def test_overlapping_changes_to_one_property_are_ambiguous_and_neither_is_applied():
    objects = _objects(OVERLAP)
    assert _view(objects, RWY_DIR, "2026-03-10T07:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T09:00:00Z")
    assert (r.outcome, r.source_of_status, r.status_state, r.asserted_status) == ("ambiguous", "none", "ambiguous", None)
    assert r.statuses == [] and [a.identity for a in r.applied] == [f"{RWY_DIR}/BASELINE/1/0"]
    assert len(r.findings) == 1 and "TS_011" in r.findings[0] and "neither is applied" in r.findings[0]
    assert f"{RWY_DIR}/TEMPDELTA/1/0" in r.findings[0] and f"{RWY_DIR}/TEMPDELTA/2/0" in r.findings[0]
    assert any("forbids them and gives no precedence" in reason for reason in r.reasons)
    assert _dispositions(r) == [("BASELINE", 1, "applied"), ("TEMPDELTA", 1, "in force"), ("TEMPDELTA", 2, "in force")]
    assert _view(objects, RWY_DIR, "2026-03-10T10:00:00Z") == ("resolved", "TEMPDELTA", "asserted", "CLOSED")
    assert resolver.resolve(objects, RWY_DIR, "2026-03-10T11:00:00Z").applied[1].identity == f"{RWY_DIR}/TEMPDELTA/2/0"
    assert _view(objects, RWY_DIR, "2026-03-10T12:00:00Z") == ("resolved", "BASELINE", "asserted", "NORMAL")


def test_overlapping_changes_to_different_properties_are_not_a_conflict():
    twin = copy.deepcopy(_twin(OVERLAP))
    second = twin["message:hasMember"][2]["aixm:timeSlice"][2]
    del second["aixm:availability"]
    second["aixm:designator"] = "09L"
    objects = [o for o in Aixm511Adapter().to_cdm(twin) if isinstance(o, Entity)]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T09:00:00Z")
    assert (r.outcome, r.asserted_status) == ("resolved", "CLOSED") and r.findings == []
    assert any("none states availability" not in reason and "changes nothing the resolver reads" in reason for reason in r.reasons)
    assert _dispositions(r) == [("BASELINE", 1, "applied"), ("TEMPDELTA", 1, "applied"), ("TEMPDELTA", 2, "in force")]


# ------------------------------------------------------------ the layers, kept separate

def test_the_resolver_applies_temporality_rules_and_neither_schema_nor_scenario_rules():
    """A schema-valid, rule-invalid document (RWY.CLS without a CLOSED branch) still RESOLVES:
    the rule finding sits on the adapter's block, the schema verdict in normative_validation,
    and the resolver reads what the slices state."""
    counter = DNOTAM / "counterexamples" / "rule_invalid_rwy_cls_without_closed_status.xml"
    objects = [o for o in Aixm511Adapter().to_cdm(counter.read_bytes()) if isinstance(o, Entity)]
    bound = [o for o in objects if o.attributes.get("dnotam", {}).get("role") == "affected-feature"][0]
    assert bound.attributes["dnotam"]["rule_findings"] and "RWY.CLS.03" in bound.attributes["dnotam"]["rule_findings"][0]
    r = resolver.resolve(objects, RWY_DIR, "2026-03-10T07:00:00Z")
    assert (r.outcome, r.source_of_status, r.status_state, r.asserted_status) == ("resolved", "TEMPDELTA", "ambiguous", None)
    assert [s.code for s in r.statuses] == ["NORMAL", "LIMITED"], "no CLOSED branch to rank; two unscheduled codes and no rule"
    assert not any("RWY.CLS.03" in f for f in r.findings), "the scenario rule layer is the adapter's, not the resolver's"
    source = pathlib.Path(resolver.__file__).read_text()
    assert "normative_validation" not in source and "SCENARIO_PROFILES" not in source


def test_the_resolver_holds_no_state_reads_nothing_and_is_deterministic():
    tree = ast.parse(pathlib.Path(resolver.__file__).read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | {
        (n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported <= {"datetime", "typing", "synapse_cdm", "__future__"}, imported
    calls = {getattr(n.func, "attr", getattr(n.func, "id", None)) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not calls & {"open", "now", "utcnow", "today", "socket", "urlopen", "environ", "getenv", "cache", "lru_cache"}, calls
    assert not any(isinstance(n, (ast.Global, ast.Nonlocal)) for n in ast.walk(tree))
    module_level = [n for n in tree.body if isinstance(n, (ast.Assign, ast.AnnAssign))]
    for node in module_level:
        value = node.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        assert not isinstance(value, (ast.Dict, ast.List, ast.Set)) or all(
            isinstance(t, ast.Name) and (t.id.isupper() or t.id == "__all__") for t in targets), \
            "a module-level container is a constant table, never a store"
    objects = _objects(OUT_OF_ORDER) + _objects(OVERLAP)
    first = resolver.resolve(objects, RWY_DIR, "2026-03-10T09:00:00Z").model_dump(mode="json")
    for _ in range(3):
        assert resolver.resolve(objects, RWY_DIR, "2026-03-10T09:00:00Z").model_dump(mode="json") == first
    script = (f"import json, sys; sys.path.insert(0, {json.dumps(str(pathlib.Path(__file__).resolve().parent.parent))}); "
              "from tests.test_cdm_aixm_resolve import _objects, OUT_OF_ORDER, OVERLAP, RWY_DIR, resolver; "
              "objects = _objects(OUT_OF_ORDER) + _objects(OVERLAP); "
              "print(json.dumps(resolver.resolve(objects, RWY_DIR, '2026-03-10T09:00:00Z').model_dump(mode='json'), sort_keys=True))")
    outputs = set()
    for seed in ("0", "1", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, env=env, timeout=120)
        assert run.returncode == 0, run.stderr[-800:]
        outputs.add(run.stdout.strip())
    assert len(outputs) == 1
    assert json.loads(outputs.pop()) == json.loads(json.dumps(first))


def test_every_resolution_validates_against_its_contract_and_names_its_rules():
    for path in sorted(DNOTAM.glob("*.xml")):
        objects = _objects(path)
        for feature, element in resolver.features_of(objects).items():
            for instant in ("2026-03-10T07:00:00Z", "2026-03-14T09:00:00Z", "2026-06-01T07:00:00Z"):
                if element == "event:Event":
                    e = resolver.EventResolution.model_validate(resolver.event_state(objects, feature, instant).model_dump(mode="json"))
                    assert e.state in ("active", "future", "ended", "cancelled", "unresolved", "ambiguous")
                    continue
                r = resolver.Resolution.model_validate(resolver.resolve(objects, feature, instant).model_dump(mode="json"))
                assert r.contract == "aixm-resolution/1" and r.rules_applied and r.as_of.endswith("Z")
                assert all(any(rule.startswith(prefix) for prefix in ("Temporality Concept 1.1", "TS_", "Digital NOTAM Specification 2.0 (DRAFT)"))
                           for rule in r.rules_applied), r.rules_applied
                if r.asserted_status is not None:
                    assert r.status_state == "asserted" and len(r.operative) == 1
