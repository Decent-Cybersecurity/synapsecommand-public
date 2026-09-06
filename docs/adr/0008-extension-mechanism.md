# ADR 0008 — Extension mechanism

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

Amended by SA.1 — M, 2026-09-06 (SA.1 §13, §24–§29, §44–§57, §60, §83). The mechanism is unchanged:
one bag, `x.<namespace>.<name>` keys, `sc.*` reserved and undefined in v0.1, `MAX_EXTENSION_DEPTH =
16`, no universal list caps, extensions never interpreted. What SA.1 fixes is three things this ADR
left to interpretation — the exact key grammar (decision 3), the exact depth-counting algorithm
(decision 7), and the *description* of the depth limit, which is a normative structural
conformance and resource-safety constraint and is no longer called operational semantics
(decision 8). Still Accepted.

## Context

§29 fixes the mechanism in three lines: one declared extension bag, `oes.extensions`, typed
`dict[str, Any]`, and "the rest of `OesMetadata` remains strict." §30 fixes the namespace —
third-party keys are `x.<namespace>.<name>` (`x.acme.radar_quality`), `sc.*` "is reserved for
future governed SC-OES extensions" — and adds a rule for this version:

> **v0.1 rule.** No governed `sc.*` extensions are defined. Therefore any `sc.*` extension key in
> v0.1 is rejected as: "reserved but undefined." Do not create an extension registry merely to
> represent an empty governed set. Create one only when the first governed extension exists.

§31 gives the semantics: unknown valid `x.*` extensions "must survive validation; must survive
serialization; must survive round-trip; are not interpreted; are not promoted into core fields;
are ignored by consumers that do not understand them", and "an extension may not redefine a core
field" — with `x.acme.confidence` named as the example that "must not be interpreted as a
replacement for `oes.confidence`".

§32 sets one structural bound, `MAX_EXTENSION_DEPTH = 16`, counted over "nested JSON containers
under an individual extension value", with raising it compatible and lowering it potentially
breaking. §33 forbids the bound's obvious generalisation: no universal maximum counts for
`event_relations`, `entity_relations` or `evidence` in v0.1, because deployment limits "are
resource policies, not universal operational semantics" and "the specification must distinguish
the two." *(SA.1 §44–§45 keeps that distinction and corrects the term on the other side of it: the
depth bound is a normative structural conformance and resource-safety constraint, not operational
semantics. §33 is quoted here as M wrote it; decision 8 carries the corrected wording.)*

**This repository has already made the strict-with-one-hatch decision once, for the CDM, and wrote
down why.** `models.py:10`–`:15`: "A canonical model whose objects accept unknown keys is not
canonical — it is a dict with a docstring. `additionalProperties: false` is what the Track
contract already does, and the reason the strictness is safe here is that the CDM pairs it with a
DECLARED escape hatch: `Entity.attributes` and `Event.payload` accept anything, so an adapter
never has to choose between dropping a field and failing validation. Strict where the meaning is
fixed, open where it is not, and the boundary between the two written down." `models.py:17`–`:20`
gives the failure mode of the alternative: `extra="allow"` on the objects themselves "puts
source-specific fields at the same level as canonical ones, and six months later nobody can tell
which fields the model guarantees and which one adapter happens to send."

The bag itself is `Attributes = dict[str, Any]` (`models.py:74`), with the note at
`models.py:72`–`:73`: "`Any` is deliberate: this is where a source's own shape lands untouched,
and narrowing it would start dropping the very data the bag exists to keep."

**And the validation discipline is already written.** `Event._payload_shape` (`models.py:336`)
validates the payload against its registered model **without rewriting it**, for three stated
reasons at `models.py:340`–`:344`: the wire form stays plain JSON, the exported schema stays
readable, and "extra keys survive byte-identically instead of being round-tripped through a model
that might reorder or coerce them. Validation is a CHECK here, not a transformation."

§127 names the resource-safety consequences this mechanism has to answer for: "malicious extension
data", "deep nesting", "oversized payloads", "resource exhaustion".

## Decision

**`oes.extensions` as §29 gives it: one declared bag inside a strict block, `dict[str, Any]`,
namespaced keys, preserved and never interpreted, with one universal structural bound and no
universal list caps.**

1. **Exactly one bag.** `OesMetadata` and every model beneath it are `STRICT` (ADR 0001), and
   `extensions` is their single declared escape hatch — the same arrangement `models.py:10`–`:15`
   describes for the canonical objects, applied one level down. There is no second open field
   anywhere in the SC-OES block, which is §11's "the only generic open bag inside it is
   `extensions`".
2. **`extensions: dict[str, Any]`**, the same type and for the same reason as `Attributes`
   (`models.py:74`): narrowing it would start dropping the data it exists to keep.
