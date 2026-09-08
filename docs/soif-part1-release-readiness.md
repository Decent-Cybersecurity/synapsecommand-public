# SOIF Part 1 release-readiness report — 2026-09-08

Written by round P8 of the SOIF Part 1 campaign (spec §56–§58). Every figure below is a reading
taken on the commit named in section 18, with the command that produced it. Nothing here is
carried from a brief: where a brief's figure and the tree's disagreed, the tree's is what is
written and the disagreement is named.

**Release status: NO RELEASE.** Section 20 carries two blockers and section 19 says what each one
blocks. `PACKAGE_VERSION` is therefore unmoved at `2.0.0`: the version moves in the round that can
say "ready", and this round cannot.

---

## 1. Baseline

| what | reading | command |
|---|---|---|
| last release | `2.0.0`, tag `v2.0.0` | `git tag --sort=-v:refname \| head -1` |
| `main` | `a9ea68c1fdb260b91142330d3d06b5b6552e8476`, unmoved since the 2.0.0 witness round | `git rev-parse origin/main` |
| branch under review | `soif/1.0`, eleven commits ahead of `v2.0.0`, ten ahead of `origin/main` | `git rev-list --count v2.0.0..HEAD` → 11; `… origin/main..HEAD` → 10 |
| arc size | **791 files changed, 50128 insertions(+), 3891 deletions(-)** | `git diff --shortstat v2.0.0..HEAD` |
| tags | 12 local, 24 remote lines; no tag names any Part 1 commit | `git tag \| wc -l`; `git ls-remote --tags origin \| wc -l` |

The arc by top-level directory (`git diff --numstat v2.0.0..HEAD`, grouped):

| directory | files | + | − |
|---|---|---|---|
| `packages/` | 673 | 32038 | 3627 |
| `tests/` | 35 | 5594 | 50 |
| `schemas/` | 8 | 3915 | 39 |
| root files | 16 | 3303 | 52 |
| `docs/` | 23 | 2813 | 57 |
| `manifests/` | 14 | 1089 | 0 |
| `gates/` | 3 | 648 | 2 |
| `examples/` | 14 | 442 | 64 |
| `security/` | 3 | 199 | 0 |
| `releases/` | 1 | 71 | 0 |
| `spec/` | 1 | 16 | 0 |

The eleven commits, oldest first: `5209c1e` P0, `f28d58e` PA, `441a509` P1, `606e844` P2,
`6351fe1` P3, `9069fa9` P4, `e37cf20` P5, `c52e496` P6, `e540de8` PC, `4ee2788` P7. (Ten commits
for the `origin/main..HEAD` arc: `a9ea68c`, the 2.0.0 witness commit, is on `main`.)

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
`PUBLIC_GOVERNMENT` ×10, `LICENSED` ×3, `OPEN` ×1; `residual` `legacy` ×14;
`evidence.available` `false` ×14; **four null `format.version`** (adsb, ais, tak, pntmap);
73 declared limitations in total.

## 6. Maturity model

Seven levels L0–L6 and six claim statuses (spec §14–§15), computed in `manifest.py` and
`suite.py` from the checks that actually ran. Declared: **L4 ×11, L3 ×3**.

Two facts about the ceiling, both readings rather than omissions. The harness's `roundtrip`
column is SKIP for **all fourteen** adapters — `harness.py` cannot compare non-JSON egress bytes
and says so — so an L4 declaration rests on the adapter's own byte-exact round-trip test in
`tests/`, named in each manifest's `maturity.basis`. And L5 is declared by none: ARCHITECTURE.md
§3.6 computes it from the full applicable conformance set, and the eligibility rule that a
declared inapplicability does not block a rung while an undeclared SKIP does produces the
inversion P2 recorded — three ingest-only adapters compute L5 while eleven bidirectional ones
compute L3. Not resolved here; item 15.

## 7. Conformance

`suite.py` (1124 lines, round P2): fifteen checks A–O, SKIP semantics, `--format json`,
`--require`, and the `synapse` console script.

`synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json` → **exit 0,
fourteen CONFORMANT, no FAIL on any check for any adapter**. That is the required set CI and the
release pipeline use (`ci.yml`, `publish.yml`), and the file states why: E, I and M are declared
inapplicable for some adapter, and spec §19 makes a required SKIP exit non-zero.

The full verdict table, from the same sweep:

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
CONFORMANT and zero FAIL. `publish.yml` records the same reasoning at the step that runs it.

**The sweep's JSON is not byte-stable under load, and that is blocker 1.** See section 20.

## 8. Evidence

`evidence.py` (762 lines, round P4), `EVIDENCE_SCHEMA_VERSION` `1.0.0`, with §34's six loss
categories in `lossless.classify` and §33's `PROVENANCE.json` per fixture directory.

* `python -m synapse_cdm.evidence provenance` → `COMPLETE: 39 fixture directories under §33`.
* `synapse evidence generate --all`, twice into two directories, then
  `synapse evidence verify` over all fourteen → **14 REPRODUCED, exit 0**, masked fields
  `generated_at`, `test_run.duration_s`, `conformance.checks.H.details.refusals[].seconds`.
* `evidence.compare` between the two generations → **empty for all fourteen**.
* Loss report, summed over the fourteen: `DROPPED` **0**, `UNSUPPORTED` **0**, `DERIVED` **0**,
  `NORMALIZED` 38, `PRESERVED` 187, `RESIDUAL` 2877.
* Badges derive from a record and from nothing else: with no record on disk,
  `synapse evidence badges` refuses and says why.

The third masked field is the same wall-clock measurement that blocker 1 is about. The evidence
system masks it and is reproducible; two tests compare it unmasked and are not.

## 9. Security

`SECURITY.md` (162 lines, round P5): supported versions, reporting, scope, "Telemetry: none",
the controls table, and handling. `.gitleaks.toml` and a `secrets` CI job carry secret scanning;
platform secret scanning and push protection were enabled in P5; the parser-safety policy's
bounds are declared per adapter in each manifest's `capabilities.limits`, with
`absent_because` where no bound is enforced.

* `gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .` in a fresh clone →
  **10 commits scanned, no leaks found**.
* `gates/codeql_gate.py` over both SARIFs of the CodeQL run on this commit
  (`codeql.yml` run 34235284208, success) → **0 results, 0 blocking, exit 0**.
* `gh api …/code-scanning/alerts?ref=refs/heads/soif/1.0` → **four alerts, all `fixed`** — the
  four HIGH findings of CodeQL's first run, closed at their sites by round PC and confirmed
  closed by CodeQL's own re-analysis of this commit (`results_count` 0 for both languages).
* `security/exceptions/` → `README.md` and `schema.json`; **zero exception files**.
* No-network proof: `pytest -k "no_network or network"` → **66 passed**.

## 10. Dependencies

`.github/dependabot.yml` (pip, github-actions, npm; weekly; minor+patch grouped),
`dependency-review.yml` at `fail-on-severity: high`, and a `supply-chain` CI job running
`pip-audit --strict` twice — over the installed environment and over the wheel's own frozen
closure in a clean venv (round P6).

* `pip-audit --strict` in a fresh clone → **No known vulnerabilities found**.
* `gh api …/dependabot/alerts` → **11 open: 7 high, 4 medium**. Every one is `npm` in
  `docs/package-lock.json`, transitive under Docusaurus. **No CI job fails on any of them**, and
  two of the seven high have no upstream fix. **This is blocker 2** — section 20.

## 11. SBOM

The pipeline produces two SBOMs in its `build` job (`publish.yml`): SPDX-JSON and CycloneDX-JSON,
both from one `anchore/sbom-action` (syft) run **over the gated wheel** rather than over the source
tree or the environment.

**The pipeline's own SBOM stage is UNPROVEN on this commit, and the reason is blocker 1.** Two
`workflow_dispatch` runs of the restructured `publish.yml` on `soif/1.0`
(34235403062, 34236081918) both failed in `gate`, so `build` was `skipped` both times and no SBOM
was produced. `syft` — the pipeline's producer — is not installed on the machine this round ran on
(`which syft` → not found), so the stage cannot be reproduced locally either.

What *was* taken, named as what it is:

