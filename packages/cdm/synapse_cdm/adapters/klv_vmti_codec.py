"""The MISB ST 0903.4 VMTI layer: item 74's Value, its VTarget Packs and the sets under them.

WHAT THIS MODULE IS, AND WHAT IT DELIBERATELY IS NOT
-----------------------------------------------------
`klv_codec` frames, `klv_uas_codec` is the ITEM layer for ST 0601.14a, `klv_security_codec` reads
the one item whose Value is another document's Local Set, `klv_pack_codec` reads the two items
whose Value is a pack, and this module reads the one item whose Value is another document's
**hierarchy**: ST 0601 item 74, the VMTI Local Set, and everything ST 0903.4 defines under it.

**IT BUILDS NO CDM OBJECT AND IS WIRED INTO NO ADAPTER.** That is the round's own boundary and not
an oversight: park 6's mapping question — whether a VTarget becomes a `DETECTION` `Event`, an
`Entity`, a `Track`, or some of each — is a decision about what a consumer receives, and it is
recorded as a fork rather than answered here. What this module does is read the octets into the
document's own shapes, so that the decision is made against fields that have been decoded rather
than against fields that have been read about. `klv_uas_codec` is untouched by this round; the
wiring is the next round's, together with the mapping.

THE COPY THIS IS READ FROM
---------------------------
Every clause cited below was read first-hand from the copy pinned at `SOURCE_ST_0903_4` — the
edition the profile pins, which is `.4` and not the current edition of the series. A later edition
is a different document; MISP-2019.1 Appendix B reference [57] names `0903.4`, and
`klv_pin.json`'s `delegation_table` row carries the same string.

WHAT IS REACHED FROM ITEM 74, AND WHAT IS NOT — §9.1, VERBATIM
----------------------------------------------------------------
    "For bandwidth efficiency, the VMTI LS contains several data elements expressed as offsets
    from the frame center geographic coordinate provided in MISB ST 0601. Thus, the VMTI LS is
    generally subordinate to a MISB ST 0601 LS, and Tag 74 in MISB ST 0601 has been assigned to
    the VMTI LS. However, the VMTI LS also contains corresponding data elements expressed in
    absolute geographic coordinates, allowing the VMTI LS to be independent (i.e. standalone) of
    MISB ST 0601. Geographic coordinates in the VTrack LS are absolute, so the VTrack LS is always
    independent of MISB ST 0601."

So item 74 reaches Tables 1-12 — the VMTI LS, the VTarget Pack, and the five nested Local Sets and
four packs under them — and it does **not** reach Table 13 (VTrack LS) or Table 14 (VTrackItem
Pack). Those two are transcribed in `FORMAT_COVERAGE.md` and are absent from this module by that
sentence; see `VTRACK_LS_IS_OUT_OF_ITEM_74S_REACH`.

THE THREE GRAMMARS THIS LAYER COMPOSES, EACH FROM THE DOCUMENT
----------------------------------------------------------------
1. **The Local Set**, for the VMTI LS itself and for the five nested sets. §9.1's Figure 4 makes
   item 74's Value "the sum of the lengths of all the TLV elements in the VMTI LS", so the Value is
   a bare run of Local Set triplets with no 16-byte key and no second BER length — the same shape
   `klv_security_codec.decode_set` walks for item 48, and walked here with the same primitives.
   The registered keys of the six sets are the sets' IDENTITY and are recorded at `LOCAL_SET_KEYS`
   rather than matched against any buffer.
2. **The Series**, `ST 0903.4-06`: "The Series type shall be a one-dimensional array of data
   elements, all of the same type, encoded as a SMPTE Variable-Length Pack." Footnote 5 states what
   that costs on the wire: "No key is required. Each element, a VTarget Pack, consists of only a
   BER-encoded Length and a Value". So a Series is `[L][V] [L][V] …` to the end of the span, and
   the number of members is discovered by walking rather than declared.
3. **The Defined-Length Truncation Pack**, for Location, Velocity and Acceleration.
   `ST 0903.4-62`: "Truncation of Location, Velocity, and Acceleration Defined-Length Truncation
   Packs shall be allowed only at a group boundary", and `ST 0903.4-63`: "no filler values shall be
   used for (unknown) higher priority elements." So the members are read in order, the pack may end
   at 3, 6 or 9 members (Location: 10, 16 or 22 octets), and any other total is a refusal rather
   than a best-effort read.

VARIABLE-LENGTH UNSIGNED INTEGERS, AND WHY NO LENGTH IS ASSUMED — §8.3
------------------------------------------------------------------------
    "MISB ST 0903 specifies a nominal maximum number of bytes for a metadata element with an
    unsigned integer value, large enough to express the maximum value. However, since leading
    zeroes are not significant, MISB ST 0903 allows smaller values to be expressed using fewer
    bytes. … The notation used to indicate variable-length encoding is 'Vmax'."

`ST 0903.4-04` bounds it — "The number of bytes used to encode a variable-length unsigned integer
value shall be less than or equal to the specified maximum length" — and `ST 0903.4-05` fixes the
one degenerate case: "The number of bytes used to encode the value zero for a variable-length
unsigned integer value shall be one (1)." Both are checked, both refuse rather than repair, and the
octets are carried through the refusal so nothing is lost.

WHAT THE DOCUMENT'S OWN WORKED EXAMPLES DO HERE
------------------------------------------------
Appendix A prints a `Example Value` / `Example Encoded LS Value` pair for each of its 75 entries.
**57 print octets and 18 do not** (17 read `NA NA`; Motion Imagery ID reads "See MISB ST 1204
[4]."). `check_against_the_documents_own_examples()` decodes every printed pair on every suite run
and reports one line each — so this module cannot drift from the document without the suite saying
so, which is `klv_uas_codec`'s own arrangement applied one document over.

**THREE PRINTED EXAMPLES DO NOT REPRODUCE, AND THEY ARE RULED RATHER THAN WORKED AROUND.** M's
ruling of 2026-09-05: *the tables, formulas and figures are normative; a worked example is an
illustration. Where a printed example is refuted by the document's own table, formula or figure,
the codec follows the table, and the example is recorded as a disagreement in the codec's own
record.* That is `imapb_codec.PRINTED_RESOLUTION_DISAGREEMENTS`'s shape and it is why
`PRINTED_EXAMPLE_DISAGREEMENTS` below is a record and not a repair: nothing in this module
special-cases the octets of a live packet. A decoder handed the printed octets returns what the
printed octets say; the disagreement is a statement about the page, at the page's own clause.

This is NOT `AIRBASE_LOCATIONS_NOT_DECODED`'s case and the difference is worth stating, because the
two look alike from a distance. There, §8.130 states one member's range twice with two different
values and no third statement arbitrates, so the *definition* cannot be resolved and the item is
left undecoded. Here the definitions are unambiguous — Figure 12's 16x9 frame, the VTracker row's
own Tag and Length cells — and only the *illustrations* are wrong. A definition that cannot be
resolved is a refusal; a misprinted illustration of a resolvable definition is an erratum.

WHAT THIS LAYER REFUSES TO SAY
--------------------------------
VObject LS Tag 1 is a URI *pointing at* an ontology and Tag 2 is a free string; VFeature LS Tag 1
is a URI pointing at a schema and Tag 2 an instance document in that schema. None of the four is an
enumeration this repository holds, so the strings are carried verbatim and no class is resolved —
`EXTERNAL_ONTOLOGIES_NOT_RESOLVED`, on `klv_security_codec.EXTERNAL_CODE_LISTS_NOT_HELD`'s ground.
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Any, Final, NamedTuple

from . import imapb_codec
from . import klv_codec as framing

__all__ = [
    "VmtiError", "SOURCE_ST_0903_4", "LOCAL_SET_KEYS", "TRACK_STATUS_VALUES",
    "VMTI_LS", "VTARGET_PACK", "VMASK_LS", "VOBJECT_LS", "VFEATURE_LS", "VTRACKER_LS", "VCHIP_LS",
    "LOCATION_PACK", "VELOCITY_PACK", "ACCELERATION_PACK", "TRUNCATION_GROUPS",
    "VTRACK_LS_IS_OUT_OF_ITEM_74S_REACH", "EXTERNAL_ONTOLOGIES_NOT_RESOLVED",
    "PRINTED_EXAMPLE_DISAGREEMENTS", "VMASK_BIT_MASK_FROM_THE_DERIVATION",
    "VTRACKER_TRACK_ID_FROM_THE_DERIVATION", "WORKED_EXAMPLES",
    "CARRIER_BASIS",
    "Element", "RefusedElement", "MaskRun", "FpaIndex", "Location", "Kinematics",
    "VTargetPack", "VmtiLocalSet",
    "decode_vmti_local_set", "decode_vtarget_series", "decode_vtarget_pack", "decode_series",
    "decode_bit_mask", "decode_polygon", "decode_location_pack", "decode_kinematics_pack",
    "decode_boundary_series", "decode_fpa_index", "decode_variable_uint",
    "check_against_the_documents_own_examples",
]

#: The pinned copy every citation in this module is read from. Named for the reason
#: `klv_pack_codec` names its own: a module that cites sections without naming the copy cites a
#: memory. 113 pages; the cover and the footer of all 113 read `MISB ST 0903.4` / `23 October 2014`.
SOURCE_ST_0903_4: Final[str] = (
    "MISB ST 0903.4, SHA-256 "
    "da46ba5eb8b07bc319cf2ba600c9f24344e3a288651e993d6e373d0ac57e442b, "
    "fixtures/klv/spec/ST0903.4.pdf"
)

#: What ST 0601.14a says item 74 carries, quoted, so the delegation is readable from this module —
#: `klv_security_codec.CARRIER_BASIS`' arrangement, applied to the third delegating item, and the
#: constant `klv_uas_codec.VMTI_BASIS` re-exports. §8.74's second bullet is the sentence that makes
#: item 74's Value a BARE run of ST 0903 triplets with no key and no second length to strip, which
#: is item 48's shape and not item 94's; and §8.74.1 is the sentence that makes the PARENT packet
#: part of this set's meaning, which is what tags 10 and 11 later depend on.
CARRIER_BASIS: Final[str] = (
    "MISB ST 0601.14a \u00a78.74, page 120: 'MISB ST 0903 VMTI Local Set metadata items', Length "
    "Variable, Max Length Not Limited, Required in LS? Optional, Multiples Allowed? No, KLV Key "
    "06.0E.2B.34.02.0B.01.01.0E.01.03.03.06.00.00.00 (CRC 51307) \u2014 the same UL and CRC this "
    "module records at LOCAL_SET_KEYS['VMTI LS'] from ST 0903.4's own Table 1 key row. "
    "\u00a78.74's bullets: 'Use the MISB ST 0903 Local Set within the MISB ST 0601 Tag 74' and "
    "'The length field is the size of all VMTI LS metadata items to be packaged within Tag 74'. "
    "\u00a78.74.1: 'The VMTI Local Set allows users to include, or nest, VMTI LS (MISB ST 0903 "
    "[15]) metadata items within MISB ST 0601. This provides users who are required to use the "
    "VMTI LS a method to leverage the items within MISB ST 0601 (like platform location, and "
    "sensor pointing angles, or frame center).'"
)

#: The six registered Universal Labels of the sets and packs this module reads, from the key row of
#: each table. THEY ARE IDENTITIES AND NOT OCTETS ANY CONFORMING ITEM 74 CARRIES — a nested set
#: inside a Local Set is reached by its parent's tag, exactly as ST 0102's is inside item 48. Each
#: is recorded with the CRC the document prints beside it; all 148 printed CRCs in the fourteen
#: element tables recompute from their own UL bytes under CRC-16/AUG-CCITT (poly 0x1021, init
#: 0x1D0F, no reflection, xorout 0x0000), which is the transcription's strongest cross-check.
LOCAL_SET_KEYS: Final[dict[str, tuple[str, int]]] = {
    "VMTI LS": ("060E2B34020B01010E01030306000000", 51307),
    "VMask LS": ("060E2B34020301010E01030308000000", 51391),
    "VObject LS": ("060E2B34020301010E01030309000000", 48651),
    "VFeature LS": ("060E2B34020301010E0103030A000000", 9687),
    "VTracker LS": ("060E2B34020301010E0103030B000000", 21347),
    "VChip LS": ("060E2B34020301010E0103030C000000", 52487),
    "VTarget Pack": ("060E2B34020501010E01030307000000", 60837),
}

#: Table 16, Track Status Values, verbatim. VTracker LS Tag 2's four states and no others.
TRACK_STATUS_VALUES: Final[dict[int, str]] = {
    0: "Inactive", 1: "Active", 2: "Dropped", 3: "Stopped",
}

#: §9.1, quoted in full in the module docstring. Recorded as a constant because a later round
#: asking "why is there no VTrack LS here" must find the sentence rather than infer the omission.
VTRACK_LS_IS_OUT_OF_ITEM_74S_REACH: Final[str] = (
    "Tables 13 (VTrack LS) and 14 (VTrackItem Pack) are NOT decoded here, and the reason is the "
    "document's own: §9.1, 'Geographic coordinates in the VTrack LS are absolute, so the VTrack "
    "LS is always independent of MISB ST 0601.' Item 74 is the ST 0601 tag assigned to the VMTI "
    "LS, so no item 74 ever carries a VTrack LS. §10 goes further and states a PREFERENCE for the "
    "carrier item 74 cannot reach: 'Note that the VMTI LS contains an element, VTracker, which "
    "could be used as an alternative to VTrack LS to specify track metadata. … Use of VTracker is "
    "discouraged (although not forbidden). Use of VTrack LS is recommended, because it maps more "
    "directly to NATO STANAG 4676, the NATO ISR Tracking Standard.' Both halves are recorded: "
    "what is reachable is decoded, and the document's discouragement of it is carried beside it "
    "rather than acted on. This repository already ships a STANAG 4676 adapter, which is where "
    "that sentence points; whether a CDM Track is built from VTracker LS, from VTargets across "
    "packets, or from neither is park 6's mapping question and is not decided in this layer."
)

#: The two URI-valued elements and the two free strings beside them, carried and never resolved.
EXTERNAL_ONTOLOGIES_NOT_RESOLVED: Final[str] = (
    "VObject LS Tag 1 (Ontology) and VFeature LS Tag 1 (Schema) are URIs POINTING AT a document "
    "this repository does not hold, and VObject LS Tag 2 (Ontology_Class) and VFeature LS Tag 2 "
    "(Schema_Feature) are free-form strings in the vocabulary those documents define — the "
    "Ontology_Class worked example is 'Dismount/Non-combatant/Female/Child', a path in an "
    "unbounded namespace and not a member of any enumeration this document prints. So all four "
    "are decoded as text and NO class is resolved, on klv_security_codec."
    "EXTERNAL_CODE_LISTS_NOT_HELD's ground: resolving one would mean this repository supplying "
    "the register the document delegates to, which is a different act from decoding an octet."
)


class VmtiError(ValueError):
    """A VMTI construct this module refuses to decode, with the clause that decides it."""


class Element(NamedTuple):
    """One row of one of the document's element tables, as the table prints it.

    `length` and `fmt` are the table's own `Length in Bytes` and `KLV Format` cells rather than a
    paraphrase, because they are what a reader checks this transcription against.
    """

    name: str
    kind: str
    length: str
    fmt: str
    imapb: tuple[float, float] | None = None
    maximum: int | None = None


def _v(maximum: int) -> str:
    return f"V{maximum}"


# ---------------------------------------------------------------- Table 1: the VMTI LS, 14 rows
VMTI_LS: Final[dict[int, Element]] = {
    1: Element("Checksum", "uint", "F2", "Uint16"),
    2: Element("Precision Time Stamp", "timestamp", "F8", "Uint64"),
    3: Element("VMTI System Name / Description", "utf8", "V32", "UTF-8", maximum=32),
    4: Element("VMTI LS Version Number", "uint", "V2", "Uint16", maximum=2),
    5: Element("Total Number of Targets Detected in the Frame", "uint", "V3", "Uint24", maximum=3),
    6: Element("Number of Reported Targets", "uint", "V3", "Uint24", maximum=3),
    7: Element("Motion Imagery Frame Number", "uint", "V3", "Uint24", maximum=3),
    8: Element("Frame Width", "uint", "V3", "Uint24", maximum=3),
    9: Element("Frame Height", "uint", "V3", "Uint24", maximum=3),
    10: Element("VMTI Source Sensor", "utf8", "V127", "UTF-8", maximum=127),
    11: Element("VMTI Sensor Horizontal Field of View", "imapb", "F2", "IMAPB", (0.0, 180.0)),
    12: Element("VMTI Sensor Vertical Field of View", "imapb", "F2", "IMAPB", (0.0, 180.0)),
    13: Element("Motion Imagery ID", "binary", "V", "Binary"),
    101: Element("VTargetSeries", "vtarget_series", "V", "Series"),
}

# ------------------------------------------------------- Table 2: the VTarget Pack, 27 elements
#: Tag 0 is not a row: the Target ID Number is the pack's first member and carries NO tag at all
#: (`ST 0903.4-09`), which is why it is a field of `VTargetPack` and not an entry here.
VTARGET_PACK: Final[dict[int, Element]] = {
    1: Element("Target Centroid Pixel Number", "uint", "V6", "Uint48", maximum=6),
    2: Element("Bounding Box Top Left Pixel Number", "uint", "V6", "Uint48", maximum=6),
    3: Element("Bounding Box Bottom Right Pixel Number", "uint", "V6", "Uint48", maximum=6),
    4: Element("Target Priority", "uint", "F1", "Uint8"),
    5: Element("Target Confidence Level", "uint", "F1", "Uint8"),
    6: Element("New Detection Flag / Target History", "uint", "V2", "Uint16", maximum=2),
    7: Element("Percentage of Target Pixels", "uint", "F1", "Uint8"),
    8: Element("Target Color", "rgb", "F3", "Uint24"),
    9: Element("Target Intensity", "uint", "V3", "Uint24", maximum=3),
    10: Element("Target Location Latitude Offset", "imapb", "F3", "IMAPB", (-19.2, 19.2)),
    11: Element("Target Location Longitude Offset", "imapb", "F3", "IMAPB", (-19.2, 19.2)),
    12: Element("Target Height", "imapb", "F2", "IMAPB", (-900.0, 19000.0)),
    13: Element("Bounding Box Top Left Latitude Offset", "imapb", "F3", "IMAPB", (-19.2, 19.2)),
    14: Element("Bounding Box Top Left Longitude Offset", "imapb", "F3", "IMAPB", (-19.2, 19.2)),
    15: Element("Bounding Box Bottom Right Latitude Offset", "imapb", "F3", "IMAPB", (-19.2, 19.2)),
    16: Element("Bounding Box Bottom Right Longitude Offset", "imapb", "F3", "IMAPB",
                (-19.2, 19.2)),
    17: Element("Target Location", "location", "V", "Location"),
    18: Element("Target Boundary", "location_series", "V", "Boundary"),
    19: Element("Target Centroid Pixel Row", "uint", "V4", "Uint32", maximum=4),
    20: Element("Target Centroid Pixel Column", "uint", "V4", "Uint32", maximum=4),
    21: Element("FPA Index", "fpa_index", "F2", "Binary"),
    101: Element("VMask LS", "vmask", "V", "VMask LS"),
    102: Element("VObject LS", "vobject", "V", "VObject LS"),
    103: Element("VFeature LS", "vfeature", "V", "VFeature LS"),
    104: Element("VTracker LS", "vtracker", "V", "VTracker LS"),
    105: Element("VChip LS", "vchip", "V", "VChip LS"),
    106: Element("VChipSeries", "vchip_series", "V", "Series"),
}

# ------------------------------------------------ Tables 3-7: the five sets under a VTarget Pack
VMASK_LS: Final[dict[int, Element]] = {
    1: Element("Polygon", "polygon", "V", "Series of Unsigned Integers"),
    2: Element("Bit Mask", "bit_mask", "V", "Series of Unsigned Integers"),
}

VOBJECT_LS: Final[dict[int, Element]] = {
    1: Element("Ontology", "utf8", "V", "UTF-8"),
    2: Element("Ontology_Class", "utf8", "V", "UTF-8"),
}

VFEATURE_LS: Final[dict[int, Element]] = {
    1: Element("Schema", "utf8", "V", "UTF-8"),
    2: Element("Schema_Feature", "utf8", "V", "UTF-8"),
}

VTRACKER_LS: Final[dict[int, Element]] = {
    1: Element("Track ID", "uuid", "F16", "Uint128"),
    2: Element("Detection Status", "detection_status", "F1", "Uint8"),
    3: Element("Start Time Stamp", "timestamp", "V8", "Uint64", maximum=8),
    4: Element("End Time Stamp", "timestamp", "V8", "Uint64", maximum=8),
    5: Element("Bounding Box", "location_series", "V", "Boundary"),
    6: Element("Algorithm", "utf8", "V", "UTF-8"),
    7: Element("Confidence", "uint", "F1", "Uint8"),
    8: Element("Number of Track Points", "uint", "V2", "Uint16", maximum=2),
    9: Element("Locus", "location_series", "V", "Series of Location Elements"),
    10: Element("Velocity", "velocity", "V", "Velocity"),
    11: Element("Acceleration", "acceleration", "V", "Acceleration"),
}

VCHIP_LS: Final[dict[int, Element]] = {
    1: Element("Image Type", "utf8", "V", "UTF-8"),
    2: Element("Image_URI", "utf8", "V", "UTF-8"),
    3: Element("Embedded Image", "binary", "V", "Binary"),
}

# ---------------------------------- Tables 9-11: the three Defined-Length Truncation Packs
#: Each pack's nine members in the document's order, `ST 0903.4-65` and `-67`, `-71`, `-72`.
LOCATION_PACK: Final[tuple[Element, ...]] = (
    Element("Latitude", "imapb", "F4", "IMAPB", (-90.0, 90.0)),
    Element("Longitude", "imapb", "F4", "IMAPB", (-180.0, 180.0)),
    Element("Height", "imapb", "F2", "IMAPB", (-900.0, 19000.0)),
    Element("Sigma_East", "imapb", "F2", "IMAPB", (0.0, 650.0)),
    Element("Sigma_North", "imapb", "F2", "IMAPB", (0.0, 650.0)),
    Element("Sigma_Up", "imapb", "F2", "IMAPB", (0.0, 650.0)),
    Element("Rho_East_North", "imapb", "F2", "IMAPB", (-1.0, 1.0)),
    Element("Rho_East_Up", "imapb", "F2", "IMAPB", (-1.0, 1.0)),
    Element("Rho_North_Up", "imapb", "F2", "IMAPB", (-1.0, 1.0)),
)

VELOCITY_PACK: Final[tuple[Element, ...]] = (
    Element("East_Component", "imapb", "F2", "IMAPB", (-900.0, 900.0)),
    Element("North_Component", "imapb", "F2", "IMAPB", (-900.0, 900.0)),
    Element("Up_Component", "imapb", "F2", "IMAPB", (-900.0, 900.0)),
) + LOCATION_PACK[3:]

ACCELERATION_PACK: Final[tuple[Element, ...]] = VELOCITY_PACK

#: `ST 0903.4-62`: truncation "shall be allowed only at a group boundary". The boundaries, in
#: octets, for each pack — three groups of three members, and the Location pack's first group is
#: 4+4+2 where the other two are 2+2+2.
TRUNCATION_GROUPS: Final[dict[str, tuple[int, ...]]] = {
    "Location": (10, 16, 22),
    "Velocity": (6, 12, 18),
    "Acceleration": (6, 12, 18),
}


# ============================================================ what comes out of the decoders


@dataclass(frozen=True, slots=True)
class RefusedElement:
    """An element whose octets are carried and whose meaning this layer declines to state."""

    tag: int
    name: str | None
    refusal_class: str
    observed_length: int
    octets: str
    clause: str


@dataclass(frozen=True, slots=True)
class MaskRun:
    """One `(pixel number, run length)` pair of a VMask LS Bit Mask, §11.15.21.2."""

    pixel: int
    run: int


@dataclass(frozen=True, slots=True)
class FpaIndex:
    """VTarget Pack Tag 21: "Specifies the column and the row of a sensor Focal Plane Array"."""

    row: int
    column: int


@dataclass(frozen=True, slots=True)
class Location:
    """One Location Truncation Pack. Members absent by truncation are `None`, never a filler.

    `ST 0903.4-63` forbids filler for unknown higher-priority elements and `ST 0903.4-62` allows
    truncation only at a group boundary, so a `None` here can only mean "the pack ended before this
    group", which is a different fact from "the emitter did not know this value".
    """

    latitude: float
    longitude: float
    height: float
    sigma_east: float | None = None
    sigma_north: float | None = None
    sigma_up: float | None = None
    rho_east_north: float | None = None
    rho_east_up: float | None = None
    rho_north_up: float | None = None


@dataclass(frozen=True, slots=True)
class Kinematics:
    """A Velocity or Acceleration Truncation Pack — the same three groups, different first triplet."""

    kind: str
    east: float
    north: float
    up: float
    sigma_east: float | None = None
    sigma_north: float | None = None
    sigma_up: float | None = None
    rho_east_north: float | None = None
    rho_east_up: float | None = None
    rho_north_up: float | None = None


@dataclass(frozen=True, slots=True)
class DecodedElement:
    """One decoded TLV of one of the six sets, with the octets it was read from."""

    tag: int
    name: str
    kind: str
    value: Any
    octets: str


@dataclass(frozen=True, slots=True)
class DecodedSet:
    """A nested Local Set — VMask, VObject, VFeature, VTracker or VChip — and its refusals."""

    set_name: str
    elements: dict[int, DecodedElement] = field(default_factory=dict)
    order: tuple[int, ...] = ()
    refusals: tuple[RefusedElement, ...] = ()
    unlisted: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class VTargetPack:
    """One VTarget Pack: the mandatory tagless Target ID Number, then LS-like triplets.

    §9.1: "The first, mandatory, element in the value field of each VTarget Pack is a BER-OID
    encoded value to convey the Target ID Number of the target. The following elements form an
    LS-like structure containing one or more Tag-Length-Value (TLV) triplets … No particular TLV
    triplet is mandatory, but at least one must be present."
    """

    target_id: int
    elements: dict[int, DecodedElement] = field(default_factory=dict)
    order: tuple[int, ...] = ()
    refusals: tuple[RefusedElement, ...] = ()
    unlisted: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class VmtiLocalSet:
    """The Value of ST 0601 item 74, decoded. NOT a CDM object and not on the way to being one."""

    elements: dict[int, DecodedElement] = field(default_factory=dict)
    order: tuple[int, ...] = ()
    targets: tuple[VTargetPack, ...] = ()
    refusals: tuple[RefusedElement, ...] = ()
    unlisted: tuple[int, ...] = ()


# ============================================================ the refusal classes, each a clause

UNLISTED_TAG: Final[str] = "unlisted_tag"
LENGTH_EXCEEDS_THE_STATED_MAXIMUM: Final[str] = "length_exceeds_the_stated_maximum"
ZERO_NOT_ENCODED_IN_ONE_BYTE: Final[str] = "zero_not_encoded_in_one_byte"
LENGTH_IS_NOT_THE_FIXED_LENGTH: Final[str] = "length_is_not_the_fixed_length"
TRUNCATED_OFF_A_GROUP_BOUNDARY: Final[str] = "truncated_off_a_group_boundary"

REFUSAL_CLAUSES: Final[dict[str, str]] = {
    UNLISTED_TAG: (
        "the tag is not a row of this table. ST 0107.3-04 — 'Applications which decode MISB KLV "
        "Local Sets shall skip unknown Local Set values so as to not impact the decoding of known "
        "Local Set items within the same Local Set instance' — so the octets are carried, the tag "
        "is recorded, and the rest of the set decodes"),
    LENGTH_EXCEEDS_THE_STATED_MAXIMUM: (
        "ST 0903.4-04: 'The number of bytes used to encode a variable-length unsigned integer "
        "value shall be less than or equal to the specified maximum length.' A longer value is "
        "not a bigger number, it is a malformed element"),
    ZERO_NOT_ENCODED_IN_ONE_BYTE: (
        "ST 0903.4-05: 'The number of bytes used to encode the value zero for a variable-length "
        "unsigned integer value shall be one (1).' Two octets of zero are a conformance failure "
        "the document names, and repairing it silently would hide an emitter defect"),
    LENGTH_IS_NOT_THE_FIXED_LENGTH: (
        "the table gives this element a FIXED length (an 'Fn' KLV Format cell) and the wire "
        "disagrees. §8.3's variable-length allowance is scoped to elements the table marks 'Vmax'; "
        "an Fn element is not one of them"),
    TRUNCATED_OFF_A_GROUP_BOUNDARY: (
        "ST 0903.4-62: 'Truncation of Location, Velocity, and Acceleration Defined-Length "
        "Truncation Packs shall be allowed only at a group boundary', with ST 0903.4-63 forbidding "
        "filler for unknown higher-priority elements. A pack ending mid-group cannot be read "
        "without guessing which member is missing"),
}


# ============================================================ the primitive value decoders


def decode_variable_uint(octets: bytes, element: Element) -> int:
    """§8.3's Vmax integer, with `ST 0903.4-04` and `-05` enforced rather than assumed."""
    if element.maximum is not None and len(octets) > element.maximum:
        raise VmtiError(
            f"{element.name}: {len(octets)} octets for an element the table gives as "
            f"{element.length}. {REFUSAL_CLAUSES[LENGTH_EXCEEDS_THE_STATED_MAXIMUM]}")
    value = int.from_bytes(octets, "big")
    if value == 0 and element.maximum is not None and len(octets) != 1:
        raise VmtiError(
            f"{element.name}: the value zero in {len(octets)} octets. "
            f"{REFUSAL_CLAUSES[ZERO_NOT_ENCODED_IN_ONE_BYTE]}")
    return value


