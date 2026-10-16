# synapse-cdm 3.4.0

**The SC Link16 Gateway translator release, and the first CDM schema MINOR since 3.0.0.** Between
the 3.3.0 release of 2026-10-07 and this one, the tree gained one adapter module,
`link16_gateway`, and the registry moved from twenty-one to twenty-two. It reads one report of SC
Link16 Gateway 1.0.0 — an internal JSON interface this repository defines, the public contract of
the SynapseCommand JREAP C and Link 16 engineering handoff 1.0.0 — into one `Entity` and, when the
report carries a position, a one-sample `Track`, and it builds a report back from CDM objects in
two egress modes. It parses no JREAP C or Link 16 bytes, claims no native interoperability and
transmits nothing. To carry the position methods the gateway reports, the CDM vocabulary
`PositionSource` gained two members, `SENSOR` and `UNKNOWN`, so the wire contract moved
**3.0.0 → 3.1.0**, a MINOR. The runtime half of the gateway lands beside the package as a separate
distribution, `synapse-link16-bridge`, carried by the tag and not by this wheel. The design record
is `docs/link16-gateway-implementation.md`, which ships in nothing; `MIGRATIONS.md`'s 3.4.0
section is the record of what the distribution carries.

**If you are upgrading from 3.3.0, upgrade readers before writers.** A 3.4.0 reader reads every
3.3.0 object, and `version.compatible("3.0.0", "3.1.0")` is `True`. A 3.3.0 reader reads a 3.4.0
object too, unless that object carries one of the two new `position_source` values: the 3.0.0
contract's enums are closed, so it refuses `SENSOR` and `UNKNOWN`, and
`version.compatible("3.1.0", "3.0.0")` is `False`. No adapter that shipped before this release
writes either member, so their objects change by the `schema_version` stamp alone. No member of the
`Adapter` contract moved, so an adapter subclass written against 3.3.0 keeps working.

## Why the number is 3.4.0

**The number is the derived floor: a MINOR from `v3.3.0`.** `gates/bump_derivation.py --json`,
run on the arc tip before any number was typed, reported the arc as `{"kind": "MINOR", "number":
"3.4.0", "unruled": []}`. The floor comes from the public names the arc added and from nothing
removed — the `Link16GatewayAdapter` subclass, registered as `link16_gateway`, with its
`ExportContext` and its refusal type, and the `link16_gateway` fixture set — and from the schema
MINOR below, since a schema MINOR is at least a package MINOR. The units the table cannot decide
on its own are ruled in `MIGRATIONS.md`'s 3.4.0 section: the enum, three adapters' basis strings,
the support matrix's binding legend, the release notes' rendering of structured limitations,
`version.KNOWN_CONTRACTS` and the wording of `version.assess` — eight rulings, which the gate reads
and reports nothing unruled. Over the arc the gate's table decides 725 signals, 35 MINOR and 690
PATCH, and the eight rulings decide the rest.

**Package version 3.4.0 · CDM `schema_version` 3.1.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are still three MINORs apart, because each moved a MINOR
on its own table. `python -m synapse_cdm.schemas --check --out schemas` reads `CURRENT: schemas vs
models at 3.1.0` and `python -m synapse_cdm.manifests --check` reads `CURRENT: manifests vs 22
shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`, `MANIFEST_SCHEMA_VERSION` and
`EVIDENCE_SCHEMA_VERSION` did not move in this arc. SC-OES, the Operational Ontology and the
profile versions did not move: `SC_OES_VERSION` is still `0.1.0` and still a Draft.
`synapse_cdm/version.py` states the nine version axes and their independence.

## Why the schema is 3.1.0 and not 4.0.0

`PositionSource` gained `SENSOR` — a position a source reports as an explicit sensor or
surveillance solution that is none of GNSS, INERTIAL, MANUAL or ESTIMATED — and `UNKNOWN` — a
position whose source does not state how it was obtained, recorded as a fact rather than as a
null. Nothing was removed, renamed or narrowed, and the table at the top of `MIGRATIONS.md` puts
an added enum member on the MINOR row. The handoff asked for a CDM 4.0.0 (its REQ012); that is not followed and
is recorded as a deviation. A 3.0.0 reader's refusal of an object carrying a new member is the
old-reader refusal every MINOR carries, and the adapter's compatibility projection
(`cdm_schema="3.0.0"`) serves a consumer that cannot read the two members: such a report yields an
Entity with no position, marked `POSITION_NOT_PROJECTED_CDM3`, which the frozen 3.0.0 contract
accepts.

