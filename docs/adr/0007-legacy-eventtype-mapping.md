# ADR 0007 — Legacy `EventType` mapping

## Status

Proposed — awaiting M's review.

## Context

§32 keeps the existing CDM `EventType` vocabulary and runs SC-OES beside it:

> `event_type` = broad CDM compatibility category; `oes.type_id` = precise semantic SC-OES
> identifier.

It then requires that "For every governed `sc.*` event type, define exactly one expected legacy
EventType where meaningful", and — the clause that decides half of this ADR — "If no meaningful
mapping exists, explicitly store null rather than inventing one."

**The vocabulary, read from the source rather than from a document.**
`packages/cdm/synapse_cdm/enums.py:52` declares `EventType` with seven members: `DETECTION`,
`GNSS_INTERFERENCE`, `TRACK_UPDATE`, `ALERT`, `STATUS_CHANGE`, `PLAN_INJECT`, `SIM_RESULT`. None
of them carries a docstring, so their meaning is read from how the shipped adapters use them.
Readings taken over `packages/cdm/synapse_cdm/adapters/`:

| member | adapters that emit it | what the tree's own comments say it means |
|---|---|---|
| `DETECTION` | 5 | `stanag4609.py:1819` — "a moving-target indication is a detection in the CDM's sense exactly"; a platform reporting something *else* than itself |
| `GNSS_INTERFERENCE` | 4 | the PNT case, and the three ASTERIX categories that carry a jamming or interference report |
| `TRACK_UPDATE` | 7 | a track or position report; `adsb.py:1383`–`:1384` selects it when the message kind carries position or motion |
| `ALERT` | 6 | `adsb.py:1382` selects it on an emergency condition, in preference to the kind that would otherwise apply |
| `STATUS_CHANGE` | 9 | `asterix_cat023.py:924`–`:925` — "a ground station or a service stating what it is doing is a status change and not a detection"; `stanag4609.py:1816` — "a platform reporting its own state" |
| `PLAN_INJECT` | **0** | declared, emitted by no shipped adapter |
| `SIM_RESULT` | **0** | declared, emitted by no shipped adapter |

Two further readings bear on the mapping.

- **Urgency is a different axis and the tree says so.** `asterix_cat023.py:925`–`:926`: "No type
  produces ALERT, and that is a decision — see `_severity` for the two bits that raise severity
  instead." `Severity` (`enums.py:62`) is a separate field. A governed type must not be mapped to
  `ALERT` because instances of it are often urgent.
- **`PAYLOAD_MODELS` is already occupied for exactly one member.** `models.py:307` maps
  `EventType.GNSS_INTERFERENCE` to `GnssInterferencePayload` (`models.py:282`), and
  `models.py:304`–`:306` records the rule: registering one "is a MINOR bump; an event_type with no
  entry keeps a free-form payload, which is how a new source lands before its shape is understood
  well enough to pin."

The thirteen governed types and their `EventClass` come from §88.

## Decision

**One expected legacy `EventType` per governed type where the vocabulary has a member that means
it; explicit `null` for the five where it does not. The mapping is stored in the registry's
`legacy_event_type` field (§31) and nowhere else.**

