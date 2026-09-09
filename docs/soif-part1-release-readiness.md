# SOIF Part 1 release-readiness report — 2026-09-09

Written by round P8 (attempt 6) of the SOIF Part 1 campaign (spec §56–§58). Every figure below is
a reading taken on the commit named in section 18, with the command that produced it. Nothing is
carried from a brief or from an earlier attempt: where an earlier report's figure and this tree's
disagree, this tree's is what is written and the disagreement is named.

This report **replaces** the one round P8 wrote as attempt 5 on 2026-09-09 at commit `b8ec0c5`.
That report certified a tree, the release round PR acted on it, and **the release it certified did
not complete**: `main` was fast-forwarded, `v2.1.0` was tagged and pushed, and the release pipeline
then refused its own tag at the security gate — `pip-audit --strict` cannot resolve the very
distribution the release is about, because the version being released is by definition not on the
index yet. Nothing was uploaded and no Release was created. Round PP repaired the gate, and this
report is the qualification of the repaired machinery.

**Release status: ready for PR (corrective 2.1.1, M's ruling 2026-09-09).** Every §56 item is
green in a fresh clone of this commit, the release pipeline is green end to end through `attest` on
this commit — including the step that refused the tag — and section 20 is empty.

`PACKAGE_VERSION` is `2.1.0` and does not move in this round. M's ruling of 2026-09-08T20:56:31Z
stands: the version, the release heading and `RELEASE_NOTES.md` move in the release round,
atomically with the tag, and PR already moved them for 2.1.0. The corrective number is **2.1.1**,
and it is the release round that types it. `tests/test_cdm_readiness.py` (round PT, amended by PP)
is what holds this report to that rule, and it reads this tree in its **pre-release** mode: the tag
`v2.1.0` exists, and it does not contain the commit this report describes.

---

## 1. Baseline

| what | reading | command |
|---|---|---|
| version the index serves | `2.0.0` | `curl pypi.org/pypi/synapse-cdm/json` → `info.version` `2.0.0`; `"2.1.0" in releases` → `False`; `"2.1.1" in releases` → `False` |
| newest tag | `v2.1.0`, on `b69a267e3ac7636c25cf878ef2b3cd5163b1b42a` | `git tag --sort=-creatordate \| head -1`; `git rev-list -n1 v2.1.0` |
| `main` | `b69a267e3ac7636c25cf878ef2b3cd5163b1b42a`, fast-forwarded by round PR on 2026-09-09 | `git rev-parse main` = `git rev-parse origin/main` |
| branch under review | `soif/1.0`, **21 commits** ahead of `v2.0.0`, **1** ahead of `origin/main` | `git rev-list --count v2.0.0..HEAD` → 21; `… origin/main..HEAD` → 1 |
| arc size | **798 files changed, 52988 insertions(+), 4036 deletions(-)** | `git diff --shortstat v2.0.0..HEAD` |
| tags | 13 local, 13 distinct remote (26 raw `ls-remote` lines with peels) | `git tag \| wc -l`; `git ls-remote --tags origin \| grep -v '\^{}' \| wc -l` |

The arc by top-level directory (`git diff --numstat v2.0.0..HEAD`, grouped):

| directory | files | + | − |
|---|---|---|---|
| `packages/` | 673 | 32423 | 3630 |
| `tests/` | 37 | 6762 | 52 |
| `schemas/` | 8 | 3915 | 39 |
| `docs/` | 26 | 3598 | 85 |
| `.github/` | 7 | 1997 | 39 |
| root files | 9 | 1758 | 125 |
| `manifests/` | 14 | 1089 | 0 |
| `gates/` | 3 | 649 | 2 |
| `examples/` | 14 | 442 | 64 |
| `security/` | 5 | 268 | 0 |
| `releases/` | 1 | 71 | 0 |
| `spec/` | 1 | 16 | 0 |

The twenty-one commits, oldest first: `a9ea68c` (the 2.0.0 witness commit), `5209c1e` P0,
`f28d58e` PA, `441a509` P1, `606e844` P2, `6351fe1` P3, `9069fa9` P4, `e37cf20` P5, `c52e496` P6,
`e540de8` PC, `4ee2788` P7, `a9c0660` P8 (the first qualification), `b9ccb2c` PB, `a214192` P8
(attempt 2), `cca0ec8` PS, `248743d` PT, `a0d5db1` P8 (attempt 4), `1a26576` PD, `b8ec0c5` P8
(attempt 5), `b69a267` PR (the release transition, and the commit `main` and `v2.1.0` both name),
`870913c` PP (the repaired security gate, and the commit this report describes).

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
`ADAPTER_API_VERSION` is `2.0.0` (`version.py:284`).

Direction model, re-derived from the fourteen `manifests/*.json` this round: `bidirectional` ×11
and `ingest` ×3. MODEL, TRANSPORT and COMPOSITE exist in the model and are declared by none.

## 4. CDM changes

`SCHEMA_VERSION` `2.0.0` → **`2.1.0`** (round P3, `version.py:253`), a MINOR: every added path is
optional or is reached only through an optional one, so a 2.0.0 reader keeps working and 2.0.0 data
keeps validating. `PACKAGE_VERSION` is now level with it at `2.1.0` (`version.py:267`), moved by
round PR with the tag.

Added, in `geo.py` and `models.py`: `MultiPoint`/`MultiLineString`/`MultiPolygon` (the geometry
union widened to six), `VerticalPosition`, `VerticalExtent`, `BoundingBox` and the CRS policy;
`SourceHash`, `Period`, `TemporalValidity`, `Waypoint`, `RouteLeg`, `Route`, `Area`, `Quality`,
`OperationalStatus`, `Residual`; seven optional `SourceRef` fields; `Position.vertical`;
`CDMBase.quality`/`status`/`residual`; `PlanObject.validity`/`route`/`area`;
`lossless.residual_block()`; `enums.VerticalUnit` and `VerticalReference`.

Published schemas: `python -m synapse_cdm.schemas --check --out schemas` (from the repository root)
→ `CURRENT: schemas vs models at 2.1.0`, in the working tree and in the fresh clone alike.
`git diff --shortstat v2.0.0..HEAD -- schemas/` → **8 files changed, 3915 insertions(+), 39
deletions(-)**, and `git diff --shortstat v2.1.0..HEAD -- schemas/` → **empty**: nothing a consumer
validates against has moved since the tag, which is the shape a corrective release must have.

Backwards compatibility, derived and not asserted — see section 14 for the goldens.

## 5. Manifests

`manifest.py` (595 lines) and `manifests.py` (round P1, `MANIFEST_SCHEMA_VERSION` `1.0.0` → `1.1.0`
in P4 → **`1.2.0`** now, `version.py:319`), the schema at
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
`suite.py` from the checks that actually ran. Declared, re-read from the sweep this round:
**L4 ×11, L3 ×3**.

Two facts about the ceiling, both readings rather than omissions. The harness's `roundtrip`
column is SKIP for **all fourteen** — `harness.py` cannot compare non-JSON egress bytes and says
so — so an L4 declaration rests on the adapter's own byte-exact round-trip test in `tests/`, named
in each manifest's `maturity.basis`. And L5 is declared by none: the sweep's own
`maturity_eligible` field computes **L3 for the eleven bidirectional ones and L5 for the three
ingest-only ones** — the inversion P2 recorded, because a declared inapplicability does not block a
rung while an undeclared SKIP does. Not resolved here; section 15.

## 7. Conformance

`suite.py` (1140 lines, rounds P2 and PB): fifteen checks A–O, SKIP semantics, `--format json`,
`--require`, and the `synapse` console script.

`synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json` → **exit 0,
fourteen CONFORMANT, no FAIL on any check for any adapter**. That is the required set CI and the
release pipeline use, and the pipeline's own run of it on this commit printed
`14 of 14 CONFORMANT` (section 13).

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
two files, are **byte-identical** (`cmp` reports no difference). That is the property round PB's
change to check H was for, and it is the property this report tests rather than the weaker "no
clock-shaped substring".

The sweep's `generated_with` block names what produced it: `adapter_api` 2.0.0, **`package`
2.1.0**, `schema` 2.1.0. The package number is the one figure in this section that moved since
attempt 5, and it moved because PR's release commit moved `PACKAGE_VERSION`.

## 8. Evidence

`evidence.py` (767 lines, rounds P4 and PB), `EVIDENCE_SCHEMA_VERSION` `1.0.0`, with §34's six
loss categories in `lossless.classify` and §33's `PROVENANCE.json` per fixture directory (39
tracked).

