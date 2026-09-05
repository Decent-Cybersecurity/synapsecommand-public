# synapse-cdm 1.6.0

A minor release, and the whole of it is the `stanag4609` adapter reading more of the document it
was already reading: **eighteen ST 0601.14a items are promoted on the document's own printed worked
examples** where 1.5.0 promoted only what one pinned stream attested, the **time scale is named as
MISB ST 0603.5 names it**, `Position.alt_m` is filled from the two ellipsoid-height items and never
from mean sea level, and `Kinematics.course_deg` is filled at all.

**Package version 1.6.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, no schema
moved: no field was added, removed or retyped, and the diff over `schemas/` since 1.5.0 is empty —
`git diff v1.5.0..HEAD -- schemas/` returns nothing, which is the check that decided
`SCHEMA_VERSION` stays where it is rather than an assumption that it would. Everything new reaches a
consumer either in a field the models already declare (`alt_m`, `course_deg`) or inside
`Entity.attributes`, which the published `entity` schema declares `additionalProperties: true` — the
1.2.0 ruling, applied a third time and checked against the schema files rather than recalled.

**If you ingest STANAG 4609 / MISB KLV, read the next section.** One key you may have been reading
is gone from every object this adapter emits, and two fields that were always `None` now carry
values when a packet supplies them.

For what 1.5.0 was — the ST 0102.12 security metadata local set, read seventeen of seventeen — see
[the 1.5.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.5.0)
and the previous notes in this file's git history. This document does not restate them.

## What changed on the wire for a `stanag4609` consumer

Six things, each stated as what a consumer receives.

**1. `attributes.time_basis` lost its `timescale` key and gained eight.** This is the one change in
this release that can raise an exception in a consumer: code reading
`attributes.time_basis["timescale"]` gets a `KeyError` from 1.6.0 on. The key is not renamed — the
claim it carried is superseded. Its place is taken by `scale`, `relation_to_TAI` and
`relation_to_UTC`, and the record also gains `the_POSIX_rule_is_SUPERSEDED`,
`leap_second_adjustment`, `correction_offset`, `applied_microseconds` and `what_observed_at_IS` —
eight keys, derived by comparing the same golden's `time_basis` at `v1.5.0` (six keys) and here
(thirteen). What `scale` now says: tag 2 is **the MISP Time System**, named as MISB ST 0603.5 names
it, and defined by that document's §6 as an SI-second count from its stated epoch that is strictly
monotonic — no skips, no repeats. Its relation to TAI, in the document's own words: *"The MISP Time
System is locked … with International Atomic Time (TAI); however, there is a fixed offset of
8.0000822 seconds between the MISP Time System and TAI"*. Its relation to UTC: *"UTC can be derived
from the MISP Time System using its correct offset and inclusion of leap seconds"*. The scale is
locked to TAI and is not TAI, and it is not UTC either — ST 0601.14a §8.2.1 says so of the item
itself. The POSIX derivation this adapter cited for nine days is what ST 0603.5's Appendix A
records as the guidance in force before the edition that superseded it; the arithmetic did not move,
because the same appendix says the epochs are the same, so not one emitted instant changed.

**2. `Event.observed_at` and `Entity.valid_from` apply items 136 and 137 when a packet carries them,
and are otherwise unchanged.** ST 0601.14a §6.4 states the arithmetic as two equations —
`TCorrected = TPrecision + TCorrection`, and `+ (LSeconds * 1,000,000)` for UTC — and tag 137
(Correction Offset) and tag 136 (Leap Seconds) are their two terms. Each is applied only when the
packet supplies it; an absent term is recorded in `time_basis` as not available rather than
substituted with a zero, and a Zero-Length Item counts as absent. **The proof that nothing else
moved is the park 3 round's structural diff**, quoted from `MIGRATIONS.md`'s 1.6.0 section: *"All
64 pre-existing goldens were compared against their `HEAD` versions leaf by leaf, keyed by JSON
path: zero undeclared leaves changed, added or removed, and the 2 178 that did change all sit under
`attributes.time_basis`, `payload.time_basis` or `attributes.document_witnessed_basis`.
`attributes.klv_items` and `attributes.document_witnessed_items` moved on no pre-existing golden,
and the 198 `observed_at`, `valid_from` and `precision_time_stamp_us` leaves were compared and are
byte-equal."* The pinned stream carries neither item, so every instant it ever produced is the
instant it produces now.

