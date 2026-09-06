# 05 — Lifecycle

**SC-OES v0.1.0 — Draft.**

`status` records the lifecycle state of the *represented condition* — not of the message, and not of
any workflow the consumer runs.

## The vocabulary

`status` is optional. Where present it MUST be one of:

```text
PLANNED
ACTIVE
RESOLVED
EXPIRED
CANCELLED
RETRACTED
SUPERSEDED
```

| Value | Meaning |
|---|---|
| `PLANNED` | the condition is expected to begin but has not begun |
| `ACTIVE` | the condition applies now, as far as the producer knows |
| `RESOLVED` | the condition ended because whatever it described was resolved |
| `EXPIRED` | the condition ended by reaching its own stated end |
| `CANCELLED` | the condition was called off before or during its effect |
| `RETRACTED` | the producer withdraws the assertion that the condition existed |
| `SUPERSEDED` | the assertion has been replaced by a later one for determining the current picture |

## Rules

Normative:

> A producer MUST NOT invent lifecycle information absent from its source semantics.

> An implementation MUST NOT default `status` to `ACTIVE`, or to any other value.

An absent `status` means the source says nothing about lifecycle. It is a common and entirely valid
state: most sensor sources report occurrences, not managed conditions.

> A consumer MUST NOT derive `status` from the effective interval.

An event whose `effective_to` has passed is not thereby `EXPIRED`. The interval is what the producer
said about the world; `status` is what the producer says about the assertion's own standing, and a
producer that has not said is not to be answered for.

*(Non-normative.)* The temptation is to compute `status` from the clock, and it fails in both
directions: a condition can outlast its stated end without anybody being wrong, and a condition can
be cancelled long before it. Where a consumer needs a computed "in force now?" flag it may compute
one — it just may not write it back into `status` or report it as the producer's assertion.

## Lifecycle and relationships

`RETRACTED` and `SUPERSEDED` overlap with the `RETRACTS` and `SUPERSEDES` relationship predicates,
and the two are not the same statement:

- The **relation** is carried by the *later* event and points at the earlier one. It is how the
  history records what happened.
- The **status** is a producer's summary of the standing of an assertion at the time it publishes
  it.

Normative:

> Setting `status` on a new event MUST NOT be used in place of the relationship that records what
> the new event does to the earlier one, and MUST NOT be used to mutate the earlier event.

`04-temporality.md` states the immutability rule those two sentences follow from, and
`08-event-relationships.md` defines the predicates.

## Lifecycle and event class

Lifecycle is meaningful for classes that represent a persisting condition — `STATE_CHANGE`,
`CONSTRAINT`, `IMPACT`, `RECOMMENDATION`, `DECISION`, `ACTION`. It is often meaningless for a bare
`OBSERVATION`, which reports a moment rather than a condition.

This specification does not forbid any combination, because a source may legitimately manage the
lifecycle of anything it publishes. A profile MAY constrain which lifecycle values its event types
use; where it does, the constraint is checked by dimension D and by nothing else.