* `python -m synapse_cdm.evidence provenance` → `COMPLETE: 39 fixture directories under §33`.
* `synapse evidence generate --all`, twice into two directories → **14 records each**; comparing
  the two generations leaf by leaf, **the only leaves that differ are the two `evidence.MASKED`
  names** — `generated_at` and `test_run.duration_s`, 14 each, **28** differing leaves over 14
  records and nothing else. The masked comparison is therefore empty for all fourteen.
* `synapse evidence verify` over all fourteen records → **14 REPRODUCED, exit 0**.
* `evidence.MASKED` is exactly `("generated_at", "test_run.duration_s")` (`evidence.py:96`) —
  **two** entries. The third candidate, the refusal record's wall clock, was removed at the source
  by PB rather than masked.
* Loss report, summed over the fourteen: `DROPPED` **0**, `UNSUPPORTED` **0**, `DERIVED` **0**,
  `NORMALIZED` 38, `PRESERVED` 187, `RESIDUAL` 2877; **274** fixtures classified and **264**
  skipped as non-JSON payloads.
* Badges derive from a record and from nothing else: run from a directory with no record,
  `synapse evidence badges` refuses with its reason and **exits 2**.
* Each record names the commit it was generated from: `source_commit`
  `870913cb52a558ea162abc0ab5b2895bc0a1716a`, and `package_version` `2.1.0`.

## 9. Security

