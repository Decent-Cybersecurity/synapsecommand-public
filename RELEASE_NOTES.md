# synapse-cdm 2.2.0

**The audit release.** Between the 2.1.2 release of 2026-09-12 and this one, nothing was added to
what the package translates: the same fourteen adapters, the same 538 fixture verdicts, the same
six published CDM schemas at `schema_version` 2.1.0. What moved is what SOIF Part 1 — the Synapse
Open Interoperability Framework's Foundation & Assurance part, a private specification whose
section numbers this file cites as §N — exists to make checkable: two adapters that crashed on a
valid document nested a thousand elements deep now refuse it at a declared bound, and four more
declare the same bound; a maturity rung that eleven manifests typed is now computed by the
harness; an evidence record generated on one machine now reproduces on another; CI runs the suite
on every interpreter the package claims, lints, and runs the wheel gate on every push; the release
pipeline's witness verifier re-derives the digests it used to check for shape; the two npm
advisory exceptions are deleted on the trigger their own files named; no tracked file points a
reader at a private document; and every sentence the audit found false is corrected where it
stands. Nothing is removed, renamed or narrowed, so a 2.1.2 consumer keeps working without doing
anything — with the three refusals listed below, each of which replaces a crash or a wrong
exception on input no shipped fixture ever carried.

**If you are upgrading from 2.1.2 — which is what the index serves — read this as the MINOR it
is.** If you are upgrading from 2.0.0, read the 2.1.2 notes first: they are the body of the
`v2.1.2` Release, and everything they describe is still here.

## Why the number is 2.2.0

**The number is the derived floor, and for the first time since v2.1.0 it moved for content.**
`gates/bump_derivation.py` reads the arc from `v2.1.2` and derives MINOR from importable names
that did not exist at that tag, with nothing removed: `adapter.InputTooDeep`,
`json_nesting_depth`, `container_depth`, `enforce_depth_bound`, `is_shipped` and `shipped`; the
`ROUNDTRIP_TOLERANCE`, `ROUNDTRIP_TRANSFORMS` and `roundtrip_reference()` members of `Adapter`;
`canonical.py`, a new module; `harness.select_fixtures` and `fixtures_required_message`;
`version.SEMVER_RE` and `is_semver`; six `*_MAX_DEPTH` module constants; and a `[lint]` extra in
`pyproject.toml`, which is the table's optional-dependency row. The eighty-three units the table
cannot classify on its own — bodies that moved with no name added or removed, and import blocks
the gate keys by position — are every one ruled in `MIGRATIONS.md`'s 2.2.0 section, and the gate
reads those rulings and reports nothing unruled. The two correctives before this release each
moved the number for a workflow's defect; this one moves it for what a consumer receives.

**Package version 2.2.0 · CDM `schema_version` 2.1.0 · Adapter API 2.1.0.** The first two are
unequal by a MINOR now, and **that is the ordinary case and not a signal**: the package moved on
`version.py`'s table for new importable names; the schema moved by nothing, because no field and
no published schema changed, and no golden moved but the ten named below, by one citation string.
`ADAPTER_API_VERSION` moved 2.0.0 -> 2.1.0 on
`VERSIONING.md` §3's own row, for three additive members on the base class whose defaults are the
behaviour they replaced. `synapse_cdm/version.py` states the nine version axes and their
independence in one place, and `tests/test_cdm_packaging.py` sweeps the package for an assignment
that would derive one number from another. A package at 2.2.0 does **not** mean SC-OES 2.2:
`SC_OES_VERSION` is a third axis, still `0.1.0` and still a Draft.

## What changed on the wire, and what a 2.1.2 consumer must do

**Nothing on the wire.** `schema_version` stays 2.1.0; `git diff v2.1.2..HEAD -- schemas/` is
four files and five lines, every one a description string; and every golden file in the package
is byte-identical to the 2.1.2 release except ten under `fixtures/klv/golden/` — the five VMTI
fixtures' `.cdm.json` and `.parsed.cdm.json` — in which the one string that quoted a private
round brief by path, the VMTI identity ruling every VMTI object carries in its attributes, now
says the ruling's source is private; no other byte of any golden moved (`git diff v2.1.2..HEAD
--numstat -- packages/cdm/synapse_cdm/fixtures/klv/golden` is ten files, thirty-four lines each
way, every line that string). A 2.1.2 reader reads a 2.2.0 object unchanged, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
2.1.0`.

Three things a producer could do before and cannot now, each on input no shipped fixture, golden
or parsed twin ever carried:

* **A JSON document or dict nesting more than sixty-four containers is refused** by `adsb`, `ais`,
  `legion`, `pntmap` and `tak` with `adapter.InputTooDeep` — a `ValueError` — before any decoder
  runs, and an XML document nesting more than sixty-four elements is refused by `tak` and
  `stanag4676` the moment the tree is built. Before this release `tak` and `stanag4676` raised
  `RecursionError` on a valid document about 7 KB deep, which is one of the four crash classes the
  conformance suite refuses to count as a refusal, and the four JSON adapters translated any depth
  the interpreter survived. Each of the six manifests now declares the bound as `max_depth`, with
  its basis; the other eight keep their declared reason for having none.
