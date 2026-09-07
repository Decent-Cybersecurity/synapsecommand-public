# SC-OES — final engineering report

**Status: Draft.** SC-OES v0.1.0 and the SynapseCommand Operational Ontology v0.1.0 are published
from this repository as drafts. Neither has been submitted to, reviewed by, or approved by any
external standards body, and nothing in this report should be read as implying that it has.

This report is the closing record of the SC-OES implementation campaign. Every figure in it is a
reading taken from the tree at commit `1282897` on branch `sc-oes/0.1`, with the command or the
`file:line` that produced it named beside it. Where a figure is a decision rather than a
measurement, the document that decides it is cited.

---

## Summary

What was built, in the order it was built:

* **A normative specification.** Sixteen numbered documents and a README under
  [`spec/sc-oes/`](../spec/sc-oes) — 2 222 lines across the seventeen, `wc -l spec/sc-oes/*.md` —
  covering conventions, core, event classes, event types,
  temporality, lifecycle, verification and confidence, provenance and evidence, event
  relationships, entity semantics, security markings, extensions, versioning, conformance,
  security considerations and governance — plus seven domain profiles.
* **A governance skeleton.** Six documents under [`spec/governance/`](../spec/governance)
  (637 lines): the governance charter, the event-type process, the ontology-term process, the
  profile process, the deprecation policy and security reporting.
* **An operational ontology.** Eight Turtle modules under [`ontology/`](../ontology) (816 lines),
  a JSON-LD context, and a generated runtime term registry that a drift gate keeps in step with
  the Turtle.
* **CDM 2.0.** `Event` gained an optional `oes` block and `Entity` gained an optional
  `ontology_types` list; `SCHEMA_VERSION` moved `1.0.0` → `2.0.0`; the six published JSON Schemas
  and 538 golden files were regenerated.
* **A governed event registry** of thirteen event types, shipped inside the package as data, with
  loader helpers and a payload map.
* **Conformance tooling** in five separately reportable dimensions with four exit codes, a
  `--require` selector, human and JSON output, and no aggregate verdict.
* **A reference producer.** The PNTMAP adapter emits the SC-OES block on its four goldens.
* **Fourteen worked examples** — thirteen individual and one chain — and seven domain profiles.
* **Documentation, packaging and licensing**, three hand-written site pages, a README positioned
  around the layer boundary, and two repository-wide gates that keep the boundary and the
  positioning claims true.
* **This audit**, the security and IP sweeps below, and this report.

Size of the campaign, against the tip of `main` it branched from:
`git diff --shortstat 23ec65d..HEAD` → **661 files changed, 23 464 insertions(+), 1 403
deletions(-)**; excluding regenerated goldens, **123 files changed, 20 881 insertions(+), 95
deletions(-)**. 84 files are additions.

---

## ADR status

Ten decision records under [`docs/adr/`](adr). Every one is **Accepted — M, 2026-09-06, per
SC-OES-SPEC-v2**, and each was re-examined under the SA.1 architecture correction; the status line
of each names that review.

| ADR | Final decision, in its own first line |
|---|---|
| 0001 — attachment model | Attach SC-OES as an optional declared field `Event.oes`, typed by a new strict model |
| 0002 — ontology representation | The hybrid: Turtle is authoritative, and both derived artefacts are generated from it |
| 0003 — identifier and namespace strategy | Event-type grammars per the specification; ontology terms in the `tag:` URI family |
| 0004 — registry packaging | Both registries ship, at the specification's path, reached by a third `package-data` glob |
| 0005 — CDM schema version impact | `SCHEMA_VERSION` `1.0.0` → `2.0.0`, a MAJOR; `PACKAGE_VERSION` moves on its own derivation |
| 0006 — canonicalization and integrity | Document the properties the repository already has, and implement nothing |
| 0007 — legacy event-type mapping | The specification's table, adopted verbatim, stored in the registry's `legacy_event_type` |
| 0008 — extension mechanism | `oes.extensions` as one declared bag inside a strict block, `dict[str, Any]` |
| 0009 — conformance model | Five separately reportable dimensions, one column each, PASS / FAIL / SKIP, never a single score |
| 0010 — open-source packaging and licensing | Apache-2.0 for everything this work authors, achieved by adding nothing |

---

## Architecture

```text
   source formats (ASTERIX, STANAG 4676/4607, TAK, AIS, ADS-B, KLV, …)
                              |
                        adapters  (14 registered)
                              v
                   Canonical Data Model  — what shape is this record
                packages/cdm/, schemas/  — Entity, Event, Track, PlanObject
                              |
              +---------------+----------------+
              |                                |
              v                                v
  Operational Ontology                      SC-OES
  what does this term mean          what kind of operational assertion is this
  ontology/*.ttl (authoritative)    spec/sc-oes/, Event.oes
  Entity.ontology_types                     |
              |                             |
              +--------------+--------------+
                             v
                  interoperable consumers
                             |
                             |  (the line this repository is drawn around)
                  - - - - - -+- - - - - - - - - - - - - - - - - - - -
                             v
             SynapseCommand private runtime — what should be done about it
                        not here, and not published
```