def _fixed(octets: bytes, element: Element) -> None:
    if element.length.startswith("F") and len(octets) != int(element.length[1:]):
        raise VmtiError(
            f"{element.name}: {len(octets)} octets where the table's Length in Bytes cell reads "
            f"{element.length}. {REFUSAL_CLAUSES[LENGTH_IS_NOT_THE_FIXED_LENGTH]}")


def _timestamp(octets: bytes, element: Element) -> dict[str, Any]:
    """§11.2's 'Microseconds elapsed since midnight … January 1, 1970 … See MISB ST 0603 [12].'

    Returned as BOTH the integer the wire carries and the ISO instant it denotes, because the
    conversion is park 3's closed document and the raw value is what a later round re-derives.
    """
    micros = int.from_bytes(octets, "big")
    stamp = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(microseconds=micros)
    return {"microseconds": micros, "utc": stamp.isoformat().replace("+00:00", "Z")}


def decode_polygon(octets: bytes) -> tuple[int, ...]:
    """VMask LS Tag 1: 'a Series of at least three pixel numbers … encoded using the Length-Value
    construct of a Variable-Length Pack' (`ST 0903.4-41`)."""
    return tuple(int.from_bytes(member, "big") for member in decode_series(octets))


def decode_bit_mask(octets: bytes) -> tuple[MaskRun, ...]:
    """VMask LS Tag 2: a Series of `{[L][pixel][BER run]}` sub-packs.

    The row: "A Series of pixel-number-plus-run-length pairs, each describing the starting pixel
    number and the number of pixels in a run. … Pixel numbers are encoded using the Length-Value
    construct of a Variable-Length Pack. The length of each run is encoded using BER Length
    encoding" — `ST 0903.4-43` and `ST 0903.4-44`. So each member of the outer Series is itself
    `[L][pixel octets]` followed by a BER length standing in for the run count.
    """
    runs: list[MaskRun] = []
    for member in decode_series(octets):
        pixel_length, cursor = framing.decode_ber_length(member, 0)
        pixel = int.from_bytes(member[cursor:cursor + pixel_length], "big")
        cursor += pixel_length
        run, cursor = framing.decode_ber_length(member, cursor)
        if cursor != len(member):
            raise VmtiError(
                f"a Bit Mask member is {len(member)} octets and its pixel-number and run-length "
                f"fields account for {cursor}. ST 0903.4-43 gives the member exactly two fields")
        runs.append(MaskRun(pixel=pixel, run=run))
    return tuple(runs)


