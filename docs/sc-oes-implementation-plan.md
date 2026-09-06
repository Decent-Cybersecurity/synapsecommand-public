# SC-OES v0.1 — implementation plan

**Date:** 2026-09-06, written in round S0 and **updated in round SA** against the governing
specification. **Written against:** `23ec65d5a80b1393e8f5c69edb0f2877a5f45d55` (`origin/main`'s
tip); the S0 form of this document is the first commit on the local branch `sc-oes/0.1` and this
form is round SA's.

This plan executes §9 of the SC-OES **Final Standalone Implementation Specification** and nothing
after it. Every figure below is a reading taken from this tree and cited to `file:line`; where a
reading refutes the specification, the section says so and the
[conflicts section](#conflicts-with-repository-invariants) after item 26 carries it with the
invariant quoted from where the repository states it.

**Citation convention, and it changed in round SA.** The governing document is the second
specification (`SC-OES-SPEC-v2.md`), which renumbers every section. A bare **`§N`** in this
document therefore cites **v2**. A citation to the first specification — the numbering S0 wrote
this plan against, which still applies where v2 is silent — is written **`§v1 N`**. Round SA
marked all 148 of S0's citations mechanically (every one of them was a v1 citation by
construction) and rewrote to v2 in the sections it revised; a `§v1 N` remaining in an unrevised
section is S0's citation, not a claim about v2.

Two conventions. **A reading is what a command printed**, not what a document claims — where the
two differ the difference is the finding. **An item the tree cannot yet answer says so and names
the reading that would**; the items that ended that way in S0 and have since been settled say
which ADR settled them.

## §9's nineteen required items, and where each is documented

§9 requires this document to cover nineteen things. The map is stated rather than left to be
inferred, because §9 is a checklist and a checklist with no index is one nobody can audit.

| §9 item | Documented in |
|---|---|
| 1. repository architecture | item 1 |
| 2. existing invariants | item 2, and the conflicts section |
| 3. files to add | item 5 |
| 4. files to modify | item 4 |
| 5. version implications | items 6 and 7 |
| 6. compatibility implications | items 3 and 8 |
| 7. ontology architecture | item 11 |
| 8. registry architecture | item 13 |
| 9. packaging changes | item 19 |
| 10. SC-OES model design | items 9, 10 and 16 |
| 11. conformance design | item 17 |
| 12. extension design | item 16's "Extension design" subsection |
| 13. governance | item 18 |
| 14. test strategy | item 22 |
| 15. documentation strategy | item 21 |
| 16. migration strategy | item 8 |
| 17. licensing implications | item 25 |
| 18. security implications | item 24 |
| 19. implementation rounds | item 26 |

---

## 1. Current architecture

Four canonical objects, one base class, one discriminated union.
`packages/cdm/synapse_cdm/models.py:434` declares `KINDS` as exactly
`{"entity", "event", "track", "plan_object"}`, and `models.py:428` builds `CDMObject` as an
`Annotated[Union[...], Field(discriminator="object_kind")]` over the same four. Both the schema
exporter (`schemas.py:88`) and the harness walk `KINDS` rather than keeping their own list, which
is why a fifth kind cannot be added in one place and forgotten in another.

`CDMBase` (`models.py:172`) carries what every object has: `schema_version` (defaulting to
`version.SCHEMA_VERSION`), `source: SourceRef`, `source_ids: list[SourceId]` with `min_length=1`,
and `integrity: Integrity | None`. `Event` (`models.py:312`) adds `event_id`, `event_type`,
`severity`, `related_entities: list[UUID]`, `geometry`, `payload: dict[str, Any]`, `observed_at`
and `received_at`. `Entity` (`models.py:221`) adds `entity_id`, `entity_type`, `affiliation`,
`symbol`, `position`, `kinematics`, `attributes`, `valid_from`, `valid_to` and `confidence`.

Translation is the adapter layer. `adapter.py:47` defines the `Adapter` ABC; its
`__init_subclass__` (`adapter.py:96`) enforces the contract at class-definition time and registers
the subclass in `REGISTRY` (`adapter.py:44`). The roster reads **fourteen adapters** at this
commit (`python -c "from synapse_cdm import adapter; len(adapter.roster())"` → 14): `adsb`, `ais`,
`cat021`, `cat023`, `cat034`, `cat048`, `cat062`, `gmti`, `legion`, `pntmap`, `stanag4586`,
`stanag4609`, `stanag4676`, `tak`. Eleven are `bidirectional`; `legion`, `pntmap` and
`stanag4586` are `ingest`.

Publication is one-way and generated. `schemas.py:81`'s `generate()` produces six documents — one
per kind, one per registered payload model, and a `cdm_object` union — written under `/schemas`
with `$id` of the form `urn:synapsecommand:cdm:<SCHEMA_VERSION>:<stem>` (`schemas.py:67`,
`schemas.py:76`). `tests/test_cdm_schemas.py:22` fails the build when the files on disk differ
from what the models generate now.

Verification is the harness. `harness.py:473` declares `_COLUMNS` as the six per-fixture columns
— `translate`, `schema`, `provenance`, `lossless`, `roundtrip`, `golden` — and an unrun column
reports `SKIP` and never `PASS` (`harness.py:230`). The tree holds **547 golden files** across
fifteen fixture directories, and **1283 tracked files** under
`packages/cdm/synapse_cdm/fixtures/`.

## 2. Existing repository invariants

Each is stated where the repository states it, with the site that enforces it. These are the
rules SC-OES inherits; §v1 160's first ordering rule ("preserve established repository invariants")
makes them senior to this specification wherever they meet.

| # | Invariant | Stated at | Enforced at |
|---|---|---|---|
| 1 | Adapters never drop data; leftovers go to `attributes`/`payload` via `lossless.residual()`, and a value that legitimately changes is declared in `TRANSFORMS` with a reason | `synapse_cdm/README.md:100`; `lossless.py:1` | harness `lossless` column, `harness.py:390` |
| 2 | Adapters are pure translation — no filtering, enrichment, inference or thresholds | `adapter.py:1`; `synapse_cdm/README.md:104` | by construction and by review; `pntmap.py:10` is the worked demonstration |
| 3 | An unknown position is the absence of a `Position`, never `(0, 0)`; `0.0` is a real coordinate | `models.py:131`; `pntmap.py:236` | `Position` requires `lat` and `lon` (`models.py:144`) |
| 4 | An unknown scalar is `None`, never `0` | `models.py:155`; `enums.py:1` | optional fields with no numeric default throughout `models.py` |
| 5 | `source.synthetic` is required and has **no default** | `models.py:90` — "There is no safe default, so there is no default" | pydantic requiredness; harness `provenance` column |
| 6 | Identity is derived, never drawn: `uuid5(NAMESPACE, kind\|system\|external_id)` | `ids.py:1`, `ids.py:33` | `NAMESPACE` fixed for CDM major 1 at `ids.py:28`; changing it is MAJOR |
| 7 | One serialised time form: RFC 3339 UTC, exactly three decimals, always `Z` | `times.py:1`, `times.py:35` | the `Timestamp` annotated type, `models.py:61`, which publishes the pattern into the schema |
| 8 | Canonical objects are strict — `extra="forbid"` — and extensibility uses declared bags | `models.py:8`, `models.py:59` | `tests/test_cdm_schemas.py:63` asserts `additionalProperties: false` on all four kinds |
| 9 | Generated schemas are never hand-edited | `schemas.py:1`; `README.md:29` | `tests/test_cdm_schemas.py:22` |
| 10 | No crypto in the contract layer; `integrity` is designed and unpopulated | `models.py:107`; `README.md:206` | `tests/test_cdm_boundary.py:104`, whose `FORBIDDEN_CRYPTO` at line 73 includes `hashlib` |
| 11 | No import from a consumer of the contract | `synapse_cdm/__init__.py:44` | `tests/test_cdm_boundary.py:95` |
| 12 | Two independent version axes, and neither is derived from the other | `version.py:1` | `tests/test_cdm_packaging.py:266`, which also pins the literal pair at line 313 |
| 13 | The wheel carries exactly what git tracks under the package — closure in both directions | `pyproject.toml:104` | `tests/test_cdm_packaging.py:117` |
| 14 | No pinned specification document ships, and none of their bytes is in the tree | `NOTICE:55` | `tests/test_cdm_packaging.py:138`; `git ls-files '*.pdf'` → 0 |
| 15 | No per-file headers: no SPDX tag and no copyright notice outside a licence file | `NOTICE:11` | `tests/test_cdm_publication.py:314`, `:327` |
| 16 | Synthetic fixtures only — no real data, ever | `CONTRIBUTING.md:166` | rule 5 plus review |
| 17 | Every commit signed off; a trailer is a trailer and prose is prose | `CONTRIBUTING.md:12`; `gates/commit_message.py:1` | `python3 gates/commit_message.py --rev HEAD` |
| 18 | A documented gap stays a gap until it is closed in the document too | `FORMAT_COVERAGE.md`, gap list | `tests/test_cdm_format_coverage.py:328` |