**3. `Entity.position.alt_m` is filled from tag 104 or tag 75 — both ellipsoid heights — and never
from tag 15, which is mean sea level.** `Position.alt_m` is documented as metres HAE, and the two
HAE items are "measured from the reference WGS84 ellipsoid" in their own Descriptions, so there is
no conversion and no geoid model. Where a packet carries both, 104 is taken, on range (40 000 m
against 19 000 m) and resolution (0.0078125 m at three octets against 0.30365 m) — a preference of
this repository's, labelled as such, because the document orders 75 against 104 nowhere. Where the
two are carried as measurements and differ by more than tag 75's own step, an advisory of class
**`hae_items_disagree`** carries both values, their difference and the step, at
`attributes.position_basis.hae_disagreement` on the Entity and in the Event payload's
`klv_advisories`; the selected value is still emitted. Packets carrying neither item — the pinned
stream's among them — emit `alt_m` as `None`, exactly as before.

**4. `Entity.kinematics.course_deg` is filled from tag 112, Platform Course Angle**, degrees
clockwise from true north over `IMAPB(0, 360, Length)`, which is what the field is documented as, so
it lands with no conversion. A course of exactly 360° — decodable at two octets — is emitted as
`0.0`, because the document states the two as one direction and the field is `[0, 360)`. Tag 5,
Platform Heading Angle, fills nothing: a heading is not a course. Packets without tag 112 emit
`None`, as before.

**5. Fourteen IMAPB items and the Wavelengths List pack ride in `attributes` under the names the
document gives them, each promoted on a document-side witness.** Twelve of the fourteen appear under
`attributes.document_witnessed_items` — `radar_altimeter_m`, `altitude_agl_m`, `zoom_percentage`,
`sensor_azimuth_rate_dps` and their siblings — the other two are items 104 and 112 above, which fill
CDM fields; the pack appears as `wavelengths_list`, its members decoded from §8.128's grammar with
wavelengths in nanometres; and items 136 and 137 appear as `leap_seconds` and `correction_offset`.
**What "promoted on a document-side witness" means**: no held stream carries any of these tags. Each
row was promoted because ST 0601.14a's own §8.x block prints one Software Value beside the KLV octets
that encode it, and `klv_uas_codec.check_against_the_documents_own_examples()` reproduces that
example — in both directions for the IMAPB items — on every suite run, 44 examples in total. The
scope contract's second condition, *"a second pinned stream, OR a document-side check as strong as
a worked example"*, is met by the second clause. Tag 130 is the row that shows it is a condition:
its block prints no example, so it is not promoted and the object's `document_witnessed_basis`
says so under `declined`. **How a reader tells the two kinds apart**: in `FORMAT_COVERAGE.md`'s
ST 0601 tag table, a document-witnessed row's Notes open with *Promoted … on the document-side
witness* and end *No held stream carries this tag*, while a stream-witnessed row reads *Promoted*
and cites the pinned stream; on every object, `attributes.document_witnessed_basis` lists the
eighteen tags read on that footing (`tags_read`, `how_many`), and those items ride under
`document_witnessed_items` rather than under `klv_items`, so the two grounds never share a key.
`klv_uas_codec.WITNESS_KINDS` states the arrangement: 26 stream-witnessed tags, 18 document-witnessed,
and item 48 on a third ground.

