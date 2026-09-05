# synapse-cdm 1.7.0

A minor release, and what it adds is one thing said three ways: the `stanag4609` adapter now emits
objects **about something other than the platform that sent the packet**. MISB ST 0601 item 74
becomes `DETECTION` events and `Track` objects; item 94 becomes entries in `Entity.source_ids` that
name the sensor and the platform as devices rather than as a packet; and every object carries a
per-packet reading of MISB ST 0902.8's minimum metadata set. Three parks closed for it — 6, 11 and
12 — and the adapter roster did not move.

**Package version 1.7.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, no schema
moved: no field was added, removed or retyped, and the diff over `schemas/` since 1.6.0 is empty —
`git diff v1.6.0..HEAD -- schemas/` returns nothing, which is the check that decided
`SCHEMA_VERSION` stays where it is rather than an assumption that it would. Everything new reaches a
consumer either in a field the models already declare (`source_ids`, and `Track` and `Event`
themselves) or inside `Entity.attributes`, which the published `entity` schema declares
`additionalProperties: true` — the 1.2.0 ruling, applied a fourth time and checked against the
schema files rather than recalled.

**If you ingest STANAG 4609 / MISB KLV, read the next section.** Nothing is removed and no key
changes shape, but a payload that used to yield one `Entity` and one `Event` can now yield several
objects, and code that assumes one packet is one pair will see more than it expects.

For what 1.6.0 was — eighteen ST 0601 items promoted on the document's own printed worked examples,
the time scale named as MISB ST 0603.5 names it, and `alt_m` filled from ellipsoid height — see
[the 1.6.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.6.0)
and the previous notes in this file's git history. This document does not restate them.

## What changed on the wire for a `stanag4609` consumer

Four things, each stated as what a consumer receives.

**1. A packet carrying item 74 now yields a `DETECTION` `Event` per VTarget Pack and a `Track` with
its `Entity` for every VTarget that carries a VTracker Track ID.** This is the first `Event` this
adapter has ever emitted about a third party. The twenty-six items the pinned stream witnesses are a
platform reporting itself, which is why the packet's own event is a `STATUS_CHANGE`; item 74 is the
item that reports something else, and `adapters/klv_vmti_codec.py` reads MISB ST 0903.4's VMTI Local
Set, its VTargetSeries and VTarget Packs, and the five nested Local Sets and four packs under them.
The packet's own `Entity`/`Event` pair is unchanged and still emitted beside the new objects.

**What identifies a track is a ruling and not a reading, and it is stated here because a consumer
keys on it.** The identifier used is **VTracker LS Tag 1**, which ST 0903.4 defines as *"[a] value
that uniquely identifies a track, using a 128-bit (16-byte) Universal Unique Identification (UUID)
as standardized by the Open Software Foundation in ISO/IEC 9834-8"*. The VTarget Pack's **Target ID
Number** is deliberately **not** a key: §11.15 scopes it *"until the identification number is reset
by the New Detection Flag (Tag 6 within the VTarget Pack)"*, §9.4 makes every triplet including that
flag optional so the reset need not be observable at all, and `ST 0903.4-28` requires uniqueness only
*"[t]o the extent possible"*. It is carried as a `source_ids` entry under the system
`VMTI-VTARGET-TARGET-ID-NUMBER`, which is a different id space from `VMTI-VTRACKER-TRACK-ID`, so
nothing can join the two by accident. The whole ruling with its clauses is readable at
`stanag4609.VMTI_IDENTITY_RULING`.

**And the carrier this adapter uses is one the document discourages**, recorded rather than argued
away. §10: *"Use of VTracker is discouraged (although not forbidden). Use of VTrack LS is
recommended, because it maps more directly to NATO STANAG 4676."* The recommended carrier is
unreachable from ST 0601 — §9.1 makes VTrack LS independent of it, and item 74 is an ST 0601 tag — so
the discouraged carrier is the only one in reach.

**2. `Entity.source_ids` gains one entry per Identifier Component of item 94, the MIIS Core
Identifier.** MISB ST 1204.1 defines the whole structure of that item's binary value, and each
component becomes its own `SourceId` under a system naming the component's role and its quality —
`MIIS-SENSOR-PHYSICAL`, `MIIS-PLATFORM-VIRTUAL` and their siblings — with the UUID as the
`external_id`. **The composite was refused by the standard before this repository could propose
it**, ST 1204.1 §8: *"Since the Core ID can change over time, combining the three identifiers into
one UUID is not used as a method for Enterprise UUIDs."* So the three are independent entries, which
is what `SourceId` being a list has been for since 1.0.0 and what `adapters/ais.py` already does with
an MMSI and an IMO number.

**`source_ids[0]` is still the packet key and `entity_id` is still derived from it.** The new
entries APPEND. `UAS-LS-PACKET` over `<stamp>|<index>` is what keeps an `Entity` addressable when
item 94 is absent, which is every packet of the only stream this repository holds.

**3. Every `Entity` now carries `attributes.mismms_conformance`: MISB ST 0902.8's Motion Imagery
Sensor Minimum Metadata Set, read against the packet that produced the object.** It states, per
packet, which of the standard's **33 rows** were reported and which were not — `rows_total`,
`rows_reported`, `rows_not_reported` and a `rows` map — and it is an **advisory and never a
refusal**: a packet short of the set translates exactly as it did in 1.6.0.

**The document is what makes it an advisory.** ST 0902.8 puts its obligation on the STREAM, twice.
`ST 0902.3-04`: *"All metadata items contained in the MISMMS shall be reported no less than once
every thirty (30) seconds under all circumstances."* And Annex A's closing Note: *"It is not
mandatory that each metadata packet contain every metadata item; Annex B demonstrates the viability
of transmitting the MISMMS in a bandwidth-constrained environment."* One packet cannot answer the
question the document asks, and a consumer aggregating these readings across thirty seconds of
packets is the party who can. The annotation says so on its own face, at
`klv_mismms.PER_PACKET_IS_NOT_A_VERDICT`.

