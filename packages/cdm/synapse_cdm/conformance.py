"""SC-OES conformance in five separately reportable dimensions, and the CLI that reports them.

WHAT THIS MODULE IS
-------------------
`docs/adr/0009-conformance-model.md` and `spec/sc-oes/13-conformance.md` fix the model: five
dimensions — A CDM, B SC-OES core syntax, C SC-OES semantic type, D SC-OES profile, E ontology —
each with its own verdict drawn from `PASS` / `FAIL` / `SKIP`, no aggregate score, four exit codes
and a mechanism for the caller to name the dimensions it requires. This module assesses a CDM
document against all five and renders the result for a person and for a machine.

`SKIP` IS NOT `PASS`, AND IT IS THE LOAD-BEARING RULE
-----------------------------------------------------
`harness.py` states the repository's own version of it: "An unrun check that reads as passed is how
a capability nobody tested acquires a green tick." `SKIP` here means *this was not assessed* —
because the caller did not ask for it, or because the object carries nothing to assess, or because
this repository does not govern the contract the object claims. It is never rendered, exported or
counted as a pass, and no aggregate verdict is produced anywhere in either output.

WHY DIMENSION A IS ASSESSED WITH THE `oes` BLOCK REMOVED
--------------------------------------------------------
`13-conformance.md` is normative: "An event with no SC-OES block is assessable under A, and A's
verdict MUST NOT depend on the presence, absence or content of the SC-OES block." `Event.oes`
is part of the canonical model, so validating the whole object under A would make a malformed
`oes` block fail A *and* B — two findings for one defect, and A's verdict would depend on the
block's content, which the rule forbids. So A validates the object with `oes` removed, and B is
the only dimension that reads it. The removal happens only for `object_kind == "event"`, where
`oes` is a declared field: on any other kind `oes` is an undeclared key, refusing it is an
existing CDM invariant (`extra="forbid"`), and A is right to fail on it.

WHAT DIMENSION C CAN AND CANNOT COMPARE
----------------------------------------
§37 lists "ontology event class matches registry" among C's checks. The wire block carries no
ontology class of its own — `OesMetadata` has the thirteen fields §52 lists and an ontology class
is not among them — so there is no pair of values on the object to compare. What C checks is that
the claim the object makes resolves end to end: the governed type it names declares an ontology
class, and that class is a term the packaged ontology-term registry carries. A governed type whose
ontology class the ontology never minted is a broken semantic contract, and an object claiming it
is claiming something this repository cannot honour.

DIMENSION D IS EXECUTABLE FOR ONE PROFILE, AND `SKIP` FOR THE OTHER SIX
------------------------------------------------------------------------
**This section read "WHY DIMENSION D IS `SKIP` FOR EVERY PROFILE IN v0.1.0" until 2026-09-07, and
the reasoning it carried is why the change is a change and not a repair.** It said that a `PASS`
drawn from an empty rule set would be exactly the claim the profile documents said was not
available, manufactured out of the absence of anything to check — and it said `PROFILE_RULES`
below "is where a profile's rules land when it acquires some". PNT has acquired one. The round
that gave it that rule wrote the rule and the check together, which is what every profile
document promised would have to happen first.

So D now has three answers rather than one, and each is a different fact:

- **No profile requested** — `SKIP`. §38, unchanged: an implementation does not infer which
  profile a producer probably meant.
- **A profile with no executable rules requested** — `SKIP`, and this is the six
  specification-only profiles. Not `PASS`, which would grade an object against nothing; not
  `FAIL`, which would grade a profile for being deliberately unfinished (§36).
- **PNT requested** — assessed. `PASS` when the object is a member of the profile and every rule
  it declares holds; `FAIL` when a governed event outside the profile's scope is put to it.

The rules themselves are NOT written in this module. They are read from
`registry/sc_oes/profiles.json` through `oes_registry.get_profile`, because a rule set stated in
two places is a rule set that can disagree with itself; `PROFILE_RULES` below is that read, and
`PROFILE_RULE_CHECKS` is the table of checks the declared rules resolve to.

OFFLINE, AND ASSERTED RATHER THAN PROMISED (§125)
--------------------------------------------------
Nothing in the assessment path opens a socket, resolves a name or reads a path a caller did not
give it. Both registries are read from packaged resources through `importlib.resources`
(`oes_registry.py`), the schemas are generated from the models with no file, and a third-party
ontology identifier is classified by its syntax and never dereferenced.
`tests/test_cdm_conformance.py` asserts both halves: the import closure of this module by AST, and
a full assessment with `socket` disabled.

THE THREE VERDICT STRINGS ARE DECLARED HERE AND NOT IMPORTED FROM `harness.py`
------------------------------------------------------------------------------
They are the same three strings, deliberately, and `test_cdm_conformance.py` asserts they agree so
that the two spellings cannot drift. They are not imported because importing the fixture harness
would put the adapter registry, `jsonschema`'s validator construction for every adapter and all
fourteen adapter modules into the import closure of a tool whose offline property is asserted OVER
that closure — a dependency taken for three string constants, paid for in the one measurement this
module has to keep small.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import traceback
from typing import Any, NamedTuple

import jsonschema
from pydantic import ValidationError

from synapse_cdm.models import KINDS
from synapse_cdm.oes import (
    GOVERNED_ONTOLOGY_PREFIX,
    OesMetadata,
    is_governed_event_type,
    is_governed_ontology_term,
    validate_ontology_identifier,
    validate_type_id,
)
from synapse_cdm.oes_registry import (
    OES_PAYLOAD_MODELS,
    PROFILES,
    ImplementationStatus,
    ProfileRecord,
    get_event_type,
    get_ontology_term,
    get_profile,
    get_profile_event_types,
)
from synapse_cdm.schemas import generate
from synapse_cdm.version import PACKAGE_VERSION, SCHEMA_VERSION, SC_OES_VERSION, compatible

#: The three verdicts, §34's. Identical to `harness.PASS/FAIL/SKIP` by test rather than by import
#: — see the module docstring on why the import is the expensive spelling of the same fact.
PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"

#: The stable string §39 fixes for a third-party term in detailed output. It is part of this
#: report's consumer-visible surface, so moving it later is a consumer-visible change.
UNASSESSED_THIRD_PARTY_TERM = "UNASSESSED_THIRD_PARTY_TERM"

#: The field `Event` carries the SC-OES block in, named once so the removal A performs and the
#: read B performs cannot fall out of step.
OES_FIELD = "oes"


class Dimension(NamedTuple):
    """One reportable dimension: the key §41 tells consumers to key on, and its stable name."""
    key: str
    name: str


#: §34's five, in §34's order. Everything that says "five" derives it from this tuple — the count
#: appears nowhere as a literal, so a sixth dimension cannot arrive while the prose still says
#: five (ADR 0009 consequences).
DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("A", "CDM Conformance"),
    Dimension("B", "SC-OES Core Syntax Conformance"),
    Dimension("C", "SC-OES Semantic Type Conformance"),
    Dimension("D", "SC-OES Profile Conformance"),
    Dimension("E", "Ontology Conformance"),
)
DIMENSION_KEYS: tuple[str, ...] = tuple(d.key for d in DIMENSIONS)

#: §40's four, as module constants in the manner of `harness.EXIT_NO_FIXTURES` rather than
#: literals scattered through `main`. The first three spend what the harness already spends them
#: on, so a caller who knows one tool's codes is not surprised by the other's.
EXIT_OK = 0
#: A requested dimension FAILed, or a REQUIRED dimension came back `SKIP` (§40's "if a required
#: dimension is SKIP, the run is unsuccessful"). The reported verdict is NOT rewritten to `FAIL`
#: to make this follow from it — the two layers are kept apart, see `exit_status`.
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERNAL = 3

#: Fields on the EVENT itself, outside the `oes` block, that carry a governed ontology reference.
#: Empty in v0.1.0 and declared anyway: SA.1 §33 names four places dimension E may inspect, and
#: this is the one the wire contract does not yet populate. A later field lands here rather than
#: in E's body, so the "four places and no others" rule stays visible in one list.
EVENT_ONTOLOGY_REFERENCE_FIELDS: tuple[str, ...] = ()

#: SA.1 §33's fourth place: "any field a profile explicitly defines as an ontology-ID field".
#: Every profile is a stub in v0.1.0 and none defines one, so every tuple is empty — declared
#: rather than omitted so that the mechanism exists and a profile that acquires such a field
#: extends a table instead of editing E.
PROFILE_ONTOLOGY_ID_FIELDS: dict[str, tuple[str, ...]] = {name: () for name in PROFILES}

#: What each profile requires of an object, when it requires anything — READ FROM THE PACKAGED
#: PROFILE REGISTRY rather than written down here, so that the rules a profile declares and the
#: rules this tool checks are one fact. `PNT` declares one in v0.1.0; the other six declare none
#: and are `()`, which is the state §36 requires be reported as `SKIP`.
#:
#: The read happens at import, which is a deliberate choice and not an oversight: it is the same
#: packaged resource `assess_c` reaches for on every governed type, it opens no socket and needs
#: no checkout (§125), and a registry that cannot be loaded is a defect a consumer should meet
#: when it imports the tool rather than three hundred objects into a run.
PROFILE_RULES: dict[str, tuple[str, ...]] = {name: get_profile(name).rules for name in PROFILES}


class Verdict(NamedTuple):
    """One dimension's answer about one object: the verdict, why, and what it found.

    `detail` is the one-line reason the verdict is what it is and is present on every verdict,
    including `PASS` — a report in which only failures explain themselves cannot be read to find
    out what was NOT assessed, which is the question five dimensions exist to answer.
    """
    verdict: str
    detail: str
    findings: tuple[str, ...] = ()


#: One validator per canonical kind, built on first use. See `_validator`.
_VALIDATORS: dict[str, Any] = {}


def _validator(kind: str) -> Any:
    """The published schema for one canonical kind, as a validator.

    Generated from the models rather than read from `schemas/`: §125 requires the assessment to
    work with no repository checkout, and the exported directory is a publication of these same
    models (`schemas.py`). Cached per kind on the module rather than per call — `generate()`
    walks every model and every payload, and an assessment over a document of five hundred
    objects would otherwise pay for it five hundred times.
    """
    if kind not in _VALIDATORS:
        _VALIDATORS[kind] = jsonschema.Draft202012Validator(generate()[kind])
    return _VALIDATORS[kind]


def _errors(exc: ValidationError, prefix: str) -> list[str]:
    out = []
    for err in exc.errors():
        where = "/".join(str(p) for p in err["loc"]) or "(root)"
        out.append(f"{prefix}: {where}: {err['msg']}")
    return out


def _identifier(obj: Any) -> str:
    """What to call this object in the report: its own id if it has one, else its kind."""
    if not isinstance(obj, dict):
        return "(not an object)"
    for key in ("event_id", "entity_id", "track_id", "object_id"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    ids = obj.get("source_ids")
    if isinstance(ids, list) and ids and isinstance(ids[0], dict):
        external = ids[0].get("external_id")
        if isinstance(external, str) and external:
            return external
    return str(obj.get("object_kind", "(unknown kind)"))


# ------------------------------------------------------------------ dimension A — CDM


def assess_a(obj: Any) -> Verdict:
    """Canonical model validity, required fields, schema version, schema validity, invariants.

    "No SC-OES-specific interpretation" (§35), which is why the `oes` block is removed from an
    event before anything here looks at it — the module docstring carries the reasoning.
    """
    if not isinstance(obj, dict):
        return Verdict(FAIL, "not a JSON object", (f"the document element is a "
                                                   f"{type(obj).__name__}, not an object",))
    kind = obj.get("object_kind")
    model = KINDS.get(kind) if isinstance(kind, str) else None
    if model is None:
        return Verdict(FAIL, "unknown object_kind",
                       (f"object_kind {kind!r} is not one of the canonical kinds "
                        f"{sorted(KINDS)}",))

    findings: list[str] = []
    written = obj.get("schema_version")
    if not isinstance(written, str) or not written:
        findings.append("schema_version: missing — an object that does not say which contract "
                        "it was written against cannot be checked against one")
    else:
        try:
            supported = compatible(written, SCHEMA_VERSION)
        except ValueError as e:
            findings.append(f"schema_version: {e}")
        else:
            if not supported:
                findings.append(
                    f"schema_version: {written} is not compatible with this package's CDM "
                    f"{SCHEMA_VERSION} — version.compatible() is False, the two are a major "
                    "apart, and MIGRATIONS.md states what a reader must do about it")

    candidate = {k: v for k, v in obj.items() if not (kind == "event" and k == OES_FIELD)}
    try:
        model.model_validate(candidate)
    except ValidationError as e:
        findings += _errors(e, "model")
    for error in sorted(_validator(kind).iter_errors(candidate), key=str):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        findings.append(f"schema: {where}: {error.message}")

    if findings:
        return Verdict(FAIL, f"{len(findings)} CDM finding(s)", tuple(findings))
    stripped = " (assessed with the oes block removed, per 13-conformance.md)" \
        if kind == "event" and OES_FIELD in obj else ""
    return Verdict(PASS, f"valid {kind} at CDM {written}{stripped}")


# ------------------------------------------------------------------ dimension B — core syntax


def _type_id_is_syntactic(block: Any) -> bool:
    """Does the block carry a `type_id` under one of the two frozen grammars?

    Answered separately from the model validation because C needs it: a `type_id` satisfying
    neither grammar is a syntax defect, so `B = FAIL` and `C = SKIP` and one character produces
    one finding (SA.1 §31, ADR 0009 decision 3).
    """
    if not isinstance(block, dict):
        return False
    raw = block.get("type_id")
    if not isinstance(raw, str):
        return False
    try:
        validate_type_id(raw)
    except ValueError:
        return False
    return True


def assess_b(obj: Any) -> Verdict:
    """The `oes` block's own structure and the two rules that need the event around it.

    §36's fourteen checks are the `OesMetadata` model's — structure, supported SC-OES version,
    EventClass, lifecycle, verification, confidence bounds, temporal ordering, type identifier
    syntax, relation structure, entity relation structure, evidence structure, security-marking
    structure, extension namespace, extension nesting bound. They are not restated here: the
    model is the normative shape and a second copy would be a second thing to keep correct.

    The two that the block cannot see are done below, because both need the EVENT: a relation
    pointing at the citing event, and an `entity_relations` subject missing from
    `related_entities`. `Event` carries them as validators, and dimension A no longer runs them
    because A no longer sees the block.

    "Supported SC-OES version" is the SHAPE of `spec_version` and not its value, deliberately.
    `OesMetadata._spec_version` rules it one level down: requiring equality with this package's
    `SC_OES_VERSION` "would refuse an event written against a later specification version — which
    12-versioning.md requires stay transportable". No document in this repository defines a
    supported-version RANGE, and inventing one here would refuse events the specification
    requires be carried. The claimed version is reported beside this implementation's instead.
    """
    if not isinstance(obj, dict):
        return Verdict(SKIP, "the element is not an object; dimension A reports it")
    kind = obj.get("object_kind")
    block = obj.get(OES_FIELD)
    if kind != "event":
        if block is None:
            return Verdict(SKIP, f"SC-OES metadata is carried on Event; this object is a "
                                 f"{kind!r}")
        return Verdict(SKIP, f"an oes key on a {kind!r} is an undeclared CDM field, which "
                             "dimension A reports; it is not assessed as an SC-OES block")
    if block is None:
        return Verdict(SKIP, "no SC-OES block: the producer made no SC-OES assertion, which is "
                             "not the producer asserting defaults")
    if not isinstance(block, dict):
        return Verdict(FAIL, "the oes block is not a JSON object",
                       (f"oes is a {type(block).__name__}",))

    findings: list[str] = []
    try:
        OesMetadata.model_validate(block)
    except ValidationError as e:
        findings += _errors(e, "oes")

    event_id = obj.get("event_id")
    relations = block.get("event_relations")
    if isinstance(relations, list):
        for index, relation in enumerate(relations):
            if isinstance(relation, dict) and relation.get("event_id") == event_id:
                findings.append(
                    f"oes: event_relations/{index}: points at the citing event {event_id} — an "
                    "event cannot stand in a relation to itself")
    related = obj.get("related_entities")
    related = set(related) if isinstance(related, list) else set()
    entity_relations = block.get("entity_relations")
    if isinstance(entity_relations, list):
        for index, relation in enumerate(entity_relations):
            if not isinstance(relation, dict):
                continue
            if relation.get("entity_id") not in related:
                findings.append(
                    f"oes: entity_relations/{index}: names entity "
                    f"{relation.get('entity_id')!r}, which is not in related_entities — a role "
                    "for an entity the event does not otherwise relate to would make the two "
                    "lists disagree about what the event concerns")

    if findings:
        return Verdict(FAIL, f"{len(findings)} SC-OES core syntax finding(s)", tuple(findings))
    claimed = block.get("spec_version")
    return Verdict(PASS, f"core syntax valid; the producer claims SC-OES {claimed}, this "
                         f"implementation carries {SC_OES_VERSION}")


# ------------------------------------------------------------------ dimension C — semantic type


def assess_c(obj: Any) -> Verdict:
    """The governed semantic contract the object's `type_id` names, checked against the registry.

    §37's five checks for a governed `sc.*` event, and §37's two `SKIP`s: a syntactically valid
    unknown `x.*` type is a third party's contract this repository does not govern, and a
    `type_id` that satisfies neither grammar was already reported by B.
    """
    if not isinstance(obj, dict) or obj.get("object_kind") != "event":
        return Verdict(SKIP, "semantic types are carried on Event")
    block = obj.get(OES_FIELD)
    if not isinstance(block, dict):
        return Verdict(SKIP, "no SC-OES block: no semantic type is claimed")
    if not _type_id_is_syntactic(block):
        return Verdict(SKIP, "semantic type not evaluated because core type identifier syntax "
                             "failed")
    type_id = block["type_id"]
    if not is_governed_event_type(type_id):
        return Verdict(SKIP, f"{type_id} is a third-party semantic type; this repository does "
                             "not govern that semantic contract")

    entry = get_event_type(type_id)
    if entry is None:
        return Verdict(FAIL, "unrecognised governed type",
                       (f"{type_id} is in the reserved sc. namespace and the packaged event "
                        "registry does not carry it: either a producer is minting governed "
                        "semantics it may not mint, or this consumer's registry is older than "
                        "the producer's. It is not interpreted either way",))

    findings: list[str] = []
    declared_class = block.get("event_class")
    if declared_class != entry.event_class.value:
        findings.append(f"event_class {declared_class!r} does not match the registry's "
                        f"{entry.event_class.value!r} for {type_id}")
    if get_ontology_term(entry.ontology_class) is None:
        findings.append(f"the registry declares ontology class {entry.ontology_class} for "
                        f"{type_id}, and the packaged ontology-term registry does not carry it")
    model = OES_PAYLOAD_MODELS.get(type_id)
    if model is not None:
        payload = obj.get("payload")
        try:
            model.model_validate(payload if isinstance(payload, dict) else {})
        except ValidationError as e:
            findings += _errors(e, f"payload ({entry.payload_model})")
    if entry.legacy_event_type is not None:
        legacy = obj.get("event_type")
        if legacy != entry.legacy_event_type.value:
            findings.append(
                f"event_type {legacy!r} does not match the legacy mapping "
                f"{entry.legacy_event_type.value!r} the registry governs for {type_id}")

    if findings:
        return Verdict(FAIL, f"{len(findings)} semantic type finding(s)", tuple(findings))
    return Verdict(PASS, f"{type_id} is governed, and its class, ontology class"
                         f"{', payload' if model is not None else ''} and legacy mapping agree "
                         "with the registry")


# ------------------------------------------------------------------ dimension D — profile


def assess_d(obj: Any, profile: str | None) -> Verdict:
    """Assessed only against a profile the caller named, and never inferred (§38).

    §34's six conditions for a `PASS`, in the order they are decided: the caller named a profile;
    the profile exists; it declares executable rules; its implementation status supports being
    evaluated; the object is a member of it; and every one of its executable requirements holds.
    The first four are questions about the PROFILE and are answered from the packaged registry;
    the last two are questions about the object.

    WHAT THIS DIMENSION DOES NOT REPORT
    ------------------------------------
    A, B, C or E as its own findings. An object with a malformed block fails B, and D says so by
    being unable to establish membership — it does not restate B's findings under its own letter.
    The registry's statement about which profile owns the object's type is REPORTED as an
    observation wherever D has no verdict of its own to give, where it informs without grading.
    """
    if profile is None:
        return Verdict(SKIP, "no profile requested; an implementation does not infer which "
                             "profile a producer probably meant")
    record = get_profile(profile)
    rules = record.rules
    if not rules:
        return Verdict(SKIP,
                       f"profile {profile} {record.version} is "
                       f"{record.implementation_status.value} and declares no executable "
                       f"conformance rules in SC-OES {SC_OES_VERSION} "
                       f"(spec/sc-oes/profiles/{profile.lower()}.md, 'Conformance'); "
                       f"{_profile_observation(obj, profile)}")
    if record.implementation_status is not ImplementationStatus.PRODUCER_BACKED:
        # Unreachable while the registry refuses the combination, and kept because §34's fourth
        # condition is a condition and not a consequence: a status that stopped supporting
        # evaluation must land here rather than in a PASS nobody re-read.
        return Verdict(SKIP,
                       f"profile {profile} {record.version} declares executable rules and its "
                       f"implementation status {record.implementation_status.value} does not "
                       "support conformance evaluation")

    if not isinstance(obj, dict) or obj.get("object_kind") != "event":
        return Verdict(SKIP, "profile conformance is assessed on Event; SC-OES metadata is "
                             "carried there and nowhere else")
    block = obj.get(OES_FIELD)
    if not isinstance(block, dict):
        # §38, and the sentence is the load-bearing half: a CDM event with no SC-OES block is a
        # legacy object, and manufacturing a block for it in order to have something to grade
        # would be this tool inventing the assertion it is here to check.
        return Verdict(SKIP,
                       f"no SC-OES block, so membership of profile {profile} {record.version} "
                       "cannot be established; SC-OES metadata is not manufactured in order to "
                       "assess it")

    findings: list[str] = []
    for rule in rules:
        finding = _profile_rule_holds(obj, record, rule)
        if finding is not None:
            findings.append(f"{profile}: {finding}")
    if findings:
        return Verdict(FAIL, f"{len(findings)} {profile} profile finding(s)", tuple(findings))
    # §44's permitted claim, stated only where it is true. `00-conventions.md` forbids the
    # certification words outright, and `13-conformance.md` requires a claim to name the
    # dimensions and their verdicts — which the table above this detail line is.
    return Verdict(PASS,
                   f"{profile} profile {record.version} rules hold ({len(rules)} checked: "
                   f"{', '.join(rules)}); the permitted claim \"SC-OES {profile} Profile "
                   f"{_claim_version(record.version)} Conformant\" is available for this object")


def _claim_version(version: str) -> str:
    """`0.1.0` -> `0.1`, the form §44 spells the permitted claim in. Nothing else uses it."""
    major, minor, _ = version.split(".")
    return f"{major}.{minor}"


def _event_type_is_a_member(obj: dict, record: ProfileRecord) -> str | None:
    """`event_type_membership_required`: the object's governed type is one the profile owns.

    The comparison is against the profile's OWN declared membership, not against the type's
    domain segment: `sc.pnt.…` looking like a PNT identifier is a naming convention, and a
    profile that graded on it would be inferring the very thing §38 forbids inferring.

    A `type_id` that is missing or not a string is B's finding and not this one — the rule can
    only say the object is not established as a member, which it does by naming what it found.
    """
    type_id = obj.get(OES_FIELD, {}).get("type_id")
    if type_id in record.event_types:
        return None
    if not isinstance(type_id, str) or not type_id:
        return ("the object claims no SC-OES semantic type, so it is not established as a member "
                f"of profile {record.id} {record.version}, whose scope is "
                f"{sorted(record.event_types)} (dimension B reports the block's own syntax)")
    return (f"event type {type_id} is not a member of the requested profile {record.id} "
            f"{record.version}, whose scope is {sorted(record.event_types)}")


#: `rule name -> the check that decides it`. The keys are `ProfileConformanceRules`' declared
#: flags, and `test_cdm_conformance.py` asserts the two sets are equal in both directions: a
#: profile cannot declare a rule with no check behind it, and a check cannot sit here unreachable
#: by any profile. Each entry returns the finding when the rule does NOT hold, and `None` when it
#: does.
PROFILE_RULE_CHECKS: dict[str, Any] = {
    "event_type_membership_required": _event_type_is_a_member,
}


def _profile_observation(obj: Any, profile: str) -> str:
    """What the REGISTRY says about this object's type and the named profile. Not a verdict."""
    block = obj.get(OES_FIELD) if isinstance(obj, dict) else None
    type_id = block.get("type_id") if isinstance(block, dict) else None
    if not isinstance(type_id, str):
        return "the object claims no SC-OES semantic type"
    owned = {entry.id for entry in get_profile_event_types(profile)}
    if type_id in owned:
        return f"observed: the registry declares {type_id} in this profile"
    if get_event_type(type_id) is None:
        return f"observed: {type_id} is not a governed type, so no profile declares it"
    return (f"observed: the registry declares {type_id} in profile "
            f"{get_event_type(type_id).profile}, not in {profile}")


