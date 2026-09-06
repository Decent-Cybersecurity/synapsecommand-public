# ADR 0009 — Conformance model

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

## Context

§34 retains five separately reportable dimensions — **A** CDM Conformance, **B** SC-OES Core
Syntax, **C** SC-OES Semantic Type, **D** SC-OES Profile, **E** Ontology Conformance — with the
vocabulary `PASS` / `FAIL` / `SKIP`, and two prohibitions: "`SKIP` is never displayed as `PASS`.
Do not produce a single 'compatibility score'."

§35–§39 fix what each dimension checks. §40 adds what v2 requires beyond the proposed design: a
CI-meaningful process status, with four codes and a required-dimension mechanism. §41 fixes the
output: a readable table and a machine-readable JSON report whose "output must contain named
dimensions, not positional columns". §125 requires all of it offline.

**The repository's validation philosophy is already exactly this shape, and it argued for it.**
`harness.py:473` declares `_COLUMNS = ("translate", "schema", "provenance", "lossless",
"roundtrip", "golden")` — one column per property rather than one verdict per fixture — and
`harness.py:230`–`:231` states the rule that makes such a report honest: a check that did not run
is "Reported as SKIP — never PASS … An unrun check that reads as passed is how a capability nobody
tested acquires a green tick."

The CLI pattern is there too, and so is a piece of §40's answer. `harness.py:534` offers `--json`
beside the rendered table. Exit codes are module constants: `harness.py:99` declares
`EXIT_NO_FIXTURES = 2`, and its comment records that the name is kept for the case "every gate
sweep is written against". `harness.py:588` returns `1 if report["failed"] else 0`. So the
repository already spends `0` on success, `1` on a substantive failure and `2` on a usage-shaped
condition — which is §40's first three codes in the same order, arrived at independently.

**Offline is already true rather than aspirational.** `packages/cdm/pyproject.toml:74` declares
two runtime dependencies; `adapter.fixture_root()` (`adapter.py:231`) resolves packaged data
through `importlib.resources` rather than through a repository path; `schemas.generate()`
(`schemas.py:81`) produces the schemas from the models with no file and no network. Nothing in the
validation path reaches out today, and §125 requires that it stay so.

## Decision

**Five separately reportable dimensions, one column each, `PASS` / `FAIL` / `SKIP`, never a single
flag — plus §40's four exit codes and a required-dimension mechanism, so the tool is useful to CI
without collapsing the report.**

1. **The five columns are §34's five dimensions**, reported per subject with no aggregate verdict.
   A caller that wants one composes it from the five and says so; the tool does not compose it for
   them, because that is the "compatibility score" §34 forbids.
2. **`SKIP` is not `PASS`, and it is the load-bearing rule.** §34 says so and `harness.py:230`'s
   sentence is the repository's own version. Concretely: dimension D is `SKIP` when the caller
   names no profile (§38); dimension E is `SKIP` when no ontology identifiers occur (§39);
   dimension C is `SKIP` for a syntactically valid unknown `x.*` event (§37), "because the
   repository does not govern that third-party semantic contract".
3. **What each dimension asserts**, taken from §35–§39 so that nothing is invented and nothing is
   homeless:
   - **A — CDM conformance** (§35). Canonical model validity, required fields, schema version,
     canonical schema validity, existing CDM invariants. "No SC-OES-specific interpretation."
   - **B — SC-OES core syntax** (§36). The `oes` structure; supported SC-OES version; EventClass;
     lifecycle; verification; confidence bounds; temporal ordering; type identifier syntax;
     relation structure; entity relation structure; evidence structure; security-marking
     structure; extension namespace; extension nesting bound. "No semantic event-type
     interpretation beyond core syntax" — and no dimension asserts anything about the *value* of
     an evidence hash (ADR 0006, §84).
   - **C — semantic type conformance** (§37). For governed `sc.*` events: the type exists in the
     packaged event registry; `EventClass` matches the registry; the ontology event class matches
     the registry; a registered payload model validates where one exists; a non-null
     `legacy_event_type` matches (ADR 0007). For a valid unknown `x.*`, `C = SKIP`. **For an
     unknown `sc.*`, `C = FAIL`** — this is where §14's namespace reservation is enforced, and the
     message says so.
   - **D — profile conformance** (§38). Checked against the profile the caller explicitly names —
     `PNT`, `Air`, `Logistics` and the rest. `SKIP` when none is requested, and §38's closing rule
     is binding: "Do not infer which profile the producer 'probably meant'."
   - **E — ontology conformance** (§39). `SKIP` when no ontology identifiers occur. For governed
     SynapseCommand ontology IDs: syntax valid, and the term present in the packaged generated
     ontology-term registry (ADR 0002, ADR 0004). **An unknown identifier in the reserved
     `tag:synapsecommand.com,2026:ontology:` family is `FAIL`.** A valid third-party absolute
     semantic identifier is preserved, not governed, and reported in detailed output as
     `UNASSESSED_THIRD_PARTY_TERM` — never converted into a guessed SynapseCommand class. Syntax
     and lookup only; no reasoning (§100, ADR 0002).
