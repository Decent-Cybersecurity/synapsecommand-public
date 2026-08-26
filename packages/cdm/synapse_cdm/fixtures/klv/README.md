# STANAG 4609 / MISP-2019.1 KLV fixtures

**There are none yet, and that is the state this directory is in rather than a step somebody
forgot.** The sentence means what it has always meant and the qualifier is now load-bearing: there is
no **adapter** fixture. Adapter `stanag4609` is at Phase 1, the row set in
`../../FORMAT_COVERAGE.md` is written with `not yet` in all 141 tag rows, and there is no adapter
code and no `.klv` payload. This directory holds `spec/` and — since the framing round of
2026-08-26 — `framing/`, and `framing/` is not a payload directory. See "What `framing/` is, and
what it is not" below.

**That did not change on 2026-08-26, and the thing that did change is worth stating precisely.** ST
0601.14 — the field dictionary MISP-2019.1 delegates the whole airborne collection to — was obtained,
pinned and transcribed: 141 items, in `../../FORMAT_COVERAGE.md`'s ST 0601 row set and in
`spec/klv_pin.json`'s `tag_table_st_0601_14`. That closed **park 1**, the largest of the twelve. It
did not produce a fixture and could not have: a `.klv` payload is a sequence of key/length/value
triplets, and the documents that say how a key and a length are written are still parks 4 and 8.
**Holding the dictionary made the stream nameable, not readable.**

**A later round the same day asked how much of that is actually true of ST 0601.14, and two thirds of
it is not.** ST 0601.14a **states** the 16-byte Universal Label (§6.2), the BER-OID tag form and its
127/128 width transition (§7.1), the two-octet bit pattern and its 14-bit ceiling (Figure 67), the
checksum algorithm with a worked vector (§6.6 and §8.1.1.2) and the Zero-Length Item (§6.5). It
**delegates the BER length grammar and nothing else**: `ST 0601.8-07` states the constraint and is
marked *(Deprecated)*, the live route `ST 0601.8-03` sends it to ST 0107.3, and no worked example in
218 pages carries a length octet above `0x24`. So **parks 4 and 8 both stay OPEN** — no document was
obtained — and what changed is their size: park 8 owned "key forms, the 16-byte Universal Label, the
length forms" and now owns the length grammar and the third BER-OID octet. All 141 tag rows stay
`not yet`; a framing rule says where an item begins and never what it means.

```bash
# Today this FAILS, deliberately, and it fails TWICE over — which is worth knowing before you
# debug it. The adapter name does not resolve yet, so `--adapter stanag4609` raises
# `LookupError: unknown adapter 'stanag4609'` and exits 1. Substitute any registered adapter and
# it fails again, this time on the directory: exit code 2, `NoFixturesFound`, because the only
# thing in here is spec/ and a run that exercises nothing must not report a green.
python -m synapse_cdm.harness --adapter stanag4609 --fixtures .   # from THIS directory
```

**The directory is `klv` and the adapter is `stanag4609`, and the two names differ on purpose.**
The adapter takes the STANAG's number because STANAG 4609 is, in MISP-2019.1 §C.1.2's own words,
"a covering document rather than a standalone document, which points directly to a version of the
U.S. Motion Imagery Standards Profile (MISP)" — five pages, one of which is a Letter of
Promulgation — so there is no NATO document whose *content* could name the adapter. The directory
takes the content's name because a directory holds payloads and a payload is not a standard, which
is the same split that puts adapter `stanag4676`'s fixtures in `fixtures/nits`. The reasoning, and
the three rejected alternatives (`misp`, `misb`, `fmv`), are in `spec/klv_pin.json` and in the
`FORMAT_COVERAGE.md` section.

What is here:

- **`spec/klv_pin.json`** — the pinned identity of all five documents and every value extracted from
  them that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021
  and CAT048 pins were: a quotation with no pin behind it is a recollection.
- **`spec/nato-stanag-4609-edition-5.pdf`** and **`spec/misb-misp-2019-1.pdf`** — in the working
  tree because they had to be read, and **not committed**, matching every other adapter here.
  `git ls-files | grep -c '\.pdf$'` is 0 across the whole repository.
