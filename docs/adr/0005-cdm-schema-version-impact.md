# ADR 0005 — CDM schema-version impact

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

Amended by SA.1 — M, 2026-09-06: reviewed under SA.1 §58 and §64 and **nothing in this ADR moves**.
`SCHEMA_VERSION` 2.0.0 and the independently derived `PACKAGE_VERSION` 2.0.0 are SA.1 §4–§5 locked
decisions, and SA.1 §64 is explicit that they are not reopened because SA.1 changes identifier
wording. The equality of the two numbers stays coincidental and stays derived rather than copied.
Still Accepted.

**Implementation note — round SK, 2026-09-07. The decision has been applied.** This ADR's
independently derived package-major decision is now in the tree. The authoritative implemented
state after SK is:

```text
PACKAGE_VERSION = "2.0.0"
SCHEMA_VERSION  = "2.0.0"
```

Their numerical equality remains coincidental. `PACKAGE_VERSION` and `SCHEMA_VERSION` remain
independent axes, and no code derives one from the other — `tests/test_cdm_packaging.py` sweeps
every module in the package for an assignment that would.

Round SK also completed the release-readiness and version documentation this ADR asks for; it is
`docs/sc-oes-release-readiness-report.md`. **Historical readings below that mention
`PACKAGE_VERSION` 1.8.0 or `SCHEMA_VERSION` 1.0.0 are intentionally preserved as observations of
the repository at the time this ADR was decided. They are not statements of current repository
state**, and the section that carries them says so at the section. Still Accepted.

## Context

ADR 0001 adds two optional fields to the canonical models: `Event.oes` and
`Entity.ontology_types`. This ADR decides what that costs on both version axes. §20 rules the
schema axis, §22 requires this ADR to record the package axis's *derivation* rather than a
number, §23 rules the migration behaviour and §24 rules the golden consequence.

**The bump rules, quoted from where the repository states them.**
`packages/cdm/synapse_cdm/MIGRATIONS.md:20` — "**MAJOR** | a field removed or renamed; a type
narrowed; an enum member removed; an optional field made required; the `ids.NAMESPACE` changed |
breaks readers; needs a migration entry below and a coordinated deployment". `MIGRATIONS.md:21` —
"**MINOR** | an optional field added; an enum member added; a payload model registered; validation
relaxed | old readers keep working, old data keeps validating". The same table is restated in the
package's source at `version.py:91`–`:95`.

**The package-version policy, quoted from where the repository states it.** `version.py:99`–`:101`
— "MAJOR  an importable name is removed or its meaning changes, the ``Adapter`` contract changes
in a way that breaks a third-party adapter, a harness exit code or flag is removed, the Python
floor is raised." `version.py:102`–`:103` — "MINOR  an adapter is added, a harness flag or check
is added, a fixture set is added, a new optional dependency. Existing code keeps working."
`version.py:106`–`:107` — "A ``SCHEMA_VERSION`` bump is ALWAYS **at least** a package MINOR,
because the objects this package emits change shape. The reverse does not hold, and that is the
whole point." `MIGRATIONS.md:52` says the same in the release procedure's words. The mechanical
form is `gates/bump_derivation.py:74`, whose signal table reads "`SCHEMA_VERSION` moves | MINOR |
`version.py`, and the table says so outright" — and whose rule of shape at
`gates/bump_derivation.py:91`–`:93` states its own limit: "an unambiguous ADDITION of a declared
surface is MINOR, an unambiguous REMOVAL is MAJOR … a modification in place is the unruled case
and goes to a human."

**The divergence ruling, quoted from where the repository states it.** `version.py:1` opens: "Two
version numbers, what each one governs, and why they are not one number." `version.py:7`:
"`SCHEMA_VERSION` is the **wire contract's** version. It is carried in EVERY serialised object".
The heading at `version.py:18` — "WHY THEY MUST BE ALLOWED TO DIVERGE — AND, SINCE 1.1.0, WHY
THAT IS NO LONGER AN ARGUMENT" — introduces the ruling's own account of its weakest moment: while
both numbers read `1.0.0`, "the claim rested on a counterfactual, and any code that derived one
number from the other would have produced the right answer on every run" (`version.py:47`–`:48`).
The supporting measurement is the section listing what landed with no schema change:
`version.py:54`–`:56` says each of its entries "added thousands of lines of shipped behaviour to
this distribution at `schema_version` 1.0.0, with no field added, removed or retyped", and
`version.py:59`–`:60` concludes that had the package been released before any of them, "each would
have been a package MINOR and none of them a schema bump". The count of those entries is
deliberately not restated here: `version.py:56`–`:57` says it "is derived from the section's own
bullets by ``tests/test_cdm_prose_counts.py`` rather than stated here on trust", and this ADR is a
tracked file. `tests/test_cdm_packaging.py:266` sweeps for any code deriving one number from the
other.

