# synapse-cdm 3.3.0

**The TacticalAPI blue-force read side release.** Between the 3.2.0 release of 2026-10-06 and this
one, the tree gained one adapter module, `tacticalapi`, and the registry moved from twenty to
twenty-one. It reads one response of the TacticalAPI blue-force tracking service
(`rheinmetall.tactical_api.v0`, upstream commit `58661c9`) — a `GetBlueForcesResponse` snapshot or
a `SubscribeBlueForceEventsResponse` stream update, as a serialized `google.protobuf.Any` or as its
parsed twin — into one `Entity` and one `Event` per blue force, in list order. It ships with its
wire reader `tacticalapi_codec`, pinned synthetic fixtures with their goldens and protoc's own
readings of every payload, a field-level preservation ledger (`MAPPINGS`), a structured residual on
every object, declared and enforced input bounds, a manifest, and a harness and conformance
reading of CONFORMANT. Nothing on the wire moved: `SCHEMA_VERSION` stays `3.0.0`, no model, enum or
published schema changed, and no golden of the twenty that predate the arc moved by a byte. The
design record is `docs/tacticalapi-implementation.md`, which ships in nothing; `MIGRATIONS.md`'s
3.3.0 section is the record of what the distribution carries.

**If you are upgrading from 3.2.0, nothing you read or write changes.** A 3.2.0 reader reads a
3.3.0 object unchanged, and `version.compatible("3.0.0", "3.0.0")` is the same answer it was. No
member of the `Adapter` contract moved, so an adapter subclass written against 3.2.0 keeps working.
Of the package's own dependency declarations only the `[lint]` extra's pin moved, ruff 0.16.7 →
0.16.9, a development tool nothing in the package imports.

## Why the number is 3.3.0

**The number is the derived floor: a MINOR from `v3.2.0`.** `gates/bump_derivation.py --json`,
run before any number was typed, reported the arc as `{"kind": "MINOR", "number": "3.3.0",
"unruled": []}`. The floor comes from the public names the arc added and from nothing removed —
the `TacticalapiAdapter` subclass with its wire reader `tacticalapi_codec` and the `tacticalapi`
fixture set — and the one unit the table cannot decide on its own,
`pyproject.toml:optional-dependencies` (the `[lint]` extra's ruff pin, moved in place by the
dependency unit that reached `main` on 2026-10-06), is ruled PATCH in `MIGRATIONS.md`'s 3.3.0
section, which the gate reads and reports nothing unruled. Over the arc the gate's table decides
186 signals, 102 MINOR and 84 PATCH, and the one ruling decides the rest (`--json` at the tag
lists 187).

**Package version 3.3.0 · CDM `schema_version` 3.0.0 · Adapter API 3.1.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two are three MINORs apart, the third for the ordinary
reason: the surface grew and the contract did not. `python -m synapse_cdm.schemas --check --out
schemas` reads `CURRENT: schemas vs models at 3.0.0` and `python -m synapse_cdm.manifests --check`
reads `CURRENT: manifests vs 21 shipped adapters at manifest schema 2.1.0`.
`ADAPTER_API_VERSION`, `MANIFEST_SCHEMA_VERSION` and `EVIDENCE_SCHEMA_VERSION` did not move in this
arc. SC-OES, the Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is
still `0.1.0` and still a Draft. `synapse_cdm/version.py` states the nine version axes and their
independence.

## The `tacticalapi` adapter, and what it is measured to do

In `FORMAT_COVERAGE.md`'s ordinal table `tacticalapi` is #22.
It is the twenty-first registered adapter and carries ordinal 22 because ordinal 9 was issued to a
specification that has no adapter: the ordinal is not the roster count.

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `tacticalapi` | TacticalAPI (`rheinmetall.tactical_api.v0`, upstream commit `58661c9` of 2026-09-01, which has no tag or release), the blue-force read side only: `GetBlueForcesResponse` and `SubscribeBlueForceEventsResponse` | ingest | one response → one `Entity` and one `Event` per blue force; the wire reader `tacticalapi_codec` with the contract's field table embedded; the `tacticalapi` fixture set |

**What it reads.** One already-received response per call, as octets or as the dict a
`.parsed.json` fixture holds; both forms go through one twin and give the same objects. gRPC
framing is not read, and the adapter holds no session, reads no network and keeps nothing between
two calls, so a stream is a sequence of calls. Each blue force becomes an `Entity` — position in
WGS 84 decimal degrees, speed, a course in [0, 360) as `course_deg` with the north reference
assumed true and said so, a symbol only from a MIL-STD-2525D numeric code, and the message and
entry exactly as stated in the typed block `tacticalapi-blueforce/1` — and an `Event`,
`TRACK_UPDATE`, or `STATUS_CHANGE` for a deleted entry, which is a status and never an invented
`valid_to`. Affiliation reads `UNKNOWN`, because the message carries no affiliation field, unless
the caller supplies one keyword-only as `TacticalapiAdapter(affiliation=...)`. Every field the
contract does not name is carried in the structured residual that every `Entity` and every `Event`
carries, and never dropped.

