"""The packaged SC-OES registries: §139's checks, the helper surface, and the payload map.

§139 lists thirteen registry checks and each one has a test here, named for the phrase it comes
from. Two of them are not what a first reading suggests, and both are recorded at the test:

- **"legacy mapping present, including null"** is a check on the RAW JSON, not on the parsed
  record. A model with a required field answers the question after the fact — a missing key would
  have failed validation for a reason that reads as a schema error — and what §110 actually
  requires is that the key be there. So the raw document is read and the keys are counted.
- **"payload model resolves when declared"** resolves against `OES_PAYLOAD_MODELS`, which is
  Python, and never by importing a name the data supplies. ADR 0004 decision 8 is the rule the
  registry is data and is never executed; a loader that imported what a registry names would be
  the one shape that breaks it.

This module is PACKAGE-ONLY (`gates/wheel_install.py`): everything it touches is reached through
`synapse_cdm`, so it is a real check against an installed wheel. The Turtle authority behind
`ontology_terms.json` is at the repository root and does not ship — the drift test that compares
the two lives in `tests/test_cdm_ontology.py`, which is repository-bound for exactly that reason.
"""
import importlib.resources
import json

import pytest
from pydantic import BaseModel, ValidationError

from synapse_cdm.enums import EventType
from synapse_cdm.models import GnssInterferencePayload
from synapse_cdm.oes import EventClass, is_governed_event_type, validate_ontology_identifier
from synapse_cdm.oes_registry import (
    OES_PAYLOAD_MODELS,
    PROFILES,
    EventTypeRecord,
    Maturity,
    get_event_type,
    get_legacy_event_type,
    get_ontology_term,
    get_profile_event_types,
    list_event_types,
    list_ontology_terms,
)

#: ADR 0007's decision table, transcribed once: the mapping column is the only part of the
#: registry no other artefact in this package can be compared against, so it is written here as
#: the independent copy a drift check needs.
LEGACY = {
    "sc.pnt.gnss_interference.v1": EventType.GNSS_INTERFERENCE,
    "sc.air.air_track_observed.v1": None,
    "sc.air.runway_availability_changed.v1": EventType.STATUS_CHANGE,
    "sc.air.airspace_restriction_changed.v1": EventType.STATUS_CHANGE,
    "sc.logistics.supply_threshold_reached.v1": EventType.STATUS_CHANGE,
    "sc.logistics.route_availability_changed.v1": EventType.STATUS_CHANGE,
    "sc.isr.threat_assessment_updated.v1": None,
    "sc.c2.system_availability_changed.v1": EventType.STATUS_CHANGE,
    "sc.mission.mission_status_changed.v1": EventType.STATUS_CHANGE,
    "sc.mission.operational_impact_assessed.v1": None,
    "sc.decision.recommendation_created.v1": None,
    "sc.decision.decision_recorded.v1": None,
    "sc.decision.action_authorized.v1": None,
}

#: §103-§109's classes, transcribed from the specification rather than read from the file the
#: test is about.
CLASSES = {
    "sc.pnt.gnss_interference.v1": EventClass.OBSERVATION,
    "sc.air.air_track_observed.v1": EventClass.OBSERVATION,
    "sc.air.runway_availability_changed.v1": EventClass.STATE_CHANGE,
    "sc.air.airspace_restriction_changed.v1": EventClass.CONSTRAINT,
    "sc.logistics.supply_threshold_reached.v1": EventClass.STATE_CHANGE,
    "sc.logistics.route_availability_changed.v1": EventClass.STATE_CHANGE,
    "sc.isr.threat_assessment_updated.v1": EventClass.ASSESSMENT,
    "sc.c2.system_availability_changed.v1": EventClass.STATE_CHANGE,
    "sc.mission.mission_status_changed.v1": EventClass.STATE_CHANGE,
    "sc.mission.operational_impact_assessed.v1": EventClass.IMPACT,
    "sc.decision.recommendation_created.v1": EventClass.RECOMMENDATION,
    "sc.decision.decision_recorded.v1": EventClass.DECISION,
    "sc.decision.action_authorized.v1": EventClass.ACTION,
}

MATURITIES = {
    "sc.pnt.gnss_interference.v1": Maturity.DRAFT,
    "sc.air.air_track_observed.v1": Maturity.DRAFT,
    "sc.air.runway_availability_changed.v1": Maturity.DRAFT,
    "sc.air.airspace_restriction_changed.v1": Maturity.DRAFT,
    "sc.logistics.supply_threshold_reached.v1": Maturity.DRAFT,
    "sc.logistics.route_availability_changed.v1": Maturity.DRAFT,
    "sc.isr.threat_assessment_updated.v1": Maturity.EXPERIMENTAL,
    "sc.c2.system_availability_changed.v1": Maturity.DRAFT,
    "sc.mission.mission_status_changed.v1": Maturity.DRAFT,
    "sc.mission.operational_impact_assessed.v1": Maturity.EXPERIMENTAL,
    "sc.decision.recommendation_created.v1": Maturity.EXPERIMENTAL,
    "sc.decision.decision_recorded.v1": Maturity.EXPERIMENTAL,
    "sc.decision.action_authorized.v1": Maturity.EXPERIMENTAL,
}