**Historical readings at the ADR-decision commit, taken rather than carried.** `SCHEMA_VERSION =
"1.0.0"` (`version.py:114`); `PACKAGE_VERSION = "1.8.0"` (`version.py:119`); `compatible()`
(`version.py:127`) returns `w_major == r_major`, and executed: `compatible("2.0.0", "1.0.0")` →
**False**, `compatible("1.0.0", "2.0.0")` → **False**, `compatible("1.0.0", "1.1.0")` → **True**.

**These values are intentionally historical and were superseded by the implementation recorded in
the SK lineage note above.** They are not rewritten to `2.0.0`, because the comparison between what
the tree read then and what this ADR decided is the evidence for the decision, and deleting it
would leave the decision looking like an assertion. The line references in this paragraph are the
decision commit's too.

## Decision

**`SCHEMA_VERSION` moves `1.0.0` → `2.0.0`, a MAJOR; `PACKAGE_VERSION` moves to `2.0.0` on its own
derivation and not by copying the other number.**

1. **The schema move is a MAJOR, and the repository's own table says so when it is read by its
   consequence column.** §20 rules it — "The new public fields alter a strict
   `additionalProperties: false` wire contract. Therefore `SCHEMA_VERSION` 1.0.0 -> 2.0.0. This is
   a MAJOR CDM schema change. Do not describe it as a forward-compatible 1.1 change" — and §21
   gives the reason as three propositions that cannot all hold: "old model forbids undeclared
   keys / new object contains new keys / old reader accepts new object". The third is the false
   one, because `models.py:59` sets `extra="forbid"` and `tests/test_cdm_schemas.py:63` asserts
   `additionalProperties: false` on all four kinds.
   **`MIGRATIONS.md`'s table has two columns and they disagree here, which is worth stating
   plainly rather than eliding.** By its *change* column, "an optional field added" is
   `MIGRATIONS.md:21`'s MINOR. By its *consequence* column, MINOR means "old readers keep working,
   old data keeps validating" — and the first half of that is false for a strict reader, as the
   readings above show. `MIGRATIONS.md:20`'s consequence column reads "breaks readers; needs a
   migration entry below and a coordinated deployment", which is exactly what happens. **The
   consequence column is what a row means; the change column is a list of the cases that were in
   view when it was written, and a strict reader was not one of them.** So the repository and §20
   agree once the table is read for what it asserts, and this is not a case where §7's
   repository-wins rule has to be invoked.
2. **The bump is not suppressible.** The alternatives are an unversioned shape change — which is
   the state `version.py:7` exists to make impossible, the version being carried in every
   serialised object — or hiding `oes` inside `Event.payload`, which ADR 0001 refuses on the
   tree's own grounds. There is no third option in which the wire form changes and the number
   does not.
