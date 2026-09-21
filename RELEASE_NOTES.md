# synapse-cdm 3.0.1

**The corrective of the tagged-never-published 3.0.0, and the first published release of the audit
remediation arc.** `v3.0.0` was tagged on 2026-09-20 and its own release run (35506445471) refused
it in the build job: the gate job had run the suite green on the same commit, and the build job's
second run of it — in an interpreter that job had first loaded with `twine` and `cyclonedx-bom`,
whose dependency closure made every spawned parser worker import a Lark grammar and seven format
libraries before its first byte of input — crossed a wall-clock budget in one isolation test and
stopped, recording a count and no name. Nothing reached PyPI. What moved between 3.0.0 and 3.0.1
is the release workflow (the tooling now lives in a venv of its own, and condition 4 names the
tests it fails on), `MIGRATIONS.md` and `version.py`; the distribution is otherwise byte-for-byte
the tree `v3.0.0` named, so everything below describes this release. `MIGRATIONS.md`'s 3.0.1
section is the record, and no test budget moved to get here.

**The audit remediation release.** Between the 2.2.0 release of 2026-09-17 and this one, the
independent audit of 2026-09-19 raised nine findings against this package, F01 to F09, and every
one of them is answered in the tree at this tag: version compatibility is directional and rests
on frozen evidence rather than on major-number arithmetic; the lossless check's empty result is
no longer treated as proof, and a path-bound preservation ledger replaces it wherever an adapter
declares its field mappings; the conformance suite's parser deadline is a real, process-isolated
one; the published JSON Schema now states every constraint the Python models enforce; the STANAG
4676 adapter's wire binding is declared provisional in its manifest, its CLI row and its page;
resource limits are enforced where the platform can enforce them and refused where it cannot,
never claimed; evidence records carry five categories with the three external ones honestly
ABSENT; governance is an auditable derivation with a runbook; and the documentation is derived
from the tree and drift-checked. The register of all nine, with reproductions, tests, evidence
paths and what stays external, is `docs/audit-remediation-report.md`. Two things are removed or
narrowed, which is why this is a MAJOR on both of the first two axes — read the next two sections.

**If you are upgrading from 2.2.0 — which is what the index serves — read this as the MAJOR it
is on both numbers.** If you are upgrading from 2.1.2 or earlier, read the 2.2.0 notes first: they
are the body of the `v2.2.0` Release, and everything they describe is still here.

## In the tree since 3.0.1, in no release: the adapter expansion (2026-09-20/21)

