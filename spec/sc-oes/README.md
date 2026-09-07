# SC-OES — SynapseCommand Operational Event Semantics

**SC-OES v0.1.0 — Draft.** **SynapseCommand Operational Ontology v0.1.0 — Draft.**

This is a draft open interoperability specification. It has not been submitted to, reviewed by, or
approved by any external standards body, and nothing in this tree should be read as implying that
it has.

## What SC-OES is

SC-OES is a thin layer of operational-event semantics applied *after* a source format has been
translated into the SynapseCommand Canonical Data Model (CDM). It answers questions the CDM
deliberately does not: what kind of assertion an event is, which governed semantic type it claims,
how confident and how verified the producer is, over what interval the represented condition
applies, what the event was derived from or supersedes, what evidence stands behind it, and what
handling markings travel with it.

SC-OES does not replace the CDM and does not introduce a second event envelope. It attaches to the
CDM's existing `Event` object as one optional block; `docs/adr/0001-sc-oes-attachment-model.md`
records that decision and the readings of this repository that force it.

## What SC-OES is not

- Not a source format, and not a replacement for one. The formats this repository already
  translates remain the source of record for their own wire semantics.
- Not a reasoner. No inference rules, no classification, no automatic mapping of a third party's
  vocabulary onto a governed one.
- Not a cross-domain guard. SC-OES transports security markings; it neither interprets nor
  enforces them.
- Not a certification programme. See `Terminology` below.

## The three layers, kept apart

| Layer | Answers | Governed by |
|---|---|---|
| Canonical Data Model | *what shape is this record* | the CDM's canonical objects and schemas |
| Operational Ontology | *what does this term mean* | the governed ontology term space |
| SC-OES | *what kind of operational assertion is this* | this specification and the event registry |

A term is not an event type and an event type is not a record shape. Conflating any two of them is
the failure mode the separation exists to prevent.

## The documents

| File | Subject |
|---|---|
| `00-conventions.md` | normative terminology, normative/non-normative/example, trademark, permitted terminology |
| `01-core.md` | the wire-semantic block, the four independent version axes |
| `02-event-classes.md` | the eight `EventClass` values and the observation/assessment rule |
| `03-event-types.md` | the governed type namespace and the thirteen initial types |
| `04-temporality.md` | `observed_at`, `received_at`, `effective_from`, `effective_to`, immutable history |
| `05-lifecycle.md` | the optional lifecycle vocabulary |
| `06-verification-and-confidence.md` | verification and confidence, and why they are not one field |
| `07-provenance-and-evidence.md` | `EvidenceRef` and its three kinds |
| `08-event-relationships.md` | the seven relationship predicates and their validation rules |
| `09-entity-semantics.md` | entity relations and `Entity.ontology_types` |
| `10-security-markings.md` | the marking transport structure and its limits |
| `11-extensions.md` | the extension bag, key grammar, and the structural depth bound |
| `12-versioning.md` | semantic majors, maturity, and unknown-semantics behaviour |
| `13-conformance.md` | dimensions A–E, `PASS`/`FAIL`/`SKIP`, exit codes |
| `14-security-considerations.md` | threat model, trust boundaries, replay, staleness |
| `15-governance.md` | how this specification changes, and who changes it |
| `profiles/` | the seven domain profiles (scope and status only in v0.1.0) |

Governance process documents live in `../governance/`.

## Machine authorities

A document is never the machine authority for something a program has to agree about. In v0.1.0:

| Contract | Machine authority | State |
|---|---|---|
| governed event types | `synapse_cdm/registry/sc_oes/event_types.json` | packaged and shipping |
| governed ontology terms | `synapse_cdm/registry/sc_oes/ontology_terms.json`, generated from the Turtle | packaged and shipping |
| executable profile conformance | `synapse_cdm/registry/sc_oes/profiles.json` | packaged and shipping |
| ontology vocabulary | the Turtle modules and the JSON-LD context | in this repository, not packaged |
| canonical record shape | the CDM models and the generated JSON Schemas | packaged and shipping |

**The third column read "a later round" for the first three rows until 2026-09-07**, which was
true when this document was written and is not now: every machine authority named above exists,
and the three under `synapse_cdm/registry/sc_oes/` are the SC-OES runtime registry artefacts, all
loaded offline through package resources with no repository checkout and no network. ADR 0004
carries the artefact-by-artefact statement and which conformance dimension each one is
load-bearing for.

Where a document and a machine authority disagree about a governed type's class, maturity or
mapping, the machine authority is correct and the document is a defect to be repaired at the
sentence that is wrong. Nothing in this tree is maintained as a second hand-authored copy of a
packaged registry.

## Implementation status in v0.1.0

PNT is the initial reference producer-backed profile, through the PNTMAP producer. The remaining
six profiles are specification-only in v0.1.0: they declare scope, version and maturity, and no
adapter in this repository emits them. Existing adapters remain CDM Conformant without being
SC-OES semantic producers, and that distinction is intentional rather than a gap.

## Trademark

> SC-OES is an open interoperability specification maintained within the SynapseCommand project by
> Decent Cybersecurity. The open-source license governing these materials does not grant rights to
> use Decent Cybersecurity or SynapseCommand trademarks except as necessary for accurate
> descriptive reference.

No certification programme and no trademark licensing programme is created by this work.

## Terminology

Permitted claims are "SC-OES Conformant" and "SC-OES *&lt;Profile&gt;* Profile Conformant" — for
example "SC-OES PNT Profile Conformant" — and each means only what `13-conformance.md` says it
means. The forbidden forms are listed in `00-conventions.md`.

## Licensing

These materials inherit this repository's Apache-2.0 licensing. Pinned external standards remain
outside that work under existing repository policy, and no protected standards text is reproduced
here: descriptions in this tree are independently authored, with references and mappings in place
of quotation. `docs/adr/0010-open-source-packaging-and-licensing.md` carries the reasoning.
