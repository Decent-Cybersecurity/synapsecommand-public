# 01 — Core

**SC-OES v0.1.0 — Draft.**

## Attachment

SC-OES semantics travel in one optional block on the Canonical Data Model's existing `Event`
object. There is no second event envelope and no fifth canonical object: an event carrying no
SC-OES semantics is a valid CDM event, and an event carrying them is the same object with one more
declared field populated. `docs/adr/0001-sc-oes-attachment-model.md` records the decision.

Normative:

> An SC-OES-aware consumer MUST accept a CDM `Event` with no SC-OES block, and MUST NOT infer SC-OES
> semantics for one.

An absent block means the producer made no SC-OES assertion. It does not mean the producer asserted
defaults.

## The wire-semantic block

The block carries these fields. Exact field spelling and types follow the CDM's own model
conventions; the contract is the field set and what each field means.

| Field | Cardinality | Meaning | Defined in |
|---|---|---|---|
| `spec_version` | required | the SC-OES version whose semantics the producer is claiming | this document |
| `event_class` | required | which of the eight kinds of assertion this is | `02-event-classes.md` |
| `type_id` | required | the governed or third-party semantic type identifier | `03-event-types.md` |
| `status` | optional | lifecycle state of the represented condition | `05-lifecycle.md` |
| `verification` | optional | how the assertion has been corroborated | `06-verification-and-confidence.md` |
| `confidence` | optional | the producer's confidence, `0.0`–`1.0` | `06-verification-and-confidence.md` |
| `effective_from` | optional | when the represented condition begins to apply | `04-temporality.md` |
| `effective_to` | optional | when it ceases to apply | `04-temporality.md` |
| `event_relations[]` | optional, list | typed references to other events | `08-event-relationships.md` |
| `entity_relations[]` | optional, list | semantic roles of entities already related to the event | `09-entity-semantics.md` |
| `evidence[]` | optional, list | what stands behind the assertion | `07-provenance-and-evidence.md` |
| `security` | optional | handling markings, transported only | `10-security-markings.md` |
| `extensions` | optional, mapping | the one declared extension bag | `11-extensions.md` |

Normative:

> Apart from `extensions`, the block is strict: an undeclared key MUST be rejected rather than
> ignored or preserved.

> `maturity` MUST NOT appear in the block.

Maturity is a property of a *governed semantic definition*, not of an event occurrence; it is
carried by the registries and the profile documents. `12-versioning.md` gives the vocabulary.
Putting it on the wire would duplicate registry governance metadata on every message and create a
second, stale authority for it.

*(Non-normative.)* The asymmetry between "strict everywhere" and "one open bag" is deliberate and
is the whole of the extension story. A strict block is what makes a validation failure mean
something; a single declared bag is what keeps an unknown producer's data from having to be
smuggled into a core field to survive. `11-extensions.md` is the contract for the bag.

## Required, optional, and unknown

Three states are distinguished throughout this specification and MUST NOT be collapsed:

| State | Representation | Means |
|---|---|---|
| asserted | the field is present with a value | the producer asserts this |
| unknown | the field is absent, or `confidence` is null | the producer does not know |
| asserted-absent | a value whose meaning is "none", where the field defines one | the producer asserts there is none |

Normative:

> An implementation MUST NOT represent an unknown value as a zero, an empty string, an empty list
> or a default enumeration member.

## Version axes

SC-OES has four independent version axes. They are independent in fact and not merely by
convention: each moves for its own reason, and none is derived from another.

| Axis | v0.1.0 value | Where it lives | Moves when |
|---|---|---|---|
| SC-OES specification version | `0.1.0` | one runtime constant, alongside the package's other version constants | the wire-semantic contract in this tree changes |
| Operational Ontology version | `0.1.0` | ontology metadata | the vocabulary changes |
| Profile version | `0.1.0`, declared per profile | each profile document, and its registry representation | that profile changes |
| Event semantic major | `v1` in each `type_id` | the type identifier itself | that one type's meaning breaks |

Normative:

> The SC-OES specification version MUST NOT be derived from the CDM schema version or from the
> package version.

> Each profile MUST declare its own version independently. A profile version MUST NOT be inferred
> from the SC-OES specification version.

> A breaking change to a governed event type's semantics MUST take a new semantic major in the type
> identifier. A published semantic major MUST NOT be redefined.

The CDM schema version and the package version are the repository's own axes and are governed by
its existing versioning rules; `docs/adr/0005-cdm-schema-version-impact.md` records what adding the
SC-OES block does to them.

*(Non-normative, example.)* All four can move in one release and none of the movements implies
another. A new governed event type raises no version at all — it is an addition to the registry.
Correcting one profile's prose raises that profile's version. Renaming an ontology class raises the
ontology version. Changing what `confidence` means would raise the SC-OES specification version.
Breaking `sc.pnt.gnss_interference.v1` does not raise any of them: it mints
`sc.pnt.gnss_interference.v2` and leaves `v1` meaning what it always meant.

## Offline

Normative:

> Core validation of an SC-OES block MUST succeed with no network access of any kind.

Every contract a validator needs — the event registry, the ontology-term registry, the schemas —
is packaged locally. No validation step performs a network fetch, a DNS lookup, a redirect, a
schema-registry call or an ontology-server call. `13-conformance.md` restates this as a property of
each dimension, and `14-security-considerations.md` explains why it is a security property and not
only a convenience.
