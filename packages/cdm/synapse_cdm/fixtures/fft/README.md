# STANAG 5527 / Friendly Force Tracking fixtures

**There are none, there is no plan for any, and that is further from a fixture than
`fixtures/klv` is.** Adapter `stanag5527` is at Phase 1 and a narrower Phase 1 than
`stanag4609`'s: that one pinned a covering document *and* the profile its AGREEMENT clause names,
so it could write a row set of 37 rows all saying `not yet` and a twelve-entry fixture plan. This
one pins the covering document alone. **ADatP-36, Edition B — the single standard STANAG 5527
Edition 2's AGREEMENT clause names — is not in hand**, and every field, message, encoding and
identifier of Friendly Force Tracking is in it. So there is no row set here, no mapping table and
no fixture plan. There is a pinned document, two ruled names, one delegation row and one park.

```bash
# Today this FAILS, deliberately, and it fails TWICE over — the same two failures
# fixtures/klv/README.md records, in the same order. The adapter name does not resolve yet, so
# `--adapter stanag5527` raises `LookupError: unknown adapter 'stanag5527'` and exits 1.
# Substitute any registered adapter and it fails again, this time on the directory: exit code 2,
# `NoFixturesFound`, because the only thing in here is spec/ and a run that exercises nothing must
# not report a green.
python -m synapse_cdm.harness --adapter stanag5527 --fixtures .   # from THIS directory
```

**`stanag5527` is adapter #9.** The ordinal was reserved and is now issued: the number did not
move and the name did. The series is tabulated once, in "The adapter ordinals, and the
reserved-ordinal rule" near the top of `../../FORMAT_COVERAGE.md`, and that table is the authority
`tests/test_cdm_ordinals.py` checks every other site against.

## The two names, and why one of them is provisional

**The directory is `fft`, the adapter is `stanag5527`, and the two differ on purpose — but they
differ with different confidence, which `fixtures/klv` did not have to say.**

The **adapter** takes the STANAG's number, and that ruling is settled. The document in hand states
no field, no message, no encoding and no identifier: its content pages are AIM, INTEROPERABILITY
REQUIREMENTS, AGREEMENT, STANDARD, OTHER RELATED DOCUMENTS, SUPERSEDED DOCUMENTS and the
administrative clauses, and the AGREEMENT clause's entire content is the name of another document.
So there is no NATO document *in hand* whose content could name the adapter. That is the same
finding STANAG 4609 Edition 5 produced, reached the stronger way: 4609's covering-document
character was stated by the MISP, while 5527's is demonstrated by reading 5527.

The **directory** takes the content's name because a directory holds payloads and a payload is not
a standard — the split that puts adapter `stanag4676`'s fixtures in `fixtures/nits` and adapter
`stanag4609`'s in `fixtures/klv`. The covering document supplies a payload noun exactly once, in
IMPLEMENTATION OF THE AGREEMENT: nations should add "interfaces to produce/consume **FFT data** in
compliance with the ADatP-36 standard". That is this document naming the thing that crosses the
wire, and it is all the evidence there is — **so the directory ruling is PROVISIONAL.** ADatP-36
Edition B may call the payload something else, and if it does the directory moves. The adapter does
not: no content document can unrule a name taken from the covering document.

`spec/fft_pin.json` carries the full ruling — the rejected candidates (`nffi`, `adatp36`, `ffts`,
`stanag5527` as a directory), the Fast-Fourier-Transform collision considered and overruled, and
the two findings that would overturn the directory — and so does the `FORMAT_COVERAGE.md` section.

**`nffi` was retired here rather than confirmed.** Ordinal #9 was reserved under that name, and the
name turned out to have no source: it appears in no document in hand — STANAG 5527 Edition 2 never
uses the term, checked at the extracted-text level and again over the raw file bytes, zero
occurrences either way — and it had no source in this repository either, which the repository
itself had already recorded. The *reservation* was right and is now made good; the *name* is gone.

What is here:

- **`spec/fft_pin.json`** — the pinned identity of the document and every value extracted from it
  that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021,
  CAT048 and KLV pins were: a quotation with no pin behind it is a recollection.
- **`spec/nato-stanag-5527-edition-2.pdf`** — in the working tree because it had to be read, and
  **not committed**, matching every other adapter here. `git ls-files | grep -c '\.pdf$'` is 0
  across the whole repository.