* `gh api …/dependency-graph/sbom` → **SPDX-2.3, 1235 packages**, creators
  `protobom` / `GitHub.com-Dependency-Graph` / `dependabot`. GitHub's producer over the
  repository, not syft over the wheel.
* `cyclonedx-py environment` over a fresh clone's venv → **CycloneDX 1.6, 73 components**. A
  second producer, over the environment rather than over the wheel.

Both formats therefore demonstrably generate; the artefact the release would publish does not yet
exist.

## 12. Build provenance

`publish.yml`'s `attest` job (round P7) takes Sigstore build provenance over the wheel, the sdist,
both SBOMs and the evidence archive, then runs `gh attestation verify` against it. `id-token:
write` and `attestations: write` are scoped to that job alone and to no other.

**Also unproven on this commit, for the same reason**: `attest` `needs: build`, and `build` was
skipped in both dispatches. `rc-build.yml` (round P6), the other workflow that composes the same
artefact set, cannot be dispatched at all until it is on the default branch — its first run is
necessarily post-release, which `SECURITY.md` now records beside the sentence that assumed
otherwise.

## 13. Release procedure

`publish.yml`, 876 lines, **six jobs, one per §50 stage boundary**, each `needs:` the one before,
so the order is enforced by the dependency graph: `gate` → `build` → `attest` → `publish` →
`release` → `witness`. Conditions 1–4 of `MIGRATIONS.md`'s "What a release requires" are the same
text in a different job (1, 3 and the annotated-tag check in `gate`; 2 and 4 in `build`, because
both read `dist/`), and `tests/test_cdm_trusted_publishing.py` holds them to that. Every `uses:`
is a full commit SHA with a version comment. `publish`, `release` and `witness` are each guarded
by `if: startsWith(github.ref, 'refs/tags/v')`, which is why a branch dispatch cannot publish.

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
well as in the schemas.** Derived here by comparing every golden at `v2.0.0` against the same
file at this commit, leaf by leaf (`git show v2.0.0:<path>` vs `git show HEAD:<path>`, JSON paths
flattened):

| reading | value |
|---|---|
| goldens at `v2.0.0` / at HEAD | 538 / 538 |
| goldens added / removed | 0 / 0 |
| JSON paths **removed** | **0** |
| JSON values **moved** | **1** — `schema_version`, on all 1308 objects |
| JSON paths added | `format_name`, `format_version`, `observed_at`, `original_id`, `quality`, `record_index`, `residual`, `source_hash`, `status` (1308 each); `vertical` (376) |

Fixture verdicts: `gates/wheel_install.py` reports **1076** over the roster, the 538 run in each of
two schema modes; the conformance sweep reports fourteen CONFORMANT with zero FAIL (section 7).

## 15. Known limitations

Everything the campaign deferred, each with where it is recorded. None of these is a blocker;
blockers are section 20.

1. **47 ruff `F` findings, and no mypy configuration** (round P7). 12 are in `packages/cdm` — 8
   F401, 2 F841, 2 F541 — and 35 more in `gates/` and `tests/`. The workflow's own command,
   `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests`, passes: the lint
   stage selects `E9` alone, because `E9` finds nothing while `F` finds 47 and fixing them means
   editing shipped modules. Widening the rule set is a round of its own.
2. **`ARCHITECTURE.md` §7's one-workflow sentence is false** (five workflows exist). §7's job
   table is otherwise satisfied.
3. **`evidence.available` is `false` on all fourteen** and `artifact_hashes` is empty. Both flip
   only when release evidence is generated from a release commit, attached to a Release and
   retrievable by a third party — the release round's, and a test asserts the declared set is
   exactly `{false}` today so the flip cannot happen silently.
4. **Four null `format.version`** (adsb, ais, tak, pntmap). Readings, not omissions: no document
   in the tree names the edition each was written against, and each manifest carries the
   limitation.
5. **L5 is declared by no adapter, and the eligibility inversion of section 6 stands.** Raising
   the eleven bidirectional ones would mean counting their own round-trip tests as a declared
   inapplicability of the harness's `E`, which is a rule change and not a reading.
