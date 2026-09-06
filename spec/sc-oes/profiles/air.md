# SC-OES Air Profile

**SC-OES Air Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This is a **stub**. It carries the four things a profile must declare before anything can reference
it — scope, version, maturity and implementation status — and nothing else. The normative profile
content (ontology concepts, event types with their classes, payload semantics, required and optional
fields, temporality, entity relations, extensions, security considerations, examples and non-goals)
is written in a later round. Until then no conformance claim may be made against this profile beyond
what "Implementation status" below permits.

## Scope

The air domain: observed air tracks, and the availability and restriction of air
infrastructure and airspace. In scope are track observations, runway availability and airspace
restrictions. Out of scope are identification, threat evaluation and engagement semantics.

Profile domain: `air`.

## Version

```text
profile:         Air
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

Three governed types are in scope for v0.1.0, in the `air` domain, spanning
`OBSERVATION`, `STATE_CHANGE` and `CONSTRAINT`.

The authoritative list of governed types, with class, maturity and mappings, is the packaged event
registry (`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human
index. This document does not restate them, and MUST NOT become a second hand-authored copy.

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event types.
Existing air-domain adapters remain CDM Conformant without being SC-OES
semantic producers, and that distinction is intentional (`../README.md`). Nothing in this tree
should be read as implying an operational adapter implementation exists for this profile.

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). Until this profile's normative content exists, a D assessment against it
has no rules to check, and the permitted claim "SC-OES Air Profile Conformant" is therefore not
yet available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.
