# SC-OES v0.1 — implementation plan

**Date:** 2026-09-06. **Written against:** `23ec65d5a80b1393e8f5c69edb0f2877a5f45d55`
(`origin/main`'s tip; this document is the first commit on the local branch `sc-oes/0.1`).

This plan executes §8 of the SC-OES Final Master Implementation Specification v1.0 and nothing
after it. Every figure below is a reading taken from this tree at that commit and cited to
`file:line`; where a reading refutes the specification, the section says so and the
[conflicts section](#conflicts-with-repository-invariants) after item 26 carries it with the
invariant quoted from where the repository states it.

Two conventions. **A reading is what a command printed**, not what a document claims — where the
two differ the difference is the finding. **An item the tree cannot yet answer says so and names
the reading that would**; three items below end that way rather than guessing.

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
rules SC-OES inherits; §160's first ordering rule ("preserve established repository invariants")
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

**The additive requirement is satisfiable and the version consequence is not optional.**
`Event` gaining an optional `oes` and `Entity` gaining an `ontology_types` with an empty-list
default are both "an optional field added", which is the MINOR row of `MIGRATIONS.md:21`. That row
is a rule, not a preference: `version.compatible()` (`version.py:127`) accepts a minor from the
future within the same major, so a 1.0.0 reader keeps reading 1.1.0 objects and a legacy object
written at 1.0.0 keeps validating against the 1.1.0 models. §16's target behaviour holds in both
directions.

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
  §108's replay distinction comes for free and needs no new mechanism.

## 4. Files expected to change

Grouped by the phase that moves them. "Mechanical" means the change is produced by a generator or
by `--update-golden` and is read rather than authored.

| File | Change | Phase |
|---|---|---|
| `packages/cdm/synapse_cdm/models.py` | `Event.oes: OesMetadata \| None = None`; `Entity.ontology_types: list[str] = []` | 7 |
| `packages/cdm/synapse_cdm/version.py` | `SCHEMA_VERSION` `1.0.0` → `1.1.0`; `SC_OES_VERSION = "0.1.0"` if it lands here (item 12) | 7 |
| `packages/cdm/synapse_cdm/MIGRATIONS.md` | a `1.1.0` schema entry naming the reason, per the procedure at `MIGRATIONS.md:33`; a release section; the pending-section derived counts | 7, 16 |
| `schemas/event.schema.json`, `schemas/entity.schema.json`, `schemas/cdm_object.schema.json` | regenerated (mechanical) | 13 |
| `schemas/track.schema.json`, `schemas/plan_object.schema.json`, `schemas/payload_gnss_interference.schema.json` | regenerated; `x-cdm-schema-version` and `$id` move with `SCHEMA_VERSION` even though the shapes do not (mechanical) | 13 |
| **538 golden files** under `packages/cdm/synapse_cdm/fixtures/*/golden/` | `schema_version` string, plus `"oes": null` on 566 event objects and `"ontology_types": []` on 653 entity objects (mechanical) | 13 |
| `packages/cdm/synapse_cdm/adapters/pntmap.py` | the one deliberate semantic upgrade (§111, item 10) | 11 |
| `packages/cdm/synapse_cdm/fixtures/pntmap/golden/*.cdm.json` | 4 files, the upgrade's real output (read, not accepted) | 11 |
| `tests/test_cdm_packaging.py:313` | the literal pair `("1.8.0", "1.0.0")` re-pinned; its own message says this is the expected event and that re-linking the two numbers is the wrong fix | 7 |
| `gates/wheel_install.py:93` / `:144` | every new test module assigned to exactly one of the two lists | 16 |
| `packages/cdm/pyproject.toml` | `package-data` widened if the registry lands outside `fixtures/` (item 19) | 9 |
| `packages/cdm/synapse_cdm/FORMAT_COVERAGE.md` | the PNTMAP row set gains its SC-OES columns; no gap closes | 11, 15 |
| `README.md`, `docs/docs/intro.mdx` | positioning per §126 | 15 |
| `docs/docs/schema-reference/*` | regenerated by `npm --prefix docs run gen:schemas` and committed (mechanical) | 15 |
| `CONTRIBUTING.md` | the contribution routes of §133 | 3 |

## 5. Files expected to be created

| Path | What | Phase |
|---|---|---|
| `docs/adr/0001…0010-*.md` | the ten mandatory ADRs of §9, eight sections each | 2 |
| `spec/governance/*.md` | six governance documents (§90) | 3 |
| `spec/sc-oes/*.md`, `spec/sc-oes/profiles/*.md` | the normative tree: sixteen documents plus seven profiles (§90) | 4 |
| the event registry, **inside the package** | the machine-readable governed registry (§31); its path is ADR 0004's, and item 19 shows why the specification's suggested location cannot hold it | 9 |
| `ontology/*.ttl`, `ontology/context.jsonld`, `ontology/README.md` | eight modules plus the context (§76) | 5 |
| `packages/cdm/synapse_cdm/oes.py` (or a small package) | the SC-OES models: `EventClass`, maturity, lifecycle, verification, relations, evidence, security, extensions, type-ID validation | 8 |
| `packages/cdm/synapse_cdm/ontology.py` | ontology-identifier syntax validation only — no reasoning (§85) | 6 |
| `examples/` — thirteen individual, one linked chain | §113, §114; synthetic identifiers only | 12 |
| `tests/test_cdm_oes_*.py`, `tests/test_cdm_ontology.py`, `tests/test_cdm_registry.py`, `tests/test_cdm_examples.py` | §116–§120 | 8–14 |

## 6. CDM schema impact

Two optional fields, one `SCHEMA_VERSION` bump, six regenerated schema documents.

`Event.oes` publishes as a `$ref` into `$defs` with `"anyOf": [{"$ref": …}, {"type": "null"}]`,
which is how `Position | None` and `Integrity | None` already publish. `Entity.ontology_types`
publishes as `{"type": "array", "items": {"type": "string"}, "default": []}`. Neither weakens
`additionalProperties: false` on the four kinds, which `tests/test_cdm_schemas.py:63` asserts —
and the SC-OES sub-models must themselves be `STRICT` for the same reason `models.py:8` gives,
with `oes.extensions` as the one declared bag, exactly as `Entity.attributes` (`models.py:74`) is
today.

Two schema documents may also be added for non-Python consumers (§122): the SC-OES metadata block
and the registry's own shape. They are additions to `generate()` (`schemas.py:81`) and therefore
arrive with `$id`s in the ruled URN form (`schemas.py:67`) automatically —
`tests/test_cdm_schemas.py:36` checks that form per file, and
`tests/test_cdm_schemas.py:29` is a **subset** check (`expected <= on_disk`), so it does not
refuse a widened set.

**The `$id` of every published schema moves**, because `SCHEMA_VERSION` is inside it
(`schemas.py:76`). `schemas.py:62` records that a `$id` is a consumer-visible identifier; here it
moves as the version moves, which is what the version segment is for, and no `$ref` in these
documents crosses a file (`schemas.py:36`), so nothing dangles.

**Not proposed, and the reading that says why.** The specification's §58 security markings live
inside `oes.security` and not as `Event.classification`. `tests/test_cdm_format_coverage.py:388`
asserts that `Entity.classification`, `Entity.top_classification` and `Event.classification` do
not exist — gap 12, which `FORMAT_COVERAGE.md` defers until gap 1 is settled. SC-OES must not
close it in passing.

## 7. Python package impact

New importable surface, all additive: the SC-OES models and enums, the registry accessors of
§103, the ontology-identifier validator, and `SC_OES_VERSION`. Every one of them is "an
importable name is added", which `version.py:101` makes a package MINOR.

`__init__.py:78`'s `__all__` is a hand-written list of 23 names; each new public name joins it.
Note that `tests/test_cdm_packaging.py:328` requires the marker
`WHY THEY MUST BE ALLOWED TO DIVERGE` to appear in exactly one `.py` file — `version.py` — so a
module introducing a third version axis routes to that file and does not restate the reasoning.

`PACKAGE_VERSION` moves at least MINOR, and `MIGRATIONS.md:52` makes it unavoidable: "A
`schema_version` bump is always at least a package MINOR". The bump-derivation gate
(`gates/bump_derivation.py`) reads `SCHEMA_VERSION` moving as a MINOR signal directly — its table
at line 74 says "and the table says so outright". Whether any unit lands **UNRULED** is item 22's
business; the gate refuses rather than guesses, and `MIGRATIONS.md`'s pending section is where a
ruling is written.

## 8. Migration implications

`MIGRATIONS.md:33`'s procedure is six steps and all six apply: edit the model, bump
`SCHEMA_VERSION`, re-export the schemas, add an entry naming the *reason*, re-run every adapter's
goldens **and read the diffs**, and close any `FORMAT_COVERAGE.md` gap the change closes (none
does — see item 6).

Step 5 is the expensive one and it is the one §121 is about. The diff is 538 files; reading it
means establishing that every hunk is one of exactly three mechanical shapes and that nothing
else moved. Item 23 states the shapes and the check.

No migration note in the MAJOR sense is owed: nothing is removed, renamed, narrowed or made
required, so the MAJOR row (`MIGRATIONS.md:20`) is not reached and no coordinated deployment is
implied. The 1.1.0 entry should say that in its own words, because the section's own convention is
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

`sort_keys=True` is also the answer §105 asks for. The repository already serialises canonically
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

**Optional `Event.oes`, as §17 prefers, and the tree supports it rather than merely permitting
it.** Three readings decide it:

- `models.py:428`'s `CDMObject` union is discriminated on `object_kind` over four kinds, and
  §4 forbids a fifth. An attachment that is a new top-level object is out on the specification's
  own terms and out on the tree's shape.
- `Event.payload` (`models.py:327`) is `dict[str, Any]` and free-form, so `oes` *could* ride
  inside it with no schema change at all. **Rejected**: `payload` is the never-drop bag for
  source-specific fields (`models.py:329`), and putting governed SynapseCommand semantics in the
  bag reserved for a source's own shape is the exact confusion `models.py:17` describes — "source-
  specific fields at the same level as canonical ones". It would also make `oes` invisible to the
  published schema, which defeats §104's offline validation for non-Python consumers.
- `models.py:59`'s `extra="forbid"` means a declared field is the only way to attach anything at
  the top level. So the choice is a declared optional field or nothing, and §17's shape is the one
  the tree wants.

The block's own fields follow §17 exactly: `spec_version`, `event_class`, `type_id`, `maturity`,
`status`, `verification`, `confidence`, `effective_from`, `effective_to`, `event_relations[]`,
`entity_relations[]`, `evidence[]`, `security`, `extensions`. `effective_from`/`effective_to` take
the `Timestamp` annotation (`models.py:61`); the `effective_to >= effective_from` check of §40 is
a `model_validator(mode="after")` in the shape `Entity._interval` already uses
(`models.py:271`), whose message is worth copying in tone — it names the defect as a translation
defect rather than as data.

ADR 0001 records this with the `payload` alternative and its refutation.

## 11. Ontology representation strategy

§71's preferred solution — conservative RDFS/OWL in Turtle plus a JSON-LD context — is what ADR
0002 should adopt, and the constraint the tree adds is about **dependencies, not format**.
`pyproject.toml:74` declares exactly two runtime dependencies, `pydantic>=2.6` and
`jsonschema>=4.0`, and `README.md:204` states that pair as a property of the distribution. §124
forbids an RDF reasoner as a runtime dependency and permits a test-only parser; item 20 takes
that reading further.

The consequence for representation: **nothing at runtime may need to parse Turtle.** Ontology
identifiers reaching the CDM are validated as *strings* against the syntax of §73
(`urn:synapsecommand:ontology:<module>:<Term>`), by a regex in the package with no RDF library
behind it. The `.ttl` files are the authority for the vocabulary and are validated in the test
suite (§118). That split also satisfies §123's "ontology RDF may remain repository-only".

`ontology/` sits at the repository root beside `schemas/`, for the reason `README.md:35` gives
about `schemas/`: it is an artefact for consumers who are not Python, and it should not require
understanding a Python package layout to find.

## 12. Namespace strategy

Four identifier spaces, three of them new, and one of them already ruled in this tree.

- **Event type IDs** — `sc.<domain>.<event_name>.v<major>` (§24), third parties on
  `x.<namespace>.<domain>.<event_name>.v<major>` (§25). A regex in the package, checked in both
  directions, and the `sc.*` prefix refused from a producer that is not the governed registry.
- **Ontology terms** — `urn:synapsecommand:ontology:<module>:<Term>` (§73).
- **Schema `$id`s** — already ruled. `schemas.py:30`–`:67` is a long, dated ruling that a `$id`
  must *identify* and not *locate*, that `https://` invites a fetch this repository will not
  serve, and that the URN form is the answer; `BASE_ID` is `urn:synapsecommand:cdm`. The ontology
  URN above is the same decision applied to a second namespace, and ADR 0003 should cite
  `schemas.py:48` rather than re-argue it — the previous value was
  `https://synapsecommand.local/cdm`, and RFC 6762 reserves `.local`, which is the concrete
  mistake that ruling exists to prevent repeating.
- **Version axes** — `SCHEMA_VERSION`, `PACKAGE_VERSION`, `SC_OES_VERSION`, an ontology version
  and per-profile versions. `version.py`'s whole docstring is the argument for the first two being
  separate facts, and `tests/test_cdm_packaging.py:266` sweeps for a derivation of either from the
  other. **Where `SC_OES_VERSION` lives is an open decision this plan does not take**: `version.py`
  is the natural home and its docstring opens "Two version numbers" (`version.py:1`), so a third
  moves that sentence. The reading that would settle it is whether any test derives the count from
  that docstring; `tests/test_cdm_prose_counts.py` pins several prose figures in this file's
  neighbourhood and the sweep for this particular one has not been run. ADR 0003 or 0005 takes it.

## 13. Event registry strategy

A machine-readable JSON registry, thirteen governed entries (§88), each carrying the fifteen
fields §31 requires, loaded and validated by tests (§119) and readable through the four helpers of
§103.

**Its location is decided by packaging and not by taste** — see item 19, which is the binding
constraint. Two readings shape the content:

- **The legacy `EventType` vocabulary has seven members** (`enums.py:52`): `DETECTION`,
  `GNSS_INTERFERENCE`, `TRACK_UPDATE`, `ALERT`, `STATUS_CHANGE`, `PLAN_INJECT`, `SIM_RESULT`.
  §32 requires exactly one expected legacy type per governed ID *where meaningful*, and explicit
  `null` otherwise. Only `sc.pnt.gnss_interference.v1 → GNSS_INTERFERENCE` is unarguable from this
  vocabulary. The other twelve are a per-entry judgement, and §32's "explicitly store null rather
  than inventing one" is the default this plan recommends for the four decision-domain types,
  which have no member that means them. **The mapping table is ADR 0007's and not this plan's.**
- **`payload_model` is already occupied for one entry.** `models.py:307`'s `PAYLOAD_MODELS` maps
  `EventType.GNSS_INTERFERENCE` to `GnssInterferencePayload` (`models.py:282`), which carries
  `frequency_band`, `interference_type` and `signal_strength_dbm` — precisely §63's list. §63 says
  reuse it and do not duplicate it, and the tree agrees: that model is already `extra="allow"`
  (`models.py:291`) for the lossless reason §61 states.

## 14. Profile strategy

Seven profiles (§89), each a document under `spec/sc-oes/profiles/` with the thirteen sections
§89 lists, each versioned independently (§20) and each at a declared maturity.

The v0.1 recommendation from the tree: **only the PNT profile has a producer.** §111 makes PNTMAP
the reference implementation and §121 says "preferably only PNTMAP should require a deliberate
semantic upgrade" for v0.1. So PNT is the profile with an implementation behind it and the other
six are specification-only at 0.1.0 — which is a state this repository already has a precedent
and a name for: `FORMAT_COVERAGE.md:8026`, "Row sets written as specifications, with no adapter
code yet". Profile conformance (dimension D of §100) is therefore claimable against PNT and
declarable-but-unexercised against the rest, and the profile documents should say so rather than
implying an implementation.

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
§62 and §61 describe between typed validation and lossless preservation. Its docstring is the
ruling: validation is a **check** and never a transformation — the dict stays byte-identical as
the adapter wrote it, extra keys survive, and `typed_payload()` (`models.py:351`) is where a
consumer gets the parsed object.

`OES_PAYLOAD_MODELS` is therefore keyed by `type_id` string, validated the same way, with an
unregistered `type_id` leaving the payload free-form and transportable — which is `PAYLOAD_MODELS`'
own documented behaviour (`models.py:304`: "an event_type with no entry keeps a free-form
payload") and simultaneously §27's unknown-semantics requirement. The two mechanisms are the same
mechanism, and registering a model is a MINOR by `MIGRATIONS.md:21`.

Payload models are `extra="allow"` (the `GnssInterferencePayload` precedent, `models.py:291`);
the SC-OES metadata models are `STRICT`. That split is item 6's and is the whole of §14 and §61
read together.

## 17. Conformance strategy

Five dimensions (§100), five separately reportable verdicts, all offline (§104).

The repository's validation philosophy is a **column per property with SKIP for unrun**
(`harness.py:473`, `harness.py:230`), and the conformance report should be the same shape: five
columns, each `PASS`/`FAIL`/`SKIP`, with `SKIP` for a dimension not exercised — never a single
"SC-OES compatible" flag, which §100's first line forbids and which the harness's own design
already argues against.

Offline is free here and is worth stating as a reading rather than a promise: the two runtime
dependencies are `pydantic` and `jsonschema` (`pyproject.toml:74`), `adapter.fixture_root()`
(`adapter.py:231`) resolves packaged data through `importlib.resources` rather than through a
repository path, and `schemas.generate()` produces the schemas from the models with no file and no
network. Nothing in the validation path reaches out today, and §104 requires that it stay so.

The CLI pattern to prefer is the harness's: a `--json` machine-readable report (`harness.py:534`)
beside the rendered table, and exit codes as module constants (`harness.py:99`).

## 18. Governance strategy

Six documents under `spec/governance/` (§90) implementing §93–§96, plus the `CONTRIBUTING.md`
routes of §133.

The tree already has the governance primitive these need: **a decision is dated, written where it
is enforced, and never silently updated.** `MIGRATIONS.md`'s history sections, the pin records'
`what_this_is` nodes, and `gates/bump_derivation.py:44`'s refusal-until-ruled are three instances
of one practice. §96's deprecation rules (identifier retained, original definition retained,
deprecation date, replacement, migration guidance) are that practice applied to semantic
identifiers, and the deprecation document should cite `MIGRATIONS.md:30` — "Renaming a field is
two releases, never one" — as the existing statement of the same rule one layer down.

`CONTRIBUTING.md:12`'s DCO requirement covers external contribution already; §133's addition is
*what* may be proposed (event types, ontology terms, profiles, adapter mappings, examples,
validators) and through which document, not a new legal mechanism.

## 19. Packaging strategy

**This is the constraint that decides where the registry lives, and the specification's suggested
location cannot satisfy it.**

`tests/test_cdm_packaging.py:117` asserts equality in both directions between what
`git ls-files synapse_cdm` tracks and what the setuptools configuration would ship. The shipping
side is `packages.find` for `.py` inside a package, plus `package-data` minus
`exclude-package-data`; `pyproject.toml:164` declares `package-data` as exactly two globs —
`fixtures/**/*` and `*.md`.

So:

- A tracked file at `packages/cdm/synapse_cdm/spec/sc-oes/event-types.json` matches **neither**
  glob and is not a `.py` in a package, so the closure test fails on `missing` — a tracked file
  that would not be in the built distribution.
- A file at the **repository root**, `spec/sc-oes/event-types.json`, is outside
  `packages/cdm/` entirely, so it can never be in the wheel — and §123's decision principle ("if
  runtime validation requires an artifact, package it") plus §104's offline requirement mean it
  must be.

Two survivable answers, and ADR 0004 chooses:

1. **Widen `package-data`** with a third glob and put the registry under
   `synapse_cdm/spec/sc-oes/`. `pyproject.toml:141` is explicit that widening a glob is the
   correct repair and that adding an extension to a list is the wrong one — the comment records
   the wheel once being short by 72 raw ASTERIX blocks for exactly that reason. This keeps the
   root `spec/` tree as the human-readable normative documents and puts the machine-readable
   artefact in the package.
2. **Put the registry under `fixtures/`**, where `fixtures/**/*` already ships it. Cheaper, and
   wrong on meaning: `fixtures/` is verification data, and a normative registry is not a fixture.

This plan recommends (1) and names (2) so the ADR has both. Either way the `.ttl` files stay
repository-only (§123 permits it) and the pinned-document exclusions at `pyproject.toml:170` are
untouched — note that those exclusions are keyed on `fixtures/*/spec/**`, a different `spec/` from
the root one, which item "conflict 4" below is about.

`gates/wheel_install.py`'s thirteen checks all continue to apply; `check_manifest`
(`wheel_install.py:296`) and `check_resources` (`wheel_install.py:413`) are the two that would
catch a registry that is declared and does not arrive.

## 20. Dependency impact

**Target: zero new runtime dependencies.** The reading that makes this achievable:
`pyproject.toml:74` declares `pydantic>=2.6` and `jsonschema>=4.0`; the SC-OES models are pydantic
models, the registry is JSON, type-ID and ontology-identifier validation are regexes, and no
runtime path parses Turtle (item 11).

One new **test-only** dependency is likely and §124 permits it explicitly: an RDF parser for §118,
which asserts that every `.ttl` file parses, that term IDs are unique, that parents resolve and
that no operational instances are present. It joins `[project.optional-dependencies]`'s `test`
extra (`pyproject.toml:79`), which today is `["pytest>=8.0"]`.

That addition has a version consequence worth naming in advance: `gates/bump_derivation.py:72`
reads "an optional dependency appears" as a **MINOR** signal directly from
`[project.optional-dependencies]`. It is one more MINOR signal in an arc that already has one from
`SCHEMA_VERSION`, so it changes no outcome — but it will appear in the gate's output and should
not surprise the round that reads it.

Everything in §135's non-goals list and §124's forbidden list stays absent, and
`tests/test_cdm_boundary.py:104` keeps `hashlib` out along with the rest of `FORBIDDEN_CRYPTO`.

## 21. Documentation changes

§125's five-way distinction (CDM = representation, ontology = semantics, SC-OES = operational-event
semantics, adapters = translation, private SynapseCommand = reasoning) goes into `README.md` and
`docs/docs/intro.mdx`, and §126's positioning sentence replaces `README.md:3`'s current one-line
description. §127's "does not replace ASTERIX / STANAG / TAK / …" belongs beside it; the tone
constraint ("keep the tone technical", §126) matches what `README.md` already does.

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

**New test modules, mapped to the specification's own lists.** §116 gives 24 SC-OES assertions,
§117 gives 8 for entity annotations, §118 gives 13 for the ontology, §119 gives 11 for the
registry, §120 requires every committed example to be iterated automatically. Each becomes a
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

**Risk 1 — the mass golden change, and it is the one §121 names.** Measured at this commit:

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
one byte of any non-CDM wire format moves**, which is the strongest available answer to §138's
"existing adapters still operate".

§121 says dozens of unrelated golden changes are a design problem and §138 forbids *unexplained*
mass changes. This one is explained and, more usefully, it is **checkable**: every hunk in the 538
files must be one of exactly three shapes —

1. `"schema_version": "1.0.0"` → `"schema_version": "1.1.0"`;
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

§107's threat model list is the document to write; the readings that shape it here:

- **The trust boundary is already named and must not move.** `models.py:107` — the `integrity`
  block is designed and unpopulated, and `tests/test_cdm_boundary.py:104` makes an import of any
  crypto module a build failure. SC-OES adds no signing, no verification and no key handling
  (§106), and §55's evidence `hash` is a descriptive string the parser never computes or checks.
- **A SC-OES parser is not a cross-domain solution** (§59). Security markings are transported,
  never interpreted, downgraded, upgraded, normalised or enforced (§58). The repository has no
  classification-enforcement code and must acquire none — it is in §2's proprietary list.
- **Synthetic/live confusion is the highest-value threat and is already structurally defended.**
  `models.py:90` records the reasoning at length: `synthetic` is required with no default because
  neither direction is safe to guess. §11 requires SC-OES to inherit it, and it does so for free —
  `oes` hangs on an `Event`, and every `Event` carries a `SourceRef`.
- **Resource safety** (§110) — the concrete surfaces are `event_relations[]`, `entity_relations[]`,
  `evidence[]` and `extensions`. Bounded nesting is the property to document; `extensions` is a
  `dict[str, Any]` like `Attributes` (`models.py:74`) and therefore recursive by type, so §110's
  "unknown extensions must not permit unbounded structural recursion" is a validation rule to
  write rather than a property to inherit.
- **Semantic poisoning and unknown-type handling** (§27, §98, §99) — the defence is the same
  mechanism as `PAYLOAD_MODELS`' free-form fallback (item 16): preserve, do not guess, do not map
  to a "similar" known type.
- **No secrets, no real data, no private endpoints** (§146). `CONTRIBUTING.md:166` is the standing
  rule and `tests/test_cdm_boundary.py:95` keeps the private topology out of the imports.

## 25. IP/licensing risks

Apache-2.0, and the repository's arrangement is stricter than the specification assumes.

`NOTICE:11`–`:39` records that this repository has **no per-file headers**: no tracked file
carries an SPDX tag and no copyright notice sits outside a licence file, and
`tests/test_cdm_publication.py:314` and `:327` enforce both halves over `git ls-files`. §129 asks
that new material be Apache-2.0; the correct way to achieve that here is to add nothing —
repository-level licensing already covers every new file, and pasting a header onto a new `.ttl`
or `.py` would fail a gate and falsify `NOTICE`'s paragraph.

`NOTICE:55` is the boundary §128 is about: "The specification documents this repository PINS are
not part of the Work and are not covered by this licence." Thirty documents are pinned by hash,
byte count, page count, edition and source URL; **none of their bytes is in the tree** (`git
ls-files '*.pdf'` → 0) and `pyproject.toml:170` excludes them from the distribution positively
rather than by omission. SC-OES must be *independently authored* — §128's own instruction —
which for the ontology means terms defined in this repository's own words with mappings to
external standards, never transcribed definitions.

§131's trademark boundary needs a short statement and not a licence: Apache-2.0 grants no
trademark rights, and the distinction to make explicit is between implementation conformance and
brand use. §132's terminology — "SC-OES Conformant", never "Certified" or "Approved" — should be
written into the conformance document and, given §101's list, the specification should also
refuse "NATO certified / approved / standard" in its own text. `LICENSE` (201 lines) is
byte-identical to the canonical Apache-2.0 and must stay so (`NOTICE:41`), so nothing is added
there.

No incompatible dependency is introduced (item 20); the one likely test-only RDF parser must be
checked for licence compatibility before it lands, which is ADR 0010's business.

## 26. Implementation phases

§136's eighteen phases, decomposed into S rounds. Phases 0 and 1 are this round. The rest are
proposed here and briefed by M after the ADR review — §8's "proceed automatically" is overridden
for this campaign, and the loop stops after S1 by design.

| Round | Phases | Exit criterion, in one line |
|---|---|---|
| **S0** | 0–1 | this document exists on `sc-oes/0.1`, 26 items plus conflicts, every item grounded in `file:line`; branch = origin/main tip + one signed commit; nothing pushed |
| **S1** | 2 | `docs/adr/0001…0010`, eight sections each, status `Proposed — awaiting M's review`, mutually consistent, every decision cited to this plan or to a reading |
| — | *M reviews the ADRs* | the loop stops here by design |
| **S2** | 3 | six governance documents under `spec/governance/`, each implementing its §93–§96 process, no code change |
| **S3** | 4 | the normative tree under `spec/sc-oes/` — sixteen documents and seven profile stubs — with §91's terminology defined and normative/non-normative distinguished |
| **S4** | 5–6 | eight `.ttl` modules plus `context.jsonld`; §118's thirteen validations green; test-only parser declared |
| **S5** | 7–8 | `Event.oes` and `Entity.ontology_types` land; `SCHEMA_VERSION` → 1.1.0; the SC-OES models; §116 and §117's 32 assertions green; **the 538-golden diff read by JSON path** and the version pin re-pinned |
| **S6** | 9–10 | the registry in the package, §119's 11 validations green, typed payloads reusing `GnssInterferencePayload` |
| **S7** | 11 | PNTMAP upgraded within its source's semantics; four goldens read individually; no other adapter touched |
| **S8** | 12 | thirteen examples plus the linked chain, all executable (§120), synthetic identifiers only |
| **S9** | 13–14 | schemas regenerated, reference pages regenerated **and** `npm --prefix docs run ci` green; conformance tooling with five separately reportable dimensions |
| **S10** | 15 | §125's five-way distinction and §126–§127's positioning in `README.md` and the site; item 23's risk-5 prose repaired |
| **S11** | 16–17 | full suite, wheel gate, security/IP review over the whole diff |
| **S12** | 18 | §147's final engineering report |

**A review belongs between S5 and S6** and between S7 and S8 at minimum: S5 is the only round that
moves the wire contract and 538 goldens, and S7 is the only one that changes what a shipped
adapter emits. S2–S4 are documentation-only and could share a round if the budget is tight, at the
cost of a larger diff to review at once.

**Release is not in this decomposition.** §148 forbids pushing, tagging, publishing or creating a
release, and the campaign's own rule (M's ruling of 2026-09-06 on §148) confines every S round to
the local branch. A release of the SC-OES work is a separate decision after M's review.

