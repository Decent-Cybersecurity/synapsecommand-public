# readsb trace fixtures

**Every one is synthetic.** No trace from adsb.lol, ADS-B Exchange or any other aggregator — not a
file, not a point — is in this repository, and no address of a live aircraft is either. Every
file here is written by `spec/build_fixtures.py` from a literal document in that script; edit the
script and run it, never a `.trace` or a twin. `python -I -B spec/build_fixtures.py --check`
rebuilds the set in memory and prints `CURRENT` when the tree matches it.

These are the fixtures of `readsb_trace` (#24 in the ordinal table, `adapters/readsb_trace.py`):
one readsb `globe_history` trace file per payload. The format is documented only by readsb's
`README-json.md`, section "trace jsons", pinned by URL and SHA-256 in `spec/readsb_trace_pin.json`
and not carried here.

## Why each fixture ships twice

`<name>.trace` is the file as readsb writes it: compact JSON inside one gzip member (readsb keeps a
`.json` name on gzip bytes; a `.json` fixture would be parsed by the harness before the adapter saw
it, so the payload here is named for what it is). `<name>.parsed.json` is the same document,
indented, which is what the harness's lossless ledger reads: a gzip payload has no leaf structure
to harvest. `tests/test_cdm_readsb_trace_adapter.py` holds each twin to its payload and the two
goldens of each pair to each other.

## The identifiers and places

Addresses are in **`0029xx`**, lower case as readsb writes them, for the reason
`fixtures/adsb/README.md` gives: the ICAO allocation table's lowest state block begins at
`004000`. `0029c1` is the adsb fixtures' own airborne address, so one test derives the same
`entity_id` from a frame and from a trace. `~0029b2` is the non-ICAO form. Callsigns begin `EX`.
Every position lies inside the Baltic rectangle of `CONTRIBUTING.md` (56.0–58.5 N, 20.0–24.5 E).
No file states `r`, `t`, `desc`, `ownOp` or `year`: every registration mark belongs to a state's
nationality prefix, so a "fictional" one is a claim about a real allocation, and the set ships
readsb's database-less form (`noRegData`) instead. The version string names commit `0000000`.
The days are 2026-03-14 and 2026-03-15 (UTC midnights 1773446400 and 1773532800).

## The set

| Fixture | What it exercises |
|---|---|
| `airborne_adsb_2022_form` | fourteen-element points, barometric altitude in feet, an aircraft object on the first and last points (`rc` 186 m), ADS-B sources; the address `0029c1` |
| `ground_heading_slot` | element 3 is `ground`, so element 5 is a true heading and never a course; an `adsb_icao_nt` source |
| `mlat_positions` | element 9 `mlat`: the position is ESTIMATED; a stale flag |
| `tisb_positions` | element 9 `tisb_icao` and `tisb_trackfile`: ESTIMATED |
| `every_flag_bit` | flags 0, 1, 2, 4, 8 and 15: stale, new leg, geometric vertical rate and geometric altitude, each decoded beside the raw value; a geometric altitude reaches `alt_m` in metres |
| `nonicao_address` | `~0029b2`: the id system is `ADSB_NONICAO`; an `adsb_other` source |
| `pre2022_nine_elements` | nine-element points and no `version` key: no source is stated, so ESTIMATED |
| `receiver_id_fifteen_elements` | a fifteenth element (a receiver id), parked whole |
| `null_altitude_and_speed` | nulls stay nulls; element 3 null with element 10 stated takes the geometric altitude; the last point states no motion, so no kinematics |
| `midnight_fragment_day_one` | a flight's last minute of 2026-03-14, ending at 23:59:58.750 |
| `midnight_fragment_day_two` | the same flight's first half-minute of 2026-03-15: a second Track, the same Entity id, nothing stitched |
| `reference_not_midnight` | a live trace's reference (`timestamp` 1773486000.512) is not a midnight; the adapter adds element 0 and assumes nothing |
| `equal_instants_and_db_flags` | two points at one instant (allowed) and `dbFlags` 9 with no database string |

`malformed/` holds the payloads the adapter must refuse; its own README names the refusal each
one expects. `golden/` is written by the harness and read.
