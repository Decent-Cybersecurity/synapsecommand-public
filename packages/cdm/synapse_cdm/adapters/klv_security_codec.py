"""The MISB ST 0102.12 Security Metadata LOCAL SET item layer: the element table and its maps.

WHAT THIS MODULE IS, AND WHY IT IS NEITHER `klv_codec` NOR `klv_uas_codec`
--------------------------------------------------------------------------
`klv_codec` is the framing layer and is deliberately **tag-blind**; `klv_uas_codec` is the ITEM
layer for **one document**, MISB ST 0601.14a, and its own docstring states the arrangement: "the
tag table lives here, one layer up, on the `cat048_codec` / `asterix_cat048` precedent: a codec
that reads octets, and above it a codec that knows what they mean." This module is that same
layer for a **different document** — MISB ST 0102.12 — and it is its own module rather than a
second table inside `klv_uas_codec` for three reasons, of which the second is decisive.

1. **The precedent is one item layer per document.** `klv_uas_codec` cites ST 0601.14a and
   EG 0601.1 by SHA-256 at module scope, so that a reader asking "which copy is this read from"
   gets one answer. A module carrying a third document's table would have to answer differently
   for different tags.
2. **THE TAG NUMBERS COLLIDE, AND `ITEMS` IS KEYED ON THE TAG.** In ST 0601.14a tag 1 is Checksum,
   tag 2 is Precision Time Stamp, tag 3 is Mission ID, tag 13 is Sensor Latitude and tag 22 is
   Target Width. In ST 0102.12 tag 1 is Security Classification, tag 2 is the Country Coding
   Method, tag 3 is Classifying Country, tag 13 is Object Country Codes and tag 22 is Version.
   **Every one of this document's seventeen tags collides with a tag of that one.** Two tables
   cannot share one `dict[int, ...]`, and a module holding two dicts keyed on the same integers is
   a module where a lookup's meaning depends on which document the reader thought they were in —
   which is the class of defect `cat048_codec`'s ellipsoid audit exists for, in a new place.
3. **The value maps have nothing in common.** ST 0601's items are affine maps over integers with
   stated Min/Max/Offset; ST 0102's are an enumeration lookup, an ISO 646 string and a uint16.
   `klv_uas_codec._Item` has twenty-seven fields, of which ST 0102.12 states none.

WHY THIS DOCUMENT'S ITEMS ARE READ AT ALL, WHEN MOST ST 0601 ITEMS ARE NOT
--------------------------------------------------------------------------
`klv_uas_codec`'s scope contract is that an item this repository has never met on a wire "is an
item whose decoder could only ever be checked against a fixture written from the same reading of
the same table". Item 48 is **not** in the pinned stream and the contract's premise therefore
applies to it — so crossing it needs a ground, and the ground is that **the check comes from a
second document rather than from a second reading of the first**:

* ST 0601.14a §8.48 prints ``KLV Key 06.0E.2B.34.02.03.01.01.0E.01.03.03.02.00.00.00 (CRC 40980)``;
* ST 0102.12 §6.7 registers the Security Metadata Local Set key as
  ``06 0E 2B 34 02 03 01 01 0E 01 03 03 02 00 00 00 (CRC 40980)``.

Two documents, obtained on different days from different routes, state the same sixteen octets and
the same CRC. **No unwitnessed ST 0601 item has a second document behind it**, which is exactly why
this one crossed the contract when it did and why no other row has crossed on THIS ground.

**AND THAT SENTENCE STOPPED BEING TRUE ON 2026-09-06, WHICH IS RECORDED HERE RATHER THAN EDITED
ABOVE.** The park 7 round pinned MISB ST 0806.4 and item 73 now has a second document behind it on
exactly this ground: ST 0601.14a §8.73 prints ``06.0E.2B.34.02.0B.01.01.0E.01.03.01.02.00.00.00
(CRC 17945)`` and `ST 0806.4-06` states the same sixteen octets and the same CRC. So the
second-document ground is no longer unique to item 48 — it has been reached TWICE, by two
different pairs of documents — and what the sentence above still records correctly is why item 48
crossed WHEN IT DID, which was the only such pair at the time. `klv_rvt_codec` is the second
module standing on it.

**THIS PARAGRAPH USED TO SAY THAT IS WHY "THE OTHER 115 STAY `not yet`", AND IT WAS OVERTAKEN ON
2026-09-04**: seventeen rows crossed on a different ground — ST 0601.14a's own printed worked
examples — so a unique second document explains item 48's promotion and no longer explains anybody
else's absence. The remaining rows are held by the scope contract and their count is derived in
`FORMAT_COVERAGE.md`'s "Not witnessed" ledger row. Corrected 2026-09-05 by the maintenance sweep. What is still true of item 48 and is
recorded rather than smoothed over: the pinned stream carries no security set, so nothing below is
checked against an octet anybody has met on a wire, and ST 0102.12 prints **no worked example of a
complete set** — see `WHY check_against_the_documents_own_examples HAS NO TWIN HERE`.

WHAT IS ON THE WIRE INSIDE ITEM 48, WHICH IS NOT A PACKET
----------------------------------------------------------
ST 0601.14a §8.48's bullets: "Use the MISB ST 0102 Local Set tags within the MISB ST 0601 item 48"
and "The length field is the size of all MISB ST 0102 metadata items to be packaged within item
48". So item 48's Value is a **bare run of Local Set triplets** — no 16-byte Universal Label and no
second BER length wrapper — which is why this module walks the span itself with `klv_codec`'s
BER-OID and BER length primitives rather than calling `walk_local_set`, whose first act is to read
a key. The registered key above is the set's IDENTITY and is not an octet a conforming item 48
carries; it is recorded at `LOCAL_SET_KEY` for that reason and never matched against a buffer.

THE LOCAL SET AND NOT THE UNIVERSAL SET, AND THE DOCUMENT SAYS SO TWICE
-----------------------------------------------------------------------
ST 0102.12 §6.6 defines a Universal Set of the same seventeen elements under 16-byte keys. It is
**out of scope here**, on two statements of the delegating document rather than on convenience:
ST 0601.14a §8.48.1 — "MISB ST 0102 [14] allows for the use of either Universal Set or Local Set
methods. However, to minimize bandwidth when incorporating MISB ST 0102 into an instance of the
UAS Datalink LS, the Local Set method is required" — and `ST 0601.14-31`, "When incorporating the
ST 0102 Security Metadata set into an instance of the UAS Datalink Local Set, the ST 0102 format
shall use the Local Set format." The Universal Set is a different carrier and nothing here reads
it.

THE CONFIDENTIALITY RULING, WHICH DECIDES EVERY MAP BELOW
----------------------------------------------------------
**A classification is CARRIED AND NEVER INVENTED** — the NITS precedent, reached a second time.
Three consequences, each visible in the code:

* an enumeration value the document does not list is carried as its **integer** with no label, and
  the absence of a label is the honest output. Emitting a nearest-match string would be this
  module inventing a marking;
* an element the document forbids in the shape it arrived in is **refused as an element** and its
  octets are parked. The set is not refused, because discarding sixteen well-formed elements over
  one malformed one destroys evidence — `klv_uas_codec.LENGTH_DIVERGENCE_POLICY`'s reasoning,
  reached by a second document;
* **a set that is absent produces no marking at all.** §6.5: "The absence of Security Metadata does
  not signify Motion Imagery Data as Unclassified." A packet with no item 48 is UNLABELLED, and
  "unlabelled" is not a value of any field — so the caller emits the sentence and no marking.

WHY `check_against_the_documents_own_examples` HAS NO TWIN HERE
---------------------------------------------------------------
`klv_uas_codec` can run its decoder over 26 worked examples because ST 0601.14a prints one per
item. **ST 0102.12 prints none.** Its only examples are two country codes at §6.1.2 and §6.1.3
("GENC Two Letter"; "//CZE", "//GB") and one Tag 2 value at §6.9 ("a Tag 2 value of '0C'"), and it
carries no hex example of an encoded element or set anywhere in its eighteen pages — every run of
hex in the document is one of the two registered 16-byte keys or a Universal Set constituent's.
So the strongest check available to `klv_uas_codec` is **not available here and is not simulated**;
what stands in its place is stated at `TRANSCRIPTION_CROSS_CHECK` and is weaker, and saying which
is the point.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from synapse_cdm.adapters import klv_codec as framing

#: The pinned copy every citation in this module is read from. Stated here as well as in
#: `klv_pin.json` because a module that cites sections without naming the copy is citing a memory.
SOURCE_ST_0102_12 = (
    "MISB ST 0102.12, SHA-256 "
    "20d40b5237cdcd2f486547add8eee238e37d5a6b11b7e0aca306be0785eca267, "
    "fixtures/klv/spec/ST0102.12.pdf"
)

#: §6.7: "The Security Metadata Local Set 16-byte Universal Label Key is registered in MISB ST 0807
#: as: 06 0E 2B 34 02 03 01 01 0E 01 03 03 02 00 00 00 (CRC 40980)." **Recorded as the set's
#: identity and never matched against a buffer** — inside ST 0601 item 48 the key is not on the
#: wire, because §8.48's own bullet makes the item's length "the size of all MISB ST 0102 metadata
#: items". ST 0601.14a §8.48 prints the same sixteen octets and the same CRC, which is the
#: two-document agreement this module's scope ruling rests on.
LOCAL_SET_KEY = bytes.fromhex("060E2B34020301010E01030302000000")
LOCAL_SET_KEY_CRC = 40980

#: §6.6, recorded so that the absence is a ruling rather than an omission. The Universal Set's key
#: is "06 0E 2B 34 02 01 01 01 02 08 02 00 00 00 00 00 (CRC 31942)" and it carries the same
#: seventeen elements under 16-byte keys. Out of scope by `ST 0601.14-31`; nothing here reads it.
UNIVERSAL_SET_KEY_NOT_READ = bytes.fromhex("060E2B34020101010208020000000000")
UNIVERSAL_SET_KEY_CRC = 31942


class SecurityItemError(ValueError):
    """A value this module refuses to decode or encode, with the clause that decides it."""


# ------------------------------------------------------------------- the element table


class _Element(NamedTuple):
    """One row of §6.7's Table 2, in THE DOCUMENT'S OWN COLUMNS, plus its §6.1.n definition.

    The six fields `tag`, `name`, `data_type`, `allowed_values`, `length`, `presence` are the six
    columns Table 2 draws, transcribed cell by cell. `section` and `definition_verbatim` are the
    §6.1.n paragraph the row points at, and `requirements` are the requirement IDs stated in that
    paragraph — so a reader can get from a row to every normative sentence about it without
    leaving this table.

    `kind` is the only field that is not transcribed: it is this module's classification of the
    Data Type cell into a decoding rule, and each value's ground is at `DECODING_RULES`.
    """

    tag: int
    name: str
    data_type: str
    allowed_values: str
    length: str
    presence: str
    section: str
    definition_verbatim: str
    requirements: tuple[str, ...]
    kind: str


#: How each `Data Type or References` cell becomes a decoding rule, and the ground for each.
DECODING_RULES = {
    "uint8_enum": (
        "the Data Type cell reads `uint8` and the Allowed Values cell enumerates the legal "
        "integers with their meanings in parentheses. Decoded as one unsigned octet; the label is "
        "looked up in the element's OWN enumeration and never in another element's — see "
        "`THE_TWO_COUNTRY_CODING_ENUMERATIONS_DIFFER`. An integer the cell does not list is "
        "carried WITHOUT a label, because a nearest match would be an invented marking"),
    "uint16": (
        "the Data Type cell reads `uint16` and the Length cell reads 2. Decoded big-endian, which "
        "is `ST 0102.10-02`'s delegation to MISB ST 0107 [9] — 'All security metadata shall be "
        "expressed in accordance with MISB ST 0107' — the document park 4 closed on"),
    "iso646": (
        "the Data Type cell reads `ISO/IEC 646 [18]`, reference [18] being 'ISO/IEC 646:1991 "
        "Information Technology - ISO 7-bit coded character set for information exchange'. "
        "Decoded as strict 7-bit ASCII: an octet at or above 0x80 is not an ISO 646 character and "
        "is refused as an element rather than reinterpreted under some other encoding"),
    "iso646_by_derivation": (
        "TAG 3 ONLY, and it is DERIVED from two held statements rather than read off one cell. "
        "Table 2's Data Type cell for tag 3 reads only \"Text from the appropriate standard "
        "preceded by '//'\" and omits the `ISO/IEC 646 [18]` that Table 1's Universal Set row for "
        "the same element carries. §6.8 lists the elements whose Local Set form differs from the "
        "Universal Set form and names EXACTLY THREE — §6.8.1 Security Classification, §6.8.2 the "
        "Classifying Country and Releasing Instructions Country Code, §6.8.3 Object Country "
        "Coding Method, which are tags 1, 2 and 12 — so tag 3's two forms do not differ and the "
        "Universal Set row's data type governs. Decoded exactly as `iso646`"),
    "utf16_country_codes": (
        "TAG 13 ONLY, AND IT IS THE COMPOSITION OF THREE HELD DOCUMENTS. §6.7's Data Type cell "
        "reads `RFC 2781 [26] [27]`, reference [26] being 'IETF RFC 2781 UTF-16, and encoding of "
        "ISO 10646, Feb 2000' — a UTF-16 encoding, where every other text element in this row set "
        "is ISO/IEC 646. **RFC 2781 IS NOW HELD**: pinned 2026-09-04 as text, at "
        "`fixtures/klv/spec/rfc2781.txt`, SHA-256 "
        "e3fed703a962e1e8a1740fef500d1908df3eca2d80de8bad012835f0ae75b502, 29 870 bytes, 14 pages. "
        "**SO THE BYTE ORDER IS READ OFF A DOCUMENT AND IS NO LONGER A GUESS.** Which document "
        "supplies which half: ST 0102.12 supplies NONE of it — §6.1.13 states presence, the "
        "semi-colon separator, concatenation and the frame-centre rule, and the strings `BOM`, "
        "`byte order`, `endian` and `Unicode` occur zero times in its own voice across all "
        "eighteen pages. RFC 2781 §4.3 supplies the rule for the unlabelled `UTF-16` charset the "
        "Data Type cell names, §3.2 supplies what a leading 0xFEFF is and what a later one is not, "
        "and §2.2 supplies the decode and its two error cases. MISB ST 0107.3's `ST 0107.2-02` "
        "independently requires big-endian across all MISB documents, so the no-BOM default and "
        "the MISB baseline AGREE by two held statements rather than by one SHOULD. `-24` and `-25` "
        "are now APPLIED — the element is one entry and its codes are split on the semi-colon — "
        "and `-26` remains a producer's rule nothing here computes. The codes are carried and "
        "never validated: GEC, ISO 3166, STANAG 1059 and GENC are external registers this "
        "repository does not hold. See `TAG_13_BYTE_ORDER_RULE`, `RFC_2781_SECTION_4_3`, "
        "`RFC_2781_SECTION_3_2`, `ST_0107_2_02` and `SPLIT_CLAUSES`"),
    "carried_octets": (
        "RETIRED 2026-09-04 AND KEPT AS THE RULE THAT WAS, because it is what four goldens said "
        "and what a consumer of every release up to 1.4.1 received. It read that RFC 2781 IS NOT "
        "HELD BY THIS REPOSITORY, so tag 13's octets were CARRIED VERBATIM as hex and no string "
        "was produced: decoding UTF-16 requires a byte order, a byte order is what RFC 2781 "
        "states, and guessing one would have been a rule read off a reference rather than off a "
        "document. That was the one element of the seventeen whose row read `not yet`, and the "
        "reason was always an unheld document rather than unwritten code. **THE SURFACE ROUND OF "
        "2026-09-04 NARROWED THE BLOCKER AND THE TEXT-PINS ROUND OF THE SAME DAY CLOSED IT.** The "
        "surface round found the document free, stable, erratum-free and served over a route that "
        "answered 200 on the first ask, and found that what stood in the way was not acquisition "
        "but this repository's own gates: every one of them recognised a pin by `.pdf`. That was a "
        "schema question, it was ruled, and the acquisition was one GET. **THE HONEST SHAPE OF THE "
        "WHOLE EPISODE, RECORDED HERE BECAUSE THIS IS WHERE A READER MEETS IT:** the row said "
        "'unheld document' for as long as it did because nobody had asked the publisher, and when "
        "somebody did the answer was a 200 and a missing PDF. The rule that replaced this one is "
        "`utf16_country_codes` above"),
}

#: §6.1.1's enumeration, from Table 2's Allowed Values cell for tag 1. The five strings are the
#: document's own and §6.1.1 states them again in prose: "Values allowed include: TOP SECRET,
#: SECRET, CONFIDENTIAL, RESTRICTED, and UNCLASSIFIED (all caps) followed by a double forward
#: slash". The mapping from integer to string is §6.8.1, "Convert unsigned integer to
#: corresponding uppercase string" — so the label is CARRIED from two clauses of a held document
#: and is not this module's paraphrase of a number.
SECURITY_CLASSIFICATION = {
    0x01: "UNCLASSIFIED//",
    0x02: "RESTRICTED//",
    0x03: "CONFIDENTIAL//",
    0x04: "SECRET//",
    0x05: "TOP SECRET//",
}

#: Tag 2's enumeration, Table 2's Allowed Values cell, sixteen values.
COUNTRY_CODING_METHOD = {
    0x01: "ISO-3166 Two Letter",
    0x02: "ISO-3166 Three Letter",
    0x03: "FIPS 10-4 Two Letter",
    0x04: "FIPS 10-4 Four Letter",
    0x05: "ISO-3166 Numeric",
    0x06: "1059 Two Letter",
    0x07: "1059 Three Letter",
    0x08: "Omitted Value",
    0x09: "Omitted Value",
    0x0A: "FIPS 10-4 Mixed",
    0x0B: "ISO 3166 Mixed",
    0x0C: "STANAG 1059 Mixed",
    0x0D: "GENC Two Letter",
    0x0E: "GENC Three Letter",
    0x0F: "GENC Numeric",
    0x10: "GENC Mixed",
}

#: Tag 12's enumeration, Table 2's Allowed Values cell, sixteen values — AND IT IS NOT TAG 2'S.
OBJECT_COUNTRY_CODING_METHOD = {
    0x01: "ISO-3166 Two Letter",
    0x02: "ISO-3166 Three Letter",
    0x03: "ISO-3166 Numeric",
    0x04: "FIPS 10-4 Two Letter",
    0x05: "FIPS 10-4 Four Letter",
    0x06: "1059 Two Letter",
    0x07: "1059 Three Letter",
    0x08: "Omitted Value",
    0x09: "Omitted Value",
    0x0A: "Omitted Value",
    0x0B: "Omitted Value",
    0x0C: "Omitted Value",
    0x0D: "GENC Two Letter",
    0x0E: "GENC Three Letter",
    0x0F: "GENC Numeric",
    0x40: "GENC AdminSub",
}

#: **THE TRAP IN THIS DOCUMENT, AND IT IS THE ONE AN IMPLEMENTER IS MOST LIKELY TO WALK INTO.**
#: Tags 2 and 12 are both a "Country Coding Method", both `uint8`, both Required, and their
#: enumerations DISAGREE at seven of sixteen positions. `0x03` is FIPS 10-4 Two Letter under tag 2
#: and ISO-3166 Numeric under tag 12; `0x04` and `0x05` are shifted by one the same way; `0x0A`,
#: `0x0B` and `0x0C` are the three "Mixed" methods under tag 2 and "Omitted Value" under tag 12;
#: and the sixteenth value is `0x10 GENC Mixed` under tag 2 against `0x40 GENC AdminSub` under
#: tag 12. Only `0x01`, `0x02`, `0x06` through `0x09`, `0x0D`, `0x0E` and `0x0F` agree.
#:
#: **The prose corroborates the table independently, which is what makes this a finding rather
#: than an extraction artefact.** §6.1.2 says of the tag 2 method "GENC administrative subdivision
#: codes are not applicable", and §6.1.12 says of the tag 12 method that it allows "GENC two-
#: letter, three-letter, three-digit numeric or administrative subdivisions" — so the asymmetry at
#: `0x40` is stated twice, in a table and in a paragraph, by two different sentences.
#:
#: A decoder sharing one enumeration between the two elements would report a coding method that
#: the packet did not state, for seven of the sixteen legal values, silently. The two dicts above
#: are separate for that reason and this constant exists so the reason cannot be lost.
THE_TWO_COUNTRY_CODING_ENUMERATIONS_DIFFER = (
    "Tags 2 and 12 are both uint8 Country Coding Methods and their Allowed Values cells disagree "
    "at 0x03, 0x04, 0x05, 0x0A, 0x0B, 0x0C and the sixteenth value (0x10 GENC Mixed under tag 2, "
    "0x40 GENC AdminSub under tag 12). Corroborated by §6.1.2's 'GENC administrative subdivision "
    "codes are not applicable' against §6.1.12's 'or administrative subdivisions'. Each element is "
    "decoded against its OWN enumeration; sharing one would misreport seven of sixteen values"
)

ELEMENTS: dict[int, _Element] = {
    1: _Element(
        tag=1, name="Security Classification", data_type="uint8",
        allowed_values=("UNCLASSIFIED// (0x01) RESTRICTED// (0x02) CONFIDENTIAL// (0x03) "
                        "SECRET// (0x04) TOP SECRET// (0x05)"),
        length="1", presence="Required", section="6.1.1",
        definition_verbatim=(
            "The Security Classification metadata element represents the overall security "
            "classification of the Motion Imagery Data in accordance with U.S. and NATO "
            "classification guidance. Values allowed include: TOP SECRET, SECRET, CONFIDENTIAL, "
            "RESTRICTED, and UNCLASSIFIED (all caps) followed by a double forward slash “//”. "
            "This is a mandatory entry in a Security Metadata set."),
        requirements=("ST 0102.10-03",), kind="uint8_enum"),
    2: _Element(
        tag=2, name="Classifying Country and Releasing Instructions Country Coding Method",
        data_type="uint8",
        allowed_values=("ISO-3166 Two Letter (0x01) ISO-3166 Three Letter (0x02) FIPS 10-4 Two "
                        "Letter (0x03) FIPS 10-4 Four Letter (0x04) ISO-3166 Numeric (0x05) 1059 "
                        "Two Letter (0x06) 1059 Three Letter (0x07) Omitted Value (0x08) Omitted "
                        "Value (0x09) FIPS 10-4 Mixed (0x0A) ISO 3166 Mixed (0x0B) STANAG 1059 "
                        "Mixed (0x0C) GENC Two Letter (0x0D) GENC Three Letter (0x0E) GENC "
                        "Numeric (0x0F) GENC Mixed (0x10)"),
        length="1", presence="Required", section="6.1.2",
        definition_verbatim=(
            "This metadata element identifies the country coding method for the Classifying "
            "Country (Par. 6.1.3) and Releasing Instructions (Par. 6.1.6) metadata. The Country "
            "Coding Method value allows GEC two-letter or four-letter alphabetic country code "
            "(legacy systems only); ISO-3166 [15] [16] two-letter, three-letter, or three-digit "
            "numeric; STANAG 1059 [17] two-letter or three-letter codes; and GENC two-letter, "
            "three-letter or three-digit numeric. GENC administrative subdivision codes are not "
            "applicable."),
        requirements=("ST 0102.10-04",), kind="uint8_enum"),
    3: _Element(
        tag=3, name="Classifying Country",
        data_type="Text from the appropriate standard preceded by ‘//’",
        allowed_values="FIPS 10-4 [7] ISO-3166 [15] [16] STANAG 1059 [17] GENC [6]",
        length="Variable", presence="Required", section="6.1.3",
        definition_verbatim=(
            "The Classifying Country metadata element contains a value for the classifying "
            "country code preceded by a double slash \"//.\""),
        requirements=("ST 0102.10-05",), kind="iso646_by_derivation"),
    4: _Element(
        tag=4, name="Security-SCI/SHI information", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Ref [1]", length="Variable", presence="Context", section="6.1.4",
        definition_verbatim=(
            "§6.1.4 is titled 'Sensitive Compartmented Information (SCI) / Special Handling "
            "Instructions (SHI) Information' and states NO descriptive paragraph at all — it is a "
            "heading followed directly by six requirements. Recorded as an absence rather than "
            "filled in, because a paraphrase of six 'shall' sentences into a definition would be "
            "this transcription writing prose the document does not carry."),
        requirements=("ST 0102.10-06", "ST 0102.10-07", "ST 0102.10-08", "ST 0102.10-09",
                      "ST 0102.10-10", "ST 0102.10-11"), kind="iso646"),
    5: _Element(
        tag=5, name="Caveats", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Ref [1]", length="Variable", presence="Context", section="6.1.5",
        definition_verbatim=(
            "The Caveats metadata element represents pertinent caveats (or code words) from each "
            "category of the appropriate security entity register. Entries in this field may be "
            "abbreviated or spelled out as free text [18] entries."),
        requirements=("ST 0102.10-13", "ST 0102.10-14"), kind="iso646"),
    6: _Element(
        tag=6, name="Releasing Instructions", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Refs [1] [20, 21, 22, 23, 24, 25]", length="Variable",
        presence="Context", section="6.1.6",
        definition_verbatim=(
            "The Releasing Instructions metadata element contains a list of country codes to "
            "indicate the countries to which the Motion Imagery Data is releasable."),
        requirements=("ST 0102.10-15", "ST 0102.10-16", "ST 0102.10-17", "ST 0102.11-63",
                      "ST 0102.11-64"), kind="iso646"),
    7: _Element(
        tag=7, name="Classified By", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Refs [1] [24]", length="Variable", presence="Context",
        section="6.1.7",
        definition_verbatim=(
            "The Classified By metadata element identifies the name and type of authority used to "
            "classify the Motion Imagery Data. The metadata element is free text and can contain "
            "either the original classification authority name and position or personal "
            "identifier, or the title of the document or security classification guide used to "
            "classify the data."),
        requirements=(), kind="iso646"),
    8: _Element(
        tag=8, name="Derived From", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Refs [1], [24]", length="Variable", presence="Context",
        section="6.1.8",
        definition_verbatim=(
            "The Derived From metadata element contains information about the original source of "
            "data from which the classification was derived. The metadata element is free text "
            "[18]."),
        requirements=(), kind="iso646"),
    9: _Element(
        tag=9, name="Classification Reason", data_type="ISO/IEC 646 [18]",
        allowed_values="Security Refs [1], [24]", length="Variable", presence="Context",
        section="6.1.9",
        definition_verbatim=(
            "The Classification Reason metadata element contains the reason for classification or "
            "a citation from a document. The metadata element is free text [18]."),
        requirements=(), kind="iso646"),
    10: _Element(
        tag=10, name="Declassification Date", data_type="ISO/IEC 646 [18]",
        allowed_values="YYYYMMDD", length="8", presence="Context", section="6.1.10",
        definition_verbatim=(
            "The Declassification Date metadata element provides a date when the classified "
            "material may be automatically declassified."),
        requirements=("ST 0102.10-22",), kind="iso646"),
    11: _Element(
        tag=11, name="Classification and Marking System", data_type="ISO/IEC 646 [18]",
        allowed_values="N/A", length="Variable", presence="Context", section="6.1.11",
        definition_verbatim=(
            "The Classification and Marking System metadata element identifies the classification "
            "or marking system used in the Security Metadata set as determined by the appropriate "
            "security entity for the country originating the data."),
        requirements=("ST 0102.10-21",), kind="iso646"),
    12: _Element(
        tag=12, name="Object Country Coding Method", data_type="uint8",
        allowed_values=("ISO-3166 Two Letter (0x01) ISO-3166 Three Letter (0x02) ISO-3166 Numeric "
                        "(0x03) FIPS 10-4 Two Letter (0x04) FIPS 10-4 Four Letter (0x05) 1059 Two "
                        "Letter (0x06) 1059 Three Letter (0x07) Omitted Value (0x08) Omitted "
                        "Value (0x09) Omitted Value (0x0A) Omitted Value (0x0B) Omitted Value "
                        "(0x0C) GENC Two Letter (0x0D) GENC Three Letter (0x0E) GENC Numeric "
                        "(0x0F) GENC AdminSub (0x40)"),
        length="1", presence="Required", section="6.1.12",
        definition_verbatim=(
            "The Object Country Coding Method metadata element identifies the coding method for "
            "the Object Country Code (Par. 6.1.13) metadata. This element allows use of GEC "
            "two-letter or four-letter alphabetic country code (legacy systems only); ISO-3166 "
            "two-letter, three-letter, or three-digit numeric; STANAG 1059 two-letter or "
            "three-letter codes; and GENC two-letter, three-letter, three-digit numeric or "
            "administrative subdivisions. Use of this element in version 6 of this Standard and "
            "later is mandatory. In version 5 and earlier, it was optional; its absence indicates "
            "the default GENC two-letter coding method was used in the Object Country Code "
            "element. See also Section 6.9."),
        requirements=(), kind="uint8_enum"),
    13: _Element(
        tag=13, name="Object Country Codes", data_type="RFC 2781 [26] [27]",
        allowed_values="Refs [15] [16] [28] [29]", length="Variable", presence="Required",
        section="6.1.13",
        definition_verbatim=(
            "The Object Country Codes metadata element contains a value identifying the country "
            "(or countries), which is the object of the Motion Imagery Data."),
        requirements=("ST 0102.10-23", "ST 0102.10-24", "ST 0102.10-25", "ST 0102.10-26"),
        kind="utf16_country_codes"),
    14: _Element(
        tag=14, name="Classification Comments", data_type="ISO/IEC 646 [18]",
        allowed_values="N/A", length="Variable", presence="Optional", section="6.1.14",
        definition_verbatim=(
            "The Classification Comments metadata element allows for security related comments "
            "and format changes necessary in the future. This field may be used in addition to "
            "those required by appropriate security entity and is optional."),
        requirements=("ST 0102.10-27",), kind="iso646"),
    22: _Element(
        tag=22, name="Version", data_type="uint16",
        allowed_values=("Value is version number of this document; e. g. for ST 0102.10, this "
                        "value is 0x000A"),
        length="2", presence="Required", section="6.1.15",
        definition_verbatim=(
            "The Version metadata element indicates the version number of MISB ST 0102 "
            "referenced."),
        requirements=("ST 0102.10-56", "ST 0102.10-57"), kind="uint16"),
    23: _Element(
        tag=23,
        name=("Classifying Country and Releasing Instructions Country Coding Method Version "
              "Date"),
        data_type="ISO/IEC 646 [18]", allowed_values="YYYY-MM-DD", length="10",
        presence="Optional", section="6.1.16",
        definition_verbatim=(
            "This metadata element provides the effective date (promulgation date) of the source "
            "(FIPS 10-4, ISO 3166, GENC 2.0, or STANAG 1059) used for the Classifying Country and "
            "Releasing Instructions Country Coding Method. As ISO 3166 is updated by dated "
            "circulars, not by version revision, the ISO 8601 YYYY-MM-DD formatted date is used."),
        requirements=(), kind="iso646"),
    24: _Element(
        tag=24, name="Object Country Coding Method Version Date", data_type="ISO/IEC 646 [18]",
        allowed_values="YYYY-MM-DD", length="10", presence="Optional", section="6.1.17",
        definition_verbatim=(
            "The Object Country Coding Method Version Date metadata element is the effective date "
            "(promulgation date) of the source (FIPS 10-4, ISO 3166, GENC 2.0, or STANAG 1059) "
            "used for the Object Country Coding Method. As ISO 3166 is updated by dated "
            "circulars, not by version revision, the ISO 8601 YYYY-MM-DD formatted date is used."),
        requirements=(), kind="iso646"),
}

#: Every tag §6.7's Table 2 draws, in the order it draws them. SEVENTEEN, and the gap is real.
ELEMENT_TAGS: tuple[int, ...] = tuple(sorted(ELEMENTS))

#: The Required/Optional/Context column, split. 6 + 8 + 3 = 17, which is the count check the table
#: offers about itself and the reason the split is derived here rather than typed.
REQUIRED_TAGS: tuple[int, ...] = tuple(
    t for t in ELEMENT_TAGS if ELEMENTS[t].presence == "Required")
CONTEXT_TAGS: tuple[int, ...] = tuple(
    t for t in ELEMENT_TAGS if ELEMENTS[t].presence == "Context")
OPTIONAL_TAGS: tuple[int, ...] = tuple(
    t for t in ELEMENT_TAGS if ELEMENTS[t].presence == "Optional")

#: **TAGS 15 THROUGH 21 ARE ABSENT FROM TABLE 2, AND WHAT THE DOCUMENT SAYS ABOUT THAT IS LESS
#: THAN THE ABSENCE.** The table runs 1..14 and then jumps to 22. The revision history's own
#: account of the edition is two bullets — "Eliminated linking of security set to transport
#: stream, elementary stream and individual metadata items" and "Deleted keys: UMID, Stream ID,
#: Transport Stream ID, Item Designator" — corroborated by Appendix A, where `ST 0102.10-32`
#: through `-48` are the deprecated linking requirements and name exactly those four carriers.
#:
#: **WHAT IS NOT DERIVABLE HERE, STATED RATHER THAN GUESSED:** the revision history names four
#: KEYS and the gap is seven TAG NUMBERS, so the two do not account for one another; and the
#: document nowhere prints the tag numbers the deleted keys occupied. MISB ST 0102.11, which would
#: settle it, is NOT HELD. So this record says the tags are absent, quotes what the document says
#: was removed, and stops — a decoder meeting tag 15..21 on a wire treats it as an unlisted tag.
ABSENT_TAGS: tuple[int, ...] = (15, 16, 17, 18, 19, 20, 21)
ABSENT_TAGS_BASIS = (
    "Table 2 carries no row between tag 14 and tag 22. ST 0102.12's Revision History states what "
    "this edition removed — 'Eliminated linking of security set to transport stream, elementary "
    "stream and individual metadata items' and 'Deleted keys: UMID, Stream ID, Transport Stream "
    "ID, Item Designator' — and Appendix A carries ST 0102.10-32 through -48 as the deprecated "
    "linking requirements naming those carriers. THE ACCOUNT IS INCOMPLETE AND IS RECORDED AS "
    "SUCH: four keys are named and seven tag numbers are absent, and the document never prints "
    "the tag number any deleted key occupied. MISB ST 0102.11 would settle it and is not held"
)

#: The count check that makes the transcription checkable, stated where the table is.
TRANSCRIPTION_CROSS_CHECK = (
    "THE DOCUMENT STATES THE SAME SEVENTEEN ELEMENTS TWICE AND BOTH WERE READ, WHICH IS PARK 1'S "
    "ARRANGEMENT REACHED BY A SECOND DOCUMENT. §6.7's Table 2 draws seventeen tag rows — 1 "
    "through 14, then 22, 23, 24 — and §6.1 carries seventeen numbered subsections, §6.1.1 "
    "through §6.1.17, one per element and in the same order. The two agree on all seventeen "
    "names with no element in one and not the other. A THIRD statement checks the three elements "
    "that matter most: §6.8 gives conversion rules between the Universal and Local Set forms and "
    "has EXACTLY THREE subsections — §6.8.1 Security Classification, §6.8.2 Classifying Country "
    "and Releasing Instructions Country Code, §6.8.3 Object Country Coding Method — which are "
    "exactly the three rows whose Table 2 Data Type reads `uint8` where Table 1's reads text. "
    "AND A FOURTH, over the same rows from the other side: §6.1's Table 1 for the Universal Set "
    "lists the same seventeen elements under 16-byte keys, so a row present in one carrier and "
    "absent from the other would show. WHAT THIS CANNOT DO, AND `klv_uas_codec` CAN: check a "
    "decoded value against the document's own worked example, because ST 0102.12 prints none"
)

#: §6.2, quoted with its clauses. The repetition rate is a PRODUCER's obligation and reaches no
#: decode: a decoder meets one packet at a time and cannot see thirty seconds.
REPETITION_RATE = (
    "§6.2 Security Metadata Repetition Rate. `ST 0102.10-49`: 'A Security Metadata set shall be "
    "repeated / updated whenever classification, special handling instructions, releasability, or "
    "other mandatory fields change value.' `ST 0102.10-50`: 'Security Metadata Sets shall be "
    "repeated no less than every thirty (30) seconds.' Followed by: 'Applications producing short "
    "Motion Imagery Data clips or segments of a few seconds in duration may need to repeat "
    "Security Metadata Sets as often as every frame.' BOTH ARE OBLIGATIONS ON A PRODUCER ACROSS "
    "PACKETS. This adapter states in its own docstring that no state crosses a packet boundary, "
    "so it neither checks nor enforces them and says so rather than implying compliance"
)

#: §6.3, quoted. The one clause that puts a VALUE on the wire for unclassified data.
UNCLASSIFIED_MOTION_IMAGERY_DATA = (
    "§6.3 Unclassified Motion Imagery Data. `ST 0102.10-54`: 'Unclassified Motion Imagery Data "
    "shall be marked with Security Metadata.' `ST 0102.10-51`: 'When Motion Imagery Data is "
    "unclassified, the Security Metadata Set value shall be \"UNCLASSIFIED//\" for Security "
    "Classification.' Followed by: 'Other entries in the set which limit or clarify the "
    "classification are optional.' WHAT THIS DECIDES HERE: unclassified is a MARKED state with a "
    "value on the wire (0x01 by §6.8.1), which is what makes §6.5's absent set a different thing "
    "from it. It is also why the complete-set fixture uses 0x01: it is the document's own value "
    "for the one classification the document itself names in prose"
)

#: §6.4, quoted. This is what makes a set carrying five elements a legitimate set.
PARTIAL_SETS = (
    "§6.4 Partial Security Metadata Universal and Local Sets: 'For some operational situations or "
    "applications not all metadata elements in Section 6.1 may be required. The originator and "
    "his cognizant Security official are responsible to ensure all appropriate security entries "
    "are populated.' SO A SET MISSING A `Required` ELEMENT IS NOT MALFORMED. The Table 2 column "
    "reading Required states the element's status in a COMPLETE set, and §6.4 says which sets "
    "must be complete is decided outside this document by a person. A decoder that refused a "
    "partial set would be enforcing a rule ST 0102.12 explicitly declines to state — so a partial "
    "set decodes, and which elements arrived is reported rather than judged"
)

#: §6.5, quoted. **THE CLAUSE THAT DECIDES THE OUTPUT SHAPE FOR AN UNLABELLED PACKET.**
ABSENCE_OF_SETS = (
    "§6.5 Absence of Security Metadata Universal or Local Sets: 'The proper insertion/extraction "
    "of Security Metadata sets into/from Motion Imagery is the responsibility of system "
    "developers. Bit stream originators and system developers are responsible to incorporate "
    "continual checks for Security Metadata in their applications. THE ABSENCE OF SECURITY "
    "METADATA DOES NOT SIGNIFY MOTION IMAGERY DATA AS UNCLASSIFIED.' (Capitals this record's; the "
    "sentence is the document's.) WHAT IT DECIDES: a packet with no item 48 is UNLABELLED, and "
    "unlabelled is not a value. No classification field is emitted for such a packet — not "
    "'UNCLASSIFIED', not null-meaning-unclassified, not a default. What IS emitted is this "
    "sentence, so that a consumer reading the object meets the document's own statement of what "
    "the absence does not mean rather than inferring one"
)

#: §6.8, quoted. Recorded because the three conversions are where the Local Set's uint8 elements
#: get their strings, and because the section's own count is a cross-check on the table.
CONVERSION_BETWEEN_SET_FORMS = (
    "§6.8 Conversion of Security Metadata Elements between Universal and Local Sets: 'For "
    "bandwidth efficiency, some elements in the Local Set are formatted differently than the "
    "Universal Set equivalent. This section provides conversion information for the differing "
    "items.' §6.8.1 Security Classification, §6.8.2 Classifying Country and Releasing Instructions "
    "Country Code and §6.8.3 Object Country Coding Method each state the same pair: 'From "
    "Universal Set to Local Set: Convert string to corresponding unsigned integer. From Local Set "
    "to Universal Set: Convert unsigned integer to corresponding uppercase string.' THREE "
    "SUBSECTIONS FOR THREE ELEMENTS, and they are exactly tags 1, 2 and 12 — the three rows whose "
    "Local Set Data Type is uint8. That is where this module's labels come from, and it is why "
    "producing one is CARRYING a string the document states rather than naming a number"
)

#: The three external code lists this repository does not hold, and the ruling about them.
EXTERNAL_CODE_LISTS_NOT_HELD = (
    "GENC (NGA.STND.0033_3.0.1, ref [6]), the GEC register (ref [8]), ISO 3166-1 and -2:2013 "
    "(refs [15] [16]), STANAG 1059 Ed 8 (ref [17]) and IETF RFC 2781 (ref [26]) are the code "
    "lists and encodings ST 0102.12's country elements are written against. **NONE IS HELD BY "
    "THIS REPOSITORY.** THE RULING: this codec CARRIES a country code as the element's own Data "
    "Type cell says to carry it and DOES NOT VALIDATE it against a list it cannot read. A "
    "decoder that rejected '//XX' because no held file lists XX would be refusing a value on the "
    "authority of a document nobody here has opened; one that accepted it while claiming "
    "conformance would be worse. So the code is carried verbatim, the coding METHOD the packet "
    "declared is carried beside it, and what the code denotes is the consumer's lookup. This is a "
    "RULING and not an omission — the same shape as klv_codec's refusal to enforce X.690's "
    "126-octet ceiling from an informative annex quoting an unheld standard"
)

#: §6.9's example, the one Tag 2 value the document prints. Carried because it is the only worked
#: value in the document that a fixture can borrow, and §6.9 is where the Mixed methods are ruled.
MIXED_COUNTRY_CODING_METHOD = (
    "§6.9 “Mixed” Country Coding Method. `ST 0102.10-58`: 'The Mixed Country Coding Method shall "
    "be used to support di- or tri-graphs (but not both) from GEC, ISO 3166, GENC and STANAG "
    "1059, respectively, and approved tetragraphs in the same field.' Its example is the "
    "document's only printed element value: 'For example, a Tag 2 value of “0C” would indicated "
    "the payload of Tag 6 consists of STANAG 1059 di-graphs or tri-graphs (but not both), and one "
    "or more tetragraphs from the CAPCO Authorized Classification and Control Marking Register.' "
    "(The document's own 'indicated' is preserved.) Note 0x0C is `STANAG 1059 Mixed` in TAG 2's "
    "enumeration and `Omitted Value` in tag 12's, which is the divergence above meeting the "
    "document's own example"
)

#: `ST 0102.12-65` and `-66`, and the register entry that settles which edition they reach.
ST_336_CONFORMANCE = (
    "`ST 0102.12-65`: 'The Security Metadata Universal Set shall conform to SMPTE ST 336 KLV "
    "encoding rules.' `ST 0102.12-66`: 'The Security Metadata Local Set shall conform to SMPTE ST "
    "336 [3] KLV encoding rules.' Reference [3] is 'SMPTE ST 336:2007', a DIFFERENT edition from "
    "the ST 336:2017 MISP-2019.1 pins — register entry KLV 11. **RESOLVED 2026-09-03, SHAPE (a), "
    "AND CITED HERE RATHER THAN RE-ARGUED:** both editions are held and were read against each "
    "other clause by clause, and the two differences that reach a key form, a length octet or a "
    "UL structure reach no octet a conforming stream can carry. So this module's use of "
    "`klv_codec` — which is written against ST 336:2017 and ST 0107.3 — satisfies -66 as well"
)

#: The three ST 0601 statements that put this set inside item 48 and make it the LOCAL set.
CARRIER_BASIS = (
    "ST 0601.14a §8.48 Tag 48 Security Local Set, Description 'MISB ST 0102 local let Security "
    "Metadata items' (the document's own typo for 'local set', preserved), Format 'KLV set', "
    "Length 'Variable', Max Length 'Not Limited', Required in LS? 'Optional'. Its two bullets: "
    "'Use the MISB ST 0102 Local Set tags within the MISB ST 0601 item 48' and 'The length field "
    "is the size of all MISB ST 0102 metadata items to be packaged within item 48'. Its §8.48.1 "
    "Details: 'MISB ST 0102 [14] allows for the use of either Universal Set or Local Set methods. "
    "However, to minimize bandwidth when incorporating MISB ST 0102 into an instance of the UAS "
    "Datalink LS, the Local Set method is required.' And `ST 0601.14-31`: 'When incorporating the "
    "ST 0102 Security Metadata set into an instance of the UAS Datalink Local Set, the ST 0102 "
    "format shall use the Local Set format.' §8.48's Example KLV Item row prints Tag 30 (hex for "
    "48), a Len of '-' and a Value of 'N/A' — SO THE DELEGATING DOCUMENT PRINTS NO WORKED "
    "EXAMPLE EITHER, and neither of the two documents behind this codec supplies one"
)

# ------------------------------------------------------------------- refusal classes

#: An element whose octet count disagrees with a Length cell stating a fixed number.
REFUSAL_STATED_LENGTH = "stated_length_disagrees"
#: An element whose octets cannot form the integer its Data Type cell names.
REFUSAL_FORMAT_CANNOT_CARRY = "format_cannot_carry_the_octets"
#: An `ISO/IEC 646 [18]` element carrying an octet at or above 0x80.
REFUSAL_NOT_ISO_646 = "octet_outside_iso_646"
#: A `RFC 2781` element carrying an odd number of octets. UTF-16 serialises 16-bit code units as
#: two octets each, so an odd count cannot be a sequence of them — a fact about the encoding rather
#: than about the length cell, which for tag 13 reads `Variable` and forbids nothing.
REFUSAL_ODD_OCTET_COUNT = "utf16_cannot_carry_an_odd_octet_count"
#: A `RFC 2781` element whose 16-bit units are not a well-formed UTF-16 sequence — a high surrogate
#: with no low surrogate after it, or a low surrogate with no high surrogate before it.
REFUSAL_UTF16_SEQUENCE = "utf16_sequence_is_in_error"
#: A tag Table 2 does not draw a row for.
UNLISTED_TAG = "tag_not_in_table_2"

#: The policy, in one place, and it is `klv_uas_codec.LENGTH_DIVERGENCE_POLICY`'s reasoning
#: reached by a second document rather than a new idea.
ELEMENT_REFUSAL_POLICY = (
    "THE ELEMENT IS REFUSED AND THE SET IS NOT. A refused element yields no value, its octets are "
    "parked verbatim, and a structured refusal names the clause it failed. The other elements "
    "decode. THREE GROUNDS, and the third is this document's own: (1) the ST 0601 length policy "
    "already rules that discarding well-formed items over one malformed one destroys the evidence "
    "a consumer needs; (2) §6.4 makes a set missing elements a legitimate set, so a set that "
    "loses one to a refusal is a shape the document already contemplates; (3) §6.5 makes the "
    "resulting gap unambiguous — an absent classification does not read as UNCLASSIFIED, so "
    "dropping a malformed Security Classification cannot be mistaken for a claim about the data. "
    "WHAT IS NEVER DONE: reinterpreting the octets under another rule, or substituting a value "
    "the packet did not carry"
)


# ------------------------------------- tag 13's byte order, and it is a COMPOSITION OF THREE

#: RFC 2781 §4.3 VERBATIM, and it is the clause that decides tag 13's byte order.
#:
#: WHY §4.3 AND NOT §4.1 OR §4.2. Sections 4.1 and 4.2 govern text LABELLED `UTF-16BE` and
#: `UTF-16LE`, and a label is an external declaration this element does not carry: §6.7's Table 2
#: gives tag 13's Data Type as `RFC 2781 [26] [27]` and nothing narrower. The unlabelled case —
#: the plain `UTF-16` charset — is §4.3, so §4.3 is the clause that applies. Reading §4.1 into this
#: element would be assuming a label the document does not print.
RFC_2781_SECTION_4_3 = (
    "RFC 2781 §4.3, 'Interpreting text labelled as UTF-16': \"Text labelled with the 'UTF-16' "
    "charset might be serialized in either big-endian or little-endian order. If the first two "
    "octets of the text is 0xFE followed by 0xFF, then the text can be interpreted as being "
    "big-endian. If the first two octets of the text is 0xFF followed by 0xFE, then the text can "
    "be interpreted as being little-endian. If the first two octets of the text is not 0xFE "
    "followed by 0xFF, and is not 0xFF followed by 0xFE, then the text SHOULD be interpreted as "
    "being big-endian.\" And the obligation, same section: \"All applications that process text "
    "with the 'UTF-16' charset label MUST be able to read at least the first two octets of the "
    "text and be able to process those octets in order to determine the serialization order of "
    "the text. Applications that process text with the 'UTF-16' charset label MUST NOT assume the "
    "serialization without first checking the first two octets to see if they are a big-endian "
    "BOM, a little-endian BOM, or not a BOM. All applications that process text with the 'UTF-16' "
    "charset label MUST be able to interpret both big-endian and little-endian text.\""
)

#: RFC 2781 §3.2 VERBATIM, on where a BOM may be and what 0xFEFF means anywhere else. This is what
#: makes stripping a leading 0xFEFF legitimate and stripping any other 0xFEFF wrong.
RFC_2781_SECTION_3_2 = (
    "RFC 2781 §3.2, 'Byte order mark (BOM)': \"In serialized UTF-16 prepended with such a "
    "signature, the order is big-endian if the first two octets are 0xFE followed by 0xFF; if "
    "they are 0xFF followed by 0xFE, the order is little-endian.\" And the limit: \"It is "
    "important to understand that the character 0xFEFF appearing at any position other than the "
    "beginning of a stream MUST be interpreted with the semantics for the zero-width non-breaking "
    "space, and MUST NOT be interpreted as a byte-order mark.\""
)

#: MISB ST 0107.3 §6.1 VERBATIM — the SECOND held document that speaks to this, and the one that
#: makes the unmarked case a requirement here rather than only a SHOULD.
ST_0107_2_02 = (
    "MISB ST 0107.3 §6.1 'Bit and Byte Order', requirement `ST 0107.2-02`: \"Byte order shall be "
    "big-endian or MSB.\" Its scope is §1: \"This Standard defines the baseline requirements for "
    "all implementations of KLV within Motion Imagery files and streams. It applies retroactively "
    "to all documents approved by the Motion Imagery Standards Board (MISB).\""
)

#: **THE COMPOSITION, AND WHICH DOCUMENT SUPPLIES WHICH HALF.** This is the note the tag 13 row
#: was owed from the day it was written, and the reason it could not be written until 2026-09-04.
#:
#: **ST 0102.12 SUPPLIES NO HALF OF IT, AND THAT IS A MEASUREMENT RATHER THAN AN IMPRESSION.**
#: §6.1.13 was read in full and says nothing about UTF-16, a BOM or a byte order: it states what
#: the element carries (a country or countries), and four requirements — `-23` presence, `-24` the
#: semi-colon separator, `-25` concatenation in one entry, `-26` the frame-centre rule. Across all
#: eighteen pages the string `UTF` occurs ONCE and `10646` ONCE, both inside reference [26]'s title
#: on page 2; `BOM`, `byte order`, `endian`, `Unicode` and `little` occur ZERO times in the
#: document's own voice. So the encoding reaches this element ONLY through §6.7's Data Type cell
#: reading `RFC 2781 [26] [27]`, and every byte-order term has to come from somewhere else.
#:
#: **RFC 2781 SUPPLIES THE RULE**: §4.3 for the unlabelled `UTF-16` case, §3.2 for what a leading
#: 0xFEFF is and what it is not, §2.2 for the decode itself and its two error cases.
#:
#: **ST 0107.3 SUPPLIES THE AGREEMENT, AND IT IS THE FINDING OF THIS ROUND.** The round expected a
#: two-document composition and the tree has three. ST 0102.12's own reference [9] is
#: "MISB ST 0107.2 Bit and Byte Order for Metadata in Motion Imagery Files and Streams" — a
#: document this repository has held and pinned since 2026-08-26, because it closed park 4 — and
#: `ST 0107.2-02` says byte order shall be big-endian, retroactively across all MISB documents.
#: **So RFC 2781 §4.3's no-BOM default and ST 0107.2-02 AGREE, by two independent held statements**,
#: and the unmarked case is not a `SHOULD` this layer is choosing to follow: it is a `SHOULD` from
#: the IETF standing on a `shall` from the custodian of the document that cites it.
#:
#: WHERE THEY COULD DISAGREE, AND WHAT HAPPENS THEN. A packet carrying a little-endian BOM. RFC
#: 2781 §4.3 says such text CAN be interpreted as little-endian and MUST NOT be assumed otherwise
#: without reading the first two octets; ST 0107.2-02 says byte order shall be big-endian. **The
#: octets are decoded under §4.3 and an ADVISORY records that `ST 0107.2-02` was not met** — the
#: tag 22 precedent exactly, where `ST 0102.10-57`'s assumed version is recorded and not applied.
#: Refusing would discard a value the packet carried on the strength of a rule the PRODUCER broke;
#: silently big-endian-decoding it would produce mojibake and call it a country code.
TAG_13_BYTE_ORDER_RULE = (
    "The byte order is read under RFC 2781 §4.3, which is the clause for the unlabelled `UTF-16` "
    "charset the Data Type cell names. ST 0102.12 states no byte order anywhere in its own voice — "
    "§6.1.13 states presence, the semi-colon separator, concatenation and the frame-centre rule, "
    "and nothing about the encoding. MISB ST 0107.3's `ST 0107.2-02` independently requires "
    "big-endian across all MISB documents, so the no-BOM default and the MISB requirement agree. A "
    "leading BOM is honoured per §4.3 and stripped per §3.2; a 0xFEFF anywhere else is a "
    "zero-width non-breaking space and is kept. A little-endian BOM is honoured and raises an "
    "advisory against `ST 0107.2-02` rather than a refusal"
)

#: `ST 0102.10-24` and `-25` VERBATIM, the two clauses that make one element several codes.
SPLIT_CLAUSES = (
    "`ST 0102.10-24`: \"Multiple Object Country Codes shall be separated by a semi-colon "
    "\u201c;\u201d (no spaces).\" `ST 0102.10-25`: \"Multiple Object Country Codes shall be "
    "concatenated in one Object Country Code metadata element entry.\" §6.1.13's Note gives the "
    "reason: \"The use of the semi-colon to separate country codes, instead of blanks or other "
    "characters, is to allow processing by current, automated imagery processing and management "
    "tools.\""
)

#: `ST 0102.10-26` is a PRODUCER's rule and is not applied, on the standing pattern.
NOT_APPLIED_MINUS_26 = (
    "`ST 0102.10-26` — \"The object country code of the geographic region lying under the center "
    "of the image frame shall populate the Object Country Code metadata element\" — is a "
    "PRODUCER's obligation and is neither applied nor checked. Nothing here computes a country "
    "from a geometry, and the clause says which code should come FIRST rather than what any octet "
    "means. A consumer holding the codes and the frame centre can check it; this layer cannot, and "
    "asserting it would be inventing a fact about the ground"
)


# ------------------------------------- the basis's wire shape, and it is TOKENS AND POINTERS

#: **THE SURFACE RULING OF 2026-09-04, IN ONE SENTENCE: THE WIRE CARRIES FACTS AND POINTERS AND
#: THE RECORD CARRIES THE ARGUMENT.** Until that day `stanag4609._security_basis` emitted every
#: paragraph in this module — `CARRIER_BASIS`, `EXTERNAL_CODE_LISTS_NOT_HELD`, `ST_336_CONFORMANCE`,
#: `REPETITION_RATE`, `PARTIAL_SETS`, `ABSENCE_OF_SETS`, `ELEMENT_REFUSAL_POLICY`,
#: `ABSENT_TAGS_BASIS`, `CONVERSION_BETWEEN_SET_FORMS` and `DECODING_RULES["carried_octets"]` —
#: on EVERY Entity, at roughly six kilobytes an object. They are still here, still the reasoning
#: every map in this module rests on, and they are **no longer emitted**: the 1.2.0 precedent for a
#: policy that rides on every object is `klv_uas_codec.LENGTH_DIVERGENCE_POLICY`, which is one
#: token and one sentence. Every sentence that left the wire was RELOCATED and not deleted — to
#: `fixtures/klv/spec/klv_pin.json`'s `security_basis_ruling`, which names the key each paragraph
#: was emitted under so the record shows what a consumer used to receive. **THE STANDING
#: CONFIDENTIALITY RULING IS UNCHANGED IN EVERY TERM**; only where its text lives moved.
BASIS_RULING = "the wire carries facts and pointers; the record carries the argument"

#: The ruling's NAME, emitted as a token so a consumer can compare it by equality. Its text is at
#: `klv_pin.json`'s `security_basis_ruling.relocated_from_the_wire.confidentiality_ruling`.
CONFIDENTIALITY_RULING = "CARRIED AND NEVER INVENTED"

#: A packet that carried no ST 0601 item 48. §6.5: unlabelled, and unlabelled is not a value.
STATE_UNLABELLED = "UNLABELLED"
#: A set present and missing at least one element §6.7 marks `Required`. Legitimate under §6.4.
STATE_PARTIAL = "PARTIAL"
#: A set carrying all six elements §6.7 marks `Required`. Not "complete" — §6.4 declines to say
#: which sets must be complete, so this token claims the column and nothing beyond it.
STATE_COMPLETE_ON_REQUIRED = "COMPLETE-ON-REQUIRED"

#: **THE CLOSED SET.** `security_metadata_basis.state` is one of these three and never anything
#: else, because `_security_basis` distinguishes exactly three cases and has no default branch.
#: A test draws from this tuple rather than from the goldens — see `tests/test_cdm_stanag4609_adapter.py`.
BASIS_STATES: tuple[str, ...] = (STATE_UNLABELLED, STATE_PARTIAL, STATE_COMPLETE_ON_REQUIRED)

#: The one pointer the basis carries to where its argument lives. One pointer and not a list: the
#: node it names carries the onward pointers, so the wire does not have to grow a directory.
BASIS_ARGUMENT_POINTER = "fixtures/klv/spec/klv_pin.json → security_basis_ruling"

#: What carried the set, and the two ST 0601 clauses that put it there and make it the LOCAL set.
#: `CARRIER_BASIS` is these two clauses quoted; this is them pointed at.
CARRIED_IN = "ST 0601 item 48, Security Local Set"
CARRIER_CLAUSES: tuple[str, ...] = ("MISB ST 0601.14a §8.48", "ST 0601.14-31")

#: The ST 0102.12 clauses that govern each of the three states. `ABSENCE_OF_SETS`,
#: `PARTIAL_SETS` and `UNCLASSIFIED_MOTION_IMAGERY_DATA` are these clauses quoted; a consumer
#: reading an object gets the pointers and reads the quotations in the record.
BASIS_CLAUSES: dict[str, tuple[str, ...]] = {
    STATE_UNLABELLED: (
        "MISB ST 0102.12 §6.5",          # the absence does not signify unclassified
        "MISB ST 0102.12 §6.3",          # the contrast: unclassified is a MARKED state, 0x01
        "MISB ST 0601.14a §8.48",        # Required in LS? Optional, so the absence is conformant
    ),
    STATE_PARTIAL: (
        "MISB ST 0102.12 §6.4",          # a set missing Required elements is a legitimate set
        "MISB ST 0102.12 §6.5",          # an absent element inside a present set is unlabelled
        "MISB ST 0102.12 §6.7",          # the Required/Context/Optional column itself
    ),
    STATE_COMPLETE_ON_REQUIRED: (
        "MISB ST 0102.12 §6.7",
        "MISB ST 0102.12 §6.4",
    ),
}

#: §6.8's three conversion subsections, by the tag each one governs. `CONVERSION_BETWEEN_SET_FORMS`
#: is the section quoted; this is the per-element pointer that replaced it on the wire, and it is
#: STRICTLY MORE than the paragraph was — the paragraph was the same text under all three labels.
LABEL_CLAUSES: dict[int, str] = {
    1: "MISB ST 0102.12 §6.8.1",
    2: "MISB ST 0102.12 §6.8.2",
    12: "MISB ST 0102.12 §6.8.3",
}

#: The two clauses that state the Local Set's registered key, one per document. Their agreement is
#: the ground item 48's reading rests on and it is a POINTER PAIR, not a paragraph.
LOCAL_SET_KEY_CLAUSES: tuple[str, ...] = ("MISB ST 0102.12 §6.7", "MISB ST 0601.14a §8.48")


class RefusedElement(NamedTuple):
    """One element this layer declined to decode, with the clause that decided it.

    Carried as data rather than raised, for the reason `ELEMENT_REFUSAL_POLICY` states. Every
    field is here so the annotation a consumer reads names the octets rather than describing them.
    """

    tag: int
    name: str | None
    refusal_class: str
    observed_length: int
    stated_length: str | None
    presence: str | None
    octets: str
    tag_offset: int
    value_offset: int
    section: str | None
    clause: str


class DecodedElement(NamedTuple):
    """One element as this layer read it: the value, the octets, and where they were."""

    tag: int
    name: str
    length: int
    value: Any
    label: str | None
    raw: bytes
    tag_offset: int
    value_offset: int
    section: str
    presence: str


class DecodedSecuritySet(NamedTuple):
    """One ST 0102.12 Security Metadata Local Set, as carried inside ST 0601 item 48.

    `completeness` is §6.4's question answered rather than judged: which of the six `Required`
    elements arrived. `advisories` carries statements the document makes that this layer records
    and does not act on — `ST 0102.10-57`'s assumed version being the one that matters.
    """

    elements: dict[int, DecodedElement]
    order: tuple[int, ...]
    refusals: tuple[RefusedElement, ...]
    advisories: tuple[dict, ...]
    unlisted_tags: tuple[int, ...]
    raw_elements: dict[int, str]
    octets: bytes

    @property
    def required_present(self) -> tuple[int, ...]:
        return tuple(t for t in REQUIRED_TAGS if t in self.elements)

    @property
    def required_absent(self) -> tuple[int, ...]:
        return tuple(t for t in REQUIRED_TAGS if t not in self.elements)

    @property
    def is_partial(self) -> bool:
        """§6.4's shape: a set that does not carry every `Required` element."""
        return bool(self.required_absent)


