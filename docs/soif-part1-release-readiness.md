# SOIF Part 1 release-readiness report — 2026-09-08

Written by round P8 (attempt 4) of the SOIF Part 1 campaign (spec §56–§58). Every figure below is
a reading taken on the commit named in section 18, with the command that produced it. Nothing is
carried from a brief or from an earlier attempt: where an earlier report's figure and this tree's
disagree, this tree's is what is written and the disagreement is named.

This report **replaces** the one round P8 wrote as attempt 2 on 2026-09-08 at commit `b9ccb2c`.
That report carried two blockers, both in the release pipeline's SBOM stage. Round PS repaired
them, and this qualification was run again from scratch — a fresh clone, a fresh pipeline dispatch
— against the tree PS and PT left. **Both of those blockers are closed**, by the pipeline's own
readings and not by assertion: sections 11 and 12.

**One new blocker is open, and it was published into existence while this qualification was
running.** Two npm advisories dated 2026-09-08T21:20:28Z and 2026-09-08T21:24:51Z make `docs/`'s
locked dependency tree carry two unexcepted HIGH findings, which is exactly what round PB's
`docs-audit` job exists to refuse. Section 10 has the readings and section 20 the argument.

**Release status: NO RELEASE.** `PACKAGE_VERSION` is therefore unmoved at `2.0.0` — and under M's
ruling of 2026-09-08T20:56:31Z it would have been unmoved either way: readiness is a claim about a
tree the release round can run ON, and the version moves in that round, atomically with the tag.

---

## 1. Baseline

| what | reading | command |
|---|---|---|
| last release | `2.0.0`, tag `v2.0.0` | `git tag --sort=-v:refname \| head -1` |
| `main` | `a9ea68c1fdb260b91142330d3d06b5b6552e8476`, unmoved since the 2.0.0 witness round | `git rev-parse origin/main` |
| branch under review | `soif/1.0`, sixteen commits ahead of `v2.0.0`, fifteen ahead of `origin/main` | `git rev-list --count v2.0.0..HEAD` → 16; `… origin/main..HEAD` → 15 |
| arc size | **797 files changed, 52053 insertions(+), 3914 deletions(-)** | `git diff --shortstat v2.0.0..HEAD` |
| tags | 12 local, 24 remote lines; no tag names any Part 1 commit | `git tag \| wc -l`; `git ls-remote --tags origin \| wc -l` |

The arc by top-level directory (`git diff --numstat v2.0.0..HEAD`, grouped):

| directory | files | + | − |
|---|---|---|---|
| `packages/` | 673 | 32234 | 3627 |
| `tests/` | 36 | 6296 | 50 |
| `schemas/` | 8 | 3915 | 39 |
| `docs/` | 26 | 3522 | 79 |
| `.github/` | 7 | 1901 | 39 |
| root files | 9 | 1650 | 14 |
| `manifests/` | 14 | 1089 | 0 |
| `gates/` | 3 | 649 | 2 |
| `examples/` | 14 | 442 | 64 |
| `security/` | 5 | 268 | 0 |
| `releases/` | 1 | 71 | 0 |
| `spec/` | 1 | 16 | 0 |

The sixteen commits, oldest first: `a9ea68c` (the 2.0.0 witness commit, which is on `main`),
`5209c1e` P0, `f28d58e` PA, `441a509` P1, `606e844` P2, `6351fe1` P3, `9069fa9` P4, `e37cf20` P5,
`c52e496` P6, `e540de8` PC, `4ee2788` P7, `a9c0660` P8 (the first qualification), `b9ccb2c` PB,
`a214192` P8 (attempt 2), `cca0ec8` PS, `248743d` PT.

## 2. Resulting architecture

`ARCHITECTURE.md` (560 lines, round P0) is the frozen contract, in nine sections: Adapter API v2
(§1), direction model (§2), capability and metadata model (§3), core rules 1–6 (§4), residual-field
policy (§5), deterministic behaviour (§6), CI layout (§7), conformance namespaces (§8), and §9's
statement of what the freeze did *not* decide. `VERSIONING.md` (255 lines, P0, §5.1 added by P7)
holds the version model; `INTEROPERABILITY.md` (198 lines, P0) holds the contract a third party
builds against.

One known staleness, carried and not repaired: `ARCHITECTURE.md:487` says
"`.github/workflows/` holds exactly one workflow, `publish.yml`". There are five
(`ci.yml`, `codeql.yml`, `dependency-review.yml`, `publish.yml`, `rc-build.yml`). It has been false
since P1 and is section 15's, not this round's.

## 3. Adapter API

