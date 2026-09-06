"""The MISB ST 0806.4 Remote Video Terminal LOCAL SET item layer: four element tables and their maps.

WHAT THIS MODULE IS, AND WHY IT IS ITS OWN MODULE
--------------------------------------------------
`klv_codec` is the framing layer and is deliberately **tag-blind**; `klv_uas_codec` is the ITEM
layer for MISB ST 0601.14a; `klv_security_codec` is the same layer for MISB ST 0102.12 and states
the arrangement — one item layer per document. This module is that layer for a third document,
MISB ST 0806.4, and it is its own module for `klv_security_codec`'s three reasons, of which the
second is again decisive.

1. **One item layer per document.** This module cites ST 0806.4 by SHA-256 at module scope, so a
   reader asking "which copy is this read from" gets one answer.
2. **THE TAG NUMBERS COLLIDE — AND THEY COLLIDE FOUR WAYS INSIDE THIS DOCUMENT ALONE.** In
   ST 0601.14a tag 2 is the Precision Time Stamp, tag 3 is Mission ID and tag 13 is Sensor
   Latitude; in ST 0102.12 tag 3 is Classifying Country and tag 13 is Object Country Codes. In
   ST 0806.4 tag 3 is Platform True Airspeed and tag 13 is the Area of Interest LS. **And this
   document draws FOUR tables, not one**: Table 8-1's tag 2 is a timestamp, Table 8-2's tag 2 is
   POI Latitude, Table 8-3's tag 2 is Corner Latitude Point 1, and Table 8-4's tag 2 is User Data.
   So the integer alone never decides the meaning here — the SET decides it, and that is why every
   table below is separate and why `decode_set` is always told which one it is walking. A single
   `dict[int, ...]` for this document would be wrong four times over before any other document was
   considered.
3. **The value maps have nothing in common with the other two.** ST 0102's are an enumeration
   lookup, an ISO 646 string and a uint16. ST 0806.4's are unsigned integers at four widths, two
   affine degree maps, an affine altitude map, a signed octet the document never enumerates, ISO-7
   strings at four stated widths, and one bit-field. `klv_uas_codec._Item` has twenty-seven fields,
   of which ST 0806.4 states none.

WHY THIS DOCUMENT'S ITEMS ARE READ AT ALL, WHEN MOST ST 0601 ITEMS ARE NOT
--------------------------------------------------------------------------
`klv_uas_codec`'s scope contract is that an item this repository has never met on a wire "is an
item whose decoder could only ever be checked against a fixture written from the same reading of
the same table". The pinned stream carries no item 73 — `WITNESSED_TAGS` stops at 65 — so the
contract's premise applies and crossing it needs a ground. **The ground is the SECOND-DOCUMENT
ground, item 48's exactly, reached for a second time:**

* ST 0601.14a §8.73 prints ``KLV Key 06.0E.2B.34.02.0B.01.01.0E.01.03.01.02.00.00.00 (CRC 17945)``;
* ST 0806.4 requirement `ST 0806.4-06` states "The 16-byte Universal Key for the RVT Local Set
  shall be 06.0E.2B.34.02.0B.01.01.0E.01.03.01.02.00.00.00  (CRC 17945)", and Table 8-1's own
  header row repeats the same sixteen octets and the same CRC in spaced form.

Two documents, obtained on different days by different routes, state the same sixteen octets and
the same CRC.

**THIS IS THE SENTENCE THIS MODULE FALSIFIES, AND IT IS CORRECTED WHERE IT IS STATED RATHER THAN
HERE.** `klv_uas_codec.NESTED_SETS` and `klv_security_codec`'s module docstring both read "No
unwitnessed ST 0601 item has a second document behind it", which was true on 2026-09-04 and stopped
being true on 2026-09-06 when ST 0806.4 was pinned. Each site carries a dated correction beside the
claim; neither was edited in place, on the append-only rule.

**AND THE AGREEMENT HERE IS WIDER THAN ITEM 48's.** Item 48's two documents agree about ONE key.
These two agree about one key, and then ST 0806.4 states the three SUBORDINATE set keys three times
each, internally — see `TRANSCRIPTION_CROSS_CHECK`.

WHAT IS ON THE WIRE INSIDE ITEM 73, WHICH IS NOT A PACKET
----------------------------------------------------------
ST 0601.14a §8.73's two bullets: "Use the MISB ST 0806 Local Set within the MISB ST 0601 Tag 73"
and "The length field is the size of all RVT LS metadata items to be packaged within Tag 73". That
is item 48's shape and item 74's: item 73's Value is a **bare run of Local Set triplets** — no
16-byte Universal Label and no second BER length wrapper — so this module walks the span itself
with `klv_codec`'s BER-OID and BER length primitives rather than calling `walk_local_set`, whose
first act is to read a key. The registered keys below are each set's IDENTITY and are not octets a
conforming item 73 carries; they are recorded for that reason and never matched against a buffer.

**THE SAME IS TRUE ONE LAYER DOWN, AND THE DOCUMENT SAYS SO IN ITS OWN COLUMNS.** RVT tags 11, 12
and 13 carry the three subordinate sets, and each of their Notes cells ends "The length field is
the size of all <X> items to be packaged within this tag". So a subordinate set's Value is a bare
run of triplets too, and `decode_set` recurses with the subordinate table rather than the RVT one.

WHAT THE DOCUMENT REQUIRES AND WHAT THIS LAYER DOES ABOUT IT
-------------------------------------------------------------
`ST 0806.4-01` through `-04` make the Precision Time Stamp first and the checksum last in an
**independent** RVT Local Set. **NONE OF THE FOUR IS ENFORCED HERE AND THE REASON IS THE CARRIER.**
An RVT LS nested inside ST 0601 item 73 is not an independent RVT Local Set: §5 says the set "can
stand as an independent local set, or be embedded within other metadata sets", and §8.73.1 says
item 73 exists so users "leverage the data field contained within MISB ST 0601 (i.e. platform
location, and sensor pointing angles)" — an embedded set draws its time and its integrity from the
ST 0601 packet that carries it, which already has both. So this layer records the four requirements
at `INDEPENDENT_SET_REQUIREMENTS`, reports which of them the octets happen to satisfy, and refuses
nothing on their account. A set that would be non-conforming standing alone is carried, annotated,
and left for a consumer to judge — `klv_security_codec.ELEMENT_REFUSAL_POLICY`'s reasoning, applied
to a requirement about ORDER rather than about length.

THE CONFIDENTIALITY RULING REACHED A THIRD TIME, AND A NEW PLACE FOR IT
-----------------------------------------------------------------------
`klv_security_codec` states it for classifications: a marking is CARRIED AND NEVER INVENTED. This
document reaches the same wall from a different direction. **POI/AOI Type — POI tag 5, AOI tag 6 —
is `int8` with an EMPTY Notes cell, and the document enumerates no value for it anywhere in its
thirteen pages**, while `ST 0806.4-18` makes it REQUIRED in every AOI. So a conforming AOI must
carry a value its own standard never defines. The integer is carried, no label is produced, and
`POI_AOI_TYPE_IS_UNENUMERATED` states the finding rather than leaving a reader to notice that one
field is quietly label-less.

WHY `check_against_the_documents_own_examples` HAS NO TWIN HERE
---------------------------------------------------------------
`klv_uas_codec` runs its decoder over 26 worked examples because ST 0601.14a prints one per item;
`klv_vmti_codec` runs 70 because ST 0903.4 prints them. **ST 0806.4 prints none.** Its one
illustration of a packet is Figure 7-1 at §7.3.4, "an example RVT LS packet containing two Point of
Interest local sets" — and it is a RASTER IMAGE. Page 5 of the pinned copy carries
`/XObject<</Image73 73 0 R>>` and its text layer yields the caption and nothing else, so the figure
prints no octet this layer could read. ST 0601.14a's own §8.73 Example KLV Item row reads
``49 - N/A``, which is the same answer §8.48's row gives for item 48. So the strongest check
available to `klv_uas_codec` is **not available here and is not simulated**; what stands in its
place is `TRANSCRIPTION_CROSS_CHECK`, which is weaker, and saying which is the point.

TWO DEFECTS IN THE DOCUMENT, RECORDED AND NOT REPAIRED
-------------------------------------------------------
Both are transcribed verbatim into the tables below and neither changes a map. They are stated at
`DOCUMENT_DEFECTS` in the shape round B's erratum note uses, because a transcription that silently
smooths its source is a transcription nobody can check.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from synapse_cdm.adapters import klv_codec as framing

#: The pinned copy every citation in this module is read from. Stated here as well as in
#: `klv_pin.json` because a module that cites sections without naming the copy is citing a memory.
SOURCE_ST_0806_4 = (
    "MISB ST 0806.4, SHA-256 "
    "58de4265d377d88b922df111aab49e52209fe4a4d54870aba53b310ad6e01037, "
    "fixtures/klv/spec/ST0806.4.pdf"
)

#: `ST 0806.4-06` and Table 8-1's header row. **Recorded as the set's identity and never matched
#: against a buffer** — inside ST 0601 item 73 the key is not on the wire, because §8.73's own
#: bullet makes the item's length "the size of all RVT LS metadata items". ST 0601.14a §8.73 prints
#: the same sixteen octets and the same CRC, which is the two-document agreement this module's
#: scope ruling rests on.
LOCAL_SET_KEY = bytes.fromhex("060E2B34020B01010E01030102000000")
LOCAL_SET_KEY_CRC = 17945

#: `ST 0806.4-07`, RVT Table 8-1's tag 12 row, and Table 8-2's header row — the same sixteen octets
#: and CRC in three places. Never matched against a buffer, for `LOCAL_SET_KEY`'s reason.
POI_LOCAL_SET_KEY = bytes.fromhex("060E2B34020B01010E0103010C000000")
POI_LOCAL_SET_KEY_CRC = 58435

#: `ST 0806.4-12`, RVT Table 8-1's tag 13 row, and Table 8-3's header row.
AOI_LOCAL_SET_KEY = bytes.fromhex("060E2B34020B01010E0103010D000000")
AOI_LOCAL_SET_KEY_CRC = 37623

#: `ST 0806.4-20`, RVT Table 8-1's tag 11 row, and Table 8-4's header row.
USER_DEFINED_LOCAL_SET_KEY = bytes.fromhex("060E2B34020B01010E0103010F000000")
USER_DEFINED_LOCAL_SET_KEY_CRC = 32671


class RvtError(ValueError):
    """A value this module refuses to decode, with the clause that decides it."""


# ------------------------------------------------------------------- the element tables


class _Element(NamedTuple):
    """One row of a §8 table, in THE DOCUMENT'S OWN COLUMNS, plus this module's decoding rule.

    The six fields `tag`, `key_hex`, `key_crc`, `name`, `units`, `data_format` and `length` are the
    columns Tables 8-1 through 8-4 draw — "RVT LS Tag ID", "Key Value (hex)" with its parenthesised
    CRC, "Key Name", "Units", "Format" and "Length in Bytes" — transcribed cell by cell, and
    `notes` is the Notes cell in full. `requirements` are the `ST 0806.4-nn` requirement IDs that
    name this element in §7.

    `kind` is the only field that is not transcribed: it is this module's classification of the
    Format cell into a decoding rule, and each value's ground is at `DECODING_RULES`.
    """

    tag: int
    key_hex: str
    key_crc: int
    name: str
    units: str
    data_format: str
    length: str
    notes: str
    requirements: tuple[str, ...]
    kind: str


#: How each `Format` cell becomes a decoding rule, and the ground for each.
DECODING_RULES = {
    "uint": (
        "the Format cell reads `uint8`, `uint16`, `uint24`, `uint32` or `uint64` and the Length "
        "cell states the matching octet count. Decoded big-endian, which is `ST 0806.4-05`'s "
        "delegation to MISB ST 0107 — 'All metadata shall be expressed in accordance with MISB ST "
        "0107' — the document park 4 closed on. **uint24 is the width no other document in this "
        "repository uses**, and it is three octets exactly as the Length cell says; it is decoded "
        "as an unsigned big-endian integer of three octets and not widened to four"),
    "int8_unenumerated": (
        "TAGS POI-5 AND AOI-6 ONLY. The Format cell reads `int8`, the Length cell reads 1, and the "
        "Notes cell is EMPTY — the document defines no value for this element anywhere. Decoded as "
        "one two's-complement octet and carried WITHOUT a label, because a nearest match would be "
        "this layer inventing a meaning for a field its own standard never gave one. See "
        "`POI_AOI_TYPE_IS_UNENUMERATED`"),
    "iso7": (
        "the Format cell reads `String ISO-7`. Decoded as strict 7-bit ASCII: an octet at or above "
        "0x80 is not an ISO-7 character and is refused as an element rather than reinterpreted "
        "under some other encoding — `klv_security_codec._decode_iso646`'s ruling, reached by a "
        "third document. The Length cell is a MAXIMUM (`Max. 127`, `Max. 255`, `Max. 2048`) for "
        "five of the seven and an EXACT width (3, 16) for the other two; only an exact width is "
        "enforced, and `_stated_length` is where that distinction lives"),
    "latitude": (
        "TAGS POI-2, AOI-2 AND AOI-4. The Notes cell states the map in the document's own words: "
        "'Map -(2^31-1)..(2^31-1) to +/- 90. Use -(2^31) as an \"error\" indicator. -(2^31) = "
        "0x80000000. Resolution: ~42 nano degrees.' Decoded as a signed 32-bit integer scaled by "
        "90/(2^31-1); the error indicator yields NO value and a signal, on "
        "`klv_uas_codec`'s special-values precedent — a signal is not a measurement"),
    "longitude": (
        "TAGS POI-3, AOI-3 AND AOI-5. The same map at 180: 'Map -(2^31-1)..(2^31-1) to +/- 180. "
        "Use -(2^31) as an \"error\" indicator.' Decoded as a signed 32-bit integer scaled by "
        "180/(2^31-1), with the same signal"),
    "poi_altitude": (
        "TAG POI-4 ONLY. The Notes cell: 'Altitude of POI as measured from Mean Sea Level (MSL). "
        "Map 0..(2^16-1) to -900..19000 meters.' An UNSIGNED affine map with a negative offset, "
        "and the document names its datum — MSL, which is NOT the WGS84 ellipsoid the two degree "
        "maps cite. The datum is carried in the reading rather than converted, because converting "
        "MSL to HAE needs a geoid model no held document supplies"),
    "numeric_id_bitfield": (
        "TAG USERDEF-1 ONLY. The Notes cell states the layout: 'Bit ordering MSB first: 87654321 "
        "Bits 8 & 7 set the data type: = 00 for strings = 01 for INT = 10 for UINT = 11 for "
        "Experimental. Bits 1 to 6 are the integer numeric ID for the user defined data ranging "
        "from 0 to 63'. Decoded into its two fields; the data type's four values are the four the "
        "cell prints and no fifth is possible in two bits"),
    "opaque": (
        "TAG USERDEF-2 ONLY. Format `N/A`, Length `V`, and the Notes cell says the type is "
        "'defined in byte 1 of this packet with variant (uint16, uint32, etc.) extracted from the "
        "overall pack length'. **THE OCTETS ARE CARRIED AS HEX AND NOTHING IS DECODED**: §7.3.3 "
        "says 'The content of the User Defined LS will be determined out of field', so the meaning "
        "is by definition not in any document this repository can hold"),
    "nested_set": (
        "RVT TAGS 11, 12 AND 13. Format `N/A`, Length `V`, and each Notes cell ends 'The length "
        "field is the size of all <X> items to be packaged within this tag' — ST 0601.14a §8.73's "
        "shape one layer down. The Value is a bare run of triplets and `decode_set` recurses with "
        "the subordinate table `SUBORDINATE_SETS` names"),
}


#: **A FIELD THE DOCUMENT REQUIRES AND NEVER DEFINES.** POI Table 8-2's tag 5 and AOI Table 8-3's
#: tag 6 are one element — the same sixteen octets, `06 0E 2B 34 01 01 01 01 0E 01 01 03 1A 00 00
#: 00 (CRC 4124)`, the same name and the same `int8` Format. POI's Notes cell is empty; AOI's reads
#: only "** REQUIRED when sending an AOI **". No section of ST 0806.4 enumerates a value, and
#: `ST 0806.4-18` nonetheless makes the element mandatory in every AOI. So the integer is carried
#: and no label is produced, on the standing confidentiality ruling's reasoning applied to a
#: non-confidentiality field: a value a document does not define is not a value this layer may name.
POI_AOI_TYPE_IS_UNENUMERATED = (
    "ST 0806.4 Table 8-2 tag 5 and Table 8-3 tag 6, POI/AOI Type, CRC 4124: Format `int8`, Length "
    "1, and NO enumeration anywhere in the document's thirteen pages. ST 0806.4-18 makes it "
    "REQUIRED in every AOI, so a conforming AOI carries a value its own standard never defines. "
    "The integer is carried without a label and this layer declines to guess one"
)


#: Defects in the pinned document, transcribed rather than repaired. Neither changes a map.
DOCUMENT_DEFECTS: tuple[dict[str, str], ...] = (
    {
        "where": "Table 8-1, tag 8 UAS LS Version Number, Notes cell",
        "quotation": (
            "Version number of the LS document used to generate a source of LS KLV metadata.  0 is "
            "pre-release, initial release (0806.0), or test data.  1..255 corresponds to document "
            "revisions 1 thru 255.  This version is represented by 0d02."),
        "contradiction": (
            "the cell's own rule maps revision N to value N, and the document IS revision 4 — its "
            "cover, the running footer of all thirteen pages and the single Revision History row "
            "all read `ST 0806.4`. Under its own rule this version is 0d04. The cell is ST 0806.2's "
            "and was carried forward unchanged"),
        "what_this_layer_does": (
            "nothing. Tag 8 is decoded as the uint8 its Format cell states and the integer is "
            "carried. This layer holds no expected value for it and refuses nothing on its account"),
    },
    {
        "where": "Table 8-1, tag 7 Frame Code, Notes cell",
        "quotation": "Range is from 0 to 4,294,967,296.  Counter runs at 60 Hz",
        "contradiction": (
            "4,294,967,296 is 2^32 and the Format cell reads `uint32`, whose largest value is "
            "4,294,967,295. The stated range names one value the stated format cannot carry — the "
            "off-by-one class round B's erratum note collected and round H1 met again in ST "
            "0903.4's VMask octets"),
        "what_this_layer_does": (
            "nothing. The Format cell governs, on the ruling that a table is normative where a "
            "prose range is descriptive; a four-octet Value decodes to 0..4294967295 and no "
            "advisory is raised, because no conforming octet can reach the disputed value"),
    },
)


#: `ST 0806.4-01` through `-04`, verbatim, and the reason this layer records them without enforcing
#: them. See the module docstring's "WHAT THE DOCUMENT REQUIRES" section.
INDEPENDENT_SET_REQUIREMENTS: dict[str, str] = {
    "ST 0806.4-01": ("Each independent RVT Local Set shall contain a Precision Time Stamp in "
                     "accordance with MISB ST 0603 ."),
    "ST 0806.4-02": "The Precision Time Stamp shall be the first element in the Local Set.",
    "ST 0806.4-03": ("Each independent RVT Local Set shall contain a checksum in accordance with "
                     "ISO/IEC 13818-1 ."),
    "ST 0806.4-04": "The Local Set checksum shall be the last element in the Local Set.",
}

#: Why the four above are reported and never enforced, stated once as data.
EMBEDDED_SET_POLICY = (
    "ST 0806.4-01 through -04 govern an INDEPENDENT RVT Local Set. An RVT LS carried in ST 0601 "
    "item 73 is not one: §5 says the set 'can stand as an independent local set, or be embedded "
    "within other metadata sets', and ST 0601.14a §8.73.1 says item 73 exists so users can "
    "'leverage the data field contained within MISB ST 0601 (i.e. platform location, and sensor "
    "pointing angles)'. An embedded set draws its time and its integrity from the ST 0601 packet, "
    "which carries both. So this layer REPORTS which of the four the octets satisfy and refuses "
    "nothing on their account"
)


#: **Table 8-1: RVT Local Set**, all twenty-one rows, transcribed cell by cell from the pinned copy.
#: The header row's key is `LOCAL_SET_KEY` above and is the set's identity rather than a member.
ELEMENTS: dict[int, _Element] = {
    1: _Element(
        tag=1, key_hex="06 0E 2B 34 01 01 01 01 0E 01 02 03 10 00 00 00", key_crc=46679,
        name="CRC 32", units="None", data_format="uint32", length="4",
        notes=("Performed on entire LS packet, including 16-byte US key.  Note: This is Not the "
               "same Checksum as is used in STANDARD 0601.  See the Appendix. This checksum must "
               "appear as that last item in an RVT LS pack when used."),
        requirements=("ST 0806.4-03", "ST 0806.4-04"), kind="uint"),
    2: _Element(
        tag=2, key_hex="06 0E 2B 34 01 01 01 03 07 02 01 01 01 05 00 00", key_crc=64827,
        name="User Defined Time Stamp -Microseconds Since 1970", units="Micro-seconds",
        data_format="uint64", length="8",
        notes=("Represents the Coordinated Universal Time (UTC) in Microseconds elapsed since "
               "midnight (00:00:00), January 1, 1970 (the UNIX Epoch).  Defined as the Precision "
               "Time Stamp in MISB ST 0603 . Resolution: 1 microsecond. Note: This timestamp must "
               "appear as the first item in an RVT LS pack when used."),
        requirements=("ST 0806.4-01", "ST 0806.4-02"), kind="uint"),
    3: _Element(
        tag=3, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 01 0A 01 00 00", key_crc=30728,
        name="Platform True Airspeed", units="Meters / Second", data_format="uint16", length="2",
        notes=("True airspeed (TAS) of platform. Indicated Airspeed adjusted for temperature and "
               "altitude. 1 m/s = 1.94384449 knots.  Resolution: 1 meter/second."),
        requirements=(), kind="uint"),
    4: _Element(
        tag=4, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 01 0B 01 00 00", key_crc=3772,
        name="Platform Indicated Airspeed", units="Meters / Second", data_format="uint16",
        length="2",
        notes=("Indicated airspeed (IAS) of platform. Derived from Pilot tube and static pressure "
               "sensors. 1 m/s = 1.94384449 knots.  Resolution: 1 meter/second."),
        requirements=(), kind="uint"),
    5: _Element(
        tag=5, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 14 00 00 00", key_crc=45638,
        name="Telemetry Accuracy Indicator", units="None", data_format="uint8", length="1",
        notes="Reserved for future use", requirements=(), kind="uint"),
    6: _Element(
        tag=6, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 15 00 00 00", key_crc=50418,
        name="Frag Circle Radius", units="Meters", data_format="uint16", length="2",
        notes=("Size of fragmentation circle selected by the aircrew.  Resolution: 1 meter"),
        requirements=(), kind="uint"),
    7: _Element(
        tag=7, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 09 00 00 00", key_crc=36967,
        name="Frame Code", units="None", data_format="uint32", length="4",
        notes="Range is from 0 to 4,294,967,296.  Counter runs at 60 Hz",
        requirements=(), kind="uint"),
    8: _Element(
        tag=8, key_hex="06 0E 2B 34 01 01 01 01 0E 01 02 03 03 00 00 00", key_crc=13868,
        name="UAS LS Version Number", units="Number", data_format="uint8", length="1",
        notes=("Version number of the LS document used to generate a source of LS KLV metadata.  "
               "0 is pre-release, initial release (0806.0), or test data.  1..255 corresponds to "
               "document revisions 1 thru 255.  This version is represented by 0d02."),
        requirements=(), kind="uint"),
    9: _Element(
        tag=9, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 01 19 00 00 00", key_crc=53059,
        name="Video Data rate", units="bps or Hz", data_format="uint32", length="4",
        notes="Video data rate (Digital only), or Analog FM", requirements=(), kind="uint"),
    10: _Element(
        tag=10, key_hex="06 0E 2B 34 01 01 01 03 04 01 0B 01 00 00 00 00", key_crc=63114,
        name="Digital Video File Format", units="String ISO-7", data_format="String ISO-7",
        length="Max.  127",
        notes=("Video Compression being used.  Maximum 127 characters. Examples: MPEG2, MPEG4, "
               "H.264, Analog FM (non-compressed) As this list is not exhaustive, other values or "
               "variants are also acceptable."),
        requirements=(), kind="iso7"),
    11: _Element(
        tag=11, key_hex="06 0E 2B 34 02 0B 01 01 0E 01 03 01 0F 00 00 00", key_crc=32671,
        name="User Defined LS", units="Varies", data_format="N/A", length="V",
        notes=("Local set key to include User Defined data items within the RVT KLV Dictionary.  "
               "Use the values of the items specified within the User Defined Data Packet.  The "
               "length field is the size of all items to be packaged within this tag."),
        requirements=("ST 0806.4-20",), kind="nested_set"),
    12: _Element(
        tag=12, key_hex="06 0E 2B 34 02 0B 01 01 0E 01 03 01 0C 00 00 00", key_crc=58435,
        name="Point of Interest LS", units="None", data_format="N/A", length="V",
        notes=("Local set key to include POI items within RVT KLV Dictionary.  Use POI local set "
               "tags within a POI packet.  The length field is the size of all POI items to be "
               "packaged within this tag."),
        requirements=("ST 0806.4-07", "ST 0806.4-25"), kind="nested_set"),
    13: _Element(
        tag=13, key_hex="06 0E 2B 34 02 0B 01 01 0E 01 03 01 0D 00 00 00", key_crc=37623,
        name="Area of Interest LS", units="None", data_format="N/A", length="V",
        notes=("Local set key to include AOI items within RVT KLV Dictionary.  Use AOI local set "
               "tags within an AOI packet.  The length field is the size of all AOI items to be "
               "packaged within this tag."),
        requirements=("ST 0806.4-12", "ST 0806.4-25"), kind="nested_set"),
    14: _Element(
        tag=14, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0A 00 00 00", key_crc=3003,
        name="MGRS Zone", units="None", data_format="uint8", length="1",
        notes=("AIRCRAFT: First two characters of Aircraft MGRS coordinates, UTM zone 01 through "
               "60"),
        requirements=(), kind="uint"),
    15: _Element(
        tag=15, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0B 00 00 00", key_crc=32015,
        name="MGRS Latitude Band  and Grid Square", units="String ISO-7",
        data_format="String ISO-7", length="3",
        notes=("AIRCRAFT: Third, fourth and fifth characters of Aircraft MGRS coordinates.  Third "
               "character is the alpha code for the latitude band (A through Z, omitting I and "
               "O).  Fourth and fifth characters are the 2-digit alpha code for the grid square "
               "designator (WGS 84).  Note that latitude bands A & B correspond to Antarctic UPS "
               "regions and Y & Z correspond to Artic UPS regions."),
        requirements=(), kind="iso7"),
    16: _Element(
        tag=16, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0C 00 00 00", key_crc=11298,
        name="MGRS Easting", units="Meters", data_format="uint24", length="3",
        notes=("AIRCRAFT: Sixth through tenth character of Aircraft MGRS coordinates. Range is "
               "from 0 to 99,999 representing the 5-digit Easting value in meters. Resolution: 1 "
               "meter"),
        requirements=(), kind="uint"),
    17: _Element(
        tag=17, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0D 00 00 00", key_crc=23190,
        name="MGRS Northing", units="Meters", data_format="uint24", length="3",
        notes=("AIRCRAFT: Eleventh through fifteenth character of Aircraft MGRS coordinates.  "
               "Range is from 0 to 99,999 representing the 5-digit Northing value in meters. "
               "Resolution: 1 meter"),
        requirements=(), kind="uint"),
    18: _Element(
        tag=18, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0A 01 00 00", key_crc=15499,
        name="MGRS Zone Second Value", units="None", data_format="uint8", length="1",
        notes=("FRAME CENTER: First two characters of Frame Center MGRS coordinates, UTM zone 01 "
               "through 60"),
        requirements=(), kind="uint"),
    19: _Element(
        tag=19, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0B 01 00 00", key_crc=19007,
        name="MGRS Latitude Band  and Grid Square  Second Value", units="String ISO-7",
        data_format="String ISO-7", length="3",
        notes=("FRAME CENTER: Third, fourth and fifth characters of Frame Center MGRS "
               "coordinates. Third character is the alpha code for the latitude band (for UTM: C "
               "through X, omitting I and O; for UPS: A, B, Y or Z).  Fourth and fifth characters "
               "are the 2-digit alpha code for the grid square designator (WGS 84)."),
        requirements=(), kind="iso7"),
    20: _Element(
        tag=20, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0C 01 00 00", key_crc=6930,
        name="MGRS Easting Second Value", units="Meters", data_format="uint24", length="3",
        notes=("FRAME CENTER: Sixth through tenth character of Frame Center MGRS coordinates.  "
               "Range is from 0 to 99,999 representing the 5-digit Easting value in meters.  "
               "Resolution: 1 meter"),
        requirements=(), kind="uint"),
    21: _Element(
        tag=21, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 0D 01 00 00", key_crc=28070,
        name="MGRS Northing  Second Value", units="Meters", data_format="uint24", length="3",
        notes=("FRAME CENTER: Eleventh through fifteenth character of Frame Center MGRS "
               "coordinates.  Range is from 0 to 99,999 representing the 5-digit Northing value "
               "in meters. Resolution: 1 meter"),
        requirements=(), kind="uint"),
}


#: **Table 8-2: Point of Interest (POI) Local Set**, all ten rows. Tags 1, 2 and 3 are mandatory by
#: `ST 0806.4-08`, `-09` and `-10`; `ST 0806.4-11` makes "POI items with Tag ID 4 through Tag ID 10
#: ... optional", which is the cross-check that fixes this table at exactly ten rows.
POI_ELEMENTS: dict[int, _Element] = {
    1: _Element(
        tag=1, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 16 00 00 00", key_crc=24366,
        name="POI/AOI Number", units="Number", data_format="uint16", length="2",
        notes="POI Number ** REQUIRED when sending a POI **",
        requirements=("ST 0806.4-08",), kind="uint"),
    2: _Element(
        tag=2, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 17 00 00 00", key_crc=10650,
        name="POI Latitude", units="Degrees", data_format="int32", length="4",
        notes=("POI Latitude.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 90. Use "
               "-(2^31) as an \"error\" indicator. -(2^31) = 0x80000000.  Resolution: ~42 nano "
               "degrees. ** REQUIRED when sending a POI **"),
        requirements=("ST 0806.4-09",), kind="latitude"),
    3: _Element(
        tag=3, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 18 00 00 00", key_crc=64884,
        name="POI Longitude", units="Degrees", data_format="int32", length="4",
        notes=("POI Longitude.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 180. Use "
               "-(2^31) as an \"error\" indicator. -(2^31) = 0x80000000.  Resolution: ~84 nano "
               "degrees. ** REQUIRED when sending a POI **"),
        requirements=("ST 0806.4-10",), kind="longitude"),
    4: _Element(
        tag=4, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 19 00 00 00", key_crc=35776,
        name="POI Altitude", units="Meters", data_format="uint16", length="2",
        notes=("Altitude of POI as measured from Mean Sea Level (MSL). Map 0..(2^16-1) to "
               "-900..19000 meters. 1 meter = 3.2808399 feet. Resolution: ~0.3 meters."),
        requirements=(), kind="poi_altitude"),
    5: _Element(
        tag=5, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1A 00 00 00", key_crc=4124,
        name="POI/AOI Type", units="None", data_format="int8", length="1",
        notes="", requirements=(), kind="int8_unenumerated"),
    6: _Element(
        tag=6, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1B 00 00 00", key_crc=26280,
        name="POI/AOI Text", units="String ISO-7", data_format="String ISO-7", length="Max. 2048",
        notes="User Defined String", requirements=(), kind="iso7"),
    7: _Element(
        tag=7, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1C 00 00 00", key_crc=14213,
        name="POI Source Icon", units="String ISO-7", data_format="String ISO-7",
        length="Max. 127",
        notes="Per MIL-STD-2525B.  Maximum 127 characters. Icon used in FalconView",
        requirements=(), kind="iso7"),
    8: _Element(
        tag=8, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1D 00 00 00", key_crc=16689,
        name="POI/AOI Source ID", units="String ISO-7", data_format="String ISO-7",
        length="Max. 255", notes="User Defined String", requirements=(), kind="iso7"),
    9: _Element(
        tag=9, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1E 00 00 00", key_crc=56045,
        name="POI/AOI Label", units="String ISO-7", data_format="String ISO-7", length="16",
        notes="User Defined String", requirements=(), kind="iso7"),
    10: _Element(
        tag=10, key_hex="06 0E 2B 34 01 01 01 01 0E 01 04 03 01 00 00 00", key_crc=22181,
        name="Operation ID", units="String ISO-7", data_format="String ISO-7", length="Max. 127",
        notes=("Operation ID is the identifier for the duration of the supporting mission or "
               "event associated with the Point of Interest; this is not the platform mission "
               "designation"),
        requirements=(), kind="iso7"),
}


#: **Table 8-3: Area of Interest (AOI) Local Set**, all ten rows. Tags 1 through 6 are mandatory by
#: `ST 0806.4-13` through `-18`; `ST 0806.4-19` makes "AOI items with Tag ID 7 through Tag ID 10
#: ... optional", which fixes this table at exactly ten rows.
#:
#: **THE FOUR CORNER ELEMENTS CARRY THE DOCUMENT'S OWN FOOTNOTES**, which are the only footnotes in
#: ST 0806.4 and are transcribed into the Notes cells below because they are what makes the
#: numbering readable: "1 Corner Latitude Point 1 is the same as the Upper Left Latitude", "2
#: Corner Longitude Point 1 is the same as the Upper Left Longitude", "3 Corner Latitude Point 3 is
#: the same as the Lower Right Latitude", "4 Corner Longitude Point 3 is the same as the Lower
#: Right Longitude". So an AOI is a two-corner box, NW and SE, and points 2 and 4 do not exist in
#: this document at all.
AOI_ELEMENTS: dict[int, _Element] = {
    1: _Element(
        tag=1, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 16 00 00 00", key_crc=24366,
        name="POI/AOI Number", units="Number", data_format="uint16", length="2",
        notes="AOI Number ** REQUIRED when sending an AOI **",
        requirements=("ST 0806.4-13",), kind="uint"),
    2: _Element(
        tag=2, key_hex="06 0E 2B 34 01 01 01 03 07 01 02 01 03 07 01 00", key_crc=23392,
        name="Corner Latitude Point 1 (Decimal Degrees)", units="Degrees", data_format="int32",
        length="4",
        notes=("NW corner of AOI.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 90. "
               "Use -(2^31) as an \"error\" indicator. -(2^31) = 0x80000000. Resolution: ~42 nano "
               "degrees. ** REQUIRED when sending an AOI ** "
               "[document footnote 1: Corner Latitude Point 1 is the same as the Upper Left "
               "Latitude]"),
        requirements=("ST 0806.4-14",), kind="latitude"),
    3: _Element(
        tag=3, key_hex="06 0E 2B 34 01 01 01 03 07 01 02 01 03 0B 01 00", key_crc=11777,
        name="Corner Longitude Point 1 (Decimal Degrees)", units="Degrees", data_format="int32",
        length="4",
        notes=("NW corner of AOI.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 180. "
               "Use -(2^31) as an \"error\" indicator. -(2^31) = 0x80000000. Resolution: ~84 nano "
               "degrees. ** REQUIRED when sending an AOI ** "
               "[document footnote 2: Corner Longitude Point 1 is the same as the Upper Left "
               "Longitude]"),
        requirements=("ST 0806.4-15",), kind="longitude"),
    4: _Element(
        tag=4, key_hex="06 0E 2B 34 01 01 01 03 07 01 02 01 03 09 01 00", key_crc=16481,
        name="Corner Latitude Point 3 (Decimal Degrees)", units="Degrees", data_format="int32",
        length="4",
        notes=("SE corner of AOI.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 90. "
               "Use -(2^31) as an \"error\" indicator. -(2^31) = 0x80000000. Resolution: ~42 nano "
               "degrees. ** REQUIRED when sending an AOI ** "
               "[document footnote 3: Corner Latitude Point 3 is the same as the Lower Right "
               "Latitude]"),
        requirements=("ST 0806.4-16",), kind="latitude"),
    5: _Element(
        tag=5, key_hex="06 0E 2B 34 01 01 01 03 07 01 02 01 03 0D 01 00", key_crc=40097,
        name="Corner Longitude Point 3 (Decimal Degrees)", units="Degrees", data_format="int32",
        length="4",
        notes=("SE corner of AOI.  Based on WGS84 ellipsoid. Map -(2^31-1)..(2^31-1) to +/- 180. "
               "Use -(2^31) as an \"error\" indicator. -(2^31) = 0x80000000. Resolution: ~84 nano "
               "degrees. ** REQUIRED when sending an AOI ** "
               "[document footnote 4: Corner Longitude Point 3 is the same as the Lower Right "
               "Longitude]"),
        requirements=("ST 0806.4-17",), kind="longitude"),
    6: _Element(
        tag=6, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1A 00 00 00", key_crc=4124,
        name="POI/AOI Type", units="None", data_format="int8", length="1",
        notes="** REQUIRED when sending an AOI **",
        requirements=("ST 0806.4-18",), kind="int8_unenumerated"),
    7: _Element(
        tag=7, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1B 00 00 00", key_crc=26280,
        name="POI/AOI Text", units="String ISO-7", data_format="String ISO-7", length="Max. 2048",
        notes="User Defined String", requirements=(), kind="iso7"),
    8: _Element(
        tag=8, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1D 00 00 00", key_crc=16689,
        name="POI/AOI Source ID", units="String ISO-7", data_format="String ISO-7",
        length="Max. 255", notes="User Defined String", requirements=(), kind="iso7"),
    9: _Element(
        tag=9, key_hex="06 0E 2B 34 01 01 01 01 0E 01 01 03 1E 00 00 00", key_crc=56045,
        name="POI/AOI Label", units="String ISO-7", data_format="String ISO-7", length="16",
        notes="User Defined String.", requirements=(), kind="iso7"),
    10: _Element(
        tag=10, key_hex="06 0E 2B 34 01 01 01 01 0E 01 04 03 01 00 00 00", key_crc=22181,
        name="Operation ID", units="String ISO-7", data_format="String ISO-7", length="Max. 127",
        notes=("Operation ID is the identifier for the duration of the supporting mission or "
               "event associated with the Area of Interest.  This is not the platform mission "
               "designation."),
        requirements=(), kind="iso7"),
}


#: **Table 8-4: User Defined Local Set**, both rows. `ST 0806.4-23` — "Only the Numeric ID for Data
#: (Tag ID 1) and the User Data (Tag ID 2) shall be present in a User Defined LS" — fixes this
#: table at exactly two rows, which is the strongest of the four cross-checks because it is an
#: EXHAUSTIVE statement rather than an optionality range.
USER_DEFINED_ELEMENTS: dict[int, _Element] = {
    1: _Element(
        tag=1, key_hex="06 0E 2B 34 01 01 01 01 0E 01 02 03 11 00 00 00", key_crc=49379,
        name="Numeric ID for Data Type", units="N/A", data_format="uint8", length="1",
        notes=("Numeric identifier with data type. Bit ordering MSB first: 87654321 Bits 8 & 7 set "
               "the data type: = 00 for strings = 01 for INT = 10 for UINT = 11 for Experimental. "
               "Bits 1 to 6 are the integer numeric ID for the user defined data ranging from 0 to "
               "63 (64 possible user data items for each type) ** REQUIRED when sending User "
               "Defined Data **"),
        requirements=("ST 0806.4-21",), kind="numeric_id_bitfield"),
    2: _Element(
        tag=2, key_hex="06 0E 2B 34 01 01 01 01 0E 01 02 03 12 00 00 00", key_crc=23359,
        name="User Data", units="N/A", data_format="N/A", length="V",
        notes=("User Data.  Data type defined in byte 1 of this packet with variant (uint16, "
               "uint32, etc.) extracted from the overall pack length. ** REQUIRED when sending "
               "User Defined Data **"),
        requirements=("ST 0806.4-22",), kind="opaque"),
}


#: Which RVT tag hands its Value to which table, and under which set name. `decode_set` reads this
#: rather than branching on the tag, so adding a subordinate set is a row here and nothing else.
SUBORDINATE_SETS: dict[int, tuple[str, dict[int, _Element], bytes, int]] = {
    11: ("User Defined Local Set", USER_DEFINED_ELEMENTS,
         USER_DEFINED_LOCAL_SET_KEY, USER_DEFINED_LOCAL_SET_KEY_CRC),
    12: ("Point of Interest Local Set", POI_ELEMENTS,
         POI_LOCAL_SET_KEY, POI_LOCAL_SET_KEY_CRC),
    13: ("Area of Interest Local Set", AOI_ELEMENTS,
         AOI_LOCAL_SET_KEY, AOI_LOCAL_SET_KEY_CRC),
}

#: The name of the outermost table, so a `DecodedSet` always says which set it is.
RVT_SET_NAME = "RVT Local Set"

#: Every tag of each table, in tag order. The scope contract for this document, stated once as data.
ELEMENT_TAGS: tuple[int, ...] = tuple(sorted(ELEMENTS))
POI_ELEMENT_TAGS: tuple[int, ...] = tuple(sorted(POI_ELEMENTS))
AOI_ELEMENT_TAGS: tuple[int, ...] = tuple(sorted(AOI_ELEMENTS))
USER_DEFINED_ELEMENT_TAGS: tuple[int, ...] = tuple(sorted(USER_DEFINED_ELEMENTS))

#: `ST 0806.4-08`, `-09`, `-10` for a POI; `-13` through `-18` for an AOI; `-21` and `-22` for a
#: User Defined LS. Derived from the tables' own `requirements` tuples rather than restated, so a
#: transcription change cannot leave this list behind.
POI_REQUIRED_TAGS: tuple[int, ...] = tuple(
    tag for tag in POI_ELEMENT_TAGS if POI_ELEMENTS[tag].requirements)
AOI_REQUIRED_TAGS: tuple[int, ...] = tuple(
    tag for tag in AOI_ELEMENT_TAGS if AOI_ELEMENTS[tag].requirements)
USER_DEFINED_REQUIRED_TAGS: tuple[int, ...] = tuple(
    tag for tag in USER_DEFINED_ELEMENT_TAGS if USER_DEFINED_ELEMENTS[tag].requirements)


#: **WHAT STANDS IN PLACE OF `check_against_the_documents_own_examples`, AND IT IS WEAKER.**
#: ST 0806.4 prints no worked example — see the module docstring — so nothing below is checked
#: against octets the document itself wrote down. What IS available is that the document states the
#: same fact more than once in more than one place, and `check_transcription_cross_check()` runs
#: every one of those agreements on every suite run.
#:
#: The four independent checks, each named with the statements it compares:
#:
#: 1. **The three subordinate keys, three statements each.** The POI key is stated by
#:    `ST 0806.4-07`, by Table 8-1's tag 12 row and by Table 8-2's header row; the AOI key by
#:    `-12`, Table 8-1's tag 13 row and Table 8-3's header; the User Defined key by `-20`,
#:    Table 8-1's tag 11 row and Table 8-4's header. Nine statements, three keys, and the CRC in
#:    every parenthesis agrees with the sixteen octets beside it.
#: 2. **The RVT key, two statements plus a SECOND DOCUMENT.** `ST 0806.4-06` and Table 8-1's header
#:    row, and then ST 0601.14a §8.73 from outside — the ground the whole module rests on.
#: 3. **The table sizes, fixed by requirements rather than by counting rows.** `ST 0806.4-11` makes
#:    POI tags 4..10 optional and `-08`/`-09`/`-10` make 1..3 mandatory, so Table 8-2 has ten rows;
#:    `-19` with `-13`..`-18` fixes Table 8-3 at ten; `-23` fixes Table 8-4 at two EXHAUSTIVELY.
#:    Each is checked against the transcribed table's length.
#: 4. **§7.3's count of the subordinate sets.** "The RVT LS makes use of three smaller Local Sets",
#:    enumerated 1..3, against `len(SUBORDINATE_SETS)`.
#:
#: What this does NOT establish, said plainly: that any value map below is right. A map is read off
#: one Notes cell and no second statement of it exists in the document.
TRANSCRIPTION_CROSS_CHECK = (
    "ST 0806.4 prints no worked example, so this module's decoder is never run against octets the "
    "document wrote. In its place: nine statements of the three subordinate Universal Keys (three "
    "each, from a requirement, a Table 8-1 row and the subordinate table's own header), two "
    "statements of the RVT key plus ST 0601.14a §8.73 from outside, three requirement-derived "
    "table sizes and §7.3's count of three subordinate sets. `check_transcription_cross_check()` "
    "runs all of them on every suite run. It establishes that the tables were transcribed "
    "consistently; it does NOT establish that any value map is right, because each map is stated "
    "once and nowhere else"
)


def check_transcription_cross_check() -> dict[str, Any]:
    """Every agreement `TRANSCRIPTION_CROSS_CHECK` names, run. Raises `RvtError` on any failure.

    Returns the checks it performed so a caller can report the count rather than assert a constant.
    """
    performed: list[str] = []

    # 1. The three subordinate keys: the RVT row's key must equal the subordinate table's key.
    for rvt_tag, (name, table, key, crc) in SUBORDINATE_SETS.items():
        row = ELEMENTS[rvt_tag]
        row_key = bytes.fromhex(row.key_hex.replace(" ", ""))
        if row_key != key or row.key_crc != crc:
            raise RvtError(
                f"Table 8-1's tag {rvt_tag} row states key {row.key_hex} (CRC {row.key_crc}) for "
                f"the {name}, and its own table header states {key.hex().upper()} (CRC {crc}). "
                "ST 0806.4 states each subordinate key three times and they must agree")
        performed.append(f"subordinate key for RVT tag {rvt_tag} ({name})")

    # 2. The RVT key's own two statements, and the CRC width of every key in every table.
    if len(LOCAL_SET_KEY) != framing.KEY_LENGTH:
        raise RvtError(
            f"ST 0806.4-06's RVT Local Set key is {len(LOCAL_SET_KEY)} octets and a Universal "
            f"Label is {framing.KEY_LENGTH}")
    performed.append("RVT Local Set key width")
    for label, table in (("Table 8-1", ELEMENTS), ("Table 8-2", POI_ELEMENTS),
                         ("Table 8-3", AOI_ELEMENTS), ("Table 8-4", USER_DEFINED_ELEMENTS)):
        for tag, element in table.items():
            octets = element.key_hex.replace(" ", "")
            if len(octets) != 2 * framing.KEY_LENGTH:
                raise RvtError(
                    f"{label} tag {tag} {element.name} states a key of {len(octets) // 2} octets; "
                    f"every Key Value (hex) cell in ST 0806.4 draws {framing.KEY_LENGTH}")
        performed.append(f"{label} key widths")

    # 3. The three requirement-derived table sizes.
    for label, table, size, clause in (
            ("Table 8-2", POI_ELEMENTS, 10,
             "ST 0806.4-08/-09/-10 make tags 1-3 mandatory and -11 makes 'Tag ID 4 through Tag ID "
             "10 ... optional'"),
            ("Table 8-3", AOI_ELEMENTS, 10,
             "ST 0806.4-13 through -18 make tags 1-6 mandatory and -19 makes 'Tag ID 7 through Tag "
             "ID 10 ... optional'"),
            ("Table 8-4", USER_DEFINED_ELEMENTS, 2,
             "ST 0806.4-23: 'Only the Numeric ID for Data (Tag ID 1) and the User Data (Tag ID 2) "
             "shall be present in a User Defined LS'")):
        if len(table) != size or tuple(sorted(table)) != tuple(range(1, size + 1)):
            raise RvtError(
                f"{label} is transcribed with {len(table)} rows at tags {sorted(table)}, and the "
                f"document fixes it at {size} contiguous from 1: {clause}")
        performed.append(f"{label} size against its requirements")

    # 4. §7.3's own count.
    if len(SUBORDINATE_SETS) != 3:
        raise RvtError(
            f"§7.3: 'The RVT LS makes use of three smaller Local Sets', enumerated 1..3, and "
            f"SUBORDINATE_SETS holds {len(SUBORDINATE_SETS)}")
    performed.append("§7.3's count of three subordinate sets")

    return {"checks": len(performed), "performed": tuple(performed)}


# ------------------------------------------------------------------------- refusal classes

REFUSAL_UNLISTED_TAG = "unlisted_tag"
REFUSAL_STATED_LENGTH = "stated_length"
REFUSAL_NOT_ISO_7 = "not_iso_7"
REFUSAL_NESTED_SET_MALFORMED = "nested_set_malformed"

#: Why a bad element is carried rather than raised, stated once as data. `klv_security_codec`'s
#: `ELEMENT_REFUSAL_POLICY`, reached by a third document and not restated as a new rule.
ELEMENT_REFUSAL_POLICY = (
    "The element is refused and the SET is not. Discarding a well-formed POI because one of its "
    "ten elements is malformed destroys the evidence a consumer needs; the octets stay parked at "
    "`raw_elements`, the clause the element failed is named, and every other element decodes. This "
    "is klv_security_codec.ELEMENT_REFUSAL_POLICY's reasoning reached by a third document"
)

#: The signal `-(2^31)` names in the three degree maps, as a value rather than as a number.
SIGNAL_ERROR = "error"


# ------------------------------------------------------------------------- the decoded shapes


class RefusedElement(NamedTuple):
    """One element this layer declined to decode, with the clause that decided it."""

    set_name: str
    tag: int
    name: str | None
    refusal_class: str
    observed_length: int
    stated_length: str | None
    octets: str
    tag_offset: int
    value_offset: int
    clause: str


class DecodedElement(NamedTuple):
    """One element as this layer read it: the value, the octets, and where they were.

    `signal` is set where the document's own Notes cell names a reserved code rather than a
    measurement — the three degree maps' `-(2^31)` "error" indicator — and `value` is None there.
    A signal is not a measurement and is never averaged with one.
    """

    set_name: str
    tag: int
    name: str
    length: int
    value: Any
    signal: str | None
    units: str
    raw: bytes
    tag_offset: int
    value_offset: int
    requirements: tuple[str, ...]


class DecodedSet(NamedTuple):
    """One ST 0806.4 Local Set — the RVT LS itself or one of its three subordinate sets.

    `set_name` says WHICH table read these octets, because the tag integers alone do not: Table
    8-1's tag 2 is a timestamp, Table 8-2's is a latitude, Table 8-3's is a corner latitude and
    Table 8-4's is opaque user data.
    """

    set_name: str
    elements: dict[int, DecodedElement]
    order: tuple[int, ...]
    refusals: tuple[RefusedElement, ...]
    unlisted_tags: tuple[int, ...]
    raw_elements: dict[int, str]
    #: Subordinate sets in the order they arrived, as `(rvt_tag, DecodedSet)`. A LIST and not a
    #: dict: `ST 0806.4-25` says a subordinate-set tag "can appear multiple times to convey
    #: information for multiple points of interest", so keying on the tag would collapse two POIs
    #: into one. Empty for a subordinate set, which carries none.
    subordinate_sets: tuple[tuple[int, "DecodedSet"], ...]
    octets: bytes

    @property
    def required_absent(self) -> tuple[int, ...]:
        """Which of this set's own mandatory tags did not arrive. Empty for the RVT LS itself.

        The RVT LS has no mandatory element WHEN EMBEDDED — see `EMBEDDED_SET_POLICY` — so this
        answers the question only for the three subordinate sets, whose requirements are
        unconditional: `ST 0806.4-08`/`-09`/`-10` for a POI, `-13`..`-18` for an AOI, `-21`/`-22`
        for a User Defined LS.
        """
        required = {
            "Point of Interest Local Set": POI_REQUIRED_TAGS,
            "Area of Interest Local Set": AOI_REQUIRED_TAGS,
            "User Defined Local Set": USER_DEFINED_REQUIRED_TAGS,
        }.get(self.set_name, ())
        return tuple(tag for tag in required if tag not in self.elements)

    @property
    def independent_set_conformance(self) -> dict[str, bool | None]:
        """Which of `ST 0806.4-01`..`-04` these octets satisfy. REPORTED, NEVER ENFORCED.

        `None` where the set is not the RVT LS, because the four requirements are about it.
        `EMBEDDED_SET_POLICY` says why a False here refuses nothing.
        """
        if self.set_name != RVT_SET_NAME:
            return {name: None for name in INDEPENDENT_SET_REQUIREMENTS}
        return {
            "ST 0806.4-01": 2 in self.elements,
            "ST 0806.4-02": bool(self.order) and self.order[0] == 2,
            "ST 0806.4-03": 1 in self.elements,
            "ST 0806.4-04": bool(self.order) and self.order[-1] == 1,
        }


# ------------------------------------------------------------------------- the value maps

#: The three degree maps' reserved code, from every one of their Notes cells: "-(2^31) = 0x80000000".
_DEGREES_ERROR = -(2 ** 31)
#: The denominator all three degree maps state: "Map -(2^31-1)..(2^31-1) to +/- 90" (or 180).
_DEGREES_DENOMINATOR = 2 ** 31 - 1
#: POI Altitude, tag 4's cell: "Map 0..(2^16-1) to -900..19000 meters."
_POI_ALTITUDE_MIN = -900.0
_POI_ALTITUDE_MAX = 19000.0
_POI_ALTITUDE_DENOMINATOR = 2 ** 16 - 1

#: Table 8-4 tag 1's own four data types, from the Notes cell's "= 00 for strings = 01 for INT =
#: 10 for UINT = 11 for Experimental". Two bits admit four values and the cell prints four, so this
#: enumeration is complete by construction and a fifth is not reachable.
USER_DATA_TYPES: dict[int, str] = {0b00: "strings", 0b01: "INT", 0b10: "UINT",
                                   0b11: "Experimental"}


def _decode_iso7(element: _Element, value: bytes) -> str:
    """`String ISO-7` text, strictly. An octet at or above 0x80 is not an ISO-7 character."""
    try:
        return value.decode("ascii")
    except UnicodeDecodeError as exc:
        raise RvtError(
            f"tag {element.tag} {element.name} declares Format '{element.data_format}' and its "
            f"octets {value.hex()} carry a byte at or above 0x80 at position {exc.start}. This "
            "layer will not reinterpret it under an encoding no held document names for this "
            "element"
        ) from exc


def _stated_length(element: _Element) -> int | None:
    """The Length cell as an exact octet count, or None where it states a maximum or `V`.

    `Max. 127`, `Max. 255`, `Max. 2048` and `V` are not exact widths and nothing is enforced for
    them; `1`, `2`, `3`, `4`, `8` and `16` are, and an element arriving at another width is refused.
    """
    text = element.length.strip()
    if not text or text == "V" or text.startswith("Max"):
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _decode_element(element: _Element, value: bytes) -> tuple[Any, str | None]:
    """One element's octets to its value and its signal, under the rule `DECODING_RULES` states."""
    if element.kind == "uint":
        return int.from_bytes(value, "big"), None
    if element.kind == "int8_unenumerated":
        return int.from_bytes(value, "big", signed=True), None
    if element.kind == "iso7":
        return _decode_iso7(element, value), None
    if element.kind in ("latitude", "longitude"):
        raw = int.from_bytes(value, "big", signed=True)
        if raw == _DEGREES_ERROR:
            return None, SIGNAL_ERROR
        limit = 90.0 if element.kind == "latitude" else 180.0
        return raw * limit / _DEGREES_DENOMINATOR, None
    if element.kind == "poi_altitude":
        raw = int.from_bytes(value, "big")
        span = _POI_ALTITUDE_MAX - _POI_ALTITUDE_MIN
        return _POI_ALTITUDE_MIN + raw * span / _POI_ALTITUDE_DENOMINATOR, None
    if element.kind == "numeric_id_bitfield":
        octet = value[0]
        return {"data_type_bits": (octet >> 6) & 0b11,
                "data_type": USER_DATA_TYPES[(octet >> 6) & 0b11],
                "numeric_id": octet & 0b111111}, None
    if element.kind == "opaque":
        return value.hex(), None
    raise RvtError(f"tag {element.tag} {element.name} has no decoding rule for kind "
                   f"{element.kind!r}")