3. **Keys are namespaced, and `sc.*` is rejected in v0.1 as reserved-but-undefined.** A key is
   either `x.<namespace>.<name>` for third parties, which is accepted on syntax alone, or `sc.*`,
   which §30's v0.1 rule refuses outright with that phrase in the message. A bare unnamespaced key
   is refused, because it is the one shape that cannot be attributed to anybody. **This replaces
   the proposed decision**, which validated an `sc.*` key against a registry of governed
   extensions; §30 forbids creating that registry — "Do not create an extension registry merely to
   represent an empty governed set. Create one only when the first governed extension exists" —
   and a v0.1 validator therefore has nothing to look one up in and nothing to allow.

   **The grammar is exact (SA.1 §25, §28), not a shape.** `namespace` and `name` are each a
   `lower_label`, `[a-z][a-z0-9_]*` — ASCII lowercase, first character a letter, no dot, hyphen,
   slash, colon, whitespace or uppercase — so the whole key is

   ```text
   ^x\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$
   ```

   Exactly three dot-separated parts. `x.acme.radar_quality` and `x.a.value1` are keys;
   `x.acme`, `x..quality`, `x.Acme.radar_quality`, `x.acme.radar-quality`, `acme.radar_quality`
   and a bare `radar_quality` are not. ADR 0003 decision 9 carries the same `lower_label`
   production for the event-type identifiers, deliberately: one production for every namespaced
   surface in SC-OES, so a producer learns the rule once. The character ranges are written out
   rather than spelled `\w`, which in Python would silently admit non-ASCII (SA.1 §86), and
   nothing is case-folded, hyphen-folded or trimmed on the producer's behalf (SA.1 §84–§85) — a
   key with whitespace around it is invalid, not a value to be tidied. **A syntactically
   well-formed `sc.*` key still fails**, because the reservation is about the namespace and not
   about the spelling.
4. **Values are never interpreted.** Nothing in the package reads inside an extension value, maps
   it, normalises it or promotes it to a core field. §31's six properties are satisfied by
   transporting: survive validation, survive serialization, survive round-trip, not interpreted,
   not promoted, ignorable. SA.1 §57 states the same list with two edges made explicit, and both
   are properties of transporting rather than checks to add: a valid unknown `x.*` extension is
   **never normalised into a core field** and is **never silently discarded**. Silently is the
   operative word — a consumer that drops an extension it does not understand produces a record
   that disagrees with what was sent, and nothing in the record says so.
5. **"An extension may not redefine a core field" is enforced by NON-INTERPRETATION, not by
   refusing the key.** §31's example is `x.acme.confidence`, which "must not be interpreted as a
   replacement for `oes.confidence`" — and that same section requires unknown valid `x.*`
   extensions to *survive validation*. A well-formed `x.acme.confidence` is therefore accepted,
   preserved and never read; it cannot shadow `oes.confidence` because nothing in this package
   ever consults an extension value for a core meaning. **This corrects the proposed decision**,
   which refused any key whose trailing `<name>` collided with a declared `OesMetadata` field.
   That refusal would have contradicted §31's survival requirement, and it defended against a
   threat decision 4 already removes structurally: a value nothing reads cannot redefine anything.
6. **Extension processing is never required for transport.** Conformance dimension B (ADR 0009)
   asserts that the block is structurally valid, including that extension keys are well-formed and
   within the depth bound (§36 lists "extension namespace" and "extension nesting bound"); it
   asserts nothing about extension *content*. A profile may require an extension, and then it is
   dimension D that says so, against the profile the caller named (§38).
7. **One universal structural bound: `MAX_EXTENSION_DEPTH = 16`, with the counting algorithm
   frozen.** §32 fixes the value and the counting *rule* — nested JSON containers under an
   individual extension value — and §32 permits the constant to "follow repository style", which
   it already does: an upper-case module-level constant, in the manner of `SCHEMA_VERSION`
   (`version.py:114`) and `KINDS` (`models.py:434`). §32's asymmetry is recorded with it: raising
   the limit later is compatible, lowering it is potentially breaking, so the bound ships with the
   block rather than arriving after producers exist.

   **A rule is not an algorithm, and two implementations counting differently is the same defect
   as two implementations parsing differently.** SA.1 §46–§54 freezes the count:

   ```text
   scalar (null, boolean, number, string)   depth 0
   object or array as the extension value   depth 1
   each further nested object or array      +1
   object property names                    contribute nothing
   empty {} or []                           still a container, so still 1
   accepted                                 depth <= 16
   rejected                                 depth >= 17
   ```

   Worked: `"x.acme.quality": 0.95` is 0. `"x.acme.data": {}` and `"x.acme.data": []` are both 1.
   `{"sensor": {"quality": 0.9}}` is 2 — outer object 1, `sensor` object 2, the scalar adds
   nothing. `[{"samples": [1, 2, 3]}]` is 3 — array 1, object 2, `samples` array 3. **The depth is
   the maximum over the value's container paths, and it is computed per extension key, never once
   across the bag** (SA.1 §54): `{"x.a.one": {"a": {"b": 1}}, "x.b.two": {"c": {"d": 2}}}` is two
   values of depth 2, not one of depth 3. An extension whose value reaches 17 fails validation,
   and the refusal names the key, the depth calculated and the maximum accepted — "extension
   x.acme.data has nesting depth 17; maximum permitted depth is 16" is the shape (SA.1 §51, §83),
   deterministic and with no stack trace and no internal detail in it.
