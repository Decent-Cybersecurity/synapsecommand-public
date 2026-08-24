# ASTERIX Category 034 / Monoradar Service Messages fixtures

**There are none yet, and there is a plan for sixteen plus four refusals.** Adapter `cat034` is at
Phase 1: the row set in `../../FORMAT_COVERAGE.md` is written and reviewed as a specification,
every row of it says `not yet`, and no adapter code, no codec and no fixture exists. What is here
is a pinned document, three edition PDFs that are not pins, and this file.

```bash
# Today this FAILS, deliberately, and it fails TWICE over — the same two failures
# fixtures/klv/README.md and fixtures/fft/README.md record, in the same order. The adapter name
# does not resolve yet, so `--adapter cat034` raises `LookupError: unknown adapter 'cat034'` and
# exits 1. Substitute any registered adapter and it fails again, this time on the directory:
# exit code 2, `NoFixturesFound`, because the only thing in here is spec/ and a run that
# exercises nothing must not report a green.
PYTHONPATH=packages/cdm python -m synapse_cdm.harness --adapter cat034 \
    --fixtures packages/cdm/synapse_cdm/fixtures/cat034
```

**`cat034` is adapter #12.** The forecast made good. The ordinal was already spoken for by one
sentence in the declines table of the section for adapter #11 — "if it lands, it lands as adapter
#12 with its own pin" — and it has landed, with its own pin, at the number that was held for it. The series is tabulated once, in "The adapter
ordinals, and the reserved-ordinal rule" near the top of `../../FORMAT_COVERAGE.md`, and that table
is the authority `tests/test_cdm_ordinals.py` checks every other site against.

## The two names, and why they are one string here

**The directory is `cat034`, the adapter is `cat034`, and they are the same on purpose.** That is
the opposite of `fixtures/fft`, where the two differ and one of them is provisional, and it is not
a relaxation of that rule — it is the rule reaching a case it does not bite on.

A directory holds *payloads* and a payload is not a standard: that split puts adapter
`stanag4676`'s fixtures in `fixtures/nits`, `stanag4609`'s in `fixtures/klv` and `stanag5527`'s in
`fixtures/fft`. It bites only when the adapter is named after a **standard**. Here the adapter is
already named after the **content** — an ASTERIX category *is* the payload, and `.cat034` is what
these files will be called — so the two coincide, exactly as `cat021`'s and `cat048`'s do.

**And this is the first name ruling in this repository that precedent decides.** The three STANAG
rulings each had to say that the roster carries both conventions "so precedent does not decide it
and the documents have to". Inside the ASTERIX family the convention is unanimous — `cat021`,
`cat048`, and no counter-example — so precedent decides it, and the document confirms the precedent
is applicable by being a content document at all: twelve data items, each with a Definition, a
Format, a Structure and an Encoding Rule, and a fourteen-FRN standard UAP. `spec/cat034_pin.json`
carries the full ruling with its four rejected candidates.

## What is here

- **`spec/cat034_pin.json`** — the pinned identity of the document and every value extracted from
  it that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021,
  CAT048, KLV and FFT pins were: a quotation with no pin behind it is a recollection.
- **`spec/eurocontrol-asterix-cat034-pt2b-ed129.pdf`** — in the working tree because it had to be
  read, and **not committed**, matching every other adapter here. `git ls-files | grep -c '\.pdf$'`
  is 0 across the whole repository.
- **`spec/history/`** — three edition PDFs that are **not pins**. See below.

| Document | SHA-256 | Bytes | Pages |
|---|---|---|---|
| `spec/eurocontrol-asterix-cat034-pt2b-ed129.pdf` | `32925e6a04d124cf1f699adb68371bd88806d8cc4ae957df8aacba18cfcae101` | 639 615 | 41 |

That row is also stated in `spec/cat034_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two. The pin row is asserted as **one composite string** rather than as hash,
bytes and pages separately, which is the residue of the mutation found inside `klv_pin.json`:
changing a page count left the suite green because the right number still occurred elsewhere.

## The pin is the covering edition and not the current one

**Edition 1.29 is the newest edition in hand. It is not the newest published**, and this repository
held the proof before this round began: `../cat048/spec/cat048_pin.json` quotes CAT048 Edition
1.32's §2.2 reference 5 naming "Category 034 Monoradar Service Messages (EUROCONTROL-SPEC-0149-2b)
**Edition 1.30**".

Every row of the row set is read against Edition 1.29 and none against any other edition. What
Edition 1.30 is known to contain — **Message Type 008**, the Interrogator-Code-conflict area — is
established from two independent sources agreeing: CAT048 §5.2.3 NOTE 6 says so outright, and the
four editions here show the Message Type list growing 004 → 004 → 005 → 007 and stopping one short.
That is recorded **as an inference**; no text of Edition 1.30 has been read.

**The reopen condition is the weakest park in this repository.** Not an access decision like #9's
and not a purchase like KLV's park 12 — a public download, on the same terms as the four already
here, that nobody has performed. `message_type_008` is planned as a fixture *now* so that the day
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

## Why no fixture exists yet, and what each planned one is for

Not scheduling, and not the KLV or FFT situation either — those cannot write a fixture because the
document that says what a payload *is* is absent. Here the document is present and complete. What
is absent is **adapter code**, and this repository's standing protocol writes the row set first: a
fixture built before the mapping is a fixture that encodes whatever the implementation happened to
do. `../../FORMAT_COVERAGE.md` lists all twenty planned fixtures with the defect each is there to
catch, and four of them are refusals.

**Everything will be synthetic.** No recorded traffic, no real radar head. Every block built from
field values by `spec/build_fixtures.py` — a data block is raw octets and cannot carry a comment,
and its `LEN` and FSPEC are functions of its contents, so a hand-edited byte file is a mis-parse
waiting to happen. Each fixture ships twice, `<name>.cat034` and `<name>.parsed.json`, because
`lossless.unrepresented()` has no leaf structure to harvest from bytes.

**The SAC evidence transfers by citation, not by analogy.** `I034/010` is the same two-octet
SAC/SIC item CAT021 uses, published in the same EUROCONTROL allocation tables, and
`../cat021/spec/sac_pin.json` already holds a retrieved and hashed copy of them in which `0x29` is
listed with an explicitly empty country cell in the EUR table and nowhere else. Same item, same
URL, same pinned copy — so these fixtures use `SAC = 0x29` without a second retrieval, and `SIC`
carries no allocation claim at all for the reason the CAT021 row gives.

Until adapter code exists, #12 is a pinned document, a row set, a lineage and this file.
