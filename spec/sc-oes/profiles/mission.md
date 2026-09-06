# SC-OES Mission Profile

**SC-OES Mission Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This is a **stub**. It carries the four things a profile must declare before anything can reference
it — scope, version, maturity and implementation status — and nothing else. The normative profile
content (ontology concepts, event types with their classes, payload semantics, required and optional
fields, temporality, entity relations, extensions, security considerations, examples and non-goals)
is written in a later round. Until then no conformance claim may be made against this profile beyond
what "Implementation status" below permits.

## Scope

Mission execution: the status of a mission, and the assessed operational consequence of
some condition for it. In scope are mission status changes and assessed operational impact. Out of
scope are mission planning, tasking, and any recommendation about what to do in response — the last
belongs to the Decision profile.

Profile domain: `mission`.

## Version

```text
profile:         Mission
profile_version: 0.1.0
sc_oes_version:  0.1.0
```

The profile version is independent of the SC-OES specification version and of every other profile's
version (`../01-core.md`). It moves when this profile changes and for no other reason.

## Maturity

```text
DRAFT
```

`../12-versioning.md` defines what each maturity value commits this specification to. A profile's
maturity is not inherited by the event types it names: each governed type carries its own maturity
in the packaged event registry, which is the machine authority for it.

## Event types in scope

Two governed types are in scope for v0.1.0, in the `mission` domain, one `STATE_CHANGE`
and one `IMPACT`.

The authoritative list of governed types, with class, maturity and mappings, is the packaged event
registry (`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human
index. This document does not restate them, and MUST NOT become a second hand-authored copy.

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event types.
One of its two governed types is `EXPERIMENTAL` and the other `DRAFT`; the
packaged registry is the authority for each (`../03-event-types.md`).

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). Until this profile's normative content exists, a D assessment against it
has no rules to check, and the permitted claim "SC-OES Mission Profile Conformant" is therefore not
yet available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.
