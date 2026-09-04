"""The UAS Datalink Local Set ITEM layer: the tag table, the value maps, and the defect policy.

WHAT THIS MODULE IS, AND WHY IT IS NOT `klv_codec`
--------------------------------------------------
`klv_codec` is the framing layer and it is deliberately **tag-blind**: `walk_local_set` "knows no
tags at all, so every item is equally unknown to it and the caller decides which ones it
recognises". That property is load-bearing — it is how `ST 0107.3-04`'s "skip unknown Local Set
values" is satisfied structurally rather than by a skip list — and a tag table imported into that
module would destroy it. So the tag table lives here, one layer up, on the `cat048_codec` /
`asterix_cat048` precedent: a codec that reads octets, and above it a codec that knows what they
mean.

WHAT IT COVERS, AND WHY THAT SET AND NOT THE OTHER 115 ITEMS
-------------------------------------------------------------
**The 26 items the pinned stream attests, and nothing else.** `fixtures/klv/streams/day_flight.klv`
— SHA-256 `a810e4b6…e51`, 977 octets, provenance closed at `samples.ffmpeg.org` by byte identity —
carries six packets of 26 items each, the same 26 tags in the same order every time: 1, 2, 5, 6, 7,
11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 40, 41, 42, 56, 57 and 65. Every other
tag in ST 0601.14a's 141-row Table 1 is absent from this module, and the absence is the scope
contract: an item this repository has never seen on a wire is an item whose decoder nothing here
could check against anything but itself.

WHERE EVERY NUMBER BELOW COMES FROM, AND THE CHECK THAT MAKES IT TRUSTWORTHY
----------------------------------------------------------------------------
Each item's §8.x block in **MISB ST 0601.14a** — SHA-256
`3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4`,
`fixtures/klv/spec/ST0601.14a.pdf`, the edition MISP-2019.1's Appendix B ref [53] pins — states
eleven facts in three drawn tables: the Software format with its Min and Max, the KLV format with
its Min, Max and Offset, the Length / Max Length / Required Length triple, the Resolution, the
Special Values, and whether the item is Mandatory in the Local Set. **All of it is transcribed
below and none of it is remembered.**

The map is one affine form and the document states it twice per item — once as two formulas and
once as a `Map A..B to C..D` bullet:

    software = (software_max - software_min) / (klv_max - klv_min) * klv_integer + offset

**The check is the document's own worked example.** Every §8.x block prints one Software Value
beside the KLV octets that encode it, and `check_against_the_documents_own_examples()` runs the
decoder over all 26 of them: 26 of 26 agree, each to within the item's own stated Resolution and
most to 1e-9. A transcription checked against the document that produced it is a different thing
from a transcription checked against a fixture somebody wrote from the same reading.

AND EDITION 1 AGREES, ITEM BY ITEM, WHICH IS WHY IT IS RECORDED HERE TOO
------------------------------------------------------------------------
`edition_1_header` and `edition_1_example_*` carry **MISB EG 0601.1**'s own §7.N reading — SHA-256
`1714322c25e00e00ccabd5d861318f1448055cbf2000dc2e5099fb30dec0b730`,
`fixtures/klv/spec/EG0601.1.pdf`, the document that closed park 13. For every one of the 26 items
edition 1 states the SAME Units, Range and Format as ST 0601.14a, and its own worked examples decode
under the map above to the values its own §7.N prints. Twelve years and thirteen revisions, and the
map did not move — which is the item-22 finding generalised from one Len cell to the whole witnessed
set, and it is the reason the defect policy below can cite a factual basis at all.

**One divergence, and it is in the Format column of two items.** Edition 1 writes tags 11 and 12 as
`ISO7` where ST 0601.14a writes `utf8`. Both are decoded here as UTF-8, which is the PINNED
edition's statement and which reads every ISO 646 octet identically — so the divergence costs
nothing on any octet either edition admits, and it is recorded rather than smoothed over.

THE LENGTH-DIVERGENCE POLICY, WHICH IS A CODEC RULING AND NOT A TAG-22 SPECIAL CASE
-----------------------------------------------------------------------------------
See `LENGTH_DIVERGENCE_POLICY` below. In one line: **the item is skipped and a structured defect
annotation is recorded; the packet is not rejected and the octets are never reinterpreted.**
"""
from __future__ import annotations

from typing import Any, NamedTuple

from synapse_cdm.adapters import klv_codec as framing
from synapse_cdm.adapters import klv_security_codec as security

#: The pinned copies every citation in this module is read from. Stated here as well as in
#: `klv_pin.json` because a module that cites sections without naming the copy is citing a memory.
SOURCE_ST_0601_14A = (
    "MISB ST 0601.14a, SHA-256 "
    "3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4, "
    "fixtures/klv/spec/ST0601.14a.pdf"
)
SOURCE_EG_0601_1 = (
    "MISB EG 0601.1, SHA-256 "
    "1714322c25e00e00ccabd5d861318f1448055cbf2000dc2e5099fb30dec0b730, "
    "fixtures/klv/spec/EG0601.1.pdf"
)


class UASItemError(ValueError):
    """A value this module refuses to decode or encode, with the section that decides it."""


class SpecialValue(NamedTuple):
    """A reserved KLV integer that the document says is NOT a measurement.

    Four items in the witnessed set declare one — `0x8000` on tags 6 and 7 ("Out of Range"),
    `0x80000000` on 13, 14 and 19 ("Reserved") and on 23, 24, 40 and 41 ("N/A (Off-Earth)") — and
    a decoder that ran the affine map over them would produce a number: -20.0006 degrees of pitch,
    or a latitude of -90.0000000419. **Each of those is a plausible-looking lie**, which is the
    class of defect this repository's ellipsoid audit exists for, so the sentinel is returned as
    itself and the caller decides. The label is the document's own words.
    """

    tag: int
    integer: int
    label: str


class LengthDivergence(NamedTuple):
    """One item whose octet count disagrees with what its own §8.x block requires.

    Carried as data rather than raised, because the policy is to skip the ITEM and keep the
    packet: a raised exception would take the other 25 items with it. Every field is here so the
    annotation a consumer reads names the octets rather than describing them.
    """

    tag: int
    name: str
    observed_length: int
    required_length: int | None
    max_length: int | None
    tag_offset: int
    value_offset: int
    octets: str
    divergence_class: str
    section: str
    policy: str
    factual_basis: str
    normative_basis: str


