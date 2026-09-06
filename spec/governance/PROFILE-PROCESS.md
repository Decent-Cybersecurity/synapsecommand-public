# Profile proposal process

**SC-OES v0.1.0 — Draft.**

This document governs the addition of an SC-OES profile. A profile is a domain's agreement about
which governed event types it uses, what it requires of them, and what a conformance claim against
it means. Seven profiles exist in v0.1.0 (`../sc-oes/profiles/`); this process is how an eighth
arrives.

## What a proposal must contain

Normative:

> A proposal for a profile MUST contain every field below. A proposal missing any field is
> incomplete and is not assessed.

```text
scope
domain
event types
ontology modules
version
maturity
required conformance rules
extension model
security considerations
```

| Field | What it must establish |
|---|---|
| scope | what the profile covers, and — explicitly — what it does not |
| domain | the domain segment its governed types use |
| event types | which governed types are in scope, each already accepted or proposed alongside |
| ontology modules | which ontology modules its terms come from |
| version | `0.1.0` for a new profile, declared independently of every other version axis |
| maturity | the entry maturity, normally `EXPERIMENTAL` |
| required conformance rules | what dimension D checks for this profile, stated as checkable rules |
| extension model | which `x.*` extensions the domain expects, and why none of them is a missing core concept |
| security considerations | what an adversary gains from false assertions in this domain |

## Required conformance rules are the substance

Normative:

> A profile's required conformance rules MUST be stated as rules a dimension D implementation can
> check against a single event, or against a bundle the caller supplied.

> A profile MUST NOT state a rule that depends on data an implementation would have to fetch.

> A profile MUST NOT restate a core rule from `../sc-oes/`. It constrains; it does not duplicate.

> A profile MUST NOT weaken a core rule. Where a profile appears to permit what the core forbids,
> the core wins and the profile is a defect.

*(Non-normative.)* A profile with no checkable rules is a document that cannot be conformed to, and
the permitted claim "SC-OES *&lt;Profile&gt;* Profile Conformant" would then mean nothing. That is
the state the six specification-only profiles are honestly in for v0.1.0, which is why each says so
in as many words rather than implying a claim is available. The restatement rule matters for the
opposite reason: a profile that copies a core rule acquires a second place for it to go stale, and
the copy is the one a domain reader will find.

## Scope must state its non-goals

Normative:

> A profile's scope MUST state what it excludes, and MUST NOT rely on omission to do it.

An excluded concept named as excluded answers the next proposer. An unmentioned one gets proposed
against this profile repeatedly.

## Implementation status must not overclaim

Normative:

> A profile MUST state its implementation status explicitly, and MUST NOT imply that an operational
> adapter implementation exists where one does not.

In v0.1.0 exactly one profile is reference producer-backed and six are specification-only. A
specification-only profile is a legitimate state, not a defect — what would be a defect is a
document that left a reader to assume a producer exists.

## Assessment

Normative:

> A proposal MUST be assessed against the fields above, and the assessment MUST name which field, if
> any, it failed.

> A rejection MUST be recorded with its reason, and MUST NOT be deleted.

> An accepted profile MUST be added under `../sc-oes/profiles/`, and its registry representation
> MUST be added where the packaging provides one.

## Changing a profile

Normative:

> A profile's version MUST move when the profile changes, and MUST NOT move because the SC-OES
> specification version or another profile's version moved.

> Adding a governed event type to a profile's scope moves that profile's version.

> Removing a type from a profile's scope, or adding a required conformance rule, is a **breaking**
> change for anybody claiming conformance against it, and is classified per `SC-OES-GOVERNANCE.md`.

> A profile version MUST NOT be raised in the same change that alters what its rules mean.

Retirement of a profile is `DEPRECATION-POLICY.md`'s subject. A retired profile's name is never
reused.