def decode_series(octets: bytes) -> tuple[bytes, ...]:
    """`ST 0903.4-06`'s Series: `[L][V] [L][V] …` to the end of the span, and nothing else.

    Footnote 5: "No key is required. Each element … consists of only a BER-encoded Length and a
    Value". The member count is discovered by walking; a member overrunning the span is a refusal
    rather than a short read, on `klv_codec.walk_local_set`'s own precedent.
    """
    members: list[bytes] = []
    cursor = 0
    while cursor < len(octets):
        length, cursor = framing.decode_ber_length(octets, cursor)
        if cursor + length > len(octets):
            raise VmtiError(
                f"a Series member at offset {cursor} declares {length} octets and only "
                f"{len(octets) - cursor} remain. ST 0903.4-06's Series is a SMPTE Variable-Length "
                f"Pack, so a member may not run past the pack")
        members.append(octets[cursor:cursor + length])
        cursor += length
    return tuple(members)


def _truncation_pack(octets: bytes, members: tuple[Element, ...], label: str) -> list[float | None]:
    widths = [int(m.length[1:]) for m in members]
    boundaries = TRUNCATION_GROUPS[label]
    if len(octets) not in boundaries:
        raise VmtiError(
            f"a {label} Truncation Pack of {len(octets)} octets, where its group boundaries are "
            f"{boundaries}. {REFUSAL_CLAUSES[TRUNCATED_OFF_A_GROUP_BOUNDARY]}")
    out: list[float | None] = []
    cursor = 0
    for element, width in zip(members, widths):
        if cursor + width > len(octets):
            out.append(None)
            continue
        assert element.imapb is not None
        out.append(imapb_codec.decode(element.imapb[0], element.imapb[1],
                                      octets[cursor:cursor + width]))
        cursor += width
    return out


