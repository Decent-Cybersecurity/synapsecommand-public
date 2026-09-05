"""The MISB ST 1204.1 MIIS Core Identifier: the binary value ST 0601 item 94 carries.

WHAT THIS MODULE IS, AND WHY IT IS ITS OWN MODULE
-------------------------------------------------
`klv_codec` frames, `klv_uas_codec` is the ITEM layer for ST 0601.14a, `klv_pack_codec` reads the
two items whose Value is a pack, and this module reads the one item whose Value is **a different
document's whole data structure**. ST 0601.14a §8.94.1 says so itself: "The MIIS Core Identifier
allows users to include the MIIS Core Identifier (MISB ST 1204 [16]) Binary Value (opposed to the
text-based representation) within MISB ST 0601. Tag 94's value does not include MISB ST 1204's
16-byte Key or length, only the value portion."

**THE PLACEMENT TAKES `klv_security_codec`'s FIRST REASON, WHICH IS THE ONE `klv_pack_codec` HAD TO
ARGUE AROUND.** That module's docstring gives three grounds for a separate file and records that
the first — *"the precedent is one item layer per document"* — pointed the other way for packs,
because §6.3 is ST 0601.14a's own section. Here it points straight at a separate file: every clause
below is read from **ST 1204.1**, a different document with its own cover, its own revision history
and its own SHA-256, and a reader asking "which copy is this read from" must not get ST 0601.14a's
answer. The second ground applies too — this structure has no tags at all, so there is nothing to
key on `ITEMS` — and the third applies hardest: `_Item`'s twenty-seven fields describe one affine
map over one integer, and a Core Identifier is a version, a bit-mapped usage byte and up to three
UUIDs whose COUNT the usage byte decides.

WHAT ST 1204.1 IS, AND THE ONE THING TO READ TWICE
---------------------------------------------------
§1: "This Standard (ST) defines (a) the required identification elements that shall be inserted
into motion imagery streams or files". §5: a Core Identifier is either a **Foundational** Core
Identifier (FCID) — up to three UUIDs, for the sensor, the platform and a window — or a **Minor**
Core Identifier (MCID), a single UUID for the case where no foundational identity exists.
`ST 1204.1-28`: "When Motion Imagery data includes a Foundational Core Identifier then a Minor Core
Identifier shall NOT be used, generated or inserted into the Motion Imagery data." The two are
alternatives and the EBNF states the exclusion as a subtraction, quoted at `USAGE_GRAMMAR` below.

**THE SENTENCE THAT RULES THE MAPPING, AND IT IS THE DOCUMENT'S AND NOT THIS REPOSITORY'S.** §8,
Generating Enterprise UUID's from Core Identifiers: "For FCIDs up to three enterprise identifiers
can be constructed: (1) an identifier from the FCID's Sensor ID, (2) an identifier from the FCID's
Platform ID and (3) an identifier from the FCID's Window ID. These three enterprise identifiers can
be used independently or together. **Since the Core ID can change over time, combining the three
identifiers into one UUID is not used as a method for Enterprise UUIDs.**" So a consumer keying on
this structure gets *several* identifiers and never one made out of them — which is why
`adapters/stanag4609.py` emits one `SourceId` per component and never a synthesised composite. The
document forbade the composite before anyone here proposed it.

THE BINARY LAYOUT, TRANSCRIBED FROM §6.2.1 (Table 4 and Table 5, pages 18)
--------------------------------------------------------------------------
Read from the pinned copy at `fixtures/klv/spec/ST1204.1.pdf`, SHA-256 `2503960a…61d9f1c5`,
36 pages, cover date 24 October 2013.

* **Version** — Table 4: "Version is a BER OID (see [1]) encoded value for the version number".
  §5.1.3.1: "The Core Identifier always contains the version number as the first value **so that
  parsers can read this value and determine how to interpret the rest of the Core Identifier
  values**", and "Standard 1204.1 would use a version value of '1'". That sentence is what makes a
  version this module does not hold a REFUSAL rather than a guess — see `decode_core_identifier`.
* **Usage Value** — Table 4: "Bitwise mapping of the Usage Values as shown in Table 5", and "The
  Usage Value Byte should be treated as a BER OID value." Table 5, verbatim, is `USAGE_BITS` below.
* **FCID** — Table 4: "Combination of Sensor ID, Platform ID and/or Window ID; variable length
  depending on which values are included. **Each UUID value is 16 bytes so valid lengths of FMIC
  are 16, 32 or 48 bytes.** The order of the Sensor ID, Platform ID and Window ID is important and
  should follow the EBNF in Section 6.1". `FMIC` is the document's own spelling in that cell and is
  quoted rather than repaired; every other mention in 36 pages reads `FCID`.
* **MCID** — Table 4: "Single UUID value of 16 bytes".

So the value is `version_octets || usage_octets || 16 * n`, and `n` is not on the wire: **the usage
byte is the only thing that says how many UUIDs follow.** That is the whole of why a usage byte
disagreeing with the octet count is refused here and not reconciled — there is no third statement
to break the tie, and picking either one over the other would be this layer deciding which half of
a malformed identifier to believe.

THE TEXT FORMAT, AND WHICH OF THE TWO RENDERINGS IS A `source_id`
------------------------------------------------------------------
§6.2.2.1 defines **two** renderings and Table 8 names both:

1. the whole Core Identifier — `VersionUsageValue:SensorID/PlatformID/WindowID:CheckValue`, e.g.
   `0170:F592-F023-7336-4AF8-AA91-62C0-0F2E-B2DA/16B7-4341-0008-41A0-BE36-5B5A-B96A-3645:D3`;
2. **UUID String Value** — Table 8's own row: "39 character value composed of: hex value of the
   UUID, plus separator characters (after every four hex characters a dash, '-', is inserted)
   E.g.: 0102-0304-0506-0708-090A-0B0C-0D0E-0F10."

**Both are carried and they are carried in different places, because they are identifiers of
different things.** A `SourceId` names ONE identity, so its value is the component's UUID String
Value — the document's own text representation *of that component*. The whole-identifier string
names the Core Identifier, which is the combination, so it rides in `attributes` beside the raw hex
along with its check value. Putting the whole string in both `source_ids` entries would make them
differ only by `system` and would assert the composite §8 has just refused.

Table 8's closing note is transcribed at `canonical_uuid` because it is the bridge to every other
UUID in this repository: "to convert an embedded UUID into the UUID Hexadecimal Representation ([2]
section 6.4) the first and last two separator characters are removed", worked in the document as
`0102-0304-0506-0708-090A-0B0C-0D0E-0F10` -> `01020304-0506-0708-090A-0B0C0D0E0F10`.

THE CHECK VALUE, AND WHY IT IS COMPUTED HERE RATHER THAN TRANSCRIBED
---------------------------------------------------------------------
Appendix B defines a two-permutation check byte and then says "Please see the reference code for
complete details of the algorithm." **No reference code is in the 36 pages**, so the algorithm was
implemented from the prose alone and then MEASURED against the document's own printed check value
— see `check_against_the_documents_own_examples`. The prose fixes the permutations exactly and
leaves one thing open, the loop's starting index; `k` starting at **1** is what reproduces the
document's `D3`, and `0` yields `A6`. That is recorded at `check_value` as a reading taken rather
than a convention chosen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from synapse_cdm.adapters import klv_codec as framing

__all__ = [
    "CoreIdentifierError", "IdentifierComponent", "CoreIdentifier",
    "SOURCE_ST_1204_1", "USAGE_BITS", "USAGE_GRAMMAR", "QUALITY_VALUES", "VALID_FCID_LENGTHS",
    "NIL_UUID_HEX", "VERSION_HELD", "REFUSAL_CLASSES", "DEFECT_CLASSES",
    "DOCUMENT_EXAMPLE", "CARRIER_BASIS", "AUGMENTATION_IDENTIFIERS_ABSENT",
    "check_value", "uuid_string_value", "canonical_uuid", "decode_core_identifier",
    "check_against_the_documents_own_examples",
]

#: The pinned copy every citation in this module is read from, stated here for the reason
#: `klv_uas_codec` states it: a module that cites sections without naming the copy cites a memory.
SOURCE_ST_1204_1: Final[str] = (
    "MISB ST 1204.1, SHA-256 "
    "2503960a0af92b73fe329663b2538b87fbdcca4823c968885a26978d61d9f1c5, "
    "fixtures/klv/spec/ST1204.1.pdf"
)

#: Where ST 0601.14a puts it. §8.94, page 147, Format `byte`, Length Variable, Max Length 50,
#: Required in LS Optional. The KLV Key in that block is the same one ST 1204.1 §6.2.1.1 gives for
#: the stand-alone item — `06.0E.2B.34.01.01.01.01.0E.01.04.05.03.00.00.00 (CRC 30280)`, "the
#: normative Symbol name is 'core_id'" — and item 94 carries the VALUE only.
CARRIER_BASIS: Final[str] = (
    "MISB ST 0601.14a §8.94, page 147: 'MISB ST 1204 MIIS Core Identifier binary value', Format "
    "byte, Length Variable, Max Length 50. §8.94.1: \"Tag 94's value does not include MISB "
    "ST 1204's 16-byte Key or length, only the value portion\""
)

#: Table 5, verbatim, most significant bit first. The two Reserved rows are kept in the table
#: rather than dropped, because a decoder that does not know a bit is reserved cannot tell a
#: reserved bit that is set from a field it forgot to read.
USAGE_BITS: Final[tuple[tuple[str, str, str], ...]] = (
    ("7 - MSB", "Reserved", "Always Zero"),
    ("6,5", "Sensor ID Type", "11 = Physical, 10=Virtual, 01=Managed, 00=None"),
    ("4,3", "Platform ID Type", "11 = Physical, 10=Virtual, 01=Managed, 00=None"),
    ("2", "Window ID Type", "1=Included, 0=None"),
    ("1", "Minor ID Type", "1=Included, 0=None"),
    ("0 - LSB", "Reserved", "Always Zero"),
)

#: §6.1's EBNF for the Usage Value, verbatim. The trailing subtraction is the clause that makes an
#: all-None usage byte a refusal rather than an empty identifier: the grammar removes that one
#: production from the set it just built.
USAGE_GRAMMAR: Final[str] = (
    "Usage Value = ((Sensor ID Type, Platform ID Type, Window ID Type, 'None') | ('None', "
    "'None', 'None', Minor ID Type)) - ('None', 'None', 'None', 'None');"
)

#: Table 5's two-bit encoding for the Sensor and Platform Identifier Types, and Table 2's names
#: for them. Table 2 is the cell that gives Window and Minor only two values, `Included` and
#: `None`, which is why those two are booleans below and not members of this map.
QUALITY_VALUES: Final[dict[int, str | None]] = {
    0b11: "Physical", 0b10: "Virtual", 0b01: "Managed", 0b00: None,
}

#: Table 4: "Each UUID value is 16 bytes so valid lengths of FMIC are 16, 32 or 48 bytes."
VALID_FCID_LENGTHS: Final[tuple[int, ...]] = (16, 32, 48)

#: §5.1.4 and `ST 1204.1-31`: the ONLY permitted temporary Platform Identifier, "the nil UUID [3],
#: which is 16 bytes of the hex value '0x00'". `ST 1204.1-32` then requires that a Core Identifier
#: leaving or stored on the platform "shall be fully formed with no temporary Identifiers" — so
#: this value on the wire is a stated defect and never an identity.
NIL_UUID_HEX: Final[str] = "0" * 32

#: §5.1.3.1: "Standard 1204.1 would use a version value of '1', Standard 1204.2 would use a version
#: value of '2', etc." One edition is held, so one version is readable.
VERSION_HELD: Final[int] = 1

#: What this module refuses, each keyed to the clause that decides it. A refusal yields NO decoded
#: identifier; the octets stay parked at the caller's `raw_items` and the class is reported.
REFUSAL_CLASSES: Final[dict[str, str]] = {
    "usage_byte_absent": (
        "the value is shorter than a Version octet plus a Usage Value octet. §6.1: 'Core "
        "Identifier = Version, Usage Value, FCID | MCID' — both are unconditional"),
    "version_not_held": (
        "the Version octet states an edition this module does not hold. §5.1.3.1: the version is "
        "first 'so that parsers can read this value and determine how to interpret the rest of "
        "the Core Identifier values' — a parser that reads on past a version it cannot interpret "
        "is doing the one thing that sentence exists to prevent"),
    "usage_value_is_all_none": (
        "the Usage Value names no identifier at all. §6.1's grammar subtracts exactly this "
        "production: " + USAGE_GRAMMAR),
    "usage_value_mixes_fcid_and_mcid": (
        "the Usage Value names both a Foundational component and a Minor Identifier. §6.1's "
        "grammar offers them as ALTERNATIVES, and `ST 1204.1-28`: 'When Motion Imagery data "
        "includes a Foundational Core Identifier then a Minor Core Identifier shall NOT be used, "
        "generated or inserted into the Motion Imagery data'"),
    "usage_value_is_multi_octet": (
        "the Usage Value Byte's reserved bit 7 is set. Table 5 gives it as 'Always Zero' and "
        "§6.2.1 states what a future edition will mean by it: 'Future changes, if needed, will "
        "use bit 7 to indicate an expanded length of this value from one byte to multiple bytes'. "
        "So the octet after it is not the first UUID octet, and every length below would be read "
        "from the wrong offset"),
    "length_does_not_match_the_usage_value": (
        "the Usage Value names a number of UUIDs the Value's length cannot carry. Table 4: 'Each "
        "UUID value is 16 bytes so valid lengths of FMIC are 16, 32 or 48 bytes.' The usage byte "
        "is the ONLY statement of how many follow, so a disagreement has no third witness and is "
        "not reconciled here"),
}

#: What this module records and does NOT refuse. A defect annotation rides beside a decoded value:
#: the identifier is readable, and something the document requires of it is not met.
DEFECT_CLASSES: Final[dict[str, str]] = {
    "reserved_lsb_set": (
        "the Usage Value Byte's reserved bit 0 is set. Table 5 gives it as 'Always Zero'. Unlike "
        "bit 7 it carries no stated future meaning, so nothing about the layout is in doubt and "
        "the identifiers the byte states are still read — recorded, not repaired"),
    "temporary_platform_identifier": (
        "the Platform Identifier is the nil UUID, which §5.1.4 defines as the pre-fill "
        "placeholder and `ST 1204.1-31` permits only as a temporary value. `ST 1204.1-32`: 'When "
        "the MIIS Compliant Sensor motion imagery data, which contains a Foundational Core "
        "Identifier, leaves the platform or is stored on the platform, the Foundational Core "
        "Identifier shall be fully formed with no temporary Identifiers'. The component is "
        "DECODED and carried; what it is not is an identity, because the document has just said "
        "it names nothing"),
}

#: ST 1301.2, read in full — four pages, the smallest document in `spec/`. Recorded here because
#: the absence is the finding, and an absence nobody wrote down reads later like an omission.
AUGMENTATION_IDENTIFIERS_ABSENT: Final[str] = (
    "MISB ST 1301.2 (27 February 2014, 4 pages, SHA-256 3d08d35d…e509f9a6) defines the "
    "Augmentation Identifiers Local Set — `ST 1301.2-01` gives its key as "
    "06.0E.2B.34.02.0B.01.01.0E.01.03.05.03.00.00.00 (CRC 47531, symbol 'miis_lds') — and defines "
    "NO augmentation identifier to put in it: Appendix A's Table 2, the table its own §6.1.1 "
    "sends the reader to for 'the MISB defined identifiers', prints four rows reading '8 <Name> "
    "<Key> <Supporting Documentation>', '9 <Name> <Key> <Supporting Documentation>', '10 <Name> "
    "<Key> <Supporting Documentation>' and '11 …' — placeholders, with the note 'Additional items "
    "are added per MISB approved updates to this document'. AND ST 0601.14a DOES NOT CARRY THE "
    "SET: over the pinned 218 pages, joined and collapsed by `gates/pdf_text.py`'s rule, the "
    "string '1301' occurs ZERO times and so does 'Augmentation'. So there is no carrier in the "
    "document this adapter reads, and had there been one there would be nothing defined to "
    "decode inside it. Both halves are recorded because either alone would read like the other's "
    "cause"
)

#: §6.2.2.1's worked example, and §8.94's, which are the SAME identifier printed by two documents.
#: Every field is quoted from a printed cell — Table 6 (page 20), Table 7 (page 21), Table 9
#: (page 24) and ST 0601.14a's §8.94 block (page 147).
DOCUMENT_EXAMPLE: Final[dict[str, object]] = {
    "octets": ("0170F592F02373364AF8AA9162C00F2EB2DA"
               "16B7434100084 1A0BE365B5AB96A3645".replace(" ", "")),
    "text": ("0170:F592-F023-7336-4AF8-AA91-62C0-0F2E-B2DA/"
             "16B7-4341-0008-41A0-BE36-5B5A-B96A-3645:D3"),
    "check_value": "D3",
    "version": 1,
    "usage_byte": 0x70,
    "sensor_quality": "Physical",
    "platform_quality": "Virtual",
    "ebnf": ("1, Physical, Virtual, None, None, F592-F023-7336-4AF8-AA91-62C0-0F2E-B2DA, "
             "16B7-4341-0008-41A0-BE36-5B5A-B96A-3645"),
    "st_1204_1_klv_length": 0x22,
    "st_0601_14a_klv_length": 0x24,
    "sections": "ST 1204.1 §6.2.1 Table 6, §6.2.1.1 Table 7, §6.2.2.1 Table 9; ST 0601.14a §8.94",
}


# ------------------------------------------------------------------ Appendix B, the check value


def _p(h: int) -> int:
    """Appendix B step 1a: p(H) = p([a,b,c,d]) = [a^b,c,d,a], `a` the most significant bit."""
    a, b, c, d = (h >> 3) & 1, (h >> 2) & 1, (h >> 1) & 1, h & 1
    return ((a ^ b) << 3) | (c << 2) | (d << 1) | a


def _q(h: int) -> int:
    """Appendix B step 1b: q([a,b,c,d]) = [d,a^d,b,c], the "inverse bit manipulation method"."""
    a, b, c, d = (h >> 3) & 1, (h >> 2) & 1, (h >> 1) & 1, h & 1
    return (d << 3) | ((a ^ d) << 2) | (b << 1) | c


def _iterated(table: tuple[int, ...], h: int, k: int) -> int:
    """`p^k(H)` — Appendix B's notation: "pj(H) is multiple permutations ... p2(H) = p(p(H))"."""
    for _ in range(k):
        h = table[h]
    return h


