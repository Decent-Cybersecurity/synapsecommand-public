# 08 — Event relationships

**SC-OES v0.1.0 — Draft.**

`event_relations[]` carries typed references from this event to other events. Every relation is an
assertion the *producer* makes; SC-OES draws no conclusions from them and resolves no conflicts
between them.

## The vocabulary

The initial governed relationship vocabulary is exactly these seven predicates:

```text
DERIVED_FROM
UPDATES
SUPERSEDES
RESOLVES
RETRACTS
CONTRADICTS
CORRELATES_WITH
```

Each relation names a predicate and a target event identifier. `event_relations[]` is optional, and
an empty or absent list asserts nothing.

Normative:

> The predicate MUST be one of the seven above. An unrecognised predicate is a dimension B failure
> and MUST NOT be interpreted as a nearby one.

## Direction

Five of the seven are directional and are carried by the *later* event. Direction is part of the
predicate's meaning, not a convention a producer may reverse.

| Predicate | Direction | Asserts |
|---|---|---|
| `DERIVED_FROM` | current → source | the source event contributed to producing this assertion |
| `UPDATES` | new → earlier | adds or revises information about substantially the same occurrence |
| `SUPERSEDES` | new → earlier | the newer assertion replaces the earlier one for determining the current representation |
| `RESOLVES` | new → active-condition event | the earlier represented condition has ended |
| `RETRACTS` | new → previous assertion | the producer withdraws the earlier assertion |
| `CONTRADICTS` | conceptually symmetric | the two assertions are materially inconsistent |
| `CORRELATES_WITH` | conceptually symmetric | the two are associated |

### DERIVED_FROM

The source event contributed to producing this assertion.

Normative:

> `DERIVED_FROM` MUST NOT be read as invalidating, replacing or superseding the source event.

The source remains a standing assertion. This is the predicate that carries the
observation-to-assessment chain honestly: the assessment cites the observation and the observation
stays what it was.

### UPDATES

Adds or revises information about substantially the same occurrence.

Normative:

> A consumer MUST NOT treat an `UPDATES` relation as a complete replacement of the earlier event.

An update may add one field, correct one value, or extend a description. Which parts changed is
determined by comparing the two events, not by assuming the newer one is total. A producer that
does intend total replacement asserts `SUPERSEDES`.

### SUPERSEDES

The producer intends the newer assertion to replace the earlier one for the purpose of determining
the current representation. The earlier assertion remains in history and MUST NOT be deleted
(`04-temporality.md`).

### RESOLVES

The producer asserts that the earlier represented condition has ended. `RESOLVES` is about the
world; `RETRACTS` is about the assertion.

### RETRACTS

The producer withdraws a previous assertion — it should not have been made, or was made in error.

Normative:

> A retracted event MUST remain historically visible.

A retraction is a new fact about an old assertion, not an erasure of it. A consumer that deleted the
retracted event would lose the record that anybody ever asserted it, which is the thing a
retraction most needs to preserve.

### CONTRADICTS

The producer asserts that two assertions are materially inconsistent.

Normative:

> SC-OES does not decide which assertion is correct, and an implementation MUST NOT resolve a
> contradiction by preferring the newer, the more confident, or the more trusted producer.

Conceptually symmetric: if A contradicts B then B contradicts A, whether or not both events carry
the relation. A producer asserts it on the event it is publishing.

### CORRELATES_WITH

The producer asserts association, and nothing more.

Normative:

> `CORRELATES_WITH` MUST NOT be read as asserting derivation, causality, replacement or
> contradiction.

Conceptually symmetric. It is the weakest predicate and exists so that a producer with a real but
uncharacterised association has somewhere honest to put it, rather than reaching for a stronger
predicate it cannot support.

## Validation

Normative:

> An implementation MUST reject:
> - a self-reference — a relation whose target is the citing event;
> - a duplicate identical relationship — the same predicate to the same target, twice;
> - a malformed event identifier.

> An implementation MUST permit references to events that are not locally available.

The last rule is what makes SC-OES usable across systems at all. A consumer holds a subset of the
history by definition, and rejecting an event because its antecedent has not arrived would make
delivery order part of the contract.

### Cycles

Normative:

> Where a supplied local bundle makes them detectable, an implementation MUST reject `SUPERSEDES`
> cycles and `DERIVED_FROM` cycles.

Both predicates assert a strict ordering — one assertion replaces an earlier one, one assertion was
produced from an earlier one — so a cycle in either is incoherent rather than merely unusual.

The check is bounded by what the caller supplied. A validator examines the events it was given
together, and it does not fetch, query or accumulate history to look further.

Normative:

> An implementation MUST NOT introduce a graph database, a triple store or a persistent event graph
> in order to perform these checks.

*(Non-normative.)* The cycle rule is deliberately conditional, which reads at first like a weak
rule. It is the only honest one: a producer emitting a single event cannot know whether its
supersession chain closes, and a specification that required the global answer would either require
every consumer to hold the whole graph or be quietly unenforced. What is enforceable is that a
validator handed a bundle notices a cycle inside it — which catches the realistic mistake, a
producer emitting a mutually superseding pair.

## Relationships are not caps

There is no normative maximum length for `event_relations[]` in v0.1.0. `11-extensions.md` states
the distinction between interoperability rules and deployment resource policies, and
`14-security-considerations.md` names relationship abuse as a threat a deployment bounds locally.
