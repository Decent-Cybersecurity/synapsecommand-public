# synapse-cdm 1.3.0

A minor release. It adds one importable module and one fixture set, and moves no wire contract.

**Package version 1.3.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, this release
asks nothing of you: no schema moved, no field was added, removed or retyped, and the diff over
`schemas/` since 1.2.1 is empty. If you decode MISB KLV metadata, the new codec is what this
release is for.

For what 1.2.1 was — no importable surface at all, shipped documents carrying repairs the published
1.2.0 did not have — see [the 1.2.1 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.2.1)
and the previous notes in this file's git history. This document does not restate them.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between
`v1.2.1` and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR**, and it
names the thirteen public top-level names in `synapse_cdm/adapters/imapb_codec.py` as the signals
that make it one — `decode`, `encode`, `decode_item`, `encode_item`, `encode_special`, `forward`,
`reverse`, `length_for_precision`, `IMAPB_ITEMS`, `Constants`, `Special`, `SpecialKind` and
`constants`. The MINOR row covers both halves of what landed: *a public top-level name appears*,
and *a fixture set appears*.

`SCHEMA_VERSION` is unmoved at 1.0.0 and that is not an oversight. Nothing about the wire contract
changed — no field was added to any model, and a consumer reading CDM objects off a queue is
unaffected. What moved is the Python surface, which is what a package MINOR states and all it
states.

**The distribution moved 67 files**: 4 shipped documents, 1 pin record, 2 modules of source and 60
fixture files. The count is the gate's, not a tally — `python gates/bump_derivation.py` prints the
set.

## What is new

- **An IMAPB codec.** `synapse_cdm.adapters.imapb_codec` implements MISB ST 1201.3's Integer
  Mapping (IMAPB) in both directions — `encode`/`decode` over the mapping's parameters, and
  `encode_item`/`decode_item` over the **fourteen** ST 0601 items whose values are IMAPB-mapped:
  tags 96, 103, 104, 105, 109, 112, 113, 114, 117, 118, 119, 120, 132 and 134. The special values
  the standard reserves — ±∞, quiet and signalling NaN with their payloads, the reserved and
  user-defined ranges — are decoded as `Special` rather than collapsed into a float, so a consumer
  can tell "the sensor said unknown" from "the sensor said zero".

- **A fixture set at `fixtures/klv/imapb/`.** Thirty payloads, each with its parsed record, for
  sixty files. They are the standards' own worked examples plus the edge cases the mapping has:
  the fourteen ST 0601.14a item examples, ST 1201.3's example 3 and example 4, the three
  wire-length variants of tag 112, the zero-offset rule in both directions, the
  power-of-two range where a high MSB is an ordinary value rather than a special, and the eight
  special-value encodings.

## What this release does NOT buy

**Park 5 is not closed, and a MINOR that reads as a park closure would be worse than no note.**
The codec is checked against ST 0601.14a's fourteen worked examples and ST 1201.3's two, and
against nothing on a wire. None of the fourteen rows it reaches is witnessed by any held octet —
the pinned transport stream's 26 items stop at tag 65, and the lowest IMAPB item is tag 96. All
fourteen still read `not yet` in `FORMAT_COVERAGE.md`. In particular `Kinematics.course_deg` is
still `None` on every object this package emits from that stream, because tag 112 is not in it.

## Fourteen adapters, all harness-verified — thirteen of them unchanged, and one that
## postdates this release

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
**The table is the roster of the TREE, not of the 1.3.0 artefact**, and the difference is one
row: `stanag4586` landed after 1.3.0 was published and is marked. It is here because
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` reads the live
registry and requires both directions to agree — a table missing an adapter tells a reader the
roster is smaller than it is. Marking the row is how that gate is satisfied without the notes
claiming 1.3.0 shipped something it did not:

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
| `stanag4586` | ingest | 24 — **NOT IN 1.3.0**, landed after publication |
| `stanag4609` | bidirectional | 20 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**408 fixture verdicts, 0 failed** across the thirteen adapters 1.3.0 shipped, against the published
schemas — the same roster and the same 408 that 1.2.1 and 1.2.0 shipped. The new fixture set of that
release is the codec's and is not an adapter's, so it added no verdict; that the table did not move
across those three releases is the measurement, and it is printed rather than asserted.

`stanag4586`'s 24 are NOT in that 408 and must not be added to it: they are verdicts on an adapter
this release does not contain. The tree's total is **432**, and the two figures are kept apart on
purpose — 408 is a fact about the artefact a `pip install synapse-cdm==1.3.0` gets, and 432 is a
fact about `main`.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models.

## Published by CI over OIDC, as 1.1.0, 1.2.0 and 1.2.1 were

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
names. Everything else in this document is readable off that tree, which is what condition 4 of the
release procedure asks for.

```bash
pip install synapse-cdm==1.3.0
python -m synapse_cdm.harness --list-adapters
```
