"""The ST 0601.14a PACK layer: §6.3's VLP/DLP/FLP grammar, and the two items whose Value is a pack.

WHAT THIS MODULE IS, AND WHY IT IS ITS OWN MODULE RATHER THAN A TABLE IN `klv_uas_codec`
----------------------------------------------------------------------------------------
`klv_codec` frames, `klv_uas_codec` is the ITEM layer for one document, `imapb_codec` maps one
item's value when that item's Format says to, and this module reads the two items whose Value is
not a value at all but a **nested structure with its own grammar** — tag 128 Wavelengths List and
tag 130 Airbase Locations.

**THE PLACEMENT WAS CHOSEN ON THE PARK 2 PRECEDENT, AND THAT PRECEDENT'S DECISIVE REASON DOES NOT
APPLY HERE.** `klv_security_codec`'s docstring gives three reasons for being its own module and
names the second as decisive. Taken one at a time against this layer:

1. *"The precedent is one item layer per document."* **Points the other way.** This module reads
   MISB ST 0601.14a — the same document `klv_uas_codec` reads and cites by SHA-256 — so a reader
   asking "which copy is this read from" gets the same answer from either file, which is the
   property that reason was protecting.
2. *"THE TAG NUMBERS COLLIDE, AND `ITEMS` IS KEYED ON THE TAG."* **Does not apply at all.** A VLP
   is "a group of items represented as length-value pairs **with the item's tags suppressed**"
   (§6.3). A pack member has no tag to collide with anything — it has a position in a stated order
   and a Universal Label in a table the section prints. There is no second `dict[int, ...]` here.
3. *"The value maps have nothing in common."* **Applies, and it is what carried the decision.**
   `klv_uas_codec._Item` has twenty-seven fields describing ONE affine map over ONE integer:
   `klv_min`, `klv_max`, `offset`, `software_min`, `software_max`, `required_length`, a single
   `example_octets`. A wavelength record is a BER-OID integer, two IMAPB values and a utf8 string
   whose length is computed by subtraction. It cannot be an `_Item` row, and a table of packs
   inside the item layer would be a second grammar living under a docstring that promises a tag
   table.

**SO THE BASIS FOR THIS FILE'S EXISTENCE IS WEAKER THAN park 2's WAS, AND IS STATED RATHER THAN
BORROWED.** Park 2 had a collision that made one module impossible; this has a shape mismatch that
makes one module unpleasant, plus the split the framing layer already draws: §6.3 is a GRAMMAR
section, like the BER rules `klv_codec` owns, and a grammar belongs beside a grammar rather than
inside a table of values. A later round that folds this into `klv_uas_codec` would not be undoing
a rule; it would be re-weighing reason 3, and this paragraph is what it should re-weigh.

§6.3's GRAMMAR, TRANSCRIBED, BECAUSE EVERY LENGTH BELOW IS READ WITH IT
-----------------------------------------------------------------------
Read from the pinned copy at `fixtures/klv/spec/ST0601.14a.pdf`, SHA-256 `3d5f1ca1…ab212ce4`,
§6.3 pages 6-7:

* **VLP** — "A VLP is a group of items represented as length-value pairs with the item's tags
  suppressed. **Lengths in BER short or long form precede each item's value.** The VLP is
  constructed as a KLV triplet, where the Tag in Figure 2 is the tag for the VLP. The Length
  (Total) (in BER short or long form) represents the sum of all length-value pairs that follow."
  So the per-value lengths are the SAME BER grammar the framing layer already owns, and
  `klv_codec.decode_ber_length` is what reads them. Nothing unheld is needed for this: the rule is
  in the governing document, and its grammar is ST 0107.3 §6.3.2's, which is park 4's closed
  document.
* **the zeroed element** — "One exception to this pattern is where a length-value pair's value is
  unknown. In this case the length for the value is zero (0) and the value is omitted. This
  preserves the defined order of the pack in cases where a value is unknown or omitted." So a
  zero length inside a VLP is a POSITION HELD OPEN and never a member that is absent — the same
  distinction `klv_uas_codec.ZeroLength` draws one layer up, and `decode_vlp` preserves it by
  returning `b""` in place rather than dropping the pair.
* **DLP** — "a group of items, each with pre-defined or computable length. … The item definitions
  (in Section 8) which utilize a DLP provides the pre-defined lengths or methods of computing the
  length of each item within the DLP. **A DLP does not allow undefined values.**"
* **FLP** — "A DLP specification can vary the size of the final element, and when this occurs the
  DLP is then a Floating Length Pack (FLP). FLPs allow the final value to be a variable length
  value such as a string. To compute the length of the final value all previous element lengths
  are determined and subtracting from the Length (Total)."
* **truncation** — "Both VLP and DLP structures become truncation packs when removing one or more
  of their items at the end of the" pack.

**A DLP CARRIES NO LENGTHS OF ITS OWN AND THAT IS THE TRAP.** A VLP's members are self-delimiting
and a DLP's are not: a DLP is decodable only against the member widths its own §8.x section
states. So there is no generic `decode_dlp` here. Each pack that contains a DLP reads it with its
own section's widths, and a member whose width the section does not state is not decodable by
guessing — which is exactly what happens to tag 130 below.

WHAT IS IMPLEMENTED, AND WHAT IS RECORDED AND NOT IMPLEMENTED
--------------------------------------------------------------
**Tag 128 Wavelengths List is implemented and is checked against §8.128's own worked example.**
The section prints one, `0D 15 0000 07D0 0000 0FA0 4E4E 4952` against the Software Value
`21,1000, 2000, NNIR (Narrow NIR)`, and `check_against_the_documents_own_example()` decodes those
octets and compares all four members on every suite run. That is the document-side witness
RULING 1 (2026-09-04) names — "a document-side check as strong as a worked example" — and it is
why this tag's row moves.

**Tag 130 Airbase Locations is NOT implemented, on two grounds this module states rather than
works around**, and its row therefore stays `not yet`:

1. **§8.130 PRINTS NO WORKED EXAMPLE.** Its summary table's Example Software Value cell reads
   `N/A` and its Example KLV Item row reads `8102 - N/A`. RULING 1's reopen condition is a
   document-side check *as strong as a worked example*, and for this item there is no worked
   example to be as strong as. The condition is not met, and the other half — a second pinned
   stream — is not met either.
2. **THE DOCUMENT CONTRADICTS ITSELF ABOUT THE HAE MEMBER'S RANGE, AND NOTHING ARBITRATES IT.**
   Figure 60 and Figure 61 both label the third member `IMAPB(-900, 9000,3)`; the prose of §8.130.1
   says "For HAE with a range **from -600 to 9000 meters** and similar precisions (1 meter or
   better) requires using three bytes. Using **IMAPB(-600, 9000, 3)** provides 0.19 cm of
   precision." Two statements of `a`, 300 metres apart, in one section. **The precision figure
   does not discriminate between them**: `1/sF` is `1/512` m for both, because 9600 and 9900 fall
   in the same power-of-two bracket, so the one number that could have settled it is equal on
   both readings. Every three octets of HAE therefore decode to two values 300 m apart, and
   choosing one would be this repository legislating an altitude.

See `AIRBASE_LOCATIONS_LAYOUT` for everything the section does state, transcribed, so the round
that settles the range does not have to re-read the section to write the decoder.

**THE OTHER PACK ITEMS OF ST 0601.14a ARE OUT OF SCOPE AND ARE NOT PARKED HERE.** Tags 81
(Image Horizon Pixel Pack), 102 (SDCC-FLP), 138 (Payload List), 140 (Weapons Stores) and 141
(Waypoint List) are packs too. None is one of park 5's sixteen — park 5's enumeration is the
sections that name IMAPB — and tag 102's layout is MISB ST 1010's, which is not held. They are
named here only so that a reader does not read this module's two entries as the document's two
packs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from synapse_cdm.adapters import imapb_codec as imapb
from synapse_cdm.adapters import klv_codec as framing

__all__ = [
    "PackError", "WavelengthRecord", "PREDEFINED_WAVELENGTHS", "WAVELENGTH_RECORD_LAYOUT",
    "AIRBASE_LOCATIONS_LAYOUT", "AIRBASE_LOCATIONS_NOT_DECODED", "PACK_ITEMS",
    "WAVELENGTHS_LIST_EXAMPLE", "decode_vlp", "decode_wavelength_record",
    "decode_wavelengths_list", "decode_airbase_locations",
    "check_against_the_documents_own_example",
]

#: The pinned copy every citation in this module is read from, stated here for the reason
#: `klv_uas_codec` states it: a module that cites sections without naming the copy cites a memory.
SOURCE_ST_0601_14A = (
    "MISB ST 0601.14a, SHA-256 "
    "3d5f1ca105befe6f48023a3cdd29262883d6b77c73c06ba915c4da91ab212ce4, "
    "fixtures/klv/spec/ST0601.14a.pdf"
)


class PackError(ValueError):
    """A pack this module refuses to decode, with the clause that decides it."""


# ------------------------------------------------------------------ §6.3, the VLP grammar


def decode_vlp(value: bytes, *, base_offset: int = 0) -> list[bytes]:
    """Split a Variable Length Pack's Value into its member values, in the pack's own order.

    §6.3: "Lengths in BER short or long form precede each item's value", and the Length (Total) —
    which is the KLV item's own length and is therefore already consumed by the caller — "represents
    the sum of all length-value pairs that follow". So this walks pairs to the end of the buffer
    and refuses a buffer that does not tile exactly.

    **A ZERO LENGTH IS A MEMBER AND NOT AN ABSENCE.** It comes back as `b""` in position, on §6.3's
    own exception: "the length for the value is zero (0) and the value is omitted. This preserves
    the defined order of the pack". Dropping the pair would renumber every member after it, which
    for a pack whose members are identified BY POSITION is not a lossy read but a wrong one.

    `base_offset` is carried so a refusal names an octet of the PACKET rather than of the Value,
    which is the arrangement `klv_security_codec.decode_set` uses for the same reason.
    """
    members: list[bytes] = []
    offset = 0
    while offset < len(value):
        try:
            length, after = framing.decode_ber_length(value, offset)
        except framing.KLVFramingError as e:
            raise PackError(
                f"a VLP member's length at octet {base_offset + offset} is not a BER length: {e}. "
                f"ST 0601.14a §6.3: 'Lengths in BER short or long form precede each item's value'"
            ) from e
        end = after + length
        if end > len(value):
            raise PackError(
                f"a VLP member at octet {base_offset + offset} declares {length} octet(s) and only "
                f"{len(value) - after} remain in the pack. §6.3's Length (Total) 'represents the "
                f"sum of all length-value pairs that follow', so a member running past the end is "
                f"either a truncation or a length read under the wrong grammar, and which is not "
                f"this layer's call"
            )
        members.append(value[after:end])
        offset = end
    return members


# ------------------------------------------------------- tag 128, Wavelengths List (§8.128)

#: §8.128.1's four fields, in the order the section states them, with each member's encoding.
#: Transcribed rather than inferred from the worked example: the example carries one record and a
#: one-record example cannot show which of four fields is variable.
WAVELENGTH_RECORD_LAYOUT: Final[tuple[tuple[str, str], ...]] = (
    ("wavelength_id", "BER-OID encoded integer, one or more octets, self-describing"),
    ("min_nm", "IMAPB(0, 1e9, 4) — four octets"),
    ("max_nm", "IMAPB(0, 1e9, 4) — four octets"),
    ("name", "utf8, 'a utf8 string of characters with varying length'"),
)

#: §8.128.1, quoted, because this is the sentence that makes the record decodable at all.
WAVELENGTH_RECORD_BASIS = (
    "ST 0601.14a §8.128.1: 'The Wavelengths List item is a list of wavelength records formatted as "
    "a Variable Length Pack (VLP). Each value of the VLP is a separate wavelength record formatted "
    "as a Floating Length Pack (FLP). The FLP consists of four fields, in order: Wavelength ID, "
    "Min Wavelength, Max Wavelength and Wavelength Name. The Wavelength ID is a BER-OID encoded "
    "integer. The Wavelength Min and Wavelength Max values are IMAPB(0,1e9,4) which provides a "
    "precision of ~1/2 a nanometer, and covers the spectrum range from X-Rays to VHF. The "
    "Wavelength Name is a utf8 string of characters with varying length.' The name's length is the "
    "FLP rule applied by the section itself: 'Namelen = Length1 - (BEROIDlen + 8)'"
)

#: The unit is NANOMETRES and the document's own precision figure is what fixes it. §8.128.1 says
#: `IMAPB(0,1e9,4)` "provides a precision of ~1/2 a nanometer" — and `1/sF` for that range at four
#: octets is exactly 0.5 — so the mapped quantity is counted in nanometres. Table 14's own records
#: are stated in nm as well, which is the second statement. Recorded because a wavelength codec
#: that is out by a factor of a thousand returns a number.
WAVELENGTH_UNITS = "nm"
WAVELENGTH_MIN = 0.0
WAVELENGTH_MAX = 1e9
WAVELENGTH_MEMBER_OCTETS = 4


@dataclass(frozen=True, slots=True)
class WavelengthRecord:
    """One §8.128 wavelength record, decoded.

    `min_nm` and `max_nm` are `float` for a normal value and an `imapb.Special` for a §7.2.3
    signal — never both and never a Special silently mapped to a number, which is the ruling
    `imapb_codec.decode` already carries and this type propagates rather than flattening.
    """

    wavelength_id: int
    min_nm: float | imapb.Special
    max_nm: float | imapb.Special
    name: str
    octets: bytes


def decode_wavelength_record(raw: bytes, *, index: int = 0) -> WavelengthRecord:
    """One FLP wavelength record. The four fields §8.128.1 states, in its order."""
    if not raw:
        raise PackError(
            f"wavelength record {index} is zero-length. §6.3's zeroed element preserves a "
            f"POSITION in a pack of fixed membership; §8.128's VLP is a LIST whose every value 'is "
            f"a separate wavelength record', so an empty record is not a held-open position but a "
            f"record with no Wavelength ID, and §8.128.1 makes the ID Mandatory (Table 15, M)"
        )
    try:
        wavelength_id, after_id = framing.decode_ber_oid(raw, 0)
    except framing.KLVFramingError as e:
        raise PackError(
            f"wavelength record {index}'s Wavelength ID is not a BER-OID integer: {e}") from e
    needed = after_id + 2 * WAVELENGTH_MEMBER_OCTETS
    if len(raw) < needed:
        raise PackError(
            f"wavelength record {index} is {len(raw)} octet(s) and its Wavelength ID takes "
            f"{after_id}, leaving {len(raw) - after_id} for two four-octet IMAPB members that need "
            f"{2 * WAVELENGTH_MEMBER_OCTETS}. §8.128.1's own name-length rule is "
            f"'Namelen = Length1 - (BEROIDlen + 8)', which is negative here — so these octets are "
            f"not a wavelength record and no member of them is read"
        )
    min_raw = raw[after_id:after_id + WAVELENGTH_MEMBER_OCTETS]
    max_raw = raw[after_id + WAVELENGTH_MEMBER_OCTETS:needed]
    name_raw = raw[needed:]
    try:
        name = name_raw.decode("utf-8")
    except UnicodeDecodeError as e:
        raise PackError(
            f"wavelength record {index}'s Wavelength Name is {len(name_raw)} octet(s) and is not "
            f"valid UTF-8: {e}. §8.128.1 states the member as 'a utf8 string of characters with "
            f"varying length' and Table 15 types it `utf8`"
        ) from e
    return WavelengthRecord(
        wavelength_id=wavelength_id,
        min_nm=imapb.decode(WAVELENGTH_MIN, WAVELENGTH_MAX, min_raw),
        max_nm=imapb.decode(WAVELENGTH_MIN, WAVELENGTH_MAX, max_raw),
        name=name,
        octets=raw,
    )


def decode_wavelengths_list(value: bytes, *, base_offset: int = 0) -> list[WavelengthRecord]:
    """Tag 128's whole Value: a VLP whose every member is an FLP wavelength record."""
    return [decode_wavelength_record(member, index=index)
            for index, member in enumerate(decode_vlp(value, base_offset=base_offset))]