_P_TABLE: Final[tuple[int, ...]] = tuple(_p(h) for h in range(16))
_Q_TABLE: Final[tuple[int, ...]] = tuple(_q(h) for h in range(16))


def check_value(hex_digits: str) -> int:
    """Appendix B's check byte over a Core Identifier's hex digits, separators excluded.

    Appendix B, step 2, verbatim: "Loop k through hex values in hex string H ... CheckVal_p =
    CheckVal_p ^ pk(H) ... CheckVal_q = CheckVal_q ^ qk(H) ... CheckVal_byte = Shift Left 4 bits
    (CheckVal_p) or'ed with (CheckVal_q)". Table 8's Other Note fixes the input: "the check
    character validates only the hex digits, not the separator characters" — and the digits are the
    WHOLE identifier's, version and usage byte included, which Table 9 shows by printing `D3`
    against a string that opens `0170`.

    **`k` STARTS AT 1, AND THAT IS A READING AND NOT A CONVENTION.** The prose fixes both
    permutations exactly and never states the loop's first index. Measured against the document's
    own printed check value on its own 68 hex digits: `k` from 1 yields `D3`, which is what
    §6.2.2.1's Table 9 prints; `k` from 0 yields `A6`. `check_against_the_documents_own_examples()`
    re-runs that measurement on every suite run rather than leaving it as a remembered result.

    Appendix B also records what this is NOT, and it is worth keeping beside the code: the method
    "is specifically designed to detect the common problems that occur when humans enter data into
    systems, which is different than other techniques such as check sums and CRC's". A Core
    Identifier that fails this check has been mistyped, not corrupted in transit.
    """
    check_p = check_q = 0
    for index, character in enumerate(hex_digits):
        digit = int(character, 16)
        k = index + 1
        check_p ^= _iterated(_P_TABLE, digit, k)
        check_q ^= _iterated(_Q_TABLE, digit, k)
    return (check_p << 4) | check_q