4. **Exit codes, per §40, using this repository's constant-per-code convention.** The
   multidimensional report remains authoritative; the process status is for CI.
   - `0` — the run completed and no requested dimension `FAIL`ed.
   - `1` — one or more requested dimensions `FAIL`ed.
   - `2` — CLI / configuration / usage error.
   - `3` — internal execution error.
   They are module constants in the manner of `harness.py:99`, not literals scattered through
   `main`, and the first three agree with what the harness already spends `0`, `1` and `2` on
   (`harness.py:588`, `harness.py:99`) — so a caller who knows one tool's codes is not surprised
   by the other's.
5. **`SKIP` does not fail the process by default, and a required-dimension mechanism is provided.**
   §40: support something "conceptually equivalent to `--require A,B,C`", and "if a required
   dimension is `SKIP`, the run is unsuccessful." So the exit code answers a question the caller
   asked — *did the dimensions I required come back `PASS`?* — while the report still says what
   every dimension did. §40 leaves the spelling to repository convention, and the repository's
   convention is `argparse` long options with a one-line help string (`harness.py:532`–`:534`).
6. **Two outputs, and the machine one is keyed by name** (§41). A rendered table for a person, in
   the shape `render_report` (`harness.py:476`) already produces, and a JSON report for a machine,
   in the shape `--json` (`harness.py:534`) already offers. §41 is explicit about the JSON: "named
   dimensions, not positional columns. Consumers should key on `A` `B` `C` `D` `E` or descriptive
   stable names." The report is emitted as a mapping for that reason, and a sixth dimension could
   not silently shift a fifth column's meaning.
7. **Offline, and asserted rather than promised.** The conformance path imports nothing outside
   the two runtime dependencies, reads both registries through `importlib.resources`, and opens no
   socket. A test asserts the import closure, in the manner `tests/test_cdm_boundary.py` already
   asserts the crypto and consumer-import boundaries, and §143 requires exactly that preservation.
8. **Terminology.** Output uses §45's permitted forms — "SC-OES Conformant", "SC-OES PNT Profile
   Conformant" — and never "SC-OES Certified", "Official SynapseCommand Partner", "Approved by
   Decent Cybersecurity", "NATO Certified", "NATO Approved" or "NATO Standard". ADR 0010 carries
   the trademark reasoning and the sweep.

**The v0.1 profile reality, stated so the report does not overclaim.** §115 makes PNTMAP the
reference producer and §114 rules the rest: "PNT is the initial reference producer-backed profile
through PNTMAP. The remaining profiles may be specification-only in 0.1.0. State this explicitly.
Do not imply an operational adapter implementation exists where one does not." This repository
already has a name for that state: `MIGRATIONS.md:8026` is a section headed "Row sets written as
specifications, with no adapter code yet", and a profile with no producer is that state one layer
up. Dimension D is claimable against PNT and declarable-but-unexercised against the other six, and
the profile documents say so rather than implying an implementation.

## Alternatives considered

**A — one boolean "SC-OES compatible".** Rejected by §34's "Do not produce a single 'compatibility
score'", and independently by `harness.py:230`'s reasoning: a single flag has to decide what an
unrun check contributes, and every answer is wrong — counting it as a pass gives a green tick to
an untested capability, and counting it as a failure makes a partial implementation
indistinguishable from a broken one.

**B — a weighted score or a conformance level (bronze/silver/gold).** Rejected: a level is a flag
with more values, and it makes the interesting question — *which* dimension failed — unanswerable
from the result. It also invites the certification language §45 forbids.

**C — fail the process whenever any dimension fails, requested or not.** Rejected by §40, which
scopes the exit code to *requested* dimensions: `1` is "one or more **requested** dimensions
FAILed". A tool that failed CI on a dimension the caller did not ask about would make `SKIP`
expensive and push callers towards not running dimensions at all. **This is a change from the
proposed design**, which had no exit-code contract beyond "the exit code reports whether the run
completed"; §40 makes the process status carry a real answer, and decision 5 is how it does so
without collapsing the report.

**D — a hosted conformance service.** Rejected by §125 and by §126's preference for local helpers.
Offline is a property of the artefact, not a deployment choice.

**E — infer profile conformance from the data rather than requiring the caller to name a
profile.** Tempting, because it removes an argument. Rejected by §38 in as many words — "Do not
infer which profile the producer 'probably meant'" — and on principle: guessing which profile a
producer meant, and then reporting conformance to it, is the tool making an assessment out of an
observation (§62). The `SKIP` rule exists so that "not asked" has an honest answer.

