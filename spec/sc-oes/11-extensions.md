# 11 — Extensions

**SC-OES v0.1.0 — Draft.**

One declared bag, a namespaced key grammar, and one structural bound. The rest of the wire-semantic
block is strict (`01-core.md`), and that asymmetry is the whole design:
`docs/adr/0008-extension-mechanism.md` records it.

## The bag

Extensions live in one mapping on the SC-OES block:

```text
extensions: mapping of key -> any JSON value
```

Normative:

> `extensions` is the only place undeclared data may be carried in the SC-OES block. Every other
> field of the block is strict and rejects undeclared keys.

## Key grammar

```text
x.<namespace>.<name>
```

The `sc.` prefix is reserved for future governed SC-OES extensions. Frozen in
`docs/adr/0008-extension-mechanism.md` (decision 3), sharing the `lower_label` production with every
other namespaced surface in SC-OES:

```text
^x\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$
```

Exactly three dot-separated parts, ASCII lowercase, each label beginning with a letter.

*(Example.)* `x.acme.radar_quality` is a key. `x.acme`, `x..quality`, `x.Acme.radar_quality`,
`x.acme.radar-quality`, `acme.radar_quality` and a bare `radar_quality` are not.

Normative:

> A key that does not match the grammar MUST be rejected. An implementation MUST NOT normalise,
> case-fold, trim or otherwise repair a key.

> An unnamespaced key MUST be rejected.

An unnamespaced key is the one shape that cannot be attributed to anybody, which is why it is
refused rather than tolerated.

### The reserved namespace in v0.1.0

Normative:

> No governed `sc.*` extension is defined in v0.1.0. Every `sc.*` extension key MUST therefore be
> rejected, as **reserved but undefined**.

> No extension registry is created in v0.1.0.

A registry representing an empty governed set would be a contract with nothing in it and a file for
a future round to keep in step. One is created when the first governed extension exists, and not
before — so in v0.1.0 there is nothing to look an `sc.*` key up in and nothing that could allow it.

## Semantics of an unknown extension

Normative:

> A valid unknown `x.*` extension MUST survive validation, MUST survive serialization, and MUST
> survive round-trip unaltered.

> A valid unknown `x.*` extension MUST NOT be interpreted, and MUST NOT be promoted into a core
> field.

> A consumer that does not understand an extension MUST ignore it, and MUST NOT reject the event for
> carrying it.

> An extension MUST NOT redefine, override or qualify a core field.

*(Example.)* An extension named

```text
x.acme.confidence
```

MUST NOT be interpreted as a replacement for, or a correction to, the block's own `confidence`
field. It is one producer's private value that happens to share a word.

*(Non-normative.)* "Survives round-trip unaltered" is stronger than it looks and is the property that
makes the bag worth having. A validator that dropped keys it did not recognise would make every
intermediary a lossy hop, and a producer would learn to smuggle data into a core field to keep it —
which is exactly what a strict block plus an open bag exists to prevent.

## The structural depth bound

Normative:

```text
MAX_EXTENSION_DEPTH = 16
```

> An extension whose value exceeds the maximum depth MUST fail validation.

The counting algorithm is frozen in `docs/adr/0008-extension-mechanism.md` (decision 7), so that
independent implementations agree:

```text
scalar (null, boolean, number, string)   depth 0
object or array as the extension value   depth 1
each further nested object or array      +1
object property names                    contribute nothing
empty {} or []                           still a container, so still 1
accepted                                 depth <= 16
first rejected                           depth 17
```

Normative:

> Depth is the maximum over the value's container paths, and is calculated **per extension key** —
> never once across the whole `extensions` mapping.

*(Example.)*

| Value | Depth |
|---|---|
| `"x.acme.quality": 0.95` | 0 |
| `"x.acme.data": {}` | 1 |
| `"x.acme.data": []` | 1 |
| `{"sensor": {"quality": 0.9}}` | 2 |
| `[{"samples": [1, 2, 3]}]` | 3 |
| `{"x.a.one": {"a": {"b": 1}}, "x.b.two": {"c": {"d": 2}}}` | two values of depth 2 — not one of depth 3 |

Normative:

> A refusal MUST name the extension key, the calculated depth and the maximum accepted depth. It
> MUST be deterministic, and MUST NOT include a stack trace or internal implementation detail.

### Compatibility of the bound

Raising `MAX_EXTENSION_DEPTH` in a future version is a compatible change: everything previously
accepted is still accepted. Lowering it is potentially breaking, because a producer's existing data
may stop validating. The bound therefore ships with the block rather than arriving after producers
exist.

## What the bound is, and is not

Normative:

> The extension depth limit is a normative SC-OES structural conformance and resource-safety
> constraint. It is not operational semantics.

> Implementations MAY enforce deployment-specific maximum message size, maximum list length, memory
> limits and processing limits. Those are deployment resource policies, not SC-OES interoperability
> requirements.

> This specification establishes **no** normative maximum count for `event_relations`,
> `entity_relations` or `evidence` in v0.1.0.

The distinction matters in both directions. A document that stated a list cap would make an
implementation accepting one more entry non-conformant, which is a claim v0.1.0 has no basis for. A
document that left the depth bound to local policy would let two conformant implementations disagree
about whether the same event is valid.

*(Non-normative.)* What an event *means* is carried by `event_class`, `type_id`, the event and entity
relations, the lifecycle, the effective interval and the ontology annotations. `MAX_EXTENSION_DEPTH`
says nothing about any of them; it says how much structure a conformant implementation must be
willing to walk. Both are universal and both are normative, which is why the two are easy to
conflate — and a reader who takes the depth limit for a semantic rule will go looking for the
meaning of 16, of which there is none.
