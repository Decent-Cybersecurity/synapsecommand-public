# ASTERIX CAT021 fixtures

**Every one is synthetic.** No recorded ASTERIX traffic, no real ground station, no real
aircraft. Each block is built from field values by `spec/build_fixtures.py`, which is the
reviewable form of what each one says and carries the arithmetic in comments — necessary here
for the reason it was necessary for AIS and ADS-B, and more so: an ASTERIX data block is raw
octets and cannot carry a comment.

## Why the generator, and not the parsed twin, is the source

The ADS-B set builds its frames FROM the `.parsed.json` twins, and that does not work here. A
record's **FSPEC** and its block's **LEN** are both functions of the contents, so a hand-edited
byte file is a mis-parse waiting to happen and a hand-edited twin would not tell you what octets
it implies. So `spec/build_fixtures.py` is the source of truth for both artefacts:

```bash
python spec/build_fixtures.py                 # from THIS directory, wherever it is
python -m synapse_cdm.harness --adapter cat021 --update-golden   # then READ the diff
```

Edit the generator, never the `.cat021` and never the `.parsed.json`.

## Why each fixture ships twice

Each `<name>.cat021` has a `<name>.parsed.json` twin holding exactly what the parser produces
from it. The harness cannot run its **lossless** check on a non-JSON fixture — there is no leaf
structure to harvest from bytes — so a blocks-only set would show a green run with the never-drop
rule never executed. `tests/test_cdm_asterix_cat021_adapter.py` asserts both that the twin is
what the block parses to and that the two produce identical CDM, because hand-maintained they
would drift and each would still pass its own golden check.

## The identifiers

| | Value | How strong the claim is |
|---|---|---|
| **Target address** | `0029xx` | The ADS-B set's block, reused deliberately. The ICAO allocation table's lowest state block begins at `004000`, so everything below it is in no administration's range. **This repository pins no retrieved copy of that table**, so the claim is weaker than the SAC one below — the test asserts the constraint so the assumption is discoverable from a failure |
| **SAC** | `0x29` | **Pinned.** `spec/sac_pin.json` records the retrieved EUROCONTROL allocation tables, which list SAC `0x29` with an explicitly empty country cell in the EUR table and in no other. That is the page *positively showing* an unallocated code — the same strength of claim ITU MID 299 gives the AIS fixtures, and stronger than the address block's. It echoes MID 299 and `0029xx` on purpose |
| **SIC** | `0x29` | **Carries no allocation claim.** A System Identification Code is assigned by the operator *within* a SAC, so no list exists to pin and its safety is inherited entirely from the SAC's |
| **Identifications** | `EXRCS01`, `EXHELO2`, `EXMAST1` | Fictional, marked as exercise traffic, matching the ADS-B set |
| **Mode 3/A** | ordinary codes such as `4271` | 7500, 7600 and 7700 are the hijack, radio-failure and emergency codes and are deliberately absent: an emergency here is declared through I021/200 and REF/STA, which is where CAT021 carries one |
| **Positions** | Gulf of Riga, west of Saaremaa, Ventspils, the Riga apron | Baltic-plausible, and no aircraft's real track |

**`0x29` replaced `0xFE`, and the pin is what caught it.** The first version of this row set
proposed SAC `0xFE` defended by an assertion in the test suite. The pinned copy says `0xFE` is
**Nicaragua** — and `0xFF` is Panama, and `0x00` is LocalAirport, which is the value an
uninitialised field produces. An assertion on an unverified constant fails when someone edits it
and never fails for the reason that matters.

## The three subdirectories, and why none of them is beside the payloads

`harness.run()` replays every **file** in a fixture directory through `to_cdm()`. Subdirectories
are skipped, which is the only reason these can exist at all:

- **`spec/`** — the SAC pin and the generator. Either one sitting beside the blocks would be fed
  to the adapter and fail as an unrecognised payload.
- **`refusals/`** — payloads that are *meant* to raise. The harness measures translation, and a
  refusal is the absence of one, so these are exercised by `tests/` instead.
- **`golden/`** — the CDM output, as for every other adapter.

## The ingest fixtures

