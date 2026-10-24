# synapse-cdm 3.6.0

**The raster observation release.** Between the 3.5.0 release of 2026-10-16 and this one, the tree
gained three adapter modules — `grib2`, `cog` and `iem_n0q` — and the registry moved from
twenty-seven to thirty. They read the gridded and raster halves of the public observation formats
3.5.0 began with: a GRIB edition 2 message (a model or analysis field, or a radar-derived
estimate), a Cloud Optimized GeoTIFF, classic GeoTIFF or GDAL VRT index (an elevation model or a
satellite band file, header-only), and an IEM NEXRAD N0Q radar composite PNG. Each becomes an
`ENVIRONMENTAL_OBSERVATION` `Event` carrying the `gridded-field/1` or `imagery-product/1` contract
3.5.0 published, or, for a GeoTIFF or VRT that states no time and is given none, an `ANNOTATION`
`PlanObject`. The two raster adapters share a standard-library codec, `adapters/raster_codec.py`
(the TIFF and GeoTIFF structure, block decoding and a PNG reader), and the offline host command
`synapse-decode` serves all three, cutting a GRIB2 file into its messages. Nothing on the wire
moved: `SCHEMA_VERSION` stays `3.2.0`, no model, enum or published schema changed, and no golden of
an adapter that predates the arc moved by a byte. `MIGRATIONS.md`'s 3.6.0 section is
the record of what the distribution carries.

**If you are upgrading from 3.5.0, nothing you read or write changes.** A 3.5.0 reader reads a
3.6.0 object unchanged, and `version.compatible("3.2.0", "3.2.0")` is the same answer it was. No
member of the `Adapter` contract moved, so an adapter subclass written against 3.5.0 keeps working.
`synapse-decode` gains three rows and a framer, and every invocation that worked against 3.5.0
works the same way: a host entry that declares no frame offset is handed exactly what it was.

## Why the number is 3.6.0

**The number is the derived floor: a MINOR from `v3.5.0`.** `gates/bump_derivation.py`, run on the
landing commit before any number was typed, read "the arc since 3.5.0 derives MINOR with 0
unruled, so the next release is at least 3.6.0", and its `--json` reported the arc as `{"kind":
"MINOR", "number": "3.6.0", "unruled": []}`. The floor comes from the public names the arc added and
from nothing removed — the three `Adapter` subclasses `Grib2Adapter`, `CogAdapter` and
`IemN0qAdapter` with their fixture sets, and the codec module `raster_codec` — and the units the
table cannot decide on its own, the host module's `Hosted`, `HOSTED`, `decode` and `listing`, each
of which gained something and kept what it had, are ruled MINOR in `MIGRATIONS.md`'s 3.6.0 section,
which the gate reads and reports nothing unruled. Over the arc the gate's table decides 379
signals, 172 MINOR and 207 PATCH, and the four rulings decide the rest.

**Package version 3.6.0 · CDM `schema_version` 3.2.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are four MINORs apart, the fourth for the ordinary
reason: the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out
schemas` reads `CURRENT: schemas vs models at 3.2.0` and `python -m synapse_cdm.manifests --check`
reads `CURRENT: manifests vs 30 shipped adapters at manifest schema 2.1.0`.
`ADAPTER_API_VERSION`, `MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` did not move in this
arc. SC-OES, the Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is
still `0.1.0` and still a Draft. `synapse_cdm/version.py` states the nine version axes and their
independence.

