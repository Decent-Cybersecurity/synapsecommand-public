# SC-OES PNT Profile

**SC-OES PNT Profile v0.1.0 — Draft.** Profile maturity: `DRAFT`.

This document is complete for v0.1.0. Complete means every heading the specification requires of a
profile is written and says what this profile does and does not commit to — not that the profile has
acquired conformance rules of its own, which it has not; see "Conformance" at the end.

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

## Ontology concepts

```text
pnt:PNTService          a positioning, navigation or timing service something depends on
pnt:GNSSReceiver        a receiver of GNSS signals
pnt:InterferenceSource  a source of interference with those signals
pnt:GNSSInterferenceEvent   the event class the governed type is annotated with
```

Each is a governed term under the frozen ontology grammar (`../09-entity-semantics.md`) and each is
carried by the packaged ontology-term registry, which is the machine authority for whether a term
exists. An entity annotated `pnt:InterferenceSource` has that term in `Entity.ontology_types`; its
`entity_type` stays the CDM's own structural value and is never derived from the annotation, nor the
annotation from it (`../09-entity-semantics.md`).

## Event types in scope

One governed type is in scope for v0.1.0, in the `pnt` domain, and it is the one governed
type with a registered payload model (`../03-event-types.md`).

```text
sc.pnt.gnss_interference.v1
```

The authoritative list of governed types, with class, maturity, ontology class, payload model and
legacy mapping, is the packaged event registry
(`synapse_cdm/registry/sc_oes/event_types.json`). `../03-event-types.md` carries the human index,
which is where each type is paired with its class and maturity. This document names the identifiers
and nothing else about them, and MUST NOT become a second hand-authored copy: where it and the
registry could be read as disagreeing, the registry is right.

## EventClass

The types above span a single class, `OBSERVATION`.

The single class is the profile's whole point. A PNT source reports a condition it
measured; the judgement about who caused it, whether it is deliberate and what it means for a
mission are `ASSESSMENT`, `IMPACT` and the decision classes, and they belong to the ISR, Mission
and Decision profiles. `../02-event-classes.md` forbids inferring the class from the type or the
payload, and this profile asserts nothing that would let a producer do so.

## Payload semantics

`sc.pnt.gnss_interference.v1` is the one governed type in v0.1.0 with a registered payload
model. The model is the CDM's existing `GnssInterferencePayload` — reused, not duplicated — so a
producer that already emitted a CDM `GNSS_INTERFERENCE` event emits the same payload with an `oes`
block beside it:

```text
frequency_band       required   the source's own band name, e.g. L1, L2, L5, E1, B1
interference_type    required   JAMMING | SPOOFING | UNKNOWN
signal_strength_dbm  optional   dBm; absent means not reported, never zero
```

Extra source fields ride along in the same dict: the payload model allows them, and the never-drop
rule is what keeps a source's own vocabulary recoverable. `UNKNOWN` is a real answer — a receiver
that has lost lock knows it is jammed, and one reporting a plausible false position does not know
it is spoofed, so a producer that cannot tell says `UNKNOWN` rather than guessing.

## Required fields

This profile adds no required field of its own. An event in it carries what dimensions A
and B already require — the CDM's `event_id`, `event_type`, `severity`, `observed_at`,
`received_at`, `source` and at least one `source_ids` entry, and the SC-OES block's
`spec_version`, `event_class` and `type_id` — and the payload fields the model above marks
required, which dimension C checks.

## Optional fields

Every other field of the block is optional and absence asserts nothing
(`../01-core.md`). Two conventions for this profile, stated as conventions and not as
requirements:

- `geometry` SHOULD carry the affected area when the source states one, because the operational
  question a PNT observation answers is *where*. A point is honest when that is all the source has.
- `confidence` SHOULD be left unset unless the source supplies a number on its own scale. The
  reference producer leaves it unset for exactly this reason: the value it would otherwise copy
  belongs to the emitter entity and is already carried at `Entity.confidence`.

## Temporality

`observed_at` is when the source saw the condition and `received_at` is when this
system took delivery; neither is ever substituted for the other, and clock skew between them in
either direction is ordinary (`../04-temporality.md`). `effective_from` and `effective_to` describe
the represented condition, not the message, and are never defaulted to either timestamp. A PNT
observation typically states neither: interference observed at an instant is not thereby a
condition with a declared interval.

## Entity relations

`related_entities` remains the single answer to which entities the event concerns, and
`oes.entity_relations` adds the role each plays. In this profile the ordinary role is
`core:Concerns` — the weakest predicate, and the one to use when a stronger one would assert more
than the source does. `core:Threatens` is available and belongs to an assessment that makes the
attribution, not to the observation that reports the signal.

## Extensions

One bag, `oes.extensions`, keys `x.<namespace>.<name>`. This profile defines no
extension and reserves none: the `sc.` prefix is reserved and undefined for the whole
specification in v0.1.0 (`../11-extensions.md`), so a PNT producer with vendor semantics publishes
them under its own namespace and nothing in this repository interprets the value.

## Security considerations

A PNT observation says where a receiver is being denied service, which is a statement
about friendly dependence as much as about an adversary. Markings on events in this profile are
transported and never enforced: presence is not authorization, absence is not proof of
unclassified status, and this repository is not a cross-domain guard
(`../10-security-markings.md`). Nothing in this profile makes a marking required.

## Examples

`examples/sc-oes/individual/sc.pnt.gnss_interference.v1.json` — one observation over one
interference source, with the typed payload and an entity relation. The linked chain
(`examples/sc-oes/chain/gnss-interference-to-route-change.json`) opens on the same type: the
observation every later event in it derives from. Both are loaded and validated on every test run
by `tests/test_cdm_examples.py`.

## Non-goals

This profile does not attribute interference to an actor, does not geolocate a source,
does not model receiver-level integrity algorithms, does not define a confidence scale, and does not
say what a consumer should do about a PNT condition. The first two are assessments; the last is the
decision domain. None of them is an observation a PNT source can report.

## Implementation status

**Reference producer-backed.** PNT is the initial reference producer-backed profile in
v0.1.0, through the PNTMAP producer — the one producer in this repository that emits SC-OES
semantics. It asserts exactly three fields of the block, `spec_version`, `event_class` and
`type_id`, and nothing its source does not support: no fabricated confidence, verification, status,
effective interval, security marking or entity relationship. Producer-backed means those three
fields are emitted by running code and checked against goldens; it does not mean this profile has
normative conformance rules of its own — see "Conformance".

## Conformance

Dimension D is assessed only against an explicitly named profile, and never inferred
(`../13-conformance.md`). This profile declares no conformance rules of its own in v0.1.0: every
constraint stated above is either one dimension A, B, C or E already checks — the CDM's structural
contract, the block's core syntax, the governed type's agreement with the registry, and the
recognition of governed ontology terms — or a convention marked SHOULD, which is guidance to a
producer and not a rule to grade against. A D assessment against this profile therefore
has no rules to check, and the permitted claim "SC-OES PNT Profile Conformant" is not yet
available. Dimensions A, B, C and E are unaffected: they do not depend on any profile.

The round that gives this profile its first rule of its own writes the rules and the check that
enforces them together, in the same commit — a dimension that reported a verdict no rule set could
change would be worse than an honest `SKIP`.
