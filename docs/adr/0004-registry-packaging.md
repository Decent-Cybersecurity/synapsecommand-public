# ADR 0004 — Registry packaging

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

## Context

§16 fixes the runtime registry's location and forbids one alternative by name: "Do not package
the runtime registry under a package directory called `spec`. Use
`packages/cdm/synapse_cdm/registry/sc_oes/`." §18 says there are two artefacts there, not one —
`event_types.json`, "the governed machine-readable event contract", and `ontology_terms.json`,
the generated lookup ADR 0002 owns. §17 states what packaging them has to achieve: ship in the
wheel; be loadable with `importlib.resources`; require no repository checkout; require no
network; be "treated as data, never executed as code". §125 requires validation to work offline.
§126 exposes seven helpers over the two registries and asks that consumers not be made to depend
on internal packaged file paths, and ADR 0003 makes both registries load-bearing for refusing
impersonated identifiers.

So the registries must be readable at runtime from an installed wheel, with no repository checkout
and no network.

**§16 also settles a word collision this repository was going to have, and its resolution is a
three-way distinction rather than a two-way one.**

- `packages/cdm/synapse_cdm/registry/sc_oes/` — machine-readable runtime artefacts, shipped.
- `/spec/` at the repository root — "human-readable normative documents", §117's tree, not
  shipped.
- `packages/cdm/synapse_cdm/fixtures/*/spec/` — "third-party pinned specification records",
  §16's third concept, never shipped and not part of the Work.

§16's closing sentence is the requirement: "These three concepts must remain visibly distinct."

**The packaging gate is what makes the location a decision rather than a preference.**
`tests/test_cdm_packaging.py:117` asserts equality **in both directions** between what
`git ls-files` tracks under the package and what the setuptools configuration would ship. The
shipping side is `packages.find` for `.py` inside a package, plus `package-data` minus
`exclude-package-data`, and `packages/cdm/pyproject.toml:165`–`:167` declares `package-data` as
exactly two globs: `fixtures/**/*` and `*.md`.

- A file at the repository root, `spec/sc-oes/event-types.json`, is outside `packages/cdm/`
  entirely. It can never be in the wheel, so runtime validation would need a checkout — which
  §125 forbids.
- A tracked file at `packages/cdm/synapse_cdm/registry/sc_oes/event_types.json` matches neither
  glob and is not a `.py` in a package, so the closure test fails in its `missing` direction: a
  tracked file that would not be in the built distribution. That direction's message names the
  defect it was written for — the wheel once short by 72 raw ASTERIX data blocks while the harness
  reported green against it, "because the parsed twins were there".

The second of those is the one this ADR has to repair, and §17 says how: "Update package-data
patterns using repository conventions. Do not modify exclusions in a way that makes pinned
third-party standards shippable."

`NOTICE:55` is why that second sentence is not a formality: the specification documents this
repository pins "are not part of the Work and are not covered by this licence", and thirty
documents are pinned under `fixtures/*/spec/`.

## Decision

**Both registries ship, at §16's path, reached by a third `package-data` glob keyed on that path;
the exclusions are not touched; the three meanings of "spec" are written down.**

1. **`packages/cdm/synapse_cdm/registry/sc_oes/` holds `event_types.json` and
   `ontology_terms.json`**, exactly as §16 and §18 name them. They are loaded through
   `importlib.resources`, in the manner `adapter.fixture_root()` (`adapter.py:231`) already
   resolves packaged data, so they resolve from an installed distribution and not from a
   repository path — §17's third and fourth conditions.
2. **The repair is a widened glob keyed on `registry/`, not an extension list.**
   `packages/cdm/pyproject.toml:154` records at length why the include rule stopped being a
   hand-written list of extensions: "the list still went stale twice, silently, in the way an
   enumeration does". `tests/test_cdm_packaging.py:126` says the same in one line: "Widen the
   package-data glob — do not add an extension to a list." The glob added is `registry/**/*`.