Four relationships, stated rather than implied:

* **CDM → Operational Ontology.** The ontology does not change the CDM's shape. It attaches
  meaning to an entity through one optional list of governed identifiers, `Entity.ontology_types`.
* **CDM → SC-OES.** SC-OES does not change the CDM's shape either. It attaches operational-event
  semantics through one optional block on the existing `Event`, `Event.oes` (ADR 0001).
* **Operational Ontology ↔ SC-OES.** A governed event type names an ontology class; the registry
  carries the reference and dimension C checks it against the term registry.
* **All three → the private runtime.** Reasoning, inference, correlation and fusion, scoring and
  course-of-action generation are the product and are not in this repository. The language that
  product reads is. `tests/test_cdm_boundary.py` enforces this over every module in the package —
  171 tests, no import of a private root, no reasoner, no graph database, no message broker, no
  model SDK, no crypto.

---

## Versions

| Number | Value | Where read |
|---|---|---|
| `PACKAGE_VERSION` | `1.8.0` | `packages/cdm/synapse_cdm/version.py:165` |
| `SCHEMA_VERSION` | `2.0.0` | `version.py:160` |
| `SC_OES_VERSION` | `0.1.0` | `version.py:171` |
| ontology version | `0.1.0` | `registry/sc_oes/ontology_terms.json`, `ontology_version` |
| profile versions | `0.1.0`, all seven | `profile_version:` in each `spec/sc-oes/profiles/*.md` |
| registry artefact version | `1`, at SC-OES `0.1.0` | `registry/sc_oes/event_types.json` |

Three independent axes, and the independence is asserted rather than assumed:
`tests/test_cdm_packaging.py` fails the build if anything derives one number from another.
`PACKAGE_VERSION` is deliberately unmoved by this campaign — see **Remaining limitations**.

---

## Files added

84 files. The ones that matter:

| Path | What it is |
|---|---|
| `spec/sc-oes/00…15-*.md`, `README.md` | the normative specification, sixteen documents |
| `spec/sc-oes/profiles/*.md` | seven domain profiles |
| `spec/governance/*.md` | six governance process documents |
| `ontology/*.ttl` | eight authoritative Turtle modules |
| `ontology/context.jsonld` | the generated JSON-LD context |
| `packages/cdm/synapse_cdm/oes.py` | the `Oes` block model and its enumerations |
| `packages/cdm/synapse_cdm/oes_registry.py` | the registry loader and its helpers |
| `packages/cdm/synapse_cdm/conformance.py` | the five-dimension conformance tool and CLI |
| `packages/cdm/synapse_cdm/registry/sc_oes/event_types.json` | the governed event-type registry (shipped) |
| `packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json` | the generated term registry (shipped) |
| `gates/ontology_terms.py` | the ontology drift gate and the generator |
| `examples/sc-oes/**` | fourteen worked examples and their README |
| `docs/adr/0001…0010-*.md` | ten decision records |
| `docs/docs/sc-oes/*.mdx` | three hand-written site pages |
| `docs/sc-oes-implementation-plan.md` | the campaign's audit and plan |
| `tests/test_cdm_{oes,registry,ontology,conformance,conformance_spec,examples,profiles,positioning}.py` | 596 new tests |

## Files modified

39 files outside the regenerated goldens. The ones that matter:

| Path | What changed |
|---|---|
| `packages/cdm/synapse_cdm/models.py` | `Event.oes`, `Entity.ontology_types` |
| `packages/cdm/synapse_cdm/version.py` | `SCHEMA_VERSION` → `2.0.0`; `SC_OES_VERSION` added |
| `packages/cdm/synapse_cdm/MIGRATIONS.md` | the MAJOR entry and its compatibility statements |
| `packages/cdm/synapse_cdm/adapters/pntmap.py` | the reference producer emits the block |
| `packages/cdm/pyproject.toml` | the registry `package-data` glob; `rdflib` in the `test` extra |
| `packages/cdm/synapse_cdm/__init__.py` | the ontology and SC-OES names on the public surface |
| `schemas/*.schema.json` | six regenerated documents |
| `gates/wheel_install.py` | the repository-bound test roster the closure check reads |
| `README.md`, `docs/README.md`, `docs/docs/intro.mdx` | positioning, the layer table, the boundary |
| `tests/test_cdm_{boundary,packaging,publication,pntmap_adapter}.py` | the new invariants |
| 538 golden files | see **Golden changes** |

---

## Registry

Thirteen governed event types, read from
`packages/cdm/synapse_cdm/registry/sc_oes/event_types.json`. The file is hand-authored under
`spec/governance/EVENT-TYPE-PROCESS.md` and is the machine authority for a type's class, maturity,
ontology class, payload model and legacy mapping.