def _profile_rule_holds(obj: dict, record: ProfileRecord, rule: str) -> str | None:
    """One declared rule against one object: `None` when it holds, the finding when it does not.

    The registry's `ProfileConformanceRules` is `extra="forbid"` and its declared flags are this
    table's keys, so a profile cannot name a rule that arrives here without a check — which is
    the arrangement every profile document promised: "the round that gives this profile its first
    rule of its own writes the rules and the check that enforces them together".
    """
    check = PROFILE_RULE_CHECKS.get(rule)
    if check is None:
        raise NotImplementedError(
            f"profile rule {rule!r} is declared in the packaged profile registry and has no "
            "check in PROFILE_RULE_CHECKS; the two are asserted equal by the test suite"
        )
    return check(obj, record)


# ------------------------------------------------------------------ dimension E — ontology


def _ontology_identifiers(obj: Any, profile: str | None) -> list[tuple[str, Any]]:
    """Every ontology identifier on the object, with the path it was found at.

    The four places SA.1 §33 permits and no others: `Entity.ontology_types`, SC-OES entity
    relation predicates, governed ontology references carried on the event, and any field a
    profile explicitly defines as an ontology-ID field. Arbitrary strings inside `payload`,
    `attributes` or `extensions` are NOT ontology identifiers and are not looked for there — a
    dimension that scanned open bags for things that look like identifiers would be inferring.

    Duplicates are returned as found. Nothing here deduplicates, sorts, trims or case-folds.
    """
    found: list[tuple[str, Any]] = []
    if not isinstance(obj, dict):
        return found
    if obj.get("object_kind") == "entity":
        types = obj.get("ontology_types")
        if isinstance(types, list):
            found += [(f"ontology_types[{i}]", t) for i, t in enumerate(types)]
    block = obj.get(OES_FIELD)
    if isinstance(block, dict):
        relations = block.get("entity_relations")
        if isinstance(relations, list):
            for index, relation in enumerate(relations):
                if isinstance(relation, dict) and "predicate" in relation:
                    found.append((f"oes.entity_relations[{index}].predicate",
                                  relation["predicate"]))
    for field in EVENT_ONTOLOGY_REFERENCE_FIELDS:
        if field in obj:
            found.append((field, obj[field]))
    if profile is not None:
        for field in PROFILE_ONTOLOGY_ID_FIELDS[profile]:
            if field in obj:
                found.append((f"{field} (profile {profile})", obj[field]))
    return found


