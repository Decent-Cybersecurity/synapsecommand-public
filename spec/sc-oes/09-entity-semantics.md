# 09 — Entity semantics

**SC-OES v0.1.0 — Draft.**

Two additions, one on the event and one on the entity. Both attach *meaning* to structure the CDM
already carries, and neither replaces it.

## Entity relations on the event

The CDM `Event` already carries `related_entities[]`: which entities this event is about. SC-OES
adds `entity_relations[]`: *what role* each of them plays.

Each entry carries:

```text
entity_id
predicate
```

Normative:

> Every `entity_id` in `entity_relations[]` MUST also appear in the event's `related_entities[]`.

> `predicate` MUST be an absolute semantic identifier. A bare word, a local name or a
> relative reference is a dimension B failure.

The first rule is the load-bearing one. `related_entities[]` remains the single answer to "which
entities does this event concern", so a consumer that reads only the CDM sees every entity involved,
and a consumer that reads SC-OES sees the same set with roles attached. A role naming an entity the
event does not otherwise relate to would make the two lists disagree about the event's scope.

*(Example.)* An airspace restriction event relates `AREA-ALPHA` and `AIRBASE-ALPHA` in
`related_entities[]`, and asserts a role for one of them:

```text
entity_id:  AIRBASE-ALPHA
predicate:  tag:synapsecommand.com,2026-09-06:ontology:core:Affects
```

## Ontology annotations on the entity

The CDM `Entity` carries `entity_type`, a closed structural classification, and that remains
unchanged and authoritative for what kind of record an entity is. SC-OES adds an optional
`ontology_types` list carrying absolute semantic identifiers.

Normative:

> `ontology_types` MUST contain absolute semantic identifiers, and MUST NOT contain duplicates.

> `entity_type` MUST NOT be derived from `ontology_types`, and `ontology_types` MUST NOT be derived
> from `entity_type`.

*(Example.)*

```text
entity_type:      FACILITY
ontology_types:
  - tag:synapsecommand.com,2026-09-06:ontology:air:Runway
```

`FACILITY` says how the record behaves in the canonical model. The ontology identifier says what the
thing *is* in operational terms. A system that only understands the CDM handles the entity
correctly; a system that also understands the ontology knows it is a runway.

## Governed and third-party identifiers

The governed ontology namespace is frozen in
`docs/adr/0003-identifier-and-namespace-strategy.md` (decision 9):

```text
^tag:synapsecommand\.com,2026-09-06:ontology:[a-z][a-z0-9_]*:[A-Z][A-Za-z0-9]*$
```

The authority date `2026-09-06` is fixed for the lifetime of the v0.1 ontology namespace. It is not
shortened, not derived at runtime, and not changed for later ontology versions.

Normative:

> A third party MUST NOT mint a term in the governed namespace above.

> A valid third-party absolute semantic identifier MUST be preserved, MUST NOT be rewritten, and
> MUST NOT be mapped onto a governed term.

> An identifier in the governed namespace that names a term absent from the packaged ontology-term
> registry is a dimension E failure. It MUST NOT be interpreted, and MUST NOT be treated as a
> third-party term.

The reserved-namespace rule and the third-party rule are the same rule seen from two sides: an
identifier claiming this project's authority is held to this project's registry, and an identifier
claiming somebody else's authority is left alone. `13-conformance.md` carries the complete verdict
table, including the case where an object's identifiers are all valid and all third-party.

Normative:

> Third-party identifiers are opaque. No implementation of this specification performs a fetch, a
> DNS resolution, a filesystem or data-URI read, a redirect, an RDF load, an automatic mapping, or
> any inference from the identifier string.

## Adapters

Normative:

> An adapter MUST NOT emit an entity relation or an ontology annotation that its source semantics do
> not justify.

An adapter is a translator. Where a source says an event affects a facility, the adapter may say so;
where the source merely mentions the facility, the adapter relates the entity and asserts no role.
An unasserted role is the correct output, not a gap to be filled by the most plausible predicate.

*(Non-normative.)* This is the same rule as the observation/assessment prohibition in
`02-event-classes.md`, applied to the entity graph. It is easy to break here because a plausible
predicate is usually available and the guess is usually right — and a graph in which some edges are
source-asserted and some are adapter-invented, with nothing distinguishing them, cannot be reasoned
over by anybody downstream.
