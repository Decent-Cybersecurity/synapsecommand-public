# STANAG 4607 / AEDP-4607 Ed A V1 (GMTIF) fixtures

**Everything here is synthetic.** No recorded GMTI traffic, no real mission, no real platform, no
real detection. Every packet is built from field values by `spec/build_fixtures.py`, which is the
only thing that should ever write to this directory:

```
python packages/cdm/synapse_cdm/fixtures/gmti/spec/build_fixtures.py
python -m synapse_cdm.harness --adapter gmti \
    --fixtures packages/cdm/synapse_cdm/fixtures/gmti
```

## Twins, and why both halves are replayed

Each case ships as a **`.gmti` binary packet and a `.parsed.json`**, and the harness replays both.

That is not redundancy. The `.gmti` half is what a real feed delivers, so it is what the decoder
has to be exercised against — a byte-order or radix-point error lives only there. The
`.parsed.json` half is the decoded form `to_cdm()` also accepts directly, and it is what gives the
harness's never-drop check something to harvest: **a bytes fixture has no leaf structure, so
`lossless` reports SKIP on the `.gmti` half by design and PASS on its twin.**
`test_the_binary_twin_and_the_parsed_twin_produce_identical_cdm` asserts the two halves produce
byte-identical CDM, which is what makes the decoder and the accepted-dict path one behaviour
rather than two.

`roundtrip` reports **SKIP on both halves**, because the harness's round-trip check compares
structures and `from_cdm()` returns binary. The round trip is covered by this adapter's own tests
instead, and it is a stronger claim than the harness could make:
`test_every_fixture_round_trips_byte_for_byte` asserts `encode(to_cdm(bytes)) == bytes` on all
sixteen packets.

## `spec/build_fixtures.py` IS the documentation

A GMTI packet cannot carry a comment, and it cannot be rebuilt from its own twin by hand: `P2`,
every `S2`, every existence mask and every target-report width are functions of the contents. So
the module with the arithmetic in it is the reviewable form of this set — the same position
`fixtures/cat021/spec/build_fixtures.py` occupies for the ASTERIX blocks, and the reason
`pyproject.toml` ships `fixtures/**/*.py` in the wheel.

## One fixture is verified by hand against Annex C

The binaries are produced by `gmtif.encode_packet`, which is the module the adapter decodes with
— so a symmetric error would round-trip perfectly and be invisible. Two things guard against it:

- `tests/test_cdm_gmtif_codec.py` checks every encoding against byte patterns worked out by hand
  from Annex C, including **the two worked examples the standard itself prints** (`BA16`
  `0101100100011100` = 125.31006°, and −34.876099° = `SA16` `1100111001100110`).
- `test_the_hand_verified_fixture_matches_the_annex_c_byte_layout` takes
  **`mission_dwell_hi_res_targets`** and asserts its first 76 bytes — Packet Header, Segment
  Header and Mission Segment — against a hand-written expectation built field by field from
  Tables 3-1, 3-6 and 3-7, with every value's hexadecimal spelled out in the test. If the encoder
  and the decoder ever agree with each other and disagree with the document, that is the test that
  says so.

## Identifiers

**GMTIF carries no UUIDs.** Every identifier on this wire is an alphanumeric string or an integer,
so the RFC 9562 version-8 rule the Legion and NITS fixtures follow has nothing here to apply to —
and `test_no_gmti_fixture_contains_a_uuid` asserts that rather than leaving the convention looking
forgotten. What is used instead:

| Field | Value | The strength of the claim |
|---|---|---|
| `P3` Nationality, `P5` Class. System, `A25`, `C2` | `ZZ` (and `ZY` for a modifying system) | not in Table 3-3's list of national examples and not `XN`. **No allocation list is pinned** — Table 3-3 is explicitly "National Examples" plus "additional codes as registered with the Custodian" — so this is the **weakest** identifier claim in the set, weaker than the CAT021 SAC's, and it says so here |
| `P8` Platform ID | `ZZSYN00001` | a tail number no nation issues, and safe **only because `P3` is non-allocated**: §3.1.8 scopes platform uniqueness to "the set of platforms it owns", so the two claims are coupled |
| `M3` Platform Type | `200` | inside Table 3-8's `57-254` **Available for Future Use** range, so no fixture claims to be an E-8C |
| `J2` / `A4` Sensor ID Type | `200` | inside Table 3-15's `36-254` Available range, so none claims an APY-7 |
| `J14` Radar Mode | `1` | the generic `MTI` mode, which Table 3-16 marks Generic rather than platform-specific |

## `P7` is never a purely-real value here, and that is forced