`packages/cdm/synapse_cdm/adapter.py` (516 lines, round P1 over P0's design). v2 is ADDITIVE over
the v1 surface: `metadata`, `detect()`, `validate_source()`, `capabilities()` are added;
`decode()`/`encode()` are the v2 names of `to_cdm`/`from_cdm` and **neither v1 name is removed** in
Part 1. The contract stays enforced at class-definition time in `__init_subclass__`.
`ADAPTER_API_VERSION` is `2.0.0` (`version.py:273`).

Direction model: the fourteen declare `bidirectional` ×11 and `ingest` ×3
(`manifests/*.json`, `adapter.direction`). MODEL, TRANSPORT and COMPOSITE exist in the model and
are declared by none of the fourteen.

## 4. CDM changes

`SCHEMA_VERSION` `2.0.0` → **`2.1.0`** (round P3, `version.py:246`), a MINOR: every added path is
optional or is reached only through an optional one, so a 2.0.0 reader keeps working and 2.0.0 data
keeps validating. `PACKAGE_VERSION` does **not** follow in this round — see section 19.

Added, in `geo.py` and `models.py`: `MultiPoint`/`MultiLineString`/`MultiPolygon` (the geometry
union widened to six), `VerticalPosition`, `VerticalExtent`, `BoundingBox` and the CRS policy;
`SourceHash`, `Period`, `TemporalValidity`, `Waypoint`, `RouteLeg`, `Route`, `Area`, `Quality`,
`OperationalStatus`, `Residual`; seven optional `SourceRef` fields; `Position.vertical`;
`CDMBase.quality`/`status`/`residual`; `PlanObject.validity`/`route`/`area`;
`lossless.residual_block()`; `enums.VerticalUnit` and `VerticalReference`.

Published schemas: `python -m synapse_cdm.schemas --check --out schemas` (from the repository root)
→ `CURRENT: schemas vs models at 2.1.0`, in the working tree and in the fresh clone alike.
`git diff --shortstat v2.0.0..HEAD -- schemas/` → **8 files changed, 3915 insertions(+), 39
deletions(-)**.

Backwards compatibility, derived and not asserted — see section 14 for the goldens.

## 5. Manifests

`manifest.py` (595 lines) and `manifests.py` (round P1, `MANIFEST_SCHEMA_VERSION` `1.0.0` → `1.1.0`
in P4 → **`1.2.0`** now, `version.py:308`), the schema at
`schemas/manifests/adapter-manifest.schema.json`, and fourteen generated records under `manifests/`.

`python -m synapse_cdm.manifests --check --out manifests` →
`CURRENT: manifests vs 14 shipped adapters at manifest schema 1.2.0`.
`pytest -q tests/test_cdm_manifests.py` → **42 passed**.

Declared across the fourteen, re-derived from `manifests/*.json` this round: `claim_status`
`VERIFIED` ×14; `license_class` `PUBLIC_GOVERNMENT` ×10, `LICENSED` ×3, `OPEN` ×1;
`residual` `legacy` ×14; `evidence.available` `false` ×14 with `artifact_hashes` empty on all
fourteen; **four null `format.version`** (adsb, ais, pntmap, tak); **73** declared limitations in
total.

## 6. Maturity model

Seven levels L0–L6 and six claim statuses (spec §14–§15), computed in `manifest.py` and
`suite.py` from the checks that actually ran. Declared: **L4 ×11, L3 ×3**.

Two facts about the ceiling, both readings rather than omissions. The harness's `roundtrip`
column is SKIP for **all fourteen** — `harness.py` cannot compare non-JSON egress bytes and says
so — so an L4 declaration rests on the adapter's own byte-exact round-trip test in `tests/`, named
in each manifest's `maturity.basis`. And L5 is declared by none: the sweep's own
`maturity_eligible` field, re-read this round, computes **L3 for the eleven bidirectional ones
and L5 for the three ingest-only ones** — the inversion P2 recorded, because a declared
inapplicability does not block a rung while an undeclared SKIP does. Not resolved here; section 15.

## 7. Conformance

`suite.py` (1140 lines, rounds P2 and PB): fifteen checks A–O, SKIP semantics, `--format json`,
`--require`, and the `synapse` console script.

`synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json` → **exit 0,
fourteen CONFORMANT, no FAIL on any check for any adapter**. That is the required set CI and the
release pipeline use (`ci.yml:143`, `publish.yml:304`, `publish.yml:514`, `rc-build.yml:94`).

The full verdict table, from one `--all` sweep in the fresh clone:

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

Requiring `E` or `N` makes exit 0 unreachable, by §17's own SKIP rule and not by a defect: with
`--require A,B,C,D,E,F,G,H,J,K,L,N,O` the sweep exits **1** while still reporting fourteen
CONFORMANT and zero FAIL. E is SKIP everywhere because `from_cdm` returns non-JSON bytes that the
check cannot compare structurally; I is SKIP for the seven binary-ingress ones (cat021, cat023,
cat034, cat048, cat062, stanag4586, stanag4609); N is SKIP for `legion` and `pntmap`, whose
fixtures are parsed dicts with nothing to truncate, and both declare the inapplicability.

**The sweep's record is deterministic.** Two consecutive sweeps with the same arguments, written to
two files, are **byte-identical** (`cmp` reports no difference). The only `seconds` substring in the
record is `microseconds`, five times, inside fixture element paths in check H's records — content,
not a clock. That is the property round PB's change to check H was for, and it is the property this
report tests rather than the weaker "no such substring".

## 8. Evidence

`evidence.py` (767 lines, rounds P4 and PB), `EVIDENCE_SCHEMA_VERSION` `1.0.0`, with §34's six
loss categories in `lossless.classify` and §33's `PROVENANCE.json` per fixture directory.

* `python -m synapse_cdm.evidence provenance` → `COMPLETE: 39 fixture directories under §33`.
* `synapse evidence generate --all`, twice into two directories → **14 records each**; comparing
  the two generations with `evidence.MASKED` removed leaf by leaf → **empty for all fourteen**.
* `synapse evidence verify` over all fourteen records → **14 REPRODUCED, exit 0**.
* `evidence.MASKED` is exactly `("generated_at", "test_run.duration_s")` — **two** entries. The
  third candidate, the refusal record's wall clock, was removed at the source by PB rather than
  masked, so the artefact no longer contains an unreproducible value to hide.
* Loss report, summed over the fourteen: `DROPPED` **0**, `UNSUPPORTED` **0**, `DERIVED` **0**,
  `NORMALIZED` 38, `PRESERVED` 187, `RESIDUAL` 2877; **274** fixtures classified and **264**
  skipped as non-JSON payloads.
* Badges derive from a record and from nothing else: run from a directory with no record,
  `synapse evidence badges` refuses with its reason and **exits 2**.

## 9. Security

`SECURITY.md` (162 lines, round P5): supported versions, reporting, scope, "Telemetry: none",
the controls table, and handling. `.gitleaks.toml` and a `secrets` CI job carry secret scanning;
platform secret scanning and push protection were enabled in P5; the parser-safety policy's
bounds are declared per adapter in each manifest's `capabilities.limits`, with
`absent_because` where no bound is enforced.

* `gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .` → **15 commits scanned,
  no leaks found**, in the fresh clone and in the working tree.
* `gates/codeql_gate.py` over both SARIFs of the CodeQL run on this commit (`codeql.yml` run
  34284003597, success; analyses `1744292479` python and `1744290501` javascript-typescript, each
  `results_count` 0) → **0 results, 0 blocking, 0 excepted, 0 unclassified, exit 0**.
* `gh api …/code-scanning/alerts?ref=refs/heads/soif/1.0` → **zero open**; the four HIGH findings
  of CodeQL's first run are all `fixed`, closed at their sites by round PC.
* `security/exceptions/` → two exception files (`GHSA-5p2g-fcmc-qvqq.json`,
  `GHSA-w3rx-r6r6-pgpr.json`), `README.md` and `schema.json`. Both files carry all eleven required
  keys, including PB's `mitigation` and `upstream_status`, and both expire `2026-11-07` — a date the
  gate reads, after which the exception is dropped rather than honoured.
* No-network proof: `pytest -k "no_network or network"` → **66 passed**.

## 10. Dependencies

`.github/dependabot.yml` (pip, github-actions, npm; weekly; minor+patch grouped),
`dependency-review.yml` at `fail-on-severity: high`, a `supply-chain` CI job running
`pip-audit --strict` twice — over the installed environment and over the wheel's own frozen
closure in a clean venv (round P6) — and, since PB, a **`docs-audit`** job (`ci.yml:322`) that runs
`npm audit` over `docs/` at `--audit-level=high` with its allowlist derived from
`security/exceptions/` and nothing typed into the workflow.

**Python: clean.** `pip-audit --strict` in the fresh clone, with the ignores the gate derives
(`--ignore-vuln GHSA-5p2g-fcmc-qvqq --ignore-vuln GHSA-w3rx-r6r6-pgpr`, printed by
`gates/codeql_gate.py --emit-pip-audit-ignores` before they are used) → **No known vulnerabilities
found**, exit 0.

**npm: two unexcepted HIGH advisories, as of 2026-09-08T22:13:41Z. This is blocker 1.** Read by the
`docs-audit` job's own logic — `npm audit --prefix docs --json`, one advisory per object-valued
`via` entry, keyed by GHSA id:

| advisory | package | installed | npm severity | excepted | first patched |
|---|---|---|---|---|---|
| `GHSA-5p2g-fcmc-qvqq` | image-size | 2.0.2 | high | **yes** | none published |
| `GHSA-w3rx-r6r6-pgpr` | image-size | 2.0.2 | high | **yes** | none published |
| `GHSA-2883-xcg3-v3hh` | js-yaml | 4.3.1 | **high** | no | **4.3.2** |
| `GHSA-w27v-7q3p-w38r` | svgo | 3.3.4 | **high** | no | **3.3.5** |
| `GHSA-4vpr-x523-8j87` | svgo | 3.3.4 | moderate | no | 3.3.5 |
| `GHSA-w5hq-g745-h8pq` | uuid | 8.3.2 | moderate | no | 11.1.1 |

Six advisories; the gate's blocking set is the high-or-critical ones that are not excepted, and
that set is **`['GHSA-2883-xcg3-v3hh', 'GHSA-w27v-7q3p-w38r']`** — two, where the gate needs zero.
`npm audit --prefix docs --audit-level=high` exits **1**.

**The timing matters, and it is why CI on this commit is green.** The two advisories were published
at **2026-09-08T21:20:28Z** (svgo) and **2026-09-08T21:24:51Z** (js-yaml)
(`gh api advisories/<id>`), and npm's audit endpoint began serving them between **22:05:06Z** and
**22:13:41Z**. `ci.yml` run 34284003679 on this commit ran its `docs-audit` step at 22:05:06Z and
printed `advisories: 3; excepted and present: ['GHSA-5p2g-fcmc-qvqq', 'GHSA-w3rx-r6r6-pgpr'];
excepted and absent: []` followed by `OK — no unexcepted high or critical npm advisory in docs/`.
That green is true of the instant it was taken and false of this tree now: the same job, run again
on the same commit, fails. A readiness report that quoted only the run would be quoting a stale
world.

**And this one is not cleared by advancing `main`.** The eleven open Dependabot alerts —
`gh api …/dependabot/alerts?state=open` → **11: 7 high, 4 medium**, every one `npm` in
`docs/package-lock.json` — are computed against the **default branch**, and eight of the nine
non-excepted ones name `fast-uri`, `qs` and `serialize-javascript`, which this branch already
overrides (`git show origin/main:docs/package-lock.json` has 3.1.5 / 6.15.3 / 6.0.2; this commit has
3.1.7 / 6.16.0 / 7.1.1). Those fall when `main` fast-forwards. The two new ones do not: `js-yaml`
is **4.3.1 on `main` and 4.3.1 here**, `svgo` **3.3.4 and 3.3.4** — the branch carries the
vulnerable versions itself, so no merge can clear them and only a lockfile change can.

**Both of attempt 2's dependency findings remain closed.** The npm tree is audited on every push by
a job that derives its allowlist from `security/exceptions/`, and it is that very job — working as
designed, on advisories published forty minutes before this reading — which now refuses the tree.

## 11. SBOM

The pipeline produces both SBOM formats in its `build` job (`publish.yml`): SPDX-JSON and
CycloneDX-JSON from one `anchore/sbom-action` (syft, pinned) run **over the clean-install
environment** the previous step built, plus a `cyclonedx-py` cross-check over that same
environment. §46 asks for both formats "where supported by tooling" and makes the SBOM a release
artefact.

**The stage is green on this commit, and that closes both of attempt 2's blockers.** The
`workflow_dispatch` run of `publish.yml` on `soif/1.0` (run
[34284117127](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/34284117127),
`head_sha` `248743d7…`, created 22:05:50Z, concluded 22:21:35Z `success`) ran all four SBOM steps
green and printed, from its own assertion step:
`SPDX: 19 packages. CycloneDX: 50 components. synapse-cdm at 2.0.0 in both, and in the
cross-check.`

Both documents were downloaded from the run and re-counted here rather than trusted:

* `synapse_cdm.spdx.json` → **SPDX-2.3, 19 packages**, with `synapse-cdm 2.0.0` present.
* `synapse_cdm.cdx.json` → **CycloneDX 1.7, 50 components** — 12 `library`, 32 `file`,
  6 `application` — with `synapse-cdm 2.0.0` a `library`, and **12 of 50** declaring a licence.
* The two documents' SHA-256 digests, re-derived locally from the downloaded bytes, equal the
  entries the run's own `SHA256SUMS` carries for them
  (`0c1683c8…` cdx, `16a239c3…` spdx). `SHA256SUMS` covers **six** artefacts: the wheel, the sdist,
  both SBOMs, the conformance JSON and the evidence archive.

Attempt 2's blocker 1 was a wheel path built out of `github.ref_name`, which never exists on a
branch dispatch; PS replaced it with a path derived from `PACKAGE_VERSION`, and the run's step 6 is
named for that rule. Attempt 2's blocker 2 was an SBOM over a wheel *file*, which enumerated one
package and zero components; PS moved the scan to the clean-install environment, and the counts
above are what that produces. Neither reading is an assertion about the repair: they are the
pipeline's own output on this commit.

## 12. Build provenance

`publish.yml`'s `attest` job (round P7) takes Sigstore build provenance over the wheel, the sdist,
both SBOM files and the evidence archive, then runs `gh attestation verify` against each.
`id-token: write` and `attestations: write` are scoped to that job alone and to no other.

**Proven on this commit for the first time.** In run 34284117127 the `attest` job is **success**:
`Attestation created for 5 subjects`, published at
`…/attestations/46093962`, and the verification step ran `gh attestation verify` over each of the
five subjects — the wheel, the sdist, `sbom/synapse_cdm.cdx.json`, `sbom/synapse_cdm.spdx.json` and
`evidence-2.0.0.tar.gz` — under `set -euo pipefail`, so the job's green is each verification's
exit 0.

`rc-build.yml` (round P6), the other workflow that composes the same artefact set, still cannot be
dispatched at all until it is on the default branch: its first run is necessarily post-release,
which `SECURITY.md` records beside the sentence that assumed otherwise.

## 13. Release procedure

`publish.yml`, 1019 lines, **six jobs, one per §50 stage boundary**, each `needs:` the one before,
so the order is enforced by the dependency graph: `gate` (`:182`) → `build` (`:402`) → `attest`
(`:726`) → `publish` (`:796`) → `release` (`:848`) → `witness` (`:934`). Conditions 1–4 of
`MIGRATIONS.md`'s "What a release requires" are the same text in a different job (1, 3 and the
annotated-tag check in `gate`; 2 and 4 in `build`, because both read `dist/`), and
`tests/test_cdm_trusted_publishing.py` holds them to that. Every `uses:` is a full commit SHA with
a version comment. `publish`, `release` and `witness` are each guarded by
`if: startsWith(github.ref, 'refs/tags/v')`, which is why a branch dispatch cannot publish.

