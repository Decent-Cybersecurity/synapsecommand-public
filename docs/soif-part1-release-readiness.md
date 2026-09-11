# SOIF Part 1 release-readiness report — 2026-09-11

Written by round P8 (attempt 8) of the SOIF Part 1 campaign (spec §56–§58). Every figure below is
a reading taken on the commit named in section 18, with the command that produced it. Nothing is
carried from a brief or from an earlier attempt: where an earlier report's figure and this tree's
disagree, this tree's is what is written and the disagreement is named.

This report **replaces** the one round P8 wrote as attempt 6 on 2026-09-09 at commit `f2d1c4a`.
That report certified a tree, the release round PR acted on it, and **the release it certified did
not complete**: `main` was fast-forwarded to `4409115`, `v2.1.1` was tagged and pushed, and the
release pipeline refused its own tag at gate step 16 — the CodeQL gate asked the API for an
analysis on `refs/tags/v2.1.1`, and no workflow in this repository can ever produce one on a tag
ref. Nothing was uploaded and no Release was created. That was the second tag lost this way; the
first, `v2.1.0`, died one step earlier at `pip-audit`. Round PP repaired the first gate and round
PQ the second, and this report is the qualification of the twice-repaired machinery.

**Release status: ready for PR (corrective 2.1.2).** Every §56 item is green in a fresh clone of
this commit, the release pipeline is green end to end through `attest` on this exact commit, and
section 20 is empty.

`PACKAGE_VERSION` is `2.1.1` and does not move in this round. M's ruling of 2026-09-08T20:56:31Z
stands: the version, the release heading and `RELEASE_NOTES.md` move in the release round,
atomically with the tag. The corrective number is **2.1.2**, and it is the release round that
types it. `tests/test_cdm_readiness.py` (round PT, amended by PP) is what holds this report to
that rule, and it reads this tree in its **pre-release** mode: the tag `v2.1.1` exists, and it does
not contain the commit this report describes.

**One sentence about what the pipeline run below does and does not prove**, because two releases
were lost to the difference. A `workflow_dispatch` on a branch ref exercises `gate`, `build` and
`attest` over the exact bytes the release round will tag — which is new here, and is why the branch
was pushed before this qualification rather than after it — but it does **not** exercise the
tag-only path. Gate step 16 passed on a branch ref both before round PQ's repair and after it; that
is precisely how `v2.1.0` and `v2.1.1` were both lost. The pre-push proof of the repair is
`gates/release_ref_rehearsal.py`, run against the tag that was refused, and section 17 records it
as such.

---

## 1. Baseline

| what | reading | command |
|---|---|---|
| version the index serves | `2.0.0` | `curl pypi.org/pypi/synapse-cdm/json` → `info.version` `2.0.0`; `"2.1.0" in releases` → `False`; `"2.1.1" in releases` → `False`; `"2.1.2"` → `False` |
| newest tag | `v2.1.1`, on `4409115ba9f762868a08244b97a0a64e55643744` | `git tag --sort=-creatordate \| head -1`; `git rev-list -n1 v2.1.1` |
| `main` | `4409115ba9f762868a08244b97a0a64e55643744`, fast-forwarded by round PR on 2026-09-10 | `git rev-parse origin/main` |
| branch under review | `soif/1.0`, **24 commits** ahead of `v2.0.0`, **1** ahead of `origin/main` | `git rev-list --count v2.0.0..HEAD` → 24; `… origin/main..HEAD` → 1 |
| arc size | **800 files changed, 54341 insertions(+), 4036 deletions(-)** | `git diff --shortstat v2.0.0..HEAD` |
| tags | 14 local, 14 distinct remote (28 raw `ls-remote` lines with peels) | `git tag \| wc -l`; `git ls-remote --tags origin \| grep -v '\^{}' \| wc -l` |

The arc by top-level directory (`git diff --numstat v2.0.0..HEAD`, grouped):

| directory | files | + | − |
|---|---|---|---|
| `packages/` | 673 | 32546 | 3630 |
| `tests/` | 38 | 7355 | 52 |
| `schemas/` | 8 | 3915 | 39 |
| `docs/` | 26 | 3668 | 85 |
| `.github/` | 7 | 2042 | 39 |
| root files | 9 | 1795 | 125 |
| `gates/` | 4 | 1134 | 2 |
| `manifests/` | 14 | 1089 | 0 |
| `examples/` | 14 | 442 | 64 |
| `security/` | 5 | 268 | 0 |
| `releases/` | 1 | 71 | 0 |
| `spec/` | 1 | 16 | 0 |