#: §8.128's Table 14, transcribed. NOT used to decode anything — a custom record's ID "begins at
#: ID 21" and the predefined six are what IDs 1-6 MEAN — and carried because a consumer reading a
#: decoded record with ID 3 needs the table that names it, and the table is in the document rather
#: than on the wire. IDs 7-20 are "Reserved for future use" and are stated as such rather than
#: omitted, so a record arriving with ID 12 is recognisably in the reserved band.
PREDEFINED_WAVELENGTHS: Final[dict[int, tuple[float, float, str, str]]] = {
    1: (380.0, 750.0, "VIS", "Visible light"),
    2: (750.0, 100_000.0, "IR", "Infrared"),
    3: (750.0, 3000.0, "NIR", "Near/Short Wave Infrared"),
    4: (3000.0, 8000.0, "MIR", "Mid-wave Infrared"),
    5: (8000.0, 14000.0, "LIR", "Long-wave Infrared"),
    6: (14000.0, 100_000.0, "FIR", "Far-Infrared"),
}
PREDEFINED_WAVELENGTHS_RESERVED = tuple(range(7, 21))
PREDEFINED_WAVELENGTHS_BASIS = (
    "ST 0601.14a §8.128.1 Table 14, 'Predefined Wavelength Information Records'. IDs 7-20 read "
    "'Reserved / Reserved / Reserved for future use'; 'Custom wavelength records begin at ID 21 "
    "and increment as needed' and 'A custom wavelength record persists only for a given flight'"
)