# ------------------------------------------------------------------------- the walk


def decode_set(value: bytes, *, table: dict[int, _Element] | None = None,
               set_name: str = RVT_SET_NAME, base_offset: int = 0) -> DecodedSet:
    """One ST 0806.4 Local Set's Value octets to its elements, recursing into subordinate sets.

    `value` is the set's Value octets and NOTHING ELSE — no Universal Label and no outer BER
    length. For the RVT LS that is what ST 0601.14a §8.73's bullet makes item 73 carry ("The length
    field is the size of all RVT LS metadata items to be packaged within Tag 73"); for a
    subordinate set it is what Table 8-1's own tag 11, 12 and 13 Notes cells make that tag carry.
    The span is walked as a bare run of Local Set triplets with `klv_codec`'s BER-OID tag and BER
    length primitives, which is the framing layer doing the framing exactly as it does one layer up.

    `table` and `set_name` say WHICH of the four tables reads these octets. They default to the RVT
    LS because that is what item 73 hands over; `decode_set` supplies the subordinate pair itself
    when it recurses, from `SUBORDINATE_SETS`.

    `base_offset` is where `value` began in the enclosing buffer, so a refusal's `tag_offset` points
    at an octet of the packet rather than of a slice.
    """
    table = ELEMENTS if table is None else table
    elements: dict[int, DecodedElement] = {}
    order: list[int] = []
    refusals: list[RefusedElement] = []
    unlisted: list[int] = []
    raw_elements: dict[int, str] = {}
    subordinate: list[tuple[int, DecodedSet]] = []

    cursor = 0
    end = len(value)
    while cursor < end:
        tag_offset = cursor
        tag, cursor = framing.decode_ber_oid(value, cursor)
        length, cursor = framing.decode_ber_length(value, cursor)
        if cursor + length > end:
            raise RvtError(
                f"the element with tag {tag} at offset {base_offset + tag_offset} declares a "
                f"{length}-octet Value, which runs {cursor + length - end} octet(s) past the end "
                f"of the {set_name} it is in. ST 0601.14a §8.73: 'The length field is the size of "
                "all RVT LS metadata items to be packaged within Tag 73' — so an element "
                "overrunning that span is a malformed set and not a malformed element")
        raw = value[cursor:cursor + length]
        value_offset = cursor
        cursor += length
        order.append(tag)
        raw_elements[tag] = raw.hex()

        element = table.get(tag)
        if element is None:
            unlisted.append(tag)
            refusals.append(RefusedElement(
                set_name=set_name, tag=tag, name=None, refusal_class=REFUSAL_UNLISTED_TAG,
                observed_length=length, stated_length=None, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                clause=(f"ST 0806.4's table for the {set_name} draws rows for tags "
                        f"{sorted(table)} and for no others. The octets are carried and this layer "
                        "declines to say what they mean")))
            continue

        if element.kind == "nested_set":
            name, subordinate_table, _key, _crc = SUBORDINATE_SETS[tag]
            try:
                nested = decode_set(raw, table=subordinate_table, set_name=name,
                                    base_offset=base_offset + value_offset)
            except RvtError as exc:
                refusals.append(RefusedElement(
                    set_name=set_name, tag=tag, name=element.name,
                    refusal_class=REFUSAL_NESTED_SET_MALFORMED, observed_length=length,
                    stated_length=element.length, octets=raw.hex(),
                    tag_offset=base_offset + tag_offset,
                    value_offset=base_offset + value_offset,
                    clause=f"{exc}. {ELEMENT_REFUSAL_POLICY}"))
                continue
            subordinate.append((tag, nested))
            continue

        stated = _stated_length(element)
        if stated is not None and length != stated:
            refusals.append(RefusedElement(
                set_name=set_name, tag=tag, name=element.name,
                refusal_class=REFUSAL_STATED_LENGTH, observed_length=length,
                stated_length=element.length, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                clause=(f"ST 0806.4's table for the {set_name} states a Length in Bytes of "
                        f"'{element.length}' for tag {tag} {element.name}, Format "
                        f"'{element.data_format}', and this element carries {length}. "
                        f"{ELEMENT_REFUSAL_POLICY}")))
            continue

        try:
            decoded, signal = _decode_element(element, raw)
        except RvtError as exc:
            refusals.append(RefusedElement(
                set_name=set_name, tag=tag, name=element.name,
                refusal_class=(REFUSAL_NOT_ISO_7 if element.kind == "iso7"
                               else REFUSAL_STATED_LENGTH),
                observed_length=length, stated_length=element.length, octets=raw.hex(),
                tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
                clause=f"{exc}. {ELEMENT_REFUSAL_POLICY}"))
            continue

        elements[tag] = DecodedElement(
            set_name=set_name, tag=tag, name=element.name, length=length, value=decoded,
            signal=signal, units=element.units, raw=raw,
            tag_offset=base_offset + tag_offset, value_offset=base_offset + value_offset,
            requirements=element.requirements)

    return DecodedSet(
        set_name=set_name, elements=elements, order=tuple(order), refusals=tuple(refusals),
        unlisted_tags=tuple(unlisted), raw_elements=raw_elements,
        subordinate_sets=tuple(subordinate), octets=value)