## The raster adapters, and what they are measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `grib2` is #29, `cog` #30 and `iem_n0q` #31. They were
registered twenty-eighth to thirtieth and carry ordinals one higher because ordinal 9 was issued to
a specification that has no adapter: the ordinal is not the roster count. All three are
ingest-only, `residual: structured`, and declare a path-bound preservation ledger.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `grib2` | GRIB edition 2 (WMO FM 92, WMO-No. 306, and the NCEP GRIB2 documentation, both cited by reference): grid templates 3.0 and 3.30, product templates 4.0 and 4.8, data representation templates 5.0, 5.3, 5.41 and 5.40 in reference form | ingest | one message → one `ENVIRONMENTAL_OBSERVATION` `Event` per field carrying `gridded-field/1`; the `grib2` fixture set |
| `cog` | OGC GeoTIFF 1.1, OGC COG 1.0 and TIFF 6.0 (cited by reference), and GDAL's VRT index form, header-only | ingest | one file → one `ENVIRONMENTAL_OBSERVATION` `Event` carrying `imagery-product/1` when a sensing time is stated or supplied, otherwise one `ANNOTATION` `PlanObject`; the codec `raster_codec`; the `cog` fixture set |
| `iem_n0q` | W3C PNG, Third Edition, and IEM's `composite_n0q` product (cited by URL) | ingest | one composite → one `ENVIRONMENTAL_OBSERVATION` `Event` carrying `gridded-field/1` at the caller's archive slot; the `iem_n0q` fixture set |

**`grib2`** reads one GRIB edition 2 message, as its octets or its parsed twin, and writes one
Event per field: the reference time as `observed_at`, never a future valid instant, with its Code
Table 1.2 significance; the forecast's validity, an instant or Template 4.8's interval, as
`validity.effective`; the grid verbatim and a WGS84 footprint Polygon — a lat/lon grid's corners,
a Lambert conformal grid's outline converted point by point on the template's sphere; and the
values by reference, with a summary decoded from simple packing, complex packing with spatial
differencing and PNG. JPEG 2000 fields are read in reference form and their values declared
unsupported. A parameter is named, and its unit stated, only for the code-table rows its pin lists;
any other keeps its code. Bounds: 8 MiB a message, at most 16 fields and 2^25 grid points a message
(complex packing can describe a run of equal values in no octets at all), and a PNG field's rows
compared with a 64 MiB bound before they are inflated, each refused by name.

**`cog`** reads one classic GeoTIFF or Cloud Optimized GeoTIFF, or one GDAL VRT index, as its
octets or its parsed twin, header-only: every directory, the GeoKeys, GDAL's metadata and nodata
are kept in the residual, every block is checked to lie in the file, and one block, block 0 of the
full-resolution image, is decoded (none, LZW, Deflate or PackBits, with predictors 2 and 3) and
summarised in its stored values, inline when small. A file whose metadata states a sensing time,
or whose caller supplies one with its basis, becomes an Event; a file that names a sensed product's
processing clock and states no sensing time is refused unless the caller supplies one; any other
file is a PlanObject under the structured limitation `no-source-time`. The footprint comes from
EPSG:4326, EPSG:4269 (stated without a datum shift) or a WGS84 UTM zone, converted point by point;
every other system is refused, and a NAVD88 height datum is stated beside the values, never as an
ellipsoidal height. A VRT's sources are listed and never opened, and a remote one is refused by
name. Bounds: 256 MiB a file, a decoded block of at most 1 MiB, and at most 64 directories, 128
entries a directory, 1 MiB a value, 4 MiB of values in all and 65 536 VRT elements.

**`iem_n0q`** reads one IEM N0Q composite PNG, as its octets or its parsed twin. The grid is a
product constant the adapter declares — 12200 x 5400 cells of 0.005 degree in EPSG:4326 — and the
PNG's header is held to it before anything is inflated; the archive's world file is never read.
Palette index 0 is missing and index i is (i − 65) / 2 dBZ; the 65 880 000 values stay in the file by
reference, with a summary in dBZ. A PNG states no time, so `observed_at` is the archive file name's
five-minute slot, which the caller supplies with its basis; IEM's `gentime` text, a generation
clock, is carried verbatim as the product's version and never as a time. Bounds: 8 MiB a file, the
rows held to the constant grid's 65 885 400 octets under an 80 MiB bound, and, since this release,
at most 64 ancillary chunks and 1 MiB of their data octets in all, refused in the chunk walk before
anything is inflated.