def decode_location_pack(octets: bytes) -> Location:
    """Table 9's Location Truncation Pack: 4+4+2, then 2+2+2, then 2+2+2 octets."""
    values = _truncation_pack(octets, LOCATION_PACK, "Location")
    return Location(*values)


def decode_kinematics_pack(octets: bytes, kind: str = "Velocity") -> Kinematics:
    """Tables 10 and 11 — the same shape with an East/North/Up component triplet in front."""
    members = VELOCITY_PACK if kind == "Velocity" else ACCELERATION_PACK
    values = _truncation_pack(octets, members, kind)
    return Kinematics(kind, *values)


def decode_boundary_series(octets: bytes) -> tuple[Location, ...]:
    """Table 12: "A Series of Location data elements, one for each vertex of a bounding area"."""
    return tuple(decode_location_pack(member) for member in decode_series(octets))


def decode_fpa_index(octets: bytes) -> FpaIndex:
    """Table 8's two-octet Defined-Length Pack. The worked example prints `(row, column) = (2, 3)`
    against `[T] [V] = [0x15][0x02 03]`, so the FIRST octet is the row and the second the column —
    which is what the pack's own member order (Table 8: FPA Row, then FPA Column, each F1)
    states, and the Table 2 Notes cell's "column and the row" wording is prose order, not wire
    order. The two agree once the pack table arbitrates, so this is not a fourth disagreement."""
    if len(octets) != 2:
        raise VmtiError(
            f"FPA Index: {len(octets)} octets where Table 2's Length in Bytes cell reads F2")
    return FpaIndex(row=octets[0], column=octets[1])


