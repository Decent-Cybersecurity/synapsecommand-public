# Interoperability — what this framework is, what it is not, and how to build against it

This document is the reader's entry point to the framework's contracts. It is normative where it
says MUST; where it describes, it describes the tree, and every figure it states is derived by
`tests/test_cdm_architecture_docs.py`.

Its two companions carry the contracts themselves: [`ARCHITECTURE.md`](ARCHITECTURE.md) is the
adapter contract, and [`VERSIONING.md`](VERSIONING.md) is the version model.

---

## 1. What this is

This repository is an **open integration and semantic contract layer**. It carries a canonical data
model, the published JSON Schemas generated from it, the adapters that translate source formats
into it, the harness and conformance tooling that judge those adapters, an operational event
specification and an operational ontology.

The purpose of the framework is stated most usefully as arithmetic. Without a canonical model in
the middle, N formats means N(N−1)/2 translations and N private notions of what a contact is. With
one, each adapter is a thin translator against a single model, and the translations grow with N
rather than with N².

The framework's objective for its foundation work is to make that model and its surrounding
contracts **stable enough to carry a much larger adapter ecosystem** — so that later adapters can
be implemented without changing the architecture for each one. The important outcome is therefore
not a visible adapter count. It is that every future adapter has:

- exactly one way to describe itself;
- exactly one way to prove conformance;
- exactly one provenance model;
- exactly one evidence mechanism;
- exactly one secure release path.

## 2. What this is not

**Not a product.** Reasoning, inference, correlation and fusion, scoring and course-of-action
generation are the SynapseCommand product and are not in this repository. The language that product
reads is here; the decisions it makes are not. That boundary is enforced over the package sources
by `tests/test_cdm_boundary.py` — no import of private code, no reasoner, no graph database, no
message broker, no model SDK and no crypto in the contract layer — rather than promised by this
paragraph.

**Not a certification authority.** There is no certification programme and this work does not
create one. The permitted conformance claims are exactly the two the specification's conventions
document defines, each meaning exactly what its conformance document says; the same document
carries the list of claims that may not be made, and a sweep over every tracked file enforces
their absence.

**Not a replacement for a source standard.** A source format remains the record of its own wire
semantics. This repository translates formats; it does not compete with them, and a translation is
not an authority over the thing translated.

**Not, in its foundation work, a new adapter portfolio.** The foundation part of this framework
deliberately implements no new source format. It does not add:

```text
AIXM 5.1      AIXM 4.5      ARINC 424     NMEA 0183     NMEA 2000
GeoJSON       GeoPackage    KML/KMZ       STIX          TAXII
OpenC2        Link 16       JREAP         AEW&C         MockC2
Synapse-Sim   Interop Lab   multi-language SDKs
```

Those are later work, to be implemented against stable interfaces. Existing adapters MUST continue
functioning throughout; a foundation round that breaks one has failed rather than progressed.

---

## 3. The layers, and where each lives

Five things are kept apart, because each answers a different question and conflating any two is the
failure the separation exists to prevent:

| layer | answers | where |
|---|---|---|
| Canonical Data Model | what shape is this record | `packages/cdm/`, `schemas/` |
| Operational Ontology | what does this term mean | `ontology/` |
| SC-OES | what kind of operational assertion is this | `spec/sc-oes/` |
| Adapters | how does a source format become a canonical record | `packages/cdm/synapse_cdm/adapters/` |
| The private runtime | what should be done about it | not here, and not published |

The repository's own layout, and what each root holds:

| root | what it holds |
|---|---|
| `packages/cdm/` | the distribution — models, adapter SDK, harness, conformance tooling, fixtures |
| `schemas/` | published JSON Schema, GENERATED from the models and never hand-edited |
| `spec/` | SC-OES and its governance — normative prose, human-readable |
| `ontology/` | the Operational Ontology — Turtle is the authority, everything else derived |
| `examples/` | synthetic events, validated by the suite |
| `tests/` | the suite |
| `gates/` | checks too slow or too networked for the suite |
| `docs/` | the documentation site |

`schemas/` is at the root deliberately: it is the artefact for consumers that are not Python, and a
reader in another language should not have to understand a Python package layout to find it. It is
generated, and a test fails the build if it drifts from the models.

---

## 4. Building an adapter against these contracts

There is **exactly one way**, and it is the same for an adapter inside this repository and one
outside it. Each step's contract is named, so an implementer can find the clause rather than the
convention.

### Step 1 — Describe yourself: metadata

Declare the metadata block of `ARCHITECTURE.md` §3: identity, the source standard and its version,
the direction, the licence class, the maturity level, the claim status, the capabilities including
`limits`, and the limitations. It MUST be inspectable programmatically from the class.