* **`pntmap` refuses a JSON value that is not an object** — an array, a string, a number, `null` —
  with one `ValueError`, where it surfaced an `AttributeError` from inside the decoder.
* **Every version field is held to one spelling.** `schema_version`, `SourceRef.adapter_version`,
  a manifest's `adapter_version` and `Event.oes.spec_version` accept `MAJOR.MINOR.PATCH` with no
  leading zero, no prefix, no suffix and no surrounding whitespace — `version.SEMVER_RE` under
  `fullmatch` — where three of the four accepted `01.0.0` or a trailing newline. Every value this
  tree has ever written passes; the published schemas carry no new `pattern`, because a pattern on
  a published type is the schema table's "a type narrowed" and a MAJOR.

`packages/cdm/synapse_cdm/MIGRATIONS.md`'s 2.2.0 section carries the records, unit by unit, and
the rulings the derivation rests on. There is no migration tooling, because there is nothing to
migrate.

## Parser safety: a declared depth bound

The parser-safety policy — `docs/docs/security/parser-safety.mdx`, the page `SECURITY.md` names as
its home — gains its fifth reading beside the four of the 2.1.0 arc, and the JSON reading of
2026-09-17 in the prose beside them.
libexpat builds a tree of any depth without recursing, and everything the two XML adapters did
with the tree afterwards recursed once per level; on CPython 3.11 `json.loads` itself recurses
once per container and fails a little under a thousand deep. So the bound sits in front of the
decoder: the base class measures JSON text off its characters in one pass, decoded the way
`json.loads` would decode it, and a dict or list off its containers, and refuses past the declared
bound before any decoder runs; an XML tree stays the adapter's to measure, because only the
adapter holds it. Sixty-four is an implementation cap and every manifest says so — every CoT
fixture nests three elements deep, the deepest path AEDP-12's class model admits is eight
elements, no shipped JSON document nests more than seven containers, and sixty-four keeps every
walker under two hundred Python frames. Three `malformed/` directories gain the payload that
exercises the change, so check H records the refusal on every run.

## The harness computes L4

At 2.1.2 the harness's `roundtrip` column read SKIP for every adapter, because it compared JSON
structurally and every shipped emitter returns bytes, so every L4 in a manifest rested on a
per-adapter test the wheel does not carry — a typed rung, which §3.6's first sentence does not
admit. The column now compares egress octets under a tolerance each adapter declares and the
report prints: `bytes`, the default, means `from_cdm(to_cdm(raw))` must equal
`roundtrip_reference(raw)` octet for octet; `values` means what was emitted is re-ingested and no
source value may be missing, with the adapter's declared transforms excused — the tolerance XML
needs, and the one `tak` and `stanag4676` declare. The readings: 16, 11, 20, 17, 17, 41, 28, 16
and 63 byte fixtures octet-exact for `adsb`, `ais`, `cat021`, `cat023`, `cat034`, `cat048`,
`cat062`, `gmti` and `stanag4609`; 6 and 17 parsed twins value-complete for `tak` and
`stanag4676`; zero FAIL. Every adapter now computes `maturity_eligible: L5` and every adapter
declares less — L3 for the three ingest-only adapters, L4 for the eleven emitters — and
`tests/test_cdm_manifests.py` derives the rung from a suite run and requires declared ≤ eligible.
A third word, an exemption under `bytes`, or a declaration on an ingest-only adapter is a
`TypeError` at import.

## Evidence that reproduces elsewhere

A 2.1.2 evidence record carried the runner's absolute fixture directory and its `source_commit`
with a `-dirty` suffix, because the gate job wrote the conformance artefact into the checkout root
before the evidence step ran there, so `synapse evidence verify` from any other checkout reported
DIFFERS on three fields none of which says anything about the tree. A record now carries the
packaged directory as `<packaged>/<directory>`, records the interpreter and platform as
environment and never compares them, and `publish.yml` refuses a record whose `source_commit` is
not the bare `HEAD`. The proof is in the suite: fourteen records generated from one tree and
verified from a copy of the package at a different absolute path, every one REPRODUCED. Every
manifest declares `evidence.available: true`, because the 2.1.2 records are attached to the
`v2.1.2` Release and retrievable by anybody; the field says the records exist and where, and
nothing about the wheel's contents, which still carry no record. Thirty-nine `PROVENANCE.json`
records — one in every fixture directory a tracked test reads — say where the fixture data came
from.

## CI, and the release pipeline

* `ci.yml` runs the suite on **3.11, 3.12, 3.13 and 3.14** — every interpreter the classifiers
  declare, where it ran one — and gains a `lint` job and a `wheel` job on every push. The lint
  stage is pinned once, `ruff==0.16.6` in a `[lint]` extra, and selects `E9,F821`: the previous set
  was exactly one rule and had never caught the undefined name its comments promised. The docs job
  runs the site's own gates rather than a bare build.
* `publish.yml`'s `release` job reads the CodeQL and pip-audit verdicts off the gate rather than
  restating them, the pip-audit verdict is read off the stream pip-audit writes it to, and
  `rc-build.yml` takes its SBOMs over the clean install as `publish.yml` does.
