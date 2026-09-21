# C2SIM egress fixtures — fresh export of records this adapter never produced

Three CDM records written as if by a planning stub (`source.adapter: planner_stub`, UUIDs under
the fictitious `c2510000-001x-` prefix), so the `from_cdm` direction is proved on input this
adapter did not make — the round trip through the harness is self-consistency, and this is the
other half. Each carries its typed block built through `c2sim_codec`'s models and NO residual;
under `golden/` is the document `from_cdm` emits for each, validated against the pinned XSD.

| Record | Objects | Emits | Header from |
|---|---|---|---|
| `fresh_initialisation_side_unit_platform_route.json` | a ForceSide, a Unit with state and a subordinate, an Aircraft, a Route (three points, one with an MSL height) | `C2SIMInitializationBody` with the scenario setting from the blocks and the `SystemEntityList` from the Envelope | `Envelope(...)` — no block carries a message |
| `fresh_order_move_and_hold.json` | one PLAN_INJECT event: a MoveToLocation task (DateTime start, SimulationTime end, a destination, a MapGraphicID) and a HoldInPlace task related STRSTR to it | `OrderBody` with two tasks in order | the payload's own `message` |
| `fresh_report_position_no_header.json` | one TRACK_UPDATE event: a position with an MSL height and a strength | `ReportBody` with one `PositionReportContent` | `Envelope(...)` |

`tests/test_cdm_c2sim_adapter.py::test_every_egress_fixture_emits_its_golden_and_validates`
compares byte for byte and validates (BLOCKED, not PASS, without the resource). What is refused
rather than invented: an Entity with no `attributes.c2sim` block, a Unit with no echelon, a Route
with no classification, a task outside the two pinned forms, an initialisation with no
`SystemEntityList`, and objects that cannot share one message.
