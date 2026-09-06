# ADR 0007 — Legacy `EventType` mapping

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

## Context

§27 keeps the existing CDM `EventType` vocabulary and runs SC-OES beside it:

> Retain the existing `EventType` enum. Do not add new members to make SC-OES fit. The precise
> SC-OES semantic type and the broad legacy CDM EventType remain separate axes.

It then supplies the initial mapping as a thirteen-row table — reproduced in the Decision below,
unchanged — and defines what a `null` row means:

> `null` means: no meaningful legacy category is governed for this semantic type. It does not mean
> unfinished.

**The vocabulary, read from the source rather than from a document.**
`packages/cdm/synapse_cdm/enums.py:52` declares `EventType` with seven members: `DETECTION`,
`GNSS_INTERFERENCE`, `TRACK_UPDATE`, `ALERT`, `STATUS_CHANGE`, `PLAN_INJECT`, `SIM_RESULT`
(reading: 7 members, in that order). None of them carries a docstring, so their meaning is read
from how the shipped adapters use them. Readings taken over
`packages/cdm/synapse_cdm/adapters/`, one `git grep -l` per member:

| member | adapters that emit it | what the tree's own comments say it means |
|---|---|---|
| `DETECTION` | 5 | `stanag4609.py:1819` — "a moving-target indication is a detection in the CDM's sense exactly"; a platform reporting something *else* than itself |
| `GNSS_INTERFERENCE` | 4 | the PNT case, and the three ASTERIX categories that carry a jamming or interference report |
| `TRACK_UPDATE` | 7 | a track or position report; `adsb.py:1383`–`:1384` selects it when the message kind carries position or motion |
| `ALERT` | 6 | `adsb.py:1382` selects it on an emergency condition, in preference to the kind that would otherwise apply |
| `STATUS_CHANGE` | 9 | `asterix_cat023.py:924`–`:925` — "a ground station or a service stating what it is doing is a status change and not a detection"; `stanag4609.py:1816` — "a platform reporting its own state" |
| `PLAN_INJECT` | **0** | declared, emitted by no shipped adapter |
| `SIM_RESULT` | **0** | declared, emitted by no shipped adapter |

Three further readings bear on the mapping.

- **Urgency is a different axis and the tree says so.** `asterix_cat023.py:925`–`:926`: "No type
  produces ALERT, and that is a decision — see `_severity` for the two bits that raise severity
  instead." `Severity` (`enums.py:62`) is a separate field. A governed type must not be mapped to
  `ALERT` because instances of it are often urgent.
- **A track is already a separate canonical kind.** `models.py:434` declares `KINDS` as
  `{"entity", "event", "track", "plan_object"}`, so "a track exists and was updated" has a
  first-class representation in the CDM that is not an `EventType` at all. That matters for the
  one row this ADR moves.
- **`PAYLOAD_MODELS` is already occupied for exactly one member.** `models.py:308` maps
  `EventType.GNSS_INTERFERENCE` to `GnssInterferencePayload` (`models.py:282`), and
  `models.py:304`–`:306` records the rule: registering one "is a MINOR bump; an event_type with no
  entry keeps a free-form payload, which is how a new source lands before its shape is understood
  well enough to pin."

The thirteen governed types, their `EventClass` and their maturity come from §103–§109.

## Decision

**§27's table, adopted verbatim. The mapping is stored in the registry's `legacy_event_type`
field (§110) and nowhere else.**

| `oes.type_id` | `EventClass` | maturity | `legacy_event_type` |
|---|---|---|---|
| `sc.pnt.gnss_interference.v1` | OBSERVATION | DRAFT | `GNSS_INTERFERENCE` |
| `sc.air.air_track_observed.v1` | OBSERVATION | DRAFT | **`null`** |
| `sc.air.runway_availability_changed.v1` | STATE_CHANGE | DRAFT | `STATUS_CHANGE` |
| `sc.air.airspace_restriction_changed.v1` | CONSTRAINT | DRAFT | `STATUS_CHANGE` |
| `sc.logistics.supply_threshold_reached.v1` | STATE_CHANGE | DRAFT | `STATUS_CHANGE` |
| `sc.logistics.route_availability_changed.v1` | STATE_CHANGE | DRAFT | `STATUS_CHANGE` |
| `sc.isr.threat_assessment_updated.v1` | ASSESSMENT | EXPERIMENTAL | **`null`** |
| `sc.c2.system_availability_changed.v1` | STATE_CHANGE | DRAFT | `STATUS_CHANGE` |
| `sc.mission.mission_status_changed.v1` | STATE_CHANGE | DRAFT | `STATUS_CHANGE` |
| `sc.mission.operational_impact_assessed.v1` | IMPACT | EXPERIMENTAL | **`null`** |
| `sc.decision.recommendation_created.v1` | RECOMMENDATION | EXPERIMENTAL | **`null`** |
| `sc.decision.decision_recorded.v1` | DECISION | EXPERIMENTAL | **`null`** |
| `sc.decision.action_authorized.v1` | ACTION | EXPERIMENTAL | **`null`** |

