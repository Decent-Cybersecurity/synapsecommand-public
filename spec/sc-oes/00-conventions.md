# 00 — Conventions

**SC-OES v0.1.0 — Draft.**

## Normative terminology

The requirement words in this specification carry established standards-document meanings, and no
others:

| Word | Meaning |
|---|---|
| **MUST** | an absolute requirement. An implementation that does not do this is not conformant. |
| **MUST NOT** | an absolute prohibition. An implementation that does this is not conformant. |
| **SHOULD** | a requirement that may be set aside only for a reason the implementer can state, having understood what is lost. |
| **SHOULD NOT** | a prohibition that may be set aside only under the same condition. |
| **MAY** | genuinely optional. An implementation that does it and one that does not are both conformant, and neither may assume the other's choice. |

Two consequences are worth stating outright, because both are routinely assumed away.

- **MAY is not a recommendation.** A producer MUST NOT require a consumer to have exercised a
  `MAY`, and a consumer MUST NOT treat a `MAY` a producer did not exercise as a defect.
- **SHOULD is not MUST.** A conformance dimension never reports `FAIL` for an unmet `SHOULD`. If a
  rule is worth failing an implementation over, it is written `MUST`.

## Normative, non-normative, example

Every statement in this tree is exactly one of three things, and each is labelled where it is not
obvious from its context:

- **Normative** — part of the interoperability contract. Requirement words carry their meanings
  above. A conformance dimension may test it.
- **Non-normative** — rationale, background, or guidance. It explains a normative statement or
  records why an alternative was rejected. It is never itself tested, and it never adds a
  requirement. Where such a passage would otherwise read as a rule, it is marked
  *(non-normative)*.
- **Example** — an illustration. Examples in this tree are marked as examples, use only the
  synthetic identifiers this repository reserves for the purpose, and are **never** normative. A
  conflict between an example and the normative text is a defect in the example.

Tables are normative unless the table itself says otherwise. Code fences carrying grammars,
vocabularies, field lists and truth tables are normative; code fences carrying worked
illustrations are examples.

## Where a rule actually lives

This specification is prose. Three kinds of statement have a machine authority elsewhere, and the
prose is subordinate to it:

1. **Record shape.** The CDM models and the JSON Schemas generated from them.
2. **Governed event types.** The packaged event registry (`synapse_cdm/registry/sc_oes/`).
3. **Governed ontology terms.** The packaged generated ontology-term registry.

A document that disagrees with one of these is wrong at the sentence that disagrees, and is
corrected there. It is never corrected by changing the machine authority to match the prose.

The architecture decisions behind these documents are recorded under `docs/adr/`, and where a
grammar, a truth table or an algorithm has been frozen, the ADR is the frozen form this
specification restates:

| Subject | Frozen in |
|---|---|
| attachment of `oes` to `Event` | `docs/adr/0001-sc-oes-attachment-model.md` |
| ontology representation | `docs/adr/0002-ontology-representation.md` |
| identifier and namespace grammars | `docs/adr/0003-identifier-and-namespace-strategy.md` |
| registry packaging | `docs/adr/0004-registry-packaging.md` |
| CDM schema version impact | `docs/adr/0005-cdm-schema-version-impact.md` |
| canonicalization and integrity | `docs/adr/0006-canonicalization-and-integrity.md` |
| legacy `EventType` mapping | `docs/adr/0007-legacy-eventtype-mapping.md` |
| the extension mechanism and depth bound | `docs/adr/0008-extension-mechanism.md` |
| the conformance model | `docs/adr/0009-conformance-model.md` |
| packaging, licensing, trademark, terminology | `docs/adr/0010-open-source-packaging-and-licensing.md` |

## Draft status

Both artefacts this tree describes are drafts, and each is labelled with its own version:

```text
SC-OES v0.1.0 — Draft
SynapseCommand Operational Ontology v0.1.0 — Draft
```

Documents in this tree MUST carry the draft label. No document in this tree may imply approval,
endorsement, adoption or review by an external standards body.

## Trademark

> SC-OES is an open interoperability specification maintained within the SynapseCommand project by
> Decent Cybersecurity. The open-source license governing these materials does not grant rights to
> use Decent Cybersecurity or SynapseCommand trademarks except as necessary for accurate
> descriptive reference.

This work creates no certification programme and no trademark licensing programme.

## Permitted terminology

Permitted claims, and the only ones this specification defines:

```text
SC-OES Conformant
SC-OES PNT Profile Conformant
```

The second generalises to any profile named in `profiles/`, in the form "SC-OES *&lt;Profile&gt;*
Profile Conformant". Each claim means what `13-conformance.md` says and nothing wider: a claim of
conformance names the dimensions assessed and the verdict each returned.

Forbidden claims, which MUST NOT appear in documents, tooling output, packaging metadata or
promotional material about SC-OES unless separately and independently established by whatever body
would actually establish them:

```text
SC-OES Certified
Official SynapseCommand Partner
Approved by Decent Cybersecurity
NATO Certified
NATO Approved
NATO Standard
```

*(Non-normative.)* The last three are the realistic accident rather than the realistic deception.
This repository pins external defence standards and describes its adapters against them, so a
loosely written sentence about a pinned standard is the way one of those phrases would appear.
Naming the standard an adapter implements is accurate description; describing the implementation as
approved is not.

## Positioning

The claim this specification makes about itself, in full:

> A lightweight operational-event semantics layer applied after source-format translation into the
> SynapseCommand Canonical Data Model.

SC-OES MUST NOT be described as replacing or superseding any source format, tactical data link,
national or alliance data model, sensor-native protocol or command-and-control message format.

## Synthetic identifiers

Every example in this tree is fictional. Committed examples MUST use synthetic identifiers, drawn
from the reserved set this repository uses for the purpose:

```text
AIRBASE-ALPHA
RUNWAY-27
UAV-17
MISSION-41
AREA-ALPHA
SUPPLY-NODE-BRAVO
```

No real unit, platform, location, callsign, mission or organisation appears in any committed
example, fixture or document in this tree.
