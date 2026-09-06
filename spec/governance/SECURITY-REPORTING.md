# Security reporting

**SC-OES v0.1.0 — Draft.**

This document covers reports about SC-OES: a defect in the normative text, or a defect in this
repository's implementation of it, with a security consequence.

## Status of the reporting channel in v0.1.0

*(Non-normative, and stated first because it is the fact a reporter needs.)* No dedicated private
security reporting channel is established for SC-OES as at v0.1.0. This document does not invent
one, and a reporter should not read a process below as evidence that a channel exists that is not
named here. Establishing a private channel — and stating it in a repository-level security policy —
is outstanding work, and until it is done a reporter's options are the ordinary public ones this
repository already offers to contributors (`CONTRIBUTING.md`).

Normative:

> A document in this tree MUST NOT name a security contact, address or channel that has not been
> established.

*(Non-normative.)* A published channel that nobody monitors is worse than none: it converts a report
somebody made into a report nobody received, and the reporter has no way to tell the difference. So
the gap is written down as a gap.

## What is in scope for a security report

- A normative statement in `../sc-oes/` whose correct implementation is unsafe.
- A statement that overclaims — text implying SC-OES provides an assurance that
  `../sc-oes/14-security-considerations.md` says it does not.
- A defect in this repository's validation, conformance or registry code with a security
  consequence: a validator that accepts what the specification forbids, a bound that is not
  enforced, a code path that makes a network request where the specification requires none.
- A packaged registry or ontology artefact that does not match the source it is generated from.

## What is not in scope, and why

Normative:

> The following are not security defects in SC-OES, because the specification states plainly that it
> does not address them (`../sc-oes/14-security-considerations.md`):

- A producer asserting false semantics in a well-formed event. SC-OES carries a producer's claims and
  does not verify them; producer authentication and trust are the deployment's.
- The absence of signing, integrity verification or cryptographic anti-replay. None is implemented in
  v0.1.0, deliberately, and `docs/adr/0006-canonicalization-and-integrity.md` records why.
- The absence of a normative maximum message size, list length or evidence-chain bound. Those are
  deployment resource policies.
- A security marking that is not enforced. SC-OES transports markings and enforces nothing; it is not
  a cross-domain guard (`../sc-oes/10-security-markings.md`).
- Two contradictory events both validating. `CONTRADICTS` records a disagreement; adjudicating it is
  not SC-OES's.

A report that one of these is unaddressed is not a vulnerability report. A report that a *document*
claims one of them is addressed is one, and belongs in the list above.

## What a report should contain

*(Non-normative — this is guidance to a reporter, not a requirement placed on one. A report missing
any of it is still worth making.)*

- Which document and clause, or which file and line, the defect is in.
- What an adversary gains, and what they need in order to gain it.
- A concrete case: an input, and the wrong behaviour it produces.
- Whether the defect is in the specification, in the implementation, or in the disagreement between
  them.
- Whether any published artefact is affected.

## How a report is handled

Normative:

> A report MUST be assessed against `../sc-oes/14-security-considerations.md`'s trust boundaries, and
> the assessment MUST say which boundary the defect sits on.

> Where a report shows that a document claims an assurance the specification does not provide, the
> document MUST be corrected at the sentence that overclaims — never by weakening the surrounding
> text to make the claim defensible.

> A fix to normative text MUST be classified per `SC-OES-GOVERNANCE.md`. A security motive does not
> make a substantive change editorial.

> A dated record that has become false gains a dated correction beside it, and is not rewritten.

## Coordinated disclosure

*(Non-normative.)* No embargo period, disclosure timetable or advisory format is established for
SC-OES as at v0.1.0, for the same reason no channel is: committing to a timetable nobody is
resourced to meet would mislead a reporter about what to expect. A reporter who wants coordination
should say so in their report and agree it explicitly rather than relying on a policy this document
does not yet have.
