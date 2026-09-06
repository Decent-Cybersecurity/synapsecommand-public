# ADR 0005 — CDM schema-version impact

## Status

Proposed — awaiting M's review.

## Context

ADR 0001 adds two optional fields to the canonical models: `Event.oes` and
`Entity.ontology_types`. This ADR decides what that costs on the CDM's own version axis, and it
is the ADR the specification's §121 and §138 bear on hardest.

**The bump rules, quoted from where the repository states them.**
`packages/cdm/synapse_cdm/MIGRATIONS.md:21` — "**MINOR** | an optional field added; an enum
member added; a payload model registered; validation relaxed | old readers keep working, old data
keeps validating". `MIGRATIONS.md:20` — "**MAJOR** | a field removed or renamed; a type narrowed;
an enum member removed; an optional field made required; the `ids.NAMESPACE` changed". The same
table is restated in the package's source at `version.py:91`–`:95`.

**The divergence ruling, quoted from where the repository states it.** `version.py:1` opens: "Two
version numbers, what each one governs, and why they are not one number." `version.py:7`:
"`SCHEMA_VERSION` is the **wire contract's** version. It is carried in EVERY serialised object".
The heading at `version.py:18` — "WHY THEY MUST BE ALLOWED TO DIVERGE — AND, SINCE 1.1.0, WHY
THAT IS NO LONGER AN ARGUMENT" — introduces the ruling's own account of its weakest moment: while
both numbers read `1.0.0`, "the claim rested on a counterfactual, and any code that derived one
number from the other would have produced the right answer on every run" (`version.py:46`–`:49`).
The supporting measurement is the section listing what landed with no schema change:
`version.py:54`–`:57` says each of its entries "added thousands of lines of shipped behaviour to
this distribution at `schema_version` 1.0.0, with no field added, removed or retyped", and
`version.py:59`–`:60` concludes that had the package been released before any of them, "each would
have been a package MINOR and none of them a schema bump". The count of those entries is
deliberately not restated here: `version.py:56`–`:57` says it "is derived from the section's own
bullets by ``tests/test_cdm_prose_counts.py`` rather than stated here on trust", and this ADR is a
tracked file inside that derivation's own sweep. And `version.py:106`: "A `SCHEMA_VERSION` bump is ALWAYS at least a
package MINOR, because the objects this package emits change shape. The reverse does not hold,
and that is the whole point." `MIGRATIONS.md:52` says the same in the release procedure's words.

`tests/test_cdm_packaging.py:266` sweeps for any code deriving one number from the other.

Readings at this commit, taken rather than carried: `SCHEMA_VERSION = "1.0.0"`
(`version.py:114`), `PACKAGE_VERSION = "1.8.0"` (`version.py:119`).

## Decision

**`SCHEMA_VERSION` moves `1.0.0` → `1.1.0`, as a MINOR, and the move is neither optional nor
avoidable.**

1. **What MINOR means for `SCHEMA_VERSION` here, precisely.** Two optional fields are added and
   nothing else moves: no field is removed, renamed or narrowed, no enum member is removed, no
   optional field becomes required, `ids.NAMESPACE` (`ids.py:28`) does not change. That is
   `MIGRATIONS.md:21`'s first clause exactly, and its stated consequence — "old readers keep
   working, old data keeps validating" — is the property this decision is claiming, in both
   directions. `version.compatible()` (`version.py:127`) accepts a minor from the future within
   the same major, so a 1.0.0 reader keeps reading 1.1.0 objects; and a legacy object written at
   1.0.0 keeps validating against the new models, because both new fields are optional with
   defaults.
2. **The bump is not suppressible.** The alternatives are an unversioned shape change — which is
   the state `version.py:7` exists to make impossible, the version being carried in every
   serialised object — or hiding `oes` inside `Event.payload`, which ADR 0001 refuses on the
   tree's own grounds. There is no third option in which the wire form changes and the number
   does not.