Readings for the untouchable set at this commit, taken rather than carried: the pinned phrase
`tests/test_cdm_prose_counts.py:1423` derives over `git ls-files` → **35** in 26 files — the
phrase itself is not spelled here, for the reason that module gives about its own text at
`tests/test_cdm_prose_counts.py:1466`, and this document is tracked and therefore inside that
derivation's file set; `pytest -k "scripted_edit and not version_floor"` → **9 passed**;
`git ls-files '*.pdf'` / `'*.zip'` → **0 / 0**; tracked extensions under `fixtures/*/spec/` →
**9 `.json`, 9 `.py`** and nothing else; the delegations-in-scope sentence of the KLV pin record
→ **1** file, `fixtures/klv/spec/klv_pin.json` — quoted here by description and not verbatim,
because that reading counts the files carrying the string and a tracked document repeating it
would move the reading it reports; `git diff v1.8.0..HEAD -- schemas/` → empty.

## 3. Compatibility constraints

*Revised in round SA against v2; §N below cites v2. **The claim S0 made here is the one §11 names
as the correction to remove.***

**The version consequence is not optional, and it is a MAJOR.** `Event` gaining an optional `oes`
and `Entity` gaining an `ontology_types` with an empty-list default are "an optional field added",
which is the *change* column of `MIGRATIONS.md:21`'s MINOR row — and S0 concluded from that row
that a 1.0.0 reader keeps reading the new objects. **It does not.** The MINOR row's consequence
column claims "old readers keep working", and `models.py:59`'s `extra="forbid"` plus
`tests/test_cdm_schemas.py:63`'s `additionalProperties: false` mean a 1.x strict reader meeting an
unknown key rejects the object. §21 states it as three propositions that cannot all hold; §11
requires the false claim be removed from ADR 0001, and this item is the plan's copy of it.

So `SCHEMA_VERSION` moves to **2.0.0** (§20), and `version.compatible()` (`version.py:127`)
refuses across majors in both directions — readings taken: `compatible("2.0.0", "1.0.0")` → False,
`compatible("1.0.0", "2.0.0")` → False. What survives from S0's reading is the *backward* half: a
legacy 1.x object validates against the 2.0.0 models unchanged, because both new fields are
optional with defaults. Item 8 states what the migration therefore has to say.

What it costs is measured in item 23 rather than asserted here, and it is the largest single
finding of this audit: **a `SCHEMA_VERSION` bump rewrites 538 golden files.**

Three further constraints bind:

- **`extra="forbid"` is on the canonical objects** (`models.py:59`), so an `oes` block that is
  not a declared field cannot ride on `Event` at all. There is no "just add a key" path; the
  attachment must be a model.
- **The `Timestamp` type is reused, not reinvented** (`models.py:61`). `effective_from` and
  `effective_to` take that annotation, which is what puts the strict pattern into the published
  schema rather than `format: date-time`.
- **`ids.NAMESPACE` may not move** (`ids.py:28`): the MAJOR row at `MIGRATIONS.md:20` names it
  explicitly. SC-OES event relations therefore reference UUIDs that are already deterministic;
  §v1 108's replay distinction comes for free and needs no new mechanism.

## 4. Files expected to change

Grouped by the phase that moves them. "Mechanical" means the change is produced by a generator or
by `--update-golden` and is read rather than authored.

| File | Change | Phase |
|---|---|---|
| `packages/cdm/synapse_cdm/models.py` | `Event.oes: OesMetadata \| None = None`; `Entity.ontology_types: list[str] = []` | 7 |
| `packages/cdm/synapse_cdm/version.py` | `SCHEMA_VERSION` `1.0.0` → **`2.0.0`**; `PACKAGE_VERSION` → **`2.0.0`** at the release (ADR 0005); `SC_OES_VERSION = "0.1.0"`, which lands here (item 12); the docstring's third axis, and the divergence section reworked for two equal numbers | SD |
| `packages/cdm/synapse_cdm/MIGRATIONS.md` | a **`2.0.0`** schema entry naming the reason, per the procedure at `MIGRATIONS.md:33`; a dated clarification beside the bump table's MINOR row (ADR 0005); a release section; the pending-section derived counts | SD |
| `tests/test_cdm_packaging.py` | re-pin the literal pair at `:313`, which is `("1.8.0", "1.0.0")` today and goes red the moment either constant moves | SD |
| `schemas/event.schema.json`, `schemas/entity.schema.json`, `schemas/cdm_object.schema.json` | regenerated (mechanical) | 13 |
| `schemas/track.schema.json`, `schemas/plan_object.schema.json`, `schemas/payload_gnss_interference.schema.json` | regenerated; `x-cdm-schema-version` and `$id` move with `SCHEMA_VERSION` even though the shapes do not (mechanical) | 13 |
| **538 golden files** under `packages/cdm/synapse_cdm/fixtures/*/golden/` | `schema_version` string, plus `"oes": null` on 566 event objects and `"ontology_types": []` on 653 entity objects (mechanical) | 13 |
| `packages/cdm/synapse_cdm/adapters/pntmap.py` | the one deliberate semantic upgrade (§v1 111, item 10) | 11 |
| `packages/cdm/synapse_cdm/fixtures/pntmap/golden/*.cdm.json` | 4 files, the upgrade's real output (read, not accepted) | 11 |
| `tests/test_cdm_packaging.py:313` | the literal pair `("1.8.0", "1.0.0")` re-pinned; its own message says this is the expected event and that re-linking the two numbers is the wrong fix | 7 |
| `gates/wheel_install.py:93` / `:144` | every new test module assigned to exactly one of the two lists | 16 |
| `packages/cdm/pyproject.toml` | `package-data` widened if the registry lands outside `fixtures/` (item 19) | 9 |
| `packages/cdm/synapse_cdm/FORMAT_COVERAGE.md` | the PNTMAP row set gains its SC-OES columns; no gap closes | 11, 15 |
| `README.md`, `docs/docs/intro.mdx` | positioning per §v1 126 | 15 |
| `docs/docs/schema-reference/*` | regenerated by `npm --prefix docs run gen:schemas` and committed (mechanical) | 15 |
| `CONTRIBUTING.md` | the contribution routes of §v1 133 | 3 |

## 5. Files expected to be created

| Path | What | Phase |
|---|---|---|
| `docs/adr/0001…0010-*.md` | the ten mandatory ADRs of §v1 9, eight sections each | 2 |
| `spec/governance/*.md` | six governance documents (§v1 90) | 3 |
| `spec/sc-oes/*.md`, `spec/sc-oes/profiles/*.md` | the normative tree: sixteen documents plus seven profiles (§v1 90) | 4 |
| `packages/cdm/synapse_cdm/registry/sc_oes/event_types.json` | the governed machine-readable event contract; the path is §16's and the packaging conditions are §17's (item 19) | SE |
| `packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json` | **generated** from the Turtle authority (§102, §135), shipped, drift-tested | SC |
| `ontology/*.ttl`, `ontology/context.jsonld`, `ontology/README.md` | eight modules plus the generated context and a README (§91) | SC |
| `packages/cdm/synapse_cdm/oes.py` (or a small package) | the SC-OES models: `EventClass`, lifecycle, verification, relations, evidence, security, extensions, `MAX_EXTENSION_DEPTH`, type-ID validation. **No `maturity` field** — §50 and §52 make it registry-owned, which corrects S0's row | SD |
| `packages/cdm/synapse_cdm/ontology.py` | ontology-identifier syntax validation only — no reasoning (§v1 85) | 6 |
| `examples/` — thirteen individual, one linked chain | §v1 113, §v1 114; synthetic identifiers only | 12 |
| `tests/test_cdm_oes_*.py`, `tests/test_cdm_ontology.py`, `tests/test_cdm_registry.py`, `tests/test_cdm_examples.py` | §v1 116–§v1 120 | 8–14 |

## 6. CDM schema impact

*Revised in round SA against v2; §N below cites v2.*

Two optional fields, one `SCHEMA_VERSION` bump **to 2.0.0 — a MAJOR** — and six regenerated schema
documents. §20 rules the number and §21 the reason: "The new public fields alter a strict
`additionalProperties: false` wire contract … Do not describe it as a forward-compatible 1.1
change." S0 recorded this as a MINOR to 1.1.0 on `MIGRATIONS.md:21`'s change column; ADR 0005
records why the consequence column decides it instead, and that ADR is where the derivation lives.

`Event.oes` publishes as a `$ref` into `$defs` with `"anyOf": [{"$ref": …}, {"type": "null"}]`,
which is how `Position | None` and `Integrity | None` already publish. `Entity.ontology_types`
publishes as `{"type": "array", "items": {"type": "string"}, "default": []}`. Neither weakens
`additionalProperties: false` on the four kinds, which `tests/test_cdm_schemas.py:63` asserts —
and the SC-OES sub-models must themselves be `STRICT` for the same reason `models.py:8` gives,
with `oes.extensions` as the one declared bag, exactly as `Entity.attributes` (`models.py:74`) is
today.

