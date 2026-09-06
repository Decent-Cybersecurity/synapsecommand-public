"""The fourteen committed examples, loaded and validated — the gate that stops them rotting.

`spec/sc-oes/`'s §141 requirement is one sentence: "Every example committed to the repository must
be loaded and validated in CI. Documentation examples must not silently rot. The linked chain must
verify local reference consistency." This module is that CI. It is REPOSITORY-BOUND
(`gates/wheel_install.py`): `examples/` sits at the repository root, does not ship in the wheel,
and against an installed distribution this module would have nothing to open.

WHY THE FILES ARE COMPARED BYTE-FOR-BYTE AGAINST A RE-RENDER
------------------------------------------------------------
Validating a committed example proves it parses. It does not prove the file on disk is the object
the models produce — an example edited by hand into a shape pydantic happens to accept, with a key
order or an indent nothing else in this repository uses, still validates and still drifts away
from every other serialization here. So each file is re-rendered from its own validated objects
with the harness's own `json.dumps(..., indent=2, sort_keys=True)` and compared to the bytes on
disk. That makes the examples regenerable: any round may rebuild them and the diff is empty unless
a value changed.

WHAT IS DELIBERATELY NOT ASSERTED
---------------------------------
Nothing here checks that an example is *good* prose, that its payload fields are the right ones,
or that a profile would recommend them. Payload shapes are free-form for twelve of the thirteen
governed types by decision (`docs/adr/0007`), and a test that pinned them would be inventing the
schemas that decision deliberately withheld.
"""
import inspect
import json
import pathlib
import uuid

import pytest

import synapse_cdm
from synapse_cdm import adapter, ids
from synapse_cdm.conformance import FAIL, assess
from synapse_cdm.enums import EventType
from synapse_cdm.models import Entity, Event
from synapse_cdm.oes import EventClass, OesMetadata, find_relation_cycles
from synapse_cdm.oes_registry import get_event_type, list_event_types
from synapse_cdm.version import SC_OES_VERSION

REPO = pathlib.Path(synapse_cdm.__file__).resolve().parents[3]
EXAMPLES = REPO / "examples" / "sc-oes"
INDIVIDUAL = EXAMPLES / "individual"
CHAIN = EXAMPLES / "chain"
README = REPO / "examples" / "README.md"

#: The one source every example names. No adapter is registered under it, on purpose — see
#: `test_no_example_claims_a_provenance_it_does_not_have`.
SYSTEM = "SC-OES-EXAMPLES"
ADAPTER_NAME = "sc-oes-examples"

#: §130's rule, made checkable. Every external identifier any example uses, in one closed set,
#: checked in BOTH directions: an identifier not on this list fails, and a name on this list that
#: no example uses fails too. A prefix rule was tried first and is the wrong shape — it would have
#: admitted any string beginning `SYNTHETIC-`, which is the one part of a fabricated identifier
#: that costs nothing to add. A closed roster makes every new identifier a deliberate entry, which
#: is what "no real unit, mission, schedule, position, customer or infrastructure" needs to be.
#: The names themselves are the specification's own placeholder register (§130) plus the two
#: generated families for events (`SYNTHETIC-…`) and for the chain's own copies (`CHAIN-…`).
FICTIONAL_IDENTIFIERS = frozenset({
    # entities — the specification's placeholder register
    "AREA-ALPHA", "C2-NODE-ECHO", "INTERFERENCE-SOURCE-BRAVO", "MISSION-41", "ROUTE-CHARLIE",
    "ROUTE-DELTA", "RUNWAY-27", "SENSOR-DELTA", "SUPPLY-NODE-BRAVO", "UAV-17",
    # the chain's own entities, distinct so the chain is readable on its own
    "CHAIN-INTERFERENCE-SOURCE-BRAVO", "CHAIN-MISSION-41", "CHAIN-ROUTE-DELTA",
    # the thirteen individual examples' events, and one working record cited as evidence
    "SYNTHETIC-ACTION-001", "SYNTHETIC-AIRSPACE-001", "SYNTHETIC-AIR-TRACK-001",
    "SYNTHETIC-C2-001", "SYNTHETIC-DECISION-001", "SYNTHETIC-GNSS-001", "SYNTHETIC-IMPACT-001",
    "SYNTHETIC-MISSION-001", "SYNTHETIC-RECOMMENDATION-001", "SYNTHETIC-ROUTE-001",
    "SYNTHETIC-RWY-001", "SYNTHETIC-SUPPLY-001", "SYNTHETIC-THREAT-001",
    "SYNTHETIC-THREAT-001-WORKING",
    # the chain's six events
    "CHAIN-41-OBSERVATION", "CHAIN-41-ASSESSMENT", "CHAIN-41-IMPACT",
    "CHAIN-41-RECOMMENDATION", "CHAIN-41-DECISION", "CHAIN-41-ACTION",
})