3. **`PACKAGE_VERSION` → `2.0.0`, and here is the actual derivation §22 asks for.** §22's rule:
   the package version is an independent axis, must not be derived mechanically from
   `SCHEMA_VERSION`, and the default expectation is `2.0.0` "unless the repository's documented
   package-version policy clearly and explicitly derives another result". Two readings, taken in
   order:
   - **What the documented policy derives is a FLOOR, not a result.** `version.py:106` says a
     schema bump is "ALWAYS **at least** a package MINOR", and `gates/bump_derivation.py:74`
     encodes that same floor as its `SCHEMA_VERSION` signal. Neither says a schema MAJOR is a
     package MINOR; both say a schema bump is not *less* than a package MINOR. And
     `gates/bump_derivation.py:91`–`:93` disclaims the case outright: a modification in place is
     "the unruled case and goes to a human". So the policy does not "clearly and explicitly derive
     another result", and §22's default is not displaced.
   - **The package MAJOR row is independently reached.** `version.py:99` — "an importable name is
     removed or its **meaning** changes" — and the same row's "the `Adapter` contract changes in a
     way that breaks a third-party adapter". Nothing is removed; what changes is meaning. After
     the bump, every object this distribution emits is refused by every peer installed at 1.x
     (`compatible("2.0.0", "1.0.0")` → False, reading taken), and every legacy object is refused
     by a consumer that gates on `compatible()` at 2.x (`compatible("1.0.0", "2.0.0")` → False).
     A third party whose adapter or consumer worked against 1.8.0 does not work against this
     release without a deliberate change. That is `MIGRATIONS.md:20`'s "breaks readers … and a
     coordinated deployment" arriving on the Python axis, and it is a package MAJOR on the
     repository's own words rather than on the schema number's.
   - **The equality is a coincidence of two majors and must not be read as a derivation.** §22:
     "Do not force numerical equality merely for aesthetics." The two numbers land equal at
     `2.0.0`, which is the state `version.py:45`–`:48` calls this file's weakest moment — "any
     code that derived one number from the other would have produced the right answer on every
     run". The register for it already exists: `version.py:81`–`:82` calls the 1.0.0 pairing "a
     coincidence of two first releases". This one is a coincidence of two majors reached on two
     independent readings, and `tests/test_cdm_packaging.py:266`'s sweep — not the numbers — is
     what keeps it honest.
   - **A reading a later round must not misread.** `tests/test_cdm_packaging.py:320` asserts
     `PACKAGE_VERSION != SCHEMA_VERSION or SCHEMA_VERSION != "1.0.0"`, so it is keyed on equality
     **at 1.0.0 specifically** and stays green at `2.0.0`/`2.0.0`. Its silence is not endorsement;
     its message says the sweep above it is "load-bearing again" whenever the numbers are level,
     and that is true at 2.0.0 even though the assertion does not fire.
   - **This ADR records a derivation; the release round types the number and writes the ruling.**
     Nothing here is a bump ruling in `MIGRATIONS.md`'s pending section, and none is written by
     the round that adopts this ADR.
4. **Migration behaviour, per §23, and the repository has a policy rather than a mechanism.**
   Reading taken: there is no migrator in the package — no `migrate` function or module anywhere
   under `packages/cdm/synapse_cdm/*.py`. What the repository has is `MIGRATIONS.md`: its MAJOR
   row obliges "a migration entry below and a coordinated deployment" (`MIGRATIONS.md:20`) and its
   History section is where the entry goes. §23's second branch therefore applies — "document the
   migration procedure rather than introducing a large new migration framework solely for SC-OES"
   — and the procedure documented is:
   - **`1.x` reader + `2.x` object = not contract-compatible.** Stated in exactly those terms, in
     `MIGRATIONS.md`'s entry and in the SC-OES versioning document (§117's `12-versioning.md`).
     No claim is made that an old consumer can parse a new object.
   - **`2.x` reader + legacy `1.x` object.** The 2.0.0 models accept a legacy object structurally
     unchanged: both new fields are optional with defaults, and no field was removed, renamed or
     narrowed, so **no field mapping exists and none is needed**. What refuses it is the version
     gate: `compatible("1.0.0", "2.0.0")` → False. A 2.x consumer that wants to read legacy data
     therefore takes an explicit decision — branch on major, or re-emit the object at 2.0.0, where
     the only value that moves is `schema_version` itself. That is the whole migration, and it is
     documented rather than coded.
5. **All six steps of the procedure at `MIGRATIONS.md:33` apply, and step 5 is the expensive one.**
   Edit the models; bump the constant; re-export the schemas; add the entry naming the reason
   (`MIGRATIONS.md:39`, step 4: "naming the reason — not just the change"); re-run every shipped
   adapter's goldens **and read the diffs** — `MIGRATIONS.md:41`: "A golden file updated without
   being read is how a defect becomes the expectation"; and close any `FORMAT_COVERAGE.md` gap the
   change closes, which is none (ADR 0001 keeps gap 12 open deliberately).
6. **Step 5 is discharged by a structural diff by JSON path, run before the goldens are
   committed.** §24 and §142 both require it and §142 gives the sequence: regenerate; run
   structural JSON-path diff; verify allowed changes; inspect the diff; only then commit. The
   assertion: across every changed golden file, the set of JSON paths whose value moved is exactly
   `{schema_version, ontology_types, oes}`. §24's exception is named and bounded — "except for the
   deliberately upgraded PNTMAP reference events", which is round SG's work under §157 — and §142
   adds that "external non-CDM outputs should not change unless independently justified". Anything
   else in the diff is a defect. §24's closing sentence is the rule this decision exists to
   enforce: "Do not approve mass goldens merely because tests regenerate successfully."

## Alternatives considered

**A — do not bump; treat the additions as invisible because they are optional.** Rejected by
`version.py:7`: the version is carried in every serialised object precisely so that a consumer can
tell which shape it is holding. An unversioned shape change makes `compatible()` answer a question
about a contract that has silently moved.

