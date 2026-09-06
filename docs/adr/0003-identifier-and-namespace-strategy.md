# ADR 0003 — Identifier and namespace strategy

## Status

Proposed — awaiting M's review.

## Context

SC-OES introduces identifier spaces that become public API on first publication. §73 says so
directly of the ontology namespace — "Identifiers become public API. Do not casually change
them" — and §26 says it of the reserved prefixes: "Published identifiers must never later be
reused with a materially different meaning."

Four spaces are in scope, and one of them is already ruled in this tree.

- **Governed event type identifiers.** §24: `sc.<domain>.<event_name>.v<major>`, lowercase ASCII,
  domain lowercase alphanumeric and underscore, event name lowercase snake case, explicit
  `v<number>` semantic major.
- **Third-party event type identifiers.** §25: `x.<namespace>.<domain>.<event_name>.v<major>`,
  with `sc.*` reserved for semantics governed by the SynapseCommand public specification and
  third parties forbidden from creating `sc.*` types independently.
- **Ontology term identifiers.** §73 prefers `urn:synapsecommand:ontology:<module>:<Term>`.
- **Version axes.** §19–§20 require the SC-OES version, the CDM schema version, the Python
  package version, the ontology version and per-profile versions to be documented as separate
  facts.

**The URN question is already decided, and this ADR cites the ruling rather than re-arguing it.**
`schemas.py:30`–`:67` is a dated ruling on schema `$id`s that fixes `BASE_ID =
"urn:synapsecommand:cdm"`. Its reasoning: a consumer registers a schema under its `$id`, may try
to *fetch* it, and compares it to tell versions apart — so "the requirement is *identify*, not
*locate*, and a URN says exactly that" (`schemas.py:47`). It records what it replaced and why that
was wrong, not merely unresolvable: `https://synapsecommand.local/cdm`, where RFC 6762 reserves
`.local` for multicast DNS, "so that identifier did not just fail to resolve, it asserted a scope
that is false for a published contract" (`schemas.py:50`–`:52`). It records the rejected
alternatives on stated grounds, including `tag:` URIs (RFC 4151) as the most formally correct
non-dereferenceable choice, rejected for obscurity. And it records that `synapsecommand` is not an
IANA-registered URN namespace under RFC 8141, naming the formality rather than hiding it.

§73's preferred ontology form is that same decision applied to a second namespace.

## Decision

**Confirm §24, §25 and §73 as written, on the reading in `schemas.py:30`–`:67`, and add nothing
new.**

1. **Event type identifiers** are `sc.<domain>.<event_name>.v<major>` for governed semantics and
   `x.<namespace>.<domain>.<event_name>.v<major>` for third parties, validated in the package by
   a regex over §24's grammar. Validation is checked in **both directions**: a well-formed
   identifier is accepted, and a malformed one is refused with a message naming which rule it
   broke.
2. **`sc.*` is refused from an unregistered producer.** A `type_id` in the `sc.` namespace that
   is not in the packaged governed registry (ADR 0004) fails dimension C of the conformance model
   (ADR 0009), and the message says which. This is what §25's "Third parties MUST NOT
   independently create `sc.*` event types" costs to enforce, and it is enforceable offline
   because the registry ships.
3. **Ontology terms** are `urn:synapsecommand:ontology:<module>:<Term>`, confirmed as §73's
   preferred form. `<module>` is lowercase; `<Term>` is UpperCamelCase, which is what §73's own
   examples show (`core:OperationalObject`, `core:Capability`, `air:Runway`, `pnt:PNTService`).
   The reserved prefix `urn:synapsecommand:*` of §26 is confirmed with it.
4. **Identifier validation is syntax only at runtime**, with recognition by registry lookup. This
   is ADR 0002's split, restated here because it is the reason the grammar can be a regex.
5. **`SC_OES_VERSION = "0.1.0"` lives in `version.py`, and `version.py`'s docstring is rewritten
   to name three axes rather than two.** The reading that settles this, taken rather than
   assumed: `tests/test_cdm_packaging.py:328`
   (`test_version_py_is_the_only_place_the_distinction_is_explained`) requires the marker
   `WHY THEY MUST BE ALLOWED TO DIVERGE` to appear in exactly one `.py` file, and that file is
   `version.py`. A third version axis introduced in any other module would either restate the
   divergence reasoning there — which that test refuses — or state a version with no explanation
   beside it. `version.py:1` opens "Two version numbers, what each one governs, and why they are
   not one number", so adding the third moves that sentence; moving it is the correct cost, and
   it is a documentation change in the one file the repository has already designated for it.
   The ontology version and the per-profile versions are **not** Python constants: they live in
   the `.ttl` version metadata (§72) and in each profile document's `version` section (§89), for
   the same reason `SCHEMA_VERSION` and `PACKAGE_VERSION` are separate — an axis belongs where the
   thing it versions is authored.

## Alternatives considered