| Event type | Maturity |
|---|---|
| `sc.pnt.gnss_interference.v1` | DRAFT |
| `sc.air.air_track_observed.v1` | DRAFT |
| `sc.air.runway_availability_changed.v1` | DRAFT |
| `sc.air.airspace_restriction_changed.v1` | DRAFT |
| `sc.logistics.supply_threshold_reached.v1` | DRAFT |
| `sc.logistics.route_availability_changed.v1` | DRAFT |
| `sc.c2.system_availability_changed.v1` | DRAFT |
| `sc.mission.mission_status_changed.v1` | DRAFT |
| `sc.isr.threat_assessment_updated.v1` | EXPERIMENTAL |
| `sc.mission.operational_impact_assessed.v1` | EXPERIMENTAL |
| `sc.decision.recommendation_created.v1` | EXPERIMENTAL |
| `sc.decision.decision_recorded.v1` | EXPERIMENTAL |
| `sc.decision.action_authorized.v1` | EXPERIMENTAL |

Eight DRAFT, five EXPERIMENTAL, **none STABLE**. No type in this release claims stability, and the
maturity ladder is `spec/governance/EVENT-TYPE-PROCESS.md`'s.

---

## Ontology

`python3 gates/ontology_terms.py` → **73 terms, 8 modules, 2 derived artefacts in sync, 0 failed**.

| Reading | Value |
|---|---|
| modules | 8 — `core`, `air`, `c2`, `decision`, `isr`, `logistics`, `mission`, `pnt` |
| terms | 73 — 58 classes, 15 properties |
| terms per module | core 46, air 8, logistics 5, pnt 4, c2 3, decision 3, isr 2, mission 2 |
| Turtle | 816 lines across the eight modules |
| identifier family | `tag:synapsecommand.com,2026-09-06:ontology:<module>:<Term>` |

Relationships: the Turtle is the single authority (ADR 0002). Two artefacts are **generated** from
it — `ontology/context.jsonld` and the shipped `registry/sc_oes/ontology_terms.json` — and the gate
regenerates both and fails on any difference, so the three cannot silently drift apart. Each term
carries its module, kind, parent, maturity, a deprecation flag and a replacement slot. Domain
modules inherit from `core`: for example `air:AirTrackObservedEvent` has parent
`core:ObservationEvent`.

The runtime never parses Turtle. It reads the generated JSON registry as data — asserted by
`tests/test_cdm_boundary.py::test_the_ontology_is_read_by_the_runtime_as_data_and_never_parsed_as_turtle`.

---

## Conformance

Five separately reportable dimensions, `python -m synapse_cdm.conformance` or the
`cdm-conformance` console script:

| Key | Dimension | What it assesses |
|---|---|---|
| A | CDM Conformance | the object is valid at CDM 2.0.0 — assessed with the `oes` block removed, per `13-conformance.md` |
| B | SC-OES Core Syntax Conformance | the block's own syntax and declared specification version |
| C | SC-OES Semantic Type Conformance | the claimed type against the registry's class, ontology class, payload and legacy mapping |
| D | SC-OES Profile Conformance | the object against a named profile's rules |
| E | Ontology Conformance | the governed identifiers the object carries |

CLI behaviour, each reading taken from a run:

* **Verdicts are `PASS`, `FAIL` or `SKIP`, per object and per dimension.** There is no aggregate
  verdict, score, grade or percentage, and the tool says so in its own footer: *"No aggregate
  verdict, score, grade or percentage is produced, and SKIP is not PASS: it means this was not
  assessed."*
* **Exit codes** are 0 success, 1 a required dimension failed or was not assessed, 2 usage,
  3 internal.
* **`--require A,B,C`** names the dimensions the caller requires. A required dimension that FAILs
  *or* SKIPs makes the invocation unsuccessful, and the reported verdict is never rewritten to make
  the exit code follow from it. Reading: `--profile PNT --require D` on the PNT example prints the
  full five-column report and exits **1**, with D still reported as SKIP.
* **`--profile`** is required for a dimension D assessment. Omitted, D is SKIP — the tool does not
  infer which profile a producer meant.
* **`--json`** produces the same report machine-readably; `--list-dimensions` prints the dimensions
  and the exit codes.
* **Offline.** No network access at any point; see **Security**.

Over all fourteen worked examples (37 objects), `--json`, no profile named:
A 37 PASS · B 19 PASS, 18 SKIP · C 19 PASS, 18 SKIP · D 37 SKIP · E 37 PASS; every file exits 0.
The 18 SKIPs in B and C are the non-event objects: SC-OES metadata is carried on `Event`.

---

## Compatibility

Stated as `packages/cdm/synapse_cdm/MIGRATIONS.md` states it, and no wider.

* **A CDM 1.x reader meeting a 2.x event: not compatible, and no claim is made that it is.** The
  canonical models are `extra="forbid"` and the published schemas are
  `additionalProperties: false`, so a 1.0.0 consumer meeting `oes` or `ontology_types` **rejects**
  the object rather than ignoring it. `version.compatible("2.0.0", "1.0.0")` → `False` (reading
  taken). This is why the schema move is a MAJOR and is not described as a forward-compatible 1.1
  change.
