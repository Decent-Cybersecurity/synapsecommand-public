# ASTERIX CAT048 fixtures

**Forty-one translatable blocks and eleven refusals.** Adapter #11 shipped in Phase 2, and the
row set in `../../FORMAT_COVERAGE.md` now claims `cat048 1.0.0` on every row that was `not yet`
through Phase 1.

```bash
python spec/build_fixtures.py                 # from THIS directory, wherever it is
python -m synapse_cdm.harness --adapter cat048 --update-golden   # then READ the diff
```

Edit `spec/build_fixtures.py`, never the `.cat048` octets and never the `.parsed.json` twins.

What is here:

- **`spec/cat048_pin.json`** — the pinned identity of EUROCONTROL-SPEC-0149-4 Edition 1.32 and
  every value extracted from it that a ruling cites, each with its locus. Written first for the
  reason the Legion and CAT021 pins were: a quotation with no pin behind it is a recollection.
- **`spec/build_fixtures.py`** — the source of truth for both artefacts, plus `check_layouts()`,
  which asserts every encoder emits the octet count §5.2 states for its item.
- **`spec/history/`** — **22 CAT048 edition PDFs, editions 1.10 to 1.32, and NOT pins.** The
  governing text is Edition 1.32 alone and no row is read against any other edition; the lineage
  is here so that a claim about *when* something was introduced can be checked against the
  standard's own change records instead of recalled. Edition **1.26** is the one edition of the
  lineage not obtained. Untracked, like every PDF here. The placement is ruled in
  `../../FORMAT_COVERAGE.md` under "The edition history", and
  `tests/test_cdm_pins.py` asserts in both directions that nothing in here is a pin — which
  matters, because the harness's own message says pinned standards live in `spec/`.
- **this file** — the identifier evidence, below.

**The specification PDF is not committed.** It sits in `spec/` in the working tree because it
had to be read, and it is excluded from the commit by naming paths explicitly. That matches
every other adapter here: `git ls-files | grep -ci pdf` is `0` across the whole repository,
`fixtures/cat021/spec/` holds a pin and a generator and no document, and `fixtures/gmti/spec/`
holds a generator while three hashed documents are cited in prose. No `.gitignore` was added —
there is none anywhere in this repository, and inventing one to solve a one-file problem would
be a new convention adopted in passing.

## Everything is synthetic

No recorded ASTERIX traffic, no real radar station, no real aircraft. As for CAT021, each block
is built from field values by `spec/build_fixtures.py` rather than hand-edited, because a
record's **FSPEC** and its block's **LEN** are both functions of the contents: a hand-edited
byte file is a mis-parse waiting to happen, and a hand-edited twin does not tell you what octets
it implies. Each `<name>.cat048` ships with a `<name>.parsed.json` twin, for the reason the
CAT021 and ADS-B sets ship twins — `lossless.unrepresented()` has no leaf structure to harvest
from bytes, so a blocks-only set shows a green run with the never-drop rule never executed.

**The twins are what make the never-drop claim real here.** The harness reports
`lossless: PASS` on all forty-one of them and `SKIP` on the forty-one binaries, so the rule runs
at full strength with nothing excused — `AsterixCat048Adapter.TRANSFORMS` is empty, and that is a
claim rather than an oversight.

## Geometry: two branches, and the fixtures cover both

`Entity.position` exists only when the caller injects a `sensor_position` at construction. The
tests inject `(57.05, 23.60, 12.0)` — the Gulf of Riga, matching the other sets, at a plausible
radar-head elevation in metres above **mean sea level**, so that `alt_m - I048/110` is a height
difference between two MSL figures. Five fixtures exist for the branches:

| Fixture | Branch |
|---|---|
| `derived_position_inverts_to_the_polar_values` | site + I048/110 → a `Position`, and the inversion audit runs on it |
| `injected_site_no_height_item` | site, no height → **no** `Position`, the record still translated |
| `injected_site_pressure_height_only` | site + I048/090 → a `Position` with the pressure-altitude approximation named |
| `injected_site_range_at_maximum` | `ERR` set with RHO all-ones → **no** `Position`, because a floor is not a measurement |
| `mode_s_roll_call_track` | replayed twice, with and without a site, so one fixture proves both outcomes from identical octets |

**No fixture is anywhere on the earth without a site.** RHO and THETA are measured from a station
whose position the format never carries, so the blocks make no geographic claim at all.

