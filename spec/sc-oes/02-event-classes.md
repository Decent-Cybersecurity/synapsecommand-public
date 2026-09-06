# 02 — Event classes

**SC-OES v0.1.0 — Draft.**

`event_class` says what *kind* of assertion an event is, independently of which governed type it
claims. It is the coarsest semantic distinction SC-OES makes, and it is the one a consumer that
understands no event types at all can still act on.

## The vocabulary

The initial stable vocabulary is exactly these eight values:

```text
OBSERVATION
STATE_CHANGE
CONSTRAINT
ASSESSMENT
IMPACT
RECOMMENDATION
DECISION
ACTION
```

Normative:

> `event_class` MUST be one of the eight values above.

> A consumer MUST NOT infer `event_class` from `type_id`, from the payload, or from the producer's
> identity. It is asserted or the event is not SC-OES Conformant.

Every governed event type in the registry declares exactly one class, and a governed event whose
asserted class disagrees with the registry is a semantic conformance failure rather than a syntax
one (`13-conformance.md`, dimension C).

## Definitions

### OBSERVATION

A producer reports an occurrence it observed, measured or directly detected.

*(Example.)* GNSS interference observed. An air track observed.

### STATE_CHANGE

The represented operational state of something changed.

*(Example.)* Runway availability changed. Route availability changed. System availability changed.
Mission status changed.

### CONSTRAINT

An operational condition limits behaviour.

*(Example.)* An airspace restriction changed.

### ASSESSMENT

An interpreted judgement, based on information or evidence, about something not itself directly
observed.

*(Example.)* A threat assessment updated.

### IMPACT

An assessed operational consequence — what some condition means for an activity.

*(Example.)* A mission navigation impact assessed.

### RECOMMENDATION

A proposed course of action or response. A recommendation asserts that something *should* be done;
it does not assert that it was decided or done.

### DECISION

A recorded decision.

### ACTION

An authorised, initiated or completed operational action.

## Observation MUST NOT silently become assessment

Normative:

> An observation MUST NOT silently become an assessment.

A producer may only assert `ASSESSMENT` where its source actually makes the interpretive claim. An
adapter translating a source that reports a measurement MUST emit `OBSERVATION`, however obvious
the interpretation appears.

*(Example.)* A source reporting

```text
RF anomaly observed
```

is not reporting

```text
hostile GNSS jammer detected
```

unless it says so. The first is an `OBSERVATION`; the second is an `ASSESSMENT` about a cause, an
actor and an intent, none of which the first asserts. An adapter that emits the second from the
first has manufactured an intelligence judgement and attributed it to a sensor.

*(Non-normative.)* This is the single rule most likely to be broken by well-meaning code, because
the promotion usually looks like enrichment and is often even correct. It is still forbidden. The
cost of the rule is that a consumer sometimes has to do its own interpreting; the cost of breaking
it is that a downstream analyst cannot tell which assertions a machine invented, which makes every
assessment in the system worth less. Where a system genuinely does make the interpretation, it
emits a *new* `ASSESSMENT` event, cites the observation with `DERIVED_FROM` (`08-event-relationships.md`)
and takes responsibility for it under its own producer identity.

The same rule holds one step further along the chain: an `ASSESSMENT` does not silently become an
`IMPACT`, an `IMPACT` does not silently become a `RECOMMENDATION`, and a `RECOMMENDATION` does not
silently become a `DECISION` or an `ACTION`. Each transition is an assertion somebody makes, and
each is a separate event.