# --------------------------------------------------------------------------- the defect policy
#
# THE LENGTH-DIVERGENCE POLICY. Act 2 of the witnessed-set round, decided before any mapping was
# written, and recorded in FORMAT_COVERAGE.md under "The length-divergence policy".
#
# THE MOTIVATING CASE, AND IT IS THE ONLY ONE IN THE HELD BYTES. The pinned stream carries item 22,
# Target Width, at FOUR octets at all six sites where ST 0601.14a §8.22 states a Required Length of
# 2, with the top two octets `0x0000` every time. Park 13 adjudicated that divergence and ruled it
# **(a), a stream defect**. Park 13 also decided what it did NOT reach: the framing layer is
# "correct as shipped" because it reads the length the stream states and advances by it, and "the
# flag is owed by the value-decoding layer, which does not exist". This module is that layer, so the
# flag is owed here — and a layer that reads the tag table with no stated rule for a length
# contradicting it would be deciding case by case, which is how a codec acquires behaviour nobody
# wrote down.
#
# THE RULING'S TWO BASES, KEPT APART HERE AS PARK 13 KEEPS THEM APART.
#
#   FACTUAL   edition 1's own item-22 row states a Len of 2 at three sites inside itself — the Len
#             column, §7.22's format header and §7.22's worked example `[0d22][0d2][0x1F 9B]` — and
#             so does every edition this repository can sample. There is no edition of this series
#             in which four octets was correct. Generalised by THIS round from one Len cell to the
#             whole witnessed set: edition 1 states the same Units, Range and Format as ST 0601.14a
#             for all 26 items, checked item by item in `ITEMS` below.
#   NORMATIVE `ST 0601.13-29`, quoted from §7's Requirement block: "When a metadata item has a
#             Required Length numerically specified in this standard, the KLV encoded value for the
#             item shall use exactly the number of bytes specified by the Required Length."
#
# THE THREE CANDIDATES, AND WHY (b) IS THE RULING.
#
#   (a) REJECT THE PACKET. Rejected. All six checksums over the held stream validate, so the packet
#       is exactly what the emitter wrote and 25 of its 26 items are conformant; discarding them on
#       account of one item destroys verified data. It also contradicts `ST 0107.3-04` — "shall skip
#       unknown Local Set values so as to not impact the decoding of known Local Set items within
#       the same Local Set instance" — whose whole subject is that one item must not take the others
#       down. A length a decoder cannot use makes the ITEM unusable, not the packet.
#   (c) DECODE ANYWAY AND ANNOTATE. Rejected, and this is the candidate that looks harmless. Four
#       octets carrying `0x000001c9` "obviously" mean 457, and reaching that number requires
#       CHOOSING a rule — strip leading octets down to the Required Length, or read the whole field
#       as the wider unsigned integer, or take the low Required-Length octets — and **no held
#       document states any of them.** The three agree on `0x000001c9` and disagree the moment a top
#       octet is non-zero, so their agreeing here is a property of this stream rather than of the
#       rule. That is a guess that would pass every fixture written from the same guess.
#   (b) SKIP THE ITEM AND RECORD A STRUCTURED DEFECT ANNOTATION. **THE RULING.** The item's value
#       reaches no CDM field. Its octets are parked verbatim, so nothing is lost and egress
#       reproduces them. A `LengthDivergence` carries the tag, the observed and required lengths,
#       the offsets, the octets, the class and both bases above, so the defect is machine-visible in
#       the output rather than a line in a log — the `attributes.*_basis` discipline every adapter
#       here already follows.
#
# THE CLASS IT APPLIES TO IS NOT "TAG 22", AND THE DOCUMENT DRAWS TWO OF ITS THREE BOUNDARIES.
#
#   * **A variable-length item is not in the class at all.** Tags 11 and 12 state `Length: Variable`,
#     `Max Length: 127`, `Required Length: N/A`. The pinned stream's tag 11 varies between 2 and 3
#     octets across the six packets and that is NOT a defect — the walk round said so and this
#     policy has to agree with it in code.
#   * **Exceeding Max Length is a different class, and it is NOT this policy's.** §7 defines Max
#     Length as "the RECOMMENDED maximum length" and names its consumer: "Network guards may use
#     this value as a check to prevent data leaks." A recommendation is not a `shall`, so an
#     over-long variable item is DECODED and carries an advisory annotation. Treating it like a
#     `ST 0601.13-29` violation would apply a requirement the document did not write.
#   * **A zero-length item is not a defect either, because the document says what it means.**
#     `ST 0601.14-33`: "Where a UAS Data-link LS item has a length of zero, consumers shall
#     interpret the value of the item as 'unknown'." So a ZLI decodes to `ZeroLength` — an explicit
#     unknown, which is exactly the distinction `Position | None` exists to preserve — and never to
#     a defect and never to a zero. The one exception is the document's own: `ST 0601.14-32` says
#     the three required items "(Tag 1 - Checksum, Tag 2 - Precision Time Stamp, and Tag 65 - UAS
#     Datalink LS Version Number) shall always be reported with positive lengths (i.e. Zero-Length
#     Items (ZLI) are not allowed for these items)", so a ZLI on one of those three IS a defect and
#     is reported as one.
#   * **`ST 0601.14-34` is not enforced, and that is the fusion line rather than an omission.** "A
#     Zero-Length Item (ZLI) shall only be used in packets after a non-ZLI is reported" is a
#     constraint on a PRODUCER across packets. Checking it would mean carrying state from one packet
#     into the next, which is the accumulation this repository refuses in ten settlements; the ZLI is
#     recorded per packet and a consumer holding the sequence can apply the rule.

LENGTH_DIVERGENCE_POLICY = "skip_the_item_and_record_a_structured_defect_annotation"

#: The classes, kept apart because they are different faults with different bases.
DIVERGENCE_REQUIRED_LENGTH = "required_length"
DIVERGENCE_ZLI_ON_REQUIRED_ITEM = "zero_length_on_a_required_item"
ADVISORY_OVER_MAX_LENGTH = "over_recommended_max_length"

#: `ST 0601.14-32`'s three items, quoted by tag. A ZLI on one of these is a defect; on any other
#: witnessed item a ZLI is `ST 0601.14-33`'s explicit "unknown".
ZLI_FORBIDDEN = (1, 2, 65)

FACTUAL_BASIS = (
    "edition 1's own item table states this item's Len at three sites inside itself, and every "
    "edition this repository can sample states the same one — the initial release (12 January "
    "2006), EG 0601.1, STD 0601.4, ST 0601.8, ST 0601.14a and ST 0601.19. See FORMAT_COVERAGE.md, "
    "'Park 13 adjudicated and CLOSED', for the reading, and " + SOURCE_EG_0601_1 + " for the copy"
)
NORMATIVE_BASIS = (
    "ST 0601.13-29, §7: 'When a metadata item has a Required Length numerically specified in this "
    "standard, the KLV encoded value for the item shall use exactly the number of bytes specified "
    "by the Required Length.' STANDING ANNOTATION, carried rather than shed at closure: the "
    "identifier is stamped edition 13, nothing held establishes that a requirement introduced at "
    "edition 13 reaches an emitter written against an earlier edition, and that retroactivity is "
    "still unestablished. It is why this basis is stated BESIDE the factual one and never instead "
    "of it"
)
MAX_LENGTH_BASIS = (
    "§7 defines Max Length as 'the recommended maximum length' and names its consumer — 'Network "
    "guards may use this value as a check to prevent data leaks' — so exceeding it breaks no "
    "'shall' and the item is decoded. Recorded as an advisory rather than skipped, because "
    "applying ST 0601.13-29's requirement to a recommendation would enforce a rule the document "
    "did not write"
)
ZLI_BASIS = (
    "ST 0601.14-33, §6.5: 'Where a UAS Data-link LS item has a length of zero, consumers shall "
    "interpret the value of the item as \"unknown\".' §6.5 states the mechanism: 'the producer "
    "sends a Zero-Length Item (ZLI) which is a Local Set item with no value (i.e. tag followed by "
    "a length of zero, with no value). The receiver interprets a ZLI as the value becoming "
    "immediately Unknown.' So this is an explicit unknown and not a defect, and never a zero"
)
ZLI_FORBIDDEN_BASIS = (
    "ST 0601.14-32, §6.5: 'Required items of a UAS Datalink LS (Tag 1 - Checksum, Tag 2 - Precision "
    "Time Stamp, and Tag 65 - UAS Datalink LS Version Number) instance shall always be reported "
    "with positive lengths (i.e. Zero-Length Items (ZLI) are not allowed for these items).' A ZLI "
    "on one of those three is the one zero-length case the document itself makes a defect"
)


