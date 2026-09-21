# synapse-cdm 3.1.0

**The adapter expansion release.** Between the 3.0.1 release of 2026-09-20 and this one, the tree
gained five adapter modules — `geojson` (#16), `geopackage` (#17), `c2sim` (#18), `aixm511` (#19)
and `aixm52` (#20) — and the registry moved from fourteen to nineteen. Two are bidirectional,
three ingest-only. Each ships pinned synthetic fixtures with a parsed twin per document, a
field-level preservation ledger (`MAPPINGS`), adversarial tests that detect a wrong mapping, a
structured residual, declared and enforced parser bounds, a manifest, and a harness and
conformance reading of CONFORMANT. Three shared modules landed with them: `secure_xml` (the one
guarded XML parse every XML adapter goes through), `normative_validation` (the schema-validation
hook behind the optional `validate` extra) and `aixm_resolve` (effective AIXM state from explicit
prior state — no file, no socket, no clock). Nothing on the wire moved: `SCHEMA_VERSION` stays
`3.0.0`, no model, enum or published schema changed, and no golden of the fourteen that predate
the arc moved by a byte. The design records are D1 to D67 in
`docs/adapter-expansion-implementation.md`, which ships in nothing.

**If you are upgrading from 3.0.1, nothing you read or write changes.** A 3.0.1 reader reads a
3.1.0 object unchanged and `version.compatible("3.0.0", "3.0.0")` is the same answer it was; the
typed blocks the five new adapter modules carry (`geo-object/1`, `geopackage`'s package block, `c2sim-order/1`,
`aixm-timeslice/1`, `aixm-dnotam/1`) are named, versioned payload contracts under fields the
3.0.0 schema already has. If you are upgrading from 2.2.0 or earlier, read the 3.0.1 notes first —
they are the body of the `v3.0.1` Release and describe the MAJOR on both of the first two axes —
and everything they describe is still here.

## Why the number is 3.1.0

**The number is the derived floor.** `gates/bump_derivation.py --json`, run before any number was
typed, reported the arc since `v3.0.1` as `{"kind": "MINOR", "number": "3.1.0", "unruled": []}`;
on the release commit `--mutation-check` reads `1 check, 0 failed`. The floor comes from the
public names the arc added and from nothing removed — five `Adapter` subclasses with their codec
modules, three shared modules, five fixture sets and the `validate` optional extra — and the nine
units the table cannot decide on its own (`lossless.Mapping`, `RULES`, `parse_path`,
`render_path`, `_match_pattern`, `_targets`, `_check_field` and `ledger` for the ledger grammar's
additive `#[*]`, `[_]` and `numeric_text`; `suite.check_temporal` for the declared
`no-source-time` skip) are every one ruled MINOR in `MIGRATIONS.md`'s 3.1.0 section, which the
gate reads and reports nothing unruled. It is the second number in a row that moved for what the
distribution carries rather than for what a workflow refused.

**Package version 3.1.0 · CDM `schema_version` 3.0.0 · Adapter API 3.0.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are a MINOR apart for the ordinary reason: the surface
grew and the contract did not. `python -m synapse_cdm.schemas --check --out schemas` reads
`CURRENT: schemas vs models at 3.0.0` and `python -m synapse_cdm.manifests --check` reads
`CURRENT: manifests vs 19 shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`,
`MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` stay where the 3.0.0 release put them:
no member of `Adapter`'s contract, no manifest field and no evidence field moved. SC-OES, the
Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is still `0.1.0` and
still a Draft. `synapse_cdm/version.py` states the nine version axes and their independence, and
`tests/test_cdm_packaging.py` sweeps the package for an assignment that would derive one number
from another.

## The five, and what each one is measured to do

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `geojson` | RFC 7946 (Feature, FeatureCollection, the seven geometry types; WGS 84 / CRS84 only, no `crs`) | bidirectional | `geo-object/1` contract, `exchange` and `mirror` export profiles, `no-source-time` declared |
| `geopackage` | OGC GeoPackage 1.4.0 (OGC 12-128r19), feature tables under EPSG:4326 / CRS84 / 4979 | ingest | in-memory read-only authorized snapshot; GDAL 3.13.3 wrote every fixture and is the independent reading |
| `c2sim` | SISO-STD-019-2020 v1.0 + SISO-STD-020-2020 (LOX), C2SIMArtifacts v1.0.1 | bidirectional | initialisation, `MoveToLocation` / `HoldInPlace` orders, position / observation / status reports; `c2sim-order/1` payload contract |
| `aixm511` | AIXM 5.1.1 (April 2016) + Digital NOTAM Event Schema 2.0.m, four pinned scenario profiles | ingest | one `Entity` per time slice, `aixm-timeslice/1` and `aixm-dnotam/1` blocks, `synapse_cdm.aixm_resolve` for effective state from explicit prior state |
| `aixm52` | AIXM 5.2 (schema release 5.2.0, 17 January 2025) | ingest | a second profile on `aixm511`'s reader; Digital NOTAM declared NOT available on 5.2 |

**What is refused, by name.** GeoJSON: `GeometryCollection`, a bare geometry, empty coordinates,
the 2008 `crs` member, a non-finite number, an unclosed ring. GeoPackage: any CRS other than the
three named, measured (M) geometry, `GeometryCollection` rows, non-linear and user-defined
geometry types, a WAL-dependent header, a `user_version` other than 1.4.0 — each refuses the
package whole with the offending row or declaration named — while raster tiles, gridded
coverages, attributes-only tables and views are inventoried as unsupported content and the
supported layers still translate. C2SIM: a system
command body, an unsupported task code, a `SimulationTime` with no caller `ExerciseClock`, a
relative-time observation. AIXM: arcs and circles by centre point (by default; typed as
unsupported on request), a projected CRS, three-dimensional positions, an `xi:include`, a slice
with no `gml:identifier`, and — on every XML adapter, through `secure_xml` — a DTD, an entity
reference, a document past the declared depth or byte bound. Every refusal is asserted by name
in the adapter's tests — most on a committed fixture under `malformed/` or `counterexamples/`,
the bounds on inputs the tests generate rather than commit.

**Digital NOTAM is read on the specification's DRAFT.** The four scenario profiles `aixm511`
pins — RWY.CLS, ATSA.ACT, SAA.ACT, NAV.UNS — are read from Digital NOTAM Specification 2.0 as
published in draft, whose rule numbering may move; the Event Schema 2.0.m is the schema the
fixtures validate against. `aixm52` declares Digital NOTAM NOT available, because no Event Schema
release binds to AIXM 5.2.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions.
The first is reached and this release claims it. The second is not claimed anywhere in the tree:
no certification, deployment, partner exchange or reference-server session is asserted for any of
the five.

* **Normative schema validation** of every positive fixture against the pinned XSD closures
  (C2SIMArtifacts v1.0.1, AIXM 5.1.1 with the Event Schema 2.0.m, AIXM 5.2.0) is a test that runs
  only where the schemas are held OUTSIDE this repository — no XSD is mirrored into the tree — and
  the optional `validate` extra (`pip install "synapse-cdm[validate]"`, lxml 6.1.3, the only
  non-standard-library import and the only optional one) is installed; it records
  `BLOCKED_EXTERNAL_EVIDENCE` otherwise. No runtime dependency changed.
* **The five evidence categories**, as measured on 2026-09-21 by the arc's Phase 7 and recorded in
  `docs/adapter-expansion-implementation.md`'s Handoff §5 — the records themselves are generated,
  gitignored, and attached by a Release rather than committed: `internal_fixture` PRESENT on all
  five; `self_round_trip` PRESENT on `geojson` and `c2sim`, NOT_APPLICABLE on the three ingest-only;
  `independent_expected` PRESENT only where GDAL 3.13.3 read the format (`geojson`, `geopackage`)
  and ABSENT on `c2sim`, `aixm511` and `aixm52`; `normative_schema` PRESENT on `c2sim`, `aixm511`
  and `aixm52` and ABSENT on the two formats no normative schema exists for; and
  **`independent_endpoint` ABSENT on every one of the five** — no partner system, reference server
  or exercise has been exchanged with, and `examples/c2sim/exercise_client.py` is the opt-in
  procedure, not a result.
* **`evidence.available` is `true` on all five, from this release and on this release's own
  ground.** The arc landed the five declaring `false` — "no published Release carries this
  adapter's records yet; it becomes true at the first release that attaches them" — and
  `tests/test_cdm_evidence.py` holds the field to the newest release tag's tree: an adapter the
  tag carries declares `true`. 3.1.0 is that first release, `.github/workflows/publish.yml`'s
  evidence job generates the records for every shipped adapter and its release job attaches
  `evidence-3.1.0.tar.gz` to the `v3.1.0` Release, so the release commit flips the five
  (`manifests/<name>.json` regenerated) and each limitation says so in words. What the field does
  NOT say: nothing about the wheel's contents, and nothing about the three external categories —
  a record can be retrievable and still read ABSENT for `independent_endpoint`.

## What changed for a 3.0.1 consumer

* **Nothing on the wire.** No field, enum, schema or golden of the fourteen that predate the arc
  moved; `git diff v3.0.1 -- schemas/` is empty.
* **The preservation-ledger grammar grew, additively.** A `MAPPINGS` ledger may now name an
  index-bound target `#[*]`, an unbound source wildcard `[_]` and the `numeric_text` rule; every
  ledger that parsed before parses to the same mappings, and a destination carrying `[_]` is
  refused rather than read (`tests/test_cdm_preservation.py` asserts the grammar round trip and
  the fourteen legacy ledgers' verdicts).
* **The conformance suite's check J reads a declared inapplicability.** An adapter that emits no
  timestamp AND carries the structured limitation `no-source-time` reads a DECLARED SKIP
  (`declared_inapplicable: true`); one that declares nothing reads the undeclared SKIP it read
  before. `geojson` and `geopackage` declare it: both translate formats that state no instant.
* **Five new fixture directories** ship in the package (`fixtures/{geojson,geopackage,c2sim,
  aixm511,aixm52}/`), each with a `spec/*_pin.json` that hashes every file and a
  `PROVENANCE.json` per directory; `--list-adapters` reports nineteen and the harness replays any
  of them with `--adapter <name>` and no `--fixtures`.
* **`NOTICE` gains a third-party notice carrier list**: the two Donlon extracts under
  `fixtures/aixm511/independent/` carry EUROCONTROL's BSD-2-Clause notice by obligation.
* **Three examples** under `examples/` demonstrate the arc end to end from a clean state:
  `c2sim/run.py`, `aixm_dnotam/run.py` and `geopackage_to_geojson/run.py`.

## What else moved

* **The release workflow's gate step now reads check J per adapter**, with the `no-source-time`
  declaration, and the wheel gate's test rosters know the new modules. `ci.yml`'s per-adapter
  loop of the same rule ran green in `CI` run 35591088608 on `main`; `publish.yml`'s step has run
  only as a local rehearsal of its body over the `--all` artefact (the record's D60) and on no run
  of that workflow: this release's tag is the first push that exercises it.
* **`gates/bump_derivation.py` resolves an adapter's base class across the snapshot's modules**, so
  a profile adapter inheriting `to_cdm` from a base in another module is classified as the adapter
  it is (`aixm52` on `aixm511.AixmAdapterBase`).
* **The release rehearsal gate** (`gates/release_ref_rehearsal.py`) replays every ref-dependent
  release step against the local tag before it is pushed, as it has since 2.1.2; it is refused
  without a tag, which is the reading the release commit records before the tag exists.

## Nineteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas --json`, run over the roster
with no `--fixtures` at this commit, and every verdict read from the run. The table is the live
registry — `python -m synapse_cdm.harness --list-adapters` prints `19 adapters registered` and
`adapter.discover()` and `adapter.roster()` each return the same nineteen names — and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. Declared maturity and claim status are read from `manifests/<name>.json`.

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
| `geojson` | bidirectional | 4 | L4 | VERIFIED (new in 3.1.0) |
| `geopackage` | ingest | 8 | L3 | VERIFIED (new in 3.1.0) |
| `c2sim` | bidirectional | 10 | L4 | VERIFIED (new in 3.1.0) |
| `aixm511` | ingest | 10 | L3 | VERIFIED (new in 3.1.0) |
| `aixm52` | ingest | 10 | L3 | VERIFIED (new in 3.1.0) |

**580 fixture verdicts, 0 failed** across the nineteen, against the published 3.0.0 schemas —
the 538 that 3.0.1 shipped, unchanged, plus 42 from the five new sets; `gates/wheel_install.py`
reads the same roster off the installed wheel as `19 adapters, 599 fixture files` and
`19 adapters x 2 schema modes, 1160 fixture verdicts, 0 failed`. The `roundtrip` column reads
PASS for the thirteen that emit their format back and a declared SKIP for the six ingest-only;
the `lossless` column reads PASS on every one, on a declared ledger for `pntmap` and the five
new ones and on the value-presence heuristic, said so, for the other thirteen. The two L4
declarations (`geojson`, `c2sim`) rest on a ledger that reports no loss over a self round trip
under the `values` tolerance; every other declaration is L3, and `tests/test_cdm_manifests.py`
holds a bidirectional adapter to L3 wherever the report's `preservation.basis` reads
`heuristic`.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this arc.

## Published by CI over OIDC, as 1.1.0 through 3.0.1 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 21 records the 3.0.1 upload — the first whose witness record the
pipeline itself produced and this repository committed.

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
pip install synapse-cdm==3.1.0
python -m synapse_cdm.harness --list-adapters
```