The twenty-four commits, oldest first: `a9ea68c` (the 2.0.0 witness commit), `5209c1e` P0,
`f28d58e` PA, `441a509` P1, `606e844` P2, `6351fe1` P3, `9069fa9` P4, `e37cf20` P5, `c52e496` P6,
`e540de8` PC, `4ee2788` P7, `a9c0660` P8 (the first qualification), `b9ccb2c` PB, `a214192` P8
(attempt 2), `cca0ec8` PS, `248743d` PT, `a0d5db1` P8 (attempt 4), `1a26576` PD, `b8ec0c5` P8
(attempt 5), `b69a267` PR (the 2.1.0 release transition, and the commit `v2.1.0` names), `870913c`
PP (the repaired pip-audit gate), `f2d1c4a` P8 (attempt 6), `4409115` PR (the 2.1.1 release
transition, and the commit `main` and `v2.1.1` both name), `78b9b4a` PQ (the commit-scoped CodeQL
gate and the pre-push rehearsal module — the commit this report describes).

## 2. Resulting architecture

`ARCHITECTURE.md` (560 lines, round P0) is the frozen contract, in nine sections: Adapter API v2
(§1), direction model (§2), capability and metadata model (§3), core rules 1–6 (§4), residual-field
policy (§5), deterministic behaviour (§6), CI layout (§7), conformance namespaces (§8), and §9's
statement of what the freeze did *not* decide. `VERSIONING.md` (266 lines, P0, §5.1 added by P7)
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
`ADAPTER_API_VERSION` is `2.0.0` (`version.py:300`).

Direction model, re-derived from the fourteen `manifests/*.json` this round: `bidirectional` ×11
and `ingest` ×3. MODEL, TRANSPORT and COMPOSITE exist in the model and are declared by none.

## 4. CDM changes

`SCHEMA_VERSION` `2.0.0` → **`2.1.0`** (round P3, `version.py:262`), a MINOR: every added path is
optional or is reached only through an optional one, so a 2.0.0 reader keeps working and 2.0.0 data
keeps validating. `PACKAGE_VERSION` is `2.1.1` (`version.py:283`), moved by round PR with the
`v2.1.1` tag.

Added, in `geo.py` and `models.py`: `MultiPoint`/`MultiLineString`/`MultiPolygon` (the geometry
union widened to six), `VerticalPosition`, `VerticalExtent`, `BoundingBox` and the CRS policy;
`SourceHash`, `Period`, `TemporalValidity`, `Waypoint`, `RouteLeg`, `Route`, `Area`, `Quality`,
`OperationalStatus`, `Residual`; seven optional `SourceRef` fields; `Position.vertical`;
`CDMBase.quality`/`status`/`residual`; `PlanObject.validity`/`route`/`area`;
`lossless.residual_block()`; `enums.VerticalUnit` and `VerticalReference`.

Published schemas: `python -m synapse_cdm.schemas --check --out schemas` (from the repository root)
→ `CURRENT: schemas vs models at 2.1.0`, in the working tree and in the fresh clone alike.
`git diff --shortstat v2.0.0..HEAD -- schemas/` → **8 files changed, 3915 insertions(+), 39
deletions(-)**, and both `git diff v2.1.0..HEAD -- schemas/` and `git diff v2.1.1..HEAD -- schemas/`
are **empty**: nothing a consumer validates against has moved since either tag, which is the shape
a corrective release must have.

Backwards compatibility, derived and not asserted — see section 14 for the goldens.

## 5. Manifests

`manifest.py` (595 lines) and `manifests.py` (round P1, `MANIFEST_SCHEMA_VERSION` `1.0.0` → `1.1.0`
in P4 → **`1.2.0`** now, `version.py:335`), the schema at
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

The full verdict table, from one `--all` sweep over all fifteen checks:

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
two files, are **byte-identical** (`cmp` reports no difference, exit 0). That is the property round
PB's change to check H was for, and it is the property this report tests rather than the weaker
"no clock-shaped substring".

The sweep's `generated_with` block names what produced it: `adapter_api` 2.0.0, **`package`
2.1.1**, `schema` 2.1.0. The package number is the one figure in this section that moved since
attempt 6, and it moved because PR's 2.1.1 release commit moved `PACKAGE_VERSION`.

## 8. Evidence

`evidence.py` (767 lines, rounds P4 and PB), `EVIDENCE_SCHEMA_VERSION` `1.0.0` (`version.py:349`),
with §34's six loss categories in `lossless.classify` and §33's `PROVENANCE.json` per fixture
directory (39 tracked).

* `synapse evidence provenance` → `COMPLETE: 39 fixture directories under §33`.
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
  `78b9b4a0aa4899ff56ebcf553a65a34cd1c93d0c`, and `package_version` `2.1.1`.

## 9. Security

