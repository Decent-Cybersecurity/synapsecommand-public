"""The SC-OES block's invariants, and every one of them exists because a producer would guess.

The specification's test list is §137 (the block) and §138 (the entity annotations); each name in
those lists has a test here and the mapping is stated in the test's own docstring where it is not
obvious from the name. Two items in §137 do not assert what their name suggests, and both are
recorded at the test rather than in a note somewhere else:

- **"unknown sc.* type"** is ACCEPTED here. A `type_id` that satisfies the governed grammar and
  names a type no registry carries is syntactically valid and a conformance failure, not a model
  failure — ADR 0003 decision 6 splits syntax from recognition deliberately, and putting a
  registry lookup in a model validator is what that split refuses.
- **"extension shadowing core field rejected"** is ACCEPTED here too, and ADR 0008 decision 5 is
  the reversal: `x.acme.confidence` survives validation, as §31 requires of every valid unknown
  extension, and it cannot shadow `oes.confidence` because nothing in this package ever reads
  inside an extension value. Non-interpretation is the enforcement; refusing the key would have
  contradicted the survival requirement it was meant to serve.
"""
import uuid

import pytest
from pydantic import ValidationError

from synapse_cdm import version
from synapse_cdm.enums import Affiliation, EntityType, EventType, InterferenceType, Severity
from synapse_cdm.models import Entity, Event, SourceId, SourceRef
from synapse_cdm.oes import (
    MAX_EXTENSION_DEPTH,
    EntityRelation,
    EventClass,
    EventRelation,
    EventRelationPredicate,
    EvidenceKind,
    EvidenceRef,
    LifecycleStatus,
    OesMetadata,
    SecurityMarking,
    Verification,
    extension_depth,
    find_relation_cycles,
    is_governed_event_type,
    is_governed_ontology_term,
    validate_event_bundle,
    validate_ontology_identifier,
    validate_type_id,
)

SOURCE = SourceRef(system="TEST", adapter="test", adapter_version="1.0.0", synthetic=True)
IDS = [SourceId(system="TEST", external_id="X-1")]
T0 = "2026-04-29T06:00:00Z"
T1 = "2026-04-29T12:00:00Z"

RUNWAY = "tag:synapsecommand.com,2026-09-06:ontology:air:Runway"
AFFECTS = "tag:synapsecommand.com,2026-09-06:ontology:core:Affects"
THIRD_PARTY = "https://example.org/ontology/Runway"


def _event(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, event_id=uuid.uuid4(),
                  event_type=EventType.DETECTION, severity=Severity.INFO,
                  observed_at=T0, received_at=T0)
    kwargs.update(overrides)
    return Event(**kwargs)


def _entity(**overrides):
    kwargs = dict(source=SOURCE, source_ids=IDS, entity_id=uuid.uuid4(),
                  entity_type=EntityType.FACILITY, affiliation=Affiliation.UNKNOWN, valid_from=T0)
    kwargs.update(overrides)
    return Entity(**kwargs)


def _block(**overrides):
    kwargs = dict(spec_version="0.1.0", event_class=EventClass.OBSERVATION,
                  type_id="sc.pnt.gnss_interference.v1")
    kwargs.update(overrides)
    return OesMetadata(**kwargs)


# --- attachment: an absent block is not a block of defaults -----------------------------------

def test_a_legacy_event_carries_no_block_and_none_is_inferred_for_it():
    """§137 'legacy Event without oes'. The whole compatibility claim of ADR 0001 rests here.

    An absent block means the producer made no SC-OES assertion. It does NOT mean the producer
    asserted defaults, and there is nowhere for a default to come from: `oes` is `None` and every
    field inside a block is either required or absent-means-unknown.
    """
    event = _event()
    assert event.oes is None
    assert "oes" in event.model_dump(mode="json")
    assert event.model_dump(mode="json")["oes"] is None


