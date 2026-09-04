# synapse-cdm 1.5.0

A minor release, and the whole of it is one capability: the `stanag4609` adapter now reads the
**MISB ST 0102.12 Security Metadata Local Set** nested under ST 0601 item 48, and says on every
object it emits what basis it had for the marking it carries — or for carrying none.

**Package version 1.5.0 · CDM `schema_version` 1.0.0.** If you consume CDM objects, no schema
moved: no field was added, removed or retyped, and the diff over `schemas/` since 1.4.1 is empty —
`git diff v1.4.1..HEAD -- schemas/` returns nothing, which is the check that decided
`SCHEMA_VERSION` stays where it is rather than an assumption that it would. Seventeen decoded
security elements reach a consumer inside `Entity.attributes`, which the published `entity` schema
declares `additionalProperties: true` while the object around it is `additionalProperties: false`
— the 1.2.0 ruling, applied a second time and checked against the schema files rather than
recalled.

**If you ingest STANAG 4609 / MISB KLV, read the next section.** Every object this adapter emits
gained a key, including objects whose packet carries no security metadata at all — and that is
what the standard requires the output to say rather than an artefact of the change.

For what 1.4.1 was — one KLV framing refusal changing its exception class — see
[the 1.4.1 release](https://github.com/Decent-Cybersecurity/synapsecommand-public/releases/tag/v1.4.1)
and the previous notes in this file's git history. This document does not restate them.

## What a `stanag4609` Entity now carries

Two keys, under `attributes`.

**`security_metadata` — present only when the packet carried ST 0601 item 48.** It holds the
decoded ST 0102.12 local set: **all seventeen elements of §6.7's Table 2 are read** — tags 1–14,
22, 23 and 24, of which six are Required, eight are Context and three are Optional. Each element
carries its decoded value together with its octets, its stated length, its presence class and the
clause that governs it, so a consumer can check the reading rather than trust it. A malformed
element is **refused with its octets parked while the other sixteen decode**; the refusal is a
recorded fact about that element and not a failure of the packet.

**`security_metadata_basis` — present on every object, marked or not.** It is a small record of
where the marking came from, and its `state` is a **token from a closed set**:

* **`UNLABELLED`** — the packet carried no item 48;
* **`PARTIAL`** — a security set was present and not all six Required elements decoded;
* **`COMPLETE-ON-REQUIRED`** — a security set was present and every Required element decoded.

(Those three are the whole set. The table below is the adapter roster and is the only table in this
document whose first column is an adapter name.)

Beside `state` the record carries what carried the set (`carried_in`, `carrier_clauses`), the
pinned copy the element layer was read from (`element_layer`, by SHA-256), the clause pointers that
govern **this** case, the required tags present and absent, any advisories and refusals, and one
pointer — `argument` — to where the reasoning is written out in full.

**No marking is ever defaulted. `confidentiality_ruling` reads `CARRIED AND NEVER INVENTED`, and
three consequences are checkable in a golden file:**

* a **`security_classification` outside §6.7's five listed values is carried with no label**, and
  an advisory names the clause. A nearest match would be inventing a marking;
* a **packet with no item 48 emits no `security_metadata` key at all** — not a null classification,
  not an empty object a reader could take for an empty marking. §6.5 is explicit that *"the absence
  of Security Metadata does not signify Motion Imagery Data as Unclassified"*, so the object says
  `UNLABELLED` and points at the clause. §6.3 is the contrast that makes it precise: `ST 0102.10-51`
  puts a VALUE on the wire for unclassified data, so **unclassified and unlabelled are two
  different states**;
* an element that cannot be decoded is **refused**, never guessed.

### Tag 13, `object_country_codes`, and the byte order it is read under

The Object Country Codes element carries UTF-16 text, and **ST 0102.12 states no byte order
anywhere in its own voice** — that is a measurement over all eighteen of its pages, not an
impression. §6.1.13 gives presence, the semi-colon separator, concatenation and the frame-centre
rule; the encoding reaches the element only through §6.7's Data Type cell, which reads
`RFC 2781 [26] [27]`. So the rule is composed from **three documents**:

* **IETF RFC 2781 §4.3** supplies it: a leading `0xFEFF` means big-endian, `0xFFFE` means
  little-endian, and **neither means big-endian** — an application must not assume the
  serialization without reading the first two octets;
* **MISB ST 0107.3's `ST 0107.2-02`** agrees independently: "Byte order shall be big-endian or
  MSB", scoped by its §1 to apply retroactively to every MISB-approved document. So the ordinary
  no-BOM case rests on **two held statements** rather than on one default this layer chose;
* **ST 0102.12 §6.1.13** supplies everything else about the element.

The decoded value is a string and a `codes` list split on the semi-colon, beside `byte_order`,
`byte_order_mark` and the clause the order was read under. **Codes are carried and never
validated** — GEC, ISO 3166, STANAG 1059 and GENC are registers this repository does not hold.

**Where the two documents pull apart, the value still decodes and an advisory records it.** A
**little-endian BOM** is legal under RFC 2781 §4.3 and breaks the MISB baseline, so the element is
decoded little-endian and an advisory of class `byte_order_contradicts_st_0107_2_02` says the
producer broke it. Refusing would discard a value the packet carried because its producer broke a
rule; decoding it big-endian would turn `CZE` into two ideographs and call them country codes.
Two refusal classes are kept separate because the repairs differ: an odd octet count is a framing
fault (`utf16_cannot_carry_an_odd_octet_count`), and a lone surrogate is a content fault
(`utf16_sequence_is_in_error`) for which RFC 2781 §2.2 specifies no recovery, so none is invented.

### `security_metadata_basis` is a token record, and 1.5.0 is the first shape it has ever had

This is worth stating because it reads like a migration and is not one. Inside this arc the basis
key was first written carrying **every ruling in the codec as prose on every object**, and was then
reshaped to the token-and-pointer record described above — 229 864 bytes of compact JSON across the
goldens became 25 294, an 89% reduction, and the absent case went from 6 146 bytes to 486. That
brings it to the scale of `length_divergence_policy`, the 1.2.0 annotation that also rides on every
object and measures 299 / 818 / 1 622 clean, advisory, defect against the basis's 486 / 1 106 /
1 773.

**No consumer ever received the prose shape.** Neither `klv_security_codec` nor
`security_metadata_basis` exists at tag `v1.4.1`; both landed inside this same unreleased arc, hours
apart. A consumer of 1.5.0 meets the token shape as the **first** shape this key ever had, which is
why there is no migration note here and why the reshape was done before a release rather than after
one. Nothing was deleted in the reshape: sixteen prose values came off the wire and every one is
recorded in `fixtures/klv/spec/klv_pin.json`'s `security_basis_ruling` node under the key it was
emitted as, with its byte count and the module constant it was generated from. The codec constants
all remain in code and are simply no longer emitted, and the confidentiality ruling is unchanged in
every term — only where its text lives moved.

## Why this is a MINOR, and the gate derived it rather than being told

`gates/bump_derivation.py` classifies the diff over the distribution's own contents between `v1.4.1`
and this tree against `version.py`'s `PACKAGE_VERSION` table. It reports **MINOR** over **173
signals** across **92 distribution files**, and the floor is **1.5.0**. The kind needed no ruling:
`adapters/klv_security_codec.py` is a **new importable module** and `fixtures/klv/` gains seven
payloads that extend a fixture set, both of which sit on the MINOR list. No importable name is
removed and no signature moves, so no MAJOR row is reached.

**Eight units the table could not decide, and a person ruled each one.** The gate's PATCH row ("a
translation fix, a message, a docstring") and its MAJOR row ("an importable name is removed or its
**meaning** changes") both reach a function whose body moved and whose name did not, so it names
the unit and stops rather than guessing. All eight rulings are in `MIGRATIONS.md`'s 1.5.0 section,
and the gate reads them back and refuses one that outlives its case. By class:

* **four MINOR rulings, on what the objects now SAY.** `DecodedPacket` gained a trailing
  `security` field with a default, so every positional unpack and every index is unchanged;
  `decode_packet` now decodes item 48 instead of parking its octets in `unknown_tags`, which is new
  emitted content rather than a corrected value — PATCH is refused because nothing it emitted was
  wrong, since parking an undecoded item's octets is what `ST 0107.3-04` requires;
  `Stanag4609Adapter` emits the two new keys; and `_parsed_packet` gained a `security` key, ruled
  on what it produces rather than on its leading underscore, because its return value is written to
  disk as a `.parsed.json` fixture and read back;
* **four PATCH rulings, on one insertion.** They name `<statement 6>` through `<statement 9>` of
  `adapters/stanag4609.py`, and **none of those statements changed**: one import was inserted above
  them, and the gate names an unnamed top-level statement by its position, so four imports were
  renamed and read as modified. One addition reported as four modifications — a property of
  positional unit naming, and the cost of a scheme that cannot be fooled into silence.

The number is the gate's and not a judgement: run `.venv/bin/python gates/bump_derivation.py` on
this tree and it prints the same classification, the same signals and the same floor. It reads the
distribution **through `git`**, so it classifies what is committed rather than what is on disk.

## What else moved

* **The fixture set grew, and every existing KLV golden was regenerated.** Seven new payloads with
  their parsed twins, thirty-four goldens of which fourteen are new and twenty regenerated, and
  seventeen `.parsed.json` twins now state whether their packets carry item 48 — because §6.5 makes
  that a claim rather than a silence. **The twenty regenerated goldens are evidence and not
  noise**: every object this adapter emits now carries `security_metadata_basis`, including objects
  of packets carrying no item 48, so a golden that did NOT move would mean the §6.5 clause had not
  reached it. `stanag4609`'s fixture verdicts move from twenty to **forty-six**; the roster's total
  moves to **458**.
* **The first text pin.** IETF **RFC 2781**, *UTF-16, an encoding of ISO 10646* (February 2000), is
  pinned at `fixtures/klv/spec/rfc2781.txt` — **the first document this repository pins that is not
  a PDF**, and the first that its pin gates had to be widened to recognise. The RFC Editor issues
  no PDF for it: its own Formats block names exactly `TXT` and `HTML`. A pin record for a text
  document carries `format` (`"text/plain"`) and `lines`; a node without `format` is a PDF, which
  is what let one document be admitted without rewriting twelve records to describe bytes that did
  not move. **It is a held document and not a delegation** — the encoding reference of one element
  of one held delegation — so the delegated-specification tally is unchanged at fourteen in scope
  and nine held. Like every pinned specification it is **gitignored and not redistributed**, even
  though RFC 2781's own Full Copyright Statement would have permitted it: a tree that vendored what
  it may and pinned what it may not would hold documents two ways, and a reader could not tell from
  a pin record which way governed a row.
* **The shipped documents.** `MIGRATIONS.md`, `FORMAT_COVERAGE.md` and `fixtures/klv/README.md`
  carry the arc; `FORMAT_COVERAGE.md` gains *The ST 0102.12 Security Metadata Local Set — the row
  set nested under item 48*, and `klv_pin.json` gains `tag_table_st_0102_12`,
  `security_basis_ruling`, `text_pin_ruling` and the RFC 2781 node. **The ST 0102.12 row set reads
  seventeen of seventeen**, and the transcription is checked four ways — §6.1's seventeen
  subsections in order, §6.8's three conversion subsections against the three `uint8` rows, Table
  1's Universal Set keys, and the Required/Context/Optional split — while stating plainly what it
  cannot check: **ST 0102.12 prints no worked example of an element or a set**, so unlike the ST
  0601 row set not one decoded value here is checked against a document.
* **A trap worth knowing if you decode this set yourself.** Tags 2 and 12 are both a `uint8`
  "Country Coding Method" and **their enumerations disagree at seven of sixteen positions** — `0x03`
  is *FIPS 10-4 Two Letter* under tag 2 and *ISO-3166 Numeric* under tag 12. A decoder sharing one
  enumeration reports a coding method the packet did not send, with no error and no clue. This
  package keeps them separate.

**No schema, model, harness flag or dependency moved**, no adapter was added or removed, and the
pinned specification documents are gitignored as they have always been — nothing in this release
redistributes a standard.

## Fourteen adapters, all harness-verified

`python -m synapse_cdm.harness --adapter <name> --json`, run over the roster with no `--fixtures`.
The table is the live registry, and
`tests/test_cdm_release.py::test_the_release_notes_roster_table_is_the_registry` requires both
directions to agree — a table missing an adapter tells a reader the roster is smaller than it is.
**The roster did not move this arc**, which is derived here rather than carried over: `discover()`
and `roster()` each return fourteen, the same fourteen names in the same two directions, and the
totals below were summed from the harness on this tree.

| Adapter | Direction | Fixture verdicts |
|---|---|---|
| `adsb` | bidirectional | 32 |
| `ais` | bidirectional | 22 |
| `cat021` | bidirectional | 40 |
| `cat023` | bidirectional | 34 |
| `cat034` | bidirectional | 34 |
| `cat048` | bidirectional | 82 |
| `cat062` | bidirectional | 56 |
| `gmti` | bidirectional | 32 |
| `legion` | ingest | 6 |
| `pntmap` | ingest | 4 |
| `stanag4586` | ingest | 24 |
| `stanag4609` | bidirectional | 46 |
| `stanag4676` | bidirectional | 34 |
| `tak` | bidirectional | 12 |

**458 fixture verdicts, 0 failed** across the fourteen adapters, against the published schemas.
The whole of the increase is `stanag4609`'s: twenty-six more verdicts than 1.4.1 shipped, from the
seven new security payloads and their parsed twins. `gates/wheel_install.py` reports **916** over
the same roster, which is these 458 run in each of two schema modes.

The six published schemas — `cdm_object`, `entity`, `event`, `plan_object`, `track`,
`payload_gnss_interference` — regenerate byte-identical from the models, and
`python -m synapse_cdm.schemas --check --out schemas` reports `CURRENT: schemas vs models at
1.0.0`.

## Published by CI over OIDC, as 1.1.0, 1.2.0, 1.2.1, 1.3.0, 1.4.0 and 1.4.1 were

No API token. `.github/workflows/publish.yml` builds on the tagged tree, gates that build with
`gates/wheel_install.py --mutation-check`, runs `twine check --strict`, checks that the tag names
the tree's `PACKAGE_VERSION`, and uploads those same files through PyPI Trusted Publishing after a
required reviewer approves the `pypi` environment. `PUBLICATION.md` ledger entry 6 records the
configuration.

## Artefacts

An sdist and a wheel, built once by the workflow, gated as that build, and uploaded as those same
files. Their **SHA-256 digests are recorded in `PUBLICATION.md`'s ledger** together with the
workflow run that produced them.

They are deliberately not committed here, for the reason this file has given since 1.1.0. A digest
is a property of one build rather than of the tree: two builds of one tree have identical payloads
but differ in their generated metadata, so a digest written here before the tag would not be the
digest of the file PyPI serves, and one written after the tag could never be inside the tree the tag
names. **1.3.0 measured that the hard way** — a local build and the published wheel came out at the
same byte count and were different files — so the digests to compare a download against are the
workflow's, never a rebuild's. Everything else in this document is readable off that tree, which is
what condition 4 of the release procedure asks for.

```bash
pip install synapse-cdm==1.5.0
python -m synapse_cdm.harness --list-adapters
```