#: §8.128's own Example Software Value and Example KLV Item, transcribed by hand from the printed
#: block. The Tag/Len octets are recorded beside the Value because §8.128 is one of the two rows
#: whose tag needs two octets of BER-OID — `8100` is 128 — and a reader checking this against the
#: page needs the whole printed row.
WAVELENGTHS_LIST_EXAMPLE: Final[dict[str, object]] = {
    "tag_octets": "8100",
    "length_octets": "0E",
    "value_octets": "0D15000007D000000FA04E4E4952",
    "printed_software_value": "21,1000, 2000, NNIR (Narrow NIR)",
    "expected": (21, 1000.0, 2000.0, "NNIR"),
    "citation": "MISB ST 0601.14a §8.128, Example Software Value / Example KLV Item",
}


# ------------------------------------------------- tag 130, Airbase Locations (§8.130) — NOT READ

#: Everything §8.130 states about its layout, transcribed, so the round that settles the HAE range
#: writes a decoder rather than re-reads a section. The `a` of the third member is the one cell
#: this table cannot fill, and it carries both readings rather than a choice.
AIRBASE_LOCATIONS_LAYOUT: Final[dict[str, object]] = {
    "outer": (
        "a Variable Length Pack: 'The Airbase Locations VLP contains the take-off location, "
        "followed by the recovery location, with each preceded by the length of the location'"),
    "members": ("take_off_location", "recovery_location"),
    "each_member": (
        "a Location Defined Length Pack: 'Each location is described in a DLP containing IMAPB "
        "values for latitude, longitude and HAE. The latitude and longitude are each four (4) "
        "bytes and the HAE is three (3) bytes'"),
    "dlp_members": (
        ("latitude", "IMAPB(-90, 90, 4)", 4, "Mandatory (Table 16, M)"),
        ("longitude", "IMAPB(-180, 180, 4)", 4, "Mandatory (Table 16, M)"),
        ("hae", "IMAPB(-900 OR -600, 9000, 3) — SEE THE CONTRADICTION", 3,
         "Optional (Table 16, O), and bandwidth optimisation 4 truncates it when unknown"),
    ),
    "truncation_rules": (
        "1) 'Do not include the Recovery Location (i.e. truncate it), if the Take-Off Location and "
        "the Recovery Location are the same. When a receiver parses the location, if the Recovery "
        "Location is absent then the Recovery Location is set equal to the Take-Off location'; "
        "2) 'If either the Take-Off Location or Recovery Location is unknown, the length for the "
        "respective location's value is set to zero (0) … the Software Values for the location are "
        "set to an \"unknown\"'; "
        "3) 'If both the Take-Off Location and Recover Locations are unknown, Tag 130 does not "
        "appear in the Local Set'; "
        "4) 'Do not include the HAE value (i.e. truncate it) in either location if it is unknown'"),
    "max_length": "24, from the summary table's Max Length cell — two locations of eleven, plus "
                  "the two VLP lengths",
    "worked_example": None,
}

