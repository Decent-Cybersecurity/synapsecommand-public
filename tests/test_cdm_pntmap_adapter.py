"""The reference adapter, checked case by case — including the cases it must REFUSE.

Every test here maps to a line in the adapter's docstring. If one of them is deleted, the
claim it defends should be deleted from the docstring in the same commit.
"""
import inspect
import json
import pathlib

import pytest

from synapse_cdm import adapter, conformance, ids, oes_registry, times
from synapse_cdm.adapters import pntmap
from synapse_cdm.adapters.pntmap import PntmapAdapter
from synapse_cdm.enums import (
    Affiliation, EntityType, EventType, InterferenceType, PositionSource, Severity,
)
from synapse_cdm.models import Event
from synapse_cdm.oes import EventClass
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION, SC_OES_VERSION

import synapse_cdm

# The package lives under packages/cdm/ while this suite sits at the repo root, so its
# internal files are located through the import system rather than by walking up from
# this file: a relative hop between the two breaks the moment either one moves, and this
# way the files checked are the ones belonging to the package that is actually importable.
FIXTURES = pathlib.Path(synapse_cdm.__file__).resolve().parent / "fixtures" / "pntmap"


def _adapter():
    return PntmapAdapter(clock=times.frozen_clock())


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _translate(name):
    entity, event = _adapter().to_cdm(_fixture(name))
    return entity, event


def test_one_alert_becomes_one_entity_and_one_event():
    entity, event = _translate("jamming_gulf_of_riga")
    assert entity.entity_type is EntityType.INTERFERENCE_SOURCE
    assert event.event_type is EventType.GNSS_INTERFERENCE
    assert event.related_entities == [entity.entity_id]


def test_no_business_logic_a_jammer_is_not_inferred_hostile():
    """The rule at its most tempting: only a stated attribution may set affiliation."""
    stated, _ = _translate("jamming_gulf_of_riga")
    assert stated.affiliation is Affiliation.HOSTILE          # payload says attribution hostile
    unstated, _ = _translate("unknown_type_vendor_fields")    # jamming, no attribution
    assert unstated.affiliation is Affiliation.UNKNOWN, (
        "inferring HOSTILE from 'there is jamming' is an intelligence judgement made inside a "
        "translator — invisible to the audit trail and wrong the first time it is a friendly "
        "EW exercise"
    )


def test_an_unlocated_emitter_has_no_position_and_not_a_zero_one():
    entity, _ = _translate("spoofing_no_geolocation")
    assert entity.position is None


def test_a_latitude_of_zero_survives_translation():
    """`if not lat` would silently discard this emitter. The equator is a real place."""
    entity, _ = _translate("equator_emitter_l5")
    assert entity.position is not None
    assert entity.position.lat == 0.0 and entity.position.lon == 6.7


def test_geolocation_method_decides_how_much_the_position_is_trusted():
    assert _translate("jamming_gulf_of_riga")[0].position.position_source is (
        PositionSource.ESTIMATED)                                     # tdoa
    assert _translate("equator_emitter_l5")[0].position.position_source is (
        PositionSource.MANUAL)                                        # surveyed


def test_an_unmapped_interference_type_becomes_unknown_not_a_guess():
    entity, event = _translate("unknown_type_vendor_fields")
    assert event.typed_payload().interference_type is InterferenceType.UNKNOWN
    # ... and the source's own word survives, so the collapse is recoverable.
    assert entity.attributes["interference_type"] == "anomalous_carrier"


def test_an_unreadable_severity_is_refused_rather_than_defaulted():
    payload = _fixture("jamming_gulf_of_riga") | {"severity": "catastrophic"}
    with pytest.raises(ValueError, match="unknown PNTMAP severity"):
        _adapter().to_cdm(payload)


def test_severity_maps_across_the_whole_range():
    seen = {name: _translate(name)[1].severity for name in
            ("jamming_gulf_of_riga", "spoofing_no_geolocation",
             "unknown_type_vendor_fields", "equator_emitter_l5")}
    assert set(seen.values()) == {Severity.CRITICAL, Severity.WARNING,
                                 Severity.ADVISORY, Severity.INFO}


