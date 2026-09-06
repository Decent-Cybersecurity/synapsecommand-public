# SC-OES PNT Profile

**SC-OES PNT Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This is a **stub**. It carries the four things a profile must declare before anything can reference
it — scope, version, maturity and implementation status — and nothing else. The normative profile
content (ontology concepts, event types with their classes, payload semantics, required and optional
fields, temporality, entity relations, extensions, security considerations, examples and non-goals)
is written in a later round. Until then no conformance claim may be made against this profile beyond
what "Implementation status" below permits.

## Scope

Positioning, navigation and timing: the availability, integrity and disturbance of PNT
services, and the operational consequences a PNT condition has for activities that depend on it. In
scope are observations of interference and of service condition. Out of scope are the assessment of
an adversary's intent, the attribution of a disturbance to an actor, and the geolocation of a source
— each of which is an `ASSESSMENT` somebody makes, not an observation a PNT source reports.

Profile domain: `pnt`.

## Version

```text
profile:         PNT
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

One governed type is in scope for v0.1.0, in the `pnt` domain, and it is the one governed
type with a registered payload model (`../03-event-types.md`).

The authoritative list of governed types, with class, maturity and mappings, is the packaged event
registry (`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human
index. This document does not restate them, and MUST NOT become a second hand-authored copy.

## Implementation status

**Reference producer-backed.** PNT is the initial reference producer-backed profile in
v0.1.0, through the PNTMAP producer — the one producer in this repository that emits SC-OES
semantics. The round that implements the producer establishes exactly which fields it emits, and it
asserts nothing its source does not support: no fabricated confidence, verification, status,
effective interval, security marking or entity relationship.

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). Until this profile's normative content exists, a D assessment against it
has no rules to check, and the permitted claim "SC-OES PNT Profile Conformant" is therefore not
yet available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.