#: The chain's six classes, in the order the specification draws them (§132).
CHAIN_CLASSES = (EventClass.OBSERVATION, EventClass.ASSESSMENT, EventClass.IMPACT,
                 EventClass.RECOMMENDATION, EventClass.DECISION, EventClass.ACTION)

#: The two legacy members no example may use. `docs/adr/0007-legacy-eventtype-mapping.md`
#: alternative F rejects pressing them into service: no adapter emits either, so nothing in this
#: tree establishes what they mean, and an example using one would DEFINE the member rather than
#: use it. The ADR declined to make that definition; an example must not make it by the back door.
UNESTABLISHED_LEGACY = (EventType.PLAN_INJECT, EventType.SIM_RESULT)


def _files() -> list[pathlib.Path]:
    return sorted(EXAMPLES.rglob("*.json"))


def _load(path: pathlib.Path) -> list:
    """The objects of one example file, validated into models."""
    return [(Entity if raw["object_kind"] == "entity" else Event).model_validate(raw)
            for raw in json.loads(path.read_text())]


ALL_FILES = _files()
EVENT_FILES = [p for p in ALL_FILES]


# --------------------------------------------------------------- 1. the corpus is what it claims


def test_the_sweep_found_the_examples_it_is_meant_to_judge():
    """A module whose glob matched nothing would pass every check below."""
    assert len(ALL_FILES) == 14, [str(p.relative_to(REPO)) for p in ALL_FILES]
    assert len(list(INDIVIDUAL.glob("*.json"))) == 13
    assert len(list(CHAIN.glob("*.json"))) == 1


def test_there_is_one_individual_example_per_governed_type_named_for_it():
    """§131, and the naming is what makes the closure checkable in both directions.

    Derived from the registry rather than from a list here: a fourteenth governed type lands as a
    missing file rather than as a passing test over the thirteen that already existed.
    """
    governed = {entry.id for entry in list_event_types()}
    on_disk = {path.stem for path in INDIVIDUAL.glob("*.json")}
    assert on_disk == governed, (
        f"missing: {sorted(governed - on_disk)}; unexpected: {sorted(on_disk - governed)}")


def test_nothing_but_the_examples_and_one_readme_lives_under_the_directory():
    stray = [str(p.relative_to(REPO)) for p in (REPO / "examples").rglob("*")
             if p.is_file() and p.suffix != ".json" and p != README]
    assert not stray, (
        f"{stray} are under examples/ and are neither an example nor its README. This directory "
        "is data and prose only — a Python file here would also have to join the version floor "
        "gate's closure (tests/test_cdm_version_floor.py)")


# ---------------------------------------------------------------------- 2. every example loads


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_example_validates_against_the_models(path):
    """§141's first clause. The failure a reader gets is pydantic's, naming field and file."""
    objects = _load(path)
    assert objects, f"{path.name} holds no objects"
    assert any(o.object_kind == "event" for o in objects), f"{path.name} carries no event"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_example_is_the_canonical_rendering_of_its_own_objects(path):
    """The bytes on disk are what the models produce — see this module's docstring."""
    rendered = json.dumps([o.model_dump(mode="json") for o in _load(path)],
                          indent=2, sort_keys=True) + "\n"
    assert path.read_text() == rendered, (
        f"{path.relative_to(REPO)} is not the canonical rendering of its own objects. Regenerate "
        "it rather than hand-editing: every other serialized object in this repository is written "
        "with indent=2 and sorted keys (synapse_cdm/harness.py)")


# -------------------------------------------------------------- 3. §130 — synthetic and fictional


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_object_declares_itself_synthetic(path):
    for obj in _load(path):
        assert obj.source.synthetic is True, f"{path.name}: {obj.source}"