def test_a_partial_alert_is_refused_with_the_missing_field_named():
    for missing in ("alert_id", "alert_time", "interference"):
        payload = {k: v for k, v in _fixture("jamming_gulf_of_riga").items() if k != missing}
        with pytest.raises(ValueError, match=missing):
            _adapter().to_cdm(payload)


def test_identity_is_derived_stable_and_states_what_it_keyed_on():
    entity, event = _translate("jamming_gulf_of_riga")
    assert entity.entity_id == ids.derive("PNTMAP", "EMT-4471", kind="entity")
    assert event.event_id == ids.derive("PNTMAP", "PNTMAP-2026-04-29-0117", kind="event")
    assert entity.attributes["entity_id_basis"] == "emitter.emitter_id"

    # A second alert from the same emitter yields the SAME entity and a DIFFERENT event.
    second = _fixture("jamming_gulf_of_riga") | {"alert_id": "PNTMAP-2026-04-29-0999"}
    entity2, event2 = _adapter().to_cdm(second)
    assert entity2.entity_id == entity.entity_id, "an emitter must not multiply per alert"
    assert event2.event_id != event.event_id


def test_the_id_basis_is_reported_when_it_is_only_alert_stable():
    """Without an upstream emitter id, the id is stable for the ALERT, not for the emitter."""
    entity, _ = _translate("unknown_type_vendor_fields")
    assert entity.attributes["entity_id_basis"] == "alert_id"


def test_entity_and_event_ids_do_not_collide_on_one_identifier():
    payload = _fixture("unknown_type_vendor_fields")
    entity, event = _adapter().to_cdm(payload)
    assert str(entity.entity_id) != str(event.event_id)


def test_source_ids_hold_the_identifier_each_object_is_dedupable_by():
    entity, event = _translate("jamming_gulf_of_riga")
    assert entity.source_ids[0].external_id == "EMT-4471"
    assert event.source_ids[0].external_id == "PNTMAP-2026-04-29-0117"


def test_nothing_is_dropped_including_a_vendor_block_never_seen_before():
    entity, _ = _translate("unknown_type_vendor_fields")
    vendor = entity.attributes["source_extras"]["vendor"]
    assert vendor["detector_firmware"] == "2.11.4-rc3"
    assert vendor["classifier"] == {"model": "pnt-cnn-v3", "margin": 0.08}


def test_a_list_valued_extra_stays_a_list():
    _, event = _translate("jamming_gulf_of_riga")
    assert event.payload["source_extras"]["affected_constellations"] == ["GPS", "GALILEO"]


def test_the_symbol_is_derived_and_says_so():
    entity, _ = _translate("jamming_gulf_of_riga")
    assert entity.symbol[3] == "6", "HOSTILE standard identity"
    assert entity.symbol[2] == "2", "synthetic -> simulation context digit"
    assert "derived from affiliation" in entity.attributes["symbol_basis"]


def test_received_at_comes_from_the_clock_and_observed_at_from_the_source():
    _, event = _translate("jamming_gulf_of_riga")
    assert times.render(event.observed_at) == "2026-04-29T06:12:44.000Z"
    assert times.render(event.received_at) == times.render(times.FROZEN_NOW)


def test_the_affected_area_becomes_the_event_geometry_in_lon_lat_order():
    _, event = _translate("jamming_gulf_of_riga")
    ring = event.geometry.coordinates[0]
    assert ring[0] == ring[-1], "closed ring"
    assert 21.0 < ring[0][0] < 23.0 and 57.0 < ring[0][1] < 58.0


def test_bytes_and_dict_input_agree():
    payload = _fixture("jamming_gulf_of_riga")
    from_dict = _adapter().to_cdm(payload)
    from_bytes = _adapter().to_cdm(json.dumps(payload).encode())
    assert [o.model_dump(mode="json") for o in from_dict] == \
           [o.model_dump(mode="json") for o in from_bytes]


def test_a_non_json_input_type_is_refused_clearly():
    with pytest.raises(TypeError, match="JSON bytes or a dict"):
        _adapter().to_cdm(42)


