# synapse-cdm 3.9.0

**The STANAG 4559 translators release.** Between the 3.8.0 release of 2026-10-25 and this one, the
tree gained three adapter modules — `stanag4559_catalog`, `stanag4559_stream` and
`stanag4559_workflow` — on a record module they share, `isr_record`, and the registry moved from
thirty-three to thirty-six. They are the pure translation layer of the SynapseCommand STANAG 4559
engineering specification (SC ISR 4559 001, revision 1.0 of 4 October 2026): each reads one
internal ISR gateway record of its family — `urn:synapsecommand:isr:record:1`, this project's own
record contract, whose JSON Schema ships byte for byte as package data at
`registry/isr/isr-record.schema.json` — as its octets or its parsed dict, and writes exactly one
`STATUS_CHANGE` `Event` carrying the record verbatim. They are **not** STANAG 4559 wire
interoperability: the stateful gateway of the specification is not in this repository, its wire
profiles C17, S18 and W19 are unimplemented, no NATO binding package is held and no peer was
exercised. Nothing on the wire moved: `SCHEMA_VERSION` stays `3.2.0`, no model, enum or published
CDM schema changed, and no golden of an adapter that predates the arc moved by a byte.
`MIGRATIONS.md`'s 3.9.0 section is the record of what the distribution carries.

**If you are upgrading from 3.8.0, nothing you read or write changes.** A 3.8.0 reader reads a
3.9.0 object unchanged, and `version.compatible("3.2.0", "3.2.0")` is the same answer it was. No
member of the `Adapter` contract moved, so an adapter subclass written against 3.8.0 keeps working.
The three adapters, the module `synapse_cdm.isr_record` and the packaged record contract are
additions; no other adapter's output, verdict or declaration moved, and no `synapse-decode`
invocation, conformance reading or harness flag changed.

## Why the number is 3.9.0

**The number is the derived floor: a MINOR from `v3.8.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, reported the pending arc as `{"kind": "MINOR",
"number": "3.9.0", "unruled": []}`. The floor comes from the public names the arc added and from
nothing removed — the `Adapter` subclasses `Stanag4559CatalogAdapter`, `Stanag4559StreamAdapter`
and `Stanag4559WorkflowAdapter` with their shared module and their fixture sets, and the record
module `isr_record`. The one unit the table cannot decide on its own is ruled in `MIGRATIONS.md`'s
3.9.0 section: the packaged record contract `registry/isr/isr-record.schema.json`, a shipped file
kind the table has no class for, ruled MINOR — one ruling over one unit, which the gate reads and
reports nothing unruled. Over the arc the gate's table decides 114 signals, 36 MINOR and 78
PATCH, and the one ruling decides the rest.

**Package version 3.9.0 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are seven MINORs apart, the seventh for the ordinary
reason: the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out
schemas` reads `CURRENT: schemas vs models at 3.2.0` and `python -m synapse_cdm.manifests --check`
reads `CURRENT: manifests vs 36 shipped adapters at manifest schema 2.1.0`.
`ADAPTER_API_VERSION`, `MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` did not move in this
arc. SC-OES, the Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is
still `0.1.0` and still a Draft. `synapse_cdm/version.py` states the nine version axes and their
independence.

## What the STANAG 4559 translators are measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `stanag4559_catalog` is #35, `stanag4559_stream` #36 and
`stanag4559_workflow` #37. They were registered thirty-fourth, thirty-fifth and thirty-sixth and
carry ordinals one higher because ordinal 9 was issued to a specification that has no adapter: the
ordinal is not the roster count. Each is ingest-only and declares a path-bound preservation ledger,
and each declares `residual: legacy` by the dated ruling `ARCHITECTURE.md` §5 records: the
specification's expected Events carry the whole record under `payload.record` and `residual` null,
so a structured container would hold a second copy of the record and change the oracle's bytes. The
legacy census is seventeen — the fourteen of Part 1 and these three — and the exception is theirs
and no other adapter's.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `stanag4559_catalog` | SC ISR gateway record `urn:synapsecommand:isr:record:1`, catalogue family — the internal record contract of SC ISR 4559 001 (revision 1.0, 4 October 2026), cited by title and date; binding `provisional-internal-profile` | ingest | one catalogue record → one `STATUS_CHANGE` `Event`, its footprint the Event's geometry; the `stanag4559_catalog` fixture set |
| `stanag4559_stream` | the same contract, stream family | ingest | one stream record → one `STATUS_CHANGE` `Event`, its footprint the Event's geometry; the `stanag4559_stream` fixture set |
| `stanag4559_workflow` | the same contract, workflow family | ingest | one workflow record → one `STATUS_CHANGE` `Event`, a geometry only for the `gaoi` service; the `stanag4559_workflow` fixture set |