`SECURITY.md` (162 lines, round P5): supported versions, reporting, scope, "Telemetry: none",
the controls table, and handling. `.gitleaks.toml` and a `secrets` CI job carry secret scanning;
platform secret scanning and push protection were enabled in P5; the parser-safety policy's
bounds are declared per adapter in each manifest's `capabilities.limits`, with
`absent_because` where no bound is enforced.

* `gitleaks git --log-opts "origin/main..HEAD" --redact --no-banner` → **1 commit scanned, no
  leaks found** (~71.17 KB). One commit is the whole arc between `origin/main` and this branch now
  that PR fast-forwarded `main` to `4409115`. The pipeline's own gitleaks step, which reads the
  full history the ref carries, also reads `no leaks found`.
* `gates/codeql_gate.py` over both SARIFs of the CodeQL run on **this** commit (`codeql.yml` run
  **34646157784**, created 20:48:36Z, **success** on both languages; analyses **1764027170**
  python and **1764024626** javascript-typescript, each `results_count` **0**, each on
  `refs/heads/soif/1.0`) → **0 result(s), 0 blocking, exit 0** for each. The release pipeline's own
  CodeQL gate step, now commit-scoped by round PQ, read the same two analyses: `analyses on
  78b9b4a0aa4899ff56ebcf553a65a34cd1c93d0c: 2 (examined 34 record(s) over 1 page(s); bound 5 x
  100)` then `0 result(s), 0 blocking`.
* `gh api …/code-scanning/alerts?ref=refs/heads/soif/1.0&state=open` → **zero open**.
* `security/exceptions/` → two exception files (`GHSA-5p2g-fcmc-qvqq.json`,
  `GHSA-w3rx-r6r6-pgpr.json`), `README.md` and `schema.json`. Both files carry all eleven required
  keys, including PB's `mitigation` and `upstream_status`, and both carry `expiry` `2026-11-07` — a
  date the gate reads, after which the exception is dropped rather than honoured.
* No-network proof: `pytest -k "no_network or network"` → **66 passed**, 5158 deselected.

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
asks the index about a version the index cannot have yet, and refuses. Reproduced here, on this
commit, with the ignores the gate derives:

```text
pip-audit --strict --ignore-vuln GHSA-5p2g-fcmc-qvqq --ignore-vuln GHSA-w3rx-r6r6-pgpr \
          -r <the unfiltered frozen list>
  → exit 1
  ERROR: Could not find a version that satisfies the requirement synapse-cdm==2.1.1
         (from versions: 1.0.0, 1.1.0, 1.2.0, 1.2.1, 1.3.0, 1.4.0, 1.4.1, 1.5.0, 1.6.0, 1.7.0,
          1.8.0, 2.0.0)
  ERROR: No matching distribution found for synapse-cdm==2.1.1
```

Round PP's repair is to audit the **third-party closure** and to exclude exactly one distribution
by name — the project under release — by filtering the frozen list and auditing that file:

```text
pip list --format=freeze | grep -v -E '^synapse[-_]cdm=='   →  19 lines → 18
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
environment ---`, `removed 1 line(s) naming the project under release`, `--- the third-party set
being audited ---`, then `No known vulnerabilities found`. The derived allowlist is printed before
it is used: `derived: [--ignore-vuln GHSA-5p2g-fcmc-qvqq --ignore-vuln GHSA-w3rx-r6r6-pgpr]`. The
same repair is in `ci.yml`'s two audits, and the CI run on this commit (**34646157837**) is
**success in all six jobs**.

**npm: clean at the floor the gate enforces.** Read by the `docs-audit` job's own logic —
`npm audit --json` over `docs/`, one advisory per object-valued `via` entry, keyed by GHSA id —
**three advisories**:

| advisory | package | npm severity | excepted | first patched |
|---|---|---|---|---|
| `GHSA-5p2g-fcmc-qvqq` | image-size | high | **yes** | none published |
| `GHSA-w3rx-r6r6-pgpr` | image-size | high | **yes** | none published |
| `GHSA-w5hq-g745-h8pq` | uuid | moderate | no | 11.1.1 |

The gate's blocking set is the high-or-critical ones that are not excepted, and that set is
**empty**: `advisories: 3; excepted and present: ['GHSA-5p2g-fcmc-qvqq', 'GHSA-w3rx-r6r6-pgpr'];
excepted and absent: []`. The bare `npm audit --audit-level=high` still exits **1** —
`20 vulnerabilities (3 moderate, 17 high)` — here and on the runner, and always will while either
`image-size` exception is outstanding; the step that decides is the one above, and the `docs-audit`
job is green on this commit.

