# ADR 0006 — Canonicalization and integrity

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

## Context

§25 retains this ADR's decision as it stood and fixes the documentation minimum. It is explicit
about what it is not asking for — "Do not implement interchange cryptographic canonicalization in
v0.1" — and lists five things to document:

> JSON object key order has no semantic significance; repository golden rendering may be
> deterministic; that does not define an interoperable canonical byte representation; consumers
> MUST NOT hash arbitrary JSON serialization and assume cross-implementation equality; a future
> signed-event profile will define an explicit canonical representation.

§26 lists what may not be added to the public contract layer — `hashlib`, `hmac`, `cryptography`,
`nacl`, `oqs`, signature generation, signature verification, PKI, certificate handling, key
management — and preserves the existing boundary: "Existing `Integrity` remains a designed future
boundary. Evidence hashes are transported metadata only." §84 says the same of the field itself:
an `EXTERNAL_ARTIFACT` evidence entry may carry an optional `hash`, with "No network retrieval. No
binary embedding. `hash` is descriptive metadata only." §150 lists "signing system" and "PKI"
among the explicit non-goals.

**The repository has a hard boundary here, and it is enforced by AST rather than by review.**
`tests/test_cdm_boundary.py:73` declares
`FORBIDDEN_CRYPTO = {"cryptography", "hashlib", "hmac", "nacl", "oqs", "secrets", "ssl"}`, and
`test_no_crypto_in_the_contract_layer` (`:104`) walks every module in the package for an import of
any of them. `hashlib` is on that list, and the tree's set is a superset of §26's. The reasoning is
at `models.py:108`–`:113`: `Integrity` is "DESIGNED, NOT IMPLEMENTED — the field the PQC signature
will occupy … The field exists from day one so that turning signing on is a value change rather
than a schema change: a schema change would be a MAJOR bump rippling through every store and every
consumer, and would arrive exactly when the signing work is already late."

**And the repository already has the deterministic rendering §25 mentions.** `harness.py:402`
renders with `json.dumps(dumped, indent=2, sort_keys=True)`. `times.py` publishes one serialised
time form; `models.py:24`–`:27` states the policy — "`Timestamp` parses loosely (sources are
undisciplined) and serialises to exactly one string form … Parse wide, emit narrow, publish
narrow" — and `models.py:65` is where the strict pattern is put into the exported schema instead
of the permissive `format: date-time`.

The trap this ADR exists to close is reading "canonicalization" as an instruction to write one.
§25 closes it explicitly; this ADR records that the repository was already in the state §25 asks
for, and what holds it there.

## Decision

**Document the properties the repository already has, and implement nothing.**

1. **Deterministic key order is the repository's golden rendering, and that is all it is.**
   `harness.py:402` sorts keys, so this repository's own output is byte-stable for a given object.
   §25's third minimum is the limit on what that buys: "that does not define an interoperable
   canonical byte representation." The property is stated as a repository fact, never as an
   interchange guarantee.
2. **Key order carries no meaning.** §25's first minimum, stated as a property of the contract:
   two serializations of the same object differing only in key order represent the same object.
   No consumer may derive anything from order.
3. **One serialised time form.** `times.render` (`times.py:70`) is the single renderer, and the
   published schema states its pattern (`models.py:65`) rather than accepting anything a
   `date-time` format would. Temporal values therefore survive serialization identically, which is
   where round-tripping actually loses information in practice.