def _external_identifiers() -> set[str]:
    """Every external identifier the corpus uses, wherever it appears — including inside evidence.

    Evidence is included on purpose: `SOURCE_RECORD` evidence carries a `SourceId` that is not a
    `source_ids` entry of any object, so a sweep over `source_ids` alone would leave one identifier
    per citation unchecked, which is exactly the corner a real one would arrive in.
    """
    found: set[str] = set()
    for path in ALL_FILES:
        for obj in _load(path):
            found |= {s.external_id for s in obj.source_ids}
            if obj.object_kind == "event" and obj.oes is not None:
                found |= {e.source_id.external_id for e in obj.oes.evidence
                          if e.source_id is not None}
    return found


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_object_is_filed_under_the_examples_own_system(path):
    for obj in _load(path):
        for source_id in obj.source_ids:
            assert source_id.system == SYSTEM, f"{path.name}: {source_id}"


def test_the_identifiers_used_are_exactly_the_fictional_roster():
    """§130, checked in both directions — see `FICTIONAL_IDENTIFIERS`."""
    used = _external_identifiers()
    assert used == FICTIONAL_IDENTIFIERS, (
        f"unrostered: {sorted(used - FICTIONAL_IDENTIFIERS)}; rostered but unused: "
        f"{sorted(FICTIONAL_IDENTIFIERS - used)}. Every identifier in examples/ is fictional and "
        "entered here deliberately; an addition is a decision, not a side effect")


def test_no_example_claims_a_provenance_it_does_not_have():
    """The source block names an adapter that does not exist, and that is the honest answer.

    These objects were written against the models by hand to illustrate the specification. A
    source block naming `pntmap` — the one adapter that emits SC-OES semantics — would claim they
    came out of a translation, which is exactly the implication §114 forbids. So the name is one
    nothing resolves, and this test is what keeps it that way: if an adapter is ever registered
    under it, these files stop being illustrations and the claim has to be re-made deliberately.
    """
    registered = set(adapter.roster())
    assert ADAPTER_NAME not in registered, (
        f"{ADAPTER_NAME!r} is now a registered adapter, so every example's source block reads as "
        "real provenance. Either rename the examples' source or make them that adapter's output")
    for path in ALL_FILES:
        for obj in _load(path):
            assert obj.source.adapter == ADAPTER_NAME, f"{path.name}: {obj.source.adapter!r}"


# ------------------------------------------------------------------- 4. identity is derived


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_identifier_is_re_derivable_from_the_source_identifier_beside_it(path):
    """`ids.derive` over (system, external_id), never a drawn uuid4 — the repository's rule.

    Re-derived here rather than compared against a written-down list, which makes the check a
    function of the file's own `source_ids` entry and not of anything this module remembers.
    """
    for obj in _load(path):
        external = obj.source_ids[0].external_id
        kind = "entity" if obj.object_kind == "entity" else "event"
        expected = ids.derive(obj.source_ids[0].system, external, kind=kind)
        actual = obj.entity_id if kind == "entity" else obj.event_id
        assert actual == expected, (
            f"{path.name}: {kind} id {actual} is not uuid5 over ({obj.source_ids[0].system}, "
            f"{external}); a drawn id would make this example irreproducible")


# ------------------------------------------------- 5. §141 — local reference consistency


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_every_reference_resolves_inside_its_own_file(path):
    """The clause §141 states for the chain, applied to all fourteen.

    Applied to all of them because the reason is not special to the chain: an example is a
    self-contained illustration, and a reference to something outside it is one a reader cannot
    follow. The models themselves permit a dangling event reference — a consumer holds a subset of
    history by definition — so this is a property of the EXAMPLES, not of SC-OES.
    """
    objects = _load(path)
    entity_ids = {o.entity_id for o in objects if o.object_kind == "entity"}
    event_ids = {o.event_id for o in objects if o.object_kind == "event"}
    dangling: list[str] = []
    for obj in objects:
        if obj.object_kind != "event":
            continue
        dangling += [f"related_entities -> {e}" for e in obj.related_entities
                     if e not in entity_ids]
        if obj.oes is None:
            continue
        dangling += [f"{r.predicate.value} -> {r.event_id}" for r in obj.oes.event_relations
                     if r.event_id not in event_ids]
        dangling += [f"evidence EVENT -> {e.event_id}" for e in obj.oes.evidence
                     if e.event_id is not None and e.event_id not in event_ids]
    assert not dangling, f"{path.name}: {dangling}"


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_no_example_contains_an_ordering_cycle(path):
    events = [o for o in _load(path) if o.object_kind == "event"]
    assert find_relation_cycles(events) == []