def test_a_valid_oes_event_round_trips_through_json_unchanged():
    """§137 'valid OES Event', and round-trip rather than construction, deliberately.

    Construction proves the validators accept it. Round-trip proves the wire form is the contract:
    an object serialised and re-read is the same object, which is what a consumer on the far side
    of a queue actually depends on.
    """
    entity_id = uuid.uuid4()
    target = uuid.uuid4()
    event = _event(
        related_entities=[entity_id],
        oes=_block(
            event_class=EventClass.CONSTRAINT,
            type_id="sc.air.runway_availability_changed.v1",
            status=LifecycleStatus.ACTIVE,
            verification=Verification.CORROBORATED,
            confidence=0.7,
            effective_from=T0,
            effective_to=T1,
            event_relations=[EventRelation(
                predicate=EventRelationPredicate.SUPERSEDES, event_id=target)],
            entity_relations=[EntityRelation(entity_id=entity_id, predicate=AFFECTS)],
            evidence=[EvidenceRef(kind=EvidenceKind.EVENT, event_id=target)],
            security=SecurityMarking(scheme="TEST-SCHEME", classification="UNCLASSIFIED",
                                     releasability=["REL A"], caveats=["CAVEAT B"],
                                     originator="TEST", marking_extras={"scheme_field": "value"}),
            extensions={"x.acme.radar_quality": {"sensor": {"quality": 0.9}}},
        ),
    )
    dumped = event.model_dump(mode="json")
    assert Event.model_validate(dumped).model_dump(mode="json") == dumped
    assert dumped["oes"]["spec_version"] == "0.1.0"
    assert "maturity" not in dumped["oes"], (
        "maturity belongs to a governed semantic DEFINITION and never to an occurrence")


def test_the_block_is_strict_and_the_only_open_field_is_extensions():
    """`01-core.md`: apart from `extensions`, an undeclared key is rejected, not preserved."""
    with pytest.raises(ValidationError):
        OesMetadata(spec_version="0.1.0", event_class=EventClass.OBSERVATION,
                    type_id="sc.pnt.gnss_interference.v1", maturity="STABLE")
    assert _block(extensions={"x.acme.anything": {"whatever": [1, 2]}}).extensions


# --- spec_version and type_id -----------------------------------------------------------------

def test_an_invalid_spec_version_is_refused_and_a_later_one_is_not():
    """§137 'invalid spec version', and the second half is the part worth stating.

    The shape is checked and the VALUE is not. Requiring equality with this package's own
    `SC_OES_VERSION` would refuse an event written against a later specification version, which
    `12-versioning.md` requires stay transportable — the field exists to make that case visible,
    not to make it fail.
    """
    for bad in ("0.1", "draft", "v0.1.0", "0.1.0-rc1", "01.0.0", ""):
        with pytest.raises(ValidationError):
            _block(spec_version=bad)
    assert _block(spec_version="9.9.9").spec_version == "9.9.9"
    assert version.SC_OES_VERSION == "0.1.0"


@pytest.mark.parametrize("type_id", [
    "sc.pnt.gnss_interference.v1",
    "sc.air.runway_availability_changed.v1",
    "sc.c2.system_availability_changed.v2",
    "x.acme.air.sensor_health_changed.v1",
    "x.vendor_name.pnt.receiver_quality_changed.v3",
])
def test_the_accepted_type_id_vectors_are_accepted(type_id):
    """The acceptance column of the frozen grammar, ADR 0003 decision 9."""
    assert _block(type_id=type_id).type_id == type_id


@pytest.mark.parametrize("type_id", [
    "sc.PNT.gnss_interference.v1",           # uppercase domain
    "sc.pnt.GnssInterference.v1",            # uppercase event name
    "sc.pnt.gnss-interference.v1",           # hyphen
    "sc.pnt.gnss_interference.v0",           # zero major
    "sc.pnt.gnss_interference.v01",          # leading zero
    "sc..gnss_interference.v1",              # empty label
    "sc.pnt.gnss_interference.v1\n",         # trailing newline: `$` would have accepted this
    " sc.pnt.gnss_interference.v1 ",         # surrounding whitespace is not trimmed
    "x.Acme.air.sensor_health_changed.v1",
    "x.acme-labs.air.sensor_health_changed.v1",
    "x.acme.air.sensor_health_changed.v01",
    "gnss_interference.v1",                  # unnamespaced
])
def test_the_refused_type_id_vectors_are_refused_and_nothing_is_repaired(type_id):
    """§137 'malformed type_id'. Each vector breaks exactly one rule of the frozen grammar.

    The trailing-newline vector is the one that would silently pass a validator written from the
    `^…$` form of the grammar, because `$` accepts one trailing newline in Python. ADR 0003
    decision 9 records the reading; `re.fullmatch` is what this module compiles instead.
    """
    with pytest.raises(ValidationError):
        _block(type_id=type_id)


def test_an_unknown_third_party_type_is_transportable():
    """§137 'unknown x.* type'. A third party's governed contract is theirs, and stays theirs."""
    block = _block(type_id="x.acme.air.sensor_health_changed.v1")
    assert block.type_id == "x.acme.air.sensor_health_changed.v1"
    assert not is_governed_event_type(block.type_id)