`SECURITY.md` (162 lines, round P5): supported versions, reporting, scope, "Telemetry: none",
the controls table, and handling. `.gitleaks.toml` and a `secrets` CI job carry secret scanning;
platform secret scanning and push protection were enabled in P5; the parser-safety policy's
bounds are declared per adapter in each manifest's `capabilities.limits`, with
`absent_because` where no bound is enforced.

* `gitleaks git --log-opts "origin/main..HEAD" --redact --no-banner` → **1 commit scanned, no
  leaks found**, in the working tree and in the fresh clone alike. One commit is the whole arc
  between `origin/main` and this branch now that PR fast-forwarded `main`. The pipeline's own
  gitleaks step, which reads the full history the ref carries, also reads `no leaks found`.
* `gates/codeql_gate.py` over both SARIFs of the CodeQL run on this commit (`codeql.yml` run
  **34343352626**, success; analyses **1747272795** python and **1747271838**
  javascript-typescript, each `results_count` **0**) → **0 result(s), 0 blocking, exit 0** for
  each. The pipeline's own CodeQL gate step reads `0 result(s), 0 blocking`.
* `gh api …/code-scanning/alerts?ref=refs/heads/soif/1.0&state=open` → **zero open**.
* `security/exceptions/` → two exception files (`GHSA-5p2g-fcmc-qvqq.json`,
  `GHSA-w3rx-r6r6-pgpr.json`), `README.md` and `schema.json`. Both files carry all eleven required
  keys, including PB's `mitigation` and `upstream_status`, and both carry `expiry` `2026-11-07` — a
  date the gate reads, after which the exception is dropped rather than honoured.
* No-network proof: `pytest -k "no_network or network"` → **66 passed**, 5116 deselected.

## 10. Dependencies

`.github/dependabot.yml` (pip, github-actions, npm — three ecosystems; weekly; minor+patch
grouped), `dependency-review.yml` at `fail-on-severity: high`, a `supply-chain` CI job running
`pip-audit --strict` twice — over the installed environment and over the wheel's own frozen
closure in a clean venv (round P6) — and a **`docs-audit`** job that runs `npm audit` over `docs/`
at `--audit-level=high` with its allowlist derived from `security/exceptions/` and nothing typed
into the workflow.

**Python: clean, and clean through the mechanism round PP had to build.** This is the item that
stopped the 2.1.0 release, so the reading is taken in full rather than summarised.

The audit runs over an environment that contains the project under release, installed from the
tree. Its version is whatever `version.py` says — at a release commit, the number being released —
and `pip-audit` resolves every distribution against PyPI. Under `--strict` a distribution it cannot
resolve is a collection failure and exit 1, by the tool's own design. So a release commit's audit
asks the index about a version the index cannot have yet, and refuses. Reproduced here, in the
fresh clone, with the ignores the gate derives:

```text
pip-audit --strict --ignore-vuln GHSA-5p2g-fcmc-qvqq --ignore-vuln GHSA-w3rx-r6r6-pgpr
  → exit 1
  ERROR:pip_audit._cli:synapse-cdm: Dependency not found on PyPI and could not be audited:
  synapse-cdm (2.1.0)
```

Round PP's repair is to audit the **third-party closure** and to exclude exactly one distribution
by name — the project under release — by filtering the frozen list and auditing that file:

```text
pip list --format=freeze | grep -v -E '^synapse[-_]cdm=='   →  59 lines → 58
pip-audit --strict --ignore-vuln … -r <the filtered file>   →  exit 0
No known vulnerabilities found
```

`--skip-editable` is **not** the mechanism and cannot be: it does not compose with `--strict`,
which counts a skipped distribution as a collection failure and exits 1 on the very distribution it
was told to skip. That was PP's fork FP.1, taken with the tool in front of it, and it is why the
filter is a line-level exclusion of one name rather than a flag.