#: WHY THE DECODER IS ABSENT, in the form a caller gets when it asks for one. Both grounds, and
#: the second is the one that would still bite if the first were discharged.
AIRBASE_LOCATIONS_NOT_DECODED = (
    "tag 130 Airbase Locations is NOT decoded, on two grounds. (1) §8.130 PRINTS NO WORKED "
    "EXAMPLE — its Example Software Value cell reads 'N/A' and its Example KLV Item row reads "
    "'8102 - N/A' — so the document-side witness RULING 1 requires, 'a document-side check as "
    "strong as a worked example', does not exist for this item, and no held stream carries it "
    "either. (2) THE SECTION CONTRADICTS ITSELF ON THE HAE MEMBER'S RANGE: Figures 60 and 61 both "
    "label it IMAPB(-900, 9000,3) while §8.130.1's prose says 'a range from -600 to 9000 meters' "
    "and 'Using IMAPB(-600, 9000, 3) provides 0.19 cm of precision'. The two readings put every "
    "decoded HAE 300 m apart, and the precision figure cannot arbitrate them because 1/sF is "
    "1/512 m on both — 9600 and 9900 fall in the same power-of-two bracket, so the document's one "
    "checkable number is equal under both. Latitude and longitude are stated consistently and "
    "would decode; a pack decoded as far as its optional third member and then refused is not a "
    "row this file's status vocabulary can express, so the whole item stays `not yet`. See "
    "AIRBASE_LOCATIONS_LAYOUT for everything the section does state"
)