**What they refuse, by name.** Every refusal is the adapter's own `ValueError` subclass —
`Grib2Refused`, `CogRefused`, `IemN0qRefused` — whose code names the rule and whose message never
quotes a value from the payload, asserted on 29 refused payloads under the three `malformed/`
directories (11 GRIB2 messages, 8 GeoTIFFs and 2 VRT indexes, 8 PNGs) and on inputs the tests
generate.

**Where their behaviour comes from.** The governing documents are cited by reference and never
carried: the NCEP GRIB2 pages and WMO-No. 306, OGC GeoTIFF 1.1, OGC COG 1.0 and TIFF 6.0, the W3C
PNG specification and IEM's pages, by their pin records. Every fixture is synthetic: the `iem_n0q`
set is written in pure Python by its builder, which writes its own DEFLATE stream; six GRIB2
messages and every malformed one by the `grib2` builder's own encoder and seven by GDAL 3.13.3;
two VRT indexes by the `cog` builder and eight GeoTIFFs by GDAL 3.13.3. Each builder's `--check`
rebuilds what it writes byte for byte and, where GDAL is absent, holds the tool-written files to
their recorded digests and says so. No byte or value of a real collection is in the tree.

## `synapse-decode`, three rows more

`synapse-decode` reads one local file through a registered adapter, as 3.5.0 shipped it, and now
serves the three: `grib2` with a framer that cuts a GRIB2 file into its messages end to end and
hands each over with its ordinal, the octet it begins at and, when it is not the whole file, its own
digest — a gap, an edition 1 message or a length that disagrees is refused; `cog`, with the band
file's name, the granule and the role of a supplied instant (`time=sensing_time` or `time=as_of`)
as request parameters, the file read whole under its 256 MiB bound; and `iem_n0q`, with `--at` the
archive slot and `--received-at` required. A URL, an `s3://` or a `/vsicurl/` locator is still
refused by name; the exit codes are still 0, 2, 3 and 4, and no diagnostic quotes the input.

## External interoperability is a separate conclusion, and it is NOT claimed

Each new adapter reads a public format from synthetic fixtures. That the translation of those
fixtures is implemented and checked is claimed; that a real file of each format translates is not,
because no real file is in this repository.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter <name>` on this tree for each of the three — the records themselves are generated,
  gitignored, and attached by a Release rather than committed: `internal_fixture` PRESENT;
  `self_round_trip` NOT_APPLICABLE, each being ingest-only; `independent_expected` ABSENT;
  `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **Declared maturity is L3 and claim status VERIFIED** for each, read from `manifests/<name>.json`.
  L4 is not declared: an ingest-only adapter has no round trip, and a rung passed vacuously is not a
  rung declared.
* **The strict readings have met the documents and not yet a real file**: the GRIB2 templates and
  code-table rows read, Code Table 3.2's two sphere radii (which rest on GDAL 3.13.3's reading of the
  table, recorded in the pin, rather than on a pinned copy of it), the GeoTIFF coordinate systems and
  compressions read, and the N0Q product constant, its `gentime` text and the ancillary chunks a real
  composite carries each stand as the stricter reading until a real file is read against them.
* **A values summary's domain is the producer's.** `cog` summarises a window in its stored values,
  with the file's scale and offset stated beside it; `grib2` and `iem_n0q` summarise decoded values.
  The observation-contracts page says so, and one domain for every producer is the contract
  owner's to rule.
* **`evidence.available` is `true` on the three from this release.** Each landed declaring `false`
  — "it becomes true at the first release that attaches them" — and `tests/test_cdm_evidence.py`
  holds the field to the newest release tag's tree. The release commit flipped each, with a
  limitation sentence that names no version, the form the five of 3.5.0 took:
  `.github/workflows/publish.yml` generates the records for every shipped adapter and attaches them
  to the Release of the version it publishes.

## The bridge, `synapse-link16-bridge` 1.1.0, on GitHub only

`packages/link16_bridge/` holds the second distribution, `synapse-link16-bridge`, still 1.1.0
(import `synapse_link16_bridge`, command `synapse-link16-bridge`): nothing under it moved since
`v3.5.0`, and its runtime dependencies are still `synapse-cdm` 3.5.0 or later and below 4, and the
standard library.

