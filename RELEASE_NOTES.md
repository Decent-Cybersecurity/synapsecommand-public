# synapse-cdm 3.7.0

**The HIGH NORTH release.** Between the 3.6.0 release of 2026-10-18 and this one, the tree gained
two adapter modules — `barentswatch_hais` and `frost_observations` — and the registry moved from
thirty to thirty-two. Both were written outside this repository for the HIGH NORTH data pack
(Martin Uhrin, 2026-10-20), offered for review, and landed here rewritten to this repository's
fixture rules. They read two public observation feeds of the Norwegian high north: a BarentsWatch
Historic AIS track response (one MMSI's decoded position reports over one requested window), which
becomes an `Entity`, a `Track` and a `TRACK_UPDATE` `Event` identified under the same `AIS`
source-id system the shipped `ais` adapter derives; and a MET Norway Frost `ObservationResponse`
(`GET /observations/v0.jsonld`), which becomes `ENVIRONMENTAL_OBSERVATION` Events carrying the
`point-observation/1` contract 3.5.0 published, one per data item and Frost time class, and one
`SENSOR` Entity per station. Nothing on the wire moved: `SCHEMA_VERSION` stays `3.2.0`, no model,
enum or published schema changed, and no golden of an adapter that predates the arc moved by a
byte. `MIGRATIONS.md`'s 3.7.0 section is the record of what the distribution carries.

**If you are upgrading from 3.6.0, nothing you read or write changes.** A 3.6.0 reader reads a
3.7.0 object unchanged, and `version.compatible("3.2.0", "3.2.0")` is the same answer it was. No
member of the `Adapter` contract moved, so an adapter subclass written against 3.6.0 keeps working.
`synapse-decode` serves neither new adapter yet — `frost_observations` needs two caller tables the
host has no request parameter for — and every invocation that worked against 3.6.0 works the same
way.

## Why the number is 3.7.0

**The number is the derived floor: a MINOR from `v3.6.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, reported the pending arc as `{"kind": "MINOR",
"number": "3.7.0", "unruled": []}`. The floor comes from the public names the arc added and from
nothing removed — the two `Adapter` subclasses `BarentswatchHaisAdapter` and
`FrostObservationsAdapter` with their fixture sets — and the gate's table decides every unit of the
arc on its own: on the release tree it reads 136 signals, 70 MINOR and 66 PATCH, and no ambiguity,
so `MIGRATIONS.md`'s 3.7.0 section carries no bump ruling and the gate reads the same MINOR with the
tag and without it.

**Package version 3.7.0 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are five MINORs apart, the fifth for the ordinary reason:
the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out schemas`
reads `CURRENT: schemas vs models at 3.2.0` and `python -m synapse_cdm.manifests --check` reads
`CURRENT: manifests vs 32 shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`,
`MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` did not move in this arc. SC-OES, the
Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is still `0.1.0` and
still a Draft. `synapse_cdm/version.py` states the nine version axes and their independence.

## The HIGH NORTH adapters, and what they are measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `barentswatch_hais` is #32 and `frost_observations` #33.
They were registered thirty-first and thirty-second and carry ordinals one higher because ordinal 9
was issued to a specification that has no adapter: the ordinal is not the roster count. Both are
ingest-only, `residual: structured`, and declare a path-bound preservation ledger.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `barentswatch_hais` | the BarentsWatch Historic AIS API, `GET /v1/historic/tracks/{mmsi}/{from}/{to}` (cited by URL), and the `ais` adapter's MMSI-category rule for the entity type | ingest | one response → one `Entity`, one `Track` and one `TRACK_UPDATE` `Event`, always the three; the `barentswatch_hais` fixture set |
| `frost_observations` | MET Norway Frost, `GET /observations/v0.jsonld`, its concepts page and its element table (cited by URL) | ingest | one response → one `ENVIRONMENTAL_OBSERVATION` `Event` per data item and Frost time class carrying `point-observation/1`, and one `SENSOR` `Entity` per station; the `frost_observations` fixture set |

**`barentswatch_hais`** reads one Historic AIS track response, as its octets or its parsed twin: a
JSON array of decoded position reports for one MMSI, delivered newest first. The Entity is typed
from the MMSI's ITU category exactly as the shipped `ais` adapter types a decoded message — a
coast-station or aid-to-navigation MMSI is a `FACILITY` whatever it transmits, every other MMSI a
`PLATFORM` — and identified by the MMSI rendered as nine digits under the `AIS` system, so one
vessel has one `entity_id` and one `entity_type` across both adapters; its residual holds the whole
document in file order. The Track carries one sample per element that states a usable position,
re-ordered ascending by `msgtime` with the file order recorded, duplicate instants kept and listed
rather than merged or refused, and the AIS in-band sentinels (latitude 91, longitude 181, the
unavailable speed, course and heading codes) read as absences. A required key missing, an MMSI that
is not nine digits or differs between elements, an instant without an offset, a coordinate outside
its range or a negative speed is refused by name. Bounds: 16 MiB a response and a parse depth of
64, each refused by name.

**`frost_observations`** reads one Frost `ObservationResponse`, as its octets or its parsed twin,
and writes one Event per data item and time class: Case 1, an instant observation, and Case 2.2, a
daily aggregate whose `observed_at` is the period's end and whose `validity.effective` is the day.
The element id, value and unit are carried verbatim in a `Measurement` whose namespace names
Frost's element table; a level is a `VerticalLevel` as stated and never a `Position.alt_m`; quality
codes are carried as MET's data clarifications page defines them. Positions come only from the
caller's station table — the response states none and the adapter fetches nothing — so a station
absent from the table is emitted without a position with the basis saying so, and a unit stated
by neither the observation nor the caller's element table is an `Absence` of cause `unit_unknown`
with the number kept verbatim in the residual: no unit is ever guessed from an element's name.
Bounds: 16 MiB a response, 50 000 objects and a parse depth of 64, each refused by name.

**What they refuse, by name.** Every refusal is the adapter's own `ValueError` subclass —
`BarentswatchHaisRefused`, `FrostRefused` — whose code names the rule and whose message never
quotes a value from the payload, asserted on 27 refused payloads under the two `malformed/`
directories (4 `.hais` octet payloads and 11 JSON cases for `barentswatch_hais`; 2 `.jsonld` octet
payloads and 10 JSON cases for `frost_observations`) and on inputs the tests generate.

**Where their behaviour comes from.** The governing documents are cited by reference and never
carried: the BarentsWatch Historic AIS API page, MET Norway's Frost concepts page and element
table, by their pin records, each recording the licence class `PUBLIC_GOVERNMENT`. Every fixture is
synthetic and written by its own builder in pure Python: five payloads with their `.parsed.json`
twins a set, MMSIs under MID 299 as the `ais` fixtures require, station ids in the `SN0000x` block
`CONTRIBUTING.md` reserves for Frost fixtures, and every position inside the Baltic fixture
rectangle. Each builder's `--check` rebuilds what it writes byte for byte. No byte or value of a
real BarentsWatch or Frost response is in the tree.

## External interoperability is a separate conclusion, and it is NOT claimed

Each new adapter reads a public feed from synthetic fixtures. That the translation of those
fixtures is implemented and checked is claimed; that a real response of either feed translates is
not, because no real response is in this repository.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter <name>` on this tree for each of the two — the records themselves are generated,
  gitignored, and attached by a Release rather than committed: `internal_fixture` PRESENT;
  `self_round_trip` NOT_APPLICABLE, each being ingest-only; `independent_expected` ABSENT;
  `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **Declared maturity is L3 and claim status VERIFIED** for each, read from `manifests/<name>.json`.
  L4 is not declared: an ingest-only adapter has no round trip, and a rung passed vacuously is not a
  rung declared.
* **The strict readings have met the documents and not yet a real response**: the Historic AIS
  track shape and its sentinels, the `ObservationResponse` shape, the two Frost time classes and
  the quality-code table each stand as the stricter reading until a real response is read against
  them.
* **The Frost positions and fallback units are the caller's.** The response states neither; the
  adapter's two tables are constructor arguments, so what a Frost Event says about where a station
  is and what unit an unstated reading has is the caller's statement, recorded with its basis.
* **`evidence.available` is `true` on the two from this release.** Each landed declaring `false`
  — "it becomes true at the first release that attaches them" — and `tests/test_cdm_evidence.py`
  holds the field to the newest release tag's tree. The release commit flipped each, with a
  limitation sentence that names no version, the form the three of 3.6.0 took:
  `.github/workflows/publish.yml` generates the records for every shipped adapter and attaches them
  to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge` 1.1.0, on GitHub only

`packages/link16_bridge/` holds the second distribution, `synapse-link16-bridge`, still 1.1.0
(import `synapse_link16_bridge`, command `synapse-link16-bridge`): nothing under it moved since
`v3.6.0`, and its runtime dependencies are still `synapse-cdm` 3.5.0 or later and below 4, and the
standard library.

It is part of the tag `v3.7.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project is created there in this release, which is an
act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.7.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.7.0#subdirectory=packages/link16_bridge"
```

Its workflow `.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main`
and to the release and arc branches.

## What changed for a 3.6.0 consumer

* **Two new adapter modules** and two new fixture directories; `--list-adapters` reports
  thirty-two and the harness replays each new adapter with `--adapter <name>` and no `--fixtures`.
  No other adapter's verdict moved.
* **`synapse-decode`** is unchanged: it serves the thirty it served at 3.6.0, and the two new
  adapters' rows are a follow-on.
* **The wire contract is still 3.2.0.** Every object this package writes is stamped `3.2.0`, as at
  3.6.0, except what `link16_gateway`'s compatibility projection (`cdm_schema="3.0.0"`) writes.

## Thirty-two adapters at 3.7.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. At `v3.7.0` `python -m synapse_cdm.harness --list-adapters` prints `32 adapters
registered`. The row marked **post-3.7.0** landed in the tree after that tag, `cesmo_internal` on
2026-10-24, and is in no release. Declared maturity and claim status are read from
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
| `barentswatch_hais` | ingest | 10 | L3 | VERIFIED (new in the 3.7.0 arc) |
| `frost_observations` | ingest | 10 | L3 | VERIFIED (new in the 3.7.0 arc) |
| `cesmo_internal` | ingest | 12 | L3 | PROVISIONAL (**post-3.7.0**, in no release) |

**744 fixture verdicts, 0 failed** across the thirty-two, against the published 3.2.0 schemas — the
724 that 3.6.0 shipped, every golden byte for byte as it was, plus 20 from the two new sets. The
two readings the wheel gate takes, its `resources` and `harness` checks, run on this tree from a
directory outside the repository, read `32 adapters, 776 fixture files` and `32 adapters x 2 schema
modes, 1488 fixture verdicts, 0 failed`; `gates/wheel_install.py` takes the same readings off the
installed wheel in the release workflow. The `lossless` column reads PASS on every JSON fixture and
a stated SKIP on every non-JSON one, and FAIL on none, on a declared ledger for `pntmap`, the five
of the 3.1.0 arc, `dis7`, `tacticalapi`, `link16_gateway`, the five of the 3.5.0 arc, the three of
the 3.6.0 arc and the two of this one, and on the value-presence heuristic, said so, for the other
thirteen. The four L4 declarations (`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger
that reports no loss over a self round trip under the adapter's declared tolerance; every other
declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this release:
the first six carry `x-cdm-schema-version: 3.2.0`, as at 3.6.0, and `git diff v3.6.0 -- schemas/`
is empty. The four observation contract schemas under `schemas/observation/`, generated by
`python -m synapse_cdm.observation_contracts`, and the three gateway schemas under
`schemas/link16_gateway/`, the handoff's, did not move either.

## Published by CI over OIDC, as 1.1.0 through 3.6.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 28 records the 3.6.0 upload. The workflow builds and uploads
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
pip install synapse-cdm==3.7.0
python -m synapse_cdm.harness --list-adapters
```
