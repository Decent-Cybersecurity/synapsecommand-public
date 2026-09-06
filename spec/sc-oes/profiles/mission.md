# SC-OES Mission Profile

**SC-OES Mission Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

## Scope

Missions and the operational consequences borne by them. In scope are a change in a
mission's represented status and an assessed operational impact on a mission or an activity. Out of
scope are mission planning, tasking, scheduling and any representation of a plan's internal
structure.

Profile domain: `mission`.

## Version

```text
profile:         Mission
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
core:Mission                            what the events are about
mission:MissionStatusChangedEvent       the status type's event class
mission:OperationalImpactAssessedEvent  the impact type's event class
core:Affects                            what an impact does to a mission
```

`core:Mission` is a core term rather than a mission-module one because missions are referred to
from every domain. The CDM's structural `entity_type` vocabulary has no member for a mission; an
entity representing one carries `UNKNOWN` there and says what it IS in `ontology_types`, which is
exactly the split `../09-entity-semantics.md` describes and the reason the annotation exists.

## Event types in scope

Two governed types are in scope for v0.1.0, in the `mission` domain, one
`STATE_CHANGE` and one `IMPACT`.

```text
sc.mission.mission_status_changed.v1
sc.mission.operational_impact_assessed.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span two classes, `STATE_CHANGE` and `IMPACT`.

The two classes are the profile's spine. A status change is a fact about the
mission; an impact is a judgement about a consequence for it. `IMPACT` rather than `ASSESSMENT` is
deliberate: the subject is the consequence for an operation, which is what a consumer routes on, and
collapsing the two would make every consequence indistinguishable from every other interpretation
(`../02-event-classes.md`).

## Payload semantics

No type in this profile has a registered payload model in v0.1.0. Payloads are free-form
and transportable. The impact example carries the mission, the impact in the assessor's own words,
an assessed severity and who assessed it; as in the ISR profile, the assessor is what makes the
judgement attributable.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id`.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Conventions, stated as conventions and not as requirements:

- a status change SHOULD carry the previous status;
- an impact SHOULD carry `confidence` and SHOULD carry a `DERIVED_FROM` relationship to the
  assessment or observation it follows from, because an impact with no antecedent is a conclusion
  with no visible premise;
- `severity` on the CDM event and an assessed severity in the payload are different fields and
  SHOULD NOT be assumed to agree: one is the producer's routing hint, the other is the judgement.

## Temporality

`observed_at` on an impact is when the impact was assessed. `effective_from` and
`effective_to` describe how long the consequence is expected to hold, when the producer states such
a window. Neither is defaulted, and lifecycle is never derived from the interval
(`../04-temporality.md`, `../05-lifecycle.md`).

## Entity relations

`core:Affects` is the characteristic role: the subject bears on the object's
operational state or freedom of action, without saying how or that the effect is adverse.
`core:Concerns` remains the weaker option for a status change that merely names its mission.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no extension and
reserves none. Mission identifiers, phase names and impact scales are a formation's own and differ
between exercises; they belong under the producer's namespace, preserved and never interpreted
(`../11-extensions.md`). The `sc.` prefix is reserved and undefined in v0.1.0 and is refused.

## Security considerations

A mission's status and the impacts on it are among the most sensitive events this
specification carries, and an aggregate of them describes an operation. Markings are transported and
never enforced (`../10-security-markings.md`); presence is not authorization, absence is not proof
of unclassified status, and nothing in this profile makes a marking required.

## Examples

Two, one per governed type:

- `examples/sc-oes/individual/sc.mission.mission_status_changed.v1.json`
- `examples/sc-oes/individual/sc.mission.operational_impact_assessed.v1.json`

Both concern an entity whose structural `entity_type` is `UNKNOWN` and whose `ontology_types`
says it is a mission, which is the split this profile's ontology section describes. The linked
chain (`examples/sc-oes/chain/gnss-interference-to-route-change.json`) carries the impact type as
its third event. All are loaded and validated on every test run by
`tests/test_cdm_examples.py`.

## Non-goals

This profile does not plan, task or schedule; it does not represent a plan's internal
structure; it does not define a mission-status vocabulary beyond the source's own words; and it does
not compute an impact from anything. Deriving an impact is reasoning, and no reasoning happens in
this repository.

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
has no rules to check, and the permitted claim "SC-OES Mission Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.
