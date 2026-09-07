# SC-OES release-readiness report — 2026-09-07

The closing record of the SC-OES campaign's release-readiness round. `docs/sc-oes-final-report.md`
is the campaign's own report and is not superseded by this one: it records what the audit of
2026-09-06 found, including two limitations, and its addendum of the same date as this file says
which of them are now closed. This document states what was changed to close them, and answers
twenty acceptance criteria with the reading that decides each.

Every figure below was taken on this tree. None is carried from a plan.

---

## 1. Executive summary

Two things changed, and nothing else was redesigned.

1. **`PACKAGE_VERSION` is `2.0.0`.** The distribution's own number now states the breaking change
   ADR 0005 decided. The bump derivation gate is unmodified in its derivation and still derives a
   **MINOR floor** for the arc; the MAJOR is a human ruling, recorded in the migration history and
   read by the gate, and the gate prints both facts separately.
2. **Dimension D of SC-OES conformance is executable for the PNT Profile 0.1.0.** A packaged
   machine-readable profile registry ships in the wheel; the PNT profile declares one conformance
   rule; and the canonical GNSS reference event assessed against it returns `PASS` on all five
   dimensions with process exit `0`. The other six profiles remain specification-only and return
   `SKIP`, which is what they are.

Nothing was pushed, tagged, merged or published. The wire contract did not move, no golden
changed, no example changed, no adapter changed, and the runtime dependency set is unchanged.

---

## 2–6. The version axes

Six axes, three of them constants in `packages/cdm/synapse_cdm/version.py` and three authored where
the thing they version is authored. Readings taken from the tree:

| Axis | Value | Where it is authored |
|---|---|---|
| Python package | `2.0.0` | `version.py:PACKAGE_VERSION` |
| CDM schema | `2.0.0` | `version.py:SCHEMA_VERSION` |
| SC-OES | `0.1.0` | `version.py:SC_OES_VERSION` |
| Operational Ontology | `0.1.0` | `ontology/*.ttl`, projected into `registry/sc_oes/ontology_terms.json` |
| Profile versions | `0.1.0` ×7 | each profile document, and `registry/sc_oes/profiles.json` |
| Event semantic major | `v1` | a segment of each governed `type_id` |

**The package and the schema being equal is a coincidence and not a derivation.** They are two
independently justified major changes that landed on one number: the schema is major because a 1.x
strict reader rejects an object carrying `oes` or `ontology_types`, on the migration history's own
table; the package is major because a third party's consumer or adapter written against 1.8.0 does
not work against this distribution, on the package table in `version.py` and ADR 0005's derivation
over it. They were equal at `1.0.0` once before, by coincidence of two first releases, and that
equality did not survive the eleventh adapter.

A package at `2.0.0` does **not** mean SC-OES 2.0. SC-OES is `0.1.0` and is a Draft.

The independence is asserted, not merely stated: `tests/test_cdm_packaging.py` sweeps every module
in the package for an assignment deriving either number from the other, re-pins both as literals so
that each bump is a deliberate edit, and its own docstring records that the sweep's teeth return
whenever the two are level — which they now are.

**No release date is invented.** The migration history's `### Unreleased` section is the
established convention for work in no release, and that is where this arc sits. The index serves
`1.8.0`; no `v2.0.0` tag exists.

---

## 7. PNT executable conformance — the architecture

Dimension D is assessed only against a profile the caller names, and never inferred. What changed
is that a named profile can now have rules.

* **`packages/cdm/synapse_cdm/registry/sc_oes/profiles.json`** — the third packaged registry
  artefact, beside the governed event contract and the generated ontology-term registry. It carries
  each profile's identifier, version, maturity, implementation status, governed event-type
  membership, and the executable rules dimension D can run against it. Nothing narrative: the
  profile documents keep that.
* **`synapse_cdm/oes_registry.py`** loads and validates it, and exposes `list_profiles()`,
  `get_profile()`, `get_profile_event_types()` and `profile_has_executable_rules()`. A caller asks a
  question; it never opens a path.
* **`synapse_cdm/conformance.py`** reads the rules from that registry rather than declaring them:
  `PROFILE_RULES` is the read, and `PROFILE_RULE_CHECKS` maps each declared rule to the check that
  decides it. The test suite asserts the two sets are equal in both directions, so a profile cannot
  declare a rule with no check and a check cannot sit unreachable.
