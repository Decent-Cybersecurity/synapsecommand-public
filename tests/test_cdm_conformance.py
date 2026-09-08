"""Every rule §35-§41 states about the five conformance dimensions, exercised against an object.

The module under test is `synapse_cdm/conformance.py`; the normative documents are
`spec/sc-oes/13-conformance.md` and `docs/adr/0009-conformance-model.md`. This module is
PACKAGE-ONLY (`gates/wheel_install.py`): every path it touches is an importable name under
`synapse_cdm` or a file it writes into `tmp_path` itself, and the packaged SC-OES registry
artefacts it reads through the module ship in the wheel. It read "both registries" until
2026-09-07, when the count stopped being two: `conformance.py` reaches `event_types.json` for
dimension C, `profiles.json` for D and `ontology_terms.json` for E. The half of the same subject that reads the normative documents at
the repository root is `tests/test_cdm_conformance_spec.py`, in the other list, for the reason
`test_cdm_registry.py` and `test_cdm_ontology.py` are split the same way.

The objects here are built in code rather than loaded from the fixture tree, deliberately: a
conformance test needs objects that are WRONG in one named way each, and the fixture tree
contains none, because every fixture in it is the output of an adapter that works.
"""
import copy
import json
import socket
import subprocess
import sys
import uuid

import pytest

import synapse_cdm
from synapse_cdm import conformance, harness
from synapse_cdm.conformance import (
    DIMENSIONS,
    DIMENSION_KEYS,
    EXIT_FAILED,
    EXIT_INTERNAL,
    EXIT_OK,
    EXIT_USAGE,
    FAIL,
    PASS,
    PROFILE_ONTOLOGY_ID_FIELDS,
    PROFILE_RULE_CHECKS,
    PROFILE_RULES,
    SKIP,
    UNASSESSED_THIRD_PARTY_TERM,
    assess,
    assess_document,
    exit_status,
    render_report,
)
from synapse_cdm.oes import MAX_EXTENSION_DEPTH
from synapse_cdm.oes_registry import (
    PROFILES,
    get_event_type,
    get_profile,
    list_ontology_terms,
)

#: The six profiles that deliberately have no executable rules (§13). Derived, so that
#: a seventh acquiring rules changes this set rather than passing unnoticed.
SPECIFICATION_ONLY = tuple(p for p in PROFILES if not get_profile(p).rules)
from synapse_cdm.version import SCHEMA_VERSION, SC_OES_VERSION

EVENT_ID = "4cd605e7-afa2-5360-b5b9-c5e9fb5c76f4"
ENTITY_ID = "84db0e50-bc3b-5f30-9d66-338c0fbd883a"
OTHER_ID = str(uuid.uuid5(uuid.NAMESPACE_URL, "another event"))
GOVERNED_TYPE = "sc.pnt.gnss_interference.v1"
THIRD_PARTY_TERM = "https://example.org/vocab#Runway"


def event(**overrides) -> dict:
    """A conformant SC-OES event: A PASS, B PASS, C PASS, D SKIP, E SKIP."""
    obj = {
        "schema_version": SCHEMA_VERSION,
        "object_kind": "event",
        "event_id": EVENT_ID,
        "event_type": "GNSS_INTERFERENCE",
        "severity": "WARNING",
        "related_entities": [],
        "geometry": None,
        "payload": {"frequency_band": "L1", "interference_type": "JAMMING"},
        "observed_at": "2026-09-06T11:31:04.000Z",
        "received_at": "2026-09-06T11:31:05.000Z",
        "oes": oes_block(),
        "source": {"system": "PNTMAP", "adapter": "pntmap", "adapter_version": "1.0.0",
                   "synthetic": True},
        "source_ids": [{"system": "PNTMAP", "external_id": "SYNTHETIC-GNSS-001"}],
        "integrity": None,
    }
    obj.update(overrides)
    return obj


def oes_block(**overrides) -> dict:
    block = {
        "spec_version": SC_OES_VERSION,
        "event_class": "OBSERVATION",
        "type_id": GOVERNED_TYPE,
        "status": None,
        "verification": None,
        "confidence": None,
        "effective_from": None,
        "effective_to": None,
        "event_relations": [],
        "entity_relations": [],
        "evidence": [],
        "security": None,
        "extensions": {},
    }
    block.update(overrides)
    return block


def entity(**overrides) -> dict:
    obj = {
        "schema_version": SCHEMA_VERSION,
        "object_kind": "entity",
        "entity_id": ENTITY_ID,
        "entity_type": "FACILITY",
        "affiliation": "UNKNOWN",
        "symbol": None,
        "position": None,
        "kinematics": None,
        "attributes": {},
        "ontology_types": [],
        "valid_from": "2026-09-06T11:31:04.000Z",
        "valid_to": None,
        "confidence": None,
        "integrity": None,
        "source": {"system": "PNTMAP", "adapter": "pntmap", "adapter_version": "1.0.0",
                   "synthetic": True},
        "source_ids": [{"system": "PNTMAP", "external_id": "SYNTHETIC-ENTITY-001"}],
    }
    obj.update(overrides)
    return obj


def verdicts(obj, profile=None) -> dict[str, str]:
    return {k: d["verdict"] for k, d in assess(obj, profile=profile)["dimensions"].items()}


def detail(obj, key, profile=None) -> str:
    return assess(obj, profile=profile)["dimensions"][key]["detail"]


def findings(obj, key, profile=None) -> list[str]:
    return assess(obj, profile=profile)["dimensions"][key]["findings"]


def governed_term() -> str:
    """A term the packaged ontology registry actually carries, asked of the registry."""
    return list_ontology_terms()[0].id


# ------------------------------------------------------------------ §34 the model


def test_the_dimensions_are_the_five_specified_ones_in_order():
    assert [d.key for d in DIMENSIONS] == ["A", "B", "C", "D", "E"]
    assert [d.name for d in DIMENSIONS] == [
        "CDM Conformance",
        "SC-OES Core Syntax Conformance",
        "SC-OES Semantic Type Conformance",
        "SC-OES Profile Conformance",
        "Ontology Conformance",
    ]


