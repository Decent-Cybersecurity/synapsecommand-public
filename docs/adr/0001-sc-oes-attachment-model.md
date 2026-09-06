# ADR 0001 — SC-OES attachment model

## Status

Proposed — awaiting M's review.

## Context

SC-OES needs somewhere to put operational-event semantics — event class, governed type
identifier, maturity, lifecycle status, verification, confidence, an effective interval,
event and entity relations, evidence, security markings and extensions — on an object the
Canonical Data Model already defines. §17 of the specification prefers an optional `oes`
block on the existing `Event` and says outright: "Do not blindly use this shape if repository
structure demonstrates a safer equivalent."

Three readings of this tree decide whether that shape is the safe one here.

- **The union is closed at four kinds.** `models.py:434` declares `KINDS` as exactly
  `{"entity", "event", "track", "plan_object"}` and `models.py:428` builds `CDMObject` as an
  `Annotated[Union[...], Field(discriminator="object_kind")]` over the same four. The schema
  exporter walks `KINDS` (`schemas.py:88`) rather than keeping its own list. A fifth top-level
  kind is therefore a coordinated change to the union, the exporter and every consumer that
  switches on the discriminator — and §4 of the specification forbids it independently.
- **The canonical objects forbid undeclared keys.** `models.py:59` sets
  `STRICT = ConfigDict(extra="forbid", …)` and `tests/test_cdm_schemas.py:63` asserts
  `additionalProperties: false` on all four kinds. There is no "just send an extra key" path.
  Whatever carries SC-OES must be a declared field of a declared model.
- **There is already a free-form bag on `Event`, and it is spoken for.** `models.py:327`
  declares `payload: dict[str, Any]`, described at `models.py:329` as validated against
  `PAYLOAD_MODELS[event_type]` where one is registered and as "the never-drop bag for events".

The last of these is the live alternative, because it would need no schema change at all.

## Decision

**Attach SC-OES as an optional declared field `Event.oes`, typed by a new strict model, in the
shape §17 gives.**

- `Event.oes: OesMetadata | None = None`. Optional, defaulting to `None`, so every object
  written before SC-OES existed stays valid and every producer that knows nothing about SC-OES
  keeps emitting valid events.
- `OesMetadata` and every model beneath it use `STRICT` (`models.py:59`), for the reason
  `models.py:8`–`:20` gives about the canonical objects: a model that accepts unknown keys "is
  not canonical — it is a dict with a docstring". The declared escape hatch is `oes.extensions`
  and nothing else; ADR 0008 governs it.
- The block's fields are §17's, unchanged: `spec_version`, `event_class`, `type_id`,
  `maturity`, `status`, `verification`, `confidence`, `effective_from`, `effective_to`,
  `event_relations[]`, `entity_relations[]`, `evidence[]`, `security`, `extensions`.
