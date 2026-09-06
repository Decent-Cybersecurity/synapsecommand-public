# 03 — Event types

**SC-OES v0.1.0 — Draft.**

`type_id` names the *governed semantic contract* an event claims. `event_class` says what kind of
assertion it is; `type_id` says which specific, versioned, documented assertion.

## The two namespaces

```text
sc.<domain>.<event_name>.v<major>
x.<namespace>.<domain>.<event_name>.v<major>
```

The `sc.` namespace is reserved for event types governed by this specification. The `x.` namespace
is for third parties.

Normative:

> A third party MUST NOT mint a `sc.*` event type.

> A `type_id` MUST match one of the two grammars exactly.

The grammars are frozen in `docs/adr/0003-identifier-and-namespace-strategy.md` (decision 9). One
production is shared by every namespaced surface in SC-OES:

```text
lower_label = [a-z][a-z0-9_]*
```

ASCII lowercase only; the first character is a letter; later characters are letters, digits or
underscore. `domain`, `event_name` and `namespace` are each a `lower_label`; `major` is a positive
base-10 integer with no leading zero. Equivalently, and normatively:

```text
^sc\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.v[1-9][0-9]*$
^x\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.v[1-9][0-9]*$
```

An implementation MAY parse structurally instead of applying these expressions; the accepted
language MUST be the same one.

Normative:

> Nothing is normalised, case-folded or trimmed on the producer's behalf. `ACME`, `radar-quality`,
> `v01`, `v0` and an identifier with surrounding whitespace are invalid, and MUST be refused rather
> than repaired.

*(Non-normative.)* `v0` and `v01` are refused by the `v[1-9][0-9]*` production itself rather than by
a second check, so there is one place to read the rule. The character ranges are written out rather
than spelled with a shorthand class, because the obvious shorthand matches non-ASCII in at least
one widely used regex implementation and two validators would then accept different languages
without either looking wrong. The ADR records the same reading about end-of-string anchors.

A `type_id` matching neither grammar is a **syntax** defect: dimension B fails and dimension C is
skipped, so one malformed character produces one finding rather than two
(`13-conformance.md`).

## The registry, and where it lives

Every governed type is an entry in the packaged machine registry:

```text
synapse_cdm/registry/sc_oes/event_types.json
```

Normative:

> The packaged event registry is the machine authority for every governed event type's class,
> maturity, ontology class, payload model and legacy mapping. Where this document and the registry
> disagree, the registry is correct and this document is a defect at the sentence that disagrees.

The registry is written in a later round and is not maintained as a copy of the table below; the
table is the human index of the same governed set. Each registry entry carries:

```text
id
title
description
domain
profile
profile_version
event_class
maturity
ontology_class
payload_model
legacy_event_type
introduced_in
deprecated
replacement
```

Normative:

> `legacy_event_type` MUST be present on every entry, including when its value is null.

A missing key and an explicit null are different facts: the first says nobody considered the
mapping, the second says somebody considered it and there is none.
`docs/adr/0007-legacy-eventtype-mapping.md` governs what those mappings are and what a mismatch
means.

Helper access is provided so that consumers need not depend on packaged file paths; the helper
surface is defined by the round that adds it.

## The thirteen initial governed types

Thirteen governed types are defined in v0.1.0. Class and maturity are normative; both are also
carried by the registry, which is the machine authority.

| `type_id` | Domain | `event_class` | Maturity |
|---|---|---|---|
| `sc.pnt.gnss_interference.v1` | PNT | `OBSERVATION` | `DRAFT` |
| `sc.air.air_track_observed.v1` | Air | `OBSERVATION` | `DRAFT` |
| `sc.air.runway_availability_changed.v1` | Air | `STATE_CHANGE` | `DRAFT` |
| `sc.air.airspace_restriction_changed.v1` | Air | `CONSTRAINT` | `DRAFT` |
| `sc.logistics.supply_threshold_reached.v1` | Logistics | `STATE_CHANGE` | `DRAFT` |
| `sc.logistics.route_availability_changed.v1` | Logistics | `STATE_CHANGE` | `DRAFT` |
| `sc.isr.threat_assessment_updated.v1` | ISR | `ASSESSMENT` | `EXPERIMENTAL` |
| `sc.c2.system_availability_changed.v1` | C2 | `STATE_CHANGE` | `DRAFT` |
| `sc.mission.mission_status_changed.v1` | Mission | `STATE_CHANGE` | `DRAFT` |
| `sc.mission.operational_impact_assessed.v1` | Mission | `IMPACT` | `EXPERIMENTAL` |
| `sc.decision.recommendation_created.v1` | Decision | `RECOMMENDATION` | `EXPERIMENTAL` |
| `sc.decision.decision_recorded.v1` | Decision | `DECISION` | `EXPERIMENTAL` |
| `sc.decision.action_authorized.v1` | Decision | `ACTION` | `EXPERIMENTAL` |

Eight are `DRAFT` and five are `EXPERIMENTAL`; `12-versioning.md` defines what each maturity
commits this specification to. All eight event classes are exercised by the initial set, which is
how the vocabulary in `02-event-classes.md` is grounded rather than aspirational.

## Payloads

Payload typing is deliberately narrow in v0.1.0.

Normative:

> Where a governed type has a registered payload model, a conformant producer's payload MUST
> validate against it. Validation is a check, not a transformation: it MUST NOT rewrite, coerce,
> reorder or drop payload content.

> Where a governed type has no registered payload model, its payload remains free-form and extra
> source-specific fields MUST survive.

Exactly one governed typed payload exists in v0.1.0, for `sc.pnt.gnss_interference.v1`, and it
reuses the CDM's existing GNSS-interference payload model rather than duplicating it. The other
twelve types remain free-form until their semantics are stable enough to govern; their profiles may
describe the concepts a payload is expected to carry without freezing a model.

*(Non-normative.)* Typing all thirteen now would freeze twelve contracts on the strength of one
implementation each, and a payload model is harder to widen than a document. A free-form payload
with a documented expectation costs a consumer a little work; a wrong frozen model costs a semantic
major.

## Unknown types

A syntactically valid `x.*` type is a third party's governed contract, not this repository's.

Normative:

> A valid unknown `x.*` event MUST remain transportable: it survives validation, serialization and
> round-trip unaltered.

> A consumer MUST NOT silently convert an unknown `x.*` type into a known `sc.*` type, or into any
> other type.

An unknown `sc.*` type is a different situation, and is a failure: the namespace is reserved, so an
unrecognised member of it is either a producer inventing governed semantics or a consumer running
against a stale registry. Either way it MUST NOT be interpreted. `12-versioning.md` gives the full
unknown-semantics behaviour, including the case where only the semantic major is unrecognised.
