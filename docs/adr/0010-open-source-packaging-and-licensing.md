# ADR 0010 — Open-source packaging and licensing

## Status

Accepted — M, 2026-09-06, per SC-OES-SPEC-v2.

Amended by SA.1 — M, 2026-09-06: reviewed under SA.1 §58 and §67 and **nothing in this ADR moves**.
Apache-2.0, the untouched `LICENSE`, repository-level licensing with no per-file SPDX headers, no
copied protected standards definitions, conformance-is-not-certification and the separate trademark
rights are SA.1 §9 and §94 locked decisions. This ADR carries no ontology identifier example, so
SA.1 §14's dated prefix requires no edit here. Still Accepted.

Lineage — round SC, 2026-09-06: decision 5's licence criterion is applied and satisfied. The
test-only RDF parser is **rdflib 7.6.0, BSD-3-Clause**; its one non-optional transitive dependency
is **pyparsing 3.3.2, MIT**. Both are permissive and both are compatible with Apache-2.0, which is
the criterion this decision states for a `test` extra; **both are accepted under repository
policy**. Neither is copyleft, so neither raises the additional licensing analysis that decision 5
declines to take on for a test dependency. The licences were
read from each installed distribution's own metadata, not recalled. Recorded here and in the
`test` extra's own comment in `packages/cdm/pyproject.toml`, as decision 5 requires. Decision 4's
independent-authorship rule was applied to round SC's own output: every one of the 73 ontology
definitions is written in this repository's words, and none is transcribed from a pinned document.
Still Accepted.

## Context

§42 rules the licensing arrangement in four sentences and one list:

> Retain the repository's existing Apache-2.0 model. Do not alter the canonical Apache `LICENSE`
> file. Do not add per-file SPDX tags or copyright headers if repository policy prohibits them.
> New `.py`, `.md`, `.json`, `.jsonld`, `.ttl` files inherit repository-level licensing.

§43 forbids copying protected standards documents or substantial protected definitions into SC-OES
or the ontology, and names what to use instead — independently authored descriptions, references,
mappings, adapter behaviour, citations — closing with "Pinned standards remain outside the
Apache-2.0 work according to existing repository policy." §44 asks for a concise trademark
statement and forbids creating a certification or trademark licensing programme. §45 fixes
conformance terminology. §2 is the strategic frame: the public repository holds the contract, not
the decision-intelligence implementation.

**The repository's arrangement is stricter than §42 assumes it might be, and it is gated.**

- `NOTICE:11` is headed "WHY THIS FILE AND NOT THE APPENDIX IN LICENSE", and records that
  Apache-2.0's appendix is a template for per-file headers which this repository does not use:
  "This repository has no per-file headers: NO tracked file carries an SPDX tag, and every
  copyright notice in the tree is in a LICENCE FILE" (`NOTICE:15`–`:16`). Both halves are enforced
  over the whole index — `tests/test_cdm_publication.py:314` for the tag, `:327` for the notice —
  and the second test's own docstring names the ordinary way the invariant breaks: "A copyright
  block pasted at the top of a new module … is correct in isolation and wrong only relative to a
  policy stated in a file nobody reads while writing code." So §42's conditional — "if repository
  policy prohibits them" — is satisfied: it does, twice, by machine.
- `NOTICE:44`–`:46` explains why `LICENSE` is untouchable: its text "stays byte-identical to the
  canonical Apache-2.0 so that GitHub's licence detection and any SPDX scanner keep recognising
  it. A modified LICENSE is a licence tools stop being sure about." Reading taken: 201 lines.
  `packages/cdm/pyproject.toml:31` declares `license = "Apache-2.0"` and `:38` carries both files
  into the distribution as `license-files`.