* **`--profile-version`** was added to the CLI. Omitted, the packaged registry's version is used and
  reported; given and different, the invocation is refused with exit 2 rather than silently assessed
  against the version this package happens to carry.

Two properties are structural rather than reviewed. **The profile's event-type list is a projection
of the event registry, not a second list**: the registry model refuses at load a `profiles.json`
whose membership disagrees with `event_types.json`, so the two cannot drift. And **implementation
status and executable rules are one fact**: the model refuses a specification-only profile that
declares a rule, and a producer-backed profile that declares none.

The PNT rule, normatively, is one:

> **Event membership.** An event assessed against PNT Profile 0.1 MUST carry an `oes.type_id` that
> is one of the governed types this profile declares.

It reads no producer identity. `source.system` and `source.adapter` are not consulted by any
profile rule, and a test asserts the same event produced by four different systems gets the same D
verdict. PNTMAP is the reference producer; it is not a condition of conforming.

The rule requires none of `confidence`, `verification`, lifecycle status, `effective_from`,
`effective_to`, security marking, evidence, entity relation, extension or geometry. A test names
that list, so a future rule making one of them required has to delete a name from it.

---

## 8. Profile registry contents

Read from the packaged artefact:

| Profile | Version | Maturity | Implementation status | Governed types | Executable rules |
|---|---|---|---|---|---|
| PNT | 0.1.0 | DRAFT | PRODUCER_BACKED | 1 | `event_type_membership_required` |
| Air | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 3 | — |
| Logistics | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 2 | — |
| ISR | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 1 | — |
| C2 | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 1 | — |
| Mission | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 2 | — |
| Decision | 0.1.0 | DRAFT | SPECIFICATION_ONLY | 3 | — |

Thirteen governed types across the seven, which is the whole registry: **no event type was added**
this round. PNT's scope for v0.1.0 is `sc.pnt.gnss_interference.v1` and nothing else.

All seven are present, including the six with no rules, so a validator can tell a known
specification-only profile from a profile name that does not exist — the second is a configuration
error, not a conformance finding.

---

## 9. Machine-readable PNT proof

The canonical reference event — the `event` object of
`examples/sc-oes/individual/sc.pnt.gnss_interference.v1.json`, which is the committed example and
not a second one written for this proof — assessed against `PNT 0.1.0` with all five dimensions
required, in the tool's established JSON shape:

```json
{
  "profile": "PNT",
  "profile_version": "0.1.0",
  "A": {"verdict": "PASS"},
  "B": {"verdict": "PASS"},
  "C": {"verdict": "PASS"},
  "D": {"verdict": "PASS"},
  "E": {"verdict": "PASS"}
}
```

The keys above are the dimension keys of the report's own `objects[0].dimensions` map, quoted
compactly; the tool emits one JSON document in one format and no second format was created for
this proof.

**Why the object and not the file.** The committed example is a two-object document: the
interference source entity, and the event. Dimensions B, C and D are carried on `Event` and return
`SKIP` for an entity, which is correct and long-standing — so requiring all five over the whole
file makes the invocation unsuccessful because of the entity, on the pre-existing rule that a
required dimension returning `SKIP` is unsuccessful. That rule is not this round's and was not
changed. The canonical **reference event** is what the five-dimension proof is about, and it is
read out of the committed example rather than copied into a new one.

---

## 10. Human-readable PNT proof

```text
sc-oes conformance   synapse-cdm 2.0.0, CDM 2.0.0, SC-OES 0.1.0
profile              PNT 0.1.0
required             A,B,C,D,E

object                                kind   A     B     C     D     E
---------------------------------------------------------------------------
61d0b924-6f8e-5536-85c6-2cdc04299ba5  event  PASS  PASS  PASS  PASS  PASS

detail
    A PASS  valid event at CDM 2.0.0 (assessed with the oes block removed, per 13-conformance.md)
    B PASS  core syntax valid; the producer claims SC-OES 0.1.0, this implementation carries 0.1.0
    C PASS  sc.pnt.gnss_interference.v1 is governed, and its class, ontology class, payload and
            legacy mapping agree with the registry
    D PASS  PNT profile 0.1.0 rules hold (1 checked: event_type_membership_required); the
            permitted claim "SC-OES PNT Profile 0.1 Conformant" is available for this object
    E PASS  1 identifier(s), 1 governed

A conformance claim names the dimensions assessed and the verdict each returned; the table above
is that statement.
No aggregate verdict, score, grade or percentage is produced, and SKIP is not PASS: it means this
was not assessed.
```

