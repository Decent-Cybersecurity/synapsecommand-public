"""ASTERIX Category 034 — Monoradar Service Messages. Data blocks in, CDM out, and back.

Adapter #12, and the first in this repository whose primary object is the SENSOR itself.

INGEST  one ASTERIX **data block** — `CAT | LEN | FSPEC + items | ...` — becomes an Entity + an
        Event per record, in block order. The Entity is the radar station.
EGRESS  Entities that CAME FROM CAT034 become one data block, byte-exactly. Anything else is a
        refusal that names what is missing.

Implements the row set in `FORMAT_COVERAGE.md` under "ASTERIX Category 034", which was written
and reviewed as a specification BEFORE this file existed. Where the code and a row disagree the
row wins, or the row changes in the same commit; the changes made here are listed in that
section under "What Phase 2 changed in the Phase 1 row set" and each is noted at its site.

EVERY RECORD DESCRIBES THE STATION, WHICH DECIDES THE OBJECT SHAPE
------------------------------------------------------------------
`asterix_cat048.py` translates what one radar says about what it DETECTED; this translates what
the same radar says about ITSELF. So `I034/010`'s SAC/SIC is a `SourceId` here and is parked at
`attributes.data_source` there, `entity_type` is `SENSOR` rather than read off a target
descriptor, and there is no `Kinematics` at any point — a station does not move, and the one
bearing in the category is the ANTENNA's, not a course.

WHAT THIS ADAPTER REFUSES TO DO WITH `I034/120`, AND WHY IT IS NOT AN OMISSION
------------------------------------------------------------------------------
`I034/120` carries the station's own WGS-84 position — the exact value the sibling adapter
requires a caller to INJECT, and whose geodesy FORMAT_COVERAGE.md **gap 24** records as absent
from the pinned CAT048 document. It becomes a `Position` on the CAT034 Entity that carries it
and it is handed to nobody: reading it out of a CAT034 record to interpret a CAT048 one is
cross-payload state, which is the fusion refusal. **Gap 24 does not close**,
`attributes.position_basis` says so in the object rather than in a comment, and a test asserts
it.

NO GEOMETRY IS DERIVED FROM `I034/100`, AND TABLE 2 IS THE REASON
-----------------------------------------------------------------
The polar window would need the station's position to become a polygon, the station's position
is in `I034/120`, and Table 2 makes those two items mutually exclusive across all seven message
types — so the position could only ever come from a DIFFERENT record. The ruling Phase 1 left
open is therefore decided by the document rather than by preference.

THE INJECTED CLOCK, AND THERE IS NO SECOND INJECTED VALUE
----------------------------------------------------------
`clock`, as every adapter has: `I034/030` is a count of 1/128 s since midnight with no date, so
the date comes from the injected clock and the adapter never reads the wall clock. Unlike its
sibling there is NO `sensor_position` argument, because the station's position is on the wire —
and accepting one anyway would create a second, silent authority for the same fact.

NO CHECKSUM, SO THE GATE IS STRUCTURAL
--------------------------------------
Neither §4.6.2 nor §4.7 nor any §5.2 item defines a CRC, checksum or parity field at block,
record or item level. So the block must satisfy LEN, the records must tile it exactly, every
FSPEC bit must name a defined FRN, every compound item's presence bits must name a subfield that
exists, every `FX` that leads nowhere is a refusal, and the items Table 2 makes mandatory for the
record's own message type must be present. `attributes.integrity_basis` records on every object
that this is what passed.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from synapse_cdm import ids, lossless, symbology, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import cat034_codec as codec
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import CDMBase, Entity, Event, Position, SourceId

#: This adapter's own system name, for `SourceRef.system`.
SYSTEM = "ASTERIX_CAT034"

#: The source id system for a radar station's SAC/SIC pair.
#:
#: NOT `ASTERIX_CAT034`, and the difference is the same one `ICAO24` makes in the CAT048 and
#: CAT021 adapters. A SAC/SIC identifies a STATION and is allocated by EUROCONTROL across the
#: whole ASTERIX family — §5.2.2's NOTE points at one list for every part — so the identifier's
#: namespace belongs to the family and not to this category. Filing it under a category name
#: would say that station 0x29/0x29 seen through Part 2b is a different station from the same
#: pair seen through any other part, which is false. Nothing joins on it today, because no other
#: adapter here emits a station Entity; the id is a pure function of the pair either way.
STATION_SYSTEM = "ASTERIX_SAC_SIC"

#: One octet, and this adapter speaks exactly one category. A CAT048 block decoded against the
#: CAT034 UAP yields a plausible wrong radar status rather than an error.
CATEGORY = 34

#: CAT (1) + LEN (2). LEN counts itself and the CAT octet, per §4.6.2.
BLOCK_HEADER_OCTETS = 3


class Cat034ParseError(ValueError):
    """A block this adapter refuses. Every message quotes the offending octets."""


def _refuse(message: str, data: bytes, offset: int, span: int = 8) -> Cat034ParseError:
    window = data[max(0, offset - 2):offset + span]
    return Cat034ParseError(
        f"{message} (at octet {offset} of {len(data)}; octets here: {window.hex()})"
    )


# ===================================================================== the vocabularies

#: §5.2.1 NOTE 3, verbatim. **Types 006 and 007 are this EDITION's**: Edition 1.29's change
#: record reads "Data Item I034/000: new message types 6&7", and Edition 1.28 standardises 001
#: to 005. An adapter written against Edition 1.28 would have exactly these two missing, which
#: is what makes the pair an edition marker rather than two more table entries.
MESSAGE_TYPE_TEXT: dict[int, str] = {
    1: "North Marker message",
    2: "Sector crossing message",
    3: "Geographical filtering message",
    4: "Jamming Strobe message",
    5: "Solar Storm Message",
    6: "SSR Jamming Strobe Message",
    7: "Mode S Jamming Strobe Message",
}

#: Three of the seven types are jamming reports and NONE of them sets `GNSS_INTERFERENCE`: that
#: enum member is paired with `GnssInterferencePayload`, whose fields exist for the PNTMAP
#: adapter, and a radar jamming strobe is not a GNSS event. Gap 29.
JAMMING_TYPES = frozenset({4, 6, 7})

EVENT_TYPE_BY_MESSAGE_TYPE: dict[int, EventType] = {
    1: EventType.STATUS_CHANGE,
    2: EventType.STATUS_CHANGE,
    3: EventType.STATUS_CHANGE,
    4: EventType.ALERT,
    5: EventType.STATUS_CHANGE,
    6: EventType.ALERT,
    7: EventType.ALERT,
}

SEVERITY_BY_MESSAGE_TYPE: dict[int, Severity] = {
    1: Severity.INFO,
    2: Severity.INFO,
    3: Severity.INFO,
    4: Severity.WARNING,
    5: Severity.INFO,
    6: Severity.WARNING,
    7: Severity.WARNING,
}

#: The twelve items, in the order §5.1's Table 1 lists them. Named once so Table 2's seven
#: columns below cannot each acquire a different idea of which items exist.
TABLE_2_ITEMS = ("I034/000", "I034/010", "I034/020", "I034/030", "I034/041", "I034/050",
                 "I034/060", "I034/070", "I034/090", "I034/100", "I034/110", "I034/120")

#: §5.2.1 NOTE 4 and Table 2, transcribed column by column. `M` mandatory, `O` optional, `X`
#: never present — and the item-level Encoding Rules are all "See table in I034/000", so THIS is
#: the encoding rule for eleven of the twelve items rather than a summary of them.
#:
#: A missing `M` is a refusal and a present `X` is parked; the asymmetry is real and
#: `_check_table_2` is where it is argued.
TABLE_2: dict[int, dict[str, str]] = {
    1: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "M", "O", "O", "O", "O", "O", "X", "X", "O"))),
    2: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "M", "M", "X", "O", "O", "O", "O", "X", "X", "X"))),
    3: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "O", "X", "X", "X", "X", "X", "O", "M", "X"))),
    4: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "O", "X", "X", "X", "X", "X", "M", "X", "X"))),
    5: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "O", "X", "X", "X", "X", "X", "M", "X", "X"))),
    6: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "O", "X", "X", "X", "X", "X", "M", "X", "X"))),
    7: dict(zip(TABLE_2_ITEMS,
                ("M", "M", "X", "O", "X", "X", "X", "X", "X", "M", "X", "X"))),
}

#: §5.2.4's Encoding Rule carries its own exception to Table 2 and is the only item that does:
#: "For the message types where this data item is mandatory, it shall be sent, EXCEPT in case of
#: failure of all sources of time stamping." So an absent time of day is a STATED absence on
#: every message type, and it lands in `attributes.unavailable_fields` rather than refusing.
TIME_ITEM = "I034/030"

#: §5.2.8's TYP table, all twenty-one values, each with the document's own wording. Four of them
#: — 17 to 20 — state their own accumulation window ("per sector"), which is why the window is
#: parked PER COUNTER and never once for the item: the Definition's "counted between two North
#: crossings" is explicitly qualified "unless otherwise stated in the TYP definition below".
COUNTER_TYP_TEXT: dict[int, str] = {
    0: "No detection (number of misses)",
    1: "Single PSR target reports",
    2: "Single SSR target reports (Non-Mode S)",
    3: "SSR+PSR target reports (Non-Mode S)",
    4: "Single All-Call target reports (Mode S)",
    5: "Single Roll-Call target reports (Mode S)",
    6: "All-Call + PSR (Mode S) target reports",
    7: "Roll-Call + PSR (Mode S) target reports",
    8: "Filter for Weather data",
    9: "Filter for Jamming Strobe",
    10: "Filter for PSR data",
    11: "Filter for SSR/Mode S data",
    12: "Filter for SSR/Mode S+PSR data",
    13: "Filter for Enhanced Surveillance data",
    14: "Filter for PSR+Enhanced Surveillance",
    15: "Filter for PSR+Enhanced Surveillance + SSR/Mode S data not in Area of Prime Interest",
    16: "Filter for PSR+Enhanced Surveillance + all SSR/Mode S data",
    17: "Re-Interrogations (per sector)",
    18: "BDS Swap and wrong DF replies (per sector)",
    19: "Mode A/C FRUIT (per sector)",
    20: "Mode S FRUIT (per sector)",
}

#: The four TYPs that state their own window. Read off the wording above rather than kept as a
#: second list a human would have to hold in agreement with it.
PER_SECTOR_TYPS = frozenset(t for t, text in COUNTER_TYP_TEXT.items() if "(per sector)" in text)

#: §5.2.11's TYP table. `0` is spelled "invalid value" by the item itself, so a zero goes to
#: `attributes.unresolved_raw` and never reads as "no filter".
DATA_FILTER_TEXT: dict[int, str] = {
    1: "Filter for Weather data",
    2: "Filter for Jamming Strobe",
    3: "Filter for PSR data",
    4: "Filter for SSR/Mode S data",
    5: "Filter for SSR/Mode S + PSR data",
    6: "Enhanced Surveillance data",
    7: "Filter for PSR+Enhanced Surveillance data",
    8: "Filter for PSR+Enhanced Surveillance + SSR/Mode S data not in Area of Prime Interest",
    9: "Filter for PSR+Enhanced Surveillance + all SSR/Mode S data",
}

#: §5.2.11's own words for the value it excludes.
DATA_FILTER_INVALID = "invalid value"

#: The SAME two bits, spelled THREE different ways by three subfields of one item. §5.2.6's PSR
#: subfield calls `11` "Diversity mode ; Channel A and B selected", its SSR subfield calls it
#: "Invalid combination", and its MDS subfield calls it "Illegal combination". Recorded rather
#: than harmonised, and parked under three separate keys, because a merged key would state that
#: the three sensors mean the same thing by one encoding and the document says they do not.
CH_AB_TEXT: dict[str, dict[int, str]] = {
    "psr": {0: "No channel selected", 1: "Channel A only selected",
            2: "Channel B only selected", 3: "Diversity mode ; Channel A and B selected"},
    "ssr": {0: "No channel selected", 1: "Channel A only selected",
            2: "Channel B only selected", 3: "Invalid combination"},
    "mds": {0: "No channel selected", 1: "Channel A only selected",
            2: "Channel B only selected", 3: "Illegal combination"},
}

#: §5.2.7's reduction ladder, identical in all four of its subfields. Parked as the integer AND
#: the step's own wording, because "3" alone is a number and the document's NOTE says the mapping
#: from a step to its actual measure "is not subject to standardisation" — so the integer is the
#: whole of what is transferable and the wording is what makes it readable.
REDUCTION_STEP_TEXT: dict[int, str] = {
    0: "No reduction active", 1: "Reduction step 1 active", 2: "Reduction step 2 active",
    3: "Reduction step 3 active", 4: "Reduction step 4 active", 5: "Reduction step 5 active",
    6: "Reduction step 6 active", 7: "Reduction step 7 active",
}

STC_TEXT: dict[int, str] = {0: "STC Map-1", 1: "STC Map-2", 2: "STC Map-3", 3: "STC Map-4"}


# ==================================================================== the item decoders
#
# Every decoder takes exactly the octets its length rule measured and returns a dict of RAW
# fields plus every spare bit as sent. Every encoder is its inverse and writes those spare bits
# back unchanged — §4.4 "Unused Bits in Data Items" is what makes that a rule rather than a
# preference, and `build_block` proves the pair round-trips on every fixture.


def _bits(value: int, high: int, low: int) -> int:
    """Bits `high`..`low` of `value`, numbered as the document numbers them (1 = LSB)."""
    return (value >> (low - 1)) & ((1 << (high - low + 1)) - 1)


def _decode_010(block: bytes) -> dict:
    return {"sac": block[0], "sic": block[1]}


def _encode_010(item: dict) -> bytes:
    return bytes([item["sac"], item["sic"]])


def _decode_000(block: bytes) -> dict:
    return {"message_type": block[0]}


def _encode_000(item: dict) -> bytes:
    return bytes([item["message_type"]])


def _decode_030(block: bytes) -> dict:
    return {"time_of_day_raw": codec.read_unsigned(block, 0, 3)}


def _encode_030(item: dict) -> bytes:
    return codec.write_unsigned(item["time_of_day_raw"], 3)


def _decode_020(block: bytes) -> dict:
    return {"sector_raw": block[0]}


def _encode_020(item: dict) -> bytes:
    return bytes([item["sector_raw"]])


def _decode_041(block: bytes) -> dict:
    return {"rotation_raw": codec.read_unsigned(block, 0, 2)}


def _encode_041(item: dict) -> bytes:
    return codec.write_unsigned(item["rotation_raw"], 2)


def _decode_090(block: bytes) -> dict:
    return {"range_error_raw": block[0], "azimuth_error_raw": block[1]}


def _encode_090(item: dict) -> bytes:
    return bytes([item["range_error_raw"], item["azimuth_error_raw"]])


def _decode_100(block: bytes) -> dict:
    return {
        "rho_start_raw": codec.read_unsigned(block, 0, 2),
        "rho_end_raw": codec.read_unsigned(block, 2, 2),
        "theta_start_raw": codec.read_unsigned(block, 4, 2),
        "theta_end_raw": codec.read_unsigned(block, 6, 2),
    }


def _encode_100(item: dict) -> bytes:
    return b"".join(codec.write_unsigned(item[key], 2) for key in
                    ("rho_start_raw", "rho_end_raw", "theta_start_raw", "theta_end_raw"))


def _decode_110(block: bytes) -> dict:
    return {"typ": block[0]}


def _encode_110(item: dict) -> bytes:
    return bytes([item["typ"]])


def _decode_120(block: bytes) -> dict:
    return {
        "height_raw": codec.read_unsigned(block, 0, 2),
        "latitude_raw": codec.read_unsigned(block, 2, 3),
        "longitude_raw": codec.read_unsigned(block, 5, 3),
    }


def _encode_120(item: dict) -> bytes:
    return (codec.write_unsigned(item["height_raw"], 2)
            + codec.write_unsigned(item["latitude_raw"], 3)
            + codec.write_unsigned(item["longitude_raw"], 3))


def _decode_070(block: bytes) -> dict:
    """§5.2.8: a one-octet REP then REP two-octet counters, each 5-bit TYP + 11-bit COUNTER.

    An ORDERED LIST with duplicates preserved, the `I048/030` rule reached for the same reason:
    order is data, the document does not say the TYPs are unique, and egress is byte-exact only
    if the counters go back out as they came in.
    """
    rep = block[0]
    counters = []
    for index in range(rep):
        word = codec.read_unsigned(block, 1 + 2 * index, 2)
        counters.append({"typ": _bits(word, 16, 12), "counter": _bits(word, 11, 1)})
    return {"rep": rep, "counters": counters}


def _encode_070(item: dict) -> bytes:
    out = bytearray([item["rep"]])
    for entry in item["counters"]:
        out += codec.write_unsigned((entry["typ"] << 11) | entry["counter"], 2)
    return bytes(out)


def _decode_050(block: bytes) -> dict:
    primary = block[0]
    parsed: dict[str, Any] = {"primary": _primary(primary)}
    at = 1
    if primary & 0x80:
        octet = block[at]
        parsed["com"] = {
            "nogo": _bits(octet, 8, 8), "rdpc": _bits(octet, 7, 7), "rdpr": _bits(octet, 6, 6),
            "ovl_rdp": _bits(octet, 5, 5), "ovl_xmt": _bits(octet, 4, 4),
            "msc": _bits(octet, 3, 3), "tsv": _bits(octet, 2, 2),
            "spare_bit_1": _bits(octet, 1, 1),
        }
        at += 1
    for key, present in (("psr", 0x10), ("ssr", 0x08)):
        if primary & present:
            octet = block[at]
            parsed[key] = {
                "ant": _bits(octet, 8, 8), "ch_ab": _bits(octet, 7, 6),
                "ovl": _bits(octet, 5, 5), "msc": _bits(octet, 4, 4),
                "spare_bits_3_1": _bits(octet, 3, 1),
            }
            at += 1
    if primary & 0x04:
        word = codec.read_unsigned(block, at, 2)
        parsed["mds"] = {
            "ant": _bits(word, 16, 16), "ch_ab": _bits(word, 15, 14),
            "ovl_sur": _bits(word, 13, 13), "msc": _bits(word, 12, 12),
            "scf": _bits(word, 11, 11), "dlf": _bits(word, 10, 10),
            "ovl_scf": _bits(word, 9, 9), "ovl_dlf": _bits(word, 8, 8),
            "spare_bits_7_1": _bits(word, 7, 1),
        }
        at += 2
    return parsed


def _encode_050(item: dict) -> bytes:
    out = bytearray([_primary_raw(item["primary"])])
    com = item.get("com")
    if com is not None:
        out.append((com["nogo"] << 7) | (com["rdpc"] << 6) | (com["rdpr"] << 5)
                   | (com["ovl_rdp"] << 4) | (com["ovl_xmt"] << 3) | (com["msc"] << 2)
                   | (com["tsv"] << 1) | com["spare_bit_1"])
    for key in ("psr", "ssr"):
        sub = item.get(key)
        if sub is not None:
            out.append((sub["ant"] << 7) | (sub["ch_ab"] << 5) | (sub["ovl"] << 4)
                       | (sub["msc"] << 3) | sub["spare_bits_3_1"])
    mds = item.get("mds")
    if mds is not None:
        out += codec.write_unsigned(
            (mds["ant"] << 15) | (mds["ch_ab"] << 13) | (mds["ovl_sur"] << 12)
            | (mds["msc"] << 11) | (mds["scf"] << 10) | (mds["dlf"] << 9)
            | (mds["ovl_scf"] << 8) | (mds["ovl_dlf"] << 7) | mds["spare_bits_7_1"], 2)
    return bytes(out)


def _decode_060(block: bytes) -> dict:
    primary = block[0]
    parsed: dict[str, Any] = {"primary": _primary(primary)}
    at = 1
    if primary & 0x80:
        octet = block[at]
        parsed["com"] = {
            "spare_bit_8": _bits(octet, 8, 8), "red_rdp": _bits(octet, 7, 5),
            "red_xmt": _bits(octet, 4, 2), "spare_bit_1": _bits(octet, 1, 1),
        }
        at += 1
    if primary & 0x10:
        octet = block[at]
        parsed["psr"] = {
            "pol": _bits(octet, 8, 8), "red_rad": _bits(octet, 7, 5),
            "stc": _bits(octet, 4, 3), "spare_bits_2_1": _bits(octet, 2, 1),
        }
        at += 1
    if primary & 0x08:
        octet = block[at]
        parsed["ssr"] = {"red_rad": _bits(octet, 8, 6), "spare_bits_5_1": _bits(octet, 5, 1)}
        at += 1
    if primary & 0x04:
        octet = block[at]
        parsed["mds"] = {"red_rad": _bits(octet, 8, 6), "clu": _bits(octet, 5, 5),
                         "spare_bits_4_1": _bits(octet, 4, 1)}
        at += 1
    return parsed


def _encode_060(item: dict) -> bytes:
    out = bytearray([_primary_raw(item["primary"])])
    com = item.get("com")
    if com is not None:
        out.append((com["spare_bit_8"] << 7) | (com["red_rdp"] << 4)
                   | (com["red_xmt"] << 1) | com["spare_bit_1"])
    psr = item.get("psr")
    if psr is not None:
        out.append((psr["pol"] << 7) | (psr["red_rad"] << 4) | (psr["stc"] << 2)
                   | psr["spare_bits_2_1"])
    ssr = item.get("ssr")
    if ssr is not None:
        out.append((ssr["red_rad"] << 5) | ssr["spare_bits_5_1"])
    mds = item.get("mds")
    if mds is not None:
        out.append((mds["red_rad"] << 5) | (mds["clu"] << 4) | mds["spare_bits_4_1"])
    return bytes(out)


def _primary(octet: int) -> dict:
    """The primary subfield of I034/050 or I034/060 — identical in both (§5.2.6, §5.2.7).

    The three SPARE presence bits are parked as sent even though a set one is refused by the
    length rule: a decoder that dropped them would make the round trip depend on their being
    zero, and §4.4 only says unused bits are unused.
    """
    return {
        "com": _bits(octet, 8, 8), "spare_bit_7": _bits(octet, 7, 7),
        "spare_bit_6": _bits(octet, 6, 6), "psr": _bits(octet, 5, 5),
        "ssr": _bits(octet, 4, 4), "mds": _bits(octet, 3, 3),
        "spare_bit_2": _bits(octet, 2, 2), "fx": _bits(octet, 1, 1),
    }


def _primary_raw(primary: dict) -> int:
    return ((primary["com"] << 7) | (primary["spare_bit_7"] << 6) | (primary["spare_bit_6"] << 5)
            | (primary["psr"] << 4) | (primary["ssr"] << 3) | (primary["mds"] << 2)
            | (primary["spare_bit_2"] << 1) | primary["fx"])


def _decode_explicit(block: bytes) -> dict:
    """RE and SP: a one-octet length INCLUDING itself, then opaque contents."""
    return {"length": block[0], "contents": block[1:].hex()}


def _encode_explicit(item: dict) -> bytes:
    return bytes([item["length"]]) + bytes.fromhex(item["contents"])


# ========================================================================= the UAP
#
# §5.3 Table 3. The fourth column gives each item's length; `1+`, `(1+2*N)` and `1+1+` are the
# notations it uses and its own legend explains ONLY `1+` — ambiguity 11 — so the lengths below
# come from the §5.2 item descriptions and, for RE and SP, from the one place this document does
# not describe at all. See `_len_explicit`.


def _len_fixed(width: int):
    def rule(data: bytes, offset: int) -> int:
        return width
    return rule


def _len_070(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("I034/070's REP octet is past the end of the block", data, offset)
    rep = data[offset]
    if rep == 0:
        raise _refuse(
            "I034/070 states REP = 0. §5.2.8's Format is 'a one-octet Field Repetition "
            "Indicator (REP) followed by AT LEAST ONE message counter of two-octet length', so "
            "a zero-length repetition is excluded by the item's own words — and an item whose "
            "presence bit is set and whose content is empty is not a counter set, it is a "
            "record whose FSPEC and body disagree", data, offset)
    return 1 + 2 * rep


def _len_compound(item: str, mds_octets: int, locus: str):
    """The one-octet extensible primary of I034/050 and I034/060, and its two refusals.

    Both refusals are `asterix_cat048.py`'s I048/120 disposition reached again, and both are the
    same kind of fault: a bit that announces something the document does not define.

    **FX.** §5.2.6 and §5.2.7 both document bit-1 as "Extension of Primary Subfield into next
    octet" and both define exactly seven subfields, all inside the first octet. So a second
    primary octet has no subfields behind it: there is nothing to decode, it cannot be skipped,
    and guessing a length would desynchronise every following item in the record.

    **A set SPARE presence bit.** Bits 7, 6 and 2 are Subfields #2, #3 and #7, and all three are
    spelled "Spare Subfield". A set one claims a secondary subfield that does not exist, and the
    same three sentences apply.
    """
    def rule(data: bytes, offset: int) -> int:
        if offset >= len(data):
            raise _refuse(f"{item}'s primary subfield is past the end of the block", data,
                          offset)
        primary = data[offset]
        if primary & codec.FX:
            raise _refuse(
                f"{item}'s primary subfield sets its FX bit, but {locus} documents it as "
                "'Extension of Primary Subfield into next octet' and defines only seven "
                "subfields, all within the first octet — so a second primary octet has no "
                "subfields behind it. There is nothing to decode, so it cannot be skipped, and "
                "guessing a length would desynchronise every following item", data, offset)
        if primary & 0x62:
            raise _refuse(
                f"{item}'s primary subfield sets a bit in 7, 6 or 2, which {locus} documents as "
                "Subfields #2, #3 and #7, 'Spare Subfield' — presence bits for secondary "
                "subfields that do not exist. There is nothing to decode, so it cannot be "
                "skipped, and guessing a length would desynchronise every following item",
                data, offset)
        return (1 + (1 if primary & 0x80 else 0) + (1 if primary & 0x10 else 0)
                + (1 if primary & 0x08 else 0) + (mds_octets if primary & 0x04 else 0))
    return rule


def _len_explicit(data: bytes, offset: int) -> int:
    """The RE and SP length octet — and this document defines neither field.

    **The convention is inherited and the inheritance is named**, because it is the one mechanic
    in this adapter the pinned text does not supply. Table 3 gives both fields the notation
    `1+1+` and the UAP's own legend explains only `1+`; there is no §5.2 entry for either; and
    ASTERIX Part 1, which does define them, **is not pinned in this repository** — the finding
    `cat048_codec.py` records for the FSPEC. What is used instead is the shipped sibling:
    `asterix_cat048.py` reads both fields as a one-octet length counting itself, and one
    convention across the two ASTERIX categories in this tree is worth more than two. The
    contents are never decoded either way, so the exposure is a length and not a meaning.
    """
    if offset >= len(data):
        raise _refuse("an explicit-length item's length octet is past the end of the block",
                      data, offset)
    stated = data[offset]
    if stated < 1:
        raise _refuse(
            "an explicit-length item states a length of 0, but the length octet counts itself "
            "so the minimum is 1", data, offset)
    return stated


#: (FRN, item, §5.2 name, Table 3 name, length rule, decoder, encoder).
#:
#: The third and fourth columns disagree twice and BOTH are recorded rather than one being
#: preferred, the `asterix_cat048.py` treatment: Table 3 calls FRN 5 "Antenna Rotation Period"
#: while §5.2.5's heading calls the same item "Antenna Rotation Speed" — and the DEFINITION under
#: that heading is a period — and Table 3 calls FRN 11 "3D-Position of Data Source" where §5.2.12
#: writes "3D-Position Of Data Source." with a capital O and a trailing full stop.
UAP: tuple[tuple[int, str, str, str, Any, Any, Any], ...] = (
    (1, "I034/010", "Data Source Identifier", "Data Source Identifier",
     _len_fixed(2), _decode_010, _encode_010),
    (2, "I034/000", "Message Type", "Message Type",
     _len_fixed(1), _decode_000, _encode_000),
    (3, "I034/030", "Time of Day", "Time-of-Day",
     _len_fixed(3), _decode_030, _encode_030),
    (4, "I034/020", "Sector Number", "Sector Number",
     _len_fixed(1), _decode_020, _encode_020),
    (5, "I034/041", "Antenna Rotation Speed", "Antenna Rotation Period",
     _len_fixed(2), _decode_041, _encode_041),
    (6, "I034/050", "System Configuration and Status", "System Configuration and Status",
     _len_compound("I034/050", 2, "§5.2.6"), _decode_050, _encode_050),
    (7, "I034/060", "System Processing Mode", "System Processing Mode",
     _len_compound("I034/060", 1, "§5.2.7"), _decode_060, _encode_060),
    (8, "I034/070", "Message Count Values", "Message Count Values",
     _len_070, _decode_070, _encode_070),
    (9, "I034/100", "Generic Polar Window", "Generic Polar Window",
     _len_fixed(8), _decode_100, _encode_100),
    (10, "I034/110", "Data Filter", "Data Filter",
     _len_fixed(1), _decode_110, _encode_110),
    (11, "I034/120", "3D-Position Of Data Source.", "3D-Position of Data Source",
     _len_fixed(8), _decode_120, _encode_120),
    (12, "I034/090", "Collimation Error", "Collimation Error",
     _len_fixed(2), _decode_090, _encode_090),
    (13, "RE", "Reserved Expansion Field", "Reserved Expansion Field",
     _len_explicit, _decode_explicit, _encode_explicit),
    (14, "SP", "Special Purpose Field", "Special Purpose Field",
     _len_explicit, _decode_explicit, _encode_explicit),
)

UAP_BY_FRN = {entry[0]: entry for entry in UAP}
FRN_BY_ITEM = {entry[1]: entry[0] for entry in UAP}
ENCODERS = {entry[1]: entry[6] for entry in UAP}

#: M in every column of Table 2, so they are mandatory whatever the message type says — which
#: matters because a record whose type this edition does not define has no Table 2 column at all
#: and these two are still required of it. §5.2.1's own Encoding Rule states it for I034/000
#: outside the table: "This data item shall be present in every ASTERIX record."
ALWAYS_MANDATORY = ("I034/010", "I034/000")


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
        entry = UAP_BY_FRN.get(frn)
        if entry is None:
            raise _refuse(
                f"record {index}: FSPEC sets FRN {frn}, which the category 034 UAP does not "
                f"define — Table 3 defines {codec.MAX_FRN}. There is no item to decode, so it "
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
            "Table 2, and §5.2.1's own Encoding Rule says I034/000 'shall be present in every "
            "ASTERIX record'. ASTERIX carries no checksum at any level, so the mandatory items "
            "are part of what replaces one", data, fspec_start)

    _check_table_2(items, data, fspec_start, index)
    return {"index": index, "fspec": fspec.hex(), "items": items,
            "item_octets": item_octets}, at


def _check_table_2(items: dict, data: bytes, offset: int, index: int) -> None:
    """A missing `M` refuses, a present `X` is parked, and the asymmetry is the ruling.

    They are different faults. **A missing mandatory item is a record that cannot be read as what
    it claims to be** — a Geographical Filtering message with no `I034/110` states no filter, a
    Sector Crossing with no `I034/020` states no sector — and there is no checksum behind it to
    have caught the truncation. **An item present where Table 2 says `X` is a record that says
    MORE than its type admits**, which is a conformance fault in the encoder and not a loss:
    every octet of it is decodable, its length is stated, and refusing would discard data the
    FSPEC correctly announced. §4.4's discipline for a bit that means nothing, applied one level
    up to an item that means nothing HERE. It is parked and named in
    `attributes.table_2_disposition`, never dropped and never treated as an error.

    `I034/030` is excluded from the mandatory half by its own Encoding Rule, which is the only
    item-level text in the category that overrides the table — see TIME_ITEM.

    A message type outside 001..007 has no column, so neither half runs; that record's only
    requirement is `ALWAYS_MANDATORY`, which has already been checked.
    """
    message_type = items["I034/000"]["message_type"]
    column = TABLE_2.get(message_type)
    if column is None:
        return
    missing = [item for item, rule in column.items()
               if rule == "M" and item != TIME_ITEM and item not in items]
    if missing:
        raise _refuse(
            f"record {index}: I034/000 is {message_type:03d} ({MESSAGE_TYPE_TEXT[message_type]}) "
            f"and Table 2 makes {', '.join(missing)} mandatory for that message type. Every "
            "item's own Encoding Rule in this category reads 'See table in I034/000', so the "
            "table IS the encoding rule and a missing M is a record that cannot be read as what "
            "it claims to be. I034/030 is the one exception and is not in this list — §5.2.4 "
            "permits its absence 'in case of failure of all sources of time stamping'",
            data, offset)


def parse_block(data: bytes) -> dict:
    """One data block into the parsed form. Every refusal quotes the offending octets."""
    if len(data) < BLOCK_HEADER_OCTETS:
        raise Cat034ParseError(
            f"a CAT034 data block is at least {BLOCK_HEADER_OCTETS} octets (CAT + LEN); "
            f"got {len(data)}: {data.hex()}"
        )
    category = data[0]
    if category != CATEGORY:
        raise _refuse(
            f"CAT octet is {category} (0x{category:02X}), not {CATEGORY}. This adapter speaks "
            "one category, and a block from another decoded against the category 034 UAP "
            "yields a plausible wrong radar status rather than an error", data, 0)
    stated = codec.read_unsigned(data, 1, 2)
    if stated != len(data):
        raise _refuse(
            f"LEN says {stated} octets and the buffer holds {len(data)}. §4.6.2 makes LEN 'a "
            "two-octet field indicating the total length in octets of the Data Block, including "
            "the CAT and LEN fields', so reading to the end of the buffer instead would "
            "translate whatever followed the block as if it were part of it", data, 1)

    records: list[dict] = []
    at = BLOCK_HEADER_OCTETS
    while at < len(data):
        record, at = _parse_record(data, at, index=len(records))
        records.append(record)
    if not records:
        raise Cat034ParseError(
            f"the block states LEN = {stated} and holds no records. An empty block is not a "
            "payload that legitimately carries nothing: §4.6.2's layout has at least one FSPEC "
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

    Every item is re-encoded from its parsed fields and then **checked against the octets that
    were parked on ingest**. That check is the point: it makes byte-exactness a proven property
    of the decoder/encoder pair rather than a trivial consequence of copying the input back out,
    and it is what would catch a spare bit the decoder read and the encoder forgot.
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
                raise Cat034ParseError(
                    f"re-encoding {item} produced {emitted.hex()} and the octets parked on "
                    f"ingest were {parked}. The round trip is only byte-exact if every bit the "
                    "decoder read is a bit the encoder writes back, spare bits included — "
                    "§4.4 addresses unused bits and does not require them to be zero, so a "
                    "conforming encoder may set them to anything"
                )
            body += emitted
    return bytes([CATEGORY]) + codec.write_unsigned(len(body) + BLOCK_HEADER_OCTETS, 2) + body


# ============================================================================ the time


def _resolve_time_of_day(seconds: float, received_at: _dt.datetime) -> tuple[_dt.datetime, str]:
    """A time of day plus the receipt date, resolved to the nearest candidate instant.

    §5.2.4 gives "a number of 1/128 s elapsed since last midnight" and NOTE 1 says "The time of
    day value is reset to zero each day at midnight", so the candidates are that time of day on
    the receipt date, the day before and the day after; the nearest to the receipt instant wins.
    Same rule as `asterix_cat021.py` and `asterix_cat048.py`, reached a third time.
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
            "reason": ("the record carries no I034/030. §5.2.4's Encoding Rule permits exactly "
                       "this — 'For the message types where this data item is mandatory, it "
                       "shall be sent, except in case of failure of all sources of time "
                       "stamping' — so this is a STATED absence and not a defect, and it is "
                       "stated for the M columns as well as for the O ones"),
            "date_from": "the injected clock",
            "time_of_day_from": "the injected clock; the record stated no time of day",
        }
    raw = tod["time_of_day_raw"]
    seconds = codec.from_raw("tod", raw)
    if seconds >= codec.SECONDS_PER_DAY:
        raise Cat034ParseError(
            f"I034/030 states {raw} units of 1/128 s = {seconds:.7f} s since midnight, and a "
            f"day is {codec.SECONDS_PER_DAY} s. Twenty-four bits at 1/128 s reach "
            "131071.9921875 s, so the field can express counts no time of day can mean. "
            "Refusing rather than taking it modulo a day — a modulo would move this record by "
            "hours and leave every other check passing. "
            "THE BASIS IS NOT A STATED RANGE, and the difference from the sibling category is "
            "recorded rather than smoothed over: CAT048 §5.2.17 prints a normative structure "
            "block, 'Acceptable Range of values: 0<= Time-of-Day<=24 hrs', and refuses one LSB "
            "PAST 86400 s while ACCEPTING 86400 s itself on that inclusive inequality. CAT034 "
            "§5.2.4 prints no range at all, so the bound here comes from the Definition ('a "
            "number of 1/128 s elapsed since last midnight') and NOTE 1 ('The time of day value "
            "is reset to zero each day at midnight'), which together make 86400 s itself "
            "unreachable. Same width, same LSB, different authority, and a boundary that "
            "therefore differs by one value. FORMAT_COVERAGE.md ambiguity 9"
        )
    instant, note = _resolve_time_of_day(seconds, received_at)
    return instant, {
        "item": "I034/030",
        "time_of_day_s": seconds,
        "time_of_day_raw": raw,
        "lsb_seconds": codec.bounds("tod")[2],
        "date_from": note,
    }


