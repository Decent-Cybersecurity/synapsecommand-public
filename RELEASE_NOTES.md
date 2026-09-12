# synapse-cdm 2.1.2

**SOIF Part 1 — Foundation & Assurance**, and this is the release that ships it. Part 1 is not a
format and not a semantic layer: it is the machinery that makes a claim about an adapter checkable
by somebody who did not write it. An adapter now describes itself in a published manifest; a
fifteen-check conformance suite runs over any adapter in the roster; an evidence record states what
was measured, on which commit, against which versions, with a digest of every fixture the run read;
and the CDM gains the geometry, time, route, quality, provenance and residual primitives an adapter
needs in order to say what it actually translated. Nothing is removed, renamed or narrowed, so a
2.0.0 consumer keeps working without doing anything.

**If you are upgrading from 2.0.0 — which is what the index served until this release — read this
as the MINOR it is.** Everything below is the arc from 2.0.0, because neither 2.1.0 nor 2.1.1 ever
reached anybody.

## Why the number is 2.1.2 and not 2.1.0 or 2.1.1

**Two tags were cut before this one, both were pushed, neither was published, and both stay where
they are.** They were refused by two different steps of this project's own release pipeline, and
both refusals were the same shape: a step whose behaviour depends on the ref, executed for the
first time on a tag ref.

* **`v2.1.0`**, on commit `b69a267`, 2026-09-09. The `gate` job's last step was
  `pip-audit --strict` over the installed environment; that environment holds the release
  candidate at the tree's own version, `--strict` turns a distribution the index cannot resolve
  into a failure, and the index cannot carry 2.1.0 until the `publish` job — which needs the gate
  that just failed. A gate that required the publication it was gating. The repair scopes both
  audits to the release candidate's dependencies, excluding only `synapse-cdm` itself by name, and
  leaves every third-party line under `--strict`.
* **`v2.1.1`**, on commit `4409115`, 2026-09-10. Step 15 passed — the repair worked — and step 16
  of 17 refused it: the CodeQL gate asked for the code-scanning analyses of `${GITHUB_REF}`, which
  on a tag push is `refs/tags/v2.1.1`, and no workflow in this repository can produce an analysis
  on a tag ref. The commit had two clean analyses on `refs/heads/main`; the ref filter excluded
  them. The repair makes the gate read the analyses of the **commit** it is gating, which is what
  the step's own name had promised since it was written.

Neither tag is moved, deleted or recreated: each remains permanently attached to its commit as a
release tag that released nothing, and 2.1.2 is the corrective. `PUBLICATION.md`'s ledger records
what was actually uploaded, and nothing in this file claims an upload that has not happened.

**What the arc closed is the class and not the two instances.** `gates/release_ref_rehearsal.py`
replays every ref-dependent release step — the tag guard, the tag-names-the-version condition, the
annotated-tag check, the CodeQL query, the five tag-derived versions and the Release name — against
a named tag and commit while that tag is still local, and it is a mandatory act between tagging and
pushing. Its last check refuses any future use of `GITHUB_REF` in the release workflow that its own
covered-uses table does not name, so the next ref-dependent step fails on a laptop rather than on a
pushed tag. Its own test now derives the tag it rehearses from `PACKAGE_VERSION`, so the rehearsal
does not become the next thing a version bump surprises.

Between `v2.1.1` and this tag the distribution itself moves by two files — `MIGRATIONS.md` and
`version.py`. `gates/bump_derivation.py` derives PATCH over that arc with nothing unruled, and
2.1.2 is that floor.

**Package version 2.1.2 · CDM `schema_version` 2.1.0.** The two numbers are unequal, and **that is
the ordinary case and not a signal**: the schema moved on `MIGRATIONS.md`'s table in the CDM round,
for optional primitives only; the package moved on `version.py`'s table for the release; and then
the package moved twice more, two PATCHes the wire contract had no part in. They were level for one
day. `synapse_cdm/version.py` states the nine version axes and their independence in one place, and
`tests/test_cdm_packaging.py` sweeps the package for an assignment that would derive either number
from the other. A package at 2.1.2 does **not** mean SC-OES 2.1: `SC_OES_VERSION` is a third axis,
still `0.1.0` and still a Draft.

