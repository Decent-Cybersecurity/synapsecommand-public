# SC-OES Governance

**SC-OES v0.1.0 — Draft.**

This document governs how SC-OES itself changes. The four proposal and retirement processes are
separate documents in this directory; `../sc-oes/15-governance.md` carries the normative rules that
hold across all of them.

## What this directory governs

| Governed thing | Process |
|---|---|
| a governed `sc.*` event type | `EVENT-TYPE-PROCESS.md` |
| a governed ontology term | `ONTOLOGY-TERM-PROCESS.md` |
| a profile | `PROFILE-PROCESS.md` |
| retirement of any of the above | `DEPRECATION-POLICY.md` |
| a security report against this specification or its implementation | `SECURITY-REPORTING.md` |
| the normative text under `../sc-oes/` | this document |

## Status of governance in v0.1.0

*(Non-normative, and stated first so nothing below is over-read.)* v0.1.0 is a draft published by one
maintaining organisation. There is no independent governance body, no membership, no voting
procedure, no external appeal and no certification programme, and none is implied by the word
"governance". What these documents establish is what a proposal must contain, how it is assessed,
and that it is recorded either way — the part that has to exist before anybody outside the project
can propose anything at all. Whether a wider structure is appropriate is a question for a later
version.

## Change classes

Every change to the normative text under `../sc-oes/` is exactly one of these, and the class decides
what it costs:

| Class | Example | Consequence |
|---|---|---|
| **editorial** | fixing a typo, clarifying without changing meaning, correcting a cross-reference | no version change |
| **additive** | a new governed event type, a new ontology term, a new optional concept | no SC-OES version change; the registries and the affected profile move |
| **substantive** | changing what an existing field or verdict means | a new SC-OES specification version |
| **breaking** | narrowing, redefining or repurposing an existing governed definition | a new identifier or semantic major; never applied to the existing one |

Normative:

> A change MUST be classified before it is made, and the classification MUST be recorded with it.

> A substantive or breaking change MUST NOT be introduced as an editorial one. Where the class is
> arguable, the higher class applies.

> An editorial change MUST NOT alter a normative statement's meaning, a grammar, a truth table, an
> exit code, a vocabulary or a bound. A change to any of those is at least substantive.

*(Non-normative.)* The failure this taxonomy guards against is the clarification that quietly
narrows. A sentence rewritten "for readability" that turns a `MAY` into a `SHOULD`, or that adds a
condition to a verdict, costs an implementer a re-read of code they believed was correct — and it
arrives with no version change to warn them. Classifying first is what makes that visible while it
is still a choice.

## Records are append-only in tense

Normative:

> A dated statement in a governance or specification record that has become false gains a dated
> correction beside it. It is not edited to read as though it had always been right.

> A rejected proposal MUST be recorded with its reason, and MUST NOT be deleted.

This is the repository's own convention for records, applied here for the same reason: the value of
a rejection is that the next person proposing the same thing finds the argument rather than
re-running it.

## The machine authorities always win

Normative:

> Where the normative text and a packaged registry disagree about a governed type's class, maturity,
> ontology class, payload model or legacy mapping, the registry is the authority. The text is a
> defect and is corrected at the sentence that disagrees.

> A specification document MUST NOT be maintained as a second hand-authored copy of a registry.

A correction is never made by moving a derivation to match a stale figure, and never by editing the
registry to agree with prose that was wrong.

## Who decides, and on what basis

In v0.1.0 the maintaining organisation decides. What constrains the decision is written down rather
than left to judgement:

Normative:

> A proposal MUST be assessed against the requirements in its own process document, and the
> assessment MUST name which requirement, if any, it failed.

> A proposal MUST NOT be accepted because of who made it, and MUST NOT be rejected for that reason
> either.

> An event type MUST NOT be added because a single consumer or customer uses a particular label
> (`EVENT-TYPE-PROCESS.md`).

## Conflict with a stronger repository invariant

*(Non-normative.)* SC-OES is published from a repository with its own invariants — a strict canonical
model, generated schemas, deterministic identity, a versioning discipline and a gate suite that
enforces them. Where this specification would require something one of those invariants forbids, the
repository wins and the conflict is recorded rather than resolved by weakening the invariant. This
has happened already during implementation and the resolutions are in the Architecture Decision
Records under `docs/adr/`, which are the reasoning of record for the decisions this specification
restates.

## Changing this document

Normative:

> A change to this document, or to any process document in this directory, is at least a substantive
> change and follows the rules above.