**Six `null`s and seven mappings.** The `EventClass` and maturity columns are §103–§109's; the
`legacy_event_type` column is §27's.

**`sc.air.air_track_observed.v1` is `null`, and this reverses what this ADR proposed.** While
`Proposed` it mapped the row to `TRACK_UPDATE` on the reading that the member is what the shipped
adapters already emit for a track or position report — the table above counts seven. §27 rules otherwise, and the tree supports the ruling once §28's
cost is priced. Three readings:

- **A non-null mapping is *enforced*, not merely suggested.** §28: where the registry declares a
  non-null mapping, "conformance checks compare the actual `Event.event_type`" and a "mismatch
  produces semantic conformance failure". So the column must name the one broad category that is
  correct for *every* honest producer of that semantic type, not the most common one.
- **Two broad categories are honestly defensible for the same air-track observation**, and the
  tree's own comments are what make both defensible: `adsb.py:1383`–`:1384` reaches for
  `TRACK_UPDATE` when a message carries position or motion, while `stanag4609.py:1819` reaches for
  `DETECTION` when a platform reports something other than itself — and an air track observed by a
  sensor is both descriptions of one occurrence, depending on the source. Governing one of them
  would fail conformance for a producer that chose the other correctly.
- **The CDM already represents a track without using this axis at all** (`models.py:434`'s
  `track` kind), so the broad category is not carrying the load a reader might assume it is.

That is §27's `null` definition exactly: no meaningful legacy category is *governed*. It is not
"unfinished", and it does not stop a producer from setting `TRACK_UPDATE` — under §28's null
branch, "ordinary CDM semantics determine the broad EventType."

Three rules go with the table.

1. **The mapping is not required to be onto.** `DETECTION`, `TRACK_UPDATE`, `ALERT`, `PLAN_INJECT`
   and `SIM_RESULT` are the expected legacy type of no governed type in v0.1. `DETECTION`,
   `TRACK_UPDATE` and `ALERT` remain in heavy use by shipped adapters that emit no SC-OES block at
   all (readings above: 5, 7 and 6 respectively); `PLAN_INJECT` and `SIM_RESULT` are
   emitted by no adapter today, and this ADR does not press them into service to make a table look
   complete.
2. **The mapping is expected, not enforced at the model.** §28's second and third bullets: a
   mismatch "produces semantic conformance failure" and "the validator must not silently rewrite
   `event_type`". So a producer that sets `oes.type_id` and an `event_type` disagreeing with the
   registry fails conformance dimension C (ADR 0009) with a message naming both values. It is not
   a validation error on the model, because `Event.event_type` is a required CDM field with its
   own meaning and SC-OES does not get to overrule it silently.
3. **No new `EventType` member is added.** §27: "Do not add new members to make SC-OES fit."
   Adding a member is a MINOR schema bump under `MIGRATIONS.md:21` on its own, and a member added
   to serve SC-OES would make the two vocabularies converge, which is the opposite of §27's
   separate-axes design. `enums.py` does not change in this campaign.

**Payload models.** `OES_PAYLOAD_MODELS` is keyed by exact `type_id` (§111) and, for
`sc.pnt.gnss_interference.v1`, reuses `GnssInterferencePayload` (`models.py:282`) rather than
duplicating it — §112: "Reuse the existing `GnssInterferencePayload`. Do not duplicate it." §112
also fixes the scope: "Do not prematurely type all thirteen event payloads … For v0.1, implement
one governed typed payload." The other twelve stay free-form and transportable, which is
`models.py:305`'s documented behaviour and §111's "Unknown event types retain free-form payloads.
Extra source-specific payload fields survive" at once.

## Alternatives considered

**A — map every governed type to its nearest legacy member, so the table has no nulls.** Rejected
by §27's own definition of the null branch. The concrete harm is in dimension C and in consumer
filters — a legacy consumer subscribing to `DETECTION` would start receiving threat assessments,
and would be receiving an interpretation while believing it was receiving an observation. §62 is
the specification's name for that failure ("An observation MUST NOT silently become an
assessment"); the repository's own version is `asterix_cat023.py:925`, which refuses to reach for
`ALERT` when the honest answer is a status change plus a severity.

**B — extend `EventType` with `ASSESSMENT`, `DECISION` and the rest.** It would remove the nulls
honestly rather than by stretching. Rejected by §27's second sentence in as many words, and
because it is a schema change to the legacy vocabulary in order to serve the vocabulary that runs
beside it — which would make `event_type` and `type_id` two spellings of one fact. The nulls are
the correct signal that the legacy vocabulary was never designed for the decision domain.

**C — map `sc.air.air_track_observed.v1` to `TRACK_UPDATE`**, this ADR's proposed decision.
Rejected by §27 and, on the tree, by the three readings above: §28 makes a declared mapping a
conformance obligation, and two members are honestly defensible for the same occurrence, so
governing either one would fail a correct producer.

