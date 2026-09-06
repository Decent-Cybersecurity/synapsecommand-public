# 10 — Security markings

**SC-OES v0.1.0 — Draft.**

`security` is an optional, generic transport structure for handling markings. This document's main
work is stating what it is not.

## The structure

```text
scheme
classification
releasability[]
caveats[]
originator
marking_extras
```

| Field | Meaning |
|---|---|
| `scheme` | which marking system these values belong to |
| `classification` | the classification value, as that scheme spells it |
| `releasability[]` | releasability values, as that scheme spells them |
| `caveats[]` | caveat values, as that scheme spells them |
| `originator` | the originator, as that scheme identifies them |
| `marking_extras` | scheme-specific values with no generic counterpart |

Normative:

> `scheme` identifies the marking system. Every other value in the structure is interpreted **only**
> relative to its `scheme`, and MUST NOT be compared across schemes.

> Marking values MUST be transported verbatim. An implementation MUST NOT translate, normalise,
> abbreviate, expand, case-fold or reorder them.

> SC-OES defines no marking vocabulary, no ordering over classifications, and no marking scheme.

The structure is a *carrier*. Two markings from different schemes are not comparable, and two
markings from the same scheme are comparable only by something that knows that scheme.

## The central rule

Normative:

> SC-OES transports markings. It does not interpret or enforce them.

And, stated as the three propositions most often assumed away:

```text
presence of a marking  !=  authorization
absence of a marking   !=  proof of unclassified status
transport of a marking !=  enforcement of it
```

Normative:

> SC-OES is not a cross-domain guard, and MUST NOT be represented as one.

> An implementation MUST NOT make a release, routing, filtering or access decision on the basis of
> this structure by virtue of conformance to this specification.

A deployment that enforces markings does so with its own accredited mechanism, which knows the
scheme, holds the policy, and is answerable for the decision. That mechanism may read this
structure. It does not inherit any authority from it.

*(Non-normative.)* The reason for stating this negatively and at length is that a marking field
invites exactly one mistake: a consumer sees `classification` populated, concludes that something in
the pipeline is enforcing it, and relaxes a check accordingly. Nothing in this specification enforces
anything. An unmarked event may be highly sensitive — the producer may simply not have marked it —
and a marked one may be freely releasable under a policy this structure knows nothing about.

## Validation

Dimension B checks the *structure* only: that the fields present are the declared ones, that the
list-valued fields are lists, and that values are strings of the declared shape.

Normative:

> No conformance dimension asserts that a marking value is valid within its scheme, that a
> classification is permitted for a producer, or that a releasability set is consistent.

> An absent `security` structure MUST NOT be reported as a conformance failure by any dimension.

## Markings and the rest of the block

Normative:

> `confidence`, `verification` and `status` MUST NOT be used as inputs to a handling decision, and a
> marking MUST NOT be inferred from any of them.

> An extension MUST NOT be interpreted as a marking, and MUST NOT be used to extend, override or
> qualify the `security` structure. `marking_extras` is where scheme-specific marking values go.

`14-security-considerations.md` names security-marking misuse among the threats and says which side
of the trust boundary it falls on.
