# ADR 0004 — Registry packaging

## Status

Proposed — awaiting M's review.

## Context

§31 requires a machine-readable registry of governed event types, treated as an executable
specification artifact that tests load and validate, and states a preferred source:
`spec/sc-oes/event-types.json`. §123 gives the decision principle: "If runtime validation
requires an artifact, package it", and lists the event registry first among the artifacts that
may need packaging. §104 requires validation to work offline. §103 exposes four helpers over the
registry, and ADR 0003 makes the registry load-bearing for refusing `sc.*` identifiers from
producers that do not own them.

So the registry must be readable at runtime from an installed wheel, with no repository checkout
and no network.

**The specification's preferred location cannot satisfy that, and neither can the obvious repair
of putting it under `synapse_cdm/spec/`. Both are refused by the same gate, from opposite sides.**

`tests/test_cdm_packaging.py:117` asserts equality **in both directions** between what
`git ls-files` tracks under the package and what the setuptools configuration would ship. The
shipping side is `packages.find` for `.py` inside a package, plus `package-data` minus
`exclude-package-data`, and `packages/cdm/pyproject.toml:164` declares `package-data` as exactly
two globs: `fixtures/**/*` and `*.md`.

- A file at the repository root, `spec/sc-oes/event-types.json`, is outside `packages/cdm/`
  entirely. It can never be in the wheel, so runtime validation would need a checkout — which
  §104 forbids.
- A tracked file at `packages/cdm/synapse_cdm/spec/sc-oes/event-types.json` matches neither glob
  and is not a `.py` in a package, so the closure test fails in its `missing` direction: a tracked
  file that would not be in the built distribution. That direction's message names the defect it
  was written for — the wheel once short by 72 raw ASTERIX data blocks while the harness reported
  green against it, "because the parsed twins were there".

There is a second, non-mechanical collision. **`spec/` already means something else here.**
`NOTICE:55` states that the specification documents this repository pins "are not part of the Work
and are not covered by this licence", and points at the pin records under
`packages/cdm/synapse_cdm/fixtures/*/spec/`. Thirty documents are pinned there. In this tree
`spec/` has meant "third-party standards this repository does not own and does not redistribute"
since before publication, and `packages/cdm/pyproject.toml:170`'s exclusions are keyed on that
path.

## Decision

**Widen `package-data` with a third glob and put the registry inside the package, at
`packages/cdm/synapse_cdm/spec/sc-oes/event-types.json`; keep the root `spec/` tree for the
human-readable normative documents; state the two meanings of the word explicitly.**

1. **The machine-readable registry ships in the wheel.** It is loaded through
   `importlib.resources`, in the manner `adapter.fixture_root()` (`adapter.py:231`) already
   resolves packaged data, so it resolves from an installed distribution and not from a
   repository path.
2. **The repair is a widened glob, not an extension list.** `packages/cdm/pyproject.toml:141`
   records at length why: the include rule used to be a hand-written list of extensions, "every
   argument in those paragraphs was right and the list still went stale twice, silently, in the
   way an enumeration does". The closure test's own message says the same in one line: "Widen the
   package-data glob — do not add an extension to a list."
3. **The exclusions are not touched.** `packages/cdm/pyproject.toml:170`'s
   `exclude-package-data` is keyed on `fixtures/*/spec/**`, a different `spec/` from the new one,
   and `test_no_specification_document_is_shippable` asserts the *result* rather than the pattern.
   A future widening reaching for `**/spec/**` would confuse the two, and this ADR records that
   as the trap it is.
4. **The root `spec/` tree holds the normative documents** — `spec/sc-oes/` and
   `spec/governance/`, §90's structure taken as given. It ships nothing and is repository-only,
   which §123 permits for material runtime validation does not require.
5. **The distinction is written down where a reader meets it**, in `spec/sc-oes/README.md` and in
   `NOTICE`'s neighbourhood: a root `spec/` holds documents this project owns; a
   `fixtures/*/spec/` holds pin records for third-party standards it does not. No third word is
   invented.
6. **One authoritative copy.** §123's "Avoid duplicate authoritative copies" is met by the
   registry being the single machine-readable authority for governed event types; the normative
   documents describe, and the ontology (ADR 0002) supplies the vocabulary the registry's
   `ontology_class` field points at.

## Alternatives considered