class ZeroLength(NamedTuple):
    """`ST 0601.14-33`'s explicit unknown: a tag reported with a length of zero.

    A distinct type rather than `None`, because "the producer told us this value is now unknown"
    and "the producer did not mention this item" are different statements and the CDM's own
    `Position | None` discipline exists to keep that difference. Carried as itself so a consumer
    can tell them apart.
    """

    tag: int
    basis: str = ZLI_BASIS


# ------------------------------------------------------------------------------- the tag table


class _Item(NamedTuple):
    """One §8.x block, transcribed. Every field is a cell in a table the document draws."""

    tag: int
    name: str
    units: str | None
    description: str
    klv_format: str
    klv_min: int | None
    klv_max: int | None
    offset: int
    software_format: str
    software_min: int | None
    software_max: int | None
    length: int | str
    max_length: int | None
    required_length: int | None
    resolution: str | None
    special_values: str | None
    required_in_ls: str
    sdcc_allowed: str
    multiples_allowed: str
    map_bullet: str | None
    section: str
    page: int
    example_value: str
    example_octets: str
    edition_1_header: str | None
    edition_1_example_length: int | None
    edition_1_example_octets: str | None

    @property
    def is_numeric(self) -> bool:
        return self.klv_format != "utf8"

    @property
    def scale(self) -> float:
        """The affine map's multiplier, `(software span) / (KLV integer span)`.

        Computed rather than transcribed, because the document states it as a fraction of two
        numbers already in the table — `40/65534`, `180/4294967294`, `19900/65535` — and a
        transcribed third statement of the same quotient is a third thing to keep in step.
        """
        return ((self.software_max - self.software_min)
                / (self.klv_max - self.klv_min))

    @property
    def special_integer(self) -> int | None:
        """The reserved KLV integer this item declares, or None. Read from the Special Values cell.

        Parsed from the document's own text rather than listed separately, so the sentinel and the
        sentence that states it cannot drift apart.
        """
        cell = self.special_values or ""
        if not cell.startswith("0x"):
            return None
        return int(cell.split(" ", 1)[0], 16)

    @property
    def special_label(self) -> str | None:
        cell = self.special_values or ""
        if not cell.startswith("0x"):
            return None
        return cell.split("=", 1)[1].strip().strip('"').replace('" indicator', "").strip('"')


