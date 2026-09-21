# Digital NOTAM fixtures — adapter #19 (`aixm511`), Event Schema 2.0.m on AIXM 5.1.1

The Digital NOTAM half of the `aixm511` fixtures (adapter expansion phase 5, 2026-09-21): synthetic
`message:AIXMBasicMessage` documents that carry an `event:Event` (Digital NOTAM Event Schema
2.0.m, namespace `http://www.aixm.aero/schema/5.1.1/event`) beside the feature time slices it
binds through `event:theEvent`, coded after the three scenario families the Digital NOTAM
Specification 2.0 (**DRAFT** — "in preparation", validated by implementation, never an approved
final standard) pins: `RWY.CLS` (runway closure), `ATSA.ACT` / `SAA.ACT` (airspace activation)
and `NAV.UNS` (navaid unserviceable), every one at scenario version `2.0`.

**Every one is synthetic and reproducible.** `spec/build_fixtures.py` writes every file here
(`--check` proves the committed files are what it writes); the aerodrome `ZZSY`, the designators
`SYN*`, the UUIDs under `a1a40000-00d0-` (features) and `a1a40000-00e0-` (Events) and every instant
are fictitious, and no file derives from a published aeronautical data set. Every positive document
validates against the pinned AIXM 5.1.1 + Event 2.0.m closure through the `dnotam` normative binding
(`tests/test_cdm_aixm511_dnotam.py`; `BLOCKED_EXTERNAL_EVIDENCE`, never a pass, when the resource is
absent), and every `.parsed.json` twin is re-derived from its XML with the standard library alone.
`../spec/aixm511_pin.json` records each file's SHA-256.

## The harness set (this directory)

Replayed by
`python -m synapse_cdm.harness --adapter synapse_cdm.adapters.aixm511:Aixm511Adapter --fixtures <this directory>`
— the module form, because this directory is a second collection beside the adapter's own and
the registered name resolves only that one; the
goldens under `golden/` are its output over each XML and each twin.

| Fixture | Reading |
|---|---|
| `rwy_cls_baseline_and_closure.xml` | RWY.CLS: an aerodrome and FIR BASELINE (so the Event's `concernedAirportHeliport` / `concernedAirspace` resolve — RWY.CLS.05, .06), the RunwayDirection BASELINE (NORMAL), the Event BASELINE 1.0 with its NOTAMN, the RunwayDirection TEMPDELTA 1.0 with the NORMAL copy beside the CLOSED branch (RWY.CLS.03) and `event:theEvent` (RWY.CLS.02) |
| `atsa_act_baseline_and_activation.xml` | ATSA.ACT: a TMA whose BASELINE activation is scheduled (ACTIVE 07:00–21:00 / INACTIVE, typed and not asserted), the Event, the TEMPDELTA activating the whole TMA (ACTIVE, FLOOR/CEILING — ER-02) |
| `saa_act_activation_with_schedule.xml` | SAA.ACT: a TSA (BASELINE INACTIVE), the Event, a TEMPDELTA with ACTIVE under a Timesheet and the INACTIVE baseline copy with the prescribed REMARK (ER-05, ER-06) — the resolved view is SCHEDULED |
| `nav_uns_baseline_and_outage.xml` | NAV.UNS: a VOR/DME Navaid and its VOR component (a NavaidEquipment feature — read generically, its availability carried), the Event, the VOR TEMPDELTA UNSERVICEABLE (NAV.UNS.02) and the Navaid TEMPDELTA type DME / PARTIAL (NAV.UNS.05, .06) |
| `future_effective_change.xml` | a closure whose window lies after the instants the tests resolve at: FUTURE, then applied from its begin exactly |
| `overlapping_tempdeltas.xml` | two RWY.CLS Events whose TEMPDELTAs overlap on one runway direction (06:00–10:00 and 08:00–12:00): TS_011 is broken between 08:00 and 10:00 and the resolver reports AMBIGUOUS, applying neither |
| `explicit_nil_values.xml` | `estimatedValidity xsi:nil`, `activity` nil with a nilReason, and a Navaid TEMPDELTA stating its availability as ONE nil occurrence (§4.4.6.3) — WITHDRAWN, never OPERATIONAL |
| `unresolved_references.xml` | `theEvent`, `concernedAirspace` and `concernedAirportHeliport` name features outside the document and no baseline is present: every reference kept and listed, the view UNRESOLVED |
| `corrections_out_of_order.xml` | immediate termination (page 220791154) with the corrections placed BEFORE the slices they correct: Event BASELINE 1.1 (end 08:00, NOTAMC) before 1.0, TEMPDELTA 1.1 before 1.0 |
| `expiry.xml` | an Event with an ESTIMATED end (`estimatedValidity`, NOTAM `estimatedEnd` YES) whose TEMPDELTA ends at 10:00: applied at 09:59:59, EXPIRED at 10:00:00 |

## `cases/` — read by name, not by the harness

| Fixture | Reading |
|---|---|
| `cancellation.xml` | an inactive Event cancelled before effect: Event BASELINE 1.1 and TEMPDELTA 1.1 with an empty `gml:validTime` (`nilReason="inapplicable"`, §4.4.8). A cancelled slice states no instant, so the adapter reads it only under `Aixm511Adapter(as_of=…)` — which is why it is not in the harness set |

## `counterexamples/` — which layer catches what

Two classes, each shown at its layer. The **schema layer** is `normative_validation` (lxml against the
pinned closure); the **rule layer** is the adapter's scenario reading (`attributes.dnotam.rule_findings`,
`validate_source`). The adapter's structural reading accepts all four and loses nothing.

