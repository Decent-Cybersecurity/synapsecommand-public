# ADR 0002 — Ontology representation

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

Amended by SA.1 — M, 2026-09-06: reviewed under SA.1 §58 and §62 and **nothing in this ADR moves**.
Turtle authority, generated JSON-LD, generated `ontology_terms.json`, no runtime RDF, a test-only
parser and no reasoning are all SA.1 §7 locked decisions. The reading that settles the review:
this ADR carries no ontology identifier literal at all — it names the registry file and delegates
the identifier form to ADR 0003 — so SA.1 §14's authority-date correction reaches it through that
delegation rather than through an edit. The terms the generator emits carry the dated prefix
`tag:synapsecommand.com,2026-09-06:ontology:`. Still Accepted.

Lineage — round SC, 2026-09-06: decision 6's test-only RDF parser is chosen and is **rdflib
7.6.0, BSD-3-Clause**, with one non-optional transitive dependency, **pyparsing 3.3.2, MIT**. Both
licences were read from the installed distributions' own metadata rather than recalled. It is
declared in `packages/cdm/pyproject.toml`'s `test` extra and nowhere else; no module under
`synapse_cdm/` imports it, and `gates/wheel_install.py` is what keeps that true rather than a
convention: its `import` and `test slice` checks install the built wheel into a fresh virtual
environment carrying only the wheel's own declared runtime dependencies, so a module that reached
for the parser would fail there. The reading, taken rather than assumed: `rdflib` appears nowhere
under `packages/cdm/synapse_cdm/`, and the environment that gate builds holds `pydantic`,
`jsonschema` and nothing else of ours. The three artefacts of
this decision now exist: `ontology/*.ttl` (eight modules, 73 governed terms), the generated
`ontology/context.jsonld`, and the generated
`packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json`; `gates/ontology_terms.py` is the
one generator and `tests/test_cdm_ontology.py` is decision 4's drift test. `ontology/README.md`
records the three points the specification left to the implementing round. Still Accepted.

## Context

§12 rules the representation of the Operational Ontology as a hybrid and states each half
separately: the authoritative ontology is "conservative RDFS/OWL serialized as Turtle"; the
developer projection is a JSON-LD context; the runtime does "no RDF parsing"; a parser "may be
used strictly as a test/development dependency after license review"; and there are "no public
ontology reasoning rules". §88 makes `ontology/*.ttl` the authoritative source and enumerates the
constructs allowed and avoided. §91 fixes the file set: eight `.ttl` modules — `core`, `pnt`,
`air`, `logistics`, `isr`, `c2`, `mission`, `decision` — plus `README.md` and `context.jsonld`.

The constraint this tree adds is about **dependencies, not format**.

`packages/cdm/pyproject.toml:74` declares exactly two runtime dependencies, `pydantic>=2.6` and
`jsonschema>=4.0`. `README.md:204` states that pair as a property of the distribution —
"`pydantic` and `jsonschema`. Nothing else". §144's runtime dependency budget names "RDF parser"
and "OWL reasoner" among the things not to add, §143 requires the boundary tests to prevent a
runtime import of an RDF reasoner, and §136 permits the test-only parser in as many words. §125
requires that validation of the public contract work with no network and no service.

So the question is not "which format" but "what has to be readable at runtime". Nothing in the
runtime validation path may parse Turtle — §102 says exactly that and names the artefact that
replaces it.

There is a second reading, about where the files sit. `README.md:35` explains why `schemas/` is at
the repository root: "it is the artefact for consumers that are not Python". An ontology is the
same kind of artefact for the same kind of consumer, and §88 puts it there.

## Decision

**The hybrid of §12, in three artefacts with one authority: Turtle is authoritative, and both the
JSON-LD context and the packaged ontology-term registry are GENERATED from it and drift-tested
against it.**

1. **The Turtle files are the authority for the vocabulary.** Eight `.ttl` modules under
   `ontology/` at the repository root, beside `schemas/`, for the reason `README.md:35` gives
   about `schemas/` and as §88 and §91 require. They use only the constructs §88 permits —
   `owl:Ontology`, `owl:Class`, `owl:ObjectProperty`, `rdfs:subClassOf`, `rdfs:label`, a
   definition annotation, `rdfs:domain`, `rdfs:range`, `owl:inverseOf` where unquestionably
   correct, and version, maturity and deprecation metadata — and none of what §88 says to avoid:
   no SWRL, no property chains, no complex restrictions, no closed-world reasoning, no
   operational inference, no cardinality machinery, no aggressive disjointness.