def test_the_count_is_derived_from_the_dimension_list_and_not_written_as_a_literal():
    """ADR 0009's consequence: a sixth dimension must not arrive while the prose says five."""
    assert len(DIMENSION_KEYS) == len(DIMENSIONS)
    report = assess_document(event())
    assert set(report["summary"]) == set(DIMENSION_KEYS)
    assert set(report["objects"][0]["dimensions"]) == set(DIMENSION_KEYS)


def test_the_three_verdict_strings_are_the_ones_the_harness_already_spells():
    """The same fact stated in two modules, so the test is what keeps them from drifting."""
    assert (PASS, FAIL, SKIP) == (harness.PASS, harness.FAIL, harness.SKIP)


def test_no_aggregate_verdict_score_or_grade_is_produced():
    report = assess_document([event(), entity()])
    assert "score" not in json.dumps(report).lower()
    for forbidden in ("grade", "percentage", "overall", "compatibility_score"):
        assert forbidden not in report
    # The summary is verdict COUNTS per named dimension — five answers, never one.
    for key in DIMENSION_KEYS:
        assert set(report["summary"][key]) == {"name", PASS, FAIL, SKIP}


def test_skip_is_never_rendered_as_pass():
    report = assess_document(event())
    rendered = render_report(report)
    # The object's own D cell, taken from the detail block rather than from the counts line,
    # which legitimately names every verdict.
    detail_line = next(line for line in rendered.splitlines()
                       if line.strip().startswith("D ") and "no profile requested" in line)
    assert SKIP in detail_line and PASS not in detail_line
    assert report["summary"]["D"][PASS] == 0 and report["summary"]["D"][SKIP] == 1
    assert "0 PASS, 0 FAIL, 1 SKIP" in rendered
    assert "SKIP is not PASS" in rendered


# ------------------------------------------------------------------ §35 dimension A


def test_a_passes_a_conformant_event_and_a_conformant_entity():
    assert verdicts(event())["A"] == PASS
    assert verdicts(entity())["A"] == PASS


def test_a_fails_an_unknown_object_kind():
    v = assess(event(object_kind="satellite"))
    assert v["dimensions"]["A"]["verdict"] == FAIL
    assert "object_kind" in v["dimensions"]["A"]["findings"][0]


def test_a_fails_a_missing_required_field():
    obj = event()
    del obj["source_ids"]
    assert verdicts(obj)["A"] == FAIL


def test_a_fails_an_object_with_no_schema_version():
    obj = event()
    del obj["schema_version"]
    assert verdicts(obj)["A"] == FAIL
    assert any("schema_version" in f for f in findings(obj, "A"))


def test_a_fails_a_schema_version_a_major_apart():
    obj = event(schema_version="1.0.0")
    assert verdicts(obj)["A"] == FAIL
    assert any("not compatible" in f for f in findings(obj, "A"))


def test_a_fails_a_document_element_that_is_not_an_object():
    assert verdicts(["not an object"])["A"] == FAIL


def test_a_does_not_depend_on_the_content_of_the_oes_block():
    """13-conformance.md, normative, and the reason A is assessed with the block removed.

    One defect, one finding: a malformed `oes` block is dimension B's, and A still reports on
    the CDM object it is there to judge.
    """
    obj = event(oes=oes_block(confidence=7.5))
    assert verdicts(obj)["A"] == PASS
    assert verdicts(obj)["B"] == FAIL


def test_a_does_not_depend_on_the_presence_or_absence_of_the_oes_block():
    without = event()
    del without["oes"]
    assert verdicts(without)["A"] == verdicts(event())["A"] == PASS
    assert verdicts(event(oes=None))["A"] == PASS


def test_an_oes_key_on_a_kind_that_does_not_declare_one_is_a_cdm_failure_not_an_sc_oes_one():
    obj = entity(oes=oes_block())
    assert verdicts(obj)["A"] == FAIL
    assert verdicts(obj)["B"] == SKIP


# ------------------------------------------------------------------ §36 dimension B


def test_b_skips_a_legacy_event_with_no_oes_block():
    obj = event()
    del obj["oes"]
    assert verdicts(obj)["B"] == SKIP
    assert "made no SC-OES assertion" in detail(obj, "B")


def test_b_skips_an_object_kind_that_carries_no_sc_oes_metadata():
    assert verdicts(entity())["B"] == SKIP


def test_b_passes_a_valid_block_and_names_both_versions():
    assert verdicts(event())["B"] == PASS
    assert SC_OES_VERSION in detail(event(), "B")


def test_b_fails_an_oes_block_that_is_not_an_object():
    assert verdicts(event(oes="0.1.0"))["B"] == FAIL


@pytest.mark.parametrize("override, why", [
    ({"spec_version": "0.1"}, "invalid spec version"),
    ({"event_class": "GUESSWORK"}, "unknown EventClass"),
    ({"status": "MAYBE"}, "unknown lifecycle status"),
    ({"verification": "PROBABLY"}, "unknown verification"),
    ({"confidence": -0.1}, "confidence below zero"),
    ({"confidence": 1.1}, "confidence above one"),
    ({"effective_from": "2026-09-06T12:00:00.000Z",
      "effective_to": "2026-09-06T11:00:00.000Z"}, "backwards effective interval"),
    ({"type_id": "sc.PNT.Bad"}, "malformed type_id"),
    ({"type_id": "gnss_interference"}, "unnamespaced type_id"),
    ({"evidence": [{"kind": "SOURCE_RECORD"}]}, "evidence missing its anchor"),
    ({"security": {"classification": ""}}, "malformed security marking"),
    ({"extensions": {"sc.anything": 1}}, "reserved sc. extension key"),
    ({"extensions": {"quality": 1}}, "unnamespaced extension key"),
])
def test_b_fails_each_core_syntax_defect(override, why):
    """The extension NESTING bound is the one §36 check not here: it has its own pair below,
    because the value that trips it has to be built rather than written."""
    assert verdicts(event(oes=oes_block(**override)))["B"] == FAIL, why


@pytest.mark.parametrize("override, why", [
    ({"confidence": None}, "confidence None is UNKNOWN, not a defect"),
    ({"effective_from": "2026-09-06T11:00:00.000Z", "effective_to": None}, "open-ended interval"),
    ({"security": None}, "the security block is optional"),
    ({"extensions": {"x.acme.quality": 0.95}}, "a valid x.* extension"),
    ({"extensions": {"x.acme.unknown": {"whatever": [1, 2]}}}, "an unknown x.* extension"),
])
def test_b_passes_each_case_that_is_not_a_defect(override, why):
    assert verdicts(event(oes=oes_block(**override)))["B"] == PASS, why


