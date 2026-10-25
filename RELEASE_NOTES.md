# synapse-cdm 3.8.0

**The CESMO internal-contract release.** Between the 3.7.0 release of 2026-10-24 and this one, the
tree gained one adapter module — `cesmo_internal` — and the registry moved from thirty-two to
thirty-three. It is Stage A of the SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0
(Decent Cybersecurity, 4 October 2026): it reads one SC CESMO Internal Exchange
(`sc.cesmo.internal/1.0`), the kit's internal JSON contract, as its octets or its parsed dict, and
writes the kit's deterministic CDM projection of its records — `DETECTION`, `TRACK_UPDATE` and
`STATUS_CHANGE` Events and emitter Entities. It is **not** STANAG 4658: the kit declares that wire
binding BLOCKED on its unresolved dependency register N01 to N12, no `stanag4658` class, manifest
or claim exists, and the gateway that would produce the internal contract is not in this
repository. Beside it the `synapse-decode` host command gained three rows — the HIGH NORTH
adapters `barentswatch_hais` and `frost_observations`, which 3.7.0 shipped unhosted, and
`cesmo_internal` — and an `--element-table` context file, and the conformance suite's checks J and
K stopped judging a source's own record held in the structured residual. Nothing on the wire moved:
`SCHEMA_VERSION` stays `3.2.0`, no model, enum or published CDM schema changed, and no golden of an
adapter that predates the arc moved by a byte. `MIGRATIONS.md`'s 3.8.0 section is the record of
what the distribution carries.

**If you are upgrading from 3.7.0, nothing you read or write changes.** A 3.7.0 reader reads a
3.8.0 object unchanged, and `version.compatible("3.2.0", "3.2.0")` is the same answer it was. No
member of the `Adapter` contract moved, so an adapter subclass written against 3.7.0 keeps working.
Every `synapse-decode` invocation that worked against 3.7.0 works the same way; the three rows and
the flag are additions. One conformance reading moves, and only in the permissive direction: checks
J and K no longer walk `residual`, so an adapter whose residual holds a source-form timestamp or a
native identifier is no longer reported NON-CONFORMANT for it, and every adapter that was
CONFORMANT stays CONFORMANT.

## Why the number is 3.8.0

**The number is the derived floor: a MINOR from `v3.7.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, reported the pending arc as `{"kind": "MINOR",
"number": "3.8.0", "unruled": []}`. The floor comes from the public names the arc added and from
nothing removed — the `Adapter` subclass `CesmoInternalAdapter` with its contract module and its
fixture set, and `decode_host.load_element_table`. The units the table cannot decide on its own are
ruled in `MIGRATIONS.md`'s 3.8.0 section: seven of `decode_host.py` (the hosted table, the
`Context` it builds, the `--element-table` flag through the parser and its three readers, and the
bounds' basis text) and the conformance suite's `PARKED` — nine rulings over eight units, which the
gate reads and reports nothing unruled. Over the arc the gate's table decides 110 signals, 43 MINOR
and 67 PATCH, and the nine rulings decide the rest.

**Package version 3.8.0 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are six MINORs apart, the sixth for the ordinary reason:
the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out schemas`
reads `CURRENT: schemas vs models at 3.2.0` and `python -m synapse_cdm.manifests --check` reads
`CURRENT: manifests vs 33 shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`,
`MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` did not move in this arc. SC-OES, the
Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is still `0.1.0` and
still a Draft. `synapse_cdm/version.py` states the nine version axes and their independence.

## The `cesmo_internal` adapter, and what it is measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `cesmo_internal` is #34. It was registered thirty-third and
carries an ordinal one higher because ordinal 9 was issued to a specification that has no adapter:
the ordinal is not the roster count. It is ingest-only, `residual: structured`, and declares a
path-bound preservation ledger.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `cesmo_internal` | SC CESMO Internal Exchange 1.0 (`sc.cesmo.internal/1.0`), the internal JSON contract of the SynapseCommand STANAG 4658 CESMO and EOB Engineering Kit 1.0, cited by title and date; binding `provisional-internal-profile` | ingest | one Exchange → per record a `DETECTION` `Event`, an emitter `Entity` and its `TRACK_UPDATE` `Event`, or a `STATUS_CHANGE` `Event`, and one `STATUS_CHANGE` `Event` for an envelope snapshot; the contract's schema as a module literal and published at `schemas/cesmo_internal/`; the `cesmo_internal` fixture set |