2. **A JSON-LD context (`ontology/context.jsonld`) is published beside them** as the developer
   projection §12 and §19 ask for. §19 fixes its standing precisely: it is a developer
   convenience, it "is not required for ordinary CDM/SC-OES JSON validation", and "runtime
   validation must not require parsing it". §19 and §135 both prefer it be generated from the
   same authority, and this ADR takes that preference: it is generated, not hand-authored.
3. **The runtime reads a generated registry, never the ontology.** §102 is the binding sentence —
   "Runtime must not parse Turtle. Generate `ontology_terms.json` from the authoritative
   ontology" — and §18 gives it its place beside the event registry, as the second of the two
   machine-readable runtime artifacts (ADR 0004). Each governed term record carries, as
   applicable, §102's fields: `id`, `label`, `module`, `kind`, `parent`, `maturity`,
   `deprecated`, `replacement`.
4. **The generated artefacts are drift-tested against the Turtle, and that test is what makes
   "generated" a fact rather than an intention.** §18: "`ontology_terms.json` must be **generated
   from the ontology**, not independently hand-maintained. A drift test must prove the generated
   registry matches the Turtle authority." §135 says the same of both derived artefacts and names
   what the test is for: "A drift test must prevent semantic registry divergence." The repository
   already has this exact mechanism one layer over — `tests/test_cdm_schemas.py:22` fails the
   build when the published schemas differ from the models, and `python -m synapse_cdm.schemas
   --check` is its CI form — so the ontology's drift test is that pattern applied to a second
   generated publication, not a new idea.
5. **What the package validates at runtime** is the *syntax* of an ontology identifier — a regex
   over §13's grammar, which ADR 0003 fixes — and, where a governed term must be *recognised*
   rather than merely well-formed, a lookup in the packaged `ontology_terms.json`. That is
   dimension E of ADR 0009, and it needs no library.
6. **The `.ttl` files are validated in the test suite**, with a test-only RDF parser declared in
   `[project.optional-dependencies]`'s `test` extra (`packages/cdm/pyproject.toml:80`, today
   `["pytest>=8.0"]`). §136's four conditions bind: test/development only; licence confirmed
   compatible with repository policy before it lands; no RDF runtime dependency; the choice
   recorded in the ADR 0002 / ADR 0010 lineage. ADR 0010 owns the licence criterion.
7. **No reasoning is published.** §100 forbids encoding operational inference: the ontology may
   define `requires`, `provides` and `affects`, but not the rule that concludes a mission is
   degraded. The ontology states a vocabulary and a subclass hierarchy and stops.

This makes §125's offline requirement true by construction rather than by intention: the only
runtime contract data is packaged JSON.

## Alternatives considered

**A — Turtle only, with runtime term lookup against the ontology.** Rejected: it puts an RDF
parser in the runtime path, which §102, §143 and §144 each forbid separately, and which
`packages/cdm/pyproject.toml:74` and `README.md:204` both state as a property the distribution
does not have. The requirement it would serve — recognising a governed term — is served instead
by the generated registry.

**B — a governed JSON or YAML vocabulary, no RDF at all.** Cheapest, and it would need no new
dependency of any kind. Rejected on §12's ruling and on one this tree adds: the vocabulary is
meant to be usable by consumers outside this project, and a bespoke JSON shape is a vocabulary
only this project can read. RDFS/OWL in Turtle is a published interchange form with existing
tooling, and the cost of that choice is confined to the test extra.

**C — hand-maintain `ontology_terms.json` beside the Turtle, so no generator is needed.**
Rejected by §18 in as many words ("not independently hand-maintained") and by §117's
"Do not maintain two hand-authored copies." Two hand-written files stating the same vocabulary give
two answers to "is this term governed?" the first time one is edited alone. **Note that this is a
narrower rejection than the one this ADR carried while proposed.** The proposed text rejected "a
generated JSON projection of the ontology, packaged" outright, as a duplicate authority; v2 §18
and §102 require exactly that artefact. The distinction that resolves it is *generated versus
hand-maintained*, not *projection versus registry*: a generated projection with a drift test has
one authority and one derivation, which is what §117 asks for.

**D — publish the ontology at an HTTP namespace and resolve terms there.** Rejected: §125 forbids
requiring network access, and this repository has already ruled the general form of this question
once, for schema `$id`s — `schemas.py:41`–`:42` records that an identifier which "promises a fetch
and 404s is worse than one that promises nothing". ADR 0003 applies that ruling to ontology
identifiers, and reaches a different form for a stated reason.