**Nothing in this section is in `3.0.1` or in any release.** `PACKAGE_VERSION` still reads `3.0.1`;
the next number is the release round's to type, and `python gates/bump_derivation.py` reads the
pending arc as at least `3.1.0` (MINOR: five new fixture sets, five `Adapter` subclasses, the
`validate` optional extra, and the ruled units `MIGRATIONS.md`'s `### Unreleased` section names).
The roster table below is the LIVE registry — `tests/test_cdm_release.py` holds it to `roster()`
in both directions — so the five rows marked **post-3.0.1** are in the tree and in no artefact
a consumer can install today.

**Implemented capability, measured in this tree** — five, each with pinned synthetic
fixtures, a parsed twin per document, a field-level preservation ledger (`MAPPINGS`), adversarial
tests that detect a wrong mapping, a structured residual, declared and enforced parser bounds, and
a harness and conformance reading of CONFORMANT:

| Adapter | Specification / profile | Direction | What ships |
|---|---|---|---|
| `geojson` | RFC 7946 (Feature, FeatureCollection, the seven geometry types; WGS 84 / CRS84 only, no `crs`) | bidirectional | `geo-object/1` contract, `exchange` and `mirror` export profiles, `no-source-time` declared |
| `geopackage` | OGC GeoPackage 1.4.0 (OGC 12-128r19), feature tables under EPSG:4326 / CRS84 / 4979 | ingest | in-memory read-only authorized snapshot; GDAL 3.13.3 wrote every fixture and is the independent reading |
| `c2sim` | SISO-STD-019-2020 v1.0 + SISO-STD-020-2020 (LOX), C2SIMArtifacts v1.0.1 | bidirectional | initialisation, `MoveToLocation` / `HoldInPlace` orders, position / observation / status reports; `c2sim-order/1` payload contract |
| `aixm511` | AIXM 5.1.1 (April 2016) + Digital NOTAM Event Schema 2.0.m, four pinned scenario profiles | ingest | one `Entity` per time slice, `aixm-timeslice/1` and `aixm-dnotam/1` blocks, `synapse_cdm.aixm_resolve` for effective state from explicit prior state |
| `aixm52` | AIXM 5.2 (schema release 5.2.0, 17 January 2025) | ingest | a second profile on `aixm511`'s reader; Digital NOTAM declared NOT available on 5.2 |

**External interoperability validation is a separate conclusion, and it is NOT claimed.** Normative
schema validation of every positive fixture against the pinned XSD closures (C2SIM, AIXM 5.1.1,
AIXM 5.2, Digital NOTAM) is a test that runs only where the schemas are held OUTSIDE this
repository and the `validate` extra is installed, and records `BLOCKED_EXTERNAL_EVIDENCE` otherwise;
the `normative_schema` evidence category reads from that. `independent_expected` rests on GDAL's
own reading of the GeoPackage fixtures and on the pinned independent samples; `independent_endpoint`
is ABSENT for every one of the five — no partner system, reference server or exercise has been
exchanged with, and `examples/c2sim/exercise_client.py` is the opt-in procedure, not a result.
`evidence.available` is `false` on all five until a Release attaches their records. The
implementation record is `docs/adapter-expansion-implementation.md`.

## Why the number is 3.0.1

**The number is the derived floor twice over: a PATCH from `v3.0.0` for the corrective — an arc of
the release workflow, `MIGRATIONS.md` and `version.py`, which `gates/bump_derivation.py` derives
as PATCH with nothing unruled — on top of the MAJOR the 3.0.0 release commit typed over `v2.2.0`,
the first MAJOR since 2.0.0.** For that arc, `gates/bump_derivation.py` reads from `v2.2.0` and
derives MAJOR from one shape signal —
`lossless.unrepresented`, an importable name removed with no alias, because the old name was a
claim of proof the function could not make — and from the units whose meaning changed and were
ruled MAJOR in `MIGRATIONS.md`'s 3.0.0 section: `version.compatible` and `version.parse` (F01),
`harness.run` and `evidence.badges` (F02), `suite.check_malformed` and
`suite.check_parser_robustness` (F03), `conformance.assess_a`, `conformance._validator` and
`models.Timestamp` (F04), `manifest.AdapterMetadata`, `Stanag4676Adapter` and `parse_document`
(F05), `harness.load_raw` (F06) and `evidence.EvidenceRecord` (F07). The units the table cannot
classify on its own are every one ruled in that section, and the gate reads those rulings and
reports nothing unruled.

**Package version 3.0.1 · CDM `schema_version` 3.0.0 · Adapter API 3.0.0 · manifest schema 2.1.0
· evidence schema 2.0.0.** The first two were level at the 3.0.0 release commit and are one PATCH
apart at this one, and **the equality was a coincidence of two separately argued majors and not a
derivation**: the package moved on `version.py`'s table for a
removed name and ruled meaning changes; the schema moved on `MIGRATIONS.md`'s table because
finding F04 NARROWED the published contract (next section). `ADAPTER_API_VERSION` moved
2.1.0 -> 3.0.0 on `VERSIONING.md` §3's own row because `AdapterMetadata.binding` is required with
no default; the manifest schema moved 1.2.0 -> 2.0.0 for that required field and 2.0.0 -> 2.1.0 for
one added enum member; the evidence schema moved 1.0.0 -> 2.0.0 for three required fields. SC-OES,
the Operational Ontology and the profile versions did not move: `SC_OES_VERSION` is still `0.1.0`
and still a Draft. `synapse_cdm/version.py` states the nine version axes and their independence,
and `tests/test_cdm_packaging.py` sweeps the package for an assignment that would derive one number
from another.

## What changed on the wire, and what a 2.2.0 consumer must do

**The published schema is narrower, and that is the MAJOR.** The four object schemas under
`schemas/` carry `pattern` on every `schema_version` and `adapter_version`, `pattern` on
`Entity.symbol` and `uniqueItems` on `Entity.ontology_types`. Every one of those constraints
restates what the Python models enforced already, so no document this package ever emitted becomes
invalid — but a consumer validating with the published schema alone accepted
`"adapter_version": "banana"` under 2.1.0 and is refused it under 3.0.0, and the bump table in
`MIGRATIONS.md` puts a narrowed type on the MAJOR row for exactly that reader. No path was removed, no
`required` list grew, no enum member went. The 2.1.0 contract stays frozen under
`tests/frozen/cdm/2.1.0/` beside the 3.0.0 one under `tests/frozen/cdm/3.0.0/`, and
`tests/test_cdm_version_matrix.py` shows the narrowing on the frozen bytes.

**Every golden moved by one stamp.** The 538 golden files under the package's `fixtures/*/golden/`
and the eight reference-position goldens under `fixtures/adsb/local/` carry
`schema_version: "3.0.0"` and differ from 2.2.0's by that line alone; the harness reads the same
538 fixture verdicts, 0 failed, on every adapter. The fourteen examples under `examples/` declare
`3.0.0` too (they declared `2.0.0` through two minors): `synapse conformance` reads a document's
`schema_version` against this package's, and a document of another major is refused in its
structural dimension rather than read on trust.

**What to change in a 2.2.0 consumer, in one place:**

* Rename `lossless.unrepresented` to `lossless.value_presence_heuristic`, and read its `{}` as
  "nothing seen", not as proof.
* Expect `version.compatible(written_with, read_by)` to answer `False` for any pair a major apart
  (`("2.1.0", "3.0.0")` in either direction), `False` for a writer newer than the reader within a
  major, `False` for a minor nobody has frozen, and to raise `ValueError` on a malformed string
  (a trailing newline, a leading zero, a prefix, a sign). Use `version.assess()` for the verdict,
  the direction and the evidence it rests on. `KNOWN_CONTRACTS` reads `("2.0.0", "2.1.0", "3.0.0")`.
* Declare `binding=` on every adapter's metadata: `"standard-encoding"` where the wire form is the
  cited document's own encoding, `"provisional-internal-profile"` with a limitation containing
  "provisional" where the element names or namespace were chosen locally. A provisional binding
  claims `PROVISIONAL` (new) and not `VERIFIED`.
* Expect the harness's `lossless` column to FAIL on a ledger loss for an adapter that declares
  `MAPPINGS`, and the `lossless-verified` badge to read `heuristic` for one that does not.
* Expect the suite's H and N checks to carry outcome codes in `details`, and N's
  `over_time_bound` strings to name a code rather than a duration; expect `--startup-timeout`,
  `--diagnostics`, `--memory-limit-bytes` and `--cpu-limit-seconds` on the suite's CLI, the last
  two refused with an explicit reason on a platform that cannot enforce them.
* Expect the conformance tool to refuse a string boolean, a trailing newline in a version, a
  malformed UUID and a timestamp outside the wire form on the JSON path.
* Expect `--list-adapters` to print a `binding` column; expect an evidence record to carry
  `snapshot`, `evidence_categories` and `maturity_support`, and a manifest to carry `binding`.
* Nothing is migrated in place: manifests, schemas, evidence and goldens are regenerated from
  their sources.

## Two maintainer rulings, applied in this release

**Preservation maturity is declared to what the evidence proves.** Eleven manifests declared L4
ROUNDTRIP VERIFIED on a basis sentence that cited the `lossless` check as evidence — and since
F02 that check, for an adapter with no declared field mappings, rests on the value-presence
heuristic: a source value present somewhere in the output is not a value that reached its path.
"Applicable information survives source -> CDM -> source" is precisely the claim the heuristic
cannot prove, so `adsb`, `ais`, `cat021`, `cat023`, `cat034`, `cat048`, `cat062`, `gmti`,
`stanag4609`, `stanag4676` and `tak` declare **L3** from this release, each basis sentence says why,
and `tests/test_cdm_manifests.py` holds a bidirectional adapter to L3 wherever the report's
`preservation.basis` reads `heuristic`. Their `roundtrip` columns still read PASS and the suite's
`maturity_eligible` still computes L5 from the verdicts; what moved is the declaration, and an
adapter regains L4 when its field mappings are declared and the ledger reports no loss. `pntmap`,
the one adapter with a ledger, is ingest-only and stays at L3 for the reason it always gave.

**A provisional binding claims PROVISIONAL.** `manifests/stanag4676.json` declared
`claim_status: VERIFIED` beside `binding: provisional-internal-profile`. A gate that passes against
element names chosen in this repository verifies nothing about the standard, so `ClaimStatus` gains
a seventh member, `PROVISIONAL` (the manifest schema's 2.1.0), the adapter claims it, and
`manifest.AdapterMetadata` refuses the two fields apart in both directions. `VERIFIED` returns
with `standard-encoding` or `normative-verified` — the road to which is the register's §5 item 1.

## The nine findings, and what each one left open

* **F01 — version compatibility** is directional and evidence-based: `assess()` returns a verdict,
  a direction and the frozen evidence; the 2.0.0 and 2.1.0 contracts are frozen from their tags
  and 3.0.0 from this commit. Nothing external.
* **F02 — preservation** rests on a path-bound ledger where `MAPPINGS` are declared (one shipped
  adapter today) and on the heuristic, said so, everywhere else. Declaring mappings for the other
  thirteen is queued work, one adapter per session.
* **F03 — parser deadlines** are process-isolated (`multiprocessing` spawn over `os.pipe()`), with
  a six-code outcome vocabulary and one refusal among them.
* **F04 — schema and model alignment**: the published schema states what the models enforce, a
  semantic-rules document and a 44-case corpus cover what a schema cannot say, and the wire path
  refuses a string boolean, a trailing newline and a malformed UUID.
* **F05 — STANAG 4676**: `binding` is a required field on every manifest, the 4676 adapter reads
  `provisional-internal-profile`, an explicit normative mode exists and refuses with a five-step
  procedure until an authorised XSD pair and a validator are supplied. The normative verification
  itself is external and has not happened.
* **F06 — resource limits**: input bounds on depth and bytes, memory and CPU limits enforced on
  Linux and refused with a reason elsewhere; the Linux enforcement branch is first observed by
  the remote CI of the pushed branch.
* **F07 — evidence**: five categories per record, the three external ones ABSENT on every adapter,
  a runner and a verifier for exercise reports. No partner, exercise or date is invented.
* **F08 — governance**: one workflow defect closed, workflow properties tested, an audit gate that
  says UNVERIFIED rather than guessing, two staged ruleset proposals and a runbook. Applying a
  ruleset needs an administrator and has not been done.
* **F09 — documentation**: a current-contracts page generated from the constants, a support matrix
  generated from the declarations, symbol citations instead of line numbers, and a widened lint
  gate with an explicit, shrink-only baseline.

## What else moved

* **No runtime dependency changed.** `pydantic` and `jsonschema`, as before; `jsonschema` was
  already a runtime dependency before F04 used it on the Python path.
* **No adapter was added or removed**, and no adapter's translation changed: every golden moved by
  its `schema_version` stamp and by nothing else.
* **The release rehearsal gate** (`gates/release_ref_rehearsal.py`) replays every ref-dependent
  release step against the local tag before it is pushed, as it has since 2.1.2; it is refused
  without a tag, which is the reading the release commit records before the tag exists.
* **The release workflow moved, and it is the reason this is 3.0.1 and not 3.0.0.** The build
  job's `twine` and `cyclonedx-py` live in a venv of their own, so the interpreter that runs
  condition 4's suite receives the documented install and nothing else, and condition 4 writes the
  suite's output to a file and prints the failing tests before it stops. Nothing about the ref was
  involved, which is why the rehearsal gate passed `v3.0.0` and was right to.

## Fourteen adapters at 3.0.1, all harness-verified — and five more in the tree since

`python -m synapse_cdm.harness --adapter <name> --update-golden`, run over the roster with no
`--fixtures` at this commit, and every verdict read from the run. The table is the live registry,
and `tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree. **The roster did not move in the 3.0.1 arc**: at `v3.0.1` `discover()` and
`roster()` each return fourteen, the same fourteen names in the same two directions as 2.2.0. The
five rows marked **post-3.0.1** landed in the tree on 2026-09-20/21 (the section at the top) and
are in no release; their verdict counts are this tree's harness reading, not 3.0.1's.

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
| `geojson` | bidirectional | 4 | L4 | VERIFIED (**post-3.0.1**, in no release) |
| `geopackage` | ingest | 8 | L3 | VERIFIED (**post-3.0.1**, in no release) |
| `c2sim` | bidirectional | 10 | L4 | VERIFIED (**post-3.0.1**, in no release) |
| `aixm511` | ingest | 10 | L3 | VERIFIED (**post-3.0.1**, in no release) |
| `aixm52` | ingest | 10 | L3 | VERIFIED (**post-3.0.1**, in no release) |

**538 fixture verdicts, 0 failed** across the fourteen adapters 3.0.1 shipped, against the
published 3.0.0 schemas — the same 538 as 2.2.0; the five post-3.0.1 rows add 42 in this tree (`python -m synapse_cdm.harness --adapter <name>`, 2026-09-21). The `roundtrip` column reads PASS for the eleven emitters and a
declared SKIP for the three that emit nothing; the `lossless` column reads PASS on every one, on
the ledger for `pntmap` and on the heuristic, said so, for the other thirteen.

## Published by CI over OIDC, as 1.1.0 through 2.2.0 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration, and entry 20 records the 2.2.0 upload.

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
pip install synapse-cdm==3.0.1
python -m synapse_cdm.harness --list-adapters
```