* **A CDM 2.x reader meeting legacy 1.x data.** The 2.0.0 models accept a legacy object
  structurally unchanged: both new fields are optional with defaults, so **no field mapping exists
  and none is needed**. What refuses it is the version gate —
  `version.compatible("1.0.0", "2.0.0")` → `False` (reading taken) — so a 2.x consumer that wants
  legacy data takes an explicit decision: branch on the major, or re-emit the object at 2.0.0,
  where the only value that moves is `schema_version` itself.
* **There is no migrator in the package and none is introduced.** Nothing was removed, renamed or
  narrowed; the migration is two documented statements rather than code.

---

## Golden changes

538 golden files changed. Compared **by JSON path** between `v1.8.0` and this commit, every change
falls into exactly three intentional categories and there is no fourth:

| Category | Files | What moved |
|---|---|---|
| `schema_version` | 538 | `1.0.0` → `2.0.0` on every canonical object |
| `ontology_types` | 537 | the field appears on every entity, empty (`[]`) |
| `oes` | 480 | the field appears on every event, `null` |

Plus the reference producer's own output, which is a subset of the third category rather than a
fourth: on the **4** PNTMAP goldens `oes` is a populated block, and the thirteen leaf paths that
appear under it are the block's fields. Three carry values —
`type_id: sc.pnt.gnss_interference.v1`, `event_class: OBSERVATION`, `spec_version: 0.1.0` — and the
rest are absent-to-`null` or empty. **Nothing outside `oes`, `ontology_types` and `schema_version`
moved in any golden file.**

---

## Dependencies

| Class | Declared where | Packages | Licence |
|---|---|---|---|
| runtime | `packages/cdm/pyproject.toml`, `[project] dependencies` | `pydantic>=2.6`, `jsonschema>=4.0` | MIT, MIT |
| test | `[project.optional-dependencies] test` | `pytest>=8.0`, `rdflib>=7.0` | MIT, BSD-3-Clause |
| development | none declared beyond the `test` extra | — | — |
| documentation | `docs/package.json` | Docusaurus 3.10.2 with `@docusaurus/faster`, MDX 3, React 19, TypeScript ~6.0 | MIT |

The campaign added **one** dependency: `rdflib`, and it is a test dependency and nothing else. It
is what the ontology's own tests parse `ontology/*.ttl` with. Versions resolved in the working
virtualenv, with the licence each declares in its own metadata: pydantic 2.13.4 MIT,
jsonschema 4.26.0 MIT, rdflib 7.6.0 BSD-3-Clause, pyparsing 3.3.2 MIT (rdflib's one non-optional
dependency), pytest 9.1.1 MIT. All permissive and all compatible with this repository's Apache-2.0
policy.

`tests/test_cdm_boundary.py::test_the_rdf_parser_is_declared_in_the_test_extra_and_only_there` and
`::test_the_runtime_dependencies_are_the_two_the_documents_promise` make the budget a build
failure rather than a promise.

---

## Tests

Every command below was run at this commit and the result beside it is what it printed. Nothing is
reported here that was not run.

| Command | Result |
|---|---|
| `python -m pytest -q` (working tree) | **3 failed, 4435 passed, 3 skipped in 85.06s** |
| fresh clone of the branch (`git clone --no-local -b sc-oes/0.1`), new virtualenv, editable install of the distribution root with the `test` extra, `pytest -q` | **4370 passed, 71 skipped, 0 failed** |
| `python3 gates/parks_table.py` | 13 rows, 0 set-claims, **0 failed** |
| `python3 gates/pin_paths.py` | 30 copies, 30 matched, **0 failed** |
| `python3 gates/ontology_terms.py` | 73 terms, 8 modules, 2 derived artefacts in sync, **0 failed** |
| `python3 gates/bump_derivation.py --mutation-check` | 1 check, **0 failed**; pending arc MINOR, floor `1.9.0`, `unruled: []` |
| `python3 gates/commit_message.py --rev HEAD` | `clean` |
| `python3 gates/deploy_record.py` | 22 deployments listed, 0 unaccounted for; served docs and `version.py` agree at 1.8.0; 2 checks, **0 failed** |
| `python -m synapse_cdm.schemas --check --out schemas` | `CURRENT: schemas vs models at 2.0.0` |
| `python3 gates/wheel_install.py --mutation-check`, real half | **13 checks, 0 failed** |
| — its manifest | 1 333 files, equal to git in both directions |
| — its closure | 58 modules: 29 judge the package, 29 judge the repository |
| — its resources and harness | 14 adapters, 538 fixture files; 14 adapters × 2 schema modes, **1 076 fixture verdicts, 0 failed** |
| — its console scripts | `cdm-harness`, `cdm-schemas` and `cdm-conformance` all run from an installed wheel |
| — its slice | 29 modules + the plant: 2 863 passed, 1 skipped |
| `python3 gates/wheel_install.py --mutation-check`, mutant half | 13 checks, **5 failed** — `harness`, `manifest`, `prose`, `resources`, `scripts` all refused a fixture-less wheel, so the gate can fail |
| `npm run ci` in `docs/` | green: schema docs `CURRENT — 9 generated files match`, `gen:schemas` 0 written / 9 current, `tsc` clean, `docusaurus build` `[SUCCESS]`, admonitions `OK — 17/17, 0 literal ':::' in 19 built pages` |
| `pytest -q tests/test_cdm_boundary.py tests/test_cdm_positioning.py tests/test_cdm_packaging.py tests/test_cdm_publication.py` | **268 passed** |
| `pytest -q -k "scripted_edit and not version_floor"` | 9 passed, 4 432 deselected |