**E — generate the Turtle from the JSON registry, inverting the authority.** Rejected by §88 and
§102 together: §88 names `ontology/*.ttl` as the authoritative source and §102 says the JSON is
generated *from* the ontology. Inverting it would make the interchange artefact the derived one,
which defeats the reason for choosing an interchange form at all.

## Consequences

- Eight `.ttl` modules plus `context.jsonld` and a `README.md` under `ontology/`, repository-only.
- **Two generated artefacts, one generator each, and a drift test for each.** `context.jsonld`
  stays repository-only (§19: a developer convenience); `ontology_terms.json` ships in the wheel
  (ADR 0004), because §102 makes it the runtime's only route to term recognition.
- One new **test-only** dependency, an RDF parser. `gates/bump_derivation.py:72` reads "an
  optional dependency appears" as a MINOR signal directly from `[project.optional-dependencies]`,
  so it will show in the gate's output; in the arc that also carries the `SCHEMA_VERSION` move it
  changes no outcome, and it should not surprise the round that reads it.
- The parser's licence must be checked for compatibility before it lands — §136, ADR 0010.
- A new test module reading `ontology/` at the repository root is **repository-bound**, so it
  joins `REPO_BOUND_TESTS` (`gates/wheel_install.py:144`) and not `PACKAGE_ONLY_TESTS` (`:93`).
  `check_slice_closure` (`gates/wheel_install.py:521`) fails on a module in neither list, by name.
  The module that loads `ontology_terms.json` from the *installed package* is the opposite case
  and joins `PACKAGE_ONLY_TESTS`.
- Runtime gains an ontology-identifier syntax validator with no library behind it, plus a lookup.

## Compatibility impact

None to the CDM wire contract: this decision adds no field and changes no model. The wire
consequence of the campaign is ADR 0001's fields and ADR 0005's version, not this ADR's files.

It is compatible with the two runtime dependencies stated at `packages/cdm/pyproject.toml:74` and
restated at `README.md:204`, and those statements stay true — they are about the runtime, and the
parser is in the `test` extra.

Ontology identifiers themselves become public API the moment they are published (§13: "Once
published, identifiers are permanent public API"), which is why their *form* is ADR 0003's
decision rather than this one's. Term-level compatibility is governed by the maturity vocabulary
of §50–§51 and by §122's deprecation rules, which retain the identifier and its original
definition rather than reusing it — and §102's term records carry `deprecated` and `replacement`
so that a consumer can read both offline.

## Security impact

- **No network at validation time**, by construction: nothing in the runtime path opens the
  ontology, and §125's list of things a validator must not need — GitHub, the internet, a
  SynapseCommand service, a schema registry service, an ontology server, a remote API — is
  satisfied because none of them is reachable from the code path.
- **The parser is not exposed to hostile input in production.** It runs in the test suite over
  files this repository authors. An RDF parser in the runtime path would be a parser exposed to
  whatever a producer sends; keeping it test-only removes that surface rather than hardening it.
  §143 makes that a test rather than a habit.
- **The drift test is a security control, not only a correctness one.** §127 names "malicious
  third-party ontology terms" and "reserved-namespace impersonation" as threats, and dimension E
  answers both by lookup against `ontology_terms.json`. A registry that had silently diverged from
  the ontology would be answering "is this governed?" from a stale list — the check would still
  run, still report, and be wrong. Generation plus drift is what keeps the answer honest.
- **No reasoning means no inference-driven escalation.** §100's ban on operational inference keeps
  the ontology from being a place where an assessment can be manufactured from observations —
  which is §62's separation ("An observation MUST NOT silently become an assessment") expressed
  one layer down.
- **Terms are independently authored.** §43 forbids copying protected standards content or
  substantial protected definitions; the ontology defines terms in this repository's own words and
  *maps* to external standards rather than transcribing their definitions. `NOTICE:55` already
  draws that boundary for the pinned specification documents.

## Reversibility

High for the format, low for the identifiers.

The ontology is repository-only and nothing at runtime parses it, so replacing Turtle with another
serialisation is a change to files no consumer receives, to the two generators, and to the test
module that reads them. The published surface — the identifier *strings* in
`Entity.ontology_types` and in `oes`, and the shipped `ontology_terms.json` — is ADR 0003's and
ADR 0004's decision respectively, and is what would be expensive to move; this decision is
deliberately arranged so that the expensive part is the identifier grammar and not the file
format.

Dropping the test-only parser later is a one-line change to the `test` extra plus the removal of
the module that used it. The generators are the part that cannot be dropped without dropping the
drift guarantee with them, which is why decision 4 states the test rather than the intention.