**And the gate itself says so, on this commit, in the pipeline.** Step 15 of the `gate` job —
`Security gate — pip-audit, strict`, the step that failed the `v2.1.0` tag run — is **success** in
this round's dispatch, and printed its own two lists before auditing: `--- the installed
environment ---` (44 lines, `synapse-cdm==2.1.0` among them), `removed 1 line(s) naming the project
under release`, `--- the third-party set being audited ---` (43 lines, no `synapse-cdm`), then
`No known vulnerabilities found`. The same repair is in `ci.yml`'s two audits, and the CI run on
this commit (**34343352622**) is **success in all six jobs**.

**npm: clean at the floor the gate enforces.** Read by the `docs-audit` job's own logic —
`npm audit --json` over `docs/`, one advisory per object-valued `via` entry, keyed by GHSA id — in
the fresh clone after `npm ci`, **three advisories**:

| advisory | package | npm severity | excepted | first patched |
|---|---|---|---|---|
| `GHSA-5p2g-fcmc-qvqq` | image-size | high | **yes** | none published |
| `GHSA-w3rx-r6r6-pgpr` | image-size | high | **yes** | none published |
| `GHSA-w5hq-g745-h8pq` | uuid | moderate | no | 11.1.1 |

The gate's blocking set is the high-or-critical ones that are not excepted, and that set is
**empty**: `advisories: 3; excepted and present: ['GHSA-5p2g-fcmc-qvqq', 'GHSA-w3rx-r6r6-pgpr'];
excepted and absent: []`. The bare `npm audit --audit-level=high` still exits **1**, here and on
the runner, and always will while either `image-size` exception is outstanding; the step that
decides is the one above, and the `docs-audit` job is green on this commit.

**Open Dependabot alerts: three, and they are exactly the excepted pair plus one moderate.**
`gh api …/dependabot/alerts?state=open` → **3**: `image-size` ×2 (high, both excepted, no fix
published) and `uuid` ×1 (moderate, below the gate's floor). Attempt 5 read eleven, of which eight
were `fast-uri`, `qs` and `serialize-javascript` alerts that this branch had already upgraded away
and `main` had not; PR's fast-forward of `main` closed all eight. Nothing open is a HIGH with an
available fix.

## 11. SBOM

The pipeline produces both SBOM formats in its `build` job: SPDX-JSON and CycloneDX-JSON from one
`anchore/sbom-action` (syft, pinned) run **over the clean-install environment** the previous step
built, plus a `cyclonedx-py` cross-check over that same environment. §46 asks for both formats
"where supported by tooling" and makes the SBOM a release artefact.

**Green on this commit, in this round's own dispatch.** The `workflow_dispatch` run of
`publish.yml` on `soif/1.0` (run
[34343475612](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/34343475612),
`head_sha` `870913cb52a558ea162abc0ab5b2895bc0a1716a`, created 11:03:05Z, concluded 11:17:06Z
**success**) ran all four SBOM steps green and printed, from its own assertion step:
`SPDX: 19 packages. CycloneDX: 50 components. synapse-cdm at 2.1.0 in both, and in the
cross-check.`

Both documents were downloaded from the run (`gh run download 34343475612`) and re-counted here
rather than trusted:

* `synapse_cdm.spdx.json` → **SPDX-2.3, 19 packages**, with `synapse-cdm 2.1.0` present.
* `synapse_cdm.cdx.json` → **CycloneDX 1.7, 50 components** — 12 `library`, 32 `file`,
  6 `application` — with `synapse-cdm 2.1.0` a `library`, and **12 of 50** declaring a licence.
* **All six** `SHA256SUMS` entries re-derived locally from the downloaded bytes and compared, not
  just the two SBOMs: `9e269253…` wheel, `c35a7e35…` sdist, `6f18c455…` cdx, `f6b3064c…` spdx,
  `ac622c14…` `conformance-2.1.0.json`, `684587e2…` `evidence-2.1.0.tar.gz`. Every one equals the
  run's own entry. `SHA256SUMS` covers **six** artefacts and no more.

## 12. Build provenance

`publish.yml`'s `attest` job (round P7) takes Sigstore build provenance over the wheel, the sdist,
both SBOM files and the evidence archive, then runs `gh attestation verify` against each.
`id-token: write` and `attestations: write` are scoped to that job alone and to no other.

**Proven on this commit.** In run 34343475612 the `attest` job is **success** (11:16:34Z→11:17:05Z),
all seven steps: `Attestation created for 5 subjects`, published at
`https://github.com/Decent-Cybersecurity/synapsecommand-public/attestations/46229189`, and the
verification step opened five `verify` groups — the wheel, the sdist, `sbom/synapse_cdm.cdx.json`,
`sbom/synapse_cdm.spdx.json` and `evidence-2.1.0.tar.gz` — under `set -euo pipefail`, so the job's
green is each verification's exit 0. The signing certificate names this commit and this workflow:
`workflow_dispatch`, `refs/heads/soif/1.0`, `870913cb…`.

`rc-build.yml` (round P6), the other workflow that composes the same artefact set, still cannot be
dispatched at all until it is on the default branch: its first run is necessarily post-release,
which `SECURITY.md` records beside the sentence that assumed otherwise.

## 13. Release procedure

`publish.yml`, 1067 lines, **six jobs, one per §50 stage boundary**, each `needs:` the one before,
so the order is enforced by the dependency graph: `gate` (`:182`) → `build` (`:450`) → `attest`
(`:774`) → `publish` (`:844`) → `release` (`:896`) → `witness` (`:982`). Conditions 1–4 of
`MIGRATIONS.md`'s "What a release requires" are the same text in a different job (1, 3 and the
annotated-tag check in `gate`; 2 and 4 in `build`, because both read `dist/`), and
`tests/test_cdm_trusted_publishing.py` holds them to that. Every `uses:` is a full commit SHA with
a version comment. `publish`, `release` and `witness` are each guarded by
`if: startsWith(github.ref, 'refs/tags/v')`, which is why a branch dispatch cannot upload.

**What the `v2.1.0` tag run did, because that is the fact this qualification exists to answer.**
Run `34332384035`, event `push`, ref `v2.1.0`, head `b69a267e`, created 2026-09-09T09:01:45Z,
conclusion **failure** at 09:08:32Z. `gate` failed; `build`, `attest`, `publish`, `release` and
`witness` were all skipped. Fourteen of the gate job's fifteen substantive steps were green and one
was red: step 15, `Security gate — pip-audit, strict`, on
`synapse-cdm: Dependency not found on PyPI and could not be audited: synapse-cdm (2.1.0)`. Nothing
was uploaded, no Release was created, `pending_deployments` on the run is `0` so no approval hold
ever existed, and the index still serves 2.0.0. Section 10 has the mechanism and the repair.