# ============================================================ the set and pack walkers

_NESTED: Final[dict[str, tuple[str, dict[int, Element]]]] = {
    "vmask": ("VMask LS", VMASK_LS),
    "vobject": ("VObject LS", VOBJECT_LS),
    "vfeature": ("VFeature LS", VFEATURE_LS),
    "vtracker": ("VTracker LS", VTRACKER_LS),
    "vchip": ("VChip LS", VCHIP_LS),
}


def _decode_value(element: Element, octets: bytes) -> Any:
    """One element's Value, by the `kind` its own table row implies. No tag is consulted twice."""
    kind = element.kind
    if kind == "uint":
        _fixed(octets, element)
        return decode_variable_uint(octets, element)
    if kind == "utf8":
        if element.maximum is not None and len(octets) > element.maximum:
            raise VmtiError(
                f"{element.name}: {len(octets)} octets for an element the table gives as "
                f"{element.length}. {REFUSAL_CLAUSES[LENGTH_EXCEEDS_THE_STATED_MAXIMUM]}")
        return octets.decode("utf-8")
    if kind == "imapb":
        _fixed(octets, element)
        assert element.imapb is not None
        return imapb_codec.decode(element.imapb[0], element.imapb[1], octets)
    if kind == "timestamp":
        return _timestamp(octets, element)
    if kind == "rgb":
        _fixed(octets, element)
        return {"red": octets[0], "green": octets[1], "blue": octets[2]}
    if kind == "uuid":
        _fixed(octets, element)
        return octets.hex()
    if kind == "detection_status":
        _fixed(octets, element)
        code = octets[0]
        if code not in TRACK_STATUS_VALUES:
            raise VmtiError(
                f"Detection Status {code}: Table 16 draws rows for {sorted(TRACK_STATUS_VALUES)} "
                f"and for no others, so this layer declines to name a fifth state")
        return {"code": code, "status": TRACK_STATUS_VALUES[code]}
    if kind == "binary":
        return octets.hex()
    if kind == "polygon":
        return decode_polygon(octets)
    if kind == "bit_mask":
        return decode_bit_mask(octets)
    if kind == "location":
        return decode_location_pack(octets)
    if kind == "location_series":
        return decode_boundary_series(octets)
    if kind == "velocity":
        return decode_kinematics_pack(octets, "Velocity")
    if kind == "acceleration":
        return decode_kinematics_pack(octets, "Acceleration")
    if kind == "fpa_index":
        return decode_fpa_index(octets)
    if kind == "vtarget_series":
        return decode_vtarget_series(octets)
    if kind == "vchip_series":
        return tuple(_decode_nested("vchip", member) for member in decode_series(octets))
    if kind in _NESTED:
        return _decode_nested(kind, octets)
    raise VmtiError(f"{element.name}: no decoder for kind {kind!r}")


def _walk(octets: bytes, table: dict[int, Element], set_name: str
          ) -> tuple[dict[int, DecodedElement], tuple[int, ...],
                     tuple[RefusedElement, ...], tuple[int, ...]]:
    """A bare run of Local Set triplets, walked with the framing layer's own primitives."""
    elements: dict[int, DecodedElement] = {}
    order: list[int] = []
    refusals: list[RefusedElement] = []
    unlisted: list[int] = []
    cursor = 0
    end = len(octets)
    while cursor < end:
        tag_offset = cursor
        tag, cursor = framing.decode_ber_oid(octets, cursor)
        length, cursor = framing.decode_ber_length(octets, cursor)
        if cursor + length > end:
            raise VmtiError(
                f"{set_name}: the element with tag {tag} at offset {tag_offset} declares a "
                f"{length}-octet Value, which runs {cursor + length - end} octet(s) past the end "
                f"of the set. §9.1 makes an enclosing Length 'the sum of the lengths of all the "
                f"TLV elements', so an element overrunning it is a malformed set")
        raw = octets[cursor:cursor + length]
        cursor += length
        order.append(tag)
        element = table.get(tag)
        if element is None:
            unlisted.append(tag)
            refusals.append(RefusedElement(tag, None, UNLISTED_TAG, length, raw.hex(),
                                           f"{set_name}: {REFUSAL_CLAUSES[UNLISTED_TAG]}"))
            continue
        try:
            value = _decode_value(element, raw)
        except (VmtiError, framing.KLVFramingError, UnicodeDecodeError, ValueError) as exc:
            refusals.append(RefusedElement(tag, element.name, _class_of(exc), length, raw.hex(),
                                           str(exc)))
            continue
        elements[tag] = DecodedElement(tag, element.name, element.kind, value, raw.hex())
    return elements, tuple(order), tuple(refusals), tuple(unlisted)


