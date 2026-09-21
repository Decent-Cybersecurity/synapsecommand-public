#!/usr/bin/env python3
"""Demonstration 1 — C2SIM initialisation, a supported order, position and status reports, and a
deterministic replay from the recorded messages, offline.

    python examples/c2sim/run.py            # run and check; exit 0 on agreement
    python examples/c2sim/run.py --update   # rewrite expected/ from this run

One command, self-checking, nothing on the network. The recorded messages are the five synthetic
C2SIM documents the package ships under `fixtures/c2sim/` (SISO-STD-019-2020 v1.0, C2SIMArtifacts
v1.0.1 schema): an initialisation, a MoveToLocation order, a HoldInPlace order, a position report
and a status report — plus, from `fixtures/c2sim/cases/`, the move order with the Route map graphic
it references carried in the order, and two report documents. The exercise-side state the adapter refuses to hold is held HERE, the way the
opt-in client (`exercise_client.py`) holds it against a real server:

* the OWN SIDE — the force side affiliation is read from — is a choice this script makes (BLUE);
* the EXERCISE CLOCK — the scenario epoch a SimulationTime resolves against — is read off the
  initialisation's `ScenarioSetting/DateTime` by this script and handed to the adapter as
  `ExerciseClock(epoch, basis)`; the adapter never carries it from one message to the next;
* the ROSTER — which UUIDs the initialisation declared — is what this script resolves an order's
  performing entity and a report's subject against; the adapter carries them as the UUIDs the
  message stated and says so.

What is checked, against expectations this script states independently of the adapter's output:
the object census of the initialisation and its organisation tree; the affiliations by the stated
hostility relations; the order's task form, its destination and its route; every report's subject
resolving to an initialised unit, the report's identity being distinct from the subject's, and
the observation times — a SimulationTime resolved against the epoch, a message time kept apart;
egress of every message validating structurally on re-ingest to the same objects; and a
deterministic replay — the same recorded messages, in order, twice, and once with the position
reports out of order — producing the canonical serialisation committed under `expected/`, byte
for byte. Normative validation of the emitted documents against the pinned XSD closure is the
test suite's job (`tests/test_cdm_c2sim_adapter.py`, BLOCKED without the resource), not this
script's: this script has no schema and claims none.

The independent-endpoint exchange — the same steps against the OpenC2SIM reference server — is
`exercise_client.py` beside this file, opt-in through `C2SIM_SERVER_URL`. This script is not it
and does not stand in for it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

from synapse_cdm import canonical, times
from synapse_cdm.adapter import packaged_fixtures
from synapse_cdm.adapters import c2sim_codec as codec
from synapse_cdm.adapters.c2sim import C2simAdapter, ExerciseClock
from synapse_cdm.models import Entity, Event, PlanObject

HERE = pathlib.Path(__file__).resolve().parent
EXPECTED = HERE / "expected" / "replay.cdm.json"
MESSAGES = ("initialisation_three_sides.xml", "order_move_to_location.xml", "order_hold_in_place.xml",
            "report_position_two_subjects.xml", "report_status_observations.xml")
ORDER_WITH_ROUTE = "cases/order_with_route.xml"
OUT_OF_ORDER = "cases/reports_out_of_order.xml"
SIMULATION_TIME = "cases/report_position_simulation_time.xml"
BLUE = "c2510000-0001-8000-8000-000000000001"
RED = "c2510000-0001-8000-8000-000000000002"
GREEN = "c2510000-0001-8000-8000-000000000003"
HQ = "c2510000-0002-8000-8000-000000000001"
A_COY = "c2510000-0002-8000-8000-000000000002"
B_COY = "c2510000-0002-8000-8000-000000000003"


def uuid_of(obj) -> str:
    return obj.source_ids[0].external_id


def replay(fixtures: pathlib.Path, names: tuple[str, ...], adapter: C2simAdapter) -> list:
    objects = []
    for name in names:
        objects += adapter.to_cdm((fixtures / name).read_bytes())
    return objects


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--update", action="store_true", help="rewrite expected/ from this run")
    args = parser.parse_args(argv)
    fixtures = packaged_fixtures(C2simAdapter)
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    # -- 1. initialisation: the exercise state this script keeps
    plain = C2simAdapter(clock=times.frozen_clock(), own_side=BLUE)
    initialised = plain.to_cdm((fixtures / MESSAGES[0]).read_bytes())
    entities = [o for o in initialised if isinstance(o, Entity)]
    roster = {uuid_of(o): o for o in initialised}
    blocks = {u: codec.ObjectBlock.model_validate(o.attributes["c2sim"]) for u, o in roster.items()
              if isinstance(o, Entity)}
    check("initialisation: 3 force sides, 5 units, 3 platforms",
          [b.object_class for b in blocks.values()] == ["ForceSide"] * 3 + ["Unit"] * 5
          + ["Aircraft", "Vehicle", "SurfaceVessel"] and len(entities) == 11,
          f"{len(entities)} entities")
    epoch_text = blocks[HQ].scenario.date_time.iso_date_time
    exercise = ExerciseClock(epoch=codec.parse_iso_date_time(epoch_text, "ScenarioSetting"), rate=1.0,
                             basis=f"ScenarioSetting/DateTime of initialisation message {blocks[HQ].message.message_id}")
    check("the exercise epoch is read off ScenarioSetting/DateTime by this script, not by the adapter",
          epoch_text == "2026-09-21T06:00:00Z" and all(b.exercise_clock is None for b in blocks.values()),
          epoch_text)
    tree = {u: (b.organisation.superior, list(b.organisation.subordinates)) for u, b in blocks.items()
            if b.object_class == "Unit"}
    check("organisation tree: HQ has A-COY and B-COY under it, both name HQ as superior, HQ names none",
          tree[HQ] == (None, [A_COY, B_COY]) and tree[A_COY][0] == HQ and tree[B_COY][0] == HQ)
    check("every organisational reference resolves inside the initialisation",
          all(ref in roster for b in blocks.values() if b.organisation
              for ref in ([b.organisation.superior] if b.organisation.superior else [])
              + b.organisation.subordinates + [r.actor for r in b.organisation.command_relations]))
    affiliations = {u: roster[u].affiliation.value for u in (BLUE, RED, GREEN, HQ, A_COY)}
    check("affiliation by BLUE's stated relations: BLUE/HQ/A-COY FRIENDLY, RED HOSTILE, GREEN NEUTRAL",
          affiliations == {BLUE: "FRIENDLY", RED: "HOSTILE", GREEN: "NEUTRAL", HQ: "FRIENDLY", A_COY: "FRIENDLY"},
          json.dumps(affiliations))
    check("nothing is inferred from a SIDC: RED-1's classification is carried, its symbol is None",
          roster["c2510000-0002-8000-8000-000000000004"].symbol is None
          and blocks["c2510000-0002-8000-8000-000000000004"].classifications[0].sidc == "SHGPUCI--------")
    check("HQ's zero speed and zero heading are real values, its MSL height is unconverted",
          roster[HQ].kinematics.speed_mps == 0.0 and roster[HQ].kinematics.course_deg == 0.0
          and roster[HQ].position.alt_m is None and roster[HQ].position.vertical.value == 42.5)

    adapter = C2simAdapter(clock=times.frozen_clock(), own_side=BLUE, exercise=exercise)

    # -- 2. a supported order
    order_objects = adapter.to_cdm((fixtures / MESSAGES[1]).read_bytes())
    order = codec.OrderPayload.model_validate(order_objects[0].payload["c2sim"])
    task = order.tasks[0]
    check("order: one PLAN_INJECT event, the task's MapGraphicID a reference the order does not carry",
          [o.object_kind for o in order_objects] == ["event"] and task.map_graphic_ids == ["c2510000-0006-8000-8000-000000000002"])
    with_route = adapter.to_cdm((fixtures / ORDER_WITH_ROUTE).read_bytes())
    check("the same order with the route carried in it: the event plus a ROUTE PlanObject the task references",
          [o.object_kind for o in with_route] == ["event", "plan_object"]
          and isinstance(with_route[1], PlanObject) and uuid_of(with_route[1]) == task.map_graphic_ids[0]
          and [w.sequence for w in with_route[1].route.waypoints] == [0, 1])
    check("the task form is one of the two pinned forms and names its destination",
          task.action_code in codec.SUPPORTED_TASK_ACTIONS and task.locations[0].latitude == 58.56,
          task.action_code)
    check("the performing entity, the sender and the receiver are initialised units",
          task.performing_entity in roster and order.from_sender in roster and order.to_receiver in roster,
          task.performing_entity)
    check("related_entities are the derived ids of the units the order concerns",
          order_objects[0].related_entities[0] == roster[task.performing_entity].entity_id)
    check("the SimulationTime end resolves against the epoch this script supplied (2 h after 06:00)",
          task.end_time.resolved == "2026-09-21T08:00:00.000Z" and task.start_time.resolved == "2026-09-21T06:30:00.000Z")
    hold = codec.OrderPayload.model_validate(adapter.to_cdm((fixtures / MESSAGES[2]).read_bytes())[0].payload["c2sim"])
    check("the hold order's second task depends on its first, resolved inside the order",
          hold.tasks[1].temporal_relationships[0].action == hold.tasks[0].uuid
          and hold.tasks[1].temporal_relationships[0].resolved_in_order is True)

    # -- 3. reports
    positions = adapter.to_cdm((fixtures / MESSAGES[3]).read_bytes())
    statuses = adapter.to_cdm((fixtures / MESSAGES[4]).read_bytes())
    payloads = [codec.ReportPayload.model_validate(e.payload["c2sim"]) for e in positions]
    check("position reports: two events, two subjects, one reporting entity, all initialised",
          [p.subject_entity in roster for p in payloads] == [True, True]
          and {p.reporting_entity for p in payloads} == {A_COY})
    check("a report's identity is the report's, not the subject's",
          all(e.event_id != roster[p.subject_entity].entity_id for e, p in zip(positions, payloads))
          and positions[0].event_id != positions[1].event_id
          and [uuid_of(e) for e in positions] == [f"{payloads[0].report_id}#0", f"{payloads[0].report_id}#1"])
    check("the subject's identity is the initialised unit's",
          [e.related_entities[0] for e in positions] == [roster[p.subject_entity].entity_id for p in payloads])
    check("message time (SendingTime) and observation time are two values",
          positions[0].source.observed_at != positions[0].observed_at
          and positions[0].observed_at.isoformat() == "2026-09-21T06:40:00+00:00")
    status_payload = codec.ReportPayload.model_validate(statuses[0].payload["c2sim"])
    check("the status report's vocabulary is the source's, verbatim, read against the pinned enumeration",
          status_payload.observations[0].health[0].code == "PartlyOperational"
          and status_payload.observations[0].health[0].in_pinned_enumeration is True)
    check("the task-status content names the move order's task",
          codec.ReportPayload.model_validate(statuses[1].payload["c2sim"]).current_task == task.uuid)
    simulated = adapter.to_cdm((fixtures / SIMULATION_TIME).read_bytes())
    check("a SimulationTime report (40 min) resolves to 06:40 against the epoch, and is refused without one",
          simulated[0].observed_at.isoformat() == "2026-09-21T06:40:00+00:00" and _refused(plain, fixtures / SIMULATION_TIME))

    # -- 4. egress: every message back out, re-ingested to the same objects
    for name in MESSAGES:
        first = adapter.to_cdm((fixtures / name).read_bytes())
        emitted = adapter.from_cdm(first)
        again = adapter.to_cdm(emitted)
        same = canonical.serialise([o.model_dump(mode="json") for o in first]) == \
            canonical.serialise([o.model_dump(mode="json") for o in again])
        check(f"egress of {name} re-ingests to the same objects", same and emitted.startswith(b"<?xml"))

    # -- 5. deterministic replay
    replayed = replay(fixtures, MESSAGES, C2simAdapter(clock=times.frozen_clock(), own_side=BLUE, exercise=exercise))
    twice = replay(fixtures, MESSAGES, C2simAdapter(clock=times.frozen_clock(), own_side=BLUE, exercise=exercise))
    serialised = canonical.serialise([o.model_dump(mode="json") for o in replayed]).encode("utf-8")
    check("replaying the recorded messages twice yields identical canonical output",
          serialised == canonical.serialise([o.model_dump(mode="json") for o in twice]).encode("utf-8"),
          f"{len(replayed)} objects")
    shuffled = adapter.to_cdm((fixtures / OUT_OF_ORDER).read_bytes())
    check("reports replayed out of order keep their own observation times and identities",
          [e.observed_at.strftime("%H:%M") for e in shuffled] == ["06:50", "06:40", "06:45"]
          and len({e.event_id for e in shuffled}) == 3
          and len({e.related_entities[0] for e in shuffled}) == 1)
    check("a repeated report is the same report: same event ids on a second replay",
          [e.event_id for e in adapter.to_cdm((fixtures / OUT_OF_ORDER).read_bytes())] == [e.event_id for e in shuffled])
    check("every object of the replay is an Entity, an Event or a PlanObject with a structured C2SIM residual",
          all(isinstance(o, (Entity, Event, PlanObject)) and o.residual.namespace == "C2SIM" for o in replayed))

    if args.update:
        EXPECTED.parent.mkdir(parents=True, exist_ok=True)
        EXPECTED.write_bytes(serialised)
        check("expected/ rewritten from this run", True, str(EXPECTED.relative_to(HERE.parent.parent)))
    else:
        check("the replay equals expected/replay.cdm.json byte for byte",
              EXPECTED.exists() and EXPECTED.read_bytes() == serialised,
              "run with --update after reviewing a deliberate change")

    failed = [c for c in checks if not c[1]]
    width = max(len(c[0]) for c in checks)
    print("C2SIM recorded messages -> CDM -> C2SIM, offline replay "
          f"({len(MESSAGES)} messages, own side BLUE, epoch {epoch_text})")
    for name, ok, detail in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}".rstrip())
    print(f"\n{len(checks) - len(failed)} of {len(checks)} checks agree")
    print("RESULT: " + ("AGREES with the stated expectations" if not failed
                        else f"{len(failed)} DISAGREEMENT(S)"))
    print("independent_endpoint: NOT EXERCISED here — see exercise_client.py (opt-in, C2SIM_SERVER_URL)")
    return 1 if failed else 0


def _refused(adapter: C2simAdapter, path: pathlib.Path) -> bool:
    try:
        adapter.to_cdm(path.read_bytes())
    except ValueError as e:
        return "SimulationTime" in str(e)
    return False


if __name__ == "__main__":
    sys.exit(main())