**Open Dependabot alerts: three, and they are exactly the excepted pair plus one moderate.**
`gh api …/dependabot/alerts?state=open` → **3**: `#5` and `#4` `image-size` (high, both excepted,
no fix published) and `#2` `uuid` (moderate, below the gate's floor). Nothing open is a HIGH with
an available fix, and the set is identical to the baseline every prior attempt and both release
attempts recorded.

## 11. SBOM

The pipeline produces both SBOM formats in its `build` job: SPDX-JSON and CycloneDX-JSON from one
`anchore/sbom-action` (syft, pinned) run **over the clean-install environment** the previous step
built, plus a `cyclonedx-py` cross-check over that same environment. §46 asks for both formats
"where supported by tooling" and makes the SBOM a release artefact.

**Green on this commit, in this round's own dispatch.** The `workflow_dispatch` run of
`publish.yml` on `soif/1.0` (run
[34646168965](https://github.com/Decent-Cybersecurity/synapsecommand-public/actions/runs/34646168965),
`head_sha` `78b9b4a0aa4899ff56ebcf553a65a34cd1c93d0c`, created 20:48:43Z, concluded 21:02:39Z
**success**) ran all four SBOM steps green and printed, from its own assertion step:
`SPDX: 19 packages. CycloneDX: 50 components. synapse-cdm at 2.1.1 in both, and in the
cross-check.`

Both documents were downloaded from the run (`gh run download 34646168965`) and re-counted here
rather than trusted:

* `synapse_cdm.spdx.json` → **SPDX-2.3, 19 packages**, with `synapse-cdm 2.1.1` present.
* `synapse_cdm.cdx.json` → **CycloneDX 1.7, 50 components** — 12 `library`, 32 `file`,
  6 `application` — with `synapse-cdm 2.1.1` a `library`, and **12 of 50** declaring a licence.
* **All six** `SHA256SUMS` entries re-derived locally from the downloaded bytes and compared, not
  just the two SBOMs: `d6297c30…` wheel, `8b6f0393…` sdist, `b2292bd2…` cdx, `04713810…` spdx,
  `aa7d680a…` `conformance-2.1.1.json`, `60012f69…` `evidence-2.1.1.tar.gz`. Every one equals the
  run's own entry. `SHA256SUMS` covers **six** artefacts and no more.

## 12. Build provenance

`publish.yml`'s `attest` job (round P7) takes Sigstore build provenance over the wheel, the sdist,
both SBOM files and the evidence archive, then runs `gh attestation verify` against each.
`id-token: write` and `attestations: write` are scoped to that job alone and to no other.

**Proven on this commit.** In run 34646168965 the `attest` job is **success** (21:02:08Z→21:02:38Z),
all seven steps: `Attestation created for 5 subjects`, published at
`https://github.com/Decent-Cybersecurity/synapsecommand-public/attestations/46964151`, and the
verification step opened five `verify` groups — `synapse_cdm-2.1.1-py3-none-any.whl`, the sdist,
`sbom/synapse_cdm.cdx.json`, `sbom/synapse_cdm.spdx.json` and `evidence-2.1.1.tar.gz` — under
`set -euo pipefail`, so the job's green is each verification's exit 0.

`rc-build.yml` (round P6), the other workflow that composes the same artefact set, still cannot be
dispatched at all until it is on the default branch: its first run is necessarily post-release,
which `SECURITY.md` records beside the sentence that assumed otherwise.

## 13. Release procedure

`publish.yml`, 1112 lines, **six jobs, one per §50 stage boundary**, each `needs:` the one before,
so the order is enforced by the dependency graph: `gate` (`:182`) → `build` (`:495`) → `attest`
(`:819`) → `publish` (`:889`) → `release` (`:941`) → `witness` (`:1027`). Conditions 1–4 of
`MIGRATIONS.md`'s "What a release requires" are the same text in a different job (1, 3 and the
annotated-tag check in `gate`; 2 and 4 in `build`, because both read `dist/`), and
`tests/test_cdm_trusted_publishing.py` holds them to that. Every `uses:` is a full commit SHA with
a version comment. `publish`, `release` and `witness` are each guarded by
`if: startsWith(github.ref, 'refs/tags/v')`, which is why a branch dispatch cannot upload.

**Two tags stand tagged-and-never-published, and both are recorded here because they are what this
qualification exists to answer.**

| tag | commit | instant | run | died at | why |
|---|---|---|---|---|---|
| `v2.1.0` | `b69a267e3ac7636c25cf878ef2b3cd5163b1b42a` | 2026-09-09T09:01:45Z (run created) | `34332384035` | `gate` **step 15 of 17**, `Security gate — pip-audit, strict` | `synapse-cdm: Dependency not found on PyPI and could not be audited: synapse-cdm (2.1.0)` — the audit asked the index about the version being released. Repaired by round PP. |
| `v2.1.1` | `4409115ba9f762868a08244b97a0a64e55643744` | 2026-09-10T07:59:24Z (tag pushed) | `34452755466` | `gate` **step 16 of 17**, `Security gate — CodeQL` | the step queried `…/code-scanning/analyses?ref=${GITHUB_REF}` — `refs/tags/v2.1.1` — and no workflow in this repository scans a tag ref. The commit HAD two analyses, on `refs/heads/main`, four minutes before the query. Repaired by round PQ. |

For each: `build`, `attest`, `publish`, `release` and `witness` were all skipped, nothing was
uploaded, no GitHub Release was created, `pending_deployments` was `0` so no approval hold ever
existed, and the index still serves 2.0.0. Neither tag is moved or deleted; the recovery is a
corrective **2.1.2** from this commit.

**This round's dispatch on the twice-repaired commit, stage by stage — every step of every job a
branch can reach is success, and no step of any job failed:**

| §50 stage | job | conclusion |
|---|---|---|
| gate — lint, suite, conformance, security gates, annotated-tag check | `gate` | **success**, 17 steps (Condition 3 and the annotated-tag check `skipped`: they are tag-only) |
| package build, clean install, package test, SBOM ×3, hash, Condition 4 | `build` | **success — all 18 steps** |
| Sigstore build provenance and its verification | `attest` | **success — 5 subjects created and verified** |
| PyPI upload / GitHub Release / witness | `publish`, `release`, `witness` | `skipped` — the tag guard |

Readings the run took of itself, quoted from its log:

* Lint (`ruff`, the narrowed rule set): `All checks passed!`
* Condition 1 — the suite: **5147 passed, 77 skipped** in 347.63s.
* Schemas: `CURRENT: schemas vs models at 2.1.0`. Manifests:
  `CURRENT: manifests vs 14 shipped adapters at manifest schema 1.2.0`.
* Conformance, as one artefact: **14 of 14 CONFORMANT**. Evidence:
  `COMPLETE: 39 fixture directories under §33`.
* Security gates: gitleaks `no leaks found`; **`pip-audit` `No known vulnerabilities found` with
  one line removed**; **CodeQL `analyses on 78b9b4a0…: 2` then `0 result(s), 0 blocking`** — the
  step that refused `v2.1.1`, now selecting on the commit.
* Condition 2 — `gates/wheel_install.py` on the runner: **13 checks, 0 failed**, slice
  **3116 passed, 7 skipped**.
* `twine check --strict` on the gated bytes: `PASSED` for the wheel and for the sdist.
* Package test: **14 adapters CONFORMANT from the installed wheel**.
* Condition 4's own re-run of the suite: **5147 passed, 77 skipped** in 266.11s.

**What this dispatch does not prove, stated here so no later reader mistakes it.** Gate step 16
passes on a **branch** ref both before round PQ's repair and after it — the query the old step made
was satisfiable for a branch and unsatisfiable for a tag — so a green branch dispatch is not a test
of the repair. It is a test of every other thing: the exact bytes PR will tag, gated, built,
installed clean, SBOM'd, hashed and attested. The pre-push proof of the repair is
`gates/release_ref_rehearsal.py` (section 17), and the release round runs it against `v2.1.2`
before the tag is pushed.

CI-side readings on this same commit: `ci.yml` run **34646157837 success** (six jobs — suite/gates/
manifests, conformance, evidence, gitleaks, supply-chain, docs-audit), `codeql.yml` run
**34646157784 success** (two languages, 0 results each). Both were triggered by the branch push
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
  ran both twice, and the second fast-forward is why section 1 reads `main` at `4409115`.

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

`git diff --name-only v2.1.1..HEAD -- packages/cdm` → **one file**,
`packages/cdm/synapse_cdm/MIGRATIONS.md`: no golden, no model and no adapter has moved since the
newest tag, which is what a corrective release to the release machinery ought to look like.

Fixture verdicts: `gates/wheel_install.py` reports **1076** over the roster (14 adapters × 2 schema
modes), 0 failed, 13 checks 0 failed, manifest 1424 files, resources 14 adapters / 552 fixture
files; the conformance sweep reports fourteen CONFORMANT with zero FAIL (section 7).

## 15. Known limitations

Everything the campaign deferred, each with where it is recorded. None of these is a blocker;
blockers are section 20, and section 20 is empty.

1. **`v2.1.0` and `v2.1.1` are both tagged, both on `main`'s history, and the index still serves
   2.0.0.** Section 13 has the table: what each run did, the step it died at, and the round that
   repaired that step. No artefact was uploaded and no GitHub Release exists for either. Round PR's
   `## Stop` made a red job before the hold a STOP, and a pushed tag is never moved or deleted, so
   the recovery is a **corrective 2.1.2** from this commit.
2. **A branch dispatch cannot exercise the tag-only path.** Gate step 16 is green on a branch ref
   with the old code and with the new; the same was true of nothing else, which is why step 15's
   defect survived one release and step 16's survived two. The mitigation is
   `gates/release_ref_rehearsal.py`, which replays every ref-dependent step against a real tag
   before it is pushed, and whose coverage assertion fails if a new ref use appears uncovered.
3. **48 ruff `F` findings, and no mypy configuration** (round P7). Re-derived this round with
   ruff 0.16.6: **12** in `packages/cdm`, **3** in `gates/`, **33** in `tests/`. The workflow's own
   command, `ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests`, prints
   `All checks passed!`: the configured rule set selects `E9`, which finds nothing, while `F` finds
   48 and fixing them means editing shipped modules. Widening the rule set is a round of its own.
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
20. **The local environment was rebuilt on 2026-09-10** and this repository pins no lock file for
    it, so the rebuild is a re-resolution: `Python 3.14.7`, `pytest 9.1.1`, and `pip-audit`,
    `build`, `twine`, `ruff` and `cyclonedx-py` provisioned into a throwaway virtual environment
    beside it. Skip counts from this environment are therefore **not** comparable with any figure
    taken before that date; the binding invariant is the failure set, and it is named in section 17.

## 16. Intentionally deferred work

The spec's own §2 non-goals, and what Part 1 deliberately left to Part 2:

* **No new adapter portfolio.** Spec §55: the release "does NOT claim the new adapter portfolio
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
`git clone --no-local -b soif/1.0` of this commit, run on the same interpreter, which sits outside
it.

```bash
# 0  the clone
git clone --no-local -b soif/1.0 <repo> <clone>
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
gh api "repos/<owner>/<repo>/code-scanning/alerts?ref=refs/heads/soif/1.0&state=open"
python -m pytest -q -k "no_network or network"
# 9  dependencies — the layer round PP repaired, both halves
python gates/codeql_gate.py --emit-pip-audit-ignores
pip list --format=freeze > all.txt
pip-audit --strict $(… ignores) -r all.txt                       # exit 1, by design
grep -v -E '^synapse[-_]cdm==' all.txt > frozen.txt
pip-audit --strict $(… ignores) -r frozen.txt                    # exit 0
npm audit --prefix docs --audit-level=high           # for the log; its status is not the verdict
npm audit --prefix docs --json                       # the verdict, by the docs-audit job's logic
gh api repos/<owner>/<repo>/dependabot/alerts?state=open
# 10 SBOM and provenance
gh workflow run publish.yml --ref soif/1.0 && gh run watch <run>
gh run download <run> && shasum -a 256 <every artefact> # against the run's own SHA256SUMS
# 11 documentation
cd <clone>/docs && npm ci && npm run build
# 12 the pipeline itself
gh run view <run> --json jobs                        # every step of every job
gh api repos/<owner>/<repo>/actions/jobs/<job>/logs  # the lines each gate printed
# 13 the ref-dependent steps, before any tag is pushed
python gates/release_ref_rehearsal.py --tag v2.1.1 --commit 4409115ba9f762868a08244b97a0a64e55643744
# 14 lint, for section 15
ruff check --config packages/cdm/pyproject.toml packages/cdm gates tests
ruff check --select F --config packages/cdm/pyproject.toml packages/cdm gates tests
```

Suite figures, at the commit of section 18: **fresh clone → 0 failed, 5148 passed, 76 skipped**
(158.67s), collection 5224. The clone's is the citable figure.

The working tree's run of the same suite reads **5 failed, 5144 passed, 75 skipped** (170.65s), and
both reconcile to the same collection of 5224. The five failures are in three modules —
`test_cdm_changelog_claim.py`'s sweep for the retired copy-claim about the changelog page (its id
is described rather than quoted: the id itself carries the pairing that check bans, and this
document is inside the sweep, so `MIGRATIONS.md`'s elision of its own pending-arc heading token is
followed here),
`test_cdm_consumer_path.py` ×3 and
`test_cdm_deploy_workflow.py::test_the_site_list_is_exactly_the_files_that_state_the_mechanism` —
every one of them naming a file in the local apparatus directory of limitation 17 and no tracked
file. **The binding invariant is that failure set: those five and no sixth.** The pass/skip
difference between the two runs is the same apparatus plus the virtual environment sitting inside
the tree and outside the clone, and neither skip count is comparable with a figure taken before the
2026-09-10 environment rebuild (limitation 20).