## What changed on the wire, and what a 2.0.0 consumer must do

**Nothing, and this is the release that says so with a gate rather than a promise.** `schema_version`
moves 2.0.0 -> 2.1.0 and every addition behind it is an optional field or a model reached only
through one, so a 2.0.0 reader still reads a 2.1.0 object and a 2.0.0 object still validates against
the 2.1.0 models. The fourteen worked examples under `spec/sc-oes/` are the witness: they still
declare `schema_version` 2.0.0 and they still validate.

What a producer gains is vocabulary, not obligation:

* **Geometry.** `synapse_cdm.geo` carries `Point`, `LineString`, `Polygon` and their multi- forms,
  plus `BoundingBox`, `VerticalPosition` and `VerticalExtent`. A vertical position states its unit
  and its datum, because an altitude without a datum is a number and not a position.
* **Time.** `TemporalValidity` and `Period` — when an assertion is held to be true, as distinct
  from when it was made.
* **Route and area.** `Route`, `RouteLeg`, `Waypoint`, `Area`.
* **Quality and provenance.** `Quality`, `SourceHash`, `OperationalStatus`, and seven added fields
  on `SourceRef` so that a CDM object can say which bytes it came from.
* **Residual data.** `Residual` and `lossless.classify()`, which partitions every source leaf into
  six categories and lets an adapter carry what the CDM has no field for instead of dropping it
  silently.

`packages/cdm/synapse_cdm/MIGRATIONS.md`'s 2.1.0 section carries the migration statement and the
derivation, entry by entry, and its 2.1.2 section carries this release's own record. There is no migration tooling, because there is nothing to migrate.

## Adapter API v2, and every adapter now describes itself

`ADAPTER_API_VERSION` is `2.0.0` — the contract an adapter class is written against, additive over
v1 and renaming nothing. v2 adds four members: `metadata`, `detect`, `validate_source` and
`capabilities`. `ARCHITECTURE.md` §1 freezes it.

The visible half is the **manifest**. All fourteen adapters ship one under `manifests/`, validated
against `schemas/manifests/adapter-manifest.schema.json` at `MANIFEST_SCHEMA_VERSION` `1.2.0`, and
`python -m synapse_cdm.manifests --check` reports `CURRENT: manifests vs 14 shipped adapters at
manifest schema 1.2.0`. A manifest states the adapter's direction, its declared limits and where
each limit's number came from, its known limitations as structured records rather than sentences,
and what it does not support — so "this adapter handles that format" becomes a document a third
party can read without reading the code.

## The Synapse Conformance Suite

`python -m synapse_cdm.suite`, also installed as `synapse`, runs **fifteen checks, A through O**,
over any adapter in the roster: identity, determinism, malformed input, parser robustness, resource
limits, streaming, temporal handling and the rest. Results come out as `--format json` and are
byte-identical across two sweeps of one tree, which is what makes them evidence rather than output.

SC-OES conformance is a separate and smaller thing and it is unchanged: `python -m
synapse_cdm.conformance`, also `cdm-conformance`, reports five separately named dimensions with
`PASS`/`FAIL`/`SKIP` each, no aggregate score, and four exit codes a CI system can branch on. The
**PNT Profile 0.1.0** remains the only profile with an executable rule of its own; against the
other six, dimension D is `SKIP`, which is a different fact from a failure and a different fact
again from a profile that does not exist. This work still creates no certification programme.

## Evidence records