# ------------------------------------------------------------------ §6.2.2.1, the text renderings


def uuid_string_value(uuid_hex: str) -> str:
    """Table 8's UUID String Value: "39 character value ... a dash after every four hex characters".

    The document's own example is `0102-0304-0506-0708-090A-0B0C-0D0E-0F10`, and 32 hex digits plus
    seven separators is where the 39 comes from. Upper case, as every printed example in the
    document is and as ST 1204.1's own XML pattern requires — `[A-F0-9]{4}` throughout Listing 1.
    """
    digits = uuid_hex.upper()
    return "-".join(digits[i:i + 4] for i in range(0, len(digits), 4))


def canonical_uuid(uuid_hex: str) -> str:
    """Table 8's note, applied: the RFC 4122 / ITU-T X.667 §6.4 Hexadecimal Representation.

    "to convert an embedded UUID into the UUID Hexadecimal Representation ([2] section 6.4) the
    first and last two separator characters are removed" — worked in the document as
    `0102-0304-0506-0708-090A-0B0C-0D0E-0F10` -> `01020304-0506-0708-090A-0B0C0D0E0F10`.

    Carried because it is the form every other UUID in this repository is written in, and a
    consumer joining a MIIS identity to anything else needs the two spellings to be one value.
    """
    d = uuid_hex.upper()
    return f"{d[0:8]}-{d[8:12]}-{d[12:16]}-{d[16:20]}-{d[20:32]}"