**The three working-tree failures, and why the fresh clone reads zero.** All three are
repository-wide prose sweeps that walk the **filesystem** rather than the git index, and all three
are reporting files under the untracked `rounds/` campaign apparatus that sits beside this
checkout: `tests/test_cdm_changelog_claim.py`'s ban on one prose pairing,
`tests/test_cdm_consumer_path.py::test_the_index_install_is_stated_before_any_clone_install`, and
`tests/test_cdm_deploy_workflow.py::test_the_site_list_is_exactly_the_files_that_state_the_mechanism`.
`git ls-files rounds/` → **0**: not one offending file is tracked, none is in the commit, and none
exists in a clone — which is why the same suite at the same commit in a fresh clone reads
**0 failed**. No tracked file is implicated in any of the three.

Test counts for the modules this campaign added: `test_cdm_oes.py` 106, `test_cdm_examples.py` 157,
`test_cdm_conformance.py` 103, `test_cdm_profiles.py` 107, `test_cdm_positioning.py` 63,
`test_cdm_registry.py` 23, `test_cdm_conformance_spec.py` 19, `test_cdm_ontology.py` 18 — 596 in
eight new modules, inside a suite that now collects **4 441** tests. `test_cdm_boundary.py` gained
its second half in the same campaign and collects 171.

---

## Security

The final security review, each line a command run over the branch and the output it gave. The file
set is `git ls-files` — the repository's own index, not a walk of the disk.

| Searched for | Command | Result |
|---|---|---|
| secrets — provider key shapes | `git grep -nIE "(AKIA[0-9A-Z]{16}\|ghp_…\|xox[baprs]-…\|sk-…\|AIza…)"` over tracked files | **0 hits** |
| private keys | `git grep -nI "BEGIN … PRIVATE KEY"` | **0 hits** |
| key material by filename | `git ls-files` filtered for `.env`, `*.pem`, `*.p12`, `*.key`, `*.pfx`, `id_rsa` | **0 files** |
| credentials in assignments | `git grep -nIE "(password\|secret\|api[_-]?key\|token\|credential)…[:=]…"` | **1 hit**, `fixtures/klv/spec/klv_pin.json:3061` — a pin record's verdict token named `COMPLETE-ON-REQUIRED`, which is a transcription of a standard's own completeness rule and not a credential |
| real customer names in operational fixtures | `examples/README.md:17`, and a sweep of every golden and example | the README states it: *"No real unit, mission, schedule, position, customer or infrastructure appears in this directory."* The sweep reads **1 345** objects across **552** files and **every one** carries `source.synthetic: true`; none carries any other value |
| real operational coordinates | the same sweep, plus each fixture set's own README | positions are synthetic scenario data, declared as such on every object by a required field with no default. The fixture READMEs record where each position came from and why — e.g. `fixtures/cat034/README.md:181`, station coordinates in the Gulf of Riga chosen to exercise a signed-height field |
| personal data | `git grep` for e-mail addresses over tracked files, excluding the lockfile | **6 addresses**: `example.org` and `other.example.org` placeholders in specification examples; the maintainer's own two addresses in `PUBLICATION.md` and the commit-message gate; and one real address in `fixtures/stanag4586/spec/stanag4586_pin.json:97`, which is the **custodian a published standard names on its own cover page**, transcribed into the pin record as that document's own front matter |
| private endpoints | every URL host in tracked `.py`, `.json`, `.ttl`, `.jsonld`, `.yml`, `.toml`, ranked | public standards bodies, archives and package indexes only; the non-public-looking names are `example.invalid` (64) and `synthetic.invalid` (21), both reserved-by-RFC placeholders, and `synapsecommand.local` (1), which appears only in documents explaining why that name was **retired** as a schema identifier |
| classified data | `git grep -nIwE "(SECRET\|TOP SECRET\|NOFORN\|CONFIDENTIAL\|COSMIC\|ATOMAL\|REL TO)"` | every hit is an **enumeration value** of a source format's classification field, or prose about how such a value is carried — `gmtif.py:578`, `klv_security_codec.py:239-249`, `FORMAT_COVERAGE.md`, and one golden whose whole purpose is an out-of-enumeration integer that is carried without a label. No object in this repository is marked, because none carries real content |
| private reasoning logic | `tests/test_cdm_boundary.py`, over all 54 package modules | **171 passed**. No import of a private product root; no LLM framework or model SDK, no graph database, no message broker, no RDF parser or reasoner, and no crypto — each class named in the gate and each name real, because a sanitised list is a gate that cannot fail |
| restricted standards content | `git ls-files '*.pdf'` → 0, `git ls-files '*.zip'` → 0; `tests/test_cdm_packaging.py::test_no_specification_document_is_shippable` | **0 / 0**, and the packaging gate has a positive control: it builds a tree that *does* contain one and asserts the exclusion bites |
| network at runtime | `tests/test_cdm_conformance.py` | the conformance import closure reaches nothing that could go out to a network, and a full assessment completes with the network removed |

