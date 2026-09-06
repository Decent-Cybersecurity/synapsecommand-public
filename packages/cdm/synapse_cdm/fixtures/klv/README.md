# STANAG 4609 / MISP-2019.1 KLV fixtures

**There are THIRTY-SEVEN, and for six rounds there were none.** **There were TEN from the
witnessed-set round of 2026-08-26 until the park 2 round of 2026-09-04**, which added the seven
`security_*` payloads below when MISB ST 0102.12's element table was read into item 48 — the
sentence is re-dated rather than silently re-synced, because its subject is a count that moved and
a bare present tense is what let the delegated-document tally go stale within a day.
**There were SEVENTEEN** from that round until the **text-pins round** of the same day, which added
the six
`security_object_country_codes_*` payloads once IETF RFC 2781 was held and tag 13's byte order
could be read off a document instead of guessed. **There were TWENTY-THREE** from that round until
the **park 5 round** of the same day, which added nine payloads for the fifteen
document-witnessed items. **There were THIRTY-TWO** from that round until the **park 3
round**, later the same day, which added the five payloads at the end of the table below for
items 136 and 137 once MISB ST 0603.5 was held and the MISP Time System had a definition
here. **FOUR rounds moved this count on 2026-09-04 and every intermediate value is kept**,
for the reason the paragraph below gives.

**AND THE SENTENCE THIS ONE REPLACES HAD DECAYED, WHICH IS WORTH MORE THAN THE COUNT.** It said
**SEVENTEEN** while twenty-three payloads sat in this directory: the text-pins round added six and
re-dated nothing, and **the guard that reads this file asserted the stale string rather than
catching it** — `test_the_klv_fixture_directory_holds_the_generators_payloads_and_says_what_each_
catches` carried `assert "There are SEVENTEEN" in readme`, a literal naming a number it did not
derive, which pins the prose to whatever it last said. **The six payloads were also missing from
the table below entirely**, so the count and the enumeration were stale in the same direction and
neither could catch the other. Both are repaired here and the guard now derives the count from the
generator, so a round that adds a payload and leaves this sentence alone fails on the number
instead of passing on a string. **This is the third instance of the defect `gates/parks_table.py`
is named for** — a claim about a set that nothing re-derives — met in a README rather than in the
parks table. This file
opened with the sentence
"There are none yet, and that is the state this directory is in rather than a step somebody
forgot" from the day the directory was created until the witnessed-set round of 2026-08-26, and
that sentence is quoted here rather than deleted because what replaced it is the interesting part: **adapter `stanag4609` has
shipped**, and the pinned stream witnesses **26 of ST 0601.14a's 141 items** — the distinct tags the
one real stream this repository holds actually carries. **RE-DERIVED 2026-09-05 BY THE HOUSEKEEPING ROUND: the adapter covers 45
of the 141 and the other 96 read `not yet`** **RE-DERIVED 2026-09-05 BY THE PARK 11 ROUND AND MOVED ONE STEP: 46 of the 141 are promoted and the other 95 read `not yet`** — 26 stream-witnessed and **20** document-witnessed, the twentieth being item 94, the MIIS Core Identifier, admitted on a FOURTH ground: MISB ST 1204.1 defines its Value's whole structure, two held documents state its key identically at CRC 30280, and both print the same worked example. Counted off the Status column, not carried. in `../../FORMAT_COVERAGE.md`, and that is a scope
contract rather than a backlog — **with the contract crossed on two grounds, each ruled rather than
waived**: item 48, whose value is a nested Local Set another held document defines, and eighteen
items promoted on ST 0601.14a's own printed worked examples. **All three figures here kept the step
before the pre-release round of 2026-09-05, which promoted tag 75**, and this is the second time
this passage has gone stale between a round that moved the ledger row and a round that read it. This sentence said *the other 115* and
*one crossing* until the maintenance sweep moved it, and both halves went stale on 2026-09-04 in the
same four rounds — which is why the counts and the grounds are now cited to the ledger row that
derives them instead of stated a second time here. See "The ten payload fixtures, and the plan they replaced" below, and the
seven `security_*` rows at the end of the table. This directory also holds `spec/` and — since the
framing round of the same day — `framing/`, and `framing/` is still not a payload directory.

**That did not change on 2026-08-26, and the thing that did change is worth stating precisely.** ST
0601.14 — the field dictionary MISP-2019.1 delegates the whole airborne collection to — was obtained,
pinned and transcribed: 141 items, in `../../FORMAT_COVERAGE.md`'s ST 0601 row set and in
`spec/klv_pin.json`'s `tag_table_st_0601_14`. That closed **park 1**, the largest of the thirteen. It
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
§6.3.1 states the BER-OID chain rule for any width. **Park 8 stayed OPEN** after that round and owned two absences:
`0x80` as a first length octet, which ST 0107.3 never mentions, and any ceiling on the count of
length octets, which it does not state. Neither is reachable from a conforming stream, which is why
`klv_codec` walked a local set end to end with park 8 open.

**PARK 8 CLOSED 2026-09-03**, on SMPTE ST 336:2017 and SMPTE 336M-2007 obtained free from the
publisher's own library, and the two absences were ruled apart rather than together. `0x80` is
**STATED** at ST 336:2017 §5.3 — a *non-deterministic length*, usable only where an application
document defines another way to find the end of the Value, which no held MISB document does — so the
codec now refuses it as a `KLVFramingError` instead of parking it. Any ceiling on the count of length
octets is **DELEGATED ONWARD**: §5.3 NOTE 1 says ST 336 imposes none, and sends the rules to
ISO/IEC 8825-1 §8.1.3.3–8.1.3.5. So the absence was never a silence in two documents — it was one
document delegating and the other declining to exercise the delegation.

**A fourth round the same day pointed the codec at a REAL STREAM, and it ended in a park.** The
first three rounds read documents; this one read octets nobody here wrote. `streams/` now holds an
MPEG-2 transport stream (SHA-256 `a491ceff…260e`, **102 004 664 bytes**) and the **977-octet** KLV
extraction taken from it (`a810e4b6…2e51`) with
`ffmpeg -i day_flight.mpg -map 0:1 -c copy -f data day_flight.klv`, **ffmpeg 9.0.1** — a command
that was **re-run rather than recalled**, and reproduces those 977 octets byte for byte.
`walk_local_set` reads it end to end: **6 packets, 26 items each, 156 items, 0 octets left over,
every length field minimal, and all 6 checksums validate.** One thing does not fit — item 22 carries
**four** octets where §8.22 states a Required Length of **2** — and the round could not decide what
kind of thing that is, because item 65 declares edition **1** and **no held document dates any
item's introduction**: ST 0601.14a's revision history begins at edition 14, no item section carries
an introduction annotation, and its 33 requirement identifiers span editions 8, 9, 10, 13 and 14 and
reach edition 1 in none of them. So the stamp stood **unrefuted**, the classification parked as
**park 13**, and register entry **KLV 14** records why. **What the round did rule,
unconditionally: the framing layer is correct as shipped** — a valid minimal BER length, four opaque
octets, and a walk that knows no tags cannot owe a Required Length check. That is the
value-decoding layer's, and it does not exist.

**PARK 13 IS NOW CLOSED, and item 22's four octets are a STREAM DEFECT — candidate (a).** The
adjudication round obtained edition 1 and it is **not** named what the park called it: there is no
*MISB ST 0601.1*, edition 1 is **MISB EG 0601.1**, an Engineering Guideline, and the series became a
Standard at 0601.2 — register entry **KLV 15**. Its tag table states item 22 at a Len of **2**, three
times inside itself, including the worked example `[0d22][0d2][0x1F 9B]`. **The length never changed**
across every edition this repository can sample — the initial release, edition 1, .4, .8, .14a and
.19 — so the four octets diverge from the emitter's **own declared edition**, which killed both
candidates that needed edition 1 to differ. `EG0601.1.pdf` is pinned in `spec/`; the initial release,
`ST0601.4` and `ST0601.8` are the **0601 lineage** in `spec/history/` and are **not pins**. **The
framing ruling above is unchanged** — nothing in `klv_codec` moved, and the flag is still owed by the
value-decoding layer.

**THE STREAM'S ORIGIN IS NOW PINNED, and the lead about it did NOT verify.** A sixth round hunted
one question: is the held clip one of the "supplementary test files" EG 0601.1 §3 says replaced its
Appendix A? Three routes — the Wayback CDX index of the MISB's own host, four MISB-adjacent hosts,
and the sample collection's own provenance — produced **no MISB-served bytes, no same-named file
with different bytes, and no MISB listing naming the file**, so the lead is **closed as unverifiable
from the routes this repository can reach** rather than refuted. What verified instead is where the
held bytes came from: `https://samples.ffmpeg.org/MPEG2/mpegts-klv/Day%20Flight.mpg`, served as
`Day Flight.mpg`, and the evidence is **byte identity** — the re-fetched copy `cmp`s identical to
the pinned one. That closed a gap in this repository's own pinning: the stream pin had recorded a
hash and no **origin** for two rounds, where every PDF here records the URL that served it.
**Park 13's ruling is unaffected and would have been unaffected had the lead verified** — the
publisher of a file is an input to neither of the ruling's two bases, so four octets against a
stated length of two stand either way. `spec/klv_pin.json` carries the routes, the failure mode of
each, and MISB's own FAQ sentence explaining why routes 1 and 2 could not succeed: its test files
were behind an account on the MISB **protected** website.

**Neither stream file is committed, and the rule is a different one from the PDFs'.** `.gitignore`
excludes `fixtures/klv/streams/` as a **directory**, where the PDFs are excluded by **extension**.
An extension rule works for `spec/` because every file there is one of three known extensions; a
stream has no such discipline — the container arrived as `.mpg`, the extraction is `.klv`, and a
later round could hold `.ts` or a raw PID dump — so an extension rule would be a list somebody has
to remember to extend, and forgetting puts a hundred-megabyte binary in the index. Both files are
pinned by SHA-256 in `spec/klv_pin.json`, so a reader who obtains the transport stream can
reproduce and check both — and since the provenance round, the pin says **where to obtain it**.
`fixtures/klv/provenance/` is a **third** not-committed rule on the same directory pattern, holding
the nineteen fetched files that provenance round's sentences are derived from.

**A SEVENTH ROUND ENUMERATED THE WITNESSED SET AND SHIPPED THE ADAPTER.** The first three rounds
read documents, the fourth read octets, the fifth and sixth adjudicated what those octets meant. This
one asked which distinct tags the six packets carry — **26** — read every one of their §8.x blocks
out of `spec/ST0601.14a.pdf`, cross-read all 26 against `spec/EG0601.1.pdf`'s §7.N, ruled the
**length-divergence policy** item 22 forces, and shipped `adapters/stanag4609.py` against the 26.
**Every map was checked against the document that states it**: each §8.x block prints one Software
Value beside the KLV octets that encode it, and all 26 agree, as do the 23 examples edition 1
independently prints. `26 of 141` rows moved; **115 still read `not yet`**, blocked on the scope
contract rather than on a park.

