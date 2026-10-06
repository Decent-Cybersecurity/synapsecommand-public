# synapse-cdm 3.2.0

**The DIS 7 Entity State release.** Between the 3.1.1 release of 2026-09-21 and this one, the tree
gained one adapter module, `dis7`, and the registry moved from nineteen to twenty. It reads one
DIS 7 Entity State PDU into one `Entity` and gives the original octets back from an unchanged
`Entity`; it ships with its codec module, an offline host command `synapse-dis7`, pinned
fixtures with their goldens, a field-level preservation ledger (`MAPPINGS`), a structured
residual, a declared and enforced input bound, a manifest, and a harness and conformance reading
of CONFORMANT. The `Adapter` contract gained one member, `fixture_instance`, whose default is the
construction the SDK performed before it existed. Nothing on the wire moved: `SCHEMA_VERSION`
stays `3.0.0`, no model, enum or published schema changed, and no golden of the nineteen that
predate the arc moved by a byte. The design records are in `docs/dis7-implementation.md`, which
ships in nothing; `MIGRATIONS.md`'s 3.2.0 section is the record of what the distribution carries.

**If you are upgrading from 3.1.1, nothing you read or write changes, except a year below 1000,
which `times.render` now zero-pads on every platform (below).** A 3.1.1 reader reads a
3.2.0 object unchanged, and `version.compatible("3.0.0", "3.0.0")` is the same answer it was. An
adapter subclass written against 3.1.1 keeps working: `fixture_instance` is an addition whose
default returns `cls(clock=clock, synthetic=synthetic)`, and no member was removed or narrowed.

## Why the number is 3.2.0

**The number is the derived floor: a MINOR from `v3.1.1`.** `gates/bump_derivation.py --json`,
run before any number was typed, reported the arc as `{"kind": "MINOR", "number": "3.2.0",
"unruled": []}`. The floor comes from the public names the arc added and from nothing removed —
the `Dis7Adapter` subclass with its codec module, the host module `dis7_host.py` and its console
script, the `dis7` fixture set, `evidence.digest_bytes`, the two `harness` helpers
`overrides_fixture_instance` and `fixtures_refused_message`, and `Adapter.fixture_instance` — and the
eleven units the table cannot decide on its own (`Adapter` itself; the callers in `evidence.py`,
`harness.py` and `suite.py` that now build an adapter through the new hook; `times.render`; the
`ADAPTER_API_VERSION` constant) are every one ruled in `MIGRATIONS.md`'s 3.2.0 section, which the
gate reads and reports nothing unruled. Over the arc the gate's table decides 212 signals, 62 MINOR
and 150 PATCH, and the eleven rulings decide the rest (`--json` at the tag lists 223).