def test_an_unknown_governed_type_is_syntactically_valid_here_and_fails_a_dimension_elsewhere():
    """§137 'unknown sc.* type' — and the model ACCEPTS it. See this module's docstring.

    Syntax validity is not governance recognition. An unrecognised `sc.*` type is a dimension C
    failure (`12-versioning.md`), which is a `FAIL` rather than a `SKIP` because both possible
    causes need a person: a producer minting governed semantics it may not mint, or a consumer
    running against a registry older than the producer's.
    """
    block = _block(type_id="sc.air.imaginary_thing.v1")
    assert is_governed_event_type(block.type_id)


# --- confidence and verification ---------------------------------------------------------------

@pytest.mark.parametrize("bad", [-0.1, -1.0, 1.1, 2.0])
def test_confidence_outside_the_closed_unit_interval_is_refused(bad):
    """§137 'confidence < 0' and 'confidence > 1'."""
    with pytest.raises(ValidationError):
        _block(confidence=bad)


def test_confidence_none_means_unknown_and_is_never_zero():
    """§137 'confidence None'. 0.0 is a claim — certainty-that-not — and unknown is not a claim."""
    assert _block().confidence is None
    assert _block(confidence=0.0).confidence == 0.0
    assert _block(confidence=1.0).confidence == 1.0


def test_verification_is_optional_and_absence_is_not_unverified():
    """`UNVERIFIED` is the positive claim that the question was asked; absence is not that."""
    assert _block().verification is None
    assert _block(verification=Verification.UNVERIFIED).verification is Verification.UNVERIFIED


def test_status_is_optional_and_is_not_defaulted_to_active():
    """`05-lifecycle.md` forbids defaulting `status` to `ACTIVE` or to anything else."""
    assert _block().status is None
    assert len(list(LifecycleStatus)) == 7


def test_event_class_is_the_eight_named_values_and_nothing_else():
    assert [c.value for c in EventClass] == [
        "OBSERVATION", "STATE_CHANGE", "CONSTRAINT", "ASSESSMENT",
        "IMPACT", "RECOMMENDATION", "DECISION", "ACTION",
    ]
    with pytest.raises(ValidationError):
        _block(event_class="ENRICHMENT")


# --- the effective interval ---------------------------------------------------------------------

def test_a_backwards_effective_interval_is_a_translation_defect_and_not_data():
    """§137 'backwards effective interval'. The only ordering rule that fails."""
    with pytest.raises(ValidationError, match="runs backwards"):
        _block(effective_from=T1, effective_to=T0)


def test_an_open_ended_effective_interval_is_ordinary():
    """§137 'open-ended effective interval'.

    An absent `effective_to` does not mean permanent and does not mean still in force. An
    open-ended runway closure carries `effective_from` and no end; when the runway reopens a NEW
    event records that, with a `RESOLVES` relation — the closure event is not edited to acquire
    one.
    """
    block = _block(effective_from=T0)
    assert block.effective_to is None
    assert _block(effective_from=T0, effective_to=T0).effective_to is not None


def test_effective_from_is_never_defaulted_from_the_message_timestamps():
    """`04-temporality.md`: the first pair is about the message, the second about the world."""
    event = _event(oes=_block())
    assert event.oes.effective_from is None and event.oes.effective_to is None
    assert event.observed_at is not None


def test_clock_skew_and_a_condition_older_than_its_observation_are_both_accepted():
    """Both are ordinary. Only an interval that ends before it starts is a defect."""
    _event(observed_at=T1, received_at=T0, oes=_block(effective_from=T0))


# --- event relationships -------------------------------------------------------------------------

def test_a_self_referential_event_relation_is_refused():
    """§137 'self relationship'. Needs the event, which is why the rule lives on `Event`."""
    event_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="citing event"):
        _event(event_id=event_id, oes=_block(event_relations=[
            EventRelation(predicate=EventRelationPredicate.UPDATES, event_id=event_id)]))


def test_a_duplicate_identical_relationship_is_refused_and_a_different_predicate_is_not():
    """§137 'duplicate relationship'. Same predicate to the same target twice adds nothing."""
    target = uuid.uuid4()
    with pytest.raises(ValidationError, match="duplicate event relation"):
        _block(event_relations=[
            EventRelation(predicate=EventRelationPredicate.UPDATES, event_id=target),
            EventRelation(predicate=EventRelationPredicate.UPDATES, event_id=target)])
    assert len(_block(event_relations=[
        EventRelation(predicate=EventRelationPredicate.UPDATES, event_id=target),
        EventRelation(predicate=EventRelationPredicate.DERIVED_FROM, event_id=target),
    ]).event_relations) == 2