6. **The harness's `roundtrip` check is SKIP for all fourteen** — a structural comparison cannot
   compare non-JSON egress bytes. Every L4 claim therefore rests on a per-adapter byte-exact test
   named in the manifest.
7. **Checks E and M are SKIP for all fourteen; I for seven; N for two.** Correct SKIP semantics
   (spec §17: a non-applicable check is never PASS), and the reason each is inapplicable is in
   the check's own `reason` field.
8. **The determinism/hash collision, still open.** `ARCHITECTURE.md` §4.4 says the determinism
   check hashes and §6.2 fixes sha256; `tests/test_cdm_boundary.py:74` forbids `hashlib` under
   `synapse_cdm/`. Check G compares canonical serialisations instead, and `evidence.py` is the one
   name the boundary gate allows, narrowed to it by name with two tests policing the allowance.
9. **The fourteen keep legacy residual parking** (`residual: legacy` ×14), by ruling: no golden
   was rewritten for placement.
10. **`defusedxml` is not a dependency**; an entity bomb is refused by libexpat and not by this
    package, which `SECURITY.md` states.
11. **`rc-build.yml` has never run**, and cannot until it is on the default branch.
12. **The `secrets` CI job has never executed on a push** to `main`, and
    `gitleaks/gitleaks-action` stays declined because it requires a paid licence for an
    organisation repository — the CI job runs the binary directly instead.
13. **`security-severity` on `actions` as a third CodeQL language** is available and not enabled;
    two languages are analysed.
14. **`docs/soif-part1-release-readiness.md` is not a page of the documentation site.** §57 fixes
    its path at `docs/`, and the site's content root is `docs/docs/`; the sidebar is autogenerated
    from that directory, so no `docs/*.md` report — including
    `docs/sc-oes-release-readiness-report.md`, the precedent — appears in it.
15. **A local apparatus file reds one suite test in the working tree only.** `Claude outputs/`
    is excluded at `.git/info/exclude`, so it is invisible to a clone and to every commit, and
    `test_cdm_version_floor.py` walks the filesystem rather than the git index.

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
`git clone --no-local` of this commit with its own venv inside it; `pip install -e
"packages/cdm[test]"`.

```bash
# 1  unit + adapter tests
python -m pytest -q                                  # in tree, and in <clone>
# 2  conformance
synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json
synapse conformance run --all --require A,B,C,D,E,F,G,H,J,K,L,N,O --format json
# 3  packaging
cd packages/cdm && python -m build && python -m twine check --strict dist/*
# 4  clean install
python gates/wheel_install.py
python gates/wheel_install.py --mutation-check
# 5  schema drift  (from the repository ROOT)
python -m synapse_cdm.schemas --check --out schemas
# 6  manifest validation
python -m synapse_cdm.manifests --check --out manifests
python -m pytest -q tests/test_cdm_manifests.py
# 7  evidence
python -m synapse_cdm.evidence provenance
synapse evidence generate --all --out /tmp/ev1 && synapse evidence generate --all --out /tmp/ev2
synapse evidence verify /tmp/ev1/*/*/evidence.json
# 8  security
gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .
python gates/codeql_gate.py <the codeql run's two SARIFs>
python -m pytest -q -k "no_network or network"
# 9  dependencies
pip-audit --strict
gh api repos/Decent-Cybersecurity/synapsecommand-public/dependabot/alerts --paginate
# 10 SBOM
gh api repos/Decent-Cybersecurity/synapsecommand-public/dependency-graph/sbom
cyclonedx-py environment .venv
# 11 documentation
cd docs && npm ci && npm run build      # and npm run ci, which adds schemas/typecheck/admonitions
# 12 the pipeline itself
gh workflow run publish.yml --ref soif/1.0
```

## 18. Commit

This report describes **`4ee2788b067384e693c144f6176b6268d5bc9f9f`** — round P7's commit, the tip
of `soif/1.0` and its remote tip, reviewed GO and pushed on 2026-09-08. `origin/main` is unmoved
at `a9ea68c1fdb260b91142330d3d06b5b6552e8476`; `git merge-base HEAD origin/main` is that same
commit; no tag names any commit on this branch.