- `NOTICE:55` draws the boundary §43 is about: "The specification documents this repository PINS
  are not part of the Work and are not covered by this licence." Readings taken: thirty documents
  pinned (`gates/pin_paths.py` → present 30, matched 30, 0 failed); `git ls-files '*.pdf'` and
  `'*.zip'` → **0** and **0**. The exclusion at `packages/cdm/pyproject.toml:192`–`:196` is
  positive rather than by omission, and the comment at `:141`–`:144` records why — the include
  list was once "one glob away from redistributing a NATO standard under Apache-2.0."

ADR 0002 introduces one new test-only dependency, an RDF parser, whose licence §136 makes this
ADR's business.

## Decision

**Apache-2.0 for everything SC-OES authors, achieved by adding nothing; the pinned-document
boundary untouched; a short trademark statement; §45's terminology written into the conformance
document and swept.**

1. **New material is covered by repository-level licensing and carries no header.** Every file
   this campaign creates — §42's `.py`, `.md`, `.json`, `.jsonld`, `.ttl` — inherits `LICENSE` and
   `NOTICE`. **Adding an SPDX tag or a per-file notice to any of them would fail
   `tests/test_cdm_publication.py:314` or `:327` and would falsify `NOTICE:15`'s sentence.** §42
   is therefore satisfied by adding nothing, which is the unusual answer and the correct one here.
2. **`LICENSE` is not touched.** §42 says so and `NOTICE:44`–`:46` gives the reason, which is a
   tooling fact rather than a preference. Not for SC-OES, not for the ontology, not for a
   third-party parser's requirements.
3. **`NOTICE` gains no new legal mechanism**, and at most a short statement in its
   already-established register: the three-way naming distinction §16 requires — a root `spec/`
   holds normative documents this project owns, `fixtures/*/spec/` holds pin records for documents
   it does not, and `synapse_cdm/registry/sc_oes/` holds the machine-readable runtime artefacts
   (ADR 0004, decision 6). That is a clarification of an existing boundary, not a new one, and
   §159 lists "NOTICE clarification if necessary" as round SI's work rather than an obligation.
4. **The ontology is independently authored.** §43's instruction is a hard rule for round SC:
   ontology terms are defined in this repository's own words and *mapped* to external standards.
   No definition is transcribed from a pinned document, and no "substantial protected definition"
   is imported. This is the same boundary `NOTICE:55` already draws, applied to prose rather than
   to bytes, and §161's final security review searches the branch for "restricted standards
   content" as the check on it.
5. **The test-only RDF parser must be licence-checked before it lands**, and §136 fixes both the
   criterion and the record: "confirm its license is compatible with repository policy … record
   the choice in ADR 0002/0010 lineage." The criterion applied here is Apache-2.0 compatibility
   for a `test` extra. **A copyleft parser is refused as a conservative repository policy**, and the
   policy is worth stating in its own terms rather than as a legal conclusion. The project declines
   copyleft test dependencies in order to avoid introducing additional licensing analysis,
   compatibility questions or distribution obligations into the development and verification
   environment — and because `LICENSE` may not be edited (decision 2), which leaves no place to
   record an obligation if one were ever found to arise. **This is a project-policy decision. It is
   not a claim that every copyleft test dependency would relicense the distributed runtime package
   or impose identical obligations on it**; whether any obligation attaches at all depends on the
   particular licence, on how the works are combined and on what is distributed, and the
   architecture does not need that question answered. Declining the dependency is cheaper than
   answering it. Permissively licensed parsers exist; the round that chooses one records the licence
   in this ADR's lineage and in the `test` extra's own comment.
6. **Trademark: a statement, not a licence.** §44's own words, adopted substantially as given, in
   `README.md` and the conformance document:

   > SC-OES is an open interoperability specification maintained within the SynapseCommand project
   > by Decent Cybersecurity. The open-source license governing these materials does not grant
   > rights to use Decent Cybersecurity or SynapseCommand trademarks except as necessary for
   > accurate descriptive reference.

   §44's closing rule binds with it: "Do not create a certification or trademark licensing
   programme in this work." No trademark licence document is created, because no trademark policy
   exists yet to license against.
