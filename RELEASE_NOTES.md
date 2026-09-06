# synapse-cdm 1.8.0

A minor release, and what it adds is one item and one document. MISB ST 0601 item 73 — the RVT
Local Set — is decoded and carried, so a `stanag4609` consumer whose packets nest a MISB ST 0806.4
set now receives it instead of an unread run of octets. And the MISP-2019.1 Motion Imagery
Handbook, the last document this profile delegates to that was not on disk, is held and pinned:
**the parks table is empty at this release**, thirteen rows and none of them open, which is the
first time this package has shipped with nothing waiting on an acquisition.

**Package version 1.8.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, no schema
moved: no field was added, removed or retyped, and the diff over `schemas/` since 1.7.0 is empty —
`git diff v1.7.0..HEAD -- schemas/` returns nothing, which is the check that decided
`SCHEMA_VERSION` stays where it is rather than an assumption that it would. Everything new reaches
a consumer inside `Entity.attributes`, which the published `entity` schema declares
`additionalProperties: true` — the 1.2.0 ruling, applied a fifth time and checked against the
schema files rather than recalled.

**If you ingest STANAG 4609 / MISB KLV, read the next section.** Nothing is removed and no key
changes shape. A packet that carries no item 73 yields exactly the object 1.7.0 yielded, byte for
byte; a packet that carries one yields the same object with four more keys on it.

For what 1.7.0 was — item 74 becoming `DETECTION` events and `Track` objects, item 94 becoming
entries in `Entity.source_ids`, and MISB ST 0902.8's minimum metadata set riding every object as a
per-packet advisory — see
[the 1.7.0 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.7.0)
and the previous notes in this file's git history. This document does not restate them.

## What changed on the wire for a `stanag4609` consumer

Three things, each stated as what a consumer receives.

**1. A packet carrying ST 0601 item 73 now puts the decoded RVT Local Set on the packet's own
`Entity`, under four new `attributes` keys.** They are `rvt_local_set`, `rvt_basis`,
`rvt_mapping_not_taken` and `rvt_embedded_set_policy`, and the parsed twin the harness harvests
gains a matching `rvt` key. `attributes.rvt_local_set` carries the set's `element_order` — the tags
in the order the octets presented them — and an `elements` map keyed by tag number, each entry
naming the element, its raw `octets`, its decoded `value`, its `units` as ST 0806.4 states them,
and the `requirements` the element satisfies. Subordinate sets appear under `subordinate_sets`,
each with the tag that carried it and the same shape recursively.

**None of these keys appears on a packet without item 73.** That is the same conditional-key rule
`vmti` was given in 1.7.0, applied to a fifth layer, and it is why every golden written before this
arc is byte-identical after it: the pinned real stream carries no item 73 at all, so all 112 of the
goldens that existed at `v1.7.0` are unchanged and the only paths this release adds are the `rvt`
ones on its own seven new fixtures.

**2. Four element tables are read, not one.** `adapters/klv_rvt_codec.py` is a new module and walks
MISB ST 0806.4's Table 8-1 (the RVT Local Set, 21 tags), Table 8-2 (Point of Interest LS, 10),
Table 8-3 (Area of Interest LS, 10) and Table 8-4 (User Defined LS, 2) with **one** recursive
`decode_set`, because a subordinate set's Value is a bare run of triplets exactly as ST 0601 item
73's own is. An RVT tag this layer does not list is carried through and reported rather than
dropped, and an element whose stated length it does not have is refused with the packet still
translating — both behaviours have a fixture of their own.

**3. Eight elements that have a CDM home are deliberately NOT mapped into one, and the release says
so rather than leaving it to be discovered.** POI Latitude, POI Longitude and POI Altitude
(Table 8-2, tags 2–4), the four AOI corner coordinates (Table 8-3, tags 2–5) and the RVT LS's own
User Defined Time Stamp (Table 8-1, tag 2) all ride in `attributes` as the document names them.
Emitting a POI as a second `Entity`, or an AOI as a geometry, is a modelling decision no clause of
either document makes, so it is written down as a proposal in `attributes.rvt_mapping_not_taken`
and is not taken. A consumer that wants that shape today can read it off these keys; a consumer
that waits for the model to grow one will not have had a guess made on its behalf in the meantime.

**And what the RVT set is NOT.** ST 0806.4's four requirements govern an *independent* RVT Local
Set. One nested in ST 0601 item 73 is not independent — it draws its time and its integrity from
the ST 0601 packet, which carries both — so this layer **reports** which of the four the octets
satisfy, per element, and refuses nothing on their account. The reasoning, with both documents'
clauses, is in `attributes.rvt_embedded_set_policy` on every packet that carries the set.

## The parks table is empty, and what that does and does not mean

`gates/parks_table.py` reads **13 rows, 0 open, 13 closed** at this commit. Two rows closed in this
arc and they were the last two.

**Park 7 closed on MISB ST 0806.4**, pinned by digest and byte count and transcribed into the four
tables above.

