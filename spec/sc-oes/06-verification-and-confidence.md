# 06 — Verification and confidence

**SC-OES v0.1.0 — Draft.**

Two optional fields, two different questions, and the whole of this document is the insistence that
they are not one field.

## Verification

`verification` is optional. Where present it MUST be one of:

```text
UNVERIFIED
CORROBORATED
VALIDATED
DISPUTED
```

| Value | Meaning |
|---|---|
| `UNVERIFIED` | no corroboration has been sought or found |
| `CORROBORATED` | at least one independent source or observation agrees |
| `VALIDATED` | a process the producer trusts has confirmed the assertion |
| `DISPUTED` | at least one source or process disagrees |

Normative:

> A producer MUST NOT assert a verification state its source semantics do not establish.

> An implementation MUST NOT default `verification` to `UNVERIFIED`.

An absent `verification` means nothing is asserted about corroboration. `UNVERIFIED` is a positive
assertion that the question was asked and the answer is "not corroborated", which is a different
and more informative fact.

`CORROBORATED`, `VALIDATED` and `DISPUTED` are claims about *other* information, so the evidence
that supports them belongs in `evidence[]` (`07-provenance-and-evidence.md`) or in an event relation
(`08-event-relationships.md`).

Normative:

> `DISPUTED` MUST NOT be interpreted as a verdict. It records that a disagreement exists.

SC-OES does not decide which of two disagreeing assertions is correct; that is the same refusal
`CONTRADICTS` makes.

## Confidence

`confidence` is optional. Where present:

```text
0.0 <= confidence <= 1.0
```

Normative:

> `confidence` MUST lie within the closed interval `[0.0, 1.0]`. A value outside it is a dimension B
> failure.

> A null or absent `confidence` means **unknown**. It MUST NOT be treated as `0.0`, and MUST NOT be
> replaced with a default.

> This specification does not define a universal confidence algorithm, and a consumer MUST NOT
> assume one.

`confidence` is the producer's own number, on the producer's own scale. Two producers' values are
comparable only where a profile or a deployment agreement says how.

*(Non-normative.)* The public contract deliberately stops short of defining what `0.7` means. Every
attempt to standardise a cross-producer confidence scale either forces producers to invent numbers
they do not have or quietly redefines an existing scale, and both make the field less trustworthy
than an honest "unknown". What the contract does guarantee is the range, the meaning of absence, and
that nobody fabricates the value.

## Why they are not one field

Normative:

> Verification is not confidence.

They vary independently, and every combination is meaningful:

| | high confidence | low confidence |
|---|---|---|
| `VALIDATED` | a checked measurement | a checked but weak inference |
| `UNVERIFIED` | a single trusted sensor, uncorroborated | a single weak sensor, uncorroborated |
| `DISPUTED` | a firm claim another source contradicts | a tentative claim another source contradicts |

A single high-grade sensor can be highly confident and entirely uncorroborated. Three weak sources
can corroborate each other and leave the producer unsure. Collapsing the pair into one number
destroys exactly the distinction an analyst needs, and the direction of the loss is not recoverable
afterwards.

## Neither field is authorisation

Normative:

> Neither `verification` nor `confidence` may be used as an authorisation, release or handling
> decision input by anything in this specification.

Handling is `10-security-markings.md`'s subject, and that document's own limits apply.