**6. Two parks closed, one document pinned, and a roster corrected.** Park 5 closed on ST 1201.3's
row set and park 3 on MISB ST 0603.5, fetched, pinned and read — `gates/parks_table.py` reads
thirteen rows, **eight closed and five open**, and `gates/pin_paths.py` reads **25 pinned copies, 25
matched**. The profile still delegates to fourteen documents and ten are held. `MIGRATIONS.md`'s
list of adapters that landed with no schema change holds **thirteen** entries: `stanag4586` was
missing and is now recorded there, and `pntmap` is correctly absent because it landed with the 1.0.0
schema.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between `v1.5.0`
and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** over **184
signals** across **135 distribution files**, and the floor is **1.6.0** — the release gate's moved set
is 136, the one file apart being `version.py`, whose only changed unit at this commit is the
declaration the gate refuses to read as evidence for itself. The kind needed no ruling:
`adapters/klv_pack_codec.py` is a **new importable module**, `imapb_codec.py`'s `__all__` grew by six
public names, and `fixtures/klv/` gains nineteen payloads that extend a fixture set, all of which sit
on the MINOR list. No importable name is removed and no signature moves, so no MAJOR row is reached.
The one removed *emitted key* — `timescale` — is not a MAJOR-row event, because that row is about
importable names; it is named in section 1 above instead, on the precedent of the 1.4.1 notes naming
a refusal's changed exception class.

**Fifteen units the table could not decide, and a person ruled each one.** The gate's PATCH row and
its MAJOR row both reach a function whose body moved and whose name did not, so it names the unit and
stops rather than guessing. All fifteen rulings are in `MIGRATIONS.md`'s 1.6.0 section, and the gate
reads them back and refuses one that outlives its case. By class, as the gate parses them — **five
MINOR and ten PATCH**:

* **five MINOR rulings, on surfaces that grew.** `imapb_codec.__all__` gained six names and lost
  none; `DecodedPacket` gained a trailing `pack_refusals` field with a default, so every positional
  unpack and every index is unchanged; `decode_packet` keeps its signature and decodes more tags with
  every previously decoded value unchanged — new emitted content, not a corrected value;
  `check_against_the_documents_own_examples` runs 44 examples where it ran 26 with the same return
  shape; and `Stanag4609Adapter` keeps both its signatures, adds one class attribute and removes
  nothing, while emitting the fields and attributes above;
* **ten PATCH rulings, eight of them on two insertions.** `_measured` and `_rendered` are
  module-private with no importer outside the module. The other eight name `<statement 2>` and
  `<statement 3>` of `adapters/klv_uas_codec.py` and `<statement 5>` through `<statement 10>` of
  `adapters/stanag4609.py`, and **none of those statements changed**: imports were inserted above
  them, and the gate names an unnamed top-level statement by its position, so eight imports were
  renamed and read as modified — a property of positional unit naming, and the cost of a scheme that
  cannot be fooled into silence.

**The first attempt at this release stopped before writing a number, and that is worth a
paragraph.** The pending section said the gate derived MINOR "with no human ruling", and the gate
exited `0 failed`, and both were true — of the KIND. The gate's exit code judges the last released
arc and only reports the pending one, so fifteen unruled units sat in its JSON output under
`pending.unruled` while the console read clean. They were ruled in a separate commit before any
version string moved, which is the order the release procedure's condition 5 asks for.

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on
this tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## What else moved

* **The fixture set grew by nineteen payloads and every KLV golden was regenerated.** Nineteen new
  payloads with their parsed twins, and **84 goldens of which 38 are new and 46 regenerated** — the
  KLV fixture set is now 42 payloads. **The 46 regenerated goldens are evidence and not noise**: two
  rounds each rewrote a basis paragraph that rides on every object (`position_basis` and
  `kinematics_basis`, then `time_basis` and `document_witnessed_basis`), and each round measured by
  JSON path that the rewrite moved no value position. `stanag4609`'s fixture verdicts move from
  forty-six to **eighty-four**; the roster's total moves to **496**.