def test_a_relation_to_an_event_that_is_not_locally_available_is_permitted():
    """The rule that makes SC-OES usable across systems at all.

    A consumer holds a subset of the history by definition, and rejecting an event because its
    antecedent has not arrived would make delivery order part of the contract.
    """
    _event(oes=_block(event_relations=[
        EventRelation(predicate=EventRelationPredicate.DERIVED_FROM, event_id=uuid.uuid4())]))


def test_a_malformed_event_identifier_is_refused():
    with pytest.raises(ValidationError):
        EventRelation(predicate=EventRelationPredicate.UPDATES, event_id="not-a-uuid")


def test_an_unrecognised_predicate_is_refused_and_not_read_as_a_nearby_one():
    with pytest.raises(ValidationError):
        EventRelation(predicate="REPLACES", event_id=uuid.uuid4())
    assert [p.value for p in EventRelationPredicate] == [
        "DERIVED_FROM", "UPDATES", "SUPERSEDES", "RESOLVES", "RETRACTS",
        "CONTRADICTS", "CORRELATES_WITH",
    ]


def _pair(predicate):
    a, b = uuid.uuid4(), uuid.uuid4()
    return [
        _event(event_id=a, oes=_block(event_relations=[
            EventRelation(predicate=predicate, event_id=b)])),
        _event(event_id=b, oes=_block(event_relations=[
            EventRelation(predicate=predicate, event_id=a)])),
    ]


def test_a_detectable_supersedes_cycle_in_a_supplied_bundle_is_rejected():
    """§137 'detectable supersedes cycle'. The realistic mistake: a mutually superseding pair."""
    bundle = _pair(EventRelationPredicate.SUPERSEDES)
    assert find_relation_cycles(bundle)
    with pytest.raises(ValueError, match="cycle"):
        validate_event_bundle(bundle)


def test_a_detectable_derived_from_cycle_in_a_supplied_bundle_is_rejected():
    """§137 'detectable derived-from cycle'. Both predicates assert a strict ordering."""
    bundle = _pair(EventRelationPredicate.DERIVED_FROM)
    assert find_relation_cycles(bundle)
    with pytest.raises(ValueError, match="cycle"):
        validate_event_bundle(bundle)


def test_the_cycle_check_is_bounded_by_the_bundle_and_the_other_predicates_do_not_cycle():
    """A half-supplied chain is acyclic as far as the caller gave it, and that is the honest answer.

    A validator handed one end of a chain does not fetch the other end, and an empty result means
    the BUNDLE is acyclic — not that the wider history is. `CORRELATES_WITH` is conceptually
    symmetric, so a mutual pair of it is ordinary rather than a cycle.
    """
    a, b = uuid.uuid4(), uuid.uuid4()
    half = [_event(event_id=a, oes=_block(event_relations=[
        EventRelation(predicate=EventRelationPredicate.SUPERSEDES, event_id=b)]))]
    assert find_relation_cycles(half) == []
    validate_event_bundle(half)
    assert find_relation_cycles(_pair(EventRelationPredicate.CORRELATES_WITH)) == []
    validate_event_bundle([_event()])


# --- entity relations ---------------------------------------------------------------------------

def test_an_entity_relation_naming_an_entity_the_event_does_not_relate_is_refused():
    """§137 'entity relation absent from related_entities'.

    `related_entities` remains the single answer to "which entities does this event concern", so
    a role naming an entity outside it would make the two lists disagree about the event's scope.
    """
    with pytest.raises(ValidationError, match="related_entities"):
        _event(related_entities=[uuid.uuid4()], oes=_block(entity_relations=[
            EntityRelation(entity_id=uuid.uuid4(), predicate=AFFECTS)]))


