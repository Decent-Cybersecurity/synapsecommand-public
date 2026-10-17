# synapse-cdm 3.5.0

**The observation carrier release, and the second CDM schema MINOR in a row.** Between the 3.4.0
release of 2026-10-11 and this one, the tree gained five adapter modules — `readsb_trace`,
`nexrad2`, `ndbc_stdmet`, `coops_csv` and `airnow_hourly` — and the registry moved from twenty-two
to twenty-seven. They read public observation formats: a readsb aircraft trace, a NEXRAD Level II
weather-radar volume, and three kinds of station text (NDBC buoy data, NOAA CO-OPS water levels and
EPA AirNow air quality). To carry what an environmental measurement states, the CDM gained one
`EventType` member, `ENVIRONMENTAL_OBSERVATION`, the optional `Event.validity` (the interval a
measurement covers) and the optional `Track.attributes` (how much of a history a Track holds), so
the wire contract moved **3.1.0 → 3.2.0**, a MINOR. What an observation states is carried in one of
four named payload contracts, `synapse_cdm.observation_contracts`, whose JSON Schemas are published
under `schemas/observation/`; the offline host command `synapse-decode` reads one local file into
CDM objects; and `synapse_cdm.projection` keeps the 3.0.0 compatibility promise at the dump
boundary. `MIGRATIONS.md`'s 3.5.0 section is the record of what the distribution carries, and the
contracts' text is `docs/docs/cdm/observation-contracts.mdx`.

**If you are upgrading from 3.4.0, upgrade readers before writers.** A 3.5.0 reader reads every
3.4.0 object, and `version.compatible("3.1.0", "3.2.0")` is `True`. A 3.4.0 reader refuses every
3.5.0 Event and every 3.5.0 Track: each now carries a `validity` or an `attributes` key — populated,
or null, because every object is written with all its optional fields — and the published schemas
are `additionalProperties: false`, so `version.compatible("3.2.0", "3.1.0")` is `False`; an Event of
the new type is refused by the closed `EventType` enum as well. A 3.4.0 reader still reads a 3.5.0
Entity or PlanObject, which moved by the stamp alone. A consumer at 3.0.0 is served by the Link 16
adapter's compatibility projection (`cdm_schema="3.0.0"`) and the bridge's `COMPAT_3_0` delivery,
both of which now dump through `projection.dump_for`, which removes the two new keys when they are
null and refuses an object that populates one. A consumer that accepts 3.1.0 and nothing else has
no projection: the `link16_gateway` adapter refuses `cdm_schema="3.1.0"`, and the bridge's
negotiation refuses a sink that accepts 3.1.0 alone, so every full Link 16 Track it would receive
is refused for its null `attributes`. No member of the `Adapter` contract moved, so an adapter
subclass written against 3.4.0 keeps working.

## Why the number is 3.5.0

