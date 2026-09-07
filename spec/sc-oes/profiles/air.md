# SC-OES Air Profile

**SC-OES Air Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

## Scope

The air domain: observed air tracks, and the availability and restriction of air
infrastructure and airspace. In scope are track observations, runway availability and airspace
restrictions. Out of scope are identification, threat evaluation and engagement semantics.

Profile domain: `air`.

## Version

```text
profile:         Air
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
air:Aircraft    air:UAV        the things observed
air:Airfield    air:Runway     the infrastructure whose availability moves
air:Airspace                   the volume a restriction applies to
air:AirTrackObservedEvent  air:RunwayAvailabilityChangedEvent  air:AirspaceRestrictionChangedEvent
```

`air:Runway` is a distinct concept from `air:Airfield` because a runway's availability moves
independently of the facility that holds it, which is the reason the governed type names the runway
as its subject. Each term is governed, each is in the packaged ontology-term registry, and an
annotation never determines an entity's structural `entity_type` (`../09-entity-semantics.md`).

## Event types in scope

Three governed types are in scope for v0.1.0, in the `air` domain, spanning
`OBSERVATION`, `STATE_CHANGE` and `CONSTRAINT`.

```text
sc.air.air_track_observed.v1
sc.air.runway_availability_changed.v1
sc.air.airspace_restriction_changed.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span three classes, `OBSERVATION`, `STATE_CHANGE` and `CONSTRAINT`.

The three classes are three different assertions and the profile keeps them apart.
An air track observed is something a sensor perceived. A runway's availability changing is a change
in what *is*. An airspace restriction changing is a change in what may be *done* — which is why it
is `CONSTRAINT` and not `STATE_CHANGE`, and the distinction is the one a consumer routes on.

## Payload semantics

No type in this profile has a registered payload model in v0.1.0 — one governed type in the
whole specification has one, and it is not in this profile (`../03-event-types.md`). Payloads here
are free-form and
transportable, extra source fields survive, and nothing validates their shape — which is deliberate
while the shapes are still being learned from real sources rather than fixed in advance. The
examples show the fields a producer in this profile would naturally carry; they are illustrative,
not a schema, and a consumer must not treat them as one.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id`.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Conventions for this profile, stated as conventions and not as requirements:

- a track observation SHOULD carry `geometry` and the observed entity in `related_entities`;
- an availability or restriction change SHOULD carry the previous value in the payload, because
  "changed" without a prior state is a fact a consumer cannot act on;
- `status` SHOULD be set on a restriction whose standing the source manages, and left unset when
  the source reports occurrences rather than managed conditions.

## Temporality

`observed_at` and `received_at` carry their ordinary meanings
(`../04-temporality.md`). The interval fields matter more here than in most profiles: an airspace
restriction that begins at a future instant is the normal case, so `effective_from` and
`effective_to` describe the restriction and are never defaulted to the observation or receipt time.
A restriction whose `effective_to` has passed is not thereby `EXPIRED` — lifecycle is what the
producer says about the assertion, and the interval is what it says about the world
(`../05-lifecycle.md`).

## Entity relations

`core:Concerns` is the ordinary role for the runway, airspace or track an event is
about. `core:Observes` is available for the sensor entity in a track observation, and it says the
subject reported what it perceived of the object — a claim about the reporting, not about what was
there. Every entity named in `oes.entity_relations` must also appear in `related_entities`; the two
lists never disagree about what the event concerns.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no
extension and reserves none. Air sources carry a great deal of vendor and national vocabulary; it
belongs under the producer's own namespace, where it is preserved and never interpreted
(`../11-extensions.md`).

## Security considerations

Air infrastructure availability and airspace restrictions are routinely handled at a
marking, and the markings differ by nation and by exercise. They are transported and never
enforced; presence is not authorization and absence is not proof of unclassified status
(`../10-security-markings.md`). Nothing in this profile makes a marking required.

## Examples

Three, one per governed type:

- `examples/sc-oes/individual/sc.air.air_track_observed.v1.json`
- `examples/sc-oes/individual/sc.air.runway_availability_changed.v1.json`
- `examples/sc-oes/individual/sc.air.airspace_restriction_changed.v1.json`

The third carries an `EXTERNAL_ARTIFACT` evidence reference and a declared effective interval, and
the first carries two entities so that the reporting sensor and the thing reported are separate
objects. All are loaded and validated on every test run by `tests/test_cdm_examples.py`.

## Non-goals

This profile does not model identification, threat evaluation, engagement, air tasking
or flight planning. It does not define a track-correlation algorithm, and it does not say when two
observations are the same track — the CDM's derived identity answers that from the source's own
identifier, and nothing here overrides it.

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event
types. Every adapter this repository ships remains CDM Conformant without being an SC-OES semantic
producer, and that distinction is intentional (`../README.md`). Nothing in this tree should be read
as implying an operational adapter implementation exists for this profile: the examples under
`examples/sc-oes/` were written against the models by hand and name an adapter nothing resolves,
and PNT is the one profile with a reference producer behind it (`pnt.md`).

The profile's state, in the form the packaged registry carries it:

```text
Version:                      0.1.0
Maturity:                     DRAFT
Implementation status:        specification-only
Executable Dimension D rules: not defined in 0.1.0
```

A reader should not have to discover this from a `SKIP` on a command line. The packaged profile
registry (`synapse_cdm/registry/sc_oes/profiles.json`) carries the same four facts in the form a
validator reads, which is how a conformance tool tells this profile — known, and deliberately
without executable rules — from a profile name that does not exist.

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). This profile declares no conformance rules of its own in v0.1.0: every
constraint stated above is either one dimension A, B, C or E already checks — the CDM's structural
contract, the block's core syntax, the governed type's agreement with the registry, and the
recognition of governed ontology terms — or a convention marked SHOULD, which is guidance to a
producer and not a rule to grade against. A D assessment against this profile therefore
has no rules to check, and the permitted claim "SC-OES Air Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.

**Executable Dimension D rules for this profile: not defined in 0.1.0.** That is a scope boundary
and not an unfinished edge: `pnt.md` acquired the specification's first executable rule on
2026-09-07, and the arrangement stated just above is the one it followed. Until this profile does
the same, a dimension D assessment against Air returns `SKIP` with a reason that says so, and
never `PASS` — a profile with no rules is not a profile anything can be conformed to — and never
`FAIL`, which would grade a profile for being deliberately specification-only.
