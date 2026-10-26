# synapse-cdm 3.9.1

**The HLA sibling release.** Between the 3.9.0 release of 2026-10-25 and this one the tree gained a
third distribution beside the package: `synapse-hla` 1.0.0 under `packages/hla/`, the receive-only
HLA Evolved observer of profile `SC-HLA-RPR2-OBS-1`. It is not an adapter of this package — it
has no manifest and no registry entry, and nothing of it is in the `synapse-cdm` wheel. Inside
this distribution one shipped document moved, `MIGRATIONS.md`, and nothing importable: no
adapter, no flag, no model, no enum, no published CDM schema and no golden. `MIGRATIONS.md`'s
3.9.1 section is the record.

**If you are upgrading from 3.9.0, nothing you read or write changes.** A 3.9.0 reader reads a
3.9.1 object unchanged, no member of the `Adapter` contract moved, and no adapter's output,
verdict or declaration moved.

## Why the number is 3.9.1

**The number is the derived floor: a PATCH from `v3.9.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, reported the pending arc as `{"kind": "PATCH",
"number": "3.9.1", "unruled": []}`. Over the arc its table decides one signal — `MIGRATIONS.md`
on the shipped-document row, PATCH — and there is no unit it cannot decide, so no ruling is
needed or recorded.

**Package version 3.9.1 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are seven MINORs and a PATCH apart. `python -m
synapse_cdm.schemas --check --out schemas` reads `CURRENT: schemas vs models at 3.2.0` and
`python -m synapse_cdm.manifests --check` reads `CURRENT: manifests vs 36 shipped adapters at
manifest schema 2.1.0`. SC-OES is still `0.1.0` and still a Draft.

## What `synapse-hla` is measured to do

The native worker `sc-hla-federate` (C++14, built from the tree against the pinned OpenRTI)
joins an existing federation through OpenRTI's rti1516e API, subscribes to four RPR FOM 2.0
physical-entity attributes and copies every callback, bytes unchanged, to its host; the host
writes a durable, hash-chained capture and reduces each frame as it is written; the projector
writes CDM 3.0.0 `Entity` objects, each validated against the packaged contract; the offline
replay writes the same records from the same capture byte for byte; `synapse-hla` is the command
line, and `sc-hla-publisher`, the synthetic publisher of its demo, is not part of the
receive-only runtime. Its evidence report (`packages/hla/docs/evidence/`), written by the
package's own tool from the runs of one session, reads the offline group `3181 passed` on Python
3.11, 3.12 and 3.14 each, the `rti` group `213 passed`, and the 147 acceptance cases PASS 140,
FAIL 0, BLOCKED 7; the handoff's capture, packaged as a fixture, replays to its 7 expected
observation records byte for byte. Its one allowed claim, verbatim: "Receives and replays the
tested RPR FOM 2.0 physical-entity attribute subset through the pinned OpenRTI baseline and
projects externally timed state into CDM."

## External interoperability is a separate conclusion, and it is NOT claimed

OpenRTI is the tested reference. The evidence report's own terms:

* **Overall status: BLOCKED.**
* **external_customer_interoperability: NOT_TESTED** — no customer simulator and no second RTI
  implementation was tested, and no compatibility with any named simulator, RTI product or
  installation is claimed.
* Every release gate that needs the reference platform (Linux x86_64, Ubuntu 24.04, GCC 13) reads
  BLOCKED: reference encoding and geodesy, the local OpenRTI lifecycle exercise, the reproducible
  build and licence review.
* The performance gate (R42) reads BLOCKED on "R42's recorded 4-vCPU x86_64 machine with 8 GiB on
  the reference platform": R42 was not measured there.
* The evidence is of the classes `DEV-macOS-arm64` and `DEV-linux-aarch64` only, development
  evidence; no run was made on `REFERENCE-linux-x86_64`.
* The gate "no unresolved severity-high defects" reads BLOCKED: the reviews of the tree are kept
  outside it.

## The sibling distributions, on GitHub only

`synapse-hla` 1.0.0 (import `synapse_hla`, command `synapse-hla`, runtime dependency
`synapse-cdm>=3.8.0,<4`) and `synapse-link16-bridge`, still 1.1.0 (`synapse-cdm>=3.5.0,<4`;
nothing under `packages/link16_bridge/` moved since `v3.9.0`), are part of the tag `v3.9.1` and of
the GitHub Release's source archives, and not part of this wheel or of the package index: no
second project is created there in this release, which is an act for the account owner. Each
installs from the tag with `pip install` of a `git+` URL naming its `#subdirectory=packages/…`,
after `synapse-cdm` from the index; `synapse-hla`'s native worker is built from the tree as its
README says, and no workflow runs its tests.

## What changed for a 3.9.0 consumer