def _decode_iso646(element: _Element, value: bytes) -> str:
    """`ISO/IEC 646 [18]` text, strictly. An octet at or above 0x80 is not an ISO 646 character."""
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise SecurityItemError(
            f"tag {element.tag} {element.name} declares Data Type "
            f"'{element.data_type}' — reference [18] is 'ISO/IEC 646:1991 ... ISO 7-bit coded "
            f"character set' — and its octets {value.hex()} carry a byte at or above 0x80 at "
            f"position {exc.start}. This layer will not reinterpret it under an encoding no held "
            "document names for this element"
        ) from exc


class ObjectCountryCodes(NamedTuple):
    """Tag 13, read. One reading, used by both the decoder and the adapter so neither re-derives.

    `text` is the whole element as one string — `-25`'s "one entry". `codes` is that string split
    on `-24`'s semi-colon. `byte_order` is `"big"` or `"little"`, and `bom` names which of the two
    signatures was found or is `None` where there was none.
    """

    text: str
    codes: tuple[str, ...]
    byte_order: str
    bom: str | None


#: The two signatures, as §3.2 gives them.
BOM_BIG = b"\xfe\xff"
BOM_LITTLE = b"\xff\xfe"


def read_object_country_codes(octets: bytes) -> ObjectCountryCodes:
    """Tag 13's Value octets to codes, under the composition `TAG_13_BYTE_ORDER_RULE` states.

    THE ORDER OF OPERATIONS IS THE RULE AND IS NOT INTERCHANGEABLE:

    1. **The octet count.** UTF-16 serialises 16-bit units as two octets each — RFC 2781 §3.1 —
       so an odd count cannot be a sequence of them and is refused before anything is decoded.
       This is a fact about the ENCODING and not about the Length cell, which reads `Variable` for
       this element and forbids no count at all.
    2. **The first two octets, read before any assumption.** §4.3's MUST. `0xFEFF` means
       big-endian, `0xFFFE` means little-endian, anything else means no BOM — and only in FIRST
       position, per §3.2.
    3. **The default.** No BOM means big-endian: §4.3's SHOULD, standing on `ST 0107.2-02`'s
       shall.
    4. **Strip the BOM if there was one.** §3.2's rationale — the signature is not part of the
       object. A `0xFEFF` at any other position is a zero-width non-breaking space and survives.
    5. **Decode strictly**, so RFC 2781 §2.2's two error cases surface as refusals instead of
       replacement characters.
    6. **Split on the semi-colon**, per `-24`, into what `-25` calls one entry's codes.

    **THE CODES ARE NOT VALIDATED**, and that is the standing coding-method ruling rather than a
    gap here: GEC, ISO 3166, STANAG 1059 and GENC are all external registers this repository does
    not hold, so a code is carried exactly as the packet spelled it. An empty code between two
    semi-colons is carried as an empty string for the same reason — the packet said it.
    """
    if len(octets) % 2:
        raise SecurityItemError(
            f"tag 13 Object Country Codes declares Data Type 'RFC 2781 [26] [27]' and carries "
            f"{len(octets)} octet(s): {octets.hex()}. UTF-16 serialises each 16-bit code unit as "
            "two octets — RFC 2781 §3.1 — so an odd count is not a sequence of code units and no "
            "byte order makes it one. This is a property of the ENCODING and not of the Length "
            "cell, which reads 'Variable' for this element"
        )
    body, order, bom = octets, "big", None
    if octets[:2] == BOM_BIG:
        body, order, bom = octets[2:], "big", "big_endian_0xFEFF"
    elif octets[:2] == BOM_LITTLE:
        body, order, bom = octets[2:], "little", "little_endian_0xFFFE"
    codec = "utf-16-be" if order == "big" else "utf-16-le"
    try:
        text = body.decode(codec)
    except UnicodeDecodeError as exc:
        raise SecurityItemError(
            f"tag 13 Object Country Codes carries {octets.hex()} and its 16-bit units are not a "
            f"well-formed UTF-16 sequence read as {order}-endian: {exc.reason} at octet "
            f"{exc.start}. RFC 2781 §2.2 steps 2 and 3 name both errors — a value between 0xD800 "
            "and 0xDBFF with no following value between 0xDC00 and 0xDFFF, or a sequence that "
            "ends on the first of such a pair — and say 'the sequence is in error'. §2.2 adds "
            "that error recovery is not specified by that document, so none is invented here"
        ) from exc
    return ObjectCountryCodes(text=text, codes=tuple(text.split(";")), byte_order=order, bom=bom)