## The identifiers

| | Value | How strong the claim is |
|---|---|---|
| **SAC** (I048/010) | `0x25` | **Pinned, and the pinned document itself supplies the pointer.** §5.2.1's own NOTE reads "The up-to-date list of SACs is published on the EUROCONTROL Web Site (http://www.eurocontrol.int/asterix)" — the same URL `../cat021/spec/sac_pin.json` pinned on 2026-08-23. So the evidence transfers by CAT048's own citation rather than by analogy. That pinned copy lists `0x25` **with an explicitly empty country cell** in the EUR table and in no other table at all. That is the page *positively showing* an unallocated code: the same grade of claim ITU MID 299 gives the AIS fixtures, and stronger than the ADS-B address block's |
| **SIC** (I048/010) | `0x25`, and `0x26` for the second-station fixture | **Carries no allocation claim.** A System Identification Code is assigned by the operator *within* a SAC rather than centrally, so no list exists to pin and its safety is inherited entirely from the SAC's. Stated so that the pin is not read as evidence about both halves of the pair — the same sentence `sac_pin.json` writes about CAT021's SIC |
| **Aircraft address** (I048/220) | `0029xx` | The ADS-B and CAT021 block, reused deliberately. The ICAO allocation table's lowest state block begins at `004000`, so everything below it is in no administration's range. **This repository still pins no retrieved copy of that table**, so the claim stays weaker than the SAC one, and a test asserts the constraint so the assumption is discoverable from a failure. Reused on purpose: one fixture exists to show a CAT048 report and a CAT021 report sharing an address and **deliberately not being joined** |
| **Aircraft identification** (I048/240) | `EXRDR01`, `EXHELO2` | Fictional and marked as exercise traffic, matching the ADS-B and CAT021 sets character for character |
| **Mode 3/A** (I048/070) | ordinary codes such as `4271` | 7500, 7600 and 7700 are the hijack, radio-failure and emergency codes and are deliberately absent. An emergency in this set is declared where CAT048 actually declares one — I048/020 first extension `ME` |
| **Mode 1 / Mode 2** (I048/055, I048/050) | `13`, `0037` | Military interrogation codes with no central allocation list to pin and no claim made about them. They exist in the set because Mode 1 and Mode 2 are the two items whose `L` bit means "smoothed by a local tracker", which is a different meaning from I048/070's `L` |
| **Track number** (I048/161) | `0x0C7`, i.e. 199 | Twelve bits, station-scoped and recycled. No allocation question exists; the fixture value is arbitrary and the *recycling* is what a fixture has to exercise |
| **RHO / THETA** (I048/040) | ranges under 256 NM, plus one at the maximum | No geographic claim is made or possible: these are slant range and azimuth from a station whose position the format never states. Nothing in this set is anywhere on the earth, because a CAT048 record does not say where it is |
| **UUIDs** | the `f1c7…-8…` version-8 convention where one is needed | CAT048's wire form contains **no UUIDs at all** — its identifiers are a 24-bit address, a SAC/SIC pair and a 12-bit track number. The UUIDs in the golden files are `entity_id`, `event_id` and `track_id`, which are **derived** uuid5 values and therefore not free to choose. The convention binds nothing in this set, and that is stated rather than left looking like an omission |

### Why `0x25` and not CAT021's `0x29`

Both are listed-but-blank, so the *evidence* is identical and the choice is not about safety.
It is about a sentence in the pinned document: §4.5.4 reads **"By convention a dedicated and
unambiguous SAC/SIC code shall be assigned to every Radar System."** An ADS-B ground station and
a monoradar are not one Radar System, so reusing the CAT021 station's code would put two
different kinds of sensor behind one address in direct contradiction of the specification's own
addressing rule — and it would make the no-fusion fixture unreadable, because a CAT048 report
and a CAT021 report sharing both a SAC/SIC *and* an aircraft address look like one system
reporting twice rather than like two sensors that must not be joined.

`0x25` sits in the same blank run as `0x29` in the EUR table, so the two sets stay recognisably
one family, which is the property `sac_pin.json` chose `0x29` for in the first place.

