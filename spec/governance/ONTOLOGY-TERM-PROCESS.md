# Ontology term proposal process

**SC-OES v0.1.0 — Draft.**

This document governs the addition of a term to the SynapseCommand Operational Ontology. The
governed namespace and its grammar are frozen in
`docs/adr/0003-identifier-and-namespace-strategy.md` and restated in
`../sc-oes/09-entity-semantics.md`. A third party does not mint a term in that namespace, and does
not need to: a valid third-party absolute semantic identifier is preserved and reported as
unassessed, never rewritten and never mapped (`../sc-oes/13-conformance.md`, dimension E).

## What a proposal must contain

Normative:

> A proposal for a governed ontology term MUST contain every field below. A proposal missing any
> field is incomplete and is not assessed.

```text
identifier
label
definition
module
parent
relationships
motivation
examples
overlap/conflict analysis
maturity
```

| Field | What it must establish |
|---|---|
| identifier | a term matching the governed grammar, with the fixed authority date |
| label | a short human label |
| definition | what the term denotes — a definition, not a synonym list and not an example |
| module | which ontology module the term belongs in |
| parent | the term it specialises, up to the module's own root |
| relationships | the governed relationships the term participates in, with their directions |
| motivation | what can be said with this term that cannot be said today |
| examples | synthetic examples of things the term does and does not denote |
| overlap/conflict analysis | the nearest existing terms, and why none of them denotes this |
| maturity | the entry maturity, normally `EXPERIMENTAL` |

## Preventing uncontrolled synonym growth

Normative:

> A term MUST NOT be added where an existing governed term already denotes the concept.

> A term MUST NOT be added as an alias, abbreviation, expansion, translation or preferred spelling
> of an existing term.

> A proposal whose overlap and conflict analysis does not name the nearest existing terms is
> incomplete.

*(Non-normative.)* Synonym growth is the way a terminological ontology stops being useful, and it
happens for good reasons every time: a requester's own systems use a different word, and adding
their word is easier than persuading them. The result is a vocabulary in which the same thing has
four identifiers, so a consumer matching one of them silently misses three quarters of the data —
and, unlike a missing term, the damage is invisible. Where a requester's label matters to them, a
label is a property of a term, not a new term; and where the concepts genuinely differ, the
overlap analysis is what shows it.

## The boundaries of the ontology

Normative:

> The ontology is terminological. It defines classes, relationships, hierarchy, labels, definitions
> and stable identifiers.

> The ontology MUST NOT contain real operational instances. No real unit, platform, location,
> callsign, mission or organisation is a term.

> No inference rule, classification rule or entailment is defined in v0.1.0, and a proposal MUST NOT
> require one.

> Runtime does not parse the ontology's source syntax; a term becomes visible to an implementation
> through the generated term registry, which is the machine authority.

`docs/adr/0002-ontology-representation.md` records the representation decision behind the last two
rules.

## Assessment

Normative:

> A proposal MUST be assessed against the fields above, and the assessment MUST name which field, if
> any, it failed.

> A rejection MUST be recorded with its reason, and MUST NOT be deleted.

> An accepted term MUST be added to the ontology module and MUST appear in the generated term
> registry produced from it. The registry MUST NOT be hand-edited to carry a term the ontology does
> not define.

Adding a term is an **additive** change and moves the ontology version, not the SC-OES specification
version (`../sc-oes/01-core.md`).

## Revising and retiring a term

Normative:

> A published identifier MUST NOT be reused for a different meaning, ever.

> Narrowing or repurposing an accepted term's definition is a **breaking** change and MUST take a
> new identifier.

> Widening a definition, adding a label or adding a relationship is assessed per
> `SC-OES-GOVERNANCE.md`, and MUST NOT be combined with a maturity increase.

Retirement is `DEPRECATION-POLICY.md`'s subject.