| `oes.type_id` | `EventClass` (§88) | `legacy_event_type` | the reading that decides it |
|---|---|---|---|
| `sc.pnt.gnss_interference.v1` | OBSERVATION | `GNSS_INTERFERENCE` | the member exists for this exact case and four adapters already emit it; §32's own worked example |
| `sc.air.air_track_observed.v1` | OBSERVATION | `TRACK_UPDATE` | the member the shipped adapters already emit for a track or position report; `adsb.py:1383`–`:1384` selects it when the message kind carries position or motion |
| `sc.air.runway_availability_changed.v1` | STATE_CHANGE | `STATUS_CHANGE` | a service stating what it is doing (`asterix_cat023.py:924`) |
| `sc.air.airspace_restriction_changed.v1` | CONSTRAINT | `STATUS_CHANGE` | the represented availability of an airspace changing; the class distinction is carried by `event_class`, not by the broad category |
| `sc.logistics.supply_threshold_reached.v1` | STATE_CHANGE | `STATUS_CHANGE` | a represented level crossing a threshold is a state change; urgency goes to `Severity`, not to `ALERT` |
| `sc.logistics.route_availability_changed.v1` | STATE_CHANGE | `STATUS_CHANGE` | as above |
| `sc.isr.threat_assessment_updated.v1` | ASSESSMENT | **`null`** | no member means an interpreted judgement; `DETECTION` would assert an observation the event does not make |
| `sc.c2.system_availability_changed.v1` | STATE_CHANGE | `STATUS_CHANGE` | `stanag4609.py:1816`, a thing reporting its own state |
| `sc.mission.mission_status_changed.v1` | STATE_CHANGE | `STATUS_CHANGE` | as above |
| `sc.mission.operational_impact_assessed.v1` | IMPACT | **`null`** | an impact assessment is a judgement; no member means it |
| `sc.decision.recommendation_created.v1` | RECOMMENDATION | **`null`** | no member means a recommendation; `PLAN_INJECT` is about injecting a plan, not about proposing one |
| `sc.decision.decision_recorded.v1` | DECISION | **`null`** | no member means a decision |
| `sc.decision.action_authorized.v1` | ACTION | **`null`** | no member means an authorisation; `PLAN_INJECT` is the nearest and it is not the same act |

Five `null`s, and every one of them is §32's explicit-null branch taken deliberately.

Three rules go with the table.

1. **The mapping is not required to be onto.** `DETECTION`, `ALERT`, `PLAN_INJECT` and
   `SIM_RESULT` are the expected legacy type of no governed type in v0.1. `DETECTION` and `ALERT`
   remain in heavy use by shipped adapters that emit no SC-OES block at all; `PLAN_INJECT` and
   `SIM_RESULT` are emitted by no adapter today, and this ADR does not press them into service to
   make a table look complete.
2. **The mapping is expected, not enforced.** A producer that sets `oes.type_id` and an
   `event_type` disagreeing with the registry's `legacy_event_type` fails conformance dimension C
   (ADR 0009) with a message naming both. It is not a validation error on the model, because
   `Event.event_type` is a required CDM field with its own meaning and SC-OES does not get to
   overrule it silently.
3. **No new `EventType` member is added.** §32 says do not remove the vocabulary; it does not ask
   to extend it, adding a member is a MINOR schema bump under `MIGRATIONS.md:21` on its own, and a
   member added to serve SC-OES would make the two vocabularies converge, which is the opposite of
   §32's parallel-track design.

**Payload models.** `OES_PAYLOAD_MODELS` is keyed by `type_id` and, for
`sc.pnt.gnss_interference.v1`, reuses `GnssInterferencePayload` (`models.py:282`) rather than
duplicating it — §63 says reuse and do not duplicate, and the model already carries exactly the
fields it names. It is `extra="allow"` (`models.py:291`), which is the lossless behaviour §61
requires. No other governed type gets a typed payload in v0.1; the rest stay free-form and
transportable, which is `models.py:305`'s documented behaviour and §27's requirement at once.

## Alternatives considered

**A — map every governed type to its nearest legacy member, so the table has no nulls.** Rejected
by §32's own instruction: "explicitly store null rather than inventing one." The concrete harm is
in dimension C and in consumer filters — a legacy consumer subscribing to `DETECTION` would start
receiving threat assessments, and would be receiving an interpretation while believing it was
receiving an observation. §23 is the specification's name for that failure ("Observation must not
become assessment silently"); the repository's own version is `asterix_cat023.py:925`, which
refuses to reach for `ALERT` when the honest answer is a status change plus a severity.

**B — extend `EventType` with `ASSESSMENT`, `DECISION` and the rest.** It would remove the nulls
honestly rather than by stretching. Rejected: it is a schema change to the legacy vocabulary in
order to serve the vocabulary that replaces it, and it makes `event_type` and `type_id` two
spellings of one fact — which §32's two-line definition exists to prevent. The nulls are the
correct signal that the legacy vocabulary was never designed for the decision domain.