**This round's dispatch on the repaired commit, stage by stage — every step of every job a branch
can reach is success, and no step of any job failed:**

| §50 stage | job | conclusion |
|---|---|---|
| gate — lint, suite, conformance, security gates, annotated-tag check | `gate` | **success**, 17 steps (Condition 3 and the annotated-tag check `skipped`: they are tag-only) |
| package build, clean install, package test, SBOM ×3, hash, Condition 4 | `build` | **success — all 18 steps** |
| Sigstore build provenance and its verification | `attest` | **success — 5 subjects created and verified** |
| PyPI upload / GitHub Release / witness | `publish`, `release`, `witness` | `skipped` — the tag guard |

Readings the run took of itself, quoted from its log:

* Lint (`ruff`, the narrowed rule set): `All checks passed!`
* Condition 1 — the suite: **5105 passed, 77 skipped** in 253.96s.
* Schemas: `CURRENT: schemas vs models at 2.1.0`. Manifests:
  `CURRENT: manifests vs 14 shipped adapters at manifest schema 1.2.0`.
* Conformance, as one artefact: **14 of 14 CONFORMANT**. Evidence:
  `COMPLETE: 39 fixture directories under §33`.
* Security gates: gitleaks `no leaks found`; **`pip-audit` `No known vulnerabilities found` over
  43 third-party lines with one removed**; CodeQL gate `0 result(s), 0 blocking`.
* Condition 2 — `gates/wheel_install.py` on the runner: **13 checks, 0 failed**, slice
  **3116 passed, 7 skipped**.
* `twine check --strict` on the gated bytes: `PASSED` for the wheel and for the sdist.
* Package test: **14 adapters CONFORMANT from the installed wheel**.
* Condition 4's own re-run of the suite: **5105 passed, 77 skipped** in 347.45s.

CI-side readings on this same commit: `ci.yml` run **34343352622 success** (six jobs — suite/gates/
manifests, conformance, evidence, gitleaks, supply-chain, docs-audit), `codeql.yml` run
**34343352626 success** (two languages, 0 results each). Both were triggered by the branch push
that carried this commit.

* Notes: `synapse release-notes` (`release_notes.py`, 387 lines) renders nine of §52's ten fields
  from the tree and **quotes** the tenth, *major changes*, from `RELEASE_NOTES.md` — refusing when
  that file's heading names another version. Condition 4 stays a person's.
* Witness: `.github/scripts/build_witness.py` builds §53's record in the `witness` job **after**
  the upload, from PyPI's JSON API and the Release API; `gates/witness_verify.py` re-derives every
  digest in it and exits non-zero on any disagreement. `releases/witness/` holds `README.md` and
  no record: a workflow does not commit, so the first record lands in the witness round after the
  release.
* Main advancement: `VERSIONING.md` §5.1 and `MIGRATIONS.md`'s pipeline section carry the same
  commands — `git merge --ff-only soif/1.0`, then the annotated tag on `main`'s new tip. Round PR
  ran both on 2026-09-09, and the fast-forward is why section 1 reads `main` at `b69a267`.

## 14. Existing-adapter regressions

**All fourteen public adapters continue to work, and the CDM change is additive in the goldens as
well as in the schemas.** Derived this round by comparing every golden at `v2.0.0` against the same
file at this commit, leaf by leaf (`git show v2.0.0:<path>` versus `git show HEAD:<path>`, JSON
paths flattened and list indices normalised), and not carried from any earlier report:

| reading | value |
|---|---|
| goldens at `v2.0.0` / at HEAD | 538 / 538 |
| goldens added / removed | 0 / 0 |
| objects compared | 1308 |
| JSON paths **removed** | **0** |
| JSON values **moved** | **1** — `schema_version`, on all 1308 objects |
| JSON paths added | 11: `source.source_hash`, `source.format_name`, `source.format_version`, `source.observed_at`, `source.original_id`, `source.record_index`, `status`, `quality`, `residual` (1308 objects each); `position.vertical` (259) and `samples.position.vertical` (89) |

The two counts in that last row are per OBJECT, which is the figure comparable across reports.

`git diff --name-only v2.1.0..HEAD -- packages/cdm` → **one file**,
`packages/cdm/synapse_cdm/MIGRATIONS.md`: no golden, no model and no adapter has moved since the
tag, which is what a corrective release to the machinery ought to look like.

Fixture verdicts: `gates/wheel_install.py` in the fresh clone reports **1076** over the roster, the
538 run in each of two schema modes, 0 failed, 13 checks 0 failed; the conformance sweep reports
fourteen CONFORMANT with zero FAIL (section 7).

## 15. Known limitations

Everything the campaign deferred, each with where it is recorded. None of these is a blocker;
blockers are section 20, and section 20 is empty.

