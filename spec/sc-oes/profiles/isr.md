# SC-OES ISR Profile

**SC-OES ISR Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

## Scope

Intelligence, surveillance and reconnaissance, in one narrow sense for v0.1.0: the
revision of a threat judgement, and the sources that stand behind it. In scope is the assessment
itself, with its evidence and its provenance. Out of scope are collection management, sensor
tasking, and the raw observations an assessment is drawn from — those are observations in the
domain that produced them.

Profile domain: `isr`.

## Version

```text
profile:         ISR
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
isr:ISRSource                    a source contributing to an assessment
isr:ThreatAssessmentUpdatedEvent the event class the governed type is annotated with
core:ThreatSource                what an assessment may name as threatening
```

`core:ThreatSource` is a core term rather than an ISR one on purpose: being assessed as a threat is
an attribution some assessment made, and the attribution belongs to that assessment rather than to
the thing. The same entity is annotated `pnt:InterferenceSource` by the observation that measured
it and `core:ThreatSource` by the assessment that judged it, and both annotations are true of
different claims.

## Event types in scope

One governed type is in scope for v0.1.0, in the `isr` domain.

```text
sc.isr.threat_assessment_updated.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span a single class, `ASSESSMENT`.

`ASSESSMENT` is the class this whole specification exists to keep separate from
`OBSERVATION`. An assessment is an interpretation somebody is responsible for; it is never inferred
from the observations behind it, and a consumer must be able to tell the two apart without reading
the payload (`../02-event-classes.md`). The observations are carried as evidence and as
`DERIVED_FROM` relationships, which is what makes the chain auditable in the direction that
matters: from the judgement back to what it rests on.

## Payload semantics

No type in this profile has a registered payload model in v0.1.0. Payloads are free-form
and transportable. The example carries the threat in the source's own words, the assessed level,
the previous level and who assessed it; the last of those is the field that makes the record
attributable, and an assessment nobody owns is the shape this profile is trying to prevent.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id`.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Conventions, stated as conventions and not as requirements, and this profile has
more of them than most because an assessment is the case where absence is least informative:

- `confidence` SHOULD be set, on the producer's own scale, because a judgement offered without one
  invites the consumer to supply a confidence of its own;
- `verification` SHOULD be set, and it is not confidence: they vary independently, and a single
  high-grade source can be confident and entirely uncorroborated (`../06-verification-and-confidence.md`);
- `evidence` SHOULD carry what the assessment rests on — `EVENT` for a local antecedent,
  `SOURCE_RECORD` for the producer's own working record, `EXTERNAL_ARTIFACT` for anything outside;
- an assessment that revises an earlier one SHOULD carry `UPDATES` or `SUPERSEDES`, whichever it
  means, and the two are not interchangeable (`../08-event-relationships.md`).

## Temporality

`observed_at` on an assessment is when the assessment was made, not when the thing
assessed was observed — the observation carries its own instant and is reachable through the
evidence. `effective_from` and `effective_to` describe how long the judgement is offered as
standing, when the producer states such a window; neither is defaulted
(`../04-temporality.md`).

## Entity relations

`core:Threatens` is the characteristic role here: the subject is assessed to be
capable of harming the object, and the word "assessed" is doing the work. `core:Concerns` remains
available when the producer means less than that. As everywhere, an entity given a role must also be
in `related_entities`.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no
extension and reserves none. An assessment method, an analyst identifier or a house confidence scale
goes under the producer's own namespace, and nothing in this repository reads inside the value
(`../11-extensions.md`).

## Security considerations

Assessments are the events most likely to arrive marked, and the marking usually says
more about the source than about the subject. It is transported, never enforced, and its absence is
never proof of unclassified status (`../10-security-markings.md`). This profile makes no marking
required and defines no scheme; the scheme is the marking's own.

## Examples

`examples/sc-oes/individual/sc.isr.threat_assessment_updated.v1.json` — an assessment with
confidence, verification, a `SOURCE_RECORD` evidence reference, a transported security marking and
a third-party extension, which together make it the one example that exercises most of the block.
The linked chain (`examples/sc-oes/chain/gnss-interference-to-route-change.json`) carries the same
type as its second event, deriving from the PNT observation before it. Both are loaded and
validated on every test run by `tests/test_cdm_examples.py`.

## Non-goals

This profile does not manage collection, does not task sensors, does not define a threat
taxonomy or a severity scale, and does not compute an assessment from observations. It contains no
reasoning: the chain in `examples/` is written down, not generated, and nothing in this repository
generates one.

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
has no rules to check, and the permitted claim "SC-OES ISR Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.

**Executable Dimension D rules for this profile: not defined in 0.1.0.** That is a scope boundary
and not an unfinished edge: `pnt.md` acquired the specification's first executable rule on
2026-09-07, and the arrangement stated just above is the one it followed. Until this profile does
the same, a dimension D assessment against ISR returns `SKIP` with a reason that says so, and
never `PASS` — a profile with no rules is not a profile anything can be conformed to — and never
`FAIL`, which would grade a profile for being deliberately specification-only.