7. **Terminology, and it is checkable.** §45's permitted forms — "SC-OES Conformant", "SC-OES PNT
   Profile Conformant" — are what tooling and documents use. The forbidden list is §45's, in full:
   "SC-OES Certified", "Official SynapseCommand Partner", "Approved by Decent Cybersecurity",
   "NATO Certified", "NATO Approved", "NATO Standard" — the last three added by v2 and the reason
   the sweep is worth having, since this repository pins NATO standards and a careless sentence
   about one is the realistic way the phrase would appear. §148 points the same way: "Do not imply
   external standard-body approval." A sweep in the shape this repository already uses for prose
   bans asserts the absence over the tracked tree, so the rule is a build failure rather than a
   style note.
8. **Positioning is a licensing-adjacent claim and is bounded too.** §147 forbids claiming SC-OES
   replaces ASTERIX, STANAG 4676, STANAG 4607, TAK, AIS, AIXM, MIP/JC3IEDM, sensor-native
   protocols or C2-native message formats, and gives the sentence that does hold: "A lightweight
   operational-event semantics layer applied after source-format translation into the
   SynapseCommand Canonical Data Model." That claim costs nothing and is true; the replacement
   claim would be neither.
9. **No patent claim is made.** Apache-2.0's patent grant stands as written; the specification
   asserts nothing further, and no third-party proprietary semantic definition is imported merely
   because it is technically useful (§43, §162's "no incompatible new dependency" and "no
   accidental trademark grant").

## Alternatives considered

**A — add SPDX tags to newly authored files, as an open-source repository normally would.**
Rejected on the gate and on the paragraph. `tests/test_cdm_publication.py:314` sweeps the whole
index for the two SPDX tag forms — its pattern at `tests/test_cdm_publication.py:292`, not spelled
here, because this ADR is tracked and inside that sweep's own file set; one tagged file makes
`NOTICE:15`'s sentence false. Its message states the only two honest resolutions: remove the tag,
or adopt per-file headers everywhere and rewrite `NOTICE`. Adding tags to SC-OES files alone would
be a third, dishonest one — a policy true of part of the tree. §42 anticipates exactly this by
making the instruction conditional on repository policy.

**B — a separate licence for the specification text (CC-BY-4.0 or similar), which is common for
specifications.** A real option, and arguably a better fit for prose than a software licence.
Rejected for v0.1: §42 asks for "the repository's existing Apache-2.0 model", a second licence
introduces a boundary inside one repository that `NOTICE` would then have to police, and the
concrete benefit — permissive reuse of specification prose — is already available under
Apache-2.0. Named here because it is the decision most likely to be revisited, and because
revisiting it is cheap while the specification tree is small.

**C — dual-license the ontology to encourage adoption.** Rejected for the same reason as B, plus a
support obligation with no offsetting benefit while the ontology is at 0.1.0 and `EXPERIMENTAL` or
`DRAFT` maturity (§50, §51).

**D — vendor a copyleft RDF parser for tests and treat any obligation as test-only.** Rejected on
decision 5's policy rather than on a legal conclusion: the analysis needed to be confident about
what does and does not reach the distributed package costs more than choosing a permissive parser,
and `LICENSE` may not be edited (decision 2), so there would be nowhere to record an obligation if
the analysis found one. The rejection is not an assertion that the obligation would in fact attach.

**E — create a trademark and certification programme now, so "SC-OES Conformant" has a defined
owner.** Rejected by §44 in as many words — "Do not create a certification or trademark licensing
programme in this work" — and by §45, which specifies the interim terminology precisely because no
programme exists.

## Consequences

- No new licence file, no header, no `LICENSE` edit. The most visible consequence of this ADR is
  the absence of the files a reader might expect.
- `NOTICE` may gain one short paragraph (decision 3) and `README.md` one short trademark statement
  (decision 6). Both are prose in files this repository already gates, so they are written to pass
  those sweeps rather than repaired afterwards.
- One licence decision is deferred to the round that chooses the RDF parser, with the criterion
  fixed here and the recording obligation fixed by §136.
- **A new prose sweep for six forbidden phrases**, up from three while this ADR was proposed:
  §45's v2 list adds the three NATO formulations. It is written in the shape of the prose bans this
  repository already enforces.
- Newly created files under `ontology/` and the root `spec/` are repository-only; the SC-OES
  runtime registry artefacts are packaged (ADR 0004). All are covered by the same repository-level
  licensing, so the packaging split has no licensing consequence.
- **`profiles.json` inherits the same arrangement, and needed nothing new to do so** (round SL,
  2026-09-07). The third packaged artefact — `packages/cdm/synapse_cdm/registry/sc_oes/profiles.json`,
  added in round SK — is original work authored in this repository and is covered by the same
  repository-level Apache-2.0 licensing as `event_types.json` and `ontology_terms.json`. No new
  licence, no new legal mechanism, no per-file licence header, and no edit to `LICENSE`: the
  absence of those four is the consequence, exactly as it was for the first two.

## Compatibility impact

None to any contract. This ADR adds no field, no dependency at runtime and no file a consumer
installs, and `packages/cdm/pyproject.toml:31`'s declared licence is unchanged.

The `license-files` list (`:38`) carries `LICENSE` and `NOTICE` into `.dist-info/licenses/`
already, so a distribution built after this campaign carries the same licensing metadata as one
built before it. `tests/test_cdm_packaging.py:117`'s closure is unaffected by this ADR;
ADR 0004's widened glob is what that test reads.

For downstream users the compatibility statement is simple and is worth making explicitly in the
specification: everything SC-OES publishes is under the same terms as the rest of this repository,
and there is no additional licence to accept.

## Security impact

- **The pinned-document boundary is a licensing control with a security shape.** The `extra`
  direction of `tests/test_cdm_packaging.py:117` catches a file that would ship and is not tracked
  — on a maintainer's machine, that is a pinned third-party standard — and its message calls
  shipping one inside an Apache-2.0 wheel "a licensing defect, not an oversight". ADR 0004 widens
  a `package-data` glob, so that control is exercised by this campaign and must be re-derived
  after the change. §17's "do not modify exclusions in a way that makes pinned third-party
  standards shippable" is the specification's statement of the same rule.
- **Independently authored ontology terms keep restricted content out of the tree**, which is the
  same property as `git ls-files '*.pdf'` → 0: nothing this repository publishes carries somebody
  else's protected text. §161 is the round that checks it over the whole branch.
- **Terminology discipline is an integrity control.** "Certified" and "Approved" imply an
  assessment by a body that does not exist, and the three NATO formulations imply one that exists
  and has not been asked. §45's forms claim only what a conformance run can substantiate (ADR
  0009), and the sweep in decision 7 makes the claim unable to drift upward quietly.
- **No secrets, no real data, no private endpoints.** `CONTRIBUTING.md:166`–`:167` is the standing
  rule for synthetic fixtures — "**No real data, ever**" — and §130 restates it with the fictional
  names to use; `tests/test_cdm_boundary.py:95` keeps the private topology out of the imports.
  Every SC-OES example is synthetic with synthetic identifiers, and §161's final search is the
  check on it.
- **The public/private split is itself a security decision.** §2 keeps the reasoning engine,
  inference rules, scoring and COA logic out of this repository; §143's boundary tests are what
  stop one arriving by import. This ADR's licensing arrangement covers what is public precisely
  because what is private is not here to be licensed.

## Reversibility

High for what is deferred, low for what is published.

Deferred and cheap: the RDF parser choice, and the specification-licence question (alternative B)
while the normative tree is small.

Published and expensive: the licence under which specification text, ontology terms and the
registries go out. Apache-2.0 is irrevocable for what has been released under it, so a later change
governs only new material and leaves a version boundary readers have to know about. That is the
ordinary shape of a licensing decision and is the reason this ADR chooses the arrangement the
repository already has rather than a new one — the cheapest licensing decision to live with is the
one that adds nothing.
