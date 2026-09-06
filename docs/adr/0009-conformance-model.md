# ADR 0009 — Conformance model

## Status

Proposed — awaiting M's review.

## Context

§100 opens with a prohibition: "Do not use one vague 'SC-OES compatible' flag internally. Define
distinct dimensions." It names five — **A** CDM conformance, **B** SC-OES core syntax conformance,
**C** SC-OES semantic type conformance, **D** SC-OES profile conformance, **E** ontology
conformance — and §101 shows what a truthful declaration looks like: several statements, each
naming what it covers, rather than one word.

§102 lists fifteen things validation should support, from SC-OES metadata validity through to
legacy `EventType` mapping, and says "Prefer existing validation APIs and CLI patterns." §104
requires all of it to work offline.

**The repository's validation philosophy is already exactly this shape, and it argued for it.**
`harness.py:473` declares `_COLUMNS = ("translate", "schema", "provenance", "lossless",
"roundtrip", "golden")` — one column per property rather than one verdict per fixture — and
`harness.py:230` states the rule that makes such a report honest: a check that did not run is
"Reported as SKIP — never PASS … An unrun check that reads as passed is how a capability nobody
tested acquires a green tick."

The CLI pattern is there too: a machine-readable report beside the rendered table
(`harness.py:534`, `--json`) and exit codes as module constants (`harness.py:99`).

**Offline is already true rather than aspirational.** `packages/cdm/pyproject.toml:74` declares
two runtime dependencies; `adapter.fixture_root()` (`adapter.py:231`) resolves packaged data
through `importlib.resources` rather than through a repository path; `schemas.generate()`
(`schemas.py:81`) produces the schemas from the models with no file and no network. Nothing in the
validation path reaches out today, and §104 requires that it stay so.

## Decision

**Five separately reportable dimensions, one column each, `PASS` / `FAIL` / `SKIP`, with `SKIP`
for a dimension not exercised — the harness's own shape, and never a single flag.**

1. **The five columns are §100's five dimensions**, reported per subject with no aggregate
   verdict. A caller that wants one composes it from the five and says so; the tool does not
   compose it for them, because that is the flag §100's first line forbids.
2. **`SKIP` is not `PASS`, and it is the load-bearing rule.** `harness.py:230`'s sentence is
   adopted verbatim in intent: a dimension that was not exercised reports `SKIP`. Concretely,
   dimension D is `SKIP` for a producer that declares no profile; dimension E is `SKIP` for an
   object carrying no ontology identifier; dimension C is `SKIP` for an event whose `type_id` is a
   well-formed third-party identifier, because this repository governs no contract it could be
   checked against.
3. **What each dimension asserts**, mapped to §102's list so that nothing on it is homeless:
   - **A — CDM conformance.** The object validates against the canonical models and the published
     schema. Existing rules; no new checks.
   - **B — SC-OES core syntax.** The `oes` block is structurally valid: `event_class` is in §21's
     vocabulary; `maturity` in §28's; `status`, where present, in §33's; `type_id` is well-formed
     under ADR 0003's grammar; the temporal interval is ordered; event relations, entity
     relations, evidence and security markings are structurally valid; extension keys are
     namespaced and within the declared bound (ADR 0008). Structure only — no dimension asserts
     anything about the *value* of an evidence hash (ADR 0006).
   - **C — semantic type conformance.** The `type_id` is in the packaged governed registry; the
     entry's `event_class` matches the event's; the payload validates against
     `OES_PAYLOAD_MODELS[type_id]` where one is registered; `Event.event_type` matches the
     registry's `legacy_event_type` where that is not null (ADR 0007). An `sc.*` identifier absent
     from the registry is a `FAIL` here and the message says so — this is where §25's namespace
     reservation is enforced.
   - **D — profile conformance.** The producer satisfies a named profile's required fields,
     temporality, entity relationships and extension behaviour (§89). Checked against the profile
     named by the caller; `SKIP` when none is named.
   - **E — ontology conformance.** Every ontology identifier is well-formed under §73's grammar
     and, where it is a `urn:synapsecommand:ontology:*` term, is governed. Syntax and lookup only;
     no reasoning (§85, ADR 0002).
4. **Existing CLI patterns are reused, not reinvented**: a rendered table for a person and a
   `--json` report for a machine, in the shape `harness.py:534` already offers, with exit codes as
   module constants in the manner of `harness.py:99`.
5. **Offline, and asserted rather than promised.** The conformance path imports nothing outside
   the two runtime dependencies, reads the registry through `importlib.resources`, and opens no
   socket. A test asserts the import closure, in the manner `tests/test_cdm_boundary.py` already
   asserts the crypto and consumer-import boundaries.
6. **Terminology.** Output uses §132's forms — "SC-OES Conformant", "SC-OES PNT Profile
   Conformant" — and never "Certified", "Approved" or a partner formulation. §101's forbidden
   phrases about external certification appear nowhere in tool output or specification text. ADR
   0010 carries the trademark reasoning.