def _class_of(exc: Exception) -> str:
    """The refusal class a raised message belongs to, by the clause it quotes."""
    text = str(exc)
    for name, clause in REFUSAL_CLAUSES.items():
        if clause[:40] in text:
            return name
    return "refused_by_a_clause_of_the_document"


def _decode_nested(kind: str, octets: bytes) -> DecodedSet:
    set_name, table = _NESTED[kind]
    elements, order, refusals, unlisted = _walk(octets, table, set_name)
    return DecodedSet(set_name, elements, order, refusals, unlisted)


def decode_vtarget_pack(octets: bytes) -> VTargetPack:
    """One VTarget Pack's Value: the tagless BER-OID Target ID Number, then TLV triplets.

    `ST 0903.4-09`, `-10` and `-11` are the three rules this composes, and the third is why the
    walk starts after the identifier rather than at offset zero: "All elements of a VTarget Pack,
    other than the first, shall be TLV encoded."
    """
    if not octets:
        raise VmtiError(
            "an empty VTarget Pack. ST 0903.4-09 makes the Target ID Number mandatory and "
            "ST 0903.4-10 requires at least one TLV triplet after it")
    target_id, cursor = framing.decode_ber_oid(octets, 0)
    elements, order, refusals, unlisted = _walk(octets[cursor:], VTARGET_PACK, "VTarget Pack")
    return VTargetPack(target_id, elements, order, refusals, unlisted)


def decode_vtarget_series(octets: bytes) -> tuple[VTargetPack, ...]:
    """VMTI LS Tag 101: `ST 0903.4-07`, "VTargetSeries shall be a Series of VTarget Packs"."""
    return tuple(decode_vtarget_pack(member) for member in decode_series(octets))


def decode_vmti_local_set(octets: bytes) -> VmtiLocalSet:
    """ST 0601 item 74's Value, and NOTHING ELSE — no Universal Label, no outer BER length.

    §9.1's Figure 4 walkthrough: "the packet begins with a Tag of value 74. … The Tag is followed
    by a Length value, which is the sum of the lengths of all the TLV elements in the VMTI LS; this
    sum includes the bytes used for the Tag and Length fields of subordinate elements." So the
    caller passes the Value the ST 0601 item layer already sliced, exactly as
    `klv_security_codec.decode_set` takes item 48's.

    The VTarget Packs are lifted out of tag 101 onto `targets` as well as being left in
    `elements[101]`, because every question park 6's mapping fork asks is a question about targets
    and none of them should have to know which tag carried them.
    """
    elements, order, refusals, unlisted = _walk(octets, VMTI_LS, "VMTI LS")
    series = elements.get(101)
    targets = tuple(series.value) if series is not None else ()
    return VmtiLocalSet(elements, order, targets, refusals, unlisted)


# ============================================================ the three printed disagreements

#: **A RECORD, NOT A REPAIR.** Each entry: the clause and page, what the document prints, what the
#: document's own table/figure gives, and which part of the document arbitrates. Nothing in this
#: module reads this dict while decoding; a decoder handed the printed octets returns what the
#: printed octets say. M's ruling, 2026-09-05: "The tables, formulas and figures are normative; a
#: worked example is an illustration. Where a printed example is refuted by the document's own
#: table, formula or figure, the codec follows the table, and the example is recorded as a
#: disagreement in the codec's own record." The shape is
#: `imapb_codec.PRINTED_RESOLUTION_DISAGREEMENTS`'s.
PRINTED_EXAMPLE_DISAGREEMENTS: Final[dict[str, dict[str, str]]] = {
    "vmask_bit_mask_octets": {
        "clause": "§11.15.21.2, VMask LS Tag 2 Bit Mask, page 82",
        "printed": (
            "Example Value '(pixel, run) = { (74, 2), (89, 4), (106, 2) }' against Example Encoded "
            "LS Value '[0x02][0F] { [0x04] { [0x02][0x01 4A][0x02] } [0x04] { [0x02][0x01 59]"
            "[0x04] } [0x04] { [0x02][0x01 6A][0x02] } }', restated in the prose below it as "
            "'(74, 2) = [0x01 4A] [0x02]', '(89, 4) = [0x01 59] [0x04]', '(106, 2) = [0x01 6A] "
            "[0x02]'"),
        "the_table_gives": (
            "0x014A is 330, 0x0159 is 345 and 0x016A is 362 — each exactly 256 above the pixel "
            "number printed beside it, i.e. a high octet reading 0x01 where 0x00 belongs"),
        "what_arbitrates": (
            "THE SECTION'S OWN FIGURE 12 AND ITS OWN EQUATION. The section states the rule — 'The "
            "calculation of the pixel number uses the equation: Column + ((Row-1) x frame "
            "width)). The top left pixel of the frame equates to (Column, Row) = (1, 1) with a "
            "pixel number of 1' — and sets the example in 'the 16 x 9 table below (Figure 12)'. A "
            "16-wide, 9-high frame has 144 pixels: 74, 89 and 106 exist in it and 330, 345 and 362 "
            "do not. 74 = 10 + (5-1) x 16 places it exactly. The outer framing is self-consistent "
            "either way (L = 0x0F = 15 = three sub-packs of 1 + 4 octets), so the framing does not "
            "arbitrate and the geometry does"),
        "so": (
            "the decimal pixel numbers are the document's meaning and the printed octets carry a "
            "spurious high byte. `VMASK_BIT_MASK_FROM_THE_DERIVATION` is built from the "
            "derivation; the printed octets are decoded as printed by "
            "`check_against_the_documents_own_examples`, which reports this row DISAGREE on every "
            "suite run so the defect stays visible rather than becoming a silent fixture"),
    },
    "vtracker_track_id_framing": {
        "clause": "§11.15.24.1, VTracker LS Tag 1 Track ID, page 90",
        "printed": (
            "Example Value 'F81D4FAE7DEC11D0A76500A0C91E6BF6' against Example Encoded LS Value "
            "'[K] [L] [V] = [0x10][0x04][0xF8 1D 4F AE 7D EC 11 D0 A7 65 00 A0 C9 1E 6B F6]'"),
        "the_table_gives": (
            "the same entry's own KLV Encoding block reads 'VTracker LS Tag 1' and its Length cell "
            "reads '16 Bytes', so [K] must be 0x01 and [L] must be 0x10. The printed pair is the "
            "two the other way round: 0x10 is the length written into the key position and 0x04 is "
            "neither the tag nor the length of anything in the row"),
        "what_arbitrates": (
            "THE ROW'S OWN TAG AND LENGTH CELLS, and Table 6, which gives VTracker LS Tag 1 as "
            "F16. The sixteen Value octets are a well-formed UUID and are not in question — "
            "'A unique identifier (UUID) for the track', 'as standardized by the Open Software "
            "Foundation in ISO/IEC 9834-8' — so the defect is confined to the two framing fields. "
            "Of the 37 Appendix A entries printing a full [K] [L] [V] triplet, 36 agree with their "
            "own row's Tag and Length cells and this is the one that does not"),
        "so": (
            "a decoder checked against the triplet as printed cannot pass it, and a producer "
            "following it emits an unparseable element. "
            "`VTRACKER_TRACK_ID_FROM_THE_DERIVATION` carries the framing the row gives"),
    },
    "appendix_a_owner_label_says_vtrack_pack": {
        "clause": (
            "§11.15's entries for VTarget Pack tags 6, 7, 9, 10 and 11 — New Detection Flag / "
            "Target History, Percentage of Target Pixels, Target Intensity, Target Location "
            "Latitude Offset and Target Location Longitude Offset, pages 67-71"),
        "printed": (
            "each of the five KLV Encoding blocks labels its owner 'VTrack Pack Tag n' where the "
            "other twenty-two entries of the same pack read 'VTarget Pack Tag n'"),
        "the_table_gives": (
            "Table 2 lists all five under the VTarget Pack at those tag numbers, with the same "
            "Universal Labels and the same printed CRCs — 47263, 9027, 50028, 46552 and 11780, "
            "each of which recomputes from its own UL bytes"),
        "what_arbitrates": (
            "TABLE 2, AND THE DOCUMENT'S OWN FOOTNOTE 10: 'Note the distinction between VTracker "
            "and VTrack (no \"er\").' There is no 'VTrack Pack' construct in this document at all "
            "— Table 14 defines a VTrackItem Pack and Table 2 a VTarget Pack — so the label names "
            "nothing, while the UL and tag number name exactly one row each"),
        "so": (
            "a NAMING defect rather than a value one: no octet decodes differently under either "
            "reading, and this module's table follows Table 2. Recorded because a reader "
            "cross-checking the Appendix against the tables meets it, and because it is a third "
            "finding for an ST 0903.4 erratum note"),
    },
}