**Nothing of any of these classes remains.** The one real personal name and the one real e-mail
address in the tree are a standards custodian's, printed on the cover of the document that names
him, recorded in the pin that identifies that document.

---

## Licensing

| Check | Reading |
|---|---|
| Apache-2.0 policy intact | `packages/cdm/pyproject.toml:31` → `license = "Apache-2.0"`; `LICENSE` is the canonical Apache-2.0 text, unmodified, so licence detection and SPDX scanners keep recognising it |
| LICENSE unchanged | `git log --oneline -- LICENSE` → one commit, `d798601 Initial commit`. `git diff v1.8.0..HEAD -- LICENSE packages/cdm/LICENSE NOTICE packages/cdm/NOTICE` → **0 lines**. `cmp` on both root/package pairs → identical |
| NOTICE carried | `license-files = ["LICENSE", "NOTICE"]`; the wheel gate asserts both are present in the built distribution and byte-identical to the originals, because section 4(d) makes carrying NOTICE a condition of redistribution and a wheel on an index is a redistribution |
| no incompatible new dependency | one dependency added by the campaign, `rdflib` 7.6.0, BSD-3-Clause, **test extra only**; its one non-optional dependency `pyparsing` is MIT. See **Dependencies** |
| no unauthorized standards content | not one byte of any pinned specification is in the repository or its history: `git ls-files '*.pdf'` → 0, `'*.zip'` → 0. Each pinned document is recorded by SHA-256, byte count, page count, edition and source URL, and remains under its publisher's own terms. NOTICE states this and names the publishers |
| no accidental trademark grant | the trademark boundary is stated at every site a reader arrives at, and `tests/test_cdm_positioning.py::test_the_trademark_boundary_is_stated_where_a_reader_arrives` fails the build if one stops saying it: the open-source licence does not grant rights to use the project's trademarks except as necessary to describe the origin of the work |
| no certification programme created or implied | `::test_no_certification_programme_is_created_or_implied`, plus a repository-wide sweep for six forbidden claim strings read out of `spec/sc-oes/00-conventions.md` rather than typed into the test. The two permitted claims are conformance claims, and the profile form of the permitted claim is checked to name a profile that exists |
| no proprietary reasoning exposed | see **Security**, last three rows |

---

## Acceptance criteria

Each answered with the reading that decides it.