The commit that carries **this file** is the round-P8 commit immediately after it, whose subject
begins `SOIF P8:`. Its hash is deliberately not written here: a hash cannot name the commit that
carries it, and a number written before the commit exists is a number nobody re-derived.

## 19. Release status

**NO RELEASE.** Spec §57: "If blockers are non-empty: NO RELEASE."

* `PACKAGE_VERSION` stays **`2.0.0`**. The bump gate would allow the move —
  `gates/bump_derivation.py --json` reads `derived_kind` **MINOR**, `pending` floor **2.1.0**,
  `unruled` **`[]`** — so the version is held back by this report's verdict and not by the
  derivation. The five other axes are unmoved: `SCHEMA_VERSION` 2.1.0, `SC_OES_VERSION` 0.1.0,
  `ADAPTER_API_VERSION` 2.0.0, `MANIFEST_SCHEMA_VERSION` 1.2.0, `EVIDENCE_SCHEMA_VERSION` 1.0.0.
* `MIGRATIONS.md`'s arc stays under `### Unreleased` with the eight round records under it
  (P1, P2, P3, P4, P5, P6, P7, PA). Nothing in it is released.
* `RELEASE_NOTES.md` still opens `# synapse-cdm 2.0.0` and still carries the dated pending
  paragraph saying so.
* The release round does not run. Beyond the two blockers, it also needs what no round can
  supply: M's authorisation of the number, and a fast-forward of `main` to this branch.

**What clearing blocker 1 requires is one decision, not one edit**, and it is not this round's to
make: default 2 of this round's brief says a red §56 item is a blocker and never a repair.

## 20. Blockers

```text
1. conformance-json-not-byte-stable
2. eleven-open-dependabot-alerts-unaudited-by-ci
```

### Blocker 1 — the conformance JSON is not byte-stable, and it reds Condition 1 of the release pipeline

**The reading.** Two `workflow_dispatch` runs of the restructured `publish.yml` on `soif/1.0`,
both on this commit, both **failed** in the `gate` job at *Condition 1 — the suite is green*:

| run | conclusion | suite | failing test |
|---|---|---|---|
| 34235403062 | `gate` failure; `build`/`attest`/`publish`/`release`/`witness` skipped | 1 failed, 5058 passed, 79 skipped | `tests/test_cdm_suite.py::test_two_sweeps_of_one_tree_are_byte_identical` |
| 34236081918 | same | 1 failed, 5058 passed, 79 skipped | the same test |

`ci.yml` on the same commit (run 34235284082) failed too — 2 failed, 5057 passed, 79 skipped — on
that test **and** on `tests/test_cdm_evidence.py::test_the_conformance_block_is_the_suites_own_
report_verbatim`. The same second test failed once in the working tree during this round
(4 failed, 5125 passed, 9 skipped) and P7's Act 0 recorded it once as well.

**The mechanism, proved rather than inferred.** `suite.py` writes a wall-clock measurement into
check H's own details — `"seconds": round(elapsed, 4)` — and both tests compare the JSON that
carries it for byte identity. On an unloaded machine all 28 refusal records read `seconds: 0.0`
and four consecutive sweeps are byte-identical (one SHA-256,
`061befe585b6f924a17cd55ba937e5faf4d68763623ed81c17ae15a2697753db`, four times; 0 differing
leaves). Every one of those 28 values therefore sits **directly on the rounding boundary**: a
single refusal taking 50 µs or more flips it to `0.0001`, which is exactly the diff the CI logs
show (`- onds": 0.0001` / `+ onds": 0.0`). Under CPU contention — a GitHub runner, or a loaded
laptop — the flip is likely rather than rare: two dispatches out of two.

**The tree already knows the field is not reproducible.** `evidence.MASKED` is exactly
`{"generated_at", "test_run.duration_s", "conformance.checks.H.details.refusals[].seconds"}`, and
`tests/test_cdm_evidence.py`'s own docstring records how it was found: "Two generations from one
fresh clone differed in exactly one field: `stanag4676`'s second refusal read `0.0` and then
`0.0001`." So `synapse evidence verify` reports 14 REPRODUCED and `evidence.compare` is empty,
while two tests compare the same bytes **unmasked**.