**What it reads.** One Exchange per call, as its octets or its parsed dict: an envelope (`contract`,
`mode`, a `source` of network, originator and identity epoch, `message_id`, `observed_at`, at most
1,000 `records` and an optional `snapshot`) and four record kinds. An `observation` becomes a
`DETECTION` Event; an `eob_upsert` an emitter `Entity` (`UNKNOWN`, `attributes.cesmo.role`
`emitter`) then its `TRACK_UPDATE` Event; an `eob_delete` a `STATUS_CHANGE` Event of operation
`withdraw`; a `status` a `STATUS_CHANGE` Event of operation `status`; and an envelope snapshot one
more `STATUS_CHANGE` Event after the records, of operation `snapshot`. Identities are the kit's
section 11 keys — the mode, the network, the originator, the identity epoch and the source's own
object, message and record identifiers — so a `live` Exchange and a `synthetic` one never share an
identity. Geometry is a `Point` only for an explicitly asserted emitter position, its height the
third coordinate and `alt_m`; the error ellipse stays in the attributes and the payload as stated.
Every object carries the envelope without its records and the record verbatim in a structured
residual, and the preservation ledger reads 70 mapped and 190 residual leaves and 0 lost over the
fixtures. The kit's expected projection of its `upsert.json` example is reproduced byte for byte
under `cdm_schema="3.0.0"` and `projection.dump_for`, with the kit's own identities
`75ccd4f2-f73a-5d32-9c27-82585ce69f55` and `64e3ed4a-b5c5-5ec3-9653-adfc5324d3e0`.

**What it refuses, by name.** Every refusal is a `CesmoError`, a `ValueError` whose `code` is one of
the five of the kit's section 19 table the adapter raises — `E_SCHEMA`, `E_SEMANTIC`, `E_LIMIT`,
`E_MODE_MISMATCH` and `E_UNSUPPORTED_MESSAGE` — and whose message, the code, the path and a fixed
detail, never carries a value taken from the payload; the codes the kit gives its gateway and its
projector are listed in the module and never raised. The caps are the contract's: 1,048,576 input
octets, JSON nested 16 deep inside the manifest's 64, 100,000 JSON values, 4,096 code points a
string, 1,000 records and 2,001 CDM objects an Exchange; an octet or depth refusal is at once a
`CesmoError` of code `E_LIMIT` and the base class's `InputTooLarge` or `InputTooDeep`. Strict JSON
on octets (a duplicate key, NaN or Infinity, a byte-order mark, invalid UTF-8, trailing octets),
token patterns with ECMA anchors and ASCII digits, a timestamp grammar with a calendar of its own,
the schema's ranges and the cross-field rules the schema cannot state are each refused at the path
of the first failure, in a fixed order. The adapter's tests assert each of the 37 refused Exchanges
under `fixtures/cesmo_internal/malformed/` (12 `.bin` octet payloads and 25 JSON cases) by its code,
and the contract's refusals by code, path and message on inputs the tests generate, each on both
input paths, including a seeded, deterministic mutation set of 2,000 mutations over the kit's five
examples, which the fuzz module's `--fuzz` entry point extends to any count.

**Where its behaviour comes from.** The kit's specification, cited by title and date and not
carried; its JSON Schema, carried as a module literal and published byte-identical as
`schemas/cesmo_internal/cesmo-internal-1.0.schema.json`, the two held equal by a test; and its five
synthetic examples and its expected projection, carried byte-identical and pinned by SHA-256 in
`fixtures/cesmo_internal/spec/cesmo_internal_pin.json`. Where the kit's reference validator,
`validate_contract.py` 1.0, is looser than the kit's own specification — a trailing newline in a
token, hour 24 on Python 3.14, a non-ASCII digit, a byte cap on a re-serialisation, a number past
binary64, the order of the first failure — the adapter follows the specification, and
`FORMAT_COVERAGE.md`'s section records each departure with the specification line it rests on.
Every fixture is synthetic: the kit's examples, and six documents and an octet twin the fixture
builder writes from them in pure Python, in the kit's invented vocabulary (`TEST-NET`,
`TEST-SOURCE-A`, `EXERCISE-1`, `mode` `synthetic`) with every authored position inside the Baltic
fixture rectangle; the builder's `--check` rebuilds what it writes byte for byte. No capture,
native vector or order-of-battle datum is in the tree.

## `synapse-decode` serves three more adapters

`decode_host.HOSTED` gains the `barentswatch_hais` and `frost_observations` rows, the follow-on the
3.7.0 notes named, and the `cesmo_internal` row, so the hosted table has thirteen entries. Each new
row reads its file whole, with `--received-at` required and the file's digest injected as
`source_hash`. `frost_observations`'s two caller tables are context files: `--station-table`, the
station table the station-text adapters already take, keyed here by the Frost station id, and the
new `--element-table`, a JSON document in the adapter's own `ElementTable` shape, read under the
context-file bounds (1 MiB, 16 levels, strict JSON) and validated by the adapter's constructor. Both
are optional, as they are at the constructor: without one the output says the position or the unit
was not supplied.

## The conformance suite parks `residual`