- **`spec/ST0601.14a.pdf`**, **`spec/ST0102.12.pdf`** and **`spec/ST0601.19.pdf`** — three of the
  fourteen delegated documents, all obtained 2026-08-26, in the working tree and **not committed**
  on the same rule. Two of the three are editions MISP-2019.1 pins: **ST 0601.14** (Appendix B
  ref [53]) and **ST 0102.12** (ref [55]). **ST 0601.19 is not** — it is five major revisions later
  — and it is kept as **context only**, never as a source of tag semantics, for the item-42
  divergence note and for the measured delta between the two editions. `spec/klv_pin.json`'s
  `reconciliation_ruling` records every reading verbatim and rules on each.

  **The `a` in `ST0601.14a.pdf` is not a typo and the filename is not normalised.** The NSG Registry
  serves the edition cited as "ST 0601.14" under that name, and its cover reads `MISB ST 0601.14a`:
  a single-letter *Minor Version*, which the standard's own §2 says is a correction to the major
  version and which "the MISB will not update the referring document" to reflect. So the **filename
  states the copy**, the pin record's `edition` field states the **edition the profile cites**, and
  the **SHA-256 states the identity**. Renaming the file to match the citation would make four
  sites agree about a file that does not exist. Register entry **KLV 10**.

| Document | SHA-256 | Bytes | Pages |
|---|---|---|---|
| `spec/nato-stanag-4609-edition-5.pdf` | `f2f9ae1a5a74528664a8751c3c105161f4597b1041928b7cedba1a57b2dbf8d8` | 273 801 | 5 |
| `spec/misb-misp-2019-1.pdf` | `3167362ace20746ed13e85522130c2e9f3fc9ecf62a112bd75bdced7b102d5ea` | 1 372 771 | 73 |
| `spec/ST0601.14a.pdf` | `3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4` | 3 969 201 | 218 |
| `spec/ST0601.19.pdf` | `e53c1e7bfdda888d5946610f89a8146a3f339394e1b127807302676c0cfb92b1` | 4 700 978 | 226 |
| `spec/ST0102.12.pdf` | `20d40b5237cdcd2f486547add8eee238e37d5a6b11b7e0aca306be0785eca267` | 514 842 | 18 |

Those five rows are also stated in `spec/klv_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two.

## What `framing/` is, and what it is not

**Thirteen byte-level fixtures for the framing rules ST 0601.14a states on its own account**, written
only by `spec/build_fixtures.py` — the Universal Label and two ways of getting it wrong, BER-OID tags
at every width boundary the document establishes, three refusals at the edges of those rules, and the
document's own checksum vector. Each is a `.klvframe` of raw octets beside a `.parsed.json` twin
carrying the section that authorises it.

**They are not adapter fixtures and the harness cannot replay one.** No CDM object comes out of any
of them. They sit in a subdirectory rather than here so that the claim at the top of this file stays
true and stays checked: the harness selects "immediate children of the directory that are files", so
a run pointed at this directory still finds nothing and still fails.

**Three classes of fixture were omitted rather than guessed**, because each needs the rule this round
could not establish: every length fixture, including the truncated-length malformation; every
key/length/value triple, which needs a length one rule up; and the 16383 → 16384 tag transition,
which needs a third BER-OID octet. They are named in `../../FORMAT_COVERAGE.md` and in
`spec/klv_pin.json`'s `framing_ruling_st_0601_14` rather than being absent.

## Why no `.klv` payload can be written yet

Not scheduling. A `.klv` payload is a sequence of key/length/value triplets, and **this phase does
not hold the document that says how a length is written**: `MISP-2015.1-07` delegates the
encoding to SMPTE ST 336:2017, which is behind a paywall, and `MISP-2015.1-08` delegates the
formatting to MISB ST 0107.3, which is a public download that was not obtained. Writing bytes
anyway would produce a file that *looks* like KLV, a golden file recording what our own guess
decodes to, and a green harness run asserting that the two agree — the round-trip trap
`../../README.md` names under "Three things the harness cannot check for you": self-consistency
without an external anchor.

The twelve planned fixtures and the park that gates each one are tabulated in
`../../FORMAT_COVERAGE.md` under "The fixtures — planned here, before they exist". When the parks
close, each will ship as a twin — a `.klv` payload and a `.parsed.json` holding the parsed form the
never-drop check measures against — on the pattern `adsb`, `cat021` and `cat048` already use, and
`spec/build_fixtures.py` is their single source of truth: it exists now, builds `framing/`, and grows
a second half when a length can be written.
