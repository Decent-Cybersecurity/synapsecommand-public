"""The packaged profile registry: §46's checks, and §47's cross-registry integrity.

`registry/sc_oes/profiles.json` is the third machine-readable artefact ADR 0004's lineage puts in
that directory, and it arrived on 2026-09-07 because dimension D became executable. Its whole job
is to let an offline validator answer three questions with no repository checkout — does this
profile exist, does it have rules a tool can run, and is this event in it — so the checks here are
written against the INSTALLED artefacts and this module is PACKAGE-ONLY (`gates/wheel_install.py`)
on `test_cdm_registry.py`'s reading exactly.

WHERE THE OTHER HALF LIVES
--------------------------
The seven normative profile DOCUMENTS are at the repository root and do not ship, so the check
that a document and this registry agree about a profile's version, maturity, implementation
status and membership is `tests/test_cdm_profiles.py`, which is repository-bound. The split is
the same one `test_cdm_registry.py` / `test_cdm_ontology.py` already draws: a check against the
artefacts travels with them, a check against the authority stays where the authority is.

MEMBERSHIP IS NOT CHECKED TWICE, IT IS CHECKED ONCE AND ASSERTED HERE
----------------------------------------------------------------------
`ProfileRegistry` refuses at load a `profiles.json` whose event-type lists disagree with
`event_types.json`, so drift between them cannot survive an import. That is deliberate and it is
what §17's "do not create two independently drifting lists of event types" asks for. The tests
below assert the refusal HAPPENS — a validator nobody proves is a validator that can be deleted by
accident — rather than re-deriving the agreement a second time and calling that a check.
"""
import importlib.resources
import json

import pytest
from pydantic import ValidationError

from synapse_cdm.oes import SEMVER_RE, is_governed_event_type
from synapse_cdm.oes_registry import (
    PROFILES,
    ImplementationStatus,
    Maturity,
    ProfileRecord,
    ProfileRegistry,
    get_event_type,
    get_ontology_term,
    get_profile,
    get_profile_event_types,
    list_event_types,
    list_profiles,
    profile_has_executable_rules,
)

#: §12/§20. The one profile with executable rules in v0.1.0, its version, and its whole scope.
#: Written down here rather than derived, because this is the module that says what the registry
#: is supposed to contain — a check that read its expectation out of the file it is checking
#: would pass on any file.
EXECUTABLE_PROFILE = "PNT"
EXECUTABLE_PROFILE_VERSION = "0.1.0"
EXECUTABLE_PROFILE_SCOPE = ("sc.pnt.gnss_interference.v1",)
EXECUTABLE_RULES = ("event_type_membership_required",)