**The number is the derived floor: a MINOR from `v3.4.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, read "the arc since 3.4.0 derives MINOR with 0 unruled,
so the next release is at least 3.5.0", and its `--json` reported the arc as `{"kind": "MINOR",
"number": "3.5.0", "unruled": []}`. The floor comes from the public names the arc added and from
nothing removed — the five `Adapter` subclasses and their fixture sets, the modules
`observation_contracts`, `decode_host` and `projection`, and the `synapse-decode` entry point — and
from the schema MINOR below, since a schema MINOR is at least a package MINOR. The units the table
cannot decide on its own are ruled in `MIGRATIONS.md`'s 3.5.0 section: the `EventType` member, the
two optional fields on `Event` and `Track`, the repaired guard of `models._timestamp_in` and
`version.KNOWN_CONTRACTS` — five rulings, which the gate reads and reports nothing unruled. Over the
arc the gate's table decides 1218 signals, 272 MINOR and 946
PATCH, and the five rulings decide the rest.

**Package version 3.5.0 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are still three MINORs apart, because each moved a MINOR
on its own table. `python -m synapse_cdm.schemas --check --out schemas` reads `CURRENT: schemas vs
models at 3.2.0` and `python -m synapse_cdm.manifests --check` reads `CURRENT: manifests vs 27
shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`, `MANIFEST_SCHEMA_VERSION` and
`EVIDENCE_SCHEMA_VERSION` did not move in this arc. SC-OES, the Operational Ontology and the profile
versions did not move: `SC_OES_VERSION` is still `0.1.0` and still a Draft.
`synapse_cdm/version.py` states the nine version axes and their independence.

## Why the schema is 3.2.0

`EventType` gained `ENVIRONMENTAL_OBSERVATION` — an environmental measurement or a model product,
whose content a named payload contract states — appended after `SIM_RESULT` so the seven existing
positions keep their values; `Event` gained `validity: TemporalValidity | None`, following
`PlanObject.validity`, so an event can state the interval its measurement covers; and `Track` gained
`attributes: TrackAttributes | None`, a typed block whose one member, `completeness`, states how
many samples a Track carries, how many its source states and whether it is a fragment, with the
carried count held equal to the samples by semantic rule SEM-014. Nothing was removed, renamed or
narrowed, and the table at the top of `MIGRATIONS.md` puts an optional field added and an enum
member added on the MINOR row. A gridded field, an image or a station is not a fifth canonical
kind: an observation is an `Event` with a named contract, a station or radar site an `Entity`.

The 3.2.0 contract is frozen under `tests/frozen/cdm/3.2.0/` beside 3.0.0 and 3.1.0, and
`version.KNOWN_CONTRACTS` reads `("2.0.0", "2.1.0", "3.0.0", "3.1.0", "3.2.0")`.
`tests/test_cdm_version_matrix.py` shows every pair within the major on the frozen bytes: a 3.0.0
or 3.1.0 document of every kind validates under the 3.2.0 schema and models, and a 3.2.0 Event or
Track carrying the new property — populated or null — or an Event of the new type is refused by
both earlier contracts. Every golden moved by its `schema_version` stamp in this release, after the
CDM 3.2.0 landing had added the null `validity` and `attributes` keys. Six schema files moved.
`cdm_object`, `event` and `track` moved past their label: `event` by the member, `validity` and the
definitions it reaches, `track` by `attributes` and its two definitions, and `cdm_object` by both;
`entity`, `plan_object` and `payload_gnss_interference` moved by the label alone. The fourteen SC-OES
examples and the corpus's `SEM-014.json` read 3.2.0, because each carries a field only 3.2.0
defines; the other fourteen semantic-corpus files stay stamped 3.0.0 and are read as documents of
an earlier minor. The DIS 7 adapter's vendored entity profile is re-derived from the 3.2.0 entity
schema, and its pin record keeps the handoff bundle's digests beside the derived ones. No adapter
that shipped before this release writes the new member or populates either new field.

## The observation adapters, and what they are measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `readsb_trace` is #24, `nexrad2` #25, `ndbc_stdmet` #26,
`coops_csv` #27 and `airnow_hourly` #28. They were registered twenty-third to twenty-seventh and carry
ordinals one higher because ordinal 9 was issued to a specification that has no
adapter: the ordinal is not the roster count. All five are ingest-only, `residual: structured`, and
declare a path-bound preservation ledger.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `readsb_trace` | readsb `globe_history` trace JSON, readsb v3.16.17 (`README-json.md`, cited by reference) | ingest | one trace file → one `Entity`, one `Track` stating its completeness and one `TRACK_UPDATE` `Event`; the `readsb_trace` fixture set |
| `nexrad2` | NEXRAD Level II Archive II, ICD 2620010J and ICD 2620002Y, Build 23.0 | ingest | one volume → one `ENVIRONMENTAL_OBSERVATION` `Event` per elevation number carrying `radar-sweep/1`, and the radar site's `Entity`; the `nexrad2` fixture set |
| `ndbc_stdmet` | NDBC standard meteorological text, NDBC Web Data Guide 2.0 | ingest | one file → one `Event` per row carrying `point-observation/1`, and the station's `Entity`; the `ndbc_stdmet` fixture set |
| `coops_csv` | NOAA CO-OPS data API response, CSV and JSON forms | ingest | one response under a required request → one `Event` per sample carrying `point-observation/1`, and the station's `Entity`; the `coops_csv` fixture set |
| `airnow_hourly` | EPA AirNow HourlyData and HourlyAQObs files | ingest | one file → one `Event` per line carrying `point-observation/1`, and one `Entity` per site; the `airnow_hourly` fixture set |

**`readsb_trace`** reads one airframe's positions over one UTC day, as the file's one gzip member
or as the decompressed document in a dict. It is the first producer of `Track.attributes`: every
Track is a fragment of one day whose total the file does not state. Identity is the address
upper-cased under `ICAO24` (`ADSB_NONICAO` for a `~` address), the `(system, external_id)` the
`adsb` adapter derives, so one airframe has one `entity_id` across the two. Barometric feet stay in
`Position.vertical`, never in `alt_m`. Bounds: 8 MiB of input, 64 MiB inflated, depth 64 and
100 000 points, each refused by name before the model is built.

**`nexrad2`** reads one Archive II volume — the volume header, then bzip2-compressed LDM records —
and writes one sweep Event per elevation number (never angle: a SAILS rescan repeats the lowest),
its `observed_at` the last radial's collection time and its `validity` running from the first. Each
moment's gate codes stay in the volume, by reference, with a summary converted with each radial's
own scale and offset; the coded values that are not measurements are counted under their own names.
The ICD's field ranges in Tables XVII-A, -B, -E, -F and -H are validation rules, Table XVII-I's data
ranges are not, and messages 1 and 29 and compressed radials are refused by name. Bounds: 32 MiB of
input and every bzip2 stream inflated under a stated limit.

**`ndbc_stdmet`**, **`coops_csv`** and **`airnow_hourly`** read their files by the header's names,
each value a typed measurement with its unit verbatim or an absence with its cause. NDBC's `MM` is
missing in a realtime file and a run of 9s only at its documented width in a historical one; CO-OPS
reads `gmt`, or `lst` with the caller's declared offset, and refuses `lst_ldt`; an AirNow stamp is
the start of a one-hour period, so `observed_at` is its end. Each file is at most 8 MiB. A station's
position comes only from the caller's station table.

**What they refuse, by name.** Every refusal is the adapter's own `ValueError` subclass —
`ReadsbTraceRefused`, `Nexrad2Refused`, `NdbcStdmetRefused`, `CoopsRefused`, `AirnowRefused` — whose
code names the rule and whose message never quotes a value from the payload, asserted on 75 refused
payloads under the five `malformed/` directories and on inputs the tests generate.

**Where their behaviour comes from.** The governing documents are cited and never carried: readsb's
`README-json.md` at v3.16.17 by URL and SHA-256, the NEXRAD ICDs, the NDBC guide, the CO-OPS pages
and the AirNow fact sheets and Data Exchange Guidelines by their pin records. Every fixture is
synthetic, written by the set's own pure-Python `spec/build_fixtures.py`, whose `--check` rebuilds
it byte for byte; no byte or value of a real collection is in the tree. The AirNow Data Exchange
Guidelines' terms bind a consumer of AirNow data, not this package.

## The observation contracts and `synapse-decode`

`synapse_cdm.observation_contracts` holds the four contracts an `ENVIRONMENTAL_OBSERVATION` Event
carries in `payload["observation"]` — `gridded-field/1`, `point-observation/1`, `radar-sweep/1` and
`imagery-product/1` — closed and frozen models with a measurement and its unit verbatim, typed
quality flags, the source's own grid structure, a locator into the file and values by reference or
inline. Their JSON Schemas are the four files under `schemas/observation/`, an artefact beside the
CDM's, and `python -m synapse_cdm.observation_contracts --check` reads them current. ADR 0012
records them as Accepted on the maintainer's default: the contract owner's answer was pending at
acceptance, and an objection is a later MINOR that adds beside what shipped, never a rewrite.

`synapse-decode` reads one local file through a registered adapter: a bounded read, its SHA-256
checked against `--sha256` or a manifest row, one gzip member or one named tar member unwrapped
under the adapter's bound, and the adapter constructed from values only. A URL, an `s3://` or a
`/vsicurl/` locator is refused by name; the exit codes are 0, 2, 3 and 4, and no diagnostic quotes
the input. It hosts `dis7`, `geojson` and each observation adapter of this release.