def test_live_mode_marks_objects_live_and_changes_the_symbol_context():
    entity, event = PntmapAdapter(clock=times.frozen_clock(), synthetic=False).to_cdm(
        _fixture("jamming_gulf_of_riga"))
    assert entity.source.synthetic is False and event.source.synthetic is False
    assert entity.symbol[2] == "0", "reality context digit"


def test_every_fixture_is_synthetic_by_default():
    """No real PNTMAP data in this repository, and the objects must say so (TR-12)."""
    for path in sorted(FIXTURES.glob("*.json")):
        for obj in _adapter().to_cdm(json.loads(path.read_text())):
            assert obj.source.synthetic is True


# --------------------------------------------------------------------------------------------
# THE SC-OES REFERENCE PRODUCER
#
# One test per claim in the adapter docstring's SC-OES section, on the same rule this file's
# header states: a claim in the docstring and a test here live and die together. The six
# refusals get a test each because a refusal nothing checks is how a fabricated field arrives
# in a later round without anybody noticing.
# --------------------------------------------------------------------------------------------

def test_the_event_carries_the_sc_oes_block_and_the_entity_has_no_such_field():
    entity, event = _translate("jamming_gulf_of_riga")
    assert event.oes is not None
    assert not hasattr(entity, "oes"), "the block is Event's; an Entity has no wire semantics"


def test_the_three_asserted_fields_are_exactly_the_three():
    event = _translate("jamming_gulf_of_riga")[1]
    assert event.oes.spec_version == SC_OES_VERSION
    assert event.oes.event_class is EventClass.OBSERVATION
    assert event.oes.type_id == "sc.pnt.gnss_interference.v1"


def test_every_fixture_gets_the_block_and_all_three_fields_agree_across_them():
    """Every PNTMAP alert is a GNSS-interference alert, including the one whose interference
    type this adapter cannot map: `anomalous_carrier` becomes `InterferenceType.UNKNOWN` in the
    payload and the SEMANTIC TYPE is unaffected, because what the type identifies is the kind of
    observation and not the classifier's answer."""
    seen = set()
    for path in sorted(FIXTURES.glob("*.json")):
        event = _adapter().to_cdm(json.loads(path.read_text()))[1]
        assert event.oes is not None, path.name
        seen.add((event.oes.spec_version, event.oes.event_class, event.oes.type_id))
    assert len(list(FIXTURES.glob("*.json"))) == 4
    assert seen == {(SC_OES_VERSION, EventClass.OBSERVATION, "sc.pnt.gnss_interference.v1")}


def test_the_unmappable_interference_type_still_gets_the_semantic_type():
    event = _translate("unknown_type_vendor_fields")[1]
    assert event.payload["interference_type"] == InterferenceType.UNKNOWN.value
    assert event.oes.type_id == "sc.pnt.gnss_interference.v1"


def test_the_event_class_is_asserted_and_not_read_out_of_the_registry():
    """`spec/sc-oes/02-event-classes.md` forbids deriving the class from `type_id`, so the
    adapter states it. This checks the source says so, and then checks the assertion AGREES with
    the registry — a consistency check, which is the opposite of a derivation."""
    source = pathlib.Path(pntmap.__file__).read_text()
    assert "event_class=EventClass.OBSERVATION," in source
    record = oes_registry.get_event_type("sc.pnt.gnss_interference.v1")
    assert record is not None
    assert record.event_class is EventClass.OBSERVATION
    assert _translate("jamming_gulf_of_riga")[1].oes.event_class is record.event_class


def test_the_type_id_is_governed_and_its_legacy_mapping_is_the_event_type_emitted():
    record = oes_registry.get_event_type("sc.pnt.gnss_interference.v1")
    event = _translate("jamming_gulf_of_riga")[1]
    assert record.legacy_event_type is event.event_type is EventType.GNSS_INTERFERENCE
    assert record.profile == "PNT"


def test_the_spec_version_is_this_packages_own_and_not_the_schema_or_package_version():
    event = _translate("jamming_gulf_of_riga")[1]
    assert event.oes.spec_version == SC_OES_VERSION == "0.1.0"
    assert event.oes.spec_version != SCHEMA_VERSION
    assert event.oes.spec_version != PACKAGE_VERSION


