# ADR 0001 — SC-OES attachment model

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

Amended by SA.1 — M, 2026-09-06: reviewed under SA.1 §58 for implications of the four corrections
(authority date, namespace grammar, dimension E, extension depth) and **nothing in this ADR moves**.
`Event.oes`, `Entity.ontology_types` and the four canonical kinds are SA.1 §2–§3 locked decisions;
this ADR mints no identifier and states no depth rule, and its one depth sentence (Consequences,
"bounded structure is a validation rule, not an inherited property") already says what SA.1 §44–§45
requires and delegates the bound to ADR 0008. Still Accepted.

## Context

SC-OES needs somewhere to put operational-event semantics — event class, governed type
identifier, lifecycle status, verification, confidence, an effective interval, event and entity
relations, evidence, security markings and extensions — on an object the Canonical Data Model
already defines. §52 of the specification gives the block's field list, §11 fixes the attachment
as an optional `oes` on the existing `Event`, and §4 forbids the alternatives by name: "Do not
create `OperationalEvent` as a fifth canonical object. Do not introduce another primary event
envelope."

Three readings of this tree decide whether that shape is the safe one here.

- **The union is closed at four kinds.** `models.py:434` declares `KINDS` as exactly
  `{"entity", "event", "track", "plan_object"}` and `models.py:428` builds `CDMObject` as an
  `Annotated[Union[...], Field(discriminator="object_kind")]` over the same four. The schema
  exporter walks `KINDS` (`schemas.py:88`) rather than keeping its own list. A fifth top-level
  kind is therefore a coordinated change to the union, the exporter and every consumer that
  switches on the discriminator — and §4 forbids it independently.
- **The canonical objects forbid undeclared keys.** `models.py:59` sets
  `STRICT = ConfigDict(extra="forbid", …)` and `tests/test_cdm_schemas.py:63` asserts
  `additionalProperties: false` on all four kinds. There is no "just send an extra key" path.
  Whatever carries SC-OES must be a declared field of a declared model. This is also the reading
  that makes ADR 0005 a MAJOR, and §21 states the consequence as three propositions that cannot
  all hold at once.
- **There is already a free-form bag on `Event`, and it is spoken for.** `models.py:327`
  declares `payload: dict[str, Any]`, described at `models.py:329` as validated against
  `PAYLOAD_MODELS[event_type]` where one is registered and as "the never-drop bag for events".

The last of these is the live alternative, because it would need no schema change at all.

## Decision

**Attach SC-OES as an optional declared field `Event.oes`, typed by a new strict model, in the
shape §52 gives.**

- `Event.oes: OesMetadata | None = None`. Optional, defaulting to `None`, so every object
  written before SC-OES existed stays structurally valid under the new models and every producer
  that knows nothing about SC-OES keeps emitting objects those models accept. What that does
  **not** buy is stated in this ADR's Compatibility impact and is the correction §11 requires.
- `OesMetadata` and every model beneath it use `STRICT` (`models.py:59`), for the reason
  `models.py:8`–`:20` gives about the canonical objects: a model that accepts unknown keys "is
  not canonical — it is a dict with a docstring". §11 says the same in one line: "`OesMetadata`
  must be a strict declared model. The only generic open bag inside it is `extensions`." ADR 0008
  governs that bag.
- The block's fields are §52's, verbatim: `spec_version`, `event_class`, `type_id`, `status`,
  `verification`, `confidence`, `effective_from`, `effective_to`, `event_relations[]`,
  `entity_relations[]`, `evidence[]`, `security`, `extensions`.
- **`maturity` is NOT a field of `OesMetadata`.** §50 rules it registry-owned — "Maturity belongs
  to governed semantic definitions, not to individual event occurrences … Do not put `maturity`
  in every `Event.oes` instance" — and §52 closes with "Do not include registry-owned maturity."
  It lives in the event registry (ADR 0004), in ontology term metadata and in profile documents.
  This corrects the field list this ADR carried while proposed.