The 3.1.0 contract is frozen under `tests/frozen/cdm/3.1.0/` beside 3.0.0, and
`version.KNOWN_CONTRACTS` reads `("2.0.0", "2.1.0", "3.0.0", "3.1.0")`.
`tests/test_cdm_version_matrix.py` shows both directions on the frozen bytes: a 3.0.0 document of
every kind validates under the 3.1.0 schema and models, and a 3.1.0 document carrying either member
is refused by the frozen 3.0.0 schema by its closed `enum`. Every golden moved by its
`schema_version` stamp alone. Six schema files moved. `cdm_object`, `entity`, `plan_object` and
`track`, the four that carry `PositionSource`, moved by their label, the two members and their dated
description; `payload_gnss_interference` moved by the label alone; at `v3.4.0` so did `event`,
which since that tag, in no release, has moved past its label by CDM 3.2.0's `validity`, as
`track` and `cdm_object` have by `attributes` (the rows marked **post-3.4.0** below). The fourteen SC-OES
examples and the semantic corpus stay stamped 3.0.0 and are read as documents of the previous minor
— the examples until `v3.4.0`: since that tag, in no release, they read 3.1.0 with CDM 3.2.0's
`"validity": null` on every Event, as does the corpus's new `SEM-014.json`, which carries
`attributes`; the DIS 7
adapter's vendored entity profile is re-derived from the 3.1.0 entity schema, and the pin record
keeps its handoff bundle's digests beside the derived ones. No shipped adapter is re-labelled:
`cat048`, `cat062`, `stanag4609` and `tacticalapi` keep the members they wrote, with their bases.

## The `link16_gateway` adapter, and what it is measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `link16_gateway` is #23.
It is the twenty-second registered adapter and carries ordinal 23 because ordinal 9 was issued to a
specification that has no adapter: the ordinal is not the roster count.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `link16_gateway` | SC Link16 Gateway 1.0.0 (profile `sc-link16-gateway/1.0.0`), an internal JSON interface defined in this repository; binding `provisional-internal-profile` | bidirectional | one report → one `Entity` and an optional one-sample `Track`; egress in two modes; the report schema as a module literal; the `link16_gateway` fixture set |

**What it reads.** One report per call, as octets or as a dict. A report is a strict JSON object of
28 keys; the adapter validates it against the report schema with no format checker, then enforces
what the schema cannot state: canonical lowercase UUIDs, ASCII-only timestamps on a strict
calendar, counters up to 2^64−1, component times not after `effective_at`, and numbers that a
finite double holds. Identity is the destination-allocated tuple of tenant, realm, synthetic flag,
origin scope, track number and incarnation; the gateway, session and record identifiers are
provenance and never identity. A height stated as HAE in feet becomes metres in both `vertical`
and `alt_m`, the feet kept in the residual; every other datum keeps its value and unit. The whole
report is kept in a structured residual on every object, and the preservation ledger reads 174
mapped and 319 residual leaves and 0 lost over the fixtures.