**Package version 3.2.0 · CDM `schema_version` 3.0.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are two MINORs apart, the second for the ordinary
reason: the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out
schemas` reads `CURRENT: schemas vs models at 3.0.0` and `python -m synapse_cdm.manifests --check`
reads `CURRENT: manifests vs 20 shipped adapters at manifest schema 2.1.0`. `ADAPTER_API_VERSION`
moved `3.0.0` → `3.1.0` in this arc for `fixture_instance`, an addition and so a MINOR on that
axis; `MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` stay where the 3.0.0 release put
them. SC-OES, the Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is
still `0.1.0` and still a Draft. `synapse_cdm/version.py` states the nine version axes and their
independence.

## The `dis7` adapter, and what it is measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `dis7` is #21.
It is the twentieth registered adapter and carries ordinal 21 because ordinal 9 was issued to a
specification that has no adapter: the ordinal is not the roster count.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `dis7` | IEEE 1278.1-2012 (DIS 7), the Entity State PDU only: protocol version 7, PDU type 1, protocol family 1 | bidirectional | one PDU of 144 to 4224 octets → one `Entity`; replay of the original octets from an unchanged `Entity`; the host command `synapse-dis7` |

**What it reads.** One Entity State PDU, handed to the adapter with a caller time context: the
state instant and its basis are supplied by the caller, and the PDU's own timestamp is preserved
and never converted. The location is projected from earth-centred coordinates to WGS 84 latitude,
longitude and ellipsoidal height; velocity becomes speed, course and climb only for the
dead-reckoning algorithms whose velocity is in world coordinates. Octets the subset does not
interpret — dead-reckoning parameters, marking, variable parameter records — are kept in the
structured residual and replayed unchanged. Affiliation reads UNKNOWN for every force ID.

**What it refuses, by name.** Every other PDU type, protocol family and DIS version; a PDU
shorter or longer than its own length field and record count say; a payload above the declared
4224-octet bound, refused before it is decoded; an envelope with an unknown key at any level; a
fresh or edited `Entity` on egress. Every refusal carries a code and a path, and the adapter's
tests assert them by name, on the five committed payloads under `fixtures/dis7/malformed/` and on
inputs the tests generate.

**The host command.** `synapse-dis7 decode` writes the one-element Entity array of one PDU file as
canonical JSON, `replay` writes the original PDU octets of a canonical Entity document,
`self-test` runs the packaged vectors and a sample of refusals offline, and `--version` prints the
adapter, package and specification identifiers. Exit codes are `0` success, `2` usage and
flag-derived context, `3` rejected data and a failed self-test, `4` file or output I/O. It reads
the one `--input` file or the packaged vectors, writes stdout and stderr only, and opens no
socket.

**Where its behaviour comes from.** A handoff specification identified by
`SC DIS7 SPEC 001 v1.0`, which is not in this repository; the part of its bundle the tests read —
three vectors, the acceptance cases and five JSON schemas — is vendored under `fixtures/dis7/`
with a pin record that hashes every file. The IEEE 1278.1-2012 text was not consulted: the layout
authority is open-dis-python (https://github.com/open-dis/open-dis-python, BSD-2-Clause) at commit
`732b6655bb47e34ccc73722eefe0f4706fd0032f`, a development reference and never a runtime
dependency. The adapter declares the licence class `LICENSED`, read from the publisher's own page;
the standard is carried neither in this repository nor in the wheel.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions.
The first is reached for `dis7` and this release claims it. The second is not claimed anywhere in
the tree: no IEEE certification, no compatibility with any particular simulator, and no
exchange with a partner system is asserted.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter dis7` on this tree — the records themselves are generated, gitignored, and attached
  by a Release rather than committed: `internal_fixture` PRESENT; `self_round_trip` PRESENT;
  `independent_expected` ABSENT; `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **The comparison with the pinned OpenDIS reference is an opt-in test and does not run in CI.**
  `tests/test_cdm_dis7_reference.py` reads the checkout named by `SYNAPSE_CDM_OPENDIS_DIR`; no
  workflow sets it, so in CI those tests record `BLOCKED_EXTERNAL_EVIDENCE` rather than passing.
  The fixture generator under `fixtures/dis7/spec/` reports whether the reference rebuilds each
  packaged PDU; it writes nothing, and the packaged vectors stay the handoff bundle's bytes.
* **Declared maturity is L4 and claim status VERIFIED**, read from `manifests/dis7.json`: the
  ledger reports no lost leaf and `from_cdm(to_cdm(raw))` reproduces every byte fixture octet for
  octet under the declared `bytes` tolerance. L5 is not declared.
* **`evidence.available` is `true` on `dis7` from this release.** The adapter landed declaring
  `false` — "it becomes true at the first release that attaches them" — and
  `tests/test_cdm_evidence.py` holds the field to the newest release tag's tree. The release
  commit flipped it, with a limitation sentence that names no version:
  `.github/workflows/publish.yml` generates the records for every shipped adapter and attaches them
  to the Release of the version it publishes. What the field does NOT say: nothing about the
  wheel's contents, and nothing about the three external categories. `geojson`, `geopackage`,
  `c2sim`, `aixm511` and `aixm52` still carry the sentence the 3.1.0 release commit wrote,
  naming `evidence-3.1.0.tar.gz` on a `v3.1.0` Release that does not exist, because that tag
  released nothing; the first Release that carries their records is `v3.1.1`'s, and the sentence
  is left for the next arc that touches those modules, because correcting it needs a bump ruling
  per module.

## What changed for a 3.1.1 consumer

* **Nothing on the wire.** No field, enum, schema or golden of the nineteen that predate the arc
  moved; `git diff v3.1.1 -- schemas/` is empty.
* **`Adapter.fixture_instance(clock=None, *, synthetic=True)`.** The harness, the conformance
  suite and the evidence generator now build the instance that replays an adapter's packaged
  fixtures through this classmethod. Its default is the old construction, so no shipped adapter
  but `dis7` overrides it and no verdict of the nineteen moved. Their command lines refuse a
  caller-supplied `--fixtures` for a shipped adapter that overrides it, with exit status 2.
* **Conformance check O builds the adapter before it feeds the oversized payload.** A refusal
  raised while the adapter is built is now FAIL instead of being read as the adapter refusing the
  bound; every adapter the package ships builds through its hook and reads the verdict it read
  before.
* **`evidence.digest_bytes(data)`** returns the SHA-256 and size of octets a caller already holds,
  the pair `digest(path)` returns; `hashlib` is still imported by `evidence.py` alone.
* **`times.render` writes the year as four digits itself.** The output for years 1000 to 9999 is
  byte-identical and no golden moved; a year below 1000 is now zero-padded on every platform.
* **A new console script, `synapse-dis7`**, and **a new fixture directory**, `fixtures/dis7/`;
  `--list-adapters` reports twenty and the harness replays `dis7` with `--adapter dis7` and no
  `--fixtures`.

## What else moved

* **The wheel gate knows the new command and modules.** `gates/wheel_install.py` runs the
  installed `synapse-dis7` in its clean environment, and two gates of the arc's own,
  `gates/dis7_mutation.py` and `gates/dis7_benchmark.py`, hold the adapter's seams and its
  resource behaviour.
* **The documentation site's `npm audit` is clear of blocking advisories.** Three `overrides`
  entries in `docs/package.json` move `brace-expansion`, `http-cache-semantics` and `joi` past
  their advisories, and `security/exceptions/GHSA-vfj7-8cjw-p6xm.json` excepts `braces`, which
  has no fixed release, until 2026-12-04, with the maintainer as owner. It is a build-time
  dependency of the documentation site and ships in nothing.
* **Two SDK defects found on the way are recorded and not fixed here:** `adapter.container_depth`
  does not return on a cyclic dict, and `evidence.generate(name, fixtures=DIR)` raises
  `ValueError` for a directory outside the packaged root. Neither touches a claim of this
  release; the `dis7` adapter holds a parsed envelope to acyclicity itself.

## Twenty adapters at 3.2.0, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --schemas schemas --json`, run over the roster
with no `--fixtures` on this tree, and every verdict read from the run. The table is the live registry, and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both directions to agree. `python -m synapse_cdm.harness --list-adapters` prints `20 adapters registered`. Declared maturity and claim status are read from `manifests/<name>.json`.

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
| `dis7` | bidirectional | 6 | L4 | VERIFIED (new in the 3.2.0 arc) |

**586 fixture verdicts, 0 failed** across the twenty, against the published 3.0.0 schemas — the
580 that 3.1.1 shipped, unchanged, plus 6 from the new set; `gates/wheel_install.py` reads the
same roster off the installed wheel as `20 adapters, 606 fixture files` and `20 adapters x 2 schema modes, 1172 fixture verdicts, 0 failed`.
The `lossless` column reads PASS on every JSON fixture and a stated SKIP on every non-JSON one,
and FAIL on none, on a declared ledger for `pntmap`, the five of
the 3.1.0 arc and `dis7`, and on the value-presence heuristic, said so, for the other thirteen.
The three L4 declarations (`geojson`, `c2sim`, `dis7`) rest on a ledger that reports no loss over
a self round trip under the adapter's declared tolerance; every other declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this arc.

## Published by CI over OIDC, as 1.1.0 through 3.1.1 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 23 records the 3.1.1 upload.

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
pip install synapse-cdm==3.2.0
python -m synapse_cdm.harness --list-adapters
synapse-dis7 self-test
```