#: The Bit Mask fixture, built from the derivation, with the printed form beside it and named as
#: refuted — the ruling's own instruction. Pixel numbers 74, 89 and 106 in the 16x9 frame of Figure
#: 12; runs 2, 4 and 2. The outer length is unchanged at 15 octets, because only the value of the
#: high octet of each pixel number moves.
VMASK_BIT_MASK_FROM_THE_DERIVATION: Final[dict[str, Any]] = {
    "octets": "0402004A0204020059040402006A02",
    "runs": ((74, 2), (89, 4), (106, 2)),
    "printed_and_refuted": "0402014A0204020159040402016A02",
    "why": PRINTED_EXAMPLE_DISAGREEMENTS["vmask_bit_mask_octets"]["what_arbitrates"],
}

#: The Track ID fixture, built from the derivation: the row's own Tag 1 and Length 16 in front of
#: the sixteen Value octets the example prints, which are not in question.
VTRACKER_TRACK_ID_FROM_THE_DERIVATION: Final[dict[str, Any]] = {
    "octets": "0110F81D4FAE7DEC11D0A76500A0C91E6BF6",
    "uuid": "f81d4fae7dec11d0a76500a0c91e6bf6",
    "printed_and_refuted": "1004F81D4FAE7DEC11D0A76500A0C91E6BF6",
    "why": PRINTED_EXAMPLE_DISAGREEMENTS["vtracker_track_id_framing"]["what_arbitrates"],
}


# ============================================================ every printed example, as data

class WorkedExample(NamedTuple):
    """One `Example Value` / `Example Encoded LS Value` pair, as Appendix A prints it."""

    clause: str
    owner: str
    tag: int
    octets: str
    printed: str
    expected: Any
    disagreement: str | None = None


_TABLES: Final[dict[str, dict[int, Element]]] = {
    "VMTI LS": VMTI_LS, "VTarget Pack": VTARGET_PACK, "VMask LS": VMASK_LS,
    "VObject LS": VOBJECT_LS, "VFeature LS": VFEATURE_LS, "VTracker LS": VTRACKER_LS,
    "VChip LS": VCHIP_LS,
}

_PACK_MEMBERS: Final[dict[str, tuple[Element, ...]]] = {
    "Location Truncation Pack": LOCATION_PACK,
    "Velocity Truncation Pack": VELOCITY_PACK,
    "Acceleration Truncation Pack": ACCELERATION_PACK,
}