Beside them ship the record module `isr_record` — the contract, section 6's transport rules,
section 28's second validation pass and section 7's identity, which the three share — and its
contract `registry/isr/isr-record.schema.json`, the bundle's `contracts/isr-record.schema.json` byte
for byte, read through `importlib.resources` and never from a checkout.

**What they read.** One record per call, as its UTF-8 octets or its parsed dict: a catalogue entry,
a stream description or a workflow entity as a SynapseCommand ISR gateway normalises it, with its
tenant, security domain, connector, origin, revision, change kind, two clocks, a reference to the
raw capture, two security labels and a family body. The Event's `payload` is `kind`, `record_id`,
`revision_key`, `time_basis` and the record verbatim; `observed_at` is the record's `source_time`
(`time_basis` `SOURCE`) or, where it states none, the gateway's `captured_at` (`GATEWAY_RECEIPT`),
and no body time is promoted. The geometry is the catalogue or stream coverage, or a workflow
record's geometry when its service is `gaoi`, each validated by section 28's polygon rules; there is
no Entity and no point at a box's centre. The identity is `ISR-ID-001`, the one transformation an
Event names: `object_key` is the unpadded base64url of the RFC 8785 array `[tenant_id,
security_domain, origin.authority, family, origin.object_id]`, `revision_key` the same over
`[object_key, revision.token, revision.semantic_sha256]`, and the record and event ids are
`ids.derive` over the two — written with `json.dumps(..., ensure_ascii=False, separators=(",",
":"))`, which the catalogue module measures against a serialiser written from the RFC's sentences;
a lone surrogate is refused by field before a key is built, and no digest is recomputed, because
the specification gives digest validation to the gateway. The preservation ledger reads 45 mapped,
124 residual and 0 lost leaves over the catalogue fixtures, the same over the stream fixtures, and
12 mapped, 142 residual and 0 lost over the workflow fixtures. The bundle's nine expected Events
are reproduced byte for byte by the three test modules, with the object keys, record ids and event
ids of the bundle's fixture manifest and the revision keys section 7 derives asserted as literals,
once projected with `projection.dump_for` to the CDM 3.0.0 contract the bundle was written
against; the adapters themselves write 3.2.0.