def _nested(depth: int):
    """A value whose container depth is exactly `depth`, per ADR 0008's counting algorithm."""
    value: object = 1
    for _ in range(depth):
        value = {"n": value}
    return value


def test_b_accepts_an_extension_at_the_maximum_permitted_depth():
    block = oes_block(extensions={"x.acme.data": _nested(MAX_EXTENSION_DEPTH)})
    assert verdicts(event(oes=block))["B"] == PASS


def test_b_refuses_an_extension_one_level_past_the_maximum():
    block = oes_block(extensions={"x.acme.data": _nested(MAX_EXTENSION_DEPTH + 1)})
    obj = event(oes=block)
    assert verdicts(obj)["B"] == FAIL
    assert any(str(MAX_EXTENSION_DEPTH) in f for f in findings(obj, "B"))


def test_b_refuses_a_relation_that_points_at_the_citing_event():
    block = oes_block(event_relations=[{"predicate": "SUPERSEDES", "event_id": EVENT_ID}])
    obj = event(oes=block)
    assert verdicts(obj)["B"] == FAIL
    assert any("relation to itself" in f for f in findings(obj, "B"))


def test_b_refuses_the_same_predicate_to_the_same_target_twice():
    block = oes_block(event_relations=[{"predicate": "SUPERSEDES", "event_id": OTHER_ID},
                                       {"predicate": "SUPERSEDES", "event_id": OTHER_ID}])
    assert verdicts(event(oes=block))["B"] == FAIL


def test_b_refuses_an_entity_relation_whose_subject_is_not_in_related_entities():
    block = oes_block(entity_relations=[{"entity_id": ENTITY_ID,
                                         "predicate": governed_term()}])
    obj = event(oes=block, related_entities=[])
    assert verdicts(obj)["B"] == FAIL
    assert any("related_entities" in f for f in findings(obj, "B"))


def test_b_accepts_an_entity_relation_whose_subject_is_in_related_entities():
    block = oes_block(entity_relations=[{"entity_id": ENTITY_ID,
                                         "predicate": governed_term()}])
    assert verdicts(event(oes=block, related_entities=[ENTITY_ID]))["B"] == PASS


# ------------------------------------------------------------------ §37 dimension C


def test_c_passes_a_governed_type_that_agrees_with_the_registry():
    assert verdicts(event())["C"] == PASS


def test_c_skips_a_syntactically_valid_unknown_third_party_type():
    """§37: the repository does not govern that third-party semantic contract."""
    obj = event(oes=oes_block(type_id="x.acme.pnt.proprietary_alert.v1"))
    assert verdicts(obj)["C"] == SKIP
    assert "does not govern" in detail(obj, "C")


def test_c_fails_an_unknown_governed_type():
    """§14's namespace reservation, enforced where 12-versioning.md says it is enforced."""
    obj = event(oes=oes_block(type_id="sc.pnt.imaginary_thing.v1"))
    assert verdicts(obj)["C"] == FAIL
    assert "reserved sc. namespace" in findings(obj, "C")[0]


def test_c_fails_an_unknown_semantic_major_of_a_known_type():
    assert verdicts(event(oes=oes_block(type_id="sc.pnt.gnss_interference.v2")))["C"] == FAIL


def test_a_type_id_in_neither_grammar_is_one_finding_in_b_and_a_skip_in_c():
    """SA.1 §31: one syntax defect produces one finding, in the dimension whose subject it is."""
    obj = event(oes=oes_block(type_id="gnss-interference"))
    assert verdicts(obj)["B"] == FAIL
    assert verdicts(obj)["C"] == SKIP
    assert detail(obj, "C") == ("semantic type not evaluated because core type identifier "
                                "syntax failed")


def test_c_fails_an_event_class_the_registry_does_not_declare_for_the_type():
    obj = event(oes=oes_block(event_class="DECISION"))
    assert verdicts(obj)["C"] == FAIL
    assert any("event_class" in f for f in findings(obj, "C"))


def test_c_fails_a_payload_the_registered_model_refuses():
    obj = event(payload={"interference_type": "JAMMING"})
    assert verdicts(obj)["C"] == FAIL
    assert any("frequency_band" in f for f in findings(obj, "C"))


def test_c_fails_a_legacy_event_type_that_contradicts_the_governed_mapping():
    obj = event(event_type="ALERT")
    assert verdicts(obj)["C"] == FAIL
    assert any("legacy mapping" in f for f in findings(obj, "C"))


def test_c_asks_nothing_of_event_type_where_the_registry_governs_no_mapping():
    """ADR 0007's six nulls: "no meaningful legacy category is governed", not "unfinished"."""
    unmapped = next(e for e in (get_event_type(t) for t in
                                ("sc.air.air_track_observed.v1",
                                 "sc.decision.decision_recorded.v1"))
                    if e is not None and e.legacy_event_type is None)
    obj = event(event_type="ALERT",
                oes=oes_block(type_id=unmapped.id, event_class=unmapped.event_class.value))
    assert verdicts(obj)["C"] == PASS


def test_c_skips_an_object_with_no_semantic_type_claimed():
    obj = event()
    del obj["oes"]
    assert verdicts(obj)["C"] == SKIP
    assert verdicts(entity())["C"] == SKIP


# ------------------------------------------------------------------ §38 dimension D


def test_d_skips_when_no_profile_is_requested():
    assert verdicts(event())["D"] == SKIP
    assert "does not infer" in detail(event(), "D")


def test_d_skips_against_a_specification_only_profile_because_it_declares_no_rule():
    """§36. `spec/sc-oes/profiles/air.md`: "a D assessment against it has no rules to check"."""
    for profile in SPECIFICATION_ONLY:
        assert verdicts(event(), profile=profile)["D"] == SKIP
        said = detail(event(), "D", profile=profile)
        assert "declares no executable conformance rules" in said
        assert "SPECIFICATION_ONLY" in said