3. **The exclusions are not touched, and the reason is a trap worth naming.**
   `packages/cdm/pyproject.toml:192`–`:196` lists four positive exclusions, all keyed on
   `fixtures/*/spec/`. §17 forbids modifying them in a way that makes pinned standards shippable,
   and the concrete trap is a *future* widening: a glob reaching for `**/spec/**` would confuse
   the pinned-document `spec/` with a package `spec/` and could stop excluding. This ADR's chosen
   path removes the collision at the source by not using the word `spec` inside the package at
   all — which is precisely why §16 forbids it.
4. **`test_no_specification_document_is_shippable` asserts the result rather than the pattern**,
   and the comment at `packages/cdm/pyproject.toml:186`–`:191` records why that matters: a round
   that enumerates the gates which *recognise* a pin leaves every *excluder* untouched. The
   round that widens the glob re-derives the closure in both directions after the change.
5. **The root `spec/` tree holds the normative documents**, §117's structure taken as given:
   `spec/sc-oes/` with its sixteen numbered documents and seven profiles, and `spec/governance/`
   with §118's six. It ships nothing and is repository-only. §117's own closing rule binds here:
   "Machine event registry is packaged separately under `synapse_cdm/registry/sc_oes/`. Do not
   maintain two hand-authored copies."
6. **The three meanings are written down where a reader meets them** (§16's "visibly distinct"),
   in `spec/sc-oes/README.md` and in `NOTICE`'s neighbourhood: a root `spec/` holds normative
   documents this project owns; `fixtures/*/spec/` holds pin records for third-party standards it
   does not; `synapse_cdm/registry/sc_oes/` holds the machine-readable runtime artefacts. No
   fourth word is invented, and the word `spec` never names a directory inside the package.
7. **Consumers reach the registries through §126's helpers, not through paths.** §126: "Avoid
   requiring consumers to depend on internal packaged file paths." `get_event_type`,
   `list_event_types`, `get_profile_event_types`, `get_legacy_event_type`,
   `is_governed_ontology_term`, `get_ontology_term` and `list_ontology_terms` are the surface;
   the path is an implementation detail the helpers exist to keep movable.
8. **Data, never code.** §17's last condition. Both files are parsed as JSON and validated against
   their own declared shape; nothing in either is evaluated, imported or `eval`'d.

## Alternatives considered

**A — put the registries under `fixtures/`, where `fixtures/**/*` already ships them.** Cheapest:
no `pyproject.toml` change, no gate to satisfy, the files arrive in the wheel today. Rejected on
meaning. `fixtures/` is verification data — synthetic inputs and their goldens, judged by the
harness — and a normative registry is not a fixture. The cost of the mistake is not a failing
test; it is that the governed event contract would live in the directory this repository reserves
for material that exists to be *tested against*. §16 also names the path, and it is not this one.

**B — `packages/cdm/synapse_cdm/spec/sc-oes/event-types.json`**, the repair this ADR proposed
while it was `Proposed`. **Rejected by §16 in as many words**: "Do not package the runtime
registry under a package directory called `spec`." The proposed text argued the collision was
survivable because the paths differ and the exclusions are keyed on `fixtures/*/spec/`; §16's
ruling is that a survivable collision is still a collision, and decision 3 records the concrete
mechanism by which it would eventually stop being survivable. The file names change with the
path: `event-types.json` becomes `event_types.json`, per §16 and §18.

**C — leave the registry at the repository root and read it from there.** Rejected by §125 and by
the packaging closure together: an installed wheel has no repository root to read.

**D — embed the registries as Python literals in a module.** They would ship automatically, being
`.py` in a package. Rejected by §17's "treated as data, never executed as code", and because a
Python literal is readable only by Python — which defeats the same non-Python consumer §125 is
about. It would also make a registry entry a code change rather than a data change, contradicting
§119's governed proposal process.

**E — one combined `sc_oes.json` holding both registries.** Fewer files, one loader. Rejected by
§18, which names two artefacts with different authorities: `event_types.json` is hand-authored
under §119's process, `ontology_terms.json` is generated from the Turtle and drift-tested (ADR
0002). Combining them would put a generated artefact and a governed one in one file, where a
regeneration rewrites something a proposal process owns.