**F — positional columns in the JSON report, matching the rendered table.** Rejected by §41. A
positional report is one whose meaning changes when the dimension set changes, and the dimension
set is the thing most likely to grow.

## Consequences

- A conformance module in the package plus a CLI entry point, and new test modules for §137–§143.
  A module that runs against the installed wheel is package-only (`gates/wheel_install.py:93`);
  one reading `ontology/` or the root `spec/` tree is repository-bound (`:144`);
  `check_slice_closure` (`:521`) fails on a module in neither list, by name.
- **A console entry point is a MINOR signal the bump gate reads by name**
  (`gates/bump_derivation.py:73`, "a console entry point appears"), and the exit-code constants
  are another (`:68`). Both are subordinate to ADR 0005's MAJOR, and neither should surprise the
  round that reads the gate's output.
- Both registries become load-bearing for dimensions C and E, which is a further reason they must
  ship (ADR 0004).
- Five columns is a number stated in tool output and in documentation; it is derived from the
  dimension list in the code rather than written as a literal, so that a sixth dimension cannot
  arrive while the prose still says five.
- Dimension D is `SKIP` for six of the seven profiles in v0.1 by construction, and that is
  reported rather than hidden (§114).
- `UNASSESSED_THIRD_PARTY_TERM` is a stable string in the detailed output (§39), so it is part of
  the report's surface and moving it later is a consumer-visible change.

## Compatibility impact

- **No effect on the wire contract.** This ADR adds no field and changes no model; dimension A is
  the existing CDM rules unchanged.
- **Additive to the package surface**: new importable names, a new CLI entry point and new exit
  codes. Under `gates/bump_derivation.py:91`–`:93`'s rule of shape an unambiguous addition of a
  declared surface is MINOR, and in this campaign it is subordinate to ADR 0005's MAJOR.
- **An object that conforms today keeps conforming.** Dimensions B–E are `SKIP` for an object
  carrying no `oes` block, so every existing adapter's output is unaffected by the model's
  existence — which is the mechanical form of §116's "Existing adapters remain CDM Conformant
  without necessarily being SC-OES semantic producers."
- **Adding a dimension later would be a report-shape change** for anything parsing the JSON. The
  five are fixed by §34, so the shape is expected to be stable; §41 requires consumers to key on
  names rather than positions, and decision 6 emits a mapping so that they can.
- **Adding an exit code later is the risky direction**, because CI configurations branch on the
  ones they know. The four in decision 4 are §40's complete set and are introduced together.

## Security impact

- **The honest-report property is the security property.** A conformance claim is something a
  buyer or an integrator relies on. `harness.py:231`'s sentence — an unrun check that reads as
  passed is how a capability nobody tested acquires a green tick — is the failure mode this
  decision is built to avoid, and it is why `SKIP` is not `PASS` and why decision 5 makes a
  required-but-skipped dimension unsuccessful rather than quietly green.
- **Dimensions C and E are namespace enforcement**, and §127 names the threat: "reserved-namespace
  impersonation" and "malicious third-party ontology terms". An `sc.*` type identifier or a
  `tag:synapsecommand.com,2026:ontology:` term that this project did not govern is caught offline,
  by a consumer, without asking anybody.
- **A third-party term is reported, not graded.** `UNASSESSED_THIRD_PARTY_TERM` says exactly what
  is true: this repository has no basis for a verdict. Grading it either way would be an
  assessment manufactured from an observation.
- **No network at validation time**, so a conformance run cannot be induced to make a request by
  the content of the object it is checking, and cannot fail open because a service was
  unreachable.
- **No interpretation of security markings.** Dimension B checks that a marking is structurally
  valid and stops. §86 says SC-OES "does not interpret or enforce" markings, and a conformance
  tool that graded them would be doing exactly that.
- **Conformance is not certification**, and the terminology rule in decision 8 keeps the output
  from implying otherwise — an integrity property of the claim as much as a trademark one.

## Reversibility

Moderate. The dimension *set* is fixed by §34 and should not move; the checks *within* a dimension
are expected to grow as profiles and governed types are added, and growth is additive — a new
check can only turn a `PASS` into a `FAIL` for an object that was already non-conformant under a
rule nobody had implemented yet.

The reversible part is the tooling: the module, the CLI and the rendering can be reworked without
touching the contract, because no canonical model depends on them. The parts to get right first
are the report *shape* — five named verdicts, `SKIP` distinct from `PASS` — and the exit-code
contract, because those are what consumers and CI pipelines will parse and quote, and both are
cheap now and expensive after the first release that ships them.