**B — `SCHEMA_VERSION` → `1.1.0`, a MINOR, on `MIGRATIONS.md:21`'s "an optional field added".**
**This was this ADR's decision while it was `Proposed`, and it is wrong.** §20 forbids it by name
("Do not describe it as a forward-compatible 1.1 change") and the tree refutes it independently:
the MINOR row's stated consequence is "old readers keep working", and a 1.0.0 reader meeting an
unknown key under `extra="forbid"` (`models.py:59`) and `additionalProperties: false`
(`tests/test_cdm_schemas.py:63`) rejects the object. The proposed text also claimed
`version.compatible()` would let a 1.0.0 reader accept the object; it would have, at 1.1.0 — which
is precisely why 1.1.0 is the wrong number, because acceptance by the version gate followed by
rejection by the schema is worse than an honest refusal at the gate.

**C — a MAJOR on the ground that the mass fixture change is large.** Rejected as the right answer
for the wrong reason. The size of the golden diff is a property of how the version string is
serialised, not of the compatibility consequence; a MAJOR justified by diff size would be a
precedent that prices churn instead of breakage. The ground is decision 1's, and it would hold if
a single golden file changed.

**D — avoid the bump by putting SC-OES in `Event.payload`.** ADR 0001's alternative B, refused
there on `models.py:329` and `models.py:18`. Named again here because "it avoids the bump" is its
strongest argument, and it is not strong enough: it trades a versioned, schema-visible contract
for an unversioned one hidden from the published schema, which defeats §125's offline validation.

**E — bump `SCHEMA_VERSION` but leave the goldens at 1.0.0.** Rejected mechanically:
`models.py:193` defaults `schema_version` to `SCHEMA_VERSION`, `harness.py:144` dumps with no
`exclude_none`, and `tests/test_cdm_schemas.py:22` fails the build when the published schemas
differ from the models. There is no configuration in which the goldens keep the old string and the
harness reports green.

**F — `PACKAGE_VERSION` → `1.9.0`, taking the gate's MINOR signal at face value.** Rejected on
decision 3's first reading: the signal is a floor and the gate says so, and treating a floor as a
result is how a distribution that breaks every consumer ships as a minor. Named because it is what
`gates/bump_derivation.py` will print, and a round reading that output without reading
`gates/bump_derivation.py:91`–`:93` beside it would take it.

## Consequences

Measured at this commit, each figure derived by walking the tree rather than quoted from a plan:

| Reading | Figure |
|---|---|
| golden files in the tree | 547 |
| golden files carrying a CDM object | 538 |
| `"schema_version": "1.0.0"` occurrences in those goldens | 1308 |
| golden files carrying at least one entity object / entity objects | 537 / 653 |
| golden files carrying at least one event object / event objects | 484 / 566 |
| golden files that do **not** change | 9 |

- **538 golden files change.** Every hunk must be one of exactly three shapes: the version string
  moving to `2.0.0`; a new `"ontology_types": []` line inside an object whose `object_kind` is
  `entity`; a new `"oes": null` line inside an object whose `object_kind` is `event`.
  `harness.py:402` renders with `sort_keys=True`, so `oes` sorts between `object_kind` and
  `payload` and `ontology_types` between `object_kind` and `position`; no existing line moves
  position within a file beyond those insertions.
- **The nine that do not change are the answer to §142's "external non-CDM outputs should not
  change".** They are the three egress adapters' external-format outputs —
  `fixtures/adsb/egress/golden/*.adsb`, `fixtures/ais/egress/golden/*.ais.nmea` and
  `fixtures/tak/egress/golden/*.cot.xml`. Not one byte of any non-CDM wire format moves.
- **Six published schema documents are regenerated**, and every `$id` moves, because
  `SCHEMA_VERSION` is a segment of it (`schemas.py:76`). `schemas.py:62` records that a `$id` is a
  consumer-visible identifier; here it moves as the version moves, which is what the version
  segment is for, and no `$ref` crosses a file, so nothing dangles.
- **`tests/test_cdm_packaging.py` goes red the moment either constant moves.** At the
  ADR-decision commit, its literal pair at `:313` was `(PACKAGE_VERSION, SCHEMA_VERSION) ==
  ("1.8.0", "1.0.0")`, and its own message says the fix is to re-pin and not to re-link. A round
  that meets it should not treat it as a surprise. **The implementation rounds did meet it and
  re-pinned the assertion to the new independently derived version state**: read in the current
  tree, the pair is `("2.0.0", "2.0.0")` at `tests/test_cdm_packaging.py:320` — the number moved,
  the two constants stayed two constants, and the sweep above the assertion is what keeps them
  that way.