Two schema documents may also be added for non-Python consumers (§134, which asks for schemas for
"OES metadata", "registry structure" and "relevant payloads"): the SC-OES metadata block and a
registry's own shape. They are additions to `generate()` (`schemas.py:81`) and therefore
arrive with `$id`s in the ruled URN form (`schemas.py:67`) automatically —
`tests/test_cdm_schemas.py:36` checks that form per file, and
`tests/test_cdm_schemas.py:29` is a **subset** check (`expected <= on_disk`), so it does not
refuse a widened set.

**The `$id` of every published schema moves**, because `SCHEMA_VERSION` is inside it
(`schemas.py:76`). `schemas.py:62` records that a `$id` is a consumer-visible identifier; here it
moves as the version moves, which is what the version segment is for, and no `$ref` in these
documents crosses a file (`schemas.py:36`), so nothing dangles.

**Not proposed, and the reading that says why.** §86's security markings live
inside `oes.security` and not as `Event.classification`. `tests/test_cdm_format_coverage.py:388`
asserts that `Entity.classification`, `Entity.top_classification` and `Event.classification` do
not exist — gap 12, which `FORMAT_COVERAGE.md` defers until gap 1 is settled. SC-OES must not
close it in passing.

## 7. Python package impact

*Revised in round SA against v2; §N below cites v2.*

New importable surface, all additive: the SC-OES models and enums, the seven registry helpers of
§126, the ontology-identifier validator, `MAX_EXTENSION_DEPTH` and `SC_OES_VERSION`.

**A defect repaired here, and the readings that repair it.** S0 wrote that each of these is "an
importable name is added", which `version.py:101` makes a package MINOR. Both halves are wrong.
Readings taken: `version.py:101` is the third line of the package **MAJOR** row — "is removed, the
Python floor is raised" — and `version.py:99` is that row's first line, about a name being
*removed* or its meaning changing. The package MINOR list is `version.py:102`–`:103` and it
enumerates "an adapter is added, a harness flag or check is added, a fixture set is added, a new
optional dependency"; **"an importable name is added" is not a clause in it.** What actually makes
an added public name a MINOR is the rule of shape at `gates/bump_derivation.py:91`–`:93` — "an
unambiguous ADDITION of a declared surface is MINOR" — together with the gate's own
`a public top-level name appears | MINOR` signal at `gates/bump_derivation.py:70`. ADR 0005 and
ADR 0009 already cite it correctly; this repair brings the plan level with them.

`__init__.py:78`'s `__all__` is a hand-written list of 23 names; each new public name joins it.
Note that `tests/test_cdm_packaging.py:328` requires the marker
`WHY THEY MUST BE ALLOWED TO DIVERGE` to appear in exactly one `.py` file — `version.py` — so a
module introducing a third version axis routes to that file and does not restate the reasoning.

**`PACKAGE_VERSION` moves to 2.0.0, and the derivation is ADR 0005's rather than this plan's.**
§22 makes it an independent axis with a default expectation of 2.0.0 "unless the repository's
documented package-version policy clearly and explicitly derives another result", and requires ADR
0005 to record the actual derivation. The two readings that matter here: `MIGRATIONS.md:52` and
`version.py:106` both say a schema bump is **at least** a package MINOR — a floor, not a result —
and the gate's `SCHEMA_VERSION` signal at `gates/bump_derivation.py:74` encodes that same floor,
while `gates/bump_derivation.py:91`–`:93` sends a modification in place to a human. So the gate
will print MINOR and the release round must not stop there. Whether any unit lands **UNRULED** is
item 22's business; the gate refuses rather than guesses, and `MIGRATIONS.md`'s pending section is
where a ruling is written.

## 8. Migration implications

*Revised in round SA against v2; §N below cites v2.*

`MIGRATIONS.md:33`'s procedure is six steps and all six apply: edit the model, bump
`SCHEMA_VERSION`, re-export the schemas, add an entry naming the *reason*, re-run every adapter's
goldens **and read the diffs**, and close any `FORMAT_COVERAGE.md` gap the change closes (none
does — see item 6).

Step 5 is the expensive one and it is the one §24 and §142 are about. The diff is 538 files;
reading it means establishing that every hunk is one of exactly three mechanical shapes and that
nothing else moved. Item 23 states the shapes and the check, and §142 states the sequence:
regenerate, structural JSON-path diff, verify allowed changes, inspect, only then commit.

**A migration entry IS owed, which reverses what S0 wrote here.** S0 recorded that the MAJOR row
(`MIGRATIONS.md:20`) is not reached because nothing is removed, renamed, narrowed or made
required. That reading is right about the change column and wrong about the consequence: at 2.0.0
`version.compatible()` refuses across majors — readings taken, `compatible("2.0.0", "1.0.0")` →
False and `compatible("1.0.0", "2.0.0")` → False — so `MIGRATIONS.md:20`'s consequence column
("breaks readers; needs a migration entry below and a coordinated deployment") is exactly what
happens. ADR 0005 carries the full derivation.

**What the migration procedure has to say, per §23.** There is no migrator in the package —
reading: no `migrate` function or module anywhere under `packages/cdm/synapse_cdm/*.py` — so §23's
second branch applies and the procedure is documented rather than coded. Two statements: a 1.x
reader plus a 2.x object is *not contract-compatible*, said in those terms; and a 2.x reader given
a legacy 1.x object accepts it structurally unchanged (both new fields optional with defaults, no
field removed or renamed, so no field mapping exists) and has only the version gate to decide
about. The 2.0.0 entry should say that in its own words, because the section's own convention is
to name the reason rather than the change.

## 9. Serialization implications

`harness.py:144` dumps with `model_dump(mode="json")` and **no `exclude_none`**, and
`harness.py:402` renders with `json.dumps(..., indent=2, sort_keys=True)`. Three consequences,
all measured:

1. `"oes": null` appears on **every** serialised event — 566 objects in 484 golden files — the
   same way `"integrity": null` and `"kinematics": null` already do.
2. `"ontology_types": []` appears on **every** serialised entity — 653 objects in 537 golden
   files.
3. Key order is `sort_keys=True`, so `oes` sorts between `object_kind` and `payload` and
   `ontology_types` between `object_kind` and `position`; no existing line moves position within
   a file beyond those insertions.

`sort_keys=True` is also the answer §v1 105 asks for. The repository already serialises canonically
in the only sense v0.1 needs — deterministic key order, one timestamp form (`times.py:70`,
truncating and never rounding), and a schema that publishes the timestamp pattern rather than
`format: date-time`. ADR 0006 documents that and stops there: implementing a canonicalization
routine would mean hashing, and `hashlib` is in `FORBIDDEN_CRYPTO` at
`tests/test_cdm_boundary.py:73`.

**The nine goldens that do not change** are the proof that existing consumers are untouched:
`fixtures/ais/egress/golden/*.ais.nmea` (3), `fixtures/tak/egress/golden/*.cot.xml` (3) and
`fixtures/adsb/egress/golden/*.adsb` (3). Those are external-format bytes produced by
`from_cdm()`, and not one of them moves. Every changed byte is inside a CDM JSON document.

## 10. SC-OES attachment strategy

**Optional `Event.oes`, as §v1 17 prefers, and the tree supports it rather than merely permitting
it.** Three readings decide it:

- `models.py:428`'s `CDMObject` union is discriminated on `object_kind` over four kinds, and
  §v1 4 forbids a fifth. An attachment that is a new top-level object is out on the specification's
  own terms and out on the tree's shape.
- `Event.payload` (`models.py:327`) is `dict[str, Any]` and free-form, so `oes` *could* ride
  inside it with no schema change at all. **Rejected**: `payload` is the never-drop bag for
  source-specific fields (`models.py:329`), and putting governed SynapseCommand semantics in the
  bag reserved for a source's own shape is the exact confusion `models.py:17` describes — "source-
  specific fields at the same level as canonical ones". It would also make `oes` invisible to the
  published schema, which defeats §v1 104's offline validation for non-Python consumers.
- `models.py:59`'s `extra="forbid"` means a declared field is the only way to attach anything at
  the top level. So the choice is a declared optional field or nothing, and §v1 17's shape is the one
  the tree wants.

The block's own fields follow **§52** exactly: `spec_version`, `event_class`, `type_id`, `status`,
`verification`, `confidence`, `effective_from`, `effective_to`, `event_relations[]`,
`entity_relations[]`, `evidence[]`, `security`, `extensions`. **`maturity` is not among them** —
S0's list carried it on §v1 17, and §50 rules it registry-owned ("Do not put `maturity` in every
`Event.oes` instance") while §52 closes with "Do not include registry-owned maturity."
`effective_from`/`effective_to` take the `Timestamp` annotation (`models.py:61`); the
`effective_to >= effective_from` check of §70 is a `model_validator(mode="after")` in the shape
`Entity._interval` already uses (`models.py:272`–`:273`), whose message is worth copying in tone
— `models.py:277` names the defect as a translation defect rather than as data. §70's second half
binds too, and it is a rule about absence: do not default `effective_from` to `observed_at` unless
the source establishes the equivalence.

ADR 0001 records this with the `payload` alternative and its refutation.

## 11. Ontology representation strategy

*Revised in round SA against v2; §N below cites v2.*