**What they refuse, by name.** Every refusal is an `isr_record.IsrRecordRefused`, a `ValueError`
whose `code` names one rule — section 6's transport rules, the record's values on either path, the
contract, section 28's timestamps, interval, identity scope, polygon topology and typed graph, and
`wrong-family` for a record handed to another family's translator — and whose message names a path
and never a value, because a record carries security labels. Every refusal comes before any output.
The two declared bounds are a `LimitBasis` each and a project default, never a normative maximum:
16,777,216 input octets (section 20's `max_metadata_bytes` of the gateway) and JSON nested 96 deep
(`isr_record.MAX_DEPTH`, eight times the deepest shipped JSON); and a geometry of more than 2,048
positions is refused `geometry-over-cap` before the quadratic polygon pass runs, a cap the
manifests state. Strict
JSON is judged on octets (a byte-order mark, invalid UTF-8, a duplicate key, NaN or Infinity, a
trailing document, an integer past 2^53 - 1); a parsed dict has passed through its caller's decoder
first, and the manifests say so. The adapters' tests assert each of the 47 refused records under
the three `malformed/` directories — 15 `.isr` octet payloads and 32 JSON cases, 16 for the
catalogue, 16 for the stream and 15 for the workflow family — by its code, as the harness's
loader hands it over, the in-memory record one octet past the input bound by `InputTooLarge`, and
the contract's other refusals by code on inputs the tests build.

**Where their behaviour comes from.** The specification, cited by title and date and not carried;
its JSON Schema, carried byte for byte as package data; its bundle's nine synthetic records and
nine expected Events, carried verbatim as test data under `tests/stanag4559_bundle/` — in the
repository and not in the wheel — and pinned by SHA-256 in each fixture set's
`spec/stanag4559_pin.json`; and the bundle's fixture manifest, pinned there by its digest and not
carried, because the repository's secret scanner reads its `object_key` lines as key assignments
and admits no allowlist — its clock and identities are the tests' literals. Every fixture is
synthetic: the bundle's records, a
catalogue or stream footprint moved whole degrees into the Baltic fixture rectangle and the semantic
digest recomputed by the bundle's own rule, the workflow records byte for byte, written by each
fixture directory's `spec/build_fixtures.py`, whose `--check` rebuilds the payloads and the refused
set byte for byte. Of the bundle's twenty-two internal acceptance cases, each named in the
docstring of the test that discharges it, fifteen are discharged in full — PARSE-009 against the
record contract's own cardinality — and seven in part, because their other half is the gateway's:
CDM-005 (one event id for a replica's capture; folding replicas into one record is the gateway's
deduplication), PARSE-003 and PARSE-004 (no XML is parsed here; the gateway's decoder is not built),
PARSE-006 and PARSE-007 (the record's own depth and node bounds; the XML limits are the gateway's),
PARSE-008 (the one super-linear pass is capped; the worker timeout is the gateway's) and PARSE-010
(no versioned NATO metadata dictionary is held, so a conflicting duplicate of a scalar attribute is
refused only as far as the contract can see).

**The deviations from the specification, stated.** The claim is `PROVISIONAL` from the start,
because this repository admits no DOCUMENTED or IMPLEMENTED claim beside a
`provisional-internal-profile` binding; the capture representation section 9 asks to record beside
`source.source_hash` survives at `payload.record.raw_ref.representation`, because `SourceHash` is
closed; the `time_basis` value `SOURCE` is taken from the bundle's expected Events, the text naming
only `GATEWAY_RECEIPT`; the bundle's expected Events are CDM 3.0.0 documents, so the byte comparison
projects to 3.0.0 and states the 3.0.0 stamp while the adapters write 3.2.0; and there is no
gateway, no wire profile and no peer exercise.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions. The
first is reached for the three translators and this release claims it. The second is not claimed
anywhere in the tree. The capability report, verbatim from `stanag4559_common`'s module docstring
(each translator's docstring, its manifest's `provisional-internal-profile` and `no-gateway`
limitations, `FORMAT_COVERAGE.md`'s section and `INTEROPERABILITY.md` say the same):

> What is implemented: the PURE TRANSLATION LAYER of the specification — `synapse_cdm/isr_record.py`
> (the record contract `urn:synapsecommand:isr:record:1`, section 6's transport rules, section 28's
> second pass, section 7's identity) and the three ingest-only translators, each turning one record
> of its family into exactly one `STATUS_CHANGE` `Event` (section 9).
>
> What is NOT implemented, and is not part of this distribution: the stateful ISR gateway of
> sections 5 to 7 and 10 to 19 (`packages/isr-gateway`: authentication, authorisation, the policy
> service, persistence, product transfer, CORBA and SOAP sessions, subscriptions, stream replay
> control, workflow mutation). Every wire profile of section 3 — C17 (AEDP-17 library access), S18
> (AEDP-18 streams) and W19 (AEDP-19 workflow) — is UNIMPLEMENTED. No STANAG 4559 or AEDP-17/18/19
> wire message is read or written here, no NATO binding package (IDL, WSDL, XSD, metadata
> dictionary) is held, no peer was exercised, and no NATO wire interoperability is claimed: the
> bundle's own `nato_wire_compatibility_verified: false` stands. The input is this project's
> internal record, which section 6 says "is not a representation to send to a NATO peer"; that is
> why the binding is `provisional-internal-profile` and the claim `PROVISIONAL` (section 9: "do not
> relabel local JSON as standard NATO wire encoding").

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter <name>` on this tree for each of the three — the records themselves are generated,
  gitignored, and attached by a Release rather than committed: `internal_fixture` PRESENT;
  `self_round_trip` NOT_APPLICABLE, each being ingest-only; `independent_expected` ABSENT;
  `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **Declared maturity is L3 and claim status PROVISIONAL** for each, read from
  `manifests/<name>.json`. The claim is `PROVISIONAL` because the binding is
  `provisional-internal-profile`: the input is the internal record contract
  `urn:synapsecommand:isr:record:1`, which the specification itself says is not a representation to
  send to a NATO peer, so a green gate proves agreement with a contract this project defines and
  nothing about a NATO wire encoding. L4 is not declared: an ingest-only adapter has no round trip,
  and a rung passed vacuously is not a rung declared.
* **The strict readings have met the specification and not a gateway**: the contract's transport
  rules, its schema and section 28's second pass have met the specification and its bundle's
  synthetic records, and no record written by a gateway is in the repository.
* **`evidence.available` is `true` on the three from this release.** Each landed declaring
  `false` — "it becomes true at the first release that attaches them" — and
  `tests/test_cdm_evidence.py` holds the field to the newest release tag's tree. The release commit
  flipped their shared declaration, with a limitation sentence that names no version, the form the
  two of 3.7.0 and the one of 3.8.0 took: `.github/workflows/publish.yml` generates the records for
  every shipped adapter and attaches them to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge` 1.1.0, on GitHub only

`packages/link16_bridge/` holds the second distribution, `synapse-link16-bridge`, still 1.1.0
(import `synapse_link16_bridge`, command `synapse-link16-bridge`): nothing under it moved since
`v3.8.0`, and its runtime dependencies are still `synapse-cdm` 3.5.0 or later and below 4, and the
standard library.

It is part of the tag `v3.9.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project is created there in this release, which is an
act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.9.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.9.0#subdirectory=packages/link16_bridge"
```

Its workflow `.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main`
and to the release and arc branches.

## What changed for a 3.8.0 consumer

* **Three new adapter modules** and three new fixture directories; `--list-adapters` reports
  thirty-six and the harness replays each new adapter with `--adapter <name>` and no `--fixtures`.
  No other adapter's verdict moved.
* **One new module, `synapse_cdm.isr_record`**, with the record contract's reader, its refusal
  `IsrRecordRefused` and the identity functions `object_key`, `revision_key`, `record_id` and
  `event_id`, and one new package data file, `registry/isr/isr-record.schema.json`.
* **`synapse-decode`** still has thirteen hosted rows; the three translators are not among them,
  and they are reached through the `Adapter` API and the harness.
* **The wire contract is still 3.2.0.** Every object this package writes is stamped `3.2.0`, as at
  3.8.0, except what the compatibility projections of `link16_gateway` and `cesmo_internal`
  (`cdm_schema="3.0.0"`) write.

## Thirty-six adapters at 3.9.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. At `v3.9.0` `python -m synapse_cdm.harness --list-adapters` prints `36 adapters
registered`. The row marked **post-3.9.0** landed in the tree after that tag, `stanag4545` on
2026-10-25, and is in no release. Declared maturity and claim status are read from
`manifests/<name>.json`.

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
| `stanag4559_catalog` | ingest | 3 | L3 | PROVISIONAL (new in the 3.9.0 arc) |
| `stanag4559_stream` | ingest | 3 | L3 | PROVISIONAL (new in the 3.9.0 arc) |
| `stanag4559_workflow` | ingest | 3 | L3 | PROVISIONAL (new in the 3.9.0 arc) |
| `stanag4545` | ingest | 22 | L3 | PROVISIONAL (**post-3.9.0**, in no release) |

**765 fixture verdicts, 0 failed** across the thirty-six, against the published 3.2.0 schemas —
the 756 that 3.8.0 shipped, every golden byte for byte as it was, plus 9 from the three new sets.
The two readings the wheel gate takes, its `resources` and `harness` checks, run on this tree from a
directory outside the repository, read `36 adapters, 801 fixture files` and `36 adapters x 2 schema modes, 1530 fixture verdicts, 0 failed`; `gates/wheel_install.py`
takes the same readings off the installed wheel in the release workflow. The `lossless` column
reads PASS on every JSON fixture and a stated SKIP on every non-JSON one, and FAIL on none, on a
declared ledger for `pntmap`, the five of the 3.1.0 arc, `dis7`, `tacticalapi`, `link16_gateway`,
the five of the 3.5.0 arc, the three of the 3.6.0 arc, the two of the 3.7.0 arc, the one of the
3.8.0 arc and the three of this one, and on the value-presence heuristic, said so, for the other
thirteen. The four L4 declarations (`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger
that reports no loss over a self round trip under the adapter's declared tolerance; every other
declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this release:
the first six carry `x-cdm-schema-version: 3.2.0`, as at 3.8.0. The four observation contract
schemas under `schemas/observation/`, generated by `python -m synapse_cdm.observation_contracts`,
the three gateway schemas under `schemas/link16_gateway/`, the handoff's, and the CESMO contract
under `schemas/cesmo_internal/` did not move either: `git diff v3.8.0 -- schemas/` is empty. The
ISR record contract is package data under `registry/isr/`, the adapters' input contract and not a
CDM schema.

## Published by CI over OIDC, as 1.1.0 through 3.8.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 30 records the 3.8.0 upload. The workflow builds and uploads
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
pip install synapse-cdm==3.9.0
python -m synapse_cdm.harness --list-adapters
```
