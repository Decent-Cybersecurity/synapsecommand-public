# ASTERIX Category 034 / Monoradar Service Messages fixtures

**Twenty of them: seventeen translatable, three refusals.** Adapter `cat034` is at Phase 2 —
`adapters/asterix_cat034.py` on the codec in `adapters/cat034_codec.py`, bidirectional, and every
row of the row set in `../../FORMAT_COVERAGE.md` now reads `cat034 1.0.0`. Phase 1 wrote and
reviewed that row set as a specification with no code behind it; this directory is what shipped
against it.

```bash
PYTHONPATH=packages/cdm python -m synapse_cdm.harness --adapter cat034 \
    --fixtures packages/cdm/synapse_cdm/fixtures/cat034
# 34 passed, 0 failed — seventeen payloads, each replayed twice
```

**Thirty-four, not seventeen, and the doubling is the point.** Each fixture ships as
`<name>.cat034` for the octets and `<name>.parsed.json` for exactly what the parser produces,
because `lossless.unrepresented()` has no leaf structure to harvest from bytes: a blocks-only set
would show a green run with the never-drop rule never executed. The binary twin gets `SKIP` on the
lossless check and says so; the parsed twin gets the check at full strength.

The three refusals live in `refusals/` and are **not** replayed by the harness, because the refusal
is the expected output and a harness that translated one would be reporting a pass on a block the
adapter must reject. `../../../../../tests/test_cdm_asterix_cat034_adapter.py` runs them and
asserts the message names what was wrong.

**`cat034` is adapter #12.** The forecast made good, then made real. The ordinal was spoken for by
one sentence in the declines table of the section for adapter #11 — "if it lands, it lands as
adapter #12 with its own pin" — and it landed at that number with that pin. The series is tabulated
once, in "The adapter ordinals, and the reserved-ordinal rule" near the top of
`../../FORMAT_COVERAGE.md`, and that table is the authority `tests/test_cdm_ordinals.py` checks
every other site against.

## The two names, and why they are one string here

**The directory is `cat034`, the adapter is `cat034`, and they are the same on purpose.** That is
the opposite of `fixtures/fft`, where the two differ and one of them is provisional, and it is not
a relaxation of that rule — it is the rule reaching a case it does not bite on.

A directory holds *payloads* and a payload is not a standard: that split puts adapter
`stanag4676`'s fixtures in `fixtures/nits`, `stanag4609`'s in `fixtures/klv` and `stanag5527`'s in
`fixtures/fft`. It bites only when the adapter is named after a **standard**. Here the adapter is
already named after the **content** — an ASTERIX category *is* the payload, and `.cat034` is what
these files are called — so the two coincide, exactly as `cat021`'s and `cat048`'s do.

**And this is the first name ruling in this repository that precedent decides.** The three STANAG
rulings each had to say that the roster carries both conventions "so precedent does not decide it
and the documents have to". Inside the ASTERIX family the convention is unanimous — `cat021`,
`cat048`, and no counter-example — so precedent decides it, and the document confirms the precedent
is applicable by being a content document at all: twelve data items, each with a Definition, a
Format, a Structure and an Encoding Rule, and a fourteen-FRN standard UAP. `spec/cat034_pin.json`
carries the full ruling with its four rejected candidates.

**The module name carries the family prefix and the registered name does not.** `cat034` is what
the registry, every `SourceRef` and `--adapter` use; `adapters/asterix_cat034.py` is where the code
lives. That is not a second convention — it is the same split `adapters/asterix_cat021.py` and
`adapters/asterix_cat048.py` already make on disk, and the ruling records it as the reason
`asterix034` and `asterix_cat034` were rejected as *registered* names.

## What is here

- **`spec/cat034_pin.json`** — the pinned identity of the document and every value extracted from
  it that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021,
  CAT048, KLV and FFT pins were: a quotation with no pin behind it is a recollection. Amended at
  Phase 2 where the shipped adapter settled a question the record had left open.