def classify_ontology_identifier(term: Any) -> tuple[str, str]:
    """One identifier's class and the sentence that says why. Syntax and lookup only.

    The five classes are SA.1 §42's rows read one identifier at a time: `governed` (valid and
    carried by the packaged registry), `unknown-governed` (valid syntax, reserved family, no such
    term), `malformed-governed` (under the reserved prefix and not matching its grammar),
    `third-party` (a valid absolute identifier this repository does not govern) and
    `malformed-third-party`. Nothing is fetched, resolved, loaded or mapped.
    """
    if not isinstance(term, str):
        return "malformed-third-party", (f"not a string: a semantic identifier is a single "
                                         f"opaque token, got {type(term).__name__}")
    if is_governed_ontology_term(term):
        if get_ontology_term(term) is None:
            return "unknown-governed", ("in the reserved SynapseCommand ontology family and the "
                                        "packaged term registry does not carry it")
        return "governed", "governed term, recognised"
    if term.startswith(GOVERNED_ONTOLOGY_PREFIX):
        return "malformed-governed", ("claims the reserved SynapseCommand ontology namespace and "
                                      "does not match its grammar")
    try:
        validate_ontology_identifier(term)
    except ValueError as e:
        return "malformed-third-party", str(e)
    return "third-party", UNASSESSED_THIRD_PARTY_TERM