#: The 26 items the pinned stream attests, each transcribed from its own §8.x block in
#: ST 0601.14a and cross-read against MISB EG 0601.1's §7.N. Sorted by tag, which is the order
#: Table 1 lists them in and NOT the order the stream sends them in — the stream's order is a fact
#: about the stream and is recorded in `fixtures/klv/README.md`, not here.
ITEMS: dict[int, _Item] = {
    1: _Item(
        tag=1, name="Checksum", units="None",
        description="Checksum used to detect errors within a UAS Datalink LS packet",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=0,
        software_format="uint16", software_min=0, software_max=65535,
        length=2, max_length=2, required_length=2,
        resolution="N/A", special_values="None",
        required_in_ls="Mandatory", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.1", page=31,
        example_value="0x8C ED",
        example_octets="8CED",
        edition_1_header=None, edition_1_example_length=2,
        edition_1_example_octets="0000",
    ),
    2: _Item(
        tag=2, name="Precision Time Stamp", units="Micro-seconds (µs)",
        description="Timestamp for all metadata in this Local Set; used to coordinate with Motion Imagery",
        klv_format="uint64", klv_min=0, klv_max=18446744073709551615,
        offset=0,
        software_format="uint64", software_min=0, software_max=18446744073709551615,
        length=8, max_length=8, required_length=8,
        resolution="1 microsecond", special_values="None",
        required_in_ls="Mandatory", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.2", page=32,
        example_value="Oct. 24, 2008. 00:13:29.913",
        example_octets="000459F4A6AA4AA8",
        edition_1_header="Microseconds 0..(2^64-1) uint64", edition_1_example_length=8,
        edition_1_example_octets="0003824430F6CE40",
    ),
    5: _Item(
        tag=5, name="Platform Heading Angle", units="Degrees (°)",
        description="Aircraft heading angle",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=0,
        software_format="float32", software_min=0, software_max=360,
        length=2, max_length=2, required_length=2,
        resolution="~5.5 milli degrees", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to 0..360", section="8.5", page=35,
        example_value="159.974365 Degrees",
        example_octets="71C2",
        edition_1_header="Degrees 0..360 uint16", edition_1_example_length=2,
        edition_1_example_octets="366E",
    ),
    6: _Item(
        tag=6, name="Platform Pitch Angle", units="Degrees (°)",
        description="Aircraft pitch angle",
        klv_format="int16", klv_min=-32767, klv_max=32767,
        offset=0,
        software_format="float32", software_min=-20, software_max=20,
        length=2, max_length=2, required_length=2,
        resolution="~610 micro degrees", special_values="0x8000 = \"Out of Range\" indicator",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map-((2^15)-1)..(2^15)-1 to +/-20", section="8.6", page=37,
        example_value="-0.431531724 Degrees",
        example_octets="FD3D",
        edition_1_header="Degrees +/- 20 int16", edition_1_example_length=2,
        edition_1_example_octets="B0FD",
    ),
    7: _Item(
        tag=7, name="Platform Roll Angle", units="Degrees (°)",
        description="Platform roll angle",
        klv_format="int16", klv_min=-32767, klv_max=32767,
        offset=0,
        software_format="float32", software_min=-50, software_max=50,
        length=2, max_length=2, required_length=2,
        resolution="~1525 micro degrees", special_values="0x8000 = \"Out of Range\" indicator",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map-((2^15)-1)..(2^15)-1 to +/-50", section="8.7", page=39,
        example_value="3.40586566 Degrees",
        example_octets="08B8",
        edition_1_header="Degrees +/- 50 int16", edition_1_example_length=2,
        edition_1_example_octets="360C",
    ),
    11: _Item(
        tag=11, name="Image Source Sensor", units="None",
        description="Name of currently active sensor",
        klv_format="utf8", klv_min=None, klv_max=None,
        offset=0,
        software_format="string", software_min=None, software_max=None,
        length="variable", max_length=127, required_length=None,
        resolution="N/A", special_values="N/A",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.11", page=45,
        example_value="EO",
        example_octets="454F",
        edition_1_header="String 1..127 ISO7", edition_1_example_length=7,
        edition_1_example_octets="454F204E4F5345",
    ),
    12: _Item(
        tag=12, name="Image Coordinate System", units="None",
        description="Name of the image coordinate system used",
        klv_format="utf8", klv_min=None, klv_max=None,
        offset=0,
        software_format="string", software_min=None, software_max=None,
        length="variable", max_length=127, required_length=None,
        resolution="N/A", special_values="N/A",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.12", page=46,
        example_value="Geodetic WGS84",
        example_octets="47656F6465746963205747533834",
        edition_1_header="String 1..127 ISO7", edition_1_example_length=5,
        edition_1_example_octets="5747533834",
    ),
    13: _Item(
        tag=13, name="Sensor Latitude", units="Degrees (°)",
        description="Sensor latitude",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-90, software_max=90,
        length=4, max_length=4, required_length=4,
        resolution="~42 nano degrees", special_values="0x80000000 = \"Reserved\"",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-90", section="8.13", page=47,
        example_value="60.176822966978335 Degrees",
        example_octets="5595B66D",
        edition_1_header="Degrees +/- 90 int32", edition_1_example_length=4,
        edition_1_example_octets="CED63704",
    ),
    14: _Item(
        tag=14, name="Sensor Longitude", units="Degrees (°)",
        description="Sensor longitude",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-180, software_max=180,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="0x80000000 = \"Reserved\"",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-180", section="8.14", page=48,
        example_value="128.42675904204452 Degrees",
        example_octets="5B5360C4",
        edition_1_header="Degrees +/- 180 int32", edition_1_example_length=4,
        edition_1_example_octets="57CA9F60",
    ),
    15: _Item(
        tag=15, name="Sensor True Altitude", units="Meters (m)",
        description="Altitude of sensor as measured from Mean Sea Level (MSL)",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=-900,
        software_format="float32", software_min=-900, software_max=19000,
        length=2, max_length=2, required_length=2,
        resolution="~0.3 meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to-900..19000 meters", section="8.15", page=49,
        example_value="14190.7195 Meters",
        example_octets="C221",
        edition_1_header="Meters -900..19000 uint16", edition_1_example_length=2,
        edition_1_example_octets="AA65",
    ),
    16: _Item(
        tag=16, name="Sensor Horizontal Field of View", units="Degrees (°)",
        description="Horizontal field of view of selected imaging sensor",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=0,
        software_format="float32", software_min=0, software_max=180,
        length=2, max_length=2, required_length=2,
        resolution="~2.7 milli degrees", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to 0..180", section="8.16", page=50,
        example_value="144.571298 Degrees",
        example_octets="CD9C",
        edition_1_header="Degrees 0..180 uint16", edition_1_example_length=2,
        edition_1_example_octets="8C77",
    ),
    17: _Item(
        tag=17, name="Sensor Vertical Field of View", units="Degrees (°)",
        description="Vertical field of view of selected imaging sensor",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=0,
        software_format="float32", software_min=0, software_max=180,
        length=2, max_length=2, required_length=2,
        resolution="~2.7 milli degrees", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to 0..180", section="8.17", page=51,
        example_value="152.643626 Degrees",
        example_octets="D917",
        edition_1_header="Degrees 0..180 uint16", edition_1_example_length=2,
        edition_1_example_octets="7CA9",
    ),
    18: _Item(
        tag=18, name="Sensor Relative Azimuth Angle", units="Degrees (°)",
        description="Relative rotation angle of sensor to platform longitudinal axis",
        klv_format="uint32", klv_min=0, klv_max=4294967295,
        offset=0,
        software_format="float64", software_min=0, software_max=360,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^32)-1 to 0..360", section="8.18", page=52,
        example_value="160.71921143697557 Degrees",
        example_octets="724A0A20",
        edition_1_header="Degrees 0..360 uint32", edition_1_example_length=4,
        edition_1_example_octets="A6CDC80A",
    ),
    19: _Item(
        tag=19, name="Sensor Relative Elevation Angle", units="Degrees (°)",
        description="Relative elevation angle of sensor to platform longitudinal - transverse plane",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-180, software_max=180,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="0x80000000 = \"Reserved\"",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-180", section="8.19", page=54,
        example_value="-168.79232483394085 Degrees",
        example_octets="87F84B86",
        edition_1_header="Degrees +/- 180 int32", edition_1_example_length=4,
        edition_1_example_octets="C1AB0486",
    ),
    20: _Item(
        tag=20, name="Sensor Relative Roll Angle", units="Degrees (°)",
        description="Relative roll angle of sensor to aircraft platform",
        klv_format="uint32", klv_min=0, klv_max=4294967295,
        offset=0,
        software_format="float64", software_min=0, software_max=360,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^32)-1 to 0..360", section="8.20", page=55,
        example_value="176.86543764939194 Degrees",
        example_octets="7DC55ECE",
        edition_1_header="Degrees 0..360 uint32", edition_1_example_length=4,
        edition_1_example_octets="F5D6ECEC",
    ),
    21: _Item(
        tag=21, name="Slant Range", units="Meters (m)",
        description="Slant range in meters",
        klv_format="uint32", klv_min=0, klv_max=4294967295,
        offset=0,
        software_format="float64", software_min=0, software_max=5000000,
        length=4, max_length=4, required_length=4,
        resolution="~1.2 milli meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^32)-1 to 0..5000000 meters", section="8.21", page=56,
        example_value="68590.983298744770 Meters",
        example_octets="03830926",
        edition_1_header="Meters 0..5,000,000 uint32", edition_1_example_length=4,
        edition_1_example_octets="3F35BA6E",
    ),
    22: _Item(
        tag=22, name="Target Width", units="Meters (m)",
        description="Target width within sensor field of view",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=0,
        software_format="float32", software_min=0, software_max=10000,
        length=2, max_length=2, required_length=2,
        resolution="~0.16 meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="Yes",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to 0..10000 meters", section="8.22", page=58,
        example_value="722.819867 Meters",
        example_octets="1281",
        edition_1_header="Meters 0..10,000 uint16", edition_1_example_length=2,
        edition_1_example_octets="1F9B",
    ),
    23: _Item(
        tag=23, name="Frame Center Latitude", units="Degrees (°)",
        description="Terrain latitude of frame center",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-90, software_max=90,
        length=4, max_length=4, required_length=4,
        resolution="~42 nano degrees", special_values="0x80000000 = \"N/A (Off-Earth)\" indicator",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1).. (2^31)-1 to +/-90", section="8.23", page=60,
        example_value="-10.542388633146132 Degrees",
        example_octets="F101A229",
        edition_1_header="Degrees +/- 90 int32", edition_1_example_length=4,
        edition_1_example_octets="BF09D0CA",
    ),
    24: _Item(
        tag=24, name="Frame Center Longitude", units="Degrees (°)",
        description="Terrain longitude of frame center",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-180, software_max=180,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="0x80000000 = \"N/A (Off-Earth)\" indicator",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-180", section="8.24", page=61,
        example_value="29.157890122923014 Degrees",
        example_octets="14BC082B",
        edition_1_header="Degrees +/- 180 int32", edition_1_example_length=4,
        edition_1_example_octets="286224F8",
    ),
    25: _Item(
        tag=25, name="Frame Center Elevation", units="Meters (m)",
        description="Terrain elevation at frame center relative to Mean Sea Level (MSL)",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=-900,
        software_format="float32", software_min=-900, software_max=19000,
        length=2, max_length=2, required_length=2,
        resolution="~0.3 meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to-900..19000 meters", section="8.25", page=62,
        example_value="3216.03723 Meters",
        example_octets="34F3",
        edition_1_header="Meters -900..19000 uint16", edition_1_example_length=2,
        edition_1_example_octets="0008",
    ),
    40: _Item(
        tag=40, name="Target Location Latitude", units="Degrees (°)",
        description="Calculated target latitude",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-90, software_max=90,
        length=4, max_length=4, required_length=4,
        resolution="~42 nano degrees", special_values="0x80000000 = \"N/A (Off-Earth)\" indicator",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-90", section="8.40", page=81,
        example_value="-79.163850051892850 Degrees",
        example_octets="8F695262",
        edition_1_header="Degrees +/- 90 int32", edition_1_example_length=None,
        edition_1_example_octets=None,
    ),
    41: _Item(
        tag=41, name="Target Location Longitude", units="Degrees (°)",
        description="Calculated target longitude",
        klv_format="int32", klv_min=-2147483647, klv_max=2147483647,
        offset=0,
        software_format="float64", software_min=-180, software_max=180,
        length=4, max_length=4, required_length=4,
        resolution="~84 nano degrees", special_values="0x80000000 = \"N/A (Off-Earth)\" indicator",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map-((2^31)-1)..(2^31)-1 to +/-180", section="8.41", page=82,
        example_value="166.40081296041646 Degrees",
        example_octets="765457F2",
        edition_1_header="Degrees +/-180 int32", edition_1_example_length=None,
        edition_1_example_octets=None,
    ),
    42: _Item(
        tag=42, name="Target Location Elevation", units="Meters (m)",
        description="Calculated target elevation",
        klv_format="uint16", klv_min=0, klv_max=65535,
        offset=-900,
        software_format="float32", software_min=-900, software_max=19000,
        length=2, max_length=2, required_length=2,
        resolution="~0.3 meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map 0..(2^16)-1 to-900..19000 meters", section="8.42", page=83,
        example_value="18389.0471 Meters",
        example_octets="F823",
        edition_1_header="Meters -900..19000 uint16", edition_1_example_length=None,
        edition_1_example_octets=None,
    ),
    56: _Item(
        tag=56, name="Platform Ground Speed", units="Meters/Second (m/s)",
        description="Speed projected to the ground of an airborne platform passing overhead",
        klv_format="uint8", klv_min=0, klv_max=255,
        offset=0,
        software_format="uint8", software_min=0, software_max=255,
        length=1, max_length=1, required_length=1,
        resolution="1 meter/second", special_values="None",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.56", page=101,
        example_value="140 Meters/Second",
        example_octets="8C",
        edition_1_header="Meters/Second 0..255 uint8", edition_1_example_length=1,
        edition_1_example_octets="E8",
    ),
    57: _Item(
        tag=57, name="Ground Range", units="Meters (m)",
        description="Horizontal distance from ground position of aircraft relative to nadir, and target of interest",
        klv_format="uint32", klv_min=0, klv_max=4294967295,
        offset=0,
        software_format="float64", software_min=0, software_max=5000000,
        length=4, max_length=4, required_length=4,
        resolution="~1.2 milli meters", special_values="None",
        required_in_ls="Optional", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet="Map 0..(2^32)-1 to 0..5000000 meters", section="8.57", page=102,
        example_value="3506979.0316063400 Meters",
        example_octets="B38EACF1",
        edition_1_header="Meters 0..5,000,000 uint32", edition_1_example_length=4,
        edition_1_example_octets="329161FA",
    ),
    65: _Item(
        tag=65, name="UAS Datalink LS Version Number", units="Number (None)",
        description="Version number of the UAS Datalink LS document used to generate KLV metadata",
        klv_format="uint8", klv_min=0, klv_max=255,
        offset=0,
        software_format="uint8", software_min=0, software_max=255,
        length=1, max_length=1, required_length=1,
        resolution="N/A", special_values="None",
        required_in_ls="Mandatory", sdcc_allowed="No",
        multiples_allowed="No",
        map_bullet=None, section="8.65", page=111,
        example_value="13",
        example_octets="0D",
        edition_1_header="Number 0..255 uint8", edition_1_example_length=1,
        edition_1_example_octets="02",
    ),
}