* **Nothing importable.** No adapter, module, flag or exit code was added or removed;
  `--list-adapters` still reports thirty-six.
* **One shipped document,** `MIGRATIONS.md`: the 3.9.0 witness record and the `synapse-hla`
  landing paragraph, now this release's section.
* **The wire contract is still 3.2.0.** Every object this package writes is stamped `3.2.0`, as at
  3.9.0, except what the compatibility projections of `link16_gateway` and `cesmo_internal`
  (`cdm_schema="3.0.0"`) write.

## Thirty-six adapters at 3.9.1, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, every verdict read from the run; declared maturity and claim status
are read from `manifests/<name>.json`. `python -m synapse_cdm.harness --list-adapters` prints `36
adapters registered`.

| Adapter | Direction | Fixture verdicts | Declared maturity | Claim |
|---|---|---|---|---|
| `adsb` | bidirectional | 32 | L3 | VERIFIED |
| `ais` | bidirectional | 22 | L3 | VERIFIED |
| `cat021` | bidirectional | 40 | L3 | VERIFIED |
| `cat023` | bidirectional | 34 | L3 | VERIFIED |
| `cat034` | bidirectional | 34 | L3 | VERIFIED |
| `cat048` | bidirectional | 82 | L3 | VERIFIED |
| `cat062` | bidirectional | 56 | L3 | VERIFIED |
| `gmti` | bidirectional | 32 | L3 | VERIFIED |
| `legion` | ingest | 6 | L3 | VERIFIED |
| `pntmap` | ingest | 4 | L3 | VERIFIED |
| `stanag4586` | ingest | 24 | L3 | VERIFIED |
| `stanag4609` | bidirectional | 126 | L3 | VERIFIED |
| `stanag4676` | bidirectional | 34 | L3 | PROVISIONAL |
| `tak` | bidirectional | 12 | L3 | VERIFIED |
| `geojson` | bidirectional | 4 | L4 | VERIFIED |
| `geopackage` | ingest | 8 | L3 | VERIFIED |
| `c2sim` | bidirectional | 10 | L4 | VERIFIED |
| `aixm511` | ingest | 10 | L3 | VERIFIED |
| `aixm52` | ingest | 10 | L3 | VERIFIED |
| `dis7` | bidirectional | 6 | L4 | VERIFIED |
| `tacticalapi` | ingest | 10 | L3 | VERIFIED |
| `link16_gateway` | bidirectional | 15 | L4 | PROVISIONAL |
| `readsb_trace` | ingest | 26 | L3 | VERIFIED |
| `nexrad2` | ingest | 10 | L3 | VERIFIED |
| `ndbc_stdmet` | ingest | 8 | L3 | VERIFIED |
| `coops_csv` | ingest | 7 | L3 | VERIFIED |
| `airnow_hourly` | ingest | 8 | L3 | VERIFIED |
| `grib2` | ingest | 26 | L3 | VERIFIED |
| `cog` | ingest | 20 | L3 | VERIFIED |
| `iem_n0q` | ingest | 8 | L3 | VERIFIED |
| `barentswatch_hais` | ingest | 10 | L3 | VERIFIED |
| `frost_observations` | ingest | 10 | L3 | VERIFIED |
| `cesmo_internal` | ingest | 12 | L3 | PROVISIONAL |
| `stanag4559_catalog` | ingest | 3 | L3 | PROVISIONAL |
| `stanag4559_stream` | ingest | 3 | L3 | PROVISIONAL |
| `stanag4559_workflow` | ingest | 3 | L3 | PROVISIONAL |

**765 fixture verdicts, 0 failed** across the thirty-six, against the published 3.2.0
schemas, every golden byte for byte as 3.9.0 shipped it. The wheel gate's `resources` and
`harness` readings, taken on this tree, are `36 adapters, 801 fixture files` and `36 adapters x 2 schema modes, 1530 fixture verdicts, 0 failed`. The evidence
generator (`python -m synapse_cdm.evidence generate --all`) reads `internal_fixture` PRESENT for
all thirty-six, `self_round_trip` PRESENT for 15 and NOT_APPLICABLE for 21, and
`independent_expected`, `normative_schema` and `independent_endpoint` ABSENT for all thirty-six.
The nine schema files did not move: `git diff v3.9.0 -- schemas/` is empty.

## Published by CI over OIDC, as 1.1.0 through 3.9.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration and entry 31 the 3.9.0 upload. The workflow builds and uploads `synapse-cdm` only.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** with the workflow run
that produced them, not here: a digest is a property of one build rather than of the tree. The
GitHub Release also carries both SBOMs, the evidence set, the conformance report, the witness
record and these notes.

```bash
pip install synapse-cdm==3.9.1
python -m synapse_cdm.harness --list-adapters
```