# ------------------------------------------------------------------ the decoded structure


class CoreIdentifierError(ValueError):
    """A Core Identifier this module refuses to decode, with the clause that decides it."""

    def __init__(self, message: str, *, refusal_class: str):
        super().__init__(message)
        self.refusal_class = refusal_class


@dataclass(frozen=True)
class IdentifierComponent:
    """One UUID out of a Core Identifier, with the role and quality the Usage Value gives it.

    `role` is `sensor`, `platform`, `window` or `minor` — §6.1's EBNF names, in its order. `quality`
    is Table 2's value for that role: `Physical`, `Virtual` or `Managed` for the two Device
    Identifiers, and `Included` for the Window and Minor Identifiers, which Table 2 gives only two
    values each.
    """

    role: str
    quality: str
    uuid_hex: str
    text: str
    canonical: str
    is_nil: bool

    @property
    def system(self) -> str:
        """The `SourceId.system` this component keys under.

        Role and quality both, because they are two different facts and a consumer joining feeds
        needs the first and needs to be able to price the second: §5.1.1 ranks the three qualities
        by what they guarantee — a Physical Identifier "is generated or stored within the device
        itself and never changes over the lifetime of the device", a Managed one only "will only
        serve users after the control station" — and Table 1 turns that ranking into nine numbered
        Identifier Quality Levels. Two feeds that agree on a Physical Sensor ID are the same sensor;
        two that agree on a Managed one agree about what one control station was told.
        """
        return f"MIIS-{self.role.upper()}-{self.quality.upper()}"