It is part of the tag `v3.6.0` and of the GitHub Release's source archives, and it is not part of
this wheel or of the package index: no second project is created there in this release, which is an
act for the account owner. It installs from the tag, after `synapse-cdm` from the index:

```bash
pip install synapse-cdm==3.6.0
pip install "synapse-link16-bridge @ git+https://github.com/Decent-Cybersecurity/synapsecommand-public@v3.6.0#subdirectory=packages/link16_bridge"
```

Its workflow `.github/workflows/gateway-bridge.yml` runs its offline tests on every push to `main`
and to the release and arc branches.

## What changed for a 3.5.0 consumer

* **Three new adapter modules**, three new fixture directories and the codec module
  `raster_codec`; `--list-adapters` reports thirty and the harness replays each new adapter with
  `--adapter <name>` and no `--fixtures`. No other adapter's verdict moved.
* **`synapse-decode`** serves `grib2`, `cog` and `iem_n0q`, and lists a framed entry with the words
  `framed by message`; every existing listing line and invocation is unchanged.
* **The wire contract is still 3.2.0.** Every object this package writes is stamped `3.2.0`, as at
  3.5.0, except what `link16_gateway`'s compatibility projection (`cdm_schema="3.0.0"`) writes.

## Thirty adapters at 3.6.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas`, run over the roster with no
`--fixtures` on this tree, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. At `v3.6.0` `python -m synapse_cdm.harness --list-adapters` prints `30 adapters
registered`. The rows marked **post-3.6.0** landed in the tree after that tag, `barentswatch_hais`
and `frost_observations` on 2026-10-22, and are in no release. Declared maturity and claim status
are read from `manifests/<name>.json`.

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
| `grib2` | ingest | 26 | L3 | VERIFIED (new in the 3.6.0 arc) |
| `cog` | ingest | 20 | L3 | VERIFIED (new in the 3.6.0 arc) |
| `iem_n0q` | ingest | 8 | L3 | VERIFIED (new in the 3.6.0 arc) |
| `barentswatch_hais` | ingest | 10 | L3 | VERIFIED (**post-3.6.0**, in no release) |
| `frost_observations` | ingest | 10 | L3 | VERIFIED (**post-3.6.0**, in no release) |

**724 fixture verdicts, 0 failed** across the thirty, against the published 3.2.0 schemas — the 670
that 3.5.0 shipped, every golden byte for byte as it was, plus 54 from the three new sets. The two readings the wheel gate takes,
its `resources` and `harness` checks, run on this tree from a directory outside the repository,
read `30 adapters, 754 fixture files` and `30 adapters x 2 schema modes, 1448 fixture verdicts, 0 failed`; `gates/wheel_install.py` takes the same readings off
the installed wheel in the release workflow. The `lossless` column reads PASS on every JSON
fixture and a stated SKIP on every non-JSON one, and FAIL on none, on a declared ledger for
`pntmap`, the five of the 3.1.0 arc, `dis7`, `tacticalapi`, `link16_gateway`, the five of the 3.5.0
arc and the three of this one, and on the value-presence heuristic, said so, for the other thirteen. The four L4 declarations
(`geojson`, `c2sim`, `dis7`, `link16_gateway`) rest on a ledger that reports no loss over a self
round trip under the adapter's declared tolerance; every other declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this release:
the first six carry `x-cdm-schema-version: 3.2.0`, as at 3.5.0, and `git diff v3.5.0 -- schemas/`
is empty. The four observation contract schemas under `schemas/observation/`, generated by
`python -m synapse_cdm.observation_contracts`, and the three gateway schemas under
`schemas/link16_gateway/`, the handoff's, did not move either.

## Published by CI over OIDC, as 1.1.0 through 3.5.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 27 records the 3.5.0 upload. The workflow builds and uploads
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
pip install synapse-cdm==3.6.0
python -m synapse_cdm.harness --list-adapters
```