## External interoperability is a separate conclusion, and it is NOT claimed

Each new adapter reads a public format from synthetic fixtures. That the translation of
those fixtures is implemented and checked is claimed; that a real file of each format translates is
not, because no real file is in this repository.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter <name>` on this tree for each of the five — the records themselves are generated,
  gitignored, and attached by a Release rather than committed: `internal_fixture` PRESENT;
  `self_round_trip` NOT_APPLICABLE, each being ingest-only; `independent_expected` ABSENT;
  `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **Declared maturity is L3 and claim status VERIFIED** for each, read from `manifests/<name>.json`.
  L4 is not declared: an ingest-only adapter has no round trip, and a rung passed vacuously is not a
  rung declared.
* **The strict readings have met the documents and not yet a real file**: NEXRAD's ICD ranges, the
  AirNow lines that state no reading or a time that is not on the hour, which are refused whole,
  and the CO-OPS unit read verbatim from the request each stand as the stricter reading until a
  real file is read against them.
* **`evidence.available` is `true` on the five from this release.** Each landed declaring `false`
  — "it becomes true at the first release that attaches them" — and `tests/test_cdm_evidence.py`
  holds the field to the newest release tag's tree. The release commit flipped each, with a
  limitation sentence that names no version, the form `link16_gateway`'s took at 3.4.0:
  `.github/workflows/publish.yml` generates the records for every shipped adapter and attaches them
  to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge` 1.1.0, on GitHub only

`packages/link16_bridge/` holds the second distribution, `synapse-link16-bridge`, now 1.1.0 (import
`synapse_link16_bridge`, command `synapse-link16-bridge`). It moved a MINOR: it gained
`negotiate.dump`, through which every object it delivers under `COMPAT_3_0` is serialised by
`synapse_cdm.projection.dump_for`, so a 3.0.0 sink still receives what the frozen 3.0.0 contract
accepts now that every Event and Track carries a CDM 3.2.0 key. Its runtime dependencies are
`synapse-cdm` 3.5.0 or later and below 4 — the floor moved from 3.4.0, because `projection` first
ships in 3.5.0 — and the standard library. Its CLI, its configuration and what a sink receives are
unchanged.

It is part of the tag `v3.5.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project is created there in this release, which is an
act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.5.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.5.0#subdirectory=packages/link16_bridge"
```

Its workflow `.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main`
and to the release and arc branches.

## What changed for a 3.4.0 consumer

* **The wire contract is 3.2.0.** Every object this package writes is stamped `3.2.0`, except what
  `link16_gateway`'s compatibility projection (`cdm_schema="3.0.0"`) writes, which is stamped
  `3.0.0`; every Event carries `validity` and every Track `attributes`, null unless an adapter
  states them. A 3.4.0 reader refuses every 3.5.0 Event and Track and reads every other object.
* **`projection.dump_for(obj, "3.0.0")`** is the one way to serialise a CDM object for the frozen
  3.0.0 contract: it removes the post-3.0.0 properties when null and refuses an object that
  populates one or carries a post-3.0.0 member, naming the path and never quoting a value.
* **Five new adapter modules**, five new fixture directories, the module `observation_contracts`, and the
  command `synapse-decode`; `--list-adapters` reports twenty-seven and the harness replays each new
  adapter with `--adapter <name>` and no `--fixtures`. No other adapter's verdict moved.
* **A value that is neither text nor a datetime** in a timestamp field is refused as a
  `ValidationError` naming its type, where it escaped as an `AttributeError`; an instant whose UTC
  reading leaves the years 0001 to 9999 is refused the same way.

## Twenty-seven adapters at 3.5.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. `python -m synapse_cdm.harness --list-adapters` prints `27 adapters
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
| `readsb_trace` | ingest | 26 | L3 | VERIFIED (new in the 3.5.0 arc) |
| `nexrad2` | ingest | 10 | L3 | VERIFIED (new in the 3.5.0 arc) |
| `ndbc_stdmet` | ingest | 8 | L3 | VERIFIED (new in the 3.5.0 arc) |
| `coops_csv` | ingest | 7 | L3 | VERIFIED (new in the 3.5.0 arc) |
| `airnow_hourly` | ingest | 8 | L3 | VERIFIED (new in the 3.5.0 arc) |