@dataclass(frozen=True)
class CoreIdentifier:
    """One decoded ST 1204.1 Core Identifier, as this layer read it."""

    version: int
    usage_byte: int
    kind: str
    components: tuple[IdentifierComponent, ...]
    text: str
    check_value_hex: str
    octets_hex: str
    defects: tuple[dict, ...]

    @property
    def identities(self) -> tuple[IdentifierComponent, ...]:
        """The components that name something, which is not always all of them.

        A nil Platform Identifier is decoded, carried and annotated — see
        `DEFECT_CLASSES['temporary_platform_identifier']` — and is absent here, because §5.1.4
        defines it as a placeholder for an identifier that has not been inserted yet. Promoting it
        to an identity would put a value on the wire's behalf that the wire says means nothing, and
        every consumer that pre-filled would then agree with every other one.
        """
        return tuple(c for c in self.components if not c.is_nil)


def _usage_value(byte: int) -> tuple[str | None, str | None, bool, bool]:
    """Table 5, applied to one octet: (sensor quality, platform quality, window, minor)."""
    sensor = QUALITY_VALUES[(byte >> 5) & 0b11]
    platform = QUALITY_VALUES[(byte >> 3) & 0b11]
    window = bool((byte >> 2) & 1)
    minor = bool((byte >> 1) & 1)
    return sensor, platform, window, minor