| Fixture | What it is there to catch |
|---|---|
| `airborne_position_time_of_applicability` | The ordinary case, and the two things that must not happen on it: a geometric height reaching `alt_m` at LSB 6.25 ft, and the high-resolution position decoding at LSB 180/2³⁰ rather than at the coarse item's LSB |
| `airborne_position_coarse_and_high_resolution` | Both I021/130 **and** I021/131, which the encoding rule says cannot happen. I021/131 must win, both must be parked, and a disagreement beyond one coarse LSB must be recorded rather than averaged away |
| `position_time_of_message_reception_high_precision` | I021/074's `FSI` = 01, a **whole-second correction** to I021/073. An adapter ignoring it lands a full second early — at exactly the moment the ground station took the trouble to say the fix was near a second boundary |
| `reserved_full_second_indication` | `FSI` = 3, reserved. The high-precision value goes to `unresolved_raw` and the plain I021/073 is used — declining to decode and losing the data are different outcomes |
| `midnight_rollover_before` | 23:59:58.500 delivered at 00:00:01.100 the next day → the **previous** day |
| `midnight_rollover_after` | 00:00:00.875 delivered at 23:59:59.700 → the **next** day. The same rule run the other way, which is the direction an adapter that special-cased "subtract a day" gets wrong. 0.875 s is exactly 112 units of 1/128 s, so the assertion reads as a rollover and not as a quantisation |
| `surface_vehicle_with_ref_ground_vector` | **Why the REF is in scope.** I021/160 is the *airborne* ground vector and is absent; the motion is in `REF/SGV`, without which this target has no kinematics at all. Also ATP 2 → `ADSB_NONICAO` |
| `surface_stopped_track_invalid` | Two absences of different kinds in one item. `STP` set is a measurement of **stillness** → 0.0 m/s, not null; `HTS` clear is the source declining → absent course, named in `unavailable_fields`, with the real-looking angle surviving in the parked octets |
| `emergency_unlawful_interference` | I021/200 priority status 5 → `ALERT` at `CRITICAL`, the line drawn at the standard's own emergency declaration |
| `version_three_emergency_in_ref` | **The fixture that justifies the REF decision.** MOPS version 3, I021/200's priority status **zero** because it is superseded, and the real emergency in `REF/STA/PS3` = 7. An adapter that skipped the REF would translate an aircraft in distress as an ordinary track update |
| `quality_indicators_without_mops_version` | I021/090 with all three extensions including `PIC` — a containment bound in nautical miles, the most tempting number in the format — and **no I021/210**, so which quantity the primary subfield holds cannot be established. Nothing may reach `accuracy_m` or `confidence` under either reading |
| `range_check_failed_still_translated` | The row where the specification asks for filtering. The record must be translated **in full** with the flag parked; a fixture producing no objects would mean the adapter had started making suppression decisions |
| `duplicate_address` | ATP 1. `ADSB_NONICAO`, and `attributes.identity_caveat` recording that this entity may conflate two airframes — which one record cannot resolve |
| `obstacle_line` | I021/020 = 24. The one place an emitter category refines the entity type: `FACILITY`, agreeing with `adsb.py`'s category set C line obstacle through a different vocabulary |
| `two_records_one_block` | Four objects from one payload, in block order, with `record_index` and `record_count` on each — and the assertion that they are two **entities** and not one track |
| `icao24_shared_with_adsb` | Address `0029C1`, the **same** airframe as the ADS-B set's Gulf of Riga fixture. Both adapters file it under `ICAO24`, so `ids.derive` gives the same `entity_id` from two wire formats without the two adapters coordinating. This is also the block a test re-assembles octet by octet from values written in the test file |
| `trajectory_intent_two_points` | The repetitive item's stride: fifteen octets per point after a one-octet `REP`. A mis-sized point shifts every field after it and still parses, so the block's total length is what makes the reading falsifiable |
| `mode_five_authenticated` | `REF/MES` with `ID` and `DA` set. The test asserts a **refusal to decide**: affiliation stays `UNKNOWN` and the basis says an attested IFF indication was present and deliberately not read |
| `special_purpose_field_opaque` | SP parked verbatim on ingest, restored verbatim on egress, and never written to for an object that did not arrive with one |
| `spare_bits_nonzero` | §4.3 only *recommends* zeroing spare bits. The byte-exact round trip survives it only because the octets are parked as sent rather than normalised. Also carries I021/295 data ages — gap 13's evidence |

## The refusals

Each raises with the offending octets quoted, and none falls back to the clock.

| Payload | The refusal |
|---|---|
| `time_beyond_one_day` | 100 000 s since midnight. Refused, never taken modulo 86 400 — a modulo would move the contact by hours and leave every other check passing |
| `wrong_category` | CAT 62 decoded against the CAT021 UAP yields a plausible wrong aircraft, not an error |
| `length_disagrees_with_buffer` | Reading to the end of the buffer instead would translate whatever followed the block as if it were part of it |
| `fspec_names_a_not_used_frn` | FRN 43 is Not Used, so it cannot be skipped and guessing a length would desynchronise the record |
| `missing_mandatory_target_address` | ASTERIX carries no checksum at any level, so the four mandatory items are part of what replaces one |