def decode_rvt_local_set(value: bytes, *, base_offset: int = 0) -> DecodedSet:
    """ST 0601 item 73's Value to an RVT Local Set. The entry point `klv_uas_codec` calls."""
    return decode_set(value, table=ELEMENTS, set_name=RVT_SET_NAME, base_offset=base_offset)


def encode_element(tag: int, octets: bytes) -> bytes:
    """One ST 0806.4 Local Set triplet: BER-OID tag, BER length, Value.

    The inverse of the walk above, for fixtures. There is no `encode_set` computing a checksum
    here and there is deliberately none: Table 8-1's tag 1 CRC-32 is "Performed on entire LS
    packet, including 16-byte US key", and an RVT LS embedded in ST 0601 item 73 carries no US key
    — so the octets that CRC is defined over do not exist inside item 73. A fixture that wanted a
    conforming independent RVT LS would need the key on the wire, which item 73 forbids.
    """
    return framing.encode_ber_oid(tag) + framing.encode_ber_length(len(octets)) + octets


def encode_set(elements: tuple[tuple[int, bytes], ...]) -> bytes:
    """A whole Local Set Value from `[(tag, octets), ...]`, in the order given.

    NO KEY AND NO OUTER LENGTH, for `decode_set`'s reason. The order is the caller's because
    `ST 0806.4-02` and `-04` are about order and a fixture must be able to violate them on purpose.
    """
    return b"".join(encode_element(tag, octets) for tag, octets in elements)


