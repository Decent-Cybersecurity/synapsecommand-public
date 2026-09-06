# SC-OES examples

Fourteen committed examples: one for each of the thirteen governed event types
(`spec/sc-oes/03-event-types.md`), and one linked decision chain. Every one of them is loaded,
validated against the CDM models and assessed by the conformance tool on every test run —
`tests/test_cdm_examples.py` is the gate, and it exists because a documentation example that
nothing executes rots silently (`spec/sc-oes/13-conformance.md` is checked the same way).

```text
examples/sc-oes/
├── individual/   one file per governed type, named for the type
└── chain/        the linked OBSERVATION → ACTION chain
```

## Everything here is fictional

No real unit, mission, schedule, position, customer or infrastructure appears in this directory.
The names are the specification's own placeholders — `AIRBASE-ALPHA`, `RUNWAY-27`, `UAV-17`,
`MISSION-41`, `AREA-ALPHA`, `SUPPLY-NODE-BRAVO` and a handful in the same register. Every object
carries `source.synthetic: true`, which is a required field with no default precisely so that
nothing can be filed without saying which layer it belongs to.

## What the source block says, and what it does not

Every object names one source:

```text
system:          SC-OES-EXAMPLES
adapter:         sc-oes-examples
adapter_version: 0.1.0
```

**No adapter of that name is registered, and that is deliberate** — `tests/test_cdm_examples.py`
asserts it. These objects were written by hand against the models to illustrate the
specification; they are not the output of a translation, and a source block naming a real adapter
would claim a provenance they do not have. Only `pntmap` emits SC-OES semantics in this
repository, and the fixtures it produces live with that adapter, not here.

## Identifiers are derived, never drawn

`entity_id` and `event_id` are `ids.derive(system, external_id, kind)` — uuid5 over the source's
own identifier inside the CDM namespace — so every id in this directory is a pure function of the
`source_ids` entry beside it, and re-deriving it is a check rather than a copy. The test re-derives
all of them on every run.

## Shape

Each file is a JSON array in the form the harness writes goldens in: the entities the event
concerns, then the event, `indent=2`, keys sorted. The specification's §133 sketches a single
event object; the array is the same objects in the serialization this repository actually uses,
which is what the same section's "adapt exact serialization to real repository models" asks for.
Section numbers here cite SC-OES-SPEC-v2, the convention `docs/adr/0001`–`0010` already use.

## The legacy `event_type` column

`Event.event_type` is the broad CDM category and `oes.type_id` is the precise semantic type; they
are separate axes (`docs/adr/0007-legacy-eventtype-mapping.md`). Seven governed types have a
governed legacy mapping and the examples carry it, because a mismatch is a dimension C failure.
Six have `legacy_event_type: null`, which means "no meaningful legacy category is governed" — and
there §28's null branch applies: *ordinary CDM semantics determine the broad EventType*. The
choice each example makes is that example producer's own and governs nothing:

| Example | `oes.type_id` | `event_type` | Governed? |
|---|---|---|---|
| `sc.pnt.gnss_interference.v1` | PNT interference | `GNSS_INTERFERENCE` | yes |
| `sc.air.air_track_observed.v1` | air track | `TRACK_UPDATE` | no — ADR 0007 names `TRACK_UPDATE` and `DETECTION` as both honest, and says the null branch "does not stop a producer from setting `TRACK_UPDATE`" |
| `sc.air.runway_availability_changed.v1` | runway availability | `STATUS_CHANGE` | yes |
| `sc.air.airspace_restriction_changed.v1` | airspace restriction | `STATUS_CHANGE` | yes |
| `sc.logistics.supply_threshold_reached.v1` | supply threshold | `STATUS_CHANGE` | yes |
| `sc.logistics.route_availability_changed.v1` | route availability | `STATUS_CHANGE` | yes |
| `sc.isr.threat_assessment_updated.v1` | threat assessment | `ALERT` | no |
| `sc.c2.system_availability_changed.v1` | C2 availability | `STATUS_CHANGE` | yes |
| `sc.mission.mission_status_changed.v1` | mission status | `STATUS_CHANGE` | yes |
| `sc.mission.operational_impact_assessed.v1` | operational impact | `ALERT` | no |
| `sc.decision.recommendation_created.v1` | recommendation | `ALERT` | no |
| `sc.decision.decision_recorded.v1` | decision | `ALERT` | no |
| `sc.decision.action_authorized.v1` | authorised action | `ALERT` | no |

`ALERT` is chosen for the five ungoverned decision-domain and judgement types on the narrow
ground that it carries no observation claim: ADR 0007's alternative A names the real harm as an
interpretation arriving under a category a consumer reads as an observation, and `ALERT` is a
notification. `PLAN_INJECT` and `SIM_RESULT` appear in no example, for the reason ADR 0007's
alternative F gives — no adapter emits either, nothing in this tree establishes what they mean in
practice, and an example that used one would be defining a member rather than using it. A test
asserts their absence.

## The linked chain

`chain/gnss-interference-to-route-change.json` is the specification's chain (§132), as six
events over three entities:

```text
OBSERVATION      GNSS interference observed
     |           DERIVED_FROM
ASSESSMENT       navigation threat assessed
     |           DERIVED_FROM
IMPACT           mission impact assessed
     |           DERIVED_FROM
RECOMMENDATION   route change recommended
     |           DERIVED_FROM
DECISION         recommendation accepted
     |           DERIVED_FROM
ACTION           route change authorised
```

The relationships are explicit — every later event carries a `DERIVED_FROM` `event_relation` and
an `EVENT` evidence reference to the one before it — and every reference resolves inside the file.
Nothing here generates the chain: no reasoning engine exists in this repository and none is
implied by these six objects sitting in one array (§132, and `spec/sc-oes/README.md` on the
public/private boundary).