**The v0.1 profile reality, stated so the report does not overclaim.** §111 makes PNTMAP the
reference implementation and §121 prefers that only PNTMAP need a deliberate semantic upgrade for
v0.1. So PNT is the one profile with a producer behind it, and the other six are
specification-only at 0.1.0. This repository already has a name for that state: `MIGRATIONS.md:8026` is a section headed
"Row sets written as specifications, with no adapter code yet", and a profile with no producer is
that state one layer up. Dimension D is claimable against PNT and declarable-but-unexercised
against the rest. The
profile documents say so rather than implying an implementation.

## Alternatives considered

**A — one boolean "SC-OES compatible".** Rejected by §100's first line, and independently by
`harness.py:230`'s reasoning: a single flag has to decide what an unrun check contributes, and
every answer is wrong — counting it as a pass gives a green tick to an untested capability, and
counting it as a failure makes a partial implementation indistinguishable from a broken one.

**B — a weighted score or a conformance level (bronze/silver/gold).** Rejected: a level is a flag
with more values, and it makes the interesting question — *which* dimension failed — unanswerable
from the result. It also invites the certification language §132 forbids.

**C — fail the whole report when any dimension fails.** Rejected: it collapses five verdicts into
one at the exit code, which is the same defect one level down. The exit code reports whether the
*run* completed; the per-dimension verdicts are the result.

**D — a hosted conformance service.** Rejected by §104 and by §103's "Do not create an online
registry service". Offline is a property of the artefact, not a deployment choice.

**E — infer profile conformance from the data rather than requiring the caller to name a
profile.** Tempting, because it removes an argument. Rejected: guessing which profile a producer
meant, and then reporting conformance to it, is the tool making an assessment out of an
observation — §23's separation, and the `SKIP` rule exists so that "not asked" has an honest
answer.

## Consequences

- A conformance module in the package plus a CLI entry point, and new test modules for §116–§120.
  A module that runs against the installed wheel is package-only (`gates/wheel_install.py:93`);
  one reading `ontology/` or the root `spec/` tree is repository-bound (`:144`);
  `check_slice_closure` (`:521`) fails on a module in neither list, by name.
- The registry becomes load-bearing for dimensions C and E, which is a further reason it must ship
  (ADR 0004).
- Five columns is a number stated in tool output and in documentation; it is derived from the
  dimension list in the code rather than written as a literal, so that a sixth dimension cannot
  arrive while the prose still says five.
- Dimension D is `SKIP` for six of the seven profiles in v0.1 by construction, and that is
  reported rather than hidden.

## Compatibility impact

- **No effect on the wire contract.** This ADR adds no field and changes no model; dimension A is
  the existing CDM rules unchanged.
- **Additive to the package surface**: new importable names and a new CLI entry point, which is a
  package MINOR under `version.py:102`'s "a harness flag or check is added" read for what it is —
  a new check surface — and in any case subordinate to ADR 0005's bump.
- **An object that conforms today keeps conforming.** Dimensions B–E are `SKIP` for an object
  carrying no `oes` block, so every existing adapter's output is unaffected by the model's
  existence.
- **Adding a dimension later would be a report-shape change** for anything parsing the `--json`
  output. The five are fixed by §100, so the shape is expected to be stable; a consumer should key
  on dimension names rather than on positions, and the report is emitted as a mapping for that
  reason.

## Security impact

- **The honest-report property is the security property.** A conformance claim is something a
  buyer or an integrator relies on. `harness.py:231`'s sentence — an unrun check that reads as
  passed is how a capability nobody tested acquires a green tick — is the failure mode this
  decision is built to avoid, and it is why `SKIP` is not `PASS`.
- **Dimension C is namespace enforcement.** It is where an `sc.*` identifier from a producer that
  does not own the namespace is caught, offline, by a consumer, without asking anybody.
- **No network at validation time**, so a conformance run cannot be induced to make a request by
  the content of the object it is checking, and cannot fail open because a service was
  unreachable.
- **No interpretation of security markings.** Dimension B checks that a marking is structurally
  valid and stops. §59 forbids interpreting, downgrading, upgrading, normalising or enforcing one,
  and a conformance tool that graded markings would be doing exactly that.
- **Conformance is not certification**, and the terminology rule in decision 6 keeps the output
  from implying otherwise — which is an integrity property of the claim as much as a trademark one.

## Reversibility

Moderate. The dimension *set* is fixed by §100 and should not move; the checks *within* a
dimension are expected to grow as profiles and governed types are added, and growth is additive —
a new check can only turn a `PASS` into a `FAIL` for an object that was already non-conformant
under a rule nobody had implemented yet.

The reversible part is the tooling: the module, the CLI and the report shape can be reworked
without touching the contract, because no canonical model depends on them. The part to get right
first is the report *shape* — five named verdicts and `SKIP` distinct from `PASS` — because that
is what consumers will parse and quote.
