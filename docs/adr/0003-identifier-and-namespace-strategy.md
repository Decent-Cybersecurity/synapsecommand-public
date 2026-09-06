# ADR 0003 — Identifier and namespace strategy

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

## Context

SC-OES introduces identifier spaces that become public API on first publication. §13 says so
directly of the ontology namespace — "Once published, identifiers are permanent public API" — and
§49 says it of the semantic majors: a breaking semantic revision becomes `v2`, and "Do not
redefine `v1`."

Four spaces are in scope.

- **Governed event type identifiers.** §14: `sc.<domain>.<event_name>.v<major>`.
- **Third-party event type identifiers.** §14: `x.<namespace>.<domain>.<event_name>.v<major>`,
  with `sc.*` reserved. "An unknown `sc.*` identifier is not treated as a valid governed type. An
  unknown `x.*` identifier is transportable."
- **Ontology term identifiers.** §13, and this is the space v2 moves.
- **Version axes.** §46–§49 require the SC-OES version, the ontology version, per-profile
  versions and the semantic type major to be documented as separate facts from `SCHEMA_VERSION`
  and `PACKAGE_VERSION`.

**The repository has ruled on identifiers once already, for a different surface, and the ruling
must be read carefully rather than transplanted.** `schemas.py:30`–`:66` is a dated ruling on
schema `$id`s that fixes `BASE_ID = "urn:synapsecommand:cdm"` (`schemas.py:67`). Its reasoning: a
consumer registers a schema under its `$id`, may try to *fetch* it, and compares it to tell
versions apart — so "the requirement is *identify*, not *locate*, and a URN says exactly that"
(`schemas.py:46`). It records what it replaced and why that was wrong, not merely unresolvable:
`https://synapsecommand.local/cdm`, where RFC 6762 reserves `.local` for multicast DNS, "so that
identifier did not just fail to resolve, it asserted a scope that is false for a published
contract" (`schemas.py:49`–`:51`). And — the sentences that decide this ADR — it weighed `tag:`
and it named its own formality:

> "A `tag:` URI (RFC 4151) is the most formally correct non-dereferenceable choice and was
> rejected for obscurity: tooling and readers both handle `urn:` without explanation. And the
> formality is named rather than hidden — `synapsecommand` is not an IANA-registered URN namespace
> under RFC 8141, **which is common practice for JSON Schema `$id`s** and is a smaller problem
> than an identifier that tooling will try to dereference." (`schemas.py:55`–`:60`)

That ruling is about JSON Schema `$id`s, and it says so in the clause that excuses the
unregistered NID. §13 rules the ontology namespace differently, and this ADR records why the two
answers are consistent rather than contradictory.

## Decision

**Event type grammars per §14; ontology terms in the `tag:` URI family per §13; the existing CDM
schema URNs untouched as legacy identifiers; `SC_OES_VERSION` in `version.py`.**

1. **Event type identifiers** are `sc.<domain>.<event_name>.v<major>` for governed semantics and
   `x.<namespace>.<domain>.<event_name>.v<major>` for third parties, validated in the package by
   a regex over §14's grammar: `module`/`domain` lowercase, event name lowercase snake case, an
   explicit `v<number>` major. Validation is checked in **both directions**: a well-formed
   identifier is accepted, and a malformed one is refused with a message naming which rule it
   broke.
2. **`sc.*` is reserved, and an unknown one is not a governed type.** §14: "The `sc.*` namespace
   is reserved. An unknown `sc.*` identifier is not treated as a valid governed type. An unknown
   `x.*` identifier is transportable." Concretely, a `type_id` in the `sc.` namespace that is not
   in the packaged governed registry (ADR 0004) fails dimension C of the conformance model (ADR
   0009), and a well-formed unknown `x.*` is `SKIP` there rather than `FAIL` (§37). This is
   enforceable offline because the registry ships.
3. **Ontology terms are `tag:synapsecommand.com,2026:ontology:<module>:<Term>`.** This replaces
   the `urn:synapsecommand:ontology:<module>:<Term>` form this ADR carried while proposed. §13's
   rules: `module` lowercase, `Term` UpperCamelCase — which is what §13's own examples show
   (`core:OperationalObject`, `core:Capability`, `air:Runway`, `pnt:PNTService`) and what §101's
   worked `Entity` example uses (`tag:synapsecommand.com,2026:ontology:air:Runway`). **No new
   public term is minted under `urn:synapsecommand:`**, which §13 forbids by name.
4. **The existing CDM schema URNs are not changed by this work.** §13: "The repository's existing
   CDM schema URNs remain legacy identifiers and are not changed by this work." `BASE_ID`
   (`schemas.py:67`) stays `urn:synapsecommand:cdm`; the `$id`s built from it at `schemas.py:76`
   keep their form. Two identifier families therefore coexist in this repository **deliberately
   and by ruling**, and the boundary between them is stated rather than left to be discovered:
   `urn:synapsecommand:cdm:*` identifies published JSON Schema documents and is legacy;
   `tag:synapsecommand.com,2026:ontology:*` identifies governed ontology terms and is the space
   new terms are minted in.