`EVIDENCE_SCHEMA_VERSION` `1.0.0`, published as `schemas/evidence/evidence.schema.json`. `synapse
evidence generate --adapter X | --all` writes one record per adapter: the manifest embedded whole,
the commit it was measured on, five version axes, the conformance report verbatim, the loss report,
and a SHA-256 of every fixture file the run read. `synapse evidence verify <file>` generates a NEW
record from the tree in front of it and compares field by field, masking only what is a measurement
of the run rather than of the tree — so reproducibility is a command and not an assertion. `synapse
badges` derives shields.io endpoint files from those records and refuses to write one without a
record behind it.

**The records are not in this distribution and not in the repository.** They are produced by CI on
every run, uploaded, and attached to a release; each adapter's manifest declares
`evidence.available: false` until the release they are attached to exists. Thirty-nine
`PROVENANCE.json` records — one in every fixture directory a tracked test reads — say where the
fixture data came from.

## Security, dependencies and the supply chain

* `SECURITY.md`: the reporting path, and a parser-safety policy with declared limits on all
  fourteen adapters.
* Secret scanning on the platform, `.gitleaks.toml` in the tree, and a CI job over the full
  history reachable from every push.
* `pip-audit --strict` twice — over the environment and over the wheel's frozen closure — with
  exactly one distribution excluded by name, `synapse-cdm` itself, because an audit that has to
  resolve the release candidate against the index is a gate requiring the publication it gates.
  Every third-party line stays under `--strict` and no transitive dependency is excluded. Plus an
  npm audit at high over the documentation tree, with the two live advisory exceptions declared as
  files under `security/exceptions/` with an expiry each rather than as a flag on a command line.
* CodeQL, and a gate that refuses a blocking alert.
* An SBOM in both SPDX and CycloneDX, built by the release pipeline over the clean-install
  environment, plus a second tool's cross-check.
* Build provenance: Sigstore attestation over the built artefacts, verified in the same run that
  produced them.

## What else moved

* **The published schemas.** All six regenerate from the models at `2.1.0`, and two new ones join
  them — the adapter manifest and the evidence record. `git diff v2.0.0..HEAD -- schemas/` is eight
  files, 3915 insertions, 39 deletions. `python -m synapse_cdm.schemas --check --out schemas`
  reports `CURRENT: schemas vs models at 2.1.0`.
* **A fourth console script**, `synapse`. It is the one entry point not spelled `cdm-*`, because
  SOIF §19 fixes the command line it has to answer to. The three that existed are unchanged.
* **No runtime dependency changed.** `pydantic` and `jsonschema`, as before. `rdflib` is a test
  extra and nothing under `synapse_cdm/` imports it.
* **No adapter was added or removed**, and no adapter's translation was changed to make a
  conformance verdict come out differently.
* **A release pipeline.** `.github/workflows/publish.yml` now runs six jobs in SOIF §50's order —
  gate, build, attest, publish, release, witness — and the last three of them only on a tag.

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
The roster's totals are unmoved from 2.0.0: this release adds vocabulary and assurance machinery
over objects already translated, and no fixture. `gates/wheel_install.py` reports **1076** over the
same roster, which is these 538 run in each of two schema modes.

## Published by CI over OIDC, as 1.1.0 through 2.0.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** together with the
workflow run that produced them. This release additionally attaches, to the GitHub Release itself,
both SBOMs, the evidence set, the conformance report, the witness record and these notes — so the
evidence a claim rests on is retrievable with the release rather than only as a workflow artefact
with a retention window.

They are deliberately not committed here, for the reason this file has given since 1.1.0. A digest
is a property of one build rather than of the tree: two builds of one tree have identical payloads
but differ in their generated metadata, so a digest written here before the tag would not be the
digest of the file PyPI serves, and one written after the tag could never be inside the tree the tag
names. **1.3.0 measured that the hard way** — a local build and the published wheel came out at the
same byte count and were different files — so the digests to compare a download against are the
workflow's, never a rebuild's. Everything else in this document is readable off that tree, which is
what condition 4 of the release procedure asks for.

```bash
pip install synapse-cdm==2.1.2
python -m synapse_cdm.harness --list-adapters
```