**What it refuses, by name.** Every refusal is a `Link16GatewayRefusal`, a `ValueError` whose
`code` is one of the eight adapter codes of the contract's eighteen, and whose message `CODE: path —
rule` never carries a value taken from the payload: `JSON_INVALID` (duplicate keys, a byte-order
mark, invalid UTF-8, a non-finite or unrepresentable number), `SCHEMA_INVALID`, `LIMIT_EXCEEDED`
(above 1 048 576 octets, depth 32 or 10 000 JSON value nodes), `SYNTHETIC_MISMATCH`,
`TIME_UNRESOLVED`, `CDM_SOURCE_CONFLICT`, `ALTITUDE_DATUM_UNSUPPORTED` and
`VALUE_NOT_REPRESENTABLE`. Past the manifest's bounds the base class refuses first, with
`InputTooLarge` or `InputTooDeep`. The adapter's tests assert every refusal by name, on 32 refused
reports under `fixtures/link16_gateway/malformed/` and on inputs the tests generate, including a
seeded mutation fuzz of every positive report.

**Egress.** The default mode rebuilds the report from the adapter's own `Entity` and `Track` and
refuses any disagreement as `CDM_SOURCE_CONFLICT`. In export mode, selected by an immutable
`ExportContext` the runtime supplies, the adapter builds one report from a CDM `Entity` the report
contract can represent, refuses what it cannot carry with a structured loss record, and lists
what it leaves out. The documentation page `docs/docs/cdm/link16-gateway.mdx` is the contract of
export mode.

**Where its behaviour comes from.** The handoff's specification, its three JSON schemas — published
under `schemas/link16_gateway/` as the contract's publication — and its six synthetic reports and
their six reference projections, carried byte-identical under the fixture directory and pinned by
sha256 in `fixtures/link16_gateway/spec/link16_gateway_pin.json`. The adapter is stricter than the
handoff's reference mapper on timestamps, identifiers, UUID case and numbers, and each departure
has a refused fixture. The deviations from the handoff — this schema MINOR among them — are listed
on the documentation page and in the implementation record.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions.
The first is reached for `link16_gateway` and this release claims it. The second is not claimed
anywhere in the tree: no JREAP C frame, Link 16 message or J-series word is parsed or produced, no
native gateway, terminal or peer has been exercised, and no exchange with any system is asserted.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter link16_gateway` on this tree — the records themselves are generated, gitignored, and
  attached by a Release rather than committed: `internal_fixture` PRESENT; `self_round_trip`
  PRESENT; `independent_expected` ABSENT; `normative_schema` ABSENT; **`independent_endpoint`
  ABSENT**.
* **Declared maturity is L4 and claim status PROVISIONAL**, read from
  `manifests/link16_gateway.json`. The claim is `PROVISIONAL` because the binding is
  `provisional-internal-profile`: a green gate proves agreement with an interface this repository
  defines and nothing about a native standard. L4 rests on a ledger that reports no loss over the
  self round trip.
* **Release acceptance has four stages, each reported on its own**: the internal gateway
  translation implemented; a native codec verified against specified evidence; interoperability
  exercised with a named peer; deployment in a named authorised environment. Only the first is
  claimed. No numerical quality score is given.