#: What ST 0601.14a says item 73 carries, quoted, so the delegation is readable from this module.
#: `klv_security_codec.CARRIER_BASIS`' arrangement, applied to the fourth delegating item.
CARRIER_BASIS = (
    "ST 0601.14a §8.73 Tag 73: RVT Local Set, Description 'MISB ST 0806 RVT Local Set metadata "
    "items', Format 'KLV set', Length 'Variable', Max Length 'Not Limited', Required in LS? "
    "'Optional', Allowed in SDCC Pack? 'No', Multiples Allowed? 'No'. Its two bullets: 'Use the "
    "MISB ST 0806 Local Set within the MISB ST 0601 Tag 73' and 'The length field is the size of "
    "all RVT LS metadata items to be packaged within Tag 73'. Its §8.73.1 Details: 'The RVT Local "
    "Set item allows users to include, or nest, RVT LS (MISB ST 0806 ) metadata items within MISB "
    "ST 0601. This provides users who are required to use the RVT LS metadata items (Points of "
    "Interest, Areas of Interest, etc.) a method to leverage the data field contained within MISB "
    "ST 0601 (i.e. platform location, and sensor pointing angles).' And the KLV Key it prints: "
    "'06.0E.2B.34.02.0B.01.01.0E.01.03.01.02.00.00.00 (CRC 17945)', which is the sixteen octets "
    "and the CRC ST 0806.4-06 states — the two-document agreement this codec rests on. §8.73's "
    "Example KLV Item row prints Tag 49 (hex for 73), a Len of '-' and a Value of 'N/A', SO THE "
    "DELEGATING DOCUMENT PRINTS NO WORKED EXAMPLE EITHER, and neither of the two documents behind "
    "this codec supplies one"
)