The harness constructs the adapter with `synthetic=True`, and a `P7` of `0` or `128` — purely real
data — against that declaration is a **conflict refusal by design** (amendment 2). So every
fixture states `1`, `2`, `129` or `130`.

The purely-real cases are exercised in `tests/test_cdm_gmtif_adapter.py`, where the declaration
can be set to match — and that is also the only place the **tagging-device exemption** can be
shown to bite, because it only matters when `P7` says real and a `D32.10` says simulated.

Every **refusal** path is a unit test with an inline packet rather than a fixture, for the reason
the NITS set gives: a fixture whose `to_cdm` raises is a harness FAIL, and a refusal that reads as
a failure is a refusal nobody keeps.

## The sixteen cases, and what each one is there to catch

| Fixture | What it pins |
|---|---|
| `mission_dwell_hi_res_targets` | the base case, and **the hand-verified one**. Three hi-res targets with three different classifications: a wheeled vehicle (`PLATFORM`), a person (`UNKNOWN`, and the CAT021 divergence) and a ground rotator (`UNKNOWN`, which **amendment 1** reversed from `FACILITY`) |
| `sparse_mask_minimum_dwell` | the sparsest conformant Dwell Segment — nine Mandatory fields and a location pair. Half of a matched pair with the next one, because one mask-decode bug shifts every field after it |
| `full_mask_every_optional_group` | every Conditional and Optional group the row set names, satisfied at once. Note that a "full" mask still cannot set every bit: `D32.2`/`D32.3` and `D32.4`/`D32.5` are **exclusive** |
| `multi_day_dwell_time` | **Annex C-3's own worked example**, reproduced exactly: reference date 2026-04-28 and `D6` = 117 935 200 ms, which the standard says is 08:45:35.2 UTC of the *next* day. Exact addition, no modulo, and the number in the row set and the number here are the same number on purpose |
| `delta_targets_across_the_prime_meridian` | reduced-bandwidth reports whose dwell area straddles 0°, including a **negative** delta longitude that underflows past zero. This is the fixture guide §E.7's integer-domain reconstruction exists for: a float-degrees implementation puts that target 360° away, and the golden file says so |
| `platform_location_mixed_time_basis` | a Dwell Segment and two Platform Location Segments in one packet, so the platform `Track` holds **both kinds of instant** and `platform_track_basis.mixed` is true — **amendment 3**'s whole point |
| `synthesized_data_parks_without_refusal` | `P7 = 2`, "a mix of real and simulated data", which contradicts neither pure declaration and parks **without a refusal** — amendment 2's third branch, and the one the Phase 1 reading resolved onto the boolean |
| `simulated_classifications_never_flip_synthetic` | four simulated classifications including **144**, whose `144 − 128 = 16` reading is `Ground Rotator Live`. The golden file is where "a lookup and never arithmetic" stops being prose |
| `tagging_device_beside_simulated_targets` | `142` beside `129` and a reserved `200`, with truth tags parked raw under both readings and interpreted as neither |
| `reserved_and_extension_segments_recorded` | a bare reserved type (`8`, Group Segment) and a **registered** Controlled Extension (`132`, Releasability) between two supported segments. Skipped by `S2`, parked with their bytes, recorded — and the Dwell Segment *after* them must still decode, which is what proves the skip was exact |
| `hrr_signature_parked_both_time_branches` | one HRR Segment whose `H2`/`H3` name the dwell beside it, and one whose name a dwell that is not in the packet — so both branches of the `observed_at` chain run and the second lands in `unresolved_references` |
| `free_text_and_test_status` | the two segments that state **no time of any kind**, so `observed_at` falls to the receipt instant with the basis saying so. `T5` bit 4 is a failed **datalink** and the severity is still `INFO` |
| `processing_history_chain` | a two-record provenance chain — Area Filtering, then Security Filtering — each naming a different modifying system. Carried in full, resolved never |
| `tasking_segments_parked_with_job_id_zero` | a Job Definition, Job Request and Job Acknowledge with **no dwell data**, so `P10 = 0` per §3.1.10 while `J1 = 77`. Under a literal `J1`/`P10` cross-check this packet is unrepresentable, and the guide's own Figure 2-1 shows one — **ambiguity 16**, and this is what pins the narrowing |
| `dwell_with_no_targets_and_target_bits_set` | `D5 = 0` with the target-report mask bits **set**, which §3.4.1 makes conformant. A Free Text Segment follows, so reading one byte too many corrupts a value the golden checks. Also **gap 22**'s fixture: the packet states that the radar looked and found nothing, and the CDM says nothing about it |
| `repeated_mission_segment` | two Mission Segments with the same reference date in one packet, which §3.3 and guide §A.1.3 make ordinary rather than exotic |