def raw() -> dict:
    """`profiles.json` as bytes-on-disk, reached the way a consumer's install reaches it."""
    root = importlib.resources.files("synapse_cdm") / "registry" / "sc_oes"
    return json.loads((root / "profiles.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ §15 — it is where it ships


def test_the_artefact_is_readable_from_the_installed_package_with_importlib_resources():
    """§15: no repository checkout, no network, no remote profile service. Just the package."""
    document = raw()
    assert document["artefact"] == "sc-oes-profiles"
    assert [p["id"] for p in document["profiles"]] == list(PROFILES)


def test_the_helpers_answer_without_a_caller_ever_naming_a_path():
    """§45: a consumer asks a question. It does not open `profiles.json`."""
    assert [record.id for record in list_profiles()] == list(PROFILES)
    assert get_profile(EXECUTABLE_PROFILE).id == EXECUTABLE_PROFILE
    assert profile_has_executable_rules(EXECUTABLE_PROFILE) is True
    assert [entry.id for entry in get_profile_event_types(EXECUTABLE_PROFILE)] == \
        list(EXECUTABLE_PROFILE_SCOPE)


def test_an_unknown_profile_raises_rather_than_answering_emptily():
    """An empty answer would read as "that profile governs nothing", which is true of none."""
    with pytest.raises(KeyError):
        get_profile("UnknownProfile")
    with pytest.raises(KeyError):
        profile_has_executable_rules("UnknownProfile")


# ------------------------------------------------------------------ §46 — artefact validation


def test_profile_ids_are_unique():
    listed = [record.id for record in list_profiles()]
    assert len(set(listed)) == len(listed) == 7


def test_every_profile_version_is_a_semantic_version():
    for record in list_profiles():
        assert SEMVER_RE.fullmatch(record.version), (record.id, record.version)


def test_every_implementation_status_is_one_the_vocabulary_knows():
    for record in list_profiles():
        assert record.implementation_status in set(ImplementationStatus)
        assert record.maturity in set(Maturity)


def test_no_status_value_is_a_certification_word():
    """§13: `CERTIFIED`, `APPROVED` and `OFFICIAL` are forbidden, and a status enum is where one
    would arrive by accident."""
    for value in (status.value for status in ImplementationStatus):
        for forbidden in ("CERTIFIED", "APPROVED", "OFFICIAL"):
            assert forbidden not in value.upper(), value


def test_the_executable_profile_exists_with_the_version_status_scope_and_rules_it_should_have():
    """§46's five PNT rows, read off the packaged record in one place."""
    record = get_profile(EXECUTABLE_PROFILE)
    assert record.version == EXECUTABLE_PROFILE_VERSION
    assert record.implementation_status is ImplementationStatus.PRODUCER_BACKED
    assert tuple(record.event_types) == EXECUTABLE_PROFILE_SCOPE
    assert record.rules == EXECUTABLE_RULES


def test_the_other_six_exist_and_are_specification_only_and_claim_no_rules():
    """§19 and §46: known-but-unexecutable is a state the registry can express, and does."""
    others = [record for record in list_profiles() if record.id != EXECUTABLE_PROFILE]
    assert len(others) == 6
    for record in others:
        assert record.implementation_status is ImplementationStatus.SPECIFICATION_ONLY
        assert record.rules == ()
        assert profile_has_executable_rules(record.id) is False


def test_exactly_one_profile_has_executable_rules_in_v0_1_0():
    """§12. Not asserted as a count: the NAME is what the other checks are written against."""
    assert [r.id for r in list_profiles() if r.rules] == [EXECUTABLE_PROFILE]


def test_every_listed_event_type_is_one_the_event_registry_carries():
    for record in list_profiles():
        for type_id in record.event_types:
            assert is_governed_event_type(type_id), (record.id, type_id)
            assert get_event_type(type_id) is not None, (record.id, type_id)


def test_every_event_types_declared_profile_agrees_with_the_profile_registry():
    """The other direction of the same fact, and the one a projection gets wrong."""
    for entry in list_event_types():
        assert entry.id in get_profile(entry.profile).event_types, entry.id


# ------------------------------------------------------------------ §47 — cross-registry integrity


def test_the_three_registries_agree_on_event_type_membership():
    """`event_types.json` declares the owner; `profiles.json` projects it. Both directions."""
    from_events: dict[str, set[str]] = {name: set() for name in PROFILES}
    for entry in list_event_types():
        from_events[entry.profile].add(entry.id)
    from_profiles = {record.id: set(record.event_types) for record in list_profiles()}
    assert from_events == from_profiles


def test_the_two_registries_agree_on_every_profile_version():
    """§48: a governed type records its owning profile's version, and so does the profile."""
    for entry in list_event_types():
        assert entry.profile_version == get_profile(entry.profile).version, entry.id


def test_every_governed_types_ontology_class_is_a_term_the_ontology_minted():
    """The third artefact. A profile whose types name a class nothing minted is a broken chain."""
    for record in list_profiles():
        for type_id in record.event_types:
            entry = get_event_type(type_id)
            assert get_ontology_term(entry.ontology_class) is not None, (type_id,
                                                                         entry.ontology_class)


def test_the_registries_agree_on_the_sc_oes_version_they_were_authored_against():
    root = importlib.resources.files("synapse_cdm") / "registry" / "sc_oes"
    versions = {name: json.loads((root / name).read_text(encoding="utf-8")).get("sc_oes_version")
                for name in ("event_types.json", "profiles.json")}
    assert len(set(versions.values())) == 1, versions


# ------------------------------------------------ the refusals, asserted rather than assumed


def _document(**overrides) -> dict:
    document = raw()
    document.update(overrides)
    return document


def test_a_registry_that_omits_a_profile_is_refused():
    """§19: a validator that could not tell `Air` from a typo is the failure this prevents."""
    document = _document()
    document["profiles"] = [p for p in document["profiles"] if p["id"] != "Air"]
    with pytest.raises(ValidationError, match="requires every profile to be present"):
        ProfileRegistry.model_validate(document)


def test_a_membership_list_that_disagrees_with_the_event_registry_is_refused():
    """§17, at load. Two lists that can disagree are two lists; this makes them one."""
    document = _document()
    for profile in document["profiles"]:
        if profile["id"] == "ISR":
            profile["event_types"] = profile["event_types"] + ["sc.pnt.gnss_interference.v1"]
    with pytest.raises(ValidationError, match="is a projection of that one"):
        ProfileRegistry.model_validate(document)


def test_a_specification_only_profile_that_declares_a_rule_is_refused():
    """§34's fourth condition, made unaskable: the status and the rules are one fact."""
    with pytest.raises(ValidationError, match="held to them"):
        ProfileRecord.model_validate({
            "id": "Air", "version": "0.1.0", "maturity": "DRAFT",
            "implementation_status": "SPECIFICATION_ONLY",
            "event_types": [], "conformance_rules": {"event_type_membership_required": True}})


def test_a_producer_backed_profile_that_declares_no_rule_is_refused():
    with pytest.raises(ValidationError, match="can only ever SKIP"):
        ProfileRecord.model_validate({
            "id": "Air", "version": "0.1.0", "maturity": "DRAFT",
            "implementation_status": "PRODUCER_BACKED",
            "event_types": [], "conformance_rules": {}})


def test_a_rule_the_package_has_no_flag_for_is_refused():
    """`extra="forbid"` on the rules model: a profile cannot declare a rule with no check."""
    with pytest.raises(ValidationError):
        ProfileRecord.model_validate({
            "id": "Air", "version": "0.1.0", "maturity": "DRAFT",
            "implementation_status": "SPECIFICATION_ONLY",
            "event_types": [], "conformance_rules": {"geometry_required": True}})


def test_a_profile_the_specification_does_not_declare_is_refused():
    with pytest.raises(ValidationError, match="has no document"):
        ProfileRecord.model_validate({
            "id": "Maritime", "version": "0.1.0", "maturity": "DRAFT",
            "implementation_status": "SPECIFICATION_ONLY", "event_types": []})


def test_a_third_party_type_cannot_be_filed_under_a_profile():
    with pytest.raises(ValidationError, match="not this\n?\\s*repository's to file under one"):
        ProfileRecord.model_validate({
            "id": "Air", "version": "0.1.0", "maturity": "DRAFT",
            "implementation_status": "SPECIFICATION_ONLY",
            "event_types": ["x.acme.thing.v1"]})