def decode_airbase_locations(value: bytes) -> None:
    """Refuse tag 130, naming both grounds. Not a stub: the refusal IS the finding."""
    raise framing.UnderivableFromPinnedCopy(AIRBASE_LOCATIONS_NOT_DECODED)


# ---------------------------------------------------------------------------- the crossing

#: The pack items this module reads, and the ones it declines, as ONE table so the two cannot
#: drift apart. `reads` is what `klv_uas_codec` consults; a tag with `reads=False` is here to be
#: findable, and its row in FORMAT_COVERAGE.md says the same thing in the same words.
PACK_ITEMS: Final[dict[int, dict[str, object]]] = {
    128: {
        "name": "Wavelengths List",
        "kind": "VLP of FLP records",
        "section": "8.128",
        "reads": True,
        "ground": (
            "§8.128 prints a worked example — Value 0D15000007D000000FA04E4E4952 against the "
            "Software Value '21,1000, 2000, NNIR (Narrow NIR)' — and "
            "check_against_the_documents_own_example() decodes it and compares all four members on "
            "every suite run. That is RULING 1's document-side witness, met by the document's own "
            "printed octets"),
    },
    130: {
        "name": "Airbase Locations",
        "kind": "VLP of Location DLPs (a truncation pack)",
        "section": "8.130",
        "reads": False,
        "ground": AIRBASE_LOCATIONS_NOT_DECODED,
    },
}