1. **`v2.1.0` is tagged, on `main`, and the index still serves 2.0.0.** The tag stands on
   `b69a267`; its pipeline refused it at the security gate; no artefact was uploaded and no
   GitHub Release exists. Round PR's `## Stop` made a red job before the hold a STOP, and a pushed
   tag is never moved or deleted, so the recovery is a **corrective 2.1.1** from a later commit —
   M's ruling of 2026-09-09. This report certifies that corrective release, and section 13 records
   what the tag run actually did.
2. **`main`'s own CI is red at `b69a267`**, run `34332377720`, five of six jobs green and the sixth
   the `pip-audit` one, failing on the identical error string. It is the very defect round PP fixed
   on this branch, and it stays red until PR's corrective release commit lands on `main`. Recorded
   by M's ruling as a fact about `main`, not a blocker for this branch — where the same job is
   green (section 10).
3. **48 ruff `F` findings, and no mypy configuration** (round P7). Re-derived this round with
   ruff 0.16.6: **12** in `packages/cdm`, **3** in `gates/`, **33** in `tests/`. The workflow's own
   command, `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests`, prints
   `All checks passed!`: the configured rule set selects `E9`, which finds nothing, while `F` finds
   48 and fixing them means editing shipped modules. Attempt 5 read 47; the one that arrived is in
   `tests/`, with round PP's new test module. Widening the rule set is a round of its own.
4. **`ARCHITECTURE.md:487`'s one-workflow sentence is false** (five workflows exist). §7's job
   table is otherwise satisfied.
5. **`evidence.available` is `false` on all fourteen** and `artifact_hashes` is empty. Both flip
   only when release evidence is generated from a release commit, attached to a Release and
   retrievable by a third party — the release round's, and a test asserts the declared set is
   exactly `{false}` today so the flip cannot happen silently.
6. **Four null `format.version`** (adsb, ais, pntmap, tak). Readings, not omissions: no document
   in the tree names the edition each was written against, and each manifest carries the
   limitation.
7. **L5 is declared by no adapter, and the eligibility inversion of section 6 stands** — the sweep
   computes L3 for the eleven bidirectional ones and L5 for the three ingest-only ones.
8. **The harness's `roundtrip` check is SKIP for all fourteen** — a structural comparison cannot
   compare non-JSON egress bytes. Every L4 claim therefore rests on a per-adapter byte-exact test
   named in the manifest.
9. **Checks E and M are SKIP for all fourteen; I for seven; N for two.** Correct SKIP semantics
   (spec §17: a non-applicable check is never PASS). `publish.yml`'s comment at the step that runs
   the sweep names E, I and M as the excluded set and omits N, which is excluded too — a comment
   one name short of the list beside it.
10. **The determinism/hash collision, still open.** `ARCHITECTURE.md` §4.4 says the determinism
    check hashes and §6.2 fixes sha256; `tests/test_cdm_boundary.py` forbids `hashlib` under
    `synapse_cdm/`. Check G compares canonical serialisations instead, and `evidence.py` is the one
    name the boundary gate allows, narrowed to it by name with two tests policing the allowance.
11. **The fourteen keep legacy residual parking** (`residual: legacy` ×14), by ruling: no golden was
    rewritten for placement.
12. **`defusedxml` is not a dependency**; an entity bomb is refused by libexpat and not by this
    package, which `SECURITY.md` states.
13. **`rc-build.yml` has never run**, and cannot until it is on the default branch.
14. **`gitleaks/gitleaks-action` stays declined** because it requires a paid licence for an
    organisation repository — the CI job runs the binary directly instead.
15. **`security-severity` on `actions` as a third CodeQL language** is available and not enabled;
    two languages are analysed.
16. **This report is not a page of the documentation site.** §57 fixes its path at `docs/`, and
    the site's content root is `docs/docs/`; the sidebar is autogenerated from that directory by
    each page's `sidebar_position`, so no `docs/*.md` report — including
    `docs/sc-oes-release-readiness-report.md`, the precedent — appears in it, and none is linked
    from any page under `docs/docs/`.
17. **A local apparatus directory reds five suite tests in the working tree only.** It is excluded
    at `.git/info/exclude`, so it is invisible to a clone and to every commit, and the tests that
    see it walk the filesystem rather than the git index. A fresh clone of this commit is **0
    failed** (section 17).
18. **Two advisories have no taken fix**: the `image-size` pair, HIGH, excepted because
    `first_patched_version` is `null` and npm's `latest` for that package is the installed version.
    The `uuid` moderate is below the floor the `docs-audit` gate enforces.
19. **`docs/docs/security/supply-chain.mdx` under-describes the two pip-audit layers** as they
    stand after round PP. No test reads those sentences; PP's review named it and no round has been
    authorised to touch it since.

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
`git clone --no-local` of this commit, on `soif/1.0`, with its own venv named `.venv` inside it and
the clone's own distribution installed editable by absolute path.