**Why it blocks a release rather than merely annoying CI.** `gate` is the first stage of §50's
order and everything else `needs:` it, so a red Condition 1 means no build, no SBOM, no
attestation, no publish — which is why sections 11 and 12 of this report have no pipeline
readings. And the artefact itself is affected: the `build` job hashes
`conformance-<version>.json` into `SHA256SUMS`, and `gates/witness_verify.py` reads those digests
back out of the witness record. A conformance artefact whose bytes depend on machine load is a
digest that cannot be re-derived, which is the one property §53 requires of a witness record.

**Not repaired here.** Default 2 of this round's brief: a red §56 item is a blocker, not a repair.
The remedy is a decision for M — mask the field in the comparison the two tests make (the shape
`evidence.masked()` already implements), or stop writing a wall time into the artefact at all, or
round it to a resolution no plausible refusal crosses. The first is the smallest and the only one
that keeps the measurement.

### Blocker 2 — eleven open Dependabot alerts, seven of them high, and no CI job fails on any

**The reading.** `gh api …/dependabot/alerts` → **11 open**: **7 high**, 4 medium. Every one is
`npm`, in `docs/package-lock.json`, transitive under Docusaurus. Round P6 enumerated them:
`fast-uri` ×4 and `serialize-javascript` (fixed upstream), `image-size` ×2 (**no fix available**);
medium `qs` ×2, `uuid`, `serialize-javascript`.

**The gap is the load-bearing half.** `pip-audit` is Python-only, `dependency-review.yml` runs
only on pull requests, and CodeQL analyses source rather than dependencies — so **no layer this
campaign installed audits the docs npm tree on a push**, and the repository's CI is green while
seven high advisories stand. Closing it means an npm audit step, which is scope no brief in this
campaign names.

**Why it is M's and not the runner's.** P6's brief reserves writing a security exception to M, and
`security/exceptions/` holds zero exception files by design. Two of the seven have no upstream fix
at all, so for those the only routes are an exception or a ruling that a documentation-site build
dependency is outside the release's scope. Either is a decision; neither is a reading.

**What it does not affect.** Nothing here is in the distribution. `pip-audit --strict` over both
the installed environment and the wheel's frozen closure reports no known vulnerability, the
runtime dependencies are unchanged across the whole arc (`pydantic`, `jsonschema`), and the wheel
carries no npm anything. The exposure is the documentation site's build toolchain.

---

## Appendix — §58's definition of done, line by line

Each line of spec §58 with the file that satisfies it, and the two that do not.

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
| machine-readable results exist | `--format json` | yes, **and not byte-stable — blocker 1** |
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
| Dependabot | `.github/dependabot.yml` | yes, **and its findings are blocker 2** |
| vulnerability scanning | `pip-audit --strict` ×2 in CI | yes, Python-only |
| CodeQL | `codeql.yml` + `gates/codeql_gate.py`, 0 blocking | yes |
| SBOM | `publish.yml` `build`, syft, both formats | **written, never executed — blocker 1** |
| build attestation | `publish.yml` `attest`, Sigstore + `gh attestation verify` | **written, never executed — blocker 1** |
| repeatable CI release pipeline | `publish.yml`, six jobs in §50's order | **written; its first stage is red — blocker 1** |
| GitHub Release | `publish.yml` `release`, notes from `synapse release-notes` | written, tag-gated |
| PyPI publication | `publish.yml` `publish`, OIDC, `pypi` environment | written, tag-gated |
| witness format | `build_witness.py`, `gates/witness_verify.py`, `releases/witness/README.md` | yes |
| main/release rules | `VERSIONING.md` §5.1, `MIGRATIONS.md`'s pipeline section | yes |
| All existing public adapters continue to work | section 14: 0 paths removed, 1 value moved | yes |

Thirty-one of §58's thirty-seven lines are satisfied outright. Four are satisfied **as files** and
have never executed, because blocker 1 stops the pipeline at its first stage. One — machine-readable
conformance results — exists and is not reproducible, which is blocker 1 itself. One — Dependabot —
works and is blocker 2.

```yaml
blocked: [conformance-json-not-byte-stable, eleven-open-dependabot-alerts-unaudited-by-ci]
```