Each dimension carries its own reason. **D is not an aggregate of the others** and does not restate
their findings; the five details above are five different sentences about five different questions.
No overall verdict, score, level or percentage is produced anywhere, and a test sweeps the rendered
output for those words.

---

## 11. Exact process exit code

```text
Example:           sc.pnt.gnss_interference.v1
Requested profile: PNT 0.1.0

A - PASS
B - PASS
C - PASS
D - PASS
E - PASS

Exit:              0
```

---

## 12. Negative profile tests

Every row run on this tree, through the command-line entry point, and each one also asserted in
the suite:

| Input | Profile requested | D | Exit |
|---|---|---|---|
| canonical PNT event | PNT, requiring A–E | `PASS` | 0 |
| canonical PNT event | PNT `0.1.0` explicitly, requiring A–E | `PASS` | 0 |
| canonical PNT event | PNT, requiring D | `PASS` | 0 |
| governed C2 event | PNT | `FAIL` | 1 |
| governed C2 event | PNT, requiring D | `FAIL` | 1 |
| canonical PNT event | Air (specification-only) | `SKIP` | 0 |
| canonical PNT event | Air, requiring D | `SKIP` | 1 |
| canonical PNT event | none | `SKIP` | 0 |
| canonical PNT event | `UnknownProfile` | not a verdict | 2 |
| canonical PNT event | PNT at version `0.2.0` | not a verdict | 2 |
| the same event with its SC-OES block removed | PNT | `SKIP` | 0 |
| the same event with its SC-OES block removed | PNT, requiring D | `SKIP` | 1 |

The two rows that matter most are the third-from-top pair against the `FAIL` rows: they are what
distinguishes **profile unavailable for executable evaluation** from **profile available and event
non-conformant**. A `SKIP` is never rewritten to `FAIL` to make an exit code follow from it — the
verdict and the process status are separate layers and stay separate.

The last two rows are the legacy case: a CDM event with no SC-OES block cannot have its profile
membership established, so D is `SKIP` and no SC-OES metadata is manufactured in order to grade it.

All fourteen committed examples still exit `0` under a plain conformance run.

---

## 13. Wheel proof

`gates/wheel_install.py --mutation-check`, on this tree: **13 checks, 0 failed** on the real wheel;
the mutant wheel with package data emptied is refused by five of them
(`harness`, `manifest`, `prose`, `resources`, `scripts`), so the gate can fail.

Readings that moved: the manifest is **1334 files**, equal to git in both directions, one more than
before — `profiles.json`. The test-module closure is **59 modules, 30 judging the package and 29
judging the repository**, one more than before, and the new module judges the package because
everything it reads ships.

Separately, and outside the gate, the built wheel was installed into a clean virtual environment
with nothing of this repository on its path, and asked:

```text
package root   : …/site-packages/synapse_cdm/__init__.py
event registry : 13 governed types
term registry  : 73 ontology terms
profile registry: 7 profiles; ['PNT'] executable
PNT            : 0.1.0 PRODUCER_BACKED ('event_type_membership_required',)
```

and then, from that install, the canonical proof again: `PNT 0.1.0`, A–E all `PASS`, exit `0`. The
same assessment was then run a second time in a process whose socket constructor raises on use, and
returned the same five verdicts: **no repository checkout, no network, no remote profile service.**

---

## 14. Dependency state

| | Before | After |
|---|---|---|
| runtime | `pydantic>=2.6`, `jsonschema>=4.0` | unchanged |
| test extra | `pytest>=8.0`, `rdflib>=7.0` | unchanged |

No dependency was added for the profile registry: it is JSON, and the standard library reads it.
The RDF parser remains test-only — nothing under `synapse_cdm/` imports it, and
`tests/test_cdm_boundary.py` proves that by AST over the package sources rather than by review.

---

## 15. Security review

Swept over the files this round changed or added:

| Class | Reading |
|---|---|
| credential-shaped tokens (cloud keys, provider tokens, PEM private-key headers) | 0 |
| `password` / `secret` / `api_key` / `access_token` / `private_key` assignments | 0 |
| e-mail addresses | 0 |
| hosts referenced | `docs.synapsecommand.com`, `pypi.org`, `www.rfc-editor.org`, `nsgreg.nga.mil`, `example.org`, `synapsecommand.local` — all documentation or synthetic |
| real operational or customer data | none: the one event in every proof is the committed synthetic example, whose `source.synthetic` is `true` |
| private endpoints, private reasoning code, classification-policy logic | none added |
| restricted standards text | none: no pinned document was added, moved or quoted, and `gates/pin_paths.py` reads 30 copies, 30 matched, 0 failed |

The conformance path opens no socket, resolves no name and reads no path a caller did not give it;
that property is asserted by AST over the module's import closure and by an assessment run with
sockets disabled, and it was re-run above from an installed wheel.

Nothing in the profile registry is executed. It is parsed as JSON and validated against a model,
and no field in it names anything to import — the same rule the other two registries are held to.

---

## 16. Licensing review

| Check | Reading |
|---|---|
| LICENSE unchanged | `git diff v1.8.0..HEAD -- LICENSE NOTICE packages/cdm/LICENSE packages/cdm/NOTICE` → empty, and the same over the working tree |
| Apache-2.0 package policy unchanged | `license = "Apache-2.0"`, `license-files = ["LICENSE", "NOTICE"]`, unchanged |
| per-file SPDX / header drift | none: this repository carries no per-file headers and none was added |
| copied protected standards definitions | none: no third-party specification text was added |
| `profiles.json` covered by the repository licence | yes — it is original work in this repository, authored here, and ships under the same Apache-2.0 terms as the other two registries |
| additional licence acceptance required | none: no dependency was added |
| no protected document becomes shippable | the wheel gate's manifest check is equal to git in both directions, and `tests/test_cdm_packaging.py` asserts what the globs SELECT. No glob was widened — `registry/**/*` already reached the new file |

**Trademark.** Only conformance terminology is used. The permitted forms are "SC-OES Conformant"
and the profile form the specification's conventions document defines; the tool's `PASS` detail
states `"SC-OES PNT Profile 0.1 Conformant"` and nothing stronger. The six claims that document
forbids appear in zero of this round's files, and repository-wide they appear only in the six files
that state the ban or sweep for it. This work creates no certification programme, no badge, no
certification authority, no partner programme and no logo licence, and the specification says so in
its own Trademark section.

---

## 17–18. Tests run, and their results

| What | Reading |
|---|---|
| `pytest -q`, in the working tree | **3 failed, 4497 passed, 7 skipped** |
| `pytest -q`, fresh clone of the round's commit | **4432 passed, 75 skipped, 0 failed** |
| `gates/parks_table.py` | 13 rows, 0 open, 0 set-claims, **0 failed** |
| `gates/pin_paths.py` | 30 copies, 30 present, 30 matched, **0 failed** |
| `gates/ontology_terms.py` | 73 terms, 8 modules, 2 derived artefacts in sync, **0 failed** |
| `python -m synapse_cdm.schemas --check --out schemas` | `CURRENT: schemas vs models at 2.0.0` |
| `gates/bump_derivation.py` | declared `2.0.0` a MAJOR over `v1.8.0`; derived **MINOR**; version rule MAJOR over the derived MINOR floor; 10 units ruled by a person; **1 check, 0 failed** |
| `gates/bump_derivation.py --mutation-check` | 8 fixtures, every one as specified: both refusal directions, the unruled case, and the version ruling honoured, refused as stale, and unable to rescue an undershoot |
| `gates/wheel_install.py --mutation-check` | real **13 checks, 0 failed**; mutant 5 caught |
| `gates/deploy_record.py` | 22 deployments, 0 unaccounted; **2 checks, 0 failed**; one witness reads the served changelog at `1.8.0` against `version.py`'s `2.0.0` — DISAGREE, which is the correct pre-release reading and cannot fail |
| `gates/commit_message.py --rev HEAD` | clean |
| `npm --prefix docs run ci` | green: schema docs CURRENT (9/9), 0 written, `tsc` clean, site build SUCCESS, 17/17 admonitions |
| conformance over all 14 committed examples | 14 exit `0`, 0 non-zero |

**The three working-tree failures are the standing untracked-apparatus set** and a clone does not
have them: three filesystem-walking prose sweeps report untracked campaign apparatus sitting beside
this checkout, `git ls-files rounds/` is `0`, and the fresh clone reads 0 failed. This is the same
limitation the campaign report records as its eighth.