- `effective_from` and `effective_to` take the existing `Timestamp` annotation
  (`models.py:61`), not a bare `datetime`. That annotation is what publishes the strict RFC 3339
  pattern into the exported schema instead of the permissive `format: date-time`
  (`models.py:65`, and the reasoning at `models.py:24`–`:28`: "Parse wide, emit narrow, publish
  narrow").
- §40's ordering requirement (`effective_to` not before `effective_from`) is a
  `model_validator(mode="after")` in the shape `Entity._interval` already uses
  (`models.py:271`), and its message follows that one's register: `models.py:275` calls a
  backwards interval "a translation defect, not data". A producer is told it has a bug, not
  that its data is unusual.
- **Entity annotations are a separate field, not part of this block.** `Entity.ontology_types:
  list[str] = []` carries §86's ontology annotations. `oes` hangs on `Event` only, because
  everything in §17's shape is a statement about an occurrence.

## Alternatives considered

**A — a fifth top-level CDM object kind (`OesEvent` or similar).** Rejected on two independent
grounds. §18 forbids introducing another top-level envelope in v0.1 and names the CDM `Event` as
the authoritative representation. Independently, `models.py:428` and `models.py:434` make a fifth
kind a change to the discriminated union that every consumer switches on, which is a MAJOR-shaped
change under `MIGRATIONS.md:20` for a requirement that an optional field satisfies.

**B — carry `oes` inside `Event.payload`.** This is the cheapest option: `payload` is
`dict[str, Any]` (`models.py:327`), so it needs no model, no schema change and no version bump.
Rejected on the tree's own stated reasoning. `models.py:329` reserves `payload` for
"Event-specific fields … the never-drop bag for events" — a *source's* shape, preserved
untouched. Putting governed SynapseCommand semantics there is the failure mode `models.py:18`
describes: "puts source-specific fields at the same level as canonical ones, and six months
later nobody can tell which fields the model guarantees and which one adapter happens to send."
It also has two mechanical consequences: `oes` would be invisible to the exported JSON Schema,
which defeats §104's requirement that a non-Python consumer can validate offline; and it would
collide with `Event._payload_shape` (`models.py:336`), which validates `payload` against a model
registered per `event_type` — an SC-OES block riding in the same dict would have to be tolerated
by every such model.

**C — a required `Event.oes`.** Rejected. It converts an optional field into a required one,
which `MIGRATIONS.md:20` makes a MAJOR bump, and it would make every existing adapter emit a
block it has no source information for — which §33 forbids in as many words ("A producer MUST NOT
invent lifecycle information absent from its source").

**D — a sidecar object related by UUID.** Rejected: it is alternative A with an extra join, and it
breaks §108's replay property, which currently comes free because `ids.NAMESPACE` (`ids.py:28`)
is fixed and identity is derived rather than drawn.

## Consequences

- One new field on `Event` and one on `Entity`; the `SCHEMA_VERSION` consequence is ADR 0005's.
- `harness.py:144` dumps with `model_dump(mode="json")` and no `exclude_none`, so `"oes": null`
  appears on every serialised event exactly as `"integrity": null` already does. That is the
  mass golden-file consequence ADR 0005 prices.
- A new module (`oes.py` or a small package) holding the SC-OES models. Its public names join
  `__init__.py`'s hand-written `__all__`.
- `Event` gains a second `model_validator`; `_payload_shape` (`models.py:336`) is untouched.
- SC-OES payload validation is keyed by `type_id` and follows `_payload_shape`'s rule exactly —
  validation is a check and never a transformation. ADR 0008 states that mechanism.

## Compatibility impact

Additive in both directions, which is §16's target.

- A 1.0.0 reader receiving an object that carries `oes` is a reader receiving an unknown key,
  and `version.compatible()` (`version.py:127`) accepts a minor from the future within the same
  major, so the reader is expected to tolerate it.
- A 1.0.0 object read by the new models validates unchanged: `oes` is optional with a `None`
  default and `ontology_types` defaults to the empty list.
- Every existing adapter keeps working untouched. None of them sets `oes`, and none has to.
- No field is removed, renamed, narrowed or made required, so `MIGRATIONS.md:20`'s MAJOR row is
  not reached and no coordinated deployment is implied.

## Security impact

- **The synthetic/live boundary is inherited rather than re-established.** `oes` hangs on an
  `Event`, every `Event` carries a `SourceRef`, and `SourceRef.synthetic` is required with no
  default — `models.py:96` states why: "There is no safe default, so there is no default." §11's
  requirement is met by construction.
- **Security markings are transported, never interpreted.** They live inside `oes.security` and
  not as `Event.classification`. `tests/test_cdm_format_coverage.py:388` asserts that
  `Entity.classification`, `Entity.top_classification` and `Event.classification` do not exist —
  a documented gap. SC-OES must not close it in passing; §59 forbids interpreting, downgrading,
  upgrading, normalising or enforcing a marking, and this repository holds no code that could.
- **No new trust surface.** `oes` is metadata a producer asserts. Nothing in it is verified by
  this package, and `Integrity` stays designed-and-unpopulated (`models.py:107`) — ADR 0006.
- **Bounded structure is a validation rule, not an inherited property.** `event_relations[]`,
  `entity_relations[]`, `evidence[]` and `extensions` are the recursive surfaces §110 names.
  ADR 0008 sets the bound.

## Reversibility

Moderate, and asymmetric.

Before any release carrying it, this decision is fully reversible: remove the field, revert the
version bump, regenerate. After a release, the field is on the wire and removing it is a MAJOR
bump under `MIGRATIONS.md:20` — but it is *deprecable* rather than trapped, because it is
optional: a producer stops emitting it, consumers keep validating, and the field is removed at
the next major with the two-release rule at `MIGRATIONS.md:30` ("Renaming a field is two
releases, never one") applied to its removal.

What is *not* cheaply reversible is the choice of `Event` as the carrier. Moving `oes` to a fifth
kind later would be alternative A arriving late, with consumers already keyed on the field. That
is the decision this ADR asks M to ratify, not the field names.