def test_d_passes_the_canonical_event_against_the_executable_profile():
    """§34's six conditions, met. The profile is named, exists, has rules, and the event is in it."""
    assert verdicts(event(), profile="PNT")["D"] == PASS
    said = detail(event(), "D", profile="PNT")
    assert "PNT profile 0.1.0 rules hold (1 checked: event_type_membership_required)" in said
    assert '"SC-OES PNT Profile 0.1 Conformant"' in said


def test_the_canonical_event_passes_all_five_dimensions_against_its_profile():
    """§35/§91: five verdicts, five reasons, no aggregate anywhere. The hard criterion."""
    # The canonical reference event carries an entity relation with a governed predicate, which
    # is what gives E a governed identifier to recognise: an event with no ontology identifier at
    # all is an honest E `SKIP` and would prove nothing about the five-PASS case.
    obj = event(related_entities=[ENTITY_ID],
                oes=oes_block(entity_relations=[{"entity_id": ENTITY_ID,
                                                 "predicate": governed_term()}]))
    result = conformance.assess(obj, profile="PNT")
    assert {k: v["verdict"] for k, v in result["dimensions"].items()} == {
        "A": PASS, "B": PASS, "C": PASS, "D": PASS, "E": PASS}
    reasons = [v["detail"] for v in result["dimensions"].values()]
    assert len(set(reasons)) == 5, "each dimension must have its own reason"
    assert "overall" not in json.dumps(result).lower()


def test_d_fails_a_governed_event_that_belongs_to_another_profile():
    """§40/§94. The distinction between "no rules to run" and "rules ran and the object is out"."""
    elsewhere = event(oes=oes_block(type_id="sc.c2.system_availability_changed.v1"))
    assert verdicts(elsewhere, profile="PNT")["D"] == FAIL
    findings = conformance.assess(elsewhere, profile="PNT")["dimensions"]["D"]["findings"]
    assert len(findings) == 1
    assert "is not a member of the requested profile PNT 0.1.0" in findings[0]
    assert "sc.c2.system_availability_changed.v1" in findings[0]


def test_d_fails_a_third_party_type_put_to_the_executable_profile():
    """An `x.` type is a contract this repository does not govern, and it is not in PNT either."""
    ungoverned = event(oes=oes_block(type_id="x.acme.pnt.thing.v1"))
    assert verdicts(ungoverned, profile="PNT")["D"] == FAIL


def test_d_skips_a_legacy_event_with_no_oes_block_against_the_executable_profile():
    """§38: membership cannot be established, and SC-OES metadata is not manufactured for it."""
    legacy = event()
    del legacy["oes"]
    assert verdicts(legacy, profile="PNT")["D"] == SKIP
    assert "not manufactured" in detail(legacy, "D", profile="PNT")


def test_d_skips_a_non_event_object_whichever_profile_is_named():
    for profile in PROFILES:
        assert verdicts(entity(), profile=profile)["D"] == SKIP


def test_the_declared_rules_are_exactly_the_checks_this_module_implements():
    """Both directions: no rule without a check, and no check no profile can reach.

    This is what makes `_profile_rule_holds`' `NotImplementedError` unreachable in a shipped
    tree, and it is the closure the profile documents promised — the round that declares a rule
    writes its check in the same commit.
    """
    assert set(PROFILE_RULES) == set(PROFILES) == set(PROFILE_ONTOLOGY_ID_FIELDS)
    declared = {rule for rules in PROFILE_RULES.values() for rule in rules}
    assert declared == set(PROFILE_RULE_CHECKS)
    assert all(fields == () for fields in PROFILE_ONTOLOGY_ID_FIELDS.values())


def test_exactly_one_profile_declares_a_rule_in_v0_1_0():
    """§12: PNT only. The other six are specification-only and D reports that, not a grade."""
    assert [name for name, rules in PROFILE_RULES.items() if rules] == ["PNT"]
    assert PROFILE_RULES["PNT"] == ("event_type_membership_required",)


def test_d_reports_the_registrys_own_statement_about_the_type_as_an_observation():
    """The observation survives where D has no verdict of its own: a specification-only profile."""
    assert "the registry declares" in detail(event(), "D", profile="Air")
    assert "not in Air" in detail(event(), "D", profile="Air")
    ungoverned = event(oes=oes_block(type_id="x.acme.pnt.thing.v1"))
    assert "not a governed type" in detail(ungoverned, "D", profile="Air")


def test_the_profile_rules_do_not_read_any_producer_identity():
    """§21/§25: PNTMAP is a reference producer, not a condition of conforming.

    The same event, produced by four different systems and adapters, gets the same D verdict.
    Asserted over the assessment rather than over the source text, because what matters is that
    the verdict does not move.
    """
    for system, adapter_name in (("PNTMAP", "pntmap"), ("ACME-GNSS-MONITOR", "acme"),
                                 ("MIL-SENSOR-7", "milsensor"), ("SIMULATOR", "sim")):
        obj = event(source={"system": system, "adapter": adapter_name,
                            "adapter_version": "9.9.9", "synthetic": True},
                    source_ids=[{"system": system, "external_id": "X-1"}])
        assert verdicts(obj, profile="PNT")["D"] == PASS, system


def test_the_profile_requires_none_of_the_optional_semantics():
    """§26/§27/§31/§32/§33: nothing optional is made mandatory by the profile.

    Every one of these is already `None`, `[]` or `{}` on the canonical event and the verdict is
    `PASS`; the test states the list so that a future rule making one of them required has to
    delete a name from it.
    """
    optional = ("confidence", "verification", "status", "effective_from", "effective_to",
                "security", "evidence", "entity_relations", "extensions")
    block = oes_block()
    assert all(not block[field] for field in optional), block
    obj = event(oes=block, geometry=None, related_entities=[])
    assert verdicts(obj, profile="PNT")["D"] == PASS


# ------------------------------------------------------------------ §39 / SA.1 dimension E


def test_e_skips_when_no_ontology_identifiers_occur():
    assert verdicts(event())["E"] == SKIP
    assert verdicts(entity())["E"] == SKIP
    assert detail(entity(), "E") == "no ontology identifiers present"


def test_e_skips_an_entity_whose_ontology_types_is_empty_or_omitted():
    omitted = entity()
    del omitted["ontology_types"]
    assert verdicts(omitted)["E"] == SKIP
    assert verdicts(entity(ontology_types=[]))["E"] == SKIP