def test_an_entity_relation_predicate_must_be_an_absolute_semantic_identifier():
    """`09-entity-semantics.md`: a bare word, a local name or a relative reference is a failure.

    AND THE LIMIT OF THAT RULE IS STATED HERE RATHER THAN LEFT TO BE DISCOVERED. A bare word and a
    relative reference are mechanically distinguishable and are refused. A PREFIXED NAME whose
    prefix happens to be a syntactically valid URI scheme — `core:Affects` — is not: by RFC 3986
    that string IS an absolute URI with scheme `core`, and §15's three tests (absolute, valid
    scheme, no whitespace or control characters) admit it. No check can separate it from a genuine
    identifier in an unusual scheme without a registry of schemes, which §125 forbids reaching for
    and which would refuse legitimate third-party vocabularies. It is therefore accepted as an
    opaque third-party identifier and is never expanded, resolved or mapped.
    """
    for bad in ("affects", "./Affects", "/Affects", "", "core Affects"):
        with pytest.raises(ValidationError):
            EntityRelation(entity_id=uuid.uuid4(), predicate=bad)
    assert EntityRelation(entity_id=uuid.uuid4(), predicate="core:Affects").predicate == \
        "core:Affects"


def test_a_duplicate_entity_relation_is_refused():
    entity_id = uuid.uuid4()
    with pytest.raises(ValidationError, match="duplicate entity relation"):
        _block(entity_relations=[EntityRelation(entity_id=entity_id, predicate=AFFECTS),
                                 EntityRelation(entity_id=entity_id, predicate=AFFECTS)])


# --- ontology identifiers -------------------------------------------------------------------------

def test_a_valid_governed_ontology_term_is_accepted():
    """§137 and §138 'valid governed ontology term' / 'governed Runway ontology type'."""
    assert validate_ontology_identifier(RUNWAY) == RUNWAY
    assert is_governed_ontology_term(RUNWAY)
    assert _entity(ontology_types=[RUNWAY]).ontology_types == [RUNWAY]


def test_a_governed_term_absent_from_the_registry_is_syntax_valid_and_a_dimension_e_failure():
    """§137 'unknown reserved SynapseCommand ontology term' — accepted HERE. See the module docstring."""
    imaginary = "tag:synapsecommand.com,2026-09-06:ontology:air:ImaginaryThing"
    assert is_governed_ontology_term(imaginary)
    assert _entity(ontology_types=[imaginary]).ontology_types == [imaginary]


def test_an_identifier_impersonating_the_governed_namespace_is_refused():
    """§15's third test. The reserved-namespace rule and the third-party rule, one seen from each side."""
    for bad in ("tag:synapsecommand.com,2026-09-06:ontology:Air:Runway",     # uppercase module
                "tag:synapsecommand.com,2026-09-06:ontology:air:runway",     # lowercase term
                "tag:synapsecommand.com,2026-09-06:ontology:air:Runway_Type",  # underscore in term
                "tag:synapsecommand.com,2026-09-06:ontology:air:"):          # no term at all
        with pytest.raises(ValueError, match="reserved SynapseCommand namespace"):
            validate_ontology_identifier(bad)


def test_a_valid_third_party_semantic_identifier_is_preserved_verbatim():
    """§137 and §138. Opaque, never rewritten, never mapped onto a governed term."""
    for good in (THIRD_PARTY, "urn:example:ontology:Runway", "tag:example.org,2020:thing"):
        assert validate_ontology_identifier(good) == good
        assert not is_governed_ontology_term(good)
    assert _entity(ontology_types=[THIRD_PARTY]).ontology_types == [THIRD_PARTY]


@pytest.mark.parametrize("bad", [
    "runway", "Runway", "./relative", "/absolute/path", "has space:x",
    "tag:example.org,2020:thing\n", "scheme:", ":noscheme", "1scheme:x",
])
def test_a_malformed_ontology_identifier_is_refused(bad):
    """§137 and §138 'malformed ontology term'. Absolute, with a scheme, no whitespace, no controls."""
    with pytest.raises(ValueError):
        validate_ontology_identifier(bad)


def test_a_control_character_anywhere_in_an_identifier_is_refused():
    with pytest.raises(ValueError, match="control character"):
        validate_ontology_identifier("https://example.org/On\x00tology")


# --- Entity: §138 --------------------------------------------------------------------------------

def test_a_legacy_entity_validates_unchanged_and_ontology_types_defaults_empty():
    """§138 'legacy Entity' and 'ontology_types omitted'."""
    entity = _entity()
    assert entity.ontology_types == []
    assert entity.model_dump(mode="json")["ontology_types"] == []


def test_an_explicitly_empty_ontology_types_is_the_same_state_as_an_omitted_one():
    """§138 'ontology_types empty'. Both mean the producer asserted no semantic type."""
    assert _entity(ontology_types=[]).ontology_types == []