3. **`PACKAGE_VERSION` moves at least MINOR with it**, on `version.py:106` and `MIGRATIONS.md:52`.
   It moves on its own axis, not derived from the schema number: the release round types it, the
   bump-derivation gate reads the signals, and `tests/test_cdm_packaging.py:266` is the guard that
   nothing links the two. Note that the package MINOR list at `version.py:102` enumerates "an
   adapter is added, a harness flag or check is added, a fixture set is added, a new optional
   dependency" and does not literally include "an importable name is added" — so the package bump
   here rests on `version.py:106`'s always-at-least clause and on the new optional test
   dependency, not on a clause about new names. The distinction matters because a round that
   argued the package bump from the wrong clause would be arguing from a sentence that is not
   there.
4. **The `MIGRATIONS.md` entry names the reason, not the change** (`MIGRATIONS.md:36`, step 4:
   "Add an entry below, naming the reason — not just the change"). The reason is that SC-OES
   attaches governed operational-event semantics to the CDM and needs a declared place to put
   them. The entry also records, in its own words, that no migration note in the MAJOR sense is
   owed: nothing is removed, renamed, narrowed or made required, so `MIGRATIONS.md:20` is not
   reached and no coordinated deployment is implied.
5. **All six steps of the procedure at `MIGRATIONS.md:33` apply, and step 5 is the expensive one.**
   Edit the models; bump the constant; re-export the schemas; add the entry naming the reason;
   re-run every shipped adapter's goldens **and read the diffs** — `MIGRATIONS.md:41`: "A golden
   file updated without being read is how a defect becomes the expectation"; and close any
   `FORMAT_COVERAGE.md` gap the change closes, which is none (ADR 0001 keeps gap 12 open
   deliberately).
6. **Step 5 is discharged by a structural diff by JSON path, written and run before the goldens
   are committed.** The assertion: across every changed golden file, the set of JSON paths whose
   value moved is exactly `{schema_version, ontology_types, oes}`, and no other path's value
   changed. Anything else in the diff is a defect, not churn.

## Alternatives considered

**A — do not bump; treat the additions as invisible because they are optional.** Rejected by
`version.py:7`: the version is carried in every serialised object precisely so that a consumer can
tell which shape it is holding. An unversioned shape change makes `compatible()` answer a question
about a contract that has silently moved.

**B — make it a MAJOR bump, on the ground that the mass fixture change is large.** Rejected: the
size of the golden diff is a property of how the version string is serialised, not of the
compatibility consequence. `MIGRATIONS.md:20`'s MAJOR row lists what breaks readers, and none of
it happens here. A MAJOR would additionally imply a coordinated deployment (`MIGRATIONS.md:20`'s
own consequence column) that nothing requires.

**C — avoid the bump by putting SC-OES in `Event.payload`.** ADR 0001's alternative B, refused
there on `models.py:329` and `models.py:18`. Named again here because "it avoids the bump" is its
strongest argument, and it is not strong enough: it trades a versioned, schema-visible contract
for an unversioned one hidden from the published schema, which defeats §104's offline validation.

**D — bump `SCHEMA_VERSION` but leave the goldens at 1.0.0.** Rejected mechanically:
`models.py:193` defaults `schema_version` to `SCHEMA_VERSION`, `harness.py:144` dumps with no
`exclude_none`, and `tests/test_cdm_schemas.py:22` fails the build when the published schemas
differ from the models. There is no configuration in which the goldens keep the old string and the
harness reports green.

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
  moving; a new `"ontology_types": []` line inside an object whose `object_kind` is `entity`; a
  new `"oes": null` line inside an object whose `object_kind` is `event`. `harness.py:402` renders
  with `sort_keys=True`, so `oes` sorts between `object_kind` and `payload` and `ontology_types`
  between `object_kind` and `position`; no existing line moves position within a file beyond those
  insertions.
- **The nine that do not change are the answer to §138.** They are the three egress adapters'
  external-format outputs — `fixtures/adsb/egress/golden/*.adsb`,
  `fixtures/ais/egress/golden/*.ais.nmea` and `fixtures/tak/egress/golden/*.cot.xml`. Not one byte
  of any non-CDM wire format moves.