def assess_e(obj: Any, profile: str | None) -> Verdict:
    """SA.1 §42's normative truth table, evaluated over the identifiers actually present.

    Third-party-only is `SKIP` — neither `PASS` nor `FAIL` — because the terms are present and
    this repository governs none of them. A valid third-party term never downgrades a governed
    result. A malformed third-party identifier is `FAIL` and is not preserved as though it were
    valid third-party semantics.
    """
    identifiers = _ontology_identifiers(obj, profile)
    if not identifiers:
        return Verdict(SKIP, "no ontology identifiers present")

    findings: list[str] = []
    unassessed: list[str] = []
    governed = 0
    seen: dict[str, list[str]] = {}
    for path, term in identifiers:
        kind, why = classify_ontology_identifier(term)
        if isinstance(term, str):
            seen.setdefault(term, []).append(path)
        if kind == "governed":
            governed += 1
        elif kind == "third-party":
            unassessed.append(f"{path}: {term} — {UNASSESSED_THIRD_PARTY_TERM}")
        else:
            findings.append(f"{path}: {term!r} — {why}")

    # Reported, never silently deduplicated and never transformed away (SA.1 §40). Duplication is
    # not itself one of the truth table's rows, so it changes no verdict: it is stated beside the
    # terms, and the owning model's own refusal of it is dimension A's business.
    duplicates = [f"{term} appears {len(paths)} times: {', '.join(paths)}"
                  for term, paths in seen.items() if len(paths) > 1]

    detail_parts = [f"{len(identifiers)} identifier(s)"]
    if governed:
        detail_parts.append(f"{governed} governed")
    if unassessed:
        detail_parts.append(f"{len(unassessed)} {UNASSESSED_THIRD_PARTY_TERM}")
    if duplicates:
        detail_parts.append(f"{len(duplicates)} duplicated")
    detail = ", ".join(detail_parts)
    notes = tuple(unassessed) + tuple(duplicates)

    if findings:
        return Verdict(FAIL, detail, tuple(findings) + notes)
    if governed:
        return Verdict(PASS, detail, notes)
    return Verdict(SKIP, detail + " — present, and this repository governs none of them", notes)