#: The two clauses a consumer needs to check the delegation, as pointers rather than as prose.
CARRIER_CLAUSES: tuple[str, ...] = ("MISB ST 0601.14a §8.73", "MISB ST 0806.4 §7.1, ST 0806.4-06")

#: **WHAT THIS LAYER DOES NOT MAP, AND WHY IT IS A PROPOSAL RATHER THAN AN OMISSION.** Six elements
#: of this document have an obvious CDM home: POI Latitude/Longitude/Altitude and the AOI's two
#: corners are positions, and the RVT LS's tag 2 is a time. `FORMAT_COVERAGE.md` row 73's CDM field
#: cell reads `Entity.attributes`, and the round that wrote this module was ruled to carry values as
#: the document names them and to PROPOSE anything with a CDM home rather than map it. So every
#: value above rides in `attributes` and nothing here becomes a `Position` or an `Entity`. The
#: proposal is written up in that round's report; the reason it is not taken here is that a POI is a
#: point on the ground the aircrew nominated, not the platform the packet is about, and emitting it
#: as a second Entity is a modelling decision with no clause behind it.
CDM_MAPPING_NOT_TAKEN = (
    "POI Latitude (Table 8-2 tag 2), POI Longitude (tag 3), POI Altitude (tag 4), Corner Latitude "
    "Point 1 (Table 8-3 tag 2), Corner Longitude Point 1 (tag 3), Corner Latitude Point 3 (tag 4), "
    "Corner Longitude Point 3 (tag 5) and the RVT LS's own User Defined Time Stamp (Table 8-1 tag "
    "2) all have a CDM home. None is mapped: FORMAT_COVERAGE.md row 73 names `Entity.attributes` "
    "and the values ride there as the document names them. Emitting a POI as a second Entity, or "
    "an AOI as a geometry, is a modelling decision no clause of either document makes, so it is "
    "proposed rather than taken"
)
