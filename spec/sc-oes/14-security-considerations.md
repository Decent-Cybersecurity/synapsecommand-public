# 14 — Security considerations

**SC-OES v0.1.0 — Draft.**

SC-OES does not solve the threats below. This document exists to identify trust boundaries honestly
and to say, for each threat, which side of the boundary it falls on — because a specification that
listed threats without saying that would be read as claiming to address them.

Normative:

> SC-OES makes no authenticity, integrity, confidentiality or availability guarantee. It is a
> semantics layer over a data model, transported by whatever the deployment transports it with.

## Trust boundaries

Three boundaries, and every threat below sits on one of them:

1. **Producer → canonical system.** Whatever authenticates the producer and protects the channel is
   the deployment's, not SC-OES's. SC-OES assertions carry the producer's claims; it does not verify
   that the producer is who it says or that the claims are true.
2. **Canonical system → consumer.** Validation, registry lookup and conformance assessment happen
   here, locally and offline. This is the only boundary SC-OES has mechanisms at, and its mechanisms
   are syntactic and structural.
3. **Consumer → decision.** What anybody does with an assertion — act, escalate, release, deny — is
   the consumer's, under its own policy and accountability. Nothing in this specification authorises
   a decision.

## The threats, and where each sits

| Threat | Boundary | v0.1.0 position |
|---|---|---|
| spoofed producers | 1 | not addressed. Producer authentication is the deployment's. |
| tampered events | 1 | not addressed. No signing in v0.1.0; `docs/adr/0006-canonicalization-and-integrity.md` records why. |
| replay | 1 | partly addressed by deterministic identity, below. No cryptographic anti-replay. |
| stale events | 1, 3 | addressed by making staleness visible, not by deciding it. See below. |
| ID collision | 1 | not addressed beyond deterministic identity. A colliding producer is a producer problem. |
| oversized payloads | 2 | deployment resource policy. No normative size cap. |
| malicious extension data | 2 | bounded structurally: the key grammar and the depth bound. Content is not interpreted. |
| deep nesting | 2 | **addressed.** `MAX_EXTENSION_DEPTH = 16`, normatively (`11-extensions.md`). |
| relationship abuse | 2 | partly addressed: self-reference, duplicates and detectable cycles are rejected. No cap. |
| evidence fan-out | 2, 3 | not addressed. A consumer bounds its own walk (`07-provenance-and-evidence.md`). |
| contradictory events | 3 | **deliberately not addressed.** `CONTRADICTS` records the disagreement; SC-OES does not adjudicate. |
| semantic poisoning | 1, 3 | not addressed. A producer asserting false semantics validly is a trust problem, not a syntax one. |
| reserved-namespace impersonation | 2 | **addressed.** An unrecognised `sc.*` type is `C = FAIL`; an unknown governed ontology term is `E = FAIL`. |
| malicious third-party ontology terms | 2 | bounded: third-party identifiers are opaque, unfetched and uninterpreted. |
| security-marking misuse | 2, 3 | not addressed. SC-OES transports markings and enforces nothing (`10-security-markings.md`). |
| synthetic/live confusion | 1, 3 | the CDM's existing synthetic/live distinction applies. All committed examples in this tree are synthetic. |
| unsupported semantic versions | 2 | **addressed.** Unknown majors are transportable and uninterpreted (`12-versioning.md`). |
| resource exhaustion | 2 | deployment resource policy, plus the one structural bound. |

Normative:

> A conformance `PASS` on any dimension MUST NOT be represented as a security assurance. It states
> that a record is well-formed and that its governed semantics are recognised, and nothing about
> whether its content is true or its producer legitimate.

## Structural bounds versus resource policies

Normative:

> The extension depth bound is a normative SC-OES structural conformance and resource-safety
> constraint: every conformant implementation applies it identically.

> Maximum message size, maximum list length, memory limits and processing limits are **deployment
> resource policies**. Implementations MAY enforce them. They are not SC-OES interoperability
> requirements, and a document MUST NOT state one as though it were.

> This specification establishes no normative maximum count for `event_relations`,
> `entity_relations` or `evidence` in v0.1.0.

The reason for keeping these apart is that each collapse fails in its own direction. A stated list
cap would make an implementation accepting one more entry non-conformant, which v0.1.0 has no basis
for. A depth bound left to local policy would let two conformant implementations disagree about
whether the same event is valid.

## Replay semantics

Normative:

> The same deterministic event identity received again does not automatically represent a new
> occurrence.

> A consumer SHOULD distinguish *the same event retransmitted* from *a new occurrence*, and MUST NOT
> assume that a repeated identity is either one without deciding.

> No cryptographic anti-replay mechanism is implemented in v0.1.0.

Deterministic identity means a duplicate delivery is *recognisable*, which is what makes the
distinction possible at all. It is not an anti-replay mechanism: an adversary who can inject events
can inject an old one, and nothing in v0.1.0 detects that this happened rather than the producer
re-sending.

*(Non-normative.)* The two failure modes are opposite and both real. Treating every repeated
identity as a duplicate loses genuinely repeated occurrences a producer distinguishes by time.
Treating every arrival as new inflates counts, and an inflated count of interference observations
looks exactly like an escalation. Which is correct depends on the producer's own identity
derivation, which is why the consumer has to decide rather than the specification.

## Staleness

Normative:

> This specification defines no universal event staleness duration, and an implementation MUST NOT
> assume one.

Staleness is determined from what is actually available:

```text
effective_to
lifecycle
domain semantics
profile semantics
```

An event whose `effective_to` has passed states that the represented condition has ended. An event
with no `effective_to` states nothing about its own end, and MUST NOT be aged out on the strength of
a default (`04-temporality.md`, `05-lifecycle.md`).

*(Non-normative.)* A universal duration would be wrong in both directions by orders of magnitude: a
GNSS interference observation is stale in minutes, a runway closure is current for days, and an
airspace restriction may be indefinite. A profile is where a domain-appropriate expectation belongs,
and a deployment may hold a stricter one — neither is a property of the wire format.

## Offline as a security property

Normative:

> Core validation and conformance assessment MUST complete with no network access of any kind.

No fetch, no DNS resolution, no filesystem or data-URI read of a remote reference, no redirect, no
RDF load, no schema-registry call, no ontology-server call. All required contract data is packaged
locally.

This is a security property and not only a convenience: it means a hostile identifier or URI in an
event cannot cause a validator to make a request, and that a validator's behaviour does not depend
on a service reachable by anybody else. `07-provenance-and-evidence.md` and `09-entity-semantics.md`
state the same rule where the fetchable-looking values actually appear.

## Reporting

Security reporting for this specification and its implementation follows
`../governance/SECURITY-REPORTING.md`.