8. **No universal list-size caps, and the distinction is normative text rather than a silence.**
   §33 forbids arbitrary maximum counts for `event_relations`, `entity_relations` and `evidence`
   in v0.1. **This removes a clause from the proposed decision**, which extended the depth bound
   to the length of those three lists. What replaces it is §33's own distinction, written into
   `11-extensions.md` and `14-security-considerations.md` (§117): implementations MAY enforce a
   maximum message size, a maximum list length, memory limits and processing limits, and those are
   *resource policies* — local, deployment-specific, not part of the interoperability contract —
   whereas the depth bound is a **normative SC-OES structural conformance and resource-safety
   constraint** that every implementation applies identically. A document that stated a list cap
   would make an implementation that accepted one more entry non-conformant, which is a claim v0.1
   has no basis for.

   **The depth bound is not operational semantics, and SA.1 §44–§45 corrects the word this ADR
   used for it.** Nesting depth is not meaning: what an event *means* is carried by `EventClass`,
   `type_id`, the event and entity relations, the lifecycle, the effective interval and the
   ontology relationships. `MAX_EXTENSION_DEPTH` says nothing about any of them; it says how much
   structure a conformant implementation must be willing to walk. Both are universal and both are
   normative, which is why the two were easy to conflate and why keeping them apart matters — a
   reader who takes the depth limit for a semantic rule will look for the meaning of 16, and there
   is none to find. §33's own sentence, quoted above, draws the same contrast with the older word;
   SA.1 replaces the word, not the contrast.
9. **Typed SC-OES payloads follow `_payload_shape` exactly.** `OES_PAYLOAD_MODELS` is keyed by
   `type_id` (§111); validation is a check and never a transformation; the payload dict stays as
   the producer wrote it; an unregistered `type_id` leaves the payload free-form and transportable.
   That is `models.py:305`'s documented behaviour and §124's unknown-semantics requirement at once
   — the same mechanism serving both, rather than two mechanisms that must be kept in step.

## Alternatives considered