# ======================================================================== the position


def _station_position(items: dict) -> tuple[Position | None, dict]:
    """`Entity.position` from I034/120, and the basis that keeps gap 24 open in the object.

    No geodesy runs here and none is imported: §5.2.12 already states WGS-84 latitude, longitude
    and height, so the work is three scalings. That is the whole difference from the sibling
    adapter, and it is why this one takes no `sensor_position` argument.
    """
    item = items.get("I034/120")
    if item is None:
        return None, {
            "item": None,
            "reason": ("the record carries no I034/120. Table 2 makes it O for a North Marker "
                       "message and X for every other type, so its absence is ordinary — and an "
                       "absent Position is the honest statement, never a Position holding "
                       "zeros, which is a real point in the Gulf of Guinea"),
        }
    lat = codec.from_raw("latitude", item["latitude_raw"])
    lon = codec.from_raw("longitude", item["longitude_raw"])
    alt = codec.from_raw("height", item["height_raw"])
    low, high, lsb = codec.bounds("latitude")
    if not low <= lat <= high:
        raise Cat034ParseError(
            f"I034/120 states a latitude of {lat!r} degrees, and §5.2.12 states 'Range: -90<= "
            f"latitude<= 90 degrees'. Twenty-four bits at {lsb!r} degrees reach ±180, so the "
            "field can express latitudes the item's own range excludes. Refusing rather than "
            "clamping — a clamped station is a station somewhere real, and every downstream "
            "check would pass"
        )
    basis = {
        "item": "I034/120",
        "definition": "3D-Position of Data Source in WGS 84 Co-ordinates",
        "latitude_raw": item["latitude_raw"],
        "longitude_raw": item["longitude_raw"],
        "height_raw": item["height_raw"],
        "lsb_degrees": lsb,
        "height_datum": ("metres above the WGS 84 reference ellipsoid, per §5.2.12's own words "
                         "'expressed in meters above WGS 84 reference ellipsoid' — an "
                         "ELLIPSOIDAL height, which is what Position.alt_m is (metres HAE) and "
                         "is NOT the mean-sea-level datum asterix_cat048.py's I048/110 uses"),
        "handed_to": None,
        "gap_24": (
            "NOT CLOSED, and this key exists so that nobody meeting both sections concludes it "
            "was. Gap 24 records that the geodesy asterix_cat048.py needs is absent from the "
            "PINNED CAT048 DOCUMENT, and what a CAT034 record contains does not change what a "
            "CAT048 document contains. This Position belongs to the station object that carries "
            "it and is handed to no other adapter: reading I034/120 out of a CAT034 record to "
            "resolve a CAT048 target's range and azimuth is cross-payload state, which is the "
            "fusion refusal every adapter here has made. A CALLER holding both adapters' output "
            "may do it, visibly, and that is a caller's decision rather than a translator's"),
    }
    return Position(
        lat=lat, lon=lon, alt_m=alt,
        # MANUAL. A surveyed station location is none of GNSS, INERTIAL or ESTIMATED, and the
        # row set records this as the least-wrong of four rather than as a fit.
        position_source=PositionSource.MANUAL,
        # None. §5.2.12's "accuracy of at least 2.3844 metres" is the QUANTISATION STEP of the
        # encoding, not a measurement uncertainty; it is parked instead.
        accuracy_m=None,
    ), basis