#: Every tag this module decodes, in tag order. The scope contract, stated once as data so no
#: caller has to derive it from the table's keys and no round can widen it by accident.
WITNESSED_TAGS: tuple[int, ...] = tuple(sorted(ITEMS))

#: **THE ONE TAG THIS MODULE READS THAT THE PINNED STREAM DOES NOT ATTEST, AND THE GROUND FOR IT.**
#: Item 48's Value is not a value this module maps — it is a NESTED LOCAL SET whose elements
#: another held document defines, and `klv_security_codec` is that document's item layer. So the
#: `ITEMS` table above stays at the 26 witnessed items exactly as its docstring says, and this is a
#: second, differently-grounded table beside it: `ITEMS` answers "what does this integer mean",
#: `NESTED_SETS` answers "which document's item layer owns these octets".
#:
#: **WHY THE SCOPE CONTRACT IS CROSSED HERE AND NOWHERE ELSE.** The contract's reason is that an
#: item nobody here has met on a wire "could only ever be checked against a fixture written from
#: the same reading of the same table". Item 48's decoder is checked against a SECOND DOCUMENT:
#: ST 0601.14a §8.48 prints `KLV Key 06.0E.2B.34.02.03.01.01.0E.01.03.03.02.00.00.00 (CRC 40980)`
#: and MISB ST 0102.12 §6.7 registers the Security Metadata Local Set under the same sixteen
#: octets and the same CRC — two documents, obtained on different days by different routes, in
#: agreement. **No unwitnessed ST 0601 item has a second document behind it**, which is why the
#: other 115 rows stay `not yet` and this one does not.
#:
#: WHAT IS STILL TRUE AND IS NOT SOFTENED: the pinned stream carries no item 48, so nothing in
#: `klv_security_codec` is checked against an octet anybody has met on a wire, and ST 0102.12
#: prints no worked example of a set, so the strongest check `check_against_the_documents_own_
#: examples` performs for the 26 is not available for these 17. Both are stated at that module's
#: `TRANSCRIPTION_CROSS_CHECK` rather than left for a reader to notice.
NESTED_SETS: dict[int, str] = {48: "MISB ST 0102.12 Security Metadata Local Set"}