| # | Criterion | Answer | The reading |
|---|---|---|---|
| A | An independent developer with only the public repository can create `sc.pnt.gnss_interference.v1` correctly | **YES** | The type is in the shipped registry with its class, ontology class, payload model and legacy mapping; `spec/sc-oes/03-event-types.md` gives the grammar; `spec/sc-oes/profiles/pnt.md` gives the profile; `examples/sc-oes/individual/sc.pnt.gnss_interference.v1.json` is a complete worked example; and the conformance tool assesses it — the event object A PASS, B PASS, C PASS, E PASS, the entity A PASS and E PASS with B and C SKIP because SC-OES metadata is carried on `Event`, and the invocation exits 0. `tests/test_cdm_examples.py` (157 tests) validates every example against the models, the schemas and the registry |
| B | An independent developer can determine exactly what the seven event relations mean | **YES** | `spec/sc-oes/08-event-relationships.md:38-44` defines each predicate with its direction and its meaning in one table row — `DERIVED_FROM` current → source; `UPDATES` new → earlier; `SUPERSEDES` new → earlier; `RESOLVES` new → active-condition event; `RETRACTS` new → previous assertion; `CONTRADICTS` conceptually symmetric; `CORRELATES_WITH` conceptually symmetric. The enumeration in `oes.py` carries exactly these seven |
| C | A consumer can safely preserve `x.<vendor>.*` semantics without understanding or guessing them | **YES** | `spec/sc-oes/11-extensions.md:68-76`, normative: *"A valid unknown `x.*` extension MUST survive validation, MUST survive serialization, and MUST survive round-trip unaltered … MUST NOT be interpreted, and MUST NOT be promoted into a core field … A consumer that does not understand an extension MUST ignore it, and MUST NOT reject the event for carrying it."* Checked by `test_an_unknown_extension_survives_validation_serialization_and_round_trip_unaltered`, `test_an_extension_that_shadows_a_core_field_is_accepted_and_never_interpreted`, the key-grammar tests, and the depth bound at 16 accepted / 17 refused with the refusal naming key, depth and maximum |
| D | An unknown governed-looking identifier cannot impersonate a valid governed term | **YES** | Two rules, one from each side. An identifier that claims the reserved namespace and does not match its grammar is **refused by the model itself**, with the refusal naming the reserved namespace — `tests/test_cdm_oes.py:425::test_an_identifier_impersonating_the_governed_namespace_is_refused`, over an uppercase module, a lowercase term, an underscore in a term and a term that is missing entirely. An identifier that *is* grammatically well formed but is absent from the packaged term registry is syntax-valid at the model and a **dimension E FAIL**: `conformance.py` classifies it `unknown-governed`, "in the reserved SynapseCommand ontology family and the packaged term registry does not carry it", and the test that pins that behaviour is named for it. Recognition is a **lookup**, never a pattern |
| E | Runtime conformance requires no network access | **YES** | `tests/test_cdm_conformance.py:761` walks the conformance import closure and finds nothing that could go out to a network; `:773` runs a full assessment with the network removed and it completes. Both registries are files inside the wheel — the wheel gate's `manifest` check is equal to git in both directions over 1 333 files, and its `import` check runs from site-packages with no part of the repository on the path |
| F | No RDF parser or reasoner is required at runtime | **YES** | `rdflib`, `owlrl` and `pyshacl` are in the boundary gate's forbidden runtime set over all 54 package modules (171 passed); the runtime reads the **generated JSON** term registry, never the Turtle; and `rdflib` is declared in the `test` extra and only there, which is itself a test |
| G | SC-OES can be implemented independently under the repository's open-source terms | **YES** | Everything this work authors is Apache-2.0 — the specification, the ontology, the registries, the examples and the code — with no additional grant required and no field-of-use restriction. The specification, the profiles, the governance processes and both registries are all in the public tree; ADR 0010 is the decision and states that it was achieved by adding nothing |
| H | The public repository does not expose the proprietary SynapseCommand reasoning engine | **YES** | `tests/test_cdm_boundary.py`: no module imports a private product root, an LLM framework, a graph database, a message broker, an RDF reasoner or a crypto library — and the gate is guarded against being sanitised into something that cannot fail. `README.md:51-72` states the same boundary in prose, and the test requires the prose and the gate to agree |
| I | Conformance tooling never represents an unrun check as a pass | **YES** | `SKIP` is a distinct verdict from `PASS` in every output form, and the tool prints *"SKIP is not PASS: it means this was not assessed"* in its own footer. A `--require`d dimension that SKIPs makes the invocation unsuccessful. The same rule holds one layer down: the wheel gate treats a harness run that exercised nothing as a FAILURE rather than a pass, and says so |
| J | A failing requested conformance dimension gives a nonzero CI-usable exit status while preserving the full report | **YES** | Reading taken: `--input examples/…/sc.pnt.gnss_interference.v1.json --profile PNT --require D` prints the complete five-column table, the per-dimension tallies and the per-object detail, and exits **1**. Without `--require`, the same input exits **0**. The verdict is never rewritten to make the exit code follow from it |
| K | The authoritative ontology, the generated runtime term registry and the JSON-LD context cannot silently drift apart | **YES** | `gates/ontology_terms.py` regenerates both derived artefacts from the Turtle and fails on any difference: 73 terms, 8 modules, **2 derived artefacts in sync, 0 failed**. `tests/test_cdm_ontology.py` (18 tests) parses the Turtle with a real RDF parser in the test environment and checks the same closure |
| L | No old strict CDM 1.x reader is falsely described as compatible with new 2.x objects | **YES** | `MIGRATIONS.md:283-311` states the opposite in terms: the move is a MAJOR, a 1.x reader meeting the new keys **rejects** the object, `version.compatible("2.0.0", "1.0.0")` is `False` (reading taken), and no claim of compatibility is made anywhere. ADR 0005 carries the derivation and refuses to describe it as a forward-compatible 1.1 change |

---

## Remaining limitations

Genuine ones, each with the reading or the document that leaves it open.

1. **`PACKAGE_VERSION` is unmoved at 1.8.0, and the release is not this campaign's.** ADR 0005
   rules the distribution to `2.0.0` on its own derivation, and the automated gate cannot reach
   that: `gates/bump_derivation.py` derives a **floor**, and the floor for this arc is MINOR →
   `1.9.0` with `unruled: []`. The MAJOR is a human decision the ADR already records, and it is
   applied when the release is cut. Nothing in the tree types a release number.
2. **Dimension D is SKIP for all seven profiles**, because no profile declares a conformance rule
   at v0.1.0. `conformance.PROFILE_RULES` maps every profile to `()`, and each profile document's
   Conformance section says so in its own words; a repository-bound test fails if one of them stops
   saying it. The dimension is declarable and reportable, and it is unexercised until a profile
   carries rules.