# ======================================================================== the adapter


class AsterixCat034Adapter(Adapter):
    """CAT034 data blocks in, CDM out; CAT034-origin Entities back out to a data block."""

    name = "cat034"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: EMPTY, and that is a claim rather than an oversight — the claim `asterix_cat021.py` and
    #: `asterix_cat048.py` both make, for the same two reasons.
    #:
    #: A declared transform is an EXEMPTION from the never-drop check, and this adapter needs
    #: none: every wire value is parked verbatim as well as converted — the octets of every item
    #: at `attributes.cat034_items`, the raw integers beside every decoded figure, and the whole
    #: decoded item tree at `attributes.source_extras`. So `lossless.unrepresented()` runs at
    #: full strength over every fixture with nothing excused.
    #:
    #: And structurally it could not be used even if it were wanted: TRANSFORMS matches dotted
    #: paths, and this adapter's parsed form has an ARRAY of records at its root, so any path a
    #: declaration could name is either per-record-index or the whole subtree.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed RECORD this adapter re-emits under a name of its own. Short on
    #: purpose: the decoded values are parked wholesale and the canonical fields are additions on
    #: top, so consuming a mapped field would DELETE the evidence rather than move it.
    CONSUMED = ("index", "fspec", "item_octets", "record_count")

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One data block -> [Entity, Event] per record, in block order.

        Several records in one block are several SERVICE MESSAGES, not a station's history. They
        may name several stations, and two records of one station are two statements about it at
        two instants rather than one accumulated state — assembling that state is exactly the
        accumulation this adapter refuses, and the CDM makes it expressible for a consumer
        rather than performing it here.
        """
        parsed = self._as_parsed(raw)
        records = parsed.get("records")
        if not isinstance(records, list) or not records:
            raise Cat034ParseError(
                "CAT034 payload holds no records — refusing to translate; top-level keys: "
                f"{sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
            )
        block = parsed.get("block") or {}
        received_at = self.now()
        source = self.source_ref()

        objects: list[CDMBase] = []
        for record in records:
            entity, event = self._translate(record, block, received_at, source)
            objects.extend((entity, event))
        return objects

    def _as_parsed(self, raw: bytes | dict) -> dict:
        if isinstance(raw, (bytes, bytearray)):
            return parse_block(bytes(raw))
        if isinstance(raw, dict):
            return raw
        raise Cat034ParseError(
            f"a CAT034 payload is a data block (bytes) or its parsed twin (dict), "
            f"got {type(raw).__name__}"
        )

    def _translate(self, record: dict, block: dict, received_at: _dt.datetime,
                   source: Any) -> tuple[Entity, Event]:
        items = record["items"]
        unavailable: list[str] = []
        unresolved: dict[str, Any] = {}

        observed_at, time_basis = _observed_at(items, received_at)
        if time_basis["item"] is None:
            unavailable.append("I034/030 (the record states no time of day)")

        station = items["I034/010"]
        external_id = f"{station['sac']:02X}{station['sic']:02X}"
        source_ids = [SourceId(system=STATION_SYSTEM, external_id=external_id)]
        entity_id = ids.derive(STATION_SYSTEM, external_id, kind="entity")

        position, position_basis = _station_position(items)
        message_type = items["I034/000"]["message_type"]
        event_type, severity, severity_basis = self._classify(message_type, unresolved)

        attributes = self._attributes(record, block, items, position_basis, external_id,
                                      unavailable, unresolved)
        entity = Entity(
            source=source,
            source_ids=source_ids,
            entity_id=entity_id,
            # SENSOR. The one enum value in the CDM that names what a radar station is, and this
            # is the first adapter here whose primary object takes it.
            entity_type=EntityType.SENSOR,
            # UNKNOWN, always, and here it is not even a decision: a monoradar service message
            # states the station's configuration and never its allegiance.
            affiliation=Affiliation.UNKNOWN,
            symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                   synthetic=self._synthetic),
            position=position,
            # None, always. A station does not move, and the one bearing this category carries is
            # the ANTENNA's — putting I034/020 in `course_deg` would state that the radar head is
            # travelling on that heading.
            kinematics=None,
            attributes=attributes,
            valid_from=observed_at,
            # None on EVERY record. I034/041 is a rotation PERIOD and a consumer holding target
            # reports could make a staleness horizon of it; deriving an expiry here would still
            # be the fusion refusal, because the horizon is about reports this adapter never sees.
            valid_to=None,
            # Every quality statement CAT034 carries is a switch position, a reduction step or a
            # per-revolution tally. None of them is a 0..1 assessment of the station's identity.
            confidence=None,
        )
        event = Event(
            source=source,
            source_ids=source_ids,
            event_id=ids.derive(
                STATION_SYSTEM,
                f"{external_id}|{times.render(observed_at)}|{record['index']}", kind="event"),
            event_type=event_type,
            severity=severity,
            related_entities=[entity.entity_id],
            # None, ALWAYS. The only geometry in the category is I034/100's polar window and it
            # is never turned into one — see `_payload`'s `geometry_basis`.
            geometry=None,
            payload=self._payload(record, block, items, time_basis, severity_basis,
                                  message_type, unresolved),
            observed_at=observed_at,
            received_at=received_at,
        )
        return entity, event

    # ------------------------------------------------------------------ classification

    def _classify(self, message_type: int,
                  unresolved: dict[str, Any]) -> tuple[EventType, Severity, dict]:
        """§5.2.1 NOTE 3's seven types onto the CDM's vocabulary, and the eighth case.

        The collapse is 7 -> 2 on `event_type` and 7 -> 2 on `severity`, and it is recoverable
        only because the raw value AND its name are parked in `Event.payload`.
        """
        if message_type in EVENT_TYPE_BY_MESSAGE_TYPE:
            jamming = message_type in JAMMING_TYPES
            return EVENT_TYPE_BY_MESSAGE_TYPE[message_type], \
                SEVERITY_BY_MESSAGE_TYPE[message_type], {
                    "message_type": message_type,
                    "name": MESSAGE_TYPE_TEXT[message_type],
                    "basis": (
                        "ALERT/WARNING. A jamming strobe reports that something is interfering "
                        "with the sensor, which is neither routine (INFO) nor an emergency "
                        "(CRITICAL)" if jamming else
                        "STATUS_CHANGE/INFO. A North marker, a sector crossing, a filter "
                        "activation and a solar storm report are all the station stating what "
                        "it is doing, which is a status change and not a detection"),
                    "gnss_interference_declined": (
                        "EventType.GNSS_INTERFERENCE is NEVER set by this adapter, on any "
                        "message type. It is paired with GnssInterferencePayload, whose fields "
                        "— frequency_band, interference_type, signal_strength_dbm — exist for "
                        "the PNTMAP adapter, and a radar jamming strobe is not a GNSS event. "
                        "Reusing the shape because it is the only interference vocabulary in "
                        "the model would put radar jamming into the field a consumer filters on "
                        "to find GNSS threats, which is a wrong answer that reads as a right "
                        "one. FORMAT_COVERAGE.md gap 29"),
                }
        unresolved["I034/000 Message Type"] = {
            "raw": message_type,
            "reason": (
                f"Edition 1.29 standardises message types 001 to 007 (§5.2.1 NOTE 3) and this "
                f"record states {message_type:03d}. NOTE 2 says 'All Message Type values are "
                "reserved for common standard use', so this is NOT a private extension point — "
                "it is a value this edition does not define, and it lands here rather than in "
                "source_extras. The record is translated and not refused: an undefined type is "
                "not a malformed record"),
        }
        return EventType.STATUS_CHANGE, Severity.ADVISORY, {
            "message_type": message_type,
            "name": None,
            "basis": (
                "STATUS_CHANGE/ADVISORY, and ADVISORY is a ruling rather than a default. The "
                "type is undefined in the pinned edition, so severity cannot be read off it: "
                "INFO would say the message is understood and ordinary, WARNING would invent an "
                "alarm out of an unknown, and both are claims this record does not support. "
                "ADVISORY is the CDM's own middle value and the only one that leaves the record "
                "VISIBLE to a consumer filtering on severity while claiming nothing about what "
                "it means. The type value is in attributes.unresolved_raw, which is where the "
                "reader has to go"),
            "edition_note": (
                "Message types 006 and 007 are Edition 1.29's own addition — its change record "
                "reads 'Data Item I034/000: new message types 6&7' — so an adapter written "
                "against Edition 1.28 would classify both of them HERE instead of as ALERTs. "
                "That is what makes the pair an edition marker rather than two table entries"),
        }

    # ------------------------------------------------------------------ the two bags

    def _attributes(self, record: dict, block: dict, items: dict, position_basis: dict,
                    external_id: str, unavailable: list[str],
                    unresolved: dict[str, Any]) -> dict:
        attributes: dict[str, Any] = {}
        station = items["I034/010"]

        attributes["cat034_block"] = dict(block)
        attributes["cat034_fspec"] = record["fspec"]
        attributes["cat034_items"] = dict(record.get("item_octets") or {})
        attributes["data_source"] = {
            "sac": station["sac"], "sic": station["sic"], "external_id": external_id,
            "basis": (
                "I034/010, 'Identification of the radar station from which the data are "
                "received' (§5.2.2), M in every column of Table 2. A SourceId here and parked "
                "at attributes.data_source in asterix_cat048.py — the same two octets of the "
                "same standard, filed two different ways, and the difference is the whole "
                "reason both rows exist: there the SAC/SIC identifies the SENSOR and the object "
                "is a target, so filing a station under the object's identifiers is how a fused "
                "picture ends up with an entity per receiver; here the station IS the object "
                "and the pair is its own identifier"),
            "note": ("The up-to-date list of SACs is published on the EUROCONTROL Web Site "
                     "(http://www.eurocontrol.int/asterix)"),
        }
        attributes["identity_basis"] = (
            f"uuid5 over ({STATION_SYSTEM}, {external_id!r}). The system name is NOT this "
            "adapter's own: a SAC/SIC is allocated across the whole ASTERIX family from one "
            "list, so filing it under a category name would say that one station seen through "
            "Part 2b is a different station from the same pair seen through any other part. "
            "Stable across every record from the station, which is what entity_id promises — "
            "and a pure function of the pair rather than a join")
        attributes["entity_type_basis"] = (
            "SENSOR, from the category rather than from any item. Every record in Part 2b "
            "describes the radar station (§4.1: 'radar service messages used to signal status "
            "information of the radar station to the user systems'), so there is nothing to "
            "read: the object's type is a property of the format")
        attributes["affiliation_basis"] = (
            "UNKNOWN, always, and here it is not even a decision. A monoradar service message "
            "states the station's configuration and status and never its allegiance, and this "
            "repository does not infer one from a SAC")
        attributes["symbol_basis"] = (
            "derived from the affiliation through symbology.sidc_from_affiliation, so every "
            "CAT034 station is an UNKNOWN glyph. CAT034 carries no symbology of any kind")
        attributes["integrity_basis"] = (
            "CAT034 defines NO checksum at any level — neither §4.6.2 nor §4.7 nor any §5.2 "
            "item specifies a CRC, checksum or parity field at block, record or item level. "
            "What passed is the structural gate: LEN matched the buffer, the records tiled it "
            "exactly, every FSPEC bit named a defined FRN, every compound item's presence bits "
            "named a subfield that exists, no FX led nowhere, and the items Table 2 makes "
            "mandatory for this record's own message type were present. This is weaker than a "
            "CRC and the difference is named rather than smoothed over: a single bit flipped "
            "inside a fixed-length field satisfies every check above and reaches the CDM as a "
            "station status")
        attributes["position_basis"] = position_basis
        if position_basis.get("item"):
            attributes["position_quantisation_m"] = {
                "quoted": codec.WGS84_QUANTISATION_NOTE,
                "basis": ("PARKED, and deliberately NOT written to Position.accuracy_m. "
                          "180/2^23 degrees is the QUANTISATION STEP of the encoding — the "
                          "finest difference the field can express — and reporting it as an "
                          "accuracy would claim the station knows where it is to 2.4 m when "
                          "the document says only that it cannot say so more finely. accuracy_m "
                          "stays None, which means unknown accuracy and never perfect accuracy"),
            }
        attributes["table_2_disposition"] = self._table_2_disposition(items)
        self._park_configuration(items, attributes)
        self._park_opaque(items, attributes)
        attributes["unavailable_fields"] = sorted(unavailable)
        attributes["unresolved_raw"] = unresolved
        attributes["source_extras"] = lossless.residual(record, self.CONSUMED)
        return attributes

    def _table_2_disposition(self, items: dict) -> dict:
        """Which items this record carries that its own message type says are never present.

        Present on EVERY record, empty list and all, because "no item is out of place" and "this
        adapter did not look" are different facts and only one of them is worth reading.
        """
        message_type = items["I034/000"]["message_type"]
        column = TABLE_2.get(message_type)
        if column is None:
            return {
                "message_type": message_type,
                "column": None,
                "items_present_where_the_table_says_X": None,
                "basis": ("Table 2 has no column for this message type, so no M/O/X rule "
                          "applies to any item in this record beyond the two that are M in "
                          "every column"),
            }
        return {
            "message_type": message_type,
            "column": dict(column),
            "items_present_where_the_table_says_X": sorted(
                item for item in items if column.get(item) == "X"),
            "basis": ("PARKED, never dropped and never an error. Table 2's X means 'never "
                      "present' for that message type, so an item under an X is a conformance "
                      "fault in the ENCODER — and every octet of it is still decodable, its "
                      "length is still stated, and refusing would discard data the FSPEC "
                      "correctly announced. §4.4's discipline for a bit that means nothing, "
                      "applied one level up to an item that means nothing here. A missing M is "
                      "the opposite case and IS refused, in _check_table_2"),
        }

    def _park_configuration(self, items: dict, attributes: dict) -> None:
        """I034/050 and I034/060 — every bit parked, none canonical, and the reason is uniform.

        These are a radar's internal switch positions and its overload-reduction steps, and the
        CDM has no vocabulary for a sensor's channel selection. Widening the model in passing to
        take four presence bits and eleven flags is how a canonical model acquires fields that
        mean nearly the same thing, so nothing here becomes one.
        """
        config = items.get("I034/050")
        if config is not None:
            parked: dict[str, Any] = {"primary": dict(config["primary"])}
            com = config.get("com")
            if com is not None:
                parked["com"] = {
                    **com,
                    "nogo_text": ("Operational use of System is inhibited, i.e. the data shall "
                                  "be discarded by an operational SDPS" if com["nogo"]
                                  else "System is released for operational use"),
                    "nogo_basis": (
                        "THE OPERATIONALLY LOUDEST BIT IN THE CATEGORY, and it is parked rather "
                        "than raised into severity. It governs what a consumer does with the "
                        "station's TARGET REPORTS, and this adapter emits none of those — "
                        "raising an alert here would be this translator judging data it has "
                        "never seen"),
                    "rdpc_text": "RDPC-2 selected" if com["rdpc"] else "RDPC-1 selected",
                    "rdpc_basis": (
                        "This is what FORMAT_COVERAGE.md's CAT048 settlement 2 names as missing "
                        "for I048/020's RDP bit, and it stays here. The two facts meet in a "
                        "consumer, not in an adapter"),
                    "rdpr_text": "Reset of RDPC" if com["rdpr"] else "Default situation",
                    "tsv_text": "invalid" if com["tsv"] else "valid",
                }
            for key in ("psr", "ssr"):
                sub = config.get(key)
                if sub is not None:
                    parked[key] = {**sub, "ch_ab_text": CH_AB_TEXT[key][sub["ch_ab"]]}
            mds = config.get("mds")
            if mds is not None:
                parked["mds"] = {**mds, "ch_ab_text": CH_AB_TEXT["mds"][mds["ch_ab"]]}
            parked["ch_ab_basis"] = (
                "ONE ENCODING, THREE WORDINGS, THREE KEYS. §5.2.6 spells `11` 'Diversity mode ; "
                "Channel A and B selected' in the PSR subfield, 'Invalid combination' in the "
                "SSR subfield and 'Illegal combination' in the MDS subfield. Same bit "
                "positions, different meaning per sensor — so the three are parked separately "
                "and never merged, because a merged key would state that the document means one "
                "thing by the encoding and it does not")
            attributes["system_configuration_and_status"] = parked

        mode = items.get("I034/060")
        if mode is not None:
            parked = {"primary": dict(mode["primary"])}
            com = mode.get("com")
            if com is not None:
                parked["com"] = {**com,
                                 "red_rdp_text": REDUCTION_STEP_TEXT[com["red_rdp"]],
                                 "red_xmt_text": REDUCTION_STEP_TEXT[com["red_xmt"]]}
            psr = mode.get("psr")
            if psr is not None:
                parked["psr"] = {**psr,
                                 "pol_text": ("Circular polarization" if psr["pol"]
                                              else "Linear polarization"),
                                 "red_rad_text": REDUCTION_STEP_TEXT[psr["red_rad"]],
                                 "stc_text": STC_TEXT[psr["stc"]]}
            for key in ("ssr", "mds"):
                sub = mode.get(key)
                if sub is not None:
                    parked[key] = {**sub, "red_rad_text": REDUCTION_STEP_TEXT[sub["red_rad"]]}
                    if key == "mds":
                        parked[key]["clu_text"] = ("Not autonomous" if sub["clu"]
                                                   else "Autonomous")
            parked["basis"] = (
                "System Processing Mode is a DIFFERENT ITEM from System Configuration and "
                "Status and the two never merge: §5.2.6 is what the station IS and §5.2.7 is "
                "what it DID 'during the last antenna revolution'. The reduction steps are "
                "parked as integers 0-7 with the step's own wording, and the integer is the "
                "whole of what transfers — §5.2.7's NOTE says the mapping between a step and "
                "its actual data-reduction measure 'is not subject to standardisation'")
            attributes["system_processing_mode"] = parked

    def _park_opaque(self, items: dict, attributes: dict) -> None:
        expansion = items.get("RE")
        if expansion is not None:
            attributes["reserved_expansion_field"] = {
                **expansion,
                "basis": (
                    "PARKED VERBATIM, OCTET FOR OCTET, RESTORED UNCHANGED ON EGRESS, NEVER "
                    "DECODED — the asterix_cat048.py disposition with a procedural reason one "
                    "step stronger. There, an appendix that defines the field exists and was "
                    "simply not acquired. Here THIS DOCUMENT DEFINES NO PART OF IT AND LISTS NO "
                    "APPENDIX THAT DOES: FRN 13 has no §5.2 entry at all, and the only trace of "
                    "the slot in the whole edition is the change record line for Edition 1.21, "
                    "'Reserved Expansion Indicator added in UAP'. So the contents were always "
                    "elsewhere and this edition does not say where"),
            }
        special = items.get("SP")
        if special is not None:
            attributes["special_purpose_field"] = {
                **special,
                "basis": (
                    "opaque by construction. Parked verbatim as hex and NEVER WRITTEN TO on "
                    "egress — a Special Purpose Field's contents are settled by bilateral "
                    "agreement between one sender and one receiver, so a byte invented here is "
                    "a byte some deployment already means something by. No §5.2 description "
                    "exists for it in this document"),
            }

    def _payload(self, record: dict, block: dict, items: dict, time_basis: dict,
                 severity_basis: dict, message_type: int,
                 unresolved: dict[str, Any]) -> dict:
        payload: dict[str, Any] = {
            "observed_at_basis": time_basis,
            "severity_basis": severity_basis,
            "message_type": {
                "raw": message_type,
                "name": MESSAGE_TYPE_TEXT.get(message_type),
                "basis": ("the raw value AND its name, parked, because the collapse onto "
                          "event_type is 7 -> 2 and must stay recoverable — and because egress "
                          "re-emits FROM HERE rather than re-deriving a type from an EventType "
                          "that four types share"),
            },
            "record_index": record["index"],
            "record_count": record.get("record_count", block.get("record_count")),
        }
        sector = items.get("I034/020")
        if sector is not None:
            payload["sector_number"] = {
                "raw": sector["sector_raw"],
                "degrees": codec.from_raw("sector", sector["sector_raw"]),
                "lsb_degrees": codec.bounds("sector")[2],
                "basis": ("§5.2.3, 'Eight most significant bits of the antenna azimuth defining "
                          "a particular azimuth sector'. AN ANTENNA BEARING, NOT A TARGET "
                          "BEARING and not the station's own course — putting it in "
                          "Kinematics.course_deg would state that the radar head is travelling "
                          "on that heading"),
            }
        rotation = items.get("I034/041")
        if rotation is not None:
            payload["antenna_rotation"] = {
                "raw": rotation["rotation_raw"],
                "period_s": codec.from_raw("rotation_period", rotation["rotation_raw"]),
                "lsb_seconds": codec.bounds("rotation_period")[2],
                "definition": ("Antenna rotation period as measured between two consecutive "
                               "North crossings or as averaged during a period of time"),
                "basis": ("§5.2.5 is HEADED 'Antenna Rotation Speed' and DEFINES a period, and "
                          "both are recorded rather than one being preferred. Parked as "
                          "seconds. This is the scan period FORMAT_COVERAGE.md's CAT048 "
                          "settlement 2 names as lost, and it stays on this object: it does not "
                          "set Entity.valid_to here and it is handed to no other adapter"),
            }
        collimation = items.get("I034/090")
        if collimation is not None:
            payload["collimation_error"] = {
                "range_raw": collimation["range_error_raw"],
                "range_nm": codec.from_raw("range_error", collimation["range_error_raw"]),
                "azimuth_raw": collimation["azimuth_error_raw"],
                "azimuth_deg": codec.from_raw("azimuth_error",
                                              collimation["azimuth_error_raw"]),
                "definition": ("Averaged difference in range and in azimuth for the primary "
                               "target position with respect to the SSR target position as "
                               "calculated by the radar station"),
                "basis": ("§5.2.9, both fields two's complement per its NOTE. A PSR-versus-SSR "
                          "calibration residual for the station — NOT a position accuracy for "
                          "anything, and never Position.accuracy_m"),
            }
        window = items.get("I034/100")
        if window is not None:
            payload["generic_polar_window"] = {
                "rho_start_raw": window["rho_start_raw"],
                "rho_end_raw": window["rho_end_raw"],
                "theta_start_raw": window["theta_start_raw"],
                "theta_end_raw": window["theta_end_raw"],
                "rho_start_nm": codec.from_raw("rho", window["rho_start_raw"]),
                "rho_end_nm": codec.from_raw("rho", window["rho_end_raw"]),
                "theta_start_deg": codec.from_raw("theta", window["theta_start_raw"]),
                "theta_end_deg": codec.from_raw("theta", window["theta_end_raw"]),
                "geometry_basis": (
                    "NO Event.geometry IS DERIVED, AND TABLE 2 IS THE REASON RATHER THAN "
                    "EFFORT. A polar window is range and azimuth FROM THE STATION, so a WGS-84 "
                    "polygon needs the station's position — which this category does carry, in "
                    "I034/120. Table 2 makes the two items MUTUALLY EXCLUSIVE: I034/120 is O "
                    "for message type 001 and X for the other six, I034/100 is X for 001 and "
                    "002 and M or O for the other five, and there is no message type for which "
                    "both are permitted. So in a conformant record the position could only ever "
                    "come from a DIFFERENT record, which is the cross-payload state this "
                    "adapter refuses; and in a non-conformant one it would make the output "
                    "depend on the malformation. Phase 1 left this open as an adapter-behaviour "
                    "question and Phase 2 rules it CLOSED, on the document rather than on "
                    "preference. The four raw fields are here, always, and a consumer holding a "
                    "station position may do the geodesy visibly"),
            }
        counts = items.get("I034/070")
        if counts is not None:
            payload["message_counts"] = {
                "rep": counts["rep"],
                "counters": [
                    {
                        "typ": entry["typ"],
                        "text": COUNTER_TYP_TEXT.get(entry["typ"]),
                        "counter": entry["counter"],
                        "window": ("one sector" if entry["typ"] in PER_SECTOR_TYPS
                                   else "one completed antenna revolution, between two North "
                                        "crossings"),
                    }
                    for entry in counts["counters"]
                ],
                "basis": ("an ORDERED list with duplicates preserved — order is data and egress "
                          "is byte-exact only if the counters go back out as they came in. A "
                          "COUNT IS NOT A DETECTION: none of the twenty-one TYPs produces an "
                          "Event per counted item, which would invent target reports this "
                          "document does not carry"),
                "window_basis": ("PER COUNTER and never once for the item. §5.2.8's Definition "
                                 "says the values are 'collected for the last completed antenna "
                                 "revolution, counted between two North crossings UNLESS "
                                 "OTHERWISE STATED IN THE TYP DEFINITION BELOW', and four TYPs "
                                 "— 17 to 20 — do state otherwise. Parking a single window for "
                                 "the item would be wrong for four of the twenty-one"),
            }
            undefined = sorted({entry["typ"] for entry in counts["counters"]
                                if entry["typ"] not in COUNTER_TYP_TEXT})
            if undefined:
                unresolved["I034/070 counter TYP"] = {
                    "raw": undefined,
                    "reason": ("§5.2.8 defines TYP values 0 to 20 and this record carries one "
                               "the edition does not define. The counter's value is still "
                               "parked in order; what is unresolved is what it counts"),
                }
        data_filter = items.get("I034/110")
        if data_filter is not None:
            typ = data_filter["typ"]
            payload["data_filter"] = {
                "raw": typ,
                "text": DATA_FILTER_TEXT.get(typ),
                "basis": ("§5.2.11, one octet. NOTE 2: 'If I034/110 is not accompanied with "
                          "I034/100, then the Data Filter is valid throughout the total area of "
                          "coverage' — so an absent polar window is a stated scope and not a "
                          "missing field"),
            }
            if typ not in DATA_FILTER_TEXT:
                unresolved["I034/110 TYP"] = {
                    "raw": typ,
                    "reason": (
                        f"§5.2.11 spells the value 0 '{DATA_FILTER_INVALID}' in the item's own "
                        "table and defines 1 to 9. A zero therefore NEVER reads as 'no filter' "
                        "— the item says it is invalid, not that filtering is off — and a value "
                        "above 9 is one this edition does not define"),
                }
        return payload

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities that CAME FROM CAT034 back to one data block, byte-exactly.

        Everything derived — `observed_at`, the decoded degrees and seconds, the `Position` — is
        a one-way view and is **not** the source of any emitted byte. Re-encoding a latitude from
        `Position.lat` would run the scaling in both directions and hide an error in it, whereas
        re-emitting the parked integers means a conversion defect can only ever affect the CDM
        view and never the wire.
        """
        entities = [obj for obj in objects if isinstance(obj, Entity)]
        if not entities:
            raise Cat034ParseError(
                f"nothing to emit: {len(objects)} object(s) and no Entity among them. A CDM "
                "Track cannot become a CAT034 data block either, and the reason is not the "
                "arithmetic: a Track carries samples of a moving thing and every record in this "
                "category is a statement about a stationary station. There is no SAC/SIC "
                "anywhere in a Track, no FSPEC and no message type, and inventing a SAC/SIC "
                "would NAME a radar station that does not exist"
            )
        return build_block([self._record_from_entity(entity) for entity in entities])

    def _record_from_entity(self, entity: Entity) -> dict:
        parked = entity.attributes.get("source_extras") or {}
        items = parked.get("items") if isinstance(parked, dict) else None
        fspec = entity.attributes.get("cat034_fspec")
        octets = entity.attributes.get("cat034_items")
        if not items or not fspec:
            missing = [name for name, value in
                       (("source_extras.items", items), ("cat034_fspec", fspec)) if not value]
            raise Cat034ParseError(
                f"Entity {entity.entity_id} did not come from CAT034: {', '.join(missing)} "
                "is absent from its attributes. There is no SAC/SIC to write and I034/010 is M "
                "in every column of Table 2; there is no message type, and §5.2.1 says I034/000 "
                "'shall be present in every ASTERIX record'; and there is no FSPEC, so nothing "
                "states which items the record claimed to carry. The refusal names each missing "
                "input rather than inventing one"
            )
        return {"index": 0, "fspec": fspec, "items": items,
                "item_octets": dict(octets or {})}