def _utf16_refusal_class(observed_length: int) -> str:
    """Which of tag 13's two refusal grounds fired, from the octet count alone.

    The two are worth separating because the repairs are different and a consumer acts on them
    differently. **An odd count is a framing question**: something upstream truncated or padded a
    value, and no byte order and no error recovery can help. **A malformed sequence is a content
    question**: the count is right, the units are there, and one of them is a surrogate without
    its partner — which RFC 2781 §2.2 calls an error and declines to specify recovery for.
    """
    return REFUSAL_ODD_OCTET_COUNT if observed_length % 2 else REFUSAL_UTF16_SEQUENCE


def _decode_element(element: _Element, value: bytes) -> tuple[Any, str | None]:
    """One element's Value octets to (value, label). The label is None where none is stated."""
    if element.kind == "uint8_enum":
        if len(value) != 1:
            raise SecurityItemError(
                f"tag {element.tag} {element.name} declares Data Type 'uint8' and a Length of "
                f"'{element.length}' in §6.7's Table 2, and carries {len(value)} octet(s): "
                f"{value.hex()}"
            )
        integer = value[0]
        table = (SECURITY_CLASSIFICATION if element.tag == 1
                 else COUNTRY_CODING_METHOD if element.tag == 2
                 else OBJECT_COUNTRY_CODING_METHOD)
        return integer, table.get(integer)
    if element.kind == "uint16":
        if len(value) != 2:
            raise SecurityItemError(
                f"tag {element.tag} {element.name} declares Data Type 'uint16' and a Length of "
                f"'{element.length}' in §6.7's Table 2, and carries {len(value)} octet(s): "
                f"{value.hex()} — which cannot form a two-octet unsigned integer"
            )
        return int.from_bytes(value, "big"), None
    if element.kind == "utf16_country_codes":
        # Tag 13. WAS `carried_octets` until 2026-09-04, when RFC 2781 became a held document and
        # the byte order stopped being a guess: see DECODING_RULES and TAG_13_BYTE_ORDER_RULE.
        return read_object_country_codes(value).text, None
    return _decode_iso646(element, value), None