def _raw(name):
    root = importlib.resources.files("synapse_cdm") / "registry" / "sc_oes"
    return json.loads((root / name).read_text(encoding="utf-8"))


def _entry(**overrides):
    base = dict(
        id="sc.pnt.gnss_interference.v1", title="t", description="d", domain="pnt", profile="PNT",
        profile_version="0.1.0", event_class="OBSERVATION", maturity="DRAFT",
        ontology_class="tag:synapsecommand.com,2026-09-06:ontology:pnt:GNSSInterferenceEvent",
        payload_model="GnssInterferencePayload", legacy_event_type="GNSS_INTERFERENCE",
        introduced_in="0.1.0", deprecated=False, replacement=None,
    )
    base.update(overrides)
    return base


# --------------------------------------------------------------------------------------------
# §139's thirteen checks.
# --------------------------------------------------------------------------------------------

def test_the_registry_ships_and_is_read_from_the_package():
    """No checkout, no network, no path a consumer has to know (§17, §125)."""
    root = importlib.resources.files("synapse_cdm") / "registry" / "sc_oes"
    assert (root / "event_types.json").is_file()
    assert (root / "ontology_terms.json").is_file()
    assert len(list_event_types()) == 13


def test_ids_are_unique():
    ids = [e.id for e in list_event_types()]
    assert len(ids) == len(set(ids)) == 13


def test_ids_are_valid_governed_identifiers():
    """"valid IDs" — the frozen grammar of ADR 0003 decision 9, and only the `sc.` namespace."""
    for entry in list_event_types():
        assert is_governed_event_type(entry.id), entry.id


def test_an_ungoverned_identifier_is_refused_by_the_record():
    for bad in ("x.acme.pnt.gnss_interference.v1", "sc.PNT.gnss_interference.v1",
                "sc.pnt.gnss_interference.v0", "gnss_interference"):
        with pytest.raises(ValidationError):
            EventTypeRecord.model_validate(_entry(id=bad))


def test_every_profile_exists():
    """"profile exists" — one of §113's seven, and nothing else may be named."""
    for entry in list_event_types():
        assert entry.profile in PROFILES
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(profile="Maritime"))


def test_every_profile_version_exists_and_is_a_version():
    for entry in list_event_types():
        assert entry.profile_version == "0.1.0"
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(profile_version="0.1"))


def test_every_event_class_exists_and_is_the_specified_one():
    """"EventClass exists" — and the value is §103-§109's, not merely a member of the enum."""
    for entry in list_event_types():
        assert isinstance(entry.event_class, EventClass)
        assert entry.event_class is CLASSES[entry.id]
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(event_class="OBSERVATIONS"))


def test_every_maturity_is_valid_and_is_the_specified_one():
    for entry in list_event_types():
        assert isinstance(entry.maturity, Maturity)
        assert entry.maturity is MATURITIES[entry.id]
    assert sum(1 for e in list_event_types() if e.maturity is Maturity.DRAFT) == 8
    assert sum(1 for e in list_event_types() if e.maturity is Maturity.EXPERIMENTAL) == 5
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(maturity="PROVISIONAL"))


def test_every_ontology_class_is_governed_by_the_term_registry():
    """"ontology class governed" — recognition against the packaged terms, not just syntax.

    A term that satisfies the grammar and that the ontology never minted would pass
    `validate_ontology_identifier` and fail here, which is the split ADR 0003 decision 6 makes.
    """
    terms = {t.id for t in list_ontology_terms()}
    for entry in list_event_types():
        assert validate_ontology_identifier(entry.ontology_class) == entry.ontology_class
        assert entry.ontology_class in terms, entry.ontology_class
        assert get_ontology_term(entry.ontology_class) is not None
    assert len({e.ontology_class for e in list_event_types()}) == 13


def test_a_declared_payload_model_resolves():
    """"payload model resolves when declared", by name against OES_PAYLOAD_MODELS."""
    for entry in list_event_types():
        if entry.payload_model is None:
            assert entry.id not in OES_PAYLOAD_MODELS
            continue
        assert OES_PAYLOAD_MODELS[entry.id].__name__ == entry.payload_model
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(payload_model="AirTrackPayload"))
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(payload_model=None))


def test_the_legacy_mapping_key_is_present_on_every_entry_including_the_nulls():
    """"legacy mapping present, including null" — asked of the raw document (§110)."""
    raw = _raw("event_types.json")
    assert len(raw["event_types"]) == 13
    for entry in raw["event_types"]:
        assert "legacy_event_type" in entry
    assert sum(1 for e in raw["event_types"] if e["legacy_event_type"] is None) == 6