* `gates/witness_verify.py` re-derives the four non-PyPI assets and the Release's `SHA256SUMS`
  offline with `--assets`, and with `--download` re-hashes the bytes the index and the Release
  serve and the wheel's attestation bundle; at 2.1.2 it checked those digests for shape. The
  `witness` job carries `actions: read` and `deployments: read`, takes the approval instant from
  the `pypi` deployment's own status history rather than from a key the approvals endpoint never
  sent, fetches the attestation store by the wheel's digest, and hands the verifier the assets
  and a token. `releases/witness/2.1.2.json`, the first record in that directory, was committed
  from the bytes the Release serves; the job that produced its predecessor failed at its own
  verification step, and this release's tag push is the first execution of the repaired job.

## Security, dependencies and the supply chain

* `SECURITY.md`: the reporting path, and a parser-safety policy with declared limits on all
  fourteen adapters and a declared depth bound on six.
* Secret scanning on the platform, `.gitleaks.toml` in the tree, and a CI job over the full
  history reachable from every push.
* `pip-audit --strict` twice — over the environment and over the wheel's frozen closure — with
  exactly one distribution excluded by name, `synapse-cdm` itself, and every third-party line
  under `--strict`. Plus an npm audit at high over the documentation tree: `image-size` 2.0.4 is
  pinned through `docs/package.json`'s `overrides`, the two advisory exceptions that named that
  fix as their removal trigger are deleted, `security/exceptions/` holds no exception file, and
  `npm audit --json` reads high 0, critical 0.
* CodeQL, and a gate that refuses a blocking alert, selecting the analysis by commit.
* An SBOM in both SPDX and CycloneDX, built by the release pipeline over the clean-install
  environment, plus a second tool's cross-check.
* Build provenance: Sigstore attestation over the built artefacts, verified in the same run that
  produced them and again, by digest, by the witness verifier.

## What else moved

* **The public tree names no private document by path.** Every citation of the round apparatus —
  a fixture spec record, a shipped `malformed/README.md`, a constant's source, a comment — either
  names the symbol it means or says the document is private, and `SOIF` is expanded once in the
  root `README.md` and on two pages of the documentation site.
* **One serialiser, written once.** `canonical.py` holds §6.2's serialisation and the seven
  sites that restated it call it; the fixture predicate is `harness.select_fixtures` and the two
  modules that restated it call that; the shipped-adapter test is `adapter.is_shipped`. No
  golden, manifest or evidence digest moves for it, because the bytes cannot differ.
* **The unused imports are gone** — twenty-seven against the 2.1.2 tree, eight of them in the
  distribution — and `ruff --select F401` reads 0.
* **The package `README.md`** lists every module the package has carried since SC-OES and SOIF
  Part 1, says the exporter writes eight JSON Schemas, and describes `geo.py` with its multi-
  forms; the package's own docstring names the fourteenth adapter it enumerated as thirteen.
* **No runtime dependency changed.** `pydantic` and `jsonschema`, as before; `rdflib` is a test
  extra; `ruff` is a lint extra and nothing under `synapse_cdm/` imports it.
* **No adapter was added or removed**, and no adapter's translation was changed to make a
  conformance verdict come out differently: check E moved from SKIP to PASS because the harness
  learned to compare, not because an adapter learned to emit.

## Fourteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
The table is the live registry, and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree — a table missing an adapter tells a reader the roster is smaller than it is.
**The roster did not move this arc**, which is derived here rather than carried over: `discover()`
and `roster()` each return fourteen, the same fourteen names in the same two directions as 2.1.2,
and the totals below were summed from the harness on this tree.

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

**538 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas —
the same 538 as 2.1.2, and the `roundtrip` column that read SKIP for all of them now reads PASS
for the eleven emitters and a declared SKIP for the three that emit nothing. `gates/wheel_install.py`
reports **1076** over the same roster, which is these 538 run in each of two schema modes, from a
wheel installed into a venv with nothing of this repository on its path.

## Published by CI over OIDC, as 1.1.0 through 2.1.2 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 19 records the 2.1.2 upload and the two tags before it that released
nothing.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** together with the
workflow run that produced them. The GitHub Release additionally carries both SBOMs, the evidence
set, the conformance report, the witness record and these notes — so the evidence a claim rests
on is retrievable with the release rather than only as a workflow artefact with a retention
window.

They are deliberately not committed here, for the reason this file has given since 1.1.0. A digest
is a property of one build rather than of the tree: two builds of one tree have identical payloads
but differ in their generated metadata, so a digest written here before the tag would not be the
digest of the file PyPI serves, and one written after the tag could never be inside the tree the tag
names. **1.3.0 measured that the hard way** — a local build and the published wheel came out at the
same byte count and were different files — so the digests to compare a download against are the
workflow's, never a rebuild's. Everything else in this document is readable off that tree, which is
what condition 4 of the release procedure asks for.

```bash
pip install synapse-cdm==2.2.0
python -m synapse_cdm.harness --list-adapters
```