**AN EIGHTH ROUND READ THE SIX EDITIONS AGAINST EACH OTHER AND CORRECTED THIS FILE.** It re-opened
parks 5, 9 and 11 and register entries KLV 14–17; **no park closed**, because all three acquisition
routes refused — `gwg.nga.mil` and `nsgreg.nga.mil` answered nothing and `web.archive.org` answered
**HTTP 429**, including on the byte-exact archived URL that served `ST0601.4.pdf` the day before. It
is a quota, not a credential, so the routes are throttled rather than closed.

**A NINTH ROUND ASKED THE SAME ROUTE AT A DIFFERENT HOUR AND PARK 9 CLOSED.** 2026-08-27T20:20Z,
against the ~14:05Z and ~14:51Z of the two recorded refusals. `web.archive.org` answered `X-RL: 0`
and **HTTP 200**, and the byte-exact archived `ST0601.4.pdf` URL served bytes digesting to this
record's pin **exactly** — so the route was proved against a known answer before it was asked for a
new one. **MISB ST 1402.2 is now held and pinned**, 13 pages, and its 26 requirements are the row
set park 9 wanted. The park arithmetic is **four closed** — 1, 4, 13, 9 — and **nine open**, eight
of them public downloads. The two official routes were askable for the first time and neither
served it: `gwg.nga.mil` answered **403**, `nsgreg.nga.mil` answered **200 carrying the F5
JavaScript interstitial**, which is a challenge page and not a document. **Parks 5 and 11 did not
close**: their documents are now reachable too — checked from the index, nothing fetched — so each
stands on its second blocker alone, an artefact half that is source under `packages/`.

