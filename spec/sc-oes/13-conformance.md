# 13 — Conformance

**SC-OES v0.1.0 — Draft.**

Conformance is reported in five separately assessable dimensions, each with its own verdict. There
is no aggregate. `docs/adr/0009-conformance-model.md` records the model.

## The five dimensions

```text
A — CDM Conformance
B — SC-OES Core Syntax Conformance
C — SC-OES Semantic Type Conformance
D — SC-OES Profile Conformance
E — Ontology Conformance
```

## The three verdicts

```text
PASS
FAIL
SKIP
```

Normative:

> `SKIP` MUST NOT be displayed, reported, exported or aggregated as `PASS`.

> No implementation of this specification produces a single combined compatibility score, grade or
> percentage.

`SKIP` means *this was not assessed* — because it was not requested, or because there was nothing
present to assess. It is not a weak pass, and the difference between "did not fail" and "passed" is
the entire value of reporting five dimensions rather than one.

*(Non-normative.)* A single score is the first thing a reader asks for and the one number this model
refuses to produce. Any weighting that combined the five would encode a judgement about which
dimension matters — and the honest answer is that it depends on what the consumer is doing. A
producer emitting third-party extensions and no ontology terms is doing nothing wrong; a score would
have to decide how much to penalise it, and would then be quoted as though it had a meaning.

## Dimension A — CDM Conformance

Checks:

- canonical model validity;
- required fields;
- schema version;
- canonical schema validity;
- existing CDM invariants.

Normative:

> Dimension A applies no SC-OES-specific interpretation. An event with no SC-OES block is assessable
> under A, and A's verdict MUST NOT depend on the presence, absence or content of the SC-OES block.

## Dimension B — SC-OES Core Syntax

Checks:

- the `oes` block structure;
- a supported SC-OES version;
- `event_class`;
- lifecycle;
- verification;
- confidence bounds;
- temporal ordering;
- type identifier syntax;
- event relation structure;
- entity relation structure;
- evidence structure;
- security-marking structure;
- extension namespace;
- extension nesting bound.

Normative:

> Dimension B makes no semantic event-type interpretation beyond core syntax.

> No dimension asserts anything about the *value* of an evidence hash
> (`07-provenance-and-evidence.md`).

## Dimension C — SC-OES Semantic Type

For a governed `sc.*` event, checks:

- the type exists in the packaged event registry;
- `event_class` matches the registry;
- the ontology event class matches the registry;
- a registered payload model validates, where one exists;
- a non-null legacy `EventType` mapping matches.

Normative:

> For a syntactically valid unknown `x.*` event, `C = SKIP` — this repository does not govern that
> third-party semantic contract.

> For an unrecognised `sc.*` type, `C = FAIL`.

> A `type_id` satisfying neither event-type grammar is a syntax defect: `B = FAIL` and `C = SKIP`,
> with the detail "semantic type not evaluated because core type identifier syntax failed".

The last rule is why one malformed character produces one finding. C does not invent a semantic
complaint about a string it could not parse, and a producer reading the report is not left choosing
between two findings about the same defect.

## Dimension D — SC-OES Profile

Normative:

> The caller names the profile explicitly. Where no profile is requested, `D = SKIP`.

> An implementation MUST NOT infer which profile a producer probably meant.

*(Example.)* `PNT`, `Air`, `Logistics` — the profiles named in `profiles/`.

In v0.1.0, D is EXECUTABLE against PNT, which has a reference producer and, since 2026-09-07, one
conformance rule of its own; it is declarable but unexercised against the other six, which are
specification-only (`profiles/`).

Normative — the complete outcome table. The profile's version, maturity, implementation status,
governed event-type membership and executable rules are read from the packaged profile registry
(`synapse_cdm/registry/sc_oes/profiles.json`), which is the machine authority for them:

| Request | Profile state | Object | D |
|---|---|---|---|
| no profile requested | — | any | `SKIP` — an implementation does not infer which profile was meant |
| a specification-only profile requested | known, no executable rules | any | `SKIP` — the profile exists and there is nothing to check it against |
| an executable profile requested | executable rules | the object is a member of the profile and every rule holds | `PASS` |
| an executable profile requested | executable rules | the object carries a governed type the profile does not declare | `FAIL` |
| an executable profile requested | executable rules | the object carries no SC-OES block | `SKIP` — membership cannot be established, and SC-OES metadata is never manufactured to establish it |
| an unknown profile requested | no such profile | — | not a verdict: a CLI / configuration error, exit code 2 |

Read as five sentences, which is how the implementation is written:

> `PNT` requested + executable PNT rules + the event is in PNT = `D` `PASS`.

> `PNT` requested + executable PNT rules + the event is outside PNT = `D` `FAIL`.

> A specification-only profile requested = `D` `SKIP`.

> No profile requested = `D` `SKIP`.

> An unknown profile requested = a CLI / configuration error, and not a conformance finding.