* **`evidence.available` is `true` on `link16_gateway` from this release.** The adapter landed
  declaring `false` — "it becomes true at the first release that attaches them" — and
  `tests/test_cdm_evidence.py` holds the field to the newest release tag's tree. The release
  commit flipped it, with a limitation sentence that names no version, the form `dis7`'s took at
  3.2.0 and `tacticalapi`'s at 3.3.0: `.github/workflows/publish.yml` generates the records for
  every shipped adapter and attaches them to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge`, on GitHub only

`packages/link16_bridge/` holds a second distribution, `synapse-link16-bridge` 1.0.0 (import
`synapse_link16_bridge`, command `synapse-link16-bridge`), whose runtime dependencies are
`synapse-cdm` 3.4.0 or later and below 4, and the standard library. It reads gateway report
batches over the gateway API, checks each record against its configured channel, hands each
report's octets to the `link16_gateway` adapter, keeps dispositions, identities, history,
lifecycle, an outbox and an audit trail in one SQLite file per channel, delivers CDM objects to a
sink at least once, and exports only what its deployment configuration permits. It ships a
synthetic provider with a loopback server; its native provider boundary refuses with
`BLOCKED_EXTERNAL_EVIDENCE` and never falls back. Its performance target is NOT_RUN: the rig the
handoff names is Linux x86_64, and no timing from another machine is recorded as evidence.

It is part of the tag `v3.4.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project was created there in this release, which is
an act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.4.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.4.0#subdirectory=packages/link16_bridge"
```

Its requirement matrix is `packages/link16_bridge/docs/requirements-matrix.md`, and its workflow
`.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main` and to the
release and arc branches.

## What changed for a 3.3.0 consumer

* **The wire contract is 3.1.0.** `PositionSource` has six members; every object this package
  writes is stamped `3.1.0`, except what `link16_gateway`'s compatibility projection
  (`cdm_schema="3.0.0"`) writes, which is stamped `3.0.0`; `schemas/` carries the two members and
  the label. A 3.3.0 reader refuses an object only when it carries `SENSOR` or `UNKNOWN`, and only
  `link16_gateway` writes them.
* **`version.assess` names a second ground.** An older reader refuses a newer object for a property
  it does not know (`additionalProperties: false`) and, from 3.1.0, for an enum value it does not
  list; every verdict and direction for the older pairs is unchanged.
* **A new adapter, `link16_gateway`**, and **a new fixture directory**,
  `fixtures/link16_gateway/`; `--list-adapters` reports twenty-two and the harness replays
  `link16_gateway` with `--adapter link16_gateway` and no `--fixtures`. No other adapter's verdict
  moved.
* **Structured limitations render as their text.** The release notes' list of known limitations
  printed a structured limitation as a Python dict; it now prints its summary.

## What else moved

* **The support matrix's binding legend** says that `provisional-internal-profile` also covers an
  interface this repository defines itself, for which no external normative binding exists.
* **The bump gate attributes a roster move per module**, the attribution its own docstring stated:
  a roster change explains an edit only in the module whose class declares the added or removed
  name. Every released arc still derives the number it shipped.
* **The ordinals gate admits an underscore** in a registry name, `link16_gateway` being the first;
  the widening is dated in `tests/test_cdm_ordinals.py` with the reading that shows the sweep still
  catches a stale pairing, a second row naming one adapter and a renamed row.
* **Open items found on the way are recorded and not fixed here**, in the implementation record's
  "Open items": `times.parse` and `times.parse_wire` accept hour 24 on Python 3.14 and refuse it on
  3.12, because `datetime.fromisoformat` changed — the adapter does not use them for its strict
  calendar; `adapter.container_depth` does not return on a dict that contains itself, which only an
  in-process caller can build; the ordinals gate does not catch a repeated ordinal number; and the
  bridge's synthetic server prints a traceback to its own stderr when it is stopped with a request
  body still arriving. None touches a claim of this release.

## Twenty-two adapters at 3.4.0, all harness-verified — and five more in the tree since

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. At `v3.4.0` `python -m synapse_cdm.harness --list-adapters` prints `22
adapters registered`. The five rows marked **post-3.4.0** landed in the tree after that tag,
`readsb_trace`, `nexrad2`, `ndbc_stdmet`, `coops_csv` and `airnow_hourly` on 2026-10-15, and are
in no release. Declared maturity and claim status are read from `manifests/<name>.json`.

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
| `link16_gateway` | bidirectional | 15 | L4 | PROVISIONAL (new in the 3.4.0 arc) |
| `readsb_trace` | ingest | 26 | L3 | VERIFIED (**post-3.4.0**, in no release) |
| `nexrad2` | ingest | 10 | L3 | VERIFIED (**post-3.4.0**, in no release) |
| `ndbc_stdmet` | ingest | 8 | L3 | VERIFIED (**post-3.4.0**, in no release) |
| `coops_csv` | ingest | 7 | L3 | VERIFIED (**post-3.4.0**, in no release) |
| `airnow_hourly` | ingest | 8 | L3 | VERIFIED (**post-3.4.0**, in no release) |

**611 fixture verdicts, 0 failed** across the twenty-two, against the published 3.1.0 schemas —
the 596 that 3.3.0 shipped, each golden re-stamped and otherwise unchanged, plus 15 from the new
set. The two readings the wheel gate takes, its `resources` and `harness` checks, run on this tree
from a directory outside the repository, read `22 adapters, 633 fixture files` and `22 adapters x 2 schema modes, 1222 fixture verdicts, 0 failed`;
`gates/wheel_install.py` takes the same readings off the installed wheel in the release workflow.
The `lossless` column reads PASS on every JSON fixture and a stated SKIP on every non-JSON one,
and FAIL on none, on a declared ledger for `pntmap`, the five of the 3.1.0 arc, `dis7`,
`tacticalapi` and `link16_gateway`, and on the value-presence heuristic, said so, for the other
thirteen. The four L4 declarations (`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger
that reports no loss over a self round trip under the adapter's declared tolerance; every other
declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. The first six moved in this release, each
carrying `x-cdm-schema-version: 3.1.0`; the other three did not move. The three gateway schemas
under `schemas/link16_gateway/` are the handoff's, published as the contract's publication, and
are not generated.

## Published by CI over OIDC, as 1.1.0 through 3.3.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 25 records the 3.3.0 upload. The workflow builds and uploads
`synapse-cdm` only; the bridge reaches the Release as source in the tag.

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
pip install synapse-cdm==3.4.0
python -m synapse_cdm.harness --list-adapters
```