§12's hybrid — conservative RDFS/OWL in Turtle as the authority, a JSON-LD context as the
developer projection, no RDF parsing at runtime, a test/development parser after licence review,
no public reasoning rules — is what ADR 0002 adopts, and the constraint the tree adds is about
**dependencies, not format**. `pyproject.toml:74` declares exactly two runtime dependencies,
`pydantic>=2.6` and `jsonschema>=4.0`, and `README.md:204` states that pair as a property of the
distribution. §144 names "RDF parser" and "OWL reasoner" among the runtime dependencies not to
add, §143 requires the boundary tests to keep an RDF reasoner out of the runtime imports, and
§136 permits the test-only parser under four conditions; item 20 takes that reading further.

The consequence for representation: **nothing at runtime may parse Turtle** — §102 says so
outright. Ontology identifiers reaching the CDM are validated as *strings* against the syntax of
§13 (`tag:synapsecommand.com,2026:ontology:<module>:<Term>`), by a regex in the package with no
RDF library behind it; a governed term that must be *recognised* is looked up in the packaged
`ontology_terms.json`, which §102 requires be generated from the ontology. *(S0 wrote the
identifier form as `urn:synapsecommand:ontology:<module>:<Term>` on §v1 73; §13 replaces it — see
item 12 and ADR 0003.)* The `.ttl` files are the authority for the vocabulary (§88) and are
validated in the test suite (§140).

