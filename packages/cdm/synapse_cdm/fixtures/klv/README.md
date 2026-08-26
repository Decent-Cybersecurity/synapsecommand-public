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
218 pages carries a length octet above `0x24`.

**A third round followed that route, and it is six pages long.** `ST 0601.8-03` reads "All UAS
Datalink LS metadata shall be expressed in accordance with MISB ST 0107 [5]", so **MISB ST 0107.3,
KLV Metadata in Motion Imagery** was obtained from NSG Registry document 4738 and pinned at
`spec/ST0107.3.pdf`, SHA-256 `500d6752…98b69794`. **It states the length grammar on its own
account, and park 4 is CLOSED** — the second park to close, and the cheapest in the table. §6.3.2
prints four encodings of two lengths while explaining which two are wasteful, `ST 0107.3-05` requires
"the fewest possible bytes" as **live** text where ST 0601.14a had only a deprecated requirement, and
§6.3.1 states the BER-OID chain rule for any width. **Park 8 stays OPEN** and now owns two absences:
`0x80` as a first length octet, which ST 0107.3 never mentions, and any ceiling on the count of
length octets, which it does not state. Neither is reachable from a conforming stream, which is why
`klv_codec` walks a local set end to end with park 8 open.

All 141 tag rows still stay `not yet`; a framing rule says where an item begins and never what it
means. What changed is that this repository can now **find** every item in a UAS Datalink LS packet
and still **decode** no value in one.

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

- **`spec/klv_pin.json`** — the pinned identity of all six documents and every value extracted from
  them that a ruling cites, each with its locus. Written first, for the reason the Legion, CAT021
  and CAT048 pins were: a quotation with no pin behind it is a recollection.
- **`spec/nato-stanag-4609-edition-5.pdf`** and **`spec/misb-misp-2019-1.pdf`** — in the working
  tree because they had to be read, and **not committed**, matching every other adapter here.
  `git ls-files | grep -c '\.pdf$'` is 0 across the whole repository.
- **`spec/ST0601.14a.pdf`**, **`spec/ST0102.12.pdf`**, **`spec/ST0601.19.pdf`** and
  **`spec/ST0107.3.pdf`** — four of the fourteen delegated documents, all obtained 2026-08-26, in the
  working tree and **not committed** on the same rule. Three of the four are editions MISP-2019.1
  pins: **ST 0601.14** (Appendix B ref [53]), **ST 0102.12** (ref [55]) and **ST 0107.3** (ref [14]).
  **ST 0601.19 is not** — it is five major revisions later — and it is kept as **context only**, never
  as a source of tag semantics, for the item-42 divergence note and for the measured delta between the
  two editions. `spec/klv_pin.json`'s `reconciliation_ruling` records every reading verbatim and rules
  on each.

  **`ST0107.3.pdf` is the one that closed a park**, and it is the smallest document in this
  directory: six pages against ST 0601.14a's 218, carrying the rule 218 pages could not state. Its
  cover reads `MISB ST0107.3` with **no letter suffix** and `1 November 2018`, which agrees with the
  registry's reported edition date and with the footer of all six pages — so unlike `ST0601.14a.pdf`
  there was nothing to adjudicate, and the KLV 10 hazard was looked for and absent. Two of its
  thirteen requirements are prefixed **`ST 0107.2`** rather than `ST 0107.3`, because MISB stamps a
  requirement with the edition that introduced it; register entry **KLV 12**, and it matters because
  the length codec's endianness cites one of them.

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
| `spec/ST0107.3.pdf` | `500d67522269e5fcbc39bec2521849dffdf2698ff40132552f3fd28998b69794` | 656 949 | 6 |

Those six rows are also stated in `spec/klv_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two.

## What `framing/` is, and what it is not

**Twenty-six byte-level fixtures for the framing rules the two held documents state**, written only by
`spec/build_fixtures.py` — the Universal Label and two ways of getting it wrong, BER-OID tags at every
width boundary either document establishes, nine BER lengths, two key/length/value triplets, two whole
packets, the refusals at the edges of all of it, and the document's own checksum vector. Each is a
`.klvframe` of raw octets beside a `.parsed.json` twin carrying the section that authorises it and
**both** pinned digests.

**They are not adapter fixtures and the harness cannot replay one.** No CDM object comes out of any
of them. They sit in a subdirectory rather than here so that the claim at the top of this file stays
true and stays checked: the harness selects "immediate children of the directory that are files", so
a run pointed at this directory still finds nothing and still fails.

**Three classes of fixture were omitted rather than guessed by the framing round, and all three are
now here.** Each needed a rule that round could not establish — every length fixture including the
truncated-length malformation; every key/length/value triple, which needs a length one rule up; and
the 16383 → 16384 tag transition, which needs a third BER-OID octet. **MISB ST 0107.3 discharged all
three.** §6.3.2 gives the length grammar, so the triples follow, and §6.3.1 gives the chain rule for
any width, so `tag_three_octet_lowest` replaces the refusal `tag_third_continuation_octet`. Four of
the nine length fixtures are the document's **own octets**: `0x02`, `0x8180`, `0x8102` and
`0x8300 0080`, the four encodings §6.3.2 prints while explaining which two are wasteful.

**One fixture is still a park, and it is the only one.** `length_indefinite_first_octet` — the single
octet `0x80`, a long form declaring zero following octets — raises `UnderivableFromPinnedCopy`, because
ST 0107.3 never mentions that form and BER's indefinite length is **SMPTE ST 336:2017**, park 8, a
purchase. `spec/build_fixtures.py` asserts the exception **type** for it, so a later round that decides
what `0x80` means without buying the document fails in the generator.

## Why no `.klv` payload can be written yet — and the reason CHANGED

**It is no longer the length grammar.** That was the reason for two rounds: a `.klv` payload is a
sequence of key/length/value triplets, and this phase did not hold the document that says how a length
is written. `MISP-2015.1-08` delegated the formatting to MISB ST 0107.3, **which is now held**, and
`framing/` contains two whole packets built from its grammar.

**The reason now is tag semantics.** A `.klv` fixture for adapter `stanag4609` is a payload beside a
`.parsed.json` holding the **parsed form** the never-drop check measures against — and a parsed form
is a CDM `Entity`, which means every value octet has to become a field. That needs park 3 for the
epoch and park 5 for the IMAPB ranges, and there is no adapter to produce an `Entity` at all. The
packets in `framing/` are exactly the octets such a payload would be made of, and they are
deliberately **not** in this directory, where the harness would find them.

Writing a payload anyway would produce a golden file recording what our own guess decodes to and a
green harness run asserting that the two agree — the round-trip trap `../../README.md` names under
"Three things the harness cannot check for you": self-consistency without an external anchor. That
trap has not moved; only the rule that was missing has.

The twelve planned fixtures and the park that gates each one are tabulated in
`../../FORMAT_COVERAGE.md` under "The fixtures — planned here, before they exist". When the parks
close, each will ship as a twin — a `.klv` payload and a `.parsed.json` holding the parsed form the
never-drop check measures against — on the pattern `adsb`, `cat021` and `cat048` already use, and
`spec/build_fixtures.py` is their single source of truth: it exists now, builds all twenty-six of
`framing/`, and grows a second half when an `Entity` can be produced.