Two rules bound what D may do with those answers. **D MUST NOT report A, B, C or E as its own
findings** — an object whose block is malformed fails B, and D says only that it cannot establish
membership. And **a profile MUST NOT require a producer to be a particular producer**: nothing in
a profile's rules may read `source.system`, `source.adapter` or any other producer identity. A
reference producer is an implementation held to the profile, not a condition of conforming to it.

*(Non-normative.)* A profile with no executable rules returns `SKIP` rather than `PASS` for the
reason the whole of this document turns on: `SKIP` means this was not assessed. A `PASS` produced
from an empty rule set would be a conformance claim manufactured out of the absence of anything to
check, and the specification-only profiles are deliberately unfinished rather than defective — so
`FAIL` is wrong for them too.

## Dimension E — Ontology Conformance

For a governed ontology identifier, checks:

- the syntax is valid (`09-entity-semantics.md`);
- the term appears in the packaged generated ontology-term registry.

Syntax and lookup only. No reasoning, no inference, no fetch.

Normative — the complete verdict table:

| Input | E | Detail |
|---|---|---|
| no ontology identifiers | `SKIP` | none present |
| only valid third-party identifiers | `SKIP` | each listed as `UNASSESSED_THIRD_PARTY_TERM` |
| valid governed identifiers only | `PASS` | governed terms recognised |
| valid governed + valid third-party | `PASS` | third-party terms separately unassessed |
| unknown identifier in the reserved SynapseCommand family | `FAIL` | reserved namespace, unknown term |
| malformed governed identifier | `FAIL` | invalid syntax |
| malformed third-party identifier | `FAIL` | invalid syntax |

Three readings of that table are worth stating outright:

- **Third-party-only is `SKIP`** — neither `PASS` nor `FAIL`. The terms are present and this
  repository governs none of them, so there is nothing it can honestly grade.
- **A valid third-party term never downgrades a governed result.** Governed-plus-third-party is
  `PASS`, with the third-party terms listed as unassessed beside it: "not assessed" and "assessed
  and wanting" are different facts, and only the second is a defect.
- **A malformed third-party identifier is `FAIL`**, not an unassessed term. Preserving a malformed
  string as though it were valid third-party semantics is how a defect acquires the same treatment
  as a legitimate extension.

Normative:

> Duplicate identifiers MUST be reported. They MUST NOT be silently deduplicated and MUST NOT be
> transformed away.

> E inspects `Entity.ontology_types`, SC-OES entity relation predicates, governed ontology
> references carried on the event, and any field a profile explicitly defines as an ontology-ID
> field. It MUST NOT scan arbitrary strings inside `payload`, `attributes` or `extensions`.

The last rule keeps E from inferring. A dimension that scanned open bags for things that look like
identifiers would be guessing at a producer's intent, which is what `02-event-classes.md` and this
whole model exist to prevent.

## Exit codes

The multidimensional report remains authoritative; the process status exists so that continuous
integration can use it.

```text
0   the run completed and no requested dimension FAILed
1   one or more requested dimensions FAILed
2   CLI / configuration / usage error
3   internal execution error
```

Normative:

> `SKIP` MUST NOT fail the process by default.

> A mechanism MUST be provided for the caller to name required dimensions — conceptually equivalent
> to `--require A,B,C`, spelled per this repository's own command-line conventions.

> Where a required dimension is `SKIP`, the invocation is unsuccessful.

> The reported verdict MUST NOT be rewritten to `FAIL` to make the exit code follow from it.

The two layers do not leak into each other, and E is where that would go wrong. `--require E`
against an object with no ontology identifiers makes the *invocation* unsuccessful; the report still
reads `E = SKIP`. A dimension verdict records what could be assessed about the object; the process
status records whether the caller got the assessment they asked for. Collapsing the first into the
second would put the caller's command line into the conformance record, and a later reader would
have no way to tell an object that failed E from one nobody could evaluate.

## Output

Normative:

> Both a human-readable report and a machine-readable JSON report MUST be provided.

> The JSON report MUST key dimensions by name — `A`, `B`, `C`, `D`, `E`, or descriptive stable names
> — and MUST NOT use positional columns.

A sixth dimension must not be able to silently shift a fifth column's meaning.

## Offline

Normative:

> Conformance assessment MUST complete with no network access. Both registries are read from local
> packaged resources.

## Claiming conformance

Normative:

> A conformance claim MUST name the dimensions assessed and the verdict each returned. An unqualified
> claim of conformance is not a claim this specification defines.

> Output and documentation MUST use only the permitted terminology in `00-conventions.md`.

*(Example.)* "SC-OES Conformant: A `PASS`, B `PASS`, C `PASS`, D `SKIP`, E `SKIP`" is a claim. "SC-OES
Conformant" alone is not, and "SC-OES Certified" is forbidden.

## Trademark

> SC-OES is an open interoperability specification maintained within the SynapseCommand project by
> Decent Cybersecurity. The open-source license governing these materials does not grant rights to
> use Decent Cybersecurity or SynapseCommand trademarks except as necessary for accurate
> descriptive reference.

This work creates no certification programme and no trademark licensing programme. A conformance
result is a self-assessment or a third-party assessment against the dimensions above; it is not an
endorsement, and no party may represent it as one.