**A — make `OesMetadata` itself `extra="allow"`, so any key rides at the top of the block.**
Simplest, and lossless by construction. Rejected by §29 ("the rest of `OesMetadata` remains
strict") and on `models.py:17`–`:20`, which describes the resulting state precisely: nobody can
tell later which fields the model guarantees and which one producer happens to send. It would also
make §31's "an extension may not redefine a core field" unenforceable, since a stray key sitting
beside a real field is exactly a redefinition attempt with nothing to distinguish it.

**B — a typed extension model with a registry, so each extension has a declared shape.** More
rigorous, and it would make extension content validatable. Rejected for v0.1 by §30's "Do not
create an extension registry merely to represent an empty governed set", and as contrary to §31's
purpose: extensions exist for semantics this specification does not govern, and requiring a
registered shape before a third party may extend makes the mechanism useless for the case it is
for. §112's payload registry already covers the governed-and-typed case.

**C — reuse `Event.payload` for extensions instead of adding a bag.** Rejected for ADR 0001's
reason: `payload` is the *source's* never-drop bag (`models.py:329`), and SC-OES extensions are
statements in SC-OES's own frame. Mixing them makes "which of these keys did the source send?"
unanswerable, which is the question `payload` exists to keep answerable.

**D — no bound on nesting, on the ground that the bag must not drop data.** Rejected: §32 requires
the bound, §127 names "deep nesting" and "resource exhaustion" as threats, and an unbounded
recursive structure from an untrusted producer is a resource-exhaustion surface in every consumer,
not only in this one. Sixteen is high enough to refuse pathological input and not real data, and
refusing loudly is different from dropping silently — the producer is told, which is what
`models.py:277`'s register calls a translation defect rather than data.

**E — allow unnamespaced keys and treat them as third-party by convention.** Rejected: the key is
the only place the owner of an extension is recorded, so an unnamespaced key is an extension
nobody owns and nobody can deprecate under §122.

**F — extend the depth bound to list lengths, so one number covers every recursive surface.** This
ADR's proposed decision 7. Rejected by §33 in as many words. It is the tidier engineering answer
and the wrong specification answer: a universal list cap turns a local resource decision into an
interoperability rule, and the first deployment that legitimately needs one more evidence entry
would be non-conformant rather than merely large.

## Consequences

- One field on `OesMetadata`, one key-syntax validator, one `sc.*` refusal, one depth bound.
- **One fewer check than the proposed design**, deliberately: no core-field collision refusal
  (decision 5) and no list caps (decision 8).
- No new dependency; the validators are a regex and a recursive descent over the value.
- Extensions appear in the published schema as an object with `additionalProperties: true`,
  which is how `Entity.attributes` and `Event.payload` already publish — the shape a consumer
  outside Python needs in order to know the bag is open on purpose.
- `sc.*` extension keys become a governed space only when the first one is defined; until then the
  namespace is reserved and empty, and the refusal message says which (§30). The proposal process
  that would create one is §119's shape adapted for extensions, which is round SB's governance
  work rather than a code consequence.
- A profile that requires an extension states it in its own document (§113) and is checked by
  dimension D, not by the core.
- `MAX_EXTENSION_DEPTH` is a public importable name and joins `__init__.py`'s hand-written
  `__all__`, so it can be read by a consumer rather than rediscovered from a refusal.

## Compatibility impact

- **Forward-compatible by design.** A producer adds an `x.*` extension key; an older consumer
  validates the block, sees a key it does not know, keeps it and ignores it (§31). No version
  moves, because the bag was declared from the first release.
- **Adding a governed `sc.*` extension later is additive** and needs no schema change: the bag's
  type does not move. It is a registry and specification change, and it *relaxes* decision 3's
  refusal for exactly the keys it defines — which is a widening, not a break.
- **No effect on the CDM's own extensibility.** `Entity.attributes` and `Event.payload` are
  untouched by this decision, and `tests/test_cdm_schemas.py:63`'s `additionalProperties: false`
  on the four canonical kinds is unaffected — the bag is inside a declared field, not beside one.
- **The depth bound is a *new refusal*, so it must be introduced with the block** rather than
  tightened later: a bound added after producers exist would reject data that used to validate.
  §32 states the asymmetry and decision 7 is why it is in this ADR and not deferred.
- **Declining the list caps costs nothing forward.** Adding a cap later would be the breaking
  direction, which is another reason §33's answer is the safe one to ship.

## Security impact

- **Resource safety is the concrete threat, and §127 names four faces of it**: malicious extension
  data, deep nesting, oversized payloads, resource exhaustion. The bound in decision 7 is the
  universal control; decision 8's deployment policies are where the rest belongs, and saying so
  explicitly is what stops an implementer from reading the absence of a list cap as permission to
  accept anything.
- **Extensions are attacker-controlled data.** Decision 4 keeps them inert: nothing is
  interpreted, so nothing in an extension can change how a core field is read. That is the
  structural version of §31's "an extension may not redefine a core field", and decision 5 records
  why the structural version is the *only* one that is both safe and compliant — a refusal would
  have broken §31's survival requirement while buying nothing a non-reading consumer did not
  already have.
- **Namespacing is attribution, and the reserved namespace is defended.** §127 names
  "reserved-namespace impersonation"; an `sc.*` key from any producer is refused in v0.1, so a
  third party cannot dress its own semantics as governed ones — and because no governed `sc.*`
  extension exists yet, the refusal is total rather than a lookup that could go stale.
- **Preservation is a security property, not only a fidelity one.** §124's requirement that
  unknown semantics survive transit unreinterpreted is what keeps an audit trail honest: a
  consumer that dropped an extension it did not understand would produce a record that disagrees
  with what was sent, and the disagreement would be invisible.
- **No extension can carry a security marking into a place that interprets it.** Markings live in
  `oes.security` and are transported only (ADR 0001, §86); an extension is likewise transported
  only, so neither is a route to enforcement this repository does not implement.

## Reversibility

High for the mechanism, low for the namespace.

The bag is a declared optional-valued field with a default, so it can be deprecated the way ADR
0001 describes for `oes` itself. The depth bound can be raised without breaking anybody (it
accepts strictly more) but not lowered — §32 says so and decision 7 records it. Decision 3's
blanket `sc.*` refusal is reversible in the widening direction only, one governed key at a time.

What is not reversible is the key grammar and the reservation of `sc.*` for governed extensions:
those are published identifiers under §13, and every key minted under them is a commitment. That
is the same exposure ADR 0003 carries and is managed the same way — the grammar is confirmed once,
early, and not revisited casually.
