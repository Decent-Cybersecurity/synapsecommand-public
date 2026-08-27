# STANAG 4609 / MISP-2019.1 KLV fixtures

**There are TEN, and for six rounds there were none.** This file opened with the sentence
"There are none yet, and that is the state this directory is in rather than a step somebody
forgot" from the day the directory was created until the witnessed-set round of 2026-08-26, and
that sentence is quoted here rather than deleted because what replaced it is the interesting part: **adapter `stanag4609` has
shipped**, and it covers **26 of ST 0601.14a's 141 items** — the distinct tags the one real stream
this repository holds actually carries. The other **115** rows still read `not yet` in
`../../FORMAT_COVERAGE.md`, and that is a scope contract rather than a backlog. See "The ten payload
fixtures, and the plan they replaced" below. This directory also holds `spec/` and — since the
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
§6.3.1 states the BER-OID chain rule for any width. **Park 8 stays OPEN** and now owns two absences:
`0x80` as a first length octet, which ST 0107.3 never mentions, and any ceiling on the count of
length octets, which it does not state. Neither is reachable from a conforming stream, which is why
`klv_codec` walks a local set end to end with park 8 open.

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

**One fixture is still a park, and it is the only one.** `length_indefinite_first_octet` — the single
octet `0x80`, a long form declaring zero following octets — raises `UnderivableFromPinnedCopy`, because
ST 0107.3 never mentions that form and BER's indefinite length is **SMPTE ST 336:2017**, park 8, a
purchase. `spec/build_fixtures.py` asserts the exception **type** for it, so a later round that decides
what `0x80` means without buying the document fails in the generator.

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

**The UUID-v8 identities are in the table above and NOT inside any payload.** `framing/`'s twins
carry theirs in the twin, because a framing fixture "has no identifiers at all to carry one". Here
the reason is sharper and it is this round's own finding: **a UAS Datalink LS packet carries no
identifier of any kind.** Items 3, 4, 10, 59 and 94 are the five that could identify an airframe and
the pinned stream carries none of them, which is why adapter #10's `entity_id` is packet-scoped. So
there is nothing in one of these payloads for a synthetic identity to stand in for, and inventing a
field to hold one would be putting an identifier on the wire that the wire does not have.

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