**What it refuses, by name.** Every refusal the codec and the adapter raise is a
`TacticalapiRefused`, a `ValueError` whose `code` is one of the codec's 31 reason codes: every other message of the contract and every
other type; a response whose header does not report success; a blue force without an identity;
a coordinate out of range; encodings a lenient protobuf parser accepts and repairs — a singular
field twice, two members of one oneof, a named field with another wire type, an out-of-range or
overlong varint; a truncated input; and more unknown fields, objects or carried text than the
declared bounds. A payload above the declared 4 195 328-octet bound is refused by the base class
before the decoder runs, and nothing is repaired. The adapter's tests assert the refusals by
name, on the eight committed payloads under `fixtures/tacticalapi/malformed/` and on inputs the
tests generate.

**Where its behaviour comes from.** The contract's ten interface definition files, pinned at
upstream commit `58661c9` outside every repository and found through
`SYNAPSE_CDM_TACTICALAPI_PROTO_DIR`; the maintainer ruled that the Eclipse Public License 2.0
governs them. The adapter embeds only their field names, field numbers and enum values, and both
copies of `NOTICE` state that derivation; no other text of the files is carried, and the files are
neither in this repository nor in the wheel. Every payload is synthetic and starts as protoc's own
encoding of a text source against the pinned files. The adapter declares the licence class `OPEN`.
This repository is not affiliated with, endorsed by or reviewed by the interface's publisher, and
the name says which published contract the adapter reads: it is kept, on the maintainer's ruling,
without seeking the publisher's written consent.

## External interoperability is a separate conclusion, and it is NOT claimed

Local implementation completion and external interoperability completion are two conclusions.
The first is reached for `tacticalapi` and this release claims it. The second is not claimed
anywhere in the tree: no TacticalAPI server, client or captured message has been exercised, and no
exchange with any system is asserted.

* **The five evidence categories**, as generated by `python -m synapse_cdm.evidence generate
  --adapter tacticalapi` on this tree — the records themselves are generated, gitignored, and
  attached by a Release rather than committed: `internal_fixture` PRESENT; `self_round_trip`
  NOT_APPLICABLE, since the adapter is ingest only; `independent_expected` ABSENT;
  `normative_schema` ABSENT; **`independent_endpoint` ABSENT**.
* **The comparison with the pinned contract is a test that needs the pinned files and `protoc`,
  and it does not run in CI.** The two tests that rebuild every generated fixture and compare the
  embedded field table with the pinned descriptor read the directory
  `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` names; no workflow sets it, so in CI they record
  `BLOCKED_EXTERNAL_EVIDENCE` rather than passing.
* **Declared maturity is L3 and claim status VERIFIED**, read from `manifests/tacticalapi.json`.
  L4 is not declared: there is no egress direction for information to be lost in.
* **`evidence.available` is `true` on `tacticalapi` from this release.** The adapter landed
  declaring `false` — "it becomes true at the first release that attaches them" — and
  `tests/test_cdm_evidence.py` holds the field to the newest release tag's tree. The release
  commit flipped it, with a limitation sentence that names no version, the form `dis7`'s took at
  3.2.0: `.github/workflows/publish.yml` generates the records for every shipped adapter and
  attaches them to the Release of the version it publishes. What the field does NOT say: nothing
  about the wheel's contents, and nothing about the three external categories.

## What changed for a 3.2.0 consumer

* **Nothing on the wire.** No field, enum, schema or golden of the twenty that predate the arc
  moved; `git diff v3.2.0 -- schemas/` is empty.
* **A new adapter, `tacticalapi`**, with the keyword-only `affiliation=` argument, and **a new
  fixture directory**, `fixtures/tacticalapi/`; `--list-adapters` reports twenty-one and the
  harness replays `tacticalapi` with `--adapter tacticalapi` and no `--fixtures`. No other
  adapter's verdict moved.
* **`NOTICE` gains one paragraph**, in both copies, stating that the embedded field table derives
  from interface definition files the Eclipse Public License 2.0 governs. The wheel's licence
  metadata does not move: `license` stays `Apache-2.0` and `license-files` stays `LICENSE` and
  `NOTICE`.
