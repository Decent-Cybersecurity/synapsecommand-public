"""ASTERIX Category 023 — CNS/ATM Ground Station and Service Status Reports. Blocks in, CDM out.

Adapter #14, the smallest specification pinned in this repository — nine data items on 21 printed
pages — and the second whose primary object is the thing that produces surveillance data rather
than the surveillance data.

INGEST  one ASTERIX **data block** — `CAT | LEN | FSPEC + items | ...` — becomes an Entity + an
        Event per record, in block order, and a SECOND Entity on the two report types that are
        about a service rather than about the station.
EGRESS  Entities that CAME FROM CAT023 become one data block, byte-exactly. Anything else is a
        refusal that names what is missing.

Implements the row set in `FORMAT_COVERAGE.md` under "ASTERIX Category 023", which was written and
reviewed as a specification BEFORE this file existed. Where the code and a row disagree the row
wins, or the row changes in the same commit.

THIS IS THE CAT034 ANALOGUE, AND THE ONE STRUCTURAL DIFFERENCE IS A SECOND OBJECT
---------------------------------------------------------------------------------
`asterix_cat034.py` established the shape: the station is the object, `entity_type` is `SENSOR`,
`affiliation` is `UNKNOWN`, there is no `Kinematics` anywhere, and a report-type item drives a
per-type presence matrix. All of that holds here. What Part 16 adds is that **two of its three
report types are about a SERVICE**, and one station provides several — §4.5.1.2: "Each ground
station may provide several services, and the status of each shall be reported independently in
each service status report." So a type 002 or 003 record emits TWO Entities, and the service's
identity is the PAIR `(SAC/SIC, Service Identification)` because the SID is "allocated by the
system" and means nothing across stations. FORMAT_COVERAGE.md settlement 2 argues it.

WHAT THIS CATEGORY DOES NOT CARRY, AND IT IS WORTH STATING FIRST
----------------------------------------------------------------
**A position.** Nine items and not one coordinate. `Entity.position` is `None` on every object this
adapter emits, and `attributes.position_basis` says so in the object rather than in a comment:
`I023/200` is an operational range in nautical miles with no centre, and §4.4.1 asserts that a
SAC/SIC is dedicated and unambiguous per ground station without saying where any station is.
Reading a station position out of a CAT034 record to locate a CAT023 station is cross-payload
state, which is the refusal `asterix_cat034.py`'s settlement 2 already made in the other
direction. `Event.geometry` is `None` for the same reason and permanently: a range is a radius and
there is no centre in the category, so the derivation cannot arise from a conformant record at all.

THE INJECTED CLOCK, AND THERE IS NO SECOND INJECTED VALUE
----------------------------------------------------------
`clock`, as every adapter has: `I023/070` is a count of 1/128 s since midnight with no date, so the
date comes from the injected clock and the adapter never reads the wall clock. There is no
`sensor_position` argument and there will not be one — this adapter produces no coordinate under
any circumstances, and accepting a position would create an authority for a fact the format does
not carry.

NO CHECKSUM, SO THE GATE IS STRUCTURAL
--------------------------------------
Neither §4.5.2 nor §4.6 nor any §5.2 item defines a CRC, checksum or parity field at any level. So
the block must satisfy LEN, the records must tile it exactly, every FSPEC bit must name a defined
and non-spare FRN, **no `FX` may lead to an extension the document does not define** — three of the
nine items have one, which is this category's sharpest finding — every `REP` must be non-zero, and
the items Table 2 makes mandatory for the record's own report type must be present.
`attributes.integrity_basis` records on every object that this is what passed.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from synapse_cdm import ids, lossless, symbology, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import cat023_codec as codec
from synapse_cdm.enums import Affiliation, EntityType, EventType, Severity
from synapse_cdm.models import CDMBase, Entity, Event, SourceId

#: This adapter's own system name, for `SourceRef.system`.
SYSTEM = "ASTERIX_CAT023"

#: The source id system for a ground station's SAC/SIC pair.
#:
#: THE SAME STRING `asterix_cat034.py` USES, and that is the whole point: a SAC/SIC is allocated
#: across the whole ASTERIX family from one list — §5.2.2's NOTE points at the same published list
#: Part 2b's does — so one station seen through Part 16 and through Part 2b is ONE entity without
#: the two adapters coordinating. Filing it under a category name would say that station 0x29/0x29
#: seen through Part 16 is a different station from the same pair seen through any other part,
#: which is false.
#:
#: Here the derivation additionally rests on a CLAUSE rather than on an inference. §4.4.1 is a
#: normative section of its own: "By convention a dedicated and unambiguous SAC/SIC code shall be
#: assigned to every Ground Station." Part 2b has only §5.2.2's definition and a NOTE.
STATION_SYSTEM = "ASTERIX_SAC_SIC"

#: The source id system for a SERVICE, which is the pair (SAC/SIC, Service Identification).
#:
#: NOT the SID alone, and §5.2.3's NOTE 1 is why: "the service identification is allocated by the
#: system", so four bits identify a service WITHIN a ground station and carry no meaning across
#: stations — exactly as an SDPS track number is scoped to its SDPS. And NOT this adapter's own
#: category name, for the reason the station's is not: another category could legitimately name the
#: same service, and §5.2.3's NOTE 2 says one does — "The service identification is also available
#: in item I021/015."
SERVICE_SYSTEM = "ASTERIX_CNS_SERVICE"

#: One octet, and this adapter speaks exactly one category.
#:
#: NO SIBLING LIST HERE, AND THAT IS DELIBERATE — the same ruling `asterix_cat062.py` records. A
#: comment that enumerates siblings acquires a defect every time a sibling lands, which is what
#: happened to `asterix_cat048.py`'s. The PROPERTY is what matters: a data block of any other
#: ASTERIX category decoded against the category 023 UAP yields a plausible wrong ground station
#: status rather than an error, and Part 2b is the dangerous one — its UAP has the same fourteen
#: FRNs and the same two-octet FSPEC ceiling with a different item at almost every position.
CATEGORY = 23

#: CAT (1) + LEN (2). LEN counts itself and the CAT octet, per §4.5.2.
BLOCK_HEADER_OCTETS = 3


class Cat023ParseError(ValueError):
    """A block this adapter refuses. Every message quotes the offending octets."""


def _refuse(message: str, data: bytes, offset: int, span: int = 8) -> Cat023ParseError:
    window = data[max(0, offset - 2):offset + span]
    return Cat023ParseError(
        f"{message} (at octet {offset} of {len(data)}; octets here: {window.hex()})"
    )


# ===================================================================== the vocabularies

#: §5.2.1 NOTE 3, verbatim, with §4.5.1's own subsection numbers — because those subsections are
#: where the reporting obligations live and the NOTE points at them.
REPORT_TYPE_TEXT: dict[int, str] = {
    1: "Ground Station Status report",
    2: "Service Status report",
    3: "Service Statistics report",
}

#: Which report types are about a SERVICE rather than about the station. Read off Table 2 rather
#: than kept as a second list: `I023/015` is `X` for type 001 and `M` for 002 and 003.
SERVICE_REPORT_TYPES = frozenset({2, 3})

#: The nine items, in the order §5.1's Table 1 lists them. Named once so Table 2's three columns
#: below cannot each acquire a different idea of which items exist.
TABLE_2_ITEMS = ("I023/000", "I023/010", "I023/015", "I023/070", "I023/100", "I023/101",
                 "I023/110", "I023/120", "I023/200")

#: §5.2.1 NOTE 4 and Table 2, transcribed column by column. `M` mandatory, `O` optional, `X` never
#: present — and every other item's Encoding Rule reads "See Table 2", so THIS is the encoding rule
#: for eight of the nine items rather than a summary of them.
#:
#: A missing `M` is a refusal and a present `X` is parked; the asymmetry is real and
#: `_check_table_2` is where it is argued. **Note what the table makes impossible**: `I023/100`,
#: `I023/101`+`I023/110` and `I023/120` are each `M` for exactly one type and `X` elsewhere, so a
#: conformant record carries the station's status OR one service's configuration and status OR one
#: service's statistics, never two of the three.
TABLE_2: dict[int, dict[str, str]] = {
    1: dict(zip(TABLE_2_ITEMS, ("M", "M", "X", "M", "M", "X", "X", "X", "O"))),
    2: dict(zip(TABLE_2_ITEMS, ("M", "M", "M", "M", "X", "M", "M", "X", "O"))),
    3: dict(zip(TABLE_2_ITEMS, ("M", "M", "M", "M", "X", "X", "X", "M", "X"))),
}

#: §5.2.4's Encoding Rule carries its own exception to Table 2 and is the only item that does:
#: "This data item shall be present in every ASTERIX record, EXCEPT in case of failure of all
#: sources of time-stamping." So an absent time of day is a STATED absence on every report type,
#: and it lands in `attributes.unavailable_fields` rather than refusing. This is `I034/030`'s
#: exception in almost the same words and the second ASTERIX category here where an item-level rule
#: overrides the presence matrix.
TIME_ITEM = "I023/070"

#: `M` in every column of Table 2, so they are mandatory whatever the report type says — which
#: matters because a record whose type this edition does not define has no Table 2 column at all
#: and these two are still required of it.
ALWAYS_MANDATORY = ("I023/010", "I023/000")

#: §5.2.3's Type of Service, nine defined values. Note that §1.1's scope sentence names FIVE
#: service kinds — "ADS-B, TIS-B, FIS-B, GRAS, and MLT" — and this table has nine values because
#: four of the five are qualified by a data link. The two agree and count differently, which is
#: worth stating because a reader checking one against the other sees five against nine.
SERVICE_TYPE_TEXT: dict[int, str] = {
    1: "ADS-B VDL4", 2: "ADS-B Ext Squitter", 3: "ADS-B UAT", 4: "TIS-B VDL4",
    5: "TIS-B Ext Squitter", 6: "TIS-B UAT", 7: "FIS-B VDL4", 8: "GRAS VDL4", 9: "MLT",
}

#: §5.2.7's Status of the Service, six values in three bits. There is no "other" value and 6 and 7
#: are undefined.
SERVICE_STATUS_TEXT: dict[int, str] = {
    0: "Unknown", 1: "Failed", 2: "Disabled", 3: "Degraded", 4: "Normal", 5: "Initialisation",
}

#: The severity each service status takes, and every one of the six is a decision.
#:
#: `Failed` is CRITICAL: the service a consumer depends on is not running. `Degraded` is WARNING.
#: `Disabled` is WARNING TOO, and that is the one worth arguing: a disabled service is a service a
#: consumer is not receiving, and the record does not say whether that was intended — so INFO would
#: claim it was routine and CRITICAL would claim it was a failure, and neither is supported.
#: `Normal` and `Initialisation` are INFO. `Unknown` is ADVISORY, which is the CDM's middle value
#: and the only one that leaves the record visible to a consumer filtering on severity while
#: claiming nothing about what it means — the `asterix_cat034.py` treatment of an undefined message
#: type, reached for a value the document DOES define as an unknown.
SERVICE_STATUS_SEVERITY: dict[int, Severity] = {
    0: Severity.ADVISORY, 1: Severity.CRITICAL, 2: Severity.WARNING, 3: Severity.WARNING,
    4: Severity.INFO, 5: Severity.INFO,
}

#: §5.2.6's Service Class, bits 8/6 of octet 2. `0` is a stated non-statement and 2 to 7 are
#: "reserved for future use".
SERVICE_CLASS_TEXT: dict[int, str] = {0: "No information", 1: "NRA class"}

#: §5.2.8's counter TYPE, eighteen defined values with the document's own wording.
COUNTER_TYPE_TEXT: dict[int, str] = {
    0: "Number of unknown messages received",
    1: "Number of ‘too old’ messages received",
    2: "Number of failed message conversions",
    3: "Total Number of messages received",
    4: "Total number of messages transmitted",
    20: "Number of TIS-B management messages received",
    21: "Number of ‘Basic’ messages received",
    22: "Number of ‘High Dynamic’ messages received",
    23: "Number of ‘Full Position’ messages received",
    24: "Number of ‘Basic Ground‘ messages received",
    25: "Number of ‘TCP’ messages received",
    26: "Number of ‘UTC time‘ messages received",
    27: "Number of “Data’ messages received",
    28: "Number of ‘High Resolution’ messages received",
    29: "Number of ‘Aircraft Target Airborne’ messages received.",
    30: "Number of ‘Aircraft Target ‘Ground’ messages received.",
    31: "Number of ‘Ground Vehicle Target’ messages received.",
    32: "Number of ‘2 slots TCP messages received.",
}

#: The band §5.2.8's NOTE reserves, and it is a DOCUMENTED RESERVATION rather than an unknown: "the
#: range from 0 to 19 is intended to cover generic messages which may be applicable to many types
#: of service". So a 7 is a generic counter this edition has not allocated and a 40 is outside the
#: table entirely, and the reason recorded with each says which band it is in.
COUNTER_GENERIC_BAND = range(0, 20)

#: §5.2.8's REF bit, per counter rather than per item — the bit is inside each six-octet block, so
#: one record may legitimately carry counters with two different references.
COUNTER_REFERENCE_TEXT: dict[int, str] = {0: "From midnight", 1: "From the last report"}

#: §5.2.9's NOTE. A range at the field's maximum is a FLOOR and not a measurement — the AIS
#: 102.2 kt discipline, reached again.
AT_OR_ABOVE_MAXIMUM_NOTE = "Maximum value indicates “maximum value or above”"


# =========================================================================== bit helpers


def _bits(value: int, high: int, low: int) -> int:
    return codec.bits(value, high, low)


# ==================================================================== the item decoders
#
# Every decoder takes exactly the octets its length rule measured and returns a dict of RAW fields
# plus every spare bit as sent. Every encoder is its inverse and writes those spare bits back
# unchanged — §4.3 "Unused Bits in Data Items" is what makes that a rule rather than a preference,
# and `build_block` proves the pair round-trips on every fixture.


def _decode_000(block: bytes) -> dict:
    return {"report_type": block[0]}


def _encode_000(item: dict) -> bytes:
    return bytes([item["report_type"]])


def _decode_010(block: bytes) -> dict:
    return {"sac": block[0], "sic": block[1]}


def _encode_010(item: dict) -> bytes:
    return bytes([item["sac"], item["sic"]])


def _decode_015(block: bytes) -> dict:
    """§5.2.3, and the two nibbles are named explicitly for a reason.

    The item is called "Service Type and Identification" and the octet is `SID` in bits 8/5 and
    `STYP` in bits 4/1 — **the name is in the other order from the bits.** A transposition yields a
    plausible wrong service rather than an error, because `SID` 2 / `STYP` 9 and `SID` 9 / `STYP` 2
    are both legal, so the two are parked under explicit names and never as one integer.
    """
    return {"sid": _bits(block[0], 8, 5), "styp": _bits(block[0], 4, 1)}


def _encode_015(item: dict) -> bytes:
    return bytes([(item["sid"] << 4) | item["styp"]])


def _decode_070(block: bytes) -> dict:
    return {"time_of_day_raw": codec.read_unsigned(block, 0, 3)}


def _encode_070(item: dict) -> bytes:
    return codec.write_unsigned(item["time_of_day_raw"], 3)


def _decode_200(block: bytes) -> dict:
    return {"range_raw": block[0]}


def _encode_200(item: dict) -> bytes:
    return bytes([item["range_raw"]])


def _decode_100(block: bytes) -> dict:
    first = block[0]
    parsed: dict[str, Any] = {
        "nogo": _bits(first, 8, 8), "odp": _bits(first, 7, 7), "oxt": _bits(first, 6, 6),
        "msc": _bits(first, 5, 5), "tsv": _bits(first, 4, 4), "spo": _bits(first, 3, 3),
        "rn": _bits(first, 2, 2), "fx": _bits(first, 1, 1),
    }
    if len(block) > 1:
        parsed["extension"] = {"gssp_raw": _bits(block[1], 8, 2), "fx": _bits(block[1], 1, 1)}
    return parsed


def _encode_100(item: dict) -> bytes:
    out = bytearray([(item["nogo"] << 7) | (item["odp"] << 6) | (item["oxt"] << 5)
                     | (item["msc"] << 4) | (item["tsv"] << 3) | (item["spo"] << 2)
                     | (item["rn"] << 1) | item["fx"]])
    extension = item.get("extension")
    if extension is not None:
        out.append((extension["gssp_raw"] << 1) | extension["fx"])
    return bytes(out)


def _decode_101(block: bytes) -> dict:
    """§5.2.6, and the FIRST PART IS TWO OCTETS with the FX in the second.

    The only `2+` item in any ASTERIX category this repository pins, so its length rule cannot be
    shared with `I023/100`'s or `I023/110`'s — and the UAP's legend explains only `1+`, which is
    ambiguity 4.
    """
    parsed: dict[str, Any] = {
        "rp_raw": block[0],
        "sc": _bits(block[1], 8, 6), "spare_bits_5_2": _bits(block[1], 5, 2),
        "fx": _bits(block[1], 1, 1),
    }
    if len(block) > 2:
        parsed["extension"] = {"ssrp_raw": _bits(block[2], 8, 2), "fx": _bits(block[2], 1, 1)}
    return parsed


def _encode_101(item: dict) -> bytes:
    out = bytearray([item["rp_raw"],
                     (item["sc"] << 5) | (item["spare_bits_5_2"] << 1) | item["fx"]])
    extension = item.get("extension")
    if extension is not None:
        out.append((extension["ssrp_raw"] << 1) | extension["fx"])
    return bytes(out)


def _decode_110(block: bytes) -> dict:
    octet = block[0]
    return {"spare_bits_8_5": _bits(octet, 8, 5), "stat": _bits(octet, 4, 2),
            "fx": _bits(octet, 1, 1)}


def _encode_110(item: dict) -> bytes:
    return bytes([(item["spare_bits_8_5"] << 4) | (item["stat"] << 1) | item["fx"]])


def _decode_120(block: bytes) -> dict:
    """§5.2.8: a one-octet REP then REP six-octet blocks, each TYPE + REF + spares + a 32-bit count.

    An ORDERED LIST with duplicates preserved, the `I048/030` and `I034/070` rule reached a third
    time: order is data, the document does not say the TYPE values are unique, and egress is
    byte-exact only if the counters go back out as they came in.
    """
    rep = block[0]
    counters = []
    for index in range(rep):
        at = 1 + 6 * index
        counters.append({
            "type": block[at],
            "ref": _bits(block[at + 1], 8, 8),
            "spare_bits_39_33": _bits(block[at + 1], 7, 1),
            "counter": codec.read_unsigned(block, at + 2, 4),
        })
    return {"rep": rep, "counters": counters}


def _encode_120(item: dict) -> bytes:
    out = bytearray([item["rep"]])
    for counter in item["counters"]:
        out.append(counter["type"])
        out.append((counter["ref"] << 7) | counter["spare_bits_39_33"])
        out += codec.write_unsigned(counter["counter"], 4)
    return bytes(out)


def _decode_explicit(block: bytes) -> dict:
    """RE and SP: a one-octet length INCLUDING itself, then opaque contents."""
    return {"length": block[0], "contents": block[1:].hex()}


def _encode_explicit(item: dict) -> bytes:
    return bytes([item["length"]]) + bytes.fromhex(item["contents"])


# ========================================================================= the UAP
#
# §5.3.1 Table 3. The fourth column's legend explains only `1+`; `2+` and `1+1+` are unexplained
# (ambiguity 4), and `1+` is given to both an FX-chained item and a REP-prefixed repetitive one. So
# every length rule below comes from §5.2 and the column is never read.


def _len_fixed(width: int):
    def rule(data: bytes, offset: int) -> int:
        return width
    return rule


def _len_extensible(item: str, first_part: int, locus: str, names: tuple[str, ...]):
    """The FX chain of I023/100, I023/101 and I023/110, and the refusal all three share.

    **THE SHARPEST FINDING IN THE DOCUMENT.** Three of the nine items are extensible and NONE of
    them defines the extension its own FX announces:

    * `I023/100`'s First Extension says "= 1 Extension into Second Extension" and §5.2.5 ends after
      the First Extension.
    * `I023/101`'s First Extension says the same and §5.2.6 ends after the First Extension.
    * `I023/110`'s single octet says "= 1 Extension" and there is no First Extension for it in ANY
      edition in hand, including 0.14.

    So a set FX with no defined continuation is a refusal — the `asterix_cat034.py` `_len_compound`
    disposition and the `asterix_cat048.py` I048/120 disposition, reached again: the bit announces
    something the document does not define, so there is nothing to decode, it cannot be skipped, and
    guessing a length would desynchronise every following item in the record.

    **This is not the general ASTERIX FX semantics being refused, and the difference decides it.**
    In the general case an FX chain continues with more octets OF THE SAME SHAPE, and CAT062's
    `I062/510` is exactly that — its "Structure of next Extents" is defined and identical, so its
    chain is genuinely unbounded and a set FX on the last extent read is legal. Here the document
    does the opposite: it NAMES a specific "Second Extension" twice and defines neither. The refusal
    rests on the document's own words.
    """
    def rule(data: bytes, offset: int) -> int:
        total = first_part
        if offset + total > len(data):
            raise _refuse(f"{item}'s {names[0]} is past the end of the block", data, offset)
        if not data[offset + total - 1] & codec.FX:
            return total
        for index, name in enumerate(names[1:], start=1):
            if offset + total >= len(data):
                raise _refuse(f"{item}'s {name} is past the end of the block", data, offset)
            octet = data[offset + total]
            total += 1
            if not octet & codec.FX:
                return total
            # HOISTED, and the gate is why: an f-string replacement field may not reuse the
            # string's own quote character or contain a backslash before Python 3.12 (PEP 701),
            # and `requires-python` here is >=3.11. `tests/test_cdm_version_floor.py` caught it.
            wording = ('"Extension into Second Extension"' if len(names) > 1
                       else '"Extension"')
            raise _refuse(
                f"{item}'s {name} sets its FX bit. {locus} documents it as {wording} "
                f"and defines no such extension — the section ends after the {name}. There is "
                "nothing to decode, so it cannot be skipped, and guessing a length would "
                "desynchronise every following item in the record. Three of this category's nine "
                "items have an FX that names a continuation the document never defines, and this "
                "is one of them", data, offset + total - 1)
        # The first part's FX led somewhere and there is no extension defined at all — I023/110.
        raise _refuse(
            f"{item}'s {names[0]} sets its FX bit. {locus} documents it as \"Extension\" and "
            "defines NO extension for this item in any edition in hand, including Edition 0.14. "
            "There is nothing to decode, so it cannot be skipped, and guessing a length would "
            "desynchronise every following item in the record", data, offset)
    return rule


def _len_120(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("I023/120's REP octet is past the end of the block", data, offset)
    rep = data[offset]
    if rep == 0:
        raise _refuse(
            "I023/120 states REP = 0. §5.2.8's Format is 'a one-octet Field Repetition Indicator "
            "(REP) followed by AT LEAST ONE block of 6 octets', so a zero-length repetition is "
            "excluded by the item's own words — and an item whose presence bit is set and whose "
            "content is empty is not a counter set, it is a record whose FSPEC and body disagree",
            data, offset)
    return 1 + 6 * rep


def _len_explicit(data: bytes, offset: int) -> int:
    """The RE and SP length octet — and this document defines neither field.

    **The convention is inherited and the inheritance is named**, because it is the one mechanic in
    this adapter the pinned text does not supply. Table 3 gives both fields the notation `1+1+` and
    the UAP's legend explains only `1+`; there is no §5.2 entry for either; no appendix exists for
    Part 16; and no edition in hand mentions either field outside the UAP. ASTERIX Part 1, which
    does define them, **is not pinned in this repository** — and this document cites it as
    SUR.ET1.ST05.2000-STD-01-01 Edition 1.29 of FEBRUARY 2002, the pre-migration number at a
    nineteen-year-old edition, in a document dated September 2021. So even acquiring Part 1 at its
    current edition would not obviously be acquiring the document this specification cites. What is
    used instead is the shipped siblings' convention: a one-octet length counting itself. The
    contents are never decoded either way, so the exposure is a length and not a meaning.
    """
    if offset >= len(data):
        raise _refuse("an explicit-length item's length octet is past the end of the block",
                      data, offset)
    stated = data[offset]
    if stated < 1:
        raise _refuse(
            "an explicit-length item states a length of 0, but the length octet counts itself so "
            "the minimum is 1", data, offset)
    return stated


#: (FRN, item, §5.2 name, Table 3 name, length rule, decoder, encoder).
#:
#: **THE ORDER IS NOT ITEM-NUMBER ORDER AND THAT IS THE TRAP.** `I023/200` sits between `I023/101`
#: and `I023/110` — three items out of numeric sequence — and Edition 0.13's change record says why:
#: "Sequence of items in UAP updated". A parser walking items in item-number order would read the
#: Operational Range octet as the first octet of Service Status and lose its place **with no length
#: error anywhere in the record.**
UAP: tuple[tuple[int, str, str, str, Any, Any, Any], ...] = (
    (1, "I023/010", "Data Source Identifier", "Data Source Identifier",
     _len_fixed(2), _decode_010, _encode_010),
    (2, "I023/000", "Report Type", "Report Type",
     _len_fixed(1), _decode_000, _encode_000),
    (3, "I023/015", "Service Type and Identification", "Service Type and Identification",
     _len_fixed(1), _decode_015, _encode_015),
    (4, "I023/070", "Time of Day", "Time of Day",
     _len_fixed(3), _decode_070, _encode_070),
    (5, "I023/100", "Ground Station Status", "Ground Station Status",
     _len_extensible("I023/100", 1, "§5.2.5", ("first part", "First Extension")),
     _decode_100, _encode_100),
    (6, "I023/101", "Service Configuration", "Service Configuration",
     _len_extensible("I023/101", 2, "§5.2.6", ("first part", "First Extension")),
     _decode_101, _encode_101),
    (7, "I023/200", "Operational Range", "Operational Range",
     _len_fixed(1), _decode_200, _encode_200),
    (8, "I023/110", "Service Status", "Service Status",
     _len_extensible("I023/110", 1, "§5.2.7", ("first part",)),
     _decode_110, _encode_110),
    (9, "I023/120", "Service Statistics", "Service Statistics",
     _len_120, _decode_120, _encode_120),
    (13, "RE", "Reserved Expansion Field", "RE-Data Item",
     _len_explicit, _decode_explicit, _encode_explicit),
    (14, "SP", "Special Purpose Field", "SP-Data Item",
     _len_explicit, _decode_explicit, _encode_explicit),
)

UAP_BY_FRN = {entry[0]: entry for entry in UAP}
FRN_BY_ITEM = {entry[1]: entry[0] for entry in UAP}
ENCODERS = {entry[1]: entry[6] for entry in UAP}


# ====================================================================== parsing a block


def _parse_record(data: bytes, offset: int, *, index: int) -> tuple[dict, int]:
    """One record: the FSPEC, then the present items in FRN order."""
    fspec_start = offset
    try:
        frns, fspec, at = codec.read_fspec(data, offset)
    except codec.CodecError as exc:
        raise _refuse(f"record {index}: {exc}", data, fspec_start) from exc

    items: dict[str, Any] = {}
    item_octets: dict[str, str] = {}
    for frn in frns:
        if frn in codec.SPARE_FRNS:
            raise _refuse(
                f"record {index}: FSPEC sets FRN {frn}, which §5.3.1 Table 3 marks '- spare -'. "
                f"{codec.SPARE_FRN_REASON}. A spare slot names no item, so there is nothing to "
                "decode, it cannot be skipped, and guessing a length would desynchronise every "
                "following item in the record", data, fspec_start)
        entry = UAP_BY_FRN.get(frn)
        if entry is None:
            raise _refuse(
                f"record {index}: FSPEC sets FRN {frn}, which the category 023 UAP does not "
                f"define — Table 3 lists {codec.MAX_FRN} slots. There is no item to decode, so it "
                "cannot be skipped, and guessing a length would desynchronise every following "
                "item in the record", data, fspec_start)
        _frn, item, _name, _uap_name, rule, decode, _encode = entry
        length = rule(data, at)
        block = data[at:at + length]
        if len(block) != length:
            raise _refuse(f"record {index}: item {item} needs {length} octet(s) and the block "
                          f"has {len(block)} left", data, at)
        item_octets[item] = block.hex()
        items[item] = decode(block)
        at += length

    missing = [item for item in ALWAYS_MANDATORY if item not in items]
    if missing:
        raise _refuse(
            f"record {index} is missing {', '.join(missing)}. Both are M in every column of "
            "Table 2. ASTERIX carries no checksum at any level, so the mandatory items are part "
            "of what replaces one", data, fspec_start)

    _check_table_2(items, data, fspec_start, index)
    return {"index": index, "fspec": fspec.hex(), "items": items,
            "item_octets": item_octets}, at


def _check_table_2(items: dict, data: bytes, offset: int, index: int) -> None:
    """A missing `M` refuses, a present `X` is parked, and the asymmetry is the ruling.

    `asterix_cat034.py`'s settlement 8, reached on a smaller table and unchanged. They are different
    faults. **A missing mandatory item is a record that cannot be read as what it claims to be** —
    a Service Status report with no `I023/110` states no status, a Service Statistics report with no
    `I023/120` states no statistics — and there is no checksum behind it to have caught the
    truncation. **An item present where Table 2 says `X` is a record that says MORE than its type
    admits**, which is a conformance fault in the encoder and not a loss: every octet of it is
    decodable, its length is stated, and refusing would discard data the FSPEC correctly announced.
    §4.3's discipline for a bit that means nothing, applied one level up to an item that means
    nothing HERE. It is parked and named in `attributes.table_2_disposition`.

    `I023/070` is excluded from the mandatory half by its own Encoding Rule, which is the only
    item-level text in the category that overrides the table — see TIME_ITEM.

    A report type outside 001..003 has no column, so neither half runs; that record's only
    requirement is `ALWAYS_MANDATORY`, which has already been checked.
    """
    report_type = items["I023/000"]["report_type"]
    column = TABLE_2.get(report_type)
    if column is None:
        return
    missing = [item for item, rule in column.items()
               if rule == "M" and item != TIME_ITEM and item not in items]
    if missing:
        raise _refuse(
            f"record {index}: I023/000 is {report_type:03d} ({REPORT_TYPE_TEXT[report_type]}) and "
            f"Table 2 makes {', '.join(missing)} mandatory for that report type. Every item's own "
            "Encoding Rule in this category reads 'See Table 2', so the table IS the encoding rule "
            "and a missing M is a record that cannot be read as what it claims to be. I023/070 is "
            "the one exception and is not in this list — §5.2.4 permits its absence 'in case of "
            "failure of all sources of time-stamping'", data, offset)


def parse_block(data: bytes) -> dict:
    """One data block into the parsed form. Every refusal quotes the offending octets."""
    if len(data) < BLOCK_HEADER_OCTETS:
        raise Cat023ParseError(
            f"a CAT023 data block is at least {BLOCK_HEADER_OCTETS} octets (CAT + LEN); "
            f"got {len(data)}: {data.hex()}"
        )
    category = data[0]
    if category != CATEGORY:
        raise _refuse(
            f"CAT octet is {category} (0x{category:02X}), not {CATEGORY}. This adapter speaks one "
            "category, and a data block of any other ASTERIX category decoded against the "
            "category 023 UAP yields a plausible wrong ground station status rather than an error. "
            "Part 2b is the dangerous one: its UAP has the same fourteen FRNs and the same "
            "two-octet FSPEC ceiling with a different item at almost every position", data, 0)
    stated = codec.read_unsigned(data, 1, 2)
    if stated != len(data):
        raise _refuse(
            f"LEN says {stated} octets and the buffer holds {len(data)}. §4.5.2 makes LEN 'a "
            "two-octet field indicating the total length in octets of the Data Block, including "
            "the CAT and LEN fields', so reading to the end of the buffer instead would translate "
            "whatever followed the block as if it were part of it", data, 1)

    records: list[dict] = []
    at = BLOCK_HEADER_OCTETS
    while at < len(data):
        record, at = _parse_record(data, at, index=len(records))
        records.append(record)
    if not records:
        raise Cat023ParseError(
            f"the block states LEN = {stated} and holds no records. An empty block is not a "
            "payload that legitimately carries nothing: §4.5.2's layout has at least one FSPEC "
            f"after LEN. Octets: {data.hex()}"
        )
    for record in records:
        record["record_count"] = len(records)
    return {
        "block": {"category": category, "length": stated, "record_count": len(records)},
        "records": records,
    }


def build_block(records: list[dict]) -> bytes:
    """The parsed form back to octets. LEN is recomputed; the FSPEC is re-emitted as parked.

    Every item is re-encoded from its parsed fields and then **checked against the octets that were
    parked on ingest**. That check is the point: it makes byte-exactness a proven property of the
    decoder/encoder pair rather than a trivial consequence of copying the input back out, and it is
    what would catch a spare bit the decoder read and the encoder forgot.
    """
    body = bytearray()
    for record in records:
        fspec = bytes.fromhex(record["fspec"])
        frns, _octets, _end = codec.read_fspec(fspec, 0)
        body += fspec
        for frn in frns:
            item = UAP_BY_FRN[frn][1]
            parsed = record["items"][item]
            emitted = ENCODERS[item](parsed)
            parked = record.get("item_octets", {}).get(item)
            if parked is not None and emitted.hex() != parked:
                raise Cat023ParseError(
                    f"re-encoding {item} produced {emitted.hex()} and the octets parked on ingest "
                    f"were {parked}. The round trip is only byte-exact if every bit the decoder "
                    "read is a bit the encoder writes back, spare bits included — §4.3 addresses "
                    "unused bits and does not require them to be zero, so a conforming encoder may "
                    "set them to anything"
                )
            body += emitted
    return bytes([CATEGORY]) + codec.write_unsigned(len(body) + BLOCK_HEADER_OCTETS, 2) + body


# ============================================================================ the time


def _resolve_time_of_day(seconds: float, received_at: _dt.datetime) -> tuple[_dt.datetime, str]:
    """A time of day plus the receipt date, resolved to the nearest candidate instant.

    §5.2.4 gives "Absolute time stamping expressed as UTC time" and its NOTE says "The time of day
    value is reset to zero each day at midnight", so the candidates are that time of day on the
    receipt date, the day before and the day after; the nearest to the receipt instant wins. Same
    rule as `asterix_cat021.py`, `asterix_cat048.py`, `asterix_cat034.py` and `asterix_cat062.py`,
    reached a fifth time.
    """
    day = received_at.date()
    candidates = []
    for offset in (-1, 0, 1):
        base = _dt.datetime.combine(day + _dt.timedelta(days=offset), _dt.time(),
                                    tzinfo=_dt.timezone.utc)
        candidates.append((offset, base + _dt.timedelta(seconds=seconds)))
    offset, instant = min(candidates, key=lambda pair: abs(pair[1] - received_at))
    if offset == 0:
        note = "the receipt date, which was the nearest of the three candidate days"
    else:
        direction = "previous" if offset < 0 else "next"
        note = (f"the {direction} day relative to the receipt date — a midnight ROLLOVER was "
                "applied, because that candidate was nearer the receipt instant")
    return instant, note


def _observed_at(items: dict, received_at: _dt.datetime) -> tuple[_dt.datetime, dict]:
    """`Event.observed_at` and the basis. Two steps, and the second is not an error path."""
    tod = items.get(TIME_ITEM)
    if tod is None:
        return received_at, {
            "item": None,
            "reason": ("the record carries no I023/070. §5.2.4's Encoding Rule permits exactly "
                       "this — 'This data item shall be present in every ASTERIX record, except in "
                       "case of failure of all sources of time-stamping' — so this is a STATED "
                       "absence and not a defect, and it is stated even though Table 2 marks the "
                       "item M for all three report types. The second ASTERIX category in this "
                       "repository where an item-level rule overrides the presence matrix"),
            "date_from": "the injected clock",
            "time_of_day_from": "the injected clock; the record stated no time of day",
        }
    raw = tod["time_of_day_raw"]
    seconds = codec.from_raw("tod", raw)
    if seconds >= codec.SECONDS_PER_DAY:
        raise Cat023ParseError(
            f"I023/070 states {raw} units of 1/128 s = {seconds:.7f} s since midnight, and a day "
            f"is {codec.SECONDS_PER_DAY} s. Twenty-four bits at 1/128 s reach 131071.9921875 s, so "
            "the field can express counts no time of day can mean. Refusing rather than taking it "
            "modulo a day — a modulo would move this record by hours and leave every other check "
            "passing. "
            "THE BASIS IS NOT A STATED RANGE, and the difference from Part 4 is recorded rather "
            "than smoothed over: CAT048 §5.2.17 prints a normative structure block, 'Acceptable "
            "Range of values: 0<= Time-of-Day<=24 hrs', and ACCEPTS 86400 s itself on that "
            "inclusive inequality. CAT023 §5.2.4 prints no range at all, so the bound here comes "
            "from the Definition ('Absolute time stamping expressed as UTC time') and the NOTE "
            "('The time of day value is reset to zero each day at midnight'), which together make "
            "86400 s unreachable. Same width, same LSB, three categories sharing this disposition "
            "and one differing, and a boundary that therefore differs by one value. "
            "FORMAT_COVERAGE.md ambiguity 8"
        )
    instant, note = _resolve_time_of_day(seconds, received_at)
    return instant, {
        "item": "I023/070",
        "time_of_day_s": seconds,
        "time_of_day_raw": raw,
        "lsb_seconds": codec.bounds("tod")[2],
        "date_from": note,
        "definition": "Absolute time stamping expressed as UTC time",
    }


# ======================================================================== the adapter


class AsterixCat023Adapter(Adapter):
    """CAT023 data blocks in, CDM out; CAT023-origin Entities back out to a data block."""

    name = "cat023"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: EMPTY, and that is a claim rather than an oversight — the claim all four ASTERIX siblings
    #: make. A declared transform is an EXEMPTION from the never-drop check, and this adapter needs
    #: none: every wire value is parked verbatim as well as converted — the octets of every item at
    #: `attributes.cat023_items`, the raw integers beside every decoded figure, and the whole
    #: decoded item tree at `attributes.source_extras`. So `lossless.unrepresented()` runs at full
    #: strength over every fixture with nothing excused.
    #:
    #: This is the easiest case in the family: **not one scaled value in this category becomes a
    #: canonical numeric field.** Every derived figure — the seconds behind `I023/070`, `GSSP`,
    #: `SSRP`, `RP` and `I023/200` — is a one-way view sitting beside its own raw octet.
    #:
    #: And structurally it could not be used even if it were wanted: TRANSFORMS matches dotted
    #: paths, and this adapter's parsed form has an ARRAY of records at its root.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed RECORD this adapter re-emits under a name of its own.
    CONSUMED = ("index", "fspec", "item_octets", "record_count")

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One data block -> [station Entity, (service Entity,) Event] per record, in block order.

        Several records in one block are several SERVICE REPORTS, not a station's history. Table 2
        makes the three report types mutually exclusive — `I023/100`, `I023/101`+`I023/110` and
        `I023/120` are each `M` for exactly one type and `X` elsewhere — so a station's full picture
        needs three records, and assembling it is the accumulation this adapter refuses. The CDM
        makes it expressible for a consumer rather than performing it here.
        """
        parsed = self._as_parsed(raw)
        records = parsed.get("records")
        if not isinstance(records, list) or not records:
            raise Cat023ParseError(
                "CAT023 payload holds no records — refusing to translate; top-level keys: "
                f"{sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
            )
        block = parsed.get("block") or {}
        received_at = self.now()
        source = self.source_ref()

        objects: list[CDMBase] = []
        for record in records:
            objects.extend(self._translate(record, block, received_at, source))
        return objects

    def _as_parsed(self, raw: bytes | dict) -> dict:
        if isinstance(raw, (bytes, bytearray)):
            return parse_block(bytes(raw))
        if isinstance(raw, dict):
            return raw
        raise Cat023ParseError(
            f"a CAT023 payload is a data block (bytes) or its parsed twin (dict), "
            f"got {type(raw).__name__}"
        )

    def _translate(self, record: dict, block: dict, received_at: _dt.datetime,
                   source: Any) -> list[CDMBase]:
        items = record["items"]
        unavailable: list[str] = []
        unresolved: dict[str, Any] = {}

        observed_at, time_basis = _observed_at(items, received_at)
        if time_basis["item"] is None:
            unavailable.append("I023/070 (the record states no time of day)")

        station = items["I023/010"]
        station_id = f"{station['sac']:02X}{station['sic']:02X}"
        station_source_id = SourceId(system=STATION_SYSTEM, external_id=station_id)
        station_entity_id = ids.derive(STATION_SYSTEM, station_id, kind="entity")

        report_type = items["I023/000"]["report_type"]
        service = items.get("I023/015")
        service_entity_id = None
        service_source_id = None
        service_basis: dict[str, Any] | None = None
        if service is not None:
            service_key = f"{station_id}|{service['sid']}"
            service_entity_id = ids.derive(SERVICE_SYSTEM, service_key, kind="entity")
            service_source_id = SourceId(system=SERVICE_SYSTEM, external_id=service_key)
            service_basis = self._service_basis(service, station_id, service_key, unresolved)

        severity, severity_basis = self._severity(items, report_type, unresolved)
        related = [station_entity_id]
        if service_entity_id is not None:
            related.append(service_entity_id)

        attributes = self._attributes(record, block, items, station_id, station_entity_id,
                                      service_basis, unavailable, unresolved)
        station_entity = Entity(
            source=source,
            source_ids=[station_source_id],
            entity_id=station_entity_id,
            # SENSOR. The one enum value in the CDM that names what a CNS/ATM ground station is,
            # and `asterix_cat034.py` established it for a radar head.
            entity_type=EntityType.SENSOR,
            # UNKNOWN, always, and here it is not even a decision: a service status report states
            # configuration and health and never allegiance.
            affiliation=Affiliation.UNKNOWN,
            symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                   synthetic=self._synthetic),
            # None on EVERY object. Nine items and not one coordinate — see the module docstring.
            position=None,
            # None, always. A ground station does not move and this category carries no bearing of
            # any kind, not even an antenna's — which CAT034 does have, in I034/020.
            kinematics=None,
            attributes=attributes,
            valid_from=observed_at,
            # None on every record. §4.5.1.1 and §4.5.1.2 give a reporting PERIOD, from which a
            # consumer could make a staleness horizon; deriving an expiry here would be this
            # adapter reasoning about reports it has not seen.
            valid_to=None,
            # None, always. Every quality statement in this category is a switch position, an
            # enumerated status or a counter; none is a 0..1 assessment of identity.
            confidence=None,
        )
        objects: list[CDMBase] = [station_entity]
        if service_entity_id is not None and service_source_id is not None:
            objects.append(Entity(
                source=source,
                source_ids=[service_source_id],
                entity_id=service_entity_id,
                entity_type=EntityType.SENSOR,
                affiliation=Affiliation.UNKNOWN,
                symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                       synthetic=self._synthetic),
                position=None,
                kinematics=None,
                attributes=self._service_attributes(record, station_id, station_entity_id,
                                                    service_basis or {}, items, unresolved),
                valid_from=observed_at,
                valid_to=None,
                confidence=None,
            ))
        objects.append(Event(
            source=source,
            source_ids=[station_source_id] + ([service_source_id] if service_source_id else []),
            event_id=ids.derive(
                STATION_SYSTEM,
                f"{station_id}|{times.render(observed_at)}|{record['index']}", kind="event"),
            # STATUS_CHANGE for all three defined types: a ground station or a service stating what
            # it is doing is a status change and not a detection. No type produces ALERT, and that
            # is a decision — see `_severity` for the two bits that raise severity instead.
            event_type=EventType.STATUS_CHANGE,
            severity=severity,
            related_entities=related,
            # None, ALWAYS, and permanently. The only quantity in the category that could become one
            # is I023/200's operational range, which is a radius with no centre.
            geometry=None,
            payload=self._payload(record, block, items, time_basis, severity_basis, report_type,
                                 service_basis, unresolved),
            observed_at=observed_at,
            received_at=received_at,
        ))
        return objects

    # ------------------------------------------------------------------ the service

    def _service_basis(self, service: dict, station_id: str, service_key: str,
                       unresolved: dict[str, Any]) -> dict:
        """Settlement 2's second object: what it is, and why the key is the pair."""
        text = SERVICE_TYPE_TEXT.get(service["styp"])
        if text is None:
            unresolved["I023/015 STYP"] = {
                "raw": service["styp"],
                "reason": ("§5.2.3 defines Type of Service values 1 to 9 and four bits give "
                           "sixteen. There is no 'unknown' or 'other' value in the table, so an "
                           "undefined STYP is a value this edition does not define rather than a "
                           "stated unknown"),
            }
        return {
            "sid": service["sid"],
            "styp": service["styp"],
            "styp_text": text,
            "external_id": service_key,
            "entity_id": ids.derive(SERVICE_SYSTEM, service_key, kind="entity"),
            "system": SERVICE_SYSTEM,
            "identity_basis": (
                f"uuid5 over ({SERVICE_SYSTEM}, {service_key!r}) — THE PAIR (SAC/SIC, Service "
                "Identification) AND NEVER THE SID ALONE. §5.2.3's NOTE 1 says 'the service "
                "identification is allocated by the system', so four bits identify a service "
                "WITHIN a ground station and carry no meaning across stations, exactly as an SDPS "
                "track number is scoped to its SDPS. Four bits give sixteen services per station, "
                "which is the whole space. The system name is not this adapter's own for the "
                "reason the station's is not: another category could legitimately name the same "
                "service, and NOTE 2 says one does"),
            "second_object_basis": (
                "A SERVICE IS A SECOND OBJECT, on report types 002 and 003 only. Three reasons. It "
                "is a thing that exists and has a state — §5.2.7's STAT has six values, which is a "
                "lifecycle and not an attribute of the station, and a station whose ADS-B service "
                "is failed and whose TIS-B service is normal has two states. Parking it inside the "
                "station's attributes would make two consecutive records about two different "
                "services produce two objects with the SAME entity_id and different attributes, "
                "which reads downstream as one object changing its mind rather than as two "
                "services. And §4.5.1.2 requires the independence: 'Each ground station may "
                "provide several services, and the status of each shall be reported independently "
                "in each service status report.' FORMAT_COVERAGE.md settlement 2"),
            "entity_type_basis": (
                "SENSOR, recorded as the LEAST-WRONG OF EIGHT rather than as a fit. A service is "
                "not a UNIT, a PLATFORM, a FACILITY, an EVACUEE_GROUP, an INTERFERENCE_SOURCE or "
                "an OVERLAY_OBJECT, and UNKNOWN would discard the one thing the record does say "
                "about it. SENSOR fits it no worse than it fits the station"),
            "cross_category_join_declined": (
                "§5.2.3's NOTE 2: 'The service identification is also available in item I021/015.' "
                "Correlating a CAT023 service status with the CAT021 target reports that service "
                "emits is the single most useful thing a consumer could do with this category, and "
                "it needs TWO PAYLOADS — which is the cross-payload state every adapter here "
                "refuses. The CAT021 row set predicted this relationship from the other side: its "
                "declines table says I021/015 and I021/016 exist 'precisely because not every "
                "service user receives CAT023'"),
        }

    def _service_attributes(self, record: dict, station_id: str, station_entity_id: Any,
                            service_basis: dict, items: dict,
                            unresolved: dict[str, Any]) -> dict:
        """The service Entity's own attributes. Deliberately narrower than the station's."""
        attributes: dict[str, Any] = {
            "object_is": "the SERVICE, not the ground station that provides it",
            "service": {k: v for k, v in service_basis.items() if k != "entity_id"},
            "provided_by": {
                "station_external_id": station_id,
                "station_entity_id": str(station_entity_id),
                "basis": (
                    "the station's own entity_id, recorded so a consumer can see the relationship "
                    "WITHOUT this adapter having joined anything: both ids are pure functions of "
                    "fields in the SAME RECORD, and the Event carries both in related_entities "
                    "with the station first. What is not done is resolving the station's id "
                    "against any other payload"),
            },
            "position_basis": (
                "None. NINE ITEMS AND NOT ONE COORDINATE in this category — I023/200 is an "
                "operational range in nautical miles with no centre, and §4.4.1 asserts that a "
                "SAC/SIC is dedicated and unambiguous per ground station without saying where any "
                "station is. Reading a position out of a CAT034 record to locate this station is "
                "cross-payload state, which is the refusal asterix_cat034.py's settlement 2 "
                "already made in the other direction"),
            "cat023_fspec": record["fspec"],
        }
        configuration = items.get("I023/101")
        if configuration is not None:
            attributes["service_configuration"] = self._configuration(configuration, unresolved)
        status = items.get("I023/110")
        if status is not None:
            attributes["service_status"] = self._status(status, unresolved)
        return attributes

    # ------------------------------------------------------------------ severity

    def _severity(self, items: dict, report_type: int,
                  unresolved: dict[str, Any]) -> tuple[Severity, dict]:
        """`Event.severity` from `I023/110`'s STAT and `I023/100`'s SPO, and from nothing else.

        `NOGO` is the operationally loudest bit in the category and is NOT one of them —
        `_ground_station_status` argues it at its site.
        """
        basis: dict[str, Any] = {
            "report_type": report_type,
            "report_type_text": REPORT_TYPE_TEXT.get(report_type),
            "default": (
                "INFO for all three defined report types. A ground station or a service stating "
                "what it is doing is routine; the type itself is not an alarm, and Event.event_type "
                "is STATUS_CHANGE for all three — no report type produces ALERT"),
            "raised_by": [],
        }
        severity = Severity.INFO
        if report_type not in REPORT_TYPE_TEXT:
            unresolved["I023/000 Report Type"] = {
                "raw": report_type,
                "reason": (
                    f"§5.2.1 NOTE 3 standardises report types 001 to 003 and this record states "
                    f"{report_type:03d}. NOTE 2 says 'All Report Type values are reserved for "
                    "common standard use', so this is NOT a private extension point — it is a "
                    "value this edition does not define. The record is translated and not refused: "
                    "an undefined type is not a malformed record"),
            }
            basis["undefined_type"] = (
                "STATUS_CHANGE/ADVISORY, and ADVISORY is a ruling rather than a default. INFO "
                "would say the report is understood and ordinary, WARNING would invent an alarm "
                "out of an unknown, and both are claims this record does not support. ADVISORY is "
                "the CDM's own middle value and the only one that leaves the record VISIBLE to a "
                "consumer filtering on severity while claiming nothing about what it means")
            severity = Severity.ADVISORY

        status = items.get("I023/110")
        if status is not None:
            stat = status["stat"]
            text = SERVICE_STATUS_TEXT.get(stat)
            raised = SERVICE_STATUS_SEVERITY.get(stat, Severity.ADVISORY)
            basis["raised_by"].append({
                "item": "I023/110", "raw": stat, "text": text, "severity": raised.value,
                "reason": ("§5.2.7's STAT. `1` Failed is CRITICAL — the service a consumer depends "
                           "on is not running. `3` Degraded is WARNING. `2` Disabled is WARNING "
                           "TOO, and that is the one worth arguing: a disabled service is a "
                           "service a consumer is not receiving and the record does not say "
                           "whether that was intended, so INFO would claim it was routine and "
                           "CRITICAL would claim it was a failure. `4` Normal and `5` "
                           "Initialisation are INFO. `0` Unknown is ADVISORY"),
            })
            if text is None:
                unresolved["I023/110 STAT"] = {
                    "raw": stat,
                    "reason": ("§5.2.7 defines Status of the Service values 0 to 5 and three bits "
                               "reach 7. A 6 or a 7 is a value this edition does not define, and "
                               "it takes ADVISORY for the reason an undefined report type does: "
                               "INFO would say the status is understood and ordinary, WARNING "
                               "would invent an alarm out of an unknown"),
                }
            severity = self._worse(severity, raised)

        station_status = items.get("I023/100")
        if station_status is not None and station_status["spo"]:
            basis["raised_by"].append({
                "item": "I023/100 SPO", "raw": 1, "text": "potential spoofing attack",
                "severity": Severity.WARNING.value,
                "reason": (
                    "§5.2.5's 'Indication of spoofing attack'. THE ONE BIT IN THIS CATEGORY THAT "
                    "RAISES SEVERITY FROM THE STATION RATHER THAN THE SERVICE, and it is a "
                    "decision: the station is reporting a detected attack on itself, which is "
                    "neither routine (INFO) nor an emergency in progress (CRITICAL). "
                    "NOT EventType.GNSS_INTERFERENCE: that member is paired with "
                    "GnssInterferencePayload, whose fields — frequency_band, interference_type, "
                    "signal_strength_dbm — exist for the PNTMAP adapter, and a spoofing "
                    "indication on an ADS-B ground station is not a GNSS event. Putting it in the "
                    "field a consumer filters on to find GNSS threats is a wrong answer that reads "
                    "as a right one. FORMAT_COVERAGE.md gap 29, reached a third time"),
            })
            severity = self._worse(severity, Severity.WARNING)
        return severity, basis

    @staticmethod
    def _worse(current: Severity, candidate: Severity) -> Severity:
        """The more severe of two, ordered worst-first so the direction cannot be got backwards."""
        order = (Severity.CRITICAL, Severity.WARNING, Severity.ADVISORY, Severity.INFO)
        return min((current, candidate), key=order.index)

    # ------------------------------------------------------------------ the parks

    def _attributes(self, record: dict, block: dict, items: dict, station_id: str,
                    station_entity_id: Any, service_basis: dict | None,
                    unavailable: list[str], unresolved: dict[str, Any]) -> dict:
        attributes: dict[str, Any] = {}
        station = items["I023/010"]
        attributes["object_is"] = "the GROUND STATION"
        attributes["cat023_block"] = dict(block)
        attributes["cat023_fspec"] = record["fspec"]
        attributes["cat023_items"] = dict(record.get("item_octets") or {})
        attributes["data_source"] = {
            "sac": station["sac"], "sic": station["sic"], "external_id": station_id,
            "basis": (
                "I023/010, 'Identification of the Ground Station from which the data is received' "
                "(§5.2.2), M in every column of Table 2. A SourceId here and parked at "
                "attributes.data_source in asterix_cat048.py and asterix_cat062.py — the same two "
                "octets of the same standard, filed two different ways, and the difference is the "
                "whole reason both dispositions exist: there the SAC/SIC identifies the SENSOR or "
                "the PROCESSOR and the object is a target, so filing it under the object's "
                "identifiers is how a fused picture ends up with an entity per receiver; here the "
                "station IS the object and the pair is its own identifier"),
            "note": ("The up-to-date list of SACs is published on the EUROCONTROL Web Site "
                     "(https://www.eurocontrol.int/asterix) — note HTTPS here and HTTP in Part "
                     "2b's equivalent NOTE, which is the same list at two spellings of one URL"),
        }
        attributes["identity_basis"] = (
            f"uuid5 over ({STATION_SYSTEM}, {station_id!r}). The system name is NOT this adapter's "
            "own: a SAC/SIC is allocated across the whole ASTERIX family from one list, so filing "
            "it under a category name would say that one station seen through Part 16 is a "
            "different station from the same pair seen through any other part. The SAME string "
            "asterix_cat034.py uses, so one station seen through both parts is ONE entity without "
            "the two adapters coordinating. "
            "AND HERE A CLAUSE SUPPORTS IT RATHER THAN AN INFERENCE: §4.4.1 is a normative section "
            "of its own — 'By convention a dedicated and unambiguous SAC/SIC code shall be "
            "assigned to every Ground Station' — where Part 2b has only §5.2.2's definition and a "
            "NOTE pointing at the published list")
        attributes["entity_type_basis"] = (
            "SENSOR, from the category rather than from any item. Every record in Part 16 is about "
            "a CNS/ATM ground station or a service it provides (§1.1: 'the structure for the "
            "transmission of service reports from a CNS/ATM Ground station'), so there is nothing "
            "to read: the object's type is a property of the format")
        attributes["affiliation_basis"] = (
            "UNKNOWN, always, and here it is not even a decision. A ground station service report "
            "states configuration and health and never allegiance, and this repository does not "
            "infer one from a SAC")
        attributes["symbol_basis"] = (
            "derived from the affiliation through symbology.sidc_from_affiliation, so every CAT023 "
            "station and service is an UNKNOWN glyph. CAT023 carries no symbology of any kind")
        attributes["position_basis"] = (
            "None, ON EVERY OBJECT, and this category is why rather than this adapter. NINE ITEMS "
            "AND NOT ONE COORDINATE: I023/200 is an operational range in nautical miles with no "
            "centre, and §4.4.1 asserts that a SAC/SIC is dedicated and unambiguous per ground "
            "station without saying where any station is. So a consumer holding CAT023 alone cannot "
            "place a station on a map, and this adapter does not help it: reading a station "
            "position out of a CAT034 record to locate a CAT023 station is cross-payload state, "
            "which is the refusal asterix_cat034.py's settlement 2 already made in the other "
            "direction. An absent Position is the honest statement, never a Position holding zeros")
        attributes["geometry_basis"] = (
            "Event.geometry is None on every object, PERMANENTLY. I023/200 is a radius and there is "
            "no centre in the category, so a circle cannot be derived from a conformant record at "
            "all — which is asterix_cat034.py's settlement 7 shape reached by a shorter route: "
            "there because Table 2 makes two items mutually exclusive, here because one of the two "
            "does not exist")
        attributes["integrity_basis"] = (
            "CAT023 defines NO checksum at any level — neither §4.5.2 nor §4.6 nor any §5.2 item "
            "specifies a CRC, checksum or parity field at block, record or item level. What passed "
            "is the structural gate: LEN matched the buffer, the records tiled it exactly, every "
            "FSPEC bit named a defined and non-spare FRN, no FX led to an extension the document "
            "does not define, every REP was non-zero, and the items Table 2 makes mandatory for "
            "this record's own report type were present. This is weaker than a CRC and the "
            "difference is named rather than smoothed over: a single bit flipped inside a "
            "fixed-length field satisfies every check above and reaches the CDM as a station "
            "status")
        attributes["table_2_disposition"] = self._table_2_disposition(items)
        if service_basis is not None:
            attributes["service_reported"] = {
                "entity_id": str(service_basis["entity_id"]),
                "sid": service_basis["sid"],
                "styp": service_basis["styp"],
                "styp_text": service_basis["styp_text"],
                "basis": ("the SERVICE this record is about, which is a SECOND Entity — settlement "
                          "2. Recorded on the station too, so a consumer holding only the station "
                          "object can see which service the record described"),
            }
        station_status = items.get("I023/100")
        if station_status is not None:
            attributes["ground_station_status"] = self._ground_station_status(station_status,
                                                                             unresolved)
        statistics = items.get("I023/120")
        if statistics is not None:
            attributes["service_statistics"] = self._statistics(statistics, unresolved)
        operational_range = items.get("I023/200")
        if operational_range is not None:
            attributes["operational_range"] = self._operational_range(operational_range)
        self._park_opaque(items, attributes)
        attributes["unavailable_fields"] = sorted(unavailable)
        attributes["unresolved_raw"] = unresolved
        attributes["source_extras"] = lossless.residual(record, self.CONSUMED)
        return attributes

    def _table_2_disposition(self, items: dict) -> dict:
        """Which items this record carries that its own report type says are never present.

        Present on EVERY record, empty list and all, because "no item is out of place" and "this
        adapter did not look" are different facts and only one of them is worth reading.
        """
        report_type = items["I023/000"]["report_type"]
        column = TABLE_2.get(report_type)
        if column is None:
            return {
                "report_type": report_type,
                "column": None,
                "items_present_where_the_table_says_X": None,
                "basis": ("Table 2 has no column for this report type, so no M/O/X rule applies to "
                          "any item in this record beyond the two that are M in every column"),
            }
        return {
            "report_type": report_type,
            "column": dict(column),
            "items_present_where_the_table_says_X": sorted(
                item for item in items if column.get(item) == "X"),
            "basis": ("PARKED, never dropped and never an error. Table 2's X means 'never present' "
                      "for that report type, so an item under an X is a conformance fault in the "
                      "ENCODER — and every octet of it is still decodable, its length is still "
                      "stated, and refusing would discard data the FSPEC correctly announced. "
                      "§4.3's discipline for a bit that means nothing, applied one level up to an "
                      "item that means nothing here. A missing M is the opposite case and IS "
                      "refused, in _check_table_2"),
            "what_the_table_makes_impossible": (
                "I023/100 is M for type 001 and X for the other two; I023/101, I023/110 and "
                "I023/120 are each M for exactly one type and X elsewhere. So a conformant record "
                "carries EITHER the station's status OR one service's configuration and status OR "
                "one service's statistics, never two of the three — and a consumer wanting a "
                "station's full picture needs three records, which is accumulation across payloads "
                "and a consumer's act"),
        }

    def _ground_station_status(self, status: dict, unresolved: dict[str, Any]) -> dict:
        """I023/100, and `NOGO` is the bit that is parked rather than raised."""
        parked: dict[str, Any] = {
            "nogo": {
                "raw": status["nogo"],
                "text": ("Data must not be used operationally" if status["nogo"]
                         else "Data is released for operational use"),
                "basis": (
                    "THE OPERATIONALLY LOUDEST BIT IN THE CATEGORY, and it is parked rather than "
                    "raised into severity. NOTE 2 restates it: 'Bit 8 (NOGO), when set to \"1\" "
                    "indicates that the data transmitted by the GS is not released for operational "
                    "use.' It governs what a consumer does with the station's TARGET REPORTS, and "
                    "this adapter emits none of those — raising an alert here would be this "
                    "translator judging data it has never been shown. asterix_cat034.py's "
                    "reasoning for I034/050's NOGO, reached again in a different part"),
            },
            "odp": {"raw": status["odp"],
                    "text": "Overload in DP" if status["odp"] else "Default, no overload"},
            "oxt": {"raw": status["oxt"],
                    "text": ("Overload in transmission subsystem" if status["oxt"]
                             else "Default, no overload")},
            "overload_basis": (
                "TWO INDEPENDENT OVERLOAD INDICATIONS, parked separately: ODP is 'Data Processor "
                "Overload Indicator' and OXT is 'Ground Interface Data Communications Overload'. "
                "One is in processing and one is in transmission, and a merged 'overloaded' key "
                "would lose which subsystem it was"),
            "msc": {
                "raw": status["msc"],
                "text": ("Monitoring system connected" if status["msc"]
                         else "Monitoring system not connected or unknown"),
                "basis": ("the wording matters and is carried verbatim: `0` is 'Monitoring system "
                          "NOT CONNECTED OR UNKNOWN' — a two-in-one value — so a clear bit is not "
                          "a statement that nothing is connected"),
            },
            "tsv": {
                "raw": status["tsv"], "text": "invalid" if status["tsv"] else "valid",
                "definition": ("NOTE 1: 'A time source is considered as valid when either "
                               "externally synchronised or running on a local oscillator within "
                               "the required accuracy of UTC.'"),
                "basis": ("PARKED, and it does NOT change how I023/070 is read. An invalid time "
                          "source with a present time of day is a record whose own clock the "
                          "station distrusts, and both facts are carried; suppressing observed_at "
                          "on it would discard the only time the record states"),
            },
            "spo": {
                "raw": status["spo"],
                "text": ("potential spoofing attack" if status["spo"] else "no spoofing detected"),
                "basis": ("the one bit in this category that raises Event.severity from the "
                          "station — see payload.severity_basis. NOT EventType.GNSS_INTERFERENCE"),
            },
            "rn": {
                "raw": status["rn"],
                "text": "track numbering has restarted" if status["rn"] else "default",
                "definition": ("NOTE 3: 'Bit 2 indicates that the allocation of Track-IDs (Item "
                               "I021/161) was re-started.'"),
                "basis": (
                    "PARKED. **THIS BIT IS CITED AS EVIDENCE IN THE CAT062 ROW SET**, and the "
                    "citation is worth stating from this side too: FORMAT_COVERAGE.md's CAT062 "
                    "settlement 3 rules that a system track number is never the basis of an "
                    "entity_id, because the number is scoped to the emitting system and recycled. "
                    "This is a different ASTERIX part, written by a different working group, and it "
                    "carries a dedicated status bit whose entire purpose is to announce that a "
                    "track-number space has been reused. The two are independent — nothing in Part "
                    "16 is about Part 9 — and the evidence is about the CLASS of identifier. What "
                    "is NOT claimed is that I021/161 and I062/040 are the same number space; they "
                    "are not"),
            },
        }
        extension = status.get("extension")
        if extension is not None:
            raw = extension["gssp_raw"]
            seconds = codec.from_raw("gssp", raw)
            low, high, _lsb = codec.bounds("gssp")
            if not low <= seconds <= high:
                field_low, field_high = codec.width("gssp")
                raise Cat023ParseError(
                    f"I023/100's First Extension states GSSP = {raw}, which is {seconds!r} s, and "
                    f"§5.2.5 states 'Valid range: {low:.0f} <= GSSP <= {high:.0f}s'. The field is "
                    f"seven bits and reaches [{field_low!r}, {field_high!r}] s, so this value is "
                    "one the item's own range excludes rather than one the field cannot express. "
                    "Refused rather than read as 'no periodic reporting': §4.5.1.1 makes the "
                    "periodic send an OBLIGATION — 'the Ground Station Status Report shall be sent "
                    "periodically (every GSSP seconds ...) and whenever a change occurs' — so a "
                    "period of zero is not a way of turning it off, it is a value the item excludes"
                )
            parked["reporting_period"] = {
                "seconds": seconds, "raw": raw, "lsb_seconds": codec.bounds("gssp")[2],
                "definition": "Ground Station Status Reporting Period",
                "obligation": ("§4.5.1.1: 'the Ground Station Status Report shall be sent "
                               "periodically (every GSSP seconds — please refer to Data Item "
                               "I023/100) and whenever a change occurs'"),
                "basis": ("SEVEN bits at 1 s, because bit 1 is the FX, with a stated range of "
                          "1 to 127. Seven bits reach exactly 127 so the TOP of the stated range "
                          "and the top of the field agree; the BOTTOM does not, and a zero is "
                          "refused. Parked and NOT used to derive Entity.valid_to — deriving a "
                          "staleness horizon would be this adapter reasoning about reports it has "
                          "not seen"),
            }
        return parked

    def _configuration(self, configuration: dict, unresolved: dict[str, Any]) -> dict:
        """I023/101, the only `2+` item in any ASTERIX category pinned here."""
        rp_raw = configuration["rp_raw"]
        data_driven = rp_raw == 0
        parked: dict[str, Any] = {
            "report_period": {
                "raw": rp_raw,
                "seconds": None if data_driven else codec.from_raw("rp", rp_raw),
                "data_driven_mode": data_driven,
                "lsb_seconds": codec.bounds("rp")[2],
                "definition": "Report Period for Category 021 Reports",
                "basis": (
                    "EIGHT bits at 0.5 SECONDS, and its ZERO IS A NAMED MODE rather than a period: "
                    "'= 0: Data driven mode'. So `seconds` is None on a zero and never 0.0 — the "
                    "AIS sentinel lesson in a new format, because 0.0 s reaching a consumer as a "
                    "period is the failure. "
                    "AND THE FIELD IS ABOUT ANOTHER CATEGORY'S FEED: its definition is 'Report "
                    "Period for Category 021 Reports', so the number governs how often the SERVICE "
                    "emits CAT021 target reports, which this adapter never sees. Parked as a "
                    "statement about a different feed and emphatically NOT applied as a staleness "
                    "horizon to anything — deriving one would be reasoning about payloads this "
                    "adapter has not been given"),
                "differs_from_gssp_and_ssrp": (
                    "three reporting periods in one nine-item specification, two LSBs and two "
                    "incompatible readings of zero: GSSP and SSRP are seven-bit fields at 1 s "
                    "whose zero is OUT OF RANGE, and this is an eight-bit field at 0.5 s whose "
                    "zero is a MODE. A shared decoder for 'a reporting period' would be wrong for "
                    "one of the three whichever reading it took, which is why there is none. "
                    "FORMAT_COVERAGE.md ambiguity 6"),
            },
            "service_class": {
                "raw": configuration["sc"], "text": SERVICE_CLASS_TEXT.get(configuration["sc"]),
                "basis": ("§5.2.6 bits 8/6 of octet 2: `0` No information, `1` NRA class, `2`-`7` "
                          "'reserved for future use'. `0` is a STATED NON-STATEMENT, which is "
                          "different from an absent item"),
            },
            "spare_bits_5_2": configuration["spare_bits_5_2"],
            "two_octet_first_part_basis": (
                "§5.2.6's first part is TWO OCTETS with the FX in the SECOND, and its extension is "
                "one octet — the only `2+` item in any ASTERIX category this repository pins. So "
                "its length rule cannot be shared with I023/100's or I023/110's, and the UAP's "
                "length legend explains only `1+`. FORMAT_COVERAGE.md ambiguity 4"),
        }
        if configuration["sc"] not in SERVICE_CLASS_TEXT:
            unresolved["I023/101 SC"] = {
                "raw": configuration["sc"],
                "reason": ("§5.2.6 defines Service Class values 0 and 1 and spells 2 to 7 "
                           "'reserved for future use'. This is a value this edition does not "
                           "assign"),
            }
        extension = configuration.get("extension")
        if extension is not None:
            raw = extension["ssrp_raw"]
            seconds = codec.from_raw("ssrp", raw)
            low, high, _lsb = codec.bounds("ssrp")
            if not low <= seconds <= high:
                field_low, field_high = codec.width("ssrp")
                raise Cat023ParseError(
                    f"I023/101's First Extension states SSRP = {raw}, which is {seconds!r} s, and "
                    f"§5.2.6 states 'Valid range: {low:.0f} <= SSRP <= {high:.0f}s'. The field is "
                    f"seven bits and reaches [{field_low!r}, {field_high!r}] s, so this value is "
                    "one the item's own range excludes rather than one the field cannot express. "
                    "Refused rather than read as 'no periodic reporting': §4.5.1.2 makes the "
                    "periodic send an obligation"
                )
            parked["service_status_reporting_period"] = {
                "seconds": seconds, "raw": raw, "lsb_seconds": codec.bounds("ssrp")[2],
                "definition": "Service Status Reporting Period",
                "obligation": ("§4.5.1.2: 'the Service Status Report shall be sent periodically "
                               "(every SSRP seconds — please refer to Data Item I023/101) and "
                               "whenever a change occurs'"),
                "basis": ("identical shape and identical bounds to GSSP, in a different item for a "
                          "different obligation. Parked separately for exactly that reason"),
            }
        return parked

    def _status(self, status: dict, unresolved: dict[str, Any]) -> dict:
        """I023/110, whose FX names an extension no edition in hand defines."""
        return {
            "raw": status["stat"],
            "text": SERVICE_STATUS_TEXT.get(status["stat"]),
            "spare_bits_8_5": status["spare_bits_8_5"],
            "basis": ("§5.2.7 bits 4/2, six values in three bits. The raw value AND its wording "
                      "are parked because the collapse onto four severities must stay recoverable "
                      "and egress re-emits FROM HERE rather than re-deriving a status from a "
                      "Severity that two statuses share"),
            "spare_bits_basis": (
                "bits 8/5, legended 'bits-8/5 (Spare) Spare BIT set to 0' — four bits described "
                "with a singular noun (FORMAT_COVERAGE.md ambiguity 10). All four are read and "
                "re-emitted as sent regardless, because §4.3 is normative that a decoder 'shall "
                "never assume and rely on specific settings of spare or unused bits'"),
            "extension_basis": (
                "§5.2.7's FX reads '= 1 Extension' and NO EXTENSION EXISTS FOR THIS ITEM IN ANY "
                "EDITION IN HAND, including Edition 0.14. So a set FX is refused — the strongest "
                "of this category's three such cases, because the other two at least name a "
                "'Second Extension' that a later edition might define"),
        }

    def _statistics(self, statistics: dict, unresolved: dict[str, Any]) -> dict:
        """I023/120's counters, ordered and per-counter referenced."""
        counters = []
        undefined_generic: list[int] = []
        undefined_outside: list[int] = []
        for counter in statistics["counters"]:
            text = COUNTER_TYPE_TEXT.get(counter["type"])
            counters.append({
                "type": counter["type"], "text": text, "counter": counter["counter"],
                "reference": COUNTER_REFERENCE_TEXT[counter["ref"]],
                "reference_raw": counter["ref"],
                "spare_bits_39_33": counter["spare_bits_39_33"],
            })
            if text is None:
                (undefined_generic if counter["type"] in COUNTER_GENERIC_BAND
                 else undefined_outside).append(counter["type"])
        if undefined_generic:
            unresolved["I023/120 TYPE in the reserved generic band"] = {
                "raw": sorted(set(undefined_generic)),
                "reason": ("§5.2.8's NOTE: 'There is no special significance attributed to the "
                           "numbering of the TYPE field. However the range from 0 to 19 is "
                           "intended to cover generic messages which may be applicable to many "
                           "types of service.' So this is a DOCUMENTED RESERVATION — a generic "
                           "counter this edition has not allocated — and not a value outside the "
                           "table. The count is still parked; what is unresolved is what it "
                           "counts"),
            }
        if undefined_outside:
            unresolved["I023/120 TYPE outside the table"] = {
                "raw": sorted(set(undefined_outside)),
                "reason": ("§5.2.8 defines TYPE values 0 to 4 and 20 to 32 and this record carries "
                           "one above the table entirely — a different kind of unknown from a "
                           "value in the reserved 0-to-19 band, and the two are recorded "
                           "separately for that reason"),
            }
        return {
            "rep": statistics["rep"],
            "counters": counters,
            "basis": ("§5.2.8, an ORDERED list with duplicates preserved — the I048/030 and "
                      "I034/070 rule reached a third time: order is data, the document does not "
                      "say the TYPE values are unique, and egress is byte-exact only if the "
                      "counters go back out as they came in. A COUNT IS NOT A DETECTION: none of "
                      "the eighteen defined TYPE values produces an Event per counted message, "
                      "which would invent target reports this document does not carry. And no rate "
                      "is computed from a counter and a reporting period, which would be a figure "
                      "the source did not state"),
            "reference_basis": (
                "PER COUNTER and never once for the item: the REF bit is inside each six-octet "
                "block, so one record may legitimately carry counters with two different "
                "references. "
                "AND THE ITEM'S OWN DEFINITION DISAGREES WITH ITS OWN FIELD: the Definition says "
                "the counts are 'since the report was last sent' UNCONDITIONALLY, while REF offers "
                "'From midnight' as well. THE FIELD IS PREFERRED over the Definition, because the "
                "field is what the wire carries. FORMAT_COVERAGE.md ambiguity 7"),
        }

    def _operational_range(self, item: dict) -> dict:
        raw = item["range_raw"]
        nautical_miles = codec.from_raw("operational_range", raw)
        parked: dict[str, Any] = {
            "nautical_miles": nautical_miles, "raw": raw,
            "definition": "Currently active operational range of the GS",
            "basis": ("§5.2.9, one octet at 1 NM, and the ONLY OPTIONAL ITEM IN THE CATEGORY — `O` "
                      "for report types 001 and 002 and `X` for 003. Parked as nautical miles and "
                      "as the raw octet. NO Event.geometry is derived from it, permanently: a "
                      "range is a radius and this category carries no centre"),
        }
        if nautical_miles >= codec.bounds("operational_range")[1]:
            parked["at_or_above_maximum"] = AT_OR_ABOVE_MAXIMUM_NOTE
            parked["floor_basis"] = (
                "255 NM is a FLOOR and not a measurement, per the item's own NOTE. Carried as the "
                "number and flagged — the AIS 102.2 kt discipline, because a consumer "
                "differentiating two saturated readings would compute a zero rate of change")
        return parked

    def _park_opaque(self, items: dict, attributes: dict) -> None:
        expansion = items.get("RE")
        if expansion is not None:
            attributes["reserved_expansion_field"] = {
                **expansion,
                "basis": (
                    "PARKED VERBATIM, OCTET FOR OCTET, RESTORED UNCHANGED ON EGRESS, NEVER "
                    "DECODED — the asterix_cat034.py disposition with a procedural reason one step "
                    "stronger again. There, an appendix that defines the field exists and was "
                    "simply not acquired; there, the change record at least recorded the slot's "
                    "arrival. HERE THIS DOCUMENT DEFINES NO PART OF IT, LISTS NO APPENDIX THAT "
                    "DOES, AND HAS NO CHANGE-RECORD LINE FOR IT EITHER: FRN 13 has no §5.2 entry, "
                    "no appendix exists for Part 16, and no edition in hand mentions the field "
                    "outside the UAP"),
                "length_convention": (
                    "a one-octet length counting itself, INHERITED from the shipped ASTERIX "
                    "siblings and named as inherited. ASTERIX Part 1 defines these fields; this "
                    "document cites Part 1 as SUR.ET1.ST05.2000-STD-01-01 Edition 1.29 of FEBRUARY "
                    "2002 — the pre-migration reference number at a nineteen-year-old edition, in "
                    "a document dated September 2021 — and Part 1 is not pinned in this "
                    "repository. So even acquiring Part 1 at its current edition would not "
                    "obviously be acquiring the document this specification cites. "
                    "FORMAT_COVERAGE.md ambiguity 3"),
            }
        special = items.get("SP")
        if special is not None:
            attributes["special_purpose_field"] = {
                **special,
                "basis": (
                    "opaque by construction. Parked verbatim as hex and NEVER WRITTEN TO on "
                    "egress — a Special Purpose Field's contents are settled by bilateral "
                    "agreement between one sender and one receiver, so a byte invented here is a "
                    "byte some deployment already means something by. No §5.2 description exists "
                    "for it in this document"),
            }

    def _payload(self, record: dict, block: dict, items: dict, time_basis: dict,
                 severity_basis: dict, report_type: int, service_basis: dict | None,
                 unresolved: dict[str, Any]) -> dict:
        payload: dict[str, Any] = {
            "observed_at_basis": time_basis,
            "severity_basis": severity_basis,
            "report_type": {
                "raw": report_type,
                "name": REPORT_TYPE_TEXT.get(report_type),
                "defined_at": ("§5.2.1 NOTE 3 gives the three values and points at §4.5.1.1, "
                               "§4.5.1.2 and §4.5.1.3 for what each one MEANS — and those three "
                               "subsections are where the reporting-period obligations live, so "
                               "the item that carries the period is I023/100 or I023/101 and the "
                               "obligation that gives it meaning is in chapter 4"),
                "basis": ("the raw value AND its name, parked, because the collapse onto "
                          "event_type is 3 -> 1 and egress re-emits FROM HERE rather than "
                          "re-deriving a type from an EventType all three share"),
                "all_values_reserved": (
                    "§5.2.1 NOTE 2: 'All Report Type values are reserved for common standard "
                    "use.' The same sentence Part 2b's I034/000 NOTE 2 carries about Message "
                    "Types. So a value outside 001-003 is NOT a private extension point — it is a "
                    "value this edition does not define — and it lands in unresolved_raw rather "
                    "than in source_extras"),
                "handling_note": (
                    "NOTE 1: 'In applications where transactions of various types are exchanged, "
                    "the Report Type Data Item facilitates the proper report handling at the "
                    "receiver side.' The item's own statement of what it is for, and the sentence "
                    "that makes Table 2 the encoding rule for the other eight items"),
            },
            "record_index": record["index"],
            "record_count": record.get("record_count", block.get("record_count")),
        }
        if service_basis is not None:
            payload["service"] = {
                "sid": service_basis["sid"], "styp": service_basis["styp"],
                "styp_text": service_basis["styp_text"],
                "nibble_basis": (
                    "the item is named 'Service Type and Identification' and the octet is SID in "
                    "bits 8/5 and STYP in bits 4/1 — THE NAME IS IN THE OTHER ORDER FROM THE BITS. "
                    "A transposition yields a plausible wrong service rather than an error, "
                    "because SID 2 / STYP 9 and SID 9 / STYP 2 are both legal, so the two nibbles "
                    "are parked under explicit names and never as one integer"),
                "scope_note": (
                    "§1.1's scope sentence names FIVE service kinds — 'ADS-B, TIS-B, FIS-B, GRAS, "
                    "and MLT' — and §5.2.3's table gives NINE values, because four of the five are "
                    "qualified by a data link. The two agree and count differently, which is worth "
                    "stating because a reader checking one against the other sees five against "
                    "nine"),
            }
        status = items.get("I023/110")
        if status is not None:
            payload["service_status"] = self._status(status, unresolved)
        configuration = items.get("I023/101")
        if configuration is not None:
            payload["service_configuration"] = self._configuration(configuration, unresolved)
        statistics = items.get("I023/120")
        if statistics is not None:
            payload["service_statistics"] = self._statistics(statistics, unresolved)
        return payload

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities that CAME FROM CAT023 back to one data block, byte-exactly.

        **THE TWO-ENTITY SHAPE NEEDS ONE RULE AND THIS IS IT.** A record that produced a station
        Entity and a service Entity is re-assembled from the STATION Entity, which carries the
        parked FSPEC and the parked item octets; the service Entity carries the same record by
        reference and contributes no octet of its own. So this groups by the parked FSPEC and emits
        one record per station Entity, and a caller passing only the service Entity gets a refusal
        naming what is missing rather than a record with an invented FSPEC.

        Everything derived — `observed_at`, the decoded seconds and nautical miles — is a one-way
        view and is not the source of any emitted byte. This category is the easiest case in the
        family for that: **not one scaled value becomes a canonical numeric field**, so there is no
        arithmetic to invert anywhere.
        """
        stations = [obj for obj in objects
                    if isinstance(obj, Entity)
                    and obj.attributes.get("object_is") == "the GROUND STATION"]
        if not stations:
            entities = [obj for obj in objects if isinstance(obj, Entity)]
            services = [obj for obj in entities
                        if obj.attributes.get("object_is", "").startswith("the SERVICE")]
            if services:
                raise Cat023ParseError(
                    f"{len(services)} service Entity(ies) and no station Entity. A CAT023 record "
                    "is re-assembled from the STATION object, which is the one carrying the parked "
                    "FSPEC and the parked item octets; a service object carries the record by "
                    "reference and contributes no octet of its own. Pass the station Entity the "
                    "record produced alongside it — inventing an FSPEC would state which items a "
                    "record claimed to carry, which is the one thing egress must not guess"
                )
            raise Cat023ParseError(
                f"nothing to emit: {len(objects)} object(s) and no station Entity among them. A "
                "CDM Track cannot become a CAT023 data block either, and the reason is not the "
                "arithmetic: a Track carries samples of a moving thing and every record in this "
                "category is a statement about a stationary ground station or a service it "
                "provides. There is no SAC/SIC anywhere in a Track, no FSPEC and no report type, "
                "and inventing a SAC/SIC would NAME a ground station that does not exist"
            )
        return build_block([self._record_from_entity(entity) for entity in stations])

    def _record_from_entity(self, entity: Entity) -> dict:
        parked = entity.attributes.get("source_extras") or {}
        items = parked.get("items") if isinstance(parked, dict) else None
        fspec = entity.attributes.get("cat023_fspec")
        octets = entity.attributes.get("cat023_items")
        if not items or not fspec:
            missing = [name for name, value in
                       (("source_extras.items", items), ("cat023_fspec", fspec)) if not value]
            raise Cat023ParseError(
                f"Entity {entity.entity_id} did not come from CAT023: {', '.join(missing)} is "
                "absent from its attributes. There is no SAC/SIC to write and I023/010 is M in "
                "every column of Table 2; there is no report type and I023/000 is M in every "
                "column too; and there is no FSPEC, so nothing states which items the record "
                "claimed to carry. The refusal names each missing input rather than inventing one"
            )
        return {"index": 0, "fspec": fspec, "items": items,
                "item_octets": dict(octets or {})}
