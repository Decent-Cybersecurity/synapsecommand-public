# synapse-cdm 1.2.0

One adapter, one codec ruling, and a schema version that deliberately did not move.

**Package version 1.2.0 · CDM `schema_version` 1.0.0.** The two numbers parted at 1.1.0 and this
release widened the gap on purpose — see "The schema version did not move, and that was a ruling"
below, which is the part of these notes worth reading if you consume CDM objects.

For what 1.1.0 was, see [the 1.1.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.1.0)
and the previous notes in this file's git history. This document does not restate them.

## Thirteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`:

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
| **`stanag4609`** | bidirectional | **20** |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**408 fixture verdicts, 0 failed**, against the published schemas. 1.1.0 shipped twelve adapters and
388 verdicts; the new one is the difference.

## The new adapter

- **`stanag4609` — STANAG 4609 / MISP-2019.1, the UAS Datalink Local Set, bidirectional,
  byte-exact.** Adapter **#10**, whose ordinal had been reserved since Phase 1 and is now made good.
  KLV metadata packets in, `Entity` + `Event` per packet out, and back to a payload byte for byte.

  **It covers 26 of ST 0601.14a's 141 items, and the other 115 rows still read `not yet`.** That is
  a scope contract rather than an unfinished edge, and it is the honest headline for this release:
  the 26 are exactly the distinct tags the one real KLV stream this repository holds actually
  carries, and an item nobody here has met on a wire is an item whose decoder could only ever be
  checked against a fixture written from the same reading of the same table. `FORMAT_COVERAGE.md`
  names the blocker on every one of the 115.

  Every one of the 26 maps was checked against the standard's own worked examples — each §8.x block
  prints a Software Value beside the octets that encode it — and against MISB EG 0601.1's
  independently printed examples for the 23 it has. Both checks run on every suite run.

  Three things about it are unlike the twelve before it. It is the **first adapter here with a real
  integrity gate**: ST 0601.14a §8.1 defines a checksum, `ST 0601.14-32` makes it mandatory in every
  packet, and CAT021, CAT048, CAT034, CAT023 and GMTIF each had to record that their format defines
  none. Its `entity_id` is **packet-scoped**, because the witnessed set contains no identifier at all
  — a measurement, not a preference, with the cost recorded as gap 30. And it ships a codec ruling:

- **The length-divergence policy.** The one real stream carries item 22 at **four octets where its
  own standard states a Required Length of 2**, at all six sites. Park 13 adjudicated that as a
  stream defect; what no held document said was what a decoder should then DO, so this release rules
  it: **the item is skipped and a structured defect annotation is recorded** — never the packet
  rejected, never the octets reinterpreted. Rejecting the packet would discard 25 conformant items
  whose checksum validates; reinterpreting them would require choosing between three truncation
  rules no held document states, which agree on this stream and disagree the moment a top octet is
  non-zero. Two of the four class boundaries are drawn by the standard's own wording — a `shall` for
  a Required Length against a "**recommended**" Max Length — and the annotation carries both the
  factual and the normative basis on every object.

## The schema version did not move, and that was a ruling

**If you consume CDM objects, this is the paragraph that matters: nothing changes for you.** A
1.0.0 reader validates a 1.2.0 object from the new adapter unchanged, and there is no migration.

The defect annotation is new output surface, which is exactly the shape that ought to move a schema
version, so the question was put before the version moved and answered from the schema files rather
than from judgement:

* the Entity and Event objects are `"additionalProperties": false` — `schemas/entity.schema.json:29`
  and `schemas/event.schema.json:17` — so a new **top-level** field would have been a schema change;
* `attributes` and `payload` are `"additionalProperties": true` — `schemas/entity.schema.json:248`
  and `schemas/event.schema.json:267` — and every part of the annotation lives inside them;
* neither object gained a top-level key, and all six published schemas regenerate byte-identical
  from the models.

**361 adapter-private keys already live in those two bags across the thirteen adapters' golden
files.** If a new key in a never-drop bag moved `SCHEMA_VERSION`, every adapter this repository has
ever shipped would have moved it. `MIGRATIONS.md`'s 1.2.0 section holds the full evidence.

## Also in this release

- **A scripted-edit safety tool, `gates/scripted_edit.py`, and it exists because of a near-miss.**
  A scripted section rewrite in the previous round anchored on a heading that appears twice in
  `FORMAT_COVERAGE.md`, and `str.index` took the first: **~5 000 lines were deleted in one write**,
  caught only by a `git diff --stat`. `replace_unique` refuses any anchor that does not occur
  exactly once, and `bounded_batch` aborts a batch that deletes more than the caller said it would.
  The incident is reproducible from git and the guard replays it against the real blob.
- Documentation: the ordinal table, the roster tables and the adapter count moved to thirteen; the
  `PUBLICATION.md` sentence describing the tree's roster was stale by one and is corrected.

## Published by CI over OIDC, as 1.1.0 was

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build, and
uploads those same files through PyPI Trusted Publishing. `PUBLICATION.md` ledger entry 6 records
the configuration.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** together with the
workflow run that produced them — entry 5 records 1.0.0's, entry 6 records 1.1.0's and 1.2.0's.

They are deliberately not committed to `RELEASE_NOTES.md` in the repository, and the reason is the
same one it was at 1.1.0. A digest is a property of one build rather than of the tree: two builds of
one tree have identical payloads but differ in their generated metadata, so a digest written here
before the tag would not be the digest of the file PyPI serves, and one written after the tag could
never be inside the tree the tag names. Everything else in this document is readable off that tree,
which is what condition 4 of the release procedure asks for.

```bash
pip install synapse-cdm==1.2.0
python -m synapse_cdm.harness --list-adapters
```
