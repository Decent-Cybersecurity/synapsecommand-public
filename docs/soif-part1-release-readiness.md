# SOIF Part 1 release-readiness report — 2026-09-08

Written by round P8 (attempt 2) of the SOIF Part 1 campaign (spec §56–§58). Every figure below is
a reading taken on the commit named in section 18, with the command that produced it. Nothing is
carried from a brief: where a brief's figure and the tree's disagreed, the tree's is what is
written and the disagreement is named.

This report **replaces** the one round P8 wrote on 2026-09-08 at commit `4ee2788`. That report
carried two blockers — a conformance JSON that was not byte-stable, and eleven Dependabot alerts
that no CI job audited. Round PB repaired both, and this qualification was run again from scratch
against PB's tree. Both of the earlier blockers are **closed**, with the readings in sections 7,
9 and 10. Two new ones are open, and both are in one stage of the release pipeline: section 20.

**Release status: NO RELEASE.** `PACKAGE_VERSION` is therefore unmoved at `2.0.0`: the version
moves in the round that can say "ready", and this round cannot.

---

## 1. Baseline

| what | reading | command |
|---|---|---|
| last release | `2.0.0`, tag `v2.0.0` | `git tag --sort=-v:refname \| head -1` |
| `main` | `a9ea68c1fdb260b91142330d3d06b5b6552e8476`, unmoved since the 2.0.0 witness round | `git rev-parse origin/main` |
| branch under review | `soif/1.0`, thirteen commits ahead of `v2.0.0`, twelve ahead of `origin/main` | `git rev-list --count v2.0.0..HEAD` → 13; `… origin/main..HEAD` → 12 |
| arc size | **797 files changed, 51414 insertions(+), 3913 deletions(-)** | `git diff --shortstat v2.0.0..HEAD` |
| tags | 12 local, 24 remote lines; no tag names any Part 1 commit | `git tag \| wc -l`; `git ls-remote --tags origin \| wc -l` |

The arc by top-level directory (`git diff --numstat v2.0.0..HEAD`, grouped):

| directory | files | + | − |
|---|---|---|---|
| `packages/` | 673 | 32165 | 3627 |
| `tests/` | 36 | 6008 | 50 |
| `schemas/` | 8 | 3915 | 39 |
| `docs/` | 26 | 3384 | 79 |
| `.github/` | 7 | 1757 | 38 |
| root files | 9 | 1650 | 14 |
| `manifests/` | 14 | 1089 | 0 |
| `gates/` | 3 | 649 | 2 |
| `examples/` | 14 | 442 | 64 |
| `security/` | 5 | 268 | 0 |
| `releases/` | 1 | 71 | 0 |
| `spec/` | 1 | 16 | 0 |

The thirteen commits, oldest first: `a9ea68c` (the 2.0.0 witness commit, which is on `main`),
`5209c1e` P0, `f28d58e` PA, `441a509` P1, `606e844` P2, `6351fe1` P3, `9069fa9` P4, `e37cf20` P5,
`c52e496` P6, `e540de8` PC, `4ee2788` P7, `a9c0660` P8 (the first qualification), `b9ccb2c` PB.

## 2. Resulting architecture

`ARCHITECTURE.md` (560 lines, round P0) is the frozen contract, in nine sections: Adapter API v2
(§1), direction model (§2), capability and metadata model (§3), core rules 1–6 (§4), residual-field
policy (§5), deterministic behaviour (§6), CI layout (§7), conformance namespaces (§8), and §9's
statement of what the freeze did *not* decide. `VERSIONING.md` (255 lines, P0, §5.1 added by P7)
holds the version model; `INTEROPERABILITY.md` (198 lines, P0) holds the contract a third party
builds against.

One known staleness, carried and not repaired: `ARCHITECTURE.md` §7 says
"`.github/workflows/` holds exactly one workflow, `publish.yml`". There are five
(`ci.yml`, `codeql.yml`, `dependency-review.yml`, `publish.yml`, `rc-build.yml`). It has been false
since P1 and is item 15's, not this round's — see section 15.

## 3. Adapter API