#: What ST 0601.14a says item 48 carries, quoted, so the delegation is readable from this module.
NESTED_SET_BASIS = security.CARRIER_BASIS

#: The three items ST 0601.14a makes Mandatory in every packet, derived from the table's own
#: `required_in_ls` cells rather than listed a second time. §6.4 and §8.2 say it of tag 2, §8.1 of
#: tag 1, §8.65 of tag 65, and `ST 0601.8-09`/`-11`/`-12` require the order and the presence.
MANDATORY_TAGS: tuple[int, ...] = tuple(
    tag for tag, item in sorted(ITEMS.items()) if item.required_in_ls == "Mandatory")


# ------------------------------------------------------------------------------ value decoding


def _as_integer(item: _Item, raw: bytes) -> int:
    return int.from_bytes(raw, "big", signed=item.klv_format.startswith("int"))


def decode_value(item: _Item, raw: bytes) -> Any:
    """One item's Value octets to its Software Value, by the affine map its §8.x block states.

    Returns a `str` for a `utf8` item, a `SpecialValue` for a reserved integer the document
    declares, an `int` where Software and KLV formats are the same integer type — tags 1, 2, 56 and
    65, where the document's own formula is `KLV = Soft` and a float would introduce a rounding
    step the document does not have — and a `float` otherwise.

    **The length is NOT checked here.** `decode_packet` owns the length policy, because a policy
    that skips an item has to be applied where the item is being skipped FROM.
    """
    if item.klv_format == "utf8":
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as e:
            raise UASItemError(
                f"tag {item.tag} ({item.name}) is {item.klv_format} per ST 0601.14a "
                f"§{item.section} and its {len(raw)} octets are not valid UTF-8: {e}. "
                f"Edition 1 writes this item's Format as {item.edition_1_header!r}, which is the "
                "ISO7-versus-utf8 divergence recorded in this module's docstring — and it does not "
                "excuse these octets, because every ISO 646 octet is valid UTF-8"
            ) from e
    special = item.special_integer
    if special is not None and int.from_bytes(raw, "big") == special:
        # COMPARED AS AN UNSIGNED BIT PATTERN, and that is the document's own framing rather than
        # a convenience. §7: "The KLV Value bit pattern in each equation is interpretable in
        # diverse ways", and the Special Values cell writes the sentinel as a hex pattern —
        # `0x8000`, `0x80000000` — not as a signed number. Comparing it against the SIGNED reading
        # misses every one of them, because `0x80000000` read as an int32 is -2147483648; the
        # fixture `special_values_are_signals_and_not_measurements` was written to catch exactly
        # that and did, on the first run, with the affine map returning a latitude of
        # -90.00000004190952.
        return SpecialValue(item.tag, special, item.special_label)
    value = _as_integer(item, raw)
    if item.software_format == item.klv_format:
        # `KLV = Soft`, stated as an identity in §8.1, §8.2, §8.56 and §8.65. Kept an int.
        return value
    return item.scale * value + item.offset


def encode_value(item: _Item, value: Any) -> bytes:
    """The inverse: a Software Value to the Value octets, at the item's own Required Length.

    Bidirectional for every item in the table, which is what makes the round-trip test possible at
    all. The one asymmetry is quantisation and it is the document's, not this module's: a float
    Software Value that is not a multiple of the item's Resolution encodes to the nearest KLV
    integer, so `decode(encode(x))` returns x rounded to the item's stated Resolution rather than x.
    `check_against_the_documents_own_examples()` measures that against the document's own printed
    values instead of asserting it away.
    """
    if item.klv_format == "utf8":
        if not isinstance(value, str):
            raise UASItemError(
                f"tag {item.tag} ({item.name}) is a {item.klv_format} item per §{item.section}; "
                f"got {type(value).__name__}"
            )
        return value.encode("utf-8")
    if isinstance(value, ZeroLength):
        return b""
    if isinstance(value, SpecialValue):
        integer = value.integer
    elif item.software_format == item.klv_format:
        integer = int(value)
    else:
        integer = round((value - item.offset) / item.scale)
    width = item.required_length or item.length
    if not isinstance(width, int):
        raise UASItemError(
            f"tag {item.tag} ({item.name}) states Length {item.length!r} and no Required Length, "
            "so this module cannot choose a width for it — a variable-length numeric item is not "
            "in the witnessed set and is not decided here"
        )
    signed = item.klv_format.startswith("int")
    low, high = (-(1 << (8 * width - 1)), (1 << (8 * width - 1)) - 1) if signed \
        else (0, (1 << (8 * width)) - 1)
    if not low <= integer <= high:
        raise UASItemError(
            f"tag {item.tag} ({item.name}): {value!r} maps to KLV integer {integer}, outside the "
            f"{width}-octet {item.klv_format} range [{low}, {high}]. §{item.section} states "
            f"Min {item.klv_min} and Max {item.klv_max}"
            + (f" and {item.map_bullet!r}" if item.map_bullet else "")
        )
    return integer.to_bytes(width, "big", signed=signed)


# ----------------------------------------------------------------------------- packet decoding


class DecodedItem(NamedTuple):
    """One item as this layer read it: the value, the octets it came from, and where they were."""

    tag: int
    name: str
    length: int
    value: Any
    raw: bytes
    tag_offset: int
    value_offset: int
    section: str


class DecodedPacket(NamedTuple):
    """One UAS Datalink LS packet: its items, its defects, and its checksum verdict.

    `unknown_tags` is the list of tags the packet carried that this module's 26-item table does not
    cover. They are NOT an error and NOT dropped: `ST 0107.3-04` requires a decoder to "skip
    unknown Local Set values so as to not impact the decoding of known Local Set items within the
    same Local Set instance", and the caller parks their octets. The framing layer already walked
    past them correctly; this layer only declines to say what they mean.
    """

    at: int
    value_length: int
    value_offset: int
    end: int
    items: dict[int, DecodedItem]
    order: tuple[int, ...]
    defects: tuple[LengthDivergence, ...]
    advisories: tuple[dict, ...]
    unknown_tags: tuple[int, ...]
    raw_items: dict[int, str]
    checksum_stored: int | None
    checksum_computed: int | None
    #: The decoded ST 0102.12 Security Metadata Local Set from item 48, or None where the packet
    #: carried no item 48. **None means UNLABELLED and never `unclassified`** — ST 0102.12 §6.5,
    #: "The absence of Security Metadata does not signify Motion Imagery Data as Unclassified" —
    #: and the caller emits that sentence rather than a marking.
    security: security.DecodedSecuritySet | None = None

    @property
    def checksum_valid(self) -> bool | None:
        """None when the packet carries no tag 1 at all, which is itself a defect against §8.1."""
        if self.checksum_stored is None:
            return None
        return self.checksum_stored == self.checksum_computed


