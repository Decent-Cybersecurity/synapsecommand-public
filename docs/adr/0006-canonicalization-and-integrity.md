# ADR 0006 — Canonicalization and integrity

## Status

Proposed — awaiting M's review.

## Context

§105 asks this ADR to address deterministic serialization, and is explicit about what it is not
asking for: "Do not implement cryptographic signing in this project. However, avoid creating a
format impossible to canonicalize later." It sets a documentation minimum — that JSON key order
has no semantic significance; that consumers must not hash an arbitrary JSON serialization and
assume interoperability; that future signed-event profiles will define explicit canonicalization;
that semantic values must survive serialization independently of property order — and adds:
"Reuse an existing canonicalization mechanism if the repository already has one."

§106 preserves the existing `integrity` architecture and forbids implementing ML-DSA, signature
generation, signature verification, certificate management, key distribution or PKI in this task.
§55 gives `EvidenceRef` an optional `hash` and says it "is descriptive metadata only in v0.1".

**The repository has a hard boundary here, and it is enforced by AST rather than by review.**
`tests/test_cdm_boundary.py:73` declares
`FORBIDDEN_CRYPTO = {"cryptography", "hashlib", "hmac", "nacl", "oqs", "secrets", "ssl"}`, and
`test_no_crypto_in_the_contract_layer` (`:104`) walks every module in the package for an import of
any of them. `hashlib` is on that list. The reasoning is at `models.py:108`–`:113`: `Integrity` is
"DESIGNED, NOT IMPLEMENTED — the field the PQC signature will occupy … The field exists from day
one so that turning signing on is a value change rather than a schema change: a schema change
would be a MAJOR bump rippling through every store and every consumer, and would arrive exactly
when the signing work is already late."

**And the repository already has the canonicalization §105 asks about.** `harness.py:402` renders
with `json.dumps(dumped, indent=2, sort_keys=True)`. `times.py` publishes one serialised time
form; `models.py:24`–`:28` states the policy — "`Timestamp` parses loosely (sources are
undisciplined) and serialises to exactly one string form … Parse wide, emit narrow, publish
narrow" — and `models.py:65` is where the strict pattern is put into the exported schema instead
of the permissive `format: date-time`.

The trap this ADR exists to close is reading "canonicalization" as an instruction to write one.

## Decision

**Document the properties the repository already has, and implement nothing.**

1. **Deterministic key order is already the serialization form.** Golden rendering sorts keys
   (`harness.py:402`), so the repository's own canonical output is byte-stable for a given object.
   That is the existing mechanism §105 says to reuse.
2. **Key order carries no meaning.** This is stated as a property of the contract: two
   serializations of the same object differing only in key order represent the same object. No
   consumer may derive anything from order.
3. **One serialised time form.** `times.render` (`times.py:70`) is the single renderer, and the
   published schema states its pattern (`models.py:65`) rather than accepting anything a
   `date-time` format would. Temporal values therefore survive serialization identically, which is
   §105's fourth minimum applied where round-tripping actually loses information in practice.
4. **Consumers are told, in the specification text, not to hash arbitrary JSON.** §105's second
   minimum is written into the SC-OES core document as a normative statement about what this
   contract does *not* promise: there is no canonical byte form defined for interchange in v0.1,
   only a canonical *object* semantics, and a hash over one producer's serialization is not
   comparable with a hash over another's.
5. **A future signed-event profile defines explicit canonicalization; this version does not.**
   The place for it is a profile document under §89's structure, and the field it would populate
   exists already (`Integrity`, `models.py:107`), which is what "avoid creating a format
   impossible to canonicalize later" costs here: nothing, because the field was designed in.
6. **`oes.evidence[].hash` is a transported string.** It is neither computed nor verified by this
   package. §55 already says so; this ADR records that the boundary test makes it structurally
   true rather than merely intended.
7. **No crypto import, in any module, for any reason.** Including for a convenience checksum,
   including in a validator, including in a helper that "only" fingerprints for caching.
   `tests/test_cdm_boundary.py:104` refuses it and the refusal is correct.

## Alternatives considered

**A — implement JCS (RFC 8785) canonical JSON in the package.** The obvious reading of §105 and
the one that produces a canonicalizer. Rejected on two grounds. It is not needed: nothing in v0.1
consumes a canonical byte form, because nothing signs or verifies (§106). And it is the trap —
canonicalization is the first half of a hashing story, and the second half needs `hashlib`, which
`tests/test_cdm_boundary.py:73` forbids. A canonicalizer with no hash beside it is an unused
function that looks like a promise.

**B — compute `evidence.hash` inside the adapter or the model.** Rejected on the reasoning
`models.py:107`–`:110` gives about signatures generally, which applies unchanged to hashes: a
value computed inside a translator is held by nothing that audits it. It would also need a
forbidden import.

**C — populate `Integrity` for SC-OES events.** Rejected by §106 and by `models.py:110`'s design
intent: the block is there so that enabling signing later is a value change rather than a schema
change. Populating it now would mean implementing signing now.

**D — say nothing about canonicalization on the ground that nothing signs.** Rejected by §105's
own words: the risk it names is "creating a format impossible to canonicalize later", and the
defence against that is to state now which properties hold, while they are cheap to state and
before consumers assume different ones.

**E — declare a canonical byte form for interchange without implementing it.** Rejected as worse
than silence: a declared form nothing produces or checks is a specification claim with no
implementation behind it, which is exactly the shape §138 and this repository's own gate practice
treat as a defect.

## Consequences

- No code. This ADR's implementation is documentation: the properties above go into the SC-OES
  core specification document and are cross-referenced from the conformance document.
- `tests/test_cdm_boundary.py` needs no change, and the fact that it needs no change is the
  evidence that this decision holds.
- A conformance dimension may assert *structural* validity of an evidence entry including the
  presence and shape of `hash`, and must not assert anything about its value. ADR 0009's
  dimension B covers structure only.
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
- **No false assurance.** `models.py:120`–`:122` records the reasoning for the analogous case:
  an unverifiable signature that *looks* present "reads as assurance to everything downstream that
  does not check". A hash this package computed and nothing verified would have the same shape. A
  transported, clearly descriptive `hash` does not.
- **Consumers are warned off the wrong assumption explicitly.** The realistic failure mode is a
  consumer hashing its own serialization of a received object and comparing it with another
  producer's hash of theirs. Decision 4 states in the normative text that this is not supported,
  which is cheaper than the incident.
- **No key material, no certificates, no PKI**, per §106 — so there is nothing in this project to
  steal, expire, rotate or misconfigure.
- The evidence `hash` field is attacker-controlled data like any other transported string, and is
  treated as such: validated for shape, never interpreted.

## Reversibility

High. This ADR adds no mechanism, so there is nothing to unwind. If a future release needs
canonicalization, it is defined then — in a profile, against a model that was designed to receive
it — and none of the properties documented here has to be retracted to make room for it: they are
the preconditions such a definition would need.

The one thing that would be expensive to reverse is the opposite decision. Shipping a
canonicalizer, letting consumers key on its output, and then changing it is a silent
interoperability break with no version to hang it on — which is the concrete reason to prefer
documentation now.