**Three artefacts, one authority, two generators.** §18 and §135 make both derived artefacts
generated rather than hand-maintained — `context.jsonld` (§19, repository-only, "not required for
ordinary CDM/SC-OES JSON validation") and `ontology_terms.json` (§102, shipped) — and require a
drift test that proves each still matches the Turtle. That test is the same mechanism
`tests/test_cdm_schemas.py:22` already applies to the published schemas, one layer over.

`ontology/` sits at the repository root beside `schemas/`, for the reason `README.md:35` gives
about `schemas/`: it is an artefact for consumers who are not Python, and it should not require
understanding a Python package layout to find. §88 puts it there too.

## 12. Namespace strategy

Four identifier spaces, three of them new, and one of them already ruled in this tree.

- **Event type IDs** — `sc.<domain>.<event_name>.v<major>` (§v1 24), third parties on
  `x.<namespace>.<domain>.<event_name>.v<major>` (§v1 25). A regex in the package, checked in both
  directions, and the `sc.*` prefix refused from a producer that is not the governed registry.
- **Ontology terms** — `tag:synapsecommand.com,2026:ontology:<module>:<Term>` (§13). **This
  reverses S0's entry**, which read `urn:synapsecommand:ontology:<module>:<Term>` on §v1 73. §13
  forbids minting new public terms under `urn:synapsecommand:` and rules the `tag:` family
  instead; ADR 0003 records the ground, which is that `schemas.py:57`–`:60` accepted an
  unregistered URN NID *because* that is "common practice for JSON Schema `$id`s" — an excuse
  scoped to `$id`s and not to a permanent public vocabulary.
- **Schema `$id`s** — already ruled, and **unchanged by this work** (§13: "The repository's
  existing CDM schema URNs remain legacy identifiers and are not changed by this work").
  `schemas.py:30`–`:66` is a long, dated ruling that a `$id` must *identify* and not *locate*, that
  `https://` invites a fetch this repository will not serve, and that the URN form is the answer;
  `BASE_ID` is `urn:synapsecommand:cdm` (`schemas.py:67`). The part of it that generalises to the
  ontology is the refusal of `https://` (`schemas.py:38`–`:42`), not the choice of `urn:`. The
  previous value was `https://synapsecommand.local/cdm`, and RFC 6762 reserves `.local`
  (`schemas.py:49`–`:51`), which is the concrete mistake that ruling exists to prevent repeating.
- **Third-party ontology terms** — §15's three tests: an absolute URI/IRI-like identifier with a
  valid scheme, no control characters or whitespace, and no impersonation of the governed
  `tag:synapsecommand.com,2026:ontology:` namespace. Preserved, never guessed, never mapped.
- **Version axes** — `SCHEMA_VERSION`, `PACKAGE_VERSION`, `SC_OES_VERSION`, an ontology version
  and per-profile versions. `version.py`'s whole docstring is the argument for the first two being
  separate facts, and `tests/test_cdm_packaging.py:266` sweeps for a derivation of either from the
  other. **`SC_OES_VERSION` lives in `version.py`, and that open decision is now closed.** §46 points
  there — "The existing ADR analysis indicates `version.py` is likely the appropriate single
  version-axis explanation location. Do not derive it from `SCHEMA_VERSION` / `PACKAGE_VERSION`" —
  and ADR 0003 decision 7 takes it on the reading that settles it: `tests/test_cdm_packaging.py:328`
  requires the marker `WHY THEY MUST BE ALLOWED TO DIVERGE` in exactly one `.py` file, so a third
  axis introduced anywhere else would either restate the reasoning (which that test refuses) or
  state a version with no explanation beside it. The docstring opens "Two version numbers"
  (`version.py:1`), so a third moves that sentence; moving it is the correct cost. The other three
  axes are not Python constants: the ontology version is ontology metadata (§47), profile versions
  live in their own documents (§48), and the semantic major is a segment of the `type_id` (§49).

## 13. Event registry strategy

*Revised in round SA against v2; §N below cites v2.*

**Two registries, not one** (§18): `event_types.json`, the governed machine-readable event
contract, and `ontology_terms.json`, generated from the Turtle authority and drift-tested against
it (§102, §135). Both live at `packages/cdm/synapse_cdm/registry/sc_oes/` — §16 names the path and
forbids the alternative S0 recommended, "Do not package the runtime registry under a package
directory called `spec`". See item 19.

The event registry holds thirteen governed entries (§103–§109), each carrying the **fourteen**
fields §110 lists — `id`, `title`, `description`, `domain`, `profile`, `profile_version`,
`event_class`, `maturity`, `ontology_class`, `payload_model`, `legacy_event_type`,
`introduced_in`, `deprecated`, `replacement` — with §110's rule that `legacy_event_type` "must be
present even when its value is null". It is loaded and validated by tests (§139) and read through
the **seven** helpers of §126. *(S0 wrote fifteen fields and four helpers, on §v1 31 and §v1 103;
both figures are v2's now and both are counted from §110's and §126's own lists.)*

Two readings shape the content:

- **The legacy `EventType` vocabulary has seven members** (`enums.py:52`): `DETECTION`,
  `GNSS_INTERFERENCE`, `TRACK_UPDATE`, `ALERT`, `STATUS_CHANGE`, `PLAN_INJECT`, `SIM_RESULT`.
  §27 supplies the whole table rather than a rule to apply, and it resolves to **six `null`s and
  seven mappings** — one `GNSS_INTERFERENCE` and six `STATUS_CHANGE`. §27's null definition is
  "no meaningful legacy category is governed for this semantic type. It does not mean unfinished."
  S0 recommended the null default for the four decision-domain types; v2 extends it to
  `sc.air.air_track_observed.v1`, `sc.isr.threat_assessment_updated.v1` and
  `sc.mission.operational_impact_assessed.v1` as well. **The mapping table is ADR 0007's and not
  this plan's**, and ADR 0007 records why the air-track row moved off `TRACK_UPDATE`.
- **`payload_model` is already occupied for one entry.** `models.py:308`'s `PAYLOAD_MODELS` maps
  `EventType.GNSS_INTERFERENCE` to `GnssInterferencePayload` (`models.py:282`), which carries
  `frequency_band`, `interference_type` and `signal_strength_dbm`. §112 says "Reuse the existing
  `GnssInterferencePayload`. Do not duplicate it", and bounds the scope — "Do not prematurely type
  all thirteen event payloads … For v0.1, implement one governed typed payload." The tree agrees:
  that model is already `extra="allow"` (`models.py:291`) for the lossless reason §111 states.

## 14. Profile strategy

Seven profiles (§v1 89), each a document under `spec/sc-oes/profiles/` with the thirteen sections
§v1 89 lists, each versioned independently (§v1 20) and each at a declared maturity.

The v0.1 recommendation from the tree: **only the PNT profile has a producer.** §v1 111 makes PNTMAP
the reference implementation and §v1 121 says "preferably only PNTMAP should require a deliberate
semantic upgrade" for v0.1. So PNT is the profile with an implementation behind it and the other
six are specification-only at 0.1.0 — which is a state this repository already has a precedent
and a name for: **`MIGRATIONS.md:8026`**, the section headed "Row sets written as specifications,
with no adapter code yet". *(S0 attributed that heading to `FORMAT_COVERAGE.md:8026`. Readings
taken in round SA: the phrase occurs **once** in `MIGRATIONS.md`, at line 8026, and **zero** times
in `FORMAT_COVERAGE.md`. ADR 0009 already cites the right file; this repairs the plan.)* Profile
conformance (dimension D of §34) is therefore claimable against PNT and
declarable-but-unexercised against the rest, and §114 requires the profile documents to say so
explicitly: "Do not imply an operational adapter implementation exists where one does not."

## 15. Schema-generation strategy

Extend `schemas.py:81`'s `generate()`; author nothing under `/schemas` by hand. The function
returns a dict keyed by file stem, `_schema()` (`schemas.py:70`) stamps `$schema`, `$id` and
`x-cdm-schema-version` uniformly, and `write()`/`check()` (`schemas.py:106`, `:116`) are already
the write and drift halves. Adding an SC-OES schema is adding an entry to that dict.

Drift is gated twice and the second gate is **outside `pytest`**:

1. `tests/test_cdm_schemas.py:22` compares `/schemas` against the models.
2. `docs/scripts/check-schema-docs.mjs` compares the committed pages under
   `docs/docs/schema-reference/` against what `generate-schema-docs.mjs` produces from `/schemas`.
   It is run by `npm --prefix docs run check:schemas`, which is part of `npm run ci`
   (`docs/package.json`) and is **not** invoked by any test module — the sweep for `check:schemas`
   across `tests/*.py` finds only `tests/test_cdm_deploy_workflow.py:287`, which mentions it in
   prose. So a phase that regenerates schemas and runs only `pytest -q` will leave the reference
   pages stale and green. Item 22 puts the node gate in the testing plan explicitly.

## 16. Payload-validation strategy

Follow `Event._payload_shape` (`models.py:336`) exactly, because it already resolves the tension
§v1 62 and §v1 61 describe between typed validation and lossless preservation. Its docstring is the
ruling: validation is a **check** and never a transformation — the dict stays byte-identical as
the adapter wrote it, extra keys survive, and `typed_payload()` (`models.py:351`) is where a
consumer gets the parsed object.

`OES_PAYLOAD_MODELS` is therefore keyed by `type_id` string, validated the same way, with an
unregistered `type_id` leaving the payload free-form and transportable — which is `PAYLOAD_MODELS`'
own documented behaviour (`models.py:304`: "an event_type with no entry keeps a free-form
payload") and simultaneously §v1 27's unknown-semantics requirement. The two mechanisms are the same
mechanism, and registering a model is a MINOR by `MIGRATIONS.md:21`.

Payload models are `extra="allow"` (the `GnssInterferencePayload` precedent, `models.py:291`);
the SC-OES metadata models are `STRICT`. That split is item 6's and is the whole of §v1 14 and §v1 61
read together.

### Extension design (§9's item 12)

*Added in round SA; §N below cites v2.* One declared bag, `oes.extensions`, typed
`dict[str, Any]`, with the rest of `OesMetadata` strict (§29) — the same
strict-with-one-declared-hatch arrangement `models.py:10`–`:15` already describes for the
canonical objects, one level down. Four rules decide the implementation and ADR 0008 carries all
of them:

- **Keys are namespaced.** `x.<namespace>.<name>` for third parties (§30). A bare unnamespaced key
  is refused, because it is the one shape that cannot be attributed to anybody.
- **`sc.*` is refused outright in v0.1** as "reserved but undefined" (§30's v0.1 rule), and no
  extension registry is created to represent an empty governed set — §30 forbids that too.
- **Values are never interpreted** (§31): they survive validation, serialization and round-trip,
  are not promoted into core fields, and are ignorable. §31's "an extension may not redefine a
  core field" is therefore enforced by *not reading* the value rather than by refusing the key —
  refusing `x.acme.confidence` would contradict §31's own survival requirement.
- **One universal bound and no universal list caps**: `MAX_EXTENSION_DEPTH = 16` (§32), nothing for
  `event_relations`, `entity_relations` or `evidence` (§33). Item 24 states why.

## 17. Conformance strategy

*Revised in round SA against v2; §N below cites v2.*

Five dimensions (§34), five separately reportable verdicts, all offline (§125).

The repository's validation philosophy is a **column per property with SKIP for unrun**
(`harness.py:473`, `harness.py:230`), and the conformance report should be the same shape: five
columns, each `PASS`/`FAIL`/`SKIP`, with `SKIP` for a dimension not exercised — never a single
"SC-OES compatible" flag, which §v1 100's first line forbids and which the harness's own design
already argues against.

Offline is free here and is worth stating as a reading rather than a promise: the two runtime
dependencies are `pydantic` and `jsonschema` (`pyproject.toml:74`), `adapter.fixture_root()`
(`adapter.py:231`) resolves packaged data through `importlib.resources` rather than through a
repository path, and `schemas.generate()` produces the schemas from the models with no file and no
network. Nothing in the validation path reaches out today, and §v1 104 requires that it stay so.

The CLI pattern to prefer is the harness's: a `--json` machine-readable report (`harness.py:534`)
beside the rendered table, and exit codes as module constants (`harness.py:99`). §41 adds a
requirement about the JSON's shape — "named dimensions, not positional columns" — so it is emitted
as a mapping keyed `A`–`E`.

**Exit codes and required dimensions, which v2 adds and S0 did not have.** §40 fixes four codes:
`0` the run completed with no requested dimension `FAIL`ed, `1` one or more requested dimensions
`FAIL`ed, `2` a CLI/configuration/usage error, `3` an internal execution error. `SKIP` does not
fail the process by default, and a mechanism "conceptually equivalent to `--require A,B,C`" makes
a required-but-skipped dimension unsuccessful. Reading taken: the harness already spends the same
first three — `harness.py:588` returns `1 if report["failed"] else 0` and `harness.py:99` declares
`EXIT_NO_FIXTURES = 2` — so §40 agrees with a convention this repository already has.

**Three per-dimension rules v2 states outright**, because each is a place a tool could quietly
overclaim: an unknown `x.*` type is `C = SKIP` and an unknown `sc.*` is `C = FAIL` (§37); a
profile is never inferred, so `D = SKIP` when the caller names none (§38); and an unknown
identifier in the reserved `tag:synapsecommand.com,2026:ontology:` family is `E = FAIL`, while a
valid third-party absolute identifier is reported as `UNASSESSED_THIRD_PARTY_TERM` rather than
graded (§39). ADR 0009 carries all of them.

## 18. Governance strategy

Six documents under `spec/governance/` (§v1 90) implementing §v1 93–§v1 96, plus the `CONTRIBUTING.md`
routes of §v1 133.

The tree already has the governance primitive these need: **a decision is dated, written where it
is enforced, and never silently updated.** `MIGRATIONS.md`'s history sections, the pin records'
`what_this_is` nodes, and `gates/bump_derivation.py:44`'s refusal-until-ruled are three instances
of one practice. §v1 96's deprecation rules (identifier retained, original definition retained,
deprecation date, replacement, migration guidance) are that practice applied to semantic
identifiers, and the deprecation document should cite `MIGRATIONS.md:30` — "Renaming a field is
two releases, never one" — as the existing statement of the same rule one layer down.

`CONTRIBUTING.md:12`'s DCO requirement covers external contribution already; §v1 133's addition is
*what* may be proposed (event types, ontology terms, profiles, adapter mappings, examples,
validators) and through which document, not a new legal mechanism.

## 19. Packaging strategy

*Revised in round SA against v2; §N below cites v2. **§16 now names the path**, so this item
records the constraint rather than choosing between candidates.*

`tests/test_cdm_packaging.py:117` asserts equality in both directions between what
`git ls-files synapse_cdm` tracks and what the setuptools configuration would ship. The shipping
side is `packages.find` for `.py` inside a package, plus `package-data` minus
`exclude-package-data`; `pyproject.toml:164` declares `package-data` as exactly two globs —
`fixtures/**/*` and `*.md`.

So:

- A tracked file at `packages/cdm/synapse_cdm/registry/sc_oes/event_types.json` matches **neither**
  glob and is not a `.py` in a package, so the closure test fails on `missing` — a tracked file
  that would not be in the built distribution.
- A file at the **repository root**, `spec/sc-oes/event-types.json`, is outside `packages/cdm/`
  entirely, so it can never be in the wheel — and §17's packaging rule (ship in the wheel, loadable
  with `importlib.resources`, no checkout, no network, data never executed as code) plus §125's
  offline requirement mean it must be.

**§16 settles which side yields, and it is not the side S0 recommended.** S0 offered two
candidates and recommended putting the registry under `synapse_cdm/spec/sc-oes/`. §16 forbids
that in as many words — "Do not package the runtime registry under a package directory called
`spec`. Use `packages/cdm/synapse_cdm/registry/sc_oes/`" — so the repair is:

1. **Widen `package-data`** with a third glob keyed on `registry/`, and put both registries under
   `synapse_cdm/registry/sc_oes/`. `pyproject.toml:154` is explicit that widening a glob is the
   correct repair and that adding an extension to a list is the wrong one — "the list still went
   stale twice, silently, in the way an enumeration does" — and
   `tests/test_cdm_packaging.py:126` says the same in one line. The other candidate S0 named,
   putting the registry under `fixtures/` where `fixtures/**/*` already ships it, stays rejected
   on meaning: `fixtures/` is verification data, and a normative registry is not a fixture.
2. **The exclusions are not touched**, which §17 requires in as many words: "Do not modify
   exclusions in a way that makes pinned third-party standards shippable." They are keyed on
   `fixtures/*/spec/` (`pyproject.toml:192`–`:196`), a different `spec/` from the root one.

§16's own reason for the path is the word collision conflict 3 below is about, and choosing
`registry/` removes it at the source: **no directory inside the package is called `spec` after
this decision**, and §16 requires the three concepts — root `spec/` for normative documents,
`fixtures/*/spec/` for pinned third-party records, `registry/sc_oes/` for runtime artefacts — to
"remain visibly distinct". The `.ttl` files stay repository-only; `context.jsonld` does too (§19),
while `ontology_terms.json` ships because §102 makes it the runtime's only route to term
recognition.

`gates/wheel_install.py`'s thirteen checks all continue to apply; `check_manifest`
(`wheel_install.py:296`) and `check_resources` (`wheel_install.py:413`) are the two that would
catch a registry that is declared and does not arrive.

## 20. Dependency impact

**Target: zero new runtime dependencies.** The reading that makes this achievable:
`pyproject.toml:74` declares `pydantic>=2.6` and `jsonschema>=4.0`; the SC-OES models are pydantic
models, the registry is JSON, type-ID and ontology-identifier validation are regexes, and no
runtime path parses Turtle (item 11).

One new **test-only** dependency is likely and §v1 124 permits it explicitly: an RDF parser for §v1 118,
which asserts that every `.ttl` file parses, that term IDs are unique, that parents resolve and
that no operational instances are present. It joins `[project.optional-dependencies]`'s `test`
extra (`pyproject.toml:79`), which today is `["pytest>=8.0"]`.

That addition has a version consequence worth naming in advance: `gates/bump_derivation.py:72`
reads "an optional dependency appears" as a **MINOR** signal directly from
`[project.optional-dependencies]`. It is one more MINOR signal in an arc that already has one from
`SCHEMA_VERSION`, so it changes no outcome — but it will appear in the gate's output and should
not surprise the round that reads it.

Everything in §v1 135's non-goals list and §v1 124's forbidden list stays absent, and
`tests/test_cdm_boundary.py:104` keeps `hashlib` out along with the rest of `FORBIDDEN_CRYPTO`.

## 21. Documentation changes

§v1 125's five-way distinction (CDM = representation, ontology = semantics, SC-OES = operational-event
semantics, adapters = translation, private SynapseCommand = reasoning) goes into `README.md` and
`docs/docs/intro.mdx`, and §v1 126's positioning sentence replaces `README.md:3`'s current one-line
description. §v1 127's "does not replace ASTERIX / STANAG / TAK / …" belongs beside it; the tone
constraint ("keep the tone technical", §v1 126) matches what `README.md` already does.

`docs/docs/schema-reference/` is generated and committed (`docs/scripts/generate-schema-docs.mjs`),
so new schemas produce new pages that must be regenerated and committed in the same change, and
`sidebars.ts` needs no edit — the sidebar is `{type: 'autogenerated'}` and pages order themselves
by front-matter `sidebar_position`.

**A prose finding this audit turned up, recorded and not repaired, because this round may write no
tracked file but the plan.** `wrangler.toml:20`–`:21` states that "there is no CI: the repository
contains no `.github/workflows`". The tree tracks `.github/workflows/publish.yml`
(`git ls-files .github/` → 1 file, landed in `d1c3d43`). The clause is false as of that commit.
`wrangler.toml` is one of the two sites in `tests/test_cdm_deploy_workflow.py:48`'s `SITES`, so
whoever repairs it should read that module first — and the repository's own rule
(`PLAN.md`'s standing rules, and `MIGRATIONS.md`'s practice) is that a dated statement which has
become false gets a dated correction beside it, never an edit.

**Four prose sweeps bind any new document under `docs/`, and this plan was written to pass all
four.** They are recorded because Phases 15 and 18 will add more prose there:
`tests/test_cdm_deploy_workflow.py:205` sweeps every `.md`/`.mdx`/`.toml`/`.py`/`.ts`/`.json` for
the two deploy markers at line 66 and requires the set to equal `SITES`;
`tests/test_cdm_deploy_workflow.py:144` forbids the affirmative form of a claim about pushes
and the documentation site, which that module quotes and this one does not;
`tests/test_cdm_changelog_claim.py:121` forbids a certain reflection metaphor within 300
characters of the schema-versioning file's name — read that module for the word, which is not
repeated here because this document is inside its sweep; `tests/test_cdm_prose_counts.py:1947` refuses any `<number> adapters` phrase that is
neither the roster count nor ruled in `TREE_EXEMPT`, over the **git index**, so a tracked plan or
ADR is swept. `tests/test_cdm_prose_counts.py:411` closes on the literal phrase that states the
harness's column count, and `tests/test_cdm_consumer_path.py:258` judges every documented harness
invocation, including the value of its `--adapter`.

## 22. Testing plan

**Every command, and what each one covers.**

| Command | Covers | In `pytest -q`? |
|---|---|---|
| `.venv/bin/python -m pytest -q` | the whole suite; 3749 tests at this commit | — |
| `python -m synapse_cdm.schemas --check --out schemas` | schema drift, models vs `/schemas` | yes, via `tests/test_cdm_schemas.py:22` |
| `npm --prefix docs run check:schemas` | reference-page drift, `/schemas` vs `docs/docs/schema-reference/` | **no** — see item 15 |
| `npm --prefix docs run ci` | the above plus typecheck, build and the admonition check | **no** |
| `python gates/wheel_install.py --mutation-check` | the built artefact: 13 checks including the test-slice closure | no |
| `python3 gates/pin_paths.py` | 30 pinned documents present and matched | yes, via `tests/test_cdm_pins.py` |
| `python3 gates/parks_table.py` | the parks table | yes, via `tests/test_cdm_parks_table.py` |
| `python3 gates/bump_derivation.py --json` | the bump kind and `pending.unruled` | yes, via `tests/test_cdm_bump_derivation.py` |
| `python3 gates/commit_message.py --rev HEAD` | the trailer block and the sign-off | yes, via `tests/test_cdm_commit_message.py` |

**New test modules, mapped to the specification's own lists.** §v1 116 gives 24 SC-OES assertions,
§v1 117 gives 8 for entity annotations, §v1 118 gives 13 for the ontology, §v1 119 gives 11 for the
registry, §v1 120 requires every committed example to be iterated automatically. Each becomes a
module under `tests/`, and **each new module must be added to exactly one of
`PACKAGE_ONLY_TESTS` (`gates/wheel_install.py:93`) or `REPO_BOUND_TESTS` (`:144`)** — the wheel
gate's `closure` check (`wheel_install.py:521`) fails on "test modules in neither list", by name.
The rule for choosing is in that function's docstring: does it judge the package (it runs against
the installed wheel) or the repository (it does not)? A module that reads `ontology/` or `spec/`
at the repository root is repository-bound; one that reads only the installed package's registry
is package-only.