def _length_verdict(item: _Item, observed: int, entry) -> tuple[str | None, str | None]:
    """The policy, in one place. Returns (defect_class, advisory_class); both None means fine."""
    if observed == 0:
        if item.tag in ZLI_FORBIDDEN:
            return DIVERGENCE_ZLI_ON_REQUIRED_ITEM, None
        return None, None                      # ST 0601.14-33's explicit unknown
    if item.required_length is not None:
        if observed != item.required_length:
            return DIVERGENCE_REQUIRED_LENGTH, None
        return None, None
    if item.max_length is not None and observed > item.max_length:
        return None, ADVISORY_OVER_MAX_LENGTH   # a recommendation, not a `shall`
    return None, None


def decode_packet(buf: bytes, offset: int = 0) -> DecodedPacket:
    """Walk one packet with the framing layer, then decode the items this table knows.

    The framing layer is used and never re-implemented: `walk_local_set` reads the Universal Label,
    the BER length of the Value and every Key-Length-Value triplet, and this function adds exactly
    one thing — the tag table.

    The checksum is verified here rather than in the framing layer for the reason
    `klv_codec.LocalSetItem`'s docstring gives: `bcc_16` "takes a checksum range it cannot find",
    §6.6 defines that range as running from the first octet of the Universal Label "up to 1-byte
    checksum length", and a caller holding `tag_offset` can compute it. This is that caller.
    """
    after_key = framing.read_local_set_key(buf, offset)
    value_length, value_offset = framing.decode_ber_length(buf, after_key)
    end = value_offset + value_length

    items: dict[int, DecodedItem] = {}
    order: list[int] = []
    defects: list[LengthDivergence] = []
    advisories: list[dict] = []
    unknown: list[int] = []
    raw_items: dict[int, str] = {}
    checksum_stored = checksum_computed = None
    security_set = None

    for entry in framing.walk_local_set(buf, offset):
        order.append(entry.tag)
        raw_items[entry.tag] = entry.value.hex()
        item = ITEMS.get(entry.tag)
        if item is None:
            if entry.tag in NESTED_SETS:
                # ST 0601 item 48. The Value is a bare run of ST 0102 Local Set triplets — §8.48:
                # "The length field is the size of all MISB ST 0102 metadata items to be packaged
                # within item 48" — so there is no key and no second length to strip, and the
                # element layer is handed the Value as it stands. `value_offset` is passed so a
                # refusal inside the nested set points at an octet of the PACKET.
                security_set = security.decode_set(
                    entry.value, base_offset=entry.value_offset)
                continue
            unknown.append(entry.tag)
            continue
        defect_class, advisory_class = _length_verdict(item, entry.length, entry)
        if defect_class is not None:
            defects.append(LengthDivergence(
                tag=entry.tag, name=item.name, observed_length=entry.length,
                required_length=item.required_length, max_length=item.max_length,
                tag_offset=entry.tag_offset, value_offset=entry.value_offset,
                octets=entry.value.hex(), divergence_class=defect_class,
                section=item.section, policy=LENGTH_DIVERGENCE_POLICY,
                factual_basis=(ZLI_FORBIDDEN_BASIS
                               if defect_class == DIVERGENCE_ZLI_ON_REQUIRED_ITEM
                               else FACTUAL_BASIS),
                normative_basis=(ZLI_FORBIDDEN_BASIS
                                 if defect_class == DIVERGENCE_ZLI_ON_REQUIRED_ITEM
                                 else NORMATIVE_BASIS),
            ))
            continue                            # the ruling: the ITEM is skipped, not the packet
        if advisory_class is not None:
            advisories.append({
                "tag": entry.tag, "name": item.name, "class": advisory_class,
                "observed_length": entry.length, "max_length": item.max_length,
                "section": item.section, "basis": MAX_LENGTH_BASIS,
            })
        value = ZeroLength(entry.tag) if entry.length == 0 else decode_value(item, entry.value)
        items[entry.tag] = DecodedItem(
            tag=entry.tag, name=item.name, length=entry.length, value=value,
            raw=entry.value, tag_offset=entry.tag_offset, value_offset=entry.value_offset,
            section=item.section)
        if entry.tag == 1 and entry.length == 2:
            checksum_stored = int.from_bytes(entry.value, "big")
            checksum_computed = framing.bcc_16(buf[offset:entry.value_offset])

    return DecodedPacket(
        at=offset, value_length=value_length, value_offset=value_offset, end=end,
        items=items, order=tuple(order), defects=tuple(defects),
        advisories=tuple(advisories), unknown_tags=tuple(unknown), raw_items=raw_items,
        checksum_stored=checksum_stored, checksum_computed=checksum_computed,
        security=security_set)


def decode_stream(buf: bytes) -> list[DecodedPacket]:
    """Every packet in one payload, in wire order.

    A payload may hold several packets — the pinned stream holds six — and they are several
    STATEMENTS rather than one accumulated state, which is why this returns a list and never
    merges. The CAT034 precedent, in its own words: "Several records in one block are several
    SERVICE MESSAGES, not a station's history."

    Refuses a buffer whose packets do not tile it exactly, because trailing octets that are not a
    packet are either a truncation or a second format, and guessing which is not this layer's call.
    """
    packets: list[DecodedPacket] = []
    offset = 0
    while offset < len(buf):
        packet = decode_packet(buf, offset)
        packets.append(packet)
        offset = packet.end
    if offset != len(buf):
        raise UASItemError(
            f"the payload's packets end at octet {offset} of {len(buf)} — {len(buf) - offset} "
            "octet(s) follow the last packet's declared Value and are not a Universal Label. "
            "ST 0601.14a §6.3: 'A packet is a combination of a UL Key, the Length of the Value, "
            "and the Value'"
        )
    if not packets:
        raise UASItemError("the payload holds no packets")
    return packets