* **The `[lint]` extra pins ruff 0.16.9.** The rule set the workflows read from it was measured
  unchanged under the new version (`MIGRATIONS.md`'s 3.3.0 section, the paragraph that begins THE
  RUFF RECORD).

## What else moved

* **The wheel gate knows the new modules.** `gates/wheel_install.py` decides each of the five new
  test modules on one of its two lists, and its `licences` check asserts the derivation statement
  in the installed wheel's `NOTICE`; `tests/test_cdm_packaging.py` asserts it offline in both copies.
  Three gate modules of the arc's own, `gates/tacticalapi_field_table.py`,
  `gates/tacticalapi_contract_comments.py` and `gates/protoc_text.py`, regenerate the embedded
  field table and check that no text of the pinned files reached the arc's files.
* **The dependency unit of 2026-10-06 landed by hand, as one signed-off commit**: the ruff pin
  above; `react`, `react-dom` and `@types/react` at `^19.3.0` and three `overrides` floors in
  `docs/package.json` (`serialize-javascript`, `fast-uri` and `shell-quote`), which now carries
  fifteen `overrides` entries; and `anchore/sbom-action` at v0.24.3 at its four sites in
  `publish.yml` and `rc-build.yml`. `security/exceptions/GHSA-vfj7-8cjw-p6xm.json`, the one
  exception, still excepts `braces`, which has no fixed release, until 2026-12-04, with the
  maintainer as owner. All of the documentation site's dependencies are build-time and ship in
  nothing.
* **Five open items found on the way are recorded and not fixed here**, in the implementation
  record's "Open items": `adapter.wire_size` raises `UnicodeEncodeError` for a `str` holding a
  lone surrogate before any adapter can refuse it; `adapter.wire_size` and
  `adapter.container_depth` take a value's type from `isinstance`, so an in-process object whose
  `__class__` claims octets, text, a `dict` or a `list` raises there; the adapter's
  `validate_source` writes a refusal's text whole; no test raises a plain `ValueError` on the path
  of `validate_source` that handles one; and a released `memoryview` leaves the codec's entry
  points, and the host's `wire_size`, with Python's own `ValueError` and no reason code. None
  touches a claim of this release: four need an input only an in-process caller can build, and
  the fifth is a test the arc did not write.

## Twenty-one adapters at 3.3.0, all harness-verified — and one more in the tree since

`python -m synapse_cdm.harness --adapter <name> --schemas schemas --json`, run over the roster
with no `--fixtures` on this tree, and every verdict read from the run. The table is the live registry, and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both directions to agree. At `v3.3.0` `python -m synapse_cdm.harness --list-adapters` prints `21 adapters registered`. The row marked **post-3.3.0** landed in the tree on 2026-10-10, after that tag, and is in no release. Declared maturity and claim status are read from `manifests/<name>.json`.

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
| `tacticalapi` | ingest | 10 | L3 | VERIFIED (new in the 3.3.0 arc) |
| `link16_gateway` | bidirectional | 15 | L4 | PROVISIONAL (**post-3.3.0**, in no release) |

**596 fixture verdicts, 0 failed** across the twenty-one, against the published 3.0.0 schemas —
the 586 that 3.2.0 shipped, unchanged, plus 10 from the new set. The two readings the wheel gate
takes, its `resources` and `harness` checks, run on this tree from a directory outside the
repository, read `21 adapters, 617 fixture files` and `21 adapters x 2 schema modes, 1192 fixture verdicts, 0 failed`;
`gates/wheel_install.py` takes the same readings off the installed wheel in the release workflow.
The `lossless` column reads PASS on every JSON fixture and a stated SKIP on every non-JSON one,
and FAIL on none, on a declared ledger for `pntmap`, the five of the 3.1.0 arc, `dis7` and
`tacticalapi`, and on the value-presence heuristic, said so, for the other thirteen. The three L4
declarations (`geojson`, `c2sim`, `dis7`) rest on a ledger that reports no loss over a self round
trip under the adapter's declared tolerance; every other declaration is L3.

**Nine schema files**, regenerated from the models by `python -m synapse_cdm.schemas` and
byte-identical to the committed ones: `entity`, `event`, `track`, `plan_object`,
`payload_gnss_interference` and `cdm_object` under `schemas/`, `manifests/adapter-manifest` and
`evidence/evidence` and `evidence/exercise` beside them. None of the nine moved in this arc.

## Published by CI over OIDC, as 1.1.0 through 3.2.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 24 records the 3.2.0 upload.

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
pip install synapse-cdm==3.3.0
python -m synapse_cdm.harness --list-adapters
```