def test_e_passes_a_governed_term_the_packaged_registry_carries():
    obj = entity(ontology_types=[governed_term()])
    assert verdicts(obj)["E"] == PASS


def test_e_fails_an_unknown_term_in_the_reserved_synapsecommand_family():
    obj = entity(ontology_types=[
        "tag:synapsecommand.com,2026-09-06:ontology:core:NoSuchThingWasEverMinted"])
    assert verdicts(obj)["E"] == FAIL
    assert "reserved SynapseCommand ontology family" in findings(obj, "E")[0]


def test_e_skips_an_object_carrying_only_valid_third_party_identifiers():
    """SA.1 §35: the terms are present and this repository governs none of them."""
    obj = entity(ontology_types=[THIRD_PARTY_TERM])
    assert verdicts(obj)["E"] == SKIP
    assert UNASSESSED_THIRD_PARTY_TERM in findings(obj, "E")[0]


def test_a_valid_third_party_term_never_downgrades_a_governed_result():
    obj = entity(ontology_types=[governed_term(), THIRD_PARTY_TERM])
    assert verdicts(obj)["E"] == PASS
    assert any(UNASSESSED_THIRD_PARTY_TERM in note for note in findings(obj, "E"))


def test_e_fails_a_malformed_governed_identifier():
    obj = entity(ontology_types=["tag:synapsecommand.com,2026-09-06:ontology:Core:lowercase"])
    assert verdicts(obj)["E"] == FAIL


def test_e_fails_a_malformed_third_party_identifier_rather_than_calling_it_unassessed():
    """SA.1 §39: preserving a malformed string as valid third-party semantics hides a defect."""
    obj = entity(ontology_types=["not-absolute"])
    assert verdicts(obj)["E"] == FAIL
    assert UNASSESSED_THIRD_PARTY_TERM not in "".join(findings(obj, "E"))


def test_e_reports_duplicates_and_neither_deduplicates_nor_transforms_them_away():
    term = governed_term()
    obj = entity(ontology_types=[term, term])
    assert "duplicated" in detail(obj, "E")
    assert any("appears 2 times" in note for note in findings(obj, "E"))


def test_e_reads_sc_oes_entity_relation_predicates():
    block = oes_block(entity_relations=[{"entity_id": ENTITY_ID, "predicate": governed_term()}])
    obj = event(oes=block, related_entities=[ENTITY_ID])
    assert verdicts(obj)["E"] == PASS
    assert "1 governed" in detail(obj, "E")


def test_e_names_the_path_an_offending_predicate_was_found_at():
    unminted = "tag:synapsecommand.com,2026-09-06:ontology:core:NeverMinted"
    block = oes_block(entity_relations=[{"entity_id": ENTITY_ID, "predicate": unminted}])
    obj = event(oes=block, related_entities=[ENTITY_ID])
    assert verdicts(obj)["E"] == FAIL
    assert findings(obj, "E")[0].startswith("oes.entity_relations[0].predicate:")


def test_e_does_not_scan_payload_attributes_or_extensions_for_things_that_look_like_terms():
    """13-conformance.md: a dimension that scanned open bags would be guessing at intent."""
    planted = "tag:synapsecommand.com,2026-09-06:ontology:core:NeverMinted"
    assert verdicts(event(payload={"frequency_band": "L1", "interference_type": "JAMMING",
                                   "term": planted}))["E"] == SKIP
    assert verdicts(entity(attributes={"term": planted}))["E"] == SKIP
    assert verdicts(event(oes=oes_block(extensions={"x.acme.term": planted})))["E"] == SKIP


def test_e_never_dereferences_a_third_party_identifier():
    """No fetch, no DNS, no filesystem, no RDF load — asserted by removing the ability."""
    kind, why = conformance.classify_ontology_identifier("file:///etc/passwd")
    assert (kind, why) == ("third-party", UNASSESSED_THIRD_PARTY_TERM)


# ------------------------------------------------------------------ §40 exit behaviour


def test_a_run_with_nothing_failing_exits_zero():
    report = assess_document(event())
    assert exit_status(report) == EXIT_OK


def test_a_failed_dimension_exits_one():
    report = assess_document(event(oes=oes_block(type_id="sc.pnt.imaginary.v1")))
    assert exit_status(report) == EXIT_FAILED


def test_skip_does_not_fail_the_process_by_default():
    report = assess_document(event())
    assert report["objects"][0]["dimensions"]["D"]["verdict"] == SKIP
    assert exit_status(report) == EXIT_OK


def test_a_required_dimension_that_is_skip_makes_the_run_unsuccessful():
    report = assess_document(event(), required=("E",))
    assert exit_status(report, ("E",)) == EXIT_FAILED


def test_the_reported_verdict_is_not_rewritten_to_fail_to_make_the_exit_code_follow():
    """13-conformance.md, normative, and the one place the two layers could leak."""
    report = assess_document(event(), required=("E",))
    assert report["objects"][0]["dimensions"]["E"]["verdict"] == SKIP
    assert exit_status(report, ("E",)) == EXIT_FAILED


def test_require_scopes_the_exit_status_to_the_dimensions_the_caller_asked_about():
    """ADR 0009 alternative C: a dimension the caller did not ask about does not fail CI."""
    obj = event(oes=oes_block(type_id="sc.pnt.imaginary.v1"))  # C FAILs
    report = assess_document(obj, required=("A", "B"))
    assert report["objects"][0]["dimensions"]["C"]["verdict"] == FAIL
    assert exit_status(report, ("A", "B")) == EXIT_OK
    assert exit_status(report) == EXIT_FAILED


# ------------------------------------------------------------------ §41 output, and the CLI


def write(tmp_path, payload, name="objects.json"):
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return str(path)


