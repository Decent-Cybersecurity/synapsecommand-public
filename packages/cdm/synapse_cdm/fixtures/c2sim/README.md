# C2SIM fixtures — adapter #18, SISO-STD-019-2020 v1.0 (C2SIMArtifacts v1.0.1 schema)

These are the harness fixtures for `adapters/c2sim.py`: five synthetic messages, one per message
kind the adapter reads, each as the XML the wire carries and as a `.parsed.json` twin — the
codec's dict form of the same document (`c2sim_codec.twin_of`: repeatable children as lists,
text-only elements as text, document order kept). The harness translates both; the twin is what
the path-bound preservation ledger walks and what the `values` round trip re-ingests, so every
leaf of every message is accounted for.

**Every one is synthetic.** Hand-written on 2026-09-21 for the case each exercises. Every name is
prefixed `EXERCISE`, every UUID sits under the `c2510000-` prefix, no coordinate describes a real
unit, and no file derives from any recorded exercise. `spec/c2sim_pin.json` records each file's
SHA-256 and byte count. Two independent readings hold the adapter's own parse honest: every `.xml`
validates against the pinned XSD closure through an actual validator (`normative_validation.py`,
lxml, the `validate` extra — `BLOCKED_EXTERNAL_EVIDENCE` and never a pass when the resource is
absent), and every twin is re-derived from the XML with the standard library alone in
`tests/test_cdm_c2sim_adapter.py::test_every_parsed_twin_corresponds_to_its_raw_fixture`.

**Required configuration for the normative reading, and nothing for translation.** `to_cdm` needs
no configuration, no file outside the package and no network. The schema validation above runs
only when two things are present: the `validate` optional extra (`pip install
"synapse-cdm[validate]"`, lxml) and the environment variable `SYNAPSE_CDM_C2SIM_XSD_DIR` naming a directory OUTSIDE
this repository that holds `xsd_pin.json` and the pinned closure of C2SIMArtifacts v1.0.1 (`C2SIM_SMX_LOX.xsd` and its imports); the layout is
`normative_binding.py`'s and the resolver is `normative_validation.py`. This closure imports by
relative path and is self-contained, so no XML catalog is needed for it (the AIXM bindings need
one). With either absent the check records `BLOCKED_EXTERNAL_EVIDENCE` and passes nothing.

## The fixtures, and what each one is for

| Fixture | Body | Exercises |
|---|---|---|
| `initialisation_three_sides.xml` | `C2SIMInitializationBody` | three force sides with their stated hostility relations (HO, NEUTRL, SUSPCT); a battalion headquarters with two companies under it (Superior / Subordinate / CommandRelation OPCON), one RED and one GREEN unit; an aircraft, a vehicle and a surface vessel; a unit with two locations; a zero speed and a zero heading (real values); the same latitude on two units; APP-6, DIS and named classifications; a unit resource and two system entity lists (residual) |
| `order_move_to_location.xml` | `OrderBody` | one `MoveToLocation` task with a destination Location, a MapGraphicID naming a Route outside the message, a DateTime start, a SimulationTime end (typed, unresolved without a clock), a duration, an affected entity, a desired effect and a temporal relationship to a task outside the order |
| `order_hold_in_place.xml` | `OrderBody` | two `HoldInPlace` tasks: one with a RelativeTime start against an outside event, a duration and a rule of engagement (residual); one temporally (STRSTR) and functionally (IOT) related to the first, so one dependency resolves inside the order; a TaskReference to an outside task; `InReplyToMessageID` and `ReplyToSystem` in the header |
| `report_position_two_subjects.xml` | `ReportBody` / `PositionReportContent` ×2 | one reporting entity, two subjects; an MSL height, health (operational status and strength) and a duration on the first; a zero AGL height on the second; the same longitude on both |
| `report_status_observations.xml` | `ReportBody` / `ObservationReportContent` + `TaskStatus` | a health observation with a confidence, a location observation with heading, speed and uncertainty, a name observation with a hostility code, an activity observation the adapter keeps untyped, and a task status about the move order's task |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter c2sim --update-golden` and read before being kept.

## What the goldens show, and where to look

- **An initialisation object's typed block** is `attributes.c2sim` (`c2sim-object/1`): class,
  UUID, names, classifications as source vocabulary, every organisational relationship with its
  endpoints as C2SIM UUIDs, the physical state (every location, motion, health), the header and
  the scenario setting. A Route map graphic is a ROUTE `PlanObject` whose block sits at
  `route.metadata.c2sim` — it is exercised from `cases/` (below), not from a harness fixture: a
  route's points sit seventeen or eighteen containers deep in the twin, past the harness loader's
  margin (`harness.LOADER_MAX_DEPTH / 4`), and the twin already drops the one root the schema
  permits to keep a unit's position at sixteen.
- **A report content** is an `Event` whose `payload.c2sim` is `c2sim-report/1`; **an order** is
  a PLAN_INJECT `Event` whose `payload.c2sim` is `c2sim-order/1`, tasks in order.
- **Affiliation is UNKNOWN in every golden**: the harness names no own side, and
  `attributes.c2sim.affiliation_basis` says so. `tests/test_cdm_c2sim_adapter.py` reads the same
  message with `own_side=` and shows FRIENDLY / HOSTILE / NEUTRAL / UNKNOWN by the stated relations.
- **`residual.data`** mirrors the message's content — `C2SIMHeader` and `MessageBody` minus what
  became an object (the header and the scenario setting stay, on every object, so a PlanObject
  carries them too), and any member the root itself carried;
  **`residual.data.Entity` / `AbstractObject` / `ReportContent` / `Task[]`** is the object's own
  element minus what the typed block consumed, list positions kept (`null` marks a consumed item).
- **`source.original_id`** is the message's `MessageID`; **`source.observed_at`** the header's
  `SendingTime`; **`source_ids[0].external_id`** the object's C2SIM UUID (a report's is
  `<ReportID>#<index>`); **`related_entities`** on an event the derived ids of the entities it
  concerns.

## The other directories

- `malformed/` — fourteen refusal payloads (wrong namespace/version, missing header fields, an
  unresolved reference, duplicate ids, an unsupported task code, a move without a destination, a
  position report without a location, a malformed timestamp, a SimulationTime without a clock, a
  RelativeTime observation, a system command body, a DTD, a truncated document, an over-depth
  document); check H and `test_every_malformed_payload_is_refused_by_name`.
- `cases/` — seven accepted counterexamples the harness never selects (a Route map graphic in an
  initialisation and in an order, simulation time under an exercise clock, out-of-order reports,
  codes outside the pinned enumerations, extension fields, untyped object classes); each read by
  name in the tests, the two Route documents with the ledger, egress and schema validity asserted
  on them.
- `egress/` — three CDM records a planning stub wrote, and under `egress/golden/` the document
  `from_cdm` emits for each, validated against the pinned XSD.
- `spec/c2sim_pin.json` — the record of all of the above.
