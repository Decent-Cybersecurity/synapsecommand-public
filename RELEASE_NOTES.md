# synapse-cdm 1.4.0

A minor release. It adds one adapter with its codec and one fixture set, and moves no wire contract.

**Package version 1.4.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, this release
asks nothing of you: no schema moved, no field was added, removed or retyped, and the diff over
`schemas/` since 1.3.0 is empty — `git diff v1.3.0..HEAD -- schemas/` returns nothing, which is the
check that decided `SCHEMA_VERSION` stays where it is rather than an assumption that it would.
If you ingest STANAG 4586 vehicle telemetry, the new adapter is what this release is for.

For what 1.3.0 was — the IMAPB codec, no adapter — see
[the 1.3.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.3.0)
and the previous notes in this file's git history. This document does not restate them.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between
`v1.3.0` and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** over
**46 signals**, on the row that covers a public top-level name appearing: **41** names in
`synapse_cdm/adapters/stanag4586_codec.py`, **4** in `synapse_cdm/adapters/stanag4586.py`, and the
`synapse_cdm/fixtures/stanag4586` fixture set. Nothing was removed and nothing was retyped, so no
MAJOR row is reached, and a new importable module is more than the PATCH row's "a translation fix,
a message, a docstring".

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on
this tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## STANAG 4586 telemetry ingest — and the edition it is built on is not the current one

`stanag4586` is **adapter #15 by ordinal and the fourteenth shipped** — those are two different
derivations over two different sources and they are not the same number. The ordinal table assigns
numbers to specifications as well as adapters, and `#9` is `stanag5527`, a Phase 1 row set with no
adapter, so the roster of fourteen occupies fifteen ordinals.

**The pinned document is Edition 3, and Edition 4 is current.** Edition 4 (2017-04-05, promulgated
as AEP-84 Edition A) could not be obtained: the NATO Standardization Office answers HTTP 403, the
Internet Archive holds no capture of any STANAG 4586 PDF, and the one mirror that carries this
family stops at Edition 3. The adapter is therefore built on, and declares, the edition it actually
read. `fixtures/stanag4586/spec/stanag4586_pin.json` records the digest, the byte count, the page
count and the title-page identity, together with the two copies' **one-byte** divergence — a mirror
stamp — and the page-by-page proof that the standard's content is identical across them.

**It is ingest only, and the scope ruling is enumerated rather than implied.** The document defines
**166 field-table messages in 27 functional groups**. **48 of them, across 9 groups, are command
uplink and are out of scope** — this repository will not decode them, because the CDM has no command
or tasking kind for them to translate into, and emitting them would make this a UCS component.
They are listed by group and number range in `FORMAT_COVERAGE.md` rather than silently omitted.
**Four messages are decoded field by field**; every other message has its wrapper read and its data
octets parked verbatim with its type recorded, so a datagram carrying one unknown message among
four known ones still translates the four.

`Stanag4586Adapter.direction` is `ingest`, which `adapter.py`'s contract enforces at
class-definition time, and `stanag4586_codec.py` has no encoder at all.

## Fourteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
The table is the live registry, and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree — a table missing an adapter tells a reader the roster is smaller than it is.
Unlike 1.3.0's table, this one needs no row marked as postdating the release: every adapter here is
in the artefact.

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
| `stanag4609` | bidirectional | 20 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**432 fixture verdicts, 0 failed** across the fourteen adapters this release ships, against the
published schemas. 1.3.0 shipped 408 across thirteen; the difference is `stanag4586`'s 24, and the
432 here was summed from the harness over the registry rather than obtained by adding 24 to 408 —
the two arrive at the same number from different directions, which is the point of deriving it.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1 and 1.3.0 were

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
pip install synapse-cdm==1.4.0
python -m synapse_cdm.harness --list-adapters
```
