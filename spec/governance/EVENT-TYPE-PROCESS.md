# Event type proposal process

**SC-OES v0.1.0 — Draft.**

This document governs the addition of a governed `sc.*` event type. Third parties do not mint `sc.*`
types (`../sc-oes/03-event-types.md`); a third party who needs a semantic type of their own mints it
under `x.*`, which requires no proposal and no permission, and may propose a governed type in
parallel if the concept is genuinely shared.

## What a proposal must contain

Normative:

> A proposal for a governed event type MUST contain every field below. A proposal missing any field
> is incomplete and is not assessed.

```text
proposed ID
title
definition
motivation
domain
profile
EventClass
maturity
ontology class
legacy EventType mapping
payload semantics
temporality
entity relationship semantics
security considerations
extension considerations
example
overlap analysis
backward-compatibility analysis
```

| Field | What it must establish |
|---|---|
| proposed ID | a `type_id` matching the governed grammar, ending in `.v1` for a new concept |
| title | a short human label |
| definition | what the event asserts, in one or two sentences, without reference to any one producer's implementation |
| motivation | what a consumer can do with this that it cannot do today |
| domain | the `lower_label` domain segment of the identifier |
| profile | which profile the type belongs to |
| EventClass | one of the eight, and why that one rather than its neighbour |
| maturity | the entry maturity, normally `EXPERIMENTAL` |
| ontology class | the governed ontology class the event corresponds to, or the term proposal that will create it |
| legacy EventType mapping | the mapping, or an explicit null with the reason there is none |
| payload semantics | what the payload carries; whether a model is proposed, or the payload stays free-form |
| temporality | which of the four instants are meaningful, and whether an effective interval applies |
| entity relationship semantics | which entities the event relates, and what roles they play |
| security considerations | what an adversary gains by asserting this falsely, and whether it carries markings |
| extension considerations | what producers will want to add, and whether that argues for a core concept instead |
| example | a complete, synthetic example using the reserved identifiers in `../sc-oes/00-conventions.md` |
| overlap analysis | the closest existing governed type, and why it does not serve |
| backward-compatibility analysis | what breaks for an existing consumer, which for a new type should be nothing |

## The two rules that do the refusing

Normative:

> An event type MUST NOT be added because a single customer or consumer uses a particular label.

> A proposal whose overlap analysis does not name the closest existing type is incomplete.

*(Non-normative.)* The first rule is the one that keeps the registry interoperable. A type added per
label produces a registry that is a list of other people's field names — and since no two producers
chose the same name, nothing in it is interoperable, which is the exact opposite of the reason a
governed registry exists. The honest answer to a label is usually one of: an existing governed type
already says this; the concept is real but the label is local, so the governed type takes a neutral
name; or the concept is genuinely private, in which case `x.*` is the correct namespace and costs
the proposer nothing.

The second rule exists because "nothing similar exists" is the most common sentence in a proposal
and the least often true. Naming the nearest neighbour and saying why it does not serve is either
easy or it is the discovery that the proposal is unnecessary.

## Assessment

Normative:

> A proposal MUST be assessed against the fields above, and the assessment MUST name which field, if
> any, it failed.

> A rejection MUST be recorded with its reason, and MUST NOT be deleted.

> An accepted type MUST be added to the packaged event registry, which is the machine authority for
> its class, maturity, ontology class, payload model and legacy mapping.

> The human index in `../sc-oes/03-event-types.md` and the owning profile MUST be updated in the same
> change that adds the registry entry.

Adding a governed type is an **additive** change (`SC-OES-GOVERNANCE.md`): it raises no version. The
owning profile's version moves, because its scope changed.

## Revising an accepted type

Normative:

> A published semantic major MUST NOT be redefined (`../sc-oes/12-versioning.md`).

> A breaking revision MUST take a new semantic major, proposed through this process as a new type
> with the earlier one named in its overlap analysis and its backward-compatibility analysis.

> A non-breaking clarification of an accepted type's definition MUST be classified per
> `SC-OES-GOVERNANCE.md`, and MUST NOT be made in the same change that raises the type's maturity.

Retirement is `DEPRECATION-POLICY.md`'s subject, and a retired identifier is never reused.
