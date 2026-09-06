# ADR 0008 — Extension mechanism

## Status

Proposed — awaiting M's review.

## Context

§60 requires "explicit forward-compatible extensions", prefers the field `oes.extensions` or "an
architecture-consistent equivalent", and sets five rules: the `sc.*` extension namespace is
reserved; unknown extensions are preserved; unknown extensions are ignored by consumers that do
not understand them; extensions must not redefine normative core semantics; and extension
processing must not be required for generic SC-OES transport unless a declared profile explicitly
requires it. Third-party keys are namespaced, with `x.acme.radar_quality` as the example.

§61 adds the lossless requirement — typed semantic payloads validate known fields "without
destroying additional source-specific fields", and "The repository's existing lossless philosophy
must remain."

**This repository has already made this decision once, for the CDM, and wrote down why.**
`models.py:10`–`:15`: "A canonical model whose objects accept unknown keys is not canonical — it
is a dict with a docstring. `additionalProperties: false` is what the Track contract already
does, and the reason the strictness is safe here is that the CDM pairs it with a DECLARED escape
hatch: `Entity.attributes` and `Event.payload` accept anything, so an adapter never has to choose
between dropping a field and failing validation. Strict where the meaning is fixed, open where it
is not, and the boundary between the two written down." `models.py:17`–`:20` gives the failure
mode of the alternative: `extra="allow"` on the objects themselves "puts source-specific fields at
the same level as canonical ones, and six months later nobody can tell which fields the model
guarantees and which one adapter happens to send."

The bag itself is `Attributes = dict[str, Any]` (`models.py:74`), with the note at
`models.py:71`–`:73`: "`Any` is deliberate: this is where a source's own shape lands untouched,
and narrowing it would start dropping the very data the bag exists to keep."

**And the validation discipline is already written.** `Event._payload_shape` (`models.py:336`)
validates the payload against its registered model **without rewriting it**, for three stated
reasons at `models.py:339`–`:344`: the wire form stays plain JSON, the exported schema stays
readable, and "extra keys survive byte-identically instead of being round-tripped through a model
that might reorder or coerce them. Validation is a CHECK here, not a transformation."

§110 names the resource-safety consequence: "unknown extensions must not permit unbounded
structural recursion."

## Decision

**`oes.extensions` as §60 prefers: one declared bag inside a strict block, `dict[str, Any]`,
namespaced keys, preserved and never interpreted, with an explicit structural bound.**

1. **Exactly one bag.** `OesMetadata` and every model beneath it are `STRICT` (ADR 0001), and
   `extensions` is their single declared escape hatch — the same arrangement `models.py:10`–`:15`
   describes for the canonical objects, applied one level down. There is no second open field
   anywhere in the SC-OES block.
2. **`extensions: dict[str, Any]`**, the same type and for the same reason as `Attributes`
   (`models.py:74`): narrowing it would start dropping the data it exists to keep.
3. **Keys are namespaced and the namespace is validated.** A key is either `sc.<name>` — reserved
   for extensions governed by the SynapseCommand public specification — or
   `x.<namespace>.<name>`, for third parties. Validation is on the key's *syntax* and, for `sc.*`,
   on the key being governed, exactly as ADR 0003 does for `type_id`. A bare unnamespaced key is
   refused, because it is the one shape that cannot be attributed to anybody.
4. **Values are never interpreted.** Nothing in the package reads inside an extension value, maps
   it, normalises it or promotes it to a core field. Extensions are transported.
5. **Extensions must not redefine core semantics**, and this is checkable rather than exhortatory:
   an extension key whose `<name>` collides with a declared field of `OesMetadata` is refused, so
   `x.acme.confidence` cannot become a second, shadow `confidence`.
6. **Extension processing is never required for transport.** Conformance dimension B (ADR 0009)
   asserts that the block is structurally valid, including that extension keys are well-formed;
   it asserts nothing about extension *content*. A profile may require an extension, and then it
   is dimension D that says so — which is exactly §60's last rule.
7. **Bounded depth, and it is a validation rule rather than an inherited property.**
   `dict[str, Any]` is recursive by type, so §110's requirement is met by a validator that refuses
   an extension value nested beyond a declared maximum depth, and by the same bound on
   `event_relations[]`, `entity_relations[]` and `evidence[]` length. The bound is stated in the
   SC-OES core specification, is the same for every producer, and the refusal message names the
   key and the depth reached.
8. **Typed SC-OES payloads follow `_payload_shape` exactly.** `OES_PAYLOAD_MODELS` is keyed by
   `type_id`; validation is a check and never a transformation; the payload dict stays as the
   producer wrote it; an unregistered `type_id` leaves the payload free-form and transportable.
   That is `models.py:305`'s documented behaviour and §27's unknown-semantics requirement at once
   — the same mechanism serving both, rather than two mechanisms that must be kept in step.

## Alternatives considered

