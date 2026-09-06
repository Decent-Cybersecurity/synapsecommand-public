# SC-OES Decision Profile

**SC-OES Decision Profile v0.1.0 — Draft.** Profile maturity: `EXPERIMENTAL`.

This is a **stub**. It carries the four things a profile must declare before anything can reference
it — scope, version, maturity and implementation status — and nothing else. The normative profile
content (ontology concepts, event types with their classes, payload semantics, required and optional
fields, temporality, entity relations, extensions, security considerations, examples and non-goals)
is written in a later round. Until then no conformance claim may be made against this profile beyond
what "Implementation status" below permits.

## Scope

The decision chain: a proposed course of action, a recorded decision, and an authorised
action. In scope are the three separate assertions and the relationships between them. Out of scope
is any automated progression between them — `../02-event-classes.md` forbids a recommendation
silently becoming a decision, or a decision silently becoming an action, and each transition is an
assertion somebody makes under their own producer identity.

Profile domain: `decision`.

## Version

```text
profile:         Decision
profile_version: 0.1.0
sc_oes_version:  0.1.0
```

The profile version is independent of the SC-OES specification version and of every other profile's
version (`../01-core.md`). It moves when this profile changes and for no other reason.

## Maturity

```text
EXPERIMENTAL
```

`../12-versioning.md` defines what each maturity value commits this specification to. A profile's
maturity is not inherited by the event types it names: each governed type carries its own maturity
in the packaged event registry, which is the machine authority for it.

## Event types in scope

Three governed types are in scope for v0.1.0, in the `decision` domain, one each of
`RECOMMENDATION`, `DECISION` and `ACTION`.

The authoritative list of governed types, with class, maturity and mappings, is the packaged event
registry (`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human
index. This document does not restate them, and MUST NOT become a second hand-authored copy.

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event types.
The profile and all three of its governed types are `EXPERIMENTAL`.

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). Until this profile's normative content exists, a D assessment against it
has no rules to check, and the permitted claim "SC-OES Decision Profile Conformant" is therefore not
yet available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.