* **Three defects in the governing document are recorded rather than worked around.** Three printed
  `Resolution` cells of ST 0601.14a are wrong — §8.104 and §8.105 by a factor of ten, §8.112 by a
  digit slip — proved from those sections' own example octets and recorded at
  `imapb_codec.PRINTED_RESOLUTION_DISAGREEMENTS`; the codec computes every step from `(a, b, L)` and
  reads no Resolution cell. §8.137 states its format as signed in two drawn cells and unsigned in one
  conversion line; it is read **signed**, and a fixture makes that checkable. §8.130 states its HAE
  member's range twice and differently, which is one of the two reasons tag 130 is not promoted.
* **The shipped documents.** `MIGRATIONS.md`, `FORMAT_COVERAGE.md`, the package `README.md` and
  `fixtures/klv/README.md` carry the arc; `klv_pin.json` gains the ST 0603.5 node and the closure
  entries for parks 3 and 5. **The ST 0601 row set reads 45 of 141 rows promoted** — 26
  stream-witnessed and 19 document-witnessed — and 96 `not yet`. **RE-DERIVED 2026-09-05 BY THE PARK 11 ROUND AND MOVED ONE STEP: 46 of the 141 are promoted and the other 95 read `not yet`** — 26 stream-witnessed and **20** document-witnessed, the twentieth being item 94, the MIIS Core Identifier, admitted on a FOURTH ground: MISB ST 1204.1 defines its Value's whole structure, two held documents state its key identically at CRC 30280, and both print the same worked example. Counted off the Status column, not carried. **CORRECTED 2026-09-05 by the
  housekeeping round, and it was wrong when it shipped rather than having gone stale**: this bullet
  kept the step before this release's own pre-release round, which promoted tag 75 and moved the
  ledger row. The figures above are counted off the 141 rows' Status column. Note that the second
  of the three is the ledger row's count of rows witnessed by a document and not the size of
  `klv_uas_codec.DOCUMENT_WITNESSED_TAGS`, which is 18 and is what the paragraph above cites: item
  48's witness is a second document rather than a printed worked example, so it is inside the one
  count and outside the other. The two statements in this file were the same number by accident
  and are different numbers on purpose.

**No schema, model, harness flag or dependency moved**, no adapter was added or removed, and the
pinned specification documents are gitignored as they have always been — nothing in this release
redistributes a standard.

## Fourteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
The table is the live registry, and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree — a table missing an adapter tells a reader the roster is smaller than it is.
**The roster did not move this arc**, which is derived here rather than carried over: `discover()`
and `roster()` each return fourteen, the same fourteen names in the same two directions, and the
totals below were summed from the harness on this tree.

| Adapter | Direction | Fixture verdicts |
|---|---|---|
| `adsb` | bidirectional | 32 |
| `ais` | bidirectional | 22 |
| `cat021` | bidirectional | 40 |
| `cat023` | bidirectional | 34 |
| `cat034` | bidirectional | 34 |
| `cat048` | bidirectional | 82 |
| `cat062` | bidirectional | 56 |
| `gmti` | bidirectional | 32 |
| `legion` | ingest | 6 |
| `pntmap` | ingest | 4 |
| `stanag4586` | ingest | 24 |
| `stanag4609` | bidirectional | 84 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**496 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas.
The whole of the increase is `stanag4609`'s: thirty-eight more verdicts than 1.5.0 shipped, from the
nineteen new payloads and their parsed twins. `gates/wheel_install.py` reports **992** over the
same roster, which is these 496 run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
1.0.0`.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1, 1.3.0, 1.4.0, 1.4.1 and 1.5.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** together with the
workflow run that produced them.

They are deliberately not committed here, for the reason this file has given since 1.1.0. A digest
is a property of one build rather than of the tree: two builds of one tree have identical payloads
but differ in their generated metadata, so a digest written here before the tag would not be the
digest of the file PyPI serves, and one written after the tag could never be inside the tree the tag
names. **1.3.0 measured that the hard way** — a local build and the published wheel came out at the
same byte count and were different files — so the digests to compare a download against are the
workflow's, never a rebuild's. Everything else in this document is readable off that tree, which is
what condition 4 of the release procedure asks for.

```bash
pip install synapse-cdm==1.6.0
python -m synapse_cdm.harness --list-adapters
```
