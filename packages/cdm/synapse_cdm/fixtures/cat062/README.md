# ASTERIX Category 062 / SDPS Track Messages fixtures

**Thirty-seven of them: twenty-eight translatable, nine refusals.** Adapter `cat062` is at Phase 2 —
`adapters/asterix_cat062.py` on the codec in `adapters/cat062_codec.py`, bidirectional, and every
row of the row set in `../../FORMAT_COVERAGE.md` now reads `cat062 1.0.0`. Phase 1 wrote and
reviewed that row set as a specification with no code behind it; this directory is what shipped
against it.

```bash
python -m synapse_cdm.harness --adapter cat062
# 56 passed, 0 failed — twenty-eight payloads, each replayed twice
```

**Fifty-six, not twenty-eight, and the doubling is the point.** Each fixture ships as
`<name>.cat062` for the octets and `<name>.parsed.json` for exactly what the parser produces,
because `lossless.unrepresented()` has no leaf structure to harvest from bytes: a blocks-only set
would show a green run with the never-drop rule never executed. The binary twin gets `SKIP` on the
lossless check and says so; the parsed twin gets the check at full strength.

The nine refusals live in `refusals/` and are **not** replayed by the harness, because the refusal
is the expected output and a harness that translated one would be reporting a pass on a block the
adapter must reject. `../../../../../tests/test_cdm_asterix_cat062_adapter.py` runs them and asserts
the message names what was wrong — and, for the two FSPEC cases, that it names *which* wrong thing:
a spare slot inside Table 1 and an FRN above 35 are different faults with different repairs.

**Three of the nine cannot be produced by the encoder and are assembled from octets.** That is a
check rather than a workaround: `cat062_codec.write_fspec` refuses an FRN Table 1 marks `- Spare -`,
and `_encode_compound` re-reads the presence map it is about to emit and refuses a spare presence
bit. A conforming encoder cannot emit those blocks either, so building them by hand is the only
honest way to have them.

## `cat062` is adapter #13

The first adapter in this repository whose **input is already the output of a fusion process** — an
SDPS system track, correlated from radars, Mode S interrogators, multilateration, ADS-B and ADS-C,
and then correlated with a flight plan. `FORMAT_COVERAGE.md`'s settlement 1 is what that costs: the
per-technology update ages, the per-parameter ages, the amalgamation and coasting flags, the
contributing-sensor lists in the Reserved Expansion Field and the tracker's own estimated standard
deviations are the **upstream system's statements about its own processing**, collected under
`attributes.fusion_provenance` with the SAC/SIC of the system that made them, and acted on nowhere.

The series is tabulated once, in "The adapter ordinals, and the reserved-ordinal rule" near the top
of `../../FORMAT_COVERAGE.md`, and that table is the authority `tests/test_cdm_ordinals.py` checks
every other site against.

## What each fixture is for

The plan is in `../../FORMAT_COVERAGE.md` under "The fixtures", written before any of these existed.
Four of them are worth naming here because they exist to catch a specific way of being wrong:

| Fixture | The mistake it catches |
|---|---|
| `full_mask_track` | all 27 items and both expansion fields, **five FSPEC octets**. A codec that imported `cat048_codec.read_fspec` has a four-octet ceiling and refuses this record at FRN 29 — before it ever reaches the `RE` at FRN 34 |
| `ads_c_age_two_octets` | `I062/290` Subfield #5 is **two** octets where the item's other nine are one, with later subfields present after it. A decoder that read it as one desynchronises the record and every following value is plausible garbage that still satisfies `LEN` |
| `spare_bits_nonzero` | every reachable spare bit set to `1`. §4.5 is normative that a decoder "shall never assume and rely on specific settings of spare or unused bits", and the CAT034 round found that a set with all-zero spares tests nothing: zeroing a spare inside the decoder re-encodes as a zero and passes |
| `adsb_version_3_emergency` | the core item says "General emergency" and the REF says "Aircraft in Distress – Manual Activation", and **the core item is legally correct**: the specification's own back-mapping table collapses both distress values onto general emergency. An adapter that skipped the REF would report the wrong emergency and have no way to know |

## Everything here is synthetic

No recorded ASTERIX traffic and no real SDPS. `SAC = 0x29` is listed with an explicitly empty
country cell in the EUROCONTROL allocation tables pinned at `../cat021/spec/sac_pin.json` and in no
other regional table — the evidence transfers to Part 9 **by citation**, because §5.2.1's NOTE
points at the same published list the CAT021 row does. `SIC` carries no allocation claim. Positions
are in the Gulf of Riga; the Mode S addresses are in the `0xF00000` block, which no ICAO 24-bit
allocation table assigns to any state. The clock is injected.

## Editing these

**Edit `spec/build_fixtures.py`, never the octets and never the twins.** A record's FSPEC, its
block's `LEN` and the Reserved Expansion Field's own length octet are all functions of the contents,
so a hand-edited byte file is a mis-parse waiting to happen in three independent ways. The generator
also runs `check_layouts()`, which asserts every encoder emits exactly the octet count §5.2 states
— including all six compound items' subfields, which is where this category's real exposure is.

`spec/` also holds `cat062_pin.json`, the record of which documents this row set was read from.
**The documents themselves are not in git and never will be**: they are EUROCONTROL's, under their
own terms, and `NOTICE` says so. A pin plus an edition plus a SHA-256 identifies a document without
redistributing it.