def test_a_duplicate_ontology_term_is_rejected_rather_than_deduplicated():
    """§138 'duplicate ontology term'.

    Rejected, not collapsed. A set silently repaired is a defect the producer is never shown, and
    the record would then disagree with what was sent.
    """
    with pytest.raises(ValidationError, match="duplicate ontology type"):
        _entity(ontology_types=[RUNWAY, RUNWAY])
    assert len(_entity(ontology_types=[RUNWAY, THIRD_PARTY]).ontology_types) == 2


def test_a_malformed_ontology_term_on_an_entity_is_refused():
    """§138 'malformed ontology term'."""
    with pytest.raises(ValidationError):
        _entity(ontology_types=["runway"])


def test_the_existing_entity_type_is_unchanged_and_neither_field_derives_the_other():
    """§138 'existing EntityType unchanged'.

    `FACILITY` says how the record behaves in the canonical model; the ontology identifier says
    what the thing is in operational terms. A system that only understands the CDM handles the
    entity correctly; a system that also understands the ontology knows it is a runway.
    """
    assert [t.value for t in EntityType] == [
        "UNIT", "PLATFORM", "SENSOR", "FACILITY", "EVACUEE_GROUP",
        "INTERFERENCE_SOURCE", "OVERLAY_OBJECT", "UNKNOWN",
    ]
    entity = _entity(entity_type=EntityType.FACILITY, ontology_types=[RUNWAY])
    assert entity.entity_type is EntityType.FACILITY
    assert _entity(entity_type=EntityType.FACILITY).ontology_types == []


# --- payloads -------------------------------------------------------------------------------------

def test_a_known_payload_is_still_validated_against_its_registered_model():
    """§137 'known payload validation'. The SC-OES block does not disturb `_payload_shape`."""
    good = _event(event_type=EventType.GNSS_INTERFERENCE, oes=_block(),
                  payload={"frequency_band": "L1",
                           "interference_type": InterferenceType.JAMMING.value})
    assert good.typed_payload().frequency_band == "L1"
    with pytest.raises(ValidationError):
        _event(event_type=EventType.GNSS_INTERFERENCE, payload={"frequency_band": "L1"})


def test_an_unregistered_event_types_payload_is_preserved_free_form():
    """§137 'unknown payload preservation'."""
    payload = {"anything": {"a source": ["shape", 1, None]}}
    event = _event(event_type=EventType.ALERT, payload=payload, oes=_block())
    assert event.payload == payload
    assert event.typed_payload() is None


def test_payload_extras_survive_beside_the_fields_the_model_understands():
    """§137 'payload extras preserved'. Validation is a CHECK, never a transformation."""
    payload = {"frequency_band": "L1", "interference_type": "JAMMING", "vendor_extra": [1, 2, 3]}
    event = _event(event_type=EventType.GNSS_INTERFERENCE, payload=payload, oes=_block())
    assert event.payload == payload
    assert event.model_dump(mode="json")["payload"]["vendor_extra"] == [1, 2, 3]


# --- extensions -------------------------------------------------------------------------------------

@pytest.mark.parametrize("key", ["x.acme.radar_quality", "x.vendor_name.sensor_state", "x.a.value1"])
def test_a_valid_extension_key_is_accepted(key):
    """§137 'valid x.* extension'."""
    assert _block(extensions={key: 1}).extensions[key] == 1


def test_an_unknown_extension_survives_validation_serialization_and_round_trip_unaltered():
    """§137 'unknown x.* extension preserved'.

    Round-trip UNALTERED is stronger than it looks and is the property that makes the bag worth
    having: a validator that dropped keys it did not recognise would make every intermediary a
    lossy hop, and a producer would learn to smuggle data into a core field to keep it.
    """
    value = {"vendor": {"nested": [1, {"deep": None}]}, "unicode": "äö"}
    event = _event(oes=_block(extensions={"x.acme.telemetry": value}))
    dumped = event.model_dump(mode="json")
    assert dumped["oes"]["extensions"]["x.acme.telemetry"] == value
    assert Event.model_validate(dumped).oes.extensions["x.acme.telemetry"] == value


def test_a_reserved_sc_extension_key_is_rejected_as_reserved_but_undefined():
    """§137 'sc.* extension rejected in v0.1'.

    A syntactically well-formed `sc.*` key still fails: the reservation is about the namespace and
    not about the spelling. No extension registry is created to represent an empty governed set,
    so there is nothing in v0.1.0 for such a key to be looked up in and nothing that could allow
    it.
    """
    for key in ("sc.core.anything", "sc.acme.radar_quality", "sc.x"):
        with pytest.raises(ValidationError, match="reserved but"):
            _block(extensions={key: 1})


