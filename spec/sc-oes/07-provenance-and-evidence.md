# 07 — Provenance and evidence

**SC-OES v0.1.0 — Draft.**

`evidence[]` records what stands behind an assertion. It is optional, it is a list, and it is
descriptive: nothing in this specification fetches, verifies or embeds what an evidence reference
points at.

## EvidenceRef

Each entry in `evidence[]` is an `EvidenceRef`. Every reference declares its kind:

```text
EVENT
SOURCE_RECORD
EXTERNAL_ARTIFACT
```

Normative:

> `kind` MUST be one of the three values above. A reference whose kind is absent or unrecognised is
> a dimension B failure.

The three kinds differ in what they point at: another assertion in this system, a record in a
source system, or something outside both.

## EVENT evidence

```text
kind: EVENT
event_id: <event identifier>
```

The assertion rests on another event known to this system.

Normative:

> `event_id` MUST be a well-formed event identifier.

> An `EVENT` evidence reference MUST NOT be required to resolve locally. A consumer that cannot
> find the referenced event MUST NOT reject the citing event for that reason.

*(Non-normative.)* `EVENT` evidence and a `DERIVED_FROM` relation are close relatives and are not
interchangeable. `DERIVED_FROM` is a claim about how this event came to exist and is part of the
event graph; `EVENT` evidence is a citation supporting the assertion's content. A producer will
often assert both about the same earlier event, and it is not redundant to do so.

## SOURCE_RECORD evidence

```text
kind: SOURCE_RECORD
source_id:
    system: <source system identifier>
    external_id: <identifier within that system>
```

The assertion rests on a record in a source system. This reuses the CDM's existing source-identifier
representation rather than introducing a second one, so that a reference here and a source
identifier elsewhere on the record are the same kind of thing and are resolved the same way.

Normative:

> A `SOURCE_RECORD` reference MUST use the canonical source-identifier representation. It MUST NOT
> encode the pair into a single opaque string.

## EXTERNAL_ARTIFACT evidence

```text
kind: EXTERNAL_ARTIFACT
uri: <absolute URI>
description: optional
media_type: optional
hash: optional
```

The assertion rests on something outside this system and outside its source systems — a document, an
image, a published notice.

Normative:

> No implementation of this specification performs network retrieval of an `EXTERNAL_ARTIFACT`
> `uri`, at validation time or at any other time.

> Binary content MUST NOT be embedded in an evidence reference.

> `hash` is descriptive metadata only. It MUST NOT be treated as an integrity guarantee, a
> signature, or evidence of authenticity, and no conformance dimension asserts anything about its
> value.

*(Non-normative.)* The `hash` rule is the one most likely to be over-read, so it is stated
negatively. A producer may record a digest it computed, and a consumer that independently holds the
artefact may find the comparison useful. What the field is not is a cryptographic assertion: SC-OES
v0.1.0 implements no signing and no verification, `docs/adr/0006-canonicalization-and-integrity.md`
records why, and a field that looked like integrity while guaranteeing nothing would be worse than
no field at all — which is why the limit is written here rather than left to be inferred.

## No caps, and no fan-out promise

There is no normative maximum length for `evidence[]` in v0.1.0; `11-extensions.md` explains the
distinction between an interoperability rule and a deployment resource policy, and
`14-security-considerations.md` names evidence fan-out as a threat a deployment handles locally.

Normative:

> A consumer MUST NOT assume that following evidence references terminates.

Evidence chains may be long, may revisit events, and may reference material the consumer will never
hold. A consumer that walks them bounds its own walk.