**Baseline at this commit**, so a later round can tell a new failure from a standing one:
`pytest -q` → **2 failed, 3739 passed, 8 skipped**, total 3749. Both failures are the untracked
`rounds/` apparatus and neither is in the tree a clone receives (`git ls-files rounds/` → 0):
the changelog-claim sweep of `tests/test_cdm_changelog_claim.py:113` at 34 unique offender
sites, and `test_the_site_list_is_exactly_the_files_that_state_the_mechanism` naming
`rounds/reports/I2.review.md`.

## 23. Regression risks

**Risk 1 — the mass golden change, and it is the one §v1 121 names.** Measured at this commit:

| Reading | Figure |
|---|---|
| golden files in the tree | 547 |
| golden files carrying a CDM object | 538 |
| `"schema_version": "1.0.0"` occurrences in goldens | 1308 |
| golden files carrying ≥1 entity / entity objects | 537 / 653 |
| golden files carrying ≥1 event / event objects | 484 / 566 |
| golden files that do **not** change | 9 |

The nine are `fixtures/ais/egress/golden/*.ais.nmea`, `fixtures/tak/egress/golden/*.cot.xml` and
`fixtures/adsb/egress/golden/*.adsb` — the three egress adapters' external-format outputs. **Not
one byte of any non-CDM wire format moves**, which is the strongest available answer to §v1 138's
"existing adapters still operate".

§v1 121 says dozens of unrelated golden changes are a design problem and §v1 138 forbids *unexplained*
mass changes. This one is explained and, more usefully, it is **checkable**: every hunk in the 538
files must be one of exactly three shapes —

1. `"schema_version": "1.0.0"` → `"schema_version": "2.0.0"`;
2. a new `"ontology_types": []` line inside an object whose `object_kind` is `entity`;
3. a new `"oes": null` line inside an object whose `object_kind` is `event`.