#: The pack tags this module actually decodes. Derived from `PACK_ITEMS` rather than listed again.
PACK_TAGS_READ: tuple[int, ...] = tuple(
    tag for tag, spec in sorted(PACK_ITEMS.items()) if spec["reads"])


# --------------------------------------------------------------- the document's own example


def check_against_the_documents_own_example() -> list[str]:
    """Decode §8.128's printed example and compare every member with the printed Software Value.

    THE SAME CHECK `klv_uas_codec.check_against_the_documents_own_examples` RUNS FOR THE 26, ON THE
    one pack that has an example to run it against. It is the whole of tag 128's witness basis, so
    it asserts all four members rather than the two IMAPB ones: a BER-OID misread and a name-length
    off by one both produce a well-formed record.

    Returns a list of disagreements, empty when the record agrees.
    """
    problems: list[str] = []
    example = WAVELENGTHS_LIST_EXAMPLE
    value = bytes.fromhex(str(example["value_octets"]))
    declared = int(str(example["length_octets"]), 16)
    if len(value) != declared:
        problems.append(
            f"tag 128: §8.128's example Value is {len(value)} octets and its printed Len cell says "
            f"{declared}")
    try:
        records = decode_wavelengths_list(value)
    except PackError as e:
        return problems + [f"tag 128: §8.128's own example will not decode: {e}"]
    if len(records) != 1:
        return problems + [
            f"tag 128: §8.128's example is one wavelength record and this decoded {len(records)}"]
    record = records[0]
    expected = example["expected"]
    got = (record.wavelength_id, record.min_nm, record.max_nm, record.name)
    if isinstance(record.min_nm, imapb.Special) or isinstance(record.max_nm, imapb.Special):
        problems.append(f"tag 128: §8.128's example read a wavelength as a §7.2.3 signal: {got!r}")
    elif got != expected:
        problems.append(
            f"tag 128 (Wavelengths List): §8.128's example octets {example['value_octets']} decode "
            f"to {got!r} and the block prints {example['printed_software_value']!r}, which is "
            f"{expected!r}")
    return problems