def test_a_non_null_legacy_mapping_is_a_real_eventtype_member():
    """"legacy EventType valid when non-null", and it is ADR 0007's table exactly."""
    for entry in list_event_types():
        assert entry.legacy_event_type == LEGACY[entry.id]
        if entry.legacy_event_type is not None:
            assert isinstance(entry.legacy_event_type, EventType)
    assert sum(1 for e in list_event_types() if e.legacy_event_type is None) == 6
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(legacy_event_type="ASSESSMENT"))


def test_every_entry_has_a_description_and_a_title():
    for entry in list_event_types():
        assert entry.description.strip() and entry.title.strip()
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(description=""))


def test_every_id_carries_a_semantic_major_and_a_version_segment():
    """"semantic version segment present" — the major is in the identifier itself (§49)."""
    for entry in list_event_types():
        assert entry.id.rsplit(".", 1)[1] == "v1"
        assert entry.introduced_in == "0.1.0"


def test_a_deprecated_entry_carries_its_migration_information():
    """"deprecated entry has migration information", and nothing is deprecated in v0.1.0."""
    assert [e.id for e in list_event_types() if e.deprecated] == []
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(deprecated=True))
    with pytest.raises(ValidationError):
        EventTypeRecord.model_validate(_entry(replacement="sc.pnt.gnss_interference.v2"))
    ok = EventTypeRecord.model_validate(
        _entry(deprecated=True, replacement="sc.pnt.gnss_interference.v2")
    )
    assert ok.replacement == "sc.pnt.gnss_interference.v2"


# --------------------------------------------------------------------------------------------
# The helper surface (§126, ADR 0004 decision 7) and the payload map (§111-§112).
# --------------------------------------------------------------------------------------------

def test_get_event_type_answers_recognition_and_not_syntax():
    assert get_event_type("sc.pnt.gnss_interference.v1").title == "GNSS interference observed"
    assert is_governed_event_type("sc.air.imaginary_thing.v1")
    assert get_event_type("sc.air.imaginary_thing.v1") is None
    assert get_event_type("x.acme.air.thing.v1") is None


def test_get_profile_event_types_partitions_the_registry():
    counts = {p: len(get_profile_event_types(p)) for p in PROFILES}
    assert counts == {"PNT": 1, "Air": 3, "Logistics": 2, "ISR": 1, "C2": 1, "Mission": 2,
                      "Decision": 3}
    assert sum(counts.values()) == 13
    with pytest.raises(KeyError):
        get_profile_event_types("Maritime")


def test_get_legacy_event_type_distinguishes_no_mapping_from_no_type():
    """§27's null is "no meaningful legacy category is governed", not "unknown" (ADR 0007)."""
    assert get_legacy_event_type("sc.pnt.gnss_interference.v1") is EventType.GNSS_INTERFERENCE
    assert get_legacy_event_type("sc.air.air_track_observed.v1") is None
    with pytest.raises(KeyError):
        get_legacy_event_type("sc.air.imaginary_thing.v1")


def test_the_ontology_helpers_read_the_generated_registry():
    terms = list_ontology_terms()
    assert len(terms) == 73
    term = get_ontology_term("tag:synapsecommand.com,2026-09-06:ontology:core:Affects")
    assert term is not None and term.kind == "property" and term.module == "core"
    assert get_ontology_term("tag:synapsecommand.com,2026-09-06:ontology:core:Nothing") is None
    assert get_ontology_term("https://example.org/ontology/Runway") is None


def test_the_payload_map_has_one_entry_and_reuses_the_existing_model():
    """§112: one governed typed payload in v0.1.0, and `GnssInterferencePayload` is not copied."""
    assert list(OES_PAYLOAD_MODELS) == ["sc.pnt.gnss_interference.v1"]
    assert OES_PAYLOAD_MODELS["sc.pnt.gnss_interference.v1"] is GnssInterferencePayload
    assert issubclass(GnssInterferencePayload, BaseModel)
    assert GnssInterferencePayload.model_config.get("extra") == "allow"


def test_an_unregistered_type_keeps_a_free_form_payload():
    """§111: unknown event types retain free-form payloads and extra fields survive."""
    free = [e.id for e in list_event_types() if e.payload_model is None]
    assert len(free) == 12
    for type_id in free:
        assert type_id not in OES_PAYLOAD_MODELS


def test_the_registry_document_declares_its_own_provenance():
    raw = _raw("event_types.json")
    assert raw["artefact"] == "sc-oes-event-types"
    assert raw["sc_oes_version"] == "0.1.0"
    assert "EVENT-TYPE-PROCESS.md" in raw["authored"]
    assert _raw("ontology_terms.json")["generated_by"] == "gates/ontology_terms.py"


def test_the_registry_is_data_and_names_nothing_to_import():
    """ADR 0004 decision 8: parsed as JSON, never executed. No value is an import path."""
    raw = _raw("event_types.json")
    for entry in raw["event_types"]:
        assert entry["payload_model"] in (None, "GnssInterferencePayload")
        assert ":" not in (entry["payload_model"] or "")
