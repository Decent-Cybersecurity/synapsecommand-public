# 04 — Temporality

**SC-OES v0.1.0 — Draft.**

SC-OES distinguishes four instants, and the distinction is the point: a system that keeps only one
timestamp cannot tell a late report of an old condition from a fresh report of a new one.

## The four instants

Two already exist on the CDM `Event`:

| Field | Meaning |
|---|---|
| `observed_at` | when the source observed or determined the occurrence |
| `received_at` | when the canonical system received the source information |

SC-OES adds two, describing the *represented condition* rather than the report of it:

| Field | Meaning |
|---|---|
| `effective_from` | when the represented operational condition begins to apply |
| `effective_to` | when the represented condition ceases to apply |

Both are optional. Timestamp representation follows the CDM's existing rule for every timestamp in
this repository.

*(Non-normative.)* The first pair is about the *message*; the second pair is about the *world*. A
restriction published at 09:00, observed by the adapter at 09:02, that takes effect at 12:00 and
lifts at 18:00 has four different instants and no two of them are interchangeable. A consumer
answering "is this in force now?" reads the effective interval; a consumer answering "how stale is
my picture?" reads `observed_at`; a consumer measuring its own pipeline reads `received_at`.

## Validation

Normative:

> Where both `effective_from` and `effective_to` exist, `effective_to` MUST be greater than or equal
> to `effective_from`.

> An implementation MUST NOT default `effective_from` to `observed_at`, or to `received_at`, or to
> the time of validation.

An absent `effective_from` means the producer did not state when the condition begins. It does not
mean the condition begins when the event was observed, and a consumer that assumes it does will
report conditions as being in force before they are. An adapter may set `effective_from` equal to
`observed_at` only where the source's own semantics establish that equivalence — and where they do,
the adapter is asserting the equivalence, not inheriting it.

An absent `effective_to` means the producer did not state an end. It does not mean the condition is
permanent, and it does not mean the condition is still in force.

*(Example.)* An open-ended runway closure carries `effective_from` and no `effective_to`. When the
runway reopens, a *new* event records that, with a `RESOLVES` relation to the closure — the closure
event is not edited to acquire an end.

## Ordering

Normative:

> Dimension B checks temporal ordering: the effective interval MUST be well-formed as above, and an
> implementation MUST NOT reject an event solely because `observed_at` is later than `received_at`
> or because `effective_from` precedes `observed_at`.

Both of those are ordinary. A source may report a condition that began before anybody observed it,
and clock skew between a source and the canonical system is a fact of life rather than a semantic
error. What is *not* ordinary — an effective interval that ends before it starts — is a defect in
the assertion itself, which is why it is the only ordering rule that fails.

## Immutable event history

Normative:

> A published event represents an immutable historical assertion.

> A correction MUST be a new event. A published event MUST NOT be edited, replaced in place, or
> deleted to reflect a change in the world or a change of mind.

The relationship predicates in `08-event-relationships.md` are how a later event says what it does
to an earlier one: `UPDATES` revises, `SUPERSEDES` replaces for the purpose of determining the
current picture, `RESOLVES` says the condition ended, `RETRACTS` withdraws the assertion
altogether. In every case the earlier event remains historically visible.

*(Example.)* Three events, in order:

```text
Event A   runway unavailable until 14:00
Event B   runway unavailable until 18:00   SUPERSEDES A
Event C   runway available                 RESOLVES B
```

Event A is not deleted and is not edited. A consumer asking "what is the current state?" follows the
supersession chain to C. A consumer asking "what did we believe at 13:00, and on what basis?" reads
A — which is the question an after-action review actually asks, and the one a mutable store cannot
answer.

*(Non-normative.)* Immutability is why `effective_to` is not a mutable field and why there is no
"cancel" operation. It is also what makes the deterministic event identity in `14-security-considerations.md`
meaningful: if events were editable, an identity would name a moving target.