4. **Consumers are told, in the specification text, not to hash arbitrary JSON.** §25's fourth
   minimum is written into the SC-OES core document (§117's `01-core.md`) and cross-referenced
   from `14-security-considerations.md` as a normative statement about what this contract does
   *not* promise: there is no canonical byte form defined for interchange in v0.1, only a
   canonical *object* semantics, and a hash over one producer's serialization is not comparable
   with a hash over another's.
5. **A future signed-event profile defines explicit canonicalization; this version does not.**
   §25's fifth minimum. The place for it is a profile document under §113's structure, and the
   field it would populate exists already (`Integrity`, `models.py:107`) — which is what "avoid
   creating a format impossible to canonicalize later" costs here: nothing, because the field was
   designed in.
6. **`evidence[].hash` is a transported string.** It is neither computed nor verified by this
   package. §84 says so — "`hash` is descriptive metadata only" — along with the two rules that
   keep it inert: no network retrieval, no binary embedding. This ADR records that the boundary
   test makes it structurally true rather than merely intended.
7. **No crypto import, in any module, for any reason.** Including for a convenience checksum,
   including in a validator, including in a helper that "only" fingerprints for caching.
   `tests/test_cdm_boundary.py:104` refuses it and the refusal is correct. §143 requires the
   boundary tests to keep preventing runtime imports of crypto implementations, so the existing
   test is the mechanism rather than a new one.

## Alternatives considered

**A — implement JCS (RFC 8785) canonical JSON in the package.** The obvious reading of the word
"canonicalization" and the one that produces a canonicalizer. Rejected on two grounds. It is not
needed: nothing in v0.1 consumes a canonical byte form, because nothing signs or verifies (§26,
§150). And it is the trap — canonicalization is the first half of a hashing story, and the second
half needs `hashlib`, which `tests/test_cdm_boundary.py:73` forbids. A canonicalizer with no hash
beside it is an unused function that looks like a promise.

**B — compute `evidence[].hash` inside the adapter or the model.** Rejected on the reasoning
`models.py:107`–`:110` gives about signatures generally, which applies unchanged to hashes: a
value computed inside a translator is held by nothing that audits it. It would also need a
forbidden import, and §84 already rules the field descriptive.

**C — populate `Integrity` for SC-OES events.** Rejected by §26 and by `models.py:110`'s design
intent: the block is there so that enabling signing later is a value change rather than a schema
change. Populating it now would mean implementing signing now.

**D — say nothing about canonicalization on the ground that nothing signs.** Rejected by §25's
own list: it sets a documentation minimum of five statements, and the risk they defend against is
a consumer assuming properties this contract does not have. Stating them now is cheap; the
alternative is discovering the assumption in somebody else's incident.

**E — declare a canonical byte form for interchange without implementing it.** Rejected as worse
than silence: a declared form nothing produces or checks is a specification claim with no
implementation behind it, and §160's audit rule — "Do not claim a test passed if it was not run" —
is the same principle applied to gates.

## Consequences

- No code. This ADR's implementation is documentation: the properties above go into the SC-OES
  core specification document and are cross-referenced from the conformance and
  security-considerations documents (§117).
- `tests/test_cdm_boundary.py` needs no change, and the fact that it needs no change is the
  evidence that this decision holds. §143 asks for the boundary to be preserved, not extended.
- A conformance dimension may assert *structural* validity of an evidence entry including the
  presence and shape of `hash`, and must not assert anything about its value. ADR 0009's
  dimension B covers structure only (§36 lists "evidence structure", not evidence content).
- Future work has a named home: a signed-event profile, at which point canonicalization becomes a
  decision with an implementation behind it rather than a property to preserve.

## Compatibility impact

None. No field is added or changed by this ADR, no serialization behaviour moves, no published
schema differs. Existing golden files are unaffected by this decision — the golden churn in this
campaign is entirely ADR 0005's.

The forward-compatibility property being protected is that a later canonicalization can be defined
over the current object model without a shape change, and it holds because `Integrity` already
exists and because key order carries no meaning today, so fixing an order later removes no
information.

## Security impact

This is the ADR whose security impact is mostly a statement of what is deliberately absent.

- **No cryptography enters the contract layer.** The boundary is enforced by AST over every
  module (`tests/test_cdm_boundary.py:104`), not by convention, so the decision cannot erode by
  accident.
- **No false assurance.** `models.py:121`–`:123` records the reasoning for the analogous case:
  an unverifiable signature that *looks* present "reads as assurance to everything downstream that
  does not check". A hash this package computed and nothing verified would have the same shape. A
  transported, clearly descriptive `hash` does not.
- **Consumers are warned off the wrong assumption explicitly.** The realistic failure mode is a
  consumer hashing its own serialization of a received object and comparing it with another
  producer's hash of theirs. Decision 4 states in the normative text that this is not supported,
  which is cheaper than the incident.
- **No key material, no certificates, no PKI**, per §26 and §150 — so there is nothing in this
  project to steal, expire, rotate or misconfigure.
- **`tampered events` and `spoofed producers` are named in §127 and are not solved here, which is
  the honest position.** §127 says outright that SC-OES "need not solve all of them. It must
  identify trust boundaries honestly." The trust boundary is that everything in `oes` is a
  producer's assertion, verified by nothing in this package; that statement belongs in
  `14-security-considerations.md` rather than in a mechanism that would imply otherwise.
- The evidence `hash` field is attacker-controlled data like any other transported string, and is
  treated as such: validated for shape, never interpreted, never fetched (§84).

## Reversibility

High. This ADR adds no mechanism, so there is nothing to unwind. If a future release needs
canonicalization, it is defined then — in a profile, against a model that was designed to receive
it — and none of the properties documented here has to be retracted to make room for it: they are
the preconditions such a definition would need.

The one thing that would be expensive to reverse is the opposite decision. Shipping a
canonicalizer, letting consumers key on its output, and then changing it is a silent
interoperability break with no version to hang it on — which is the concrete reason to prefer
documentation now.