**The relationship to `sac_pin.json`, stated once so it is not mistaken for a second pin.** This
directory pins no allocation list of its own and does not need to: a System Area Code is
category-independent, `../cat021/spec/sac_pin.json` already holds the retrieved copy of the
EUROCONTROL tables, and CAT048 §5.2.1's own NOTE points at the very page that copy was taken from.
So CAT048 **reuses cat021's evidence and picks a different value from it** — the pin is shared, the
choice is not. If that copy is ever re-retrieved and `0x25` has acquired a country cell, this
fixture set is wrong and `test_the_fixture_sac_is_unallocated_in_the_pinned_copy`'s CAT048
counterpart is what will say so.

### The values rejected, and why each

Recorded because the CAT021 set learned this the expensive way: **an assertion on an unverified
constant looks like evidence, fails loudly when someone edits it, and never fails for the reason
that matters — the constant being wrong to begin with.** `0xFE` was defended by a test until the
list was pinned and turned out to be Nicaragua.

| Candidate | The pinned copy says | Verdict |
|---|---|---|
| `0x48` | **Estonia** in the EUR table and **Micronesia** in the APAC table | **Rejected, and it is the trap this format invites**: `0x48` is the obvious mnemonic for Category 048 and it is allocated twice over. Exactly the shape of the `0xFE` mistake, caught by the pin instead of by a reviewer |
| `0x2A` | **absent from every one of the six regional tables** | Rejected. `sac_pin.json` separates two grades of negative evidence on purpose: a code *listed with a blank cell* is the page stating there is no allocation, while a code *absent altogether* may be unallocated or may simply be untabulated. No fixture value rests on the weaker grade |
| `0x29` | listed with an empty country cell in EUR, in no other table | Unallocated, and **rejected anyway** — it is the CAT021 ground station's code, and §4.5.4 says a Radar System gets its own. See above |
| `0xFE` | **Nicaragua** — South America & Caribbean table | Rejected. The value CAT021's Phase 1 proposed on no evidence |
| `0x00` | **LocalAirport** — EUR *and* South America & Caribbean | Rejected, and the most dangerous of these: it is the value an uninitialised field produces |
| `0xFF` | **Panama** | Rejected — the other obvious placeholder, also allocated |

`0x25`'s own evidence, restated as the pin holds it: one occurrence across all six regional
tables, in `EUR`, with an empty country cell. Twenty-six codes in that copy are listed-with-blank
somewhere; twenty of them are blank-or-absent in every table they appear in, and `0x25` is one.

## The three subdirectories, and why none of them sits beside the payloads

`harness.run()` replays every **file** in a fixture directory through `to_cdm()` — subdirectories
are skipped, and `README.md` is skipped by name. That is the only reason these can exist:

- **`spec/`** — the pin and (in Phase 2) the generator. Either one sitting beside the blocks
  would be fed to the adapter and fail as an unrecognised payload. The uncommitted specification
  PDF lives here for the same reason.
- **`refusals/`** — payloads that are *meant* to raise. The harness measures translation and a
  refusal is the absence of one, so these are exercised from `tests/` instead.
- **`golden/`** — the CDM output, as for every other adapter.

## The worked arithmetic

The arithmetic that matters most in this format is the part with no analogue in CAT021. Every
figure below is asserted by `tests/test_cdm_asterix_cat048_adapter.py` against the value §5.2
prints, so a drift shows as a failure rather than as a stale table:

| Quantity | Arithmetic | Why it is written out |
|---|---|---|
| `RHO` | raw × 1/256 NM, max `256 − 1/256` NM | The maximum is a **floor and not a range** when I048/020's `ERR` bit is set, per §5.2.4 NOTE 4 |
| `THETA` | raw × 360/2¹⁶ ≈ 0.0055° | Exact in binary; a decimal-degree fixture value would not round-trip |
| `I048/090` | raw × ¼ FL, two's complement over 14 bits | The "in two's complement form" wording is Edition 1.32's own clarification, so a fixture with a negative flight level is the one that proves the edition was read |
| `I048/110` | raw × 25 ft, two's complement over 14 bits, **mean sea level** zero reference | A different datum from I048/090 and from `Position.alt_m`. The fixture carries both items so the difference is visible rather than argued |
| `I048/200` groundspeed | raw × 2⁻¹⁴ NM/s × 1852 m = raw × 0.113 037 109 375 m/s | Exact in float64: 1852 needs 11 significand bits and the scale is dyadic |
| `I048/140` | raw × 1/128 s since last midnight | 1/128 s is not a whole number of milliseconds, so the raw integer is what egress re-emits |