- **`spec/build_fixtures.py`** — the source of truth for both artefacts. Edit it, never the
  `.cat034` octets and never the `.parsed.json` twins: a record's FSPEC and its block's `LEN` are
  functions of the contents, so a hand-edited byte file is a mis-parse waiting to happen. It
  carries a `check_layouts()` that asserts every encoder emits exactly the octet count §5.2 and
  Table 3 state for its item, and the test module calls it, so it cannot be skipped by not running
  the generator.
- **`spec/eurocontrol-asterix-cat034-pt2b-ed129.pdf`** — in the working tree because it had to be
  read, and **not committed**, matching every other adapter here. `git ls-files | grep -c '\.pdf$'`
  is 0 across the whole repository.
- **`spec/history/`** — three edition PDFs that are **not pins**. See below.
- **`golden/`** — one golden file per replayed fixture, thirty-four of them, written under the
  harness's frozen clock.

| Document | SHA-256 | Bytes | Pages |
|---|---|---|---|
| `spec/eurocontrol-asterix-cat034-pt2b-ed129.pdf` | `32925e6a04d124cf1f699adb68371bd88806d8cc4ae957df8aacba18cfcae101` | 639 615 | 41 |

That row is also stated in `spec/cat034_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two. The pin row is asserted as **one composite string** rather than as hash,
bytes and pages separately, which is the residue of the mutation found inside `klv_pin.json`:
changing a page count left the suite green because the right number still occurred elsewhere.

## Edition 1.30 is cited twice and published nowhere

**Edition 1.29 is the newest edition in hand and it is also the newest edition PUBLISHED** —
EUROCONTROL's Category 034 publication page was checked on **2026-08-24** and the newest file it
offers is Edition 1.29, the edition pinned here. Phase 1 recorded the opposite, from a citation and
without a check, and this is the correction.

**The fact is two-part and both parts are recorded.**

- **Cited.** Two independent sibling specifications name an Edition 1.30 of Part 2b:
  `../cat048/spec/cat048_pin.json` quotes CAT048 Edition 1.32's §2.2 reference 5 naming "Category
  034 Monoradar Service Messages (EUROCONTROL-SPEC-0149-2b) **Edition 1.30**", and CAT007 Edition
  1.12 of July 2024 carries the same reference in its own §2.2. Neither is quoting the other and
  neither is quoting this repository, and they are three years apart. That the edition exists is
  not in doubt.
- **Unpublished.** It is not offered on the publisher's own page for the category. That is a state
  this repository had no name for: not a pin, not a park like KLV's twelve obtainable-and-not-
  obtained documents, not #9's classification contingency. **Cited-but-unpublished** — which is a
  CLASS, checked by `tests/test_cdm_pins.py` and printed by the pin gate, not a description. Its
  two halves are computed from the data rather than declared: the citation is found by reading
  quotations across the pin records, and the availability comes from the dated check in
  `spec/cat034_pin.json`. The day Edition 1.30 publishes, the gate fails.

**The check date is recorded because a future round needs it.** "Was not published" and "was not
checked" look identical six months later, and the difference decides whether the next reader
re-checks the page or re-reads this paragraph.

Every row of the row set is read against Edition 1.29 and none against any other edition. What
Edition 1.30 is known to contain — **Message Type 008**, the Interrogator-Code-conflict area — is
established from two sources agreeing: CAT048 §5.2.3 NOTE 6 says so outright, and the four editions
here show the Message Type list growing 004 → 004 → 005 → 007 and stopping one short. That is
recorded **as an inference** and the availability check does not touch it: a page that does not
offer a document says nothing about what the document contains. No text of Edition 1.30 has been
read.

**The reopen condition got weaker rather than being met.** Phase 1 called it the weakest park in
this repository — a public download nobody had performed, where the only obstacle was effort.
Effort will not close it now. `message_type_008` ships as a fixture *today* so that the day
Edition 1.30 lands, one fixture changes from a park to a translation.

## The edition history — three editions, and none of them a pin

`spec/history/` holds editions **1.26, 1.27 and 1.28**, untracked. The treatment is CAT048's,
adopted unchanged rather than re-derived: it was ruled in commit `844e336` and is recorded in
`../cat048/spec/cat048_pin.json` under `edition_history` and in `../../FORMAT_COVERAGE.md` under
"The edition history — 22 editions in hand, and none of them a pin".

| Edition | Date | Status | Document identifier | Pages |
|---|---|---|---|---|
| 1.26 | November 2000 | Released Issue | `SUR.ET1.ST05.2000-STD-02b-01` | 38 |
| 1.27 | May 2007 | Released Issue | `SUR.ET1.ST05.2000-STD-02b-01` | 38 |
| 1.28 | 02/03/2021 | Released Edition | `EUROCONTROL-SPEC-0149-2b` | 43 |

All three digests verified against the manifest before use and re-verified at the committed path
after landing: 3/3 both times. **The pinned edition is not among them** — it lives in `spec/`
itself, and a second copy under `history/` would be an unrecorded PDF that the pin gate's closure
check would be right to reject. `tests/test_cdm_pins.py` asserts exactly that.

**Two facts of the lineage are worth the reader's time**, and both are sourced to the documents
rather than to their filenames:

- **The reference number migrated between 1.27 and 1.28**, `SUR.ET1.ST05.2000-STD-02b-01` →
  `EUROCONTROL-SPEC-0149-2b`, and both sides of the boundary are in hand — the rare migration that
  is bracketed rather than inferred. Part 4 made the same move four and a half years earlier, at
  its edition 1.22. An ICD citing the old reference is citing 2007 or older, which is **four**
  Message Types rather than seven.
- **Category 034 is the successor of Category 002**, and the whole of the evidence is EUROCONTROL's
  own publication filename for edition 1.26. "Category 002" occurs **zero** times in the body of
  all four editions. Recorded at that strength — a publisher's filename, weaker than a clause and
  stronger than a recollection — and *not* used to name anything. The identical device names Part 4
  "next version of cat-001" in six of the CAT048 history filenames, and that adapter is `cat048`.

## The editions the fixture set can tell apart

**Message types 006 and 007 are Edition 1.29's own additions** — its change record reads "Data
Item I034/000: new message types 6&7", and Edition 1.28 standardises 001 to 005. So an adapter
accidentally written against Edition 1.28 would lack exactly those two, and `mode_s_jamming_strobe`
is the fixture that catches it: under an Edition 1.28 vocabulary that record classifies as an
undefined message type at `STATUS_CHANGE` / `ADVISORY` instead of as an `ALERT` at `WARNING`. The
edition the adapter was written against is therefore a property the suite can measure, not a claim
in a docstring.

## Everything here is synthetic

No recorded ASTERIX traffic, no real radar head, and nothing is hand-written.

**The SAC evidence transfers by citation, not by analogy.** `I034/010` is the same two-octet
SAC/SIC item CAT021 uses, published in the same EUROCONTROL allocation tables, and
`../cat021/spec/sac_pin.json` already holds a retrieved and hashed copy of them in which `0x29` is
listed with an explicitly empty country cell in the EUR table and nowhere else. Same item, same
URL, same pinned copy — so these fixtures use `SAC = 0x29` without a second retrieval, and `SIC`
carries no allocation claim at all for the reason the CAT021 row gives.

**Station coordinates are in the Gulf of Riga, off Ventspils**, matching the other five sets. The
one station with a position carries a **negative** ellipsoidal height, which is a legal WGS-84
value and is what exercises §5.2.12's signed height field end to end.

**Times come from the injected clock, never the wall clock.** `midnight_rollover_nearest` is built
so the wrap happens under the harness's *own* frozen instant rather than only under one a test
injects — the failure `../../README.md` records for CAT048's two rollover fixtures, which described
times that resolved to the receipt date at the frozen instant and so tested no rollover in either
direction.

**One of the twenty was asked for by a mutation rather than by the plan.** `spare_bits_nonzero`
exists because zeroing a spare bit inside the decoder passed every test: every fixture in the Phase
1 plan has its spare bits at zero, and a dropped zero re-encodes as a zero. §4.4 is normative about
exactly that — "Decoders of ASTERIX data shall **never assume and rely on** specific settings of
spare or unused bits" — so a set that cannot tell a read spare bit from an assumed one is not
testing the round trip the document requires.

`../../FORMAT_COVERAGE.md` lists all twenty fixtures with the defect each one is there to catch,
and names the five Phase 1 rows Phase 2 changed and why.