Both runs collect the same 4507 tests. The clone skips 75 where the working tree skips 7, and the
68-skip difference is the pinned specification documents: 43 in the pin module, 10 in the
format-coverage module, 7 in the pin-path module, 6 + 1 in two adapter modules and 1 in the parks
module all skip where no pinned document is on disk, and a clone has none — not one of them is
tracked, which is the property this repository maintains deliberately. The four release skips are
the same four in both runs.

**The seven skips are three standing ones and four that are new and expected.** The four are the
release tests that are conditional on a tag for the tree's own `PACKAGE_VERSION`: there is no
`v2.0.0` tag, so there is no released arc for them to measure. They are skips a release round turns
back into checks by tagging, and their skip messages say exactly that.

One consequence of the same fact is worth stating rather than leaving to be discovered. While
`PACKAGE_VERSION` is ahead of every tag, the bump gate's **judged** arc ends at the working tree,
so there is no separate **pending** arc behind it and the gate prints no pending line. That is the
release-candidate state the gate's own documentation describes, and `pending.unruled` is
consequently `[]` — not because nothing is unruled, but because the units are all inside the judged
arc, where the gate reports **0 ambiguities and 10 rulings**.

---

## 19. Branch and commit status

`git status --short` is empty and `git diff --check` reports nothing. The work is on the local
branch `sc-oes/0.1`, whose merge base with `origin/main` is `origin/main`'s own tip; `origin/main`
is unmoved. The branch is not on the remote, no pull request exists, no tag was created and
nothing was published. Every commit on the branch is signed off.

**Remote publication: NOT PERFORMED — owner decision required.** Release readiness means the branch
is technically, semantically, legally and operationally ready to be published. It does not mean
publication has occurred.

---

## 20. Remaining intentional limitations

These are scope boundaries, and each is a decision with a document behind it. None is a
release-readiness defect.

1. **SC-OES remains Draft `0.1.0`**, and so does the Operational Ontology. Every reader-facing site
   labels it so, and a test derives the label's version from the package rather than trusting it.
2. **Only PNT has executable profile conformance.** The other six profiles are specification-only,
   say so in their own documents and in the packaged registry, and return `SKIP`.
3. **Only GNSS interference has a governed typed payload.** The other twelve governed types keep
   free-form payloads until their semantics are stable enough to freeze.
4. **No governed event type is STABLE**: eight are DRAFT and five EXPERIMENTAL. The ladder and the
   promotion process exist; nothing has been promoted.
5. **No signing or canonical-byte profile**, no public reasoning engine, no runtime ontology
   reasoning, no reasoner and no RDF at runtime. These are architectural exclusions.
6. **No external standards-body status.** Nothing here has been submitted to, reviewed by, or
   approved by any external standards body, and every reader-facing site says so.
7. **The reference producer leaves `oes.confidence` unset** on all four of its goldens, because the
   number it would otherwise copy is already carried at `Entity.confidence`.
8. **Five decision-domain examples take the null branch of the legacy mapping**, because the legacy
   enumeration has no member for a judgement or an authorization.
9. **Ten domains are named as future work and none is implemented.** A test asserts that none of
   them has quietly acquired a profile document or a governed type.
10. **Three working-tree suite failures a clone does not have**, described above.
11. **The branch is not merged and nothing is published**, described above.

---

## Acceptance criteria

Twenty, each with the reading that decides it.

