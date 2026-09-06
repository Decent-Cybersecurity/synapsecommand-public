# 15 — Governance

**SC-OES v0.1.0 — Draft.**

SC-OES is intended to evolve as a public specification, so governance is part of the product rather
than an administrative addendum. This document states the normative rules; the process documents in
`../governance/` say how a proposal is actually made and handled.

## What is governed

| Governed thing | Process document | Machine authority |
|---|---|---|
| governed `sc.*` event types | `../governance/EVENT-TYPE-PROCESS.md` | the packaged event registry |
| governed ontology terms | `../governance/ONTOLOGY-TERM-PROCESS.md` | the packaged ontology-term registry |
| profiles | `../governance/PROFILE-PROCESS.md` | the profile documents and their registry representation |
| deprecation of any of the above | `../governance/DEPRECATION-POLICY.md` | the registries' own deprecation fields |
| this specification's own text | `../governance/SC-OES-GOVERNANCE.md` | this tree |
| security reports | `../governance/SECURITY-REPORTING.md` | — |

## The rules that hold across every process

Normative:

> A governed identifier MUST NOT be minted without a completed proposal carrying every field its
> process document requires.

> A published identifier MUST NOT be reused for a different meaning, ever.

> A breaking change to a governed semantic definition MUST take a new identifier or a new semantic
> major. It MUST NOT be applied to the existing one.

> A document MUST NOT be maintained as a second hand-authored copy of a packaged registry. Where a
> document and a registry disagree, the registry is the authority and the document is corrected at
> the sentence that disagrees.

> A proposal MUST be recorded whether it is accepted or rejected, with the reason.

The last rule is what makes the vocabulary defensible later. A rejected event type with a recorded
reason answers the next person who proposes it; a rejection that left no trace gets re-proposed until
somebody accepts it out of fatigue.

## Two rules against uncontrolled growth

Normative:

> An event type MUST NOT be added because a single consumer or customer uses a particular label.

> An ontology term MUST NOT be added where an existing term already denotes the concept.

*(Non-normative.)* These are the two ways a governed vocabulary dies, and they are opposites. Adding
a type per label produces a registry that is a list of other people's field names, in which nothing
is interoperable because no two producers chose the same one. Adding a synonym per requester
produces a vocabulary where the same thing has four names and every consumer has to know all four.
Both look accommodating at the time. The alternative is not refusal: it is an overlap analysis that
either finds the existing term, or shows there is genuinely nothing that says this, which is exactly
the case a proposal needs to make.

## Overlap analysis is mandatory

Normative:

> An event-type proposal MUST carry an overlap analysis against the existing governed set, and a
> backward-compatibility analysis.

> An ontology-term proposal MUST carry an overlap and conflict analysis against the existing
> vocabulary.

An overlap analysis names the closest existing item and says why it does not serve. "Nothing similar
exists" is an analysis only where it is demonstrated.

## Maturity is a governance instrument

`12-versioning.md` defines the four maturity values. Governance uses them rather than delaying
publication:

- a new definition normally enters as `EXPERIMENTAL`;
- it moves to `DRAFT` when its shape has survived use;
- it moves to `STABLE` only when its meaning can be frozen, because `STABLE` is a promise this
  specification then has to keep;
- it moves to `DEPRECATED` under `../governance/DEPRECATION-POLICY.md`, never by deletion.

Normative:

> A maturity MUST NOT be raised in the same change that alters the definition's meaning.

Raising maturity is a statement that the meaning has held still. Doing both at once makes the
statement false at the moment it is made.

## What governance does not decide

Normative:

> Governance decides what the governed vocabulary contains and what each item means. It does not
> decide whether a particular producer's assertion is true, which of two contradictory assertions is
> correct, or whether a deployment may act on an event.

Those are the consumer's, under `13-conformance.md`'s and `14-security-considerations.md`'s limits.

## Status of this governance in v0.1.0

*(Non-normative.)* v0.1.0 is a draft published by one maintaining organisation. There is no
independent governance body, no membership, no voting procedure and no external appeal, and none is
implied by the word "governance" here: the process documents describe what a proposal must contain
and how it is recorded, which is the part that has to exist before anybody can propose anything.
Whether a wider governance structure is appropriate is a question for a later version, and it is not
answered by this one.