def decode_core_identifier(value: bytes) -> CoreIdentifier:
    """Read ST 0601.14a item 94's Value as ST 1204.1 §6.2.1's Core Identifier Binary Value.

    The Value is the VALUE portion only — §8.94.1 says so — so there is no 16-byte key and no BER
    length to strip here, exactly as `klv_security_codec.decode_set` is handed item 48's Value bare.

    **THE ORDER IS THE EBNF'S AND IS NOT DERIVABLE FROM THE OCTETS.** §6.1: `FCID = (Sensor ID,
    [Platform ID], [Window ID]) | (Platform ID, [Window ID]) | Window ID`, and Table 4 repeats it —
    "The order of the Sensor ID, Platform ID and Window ID is important and should follow the EBNF
    in Section 6.1". Sixteen octets with the Platform bit set and the Sensor bit clear are a
    Platform ID; the same sixteen with the Sensor bit set are a Sensor ID. Nothing in the UUID says
    which, which is the property that makes the usage byte load-bearing rather than descriptive.
    """
    if len(value) < 2:
        raise CoreIdentifierError(
            f"a Core Identifier of {len(value)} octet(s) carries no Version and Usage Value pair. "
            + REFUSAL_CLASSES["usage_byte_absent"],
            refusal_class="usage_byte_absent")

    version, after_version = framing.decode_ber_oid(value, 0)
    if version != VERSION_HELD:
        raise CoreIdentifierError(
            f"a Core Identifier stating Version {version}; this module holds ST 1204.{VERSION_HELD}"
            f" and reads Version {VERSION_HELD} only. "
            + REFUSAL_CLASSES["version_not_held"],
            refusal_class="version_not_held")

    if after_version >= len(value):
        raise CoreIdentifierError(
            "a Core Identifier whose Version octets are the whole value. "
            + REFUSAL_CLASSES["usage_byte_absent"],
            refusal_class="usage_byte_absent")

    usage_byte = value[after_version]
    if usage_byte & 0b1000_0000:
        raise CoreIdentifierError(
            f"a Usage Value Byte of 0x{usage_byte:02X} with bit 7 set. "
            + REFUSAL_CLASSES["usage_value_is_multi_octet"],
            refusal_class="usage_value_is_multi_octet")

    sensor, platform, window, minor = _usage_value(usage_byte)
    if sensor is None and platform is None and not window and not minor:
        raise CoreIdentifierError(
            f"a Usage Value Byte of 0x{usage_byte:02X} naming no identifier. "
            + REFUSAL_CLASSES["usage_value_is_all_none"],
            refusal_class="usage_value_is_all_none")
    if minor and (sensor is not None or platform is not None or window):
        raise CoreIdentifierError(
            f"a Usage Value Byte of 0x{usage_byte:02X} naming a Minor Identifier beside a "
            "Foundational component. " + REFUSAL_CLASSES["usage_value_mixes_fcid_and_mcid"],
            refusal_class="usage_value_mixes_fcid_and_mcid")

    declared: list[tuple[str, str]] = []
    if minor:
        declared.append(("minor", "Included"))
    else:
        if sensor is not None:
            declared.append(("sensor", sensor))
        if platform is not None:
            declared.append(("platform", platform))
        if window:
            declared.append(("window", "Included"))

    body = value[after_version + 1:]
    expected = 16 * len(declared)
    if len(body) != expected:
        roles = ", ".join(f"{role} ({quality})" for role, quality in declared)
        raise CoreIdentifierError(
            f"a Usage Value Byte of 0x{usage_byte:02X} names {len(declared)} identifier(s) — "
            f"{roles} — which is {expected} octet(s), and {len(body)} octet(s) follow it. "
            + REFUSAL_CLASSES["length_does_not_match_the_usage_value"],
            refusal_class="length_does_not_match_the_usage_value")

    components: list[IdentifierComponent] = []
    defects: list[dict] = []
    for index, (role, quality) in enumerate(declared):
        uuid_hex = body[index * 16:(index + 1) * 16].hex().upper()
        is_nil = uuid_hex == NIL_UUID_HEX
        components.append(IdentifierComponent(
            role=role, quality=quality, uuid_hex=uuid_hex,
            text=uuid_string_value(uuid_hex), canonical=canonical_uuid(uuid_hex), is_nil=is_nil))
        if is_nil and role == "platform":
            defects.append({
                "class": "temporary_platform_identifier",
                "role": role, "quality": quality, "uuid": uuid_hex,
                "basis": DEFECT_CLASSES["temporary_platform_identifier"],
                "source": SOURCE_ST_1204_1,
            })

    if usage_byte & 0b0000_0001:
        defects.append({
            "class": "reserved_lsb_set",
            "usage_byte": f"0x{usage_byte:02X}",
            "basis": DEFECT_CLASSES["reserved_lsb_set"],
            "source": SOURCE_ST_1204_1,
        })

    prefix = value[:after_version + 1].hex().upper()
    digits = prefix + "".join(c.uuid_hex for c in components)
    check = check_value(digits)
    text = (f"{prefix}:" + "/".join(c.text for c in components) + f":{check:02X}")

    return CoreIdentifier(
        version=version, usage_byte=usage_byte,
        kind="MCID" if minor else "FCID",
        components=tuple(components), text=text, check_value_hex=f"{check:02X}",
        octets_hex=value.hex().upper(), defects=tuple(defects))