| Counterexample | Class | Schema layer | Rule layer | Adapter |
|---|---|---|---|---|
| `schema_invalid_unknown_event_property.xml` | well-formed, schema-INVALID | INVALID (`event:closureReason` not expected) | nothing to say | reads it; the element sits in the residual |
| `schema_invalid_event_schema_1_0_namespace.xml` | well-formed, schema-INVALID | INVALID (an Event in `…/5.1/event` is not declared) | `theEvent` names a member that is not an `event:Event` | the old-namespace member is not an AIXM feature (carried whole in the residual); the TEMPDELTA's binding is unresolved |
| `rule_invalid_rwy_cls_on_an_airspace.xml` | schema-VALID, rule-INVALID | VALID | `RWY.CLS RWY.CLS.02: the Event binds a <aixm:Airspace> slice; the profile's TEMPDELTA sits on ['aixm:RunwayDirection']` | reads it |
| `rule_invalid_rwy_cls_without_closed_status.xml` | schema-VALID, rule-INVALID | VALID (LIMITED is in the enumeration) | `RWY.CLS RWY.CLS.03: no aixm:ManoeuvringAreaAvailability on the TEMPDELTA states operationalStatus in ['CLOSED']` | reads it |

## What the goldens show

- **The Event is a feature.** Each `event:EventTimeSlice` is one Entity (type UNKNOWN — the CDM has
  no structural class for an operational situation), identity from the Event's `gml:identifier`,
  `attributes.aixm` the `aixm-timeslice/1` block (interpretation, numbers, validTime, featureLifetime,
  the `EventPropertyGroup` scalars as `properties`, `concernedAirspace` / `concernedAirportHeliport` /
  `parentEvent` / `causeEvent` / `provider` as `references`) and `attributes.dnotam` the
  `aixm-dnotam/1` block: `role: event`, the scenario and version as stated, the pinned `profile`
  (identifier, version, guidance page and page version, rule ids, DRAFT), the NOTAM objects typed
  beside their verbatim source, and the **source assertion** — `initial`, `correction`,
  `cancellation`, `termination` (a NOTAM C) or `replacement` (a NOTAM R) — with its temporal basis
  (`effective_from` / `effective_to`, `lifetime_end`, `estimated_end`, the NOTAM types).
- **A bound feature slice** carries `attributes.dnotam` with `role: affected-feature`: the extension
  element and gml:id, `the_event` (resolved in the document or the caller's table, or kept
  unresolved), the Event's scenario, its own source assertion and the scenario rule layer's
  findings. The extension itself is READ and NOT consumed: it stays in the residual at its position,
  so a foreign extension beside it keeps the same shape.
- **Nothing is resolved by the adapter.** The baseline NORMAL and the TEMPDELTA CLOSED are two
  Entities; `synapse_cdm.aixm_resolve` is what turns them into a view at an instant, and only when
  a caller hands it both.