# ------------------------------------------------------------------ the report


def assess(obj: Any, *, profile: str | None = None) -> dict:
    """One object, five verdicts, keyed by name (§41). No aggregate verdict is produced."""
    verdicts = {
        "A": assess_a(obj),
        "B": assess_b(obj),
        "C": assess_c(obj),
        "D": assess_d(obj, profile),
        "E": assess_e(obj, profile),
    }
    return {
        "object_kind": obj.get("object_kind") if isinstance(obj, dict) else None,
        "identifier": _identifier(obj),
        "dimensions": {
            key: {"name": name, "verdict": v.verdict, "detail": v.detail,
                  "findings": list(v.findings)}
            for (key, name), v in ((d, verdicts[d.key]) for d in DIMENSIONS)
        },
    }


def assess_document(payload: Any, *, profile: str | None = None,
                    required: tuple[str, ...] = ()) -> dict:
    """A whole document — one object or a list of them — as one report.

    The per-dimension counts are counts of verdicts, not a score: §34 forbids a single
    "compatibility score", and a caller that wants one composes it from the five and says so.
    """
    objects = payload if isinstance(payload, list) else [payload]
    results = [assess(obj, profile=profile) for obj in objects]
    summary = {
        d.key: {"name": d.name,
                **{verdict: sum(1 for r in results
                                if r["dimensions"][d.key]["verdict"] == verdict)
                   for verdict in (PASS, FAIL, SKIP)}}
        for d in DIMENSIONS
    }
    return {
        "tool": "synapse-cdm conformance",
        "package_version": PACKAGE_VERSION,
        "cdm_schema_version": SCHEMA_VERSION,
        "sc_oes_version": SC_OES_VERSION,
        "profile": profile,
        # The version dimension D actually assessed against, taken from the packaged registry
        # rather than from the caller. `null` when no profile was requested. It is reported
        # because a D verdict is a verdict against a PROFILE VERSION, and a record of one that
        # does not say which version was in force is a record of half the claim (§48).
        "profile_version": None if profile is None else get_profile(profile).version,
        "required": list(required),
        "objects": results,
        "summary": summary,
    }