| Document | SHA-256 | Bytes | Pages |
|---|---|---|---|
| `spec/nato-stanag-5527-edition-2.pdf` | `2dba2026cab49c2c3c6f576244edc1be1abfe2df9c545a46ae341cc2a2d30b83` | 319 795 | 5 |

That row is also stated in `spec/fft_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two. The pin row is asserted as **one composite string** rather than as hash,
bytes and pages separately, which is the residue of the same shape that mutation found inside
`klv_pin.json`: changing a page count left the suite green because the right number still occurred
elsewhere in the file.

## What the document is, in the five pages it has

STANAG 5527, **Friendly Force Tracking Systems (FFTS) Interoperability, Edition 2, 24 April 2025**,
published by the NATO Standardization Office; Letter of Promulgation reference
`NSO(DPC)0523(2025)CAP2/5527`; supervised under the Digital Policy Committee (DPC) / Navigation and
Identification Capability Panel (CaP 2). It supersedes "STANAG 5527, Edition 1, dated 20 March
2017". NATO non-classified, to be handled in accordance with C-M(2002)60. NATO Effective Date: "Not
applicable."

One standard is delegated to and two documents are merely related, and that distinction is the
document's own:

- **AGREEMENT → ADatP-36, Edition B.** "Participating nations agree to implement the following
  standard." One standard, an edition letter and **no version** — the AEDP-12 shape, which this
  repository elsewhere has to cite as "Edition B Version 2", so an edition letter alone does not
  identify a text. ADatP-36 is named nine times across the document and exactly two of those nine
  carry the edition letter, both in the STANDARD clause. **Park 1.**
- **OTHER RELATED DOCUMENTS → STANAG 7149** (NATO Message Catalogue, APP-11) and **STANAG 2019**
  (NATO Joint Military Symbology, APP-06). Recorded as *related* and deliberately **not** as
  delegation: neither appears in the AGREEMENT, and filing a related document as a delegation would
  overstate what the nations agreed to implement.

## Why no fixture can be written, and what would change that

Not scheduling, and not the KLV situation either. `fixtures/klv` could name twelve fixtures and the
park gating each one, because the MISP told it what a KLV payload is even though no field dictionary
was in hand. Here the covering document does not say what a payload *is* — only that it is called
FFT data. A file invented against that would be a guess with an extension on it, and a golden file
recording what our own guess decodes to is the round-trip trap `../../README.md` names under "Three
things the harness cannot check for you": self-consistency without an external anchor.

**Park 1, and it is the only one.** Obtain **ADatP-36, Edition B** — that edition specifically, not
"the current ADatP-36", and a copy in hand must also settle *which version* of Edition B it is. The
route the pinned document prints for NATO standardization documents is the NATO Standardization
Documents Database, `https://nso.nato.int/nso/`, "or through your national standardization
authorities". That is weaker than eleven of the twelve KLV parks and stronger than the twelfth:
those are public downloads, SMPTE ST 336 needs a budget, and this one needs an **access** decision.

**And obtaining it may not be the same act as pinning it.** A third-party standards index carries
two ADatP-36 records, one marked NATO RESTRICTED and one — matching Edition A — unmarked. **Which
edition the marking attaches to is not established**, and nothing here asserts that Edition B is
classified or that it is not; the statement that decides it is the NSDD classification line on the
record, and it is not in hand. So the park closes down one of two branches:

- **Branch U — unclassified or public.** The plan above, unchanged: the copy lands in `spec/` beside
  the covering document, untracked, and its identity and SHA-256 join the pin table on this page.
- **Branch R — NATO RESTRICTED.** **Cite-not-carry.** The document's promulgation identity, edition,
  date and NSDD classification line are recorded; its bytes never enter this repository — no pin, no
  hash of them, no PDF in `spec/` even untracked — and a mapping table would rest on clause
  citations rather than on quotations. The precedent is `FORMAT_COVERAGE.md`'s AEDP-12 Edition A
  (2014) row, whose bytes are likewise outside the tree; that one is a defect `3e0aed0` recorded as
  such, and this one would be deliberate and would record no hash to leave unverifiable.

The NSDD visit therefore has to return **two** facts, not one: the classification line, and which
version of Edition B the copy is. `tests/test_cdm_pins.py` already carries the representation for
the second branch — a **cited class** disjoint from the pin set, which fails loudly if a cited
document grows bytes on disk, and which is legal and empty today.

Until then #9 is a pinned covering document, two names and this file.