def test_the_json_report_keys_dimensions_by_name_and_not_by_position(tmp_path, capsys):
    assert conformance.main(["--input", write(tmp_path, event()), "--json"]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    dimensions = report["objects"][0]["dimensions"]
    assert list(dimensions) == list(DIMENSION_KEYS)
    assert all(isinstance(v, dict) and "verdict" in v for v in dimensions.values())
    assert dimensions["A"]["name"] == "CDM Conformance"


def test_the_human_report_names_every_dimension_and_its_verdict(tmp_path, capsys):
    assert conformance.main(["--input", write(tmp_path, [event(), entity()])]) == EXIT_OK
    out = capsys.readouterr().out
    for d in DIMENSIONS:
        assert d.name in out
    assert "A conformance claim names the dimensions assessed" in out


# ---------------------------------------------- §66 the profile battery, at the process boundary
#
# Eight invocations, each one a row of §66's table. They are run through `main` rather than
# through `assess` because what they are about is the EXIT STATUS a CI system branches on, and
# the exit status is a different layer from the verdict — `13-conformance.md` keeps them apart
# and this is where both halves are read at once.


def _canonical(tmp_path):
    """The canonical PNT reference event, in a file, with a governed ontology identifier on it."""
    return write(tmp_path, event(related_entities=[ENTITY_ID],
                                 oes=oes_block(entity_relations=[
                                     {"entity_id": ENTITY_ID, "predicate": governed_term()}])),
                 name="pnt.json")


def _verdicts_from(capsys):
    return {k: v["verdict"]
            for k, v in json.loads(capsys.readouterr().out)["objects"][0]["dimensions"].items()}


def test_cli_valid_pnt_event_against_pnt_profile_passes_d(tmp_path, capsys):
    assert conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT",
                             "--json"]) == EXIT_OK
    assert _verdicts_from(capsys)["D"] == PASS


def test_cli_the_machine_readable_proof_carries_five_named_dimensions(tmp_path, capsys):
    """§43: the established shape, not a second JSON format written for the proof."""
    assert conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT", "--require",
                             "A,B,C,D,E", "--json"]) == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["profile"] == "PNT"
    assert report["profile_version"] == "0.1.0"
    dimensions = report["objects"][0]["dimensions"]
    assert list(dimensions) == ["A", "B", "C", "D", "E"]
    assert {k: v["verdict"] for k, v in dimensions.items()} == {k: PASS for k in "ABCDE"}


def test_cli_the_human_proof_states_the_permitted_pnt_claim(tmp_path, capsys):
    """§44's permitted language, and none of the words §80 forbids."""
    assert conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT",
                             "--require", "A,B,C,D,E"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "SC-OES PNT Profile 0.1 Conformant" in out
    assert "profile              PNT 0.1.0" in out
    for forbidden in ("Certified", "Approved", "Official", "NATO Certified", "NATO Approved"):
        assert forbidden not in out, forbidden


def test_cli_a_non_pnt_governed_event_against_pnt_fails_and_exits_one(tmp_path, capsys):
    obj = event(oes=oes_block(type_id="sc.c2.system_availability_changed.v1"))
    assert conformance.main(["--input", write(tmp_path, obj), "--profile", "PNT",
                             "--require", "D", "--json"]) == EXIT_FAILED
    assert _verdicts_from(capsys)["D"] == FAIL


def test_cli_a_specification_only_profile_skips_and_a_required_d_is_unsuccessful(
        tmp_path, capsys):
    """§36 and §41's second half: SKIP is honest, and requiring it is still unsuccessful."""
    path = _canonical(tmp_path)
    assert conformance.main(["--input", path, "--profile", "Air", "--json"]) == EXIT_OK
    assert _verdicts_from(capsys)["D"] == SKIP
    assert conformance.main(["--input", path, "--profile", "Air", "--require", "D",
                             "--json"]) == EXIT_FAILED
    assert _verdicts_from(capsys)["D"] == SKIP


def test_cli_no_profile_requested_skips_d(tmp_path, capsys):
    assert conformance.main(["--input", _canonical(tmp_path), "--json"]) == EXIT_OK
    assert _verdicts_from(capsys)["D"] == SKIP


def test_cli_an_unknown_profile_is_a_configuration_error_and_not_a_finding(tmp_path):
    """§37/§95: exit 2, and no report — a report would claim an assessment happened."""
    with pytest.raises(SystemExit) as raised:
        conformance.main(["--input", _canonical(tmp_path), "--profile", "UnknownProfile"])
    assert raised.value.code == EXIT_USAGE


def test_cli_an_unsupported_profile_version_does_not_fall_back(tmp_path):
    """§23. The refusal is the point: a caller asking for rules this package does not carry is
    told so, rather than handed the rules it does carry under the number it asked for."""
    with pytest.raises(SystemExit) as raised:
        conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT",
                          "--profile-version", "0.2.0"])
    assert raised.value.code == EXIT_USAGE
    with pytest.raises(SystemExit) as raised:
        conformance.main(["--input", _canonical(tmp_path), "--profile-version", "0.1.0"])
    assert raised.value.code == EXIT_USAGE


def test_cli_the_supported_profile_version_is_accepted(tmp_path, capsys):
    assert conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT",
                             "--profile-version", "0.1.0", "--require", "A,B,C,D,E",
                             "--json"]) == EXIT_OK
    assert _verdicts_from(capsys)["D"] == PASS


def test_no_aggregate_verdict_appears_even_when_all_five_pass(tmp_path, capsys):
    """§67: five PASSes are still five facts. No overall, no score, no level."""
    conformance.main(["--input", _canonical(tmp_path), "--profile", "PNT", "--require",
                      "A,B,C,D,E"])
    human = capsys.readouterr().out.lower()
    for banned in ("overall", "score", "5/5", "gold", "grade", "percentage"):
        assert banned not in human.replace("no aggregate verdict, score, grade or percentage", ""), \
            banned


def test_the_output_uses_no_forbidden_claim(tmp_path, capsys):
    """00-conventions.md's forbidden list, over both renderings of the same report."""
    conformance.main(["--input", write(tmp_path, event()), "--profile", "PNT"])
    human = capsys.readouterr().out
    conformance.main(["--input", write(tmp_path, event()), "--profile", "PNT", "--json"])
    machine = capsys.readouterr().out
    for forbidden in ("SC-OES Certified", "Official SynapseCommand Partner",
                      "Approved by Decent Cybersecurity", "NATO Certified", "NATO Approved",
                      "NATO Standard"):
        assert forbidden not in human and forbidden not in machine