def _stated_length(element: _Element) -> int | None:
    """The Length cell as a number, or None where it reads 'Variable'."""
    return int(element.length) if element.length.isdigit() else None


def decode_set(value: bytes, *, base_offset: int = 0) -> DecodedSecuritySet:
    """One ST 0601 item 48 Value to its elements.

    `value` is the item's Value octets and NOTHING ELSE — no Universal Label and no outer BER
    length, because §8.48's bullet makes item 48's own length "the size of all MISB ST 0102
    metadata items to be packaged within item 48". The span is walked as a bare run of Local Set
    triplets with `klv_codec`'s BER-OID tag and BER length primitives, which is the framing layer
    doing the framing exactly as it does for the outer set.

    `base_offset` is where `value` began in the enclosing buffer, so a refusal's `tag_offset`
    points at an octet of the packet rather than of a slice — the arrangement
    `klv_codec.LocalSetItem` exists for.
    """
    elements: dict[int, DecodedElement] = {}
    order: list[int] = []
    refusals: list[RefusedElement] = []
    advisories: list[dict] = []
    unlisted: list[int] = []
    raw_elements: dict[int, str] = {}

    cursor = 0
    end = len(value)
    while cursor < end:
        tag_offset = cursor
        tag, cursor = framing.decode_ber_oid(value, cursor)
        length, cursor = framing.decode_ber_length(value, cursor)
        if cursor + length > end:
            raise SecurityItemError(
                f"the element with tag {tag} at offset {base_offset + tag_offset} declares a "
                f"{length}-octet Value, which runs {cursor + length - end} octet(s) past the end "
                f"of the ST 0102 Local Set carried in ST 0601 item 48. §8.48: 'The length field is "
                "the size of all MISB ST 0102 metadata items to be packaged within item 48' — so "
                "an element overrunning that span is a malformed set and not a malformed element"
            )
        raw = value[cursor:cursor + length]
        value_offset = cursor
        cursor += length
        order.append(tag)
        raw_elements[tag] = raw.hex()

        element = ELEMENTS.get(tag)
        if element is None:
            unlisted.append(tag)
            refusals.append(RefusedElement(
                tag=tag, name=None, refusal_class=UNLISTED_TAG, observed_length=length,
                stated_length=None, presence=None, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                section=None,
                clause=("§6.7's Table 2 draws rows for tags 1-14, 22, 23 and 24 and for no others. "
                        "The octets are carried and this layer declines to say what they mean. "
                        f"Tags 15-21 in particular: {ABSENT_TAGS_BASIS}")))
            continue

        stated = _stated_length(element)
        if stated is not None and length != stated:
            refusals.append(RefusedElement(
                tag=tag, name=element.name,
                refusal_class=(REFUSAL_FORMAT_CANNOT_CARRY
                               if element.kind in ("uint8_enum", "uint16")
                               else REFUSAL_STATED_LENGTH),
                observed_length=length, stated_length=element.length,
                presence=element.presence, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                section=f"ST 0102.12 §{element.section}",
                clause=(f"§6.7's Table 2 states a Length (Bytes) of '{element.length}' for tag "
                        f"{tag} {element.name}, Data Type '{element.data_type}', and this element "
                        f"carries {length}. {ELEMENT_REFUSAL_POLICY}")))
            continue

        try:
            decoded, label = _decode_element(element, raw)
        except SecurityItemError as exc:
            refusals.append(RefusedElement(
                tag=tag, name=element.name,
                refusal_class=(REFUSAL_NOT_ISO_646
                               if element.kind in ("iso646", "iso646_by_derivation")
                               else _utf16_refusal_class(length)
                               if element.kind == "utf16_country_codes"
                               else REFUSAL_FORMAT_CANNOT_CARRY),
                observed_length=length, stated_length=element.length,
                presence=element.presence, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                section=f"ST 0102.12 §{element.section}",
                clause=f"{exc}. {ELEMENT_REFUSAL_POLICY}"))
            continue

        if element.tag == 1 and label is None:
            advisories.append({
                "tag": 1, "name": element.name, "class": "classification_not_in_enumeration",
                "value": decoded, "section": "ST 0102.12 §6.1.1",
                "basis": (
                    "§6.7's Table 2 enumerates five values for Security Classification — "
                    "UNCLASSIFIED// (0x01) through TOP SECRET// (0x05) — and this element carries "
                    f"0x{decoded:02X}, which is none of them. THE INTEGER IS CARRIED AND NO LABEL "
                    "IS PRODUCED. A nearest match would be this adapter inventing a marking, "
                    "which the standing confidentiality ruling forbids: a classification is "
                    "carried and never invented"),
            })
        elif element.tag == 13:
            reading = read_object_country_codes(raw)
            if reading.byte_order == "little":
                advisories.append({
                    "tag": 13, "name": element.name,
                    "class": "byte_order_contradicts_st_0107_2_02",
                    "value": reading.text, "section": "ST 0102.12 §6.1.13",
                    "basis": (
                        "This element carries a little-endian byte-order mark, so RFC 2781 §4.3 "
                        "makes it little-endian text and it is decoded as such — that section's "
                        "MUST NOT is explicit that the serialization may not be assumed without "
                        "reading the first two octets. **AND `ST 0107.2-02` SAYS BYTE ORDER SHALL "
                        "BE BIG-ENDIAN**, retroactively across all MISB documents per ST 0107.3 "
                        "§1, so this packet meets RFC 2781 and breaks the MISB baseline. THE "
                        "VALUE IS CARRIED AND THE DISAGREEMENT IS RECORDED, on the `ST "
                        "0102.10-57` precedent at tag 22: refusing would discard a value the "
                        "packet carried because its PRODUCER broke a rule, and big-endian-decoding "
                        "it anyway would produce mojibake and call it a country code. " +
                        ST_0107_2_02),
                })
        elif element.tag in (2, 12) and label is None:
            advisories.append({
                "tag": element.tag, "name": element.name,
                "class": "coding_method_not_in_enumeration", "value": decoded,
                "section": f"ST 0102.12 §{element.section}",
                "basis": (
                    f"tag {element.tag}'s Allowed Values cell enumerates sixteen values and this "
                    f"element carries 0x{decoded:02X}, which is not among them. The integer is "
                    "carried without a label. " + THE_TWO_COUNTRY_CODING_ENUMERATIONS_DIFFER),
            })

        elements[tag] = DecodedElement(
            tag=tag, name=element.name, length=length, value=decoded, label=label, raw=raw,
            tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
            section=f"ST 0102.12 §{element.section}", presence=element.presence)

    if 22 not in elements and 22 not in {r.tag for r in refusals}:
        advisories.append({
            "tag": 22, "name": ELEMENTS[22].name, "class": "version_absent",
            "value": None, "section": "ST 0102.12 §6.1.15",
            "basis": (
                "`ST 0102.10-57`: 'When the Security Metadata Version is not found in the "
                "Security Metadata, version three (3) shall be assumed.' RECORDED AND NOT "
                "APPLIED: the assumed version is not written into the decoded elements, because "
                "the packet did not carry it and this record keeps what a packet stated apart "
                "from what a clause would let a reader assume. A consumer holding this advisory "
                "can apply -57 themselves and can see that they did"),
        })

    return DecodedSecuritySet(
        elements=elements, order=tuple(order), refusals=tuple(refusals),
        advisories=tuple(advisories), unlisted_tags=tuple(unlisted), raw_elements=raw_elements,
        octets=bytes(value))


def encode_set(raw_elements: dict[int, bytes], order: tuple[int, ...]) -> bytes:
    """The elements back to one item 48 Value, byte-exactly, from parked octets.

    Takes OCTETS and never values, for `stanag4609.from_cdm`'s reason: re-encoding a decoded value
    would silently repair a refused element and would make egress non-byte-exact for exactly the
    input where fidelity matters most. Nothing here re-encodes a marking.
    """
    out = bytearray()
    for tag in order:
        if tag not in raw_elements:
            raise SecurityItemError(
                f"tag {tag} is listed in the set's element order and no octets were parked for it"
            )
        octets = raw_elements[tag]
        out += framing.encode_ber_oid(tag) + framing.encode_ber_length(len(octets)) + octets
    return bytes(out)
