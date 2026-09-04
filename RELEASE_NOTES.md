# synapse-cdm 1.4.1

A patch release. One refusal changes its exception class, two messages change what they cite, and
no importable name is added, removed or retyped.

**Package version 1.4.1 · CDM `schema_version` 1.0.0.** If you consume CDM objects, this release
asks nothing of you: no schema moved, no field was added, removed or retyped, and the diff over
`schemas/` since 1.4.0 is empty — `git diff v1.4.0..HEAD -- schemas/` returns nothing, which is the
check that decided `SCHEMA_VERSION` stays where it is rather than an assumption that it would.

**If you decode KLV lengths and catch this package's exceptions, read the next section.** It
carries the one behaviour change a caller can see, and it is the reason a patch release has a
section about behaviour at all.

For what 1.4.0 was — STANAG 4586 telemetry ingest — see
[the 1.4.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.4.0)
and the previous notes in this file's git history. This document does not restate them.

## The one change a caller can see: `0x80` as a first BER length octet

`klv_codec.decode_ber_length` now raises **`KLVFramingError`** for a length whose first octet is
`0x80`, where it raised **`UnderivableFromPinnedCopy`**. `KLVFramingError` is a `ValueError` and
`UnderivableFromPinnedCopy` is a `NotImplementedError`, so they share no base but `Exception`:
**a caller catching `UnderivableFromPinnedCopy` to handle indefinite lengths must catch
`KLVFramingError` instead.** Nothing else about the function moved — the same inputs are accepted,
every length it decodes decodes to the same value, and no other octet changed which refusal it gets.

The change is a fact about what this repository can now cite rather than about the octets. `0x80`
declares zero following octets; MISB ST 0107.3 never mentions that form, so until now the decoder
said *nobody here knows whether these bytes are wrong*. SMPTE ST 336:2017 §5.3 states it — the
Length field "shall be set to [0x80] which shall indicate a non-deterministic length of the Value
field", available only where an application document "shall define an alternative method of locating
the end of the Value field". No MISB document this repository holds defines such a method, and
`ST 0107.3-05` requires every item Length to be encoded "using the fewest possible bytes", which
makes every conforming length determinate. So the bytes are wrong, and the decoder now says so.

**Note the scope, because it is narrower than "ST 336 forbids `0x80`":** ST 336 *permits* it. The
refusal is the MISB profile's, and it rests on a missing end-finding method in the application
documents rather than on a prohibition in the framing standard.

## Why this is a PATCH, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between `v1.4.0`
and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **PATCH** over
**14 signals** — shipped documents, pin records, one fixture payload and four units inside two
modules — and no signal reaches a MINOR row: no importable name appears or disappears, no fixture
set is added, no harness flag and no dependency moved.

**Two of those signals the table could not classify, and a person ruled them.** The gate's PATCH row
("a translation fix, a message, a docstring") and its MAJOR row ("an importable name is removed or
its **meaning** changes") both reach a function whose body moved and whose name did not, so it names
the unit and stops rather than guessing. Both rulings are recorded in `MIGRATIONS.md`'s 1.4.1
section, and the gate reads them back and refuses one that outlives its case:

* **`decode_ber_length` — PATCH.** The exception class for one first-octet value changes between two
  refusals the function already raised on other inputs. The accepted input set is unchanged, so no
  caller that handled its refusals handles fewer of them now.
* **`_CEILING_RESIDUE` — PATCH.** A module-private message string, not exported and not reachable by
  name from outside the module.

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on
this tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## What else moved

* **The long-form ceiling message.** `_CEILING_RESIDUE` now cites SMPTE ST 336:2017 §5.3 NOTE 1 —
  which states in the standard's own words that it imposes no maximum on the number of bytes in the
  Length field — and ISO/IEC 8825-1 §8.1.3.5(c), which forbids an initial octet of `0xFF` and would
  cap the count at 126. **`BER_LENGTH_OF_LENGTH_MAX` is unmoved at 127** and the encoder refuses
  exactly the values it refused before: that tighter bound is recorded and deliberately not
  enforced, because X.690 is not held and the text is reproduced in an *informative* annex.
* **One fixture payload's verdict changed.**
  `fixtures/klv/framing/length_indefinite_first_octet.parsed.json` is the single octet `0x80`, and
  its recorded refusal moved with the codec's. It is the only fixture in the distribution whose
  verdict this release changes.
* **The shipped documents.** Park 8 — SMPTE ST 336, the one entry the coverage record had priced as
  needing a purchase rather than an afternoon — **closed**, on both editions obtained free from the
  publisher's own library at `pub.smpte.org`. Two ambiguity-register entries closed with it: KLV 11,
  by reading the 2017 and 2007 editions against each other, and KLV 13, adjudicated by ST 336:2017's
  own reference list. `FORMAT_COVERAGE.md` and `fixtures/klv/spec/klv_pin.json` carry the clause
  numbers and the quotations.

**No adapter, model, schema, harness flag or dependency moved**, and the pinned specification
documents are gitignored as they have always been — nothing in this release redistributes a
standard.

## Fourteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
The table is the live registry, and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree — a table missing an adapter tells a reader the roster is smaller than it is.
**The roster did not move this arc**, which is derived here rather than carried over: `discover()`
and `roster()` each return fourteen, and the totals below were summed from the harness on this tree.

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

**432 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas —
the same total 1.4.0 shipped, because this release adds no fixture and removes none. The one payload
whose *verdict* changed is the `0x80` framing fixture above, which is a framing fixture rather than
an adapter fixture and is not counted in this table. `gates/wheel_install.py` reports **864** over
the same roster, which is these 432 run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1, 1.3.0 and 1.4.0 were

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
pip install synapse-cdm==1.4.1
python -m synapse_cdm.harness --list-adapters
```