def exit_status(report: dict, required: tuple[str, ...] = ()) -> int:
    """§40's process status, which is a different question from any dimension's verdict.

    `0` when the run completed and no requested dimension FAILed; `1` when one did, or when a
    dimension the caller REQUIRED came back `SKIP`. "Requested" means the dimensions named by
    `--require` when it is given, and all of them when it is not — a caller who scoped nothing
    asked about everything, and a caller who scoped `A,B` is not failed by a dimension it did
    not ask about (ADR 0009 alternative C).

    Nothing here rewrites a verdict. `--require E` against an object with no ontology
    identifiers makes the INVOCATION unsuccessful and the report still reads `E = SKIP`:
    collapsing the first into the second would put the caller's command line into the
    conformance record, and a later reader could not tell an object that failed E from one
    nobody could evaluate.
    """
    considered = required or DIMENSION_KEYS
    for result in report["objects"]:
        for key in considered:
            if result["dimensions"][key]["verdict"] == FAIL:
                return EXIT_FAILED
        for key in required:
            if result["dimensions"][key]["verdict"] == SKIP:
                return EXIT_FAILED
    return EXIT_OK


def render_report(report: dict) -> str:
    """The readable half of §41. The machine half is `--json`, and neither is derived from it."""
    results = report["objects"]
    width = max([len(r["identifier"]) for r in results] + [10])
    kind_width = max([len(str(r["object_kind"] or "-")) for r in results] + [4])
    required = report["required"] or ["(none)"]
    lines = [
        f"sc-oes conformance   synapse-cdm {report['package_version']}, CDM "
        f"{report['cdm_schema_version']}, SC-OES {report['sc_oes_version']}",
        f"profile              "
        f"{report['profile'] + ' ' + report['profile_version'] if report['profile'] else '(none requested)'}",
        f"required             {','.join(required)}",
        "",
        f"{'object'.ljust(width)}  {'kind'.ljust(kind_width)}  "
        + "  ".join(d.key.ljust(4) for d in DIMENSIONS),
        "-" * (width + 2 + kind_width + 2 + len(DIMENSIONS) * 6),
    ]
    for result in results:
        cells = "  ".join(result["dimensions"][d.key]["verdict"][:4].ljust(4) for d in DIMENSIONS)
        lines.append(f"{result['identifier'].ljust(width)}  "
                     f"{str(result['object_kind'] or '-').ljust(kind_width)}  {cells}")
    lines += ["", "dimensions"]
    for d in DIMENSIONS:
        counts = report["summary"][d.key]
        lines.append(f"  {d.key}  {d.name.ljust(34)} "
                     f"{counts[PASS]} {PASS}, {counts[FAIL]} {FAIL}, {counts[SKIP]} {SKIP}")
    lines += ["", "detail"]
    for result in results:
        lines.append(f"  {result['identifier']}")
        for d in DIMENSIONS:
            entry = result["dimensions"][d.key]
            lines.append(f"    {d.key} {entry['verdict'].ljust(4)}  {entry['detail']}")
            lines += [f"        - {finding}" for finding in entry["findings"]]
    lines += [
        "",
        # 13-conformance.md: "A conformance claim MUST name the dimensions assessed and the
        # verdict each returned." The table above IS that statement, and this line says so
        # rather than adding a summary the same document forbids.
        "A conformance claim names the dimensions assessed and the verdict each returned; the "
        "table above is that statement.",
        "No aggregate verdict, score, grade or percentage is produced, and SKIP is not PASS: it "
        "means this was not assessed.",
    ]
    return "\n".join(lines)