---

## Conflicts with repository invariants

§7's last paragraph rules that "the real repository is authoritative where this specification
conflicts with an established repository invariant". Five conflicts were found. **None of them is
a requirement that is impossible under an invariant**, so this round does not stop on any of them;
each names the invariant, quotes it from where the repository states it, and says which side
yields.

### Conflict 1 — the version bump forces the mass golden change §121 calls a design problem

*The specification:* §121 — "If dozens of unrelated golden files change, treat that as a design
problem. Do not accept mass fixture churn without justification." §138 — "no unexplained mass
golden-fixture changes." §16 asks for additive change "wherever practical".

*The invariant:* `MIGRATIONS.md:21` — "**MINOR** | an optional field added; an enum member added;
a payload model registered; validation relaxed". And `models.py:193`: `schema_version` defaults to
`SCHEMA_VERSION` and is carried in every serialised object.

*The collision:* the two optional fields SC-OES needs are exactly the MINOR row's first clause, so
the bump is required by the repository's own table; and because the version string is inside every
object, 538 golden files move — 1308 version-string occurrences, 653 entity objects and 566 event
objects. That is not "dozens".

*Resolution — the repository wins, and the specification's requirement is met differently.* The
bump is not optional and not avoidable: suppressing it would mean either an unversioned shape
change (which `version.py:7` exists to prevent) or hiding `oes` inside `payload` (refused in item
10 on the tree's own grounds). What §121 and §138 actually forbid is churn that is *unrelated* and
*unexplained*. This churn is neither: it is related — one version bump and two field additions, in
one release — and it is explainable to the byte, in the three shapes item 23 enumerates. The
obligation this places on Phase 7/13 is the JSON-path structural diff of item 23, which converts
"justified" from a claim into a check. **Nine golden files, all external-format egress output, do
not change at all.**

### Conflict 2 — the registry's suggested location cannot be in the wheel

*The specification:* §31 — "Preferred source: `spec/sc-oes/event-types.json`". §123 — "If runtime
validation requires an artifact, package it." §104 — validation MUST work offline.

*The invariant:* `tests/test_cdm_packaging.py:117`, which asserts equality in both directions
between `git ls-files synapse_cdm` and what setuptools would ship, and `pyproject.toml:164`, whose
`package-data` is exactly `["fixtures/**/*", "*.md"]`.

*The collision:* a root-level `spec/` is outside the distribution root and can never ship; a
`synapse_cdm/spec/` matches neither glob and fails the closure test as a tracked-but-unshipped
file. Both of the specification's readings of "where the registry goes" are refused by the same
gate, from opposite sides.

*Resolution — the repository wins on the mechanism, the specification wins on the requirement.*
The registry must be inside the package and the glob must be widened to reach it (item 19), which
`pyproject.toml:141` already names as the correct kind of repair. §31's word is "preferred", and
§90's own closing sentence — "Use repository conventions if they make another structure materially
better" — grants the move.

### Conflict 3 — `spec/` already means something else in this repository

*The specification:* §90 proposes `spec/sc-oes/` and `spec/governance/` at the root for
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

*Resolution — a naming decision, not a blocker, and it is ADR 0004's.* The paths differ
(`fixtures/*/spec/` versus a root `spec/`) and every existing gate is keyed on the former, so the
two can coexist. The plan's recommendation is to take §90's structure as given and to state the
distinction explicitly in `spec/sc-oes/README.md` and in `NOTICE`'s neighbourhood, rather than to
invent a third word. Should the ADR prefer a distinct root name, `sc-oes/` is the obvious one.

### Conflict 4 — evidence hashes and canonicalization meet the no-crypto boundary

*The specification:* §55 gives `EvidenceRef` an optional `hash`. §105 requires ADR 0006 to address
deterministic serialization and says to "reuse an existing canonicalization mechanism if the
repository already has one".

*The invariant:* `tests/test_cdm_boundary.py:73` — `FORBIDDEN_CRYPTO = {"cryptography",
"hashlib", "hmac", "nacl", "oqs", "secrets", "ssl"}` — enforced by AST over every module in the
package (`:104`), because "a signature computed inside a translator is held by nothing that audits
it" (`models.py:107`).

*The collision:* it is narrower than it looks and is recorded because it is a trap rather than a
contradiction. §55 already says the hash "is descriptive metadata only in v0.1", so the field is a
string the parser transports and never computes or verifies. The trap is §105: a round that reads
"canonicalization" as "implement one" would `import hashlib` and fail the boundary test.

*Resolution — no conflict once stated, and the invariant is what states it.* ADR 0006 documents
the four properties §105 lists and points at what the tree already does — `sort_keys=True`
(`harness.py:402`), one timestamp form that truncates rather than rounds (`times.py:70`), and a
schema that publishes the strict pattern (`models.py:65`). It implements nothing. §106's list of
what not to build is the same boundary the repository already draws around `integrity`.

### Conflict 5 — the ontology needs an RDF parser the runtime may not have

*The specification:* §118 requires machine validation of the Turtle files; §71 prefers RDFS/OWL in
Turtle; §102 wants ontology-identifier validation in the conformance tooling.

*The invariant:* `pyproject.toml:74` — two runtime dependencies, `pydantic>=2.6` and
`jsonschema>=4.0` — restated as a property of the distribution at `README.md:204` and in the
package's own description.

*The collision:* validating "is this a governed ontology term?" at runtime, against the `.ttl`
files, needs an RDF parser at runtime.

*Resolution — both, by splitting the question, and §124 authorises the split.* Runtime validates
identifier **syntax** (a regex, §73's grammar) and, where a governed term must be *recognised*,
looks it up in the packaged registry rather than in the ontology. The `.ttl` files are validated in
the **test** suite with a test-only parser, which §124 permits in as many words ("Test-only
ontology parsers are acceptable"). §123's "ontology RDF may remain repository-only if runtime
validation does not require it" is then true by construction rather than by hope.
