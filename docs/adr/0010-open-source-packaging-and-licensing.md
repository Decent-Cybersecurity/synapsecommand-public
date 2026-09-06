# ADR 0010 — Open-source packaging and licensing

## Status

Proposed — awaiting M's review.

## Context

§129 states the intended public model — "open specification + open ontology + open schemas + open
reference implementation + proprietary high-value reasoning runtime" — and asks that newly
authored material use "the repository's existing Apache License 2.0 model … unless the existing
repository explicitly establishes another compatible licensing arrangement". It lists what open
licensing must at minimum cover: the SC-OES specification, the Operational Ontology, schemas,
registry, SDK changes, validators, conformance tooling, synthetic examples and reference
implementation code. §130 keeps Apache-2.0's patent provisions intact and forbids importing
third-party proprietary semantic definitions. §131 asks for a short trademark statement, not a
licence. §132 fixes conformance terminology. §128 forbids reproducing protected standards
content.

**The repository's arrangement is stricter than the specification assumes, and it is gated.**

- `NOTICE:11` is headed "WHY THIS FILE AND NOT THE APPENDIX IN LICENSE", and records that
  Apache-2.0's appendix is a template for per-file headers which this repository does not use:
  "This repository has no per-file headers: NO tracked file carries an SPDX tag, and every
  copyright notice in the tree is in a LICENCE file." Both halves are enforced over the whole
  index — `tests/test_cdm_publication.py:314` for the tag, `:327` for the notice — and the second
  test's own docstring names the ordinary way the invariant breaks: "A copyright block pasted at
  the top of a new module … is correct in isolation and wrong only relative to a policy stated in
  a file nobody reads while writing code."
- `NOTICE:41`–`:46` explains why `LICENSE` is untouchable: its text "stays byte-identical to the
  canonical Apache-2.0 so that GitHub's licence detection and any SPDX scanner keep recognising
  it. A modified LICENSE is a licence tools stop being sure about." It is 201 lines.
  `packages/cdm/pyproject.toml:31` declares `license = "Apache-2.0"` and `:38` carries both files
  into the distribution as `license-files`.
- `NOTICE:55` draws the boundary §128 is about: "The specification documents this repository PINS
  are not part of the Work and are not covered by this licence. None of their bytes is in this
  repository or in its history: each is recorded by SHA-256, byte count, page count, edition and
  source URL, and the documents themselves remain under their publishers' own terms". Readings
  taken: thirty documents pinned; `git ls-files '*.pdf'` and `'*.zip'` → 0 and 0. The exclusion at
  `packages/cdm/pyproject.toml:170` is positive rather than by omission, and the comment at
  `:139`–`:144` records why — the include list was once "one glob away from redistributing a NATO
  standard under Apache-2.0."

ADR 0002 introduces one new test-only dependency, an RDF parser, whose licence is this ADR's
business.

## Decision

**Apache-2.0 for everything SC-OES authors, achieved by adding nothing; the pinned-document
boundary untouched; a short trademark statement; §132's terminology written into the conformance
document.**

1. **New material is covered by repository-level licensing and carries no header.** Every file
   this campaign creates — `.ttl`, `.jsonld`, `.py`, `.json`, `.md` — inherits `LICENSE` and
   `NOTICE`. **Adding an SPDX tag or a per-file notice to any of them would fail
   `tests/test_cdm_publication.py:314` or `:327` and would falsify `NOTICE:11`'s paragraph.** §129
   is therefore satisfied by adding nothing, which is the unusual answer and the correct one here.
2. **`LICENSE` is not touched.** Not for SC-OES, not for the ontology, not for a third-party
   parser's requirements. `NOTICE:44` states the reason and it is a tooling fact, not a
   preference.
3. **`NOTICE` gains no new legal mechanism**, and at most a short statement in its
   already-established register: the SC-OES normative tree at the root `spec/` holds documents
   this project owns, distinct from the pin records under `fixtures/*/spec/` which describe
   documents it does not (ADR 0004, decision 5). That is a clarification of an existing boundary,
   not a new one.
4. **The ontology is independently authored.** §128's instruction — references, independently
   authored descriptions, mappings, adapter behaviour, rather than reproducing restricted
   standards — is a hard rule for Phase 5: ontology terms are defined in this repository's own
   words and *mapped* to external standards. No definition is transcribed from a pinned document.
   This is the same boundary `NOTICE:55` already draws, applied to prose rather than to bytes.
5. **The test-only RDF parser must be licence-checked before it lands**, and the check is
   Apache-2.0 compatibility for a `test` extra. A copyleft parser is refused, not because a test
   dependency propagates in the way a runtime one might, but because it would put a licence
   obligation on a distribution whose licence file may not be edited (decision 2). Permissively
   licensed parsers exist; the phase that chooses one records the licence in the ADR-0002 lineage
   and in the `test` extra's own comment.
6. **Trademark: a statement, not a licence.** §131's shape, in `README.md` and the conformance
   document: SC-OES is an open interoperability specification maintained within the
   SynapseCommand project by Decent Cybersecurity; the Apache-2.0 licence governing source
   materials grants no rights to use Decent Cybersecurity or SynapseCommand trademarks except as
   necessary for accurate descriptive reference. Three properties, per §131: ownership preserved,
   no implication of certification or endorsement, implementation conformance distinguished from
   brand rights. No trademark licence document is created, because no trademark policy exists yet
   to license against.