**A — make `OesMetadata` itself `extra="allow"`, so any key rides at the top of the block.**
Simplest, and lossless by construction. Rejected on `models.py:17`–`:20`, which describes the
resulting state precisely: nobody can tell later which fields the model guarantees and which one
producer happens to send. It would also make §60's "extensions must not redefine normative core
semantics" unenforceable, since a stray key sitting beside a real field is exactly a redefinition
attempt with nothing to refuse it.

**B — a typed extension model with a registry, so each extension has a declared shape.** More
rigorous, and it would make extension content validatable. Rejected for v0.1 as premature and as
contrary to §60's purpose: extensions exist for semantics this specification does not govern, and
requiring a registered shape before a third party may extend makes the mechanism useless for the
case it is for. §62's payload registry already covers the governed-and-typed case.

**C — reuse `Event.payload` for extensions instead of adding a bag.** Rejected for ADR 0001's
reason: `payload` is the *source's* never-drop bag (`models.py:329`), and SC-OES extensions are
statements in SC-OES's own frame. Mixing them makes "which of these keys did the source send?"
unanswerable, which is the question `payload` exists to keep answerable.

**D — no bound on nesting, on the ground that the bag must not drop data.** Rejected: §110
requires the bound, and an unbounded recursive structure from an untrusted producer is a
resource-exhaustion surface in every consumer, not only in this one. The bound is set high enough
that it refuses pathological input and not real data, and refusing loudly is different from
dropping silently — the producer is told, which is what `models.py:275`'s register calls a
translation defect rather than data.

**E — allow unnamespaced keys and treat them as third-party by convention.** Rejected: the key is
the only place the owner of an extension is recorded, so an unnamespaced key is an extension
nobody owns and nobody can deprecate under §96.

## Consequences

- One field on `OesMetadata`, one key-syntax validator, one depth bound, one collision check.
- No new dependency; the validators are regexes and a recursive descent over the value.
- Extensions appear in the published schema as an object with `additionalProperties: true`,
  which is how `Entity.attributes` and `Event.payload` already publish — the shape a consumer
  outside Python needs in order to know the bag is open on purpose.
- `sc.*` extension keys become a governed space needing the same proposal process as event types
  (§93 adapted per §95's shape), which is a governance consequence for Phase 3 rather than a code
  one.
- A profile that requires an extension states it in its own document (§89's "extension behavior"
  section) and is checked by dimension D, not by the core.

## Compatibility impact

- **Forward-compatible by design, which is §60's first sentence.** A producer adds an extension
  key; an older consumer validates the block, sees a key it does not know, keeps it and ignores
  it. No version moves, because the bag was declared from the first release.
- **Adding a governed `sc.*` extension later is additive** and needs no schema change: the bag's
  type does not move. It is a registry and specification change.
- **No effect on the CDM's own extensibility.** `Entity.attributes` and `Event.payload` are
  untouched by this decision, and `tests/test_cdm_schemas.py:63`'s `additionalProperties: false`
  on the four canonical kinds is unaffected — the bag is inside a declared field, not beside one.
- The depth bound is a *new refusal*, so it must be introduced with the block rather than
  tightened later: a bound added after producers exist would reject data that used to validate.
  That is why decision 7 is in this ADR and not deferred.

## Security impact

- **Resource safety is the concrete threat, and §110 names it.** The bound in decision 7 is the
  control. Without it, `dict[str, Any]` is an unbounded recursive structure supplied by whoever
  writes the event.
- **Extensions are attacker-controlled data.** Decision 4 keeps them inert: nothing is
  interpreted, so nothing in an extension can change how a core field is read. This is the
  structural version of §60's "must not redefine normative core semantics", and decision 5 makes
  the shadowing attempt itself refusable.
- **Namespacing is attribution.** A `sc.*` key from a producer that does not own the namespace is
  refused (ADR 0003's rule applied to extension keys), so a third party cannot dress its own
  semantics as governed ones.
- **Preservation is a security property, not only a fidelity one.** §27's requirement that unknown
  semantics survive transit unreinterpreted is what keeps an audit trail honest: a consumer that
  dropped an extension it did not understand would produce a record that disagrees with what was
  sent, and the disagreement would be invisible.
- **No extension can carry a security marking into a place that interprets it.** Markings live in
  `oes.security` and are transported only (ADR 0001, §58, §59); an extension is likewise
  transported only, so neither is a route to enforcement this repository does not implement.

## Reversibility

High for the mechanism, low for the namespace.

The bag is a declared optional-valued field with a default, so it can be deprecated the way ADR
0001 describes for `oes` itself. The depth bound can be raised without breaking anybody (it
accepts strictly more) but not lowered.

What is not reversible is the key grammar and the reservation of `sc.*` for governed extensions:
those are published identifiers under §26, and every key minted under them is a commitment. That
is the same exposure ADR 0003 carries and is managed the same way — the grammar is confirmed once,
early, and not revisited casually.