**Correction, 2026-09-11, appended by the round that repairs this file.** The paragraph above was
true of the commit section 18 names and was NOT true of the commit that first carried this report.
That commit quoted whole the id of the check the paragraph describes, and the id itself carries the
pairing that check bans — so this report became the one TRACKED offender against it, at this file's
line 621 as it then stood. Measured, not inferred: a fresh clone of that commit read **1 failed,
5147 passed, 76 skipped** with `docs/soif-part1-release-readiness.md:621` the whole offender list,
`git log -S` put the pairing in that commit and in no earlier one, and the push run 34649439341 was
red on its `Suite, gates and manifests` job for that line alone. The sentence "and no tracked file"
above is corrected to read: no tracked file other than this one, and only until this repair. The
line is now narrowed to describe the check instead of quoting it, and the sweep over the tracked
tree is empty again; the in-tree run still reports the failure, because the apparatus directory of
limitation 17 is untracked yet sits inside the repository and inside the sweep.

**The ref-dependent steps, rehearsed against a real tag.** `gates/release_ref_rehearsal.py`
(484 lines, round PQ) replays each step of `publish.yml` whose behaviour depends on the ref, against
a tag and the live API, before that tag is pushed. Against `v2.1.1` and `4409115b…` — the tag the
pipeline refused on 2026-09-10 — it runs **7 checks, 0 failed, exit 0**:

