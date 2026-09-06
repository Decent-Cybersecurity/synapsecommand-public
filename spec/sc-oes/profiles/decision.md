# SC-OES Decision Profile

**SC-OES Decision Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

## Scope

The decision cycle, recorded rather than performed: a course of action proposed, a
decision taken, an action authorised. In scope are those three occurrences and the relationships
between them. Out of scope is everything that produces them — option generation, evaluation,
optimisation and any other form of reasoning.

Profile domain: `decision`.

## Version

```text
profile:         Decision
profile_version: 0.1.0
sc_oes_version:  0.1.0
```

The profile version is independent of the SC-OES specification version and of every other profile's
version (`../01-core.md`). It moves when this profile changes and for no other reason.

## Maturity

```text
DRAFT
```

`../12-versioning.md` defines what each maturity value commits this specification to. A profile's
maturity is not inherited by the event types it names: each governed type carries its own maturity
in the packaged event registry, which is the machine authority for it.

## Ontology concepts

```text
decision:RecommendationCreatedEvent  decision:DecisionRecordedEvent  decision:ActionAuthorizedEvent
core:Actor      who proposes, decides or authorises
core:Activity   what is proposed, decided or authorised
core:Route      a frequent object of all three in practice
```

The three event classes are siblings under `core:OperationalEvent` and each is annotated on exactly
one governed type. `core:Actor` is what makes a decision attributable: the actor is the point of the
record, and a decision with no attributable decider is an assertion nobody owns.

## Event types in scope

Three governed types are in scope for v0.1.0, in the `decision` domain, spanning
`RECOMMENDATION`, `DECISION` and `ACTION`.

```text
sc.decision.recommendation_created.v1
sc.decision.decision_recorded.v1
sc.decision.action_authorized.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span three classes, `RECOMMENDATION`, `DECISION` and `ACTION`.

Three classes, three separate events, and the separation is the profile's entire
claim. A recommendation is not a decision and does not become one by being accepted downstream; a
decision is not an action and does not become one by being taken; an authorised action records the
authorisation and not the execution. Collapsing any pair would destroy the audit trail that makes
the sequence worth recording at all (`../02-event-classes.md`).

## Payload semantics

No type in this profile has a registered payload model in v0.1.0. Payloads are free-form
and transportable. The examples carry the proposer, the decider or the authoriser, what was
proposed, decided or authorised, and a reference a consumer can trace — an authorisation reference
in the action's case. Those are the fields an audit asks for, and they are illustrative rather than
a schema.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id`.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Conventions, stated as conventions and not as requirements, and this profile
leans on relationships more than on fields:

- each event SHOULD carry `DERIVED_FROM` to the one before it in the cycle, which is what makes the
  sequence reconstructible from the events alone;
- a decision that reverses an earlier one SHOULD carry `SUPERSEDES`, and a withdrawn recommendation
  SHOULD be `RETRACTS`ed rather than deleted — history is immutable and a correction is a new event
  (`../08-event-relationships.md`, `../05-lifecycle.md`);
- the payload SHOULD name the actor, for the reason the ontology section gives.

## Temporality

`observed_at` is when the recommendation was made, the decision taken or the action
authorised. `effective_from` on an authorised action is when the authorisation begins to hold, which
is frequently later than the authorisation itself and is never defaulted to it
(`../04-temporality.md`).

## Entity relations

`core:Concerns` for the mission or activity the event is about, `core:Uses` for a
resource the proposed or authorised course draws on. As everywhere, an entity given a role must also
appear in `related_entities`.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no
extension and reserves none. A house workflow identifier or an approval-chain reference goes under
the producer's own namespace (`../11-extensions.md`).

## Security considerations

Decisions and authorisations are the events whose disclosure is most consequential, and
they are also the events most likely to be retained longest. Markings are transported and never
enforced (`../10-security-markings.md`). Nothing in this profile makes a marking required, and
nothing in this repository can enforce one.

## Examples

Three, one per governed type:

- `examples/sc-oes/individual/sc.decision.recommendation_created.v1.json`
- `examples/sc-oes/individual/sc.decision.decision_recorded.v1.json`
- `examples/sc-oes/individual/sc.decision.action_authorized.v1.json`

The linked chain (`examples/sc-oes/chain/gnss-interference-to-route-change.json`) closes on all
three, in order, each deriving from the one before and citing it as evidence. All are loaded and
validated on every test run by `tests/test_cdm_examples.py`.

## Non-goals

This profile does not generate recommendations, does not evaluate options, does not
optimise anything and does not implement a decision engine. The chain in `examples/` is written
down, not computed. Reasoning is the private runtime's, and the boundary is the point of publishing
this layer at all (`../README.md`).

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event
types. Every adapter this repository ships remains CDM Conformant without being an SC-OES semantic
producer, and that distinction is intentional (`../README.md`). Nothing in this tree should be read
as implying an operational adapter implementation exists for this profile: the examples under
`examples/sc-oes/` were written against the models by hand and name an adapter nothing resolves,
and PNT is the one profile with a reference producer behind it (`pnt.md`).

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). This profile declares no conformance rules of its own in v0.1.0: every
constraint stated above is either one dimension A, B, C or E already checks — the CDM's structural
contract, the block's core syntax, the governed type's agreement with the registry, and the
recognition of governed ontology terms — or a convention marked SHOULD, which is guidance to a
producer and not a rule to grade against. A D assessment against this profile therefore
has no rules to check, and the permitted claim "SC-OES Decision Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.