@pytest.mark.parametrize("key", [
    "radar_quality", "acme.radar_quality", "x.Acme.radar_quality", "x.acme.radar-quality",
    "x.acme", "x..quality", "x.acme.radar_quality.extra", " x.acme.radar_quality",
])
def test_an_unnamespaced_or_malformed_extension_key_is_rejected_and_never_repaired(key):
    """§137 'unnamespaced extension rejected'.

    An unnamespaced key is the one shape that cannot be attributed to anybody, which is why it is
    refused rather than tolerated. Nothing is case-folded, hyphen-folded or trimmed.
    """
    with pytest.raises(ValidationError):
        _block(extensions={key: 1})


def test_an_extension_that_shadows_a_core_field_is_accepted_and_never_interpreted():
    """§137 'extension shadowing core field rejected' — REVERSED by ADR 0008 decision 5.

    §31 requires every valid unknown `x.*` extension to survive validation, and a refusal keyed on
    the trailing name would have contradicted that. What actually prevents the shadowing is
    non-interpretation: nothing in this package reads inside an extension value, so a value
    nothing reads cannot redefine anything. The assertion below is that the core field is
    untouched by the extension sharing its word.
    """
    block = _block(confidence=0.4, extensions={"x.acme.confidence": 0.99})
    assert block.confidence == 0.4
    assert block.extensions["x.acme.confidence"] == 0.99


@pytest.mark.parametrize("value,depth", [
    (0.95, 0), ("text", 0), (None, 0), (True, 0),
    ({}, 1), ([], 1),
    ({"sensor": {"quality": 0.9}}, 2),
    ([{"samples": [1, 2, 3]}], 3),
])
def test_the_frozen_depth_counting_algorithm_gives_the_worked_answers(value, depth):
    """ADR 0008 decision 7's worked examples, verbatim. Property names contribute nothing."""
    assert extension_depth(value) == depth


def test_depth_is_calculated_per_key_and_never_once_across_the_bag():
    """Two values of depth 2, not one of depth 3 — SA.1's own example."""
    extensions = {"x.a.one": {"a": {"b": 1}}, "x.b.two": {"c": {"d": 2}}}
    assert [extension_depth(v) for v in extensions.values()] == [2, 2]
    assert _block(extensions=extensions).extensions == extensions


def _nest(depth):
    value = 1
    for _ in range(depth):
        value = [value]
    return value


def test_an_extension_at_depth_sixteen_is_accepted():
    """§137 'extension nesting depth 16 accepted'."""
    assert MAX_EXTENSION_DEPTH == 16
    assert extension_depth(_nest(16)) == 16
    assert _block(extensions={"x.acme.deep": _nest(16)}).extensions


def test_an_extension_at_depth_seventeen_is_refused_and_the_refusal_names_key_depth_and_maximum():
    """§137 'extension nesting depth 17 rejected'.

    The message is part of the contract: a producer reading it has to be able to fix its own data
    from the message alone, so the key, the calculated depth and the maximum are all named and no
    stack trace or internal detail is included.
    """
    assert extension_depth(_nest(17)) == 17
    with pytest.raises(ValidationError) as caught:
        _block(extensions={"x.acme.deep": _nest(17)})
    message = str(caught.value)
    assert "x.acme.deep" in message and "17" in message and "16" in message


def test_the_depth_bound_counts_objects_and_arrays_alike_and_ignores_property_names():
    deep_object = 1
    for name in range(17):
        deep_object = {f"level_{name}": deep_object}
    with pytest.raises(ValidationError, match="depth 17"):
        _block(extensions={"x.acme.deep": deep_object})


def test_no_universal_list_size_cap_is_established_for_the_three_lists():
    """§33: those are deployment resource policies, not SC-OES interoperability requirements."""
    targets = [uuid.uuid4() for _ in range(50)]
    block = _block(event_relations=[
        EventRelation(predicate=EventRelationPredicate.CORRELATES_WITH, event_id=t)
        for t in targets])
    assert len(block.event_relations) == 50
    assert len(_block(evidence=[EvidenceRef(kind=EvidenceKind.EVENT, event_id=t)
                                for t in targets]).evidence) == 50


# --- evidence -----------------------------------------------------------------------------------------

def test_each_evidence_kind_requires_the_field_that_says_what_it_points_at():
    for kind in EvidenceKind:
        with pytest.raises(ValidationError, match="requires"):
            EvidenceRef(kind=kind)