```text
PASS  tag guard           v2.1.1 satisfies startsWith(github.ref, 'refs/tags/v')
PASS  condition 3         tag=v2.1.1  PACKAGE_VERSION=2.1.1
PASS  annotated tag       v2.1.1 is a tag object 68d3a3c4
PASS  codeql gate         analyses on 4409115b…: 2 (1753266107, 1753264364); 0 result(s), 0 blocking
PASS  version sites       5 site(s) derive ${GITHUB_REF_NAME#v}; v2.1.1[1:] == 2.1.1
PASS  release name free   no GitHub Release is named v2.1.1 yet
PASS  ref use coverage    22 ref use(s) over 14 covered-use entries, 0 uncovered
```

That run is the proof of the repair, because it asks the API the question the tag run asked and
gets the answer the tag run could not. Run against a tag that does not exist yet
(`--tag v2.1.2 --commit 78b9b4a0…`) the module stops at its second check —
`condition 3: v2.1.2 points at a tree whose PACKAGE_VERSION is 2.1.1` — and says `the tag is still
local; do NOT push it`. That red is expected at qualification time and is not a blocker: the
version moves in the release round, with the tag, and the release round's own mandatory act is to
run this module again, green, before it pushes.

Documentation check (§56's last item, F8.3 = build only): `npm ci` then `npm run build` in the
fresh clone → `npm ci` exit 0 (1297 packages added from the committed lock, 1298 audited), then
**`[SUCCESS] Generated static files in "build".`, exit 0**, with the `prebuild` schema generator
reporting `0 written, 9 already current (9 files from ../schemas)`.

## 18. Commit

This report describes **`78b9b4a0aa4899ff56ebcf553a65a34cd1c93d0c`** — round PQ's commit and the tip
of `soif/1.0`, pushed to `origin/soif/1.0` at 2026-09-11T20:48:34Z (`f2d1c4a..78b9b4a`, a
fast-forward, no force, no tags) so that the pipeline could be dispatched at the exact bytes this
report certifies. `origin/main` is at `4409115ba9f762868a08244b97a0a64e55643744`;
`git merge-base HEAD origin/main` is that same commit, so a fast-forward is available. The tag
`v2.1.1` names `4409115` and does **not** contain this commit:
`git merge-base --is-ancestor 78b9b4a v2.1.1` exits 1.

The commit that carries **this file** is the round-P8 commit immediately after it, whose subject
begins `SOIF P8`. Its hash is deliberately not written here: a hash cannot name the commit that
carries it, and a number written before the commit exists is a number nobody re-derived.

## 19. Release status

**The verdict is `ready for PR` (corrective 2.1.2)** — §57's own phrase for an empty blocker list,
and this tree earns it. The release round is the next step.

* Every §56 item is green in a fresh clone of this commit — the suite, the conformance sweep,
  packaging, clean install, schema drift, manifest validation, evidence, security analysis,
  dependency analysis, SBOM, and the documentation build.

  **Correction, 2026-09-11.** True of the commit section 18 names, and not of the commit that first
  carried this file: that commit's own copy of this report failed one tracked check, so a fresh
  clone of IT read 1 failed / 5147 passed / 76 skipped. Section 17's correction has the readings.
  The same qualification applies to the identical sentence in this document's opening summary. The
  repair is one narrowed line in section 17 plus these two dated corrections and nothing else — no
  code, no gate, no schema and no §56 figure moves with it.
* **Both steps that refused a tag are green on the runner, on this commit, in the steps that
  refused them.** `gate` step 15 (pip-audit) is success with one line removed from the closure, and
  `gate` step 16 (CodeQL) is success reading `analyses on 78b9b4a0…: 2`. Step 16's green on a
  branch ref is not by itself the proof of PQ's repair — section 13 says so plainly — and the proof
  is the rehearsal module's run against `v2.1.1` in section 17.
* The release pipeline is green end to end through every stage a branch can reach: `gate`,
  `build` and `attest`, every step, in run 34646168965 at this exact commit. No previous
  qualification could say "at this exact commit": the branch was pushed first, under M's ruling of
  2026-09-11, so that the dispatch and the certification name the same bytes.
* The derivation allows the corrective release: `gates/bump_derivation.py --json` reads
  `declared` **2.1.1**, arc `v2.1.0`→`v2.1.1`, `derived_kind` **PATCH** over one signal
  (`synapse_cdm/MIGRATIONS.md`), and `pending` **PATCH**, number **2.1.2**, `unruled` **`[]`**.
  M's amended F8.1 requires PATCH or NONE for this attempt and refuses MAJOR, MINOR or any unruled
  unit; the reading is PATCH with an empty unruled list.
* `PACKAGE_VERSION` stays **`2.1.1`**, and that is the point. It moves in the corrective release
  commit, with the corrective tag. The bump gate is the reason: it reads its rulings from
  `### Unreleased` until a tag names the declared version.
* The five other axes are unmoved: `SCHEMA_VERSION` 2.1.0, `SC_OES_VERSION` 0.1.0,
  `ADAPTER_API_VERSION` 2.0.0, `MANIFEST_SCHEMA_VERSION` 1.2.0, `EVIDENCE_SCHEMA_VERSION` 1.0.0.
* `MIGRATIONS.md` carries `### 2.1.1` (`:385`) with the published-arc record and, above it,
  `### Unreleased` (`:334`) with round PQ's record — the corrective arc, one round long so far.
  `RELEASE_NOTES.md` opens `# synapse-cdm 2.1.1`, which is the version this tree is on.

**What "ready" does not decide.** Two things this report cannot supply and does not claim:

1. **M's authorisation of the number.** The release round's own fork FR.1 is unruled by design, and
   the 2.1.0 and 2.1.1 authorisations were both spent on releases that did not complete. Readiness
   is a property of the tree; the decision to release is not.
2. **The fast-forward of `main`.** `git merge --ff-only soif/1.0` on this commit has not been run,
   and a refusal is a stop rather than a merge commit. It is the release round's first act, and no
   reading taken here can predict it — only that `git merge-base HEAD origin/main` equals
   `origin/main`'s tip today, which is the condition a fast-forward needs.

## 20. Blockers

```text
(none)
```

No §56 item is red on this commit, no pipeline stage a branch can reach is red, and nothing in
section 15 rises to a blocker. Two earlier reports also had no blocker and the releases they
certified still failed — because each defect lived in a step no branch dispatch could exercise: one
whose input was the index's version list, one whose input was the ref. Both are repaired, both are
green here, and the second is additionally proved by a module that replays the ref-dependent steps
against a real tag before it is pushed. Limitations 1 and 2 record the two standing tags and the
structural limit of a branch dispatch, and both are properties of the releases that did not
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
| CodeQL | `codeql.yml` + `gates/codeql_gate.py`, 0 blocking, and the release gate now selects the analysis by COMMIT | **yes — and the case round PQ repaired is proved by `release_ref_rehearsal.py` against `v2.1.1`, not by this branch dispatch** |
| SBOM | `publish.yml` `build`, syft over the clean-install environment, both formats, plus a `cyclonedx-py` cross-check | yes — green on this commit |
| build attestation | `publish.yml` `attest`, Sigstore + `gh attestation verify`, 5 subjects | yes — executed and verified on this commit |
| repeatable CI release pipeline | `publish.yml`, six jobs in §50's order, green through `attest` | yes for every stage a branch can reach |
| GitHub Release | `publish.yml` `release`, notes from `synapse release-notes` | written, tag-gated, and never yet executed |
| PyPI publication | `publish.yml` `publish`, OIDC, `pypi` environment | written, tag-gated, and never yet executed |
| witness format | `build_witness.py`, `gates/witness_verify.py`, `releases/witness/README.md` | yes |
| main/release rules | `VERSIONING.md` §5.1, `MIGRATIONS.md`'s pipeline section, exercised twice by round PR | yes |
| All existing public adapters continue to work | section 14: 0 paths removed, 1 value moved | yes |

**Thirty-five of §58's thirty-seven lines are satisfied.** Two remain satisfied **as files** and
tag-gated by design — the PyPI publication and the GitHub Release — and they cannot execute on a
branch at all. They are the two neither refused tag run ever reached, and the corrective release is
where they first run. **None is red.**

Two of the thirty-five carry a qualification worth reading rather than burying: dependency review
runs on pull requests only, because that is what `actions/dependency-review-action` supports, and
the release pipeline's green covers every stage a branch can reach and not the three the tag guard
holds back.

```yaml
blocked: []
```