**A — HTTP/HTTPS ontology identifiers (`https://synapsecommand.com/ontology/core#Runway`).** The
conventional RDF choice, and rejected on `schemas.py:38`–`:43`'s already-recorded ground: an
`https://` identifier *invites* retrieval, this repository does not serve these files at any URL
and will not promise to, and an identifier that promises a fetch and 404s is worse than one that
promises nothing. §104's offline requirement points the same way. Re-deciding this differently for
the ontology than for schema `$id`s would put two identifier philosophies in one project.

**B — a `tag:` URI (RFC 4151) for ontology terms.** The most formally correct non-dereferenceable
choice, and already weighed and rejected once at `schemas.py:56`–`:58` for obscurity: "tooling and
readers both handle `urn:` without explanation." Consistency with the existing `$id` decision is
the additional ground here.

**C — flat event type identifiers with no version segment (`sc.pnt.gnss_interference`).**
Rejected: §24 requires an explicit `v<number>`, and §98 depends on it — a consumer that receives a
semantic major it does not know must be able to *see* that it is a different major rather than
inferring it. Without the segment, a breaking semantic change has nowhere to go but a new name.

**D — put `SC_OES_VERSION` in the new `oes` module instead of `version.py`.** Locally tidier: the
constant sits with the models it versions. Rejected on the reading above —
`tests/test_cdm_packaging.py:328` designates `version.py` as the single place the axes are
explained, and a version constant sitting away from that explanation is the drift that test
exists to catch. Named here because it is the obvious alternative and because the plan left this
open rather than deciding it.

**E — reuse `EventType` as the identifier space.** Rejected by §32, which requires the legacy
vocabulary to be kept and SC-OES to run in parallel with a more precise identifier. ADR 0007
governs the relationship between the two.

## Consequences

- A regex and a validator in the package for each of the two grammars; no dependency.
- `version.py` gains `SC_OES_VERSION` and its docstring gains a third axis. That edit touches the
  file `tests/test_cdm_packaging.py:266` sweeps for a derivation of one version from another; the
  new constant must be an independent literal, not computed from either existing one.
- `tests/test_cdm_packaging.py:313` pins the literal pair `(PACKAGE_VERSION, SCHEMA_VERSION)`.
  Adding a third constant does not move that assertion; the schema bump does, and that is ADR
  0005's consequence.
- The packaged registry becomes load-bearing for `sc.*` enforcement, which is one more reason it
  must ship (ADR 0004).
- Every published identifier is a permanent commitment under §26.

## Compatibility impact

No existing identifier moves. `BASE_ID` (`schemas.py:67`) is untouched by this decision; the
schema `$id`s move only because `SCHEMA_VERSION` is a segment of them (`schemas.py:76`), which is
ADR 0005's consequence and is what the version segment is for.

`ids.NAMESPACE` (`ids.py:28`) is untouched. It is named explicitly in `MIGRATIONS.md:20`'s MAJOR
row, and SC-OES needs no change to it: event and entity relations reference UUIDs that are already
deterministic, so §108's replay distinction needs no new mechanism.

Going forward, an identifier's *meaning* is frozen by §26 and its *maturity* is declared by §28;
a materially different meaning requires a new identifier with a new semantic major, never a reuse.

## Security impact

- **Namespace confusion is the threat this decision is against.** An unregistered producer
  emitting `sc.*` identifiers would be asserting governed semantics it does not own. The defence
  is the registry check in decision 2, and it works offline.
- **Unknown identifiers are preserved, never mapped.** §27 is normative: a consumer that does not
  understand `x.example.fire_control_status.v3` must still validate generic structure, retain
  provenance and payload, store, forward, audit and display the opaque identifier, and "MUST NOT
  silently map the unknown type to a 'similar' known event". This is the same behaviour
  `PAYLOAD_MODELS` already has for an unregistered `event_type` (`models.py:304`: "an event_type
  with no entry keeps a free-form payload").
- **No identifier invites a fetch**, so no validator can be induced to make a request by the
  content of an object it is validating. That is the concrete security value of the URN ruling,
  as distinct from its correctness value.
- Identifiers carry no data and no markings; they are opaque strings to everything except the
  registry lookup.

## Reversibility

**Low, and deliberately so — this is the least reversible decision in the set.** Once an
identifier is published, §26 forbids reusing it with a materially different meaning, and §73 says
identifiers are public API. Changing the *grammar* later would orphan every identifier minted
under the old one.

Two things reduce the exposure. First, the decision is not novel: it applies a ruling this
repository already made and already lives with (`schemas.py:30`–`:67`), so the failure mode it
could repeat is the one that ruling exists to prevent. Second, `SC_OES_VERSION` starting at
`0.1.0` and the initial maturity being `DRAFT` or `EXPERIMENTAL` per §30 means the *semantics*
behind the identifiers are explicitly not frozen yet, even though their form is.

The `SC_OES_VERSION` placement (decision 5) is separately and cheaply reversible: it is a
constant and a docstring in one file, with no wire consequence.