`synapse_cdm.suite.PARKED` gains `residual`, §28's structured container, beside `attributes`,
`payload` and `source_extras`, so checks J and K no longer judge a source's own record held there
as CDM fields. `lossless.PARKED_KEYS` already parked it, and no golden shipped before this release
had a residual leaf either check would judge; the internal contract's residual is what met it,
because the kit mandates the source's own `observed_at` strings and native identifiers there.
Every adapter that was CONFORMANT stays CONFORMANT, and `tests/test_cdm_suite.py` holds that J and
K do not walk `residual`.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions. The
first is reached for `cesmo_internal` and this release claims it. The second is not claimed
anywhere in the tree: no STANAG 4658 or AEDP-13 message, frame or field is parsed or produced, the
kit itself declares that binding BLOCKED on its unresolved register N01 to N12, and the gateway
that would produce the internal contract, the EOB projector, the journal, egress and the normative
plugin are not in this repository.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter cesmo_internal` on this tree — the records themselves are generated, gitignored, and
  attached by a Release rather than committed: `internal_fixture` PRESENT; `self_round_trip`
  NOT_APPLICABLE, the adapter being ingest-only; `independent_expected` ABSENT; `normative_schema`
  ABSENT; **`independent_endpoint` ABSENT**.
* **Declared maturity is L3 and claim status PROVISIONAL**, read from
  `manifests/cesmo_internal.json`. The claim is `PROVISIONAL` because the binding is
  `provisional-internal-profile`: a green gate proves agreement with a contract this repository's
  owner defines and nothing about a native standard. L4 is not declared: an ingest-only adapter has
  no round trip, and a rung passed vacuously is not a rung declared.
* **The strict readings have met the kit and not a producer**: the contract's grammar, its caps
  and its cross-field rules have met the kit's specification, its schema and its five examples, and
  no Exchange written by a gateway is in the repository.
* **`evidence.available` is `true` on the adapter from this release.** It landed declaring `false`
  — "it becomes true at the first release that attaches them" — and `tests/test_cdm_evidence.py`
  holds the field to the newest release tag's tree. The release commit flipped it, with a
  limitation sentence that names no version, the form the two of 3.7.0 took:
  `.github/workflows/publish.yml` generates the records for every shipped adapter and attaches them
  to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge` 1.1.0, on GitHub only

`packages/link16_bridge/` holds the second distribution, `synapse-link16-bridge`, still 1.1.0
(import `synapse_link16_bridge`, command `synapse-link16-bridge`): nothing under it moved since
`v3.7.0`, and its runtime dependencies are still `synapse-cdm` 3.5.0 or later and below 4, and the
standard library.

It is part of the tag `v3.8.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project is created there in this release, which is an
act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.8.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.8.0#subdirectory=packages/link16_bridge"
```

Its workflow `.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main`
and to the release and arc branches.

## What changed for a 3.7.0 consumer

* **One new adapter module** and one new fixture directory; `--list-adapters` reports
  thirty-three and the harness replays the new adapter with `--adapter cesmo_internal` and no
  `--fixtures`. No other adapter's verdict moved.
* **`synapse-decode`** has thirteen hosted rows: the ten it had at 3.7.0, and the
  `barentswatch_hais`, `frost_observations` and `cesmo_internal` rows, with the `--element-table`
  flag for `frost_observations`.
* **The conformance suite** parks `residual` for checks J and K; an adapter that was CONFORMANT
  stays CONFORMANT.
* **The wire contract is still 3.2.0.** Every object this package writes is stamped `3.2.0`, as at
  3.7.0, except what the compatibility projections of `link16_gateway` and `cesmo_internal`
  (`cdm_schema="3.0.0"`) write.

## Thirty-three adapters at 3.8.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. At `v3.8.0` `python -m synapse_cdm.harness --list-adapters` prints `33 adapters
registered`. Declared maturity and claim status are read from `manifests/<name>.json`.

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
| `cesmo_internal` | ingest | 12 | L3 | PROVISIONAL (new in the 3.8.0 arc) |

**756 fixture verdicts, 0 failed** across the thirty-three, against the published 3.2.0 schemas —
the 744 that 3.7.0 shipped, every golden byte for byte as it was, plus 12 from the new set. The two
readings the wheel gate takes, its `resources` and `harness` checks, run on this tree from a
directory outside the repository, read `33 adapters, 789 fixture files` and `33 adapters x 2 schema modes, 1512 fixture verdicts, 0 failed`; `gates/wheel_install.py`
takes the same readings off the installed wheel in the release workflow. The `lossless` column
reads PASS on every JSON fixture and a stated SKIP on every non-JSON one, and FAIL on none, on a
declared ledger for `pntmap`, the five of the 3.1.0 arc, `dis7`, `tacticalapi`, `link16_gateway`,
the five of the 3.5.0 arc, the three of the 3.6.0 arc, the two of the 3.7.0 arc and the one of this
one, and on the value-presence heuristic, said so, for the other thirteen. The four L4 declarations
(`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger that reports no loss over a self
round trip under the adapter's declared tolerance; every other declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this release:
the first six carry `x-cdm-schema-version: 3.2.0`, as at 3.7.0. The four observation contract
schemas under `schemas/observation/`, generated by `python -m synapse_cdm.observation_contracts`,
and the three gateway schemas under `schemas/link16_gateway/`, the handoff's, did not move either.
`git diff v3.7.0 -- schemas/` adds one file and changes none:
`schemas/cesmo_internal/cesmo-internal-1.0.schema.json`, the kit's contract schema, published
byte-identical beside the adapter's module literal; it is the adapter's input contract and not a
CDM schema.

## Published by CI over OIDC, as 1.1.0 through 3.7.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 29 records the 3.7.0 upload. The workflow builds and uploads
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
pip install synapse-cdm==3.8.0
python -m synapse_cdm.harness --list-adapters
```