```bash
# 0  the clone
git clone --no-local <repo> clone && cd clone && git checkout soif/1.0
python3 -m venv .venv && .venv/bin/pip install -e "$PWD/packages/cdm[test]"
pip install build twine pip-audit ruff pyyaml    # what the clone needs and the package does not
# 1  unit + adapter tests
python -m pytest -q                                  # in <clone>, and in the working tree
# 2  conformance
synapse conformance run --all --require A,B,C,D,F,G,H,J,K,L,O --format json   # twice, then cmp
synapse conformance run --all --require A,B,C,D,E,F,G,H,J,K,L,N,O --format json  # the §17 SKIP proof
# 3  packaging
python -m build packages/cdm --outdir dist && twine check --strict dist/*
# 4  clean install
python gates/wheel_install.py
# 5  schema drift  (from the repository ROOT)
python -m synapse_cdm.schemas --check --out schemas
# 6  manifest validation
python -m synapse_cdm.manifests --check --out manifests
python -m pytest -q tests/test_cdm_manifests.py
# 7  evidence
synapse evidence provenance
synapse evidence generate --all --out ev1 && synapse evidence generate --all --out ev2  # then diff
synapse evidence verify ev1/*/*/evidence.json
synapse evidence badges                              # from a directory with no record: exits 2
# 8  security
gitleaks git --log-opts "origin/main..HEAD" --redact --no-banner
gh api repos/<owner>/<repo>/code-scanning/analyses/<id> -H 'Accept: application/sarif+json' \
  | python gates/codeql_gate.py /dev/stdin           # both languages of this commit's run
python -m pytest -q -k "no_network or network"
# 9  dependencies — the layer round PP repaired, both halves
python gates/codeql_gate.py --emit-pip-audit-ignores
pip-audit --strict $(python gates/codeql_gate.py --emit-pip-audit-ignores)   # exit 1, by design
pip list --format=freeze | grep -v -E '^synapse[-_]cdm==' > frozen.txt
pip-audit --strict $(python gates/codeql_gate.py --emit-pip-audit-ignores) -r frozen.txt  # exit 0
npm audit --prefix docs --audit-level=high           # for the log; its status is not the verdict
npm audit --prefix docs --json                       # the verdict, by the docs-audit job's logic
gh api repos/<owner>/<repo>/dependabot/alerts?state=open
# 10 SBOM and provenance
gh workflow run publish.yml --ref soif/1.0 && gh run watch <run>
gh run download <run> && shasum -a 256 <every artefact> # against the run's own SHA256SUMS
# 11 documentation
cd docs && npm ci && npm run build
# 12 the pipeline itself
gh run view <run> --json jobs                        # every step of every job
# 13 lint, for section 15
ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests
ruff check --select F --config packages/cdm/pyproject.toml packages/cdm gates tests
```

Suite figures, at the commit of section 18: **fresh clone → 0 failed, 5107 passed, 75 skipped**
(192.36s), collection 5182. The clone's is the citable figure.

The working tree's run of the same suite reads **5 failed, 5170 passed, 7 skipped** (196.01s), and
both reconcile to the same collection of 5182. The five failures are in three modules
(`test_cdm_changelog_claim.py` ×1, `test_cdm_consumer_path.py` ×3, `test_cdm_deploy_workflow.py`
×1), every one of them naming a file in the local apparatus directory of limitation 17 and no
tracked file. The pass/skip difference between the two runs is the same apparatus: those five tests
pass in the clone, where the directory does not exist.

