# synapse-cdm 1.2.1

A patch release. Nothing you import changed; the documents shipped inside the distribution did.

**Package version 1.2.1 · CDM `schema_version` 1.0.0.** If you consume CDM objects, this release
asks nothing of you: no schema moved, no field was added, removed or retyped, and the diff over
`schemas/` since 1.2.0 is empty. If you write an adapter against the shipped protocol documents,
they are what this release is for.

For what 1.2.0 was — one new adapter, a codec ruling, and the schema version that deliberately did
not move — see [the 1.2.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.2.0)
and the previous notes in this file's git history. This document does not restate them.

## Why this is a PATCH, and it was nearly numbered wrong

The round behind this release is about 2 800 lines, and almost none of it is in the distribution.
Every file that changed under `packages/` is a comment or a shipped document: `pyproject.toml` and
`adapter.py` changed comment lines only — filtering both diffs to functional lines yields nothing —
and the rest are `MIGRATIONS.md`, `FORMAT_COVERAGE.md`, the two READMEs and one pin record.

No importable name, no `Adapter` contract change, no harness flag or exit code, no fixture set and
no dependency moved. That is `version.py`'s MINOR list in full, and none of it occurred; its PATCH
row — "a translation fix, a message, a docstring. No surface change" — is this release read
literally. The large work is in `gates/`, `tests/` and `PUBLICATION.md`, none of which a wheel
carries.

**This release was drafted as 1.3.0 and renumbered before anything was tagged**, on the diff rather
than on the size of the round. A release number states what a consumer receives.

## Thirteen adapters, all harness-verified, all unchanged

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
| `stanag4609` | bidirectional | 20 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**408 fixture verdicts, 0 failed**, against the published schemas — the same roster and the same
408 that 1.2.0 shipped. No fixture changed, so an identical table is the correct table, and it is
printed because a release that claims nothing moved should show the measurement rather than assert
it.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models.

## What actually reaches you

- **The shipped protocol documents carry repairs that the published 1.2.0 does not.** An adapter
  count disagreed with itself across the tree, and four of the sentences involved were inside the
  1.2.0 artefacts on the index — prose in comments and in a packaged document, which is why 1.2.0
  was not withdrawn and is not yanked now. `PUBLICATION.md`'s ledger records which four, with the
  digests of the artefacts carrying them. **This release is where the repaired text reaches a
  consumer.**

  The repair worth naming for anyone writing an adapter is in `adapter.py`'s `fixture_dir` note. It
  said `stanag4676` was "the only one" whose fixture directory differs from its adapter name.
  `stanag4609` had shipped in 1.2.0 with `fixture_dir = "klv"`, which made that false while the
  count in the same sentence stayed right — a claim of *uniqueness* has no number in it. Both
  halves are derived from the registry now.

- **`FORMAT_COVERAGE.md` gained a round of standards reading and one restoration.** Three entries
  in the KLV register narrowed, two of them against conclusions the document had already recorded,
  and every byte of that came from documents already held rather than from anything newly fetched.
  A register entry that had been truncated mid-clause is restored from the pin record that held the
  complete sentence.

  **No coverage gap closed and no tag row moved.** All 115 `not yet` rows still read `not yet`. The
  findings are about the standard's history, not about what an octet means, and the document says so
  in each entry rather than leaving a reader to infer scope from a narrowed blocker.

- **Nothing else.** No adapter, model, fixture or schema changed. `--list-adapters`, the harness
  exit codes and the `Adapter` contract are what 1.2.0 shipped.

## Published by CI over OIDC, as 1.1.0 and 1.2.0 were

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
pip install synapse-cdm==1.2.1
python -m synapse_cdm.harness --list-adapters
```
