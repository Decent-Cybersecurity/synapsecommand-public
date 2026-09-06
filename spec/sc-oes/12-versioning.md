# 12 — Versioning and unknown semantics

**SC-OES v0.1.0 — Draft.**

`01-core.md` lists the four independent version axes. This document governs the two that a producer
and a consumer have to agree about at runtime: the semantic major inside a `type_id`, and the
maturity of a governed definition. It then states what a consumer does when it meets semantics it
does not know.

## Event semantic majors

The semantic major is part of the type identifier:

```text
sc.pnt.gnss_interference.v1
```

A breaking semantic revision takes a new identifier:

```text
sc.pnt.gnss_interference.v2
```

Normative:

> A published semantic major MUST NOT be redefined. Its meaning is fixed for as long as the
> identifier exists.

> A breaking change to a governed type's semantics MUST take a new semantic major.

> A consumer MUST NOT assume that two majors of the same type name are semantically equivalent, or
> that the higher one is a superset of the lower.

A breaking change is any change that would make a conformant producer's existing events mean
something different, or make a conformant consumer's existing handling wrong. Adding an optional
concept a consumer may ignore is not breaking. Narrowing, redefining or repurposing an existing one
is.

*(Non-normative.)* Versioning inside the identifier rather than beside it is what makes the rule
enforceable. A consumer that knows `v1` and meets `v2` cannot fail to notice, because the string it
matches on has changed; had the major lived in a separate field, the common implementation — match
the name, ignore the version — would have silently mismatched semantics, and it would have looked
like it worked.

## Semantic maturity

Maturity belongs to a **governed semantic definition**, not to an event occurrence.

```text
EXPERIMENTAL
DRAFT
STABLE
DEPRECATED
```

| Maturity | Commitment |
|---|---|
| `EXPERIMENTAL` | the meaning may materially change |
| `DRAFT` | reasonably mature, but not frozen |
| `STABLE` | the meaning cannot be silently changed; breaking semantics require a new identifier or version |
| `DEPRECATED` | recognised, but no longer recommended; a replacement is supplied where one exists |

Normative:

> Maturity MUST be stored in the event registry, in ontology term metadata, and in profile
> documents, as applicable to the thing being governed.

> Maturity MUST NOT appear in an SC-OES event instance.

> A consumer MUST NOT infer a maturity for a type absent from its registry.

Putting maturity on the wire would duplicate registry governance metadata on every message and give
it a second authority, which would then go stale. A consumer that needs to know a type's maturity
reads its own packaged registry — and if the type is not there, the answer is "unknown type", which
is a different question with its own answer below.

*(Non-normative.)* `EXPERIMENTAL` is a real warning rather than a formality: five of the thirteen
initial governed types carry it (`03-event-types.md`), which is a statement that their semantics are
not yet worth relying on in a system that cannot tolerate a change. `STABLE` is the only maturity
that promises anything, and no type in v0.1.0 claims it.

## Unknown semantic major

The realistic case: a consumer understands

```text
sc.pnt.gnss_interference.v1
```

and receives

```text
sc.pnt.gnss_interference.v2
```

Normative:

> The consumer MUST NOT assume `v2` is semantically equivalent to `v1`, and MUST NOT interpret the
> `v2` event under the `v1` contract.

> The consumer MAY preserve, store, forward, display and audit the event.

> Where interpretation is requested, the consumer SHOULD report an unsupported semantic major rather
> than returning a best guess or nothing at all.

The five permitted actions are what "transportable but uninterpreted" means in practice. The event
is not dropped, not silently downgraded, and not rewritten; it is carried, and the consumer says
plainly that it cannot read it.

## Unknown third-party semantics

Normative:

> A valid unknown `x.*` event MUST remain transportable.

> A consumer MUST NOT silently convert an unknown `x.*` event into a known `sc.*` type, or into any
> other type.

A third party's governed contract is theirs. This repository does not govern it, does not guess at
it, and does not map it onto its own vocabulary. The same rule holds for third-party ontology
identifiers (`09-entity-semantics.md`) and for unknown extensions (`11-extensions.md`): preserve,
do not interpret, do not translate.

## Unknown governed type

An unrecognised `sc.*` type is not an unknown third party — the namespace is reserved, so an
unrecognised member of it means either a producer minting governed semantics it may not mint, or a
consumer running against a registry older than the producer's.

Normative:

> An unrecognised `sc.*` type MUST NOT be interpreted. It is a dimension C failure
> (`13-conformance.md`).

*(Non-normative.)* The verdict is `FAIL` rather than `SKIP` because the two possible causes both
need a person: the first is a governance violation and the second is a deployment that will
misunderstand events until it updates. Reporting `SKIP` would make both look like an ordinary
third-party event nobody needs to act on.

## Deprecation

Normative:

> A published identifier MUST NOT be reused for a different meaning, ever — including after
> deprecation and including after removal from a profile.

`../governance/DEPRECATION-POLICY.md` carries the process and the metadata a deprecated item
retains.