Two of those fields are the ones implementers get wrong, so they are called out here. **Direction**
is a declaration checked at class-definition time and not inferred from which methods exist.
**Limitations** MUST NOT be empty: every adapter has a format edition it does not implement or a
field with no canonical home, and an adapter declaring none is an adapter nobody has audited.

### Step 2 — Publish that declaration: the manifest

The manifest is the machine-readable projection of the metadata, validated against a schema whose
version is one of the framework's axes. It is GENERATED from the adapter, never hand-written
alongside it, and a drift test is what keeps the two from disagreeing — a manifest maintained by
hand becomes a second declaration, and two declarations of one fact is how a stale one survives.

### Step 3 — Prove it: conformance

Run the conformance suite. The framework's harness checks are `ARCHITECTURE.md` §8's first
namespace; a check that does not apply to your adapter reports SKIP, with the declaration that made
it inapplicable, and **never PASS**. Maturity is then COMPUTED from those results by the algorithm
in §3.6 of that document — a level is a claim about evidence and is never typed by hand.

An adapter's claim status is a separate axis and is not computed from its maturity. `INTEGRATED`
requires that integration with a named external system has actually occurred, which is not
something a test run can establish.

### Step 4 — Record it: evidence

Conformance results become deterministic evidence records: what was run, against which fixtures, at
which adapter and schema version, with hashes over the canonical serialisation
(`ARCHITECTURE.md` §6.2). Fixture provenance is part of the record — every fixture in this
repository is synthetic, and the record says so rather than leaving a reader to assume it.

Because the evidence is deterministic, a third party can regenerate it and compare. That is the
whole point of the mechanism: a badge that cannot be recomputed is a decoration.

### Step 5 — Ship it: the release path

One path, gated: the suite and the gates pass; the version axes move per `VERSIONING.md` §3, each
with a derivation rather than a typed number; the release advances `main` by fast-forward only and
STOPs otherwise; the tag names the version the tree declares; the artefact is published and
witnessed by a record that can be checked against what was actually served.

---

## 5. The boundary with SC-OES

SC-OES is the SynapseCommand Operational Event Specification. It is a **lightweight
operational-event semantics layer applied after source-format translation into the SynapseCommand
Canonical Data Model**, and this repository publishes it as a **Draft**: it has not been submitted
to, reviewed by, or approved by any external standards body, and nothing here should be read as
implying that it has.

The boundary is worth stating precisely, because the two things in this repository that sound alike
are the framework's adapter contracts and SC-OES's semantic contracts.

| | the adapter contracts | SC-OES |
|---|---|---|
| what it governs | how a source format becomes a canonical record | what kind of operational assertion a canonical event carries |
| where it is authored | `ARCHITECTURE.md`, `VERSIONING.md` and the package | `spec/sc-oes/` |
| its version axis | the Adapter API and manifest axes | `SC_OES_VERSION`, independent of both |
| how conformance is judged | the harness checks — `ARCHITECTURE.md` §8's first namespace | the SC-OES dimensions — that section's second namespace |

**Three rules follow, and they are what keep the layers from merging:**

1. An adapter is **CDM Conformant** without being an SC-OES producer. Producing the SC-OES block is
   an additional, optional undertaking, and one reference producer exists in this repository.
2. The two conformance letterings are two namespaces. Prose names which one it means — "harness
   check G", "SC-OES dimension D", never a bare letter — because a bare letter in a document that
   discusses both is ambiguous in the way a reader cannot detect.
3. The version axes do not follow each other. The specification's version and the CDM schema's
   version move for different reasons, and neither is computed from the other.

SC-OES adds nothing to the adapter contract and takes nothing from it. What it adds sits on the
CDM's existing event as one optional block, and an object written before it existed stays
structurally valid.

---

## 6. Where to read next

| document | what it answers |
|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | the adapter contract: API v2, directions, metadata, the six core rules, residual, determinism, the conformance namespaces |
| [`VERSIONING.md`](VERSIONING.md) | the nine version axes, what moves each, where each is authored, and how `main` advances |
| [`packages/cdm/synapse_cdm/README.md`](packages/cdm/synapse_cdm/README.md) | the canonical objects, the CDM's authoring rules and where each is enforced, and how to write the next adapter |
| [`packages/cdm/synapse_cdm/MIGRATIONS.md`](packages/cdm/synapse_cdm/MIGRATIONS.md) | what MAJOR, MINOR and PATCH mean for the wire contract, and the procedure for changing it |
| [`packages/cdm/synapse_cdm/FORMAT_COVERAGE.md`](packages/cdm/synapse_cdm/FORMAT_COVERAGE.md) | field-by-field source-format mappings and the named gaps |
| [`spec/sc-oes/README.md`](spec/sc-oes/README.md) | SC-OES: its normative documents, what it is and is not, and the profiles |