**Four member states, and two of them exist because collapsing them would be a claim about somebody
else's stream.** `absent` says the packet's octets carry no such tag — a statement about the wire,
readable for all **39 tag numbers** the set names. `present_not_decoded` says the tag IS on the wire
and this repository has no block for it — a statement about this software, true of five of the set's
tags (3, 10, 78, 90 and 91) and DERIVED at import from the codec's own tables, so wiring one of them
retires it with no edit here. `zero_length` is the third, on `ST 0902.8-05` — *"No Zero-Length items
(ZLI) shall be used to meet minimum reporting requirements"* — so a zero-length item is read as
ST 0601's explicit unknown and is not counted as reported. `present` is the fourth.

**4. Nothing was removed, and the objects the pinned stream produces did not change in any value it
already had.** The one stream this repository holds carries neither item 74 nor item 94, so it emits
no detections, no tracks and no MIIS entries; what it gained is the conformance annotation, which
reads identically on all six of its packets — **21 of the 33 rows reported and 12 not**, the twelve
being Mission ID, Platform Designation, the Core Identifier itself and the whole nine-row security
group. The ninety-six goldens that pre-dated the item 74 work are byte-identical across it, measured
by JSON path; the eighty-four that pre-dated the ST 0902.8 work changed at exactly one added path,
`attributes.mismms_conformance`, and nowhere else.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between `v1.6.0`
and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** over
**312 signals** across **151 distribution files**, and the floor is **1.7.0** — the
release gate's moved set is 152, the one file apart being `version.py`, whose only changed unit at
this commit is the declaration the gate refuses to read as evidence for itself. The kind needed no
argument: `adapters/klv_vmti_codec.py` and `adapters/klv_miis_codec.py` and `adapters/klv_mismms.py`
are three **new importable modules**, and `fixtures/klv/` gains fourteen payloads that extend a
fixture set, all of which sit on the MINOR list. No importable name is removed and no signature
moves, so no MAJOR row is reached, and no emitted key was removed either — which is the one thing
1.6.0 had to say and this release does not.

**Twelve units the table could not decide carry a person's ruling, and not one of them is this
release round's.** The gate's PATCH row and its MAJOR row both reach a function whose body moved and
whose name did not, so it names the unit and stops rather than guessing. Every ruling in this arc was
written by the round that made the unit: the park 11 round ruled one and left ten it named, and the
park 6 round's second part made an eleventh and ruled all eleven. Each is in `MIGRATIONS.md`'s 1.7.0
section in the form the gate parses, with the check that was taken recorded beside it — **eight of
the twelve are PATCH and four MINOR**, and all eight PATCH units are top-level statements the gate
names by POSITION — six of them import lines renumbered by an inserted import, two of them
module-level statements modified in place with no name added or removed. That is a property of
positional unit naming rather than a change to anything a caller can see. `pending.unruled` is the
empty list at this commit, which is the pre-step the release procedure's condition 5 requires before
a version number is typed.

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on this
tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## What else moved

* **Three documents were obtained and pinned, and three parks closed on them.** MISB ST 0903.4
  (park 6), MISB ST 0902.8 (park 12) and the artefact half of park 11's already-held ST 1204.1 and
  ST 1301.2. `gates/parks_table.py` reads **thirteen rows, eleven closed and two open** — parks 7
  and 10, both public downloads — and `gates/pin_paths.py` reads **27 pinned copies, 27 present, 27
  matched, 0 failed**. The profile still delegates to fourteen documents and **twelve are held**.
  The pinned documents themselves are gitignored, as they have always been: nothing in this release
  redistributes a standard.
* **The KLV fixture set grew by fourteen payloads and their fourteen parsed twins, and the golden
  set by twenty-eight**, to 56 payloads and 112 goldens. `stanag4609`'s fixture verdicts move from
  eighty-four to **112**, and the roster's total from 496 to **524**.
* **Two document defects are recorded rather than worked around.** ST 0902.8's Annex C prints its
  "Dynamic Only" example packet twice — as a per-item table and as seven lines of complete-packet
  hex — and the two disagree in exactly one value; the document adjudicates its own disagreement,
  because the checksum SS 6.6 prints over the packet matches the complete-packet form and not the
  table row. And ST 1204.1's Appendix B ends its check-value definition with *"Please see the
  reference code for complete details of the algorithm"* in a document that carries no such code;
  the loop's first index is the one thing its prose does not fix, so both candidates are computed on
  every suite run and the one that reproduces the document's own printed check byte is the one used.
* **The shipped documents.** `MIGRATIONS.md`, `FORMAT_COVERAGE.md`, the package `README.md` and
  `fixtures/klv/README.md` carry the arc; `klv_pin.json` gains the ST 0903.4 and ST 0902.8 nodes and
  the closure entries for parks 6, 11 and 12.

**No schema, model, harness flag or dependency moved**, and no adapter was added or removed.

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
| `stanag4609` | bidirectional | 112 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**524 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas.
The whole of the increase is `stanag4609`'s: twenty-eight more verdicts than 1.6.0 shipped, from the
fourteen new payloads and their parsed twins. `gates/wheel_install.py` reports **1048** over the
same roster, which is these 524 run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
1.0.0`.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1, 1.3.0, 1.4.0, 1.4.1, 1.5.0 and 1.6.0 were

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
pip install synapse-cdm==1.7.0
python -m synapse_cdm.harness --list-adapters
```
