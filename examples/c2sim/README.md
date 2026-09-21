# Demonstration 1 — C2SIM: initialisation, an order, reports, deterministic replay

```
python examples/c2sim/run.py            # offline; one command; exit 0 when every check agrees
python examples/c2sim/run.py --update   # rewrite expected/replay.cdm.json after a reviewed change
```

`run.py` replays the five synthetic C2SIM messages the package ships under `fixtures/c2sim/`
(SISO-STD-019-2020 v1.0, C2SIMArtifacts v1.0.1 schema) through `adapters/c2sim.py` and checks
thirty expectations it states itself: the initialisation's census and organisation tree, the
affiliations by the force sides' stated hostility relations (own side BLUE — a choice the script
makes), the MoveToLocation order's task form, destination and route, every report's subject
resolving to an initialised unit with the report's identity kept distinct from the subject's, a
SimulationTime resolved against the scenario epoch the script reads off `ScenarioSetting` and
hands to the adapter as an `ExerciseClock`, message time kept apart from observation time, egress
of every message re-ingesting to the same objects, and a deterministic replay — twice in order and
once with the position reports out of order — whose canonical serialisation is committed under
`expected/replay.cdm.json` and compared byte for byte.

The exercise-side state the adapter refuses to hold (own side, epoch, roster) is held by the
script, the way `exercise_client.py` holds it against a server. Nothing here touches the network,
and the script claims no schema validity: the normative validation of every emitted document
against the pinned XSD closure is `tests/test_cdm_c2sim_adapter.py`'s (BLOCKED, never PASS,
without the resource and the `validate` extra).

## The independent endpoint — `exercise_client.py` (opt-in)

```
export C2SIM_SERVER_URL=http://<host>:8080 ; export C2SIM_SERVER_PASSWORD=<server.c2sim_password>
python examples/c2sim/exercise_client.py --out evidence
```

The client for the pinned OpenC2SIM C2SIM Reference Implementation Server 4.8.3.1, speaking the
protocol its documentation gives (REST `/C2SIMServer/c2sim` and `/C2SIMServer/command`, STOMP 1.2
on `/topic/C2SIM`): it resets the session, submits the packaged initialisation, SHAREs and STARTs,
submits the MoveToLocation order and the two position reports, reads QUERYINIT, replays the
reports and STOPs — and writes an `independent_endpoint` exercise report through
`synapse_cdm.evidence.exercise`, one AGREE/DIFFER verdict per step computed by the runner from the
digests of the projections the client writes beside the report. Without `C2SIM_SERVER_URL` it
runs nothing, prints the reproduction procedure and exits 2 — `BLOCKED_EXTERNAL_EVIDENCE`. No
exercise report exists in this repository; the record (`docs/adapter-expansion-implementation.md`)
says so, with the procedure. A mock, or a second process running this package, is not
independence and is not offered as it.