def test_confidence_is_supplied_by_the_source_and_still_not_asserted_on_the_block():
    """The one refusal that is not obvious, so it is the one stated most loudly.

    PNTMAP gives `interference.confidence` on every alert. It is not fabricated and it is not
    dropped — it is already carried at `Entity.confidence`, and restating it on the event would
    put one producer number under two subjects."""
    alert = _fixture("jamming_gulf_of_riga")
    assert alert["interference"]["confidence"] == 0.87
    entity, event = _translate("jamming_gulf_of_riga")
    assert entity.confidence == 0.87
    assert event.oes.confidence is None
    for path in sorted(FIXTURES.glob("*.json")):
        raw = json.loads(path.read_text())
        assert "confidence" in raw["interference"], path.name
        assert _adapter().to_cdm(raw)[1].oes.confidence is None, path.name


def test_no_verification_state_is_invented():
    """`06-verification-and-confidence.md`: MUST NOT default to UNVERIFIED."""
    assert _translate("jamming_gulf_of_riga")[1].oes.verification is None


def test_no_lifecycle_status_is_invented():
    """`05-lifecycle.md`: MUST NOT default to ACTIVE."""
    assert _translate("jamming_gulf_of_riga")[1].oes.status is None


def test_the_alerts_own_validity_window_does_not_become_the_conditions_effective_interval():
    """`valid_until` says how long the ALERT stands. Reading it as `effective_to` would put a
    statement about a message onto the world, and `effective_from` would be `observed_at` under
    another name."""
    alert = _fixture("jamming_gulf_of_riga")
    assert alert["valid_until"] == "2026-04-29T07:00:00Z"
    entity, event = _translate("jamming_gulf_of_riga")
    assert entity.valid_to == times.parse("2026-04-29T07:00:00Z")
    assert event.oes.effective_from is None and event.oes.effective_to is None
    assert event.observed_at == times.parse(alert["alert_time"])


def test_no_security_marking_is_invented():
    assert _translate("jamming_gulf_of_riga")[1].oes.security is None


def test_the_emitter_gets_no_role_because_the_source_states_none():
    """The emitter IS in `related_entities`; what the source does not give is a role, and a role
    here has to be a governed ontology term. Choosing one is the intelligence judgement this
    adapter refuses everywhere else."""
    entity, event = _translate("jamming_gulf_of_riga")
    assert event.related_entities == [entity.entity_id]
    assert event.oes.entity_relations == []


def test_nothing_is_related_cited_or_extended():
    event = _translate("unknown_type_vendor_fields")[1]
    assert event.oes.event_relations == []
    assert event.oes.evidence == []
    assert event.oes.extensions == {}
    # and the vendor block is still parked losslessly rather than smuggled into extensions
    assert _translate("unknown_type_vendor_fields")[0].attributes["source_extras"]["vendor"][
        "detector_firmware"] == "2.11.4-rc3"


def test_pntmap_is_the_only_sc_oes_producer_in_this_package():
    """§116: existing adapters stay CDM Conformant without becoming SC-OES semantic producers.
    Read off the registered adapters rather than a list written here, so an adapter that starts
    emitting the block has to come back to this test and say so."""
    emitting = [name for name, cls in adapter.roster().items()
                if "OesMetadata(" in pathlib.Path(inspect.getfile(cls)).read_text()]
    assert emitting == ["pntmap"]


def test_the_block_survives_the_json_round_trip_the_goldens_are_written_from():
    event = _translate("jamming_gulf_of_riga")[1]
    reparsed = Event.model_validate(json.loads(event.model_dump_json()))
    assert reparsed.oes == event.oes


def test_the_emitted_event_passes_conformance_dimensions_a_b_and_c():
    """The reference producer is the one object in this repository that has to satisfy the
    conformance tool it ships beside. D is `SKIP` because the PNT profile has no normative
    content yet, and E is assessed against ontology identifiers this event carries none of."""
    event = _translate("jamming_gulf_of_riga")[1]
    report = conformance.assess(json.loads(event.model_dump_json()))
    verdicts = {k: v["verdict"] for k, v in report["dimensions"].items()}
    assert verdicts["A"] == "PASS"
    assert verdicts["B"] == "PASS"
    assert verdicts["C"] == "PASS"
    assert verdicts["D"] == "SKIP"
