# SynapseCommand Operational Ontology

**SC-OES v0.1.0 — Draft.** Ontology version `0.1.0`.

A public *terminological* ontology: classes, relationships, hierarchy, labels, definitions and
stable identifiers. It contains no operational instances, no inference rules and no reasoning
(SC-OES-SPEC-v2 §87, §100). The reasoning this vocabulary would be written over is not in this
repository and is not part of what SC-OES publishes.

## One authority, two derived files

```text
ontology/*.ttl                                              AUTHORITY — eight modules
ontology/context.jsonld                                     derived — the developer projection
packages/cdm/synapse_cdm/registry/sc_oes/ontology_terms.json  derived — what the runtime reads
```

Neither derived file is hand-maintained. Both are written by `gates/ontology_terms.py`, and
`tests/test_cdm_ontology.py` fails the build if either has drifted from the Turtle:

```sh
python gates/ontology_terms.py            # check both derived files against the ontology
python gates/ontology_terms.py --write    # regenerate them after editing a module
```

The runtime never parses Turtle and never loads the JSON-LD context. It reads
`ontology_terms.json`, which is packaged JSON, requires no network and requires no RDF library
(§102, §125, §144; `docs/adr/0002-ontology-representation.md`). The RDF parser exists only in the
`test` extra.

## The modules

| File | Holds |
|---|---|
| `core.ttl` | the two branches of §89–§90, every object class, the eight event classes, and the fifteen §92 relationships |
| `pnt.ttl` | positioning, navigation and timing (§93) |
| `air.ttl` | air domain (§94) |
| `logistics.ttl` | logistics (§95) |
| `isr.ttl` | intelligence, surveillance and reconnaissance (§96) |
| `c2.ttl` | command, control and communications (§97) |
| `mission.ttl` | mission event classes (§98) |
| `decision.ttl` | recommendation, decision and action records (§99) |

No module `owl:imports` another. The eight files are loaded together and a parent in another
module is referred to by its identifier, which keeps each file readable on its own and keeps the
import closure out of the derived artefacts.

## Identifiers

```text
tag:synapsecommand.com,2026-09-06:ontology:<module>:<Term>
```

frozen by `docs/adr/0003-identifier-and-namespace-strategy.md` decision 9 and restated normatively
in `../spec/sc-oes/09-entity-semantics.md`. `module` matches `[a-z][a-z0-9_]*`, `Term` matches
`[A-Z][A-Za-z0-9]*`, and the authority date `2026-09-06` is fixed for the lifetime of the v0.1
namespace — it is not shortened, not derived from a clock and not changed for later versions.

Each module also has a **document IRI**, `tag:synapsecommand.com,2026-09-06:ontology:<module>`,
which names the file and is deliberately *not* a governed term: it carries no `<Term>` segment, so
the grammar above cannot match it. The generator asserts that closure rather than leaving it to be
noticed — every subject in the governed namespace is either a declared term or one of the eight
module document IRIs, and anything else stops the build.

## Three things this ontology derived rather than read

The specification did not settle these, and each is written down here so that a later reader meets
the reasoning rather than the result.

**1. The fifteen §92 relationships are `UpperCamelCase` identifiers with §92's spelling as their
label.** §92 lists them as `partOf`, `hasPart`, `locatedAt`, … and instructs "use governed tag
identifiers". The governed grammar admits only `[A-Z][A-Za-z0-9]*` in the term segment, so
`…:core:partOf` is not an identifier this project can mint; SA.1 §17 rules the case directly —
"If a concept name would violate this grammar, choose a conforming UpperCamelCase public term."
So the identifier is `…:core:PartOf` and the `rdfs:label` is `partOf`, which is where §92's own
spelling belongs: `../spec/governance/ONTOLOGY-TERM-PROCESS.md` says a preferred spelling "is a
property of a term, not a new term". All fifteen of §92's names survive verbatim, as labels.

*One consequence is a defect in a document this round may not edit.* The worked example at
`../spec/sc-oes/09-entity-semantics.md` writes a predicate as
`tag:synapsecommand.com,2026-09-06:ontology:core:affects`, which the grammar quoted eight lines
below it in that same document refuses. The governed identifier for that relationship is
`…:ontology:core:Affects`. Correcting the example belongs to whoever owns that normative file.

**2. A class the specification left unparented takes the most general core class it cannot fail to
satisfy.** §94, §95 and §97 state their hierarchies and those are taken exactly. §93 and §96 state
none, and inventing a specific parent there would publish an axiom the specification did not make
and a consumer cannot renegotiate. So: `pnt:PNTService` is a `core:Service` (a PNT service cannot
fail to be a service); `pnt:GNSSReceiver` is a `core:Asset` and not a `core:Sensor`, because a
receiver's purpose is navigation rather than reporting observations; `pnt:InterferenceSource` is a
`core:OperationalObject` and not a `core:ThreatSource`, because interference is often
unintentional; `isr:ISRSource` is a `core:OperationalObject`, because an ISR source is as
legitimately an organisation or a unit as it is an asset.

**3. Maturity and deprecation are carried in a separate metadata namespace.** §88 permits
"maturity metadata" and "deprecation metadata" and names no vocabulary, and no standard vocabulary
has a maturity property. This ontology uses `tag:synapsecommand.com,2026-09-06:ontology-metadata:`
for `maturity`, `replacedBy` and `module`, and the standard `owl:deprecated` for the flag itself.
That namespace is provably disjoint from the governed term namespace — the grammar requires the
literal segment `ontology:` after the date, and this one reads `ontology-metadata:` — so a
metadata property can never be read as a term or reach the registry.

Definitions are `skos:definition`, versions are `owl:versionInfo`, and every term carries both.

## Maturity

Every term in v0.1.0 is `EXPERIMENTAL`, the entry maturity
`../spec/governance/ONTOLOGY-TERM-PROCESS.md` and `../spec/sc-oes/15-governance.md` set for a new
definition. This is the ontology's own axis and is **independent of the event registry's**: an
event *type* may be `DRAFT` in `../spec/sc-oes/03-event-types.md` while the ontology *class* its
registry entry points at is `EXPERIMENTAL`, because the two govern different things and
`../spec/sc-oes/12-versioning.md` stores maturity separately for each. No term claims `STABLE`.

## Adding a term

`../spec/governance/ONTOLOGY-TERM-PROCESS.md` governs it, and the rule with the sharpest edge is
that the registry "MUST NOT be hand-edited to carry a term the ontology does not define". Add the
term to its module, regenerate, and commit the ontology and both derived files together.