Documentation check (§56's last item, F8.3 = build only): `npm ci` then `npm run build` in the
fresh clone → `npm ci` exit 0 (1297 packages added from the committed lock, 1298 audited), then
**`[SUCCESS] Generated static files in "build".`, exit 0**, with the `prebuild` schema generator
reporting `0 written, 9 already current (9 files from ../schemas)`.

## 18. Commit

This report describes **`870913cb52a558ea162abc0ab5b2895bc0a1716a`** — round PP's commit, the tip
of `soif/1.0` and, since 2026-09-09T11:01:41Z, its remote tip. `origin/main` is at
`b69a267e3ac7636c25cf878ef2b3cd5163b1b42a`; `git merge-base HEAD origin/main` is that same commit,
so a fast-forward is available. The tag `v2.1.0` names `b69a267` and does **not** contain this
commit: `git merge-base --is-ancestor 870913c v2.1.0` exits 1.

The commit that carries **this file** is the round-P8 commit immediately after it, whose subject
begins `SOIF P8`. Its hash is deliberately not written here: a hash cannot name the commit that
carries it, and a number written before the commit exists is a number nobody re-derived.

## 19. Release status

**The verdict is `ready for PR` (corrective 2.1.1, M's ruling of 2026-09-09)** — §57's own phrase
for an empty blocker list, and this tree earns it. The release round is the next step.

* Every §56 item is green in a fresh clone of this commit — the suite, the conformance sweep,
  packaging, clean install, schema drift, manifest validation, evidence, security analysis,
  dependency analysis, SBOM, and the documentation build.
* **The item that refused the last release is green, on the runner, in the step that refused it.**
  `gate` step 15 is success in this round's dispatch, over 43 third-party lines with exactly one
  removed, and `ci.yml`'s two audits are green on the same commit. That is the specific thing this
  attempt exists to prove, and it is proved by the pipeline rather than argued from the diff.
* The release pipeline is green end to end through every stage a branch can reach: `gate`,
  `build` and `attest`, every step, in run 34343475612.
* The derivation allows the corrective release: `gates/bump_derivation.py --json` reads
  `declared` **2.1.0**, arc `v2.0.0→v2.1.0`, `derived_kind` **MINOR** over **958** signals and
  **42** ruled units, and — for the arc since the tag — `pending` **PATCH**, number **2.1.1**,
  `unruled` **`[]`**. `--mutation-check` → 1 check, 0 failed. M's amended F8.1 requires PATCH or
  NONE for this attempt and refuses MAJOR, MINOR or any unruled unit; the reading is PATCH with an
  empty unruled list.
* `PACKAGE_VERSION` stays **`2.1.0`**, and that is the point. It moved in PR's release commit, with
  the tag; the corrective number moves in the corrective release round, with its tag. The bump gate
  is the reason: it reads its rulings from `### Unreleased` until a tag names the declared version.
* The five other axes are unmoved: `SCHEMA_VERSION` 2.1.0, `SC_OES_VERSION` 0.1.0,
  `ADAPTER_API_VERSION` 2.0.0, `MANIFEST_SCHEMA_VERSION` 1.2.0, `EVIDENCE_SCHEMA_VERSION` 1.0.0.
* `MIGRATIONS.md` carries `### 2.1.0` with the released arc and, above it, `### Unreleased`
  (`:320`) with round PP's record — the corrective arc, one round long so far.
  `RELEASE_NOTES.md` opens `# synapse-cdm 2.1.0`, which is the released version and the version
  this tree is on.

**What "ready" does not decide.** Two things this report cannot supply and does not claim:

1. **M's authorisation of the number.** The release round's own fork FR.1 is unruled by design, and
   the 2.1.0 authorisation was spent on the release that did not complete. Readiness is a property
   of the tree; the decision to release is not.
2. **The fast-forward of `main`.** `git merge --ff-only soif/1.0` on this commit has not been run,
   and a refusal is a stop rather than a merge commit. It is the release round's first act, and no
   reading taken here can predict it — only that `git merge-base HEAD origin/main` equals
   `origin/main`'s tip today, which is the condition a fast-forward needs.

## 20. Blockers

```text
(none)
```

No §56 item is red on this commit, no pipeline stage a branch can reach is red, and nothing in
section 15 rises to a blocker. Attempt 5's report had no blocker either and the release it
certified still failed — because the defect was in a step no branch dispatch could ever exercise,
the one whose input is the index's version list. That step is now exercised in the only way it can
be exercised before a tag exists: its logic no longer depends on the released version being
resolvable, and the step is green here over the same closure it will audit at the tag. Limitations
1 and 2 record the tag and `main`'s red CI, and both are properties of the release that did not
complete rather than of this tree.

## Appendix — §58's definition of done, line by line

Each line of spec §58 with the file that satisfies it, and the ones that are satisfied only as
files because a branch cannot execute them.

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
| dependency review | `dependency-review.yml`, `fail-on-severity: high` | yes, and pull-request-only by the action's own trigger |
| Dependabot | `.github/dependabot.yml`, three ecosystems, and `docs-audit` enforcing its npm findings on every push | yes |
| vulnerability scanning | `pip-audit --strict` over the third-party closure ×3 sites plus `npm audit` at high, in CI and in the release gate | **yes — and green in the release gate at a release version, which is the case round PP repaired** |
| CodeQL | `codeql.yml` + `gates/codeql_gate.py`, 0 blocking | yes |
| SBOM | `publish.yml` `build`, syft over the clean-install environment, both formats, plus a `cyclonedx-py` cross-check | yes — green on this commit |
| build attestation | `publish.yml` `attest`, Sigstore + `gh attestation verify`, 5 subjects | yes — executed and verified on this commit |
| repeatable CI release pipeline | `publish.yml`, six jobs in §50's order, green through `attest` | yes for every stage a branch can reach |
| GitHub Release | `publish.yml` `release`, notes from `synapse release-notes` | written, tag-gated, and never yet executed |
| PyPI publication | `publish.yml` `publish`, OIDC, `pypi` environment | written, tag-gated, and never yet executed |
| witness format | `build_witness.py`, `gates/witness_verify.py`, `releases/witness/README.md` | yes |
| main/release rules | `VERSIONING.md` §5.1, `MIGRATIONS.md`'s pipeline section, exercised by round PR | yes |
| All existing public adapters continue to work | section 14: 0 paths removed, 1 value moved | yes |

**Thirty-five of §58's thirty-seven lines are satisfied.** Two remain satisfied **as files** and
tag-gated by design — the PyPI publication and the GitHub Release — and they cannot execute on a
branch at all. They are the two the `v2.1.0` run never reached, and the corrective release is where
they first run. **None is red.**

Two of the thirty-five carry a qualification worth reading rather than burying: dependency review
runs on pull requests only, because that is what `actions/dependency-review-action` supports, and
the release pipeline's green covers every stage a branch can reach and not the three the tag guard
holds back.

```yaml
blocked: []
```
