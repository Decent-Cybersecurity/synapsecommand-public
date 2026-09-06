# SC-OES Logistics Profile

**SC-OES Logistics Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

## Scope

Sustainment: the holdings a force depends on and the routes that move them. In scope are
supply thresholds a holder tracks and the availability of routes used to move supply. Out of scope
are demand forecasting, prioritisation between competing demands and any judgement about whether a
level is adequate.

Profile domain: `logistics`.

## Version

```text
profile:         Logistics
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

## Ontology concepts

```text
logistics:SupplyNode      a place holding supply
logistics:SupplyItem      a kind of supply held
logistics:LogisticsRoute  a route used to move it
logistics:SupplyThresholdReachedEvent  logistics:RouteAvailabilityChangedEvent
```

`core:Route` is the general concept and `logistics:LogisticsRoute` is the sustainment reading of it;
a producer annotates with whichever it can support, and neither annotation changes the entity's
structural `entity_type` (`../09-entity-semantics.md`).

## Event types in scope

Two governed types are in scope for v0.1.0, in the `logistics` domain, both
`STATE_CHANGE`.

```text
sc.logistics.supply_threshold_reached.v1
sc.logistics.route_availability_changed.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span a single class, `STATE_CHANGE`.

Both types report that something in the world moved, not what it means. A threshold
reached is a fact about a holding measured against the holder's own threshold; whether the
resulting level is good or bad is an `ASSESSMENT` somebody makes and belongs to another profile.
Keeping that line is what stops a sustainment feed from quietly becoming a judgement feed.

## Payload semantics

No type in this profile has a registered payload model in v0.1.0. Payloads are free-form
and transportable, extra source fields survive, and nothing validates their shape. The examples show
the fields a producer would naturally carry — the node, the item, the threshold's own name, the
quantity and its unit — and they are illustrative, not a schema.

The unit is worth one sentence of its own: a quantity with no unit is the defect this domain
produces most often, and a producer that cannot state one should carry the source's own text rather
than assume litres.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id`.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Conventions, stated as conventions and not as requirements:

- both types SHOULD carry the previous value, for the reason the Air profile gives: "changed"
  without a prior state is not actionable;
- a route event SHOULD carry `geometry` for the affected segment when the source states one;
- `confidence` is rarely meaningful here — a holding is counted, not judged — and SHOULD be left
  unset rather than set to 1.0.

## Temporality

`observed_at` and `received_at` carry their ordinary meanings
(`../04-temporality.md`). A route restriction with a stated window uses `effective_from` and
`effective_to`; a threshold reached is an instant and ordinarily states neither. Nothing derives
lifecycle from the interval (`../05-lifecycle.md`).

## Entity relations

`core:Concerns` for the node or route the event is about. `core:DependsOn` and
`core:Provides` exist in the core module for the relationships between a consumer, a route and a
node, and a producer that can support one may use it; this profile requires none of them.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no extension and
reserves none. Sustainment sources carry stock codes, national nomenclature and unit-of-issue
vocabularies that no interoperability layer should try to normalise; they belong under the
producer's own namespace, where they are preserved byte-for-byte and never interpreted
(`../11-extensions.md`). The `sc.` prefix is reserved and undefined for the whole specification in
v0.1.0, so a producer reaching for it is refused rather than accommodated.

## Security considerations

Holdings and route availability together describe a force's freedom of action, and the
aggregate is more sensitive than any single event in it. Markings are transported and never
enforced (`../10-security-markings.md`); aggregation risk is a deployment's to manage and this
specification does not pretend to manage it.

## Examples

Two, one per governed type:

- `examples/sc-oes/individual/sc.logistics.supply_threshold_reached.v1.json`
- `examples/sc-oes/individual/sc.logistics.route_availability_changed.v1.json`

The first carries a quantity with its unit, the second the affected segment as a `LineString`.
Both are loaded and validated on every test run by `tests/test_cdm_examples.py`.

## Non-goals

This profile does not forecast demand, does not prioritise between competing demands,
does not model stock accounting or transactions, and does not assert that a level is adequate or
inadequate. It does not define thresholds: the threshold is the holder's own and the event reports
that it was reached.

## Implementation status

**Specification-only in v0.1.0.** No adapter in this repository emits this profile's event
types. Every adapter this repository ships remains CDM Conformant without being an SC-OES semantic
producer, and that distinction is intentional (`../README.md`). Nothing in this tree should be read
as implying an operational adapter implementation exists for this profile: the examples under
`examples/sc-oes/` were written against the models by hand and name an adapter nothing resolves,
and PNT is the one profile with a reference producer behind it (`pnt.md`).

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). This profile declares no conformance rules of its own in v0.1.0: every
constraint stated above is either one dimension A, B, C or E already checks — the CDM's structural
contract, the block's core syntax, the governed type's agreement with the registry, and the
recognition of governed ontology terms — or a convention marked SHOULD, which is guidance to a
producer and not a rule to grade against. A D assessment against this profile therefore
has no rules to check, and the permitted claim "SC-OES Logistics Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.
