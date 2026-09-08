# synapse-cdm 2.0.0

A major release, and what it adds is a semantic layer over the model this package has always
carried. **SC-OES** — the SynapseCommand Operational Event Specification, v0.1.0 Draft — attaches
operational-event semantics to a CDM object *after* source-format translation: what kind of
assertion an event is, which governed semantic type it claims, what it relates to and with which
role, and how sure its source was. It is a wire-semantic contract, not a new format and not a
replacement for one.

**Package version 2.0.0 · CDM `schema_version` 2.0.0.** If you consume CDM objects, this is a
breaking change and the next section says exactly how. **The two numbers being equal is a
coincidence of two independently justified major changes and not a derivation** — the schema moved
on `MIGRATIONS.md`'s table because a 1.x strict reader rejects the new objects, the package moved
on `version.py`'s because a third party's consumer written against 1.8.0 does not work against this
distribution, and `synapse_cdm/version.py` states the six version axes and their independence in
one place. A package at 2.0.0 does **not** mean SC-OES 2.0: SC-OES is at `0.1.0` and is a Draft.

**UNRELEASED, ADDED 2026-09-08 — the wire contract has moved again, and these notes are still
2.0.0's.** The paragraph above describes the distribution the index serves and stays exactly true
of it: 2.0.0 shipped at CDM `schema_version` 2.0.0 and the two numbers really were equal at that
tag. On the working branch the SOIF Part 1 CDM round has taken `SCHEMA_VERSION` to
**`schema_version` 2.1.0**, a MINOR — the geometry, vertical-position, temporal-validity, route,
area, quality, provenance, status and residual primitives are added, every one of them as an
optional field or a model reached only through one, so a 2.0.0 reader keeps working and 2.0.0 data
keeps validating. `PACKAGE_VERSION` has NOT followed and is still `2.0.0`: a schema bump obliges a
release, it does not perform one, and the number is the release round's to type. **No release
carries any of that yet.** This paragraph is here for the reason the same paragraph was here for
the 1.8.0 -> 2.0.0 arc: these notes are one of the few documents that state both numbers, which
makes them one of the few places the two could be made to disagree without anybody noticing.
`packages/cdm/synapse_cdm/MIGRATIONS.md`'s pending section carries the migration statement, the
derivation and the bump rulings.

## What changed on the wire, and what a 1.x consumer must do

Two optional keys, and they are what makes this a major:

* `Event.oes` — the SC-OES block, `null` unless the producer made an SC-OES assertion.
* `Entity.ontology_types` — a list of governed ontology identifiers, empty unless the producer
  asserted one.

Both are OPTIONAL and both default to nothing, so legacy data is structurally representable
without change. That is not the same as compatibility, and this document does not claim it is: the
canonical objects are `additionalProperties: false`, so **a 1.x strict reader meeting either key
rejects the object rather than ignoring it**. `version.compatible("2.0.0", "1.0.0")` is `False`,
and that refusal is the message the major exists to carry. Whether to move is an explicit consumer
decision; `packages/cdm/synapse_cdm/MIGRATIONS.md` carries the migration statement and the
derivation.

There is no migration tooling and none was written for this release. Migration in this repository
is documented rather than executable, deliberately, and a framework invented for one release would
be a second thing to keep correct.

## What SC-OES adds

* **The specification**, `spec/sc-oes/`, v0.1.0 Draft: core model, event classes, governed event
  types, temporality, relations, confidence, entity semantics, security markings, extensions,
  versioning and conformance.
* **The SynapseCommand Operational Ontology**, v0.1.0 Draft. Turtle is the authority; the JSON-LD
  context and the packaged term registry are derived from it and drift-tested against it, and
  **nothing at runtime parses RDF** — `rdflib` is a test dependency and a boundary test proves it.
* **Three packaged machine-readable registries** under `synapse_cdm/registry/sc_oes/`: the governed
  event contract, the generated ontology-term registry, and the profile registry. All three ship in
  the wheel, load through `importlib.resources`, and need no checkout and no network.
* **Offline conformance tooling** — `python -m synapse_cdm.conformance`, also installed as
  `cdm-conformance` — reporting five separately named dimensions, `PASS`/`FAIL`/`SKIP` each, with
  no aggregate score and four exit codes a CI system can branch on.
* **A reference producer.** The `pntmap` adapter emits the block on every alert, asserting three
  fields and nothing its source does not support.
* **Fourteen worked examples**, thirteen individual and one linked operational chain, and **seven
  profile documents**.

## Dimension D is executable for one profile

The **PNT Profile 0.1.0** is the first profile with a conformance rule of its own, so a
conformance assessment of the reference GNSS-interference event against it returns
A `PASS`, B `PASS`, C `PASS`, D `PASS`, E `PASS` and exits `0`. The permitted claim is
**"SC-OES PNT Profile 0.1 Conformant"**, it names one assessed object, and it is not a
certification: this work creates no certification programme.

The other six profiles are **specification-only** and dimension D against them is `SKIP` — the
profile is known and has no executable rules, which is a different fact from a profile name that
does not exist and a different fact again from an object that failed. A `PASS` drawn from an empty
rule set would be a claim manufactured out of the absence of anything to check.

The profile does **not** require any particular producer. `PNTMAP` is a reference producer; a
third-party GNSS monitor, a military sensor adapter or a simulation producer conforms on the same
terms.

## Why this is a MAJOR, and the gate derived a MINOR floor

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between
`v1.8.0` and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** — and
that is not a disagreement, it is the gate answering the question it can answer. Every signal it
can prove is an ADDITION: an optional field on two models, seventeen exported names, two new
modules, three shipped registries, an adapter emitting a key it did not emit before. No importable
name is removed and no signature moves, so no MAJOR row is reached **by the diff**.

What the derivation cannot reach is the fact that decides the number: **what breaks is a third
party's consumer**, and no file in this distribution records a third party's code.
`docs/adr/0005-cdm-schema-version-impact.md` is where that derivation is argued and it was argued
before the number was typed. The gate calls its own answer a FLOOR and says so; the release that
types the number writes the ruling, and the ruling is a dated paragraph in `MIGRATIONS.md`'s
section for this arc naming both ends of it. Run
`.venv/bin/python gates/bump_derivation.py` on this tree and it prints both: `derived MINOR`, and
`version rule MAJOR over the derived MINOR floor`.

`pending.unruled` is the empty list at this commit, which is the pre-step the release procedure's
condition 5 requires before a version number is typed.

## What else moved

* **The published schemas.** All six regenerate from the models and carry `2.0.0`; `event` and
  `entity` gain one optional property each and nothing is removed or retyped.
* **Every golden in the package** now carries `schema_version` `2.0.0`, every entity an
  `ontology_types` list and every event an `oes` key. Compared by JSON path, the moved set across
  the CDM goldens is exactly those three paths — the `pntmap` adapter's four goldens additionally
  carry the block it now emits.
* **No runtime dependency changed.** `pydantic` and `jsonschema`, as before. `rdflib` is a test
  extra and nothing under `synapse_cdm/` imports it.
* **No adapter was added or removed**, and no adapter's translation was changed to make a
  conformance verdict come out differently.

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
The roster's totals are unmoved from 1.8.0: this release adds a semantic layer over the objects
and no fixture. `gates/wheel_install.py` reports **1076** over the same roster, which is these 538
run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
2.0.0`.

## Published by CI over OIDC, as 1.1.0 through 1.8.0 were

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
pip install synapse-cdm==2.0.0
python -m synapse_cdm.harness --list-adapters
```