5. **Third-party ontology identifiers are admitted under §15's three tests.** A third-party
   identifier must be an absolute URI/IRI-like identifier with a valid scheme; must contain no
   control characters and no whitespace; and must not impersonate the governed
   `tag:synapsecommand.com,2026:ontology:` namespace. Unknown third-party identifiers "must be
   preserved. They must never be guessed or mapped to a SynapseCommand term automatically" (§15).
   Dimension E reports them as `UNASSESSED_THIRD_PARTY_TERM` (§39, ADR 0009); it does not grade
   them.
6. **Identifier validation is syntax only at runtime**, with recognition by registry lookup —
   the event registry for `type_id`, the generated `ontology_terms.json` for governed ontology
   terms. This is ADR 0002's split, restated here because it is the reason both grammars can be
   regexes.
7. **`SC_OES_VERSION = "0.1.0"` lives in `version.py`, and `version.py`'s docstring is rewritten
   to name three axes rather than two.** §46 permits this and points at it: "Place it according
   to existing repository version architecture. The existing ADR analysis indicates `version.py`
   is likely the appropriate single version-axis explanation location. Do not derive it from
   `SCHEMA_VERSION` / `PACKAGE_VERSION`." The reading that settles the placement, taken rather
   than assumed: `tests/test_cdm_packaging.py:328`
   (`test_version_py_is_the_only_place_the_distinction_is_explained`) requires the marker
   `WHY THEY MUST BE ALLOWED TO DIVERGE` to appear in exactly one `.py` file, and that file is
   `version.py`. A third version axis introduced in any other module would either restate the
   divergence reasoning there — which that test refuses — or state a version with no explanation
   beside it. `version.py:1` opens "Two version numbers, what each one governs, and why they are
   not one number", so adding the third moves that sentence; moving it is the correct cost, and
   it is a documentation change in the one file the repository has already designated for it.
