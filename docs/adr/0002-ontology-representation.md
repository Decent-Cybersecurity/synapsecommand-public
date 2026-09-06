# ADR 0002 — Ontology representation

## Status

Proposed — awaiting M's review.

## Context

§71 asks this ADR to compare three options for representing the Operational Ontology — RDF/OWL
serialised as Turtle (A), a governed JSON or YAML vocabulary (B), or a hybrid (C) — and states a
preference: "Conservative RDFS/OWL ontology in Turtle plus a lightweight JSON-LD context or
registry for developers. Do not introduce sophisticated semantic-web reasoning merely because OWL
supports it."

The constraint this tree adds is about **dependencies, not format**.

`packages/cdm/pyproject.toml:74` declares exactly two runtime dependencies, `pydantic>=2.6` and
`jsonschema>=4.0`. `README.md:204` states that pair as a property of the distribution —
"`pydantic` and `jsonschema`. Nothing else". §124 forbids adding an RDF reasoner as a runtime
dependency and permits a test-only parser in as many words: "Test-only ontology parsers are
acceptable." §104 requires that validation of the public contract work with no network and no
service.

So the question is not "which format" but "what has to be readable at runtime". Nothing in the
runtime validation path may need to parse Turtle.

There is a second reading, about where the files sit. `README.md:35` explains why `schemas/` is at
the repository root: "it is the artefact for consumers that are not Python". An ontology is the
same kind of artefact for the same kind of consumer.

## Decision

**Option C, the hybrid, in the precise split §124 authorises.**

1. **The Turtle files are the authority for the vocabulary.** Eight `.ttl` modules under
   `ontology/` at the repository root, beside `schemas/`, for the reason `README.md:35` gives
   about `schemas/`. They use only the conservative constructs §72 permits — `owl:Ontology`,
   `owl:Class`, `owl:ObjectProperty`, `rdfs:subClassOf`, `rdfs:label`, a definition annotation,
   `rdfs:domain`, `rdfs:range`, `owl:inverseOf` where clearly valid, and version, deprecation and
   maturity metadata — and none of what §72 says to avoid: no SWRL, no complex restrictions, no
   cardinality restrictions, no property chains, no operational inference rules.
2. **A JSON-LD context (`ontology/context.jsonld`) is published beside them** for developers and
   for non-Python consumers, as §71 prefers.
3. **Nothing at runtime parses either file.** What the package validates at runtime is the
   *syntax* of an ontology identifier — a regex over §73's grammar, which ADR 0003 fixes — and,
   where a governed term must be *recognised* rather than merely well-formed, a lookup in the
   packaged registry (ADR 0004), not in the ontology.
4. **The `.ttl` files are validated in the test suite**, with a test-only RDF parser declared in
   `[project.optional-dependencies]`'s `test` extra (`packages/cdm/pyproject.toml:79`, today
   `["pytest>=8.0"]`). §118's thirteen validations live there.
5. **No reasoning is published.** §85 forbids public reasoning rules; the ontology states a
   vocabulary and a subclass hierarchy and stops.

This makes §123's "ontology RDF may remain repository-only if runtime validation does not require
it" true by construction rather than by intention.

## Alternatives considered

**A — Turtle only, with runtime term lookup against the ontology.** Rejected: it puts an RDF
parser in the runtime path, which §124 forbids by name and which `packages/cdm/pyproject.toml:74`
and `README.md:204` both state as a property the distribution does not have. The requirement it
would serve — recognising a governed term — is served instead by the packaged registry, which is
already required for §103's helpers.

**B — a governed JSON or YAML vocabulary, no RDF at all.** Cheapest, and it would need no new
dependency of any kind. Rejected on §71's own ground and on one this tree adds: the vocabulary is
meant to be usable by consumers outside this project, and a bespoke JSON shape is a vocabulary
only this project can read. RDFS/OWL in Turtle is a published interchange form with existing
tooling, and the cost of that choice is confined to the test extra.

**C — Turtle plus a generated JSON projection of the ontology, packaged, replacing the registry.**
Rejected as a duplicate authority. §123 says "Avoid duplicate authoritative copies", and a
generated projection alongside the governed registry gives two answers to "is this term
governed?". The registry is the packaged artefact; the ontology is the vocabulary's authority;
the mapping between them is stated in the registry's `ontology_class` field (§31).

**D — publish the ontology at an HTTP namespace and resolve terms there.** Rejected: §104 forbids
requiring network access, and this repository has already ruled the general form of this question
once, for schema `$id`s — `schemas.py:38`–`:43` records that an identifier which "promises a fetch
and 404s is worse than one that promises nothing". ADR 0003 applies that ruling to ontology
identifiers.

## Consequences

- Eight `.ttl` modules plus `context.jsonld` and a `README.md` under `ontology/`, repository-only.
- One new **test-only** dependency, an RDF parser. `gates/bump_derivation.py:72` reads "an
  optional dependency appears" as a MINOR signal directly from `[project.optional-dependencies]`,
  so it will show in the gate's output; in the arc that also carries the `SCHEMA_VERSION` move it
  changes no outcome, and it should not surprise the round that reads it.
- The parser's licence must be checked for compatibility before it lands — ADR 0010.
- A new test module reading `ontology/` at the repository root is **repository-bound**, so it
  joins `REPO_BOUND_TESTS` (`gates/wheel_install.py:144`) and not `PACKAGE_ONLY_TESTS` (`:93`).
  `check_slice_closure` (`gates/wheel_install.py:521`) fails on a module in neither list, by name.
- Runtime gains an ontology-identifier syntax validator with no library behind it.

## Compatibility impact

None to the CDM wire contract: this decision adds no field and changes no model. It is compatible
with the two runtime dependencies stated at `packages/cdm/pyproject.toml:74` and restated at
`README.md:204`, and those statements stay true — they are about the runtime, and the parser is in
the `test` extra.

Ontology identifiers themselves become public API the moment they are published (§73: "Do not
casually change them"), which is why their *form* is ADR 0003's decision rather than this one's.
Term-level compatibility is governed by the maturity vocabulary of §28–§29 and by §96's
deprecation rules, which retain the identifier and its original definition rather than reusing it.

## Security impact

- **No network at validation time**, by construction: nothing in the runtime path opens the
  ontology, and §104's list of things a validator must not need — GitHub, SynapseCommand servers,
  a schema registry service, an ontology server, the internet — is satisfied because none of them
  is reachable from the code path.
- **The parser is not exposed to hostile input in production.** It runs in the test suite over
  files this repository authors. An RDF parser in the runtime path would be a parser exposed to
  whatever a producer sends; keeping it test-only removes that surface rather than hardening it.
- **No reasoning means no inference-driven escalation.** §85's ban on public reasoning rules
  keeps the ontology from being a place where an assessment can be manufactured from observations
  — which is §23's separation ("Observation must not become assessment silently") expressed one
  layer down.
- **Terms are independently authored.** §128 forbids reproducing protected standards content;
  the ontology defines terms in this repository's own words and *maps* to external standards
  rather than transcribing their definitions. `NOTICE:55` already draws that boundary for the
  pinned specification documents.

## Reversibility

High. The ontology is repository-only and nothing at runtime depends on it, so replacing Turtle
with another serialisation is a change to files no consumer receives and to the test module that
reads them. The published surface — the identifier *strings* in `Entity.ontology_types` and in
`oes` — is ADR 0003's decision and is what would be expensive to move; this decision is
deliberately arranged so that the expensive part is the identifier grammar and not the file
format.

Dropping the test-only parser later is a one-line change to the `test` extra plus the removal of
the module that used it.