**D — make `legacy_event_type` a per-producer decision rather than a registry field.** Rejected:
§27 supplies one table for the whole vocabulary and §110 gives it a registry field that "must be
present even when its value is null". A per-producer choice would make the same governed type
arrive under different broad categories from different systems, which is the interoperability
problem the registry exists to close.

**E — enforce the mapping in the model, rejecting a mismatched `event_type`.** Rejected by §28's
"the validator must not silently rewrite `event_type`" and by the consequence: it would make an
SC-OES rule a hard CDM validation failure, so an adapter adding an `oes` block could suddenly fail
on events it has emitted correctly for versions. Conformance dimension C reports it, which is what
a separately reportable dimension is for (ADR 0009).

**F — map `sc.decision.action_authorized.v1` to `PLAN_INJECT`.** The nearest available member, and
tempting because `PLAN_INJECT` is otherwise unused (reading: 0 adapters). Rejected on the reading
that it is unused: nothing in the tree establishes what it means in practice, so the mapping would
be defined by this ADR rather than discovered, and §27's null branch is precisely the instruction
for that case.

## Consequences

- Thirteen registry entries carry `legacy_event_type`, six of them explicitly `null` — present
  with a null value, never absent. §110 requires exactly that: "The key `legacy_event_type` must
  be present even when its value is null." Registry validation (§139) asserts it on every entry.
- `get_legacy_event_type(type_id)` (§126) returns `None` for those six, and its docstring says
  that `None` means "no meaningful legacy category is governed", not "unknown".
- Conformance dimension C gains a check comparing `Event.event_type` with the registry's
  expectation for the seven non-null rows; it reports and does not raise.
- `OES_PAYLOAD_MODELS` has one entry in v0.1, reusing an existing model, so it registers no new
  payload model and adds no MINOR signal of its own beyond the one ADR 0005 already carries.
- `EventType` is untouched; `enums.py` does not change in this campaign.
- **Three of the seven members are the expected legacy type of nothing**, up from two while this
  ADR was proposed. That is a fact about the vocabulary rather than a gap, and the profile and
  registry documents state it rather than leaving a reader to count.

## Compatibility impact

- **The legacy vocabulary is unchanged**, which is §27's first sentence. No member is added,
  removed or redefined, so `MIGRATIONS.md:20`'s "an enum member removed" is not reached and
  neither is `:21`'s "an enum member added". The campaign's schema MAJOR is ADR 0005's and does
  not come from this ADR.
- **Existing adapters keep emitting exactly what they emit today.** None of them sets `oes`, so
  none of them is judged against this table — §116 makes that explicit and calls the distinction
  intentional.
- **A legacy consumer filtering on `event_type` sees no change in behaviour**: an SC-OES-aware
  producer sets the same broad category the table expects, and a governed type with a `null`
  expectation is one whose producer chooses its own `event_type` under ordinary CDM rules (§28).
- **Adding a governed type later** adds a registry entry and, if it maps, an expectation; both are
  data changes under §119's proposal process, not schema changes.

## Security impact

- **The null branch is the security-relevant half.** A stretched mapping causes semantic poisoning
  by mislabelling — §127 names "semantic poisoning" directly — and an assessment arriving in a
  consumer's detection stream is an interpretation presented as an observation. Downstream that
  difference is the difference between a fix and a guess, which is the distinction `enums.py:41`
  says the CDM exists to preserve in the analogous case of position source.
- **Unknown types are preserved, not mapped.** §124 is normative and this ADR does not weaken it:
  an unregistered `type_id` gets no legacy expectation, keeps a free-form payload
  (`models.py:305`) and is transported, stored, forwarded, audited and displayed opaquely. "The
  consumer must not silently convert it to a known `sc.*` type."
- **A mismatch is reported, not silently corrected.** Dimension C names both values. Correcting an
  `event_type` to match the registry would be an adapter enriching data, and `adapter.py:5`–`:7`
  forbids exactly that — "No filtering …, no enrichment …, no business logic …. Each of those is a
  DECISION, and a decision made inside a translator is a decision nobody can find later." §157
  repeats the rule for the one adapter that does gain SC-OES semantics: "Do not enrich source
  information."
- **Urgency stays on its own axis.** Refusing `ALERT` as a mapping target keeps severity a
  producer's assertion about severity rather than something inferable from a semantic type.

## Reversibility

Moderate. The mapping is data in the registry, so changing one entry is a data change plus a
registry-validation run — not a code or schema change.

What is less reversible is a mapping that has been *published and relied on*: a consumer filtering
on the broad category will have built expectations on it, and moving `STATUS_CHANGE` to something
else later would silently change what such a filter receives. §122's deprecation rules apply to
governed identifiers rather than to this field, so the discipline here is the one this ADR now
follows — map only where one category is correct for every honest producer, and leave the rest
null, since turning a null into a mapping later is additive while changing a mapping is not. The
`air_track_observed` correction is that discipline applied before publication, which is the only
time it is free.