- `effective_from` and `effective_to` take the existing `Timestamp` annotation
  (`models.py:61`), not a bare `datetime`. That annotation is what publishes the strict RFC 3339
  pattern into the exported schema instead of the permissive `format: date-time`
  (`models.py:65`, and the reasoning at `models.py:24`–`:27`: "Parse wide, emit narrow, publish
  narrow").
- §70's ordering requirement (`effective_to >= effective_from` when both exist) is a
  `model_validator(mode="after")` in the shape `Entity._interval` already uses
  (`models.py:272`–`:273`), and its message follows that one's register: `models.py:277` calls a
  backwards interval "a translation defect, not data". A producer is told it has a bug, not
  that its data is unusual. §70's second half is equally binding and is a rule about *absence*:
  "Do not default `effective_from = observed_at` unless source semantics establish that
  equivalence."
- **Entity annotations are a separate field, not part of this block.** `Entity.ontology_types:
  list[str] = []` carries §101's ontology annotations, with §101's two rules — duplicate
  identifiers rejected, valid unknown third-party identifiers preserved. `oes` hangs on `Event`
  only, because everything in §52's shape is a statement about an occurrence.

## Alternatives considered

**A — a fifth top-level CDM object kind (`OesEvent` or similar).** Rejected on two independent
grounds. §4 forbids introducing another primary event envelope and names the CDM `Event` as the
thing SC-OES extends. Independently, `models.py:428` and `models.py:434` make a fifth kind a
change to the discriminated union that every consumer switches on.

**B — carry `oes` inside `Event.payload`.** This is the cheapest option: `payload` is
`dict[str, Any]` (`models.py:327`), so it needs no model, no schema change and no version bump.
Rejected on the tree's own stated reasoning. `models.py:329` reserves `payload` for
"Event-specific fields … the never-drop bag for events" — a *source's* shape, preserved
untouched. Putting governed SynapseCommand semantics there is the failure mode `models.py:18`
describes: "puts source-specific fields at the same level as canonical ones, and six months
later nobody can tell which fields the model guarantees and which one adapter happens to send."
It also has two mechanical consequences: `oes` would be invisible to the exported JSON Schema,
which defeats §125's requirement that a non-Python consumer can validate offline; and it would
collide with `Event._payload_shape` (`models.py:336`), which validates `payload` against a model
registered per `event_type` — an SC-OES block riding in the same dict would have to be tolerated
by every such model.

**C — a required `Event.oes`.** Rejected. It would make every existing adapter emit a block it
has no source information for — which §115 forbids in as many words for the one adapter that
does gain SC-OES semantics ("Do not fabricate confidence, verification, status, effective_from,
effective_to, security marking, entity relationships unless source semantics actually provide
them") and §116 forbids in general ("Do not retrofit every adapter in v0.1"). Under
`MIGRATIONS.md:20` an optional field made required is a MAJOR on its own; that is now no longer
the deciding cost, since ADR 0005 is a MAJOR anyway, so the ground for rejecting C is §115 and
§116 rather than the version.

**D — a sidecar object related by UUID.** Rejected: it is alternative A with an extra join, and it
breaks §128's replay property, which currently comes free because `ids.NAMESPACE` (`ids.py:28`)
is fixed and identity is derived rather than drawn.

## Consequences

- One new field on `Event` and one on `Entity`; the `SCHEMA_VERSION` consequence is ADR 0005's,
  and it is a **MAJOR**, not a MINOR.
- `harness.py:144` dumps with `model_dump(mode="json")` and no `exclude_none`, so `"oes": null`
  appears on every serialised event exactly as `"integrity": null` already does. That is the
  mass golden-file consequence ADR 0005 prices and §142 requires be verified by JSON path.
- A new module (`oes.py` or a small package) holding the SC-OES models. Its public names join
  `__init__.py`'s hand-written `__all__`.
- `Event` gains a second `model_validator`; `_payload_shape` (`models.py:336`) is untouched.
- SC-OES payload validation is keyed by `type_id` and follows `_payload_shape`'s rule exactly —
  §111: "Validation is a check, not a transformation." ADR 0008 states that mechanism.

## Compatibility impact

**This section is the correction §11 requires, and it reverses what this ADR claimed while it was
proposed.**

- **A CDM 1.x strict reader CANNOT consume an object carrying `oes` or `ontology_types`, and this
  project does not claim otherwise.** Two independent readings say so. `models.py:59`'s
  `extra="forbid"` and `tests/test_cdm_schemas.py:63`'s `additionalProperties: false` mean a 1.x
  reader meeting either key rejects the object rather than ignoring the key. And
  `version.compatible()` (`version.py:127`) returns `w_major == r_major`, so once ADR 0005 moves
  `SCHEMA_VERSION` to 2.0.0 a 1.x reader refuses the object by version before it ever reaches the
  keys — reading taken: `compatible("2.0.0", "1.0.0")` → **False**. §21's three propositions
  ("old model forbids undeclared keys / new object contains new keys / old reader accepts new
  object") cannot all be true, and it is the third that is false.
- **The major version is how that is communicated**, which is §21's point and the whole function
  of the number. See ADR 0005.
- **Backward, within the new models:** a 1.x object validates against the 2.0.0 models unchanged;
  `oes` defaults to `None` and `ontology_types` to `[]`. Note that this is a statement about the
  *models*, not about `compatible()`: `compatible("1.0.0", "2.0.0")` is also **False** (reading
  taken), so a 2.x consumer that gates on `compatible()` refuses a legacy object by version even
  though the models would accept it. ADR 0005 decides what the migration does about that.
- **Every existing adapter keeps working untouched.** None of them sets `oes`, and §116 says none
  has to: they remain "CDM Conformant" without being SC-OES semantic producers, and that
  distinction is intentional.
- **No field is removed, renamed, narrowed or made required.** That keeps `MIGRATIONS.md:20`'s
  other MAJOR clauses out of it, but it does not make the change MINOR: the MINOR row's stated
  consequence at `MIGRATIONS.md:21` is "old readers keep working, old data keeps validating", and
  the first half of that is exactly what is false here.

## Security impact

- **The synthetic/live boundary is inherited rather than re-established.** `oes` hangs on an
  `Event`, every `Event` carries a `SourceRef`, and `SourceRef.synthetic` is required with no
  default — `models.py:96` states why: "There is no safe default, so there is no default."
  §127 lists "synthetic/live confusion" as a threat this layer must be honest about; it is
  answered by construction rather than by a new mechanism.
- **Security markings are transported, never interpreted.** They live inside `oes.security` and
  not as `Event.classification`. `tests/test_cdm_format_coverage.py:388` asserts that
  `Entity.classification`, `Entity.top_classification` and `Event.classification` do not exist —
  a documented gap. SC-OES must not close it in passing; §86 is normative — "SC-OES transports
  markings. It does not interpret or enforce them" — and adds the two statements a consumer most
  needs: presence of a marking is not authorization, absence is not proof of unclassified status.
  This repository holds no code that could enforce one.
- **No new trust surface.** `oes` is metadata a producer asserts. Nothing in it is verified by
  this package, and `Integrity` stays designed-and-unpopulated (`models.py:107`) — ADR 0006.
- **Bounded structure is a validation rule, not an inherited property.** `event_relations[]`,
  `entity_relations[]`, `evidence[]` and `extensions` are the recursive surfaces §127 names
  ("deep nesting", "relationship abuse", "evidence fan-out", "resource exhaustion"). ADR 0008
  sets the one universal bound §32 authorises and declines the list caps §33 forbids.
- **An observation must not silently become an assessment** (§62). The block carries
  `event_class` precisely so that the difference is stated by the producer rather than inferred
  by a consumer; ADR 0007 is where that principle costs something, in the legacy mapping.

## Reversibility

Moderate, and asymmetric.

Before any release carrying it, this decision is fully reversible: remove the field, revert the
version bump, regenerate. After a release, the field is on the wire and removing it is
`MIGRATIONS.md:20`'s "a field removed" — a MAJOR — but it is *deprecable* rather than trapped,
because it is optional: a producer stops emitting it, consumers keep validating, and the field is
removed at the next major with the two-release rule at `MIGRATIONS.md:29` ("Renaming a field is
two releases, never one") applied to its removal.

What is *not* cheaply reversible is the choice of `Event` as the carrier. Moving `oes` to a fifth
kind later would be alternative A arriving late, with consumers already keyed on the field. That
is the decision this ADR records, not the field names.