| # | Criterion | | Reading |
|---|---|---|---|
| 1 | `PACKAGE_VERSION = 2.0.0` | **YES** | `packages/cdm/synapse_cdm/version.py`; `synapse_cdm.version.PACKAGE_VERSION` → `2.0.0`; the built wheel's metadata reads `synapse-cdm 2.0.0` |
| 2 | `SCHEMA_VERSION` remains `2.0.0` | **YES** | `version.py`; `python -m synapse_cdm.schemas --check` → `CURRENT: schemas vs models at 2.0.0`; `git diff -- schemas/` empty |
| 3 | `SC_OES_VERSION` remains `0.1.0` | **YES** | `version.py`; the block's `spec_version` on the canonical event reads `0.1.0` and the tool reports it beside its own |
| 4 | Machine-readable packaged PNT profile metadata exists | **YES** | `synapse_cdm/registry/sc_oes/profiles.json`, in the wheel manifest, read through `importlib.resources` from an install with no checkout on the path |
| 5 | PNT is explicitly `PRODUCER_BACKED` | **YES** | `get_profile("PNT").implementation_status` → `PRODUCER_BACKED`; the profile document states the same word in its Implementation status section, and a test fails if the two disagree |
| 6 | All six others explicitly `SPECIFICATION_ONLY` | **YES** | the six records read `SPECIFICATION_ONLY`; each document states it; a test checks each pair |
| 7 | Canonical GNSS event + explicitly requested PNT 0.1 → `D = PASS` | **YES** | shown in §9 and §10; exit `0` |
| 8 | Canonical PNT example: A, B, C, D, E all `PASS` | **YES** | shown in §10; five verdicts with five distinct reasons and no aggregate |
| 9 | Requiring `A,B,C,D,E` for it exits `0` | **YES** | §11, and the same invocation from an installed wheel |
| 10 | A known specification-only profile returns `D = SKIP`, not `PASS` | **YES** | §12, rows 6 and 7; the model refuses a specification-only profile that declares a rule, so a `PASS` is unreachable for one |
| 11 | A non-PNT governed event against executable PNT returns `D = FAIL` | **YES** | §12, rows 4 and 5; the finding names the type and the profile it was put to |
| 12 | An unknown profile is a configuration error | **YES** | §12, row 9: exit `2`, no report printed — a report would claim an assessment happened |
| 13 | Profile conformance works from the installed wheel with no network | **YES** | §13: from a clean venv, and again with the socket constructor raising |
| 14 | Runtime dependency set unchanged | **YES** | §14: `pydantic`, `jsonschema`, and nothing else |
| 15 | RDF parser remains test-only | **YES** | §14; `rdflib` appears only under the `test` extra, and the boundary test proves nothing in the package imports it |
| 16 | No new CDM schema shape change | **YES** | `git diff -- schemas/` empty; `SCHEMA_VERSION` unmoved; the six schemas regenerate byte-identical from the models, from outside the repository |
| 17 | PNTMAP remains translation-only | **YES** | `git diff -- packages/cdm/synapse_cdm/adapters/` empty: no adapter file was touched this round, so no correlation, classification, attribution, assessment or recommendation could have been added |
| 18 | No protected third-party specification document becomes shippable | **YES** | no glob was widened; the wheel manifest equals git in both directions at 1334 files; the packaging test asserts what the globs select, and the pinned documents are untracked and excluded positively |
| 19 | All authoritative test and gate suites pass | **YES** | §17–§18, with the three untracked-apparatus failures identified and the fresh clone at 0 failed |
| 20 | Final branch clean, local only, signed commits, nothing pushed | **YES** | §19 |

---

## Release-readiness statement

```text
Package 2.0.0:                          READY
CDM Schema 2.0.0:                       READY
SC-OES 0.1.0 Draft:                     READY
Operational Ontology 0.1.0 Draft:       READY
PNT Profile 0.1.0 executable conformance: READY
PNT reference event:                    A/B/C/D/E PASS
Offline validation:                     READY
Wheel packaging:                        READY
Security/IP boundary:                   READY
Full regression:                        PASS
Remote publication:                     NOT PERFORMED - OWNER DECISION REQUIRED
```

---

## SL Documentation Closure — 2026-09-07

The publication-consistency round. It changed no architecture, no model, no ontology, no example and
no conformance behaviour; it made the accepted decision record say what the tree says. Each line
below is a check that was actually run, with what it found.

**ADR 0005 historical/current state clarified.** A lineage note records the implemented state —
`PACKAGE_VERSION = "2.0.0"`, `SCHEMA_VERSION = "2.0.0"`, their equality still coincidental and still
underived. The section carrying the pre-implementation figures is now headed *Historical readings at
the ADR-decision commit* and says in its own words that those values were superseded; they are not
rewritten to `2.0.0`, because the comparison is the evidence for the decision. The consequence
bullet about the packaging test's pinned pair is qualified to the decision commit and records the
current reading beside it: `("2.0.0", "2.0.0")` at `tests/test_cdm_packaging.py:320`, read from the
file rather than assumed.