## Consequences

- `packages/cdm/pyproject.toml`'s `package-data` gains a third glob.
  `tests/test_cdm_packaging.py:117`'s closure must be re-derived after the change, in both
  directions — the `extra` direction is the one that catches a glob widened too far, and its
  message is explicit that shipping a pinned document inside an Apache-2.0 wheel "is a licensing
  defect, not an oversight".
- `gates/wheel_install.py`'s checks continue to apply unchanged; `check_manifest` and
  `check_resources` are the two that would catch a registry declared and not delivered.
- A test module that loads a registry from the **installed package** is package-only and joins
  `PACKAGE_ONLY_TESTS` (`gates/wheel_install.py:93`); one that reads the root `spec/` tree or
  `ontology/` is repository-bound and joins `REPO_BOUND_TESTS` (`:144`). `check_slice_closure`
  (`:521`) fails on a module in neither.
- A registry's own shape may be published as a JSON Schema for non-Python consumers (§134's "Add
  any required schemas for … registry structure"), which is an entry in `schemas.generate()`
  (`schemas.py:81`) and arrives with a `$id` in the ruled URN form automatically
  (`schemas.py:76`) — the legacy family of ADR 0003 decision 4, which is correct for a schema
  `$id` and is not the ontology family.
- **No directory inside the package is called `spec` after this decision**, which is the property
  §16 is protecting and is cheaper to hold than to restore.

## Compatibility impact

None to the wire contract; this decision adds no field to any canonical model.

The distribution grows by the two registries. That is a package-version consequence, not a schema
one: `version.py:102` makes a fixture set added a package MINOR, and a shipped data artefact is
the same kind of change. It is subordinate to ADR 0005's bump in any case.

Consumers gain two packaged files they may read directly. Decision 7 is what keeps that from
becoming a commitment: the §126 helpers exist so that the path can move without a consumer
noticing, and documentation and examples should use them from the first release rather than
showing a path. A consumer that reads by path anyway has taken a dependency this ADR declines to
promise.

## Security impact

- **Offline enforcement is the point.** Because both registries ship, refusing an impersonated
  `sc.*` type identifier or an impersonated governed ontology term (ADR 0003, §127's
  "reserved-namespace impersonation") needs no network and no service, which is what §125
  requires.
- **No pinned third-party document moves.** The exclusions at
  `packages/cdm/pyproject.toml:192`–`:196` stay keyed on `fixtures/*/spec/`, and
  `test_no_specification_document_is_shippable` asserts the result. The licensing boundary
  `NOTICE:55` draws is untouched, and §17's "do not modify exclusions in a way that makes pinned
  third-party standards shippable" is satisfied by not modifying them at all.
- **The registries are data the package reads, not code it executes** (§17). They are parsed as
  JSON and validated against their own shape; nothing in either is evaluated.
- **A widened glob is a licensing surface.** The `extra` direction of the closure test is the
  control, and it is derived rather than declared, so it cannot go stale in the direction that
  matters. `packages/cdm/pyproject.toml:139`–`:144` records the near-miss this control exists for:
  the old include list was "one glob away from redistributing a NATO standard under Apache-2.0".

## Reversibility

High on the mechanism, moderate on the path.

Reverting the glob and moving the files is a small change while nothing depends on the location.
Once the wheel ships with the registries at a path, consumers may read them there — and decision 7
is the mitigation, not a guarantee. The path is fixed by §16 rather than chosen here, so the
question a later round faces is not "where should this live" but "may we move what §16 named",
which is a specification change and not a packaging one.

The three-way naming distinction (decision 6) is reversible only before the normative tree is
written and cross-referenced, which is round SB. That is why it is recorded here in full rather
than left to the round that writes the documents.