def test_a_source_record_reference_uses_the_canonical_representation_and_not_an_opaque_string():
    """§83. A reference here and a source identifier elsewhere are the same kind of thing."""
    ref = EvidenceRef(kind=EvidenceKind.SOURCE_RECORD,
                      source_id=SourceId(system="PNTMAP", external_id="ALERT-1"))
    assert ref.source_id.system == "PNTMAP"
    with pytest.raises(ValidationError):
        EvidenceRef(kind=EvidenceKind.SOURCE_RECORD, source_id="PNTMAP|ALERT-1")


def test_an_external_artifact_carries_its_descriptive_fields_and_the_hash_guarantees_nothing():
    """§84. `hash` is descriptive metadata only: not integrity, not a signature, not authenticity."""
    ref = EvidenceRef(kind=EvidenceKind.EXTERNAL_ARTIFACT, uri="https://example.org/notice.pdf",
                      description="a published notice", media_type="application/pdf",
                      hash="sha256:deadbeef")
    assert ref.uri.startswith("https://")
    assert ref.hash == "sha256:deadbeef"


def test_a_field_belonging_to_another_evidence_kind_is_refused():
    with pytest.raises(ValidationError, match="belongs to another kind"):
        EvidenceRef(kind=EvidenceKind.EVENT, event_id=uuid.uuid4(), uri="https://example.org/x")
    with pytest.raises(ValidationError, match="belongs to another kind"):
        EvidenceRef(kind=EvidenceKind.SOURCE_RECORD,
                    source_id=SourceId(system="S", external_id="1"), hash="sha256:beef")


def test_an_unrecognised_evidence_kind_is_refused():
    with pytest.raises(ValidationError):
        EvidenceRef(kind="DOCUMENT", uri="https://example.org/x")


# --- security markings -----------------------------------------------------------------------------------

def test_the_security_block_is_optional_and_its_absence_is_not_a_failure():
    """§137 'security block optional'. Absence is not proof of unclassified status either."""
    assert _block().security is None


def test_marking_values_are_transported_verbatim_and_the_scheme_is_required():
    """`10-security-markings.md`: no translation, normalisation, abbreviation, expansion,
    case-folding or reordering, and every value is interpreted only relative to its scheme."""
    marking = SecurityMarking(scheme="NATO", classification="nato secret",
                              releasability=["ZZZ", "AAA"], caveats=["rel to xyz"],
                              originator="an originator", marking_extras={"policy": "P-1"})
    assert marking.classification == "nato secret"
    assert marking.releasability == ["ZZZ", "AAA"]
    with pytest.raises(ValidationError):
        SecurityMarking(classification="SECRET")


def test_no_classification_field_appears_on_the_canonical_objects():
    """The documented gap stays a gap: markings live inside `oes.security` and nowhere else.

    SC-OES transports markings and does not interpret or enforce them, so a top-level
    `classification` on `Entity` or `Event` would be exactly the field a consumer would mistake
    for enforcement.
    """
    assert "classification" not in Entity.model_fields
    assert "classification" not in Event.model_fields
    assert "security" not in Event.model_fields


# --- the schema publication -----------------------------------------------------------------------------

def test_the_block_is_published_inside_the_event_schema_rather_than_only_in_python():
    """§125: a non-Python consumer validates offline, so the block has to reach the schema."""
    schema = Event.model_json_schema(mode="serialization")
    assert "oes" in schema["properties"]
    for name in ("OesMetadata", "EventRelation", "EntityRelation", "EvidenceRef",
                 "SecurityMarking", "EventClass", "LifecycleStatus", "Verification",
                 "EvidenceKind", "EventRelationPredicate"):
        assert name in schema["$defs"], name
    assert schema["$defs"]["OesMetadata"]["additionalProperties"] is False
    assert Entity.model_json_schema(mode="serialization")["additionalProperties"] is False


def test_the_wire_contract_is_a_major_and_a_one_x_reader_is_refused_at_the_version_gate():
    """ADR 0005's readings, taken here rather than quoted from the ADR."""
    assert version.SCHEMA_VERSION == "2.0.0"
    assert version.compatible("2.0.0", "1.0.0") is False
    assert version.compatible("1.0.0", "2.0.0") is False
    assert _event().schema_version == "2.0.0"


def test_a_legacy_one_x_object_still_validates_against_the_two_x_models():
    """Backward: structurally clean, version-gated. No field mapping exists and none is needed."""
    legacy = _event().model_dump(mode="json")
    legacy["schema_version"] = "1.0.0"
    del legacy["oes"]
    revived = Event.model_validate(legacy)
    assert revived.schema_version == "1.0.0" and revived.oes is None