The dispatch on this commit, stage by stage:

| §50 stage | job | conclusion |
|---|---|---|
| gate — lint, suite, conformance, security gates, annotated-tag check | `gate` | **success** (Condition 3 and the annotated-tag check `skipped`: they are tag-only) |
| package build, clean install, package test, SBOM ×3, hash, Condition 4 | `build` | **success — every step** |
| Sigstore build provenance and its verification | `attest` | **success — 5 subjects created and verified** |
| PyPI upload / GitHub Release / witness | `publish`, `release`, `witness` | `skipped` — the tag guard |

The `gate` job's own suite step read **5103 passed, 76 skipped** on the runner, and its clean-install
slice **3116 passed, 7 skipped**.

CI-side readings on this same commit: `ci.yml` run **34284003679 success** (six jobs — suite/gates/
manifests, conformance, evidence, gitleaks, supply-chain, docs-audit), `codeql.yml` run
**34284003597 success** (two languages, 0 results each). Section 10 records what the `docs-audit`
job's green does and does not mean on a tree whose advisory set changed eight minutes later.

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
well as in the schemas.** Derived this round by comparing every golden at `v2.0.0` against the same
file at this commit, leaf by leaf (`git show v2.0.0:<path>` versus `git show HEAD:<path>`, JSON
paths flattened), and not carried from any earlier report:

| reading | value |
|---|---|
| goldens at `v2.0.0` / at HEAD | 538 / 538 |
| goldens added / removed | 0 / 0 |
| objects compared | 1308 |
| JSON paths **removed** | **0** |
| JSON values **moved** | **1** — `schema_version`, on all 1308 objects |
| JSON paths added | 11: `source.source_hash`, `source.format_name`, `source.format_version`, `source.observed_at`, `source.original_id`, `source.record_index`, `status`, `quality`, `residual` (1308 each); `position.vertical` (259) and `samples.position.vertical` (89) |

`git diff --shortstat cca0ec8..HEAD -- '**/golden/**'` → empty: no golden moved in PS or PT either.

Fixture verdicts: `gates/wheel_install.py` reports **1076** over the roster, the 538 run in each of
two schema modes, 0 failed, 13 checks 0 failed; the conformance sweep reports fourteen CONFORMANT
with zero FAIL (section 7).

## 15. Known limitations

Everything the campaign deferred, each with where it is recorded. None of these is a blocker;
blockers are section 20.

1. **47 ruff `F` findings, and no mypy configuration** (round P7). Re-derived this round with the
   pinned ruff 0.16.6: **12** in `packages/cdm`, **3** in `gates/`, **32** in `tests/`. The
   workflow's own command, `ruff check --config packages/cdm/pyproject.toml packages/cdm gates
   tests`, prints `All checks passed!`: the configured rule set selects `E9`, which finds nothing,
   while `F` finds 47 and fixing them means editing shipped modules. Widening the rule set is a
   round of its own.
2. **`ARCHITECTURE.md:487`'s one-workflow sentence is false** (five workflows exist). §7's job
   table is otherwise satisfied.
3. **`evidence.available` is `false` on all fourteen** and `artifact_hashes` is empty. Both flip
   only when release evidence is generated from a release commit, attached to a Release and
   retrievable by a third party — the release round's, and a test asserts the declared set is
   exactly `{false}` today so the flip cannot happen silently.
4. **Four null `format.version`** (adsb, ais, pntmap, tak). Readings, not omissions: no document
   in the tree names the edition each was written against, and each manifest carries the
   limitation.
5. **L5 is declared by no adapter, and the eligibility inversion of section 6 stands** — the sweep
   computes L3 for the eleven bidirectional ones and L5 for the three ingest-only ones.
   Raising the eleven would mean counting their own round-trip tests as a declared inapplicability
   of the harness's `E`, which is a rule change and not a reading.
6. **The harness's `roundtrip` check is SKIP for all fourteen** — a structural comparison cannot
   compare non-JSON egress bytes. Every L4 claim therefore rests on a per-adapter byte-exact test
   named in the manifest.
7. **Checks E and M are SKIP for all fourteen; I for seven; N for two.** Correct SKIP semantics
   (spec §17: a non-applicable check is never PASS), and the reason each is inapplicable is in the
   check's own `reason` field. `publish.yml`'s comment at the step that runs the sweep names E, I
   and M as the excluded set and omits N, which is excluded too — a comment one name short of the
   list beside it.
8. **The determinism/hash collision, still open.** `ARCHITECTURE.md` §4.4 says the determinism
   check hashes and §6.2 fixes sha256; `tests/test_cdm_boundary.py` forbids `hashlib` under
   `synapse_cdm/`. Check G compares canonical serialisations instead, and `evidence.py` is the one
   name the boundary gate allows, narrowed to it by name with two tests policing the allowance.
9. **The fourteen keep legacy residual parking** (`residual: legacy` ×14), by ruling: no golden was
   rewritten for placement.
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
15. **A local apparatus directory reds four suite tests in the working tree only.** It is excluded
    at `.git/info/exclude`, so it is invisible to a clone and to every commit, and the tests that
    see it walk the filesystem rather than the git index. A fresh clone of this commit is **0
    failed** (section 17).
16. **The `uuid` and `svgo` moderate advisories have no taken fix**, and the eleven default-branch
    Dependabot alerts of section 10 stay open until `main` fast-forwards. The moderates are below
    the floor the `docs-audit` gate enforces; the eleven are a property of `main`'s tree and are
    verified after the release rather than before it. The two HIGH ones are **not** in this list:
    they are section 20's blocker.

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
git clone --no-local <repo> clone && cd clone && git checkout 248743d
python -m venv .venv && .venv/bin/pip install -e "$PWD/packages/cdm[test]"
# 1  unit + adapter tests
python -m pytest -q                                  # in <clone>, and in the working tree
# 2  conformance
synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json   # twice, then cmp
synapse conformance run --all --require A,B,C,D,E,F,G,H,J,K,L,N,O --format json
synapse conformance run --all --format json          # the verdict table of section 7
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
synapse evidence generate --all --out ev1 && synapse evidence generate --all --out ev2
synapse evidence verify ev1/*/*/evidence.json        # and a masked leaf-by-leaf diff of ev1 vs ev2
synapse evidence badges                              # from a directory with no record
# 8  security
gitleaks git --config .gitleaks.toml --log-opts "origin/main..HEAD" .
gh api -H "Accept: application/sarif+json" repos/<owner>/<repo>/code-scanning/analyses/<id>
python gates/codeql_gate.py <both sarifs>
python -m pytest -q -k "no_network or network"
gh api repos/<owner>/<repo>/code-scanning/alerts?ref=refs/heads/soif/1.0
# 9  dependencies
python gates/codeql_gate.py --emit-pip-audit-ignores
pip-audit --strict <the derived ignores>
npm audit --prefix docs --audit-level=high ; npm audit --prefix docs --json
gh api advisories/<ghsa-id>                          # each advisory's publication instant
gh api repos/<owner>/<repo>/dependabot/alerts?state=open --paginate
# 10 SBOM and provenance
gh run download <run> && shasum -a 256 <the downloaded SBOMs>
# 11 documentation
npm ci && npm run build                # in <clone>/docs, F8.3's scope
# 12 the pipeline itself
gh workflow run publish.yml --ref soif/1.0 && gh run view <run> --log
# 13 lint, for section 15
ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests
ruff check --select F --config packages/cdm/pyproject.toml packages/cdm gates tests
```