# ------------------------------------------------------------------ the CLI


def _required(value: str, parser: argparse.ArgumentParser) -> tuple[str, ...]:
    keys = tuple(part.strip() for part in value.split(",") if part.strip())
    unknown = [k for k in keys if k not in DIMENSION_KEYS]
    if unknown:
        parser.error(f"--require names {unknown}, which are not dimensions. The dimensions are "
                     f"{','.join(DIMENSION_KEYS)} (see --list-dimensions)")
    return keys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--input", type=pathlib.Path, default=None,
                        help="a JSON file holding one CDM object or a list of them. `-` reads "
                             "stdin")
    parser.add_argument("--profile", default=None, choices=PROFILES,
                        help="assess dimension D against this profile. Omitted, D is SKIP: an "
                             "implementation does not infer which profile a producer meant")
    parser.add_argument("--profile-version", default=None, metavar="X.Y.Z",
                        help="the profile version the caller means. Omitted, the packaged "
                             "registry's version for that profile is used and reported; given "
                             "and different, the invocation is refused rather than silently "
                             "assessed against the version this package happens to carry")
    parser.add_argument("--require", default=None, metavar="A,B,C",
                        help="dimensions the caller requires. A required dimension that FAILs "
                             "or SKIPs makes the invocation unsuccessful; the reported verdict "
                             "is never rewritten to make the exit code follow from it")
    parser.add_argument("--list-dimensions", action="store_true",
                        help="print the dimensions and the exit codes, and exit. Honours --json")
    parser.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = parser.parse_args(argv)

    if args.list_dimensions:
        # Answered before --input is required, on `harness --list-adapters`' reasoning: a caller
        # who does not know the names cannot be asked for one in order to be told them.
        if args.json:
            print(json.dumps({"dimensions": {d.key: d.name for d in DIMENSIONS},
                              "verdicts": [PASS, FAIL, SKIP],
                              "exit_codes": {"0": "no requested dimension FAILed",
                                             "1": "a requested dimension FAILed, or a required "
                                                  "dimension was SKIP",
                                             "2": "CLI / configuration / usage error",
                                             "3": "internal execution error"}}, indent=2))
        else:
            print("\n".join([f"{d.key}  {d.name}" for d in DIMENSIONS]
                            + ["", f"verdicts: {PASS} {FAIL} {SKIP} — {SKIP} is never {PASS}"]))
        return EXIT_OK

    required = _required(args.require, parser) if args.require else ()
    if args.profile_version is not None:
        # §23. A profile version is part of the request, so a request this package cannot serve
        # is a configuration error (exit 2) and never a quiet fall-back to the version installed:
        # a caller asking for rules that do not exist here must be told so, not handed the ones
        # that do.
        if args.profile is None:
            parser.error("--profile-version names a version and no --profile names the profile "
                         "it belongs to; a profile version is not a global setting")
        carried = get_profile(args.profile).version
        if args.profile_version != carried:
            parser.error(
                f"--profile-version {args.profile_version} is not the {args.profile} profile "
                f"version this package carries, which is {carried}. The request is refused "
                "rather than assessed against a different version of the profile's rules")
    if args.input is None:
        parser.error("--input is required (or --list-dimensions to see what is assessed)")

    try:
        text = sys.stdin.read() if str(args.input) == "-" else args.input.read_text()
    except OSError as e:
        print(f"conformance: {e}", file=sys.stderr)
        return EXIT_USAGE
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as e:
        # An invocation error, not a conformance finding: a file that is not JSON was never a
        # candidate CDM document, and reporting `A = FAIL` on it would put a parse failure in the
        # caller's file into the conformance record of an object that does not exist.
        print(f"conformance: {args.input} is not JSON: {e}", file=sys.stderr)
        return EXIT_USAGE
    if not isinstance(payload, (dict, list)):
        print(f"conformance: {args.input} holds a {type(payload).__name__}; a CDM document is "
              "one object or a list of them", file=sys.stderr)
        return EXIT_USAGE

    try:
        report = assess_document(payload, profile=args.profile, required=required)
        rendered = json.dumps(report, indent=2) if args.json else render_report(report)
        status = exit_status(report, required)
    except Exception:  # noqa: BLE001 — §40's code 3 is exactly this case, and it must be distinct
        traceback.print_exc()
        print("conformance: the run did not complete; no report is printed, because the shape of "
              "a report is a claim that objects were assessed", file=sys.stderr)
        return EXIT_INTERNAL
    print(rendered)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