The reading that discharges the risk is a structural diff **by JSON path**, asserting that the set
of changed paths across all 538 files is exactly `{schema_version, ontology_types, oes}` and that
no other path's value moved. Anything else in the diff is a defect, not churn. That check should
be written and run before the goldens are committed, not after — `MIGRATIONS.md:37` ("A golden
file updated without being read is how a defect becomes the expectation") is the rule it
implements.

**Risk 2 — the PNTMAP goldens, which are the only *semantic* golden change.** Four files, and
they must be read individually rather than swept with the 538.

**Risk 3 — the version pin.** `tests/test_cdm_packaging.py:313` asserts the literal pair
`("1.8.0", "1.0.0")`. It goes red the moment `SCHEMA_VERSION` moves, deliberately, and its own
message says the fix is to re-pin and not to re-link. A round that meets it should not treat it as
a surprise.

**Risk 4 — `test_the_documented_gaps_are_still_gaps`** (`tests/test_cdm_format_coverage.py:328`)
asserts fourteen-odd field names are absent from the models. None of the SC-OES field names
collides with any of them (checked: `label`, `alt_accuracy_m`, `heading_deg`, `turn_rate_dpm`,
`baro_alt_m`, `parent_id`, `parent_entity_id`, `children`, `classification`, `top_classification`,
`observed_at`/`measured_at`/`age_s` on `Position` and `Kinematics`, `data_ages`, and
`sensor`/`sensor_id`/`station`/`producer` on `SourceRef`). The risk is not collision but
**accidental closure**: `oes.security` must not become `Event.classification`, and
`oes.confidence` must not be read as closing anything about `Entity.confidence`.

**Risk 5 — prose counts.** `tests/test_cdm_prose_counts.py` derives several stated figures from
the tree. "Six schemas" is stated at `README.md:63`, `README.md:74`, `RELEASE_NOTES.md:179` and
`docs/docs/changelog.mdx:33`; the sweep for a test deriving that particular figure found none, so
those four sites are **not** gated and will go stale silently if `generate()` gains an entry.
Phase 15 should repair them where they are stated and, per the repository's practice, prefer a
derivation over a literal.

## 24. Security risks

§v1 107's threat model list is the document to write; the readings that shape it here:

- **The trust boundary is already named and must not move.** `models.py:107` — the `integrity`
  block is designed and unpopulated, and `tests/test_cdm_boundary.py:104` makes an import of any
  crypto module a build failure. SC-OES adds no signing, no verification and no key handling
  (§v1 106), and §v1 55's evidence `hash` is a descriptive string the parser never computes or checks.
- **A SC-OES parser is not a cross-domain solution** (§v1 59). Security markings are transported,
  never interpreted, downgraded, upgraded, normalised or enforced (§v1 58). The repository has no
  classification-enforcement code and must acquire none — it is in §v1 2's proprietary list.
- **Synthetic/live confusion is the highest-value threat and is already structurally defended.**
  `models.py:90` records the reasoning at length: `synthetic` is required with no default because
  neither direction is safe to guess. §v1 11 requires SC-OES to inherit it, and it does so for free —
  `oes` hangs on an `Event`, and every `Event` carries a `SourceRef`.
- **Resource safety** (§127's "deep nesting", "oversized payloads", "resource exhaustion") — the
  concrete surfaces are `event_relations[]`, `entity_relations[]`, `evidence[]` and `extensions`.
  `extensions` is a `dict[str, Any]` like `Attributes` (`models.py:74`) and therefore recursive by
  type, so the bound is a validation rule to write rather than a property to inherit. **v2 fixes
  exactly one universal bound and forbids the obvious generalisation**: §32 sets
  `MAX_EXTENSION_DEPTH = 16`, counted over nested JSON containers under an individual extension
  value, while §33 forbids universal maximum counts for `event_relations`, `entity_relations` and
  `evidence` — a deployment may cap message size, list length, memory and processing time, but
  those are "resource policies, not universal operational semantics", and §33 requires the
  specification to distinguish the two. ADR 0008 carries both halves.
- **Semantic poisoning and unknown-type handling** (§v1 27, §v1 98, §v1 99) — the defence is the same
  mechanism as `PAYLOAD_MODELS`' free-form fallback (item 16): preserve, do not guess, do not map
  to a "similar" known type.
- **No secrets, no real data, no private endpoints** (§v1 146). `CONTRIBUTING.md:166` is the standing
  rule and `tests/test_cdm_boundary.py:95` keeps the private topology out of the imports.

## 25. IP/licensing risks

Apache-2.0, and the repository's arrangement is stricter than the specification assumes.

`NOTICE:11`–`:39` records that this repository has **no per-file headers**: no tracked file
carries an SPDX tag and no copyright notice sits outside a licence file, and
`tests/test_cdm_publication.py:314` and `:327` enforce both halves over `git ls-files`. §v1 129 asks
that new material be Apache-2.0; the correct way to achieve that here is to add nothing —
repository-level licensing already covers every new file, and pasting a header onto a new `.ttl`
or `.py` would fail a gate and falsify `NOTICE`'s paragraph.

`NOTICE:55` is the boundary §v1 128 is about: "The specification documents this repository PINS are
not part of the Work and are not covered by this licence." Thirty documents are pinned by hash,
byte count, page count, edition and source URL; **none of their bytes is in the tree** (`git
ls-files '*.pdf'` → 0) and `pyproject.toml:170` excludes them from the distribution positively
rather than by omission. SC-OES must be *independently authored* — §v1 128's own instruction —
which for the ontology means terms defined in this repository's own words with mappings to
external standards, never transcribed definitions.

§v1 131's trademark boundary needs a short statement and not a licence: Apache-2.0 grants no
trademark rights, and the distinction to make explicit is between implementation conformance and
brand use. §v1 132's terminology — "SC-OES Conformant", never "Certified" or "Approved" — should be
written into the conformance document and, given §v1 101's list, the specification should also
refuse "NATO certified / approved / standard" in its own text. `LICENSE` (201 lines) is
byte-identical to the canonical Apache-2.0 and must stay so (`NOTICE:41`), so nothing is added
there.

No incompatible dependency is introduced (item 20); the one likely test-only RDF parser must be
checked for licence compatibility before it lands, which is ADR 0010's business.

## 26. Implementation rounds

*Rewritten in round SA against v2; §N below cites v2. This is §9's item 19.*

§151 replaces §v1 136's eighteen phases with ten lettered rounds, A–J, and adds the rule that
governs all of them: "Use isolated local signed commits per round." The campaign's own round ids
are the S-series in `rounds/PLAN.md`; the table below is that table's content, with each row's
governing section named. **Rounds S0, S1 and SA are done**; SB onwards is what remains.

| Round | §151 round | Governing §§ | Exit criterion, in one line |
|---|---|---|---|
| **S0** | — | §7, §9 | this document exists on `sc-oes/0.1`, every item grounded in `file:line`; branch = origin/main tip + one signed commit; nothing pushed |
| **S1** | — | §10 | `docs/adr/0001…0010`, eight sections each, mutually consistent, every decision cited to this plan or to a reading |
| — | *M reviews the ADRs* | — | settled by the second specification, which is M's ruling on them |
| **SA** | A | §11–§45, §151 | the ten ADRs revised to record v2's decisions and moved to an accepted state; this plan updated per §9's nineteen items; no other tracked file changed |
| **SB** | B | §152 | governance documents, specification skeleton, EventClass definitions, event relationship semantics, versioning semantics, extension policy, security considerations, conformance definitions — "No major CDM code yet" |
| **SC** | C | §153 | core Turtle plus seven domain modules, identifier rules, relationships, JSON-LD context, **generated** ontology-term registry, ontology validation tests |
| **SD** | D | §154 | `Event.oes` and `Entity.ontology_types` land with `OesMetadata`, relations, evidence, security metadata and extension validation; **schema 2.0.0**; migration documentation; regenerated schemas; the 538-golden diff read by JSON path (§142) and the version pin re-pinned |
| **SE** | E | §155 | event registry, registry model, registry helpers, legacy mappings, maturity, payload mapping, registry tests |
| **SF** | F | §156 | conformance tooling reporting A–E as `PASS`/`FAIL`/`SKIP`, with human output, JSON output, **exit codes**, offline behaviour, profile selection and required-dimension behaviour |
| **SG** | G | §157 | PNTMAP gains SC-OES semantics only where the source justifies them; its goldens updated deliberately; "Do not enrich source information" |
| **SH** | H | §158 | thirteen individual examples, the linked decision-chain example, seven profile documents, example validation |
| **SI** | I | §159 | README, docs site, NOTICE clarification if necessary, package-data, registry packaging, wheel tests, publication checks, terminology sweeps |
| **SJ** | J | §160–§163 | `pytest -q` and every authoritative gate run — "Do not claim a test passed if it was not run" — plus the final security review (§161), IP review (§162) and engineering report (§163) |

**Where the reviews belong.** SD is the only round that moves the wire contract and 538 goldens,
and SG is the only one that changes what a shipped adapter emits; both want a review of their own
diff rather than a shared one. `rounds/PLAN.md` reviews every round, so this is a note about
attention rather than about procedure.

**SB is held, not pending.** `rounds/PLAN.md` records it as "held — M confirms SA's ADRs, then
pending", which is the same gate §10 sets for the ADRs themselves: the specification is M's ruling
on the ADR drafts, and SA's revision of them is what M confirms before the normative tree is
written against them.

**Release is not in this decomposition.** §8 forbids pushing, creating a remote branch, opening a
PR, merging, tagging, publishing a package and creating a release — "Final push, PR, merge, tag
and release require explicit owner authorization" — and the campaign's own rule (M's ruling of
2026-09-06 on §8) confines every S round to the local branch. A release of the SC-OES work is a
separate decision after M's review.

---

## Conflicts with repository invariants

§7's last line rules that "The repository is authoritative where this brief conflicts with a
stronger existing invariant". S0 found five conflicts. **None of them is a requirement that is
impossible under an invariant**, so no round stopped on any of them; each names the invariant,
quotes it from where the repository states it, and says which side yields.

**Round SA re-read all five against v2, and three of them are now settled by ruling rather than by
recommendation.** Conflict 1's resolution changes shape (the bump is a MAJOR and the migration
entry IS owed), conflict 2's location is named by §16, and conflict 3's word collision is removed
at the source rather than managed. Each is marked below. Conflicts 4 and 5 stand as S0 wrote
them, with their citations carried to v2.