- **Six published schema documents are regenerated**, and every `$id` moves, because
  `SCHEMA_VERSION` is a segment of it (`schemas.py:76`). `schemas.py:62` records that a `$id` is a
  consumer-visible identifier; here it moves as the version moves, which is what the version
  segment is for, and no `$ref` crosses a file, so nothing dangles.
- **`tests/test_cdm_packaging.py:313` goes red the moment the constant moves.** It asserts the
  literal pair `(PACKAGE_VERSION, SCHEMA_VERSION) == ("1.8.0", "1.0.0")`, and its own message says
  the fix is to re-pin and not to re-link. A round that meets it should not treat it as a surprise.
- **`version.py`'s prose needs care.** Its divergence section is written around the moment
  `PACKAGE_VERSION` reached 1.1.0 while `SCHEMA_VERSION` stayed at 1.0.0. Once `SCHEMA_VERSION`
  itself reads 1.1.0, a reader meets that number in two roles in one file; the section should say
  which is which rather than leave it to inference. The two numbers stay unequal — 1.1.0 against a
  package version at 1.8.0 or beyond — so the ruling's substance is unaffected and
  `tests/test_cdm_packaging.py:266` is untroubled.
- The `docs/docs/schema-reference/` pages are generated from `/schemas` and must be regenerated
  and committed in the same change. That drift check is a node script run by the documentation
  site's own CI target, not by `pytest`, so a round that regenerates schemas and runs only the
  Python suite leaves those pages stale and green.

## Compatibility impact

This is the section §138's acceptance criterion reads.

- **Forward:** a 1.0.0 consumer receiving 1.1.0 objects is accepted by `compatible()`
  (`version.py:127`) — same major, minor from the future — and the two new keys are optional
  additions it may ignore.
- **Backward:** a 1.0.0 object validates against the 1.1.0 models unchanged; `oes` defaults to
  `None` and `ontology_types` to `[]`.
- **Existing adapters:** every one of the fourteen keeps operating with no change to its
  translation. None sets either new field; the nine external-format goldens prove the egress side
  byte-for-byte.
- **Nothing is removed or narrowed**, so `MIGRATIONS.md:20` is not reached and no migration note
  in the MAJOR sense is owed.

§121 says dozens of unrelated golden changes are a design problem and §138 forbids *unexplained*
mass golden changes. This churn is neither unrelated nor unexplained: it is one version bump and
two field additions in one release, and the JSON-path diff of decision 6 converts "explained" from
a claim into a check.

## Security impact

- **No security surface moves.** Two optional metadata fields are added; no validation is relaxed
  in the sense `MIGRATIONS.md:21`'s last clause means, no type is widened, and
  `tests/test_cdm_schemas.py:63`'s `additionalProperties: false` on the four kinds is unaffected —
  the new fields are declared, which is what makes them expressible at all.
- **The golden diff is the security-relevant artefact of this decision.** A mass mechanical change
  is exactly the diff a reviewer skims, and a substantive change hidden inside it would pass. That
  is why decision 6 makes the diff machine-checked by JSON path rather than read by eye:
  `MIGRATIONS.md:41`'s rule, enforced rather than remembered.
- **The version string itself carries no data about a source**, so no marking, provenance or
  synthetic/live distinction is affected by the bump.
- **Schema `$id`s moving is a consumer-registration event, not a trust event.** No `$ref` in these
  documents crosses a file (`schemas.py:36`), so no identifier is resolved at validation time and
  no fetch is invited — the property `schemas.py:38`–`:43` rules for.

## Reversibility

Low after release, high before it, and the asymmetry is the whole reason this ADR exists ahead of
the implementation.

Before the release that carries it, reverting is: restore the constant, regenerate the schemas,
regenerate the goldens, re-pin `tests/test_cdm_packaging.py:313`. All mechanical.

After release, the number cannot go backwards — a published `schema_version` is on objects in
consumers' stores, and every `$id` minted at 1.1.0 is registered somewhere. The fields themselves
remain deprecable under ADR 0001's reversibility, but the version move is permanent. That is
ordinary for a version and is not a defect; it is stated here so the decision is taken once,
deliberately, rather than discovered during Phase 7.