7. **Terminology, and it is checkable.** §132's permitted forms — "SC-OES Conformant", "SC-OES
   PNT Profile Conformant" — are what tooling and documents use. "SC-OES Certified", "Official
   SynapseCommand Partner" and "Approved by Decent Cybersecurity" are not used. §101's forbidden
   external-certification phrasings are used nowhere in the specification's own text. A sweep in
   the shape this repository already uses for prose bans asserts the absence over the tracked
   tree, so the rule is a build failure rather than a style note.
8. **No patent claim is made.** §130: Apache-2.0's patent grant stands as written; the
   specification asserts nothing further, and no third-party proprietary semantic definition is
   imported merely because it is technically useful.

## Alternatives considered

**A — add SPDX tags to newly authored files, as §129 implies is normal practice.** Rejected on the
gate and on the paragraph. `tests/test_cdm_publication.py:314` sweeps the whole index for
the two SPDX tag forms — its `SPDX` pattern at `tests/test_cdm_publication.py:292`, not spelled
here, because this ADR is tracked and inside that sweep's own file set; one tagged file makes
`NOTICE:14`'s sentence false. Its message states the only two honest resolutions: remove the tag, or adopt
per-file headers everywhere and rewrite `NOTICE`. Adding tags to SC-OES files alone would be a
third, dishonest one — a policy true of part of the tree.

**B — a separate licence for the specification text (CC-BY-4.0 or similar), which is common for
specifications.** A real option, and arguably a better fit for prose than a software licence.
Rejected for v0.1: §129 asks for "the repository's existing Apache License 2.0 model", a second
licence introduces a boundary inside one repository that `NOTICE` would then have to police, and
the concrete benefit — permissive reuse of specification prose — is already available under
Apache-2.0. Named here because it is the decision most likely to be revisited, and because
revisiting it is cheap while the specification tree is small.

**C — dual-license the ontology to encourage adoption.** Rejected for the same reason as B, plus
§130's caution: a second licence on an artefact whose terms downstream users will quote is a
support obligation with no offsetting benefit while the ontology is at 0.1.0 and `EXPERIMENTAL`
or `DRAFT` maturity.

**D — vendor a copyleft RDF parser for tests and accept the obligation as test-only.** Rejected on
decision 5's reasoning: the obligation would attach to a distribution whose `LICENSE` may not be
edited, and the analysis needed to be confident it does not propagate costs more than choosing a
permissive parser.

**E — create a trademark and certification programme now, so "SC-OES Conformant" has a defined
owner.** Rejected by §131 in as many words — "Do not create an elaborate legal trademark licence
in this technical change unless an existing policy already exists" — and by §132, which specifies
the interim terminology precisely because no programme exists.

## Consequences

- No new licence file, no header, no `LICENSE` edit. The most visible consequence of this ADR is
  the absence of the files a reader might expect.
- `NOTICE` may gain one short paragraph (decision 3) and `README.md` one short trademark statement
  (decision 6). Both are prose in files this repository already gates, so they are written to pass
  those sweeps rather than repaired afterwards.
- One licence decision is deferred to the phase that chooses the RDF parser, with the criterion
  fixed here.
- A new prose sweep for the forbidden conformance and certification phrasings, in the shape of the
  bans this repository already enforces.
- Newly created files under `ontology/` and the root `spec/` are repository-only; the registry is
  packaged (ADR 0004). Both are covered by the same repository-level licensing, so the packaging
  split has no licensing consequence.

## Compatibility impact

None to any contract. This ADR adds no field, no dependency at runtime and no file a consumer
installs, and `packages/cdm/pyproject.toml:31`'s declared licence is unchanged.

The `license-files` list (`:38`) carries `LICENSE` and `NOTICE` into `.dist-info/licenses/`
already, so a distribution built after this campaign carries the same licensing metadata as one
built before it. `tests/test_cdm_packaging.py:117`'s closure is unaffected by this ADR;
ADR 0004's widened glob is what that test reads.

For downstream users, the compatibility statement is simple and is worth making explicitly in the
specification: everything SC-OES publishes is under the same terms as the rest of this repository,
and there is no additional licence to accept.

## Security impact

- **The pinned-document boundary is a licensing control with a security shape.** The `extra`
  direction of `tests/test_cdm_packaging.py:117` catches a file that would ship and is not tracked
  — on a maintainer's machine, that is a pinned third-party standard — and its message calls
  shipping one inside an Apache-2.0 wheel "a licensing defect, not an oversight". ADR 0004 widens
  a `package-data` glob, so that control is exercised by this campaign and must be re-derived
  after the change.
- **Independently authored ontology terms keep restricted content out of the tree**, which is the
  same property as `git ls-files '*.pdf'` → 0: nothing this repository publishes carries somebody
  else's protected text.
- **Terminology discipline is an integrity control.** "Certified" and "Approved" imply an
  assessment by a body that does not exist; §132's forms claim only what a conformance run can
  substantiate (ADR 0009), and the sweep in decision 7 makes the claim unable to drift upward
  quietly.
- **No secrets, no real data, no private endpoints.** `CONTRIBUTING.md:166` is the standing rule
  for synthetic fixtures and §146 restates it; `tests/test_cdm_boundary.py:95` keeps the private
  topology out of the imports. Every SC-OES example is synthetic with synthetic identifiers
  (§113).

## Reversibility

High for what is deferred, low for what is published.

Deferred and cheap: the RDF parser choice, and the specification-licence question (alternative B)
while the normative tree is small.

Published and expensive: the licence under which specification text, ontology terms and the
registry go out. Apache-2.0 is irrevocable for what has been released under it, so a later change
governs only new material and leaves a version boundary readers have to know about. That is the
ordinary shape of a licensing decision and is the reason this ADR chooses the arrangement the
repository already has rather than a new one — the cheapest licensing decision to live with is the
one that adds nothing.