# ---------------------------------------------------------------- 6. the individual examples


@pytest.mark.parametrize("path", sorted(INDIVIDUAL.glob("*.json")), ids=lambda p: p.stem)
def test_each_individual_example_carries_exactly_the_type_it_is_named_for(path):
    events = [o for o in _load(path) if o.object_kind == "event"]
    assert len(events) == 1, f"{path.name} holds {len(events)} events; an individual example is one"
    assert events[0].oes is not None
    assert events[0].oes.type_id == path.stem


@pytest.mark.parametrize("path", sorted(INDIVIDUAL.glob("*.json")), ids=lambda p: p.stem)
def test_each_individual_example_asserts_the_class_the_registry_governs(path):
    """Dimension C already reports this; asserting it here names the FILE when it breaks."""
    entry = get_event_type(path.stem)
    assert entry is not None
    event = next(o for o in _load(path) if o.object_kind == "event")
    assert event.oes.event_class == entry.event_class
    assert event.oes.spec_version == SC_OES_VERSION


# ------------------------------------------------------------------- 7. the legacy axis (§28)


def _events() -> list[tuple[str, Event]]:
    return [(path.name, obj) for path in ALL_FILES for obj in _load(path)
            if obj.object_kind == "event"]


def test_the_governed_legacy_mapping_is_carried_wherever_the_registry_declares_one():
    """Seven of the thirteen types govern a legacy `event_type`; a mismatch is a C failure."""
    for name, event in _events():
        entry = get_event_type(event.oes.type_id)
        if entry is not None and entry.legacy_event_type is not None:
            assert event.event_type == entry.legacy_event_type, (
                f"{name}: event_type {event.event_type} but the registry governs "
                f"{entry.legacy_event_type} for {event.oes.type_id}")


def test_no_example_presses_an_unestablished_legacy_member_into_service():
    """ADR 0007 alternative F, applied to the examples — see `UNESTABLISHED_LEGACY`."""
    used = {event.event_type for _, event in _events()}
    assert not used & set(UNESTABLISHED_LEGACY), (
        f"an example uses {sorted(used & set(UNESTABLISHED_LEGACY))}. No adapter emits either, so "
        "the example would be establishing the member's meaning rather than using it")


def test_the_six_ungoverned_types_are_still_the_six_the_registry_says_they_are():
    """The counterweight: the freedom above exists only while the registry declares no mapping."""
    ungoverned = {entry.id for entry in list_event_types() if entry.legacy_event_type is None}
    assert len(ungoverned) == 6, sorted(ungoverned)
    for name, event in _events():
        entry = get_event_type(event.oes.type_id)
        if entry is not None and entry.id in ungoverned:
            assert isinstance(event.event_type, EventType)


# --------------------------------------------------------------------- 8. the linked chain (§132)


CHAIN_FILE = sorted(CHAIN.glob("*.json"))[0]


def test_the_chain_is_the_six_classes_in_the_specifications_order():
    events = [o for o in _load(CHAIN_FILE) if o.object_kind == "event"]
    assert tuple(e.oes.event_class for e in events) == CHAIN_CLASSES


def test_each_chain_event_derives_from_the_one_before_it_explicitly():
    """§132: "Use explicit event relationships." Explicit, and reconstructible from the file.

    The chain is checked by walking the DERIVED_FROM edges rather than by reading the array's
    order: an array order that happened to agree with a broken relation set would pass a check
    written the other way round, and the relations are what a consumer actually follows.
    """
    events = [o for o in _load(CHAIN_FILE) if o.object_kind == "event"]
    by_id = {e.event_id: e for e in events}
    first, rest = events[0], events[1:]
    assert first.oes.event_relations == [], (
        "the chain's first event derives from nothing inside the file, and saying so by carrying "
        "no relation is different from carrying one that points outside it")
    previous = first
    for event in rest:
        derived = [r for r in event.oes.event_relations if r.predicate.value == "DERIVED_FROM"]
        assert len(derived) == 1, f"{event.event_id}: {event.oes.event_relations}"
        assert derived[0].event_id == previous.event_id, (
            f"{event.oes.type_id} derives from {derived[0].event_id}, not from the event before "
            f"it ({previous.oes.type_id})")
        assert by_id[derived[0].event_id] is previous
        previous = event