**670 fixture verdicts, 0 failed** across the twenty-seven, against the published 3.2.0 schemas —
the 611 that 3.4.0 shipped, each golden re-stamped and otherwise unchanged but for the null keys
the CDM 3.2.0 landing added, plus 59 from the five new sets. The two readings the wheel gate takes,
its `resources` and `harness` checks, run on this tree from a directory outside the repository,
read `27 adapters, 697 fixture files` and `27 adapters x 2 schema modes, 1340 fixture verdicts, 0 failed`; `gates/wheel_install.py` takes the same readings off
the installed wheel in the release workflow. The `lossless` column reads PASS on every JSON
fixture and a stated SKIP on every non-JSON one, and FAIL on none, on a declared ledger for
`pntmap`, the five of the 3.1.0 arc, `dis7`, `tacticalapi`, `link16_gateway` and the five of this
arc, and on the value-presence heuristic, said so, for the other thirteen. The four L4 declarations
(`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger that reports no loss over a self
round trip under the adapter's declared tolerance; every other declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. The first six moved in this release, each
carrying `x-cdm-schema-version: 3.2.0`; the other three did not move. The four observation
contract schemas under `schemas/observation/` are new in this release, generated by
`python -m synapse_cdm.observation_contracts`; the three gateway schemas under
`schemas/link16_gateway/` are the handoff's and did not move.

## Published by CI over OIDC, as 1.1.0 through 3.4.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 26 records the 3.4.0 upload. The workflow builds and uploads
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
pip install synapse-cdm==3.5.0
python -m synapse_cdm.harness --list-adapters
```