Suite figures, both taken at this commit: **fresh clone → 0 failed, 5105 passed, 74 skipped**
(collection 5179); **working tree → 4 failed, 5169 passed, 6 skipped**, whose failures are all in the local apparatus
directory of limitation 15 and in no tracked file.

Documentation check (§56's last item, F8.3 = build only): `npm ci` then `npm run build` in the
fresh clone → `npm ci` exit 0, then **`[SUCCESS] Generated static files in "build"`, exit 0**.

## 18. Commit

This report describes **`248743d737553fc2c33cec9ea716fec571bef9d0`** — round PT's commit, the tip
of `soif/1.0` and, since 2026-09-08T22:04:30Z, its remote tip. `origin/main` is unmoved at
`a9ea68c1fdb260b91142330d3d06b5b6552e8476`; `git merge-base HEAD origin/main` is that same commit;
no tag names any commit on this branch (12 local, 24 remote tag lines, unmoved).

The commit that carries **this file** is the round-P8 commit immediately after it, whose subject
begins `SOIF P8`. Its hash is deliberately not written here: a hash cannot name the commit that
carries it, and a number written before the commit exists is a number nobody re-derived.

## 19. Release status

**NO RELEASE.** Spec §57: "If blockers are non-empty: NO RELEASE."

* `PACKAGE_VERSION` stays **`2.0.0`** — and this round would not have moved it in any case. M's
  ruling of 2026-09-08T20:56:31Z: readiness means a tree the release round can run ON, so the
  version, the `### Unreleased` heading and `RELEASE_NOTES.md` all move in the release round,
  atomically with the tag. `tests/test_cdm_readiness.py` (round PT) is what holds this report to
  that rule in both directions.
* The derivation would allow the release: `gates/bump_derivation.py --json` reads `derived_kind`
  **MINOR**, `pending` floor **2.1.0**, `unruled` **`[]`** over **697** signals and **10** ruled
  units, and `--mutation-check` → 1 check, 0 failed. The number is held back by this report's
  verdict, not by the derivation.
* The five other axes are unmoved: `SCHEMA_VERSION` 2.1.0, `SC_OES_VERSION` 0.1.0,
  `ADAPTER_API_VERSION` 2.0.0, `MANIFEST_SCHEMA_VERSION` 1.2.0, `EVIDENCE_SCHEMA_VERSION` 1.0.0.
* `MIGRATIONS.md`'s arc stays under `### Unreleased` (`:320`) with its round records under it.
  Nothing in it is released.
* `RELEASE_NOTES.md` still opens `# synapse-cdm 2.0.0`.
* The release round does not run. Beyond the blocker it also needs what no round can supply: M's
  authorisation of the number, and a fast-forward of `main` to this branch.

**Everything §56 asks for is green except one item.** The pipeline is green through `attest` for
the first time; the SBOMs enumerate the release; the attestation exists and verifies; the suite,
conformance, packaging, clean install, schema drift, manifests, evidence, secret scanning, CodeQL,
`pip-audit` and the docs build are all green in a fresh clone. The one red item is the npm half of
dependency analysis, and by this round's default 2 it is a blocker and not a repair: a red §56 item
is written down, not fixed in passing.

## 20. Blockers

```text
1. docs-npm-tree-carries-two-unexcepted-high-advisories
```

### Blocker 1 — two HIGH npm advisories published today put `docs/`'s locked tree in breach of the gate round PB built

**What is red.** `npm audit` over `docs/`, read by the exact logic of `ci.yml`'s `docs-audit` job,
reports six advisories, of which **two are HIGH and neither is excepted**:

* **`GHSA-2883-xcg3-v3hh`** — *js-yaml: `maxTotalMergeKeys` does not limit CPU use for empty
  merges*. Installed **4.3.1**; vulnerable range `>= 4.0.0, < 4.3.2`; first patched **4.3.2**.
  Published **2026-09-08T21:24:51Z**.
* **`GHSA-w27v-7q3p-w38r`** — *SVGO: `removeScripts` allows executable links through namespace
  confusion*. Installed **3.3.4**; the 3.x range is `>= 3.0.0, < 3.3.5`; first patched **3.3.5**.
  Published **2026-09-08T21:20:28Z**.

The gate's blocking set is therefore `['GHSA-2883-xcg3-v3hh', 'GHSA-w27v-7q3p-w38r']` and
`npm audit --prefix docs --audit-level=high` exits 1. Nothing about the tree changed: the advisory
database did, forty minutes before this reading.

**Why it is a blocker and not a limitation.** Round PB added `docs-audit` precisely so that a push
carrying an unexcepted high or critical npm advisory fails CI, and attempt 2's blocker 2 was the
absence of that audit. The gate now does what it was built to do. The consequence is concrete: the
next push of this branch reds `ci.yml`, and the first step of the release procedure
(`VERSIONING.md` §5.1) is a fast-forward of `main` to this branch — so the release would land a red
default branch. Declaring "ready for PR" over a gate that refuses the tree would be a readiness
claim the tree contradicts.

**Why advancing `main` cannot clear it.** Unlike the eleven open Dependabot alerts of section 10,
these two are not artefacts of `main` lagging the branch: `js-yaml` is 4.3.1 on both,
`svgo` is 3.3.4 on both. The branch carries the vulnerable versions itself.

**What it does not touch.** The release pipeline does not audit npm: `publish.yml` contains no
`npm` step, and its `gate` job's security stage is gitleaks plus the CodeQL gate plus `pip-audit`.
Run 34284117127 is green end to end through `attest` (sections 11–13) and would be green on a tag
today. The docs site also still builds from the audited tree (`npm run build`, exit 0). What is
broken is the branch's compliance with its own dependency policy, not its ability to produce
artefacts.

**What the fix looks like, for whoever briefs it** — recorded because §57 asks for the blocker's
mechanism, not because this round may take it: both packages are transitive dependencies of
`@docusaurus/*`, so the shape is PB's own — an `overrides` entry in `docs/package.json` pinning
`js-yaml ^4.3.2` and `svgo ^3.3.5`, `npm install` to move `docs/package-lock.json`, then the docs
build and the audit re-run. Two files, one of them generated. The alternative — a
`security/exceptions/` entry for each — is available and, unlike the `image-size` pair, would be
hard to argue: a fix exists upstream in both cases.

**What is unproven.** Whether a bump to `js-yaml 4.3.2` and `svgo 3.3.5` leaves the Docusaurus
build green. This round did not try it: trying it is the repair.

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
| machine-readable results exist | `--format json`, byte-identical across two sweeps | yes |
| geometry foundation exists | `geo.py`, union of six + `BoundingBox` + CRS policy | yes |
| temporal validity exists | `models.TemporalValidity`, `Period` | yes |
| route/area foundation exists | `models.Route`, `RouteLeg`, `Waypoint`, `Area` | yes |
| quality/provenance support exists | `models.Quality`, `SourceHash`, `OperationalStatus` | yes |
| residual preservation exists | `models.Residual`, `lossless.classify` | yes |
| evidence schema exists | `evidence.py`, `EVIDENCE_SCHEMA_VERSION` 1.0.0 | yes |
| fixtures carry provenance | 39 `PROVENANCE.json`, `provenance` → COMPLETE | yes |
| adapters can emit evidence | `synapse evidence generate --all`, 14 records | yes |
| badges derive from evidence | `synapse evidence badges`, which refuses without a record (exit 2) | yes |
| SECURITY.md | `SECURITY.md`, 162 lines | yes |
| secret scanning | platform + `.gitleaks.toml` + the `secrets` CI job | yes |
| push protection where available | enabled in P5 | yes |
| parser safety policy | `SECURITY.md`, `capabilities.limits` on all fourteen | yes |
| dependency review | `dependency-review.yml`, `fail-on-severity: high` | yes, pull-request-only |
| Dependabot | `.github/dependabot.yml`, and `docs-audit` enforcing its npm findings | yes — and it is the gate now refusing the tree, blocker 1 |
| vulnerability scanning | `pip-audit --strict` ×2 plus `npm audit` at high, in CI | **written and working; the npm half is RED on this tree** |
| CodeQL | `codeql.yml` + `gates/codeql_gate.py`, 0 blocking | yes |
| SBOM | `publish.yml` `build`, syft over the clean-install environment, both formats, plus a `cyclonedx-py` cross-check | **yes — green on this commit** |
| build attestation | `publish.yml` `attest`, Sigstore + `gh attestation verify`, 5 subjects | **yes — executed and verified on this commit** |
| repeatable CI release pipeline | `publish.yml`, six jobs in §50's order, green through `attest` | **yes for every stage a branch can reach** |
| GitHub Release | `publish.yml` `release`, notes from `synapse release-notes` | written, tag-gated |
| PyPI publication | `publish.yml` `publish`, OIDC, `pypi` environment | written, tag-gated |
| witness format | `build_witness.py`, `gates/witness_verify.py`, `releases/witness/README.md` | yes |
| main/release rules | `VERSIONING.md` §5.1, `MIGRATIONS.md`'s pipeline section | yes |
| All existing public adapters continue to work | section 14: 0 paths removed, 1 value moved | yes |

**Thirty-four of §58's thirty-seven lines are satisfied outright** — three more than attempt 2's
report, and the three are the SBOM, the attestation and the pipeline, all of which PS's repair took
from written-but-never-executed to executed and verified. Three remain satisfied **as files** and
tag-gated by design (`publish`, `release`, `witness`); they cannot execute on a branch. **One is
red**: vulnerability scanning, whose npm half refuses this tree — blocker 1.

```yaml
blocked: [docs-npm-tree-carries-two-unexcepted-high-advisories]
```