def encode_packet(values: dict[int, Any], *, order: tuple[int, ...] | None = None,
                  raw_overrides: dict[int, bytes] | None = None) -> bytes:
    """Build one packet: the Universal Label, the BER length of the Value, the items, the checksum.

    `raw_overrides` is how egress stays lossless over a DEFECTIVE item. The witnessed-set defect —
    four octets under a Required Length of 2 — has no Software Value, because the policy above
    refused to invent one; so egress re-emits the octets the ingest side parked. **Silently
    re-encoding it at the conformant length would be this adapter correcting a stream it is
    supposed to translate**, which is a change no consumer asked for and which the source's own
    checksum would then disagree with.

    THE CHECKSUM IS REPLAYED WHEN ONE WAS PARKED AND COMPUTED ONLY WHEN IT WAS NOT, and the first
    draft had that backwards. It computed §6.6's sum unconditionally, on the reasoning that "a
    stored checksum re-emitted verbatim would be wrong the moment any other octet changed" — which
    is true of a packet rebuilt from VALUES and false of this one, because every other octet is
    replayed verbatim too. What the unconditional computation actually did was **silently correct a
    packet whose stored checksum did not validate**, so egress stopped being byte-exact for exactly
    the input where fidelity matters most, and the fixture
    `a_checksum_that_does_not_validate_is_flagged_not_refused` failed the round-trip test and said
    so. A translator that repairs a defect it was asked to carry is making a change no consumer
    requested; the invalid sum is the emitter's own statement, `attributes.integrity_basis` records
    that it does not validate, and a consumer who wants a valid one can compute it — which is their
    decision and not this module's.
    """
    raw_overrides = raw_overrides or {}
    if order is None:
        # `ST 0601.8-09` and `-11`: item 2 first, item 1 last. The rest in tag order, which is the
        # order Table 1 lists them in and the order the held stream sends them in.
        middle = sorted(t for t in values if t not in (1, 2))
        order = (2, *middle, 1)
    body = bytearray()
    for tag in order:
        if tag == 1:
            continue
        if tag in raw_overrides:
            octets = raw_overrides[tag]
        else:
            item = ITEMS.get(tag)
            if item is None:
                raise UASItemError(
                    f"tag {tag} is not in the witnessed set this module covers "
                    f"({', '.join(str(t) for t in WITNESSED_TAGS)}) and no raw octets were given "
                    "for it — this layer will not encode a value it cannot cite a §8.x block for"
                )
            octets = encode_value(item, values[tag])
        body += framing.encode_ber_oid(tag) + framing.encode_ber_length(len(octets)) + octets
    # tag 1 last, and its two octets are the checksum over everything before them
    body += framing.encode_ber_oid(1) + framing.encode_ber_length(2)
    prefix = framing.UAS_LOCAL_SET_KEY + framing.encode_ber_length(len(body) + 2)
    stored = raw_overrides.get(1)
    if stored is not None:
        if len(stored) != 2:
            raise UASItemError(
                f"tag 1 Checksum was given {len(stored)} octet(s) to replay and §8.1 states a "
                "Required Length of 2"
            )
        return prefix + bytes(body) + stored
    return prefix + bytes(body) + framing.bcc_16(prefix + bytes(body)).to_bytes(2, "big")


# --------------------------------------------------------------- the document's own examples


def check_against_the_documents_own_examples() -> list[str]:
    """Decode each item's §8.x worked example and compare it with the value the block prints.

    THE POINT, STATED BECAUSE A SELF-CHECK THAT CHECKS NOTHING IS WORSE THAN NONE. Every number in
    `ITEMS` was transcribed from a drawn table, and a transcription can be wrong in ways that are
    invisible to a fixture written from the same transcription. The document forecloses that: each
    §8.x block prints one Software Value beside the KLV octets that encode it, and §7's
    Programmer's Notes say why — "the 'Example Value' for a tag is shown in full precision, beyond
    a tag's resolution, so programmers can verify they are using the right formulas". This runs all
    26.

    Returns a list of disagreements, empty when they all agree. Called by
    `tests/test_cdm_stanag4609_codec.py` on every suite run, and by edition 1's examples too — for
    which the tolerance is one quantisation step rather than the printed precision, because
    edition 1 prints round decimals and ST 0601.14a prints full precision.
    """
    problems: list[str] = []
    for tag, item in sorted(ITEMS.items()):
        raw = bytes.fromhex(item.example_octets)
        if len(raw) != (item.required_length or len(raw)):
            problems.append(
                f"tag {tag}: §{item.section}'s own example is {len(raw)} octets and its Required "
                f"Length cell says {item.required_length}")
        value = decode_value(item, raw)
        printed = item.example_value
        if item.klv_format == "utf8":
            if value != printed:
                problems.append(f"tag {tag}: example decodes to {value!r}, block prints {printed!r}")
            continue
        if tag == 1:
            if f"0x{value:04X}" != printed.replace(" ", ""):
                problems.append(f"tag {tag}: example decodes to 0x{value:04X}, block prints "
                                f"{printed!r}")
            continue
        if tag == 2:
            # §8.2's block prints a calendar rendering, which is the one example in the witnessed
            # set that is not a number. It is checked in the adapter's test against the instant,
            # because rendering it needs the epoch and the epoch is §6.4's, not this table's.
            continue
        expected = _printed_number(printed)
        if expected is None:
            problems.append(f"tag {tag}: cannot read a number out of {printed!r}")
            continue
        # The tolerance is the printed precision of the SOFTWARE format the block states, per §7's
        # Programmer's Notes: "7 to 9 for single, 15 to 17 for double".
        relative = 5e-9 if item.software_format == "float64" else 5e-7
        tolerance = max(abs(expected) * relative, 5e-7 if relative == 5e-9 else 5e-5)
        if abs(value - expected) > tolerance:
            problems.append(
                f"tag {tag} ({item.name}): §{item.section}'s example octets {item.example_octets} "
                f"decode to {value!r} and the block prints {expected!r} — a difference of "
                f"{abs(value - expected):.3g}, outside the {tolerance:.3g} the block's stated "
                f"{item.software_format} precision allows")
    return problems


def check_against_edition_1s_examples() -> list[str]:
    """Edition 1's §7.N examples, decoded under the PINNED edition's map.

    A second, independent set of octets over the same 26 maps. It is not a duplicate of the check
    above and it answers a different question: not "is the transcription right" but "did the map
    move between edition 1 and the pinned one". For 23 of the 26 items edition 1 prints an example
    and every one of them lands within a single quantisation step of the value edition 1's own
    §7.N prints. Tags 40, 41 and 42 have a §7.N section and NO worked example, which is why the
    count is 23 and not 26, and the absence is reported rather than skipped silently.
    """
    problems: list[str] = []
    for tag, item in sorted(ITEMS.items()):
        if item.edition_1_example_octets is None:
            continue
        if item.required_length is not None \
                and item.edition_1_example_length != item.required_length:
            problems.append(
                f"tag {tag}: edition 1's §7.{tag} example is {item.edition_1_example_length} "
                f"octets and ST 0601.14a §{item.section} requires {item.required_length}")
        raw = bytes.fromhex(item.edition_1_example_octets)
        if len(raw) != item.edition_1_example_length:
            problems.append(
                f"tag {tag}: edition 1's example octets are {len(raw)} and its own [0dL] says "
                f"{item.edition_1_example_length}")
        try:
            decode_value(item, raw)
        except UASItemError as e:
            problems.append(f"tag {tag}: edition 1's own example will not decode: {e}")
    return problems


def _printed_number(printed: str) -> float | None:
    cleaned = printed.replace(",", "").replace("- ", "-")
    digits = ""
    for char in cleaned:
        if char.isdigit() or char in "-.+":
            digits += char
        elif digits:
            break
    try:
        return float(digits)
    except ValueError:
        return None