3. **No governed event type is STABLE.** Eight are DRAFT and five EXPERIMENTAL. The maturity ladder
   and the promotion process exist; nothing has been promoted.
4. **The reference producer leaves `oes.confidence` null** on all four PNTMAP goldens, although the
   source supplies an interference confidence, because that number is already carried at
   `Entity.confidence` and duplicating it into the block would make two fields the producer would
   have to keep equal. `spec/sc-oes/profiles/pnt.md` is where a decision to change that belongs.
5. **Five worked examples in the decision domain take `ALERT` as their legacy event type** under
   the null branch of the legacy mapping, because the legacy enumeration has no member for a
   judgement or an authorization. ADR 0007 records the reasoning; the alternative was inventing
   legacy members, which the ADR refuses.
6. **Ten domains are named as future work and none is implemented**: maritime, land, space, cyber,
   medical, fires, IAMD, exercise, weather and infrastructure. A positioning test asserts that none
   of them has been quietly implemented while still being described as future work.
7. **One documentation nit, carried and not fixed here.** `tests/test_cdm_positioning.py`'s
   docstring counts the files on its quoting allowlist as five where the tuple holds seven — the
   module is on its own allowlist, and the seventh entry is the module itself. Every one of the
   seven is checked and passes; no gate is wrong and no claim in the tree is false, so this round
   changed no code for it. It is recorded here so that the next round that touches the module
   corrects the count where it is stated.
8. **Three working-tree suite failures that a clone does not have.** See **Tests**: three
   filesystem-walking prose sweeps report untracked campaign apparatus sitting beside this
   checkout. `git ls-files rounds/` → 0 and the fresh clone reads 0 failed. It is a property of one
   working directory, not of the repository — but it does mean a contributor with an unusual
   untracked directory beside their checkout can see the same three fail.
9. **The branch is not merged and nothing has been published.** `sc-oes/0.1` is 12 commits ahead of
   `origin/main`, which is unmoved; the branch is not on the remote; no tag was created. Pushing,
   opening a pull request, merging, tagging and releasing are deliberately outside this campaign.

---

## Addendum, 2026-09-07 — limitations 1 and 2 are closed, and the record of finding them stands

**Nothing above is edited.** This report is the record of what the campaign's audit found on
2026-09-06, and it found nine open limitations. The release-readiness round of 2026-09-07 closed
the first two of them. They are left written above, in the tense they were found in, because a
report that quietly deletes what it once found is a report nobody can date; this section says what
changed and where the evidence is.

**Limitation 1 — `PACKAGE_VERSION` unmoved at 1.8.0 — CLOSED.** `PACKAGE_VERSION` is `2.0.0`
(`packages/cdm/synapse_cdm/version.py`, reading taken). The limitation's own analysis was right and
is unchanged: `gates/bump_derivation.py` still derives a **MINOR floor** for this arc, because
every signal it can prove is an addition and what actually breaks is a third party's consumer,
which no file in this distribution records. The gate is unmodified in its derivation and now
distinguishes the two facts in its own output — `derived MINOR` and `version rule MAJOR over the
derived MINOR floor` — reading the ruling from a dated paragraph in
`packages/cdm/synapse_cdm/MIGRATIONS.md`'s section for this arc that names both of its ends. ADR
0005 remains the deciding document. The sentence that closed it was already in the tree:
`version.py`'s "the release that types the number is the one that writes the ruling".

**Limitation 2 — dimension D is SKIP for all seven profiles — CLOSED for one profile, and
deliberately not for the other six.** The **PNT Profile 0.1.0** declares one executable
conformance rule and `conformance.PROFILE_RULES` no longer maps every profile to `()`: it is read
from the packaged profile registry `synapse_cdm/registry/sc_oes/profiles.json`, and it maps `PNT`
to one rule and the other six to none. The canonical GNSS reference event assessed against PNT
returns A, B, C, D and E all `PASS` and exits `0`. The six specification-only profiles stay `SKIP`
by their own documents' words, which is a scope boundary and not a defect — and the
repository-bound test that fails when a profile stops saying so is still armed for them.

**Limitations 3 to 9 stand as written.** 3 (no governed type is STABLE), 4 (the producer leaves
`oes.confidence` null), 5 (five decision-domain examples take the null legacy branch), 6 (ten
domains named as future work), 8 (three working-tree failures a clone does not have) and 9 (the
branch is unmerged and unpublished) are unchanged and are recorded again in
`docs/sc-oes-release-readiness-report.md`. **Limitation 7 is also closed**: the docstring count in
`tests/test_cdm_positioning.py` said five where its tuple held seven, and the round that next
touched profile prose corrected it where it was stated.

The full evidence for this addendum, with the reading that decides each of twenty acceptance
criteria, is `docs/sc-oes-release-readiness-report.md`.