# ------------------------------------------------------------------ the document's own examples


def check_against_the_documents_own_examples() -> list[str]:
    """Decode the printed example and compare every derived field with a printed cell.

    THE POINT, on `klv_uas_codec.check_against_the_documents_own_examples`'s own ground: the layout
    above was transcribed from drawn tables, and the check-value algorithm was implemented from
    prose whose closing sentence points at reference code the document does not contain. Both are
    the kind of thing that is wrong in ways only the document can catch.

    **THE TWO DOCUMENTS PRINT THE SAME IDENTIFIER, WHICH MAKES THIS A CROSS-CHECK AND NOT ONLY A
    SELF-CHECK.** ST 1204.1 prints it three times — Table 6's binary explanation, Table 7's KLV
    triplet, Table 9's text value — and ST 0601.14a §8.94 prints it a fourth, as item 94's Example
    KLV Item. Four printings, two documents, one value.

    **THE ONE PLACE THE FOUR DISAGREE IS REPORTED AND NOT RECONCILED.** ST 1204.1 Table 7 gives the
    KLV Length as `22` and glosses it "Value is 34 bytes"; ST 0601.14a §8.94 gives the same value's
    Len as `24`. The Value both print is 34 octets, which is `0x22`; `0x24` is 36, which is 34 plus
    the two octets of Tag and Len that the same row prints beside it. This function asserts the
    octet count against ST 1204.1's cell and RECORDS ST 0601.14a's as a divergence — a gate is
    never corrected in passing, and the arithmetic that fits is not a finding about intent.

    Returns one line per comparison, in the shape `klv_uas_codec`'s twin returns.
    """
    lines: list[str] = []
    octets = bytes.fromhex(str(DOCUMENT_EXAMPLE["octets"]))
    decoded = decode_core_identifier(octets)

    def record(what: str, printed: object, derived: object) -> None:
        verdict = "AGREE" if printed == derived else "DISAGREE"
        lines.append(f"{verdict}  {what}: printed {printed!r}, derived {derived!r}")

    record("ST 1204.1 §6.2.2.1 Table 9 text value", DOCUMENT_EXAMPLE["text"], decoded.text)
    record("ST 1204.1 Appendix B check value", DOCUMENT_EXAMPLE["check_value"],
           decoded.check_value_hex)
    record("ST 1204.1 §6.2.1 Table 6 version", DOCUMENT_EXAMPLE["version"], decoded.version)
    record("ST 1204.1 §6.2.1 Table 6 usage byte", DOCUMENT_EXAMPLE["usage_byte"],
           decoded.usage_byte)
    record("ST 1204.1 §6.2.1 Table 6 UUID-1 role and quality", ("sensor", "Physical"),
           (decoded.components[0].role, decoded.components[0].quality))
    record("ST 1204.1 §6.2.1 Table 6 UUID-2 role and quality", ("platform", "Virtual"),
           (decoded.components[1].role, decoded.components[1].quality))
    record("ST 1204.1 §6.2.1.1 Table 7 KLV Length", DOCUMENT_EXAMPLE["st_1204_1_klv_length"],
           len(octets))
    record("ST 0601.14a §8.94 Len cell", DOCUMENT_EXAMPLE["st_0601_14a_klv_length"], len(octets))
    record("Appendix B loop index k from 0 (the reading NOT taken)", "A6",
           f"{_k_from_zero(str(DOCUMENT_EXAMPLE['octets'])):02X}")
    return lines


def _k_from_zero(digits: str) -> int:
    """The check value the same algorithm gives with `k` from 0, kept so the reading is re-derived.

    Appendix B leaves the loop's first index unstated, and `check_value`'s docstring says `1` was
    chosen because it reproduces `D3`. A remembered alternative is not a measurement, so the
    alternative is computed here and reported by
    `check_against_the_documents_own_examples()` on every suite run.
    """
    check_p = check_q = 0
    for index, character in enumerate(digits):
        digit = int(character, 16)
        check_p ^= _iterated(_P_TABLE, digit, index)
        check_q ^= _iterated(_Q_TABLE, digit, index)
    return (check_p << 4) | check_q