`packages/cdm/synapse_cdm/adapter.py` (round P1 over P0's design). v2 is ADDITIVE over the v1
surface: `metadata`, `detect()`, `validate_source()`, `capabilities()` are added; `decode()`/
`encode()` are the v2 names of `to_cdm`/`from_cdm` and **neither v1 name is removed** in Part 1.
The contract stays enforced at class-definition time in `__init_subclass__`. `ADAPTER_API_VERSION`
is `2.0.0` (`version.py`).

Direction model: the fourteen declare `bidirectional` ×11 and `ingest` ×3
(`manifests/*.json`, `adapter.direction`). MODEL, TRANSPORT and COMPOSITE exist in the model and
are declared by none of the fourteen.

## 4. CDM changes

`SCHEMA_VERSION` `2.0.0` → **`2.1.0`** (round P3), a MINOR: every added path is optional or is
reached only through an optional one, so a 2.0.0 reader keeps working and 2.0.0 data keeps
validating. `PACKAGE_VERSION` did **not** follow — see section 19.

Added, in `geo.py` and `models.py`: `MultiPoint`/`MultiLineString`/`MultiPolygon` (the geometry
union widened to six), `VerticalPosition`, `VerticalExtent`, `BoundingBox` and the CRS policy;
`SourceHash`, `Period`, `TemporalValidity`, `Waypoint`, `RouteLeg`, `Route`, `Area`, `Quality`,
`OperationalStatus`, `Residual`; seven optional `SourceRef` fields; `Position.vertical`;
`CDMBase.quality`/`status`/`residual`; `PlanObject.validity`/`route`/`area`;
`lossless.residual_block()`; `enums.VerticalUnit` and `VerticalReference`.

Published schemas: `python -m synapse_cdm.schemas --check --out schemas` (from the repository root)
→ `CURRENT: schemas vs models at 2.1.0`. `git diff --shortstat v2.0.0..HEAD -- schemas/` → **8
files changed, 3915 insertions(+), 39 deletions(-)**.

Backwards compatibility, derived and not asserted — see section 14 for the goldens.

## 5. Manifests

`manifest.py` (595 lines) and `manifests.py` (round P1, `MANIFEST_SCHEMA_VERSION` `1.0.0` → `1.1.0`
in P4 → **`1.2.0`** now), the schema at `schemas/manifests/adapter-manifest.schema.json`, and
fourteen generated records under `manifests/`.

`python -m synapse_cdm.manifests --check --out manifests` →
`CURRENT: manifests vs 14 shipped adapters at manifest schema 1.2.0`.
`pytest -q tests/test_cdm_manifests.py` → **42 passed**.

Declared across the fourteen: `claim_status` `VERIFIED` ×14; `license_class`
`PUBLIC_GOVERNMENT` ×10, `LICENSED` ×3, `OPEN` ×1; `residual.placement` `legacy` ×14;
`evidence.available` `false` ×14; **four null `format.version`** (adsb, ais, pntmap, tak);
73 declared limitations in total.

## 6. Maturity model

Seven levels L0–L6 and six claim statuses (spec §14–§15), computed in `manifest.py` and
`suite.py` from the checks that actually ran. Declared: **L4 ×11, L3 ×3**.

Two facts about the ceiling, both readings rather than omissions. The harness's `roundtrip`
column is SKIP for **all fourteen** — `harness.py` cannot compare non-JSON egress bytes and says
so — so an L4 declaration rests on the adapter's own byte-exact round-trip test in `tests/`, named
in each manifest's `maturity.basis`. And L5 is declared by none: ARCHITECTURE.md §3.6 computes it
from the full applicable conformance set, and the eligibility rule that a declared inapplicability
does not block a rung while an undeclared SKIP does produces the inversion P2 recorded — the three
ingest-only ones compute L5 while the eleven bidirectional ones compute L3. Not resolved here;
item 15.

## 7. Conformance

`suite.py` (1140 lines, rounds P2 and PB): fifteen checks A–O, SKIP semantics, `--format json`,
`--require`, and the `synapse` console script.

`synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json` → **exit 0,
fourteen CONFORMANT, no FAIL on any check for any adapter**. That is the required set CI and the
release pipeline use (`ci.yml:143`, `publish.yml:304`, `publish.yml:466`, `rc-build.yml:94`).

The full verdict table, from one `--all` sweep:

| check | PASS | SKIP | FAIL |
|---|---|---|---|
| A translate | 14 | 0 | 0 |
| B schema | 14 | 0 | 0 |
| C provenance | 14 | 0 | 0 |
| D lossless | 14 | 0 | 0 |
| E roundtrip | 0 | **14** | 0 |
| F golden | 14 | 0 | 0 |
| G deterministic | 14 | 0 | 0 |
| H malformed-input | 14 | 0 | 0 |
| I unknown-field-preservation | 7 | **7** | 0 |
| J temporal | 14 | 0 | 0 |
| K identity | 14 | 0 | 0 |
| L version | 14 | 0 | 0 |
| M streaming | 0 | **14** | 0 |
| N parser robustness | 12 | **2** | 0 |
| O resource limits | 14 | 0 | 0 |

Requiring `E` or `N` makes exit 0 unreachable, by §19's own rule and not by a defect: with
`--require A,B,C,D,E,F,G,H,J,K,L,N,O` the sweep exits **1** while still reporting fourteen
CONFORMANT and zero FAIL. E is SKIP everywhere because `from_cdm` returns non-JSON bytes that the
check cannot compare structurally; N is SKIP for `legion` and `pntmap`, whose fixtures are parsed
dicts with nothing to truncate, and both declare the inapplicability.

**The sweep's JSON is byte-stable, and that closes the first blocker of the previous report.**
Round PB removed the wall-clock `seconds` field from check H's refusal records and replaced it
with `over_time_bound`, a boolean. Read here: the sweep's own JSON carries no key or substring
matching `seconds` anywhere; `pytest -q tests/test_cdm_suite.py tests/test_cdm_evidence.py`
passes; `ci.yml` run 34257749831 and both `publish.yml` gate stages on this commit are green on
the two tests that were red before (section 13).

## 8. Evidence

`evidence.py` (767 lines, rounds P4 and PB), `EVIDENCE_SCHEMA_VERSION` `1.0.0`, with §34's six
loss categories in `lossless.classify` and §33's `PROVENANCE.json` per fixture directory.

* `python -m synapse_cdm.evidence provenance` → `COMPLETE: 39 fixture directories under §33`.
* `synapse evidence generate --all`, twice into two directories → 14 records each; the masked
  comparison between the two generations is **empty for all fourteen**.
* `synapse evidence verify` over all fourteen records → **14 REPRODUCED, exit 0**.
* `evidence.MASKED` is now exactly `("generated_at", "test_run.duration_s")` — **two** entries.
  The third, the refusal record's wall clock, was not masked but removed at the source by PB, so
  the artefact no longer contains an unreproducible value to mask.
* Loss report, summed over the fourteen: `DROPPED` **0**, `UNSUPPORTED` **0**, `DERIVED` **0**,
  `NORMALIZED` 38, `PRESERVED` 187, `RESIDUAL` 2877; 274 fixtures classified and 264 skipped as
  non-JSON payloads.
* Badges derive from a record and from nothing else: with no record on disk,
  `synapse evidence badges` refuses and says why.

## 9. Security

`SECURITY.md` (162 lines, round P5): supported versions, reporting, scope, "Telemetry: none",
the controls table, and handling. `.gitleaks.toml` and a `secrets` CI job carry secret scanning;
platform secret scanning and push protection were enabled in P5; the parser-safety policy's
bounds are declared per adapter in each manifest's `capabilities.limits`, with
`absent_because` where no bound is enforced.

* `gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .` in a fresh clone →
  **12 commits scanned, no leaks found**.
* `gates/codeql_gate.py` over both SARIFs of the CodeQL run on this commit (`codeql.yml` run
  34257749765, success; analyses 1742799507 python and 1742798279 javascript-typescript) →
  **0 results, 0 blocking, 0 excepted, 0 unclassified, exit 0**.
* `gh api …/code-scanning/alerts?ref=refs/heads/soif/1.0` → **four alerts, all `fixed`, zero
  open** — the four HIGH findings of CodeQL's first run, closed at their sites by round PC.
* `security/exceptions/` → two exception files (`GHSA-5p2g-fcmc-qvqq.json`,
  `GHSA-w3rx-r6r6-pgpr.json`), `README.md` and `schema.json`. Both files validate against the
  live schema and carry all eleven required keys, including PB's `mitigation` and
  `upstream_status`; both expire on a date the gate reads, and an expired one is dropped by the
  gate rather than honoured.
* No-network proof: `pytest -k "no_network or network"` → **66 passed**.

## 10. Dependencies

`.github/dependabot.yml` (pip, github-actions, npm; weekly; minor+patch grouped),
`dependency-review.yml` at `fail-on-severity: high`, a `supply-chain` CI job running
`pip-audit --strict` twice — over the installed environment and over the wheel's own frozen
closure in a clean venv (round P6) — and, since PB, a **`docs-audit`** job that runs
`npm audit` over `docs/` at `--audit-level=high` with its allowlist derived from
`security/exceptions/` and nothing typed into the workflow.

* `pip-audit --strict` in a fresh clone, with the derived ignores → **No known vulnerabilities
  found**. The derived allowlist is
  `--ignore-vuln GHSA-5p2g-fcmc-qvqq --ignore-vuln GHSA-w3rx-r6r6-pgpr`, printed by the gate
  before it is used.
* `npm audit --prefix docs --json` on this commit → **three advisories**:
  `GHSA-5p2g-fcmc-qvqq` and `GHSA-w3rx-r6r6-pgpr` (both `image-size`, high, both excepted with a
  dated expiry and no upstream fix — `npm view image-size version` → 2.0.2) and
  `GHSA-w5hq-g745-h8pq` (`uuid`, **medium**, first patched in 11.1.1 against 8.3.2 installed).
  The enforcing step's verdict on this commit, from `ci.yml` run 34257749831's own log:
  `advisories: 3; excepted and present: ['GHSA-5p2g-fcmc-qvqq', 'GHSA-w3rx-r6r6-pgpr'];
  excepted and absent: []` and `OK — no unexcepted high or critical npm advisory in docs/`.
* PB's three `overrides` — `fast-uri ^3.1.7`, `qs ^6.16.0`, `serialize-javascript ^7.1.1` —
  are what took the branch's own advisory set from eleven to three.

**The eleven-alert reading, and why it is not a blocker.** `gh api …/dependabot/alerts?state=open`
→ **11 open: 7 high, 4 medium**, every one `npm` in `docs/package-lock.json`. That count did not
change when this branch was pushed, and the reason is scope rather than staleness: Dependabot
alerts are computed against the **default branch**, and `main` still carries the pre-PB lock. Read
directly: `git show origin/main:docs/package-lock.json` has `fast-uri 3.1.5`, `qs 6.15.3`,
`serialize-javascript 6.0.2`, while this commit has `3.1.7`, `6.16.0`, `7.1.1`. Eight of the nine
non-excepted alerts name exactly those three packages and are already fixed on this branch; the
ninth is the `uuid` medium above, which is below the `high` floor the gate enforces. So the count
falls when `main` fast-forwards to this branch — which is the first step of the release itself
(`VERSIONING.md` §5.1). A blocker that only the release can clear would make the release
impossible; this is recorded as a post-release verification for the witness round instead, and as
limitation 16.

**Both halves of the previous report's blocker 2 are therefore closed**: the count on this branch
is three rather than eleven, and CI now fails a push that adds an unexcepted high or critical npm
advisory — which is the audit that did not exist before PB.

## 11. SBOM

The pipeline produces both SBOM formats in its `build` job (`publish.yml`): SPDX-JSON and
CycloneDX-JSON, from one `anchore/sbom-action` (syft, pinned at v1.51.1) run **over the gated
wheel** rather than over the source tree or the environment. §46 asks for both formats "where
supported by tooling" and makes the SBOM a release artefact.

**The pipeline's SBOM stage FAILED on this commit, and that is blocker 1.** The
`workflow_dispatch` run of `publish.yml` on `soif/1.0` (run 34257867522) passed `gate` and then
failed in `build` at *SBOM — SPDX, from syft over the gated wheel*. Section 20 carries the
mechanism, the proof that a tag fares no better, and what it leaves unproven.

What *was* taken locally, named as what it is:

* syft **v1.51.1**, the version the workflow pins, over the wheel the gate exports
  (`synapse_cdm-2.0.0-py3-none-any.whl`, built in the fresh clone): both formats write —
  **SPDX-2.3** and **CycloneDX 1.7**. So the tooling supports both and §46's format requirement is
  reachable.
* And both are empty of contents: the SPDX document's `packages` list is **one** entry, the wheel's
  own filename and SHA-256, and the CycloneDX document's `components` list is **zero**. Scanning
  the same wheel unpacked (`syft scan dir:<extracted>`) instead yields `synapse-cdm 2.0.0` as a
  package. That is blocker 2.
* `gh api …/dependency-graph/sbom` → **SPDX-2.3, 1235 packages**, creators `protobom` /
  `GitHub.com-Dependency-Graph` / `dependabot`. GitHub's producer over the repository, not syft
  over the wheel, and not an artefact the release publishes.
* `cyclonedx-py environment` over the fresh clone's venv → **CycloneDX 1.6, 73 components**. A
  second producer, over the environment rather than over the wheel.

## 12. Build provenance

`publish.yml`'s `attest` job (round P7) takes Sigstore build provenance over the wheel, the sdist,
both SBOM files and the evidence archive, then runs `gh attestation verify` against it.
`id-token: write` and `attestations: write` are scoped to that job alone and to no other.

**Unproven on this commit, and the reason is blocker 1**: `attest` `needs: build`, and `build`
failed. Everything downstream of the SBOM step — the `SHA256SUMS` hash step, condition 4's
derivations, the artefact hand-off, and therefore `attest`, `publish`, `release` and `witness` —
was `skipped`. `rc-build.yml` (round P6), the other workflow that composes the same artefact set,
cannot be dispatched at all until it is on the default branch: its first run is necessarily
post-release, which `SECURITY.md` records beside the sentence that assumed otherwise.

What the run **did** prove, and it is most of the pipeline: `gate` green end to end (lint, suite,
conformance, security gates, the annotated-tag check), and in `build` — the gate with its mutation
check exporting the one build, `twine check --strict` PASSED on both artefacts, a clean install of
that wheel into a venv of its own, and the package test running the conformance sweep from the
installed wheel with no repository near it. Eight of the `build` job's fifteen steps succeeded;
the ninth is where it stopped.

## 13. Release procedure

`publish.yml`, 876 lines, **six jobs, one per §50 stage boundary**, each `needs:` the one before,
so the order is enforced by the dependency graph: `gate` → `build` → `attest` → `publish` →
`release` → `witness`. Conditions 1–4 of `MIGRATIONS.md`'s "What a release requires" are the same
text in a different job (1, 3 and the annotated-tag check in `gate`; 2 and 4 in `build`, because
both read `dist/`), and `tests/test_cdm_trusted_publishing.py` holds them to that. Every `uses:`
is a full commit SHA with a version comment. `publish`, `release` and `witness` are each guarded
by `if: startsWith(github.ref, 'refs/tags/v')`, which is why a branch dispatch cannot publish.

CI-side readings on this commit, all taken after the branch was pushed:

| workflow | run | conclusion | note |
|---|---|---|---|
| `ci.yml` | 34257749831 | **success** | six jobs green: suite/gates/manifests, conformance, evidence, gitleaks, supply-chain, docs-audit |
| `codeql.yml` | 34257749765 | **success** | two languages, 0 results each |
| `publish.yml` (dispatch) | 34257867522 | **failure** | `gate` success; `build` failed at the SPDX SBOM step; four jobs skipped |

The `gate` job's green is the first time it has been green on this branch: the two runs the
previous report recorded (34235403062, 34236081918) both failed Condition 1 on the byte-stability
test that PB repaired.

* Notes: `synapse release-notes` (`release_notes.py`, 387 lines) renders nine of §52's ten fields
  from the tree and **quotes** the tenth, *major changes*, from `RELEASE_NOTES.md` — refusing when
  that file's heading names another version. Condition 4 stays a person's.
* Witness: `.github/scripts/build_witness.py` builds §53's record in the `witness` job **after**
  the upload, from PyPI's JSON API and the Release API; `gates/witness_verify.py` re-derives every
  digest in it and exits non-zero on any disagreement. `releases/witness/` holds `README.md` and
  no record: a workflow does not commit, so the first record lands in the witness round after the
  release.
* Main advancement: `VERSIONING.md` §5.1 and `MIGRATIONS.md`'s pipeline section carry the same
  commands — `git merge --ff-only soif/1.0`, then the annotated tag on `main`'s new tip. A refusal
  is a stop, never a merge commit and never a rebase.

## 14. Existing-adapter regressions

**All fourteen public adapters continue to work, and the CDM change is additive in the goldens as
well as in the schemas.** Derived here by comparing every golden at `v2.0.0` against the same file
at this commit, leaf by leaf (`git show v2.0.0:<path>` vs `git show HEAD:<path>`, JSON paths
flattened), and not carried from the previous report:

| reading | value |
|---|---|
| goldens at `v2.0.0` / at HEAD | 538 / 538 |
| goldens added / removed | 0 / 0 |
| objects compared | 1308 |
| JSON paths **removed** | **0** |
| JSON values **moved** | **1** — `schema_version`, on all 1308 objects |
| JSON paths added | 11: `source.source_hash`, `source.format_name`, `source.format_version`, `source.observed_at`, `source.original_id`, `source.record_index`, `status`, `quality`, `residual` (1308 each); `position.vertical` (259) and `samples.position.vertical` (89) |

`git diff --shortstat a9c0660..HEAD -- '**/golden/**'` → empty: no golden moved in PB either.

Fixture verdicts: `gates/wheel_install.py` reports **1076** over the roster, the 538 run in each of
two schema modes, 0 failed; the conformance sweep reports fourteen CONFORMANT with zero FAIL
(section 7).

## 15. Known limitations

Everything the campaign deferred, each with where it is recorded. None of these is a blocker;
blockers are section 20.

1. **47 ruff `F` findings, and no mypy configuration** (round P7). 12 are in `packages/cdm` and
   35 more in `gates/` and `tests/`. The workflow's own command,
   `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests`, passes: the lint
   stage selects `E9` alone, because `E9` finds nothing while `F` finds 47 and fixing them means
   editing shipped modules. Widening the rule set is a round of its own.
2. **`ARCHITECTURE.md` §7's one-workflow sentence is false** (five workflows exist). §7's job
   table is otherwise satisfied.
3. **`evidence.available` is `false` on all fourteen** and `artifact_hashes` is empty. Both flip
   only when release evidence is generated from a release commit, attached to a Release and
   retrievable by a third party — the release round's, and a test asserts the declared set is
   exactly `{false}` today so the flip cannot happen silently.
4. **Four null `format.version`** (adsb, ais, pntmap, tak). Readings, not omissions: no document
   in the tree names the edition each was written against, and each manifest carries the
   limitation.
5. **L5 is declared by no adapter, and the eligibility inversion of section 6 stands.** Raising
   the eleven bidirectional ones would mean counting their own round-trip tests as a declared
   inapplicability of the harness's `E`, which is a rule change and not a reading.
6. **The harness's `roundtrip` check is SKIP for all fourteen** — a structural comparison cannot
   compare non-JSON egress bytes. Every L4 claim therefore rests on a per-adapter byte-exact test
   named in the manifest.
7. **Checks E and M are SKIP for all fourteen; I for seven; N for two.** Correct SKIP semantics
   (spec §17: a non-applicable check is never PASS), and the reason each is inapplicable is in the
   check's own `reason` field. `publish.yml`'s comment at the step that runs the sweep names E, I
   and M as the excluded set and omits N, which is excluded too — a comment one name short of the
   list beside it.
8. **The determinism/hash collision, still open.** `ARCHITECTURE.md` §4.4 says the determinism
   check hashes and §6.2 fixes sha256; `tests/test_cdm_boundary.py:74` forbids `hashlib` under
   `synapse_cdm/`. Check G compares canonical serialisations instead, and `evidence.py` is the one
   name the boundary gate allows, narrowed to it by name with two tests policing the allowance.
9. **The fourteen keep legacy residual parking** (`residual.placement: legacy` ×14), by ruling: no
   golden was rewritten for placement.
10. **`defusedxml` is not a dependency**; an entity bomb is refused by libexpat and not by this
    package, which `SECURITY.md` states.
11. **`rc-build.yml` has never run**, and cannot until it is on the default branch.
12. **The `secrets` CI job has never executed on a push to `main`**, and
    `gitleaks/gitleaks-action` stays declined because it requires a paid licence for an
    organisation repository — the CI job runs the binary directly instead.
13. **`security-severity` on `actions` as a third CodeQL language** is available and not enabled;
    two languages are analysed.
14. **This report is not a page of the documentation site.** §57 fixes its path at `docs/`, and
    the site's content root is `docs/docs/`; the sidebar is autogenerated from that directory by
    each page's `sidebar_position`, so no `docs/*.md` report — including
    `docs/sc-oes-release-readiness-report.md`, the precedent — appears in it, and none is linked
    from any page under `docs/docs/`.
15. **A local apparatus directory reds one suite test in the working tree only.** It is excluded
    at `.git/info/exclude`, so it is invisible to a clone and to every commit, and the tests that
    see it walk the filesystem rather than the git index. A fresh clone of this commit is 0 failed.
16. **The `uuid` medium advisory (`GHSA-w5hq-g745-h8pq`) has no taken fix**, and the eleven
    default-branch Dependabot alerts of section 10 stay open until `main` fast-forwards. The first
    is below the floor the `docs-audit` gate enforces; the second is a property of `main`'s tree
    and is verified after the release rather than before it.

## 16. Intentionally deferred work

The spec's own §2 non-goals, and what Part 1 deliberately left to Part 2:

* **No new adapter portfolio.** Spec §55: 2.1.0 "does NOT claim the new adapter portfolio
  exists". **Fourteen adapters**, the same fourteen as 2.0.0, is what this arc ships — no adapter
  was added, removed, or had its translation changed to move a conformance verdict.
* **Part 2's formats** — GeoJSON, KML/KMZ, GeoPackage, AIXM 5.1 and the rest of §59's list — are
  not begun.
* **CRS names for projected sources**, **curved geometry** (arcs and circles by centre/radius),
  **altitude bands on a waypoint**, and **`GeometryCollection`**: named in P3's record with the
  format that will want each, and deliberately absent. An approximation would be data the source
  did not send.
* **`Timestamp` documentation-only change**: it still accepts the epoch instant.
* **No migration tooling.** Migration in this repository is documented rather than executable.
* **No certification programme.** A conformance verdict is evidence, not a certificate.

## 17. Test commands

Every command run for this report, in the order the sections use them. `<clone>` is a fresh
`git clone --no-local` of this commit, checked out detached at it, with its own venv inside it and
the clone's own distribution installed editable by absolute path.

```bash
# 0  the clone
git clone --no-local <repo> clone && cd clone && git checkout b9ccb2c
python -m venv .venv && .venv/bin/pip install -e \
  "$PWD/packages/cdm[test]"
# 1  unit + adapter tests
python -m pytest -q                                  # in tree, and in <clone>
# 2  conformance
synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json
synapse conformance run --all --require A,B,C,D,E,F,G,H,J,K,L,N,O --format json
# 3  packaging
cd packages/cdm && python -m build && python -m twine check --strict dist/*
# 4  clean install
python gates/wheel_install.py
# 5  schema drift  (from the repository ROOT)
python -m synapse_cdm.schemas --check --out schemas
# 6  manifest validation
python -m synapse_cdm.manifests --check --out manifests
python -m pytest -q tests/test_cdm_manifests.py
# 7  evidence
python -m synapse_cdm.evidence provenance
synapse evidence generate --all --out /tmp/ev1 && synapse evidence generate --all --out /tmp/ev2
synapse evidence verify /tmp/ev1/*/*/evidence.json
synapse evidence badges                              # from a directory with no record
# 8  security
gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .
gh api -H "Accept: application/sarif+json" repos/<owner>/<repo>/code-scanning/analyses/<id>
python gates/codeql_gate.py sarif/*.sarif
python -m pytest -q -k "no_network or network"
# 9  dependencies
python gates/codeql_gate.py --emit-pip-audit-ignores
pip-audit --strict
npm audit --prefix docs --json
gh api repos/<owner>/<repo>/dependabot/alerts?state=open --paginate
# 10 SBOM
syft scan file:dist/synapse_cdm-2.0.0-py3-none-any.whl -o spdx-json
syft scan file:dist/synapse_cdm-2.0.0-py3-none-any.whl -o cyclonedx-json
syft scan dir:<the same wheel, unpacked> -o spdx-json
gh api repos/<owner>/<repo>/dependency-graph/sbom
cyclonedx-py environment .venv
# 11 documentation
cd docs && npm ci && npm run build     # from the clean tree, F8.3's scope
# 12 the pipeline itself
gh workflow run publish.yml --ref soif/1.0 && gh run view <run> --log-failed
```

Documentation check (§56's last item, F8.3 = build only): `npm ci` then `npm run build` in the
fresh clone → **`[SUCCESS] Generated static files in "build"`, exit 0**, and the same in the
working tree.

## 18. Commit

This report describes **`b9ccb2c3d2f204081fda5319dbc8af5ce6883a30`** — round PB's commit, the tip
of `soif/1.0` and, since 2026-09-08T17:32:44Z, its remote tip. `origin/main` is unmoved at
`a9ea68c1fdb260b91142330d3d06b5b6552e8476`; `git merge-base HEAD origin/main` is that same
commit; no tag names any commit on this branch (12 local, 24 remote tag lines, unmoved).

The commit that carries **this file** is the round-P8 commit immediately after it, whose subject
begins `SOIF P8:`. Its hash is deliberately not written here: a hash cannot name the commit that
carries it, and a number written before the commit exists is a number nobody re-derived.

## 19. Release status

**NO RELEASE.** Spec §57: "If blockers are non-empty: NO RELEASE."

* `PACKAGE_VERSION` stays **`2.0.0`**. The bump gate would allow the move —
  `gates/bump_derivation.py --json` reads `derived_kind` **MINOR**, `pending` floor **2.1.0**,
  `unruled` **`[]`** over 697 signals and ten ruled units — so the version is held back by this
  report's verdict and not by the derivation. The five other axes are unmoved: `SCHEMA_VERSION`
  2.1.0, `SC_OES_VERSION` 0.1.0, `ADAPTER_API_VERSION` 2.0.0, `MANIFEST_SCHEMA_VERSION` 1.2.0,
  `EVIDENCE_SCHEMA_VERSION` 1.0.0.
* `MIGRATIONS.md`'s arc stays under `### Unreleased`, with the round records under it. Nothing in
  it is released.
* `RELEASE_NOTES.md` still opens `# synapse-cdm 2.0.0` and still carries the dated pending
  paragraph saying so.
* The release round does not run. Beyond the two blockers it also needs what no round can supply:
  M's authorisation of the number, and a fast-forward of `main` to this branch.

**What both blockers are is one step of one job**, and neither is this round's to repair: default 2
of this round's brief says a red §56 item is a blocker and never a repair.

The two blockers the previous report carried are **closed**, and closed by reading rather than by
assertion: the conformance JSON no longer contains a wall-clock value and the tests that compare it
are green in CI (section 7), and the npm dependency tree is audited on every push by a job that
derives its allowlist from `security/exceptions/` and is green on this commit with three advisories
of which two are excepted (section 10).

## 20. Blockers

```text
1. sbom-stage-fails-on-a-ref-derived-wheel-path
2. sbom-over-a-wheel-file-enumerates-no-components
```

### Blocker 1 — the SBOM steps build the wheel's filename out of `github.ref_name`, so the path never exists

**The reading.** The `workflow_dispatch` run of `publish.yml` on `soif/1.0`, run
**34257867522**, on this commit:

| job | conclusion | where |
|---|---|---|
| `gate` — lint, suite, conformance, security | **success** | all conditions green |
| `build` — build, install clean, SBOM and hash | **failure** | step 9 of 15, *SBOM — SPDX, from syft over the gated wheel* |
| `attest`, `publish`, `release`, `witness` | `skipped` | each `needs:` the one before |

The failing step's own log:

```text
[command] syft scan file:dist/synapse_cdm-soif/1.0-py3-none-any.whl -o spdx-json
[0000] ERROR could not determine source: no source providers were able to resolve the
       input "dist/synapse_cdm-soif/1.0-py3-none-any.whl"
```

**The mechanism, and it is one expression.** `publish.yml:476` and `:485` both read

```yaml
file: dist/synapse_cdm-${{ github.ref_name }}-py3-none-any.whl
```

and `github.ref_name` on this dispatch is the branch name, `soif/1.0`. Every other version-bearing
expression in the file derives the number from the tree or strips the tag's prefix —
`version="$(python -c '… PACKAGE_VERSION …')"` at `:259`, `:302`, `:310`, and
`version="${GITHUB_REF_NAME#v}"` at `:750`, `:777`, `:832`, `:850`, `:866`. These two steps are the
only sites that interpolate the raw ref.

**A tag fares no better, which is why this is a blocker and not a dispatch artefact.** The wheel is
named from `PACKAGE_VERSION` and nothing else: the same run's own gate step printed
`build PASS synapse_cdm-2.0.0-py3-none-any.whl (6986 KiB) and synapse_cdm-2.0.0.tar.gz`, and
`ls -l dist` in the next step listed exactly `synapse_cdm-2.0.0-py3-none-any.whl` and
`synapse_cdm-2.0.0.tar.gz`. On a tag push of `v2.1.0`, `github.ref_name` is `v2.1.0`, so the two
steps would look for `dist/synapse_cdm-v2.1.0-py3-none-any.whl` while the file on disk is
`synapse_cdm-2.1.0-py3-none-any.whl` — the same "could not determine source", one character
apart. **The tag route has never executed this step**: `git show v2.0.0:.github/workflows/publish.yml`
carries no SBOM step at all, and `git log -S` on the expression returns exactly one commit,
`4ee2788` (round P7), which restructured the file into §50's order and was pushed but never tagged.

**Nothing in the tree would have caught it.** No test asserts either SBOM step's `file:` value:
`grep -rn "sbom-action\|ref_name" tests/` returns no site that reads it, and
`tests/test_cdm_trusted_publishing.py:747` asserts only that `synapse_cdm.spdx.json` and
`synapse_cdm.cdx.json` are among the release assets — which is a statement about the names the
`release` job uploads, not about the paths the `build` job reads.

**What it leaves unproven.** §50's stages after SBOM: the `SHA256SUMS` hash over every published
artefact, condition 4's derivations, Sigstore attestation and `gh attestation verify`, the PyPI
upload, the GitHub Release, and the witness record. Sections 11 and 12 have no pipeline readings
for that reason. It also touches the artefact set §53 hashes: the witness record carries the SBOM
digests, so a release taken with this step red would publish a witness naming files that were never
produced.

**Not repaired here.** The remedy is small and is still a decision, because there are three shapes
of it and they are not equivalent: derive the filename from `PACKAGE_VERSION` as the neighbouring
steps do; strip the prefix (`${GITHUB_REF_NAME#v}`) and accept that a dispatch on a branch still
cannot resolve it; or glob `dist/*.whl` and let the step describe whatever the one build produced.
Whichever is chosen has to be taken together with blocker 2, because both live in the same step.

### Blocker 2 — the SBOM the pipeline would publish lists no software

**The reading**, taken locally at the version the workflow pins (syft **v1.51.1**, installed to a
temporary directory, not into the tree) over the wheel the gate exports in the fresh clone:

| command | SPDX `packages` | CycloneDX `components` |
|---|---|---|
| `syft scan file:<wheel> -o spdx-json` | **1** | — |
| `syft scan file:<wheel> -o cyclonedx-json` | — | **0** |
| `syft scan <wheel>` (no source scheme) | **1** | — |
| `syft scan dir:<the same wheel, unpacked>` | **2**, including `synapse-cdm 2.0.0` | — |

The single SPDX entry is not a component of the distribution; it is the distribution's **own
filename**, `synapse_cdm-2.0.0-py3-none-any.whl`, with `primaryPackagePurpose: FILE` and its
SHA-256 as `versionInfo`. The CycloneDX document has an empty `components` array.

**Why it is a blocker and not a limitation.** §46 makes the SBOM a release artefact, §53's witness
record carries its digest, and the release's whole claim about it is that a consumer can read what
is inside the artefact they downloaded. A document whose only entry is the name of the file it
describes states nothing a consumer could not read from the filename, and it would be published,
hashed and attested as though it did. This is not syft failing: the same tool over the same bytes
unpacked finds the package, so the fix is a source the scanner can enumerate rather than a
different producer.

**Its relation to blocker 1.** Fixing the path alone turns a red step green and produces these two
near-empty documents — which is the worse outcome of the two, because a failed step is visible and
an empty SBOM is not. Both belong to one repair.

---

## Appendix — §58's definition of done, line by line

Each line of spec §58 with the file that satisfies it, and the ones that do not.

| §58 line | satisfied by | verdict |
|---|---|---|
| Adapter API v2 exists | `adapter.py`, `ARCHITECTURE.md` §1 | yes |
| Version model exists | `VERSIONING.md`, `version.py` (six axes) | yes |
| Direction model exists | `ARCHITECTURE.md` §2, `adapter.py` | yes |
| residual-data rule exists | `ARCHITECTURE.md` §5, `models.Residual`, `lossless.residual_block()` | yes |
| provenance rule exists | `ARCHITECTURE.md` §4 rule 5, `models.SourceRef`, seven added fields | yes |
| manifest schema exists | `schemas/manifests/adapter-manifest.schema.json` | yes |
| every existing adapter has a manifest | `manifests/*.json`, 14 | yes |
| manifests are tested | `tests/test_cdm_manifests.py`, 42 passed; `--check` CURRENT | yes |
| Conformance Suite v2 exists | `suite.py`, checks A–O | yes |
| existing checks retained | A–F, unchanged verdicts | yes |
| new generic checks implemented | G–O | yes |
| machine-readable results exist | `--format json`, and byte-stable since PB | yes |
| geometry foundation exists | `geo.py`, union of six + `BoundingBox` + CRS policy | yes |
| temporal validity exists | `models.TemporalValidity`, `Period` | yes |
| route/area foundation exists | `models.Route`, `RouteLeg`, `Waypoint`, `Area` | yes |
| quality/provenance support exists | `models.Quality`, `SourceHash`, `OperationalStatus` | yes |
| residual preservation exists | `models.Residual`, `lossless.classify` | yes |
| evidence schema exists | `evidence.py`, `EVIDENCE_SCHEMA_VERSION` 1.0.0 | yes |
| fixtures carry provenance | 39 `PROVENANCE.json`, `provenance` → COMPLETE | yes |
| adapters can emit evidence | `synapse evidence generate --all`, 14 records | yes |
| badges derive from evidence | `synapse evidence badges`, which refuses without a record | yes |
| SECURITY.md | `SECURITY.md`, 162 lines | yes |
| secret scanning | platform + `.gitleaks.toml` + the `secrets` CI job | yes |
| push protection where available | enabled in P5 | yes |
| parser safety policy | `SECURITY.md`, `capabilities.limits` on all fourteen | yes |
| dependency review | `dependency-review.yml`, `fail-on-severity: high` | yes, pull-request-only |
| Dependabot | `.github/dependabot.yml`, and `docs-audit` enforcing its npm findings | yes |
| vulnerability scanning | `pip-audit --strict` ×2 plus `npm audit` at high, in CI | yes |
| CodeQL | `codeql.yml` + `gates/codeql_gate.py`, 0 blocking | yes |
| SBOM | `publish.yml` `build`, syft, both formats | **red — blockers 1 and 2** |
| build attestation | `publish.yml` `attest`, Sigstore + `gh attestation verify` | **written, never executed — blocker 1** |
| repeatable CI release pipeline | `publish.yml`, six jobs in §50's order | **written; `gate` green, `build` red — blocker 1** |
| GitHub Release | `publish.yml` `release`, notes from `synapse release-notes` | written, tag-gated |
| PyPI publication | `publish.yml` `publish`, OIDC, `pypi` environment | written, tag-gated |
| witness format | `build_witness.py`, `gates/witness_verify.py`, `releases/witness/README.md` | yes |
| main/release rules | `VERSIONING.md` §5.1, `MIGRATIONS.md`'s pipeline section | yes |
| All existing public adapters continue to work | section 14: 0 paths removed, 1 value moved | yes |

Thirty-three of §58's thirty-seven lines are satisfied outright — two more than the previous
report, both of them the lines the closed blockers held. Three are satisfied **as files** and have
never executed, because the pipeline now stops in its second job rather than its first. One — SBOM
— is red at both readings a release would take.

```yaml
blocked: [sbom-stage-fails-on-a-ref-derived-wheel-path, sbom-over-a-wheel-file-enumerates-no-components]
```