WORKED_EXAMPLES: Final[tuple[WorkedExample, ...]] = (
    WorkedExample("§11.1", "VMTI LS", 1, "0000", "0x00 00", 0),
    WorkedExample("§11.2", "VMTI LS", 2, "0003824430F6CE40",
                  "April 19 2001, 04:25:21.000000 GMT", "2001-04-19T04:25:21Z"),
    WorkedExample("§11.3", "VMTI LS", 3, "4453544F5F414453535F564D5449",
                  "DSTO_ADSS_VMTI", "DSTO_ADSS_VMTI"),
    WorkedExample("§11.4", "VMTI LS", 4, "04", "4", 4),
    WorkedExample("§11.5", "VMTI LS", 5, "1C", "28 (0x1C)", 28),
    WorkedExample("§11.6", "VMTI LS", 6, "0E", "14 (0x0E)", 14),
    WorkedExample("§11.7", "VMTI LS", 7, "0130B0", "78,000 (0x0130B0)", 78000),
    WorkedExample("§11.8", "VMTI LS", 8, "0780", "1920 (0x0780)", 1920),
    WorkedExample("§11.9", "VMTI LS", 9, "0438", "1080 (0x0438)", 1080),
    WorkedExample("§11.10", "VMTI LS", 10, "454F204E6F7365", "“EO Nose”", "EO Nose"),
    WorkedExample("§11.11", "VMTI LS", 11, "0640", "12.5 Degrees", 12.5),
    WorkedExample("§11.12", "VMTI LS", 12, "0500", "10.0 Degrees", 10.0),
    WorkedExample("§11.15.1", "VTarget Pack", 1, "064000", "409,600 (0x06 40 00)", 409600),
    WorkedExample("§11.15.2", "VTarget Pack", 2, "064000", "409,600 (0x06 40 00)", 409600),
    WorkedExample("§11.15.3", "VTarget Pack", 3, "064000", "409,600 (0x06 40 00)", 409600),
    WorkedExample("§11.15.4", "VTarget Pack", 4, "1B", "27 (0x1B)", 27),
    WorkedExample("§11.15.5", "VTarget Pack", 5, "50", "80 (0x50)", 80),
    WorkedExample("§11.15.6", "VTarget Pack", 6, "0ACD", "2765 (0x0A CD)", 2765),
    WorkedExample("§11.15.7", "VTarget Pack", 7, "32", "50% (0x32)", 50),
    WorkedExample("§11.15.8", "VTarget Pack", 8, "558833", "[0x55 88 33]",
                  {"red": 0x55, "green": 0x88, "blue": 0x33}),
    WorkedExample("§11.15.9", "VTarget Pack", 9, "3354", "13140 [0x33 54]", 13140),
    WorkedExample("§11.15.10", "VTarget Pack", 10, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.11", "VTarget Pack", 11, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.12", "VTarget Pack", 12, "2A94", "10,000 Meters", 10000.0),
    WorkedExample("§11.15.13", "VTarget Pack", 13, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.14", "VTarget Pack", 14, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.15", "VTarget Pack", 15, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.16", "VTarget Pack", 16, "3A6667", "10.00 Degrees", 10.0),
    WorkedExample("§11.15.19", "VTarget Pack", 19, "0368", "872 (0x03 68)", 872),
    WorkedExample("§11.15.20", "VTarget Pack", 20, "0471", "1137 (0x04 71)", 1137),
    WorkedExample("§11.15.21", "VTarget Pack", 21, "0203", "(row, column) = (2, 3)",
                  FpaIndex(row=2, column=3)),
    WorkedExample("§11.15.21.1", "VMask LS", 1, "0239AA0239BF023B0B", "14762, 14783, 15115",
                  (14762, 14783, 15115)),
    WorkedExample("§11.15.21.2", "VMask LS", 2, "0402014A0204020159040402016A02",
                  "(pixel, run) = { (74, 2), (89, 4), (106, 2) }",
                  (MaskRun(74, 2), MaskRun(89, 4), MaskRun(106, 2)),
                  "vmask_bit_mask_octets"),
    WorkedExample("§11.15.22.2", "VObject LS", 2,
                  "4469736D6F756E742F4E6F6E2D636F6D626174616E742F46656D616C652F4368696C64",
                  "Dismount/Non-combatant/Female/Child", "Dismount/Non-combatant/Female/Child"),
    WorkedExample("§11.15.24.1", "VTracker LS", 1, "F81D4FAE7DEC11D0A76500A0C91E6BF6",
                  "F81D4FAE7DEC11D0A76500A0C91E6BF6", "f81d4fae7dec11d0a76500a0c91e6bf6",
                  "vtracker_track_id_framing"),
    WorkedExample("§11.15.24.2", "VTracker LS", 2, "01", "1 [0x01]",
                  {"code": 1, "status": "Active"}),
    WorkedExample("§11.15.24.3", "VTracker LS", 3, "0003824430F6CE40",
                  "April 19 2001, 04:25:21 GMT", "2001-04-19T04:25:21Z"),
    WorkedExample("§11.15.24.4", "VTracker LS", 4, "0003824430F6CE40",
                  "April 19 2001, 04:25:21 GMT", "2001-04-19T04:25:21Z"),
    WorkedExample("§11.15.24.6", "VTracker LS", 6, "74657374", "“test” [74 65 73 74]",
                  "test"),
    WorkedExample("§11.15.24.7", "VTracker LS", 7, "32", "50 [0x32]", 50),
    WorkedExample("§11.15.24.8", "VTracker LS", 8, "1B", "27 [0x1B]", 27),
    WorkedExample("§11.15.25.1", "VChip LS", 1, "6A706567", "jpeg", "jpeg"),
)

#: The pack members' printed examples, which have no tag of their own — a truncation pack's members
#: are positional. Keyed by pack and member index, checked by the same function.
PACK_WORKED_EXAMPLES: Final[tuple[tuple[str, str, int, str, str, float], ...]] = (
    ("§11.16", "Location Truncation Pack", 0, "42800000", "43.00 Degrees", 43.0),
    ("§11.16", "Location Truncation Pack", 1, "48800000", "110.00 Degrees", 110.0),
    ("§11.16", "Location Truncation Pack", 2, "2A94", "10,000 meters", 10000.0),
    ("§11.16", "Location Truncation Pack", 3, "2580", "Sigma_East = 300 (0x25 80)", 300.0),
    ("§11.16", "Location Truncation Pack", 4, "1900", "Sigma_North = 200 (0x19 00)", 200.0),
    ("§11.16", "Location Truncation Pack", 5, "0C80", "Sigma_Up = 100 (0x0C 80)", 100.0),
    ("§11.16", "Location Truncation Pack", 6, "7000", "Rho_East_North = 0.75 (0x70 00)", 0.75),
    ("§11.16", "Location Truncation Pack", 7, "6000", "Rho_East_Up = 0.50 (0x60 00)", 0.50),
    ("§11.16", "Location Truncation Pack", 8, "5000", "Rho_North_Up = 0.25 (0x50 00)", 0.25),
    ("§11.17", "Velocity Truncation Pack", 0, "4B00", "East_Component = 300 (0x4B 00)", 300.0),
    ("§11.17", "Velocity Truncation Pack", 1, "44C0", "North_Component = 200 (0x44 C0)", 200.0),
    ("§11.17", "Velocity Truncation Pack", 2, "3E80", "Up_Component = 100 (0x3E 80)", 100.0),
    ("§11.17", "Velocity Truncation Pack", 3, "2580", "Sigma_East = 300 (0x25 80)", 300.0),
    ("§11.17", "Velocity Truncation Pack", 4, "1900", "Sigma_North = 200 (0x19 00)", 200.0),
    ("§11.17", "Velocity Truncation Pack", 5, "0C80", "Sigma_Up = 100 (0x0C 80)", 100.0),
    ("§11.17", "Velocity Truncation Pack", 6, "7000", "Rho_East_North = 0.75 (0x70 00)", 0.75),
    ("§11.17", "Velocity Truncation Pack", 7, "6000", "Rho_East_Up = 0.50 (0x60 00)", 0.50),
    ("§11.17", "Velocity Truncation Pack", 8, "5000", "Rho_North_Up = 0.25 (0x50 00)", 0.25),
    ("§11.18", "Acceleration Truncation Pack", 0, "4B00", "East_Component = 300 (0x4B 00)", 300.0),
    ("§11.18", "Acceleration Truncation Pack", 1, "44C0", "North_Component = 200 (0x44 C0)", 200.0),
    ("§11.18", "Acceleration Truncation Pack", 2, "3E80", "Up_Component = 100 (0x3E 80)", 100.0),
    ("§11.18", "Acceleration Truncation Pack", 3, "2580", "Sigma_East = 300 (0x25 80)", 300.0),
    ("§11.18", "Acceleration Truncation Pack", 4, "1900", "Sigma_North = 200 (0x19 00)", 200.0),
    ("§11.18", "Acceleration Truncation Pack", 5, "0C80", "Sigma_Up = 100 (0x0C 80)", 100.0),
    ("§11.18", "Acceleration Truncation Pack", 6, "7000", "Rho_East_North = 0.75 (0x70 00)", 0.75),
    ("§11.18", "Acceleration Truncation Pack", 7, "6000", "Rho_East_Up = 0.50 (0x60 00)", 0.50),
    ("§11.18", "Acceleration Truncation Pack", 8, "5000", "Rho_North_Up = 0.25 (0x50 00)", 0.25),
)

#: §11.15's BER-OID Target ID Number example, which is neither a tagged element nor a pack member:
#: "1234 = [0x04 D2] = [0000 0100][1101 0010]2 [V] = [1 000 1001][0 101 0010]2 = [0x89 52]".
TARGET_ID_WORKED_EXAMPLE: Final[tuple[str, int]] = ("8952", 1234)


def _same(got: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        return isinstance(got, float) and abs(got - expected) < 5e-4
    if isinstance(got, dict) and "utc" in got:
        return got["utc"] == expected
    return got == expected


def check_against_the_documents_own_examples() -> list[str]:
    """Decode every printed example and say, one line each, whether it reproduces.

    Run on every suite run by `tests/test_cdm_vmti_codec.py`, which is `klv_uas_codec`'s and
    `klv_miis_codec`'s arrangement: the document-side witness is a test rather than a claim, and
    the three ruled disagreements are asserted to be exactly three — a fourth would mean either
    this transcription or the ruling has moved, and either is a person's to look at.
    """
    lines: list[str] = []

    octets, expected = TARGET_ID_WORKED_EXAMPLE
    got, _cursor = framing.decode_ber_oid(bytes.fromhex(octets), 0)
    lines.append(f"{'AGREE' if got == expected else 'DISAGREE'} §11.15 VTarget Pack Target ID "
                 f"Number (BER-OID): [0x{octets}] -> {got}, printed {expected}")

    for example in WORKED_EXAMPLES:
        element = _TABLES[example.owner][example.tag]
        try:
            got = _decode_value(element, bytes.fromhex(example.octets))
        except (VmtiError, ValueError) as exc:                        # pragma: no cover - a stop
            lines.append(f"DISAGREE {example.clause} {example.owner} Tag {example.tag} "
                         f"{element.name}: refused — {exc}")
            continue
        agrees = _same(got, example.expected)
        if example.disagreement is None:
            lines.append(f"{'AGREE' if agrees else 'DISAGREE'} {example.clause} {example.owner} "
                         f"Tag {example.tag} {element.name}: [0x{example.octets}] -> {got!r}, "
                         f"printed {example.printed!r}")
        else:
            record = PRINTED_EXAMPLE_DISAGREEMENTS[example.disagreement]
            half = ("the VALUE octets reproduce and the FRAMING octets printed around them do not"
                    if agrees else
                    f"the printed octets decode to {got!r} where the entry prints "
                    f"{example.printed!r}")
            lines.append(f"DISAGREE {example.clause} {example.owner} Tag {example.tag} "
                         f"{element.name}: {half}. {record['the_table_gives']}")

    for clause, pack, index, octets, printed, expected in PACK_WORKED_EXAMPLES:
        member = _PACK_MEMBERS[pack][index]
        assert member.imapb is not None
        got = imapb_codec.decode(member.imapb[0], member.imapb[1], bytes.fromhex(octets))
        agrees = isinstance(got, float) and abs(got - expected) < 5e-4
        lines.append(f"{'AGREE' if agrees else 'DISAGREE'} {clause} {pack} member {index} "
                     f"{member.name}: [0x{octets}] -> {got!r}, printed {printed!r}")

    disagreements = sum(1 for line in lines if line.startswith("DISAGREE"))
    lines.append(
        f"{len(lines)} printed examples decoded, {len(lines) - disagreements} AGREE and "
        f"{disagreements} DISAGREE, both of them ruled at PRINTED_EXAMPLE_DISAGREEMENTS — which "
        f"carries {len(PRINTED_EXAMPLE_DISAGREEMENTS)} entries, the third being a naming defect "
        f"with no octet behind it and therefore no row here")
    return lines
