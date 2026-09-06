# Deprecation policy

**SC-OES v0.1.0 — Draft.**

Deprecation is how a governed thing stops being recommended without ceasing to be understood. It is
not deletion, and it is not renaming.

## The rule everything else follows from

Normative:

> A published identifier MUST NOT be reused for a different meaning, ever.

This holds for governed event types, ontology terms, profile names, relationship predicates,
`EventClass` values, lifecycle values, verification values and evidence kinds. It holds after
deprecation, after removal from a profile, and after the last known producer stops emitting it.

*(Non-normative.)* Identifier reuse is the one governance failure with no recovery path. Every stored
event, every archived report, every downstream record and every after-action review holds identifiers
that were resolved against the meaning in force when they were written. Redefining one silently
rewrites the meaning of history — and nothing in the data records which meaning applied, so the
damage cannot be detected afterwards, only assumed. This is the same reason a published event is an
immutable historical assertion (`../sc-oes/04-temporality.md`): both rules protect the readability of
the past against a convenience in the present.

## What a deprecated item retains

Normative:

> A deprecated item MUST retain all of the following. An item that has lost any of them has been
> deleted rather than deprecated.

```text
identifier
original meaning
deprecated status
deprecation version/date
replacement where available
migration guidance
```

| Retained | Why |
|---|---|
| identifier | so a stored event carrying it still resolves |
| original meaning | so it resolves to what it meant, not to what its replacement means |
| deprecated status | so a new producer is warned off it |
| deprecation version/date | so a reader can tell whether an event predates the deprecation |
| replacement where available | so a producer has somewhere to go |
| migration guidance | so a producer knows what changes, including what does not map |

Normative:

> Where no replacement exists, that MUST be stated. A deprecation MUST NOT name a replacement whose
> meaning differs from the deprecated item's, without saying how it differs.

> Migration guidance MUST state what does **not** map. A deprecation that presents a partial mapping
> as a complete one causes exactly the silent semantic drift the reuse rule exists to prevent.

## Effects of deprecation

Normative:

> A deprecated governed event type MUST continue to validate. A consumer MUST NOT reject an event
> solely because its type is deprecated.

> A deprecated ontology term MUST remain in the generated term registry, marked deprecated, and MUST
> continue to resolve for dimension E.

> A new producer SHOULD NOT adopt a deprecated item.

> A deprecated item MUST NOT be removed from the packaged registries while any of its published
> events can still exist — which, given immutable history, is indefinitely.

Deprecation therefore changes what is *recommended*, and changes nothing about what is *understood*.

## Process

Normative:

> A deprecation MUST be proposed and recorded with: the item, the reason, the replacement or the
> explicit absence of one, the migration guidance, and the version and date from which the
> deprecation takes effect.

> A deprecation MUST NOT be combined in one change with a redefinition of the item being deprecated.

> A deprecation MUST NOT be recorded retroactively. Its date is the date it took effect, and a
> correction to an earlier record is added beside it rather than replacing it
> (`SC-OES-GOVERNANCE.md`).

## Maturity and deprecation

`DEPRECATED` is one of the four maturity values (`../sc-oes/12-versioning.md`), and it is where a
definition ends rather than a state it passes through.

Normative:

> A `DEPRECATED` item MUST NOT be returned to `EXPERIMENTAL`, `DRAFT` or `STABLE`.

If the concept is wanted again, it is proposed again, under a new identifier, through its own
process. Reviving a deprecated identifier would leave two periods in which it meant different
things, distinguishable only by a date nobody stored.
