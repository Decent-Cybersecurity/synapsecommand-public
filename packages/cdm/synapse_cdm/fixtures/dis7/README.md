# DIS 7 fixtures — adapter #21, Entity State PDU subset

These are the harness fixtures for `adapters/dis7.py`. Each `<name>.dis` is one DIS 7 Entity
State PDU and each `<name>.parsed.json` is its envelope twin (`pdu`, `wire_hex`,
`time_context`). All six share one context: session `unnamed`, synthetic, state instant
`2026-04-29T06:15:00.000Z`.

**Every one is synthetic.** They are byte-identical copies of files under `vectors/`, which come
from the handoff bundle identified by `SC DIS7 SPEC 001 v1.0` (a handoff document that is not in
this repository); `spec/dis7_pin.json` pins those files. No file derives from recorded traffic.

| Fixture | Bytes | Exercises |
|---|---|---|
| `equator_eastbound` | 144 | a position on the equator and a world-coordinate velocity due east |
| `north_pole_stationary` | 144 | the pole branch of the projection; zero speed, so no course |
| `unprojectable_with_extensions` | 160 | a zero position vector (position absent) and one opaque 16-byte record |

`golden/` holds the adapter's output over each, written by
`python -m synapse_cdm.harness --adapter dis7 --schemas schemas --update-golden` and held equal
to `vectors/<name>.expected.json` by `tests/test_cdm_dis7_adapter.py`.

## Subdirectories

- `malformed/` — five refusal payloads for the conformance suite's check H; its README names each.
- `vectors/` — the bundle's vectors, verbatim. `contract/` — its schemas and acceptance cases.
- `spec/` — the pin record `dis7_pin.json`, `build_fixtures.py` (it regenerates the three PDUs
  through the pinned open-dis-python checkout, compares them with `vectors/` and writes nothing)
  and the other specification-side files. Nothing in a subdirectory is replayed by the harness.

## Reproducing

```bash
python -m synapse_cdm.harness --adapter dis7 --schemas schemas
python -m synapse_cdm.suite conformance run --adapter dis7 --require A,B,C,D,E,F,G,H,J,K,L,N,O
```