def test_list_dimensions_answers_before_an_input_is_required(capsys):
    assert conformance.main(["--list-dimensions"]) == EXIT_OK
    out = capsys.readouterr().out
    assert all(d.key in out and d.name in out for d in DIMENSIONS)
    assert conformance.main(["--list-dimensions", "--json"]) == EXIT_OK
    listing = json.loads(capsys.readouterr().out)
    assert listing["dimensions"] == {d.key: d.name for d in DIMENSIONS}
    assert set(listing["exit_codes"]) == {"0", "1", "2", "3"}


def test_the_cli_exits_one_on_a_failing_dimension(tmp_path, capsys):
    obj = event(oes=oes_block(type_id="sc.pnt.imaginary.v1"))
    assert conformance.main(["--input", write(tmp_path, obj)]) == EXIT_FAILED


def test_the_cli_exits_one_when_a_required_dimension_is_skip(tmp_path, capsys):
    assert conformance.main(["--input", write(tmp_path, event()), "--require", "E",
                             "--json"]) == EXIT_FAILED
    report = json.loads(capsys.readouterr().out)
    assert report["objects"][0]["dimensions"]["E"]["verdict"] == SKIP
    assert report["required"] == ["E"]


def test_a_missing_input_file_is_a_usage_error(tmp_path):
    assert conformance.main(["--input", str(tmp_path / "absent.json")]) == EXIT_USAGE