**Park 10 closed on the MISP-2019.1 Motion Imagery Handbook**, and it closed on a *reading* rather
than on code: the Handbook is the fourteenth and last document MISP-2019.1 delegates to, and the
open question against it was register entry KLV 8 — whether the Handbook is normative for the KLV
metadata this adapter emits. It is not. The Handbook's own Scope page says *"The MISP succinctly
states requirements, while the Motion Imagery Handbook discusses principles underlying requirements
more thoroughly,"* and the document bears that out: 124 pages carrying **one** `shall`, about the
term FMV, no Common Metadata System named anywhere in it, and no required data items defined. So it
is ruled a **companion**, the ruling is closed in `fixtures/klv/spec/klv_pin.json`'s ambiguity
register with the sentence that decided it, and **no row of `FORMAT_COVERAGE.md` moved on its
account.** A consumer receives nothing new from park 10 and that is the correct outcome: what
changed is that a question this record had carried open since it was written now has an answer with
a page number on it.

**What it does not mean.** An empty parks table is a statement about *acquisition* — every document
the profile delegates to is on disk and pinned — and not about coverage. Rows in
`FORMAT_COVERAGE.md` still read `not yet`, and the parks table never tracked those.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between `v1.7.0`
and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** over
**100 signals** across **37 distribution files**, and the floor is **1.8.0** — the release gate's
moved set is 38, the one file apart being `version.py`, whose only changed unit at this commit is
the declaration the gate refuses to read as evidence for itself. The kind needed no argument:
`adapters/klv_rvt_codec.py` is a **new importable module**, `klv_uas_codec` gains the public names
`RVT_TAG` and `RVT_BASIS`, `stanag4609` gains `RVT_ABSENT_BASIS`, and `fixtures/klv/` gains seven
payloads that extend a fixture set — all of which sit on the MINOR list. No importable name is
removed and no signature moves, so no MAJOR row is reached, and no emitted key was removed either.

**Twelve units the table could not decide carry a person's ruling, and not one of them is this
release round's.** The gate's PATCH row and its MAJOR row both reach a function whose body moved and
whose name did not, so it names the unit and stops rather than guessing. Every one of the twelve was
ruled by the round that made it, in `MIGRATIONS.md`'s 1.8.0 section, in the form the gate parses,
with the check that was taken recorded beside it — **eight of the twelve are PATCH and four MINOR**,
and all eight PATCH units are top-level statements the gate names by POSITION, six of them import
lines renumbered by an inserted import and two of them module-level statements modified in place
with no name added or removed. That is a property of positional unit naming rather than a change to
anything a caller can see. `pending.unruled` is the empty list at this commit, which is the pre-step
the release procedure's condition 5 requires before a version number is typed.

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on this
tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## What else moved

* **Three documents were pinned and the pin corpus reached every delegation.** MISB ST 0806.4
  (park 7) and both editions of the Motion Imagery Handbook — MISP-2019.1, which park 10 stands on,
  and MISP-2019.2, pinned **context only** as a later edition of the same delegated document.
  `gates/pin_paths.py` reads **30 pinned copies, 30 present, 30 matched, 0 failed**, three more than
  1.7.0 shipped. `klv_pin.json`'s own derivation from its sha256-bearing entries now reads
  **nineteen** of them, of which five are held and are not delegations, leaving **fourteen — the
  whole of what MISP-2019.1 delegates to.** The pinned documents themselves are gitignored, as they
  have always been: nothing in this release redistributes a standard.
* **The KLV fixture set grew by seven payloads and their seven parsed twins, and the golden set by
  fourteen**, to 63 payloads and 126 goldens. `stanag4609`'s fixture verdicts move from 112 to
  **126**, and the roster's total from 524 to **538**.
* **The seven new fixtures are built from the element rules, not from a printed example, and the
  release says which.** ST 0806.4 prints no worked packet: its one packet illustration, Figure 7-1,
  is a raster image, and ST 0601.14a §8.73's Example KLV Item row reads `49 - N/A`. So there is no
  `check_against_the_documents_own_examples` in the new module, because there are no examples to
  check against — which is stated rather than quietly omitted.
* **The shipped documents.** `MIGRATIONS.md`, `FORMAT_COVERAGE.md` and `fixtures/klv/README.md`
  carry the arc; `klv_pin.json` gains the `st_0806_4` node, both Handbook nodes, the closure entries
  for parks 7 and 10, the closed KLV 8 register entry, and a dated negative recording that no
  archive capture of any 2019.x Handbook exists on any `nga.mil` host.

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
| `stanag4609` | bidirectional | 126 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**538 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas.
The whole of the increase is `stanag4609`'s: fourteen more verdicts than 1.7.0 shipped, from the
seven new payloads and their parsed twins. `gates/wheel_install.py` reports **1076** over the
same roster, which is these 538 run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
1.0.0`.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1, 1.3.0, 1.4.0, 1.4.1, 1.5.0, 1.6.0 and 1.7.0 were

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
pip install synapse-cdm==1.8.0
python -m synapse_cdm.harness --list-adapters
```