**A TENTH ROUND PINNED THOSE FOUR DOCUMENTS AND WROTE NO SOURCE.** The ninth round ended with a
recommendation and this one executed it. **ST 1201.3** (20 pages), **ST 1303.1** (14), **ST 1204.1**
(36) and **ST 1301.2** (4, the smallest document in `spec/`) are held and pinned, obtained
2026-08-27 between 21:05:18Z and 21:05:40Z at the exact revisions parks 5 and 11 name — and only
after the **pin-as-control** step passed, the archived `ST0601.4.pdf` URL re-serving bytes that
digest to this record's pin in both terms. **The delegated-document tally moves from four to eight of
fourteen.** *(CORRECTED 2026-08-28 by the repair round: this sentence read "from five to nine" when it was written and both figures were one too high. The tally counts DELEGATIONS THE PROFILE MAKES, and the copy of ST 0601.19 is not one — the row set's own tally row says so, calling it not an edition the profile pins and retaining it as context only. It was counted anyway from the day the figure was first stated. Fourteen delegated documents, six unobtained on parks 3, 6, 7, 8, 10 and 12, leaves eight.)* **NEITHER PARK CLOSED**: each park's exit condition is a document *plus* the artefact it
makes writable, and the artefact for both is source under `packages/` — an `IMAPB` codec for park 5,
`Entity.source_ids` for park 11 — which this round did not write. So both are now **blocked on a
per-change ruling** and the park arithmetic is unchanged in every term: four closed, nine open.
**Park 2 is the precedent** for the state, and it is exact — document held, row set unwritten, park
open. Two register entries were written, **KLV 18 and KLV 19**, both re-derived from **ST 1402.2**'s
pinned bytes rather than from the round that fetched it. All four covers passed the disjunction
sweep — cover, footer and changes table agreeing in each — and all four agree with MISP-2019.1's
Appendix B read first-hand. **Both official routes were asked first and refused again**: `403` with
an S3 body, and a `200` whose body is the F5 interstitial.

**The sentence above about item introductions was true when it was written and is not true now.**
This file says "**no held document dates any item's introduction**", scoped in the same breath to
`ST 0601.14a` and `ST 0601.19` — the only two ST 0601 copies held at the time. **Six editions are now
held**, and two of them do date item introductions: EG 0601.1's §3 says "Added metadata items 40
through 72", and ST 0601.4's §3 dates the additions at editions `.2` and `.3`. So the scoped clause
still holds of `.14a` and `.19` and **the unscoped claim does not**, which is register entry KLV 14's
correction rather than this file's — but this is a site of the fact and the fact moved. What the same
§3 does **not** do is account for items **77, 78, 79 and 80**, four of the eight items separating
edition 1 from edition 4, so the surviving changelog is incomplete where it exists.

**And this file's claim about item 22's length is now first-hand at all six editions rather than
three.** "**The length never changed** across every edition this repository can sample" was
re-derived from the bytes: `uint16`, Len **2**, at the initial release, `.1`, `.4`, `.8`, `.14a` and
`.19`. **It holds.** So do this file's stream counts, re-walked the same way: **6 packets, 26 items
each, 156 items, 977 octets, 0 left over.**

```bash
# This now RUNS, and for six rounds it did not. Twenty fixtures — ten payloads and their ten
# parsed twins — replay against adapter #10, with goldens in golden/. No --fixtures: the adapter
# declares its own directory and the harness resolves it through importlib.resources, so the
# command is identical from a clone and from a `pip install`.
python -m synapse_cdm.harness --adapter stanag4609
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

- **`spec/klv_pin.json`** — the pinned identity of every document in `spec/` and every value
  extracted from them that a ruling cites, each with its locus. **The count is the record's own and
  is not restated here**: its root `what_this_is` closes each dated clause by stating how many
  documents the directory holds and how many of them are pins, and
  `tests/test_cdm_pin_header.py` derives both from the record and refuses a clause that disagrees.
  This bullet said *all six documents* from the day it was written until 2026-09-05, through nine
  acquisitions — a restated count with nothing watching it, which is what rule 7 prefers deleting to
  re-syncing. Written first, for the reason the Legion, CAT021
  and CAT048 pins were: a quotation with no pin behind it is a recollection.
- **`spec/nato-stanag-4609-edition-5.pdf`** and **`spec/misb-misp-2019-1.pdf`** — in the working
  tree because they had to be read, and **not committed**, matching every other adapter here.
  `git ls-files | grep -c '\.pdf$'` is 0 across the whole repository.
- **`spec/ST0601.14a.pdf`**, **`spec/ST0102.12.pdf`**, **`spec/ST0601.19.pdf`**,
  **`spec/ST0107.3.pdf`**, **`spec/ST1402.2.pdf`**, **`spec/ST1201.3.pdf`**,
  **`spec/ST1303.1.pdf`**, **`spec/ST1204.1.pdf`** and **`spec/ST1301.2.pdf`** — **nine** of the
  fourteen delegated documents, four obtained 2026-08-26 and **five on 2026-08-27** — ST 1402.2 by
  the off-peak round and the last four by the pins round the same evening — in the
  working tree and **not committed** on the same rule. Three of the four are editions MISP-2019.1
  pins: **ST 0601.14** (Appendix B ref [53]), **ST 0102.12** (ref [55]) and **ST 0107.3** (ref [14]).
  **ST 0601.19 is not** — it is five major revisions later — and it is kept as **context only**, never
  as a source of tag semantics, for the item-42 divergence note and for the measured delta between the
  two editions. `spec/klv_pin.json`'s `reconciliation_ruling` records every reading verbatim and rules
  on each.

  **`ST0107.3.pdf` is the smallest document here that CLOSED a park**: six pages against ST
  0601.14a's 218, carrying the rule 218 pages could not state. **It was the smallest document in
  this directory outright until 2026-08-27 evening**, when `ST1301.2.pdf` landed at **four** pages
  and the STANAG wrapper's five were already between them — so the claim is narrowed to the one that
  is still true and still the point. **Caught by the pins round's own disjunction sweep**, against
  text that round had just written two sites away: a superlative is a claim about every other member
  of a set, so it goes stale the moment the set grows, and this one went stale in the same commit
  that falsified it. Its
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
| `spec/rfc2781.txt` | `e3fed703a962e1e8a1740fef500d1908df3eca2d80de8bad012835f0ae75b502` | 29 870 | 14 |

Those seven rows are also stated in `spec/klv_pin.json` and in `../../FORMAT_COVERAGE.md`, and
`tests/test_cdm_format_coverage.py` checks **every** occurrence rather than any one of them — the
80b38d1 finding, which was that an `in` check is satisfied by one site while a fact stated at three
sites can drift at two.

**The seventh is text and not a PDF, and its `Pages` column is a different measurement.** `RFC 2781`
is served by the RFC Editor as `text/plain` — there is no PDF of it to hold — so its page count is
not a walk of a PDF page tree but the document's own pagination: 14 form feeds, 14 `[Page N]`
footers, and a highest footer number of 14, all three required to agree. Its pin additionally
carries `lines` (787, the count of `\n` bytes) and `format` (`"text/plain"`; a pin node without that
field is a PDF). Ruled at `spec/klv_pin.json`'s `text_pin_ruling`, and the count of six above was
corrected to seven in the same commit that added the row.

## What `framing/` is, and what it is not

**Twenty-six byte-level fixtures for the framing rules the two held documents state**, written only by
`spec/build_fixtures.py` — the Universal Label and two ways of getting it wrong, BER-OID tags at every
width boundary either document establishes, nine BER lengths, two key/length/value triplets, two whole
packets, the refusals at the edges of all of it, and the document's own checksum vector. Each is a
`.klvframe` of raw octets beside a `.parsed.json` twin carrying the section that authorises it and
**both** pinned digests.

**They are not adapter fixtures and the harness cannot replay one.** No CDM object comes out of any
of them. They sit in a subdirectory rather than here, and since the witnessed-set round that
separation has stopped being tidiness and become load-bearing: the harness selects "immediate
children of the directory that are files", and this directory now HAS ten payloads it replays. One
`.klvframe` copied up a level would become an eleventh, and the harness would try to translate a bare
BER length as a whole UAS Datalink LS packet and report a failure that blames the adapter for a file
that was never a payload.
`tests/test_cdm_klv_framing.py::test_the_framing_fixtures_are_still_not_reachable_as_adapter_fixtures`
asserts the partition in both directions.

**Three classes of fixture were omitted rather than guessed by the framing round, and all three are
now here.** Each needed a rule that round could not establish — every length fixture including the
truncated-length malformation; every key/length/value triple, which needs a length one rule up; and
the 16383 → 16384 tag transition, which needs a third BER-OID octet. **MISB ST 0107.3 discharged all
three.** §6.3.2 gives the length grammar, so the triples follow, and §6.3.1 gives the chain rule for
any width, so `tag_three_octet_lowest` replaces the refusal `tag_third_continuation_octet`. Four of
the nine length fixtures are the document's **own octets**: `0x02`, `0x8180`, `0x8102` and
`0x8300 0080`, the four encodings §6.3.2 prints while explaining which two are wasteful.

**No fixture is a park any more, and one stopped being one on 2026-09-03.**
`length_indefinite_first_octet` — the single octet `0x80`, a long form declaring zero following
octets — used to raise `UnderivableFromPinnedCopy`, because ST 0107.3 never mentions that form and
the rule belonged to **SMPTE ST 336:2017**, park 8, which this record had priced as a purchase.
**ST 336:2017 was obtained free from SMPTE's own library and §5.3 states the form**, so the fixture
is an ordinary refusal: the standard permits `0x80` only where an application document defines
another way to find the end of the Value, none does here, and the bytes are wrong.
`spec/build_fixtures.py` still asserts the exception **type**, and now asserts it in both directions
— it guarded against a round deciding what `0x80` means without buying the document, and it also
guards a round quietly parking the question again after it has been answered.

## The ten payload fixtures, and the plan they replaced

**Every octet is synthetic, and the one thing borrowed is borrowed from the standard.** Not one of
these payloads contains a run from `streams/day_flight.klv`. What the value-carrying fixture uses
instead is each item's **own worked example** from its §8.x block — the same borrowing `framing/`'s
checksum vector makes, and for the same reason: a fixture whose values come from the document checks
this repository's maps against the document rather than against themselves. **The held stream decided
WHICH tags to cover; it supplied no octets.**

**Why the defect fixture is not the stream's bytes.** `length_divergence_at_a_required_length.klv`
reproduces the *class* — four octets under a Required Length of 2 — with a value the stream does not
carry: `0x00000FA0`, not `0x000001c9`. A golden file built from a real emitter's defective octets
would make this repository's test suite a place where somebody else's stream lives. The class is what
the policy rules on; the particular four octets are park 13's evidence and stay in the report.

Each ships as a twin — a `.klv` payload and a `.parsed.json` holding the parsed form the never-drop
check measures against — on the pattern `adsb`, `cat021`, `cat048` and the three ASTERIX adapters
after them already use. `spec/build_fixtures.py` is the single source of truth for both halves and
for `framing/`'s twenty-six as well. The **parsed twin carries the payload and nothing else**: no
`what_it_is_for`, no citation, no fixture id, because the lossless check harvests every leaf of a
JSON fixture and requires each to appear in the CDM output, so a purpose string in the twin would
have to be echoed into an object to pass. That is what this table is for.

| Fixture | What it is there to catch | Cited from | UUID-v8 identity |
|---|---|---|---|
| `witnessed_set_from_the_documents_own_examples.klv` | all 26 witnessed items in one packet, each carrying the Example KLV Value its own §8.x block prints. Every affine map, every string and every identity conversion in `klv_uas_codec` runs once here, against values transcribed from the document rather than chosen by this repository. Tag 1's value is REPLACED on the way out — `encode_packet` computes §6.6's checksum over the packet it actually built, so the example checksum octets `8CED` are what the fixture asked for and the computed sum is what it carries | ST 0601.14a §8.1 through §8.65, each item's Example KLV Value row | `f1c70601-14a0-8001-8000-000000000001` |
| `length_divergence_at_a_required_length.klv` | THE POLICY FIXTURE. Tag 22 Target Width at FOUR octets where §8.22's Required Length cell says 2 — the divergence class park 13 adjudicated, reproduced with octets the held stream does not carry. What must happen: the ITEM is skipped, its octets are parked verbatim, a structured `LengthDivergence` names both bases of the ruling, and the other four items translate normally. What must NOT happen: the packet refused (candidate a), or `0x00000FA0` read as 4000 by a truncation rule no document states (candidate c) | ST 0601.14a §8.22 Required Length 2; ST 0601.13-29 in §7; FORMAT_COVERAGE.md, 'Park 13 adjudicated and CLOSED' | `f1c70601-14a0-8001-8000-000000000002` |
| `zero_length_item_is_an_explicit_unknown.klv` | a Zero-Length Item on tag 56, which is NOT a defect: `ST 0601.14-33` says 'Where a UAS Data-link LS item has a length of zero, consumers shall interpret the value of the item as "unknown"'. So it decodes to an explicit unknown, `Kinematics` is None rather than a speed of zero, and no defect is recorded. The distinction this catches is the one that matters most in a never-drop model: a producer SAYING a value is now unknown, versus a producer not mentioning the item | ST 0601.14a §6.5 and ST 0601.14-33 | `f1c70601-14a0-8001-8000-000000000003` |
| `zero_length_item_on_a_required_item_is_a_defect.klv` | the one zero-length case the document itself makes a defect. `ST 0601.14-32`: the required items '(Tag 1 - Checksum, Tag 2 - Precision Time Stamp, and Tag 65 - UAS Datalink LS Version Number) shall always be reported with positive lengths (i.e. Zero-Length Items (ZLI) are not allowed for these items)'. So a ZLI on tag 65 is reported as `zero_length_on_a_required_item` while the same octets on tag 56 above are an explicit unknown — which is the policy reading the document rather than applying one rule to a length of zero | ST 0601.14a §6.5 and ST 0601.14-32 | `f1c70601-14a0-8001-8000-000000000004` |
| `special_values_are_signals_and_not_measurements.klv` | the three Special Values the witnessed set declares, each in an item that declares it. What must happen: none of them is run through its item's affine map, so no `Position` is built from a 'Reserved' latitude and no `Event.geometry` from an 'N/A (Off-Earth)' frame centre — even though tag 14 and tag 24 are present and valid, which is the case where a half-built point is tempting. Run the map anyway and 0x80000000 becomes a latitude of -90.0000000419: a plausible-looking lie, which is the class of defect this repository's ellipsoid audit exists for | ST 0601.14a §8.6, §8.13 and §8.23, Special Values cells; §7's definition of the Special Values column | `f1c70601-14a0-8001-8000-000000000005` |
| `over_recommended_max_length_is_an_advisory.klv` | a variable-length item one octet past its Max Length. This is NOT the length-divergence class and the document is why: §7 defines Max Length as 'the recommended maximum length' and names a network guard as its consumer, so nothing here breaks a 'shall'. The item is DECODED and carries an advisory. Treating it like a ST 0601.13-29 violation would enforce a requirement the document did not write, which is the mirror image of the mistake candidate (c) would have made | ST 0601.14a §7, the Max Length column definition; §8.11 | `f1c70601-14a0-8001-8000-000000000006` |
| `an_unwitnessed_tag_is_skipped_and_the_packet_translates.klv` | `ST 0107.3-04` in the one place it can be tested from above the framing layer: 'Applications which decode MISB KLV Local Sets shall skip unknown Local Set values so as to not impact the decoding of known Local Set items within the same Local Set instance'. Tag 3 is a real ST 0601 item that this round did not cover because the pinned stream does not carry it, so it is UNKNOWN to `klv_uas_codec` and its octets are parked at attributes.klv_unknown_items. The packet translates and no defect is recorded — an uncovered item is not a malformed one. It is also the fixture that would break if a later round widened the witnessed set without updating the scope contract, which is deliberate | MISB ST 0107.3 ST 0107.3-04; ST 0601.14a §8.3 | `f1c70601-14a0-8001-8000-000000000007` |
| `mandatory_items_only.klv` | the smallest conformant packet the standard admits: the three items ST 0601.14a makes Mandatory and nothing else. It is the fixture that proves the absences are absences — no Position, no Kinematics, no Event.geometry, and attributes.unavailable_fields saying so in words rather than the object simply having fewer keys | ST 0601.14a §6.4, §8.1, §8.65 and ST 0601.14-32 | `f1c70601-14a0-8001-8000-000000000008` |
| `two_packets_one_payload_are_two_statements.klv` | two packets in one payload, half a second apart, at the same position and one metre per second different in ground speed. Four objects come out, not two, and the two Entities have DIFFERENT entity_id values — which is the packet-scoped identity's cost made visible in a golden file rather than described in a docstring. Nothing is accumulated across the boundary: no velocity is differenced, no state is carried | ST 0601.14a §6.3; FORMAT_COVERAGE.md, the fusion refusal | `f1c70601-14a0-8001-8000-000000000009` |
| `a_checksum_that_does_not_validate_is_flagged_not_refused.klv` | a packet whose stored tag 1 disagrees with §6.6's summation over its own octets. It TRANSLATES, and attributes.integrity_basis carries `valid: false`. The reasoning is the length policy's: the stored checksum is one item among the packet's items, and discarding the others because a 16-bit sum disagrees destroys the evidence a consumer needs. `valid: false` on an object is a statement; a missing object is not | ST 0601.14a §6.6 and §8.1 | `f1c70601-14a0-8001-8000-000000000010` |

| `security_local_set_complete_from_the_element_rules.klv` | ALL SEVENTEEN ST 0102.12 elements in one Security Metadata Local Set, carried in ST 0601 item 48. Every row of §6.7's Table 2 decodes once here — the three uint8 enumerations through their own tables, the uint16 Version, twelve ISO/IEC 646 strings, and tag 13's octets CARRIED AND NOT DECODED because RFC 2781 is not held. It is the fixture the confidentiality ruling is checked on: every value is either a code the document prints or a string beginning SYNTHETIC, and tag 1 is 0x01 UNCLASSIFIED//, which is the one classification §6.3 itself names in prose. **The octets of tag 13 assert nothing about their encoding** — the fixture states them and the codec carries them, which is exactly what a decoder without RFC 2781 can do | ST 0102.12 §6.7 Table 2 (all 17 rows), §6.1.1–§6.1.17, §6.8's three conversions; §6.9's own Tag 2 value 0x0C; §6.1.3's own //CZE; ST 0601.14a §8.48 and ST 0601.14-31 for the carrier | `f1c70601-14a0-8001-8000-000000000011` |
| `security_local_set_minimal_required_only.klv` | the six elements §6.7 marks `Required` and nothing else — the smallest set that is not partial under §6.4. It is the fixture that proves the eleven absences are absences: no caveats key, no releasing instructions key, no declassification date, and `security_metadata_basis.state` reading COMPLETE-ON-REQUIRED rather than the object merely having fewer keys. The coding method and the code AGREE IN WIDTH here — ISO-3166 Two Letter with //GB, which §6.1.3 prints as its ISO-3166 example | ST 0102.12 §6.7's Required/Optional/Context column (tags 1, 2, 3, 12, 13, 22); §6.4; §6.1.3's own //GB | `f1c70601-14a0-8001-8000-000000000012` |
| `security_local_set_partial_is_carried_as_partial.klv` | §6.4's SHAPE: a set carrying three of the six `Required` elements and one `Context` element, which the document explicitly admits — "For some operational situations or applications not all metadata elements in Section 6.1 may be required". What must happen: the set DECODES, `partial` is true, `required_absent` names tags 12, 13 and 22, and no element is completed or defaulted. What must NOT happen: the set refused for incompleteness, which would be enforcing a rule §6.4 declines to state. Note the absent Version: `ST 0102.10-57` says version three "shall be assumed" and the advisory records that clause WITHOUT writing 3 into the decoded elements | ST 0102.12 §6.4; §6.7's presence column; §6.1.15's ST 0102.10-57 | `f1c70601-14a0-8001-8000-000000000013` |
| `no_security_local_set_is_unlabelled_not_unclassified.klv` | **§6.5's FIXTURE, AND IT IS THE ONE THE PARK 2 ROUND EXISTS FOR AS MUCH AS THE COMPLETE SET.** A well-formed UAS Datalink LS packet carrying NO item 48. "The absence of Security Metadata does not signify Motion Imagery Data as Unclassified", so what must happen is that the object carries NO `security_metadata` key at all — not an empty one, not a null classification — and carries `security_metadata_basis.state` reading UNLABELLED with §6.5 CITED beside it in `clauses` — the surface round of 2026-09-04 moved the sentence itself into the record and left the pointer on the wire. What must NOT happen is any of the three ways a decoder can quietly say unclassified: a default value, an empty object a reader can take for an empty marking, or silence. Item 48 is `Optional` in ST 0601.14a §8.48, so this packet is fully conformant and the absence is not a defect | ST 0102.12 §6.5, and §6.3 for the contrast; ST 0601.14a §8.48 "Required in LS? Optional" | `f1c70601-14a0-8001-8000-000000000014` |
| `security_classification_outside_the_enumeration_carries_no_label.klv` | **THE CONFIDENTIALITY RULING'S SHARPEST CASE.** Tag 1 carries `0x07`, which §6.7's Allowed Values cell does not list — it enumerates 0x01 through 0x05 and no more. What must happen: the INTEGER is carried, NO label is produced, and an advisory names the clause. What must NOT happen: a nearest match (0x05 TOP SECRET// is the closest listed value and choosing it would be this adapter inventing a marking), a refusal that drops the element and makes the packet read as unlabelled when it is not, or a default. A classification is CARRIED AND NEVER INVENTED, and an integer with no name is exactly what carrying it looks like | ST 0102.12 §6.7 Table 2 tag 1 Allowed Values; §6.8.1; §6.1.1 | `f1c70601-14a0-8001-8000-000000000015` |
| `security_required_element_at_a_forbidden_length_is_refused.klv` | A MALFORMED `Required` ELEMENT. Tag 1 Security Classification at two octets where §6.7's Length (Bytes) cell states 1 and its Data Type states uint8. What must happen: the ELEMENT is refused, its octets are parked verbatim, the refusal names the cell, and the other five elements decode — `klv_uas_codec`'s length policy reached by a second document, and §6.4 plus §6.5 are why it is safe here: a set that loses an element to a refusal is a shape §6.4 already admits, and the resulting gap cannot be mistaken for a claim because §6.5 says an absent marking is not "unclassified". What must NOT happen: the first octet read as the value, the whole set refused, or the packet refused | ST 0102.12 §6.7 Table 2 tag 1 Length (Bytes) = 1, Data Type = uint8; §6.4; §6.5 | `f1c70601-14a0-8001-8000-000000000016` |
| `security_uint16_that_the_format_cannot_carry_is_refused.klv` | A LENGTH THE FORMAT CANNOT CARRY. Tag 22 Version at one octet where §6.7 states Data Type uint16 and Length 2 — a single octet cannot form a two-octet unsigned integer, so there is no reading of it that is not a guess. What must happen: the element is refused with `format_cannot_carry_the_octets`, the octet is parked, and the remaining five elements decode. What must NOT happen: zero-extension to 0x000C, which would produce a version number the packet did not state and which happens to be the RIGHT one for this document — the most dangerous possible near-miss, and the reason this fixture uses 0x0C rather than an arbitrary octet | ST 0102.12 §6.7 Table 2 tag 22 Data Type = uint16, Length (Bytes) = 2; §6.1.15 | `f1c70601-14a0-8001-8000-000000000017` |
| `security_object_country_codes_big_endian_bom_is_honoured_and_stripped.klv` | **RFC 2781 §4.3's FIRST BRANCH.** Tag 13 carries `0xFEFF` then `CZE` in UTF-16BE. What must happen: the byte order is read as big-endian FROM THE MARK rather than from the default, the mark is STRIPPED — §3.2's rationale, the signature is not part of the object — and `value` reads `CZE` with `byte_order_mark` naming which signature was found. What must NOT happen: the mark surviving into the value as a zero-width non-breaking space, which is what a decoder that honours §4.3 and ignores §3.2 produces, and which is invisible in every rendering a human will look at. THE FIXTURE IS NOT REDUNDANT WITH THE UNMARKED ONE even though both are big-endian: there the order comes from a default and here from the bytes, and only one of the two can be got wrong by assuming | RFC 2781 §4.3 first branch and §3.2; ST 0102.12 §6.7 Table 2 tag 13 Data Type | `f1c70601-14a0-8001-8000-000000000018` |
| `security_object_country_codes_little_endian_bom_is_honoured_with_an_advisory.klv` | **THE ONE CASE WHERE THE TWO HELD DOCUMENTS PULL APART, AND THE FIXTURE THAT DECIDES IT.** Tag 13 carries `0xFFFE` then `CZE` in UTF-16LE. RFC 2781 §4.3 says such text can be interpreted as little-endian and MUST NOT be assumed otherwise without reading the first two octets; `ST 0107.2-02` says byte order shall be big-endian across all MISB documents. What must happen: the value DECODES to `CZE` under §4.3, and an advisory of class `byte_order_contradicts_st_0107_2_02` records that the producer broke the MISB baseline — the `ST 0102.10-57` precedent at tag 22, where a clause is recorded and not applied. What must NOT happen: a refusal, which would discard a value the packet carried because its producer broke a rule; or a big-endian read, which turns `CZE` into two ideographs and calls them country codes — the most dangerous outcome here, because it is a plausible-looking string | RFC 2781 §4.3 second branch; MISB ST 0107.3 §6.1 `ST 0107.2-02` and §1's scope | `f1c70601-14a0-8001-8000-000000000019` |
| `security_object_country_codes_with_no_bom_are_big_endian_by_two_documents.klv` | **RFC 2781 §4.3's THIRD BRANCH, WHICH IS THE ORDINARY CASE AND THE ONE THAT WAS UNREADABLE FOR AS LONG AS RFC 2781 WAS UNHELD.** Tag 13 carries `CZE` in UTF-16BE with no mark. What must happen: `byte_order` reads `big` and `byte_order_mark` is null, so the object distinguishes an order that was DETERMINED from one that was DEFAULTED. **The default is not this layer's choice**: §4.3 says such text SHOULD be big-endian and `ST 0107.2-02` says it SHALL be, so two held documents agree and the second is the custodian of the document that cites the first. That agreement is the finding this fixture exists to fix in place — the round expected the byte order to rest on one SHOULD | RFC 2781 §4.3 third branch; MISB ST 0107.3 §6.1 `ST 0107.2-02`; ST 0102.12 §6.1.13, which states no byte order in its own voice | `f1c70601-14a0-8001-8000-000000000020` |
| `security_object_country_codes_multiple_are_split_on_the_semicolon.klv` | **`ST 0102.10-24` AND `-25`, APPLIED FOR THE FIRST TIME.** Tag 13 carries `CZE;GB` — both codes §6.1.3 prints as its own examples, one GENC and one ISO-3166. What must happen: `value` is the whole string, because `-25` makes multiple codes ONE entry, and `codes` is `["CZE", "GB"]`, because `-24` makes the semi-colon the separator. Both are emitted, which is not redundancy: the entry is what the packet sent and the split is what the clause says it means. What must NOT happen: splitting on blanks — §6.1.13's own Note says the semi-colon was chosen 'instead of blanks or other characters' precisely so automated tools can split it — or validating either code, which would require registers this repository does not hold. **`-26` IS NOT APPLIED**: nothing here computes a country from a frame centre, so the ORDER of the two codes carries no claim about which region is under the centre | ST 0102.12 §6.1.13's `ST 0102.10-24`, `-25` and `-26`, and its Note on the separator; §6.1.3's own //CZE and //GB | `f1c70601-14a0-8001-8000-000000000021` |
| `security_object_country_codes_at_an_odd_octet_count_is_refused.klv` | **AN OCTET COUNT UTF-16 CANNOT CARRY, AND THE LENGTH CELL FORBIDS NOTHING.** Tag 13 carries five octets. §6.7's Length (Bytes) cell for this element reads `Variable`, so unlike tag 1 and tag 22 there is NO stated length to disagree with — the refusal comes from the ENCODING: RFC 2781 §3.1 serialises each 16-bit code unit as two octets, so an odd count is not a sequence of code units under either byte order. What must happen: refusal class `utf16_cannot_carry_an_odd_octet_count`, the five octets parked verbatim, and the other five elements decode. What must NOT happen: dropping the trailing octet and decoding four, which produces `CZ` — a shorter, entirely plausible country code that the packet did not send. That is the near-miss this fixture exists for, and it is the tag 22 zero-extension trap in a second place | RFC 2781 §3.1 and §2.2; ST 0102.12 §6.7 Table 2 tag 13 Length (Bytes) = Variable; §6.4 and §6.5 for why refusing one element is safe | `f1c70601-14a0-8001-8000-000000000022` |
| `security_object_country_codes_with_a_lone_surrogate_is_refused.klv` | **RFC 2781 §2.2's ERROR CASES, WHICH ARE A SEPARATE REFUSAL FROM THE ODD COUNT AND ARE HERE SO THE SECOND CLASS IS NOT AN UNWITNESSED BRANCH.** Tag 13 carries six octets — a well-formed count — whose middle code unit is `0xD800`, a high surrogate with no low surrogate after it. §2.2 step 3: 'If there is no W2 ... or if W2 is not between 0xDC00 and 0xDFFF, the sequence is in error.' What must happen: refusal class `utf16_sequence_is_in_error`, distinct from the odd-count class because the REPAIRS differ — an odd count is a framing fault upstream and this is a content fault — and the octets parked verbatim. What must NOT happen: a replacement character, which is what a non-strict decode produces and which would put `�` into a country code; or error recovery of any kind, since §2.2 says 'Error recovery is not specified by this document' and inventing one would be reading a rule off nothing | RFC 2781 §2.2 steps 2 and 3; ST 0102.12 §6.7 Table 2 tag 13 Data Type | `f1c70601-14a0-8001-8000-000000000023` |
| `imapb_items_from_the_documents_own_examples.klv` | all fourteen IMAPB items in one packet, each carrying the Example KLV Value its own §8.x block prints. It is the adapter-level twin of `imapb_codec`'s worked-example check: that check runs the map, this one runs the map THROUGH the item layer, the adapter and the schema, so a tag wired to the wrong range, decoded at a fixed width instead of the wire's, or landing in the wrong attribute fails here. Two of the fourteen reach canonical fields — tag 104 fills Position.alt_m and tag 112 fills Kinematics.course_deg — and the other twelve land at attributes.document_witnessed_items under the names the document gives them. Note what is NOT here: no Position is built, because tags 13 and 14 are absent and an altitude with no coordinates is not a fix | ST 0601.14a §8.96 … §8.134, each item's Example KLV Item row; ST 1201.3 §7.1.2 | `f1c70601-14a0-8001-8000-000000000024` |
| `hae_is_tag_104_and_never_tag_15s_msl.klv` | **RULING 4's FIXTURE (2026-09-04): ONE PACKET CARRYING BOTH ALTITUDES.** Tag 15 Sensor True Altitude is MSL and stream-witnessed; tag 104 Sensor Ellipsoid Height Extended is HAE and document-witnessed. `ST 0601.8-17` requires a decoder that understands HAE to 'use the HAE representation and ignore the Mean Sea Level (MSL) representation when both exist in the same UAS Datalink LS packet', and §8.104.1, §8.75.1 and §8.15.1 each state 'preference for Tag 75 | Tag 104'. What must happen: Position.alt_m is 104's 23 456.234375 m and NOT 15's 14 190.72 m, and the MSL figure is still parked whole at attributes.sensor_true_altitude_msl_m. **What must NOT happen is a precedence rule firing**: alt_m is an HAE field and tag 15 was never a candidate for it, so the right answer here comes out of the field's definition rather than out of a comparison — which is the whole of RULING 4. The two values are 9 265 m apart, deliberately: a fixture where the two altitudes were close would pass under a wiring that read the wrong one | ST 0601.14a §8.15, §8.104 and their Details subsections; ST 0601.8-17; FORMAT_COVERAGE.md, RULING 4 of the park 5 round | `f1c70601-14a0-8001-8000-000000000025` |
| `tag_104_carrying_a_signal_emits_no_altitude.klv` | RULING 4's second fixture: tag 104 present and carrying a ST 1201.3 §7.2.3 signal rather than a height. What must happen: a Position IS emitted — tags 13 and 14 are measurements — with alt_m None, the signal recorded at attributes.position_basis.alt_not_measured naming which of Table 2's eight patterns it was, and attributes.unavailable_fields saying Position.alt_m is unavailable BECAUSE the item was present and not a measurement, which is a different statement from the item being absent. What must NOT happen: 0xD00000 run through §7.2.2's reverse map, which yields 40 038 m — a plausible-looking altitude above the item's own stated maximum, and the same class of defect item 13's 0x80000000 got | ST 1201.3 §7.2.3 Tables 1 and 2; ST 0601.14a §8.104 | `f1c70601-14a0-8001-8000-000000000026` |
| `imapb_special_values_are_signals_and_not_measurements.klv` | **ALL EIGHT of ST 1201.3 §7.2.3 Table 2's patterns in one packet, each on a different item and each at a different length** — two, three and four octets — because §7.4 makes the width the wire's and a special-value test written against a fixed sentinel would pass at one width and fail at another. The two SNaN rows and UserDefined carry a non-zero remainder, which Table 2 gives a meaning to ('Remaining bits are used as the signal value'), so the fixture also proves the payload survives. What must happen: eight signals, no numbers, each rendered with its Table 2 name and its remainder. **The twin of the witnessed set's own `special_values_are_signals_and_not_measurements`**, one document down: there the sentinels are integers ST 0601.14a's own Special Values cells declare, here they are bit patterns ST 1201.3 reserves in every IMAPB value regardless of what the §8.x Special Values cell says — and every one of these fourteen cells says 'None', which is exactly why this fixture is not redundant | ST 1201.3 §7.2.3 Table 1 and Table 2; §7.4 on the KLV-supplied length | `f1c70601-14a0-8001-8000-000000000027` |
| `a_wavelengths_list_from_the_documents_own_example.klv` | tag 128 Wavelengths List, carrying §8.128's own printed Example KLV Value — `0D 15 0000 07D0 0000 0FA0 4E4E 4952` against the Software Value '21,1000, 2000, NNIR (Narrow NIR)'. It is the only pack fixture in this file whose octets the document prints, and **the only pack in park 5's sixteen that has an example at all**: §8.130's Example Software Value cell reads 'N/A', which is one of the two reasons tag 130 stays `not yet`. Four things must come out right and each would fail differently — the VLP's BER length (§6.3), the BER-OID Wavelength ID, two IMAPB(0, 1e9, 4) members in NANOMETRES, and a utf8 name whose length is found by the FLP subtraction §8.128.1 prints, 'Namelen = Length1 - (BEROIDlen + 8)' | ST 0601.14a §6.3 (the VLP/DLP/FLP grammar), §8.128 and §8.128.1 with Table 15 | `f1c70601-14a0-8001-8000-000000000028` |
| `a_short_wavelength_record_is_refused_and_the_packet_translates.klv` | a malformed pack, and the fixture that fixes the POLICY for one. The wavelength record declares eight octets where its own layout needs at least nine, so §8.128.1's name-length rule yields a NEGATIVE length. What must happen: **the ITEM is refused and the PACKET is not** — the ST 0102.12 element precedent and the length-divergence ruling's own ground, that discarding well-formed items over one malformed one destroys the evidence a consumer needs. So tag 56's ground speed still reaches Kinematics.speed_mps, the pack's octets are parked verbatim at attributes.klv_item_octets['128'], and a structured refusal at attributes.pack_refusals names the clause. What must NOT happen: the packet refused, or the eight octets read as a record with an empty name — which is the same truncation-by-guessing that candidate (c) was rejected for at tag 22 | ST 0601.14a §8.128.1's Namelen rule and Table 15's Mandatory members; §6.3 | `f1c70601-14a0-8001-8000-000000000029` |
| `a_course_of_360_degrees_is_the_documents_own_zero.klv` | the one value tag 112 can carry that the CDM's own field cannot hold as it stands. §8.112's range is IMAPB(0, 360) — CLOSED at both ends — so 360.0 is conformant and encodes to exactly `5A00` at two octets, while Kinematics.course_deg is documented '[0, 360)' and declares lt=360.0. What must happen: course_deg is 0.0, and attributes.kinematics_basis.course_360_folded_to_0 says so and quotes the sentence that licenses it — §8.112's own bullet, '0 (or 360) is true north, east is 90, south is 180, west is 270'. **The document states the identity, so the fold applies its sentence rather than this adapter's judgement.** What must NOT happen: a ValidationError on a conforming packet, a silent clamp to 359.99, or a schema change — the last was this round's brief's explicit STOP | ST 0601.14a §8.112 and its bullets; models.Kinematics.course_deg | `f1c70601-14a0-8001-8000-000000000030` |
| `a_zero_length_imapb_item_is_an_explicit_unknown.klv` | `ST 0601.14-33` reaching the fifteen document-witnessed items, which is the length policy applying to them unchanged rather than being re-decided for them. A zero-length tag 104 and tag 112 are the producer SAYING those values are now unknown, not a defect: neither is among the three items `ST 0601.14-32` forbids a ZLI on, so no defect is recorded, alt_m and course_deg are None, and the explicit unknown is carried as itself. It also exercises the one branch of `imapb_codec` that REFUSES rather than decodes — `decode` raises on empty octets, calling a zero-length item 'ST 0601.14a §6.5's explicit unknown and the caller's to handle' — so this fixture proves the item layer handles it above the codec and the codec is never asked | ST 0601.14a §6.5, ST 0601.14-33 and ST 0601.14-32; ST 1201.3 §7.4 | `f1c70601-14a0-8001-8000-000000000031` |
| `an_imapb_item_past_its_max_length_is_an_advisory.klv` | the Max Length advisory on a document-witnessed item, which is the third branch of `_length_verdict` — the only one an IMAPB item can reach, since all fifteen state `Length` Variable and `Required Length` N/A and `ST 0601.13-29` therefore reaches none of them. What must happen: the value is DECODED at four octets — §7.4's rule, 'it is important to compute the constants needed to do the forward and reverse mapping based on the KLV supplied length', so the constants differ from the three-octet case and the answer is still right — and an advisory records that the item is past its recommendation. What must NOT happen: a defect, a refusal, or a decode at the recommended width, which is the mutation `test_cdm_imapb_codec.py` already fixtures for tag 112 | ST 0601.14a §7's Max Length column definition, §8.120; ST 1201.3 §7.4 | `f1c70601-14a0-8001-8000-000000000032` |
| `the_time_adjustments_from_the_documents_own_examples.klv` | **BOTH TERMS OF ST 0601.14a §6.4 EQUATION 2 IN ONE PACKET, each carrying the Example KLV Value its own §8.x block prints.** Equation 2 reads `TCorrected = TPrecision + TCorrection + (LSeconds * 1,000,000)`, and with §8.2's printed stamp of 1 224 807 209 913 000 µs, §8.137's 5 025 678 901 µs and §8.136's 30 s the instant is 1 224 812 265 591 901 µs — 2008-10-24T01:37:45.591Z once times.render truncates to a millisecond. What must happen: observed_at is that instant, attributes.precision_time_stamp_us is still the RAW 1 224 807 209 913 000 because §6.4's own reason for the Correction Offset is that the stamp is NOT rewritten, and attributes.time_basis records both terms as applied with the clause each came from. What must NOT happen: either term applied twice, the correction multiplied by 1 000 000 (which is the leap-second term's rule and not its own), or the raw stamp moved | ST 0601.14a §6.4 Equations 1 and 2, §8.136 and §8.137 Example KLV Item rows; MISB ST 0603.5 §6 | `f1c70601-14a0-8001-8000-000000000033` |
| `leap_seconds_alone_convert_the_stamp_toward_utc.klv` | **EQUATION 2 WITH ITS CORRECTION TERM ABSENT, which is the case a real packet is far likeliest to be.** Tag 137 is a post-mission item and tag 136 is not, so a live feed carrying one carries this one. What must happen: observed_at is 2008-10-24T00:13:59.913Z, thirty seconds past the raw stamp; time_basis.leap_second_adjustment says applied with §8.136's bullet quoted; and time_basis.correction_offset says NOT applied because the packet carries no tag 137 — not applied as zero, which is the distinction RULING 2 of the park 3 round exists to hold. **And what the object still does not claim**: MISB ST 0603.5 §6 derives UTC 'using its correct offset and inclusion of leap seconds', and this is the leap seconds only, so time_basis.relation_to_UTC names the 82-microsecond residue rather than letting the object read as UTC on the nose | ST 0601.14a §6.4 Equation 2 and §8.136; MISB ST 0603.5 §6 and its footnote 2 | `f1c70601-14a0-8001-8000-000000000034` |
| `a_correction_offset_is_applied_and_the_raw_stamp_is_kept.klv` | **EQUATION 1 ALONE, and it is the fixture RULING 2(c) turns on.** That ruling applies the Correction Offset to the instant ONLY IF a held document says the receiver applies it, and §6.4 does: 'To compute the Corrected Time (TCorrected) for display or other uses, add the Correction Offset (TCorrection) to the Precision Time Stamp (TPrecision)'. What must happen: observed_at is 2008-10-24T01:37:15.591Z and attributes.precision_time_stamp_us is unchanged at 1 224 807 209 913 000. **The two together are the point**, and §6.4 gives the reason in its own words — 'The Correction Offset eliminates the need to do a post-mission change of the Precision Time Stamp value, which if changed can cause synchronization issues with the Motion Imagery frames' — so an adapter that corrected the stamp instead of the instant would break the correlation the item exists to preserve. **And this object is still not UTC**: §8.137's own bullet says 'This value DOES NOT INCLUDE leap seconds offset', there is no tag 136 here, and time_basis says the adjustment was not available | ST 0601.14a §6.4 Equation 1 and §8.137; ST 0601.14a §8.2.1 | `f1c70601-14a0-8001-8000-000000000035` |
| `a_negative_time_adjustment_is_read_signed.klv` | **THE CASE THE DOCUMENT'S OWN EXAMPLES CANNOT WITNESS, and it is a live disagreement inside one §8.x block.** §8.137 states Format `int64` / `int` with a Min of -(2^63) in its drawn table and then prints 'KLV Value To Software Value: Softval = KLVuint' one line below — while §8.136, the sibling item with the identical shape, prints 'Softval = KLVint'. The printed example cannot separate the two readings: `012B8DC635` has a clear top bit. This fixture does. What must happen: tag 136 decodes to -1 and tag 137 to -500 000, and observed_at is 2008-10-24T00:13:28.413Z — 1.5 s BEFORE the raw stamp. Under the `KLVuint` reading the same octets would give 255 and 4 294 467 296, putting the instant more than an hour and four minutes late and four thousand years past that on the leap term. Registered at **KLV 23** and decided on the Format cells, which is two of the block's drawn facts against one of its conversion lines | ST 0601.14a §8.136 and §8.137 Format rows and conversion lines; FORMAT_COVERAGE.md register entry KLV 23 | `f1c70601-14a0-8001-8000-000000000036` |
| `a_zero_length_leap_seconds_item_is_not_a_zero_adjustment.klv` | **AN EXPLICIT UNKNOWN IS NOT A ZERO, and on a time term the difference is a wrong instant rather than a missing one.** `ST 0601.14-33` says a consumer shall interpret a zero-length item's value as 'unknown', and §6.5 makes a ZLI the producer's way of saying a value has become Unknown 'immediately'. So a producer sending a ZLI for tag 136 has WITHDRAWN the leap-second count, and adding zero seconds on its behalf would assert the very number it just withdrew. What must happen: neither term is applied, observed_at is the raw stamp's instant 2008-10-24T00:13:29.913Z, time_basis says for each term that the packet carries no usable item, and both zero-length items are carried as themselves. What must NOT happen: a defect — neither tag is among the three `ST 0601.14-32` forbids a ZLI on — or a +0 recorded as an applied adjustment | ST 0601.14a §6.5, ST 0601.14-33 and ST 0601.14-32; §8.136, §8.137 | `f1c70601-14a0-8001-8000-000000000037` |
| `tag_75_from_the_documents_own_example.klv` | **RULING 4's FIRST FIXTURE (2026-09-05): TAG 75'S OWN PRINTED WORKED EXAMPLE, THROUGH THE WHOLE STACK.** §8.75 prints `14190.7195 Meters` against the Value octets `C221`, and that printed pair IS the document-side witness the row was promoted on — the same ground as the fifteen IMAPB items and the two time adjustments. `klv_uas_codec.check_against_the_documents_own_examples()` already runs the map; this fixture runs it THROUGH the item layer, the adapter and the schema, so a tag wired to the wrong range, decoded at a fixed width, or landing in the wrong attribute fails here and not only there. What must happen: the item decodes to 14 190.719462882427 m — the printed value to the precision §7's Programmer's Notes promise — and lands at attributes.klv_items['75'] with witness DOCUMENT and not stream. **What must NOT happen is a Position**: tags 13 and 14 are absent and an altitude with no coordinates is not a fix, which is the `imapb_items_from_the_documents_own_examples` note reached by the one item that could most plausibly have been special-cased into one | ST 0601.14a §8.75, its Example KLV Item row and its Map bullet; §7's Programmer's Notes on printed precision | `f1c70601-14a0-8001-8000-000000000038` |
| `hae_from_tag_75_when_it_is_the_only_ellipsoid_item.klv` | **RULING 4's SECOND FIXTURE: 75 ALONE FILLS `Position.alt_m`, WHICH IS THE HALF THAT MOVED.** From 2026-09-04 until 2026-09-05 `alt_m` was tag 104's or nothing, and a packet carrying only tag 75 emitted a Position with no altitude at all while the height sat unread on the wire. What must happen: alt_m is 14 190.719462882427 m, attributes.position_basis.alt_item names `tag 75 Sensor Ellipsoid Height`, and hae_items_carried is [75]. No conversion happens in either direction — §8.75's own Description says 'as measured from the reference WGS84 ellipsoid' and Position.alt_m is documented 'Metres HAE', which is the same datum. **What must NOT happen is an advisory**: one HAE item cannot disagree with anything | ST 0601.14a §8.75 and §8.75.1; models.Position.alt_m; adapters/stanag4609.HAE_PRECEDENCE | `f1c70601-14a0-8001-8000-000000000039` |
| `both_hae_items_agreeing_take_tag_104_and_raise_nothing.klv` | **RULING 4's THIRD FIXTURE: BOTH HAE ITEMS, AGREEING, AND THE PRECEDENCE IS THIS REPOSITORY'S.** ST 0601.14a states no ordering between 75 and 104 — §8.104.1's preference is written as the disjunction `Tag 75 \| Tag 104` and is about tag 15 — so what decides this packet is `adapters/stanag4609.HAE_PRECEDENCE`, on the two grounds the blocks do state: 104's range (40 000 m against 19 000 m, §8.104.1's own stated purpose) and its resolution (0.0078125 m at three octets against 0.30365 m). What must happen: alt_m is 104's 14 190.71875 m, alt_item names tag 104, hae_items_carried is [75, 104], and hae_difference_m is recorded even though nothing is raised. **What must NOT happen is an advisory**: the two differ by 0.00071 m and the threshold is tag 75's own LSB, 0.30365 m. That threshold is the whole reason this fixture exists beside the disagreeing one — two items quantised over different ranges will differ in their low bits on any real airframe, and an advisory that fired here would fire on every packet and be read by nobody | ST 0601.14a §8.75, §8.104, §8.104.1; adapters/stanag4609.HAE_PRECEDENCE | `f1c70601-14a0-8001-8000-000000000040` |
| `both_hae_items_disagreeing_raise_an_advisory_and_still_emit.klv` | **RULING 4's FOURTH FIXTURE: THE TWO HAE ITEMS CONTRADICTING EACH OTHER, EACH AT ITS OWN BLOCK'S PRINTED VALUE.** 14 190.72 m against 23 456.23 m is 9 265 m apart — one of the two is wrong about where the sensor is and the packet does not say which. What must happen: alt_m is still 104's, because a disagreement does not change the precedence; an advisory of class `hae_items_disagree` carries BOTH values, their difference and tag 75's LSB, at payload.klv_advisories with layer `adapter` and at attributes.position_basis.hae_disagreement so a consumer holding only the Entity can still find it. **What must NOT happen is a refusal, and what must NOT happen is silence** — the ST 0102.10-57 precedent klv_security_codec cites for tag 13's byte order, reached in a second place: refusing would discard a measurement over a producer's inconsistency, and taking one quietly would put a figure in alt_m that nobody can audit. The two values are the documents' own, deliberately: a fixture whose disagreement was invented would be testing a number somebody chose | ST 0601.14a §8.75, §8.104; MISB ST 0102.10-57 as cited at adapters/klv_security_codec; adapters/stanag4609.HAE_DISAGREEMENT_BASIS | `f1c70601-14a0-8001-8000-000000000041` |
| `hae_is_tag_75_and_never_tag_15s_msl.klv` | **RULING 4's FIFTH FIXTURE: THE MSL/HAE REFUSAL, NOW AGAINST THE BASE HAE ITEM.** `hae_is_tag_104_and_never_tag_15s_msl` asks this of tag 104; this asks it of tag 75, which is the item §8.15's own Details points at FIRST — 'For improved modeling accuracy use Sensor Ellipsoid Height (Tag 75) or Sensor Ellipsoid Height Extended (Tag 104)'. What must happen: alt_m is 75's 14 190.719462882427 m, and tag 15's 9 050.35 m stays parked whole at attributes.sensor_true_altitude_msl_m, converting nothing — a geoid separation is a model this repository does not hold. **THE TWO VALUES ARE DELIBERATELY DIFFERENT AND THAT IS THIS FIXTURE'S WHOLE CONSTRUCTION**: §8.15 and §8.75 print the SAME worked example, `C221` against 14190.7195, because they share one affine map and differ only in the datum their Descriptions name — so a fixture carrying both at their printed values would pass under an adapter that read tag 15 into alt_m. Tag 15 carries `8000` here instead. **What must NOT happen is a precedence firing**: tag 15 is MSL and was never a candidate for an HAE field, so HAE_PRECEDENCE never reaches it and the right answer comes out of the field's definition — RULING 4 of the park 5 round, which stands | ST 0601.14a §8.15, §8.15.1, §8.75; ST 0601.8-17; FORMAT_COVERAGE.md, RULING 4 of the park 5 round and RULING 4 of the pre-release round | `f1c70601-14a0-8001-8000-000000000042` |
| `the_miis_core_identifier_from_the_documents_own_example.klv` | **THE ONE FIXTURE IN THIS SET WHOSE OCTETS NOBODY HERE CHOSE.** Item 94 carries ST 1204.1 §6.2.1's printed Foundational Core Identifier verbatim — Version 1, Usage Value Byte 0x70, a Physical Sensor ID and a Virtual Platform ID — which is also the value ST 0601.14a §8.94 prints in its own Example KLV Item. What must happen: TWO entries appear in source_ids BESIDE the packet key, never instead of it, under MIIS-SENSOR-PHYSICAL and MIIS-PLATFORM-VIRTUAL, each carrying Table 8's 39-character UUID String Value; attributes.core_identifier.text reads the whole `0170:...:D3` string with Appendix B's check value, which the codec COMPUTES and does not transcribe. **The check value is the fixture's sharpest edge**: Appendix B ends 'Please see the reference code for complete details of the algorithm' and the document ships no reference code, so `D3` appearing here is the algorithm read out of prose and measured against the document's own printed answer | ST 1204.1 §6.1, §6.2.1 Table 6, §6.2.2.1 Table 9, Appendix B; ST 0601.14a §8.94 | `f1c70601-14a0-8001-8000-000000000043` |
| `a_minor_core_identifier_is_one_uuid_and_no_foundational_claim.klv` | **THE OTHER HALF OF §6.1's ALTERNATION, and the document says what it is worth.** Usage Value Byte 0x02 sets the Minor ID bit alone, so the Value is Version, Usage and ONE UUID. §5.1.2: Minor Core Identifiers 'support a low level of identification when a Foundational Core Identifiers are not used ... they are considered inadequate to satisfy the four problems listed in Section 1'. What must happen: exactly one appended source_id, under MIIS-MINOR-INCLUDED, and attributes.core_identifier.kind reads MCID — the consumer is told which of the two kinds it has, because the document prices them differently and the CDM must not flatten that into 'an identifier' | ST 1204.1 §5.1.2, §6.1, `ST 1204.1-27`, `ST 1204.1-28`, `ST 1204.1-30` | `f1c70601-14a0-8001-8000-000000000044` |
| `a_windowed_core_identifier_carries_three_uuids_in_the_ebnfs_order.klv` | **THE 48-OCTET FCID, AND THE FIXTURE THAT PROVES THE ORDER IS READ AND NOT GUESSED.** Usage Value Byte 0x74: bits 6,5 = 11 Physical Sensor, bits 4,3 = 10 Virtual Platform, bit 2 = 1 Window Included. Three UUIDs follow, in §6.1's order — `FCID = (Sensor ID, [Platform ID], [Window ID])` — and Table 4 says the order 'is important and should follow the EBNF in Section 6.1'. **Nothing in a UUID says which role it holds**, so the three synthetic values are deliberately distinguishable (0xA1…, 0xB2…, 0xC3…) and a decoder that read them in any other order would put the wrong bytes under the wrong system name and still emit three well-formed entries. §5.1.1.1.1 is why a window is here at all: a WAMI system extracting a sub-frame 'shall contain a copy of the original Foundational Identifier, if one exists, with a Window Identifier included' (`ST 1204.1-26`) | ST 1204.1 §6.1, §6.2.1 Table 4, Table 5, §5.1.1.1.1, `ST 1204.1-26` | `f1c70601-14a0-8001-8000-000000000045` |
| `a_platform_only_core_identifier_names_one_of_the_two_devices.klv` | **§6.1's SECOND FCID PRODUCTION, WHICH IS NOT A DEGRADED FIRST ONE.** Usage Value Byte 0x08: Sensor ID Type 00 = None, Platform ID Type 01 = Managed, no window, no minor. The grammar has a production for exactly this — `FCID = ... | (Platform ID, [Window ID]) | ...` — and Table 11 gives it compliance level 18, 'None / Managed'. What must happen: ONE appended source_id under MIIS-PLATFORM-MANAGED and no sensor entry invented to sit beside it. **The quality is in the system name for a reason this fixture is the cheapest place to state**: §5.1.1 says a Managed Identifier 'will only serve users after the control station', so two feeds agreeing on this value agree about what one ground station was told, not about a device — and a consumer fusing on it needs that difference legible without opening ST 1204.1 | ST 1204.1 §6.1, §5.1.1, §10 Table 11 level 18, Table 5 | `f1c70601-14a0-8001-8000-000000000046` |
| `a_prefilled_platform_identifier_is_a_defect_and_never_an_identity.klv` | **THE NIL UUID, AND THE ONE CASE WHERE A WELL-FORMED COMPONENT IS NOT PROMOTED.** §5.1.4 defines pre-fill: 'a sensor produces a Foundational Core Identifier with a temporary ID for the Platform ID ... The value for the temporary ID is the nil UUID [3], which is 16 bytes of the hex value 0x00', and `ST 1204.1-32` requires a Core Identifier that has left the platform to be 'fully formed with no temporary Identifiers'. So these octets are a MIIS-compliant sensor's output that a MIIS-compliant platform failed to complete. What must happen: ONE appended source_id — the Physical Sensor ID — a defect of class temporary_platform_identifier at attributes.core_identifier.defects, and the nil component still PRESENT in attributes.core_identifier.components with is_an_identity false. **Nothing is dropped and nothing is repaired**: the octets are in the record, and what is withheld is only the claim that they name something. Promoting it would make every pre-filling emitter on earth agree with every other one | ST 1204.1 §5.1.4, `ST 1204.1-31`, `ST 1204.1-32`; RFC 4122 as its reference [3] | `f1c70601-14a0-8001-8000-000000000047` |
| `a_usage_byte_naming_more_uuids_than_follow_is_refused_and_the_packet_translates.klv` | **THE REFUSAL, AND THE RULING IS THE LENGTH-DIVERGENCE ONE APPLIED A THIRD TIME.** Usage Value Byte 0x70 names a Physical Sensor ID and a Virtual Platform ID — Table 4: 'Each UUID value is 16 bytes so valid lengths of FMIC are 16, 32 or 48 bytes' — and only 16 octets follow it. What must happen: item 94 is REFUSED with class length_does_not_match_the_usage_value, its octets stay parked at attributes.klv_item_octets, attributes.core_identifier.refused names the clause, and **the other three items translate normally** — the Precision Time Stamp, the UAS LS Version Number and the Checksum all come out. **WHY IT IS NOT RECONCILED**: the usage byte is the ONLY statement of how many UUIDs follow, so believing the length instead would mean this layer choosing which half of a malformed identifier is the true one, with no third witness to break the tie | ST 1204.1 §6.2.1 Table 4, Table 5; klv_uas_codec.LENGTH_DIVERGENCE_POLICY; klv_security_codec's element refusal precedent | `f1c70601-14a0-8001-8000-000000000048` |

| `a_vtracker_uuid_is_the_only_key_a_vmti_track_gets.klv` | **THE FIXTURE M'S IDENTITY RULING OF 2026-09-05 IS ABOUT.** One VTarget Pack, Target ID Number 1234 (§11.15's own BER-OID example `0x89 0x52`), carrying a VTracker LS whose Tag 1 is §11.15.24.1's printed UUID `F81D4FAE7DEC11D0A76500A0C91E6BF6`. What must happen: THREE objects beside the packet's own `Entity`/`Event` pair — a `DETECTION` `Event`, an `Entity` and a `Track`, the last two keyed on that UUID under `VMTI-VTRACKER-TRACK-ID` and on nothing else. The Target ID Number appears in `source_ids` under `VMTI-VTARGET-TARGET-ID-NUMBER` and NEVER as a key. `Position` is Tags 10/11's printed +10.00° offsets added to §8.23/§8.24's Frame Center pair, `PositionSource` `ESTIMATED`, `alt_m` 10 000 m from Tag 12. `entity_type` is `UNKNOWN` although VObject Tag 2 reads `Dismount/Non-combatant/Female/Child` — M's amended default 3, and gap 20's answer. `track_quality` is 0.5 from Tag 7's printed 50 % | ST 0903.4 §9.1, §11.1–§11.12, §11.15, §11.15.22.2, §11.15.24.1–.8, `ST 0903.4-06/-07/-09/-10/-11/-24/-46`, Table 16; ST 0601.14a §8.74 | `f1c70601-14a0-8001-8000-000000000049` |
| `a_vtarget_with_no_vtracker_is_a_detection_and_never_a_track.klv` | **THE HALF OF THE RULING THAT WOULD PASS UNDER ANY MAPPING BUT THIS ONE.** A VTarget with a Target ID Number and no VTracker LS. What must happen: ONE `DETECTION` `Event` and NOTHING else — no `Entity`, no `Track` — because §11.15 scopes the Target ID Number "until the identification number is reset by the New Detection Flag (Tag 6 within the VTarget Pack)", §9.4 makes tag 6 optional (it is absent here) and `ST 0903.4-28` requires uniqueness only "[t]o the extent possible". `Event.geometry` is `None`: the pack states a centroid PIXEL and pixel rows and columns, and no geolocation is computed from a pixel because ST 0903.4 defines none. The shipped `asterix_cat048.py` / `legion.py` shape, reached by a third format | ST 0903.4 §9.4, §11.15, §11.15.1, §11.15.5, §11.15.8–.9, §11.15.19–.21, `ST 0903.4-09/-10/-24/-28` | `f1c70601-14a0-8001-8000-000000000050` |
| `a_target_location_pack_is_absolute_and_needs_no_frame_centre.klv` | **THE PRECEDENCE, AND THE PACKET DELIBERATELY CARRIES NO FRAME CENTRE.** VTarget Tag 17 Target Location is §11.16's whole printed Location Truncation Pack — 43.00°, 110.00°, 10 000 m, three sigmas and three rhos — and the ST 0601 packet around it carries neither item 23 nor item 24. What must happen: a `Position` at (43.0, 110.0) with `alt_m` 10 000 all the same, because §11.15 Tag 17 is ABSOLUTE: "even if the VMTI LS is embedded within a MISB ST 0601 LS, Target Location may still be used". `accuracy_m` stays `None` with the three sigmas carried verbatim — combining them into one number is a statistic the document does not define | ST 0903.4 §11.15 Tag 17, §11.16, §11.19, `ST 0903.4-62/-63/-65/-67` | `f1c70601-14a0-8001-8000-000000000051` |
| `an_offset_target_with_no_frame_centre_emits_no_position.klv` | **THE REFUSAL M RULED ON, AND THE CASE THAT SEPARATES AN `Entity` FROM A `Track`.** The same +10.00° offsets as the first fixture and NO item 23 or 24 to add them to. §11.15 Tag 10: the offsets have "meaning only if the VMTI LS is embedded within a MISB ST 0601 LS" and are "added to the Frame Center Latitude metadata item from the parent MISB ST 0601 packet"; target locations off the earth or outside the mapped range "should either not be reported, or be reported as an 'error'". What must happen: NO `Position`, the `DETECTION` `Event`'s geometry `None`, the `Entity` STILL emitted because the VTracker UUID guarantees the identity regardless — and NO `Track`, because `Track.samples` requires at least one position at an instant and there is none. The reason is on the object, at `position_basis` | ST 0903.4 §11.15 Tags 10 and 11; ST 0601.14a §8.23; `models.Track.samples` | `f1c70601-14a0-8001-8000-000000000052` |
| `two_vtargets_sharing_one_target_id_number_are_two_detections.klv` | **THE FIXTURE THAT IS ONLY BUILDABLE BECAUSE `ST 0903.4-28` SAYS "TO THE EXTENT POSSIBLE".** Two VTarget Packs in one VTargetSeries carrying the SAME Target ID Number 1234. §11.15 adds the deliberate case: "Sophisticated VMTI systems may use the same Target ID Number to identify a common target detected by different sensors". What must happen: TWO `DETECTION` `Event`s with DIFFERENT `event_id`s, because the detection key is the packet's stamp and index plus the target's ORDINAL in the series and only then the Target ID Number. A mapping that keyed on the id alone would emit one event here and silently drop a detection | ST 0903.4 §9.1, §11.15, `ST 0903.4-07/-28` | `f1c70601-14a0-8001-8000-000000000053` |
| `rvt_local_set_complete_from_the_element_rules.klv` | EVERY ROW OF ALL FOUR ST 0806.4 TABLES IN ONE PACKET, carried in ST 0601 item 73 — sixteen of Table 8-1's twenty-one elements plus its three subordinate-set tags, all ten of Table 8-2's POI rows, all ten of Table 8-3's AOI rows and both of Table 8-4's. Every decoding rule in `klv_rvt_codec` runs once here: the five uint widths including the **uint24 no other document in this repository uses**, the two degree maps, the POI altitude's unsigned map with a negative offset, the unenumerated `int8`, ISO-7 strings at both a stated exact width (tag 9, exactly 16) and a stated maximum, the User Defined LS's bit-field and the opaque User Data. **The subordinate sets are sent OUT of tag order, 12 then 13 then 11**, because `element_order` is the wire order and a fixture that always sorts would never show that. **No fixture here carries a `Frag Circle Radius`** (Table 8-1 tag 6) — a deliberate omission, and nothing goes unchecked by it, the element taking the same `uint` path tags 3, 4 and 9 exercise | ST 0806.4 §8 Tables 8-1, 8-2, 8-3, 8-4 (all 43 rows), §7.1's ST 0806.4-06, §7.3's -07 through -24; ST 0601.14a §8.73 for the carrier | `f1c70601-14a0-8001-8000-000000000054` |
| `an_rvt_local_set_carrying_two_points_of_interest_is_two_pois.klv` | tag 12 TWICE in one RVT LS, which `ST 0806.4-25` explicitly allows: *'Tag ID 12, representing a Point of Interest Local Set instance, can appear multiple times to convey information for multiple points of interest.'* **This is the fixture that proves `DecodedSet.subordinate_sets` is a LIST and not a dict keyed on the tag** — a dict would carry one POI where the wire carried two, and the two here differ in every element they share | ST 0806.4 §7.4 ST 0806.4-25, §7.3.1 ST 0806.4-08/-09/-10, Table 8-2 | `f1c70601-14a0-8001-8000-000000000055` |
| `a_poi_missing_a_mandatory_element_is_carried_and_reported.klv` | a POI carrying its Number but neither its Latitude nor its Longitude, which `ST 0806.4-09` and `-10` both require. IT IS CARRIED, and `required_absent` reads `[2, 3]`. Nothing is refused: discarding well-formed elements over a missing one destroys evidence, and a non-conforming set is a FACT a consumer needs rather than a set that did not arrive. **The RVT LS itself satisfies none of `ST 0806.4-01`..`-04` here** — no timestamp, no checksum — which is reported at `independent_set_conformance` and refused for `klv_rvt_codec.EMBEDDED_SET_POLICY`'s reason: a set inside item 73 is not an independent one and draws its time and integrity from the ST 0601 packet | ST 0806.4 §7.3.1 ST 0806.4-08/-09/-10, §6 ST 0806.4-01 through -04, §5; ST 0601.14a §8.73.1 | `f1c70601-14a0-8001-8000-000000000056` |
| `an_rvt_element_at_a_stated_length_it_does_not_have_is_refused.klv` | two elements at widths their own Length in Bytes cells forbid — tag 3 Platform True Airspeed at three octets where Table 8-1 says 2, and tag 15 MGRS Latitude Band and Grid Square at two where it says 3. BOTH ARE REFUSED AS ELEMENTS AND THE SET IS NOT: the refusals name the cell they failed, their octets stay parked at `raw_elements`, and tags 2, 16 and 1 decode beside them. **Also the fixture that shows a MAXIMUM is not enforced**: tag 15's `3` is an exact width and tag 10's `Max. 127` is not, and `_stated_length` is where the two are told apart | ST 0806.4 Table 8-1, the Length in Bytes column for tags 3 and 15 | `f1c70601-14a0-8001-8000-000000000057` |
| `an_rvt_string_that_is_not_iso_7_is_refused_and_the_packet_translates.klv` | a `String ISO-7` element carrying `0xFF`, which is not an ISO-7 character. The element is refused with the position of the offending octet named and the packet translates — `klv_security_codec._decode_iso646`'s ruling reached by a third document. The value is `H.264` followed by one impossible octet, so a reader can see the refusal is about the last byte and not about the string | ST 0806.4 Table 8-1 tag 10, Format 'String ISO-7' | `f1c70601-14a0-8001-8000-000000000058` |
| `a_poi_coordinate_at_the_error_indicator_is_a_signal_and_not_a_position.klv` | a POI whose latitude and longitude both carry `0x80000000`, which every coordinate Notes cell in ST 0806.4 names in terms: *'Use -(2^31) as an "error" indicator. -(2^31) = 0x80000000.'* Both decode to NO value and the signal `error` — a signal is not a measurement and is never averaged with one. **The elements are PRESENT, so `required_absent` is EMPTY**: `-09` and `-10` require the ITEM, and a producer sending it to say it does not know is a different state from not sending it. Tag 4 carries the altitude map's own zero, which is -900 m and not sea level | ST 0806.4 Table 8-2 tags 2, 3 and 4, the Notes column | `f1c70601-14a0-8001-8000-000000000059` |
| `an_unlisted_rvt_tag_is_carried_and_this_layer_declines_to_read_it.klv` | tag 22 inside an RVT LS, one past the twenty-one Table 8-1 draws. It is carried at `raw_elements`, listed at `unlisted_tags`, and refused with the clause that says why — the same treatment `klv_uas_codec` gives an unwitnessed ST 0601 tag under `ST 0107.3-04`, one layer down. This layer declines to say what the octets MEAN and does not drop them | ST 0806.4 Table 8-1, which draws rows for tags 1 through 21 | `f1c70601-14a0-8001-8000-000000000060` |

**THE SEVEN RVT FIXTURES ARE THE `security_*` SEVEN's KIND AND NOT THE FIVE VMTI ONES', AND THE COINCIDENCE IN COUNT IS ONLY A COINCIDENCE.** ST 0806.4 prints NO worked example of anything — its one packet illustration, Figure 7-1 at §7.3.4, is a raster image, and ST 0601.14a's §8.73 Example KLV Item row reads `49 - N/A` — so every octet above is built from an ELEMENT RULE and cites the clause it exercises, exactly as the ST 0102.12 seven are and for the same reason. **Not one of the seven carries a real place, callsign or target**: every string begins `SYNTHETIC`, every coordinate is at or within a degree of 0°N 0°E, and the one non-synthetic value is `H.264`, which Table 8-1 tag 10's own Notes cell prints as an example. What stands in place of the document's examples is `klv_rvt_codec.check_transcription_cross_check()`, twelve agreements INTERNAL to ST 0806.4, and it establishes that four tables were transcribed consistently and nothing about any value map.


**THE FIVE VMTI FIXTURES ARE THE OPPOSITE OF THE `security_*` SEVEN, AND THAT IS WORTH ONE
SENTENCE.** Those seven are built from element rules because ST 0102.12 prints no worked example.
ST 0903.4 prints one for nearly every element it defines — `klv_vmti_codec.WORKED_EXAMPLES` holds
70 and reproduces 68 on every suite run — so every VMTI octet above is looked up from that table
rather than typed. **One value is not the document's**: VObject LS Tag 1 Ontology has no printed
example while Tag 2 Ontology_Class does, and `ST 0903.4-46` requires the Ontology to appear before
any Class, so a fixture with the printed Class and no Ontology would be a non-conforming stream.
The URI used is in the `.invalid` TLD RFC 2606 reserves for names guaranteed never to resolve.

**THE SEVEN `security_*` FIXTURES ARE BUILT FROM CLAUSES AND NOT FROM A WORKED EXAMPLE, AND THAT IS
A WEAKER ARRANGEMENT THAN THE TEN ABOVE.** Every value-carrying fixture in the first ten borrows
its octets from a printed Example KLV Value, so `check_against_the_documents_own_examples` checks
this repository's maps against ST 0601.14a rather than against itself. **MISB ST 0102.12 prints no
worked example of an element or a set anywhere in its eighteen pages** — its only examples are two
country codes (§6.1.2, §6.1.3) and one Tag 2 value (§6.9) — and **ST 0601.14a §8.48's own Example
KLV Item row reads `30 - N/A`**, so neither of the two documents behind these fixtures supplies
one. There is therefore **no analogue of `check_against_the_documents_own_examples` for the
seventeen elements and none is simulated.** What stands in its place is the four-way agreement at
`klv_security_codec.TRANSCRIPTION_CROSS_CHECK` — Table 2's seventeen rows against §6.1's seventeen
subsections, §6.8's three conversions against the three `uint8` rows, and Table 1's Universal Set
listing the same seventeen elements — which checks the TRANSCRIPTION and cannot check a decoded
value. Saying which is the point.

**NO FIXTURE HERE CARRIES A REAL-WORLD MARKING.** Two kinds of value appear and they are kept
apart deliberately: codes the held document itself prints (`0x01` UNCLASSIFIED//, `0x0C` STANAG
1059 Mixed, `//CZE`, `//GB`, `0x000C` for this document's own version), and clearly synthetic
strings — every one begins `SYNTHETIC`, and `ZZZ` stands in where a second country code is needed,
`ZZ` being the ISO 3166 user-assigned range and unmistakably not a state. **Not one caveat,
compartment, handling instruction or releasability marking used in the real world appears in any
fixture**, and no fixture pairs a coding method with a code of the wrong width. §6.1.2's "GENC Two
Letter" and §6.1.3's "//CZE" are two independent examples in two sections rather than one worked
set, so combining them verbatim would be internally incoherent; each fixture pairs a document code
with a method of the matching width instead, and this sentence records that the choice was made
rather than found.

**The UUID-v8 identities are in the table above and NOT inside any payload.** `framing/`'s twins
carry theirs in the twin, because a framing fixture "has no identifiers at all to carry one". Here
the reason is sharper and it is this round's own finding: **a UAS Datalink LS packet carries no
identifier of any kind.** Items 3, 4, 10, 59 and 94 are the five that could identify an airframe and
the pinned stream carries none of them, which is why adapter #10's `entity_id` is packet-scoped. So
there is nothing in one of these payloads for a synthetic identity to stand in for, and inventing a
field to hold one would be putting an identifier on the wire that the wire does not have.

**Corrected in tense, 2026-09-05, by the park 11 round: the sentence above is true of the PINNED
STREAM and is no longer true of this directory.** Six payloads here now carry item 94, the MIIS
Core Identifier, and three of them put a UUID in `Entity.source_ids` beside the packet key — the
first identifier this format has ever given adapter #10 that outlives one packet. What has not
changed and is the reason `entity_id` is still packet-scoped: `streams/day_flight.klv`'s 26 items
stop at tag 65, so none of the five identifying items is on a held wire, and the six payloads that
carry one carry it from **ST 1204.1's own printed example** or from values that begin `0xA1`,
`0xB2`, `0xC3` and `0xD4` and are synthetic by construction. No real device identifier is in any
fixture in this repository.

## The plan this replaced, and what is left of it

The section above used to be "Why no `.klv` payload can be written yet — and the reason CHANGED", and
it named tag semantics — park 3 for the epoch, park 5 for the IMAPB ranges — as the blocker. **Both
of those readings turned out to be narrower than they looked, and reading the pinned edition is what
narrowed them:**

* **The epoch is in a held document.** ST 0601.14a §8.2.1 states it on its own account —
  "the number of microseconds elapsed since January 1, 1970 (1970-01-01T00:00:00Z)" — so
  `Event.observed_at` was never blocked on park 3. What park 3 still owns is the **name** of a
  timescale that §8.2.1 says "does not represent UTC", and `attributes.time_basis` carries that
  caveat on every object rather than resolving it.
* **`IMAPB` does not reach the witnessed set at all.** `MISP-2015.1-09` says every scaled value is
  mapped by ST 1201.3, and that is the PROFILE's claim; **not one of the 26 witnessed items' §8.x
  sections names IMAPB**, because each states its own affine map twice over. The 16 sections that do
  name it are tags 96, 103, 104, 105, 109, 112, 113, 114, 117, 118, 119, 120, 128, 130, 132 and 134,
  and none of them is witnessed. **Park 5 is narrowed and not lifted** — recording that a blocker
  shrank is not recording that it lifted.

**The twelve planned fixtures the old plan tabulated are not all superseded**, and the ones that are
not are still tabulated in `../../FORMAT_COVERAGE.md`: `security_local_set_present.klv` needs park 2,
`vmti_detections.klv` needs park 6, `mismms_minimum_set.klv` needs park 12. What the ten above
discharge is the envelope, the witnessed items, the defect classes and the refusals — and the
round-trip trap `../../README.md` names under "Four things the harness cannot check for you",
self-consistency without an external anchor, is answered here by the documents' own worked examples
rather than by a promise.