def test_a_file_that_is_not_json_is_a_usage_error_and_not_a_conformance_finding(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json")
    assert conformance.main(["--input", str(path)]) == EXIT_USAGE


def test_a_document_that_is_neither_an_object_nor_a_list_is_a_usage_error(tmp_path):
    assert conformance.main(["--input", write(tmp_path, "a string")]) == EXIT_USAGE


def test_an_unknown_profile_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        conformance.main(["--input", write(tmp_path, event()), "--profile", "Maritime"])
    assert exit_info.value.code == EXIT_USAGE


def test_an_unknown_required_dimension_is_a_usage_error(tmp_path):
    with pytest.raises(SystemExit) as exit_info:
        conformance.main(["--input", write(tmp_path, event()), "--require", "A,Z"])
    assert exit_info.value.code == EXIT_USAGE


def test_a_missing_input_argument_is_a_usage_error():
    with pytest.raises(SystemExit) as exit_info:
        conformance.main([])
    assert exit_info.value.code == EXIT_USAGE


def test_an_internal_failure_exits_three_and_prints_no_report(tmp_path, capsys, monkeypatch):
    """§40's fourth code, distinct so that CI can tell a broken tool from a failed object."""
    def explode(*args, **kwargs):
        raise RuntimeError("the assessment blew up")
    monkeypatch.setattr(conformance, "assess_document", explode)
    assert conformance.main(["--input", write(tmp_path, event())]) == EXIT_INTERNAL
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "did not complete" in captured.err


def test_the_module_runs_as_a_command(tmp_path):
    """The console entry point's own path: `python -m synapse_cdm.conformance`."""
    result = subprocess.run([sys.executable, "-m", "synapse_cdm.conformance",
                             "--input", write(tmp_path, event())],
                            capture_output=True, text=True, cwd=str(tmp_path))
    assert result.returncode == EXIT_OK, result.stderr
    assert "SC-OES Semantic Type Conformance" in result.stdout


def test_stdin_is_readable_as_the_input(tmp_path):
    result = subprocess.run([sys.executable, "-m", "synapse_cdm.conformance", "--input", "-"],
                            input=json.dumps(event()), capture_output=True, text=True,
                            cwd=str(tmp_path))
    assert result.returncode == EXIT_OK, result.stderr


# ------------------------------------------------------------------ §125 offline


#: Roots no module in the conformance path may reach for. The network ones are §125's; the rest
#: are §143's list, which this closure is a second place to enforce because the tool is the thing
#: a consumer runs against untrusted content.
FORBIDDEN_ROOTS = {
    "socket", "ssl", "http", "urllib", "urllib2", "urllib3", "requests", "httpx", "aiohttp",
    "ftplib", "smtplib", "telnetlib", "webbrowser", "xmlrpc", "asyncio",
    "rdflib", "owlrl", "neo4j", "networkx", "kafka", "pika", "redis",
    "openai", "anthropic", "langchain", "llama_index", "transformers",
    "cryptography", "hashlib", "hmac", "nacl", "oqs", "secrets",
}


#: The one reach into `FORBIDDEN_ROOTS` this closure tolerates, and it is a (root, module) PAIR
#: rather than a root — M's ruling of 2026-09-08, the same allowance
#: `tests/test_cdm_boundary.py`'s `CRYPTO_ALLOWANCE` carries and scoped the same way.
#:
#: `synapse_cdm/evidence.py` imports `hashlib` to digest fixture files for an evidence record.
#: The conformance path reaches it because `conformance.py` imports `schemas.generate`, and
#: `schemas.evidence_schema()` needs the record's model to publish its shape. It is a REACH and
#: not a use: no code on the conformance path calls a digest, and §125's offline behaviour test
#: below is unaffected either way. It is recorded here rather than dropped from
#: `FORBIDDEN_ROOTS`, because deleting `hashlib` from that set would stop this gate noticing the
#: day some other module on this path started hashing.
CLOSURE_ALLOWANCE: set[tuple[str, str]] = {("hashlib", "evidence")}


def _closure(module_name: str, *, by_module: bool = False):
    """Every module the named package module reaches, by AST, without importing anything.

    AST rather than `sys.modules`, on the same reasoning `test_cdm_boundary.py` uses: importing
    the module to measure its imports would measure the whole package, because importing any
    submodule runs `synapse_cdm/__init__.py` first. What is being asserted here is what the
    conformance PATH reaches, which is a property of the source.

    `by_module=True` returns `{(outside root, the package module that imports it)}` instead of
    the bare set. The pair is what makes a NAMED allowance possible: "nothing reaches hashlib"
    and "only the evidence module reaches hashlib" are different gates, and the second one still
    fails the day a second module reaches it.
    """
    import ast
    import pathlib
    package = pathlib.Path(synapse_cdm.__file__).resolve().parent
    seen: set[str] = set()
    outside: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    queue = [module_name]
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        path = package / f"{name.replace('.', '/')}.py"
        if not path.exists():
            path = package / name.replace(".", "/") / "__init__.py"
        if not path.exists():
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                targets = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                targets = [node.module]
            else:
                continue
            for target in targets:
                if target == "synapse_cdm" or target.startswith("synapse_cdm."):
                    queue.append(target[len("synapse_cdm."):] or "__init__")
                else:
                    outside.add(target.split(".")[0])
                    pairs.add((target.split(".")[0], name))
    return pairs if by_module else outside


def test_the_conformance_import_closure_reaches_nothing_that_could_go_out_to_a_network():
    pairs = _closure("conformance", by_module=True)
    assert pairs, "the closure walk found nothing, so its PASS would mean nothing"
    offending = {pair for pair in pairs
                 if pair[0] in FORBIDDEN_ROOTS} - CLOSURE_ALLOWANCE
    assert not offending, sorted(offending)


def test_the_one_allowed_reach_is_still_exactly_one_and_is_still_there():
    """The allowance's shape, asserted — an exemption list is one edit from being a hole.

    Both directions. If the pair disappears (the evidence module stops hashing, or stops being
    reachable) the allowance is guarding nothing and should go; if it grows, a second module has
    started reaching for a forbidden root and that is a decision for a person.
    """
    assert CLOSURE_ALLOWANCE == {("hashlib", "evidence")}, (
        f"the closure allowance now covers {sorted(CLOSURE_ALLOWANCE)}. M's ruling of "
        "2026-09-08 permits SHA-256 content digests in ONE module and nothing else"
    )
    assert ("hashlib", "evidence") in _closure("conformance", by_module=True), (
        "the evidence module no longer reaches hashlib from the conformance path, so this "
        "allowance is a standing exception for something that is not happening"
    )


def test_the_closure_walk_would_catch_a_forbidden_import():
    """A negative test that cannot fail is worse than none — so this one proves it can."""
    assert _closure("harness") & {"jsonschema"}, "the walk does not see third-party imports"
    assert FORBIDDEN_ROOTS & {"socket"}
    # And the allowance is a PAIR: the same root reached from any other module is still caught.
    assert ("hashlib", "harness") not in CLOSURE_ALLOWANCE


def test_a_full_assessment_completes_with_the_network_removed(monkeypatch, tmp_path, capsys):
    """§125 proved on the behaviour, not only on the closure."""
    def refuse(*args, **kwargs):
        raise AssertionError("the conformance path opened a socket")
    monkeypatch.setattr(socket, "socket", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    document = [event(), entity(ontology_types=[governed_term(), THIRD_PARTY_TERM])]
    report = assess_document(document, profile="PNT")
    assert [r["dimensions"]["A"]["verdict"] for r in report["objects"]] == [PASS, PASS]
    assert conformance.main(["--input", write(tmp_path, document), "--profile", "PNT"]) == EXIT_OK
    capsys.readouterr()


def test_both_registries_are_read_from_the_packaged_resources(tmp_path):
    """No repository checkout: the assessment runs with the process outside the tree."""
    result = subprocess.run(
        [sys.executable, "-c",
         "import json, sys; from synapse_cdm.conformance import assess_document; "
         "print(json.dumps(assess_document(json.load(sys.stdin))['summary']))"],
        input=json.dumps(event()), capture_output=True, text=True, cwd=str(tmp_path))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["C"][PASS] == 1


# ------------------------------------------------------------------ the public surface


def test_the_conformance_names_are_reached_through_the_module_like_the_harness_names():
    """`conformance` is the third runnable-as-a-command module, and it keeps their standing.

    None of the eight names is in `synapse_cdm.__all__`, deliberately: a module the package
    `__init__` imports cannot be run cleanly with `python -m`, which the next test proves. The
    names are public on the module, exactly as `harness.run` and `schemas.generate` are.
    """
    for name in ("DIMENSIONS", "UNASSESSED_THIRD_PARTY_TERM", "Dimension", "Verdict", "assess",
                 "assess_document", "classify_ontology_identifier", "exit_status",
                 "render_report"):
        assert hasattr(conformance, name)
        assert name not in synapse_cdm.__all__
    assert callable(conformance.render_report) and callable(harness.render_report)


def test_none_of_the_three_command_modules_is_imported_by_the_package_init():
    """The property the withdrawal above defends, asserted where it can fail.

    A name added to `__all__` for one of these three drags its module into `__init__`'s import,
    and `runpy` then warns on every `python -m` invocation of it — a warning on a documented
    command, printed to a caller who did nothing wrong.
    """
    import ast
    import pathlib
    init = pathlib.Path(synapse_cdm.__file__).resolve()
    tree = ast.parse(init.read_text(), filename=str(init))
    imported = {node.module for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module}
    for module in ("synapse_cdm.conformance", "synapse_cdm.harness", "synapse_cdm.schemas"):
        assert module not in imported, f"{module} is imported by __init__.py; python -m warns"


@pytest.mark.parametrize("module", ["synapse_cdm.conformance", "synapse_cdm.harness",
                                    "synapse_cdm.schemas"])
def test_running_a_command_module_prints_no_runtime_warning(tmp_path, module):
    """The behaviour the previous test guards structurally, measured on the real invocation."""
    flag = {"synapse_cdm.conformance": ["--list-dimensions"],
            "synapse_cdm.harness": ["--list-adapters"],
            "synapse_cdm.schemas": ["--check", "--out", str(tmp_path / "schemas")]}[module]
    result = subprocess.run([sys.executable, "-m", module, *flag],
                            capture_output=True, text=True, cwd=str(tmp_path))
    assert "RuntimeWarning" not in result.stderr, result.stderr


def test_a_document_of_many_objects_is_assessed_object_by_object():
    document = [event(), entity(), event(oes=oes_block(type_id="sc.pnt.imaginary.v1"))]
    report = assess_document(document)
    assert len(report["objects"]) == len(document)
    assert report["summary"]["C"][FAIL] == 1
    assert report["summary"]["C"][PASS] == 1
    assert report["summary"]["C"][SKIP] == 1


def test_the_report_names_the_versions_it_assessed_against():
    report = assess_document(event())
    assert report["cdm_schema_version"] == SCHEMA_VERSION
    assert report["sc_oes_version"] == SC_OES_VERSION
    assert report["package_version"] == synapse_cdm.version.PACKAGE_VERSION


def test_assessing_the_same_object_twice_gives_the_same_report():
    obj = event()
    assert assess(copy.deepcopy(obj)) == assess(copy.deepcopy(obj))