**C — make `legacy_event_type` a per-producer decision rather than a registry field.** Rejected:
§32 says "For every governed `sc.*` event type, define exactly one expected legacy EventType",
which is a property of the type and not of the producer, and §31 gives it a registry field. A
per-producer choice would make the same governed type arrive under different broad categories from
different systems, which is the interoperability problem the registry exists to close.

**D — enforce the mapping in the model, rejecting a mismatched `event_type`.** Rejected: it makes
an SC-OES rule a hard CDM validation failure, so an adapter adding an `oes` block could suddenly
fail on events it has emitted correctly for versions. Conformance dimension C reports it, which is
what a separately reportable dimension is for (ADR 0009).

**E — map `sc.decision.action_authorized.v1` to `PLAN_INJECT`.** The nearest available member, and
tempting because `PLAN_INJECT` is otherwise unused. Rejected on the reading that it is unused:
nothing in the tree establishes what it means in practice, so the mapping would be defined by this
ADR rather than discovered, and §32's null branch is precisely the instruction for that case.

## Consequences

- Thirteen registry entries carry `legacy_event_type`, five of them explicitly `null` — present
  with a null value, never absent, so that "no meaningful mapping" is distinguishable from "not
  filled in yet". Registry validation (§119) asserts that the key is present on every entry.
- `get_legacy_event_type(type_id)` (§103) returns `None` for those five, and its docstring says
  that `None` means "no meaningful legacy category", not "unknown".
- Conformance dimension C gains a check comparing `Event.event_type` with the registry's
  expectation; it reports and does not raise.
- `OES_PAYLOAD_MODELS` has one entry in v0.1, reusing an existing model, so it registers no new
  payload model and adds no MINOR signal of its own beyond the one ADR 0005 already carries.
- `EventType` is untouched; `enums.py` does not change in this campaign.

## Compatibility impact

- **The legacy vocabulary is unchanged**, which is §32's first sentence. No member is added,
  removed or redefined, so `MIGRATIONS.md:20`'s "an enum member removed" is not reached and
  neither is `:21`'s "an enum member added".
- **Existing adapters keep emitting exactly what they emit today.** None of them sets `oes`, so
  none of them is judged against this table.
- **A legacy consumer filtering on `event_type` sees no change in behaviour**: an SC-OES-aware
  producer sets the same broad category the table expects, and a governed type with a `null`
  expectation is one whose producer chooses its own `event_type` under ordinary CDM rules.
- **Adding a governed type later** adds a registry entry and, if it maps, an expectation; both are
  data changes under §93's proposal process, not schema changes.

## Security impact

- **The null branch is the security-relevant half.** A stretched mapping causes semantic
  poisoning by mislabelling: an assessment arriving in a consumer's detection stream is an
  interpretation presented as an observation, and downstream that difference is the difference
  between a fix and a guess — which is the distinction `enums.py:41` says the CDM exists to
  preserve in the analogous case of position source.
- **Unknown types are preserved, not mapped.** §27 is normative and this ADR does not weaken it:
  an unregistered `type_id` gets no legacy expectation, keeps a free-form payload
  (`models.py:305`) and is transported, stored, forwarded, audited and displayed opaquely. It is
  never silently mapped to a similar known type.
- **A mismatch is reported, not silently corrected.** Dimension C names both values. Correcting an
  `event_type` to match the registry would be an adapter enriching data, and `adapter.py:5`–`:7`
  forbids exactly that — "No filtering …, no enrichment …, no business logic …. Each of those is a
  DECISION, and a decision made inside a translator is a decision nobody can find later."

- **Urgency stays on its own axis.** Refusing `ALERT` as a mapping target keeps severity a
  producer's assertion about severity rather than something inferable from a semantic type.

## Reversibility

Moderate. The mapping is data in the registry, so changing one entry is a data change plus a
registry-validation run — not a code or schema change.

What is less reversible is a mapping that has been *published and relied on*: a consumer filtering
on the broad category will have built expectations on it, and moving `STATUS_CHANGE` to something
else later would silently change what such a filter receives. §96's deprecation rules apply to
governed identifiers rather than to this field, so the discipline here is the one this ADR follows
— map only where the reading supports it, and leave the rest null, since turning a null into a
mapping later is additive while changing a mapping is not.