**A — put the registry under `fixtures/`, where `fixtures/**/*` already ships it.** Cheapest: no
`pyproject.toml` change, no gate to satisfy, the file arrives in the wheel today. Rejected on
meaning. `fixtures/` is verification data — synthetic inputs and their goldens, judged by the
harness — and a normative registry is not a fixture. The cost of the mistake is not a failing
test; it is that the artefact the specification calls "an executable specification artifact" would
live in the directory this repository reserves for material that exists to be *tested against*.

**B — leave the registry at the repository root as §31 prefers, and read it from there.**
Rejected by §104 and by the packaging closure together: an installed wheel has no repository root
to read. §31's word is "preferred", and §90's own closing sentence — "Use repository conventions
if they make another structure materially better" — grants the move.

**C — root `spec/` renamed to `sc-oes/` to avoid the word collision entirely.** A real option, and
the one to take if M judges the collision too sharp: the paths differ today
(`fixtures/*/spec/` versus a root `spec/`), every existing gate is keyed on the former, and the
two can coexist — but they coexist because nothing has yet widened a glob across them. Not chosen,
because §90 states the structure and inverting it costs every cross-reference in the specification
tree; recorded as the named fallback.

**D — embed the registry as a Python literal in a module.** It would ship automatically, being a
`.py` in a package. Rejected: §31 requires a machine-readable artifact that tests load and
validate, and a Python literal is readable only by Python — which defeats the same non-Python
consumer §122 and §104 are about. It would also make the registry a code change rather than a
data change, contradicting §93's governed proposal process.

## Consequences

- `packages/cdm/pyproject.toml`'s `package-data` gains a third glob.
  `tests/test_cdm_packaging.py:117`'s closure must be re-derived after the change, in both
  directions — the `extra` direction is the one that catches a glob widened too far, and its
  message is explicit that shipping a pinned document inside an Apache-2.0 wheel "is a licensing
  defect, not an oversight".
- `gates/wheel_install.py`'s checks continue to apply unchanged; `check_manifest` and
  `check_resources` are the two that would catch a registry declared and not delivered.
- A test module that loads the registry from the **installed package** is package-only and joins
  `PACKAGE_ONLY_TESTS` (`gates/wheel_install.py:93`); one that reads the root `spec/` tree is
  repository-bound and joins `REPO_BOUND_TESTS` (`:144`). `check_slice_closure` (`:521`) fails on
  a module in neither.
- The registry's own shape may be published as a JSON Schema for non-Python consumers (§122),
  which is an entry in `schemas.generate()` (`schemas.py:81`) and arrives with a `$id` in the
  ruled URN form automatically (`schemas.py:76`).
- Two directories in this repository are called `spec`, deliberately, with the difference stated.

## Compatibility impact

None to the wire contract; this decision adds no field to any canonical model.

The distribution grows by the registry and by whatever else §123's principle later pulls in. That
is a package-version consequence, not a schema one: `version.py:102` makes a fixture set added a
package MINOR, and a shipped data artefact is the same kind of change.

Consumers gain a packaged file they may read directly. Its path therefore becomes part of the
package's surface, and moving it later is a package-MAJOR-shaped change under `version.py:99` if
consumers read it by path rather than through the §103 helpers. The helpers exist so that they
need not.

## Security impact

- **Offline enforcement is the point.** Because the registry ships, refusing an unauthorised
  `sc.*` identifier (ADR 0003) needs no network and no service, which is what §104 requires and
  what §103's "Do not create an online registry service" forbids the alternative of.
- **No pinned third-party document moves.** The exclusions at
  `packages/cdm/pyproject.toml:170` stay keyed on `fixtures/*/spec/**`, and
  `test_no_specification_document_is_shippable` asserts the result. The licensing boundary
  `NOTICE:55` draws is untouched by this decision, and decision 3 records why a future glob
  widening is the way it could be broken.
- **The registry is data the package reads, not code it executes.** It is parsed as JSON and
  validated against its own shape; nothing in it is evaluated.
- **A widened glob is a licensing surface.** The `extra` direction of the closure test is the
  control, and it is derived rather than declared, so it cannot go stale in the direction that
  matters.

## Reversibility

High on the mechanism, low on the path.

Reverting the glob and moving the file is a small change while nothing depends on the location.
Once the wheel ships with the registry at a path, consumers may read it there, and the §103
helpers are what let a later move be an internal detail — which is the reason to prefer them in
documentation and examples from the first release.

The root `spec/` naming decision (alternative C) is reversible only before the normative tree is
written and cross-referenced; that is why it is put to M now rather than at Phase 4.