def test_each_chain_event_cites_its_antecedent_as_evidence():
    """The relationship says how the events stand to each other; the evidence says what the
    later one rests on. §81 keeps them separate, and the chain carries both because an
    audit follows the evidence and a consumer follows the relation."""
    events = [o for o in _load(CHAIN_FILE) if o.object_kind == "event"]
    for earlier, later in zip(events, events[1:]):
        cited = [e.event_id for e in later.oes.evidence if e.kind.value == "EVENT"]
        assert cited == [earlier.event_id], f"{later.oes.type_id}: {cited}"


def test_the_chain_reaches_three_entities_and_no_more():
    """A chain that accumulated an entity per event would be illustrating fusion, not a chain."""
    objects = _load(CHAIN_FILE)
    entities = [o for o in objects if o.object_kind == "entity"]
    assert len(entities) == 3
    concerned = {e for o in objects if o.object_kind == "event" for e in o.related_entities}
    assert concerned == {o.entity_id for o in entities}


# ------------------------------------------------------- 9. what the examples are meant to show


def test_every_field_of_the_block_is_exercised_by_at_least_one_example():
    """Fourteen examples that all carried the same three fields would illustrate nothing.

    Derived from `OesMetadata.model_fields` rather than from a list here, so a fourteenth field
    added to the block arrives as a missing illustration rather than as a silent gap.
    """
    unexercised = []
    for field in OesMetadata.model_fields:
        if not any(getattr(event.oes, field) not in (None, [], {}) for _, event in _events()):
            unexercised.append(field)
    assert not unexercised, (
        f"no committed example asserts {unexercised}. Every field of the block is part of the "
        "contract, and one nothing illustrates is one nobody implements")


def test_all_three_evidence_kinds_appear_somewhere_in_the_corpus():
    kinds = {e.kind.value for _, event in _events() for e in event.oes.evidence}
    assert kinds == {"EVENT", "SOURCE_RECORD", "EXTERNAL_ARTIFACT"}


def test_no_object_carries_an_extension_outside_a_third_party_namespace():
    """The models refuse `sc.*`; this asserts the examples never even reach for it."""
    for name, event in _events():
        for key in event.oes.extensions:
            assert key.startswith("x."), f"{name}: {key}"


# ------------------------------------------------------- 10. conformance over the whole corpus


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: p.name)
def test_no_example_fails_a_conformance_dimension(path):
    """The examples are what a producer copies. One that failed a dimension would teach the
    failure, and it would teach it under the specification's own name."""
    failures = []
    for obj in json.loads(path.read_text()):
        report = assess(obj, profile=None)
        failures += [f"{report['identifier']} {key}: {d['findings']}"
                     for key, d in report["dimensions"].items() if d["verdict"] == FAIL]
    assert not failures, f"{path.name}: {failures}"


# ------------------------------------------------------------------ 11. the directory's README


def test_the_readme_names_every_governed_type_it_tabulates():
    text = README.read_text()
    for entry in list_event_types():
        assert f"`{entry.id}`" in text, f"the README does not name {entry.id}"


def test_the_readme_states_the_source_block_the_examples_actually_carry():
    text = README.read_text()
    assert SYSTEM in text and ADAPTER_NAME in text
    assert "No adapter of that name is registered" in text


def test_this_module_is_the_gate_the_readme_says_it_is():
    """A README naming a checker that had been renamed would be the rot this module prevents."""
    assert pathlib.Path(inspect.getfile(test_this_module_is_the_gate_the_readme_says_it_is)).name \
        in README.read_text()


def test_no_example_identifier_is_a_uuid_written_by_hand():
    """Every id parses as a UUID — the derived ones do by construction, and a typo does not."""
    for path in ALL_FILES:
        for raw in json.loads(path.read_text()):
            key = "entity_id" if raw["object_kind"] == "entity" else "event_id"
            uuid.UUID(raw[key])