### Conflict 1 — the version bump forces the mass golden change §v1 121 calls a design problem

*The specification:* §v1 121 — "If dozens of unrelated golden files change, treat that as a design
problem. Do not accept mass fixture churn without justification." §v1 138 — "no unexplained mass
golden-fixture changes." §v1 16 asks for additive change "wherever practical".

*The invariant:* `MIGRATIONS.md:21` — "**MINOR** | an optional field added; an enum member added;
a payload model registered; validation relaxed". And `models.py:193`: `schema_version` defaults to
`SCHEMA_VERSION` and is carried in every serialised object.

*The collision:* the two optional fields SC-OES needs are exactly the MINOR row's first clause, so
the bump is required by the repository's own table; and because the version string is inside every
object, 538 golden files move — 1308 version-string occurrences, 653 entity objects and 566 event
objects. That is not "dozens".

*Resolution — **revised in round SA**; the two documents agree once the table is read for what it
asserts.* The bump is not optional and not avoidable: suppressing it would mean either an
unversioned shape change (which `version.py:7` exists to prevent) or hiding `oes` inside `payload`
(refused in item 10 on the tree's own grounds). **And it is a MAJOR to 2.0.0, not a MINOR to
1.1.0**: §20 rules the number, and `MIGRATIONS.md`'s own MAJOR row is reached by its *consequence*
column ("breaks readers; needs a migration entry below and a coordinated deployment") even though
its *change* column lists "an optional field added" under MINOR. ADR 0005 carries the derivation,
including the readings of `version.compatible()` that decide it. What §24 and §142 actually forbid
is churn that is *unrelated* and *unexplained*. This churn is neither: it is related — one version
bump and two field additions, in one release — and it is explainable to the byte, in the three
shapes item 23 enumerates. The obligation this places on round SD is §142's five-step sequence and
the JSON-path structural diff of item 23, which converts "justified" from a claim into a check.
**Nine golden files, all external-format egress output, do not change at all**, which is §142's
"external non-CDM outputs should not change unless independently justified" satisfied by
measurement.

### Conflict 2 — the registry's suggested location cannot be in the wheel

*The specification:* §v1 31 — "Preferred source: `spec/sc-oes/event-types.json`". §v1 123 — "If runtime
validation requires an artifact, package it." §v1 104 — validation MUST work offline.

*The invariant:* `tests/test_cdm_packaging.py:117`, which asserts equality in both directions
between `git ls-files synapse_cdm` and what setuptools would ship, and `pyproject.toml:164`, whose
`package-data` is exactly `["fixtures/**/*", "*.md"]`.

*The collision:* a root-level `spec/` is outside the distribution root and can never ship; a
`synapse_cdm/spec/` matches neither glob and fails the closure test as a tracked-but-unshipped
file. Both of the specification's readings of "where the registry goes" are refused by the same
gate, from opposite sides.

*Resolution — **revised in round SA**; v2 names the path, so this is no longer a judgement.* The
registries must be inside the package and the glob must be widened to reach them (item 19), which
`pyproject.toml:154` already names as the correct kind of repair. §16 supplies the destination —
`packages/cdm/synapse_cdm/registry/sc_oes/` — and §17 supplies the five conditions it has to meet.
S0's own reading that the specification's preferred root location "can never ship" is what v2
acted on.

### Conflict 3 — `spec/` already means something else in this repository

*The specification:* §v1 90 proposes `spec/sc-oes/` and `spec/governance/` at the root for
SynapseCommand's **own** normative documents.

*The invariant:* `NOTICE:55` — "The specification documents this repository PINS are not part of
the Work and are not covered by this licence… See the pin records under
`packages/cdm/synapse_cdm/fixtures/*/spec/`". Thirty documents are pinned there, governed by
`gates/pin_paths.py`, `tests/test_cdm_pins.py` and the untouchable that `fixtures/*/spec/` tracks
only `.json` and `.py`.

*The collision:* in this tree `spec/` has meant "third-party standards this repository does not
own and does not redistribute" since before publication. A root `spec/` holding documents this
repository *does* own inverts the word inside one repository, and the risk is not a test failure
but a reader — or a future exclusion glob — treating one for the other. `pyproject.toml:170`'s
exclusions are keyed on `fixtures/*/spec/**` and so are not fooled today; a widening that reached
for `**/spec/**` would be.

*Resolution — **revised in round SA**; the collision is removed at the source rather than
managed.* S0's recommendation was to take the root `spec/` structure as given, state the
distinction in prose, and rely on the paths differing. §16 goes further and forbids the package
half of the collision outright: the runtime registries go to `synapse_cdm/registry/sc_oes/`, so
**no directory inside the package is called `spec`**, and the word keeps exactly two meanings —
a root `spec/` for normative documents this project owns (§117, §118) and `fixtures/*/spec/` for
pin records for documents it does not. §16 still requires the three concepts to "remain visibly
distinct", so the prose statement in `spec/sc-oes/README.md` and `NOTICE`'s neighbourhood is kept
(ADR 0004 decision 6) — it is now a clarification rather than the only defence. The future
widening that would have broken it, a glob reaching for `**/spec/**`, no longer has a package
`spec/` to reach.

### Conflict 4 — evidence hashes and canonicalization meet the no-crypto boundary

*The specification (citations carried to v2 in round SA):* §84 gives an `EXTERNAL_ARTIFACT`
evidence entry an optional `hash`, with "No network retrieval. No binary embedding. `hash` is
descriptive metadata only." §25 requires ADR 0006 to document deterministic serialization while
saying outright "Do not implement interchange cryptographic canonicalization in v0.1".

*The invariant:* `tests/test_cdm_boundary.py:73` — `FORBIDDEN_CRYPTO = {"cryptography",
"hashlib", "hmac", "nacl", "oqs", "secrets", "ssl"}` — enforced by AST over every module in the
package (`:104`), because "a signature computed inside a translator is held by nothing that audits
it" (`models.py:107`).

*The collision:* it is narrower than it looks and is recorded because it is a trap rather than a
contradiction. §84 already says the hash is "descriptive metadata only", so the field is a string
the parser transports and never computes or verifies. The trap is the word: a round that reads
"canonicalization" as "implement one" would `import hashlib` and fail the boundary test. v2
closes the trap in the section heading itself — §25's first line is "Retain the decision: **Do not
implement interchange cryptographic canonicalization in v0.1.**"

*Resolution — no conflict once stated, and the invariant is what states it.* ADR 0006 documents
the five properties §25 lists and points at what the tree already does — `sort_keys=True`
(`harness.py:402`), one timestamp form that truncates rather than rounds (`times.py:70`), and a
schema that publishes the strict pattern (`models.py:65`). It implements nothing. §26's list of
what not to build is the same boundary the repository already draws around `integrity`, and the
tree's `FORBIDDEN_CRYPTO` set is a superset of it.

### Conflict 5 — the ontology needs an RDF parser the runtime may not have

*The specification (citations carried to v2 in round SA):* §140 requires ontology tests; §12
rules the authoritative ontology to be "conservative RDFS/OWL serialized as Turtle"; §39 wants
ontology-identifier validation in the conformance tooling; and §18 adds a drift test that must
"prove the generated registry matches the Turtle authority".

*The invariant:* `pyproject.toml:74` — two runtime dependencies, `pydantic>=2.6` and
`jsonschema>=4.0` — restated as a property of the distribution at `README.md:204` and in the
package's own description.

*The collision:* validating "is this a governed ontology term?" at runtime, against the `.ttl`
files, needs an RDF parser at runtime.

*Resolution — **both, by splitting the question**, and v2 authorises the split twice over.*
Runtime validates identifier **syntax** (a regex over §13's grammar) and, where a governed term
must be *recognised*, looks it up in the packaged `ontology_terms.json` rather than in the
ontology — §102 requires exactly that: "Runtime must not parse Turtle. Generate
`ontology_terms.json` from the authoritative ontology." The `.ttl` files are validated in the
**test** suite with a test-only parser, which §12 permits ("An RDF parser may be used strictly as
a test/development dependency after license review") and §136 conditions: test/development only,
licence confirmed compatible, no RDF runtime dependency, the choice recorded in ADR 0002/0010
lineage. §144's runtime dependency budget names "RDF parser" and "OWL reasoner" among what may
not be added, and §143 makes the boundary a test rather than a habit. The `.ttl` files being
repository-only is then true by construction rather than by hope. **What v2 adds beyond S0's
resolution is the drift test** (§18, §135): a generated registry that had silently diverged from
the ontology would still answer "is this term governed?", and be wrong.