8. **The other three axes are not Python constants.** The ontology version lives in the `.ttl`
   version metadata (§47: "Store it in ontology metadata. Do not introduce another Python runtime
   constant unless repository architecture makes one necessary"); each profile declares `0.1.0`
   in its own normative document and registry representation (§48); the semantic type major is a
   segment of the `type_id` itself (§49). The reason is the same one `SCHEMA_VERSION` and
   `PACKAGE_VERSION` are separate: an axis belongs where the thing it versions is authored.

## Alternatives considered

**A — `urn:synapsecommand:ontology:<module>:<Term>`, the form this ADR proposed and the one
consistent-by-symmetry with `BASE_ID`.** Rejected by §13 in as many words — "Do **not** mint new
public terms under `urn:synapsecommand:...`" — and, independently, on the `$id` ruling's own
recorded reservation. `schemas.py:57`–`:60` accepts an unregistered URN NID for JSON Schema
`$id`s explicitly *because* that is "common practice for JSON Schema `$id`s". An ontology
vocabulary is not a JSON Schema `$id`: it is a permanent public term space intended for RDF
tooling and third-party reuse, where `tag:` (RFC 4151) is standards-valid without any registry
and `urn:synapsecommand:` is an unregistered NID under RFC 8141 with nothing but this project
behind it. Minting a permanent public vocabulary there is a larger claim than reusing the prefix
for internal `$id`s, and the ruling that excused the smaller claim named the excuse rather than
generalising it.

**B — the `tag:` form, on the ground that `schemas.py:56`–`:57` already called it "the most
formally correct non-dereferenceable choice".** Chosen. The obscurity objection recorded there
was weighed against `urn:`'s familiarity to *JSON Schema* tooling and readers; in RDF, `tag:` is
neither obscure nor unexplained, and the date segment (`,2026`) carries exactly the "minted by
this owner, from this date" claim RFC 4151 is for. §13 rules it, and this ADR records the ground
so that the earlier ruling reads as scoped rather than reversed.

**C — HTTP/HTTPS ontology identifiers (`https://synapsecommand.com/ontology/core#Runway`).** The
conventional RDF choice, and rejected on `schemas.py:38`–`:42`'s already-recorded ground: an
`https://` identifier *invites* retrieval, this repository does not serve these files at any URL
and will not promise to, and an identifier that promises a fetch and 404s is worse than one that
promises nothing. §125's offline requirement points the same way. This is the part of the `$id`
ruling that does generalise, and it is why the answer is a non-dereferenceable scheme in both
cases even though the schemes differ.

**D — flat event type identifiers with no version segment (`sc.pnt.gnss_interference`).**
Rejected: §14 requires an explicit `v<number>`, and §123 depends on it — a consumer that
understands `sc.pnt.gnss_interference.v1` and receives `.v2` "must not assume equivalence", which
it can only do if it can *see* that it is a different major. Without the segment, a breaking
semantic change has nowhere to go but a new name.

**E — put `SC_OES_VERSION` in the new `oes` module instead of `version.py`.** Locally tidier: the
constant sits with the models it versions. Rejected on the reading in decision 7 —
`tests/test_cdm_packaging.py:328` designates `version.py` as the single place the axes are
explained, and a version constant sitting away from that explanation is the drift that test
exists to catch. §46 points the same way.

**F — reuse `EventType` as the identifier space.** Rejected by §27, which retains the existing
enum and keeps "the precise SC-OES semantic type and the broad legacy CDM EventType … separate
axes". ADR 0007 governs the relationship between the two.

## Consequences

- A regex and a validator in the package for each of the two event-type grammars, one for the
  governed ontology term grammar, and the three §15 tests for a third-party ontology identifier.
  No dependency.
- `version.py` gains `SC_OES_VERSION` and its docstring gains a third axis. That edit touches the
  file `tests/test_cdm_packaging.py:266` sweeps for a derivation of one version from another; the
  new constant must be an independent literal, not computed from either existing one (§46 says so
  as well).
- `tests/test_cdm_packaging.py:313` pins the literal pair `(PACKAGE_VERSION, SCHEMA_VERSION)`.
  Adding a third constant does not move that assertion; the schema bump does, and that is ADR
  0005's consequence.
- **Two identifier families in one repository, with the boundary written down** (decision 4).
  That is a documentation obligation for the normative tree (§117) and for `schemas.py`'s own
  comment block, which should gain a sentence pointing at this ADR so that a reader who arrives
  at `BASE_ID` first is not left inferring that the ontology follows it.
- The packaged registries become load-bearing for `sc.*` and for governed-term enforcement, which
  is one more reason they must ship (ADR 0004).
- Every published identifier is a permanent commitment under §13.

## Compatibility impact

No existing identifier moves. `BASE_ID` (`schemas.py:67`) is untouched by this decision, per §13.
The schema `$id`s move only because `SCHEMA_VERSION` is a segment of them (`schemas.py:76`), which
is ADR 0005's consequence and is what the version segment is for — at 2.0.0 rather than the 1.1.0
this ADR assumed while proposed.

`ids.NAMESPACE` (`ids.py:28`) is untouched. It is named explicitly in `MIGRATIONS.md:20`'s MAJOR
row, and SC-OES needs no change to it: event and entity relations reference UUIDs that are already
deterministic, so §128's replay distinction needs no new mechanism.

Going forward, an identifier's *meaning* is frozen by §13 and §51's `STABLE` definition —
"Meaning cannot be silently changed. Breaking semantics require a new identifier/version" — and a
materially different meaning requires a new identifier with a new semantic major, never a reuse
(§49).

## Security impact

- **Namespace confusion is the threat this decision is against, and §127 names it twice**:
  "reserved-namespace impersonation" and "malicious third-party ontology terms". The defences are
  decision 2 (an unknown `sc.*` is not a governed type) and decision 5's third test (a third-party
  ontology identifier must not impersonate the governed `tag:` namespace), and both work offline.
- **Unknown identifiers are preserved, never mapped.** §124 is normative for event types — a
  valid unknown `x.vendor.*` event "must remain transportable" and "the consumer must not silently
  convert it to a known `sc.*` type" — and §15 is normative for ontology terms in the same shape.
  This is the same behaviour `PAYLOAD_MODELS` already has for an unregistered `event_type`
  (`models.py:305`: "an event_type with no entry keeps a free-form payload").
- **No identifier invites a fetch.** `tag:` and `urn:` are both non-dereferenceable by design, so
  no validator can be induced to make a request by the content of an object it is validating.
  That is the concrete security value of both rulings, as distinct from their correctness value.
- **Identifiers carry no data and no markings**; they are opaque strings to everything except the
  registry lookup.

## Reversibility

**Low, and deliberately so — this is the least reversible decision in the set.** Once an
identifier is published, §13 makes it permanent public API and §49 forbids redefining a semantic
major. Changing the *grammar* later would orphan every identifier minted under the old one.

Three things reduce the exposure. First, nothing has been published: no ontology term exists yet
in this tree, which is why the correction from `urn:` to `tag:` is free now and would not have
been after round C. Second, the CDM's own published identifiers are explicitly out of scope
(decision 4), so this decision cannot break anything already on the wire. Third,
`SC_OES_VERSION` starting at `0.1.0` and the initial maturity being `DRAFT` or `EXPERIMENTAL`
(§50, §51) means the *semantics* behind the identifiers are explicitly not frozen yet, even
though their form is.

The `SC_OES_VERSION` placement (decision 7) is separately and cheaply reversible: it is a
constant and a docstring in one file, with no wire consequence.