**Registry-count terminology reconciled.** ADR 0004 carries the current-state statement of the three
packaged runtime artefacts and which conformance dimension each is load-bearing for; ADR 0009 states
the same ownership as `event_types.json` → C, `profiles.json` → D, `ontology_terms.json` → E, with B
structural and A CDM, and its offline sentence now reads *the applicable packaged SC-OES registry
artefacts* rather than a count; ADR 0010's packaging consequence reads the same way. Original-decision
sentences that say "two" are qualified as the original pair rather than deleted. The specification
README's machine-authority table names all three and no longer says a later round will write them.
Where prose does not need a number it does not carry one, so a future governed artefact will not
oblige an edit to an unrelated sentence.

**RFC 4151 authority evidence verified.** ADR 0003 records that the authority for
`tag:synapsecommand.com,2026-09-06:` was verified against authoritative administrative and registrar
records, naming the tagging entity as Decent Cybersecurity, and records that the evidence itself is
intentionally not committed because it carries private account information. The prefix is unchanged,
so nothing in the ontology, the registries, the examples, the models or the conformance
implementation moved.

**ADR 0010 licensing-policy wording tightened.** Declining copyleft test dependencies is stated as
conservative repository policy — avoiding additional licensing analysis, compatibility questions and
distribution obligations in the development and verification environment — and states in as many
words that it is not a claim that every copyleft test dependency would relicense the distributed
package or impose identical obligations on it. The verified finding is retained unchanged: rdflib
7.6.0 BSD-3-Clause, pyparsing 3.3.2 MIT, both accepted under repository policy. `profiles.json` is
recorded as inheriting the same repository-level Apache-2.0 arrangement as the other two artefacts:
no new licence, no new mechanism, no per-file header, no `LICENSE` edit.

**All ten ADRs cross-reviewed.** 0001–0010 read for the current/historical/future distinction. All
ten remain **Accepted**; none was returned to Proposed and none was created. 0001, 0002, 0006, 0007
and 0008 needed no change: their implementation-specific statements are already either dated lineage
notes or compatibility readings marked as such.

**No architecture changes and no code behaviour changes.** No canonical object, no attachment model,
no version axis, no ontology term, no event type, no profile and no dimension moved. Readings taken: `git diff`
against the previous commit is **empty** for `schemas/`, `ontology/`, `examples/`, every golden
file, `packages/cdm/synapse_cdm/adapters/`, `packages/cdm/synapse_cdm/registry/` and every `.py`
file under `packages/cdm/synapse_cdm/`. The one Python file this round touched at all is a test
module's docstring, `tests/test_cdm_conformance.py`, where a registry count had gone stale.

**All gates green.** The full suite, the parks, pin-path, ontology-drift, schema-drift,
bump-derivation, commit-message, wheel-install and deploy-record gates, the documentation site's own
CI target, and the conformance proofs — the canonical PNT reference event returning A/B/C/D/E all
`PASS` at exit `0` from the source tree and again from the installed wheel, the four negative profile
cases returning what they returned before. The bump gate derives no new pending unit: this round is
documentation and its `pending.unruled` is empty.

**One thing this round did not fix, and it is the owner's call.**
`packages/cdm/synapse_cdm/oes_registry.py`'s comment above the registry constants opens "Where the
two artefacts live inside the package" while the three constants directly beneath it name
`event_types.json`, `ontology_terms.json` and `profiles.json`. It is a stale count in a comment, it
changes no behaviour, and correcting it is a one-word edit — but it is a change to a file this
round was instructed to leave alone, so it is recorded here rather than made. It is the only
surviving place in the tree where a current-state sentence still implies two runtime SC-OES registry
artefacts.

**CORRECTED 2026-09-07: THE OWNER RULED, AND THE SITE ABOVE IS NOW FIXED.** The paragraph above was
true when it was written and records why the edit was withheld. The owner ruled the same day that
the comment is a current-state statement, that the no-code-change instruction protects behaviour and
a comment changes none, and authorised the one-line correction; the comment now reads "Where the
registry artefacts live inside the package" and carries no count. That is the only line under
`packages/` this round changed — the diff shows it and nothing else there — and it moved no schema,
golden, registry, ontology, example or conformance verdict: the structural gates were re-run to
prove it, `A/B/C/D/E` still `PASS` at exit `0` for the canonical PNT reference event from the source
tree and from the installed wheel, and the bump gate derives no pending unit from it. No
current-state sentence anywhere in the tree now implies that only two runtime SC-OES registry
artefacts exist; the sentence quoted in the paragraph above is the superseded wording, quoted there
as the defect it was and kept because this record is append-only.