- **`MIGRATIONS.md`'s bump table needs a dated clarification, and this round does not write it.**
  Decision 1 rests on reading the table by its consequence column; the table itself still lists
  "an optional field added" under MINOR with no note that a strict reader changes the answer.
  Under the repository's append-only rule a dated correction belongs beside the row, not an edit
  of it. `MIGRATIONS.md` is a distribution file and is round SD's to touch (§154), not this one's.
- **`version.py`'s prose needs care.** Its divergence section is written around the moment
  `PACKAGE_VERSION` reached 1.1.0 while `SCHEMA_VERSION` stayed at 1.0.0, and it argues from the
  two numbers being unequal. At `2.0.0`/`2.0.0` they are equal again, and the section has to say
  why that is a coincidence rather than a refutation — decision 3's third bullet is the argument,
  and `version.py:81`–`:82` is the sentence pattern to follow.
- The `docs/docs/schema-reference/` pages are generated from `/schemas` and must be regenerated
  and committed in the same change. That drift check is a node script run by the documentation
  site's own CI target, not by `pytest`, so a round that regenerates schemas and runs only the
  Python suite leaves those pages stale and green.

## Compatibility impact

- **Forward: not contract-compatible, and that is the message the major carries.** A 1.x consumer
  receiving a 2.0.0 object is refused twice over — by `compatible()` on the major (reading:
  `compatible("2.0.0", "1.0.0")` → False) and, if it skipped the version gate, by
  `additionalProperties: false` on the unknown keys. §21 is the specification's statement of the
  same fact and §11 required this ADR and ADR 0001 to stop claiming otherwise.
- **Backward: structurally clean, version-gated.** A 1.x object validates against the 2.0.0 models
  unchanged; `oes` defaults to `None` and `ontology_types` to `[]`. `compatible("1.0.0", "2.0.0")`
  → False, so the version gate is the only thing a 2.x consumer has to decide about. Decision 4 is
  the procedure.
- **Existing adapters:** every one of the fourteen keeps operating with no change to its
  translation (roster read: 14). None sets either new field, and §116 says none has to; the nine
  external-format goldens prove the egress side byte-for-byte.
- **Nothing is removed, renamed or narrowed**, so a migration entry has no field mapping to carry.
  What it carries is decision 4's two statements.

## Security impact

- **No security surface moves.** Two optional metadata fields are added; no validation is relaxed
  in the sense `MIGRATIONS.md:21`'s last clause means, no type is widened, and
  `tests/test_cdm_schemas.py:63`'s `additionalProperties: false` on the four kinds is unaffected —
  the new fields are declared, which is what makes them expressible at all.
- **An honest major is itself the security property here.** A consumer that is told "same major,
  minor from the future" and then handed an object its schema rejects has been given a wrong
  answer by the mechanism it trusts to give right ones. Refusing at the version gate is the
  failure a consumer can handle; §127's "unsupported semantic versions" is the same concern one
  layer up, for `type_id` majors.
- **The golden diff is the security-relevant artefact of this decision.** A mass mechanical change
  is exactly the diff a reviewer skims, and a substantive change hidden inside it would pass. That
  is why decision 6 makes the diff machine-checked by JSON path rather than read by eye:
  `MIGRATIONS.md:41`'s rule and §142's sequence, enforced rather than remembered.
- **The version string itself carries no data about a source**, so no marking, provenance or
  synthetic/live distinction is affected by the bump.
- **Schema `$id`s moving is a consumer-registration event, not a trust event.** No `$ref` in these
  documents crosses a file (`schemas.py:37`–`:38`), so no identifier is resolved at validation time and
  no fetch is invited — the property `schemas.py:38`–`:42` rules for.

## Reversibility

Low after release, high before it, and the asymmetry is the whole reason this ADR exists ahead of
the implementation.

Before the release that carries it, reverting is: restore both constants, regenerate the schemas,
regenerate the goldens, re-pin `tests/test_cdm_packaging.py:313`. All mechanical.

After release, neither number can go backwards — a published `schema_version` is on objects in
consumers' stores, every `$id` minted at 2.0.0 is registered somewhere, and a package version on
an index cannot be reused. The fields themselves remain deprecable under ADR 0001's reversibility,
but the version move is permanent. That is ordinary for a version and is not a defect; it is
stated here so the decision is taken once, deliberately, rather than discovered during round SD.
