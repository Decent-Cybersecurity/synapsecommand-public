"""ASTERIX Category 048 — Monoradar Target Reports. Data blocks in, CDM out, and back.

INGEST  one ASTERIX **data block** — `CAT | LEN | FSPEC + items | ...` — becomes an Entity + an
        Event per record, in block order.
EGRESS  Entities that CAME FROM CAT048 become one data block, byte-exactly. Anything else is a
        refusal that names what is missing.

Implements the row set in `FORMAT_COVERAGE.md` under "ASTERIX Category 048", which was written
and reviewed as a specification BEFORE this file existed. Where the code and a row disagree the
row wins, or the row changes in the same commit; three of them changed here and each is noted at
the site.

WHAT THIS ADAPTER IS THE SENSOR-SIDE COMPLEMENT OF
--------------------------------------------------
`asterix_cat021.py` translates what a ground station emits after receiving cooperative
broadcasts. This translates what ONE RADAR emits about what IT detected, and that inverts three
of CAT021's easy problems: the position arrives as slant range and azimuth from a station whose
location the format never carries (settlement 3), there is one time item rather than seven, and
**the target may not be an object at all** — the format has codes for a reflection, a sidelobe
reply, an angel, a phantom plot, a bird and a wind turbine.

It shares no code with `asterix_cat021.py` and that is deliberate: see `cat048_codec.py`'s
docstring for the Part 1 finding that makes reuse an appearance of a common basis rather than one.

THE TWO INJECTED VALUES
-----------------------
`clock`, as every adapter has. And `sensor_position`, which is new to this family and is the
same KIND of thing: a value the caller owns, supplied once at construction, outside the payload,
visible in every golden file. I048/140 carries no date and the adapter supplies one from the
clock; I048/040 carries no site and the adapter supplies one from configuration. What stays
forbidden is the adapter OBTAINING either for itself — reading a site out of the payload, or
resolving a SAC/SIC through a lookup table it carries. That is "a station configuration it
discovered from the data", which is a different act from accepting an argument.

WITHOUT A SITE THERE IS NO POSITION, AND THAT IS THE DEFAULT
------------------------------------------------------------
`sensor_position=None` is the default, so the default behaviour is the conservative one: the
polar measurement is parked and `Entity.position` is None. With a site AND a height item the
geometry is derived, the arithmetic is declared in `attributes.position_basis`, and the raw RHO
and THETA are STILL parked — a derived Position is a one-way view and egress re-emits from the
integers, never from the float.

NO CHECKSUM, SO THE GATE IS STRUCTURAL
--------------------------------------
Neither §4.6.2 nor §4.7 nor any §5.2 item defines a CRC, checksum or parity field at block,
record or item level. So the block must satisfy LEN, the records must tile it exactly, every
FSPEC bit must name a defined FRN, every variable item must terminate inside the record, every
`FX` that leads nowhere is a refusal, and the mandatory items must be present.
`attributes.integrity_basis` records on every object that this is what passed.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any

from synapse_cdm import ids, lossless, symbology, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import cat048_codec as codec
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, Position, SourceId

#: This adapter's own system name, for `SourceRef.system`.
SYSTEM = "ASTERIX_CAT048"

#: The source id system for a 24-bit ICAO aircraft address. The SAME string `adsb.py` and
#: `asterix_cat021.py` file it under, so a CAT048 report and a CAT021 record of one airframe
#: derive the SAME `entity_id` without any of the three coordinating. That is not a join: it is
#: a pure function of the address, and it is what lets a fusion layer do the joining where the
#: join is audited. Settlement 11.
ICAO_SYSTEM = "ICAO24"

#: A report with no aircraft address states no identity at all, so the id is scoped to the
#: REPORT and says so. Step 2 of settlement 9's two-step chain. Deliberately NOT the track
#: number: a station-scoped, recycled 12-bit number keyed into `entity_id` merges two airframes
#: into one entity, which is a false statement, and gap 27 records the truncation instead.
REPORT_SYSTEM = "CAT048_REPORT"

#: One octet, and this adapter speaks exactly one category. A CAT021 or CAT062 block decoded
#: against the CAT048 UAP yields a plausible wrong aircraft rather than an error.
CATEGORY = 48

#: CAT (1) + LEN (2). LEN counts itself and the CAT octet, per §4.6.2.
BLOCK_HEADER_OCTETS = 3


class Cat048ParseError(ValueError):
    """A block this adapter refuses. Every message quotes the offending octets."""


def _refuse(message: str, data: bytes, offset: int, span: int = 8) -> Cat048ParseError:
    window = data[max(0, offset - 2):offset + span]
    return Cat048ParseError(
        f"{message} (at octet {offset} of {len(data)}; octets here: {window.hex()})"
    )


# ===================================================================== the vocabularies

#: I048/020 bits 8/6. Mandatory in every target record (§5.2.2's Encoding Rule), which is why
#: `entity_type` and `event_type` are both read from here rather than from I048/030 — whose own
#: Note 7 makes it "implementation specific … described in the ICD".
TYP_TEXT: dict[int, str] = {
    0: "No detection",
    1: "Single PSR detection",
    2: "Single SSR detection",
    3: "SSR + PSR detection",
    4: "Single ModeS All-Call",
    5: "Single ModeS Roll-Call",
    6: "ModeS All-Call + PSR",
    7: "ModeS Roll-Call +PSR",
}

#: The Mode S values. Their presence is what makes I048/220 and I048/230 gateable at all: their
#: encoding rules condition on "a record conveying data related to a Mode S target", and this is
#: the only observable statement of that in the record.
MODE_S_TYP = frozenset({4, 5, 6, 7})

#: Settlement 9. A primary return is an ECHO before it is an object — the format's own code list
#: (reflection, sidelobe, split plot, angel, bird, wind turbine) exists because it may not be one
#: — and TYP = 0 is "No detection", which is a track report with no plot behind it.
ENTITY_TYPE_BY_TYP: dict[int, EntityType] = {
    0: EntityType.UNKNOWN,
    1: EntityType.UNKNOWN,
    2: EntityType.PLATFORM,
    3: EntityType.PLATFORM,
    4: EntityType.PLATFORM,
    5: EntityType.PLATFORM,
    6: EntityType.PLATFORM,
    7: EntityType.PLATFORM,
}

#: I048/020 first extension, bits 3/2. Note the vocabulary makes THREE distinct claims and
#: "01 Friendly target" is the tempting one. Declined as an affiliation: an IFF result belongs to
#: an IFF authority, over-claiming FRIENDLY is the dangerous direction, and §5.2.2's own M4E note
#: forces this field to "00" whenever the real three-level result is in the un-pinned REF — so
#: `00` is ambiguous between "not interrogated" and "unreadable here".
FOE_FRI_TEXT: dict[int, str] = {
    0: "No Mode 4 interrogation",
    1: "Friendly target",
    2: "Unknown target",
    3: "No reply",
}

#: I048/170 bits 7/6. `11` is spelled "Invalid" by the document, so it goes to `unresolved_raw`.
RAD_TEXT: dict[int, str] = {0: "Combined Track", 1: "PSR Track", 2: "SSR/Mode S Track",
                            3: "Invalid"}

#: I048/170 bits 3/2. A four-value CATEGORY and not a rate: it never reaches
#: `Kinematics.climb_mps`, which is metres per second. CAT048 states no vertical rate anywhere.
CDM_TEXT: dict[int, str] = {0: "Maintaining", 1: "Climbing", 2: "Descending", 3: "Unknown"}

#: I048/230 bits 16/14. `0` is ambiguous between "surveillance only" and "not yet extracted" —
#: the item's own Encoding Rule says "If the datalink capability has not been extracted yet, bits
#: 16/14 shall be set to zero". Both readings are recorded; ambiguity 9.
COM_TEXT: dict[int, str] = {
    0: "No communications capability (surveillance only)",
    1: "Comm. A and Comm. B capability",
    2: "Comm. A, Comm. B and Uplink ELM",
    3: "Comm. A, Comm. B, Uplink ELM and Downlink ELM",
    4: "Level 5 Transponder capability",
}

#: I048/230 bits 13/11. Alert values 2, 3 and 4 do NOT raise severity: a Mode S flight-status
#: alert fires on a Mode 3/A code change as well as on an emergency, so it is procedural — the
#: reading CAT021 gives I021/200 `SS` = 2 and `adsb.py` gives surveillance status 2.
STAT_TEXT: dict[int, str] = {
    0: "No alert, no SPI, aircraft airborne",
    1: "No alert, no SPI, aircraft on ground",
    2: "Alert, no SPI, aircraft airborne",
    3: "Alert, no SPI, aircraft on ground",
    4: "Alert, SPI, aircraft airborne or on ground",
    5: "No alert, SPI, aircraft airborne or on ground",
    7: "Unknown",
}

#: I048/020 third extension, bits 7/4. Load-bearing for I048/260: on ACAS Xu the advisory is
#: split across /260 and /250, so either half alone is incomplete.
ACASXV_TEXT: dict[int, str] = {
    0: "Non-Extended Version",
    1: "ACAS Xa Version 1",
    2: "ACAS Xu Version 1",
}

#: §5.2.3's code table, transcribed from Edition 1.32's own text — codes 0 to 37 with no gaps,
#: including the "see Note" annotations that are part of the entries. Code 37 is 1.32's own
#: addition; code 36 carries the nested NOTE the change record flags ("the use of this code
#: should be limited to the target acquisition phase"), which is parked with it.
WARNING_ERROR_TEXT: dict[int, str] = {
    0: "Not defined; never used.",
    1: "Multipath Reply (Reflection)",
    2: "Reply due to sidelobe interrogation/reception",
    3: "Split plot",
    4: "Second time around reply",
    5: "Angel",
    6: "Slow moving target correlated with road infrastructure (terrestrial vehicle)",
    7: "Fixed PSR plot",
    8: "Slow PSR target",
    9: "Low quality PSR plot",
    10: "Phantom SSR plot",
    11: "Non-Matching Mode-3/A Code",
    12: "Mode C code / Mode S altitude code abnormal value compared to the track",
    13: "Target in Clutter Area",
    14: "Maximum Doppler Response in Zero Filter",
    15: "Transponder anomaly detected -see Note 4 below",
    16: "Duplicated or Illegal Mode S Aircraft Address",
    17: "Mode S error correction applied",
    18: "Undecodable Mode C code / Mode S altitude code",
    19: "Birds",
    20: "Flock of Birds",
    21: "Mode-1 was present in original reply",
    22: "Mode-2 was present in original reply",
    23: "Plot potentially caused by Wind Turbine",
    24: "Helicopter",
    25: "Maximum number of re-interrogations reached (surveillance information)",
    26: "Maximum number of re-interrogations reached (BDS Extractions)",
    27: "BDS Overlay Incoherence",
    28: "Potential BDS Swap Detected",
    29: "Track Update in the Zenithal Gap",
    30: "Mode S Track re-acquired",
    31: "Duplicated Mode 5 Pair NO/PIN detected",
    32: "Wrong DF reply format detected",
    33: "Transponder anomaly (MS XPD replies with Mode A/C to Mode A/C-only all-call) "
        "-see Note 5 below",
    34: "Transponder anomaly (SI capability report wrong) -see Note 5 below",
    35: "Potential IC Conflict",
    36: "IC Conflict detection possible -no conflict currently detected",
    37: "Duplicate Mode 5 PIN (refer to the Mode 5 items in the REF)",
}

#: "Values 0-63 are allocated by the AMG, values 64 to 127 are available for allocation by
#: manufacturers and shall be described in the corresponding ICD." An unassigned AMG code is a
#: FUTURE standard value; a manufacturer code is a PRIVATE one. Different facts, kept apart.
AMG_CODE_MAX = 63
MANUFACTURER_CODE_MAX = 127

#: I048/090 Note 1 and Note 2 route the two altitude failure cases into I048/030 by name. So a
#: conforming station tells us, in a third item, that its own altitudes disagree.
ALTITUDE_WE_CODES = {18: "Undecodable Mode C code / Mode S altitude code",
                     12: "Mode C code / Mode S altitude code abnormal value compared to the "
                         "track"}


# ==================================================================== the item decoders
#
# Every decoder returns a dict holding EVERY bit of its item, spare bits included, because
# §4.4's zeroing is a RECOMMENDATION ("it is recommended to set all spare bits to zero") and a
# conforming encoder may set them to anything. `_encode_*` is the exact inverse of each, and
# `from_cdm` asserts that inverse against the parked octets rather than trusting it.


def _bits(value: int, high: int, low: int) -> int:
    """Bits `high`..`low` inclusive, numbered as the document numbers them (1 = LSB)."""
    return (value >> (low - 1)) & ((1 << (high - low + 1)) - 1)


def _quality_bits(value: int, count: int) -> list[int]:
    """The per-pulse confidence bits, MSB first. `1` is a LOW quality pulse."""
    return [(value >> (count - 1 - i)) & 1 for i in range(count)]


def _quality_raw(bits: list[int]) -> int:
    raw = 0
    for bit in bits:
        raw = (raw << 1) | (bit & 1)
    return raw


def _decode_010(block: bytes) -> dict:
    return {"sac": block[0], "sic": block[1]}


def _encode_010(item: dict) -> bytes:
    return bytes([item["sac"], item["sic"]])


def _decode_020(block: bytes) -> dict:
    first = block[0]
    out: dict[str, Any] = {
        "typ": _bits(first, 8, 6),
        "typ_text": TYP_TEXT[_bits(first, 8, 6)],
        "sim": bool(_bits(first, 5, 5)),
        "rdp": _bits(first, 4, 4),
        "spi": bool(_bits(first, 3, 3)),
        "rab": bool(_bits(first, 2, 2)),
    }
    extensions: list[dict] = []
    for index, octet in enumerate(block[1:], start=1):
        if index == 1:
            ext = {
                "tst": bool(_bits(octet, 8, 8)), "err": bool(_bits(octet, 7, 7)),
                "xpp": bool(_bits(octet, 6, 6)), "me": bool(_bits(octet, 5, 5)),
                "mi": bool(_bits(octet, 4, 4)),
                "foe_fri": _bits(octet, 3, 2),
                "foe_fri_text": FOE_FRI_TEXT[_bits(octet, 3, 2)],
            }
        elif index == 2:
            ext = {
                "adsb": {"populated": bool(_bits(octet, 8, 8)),
                         "available": bool(_bits(octet, 7, 7))},
                "scn": {"populated": bool(_bits(octet, 6, 6)),
                        "available": bool(_bits(octet, 5, 5))},
                "pai": {"populated": bool(_bits(octet, 4, 4)),
                        "available": bool(_bits(octet, 3, 3))},
                "spare_bit_2": _bits(octet, 2, 2),
            }
        elif index == 3:
            ext = {
                "acasxv": {"populated": bool(_bits(octet, 8, 8)),
                           "value": _bits(octet, 7, 4),
                           "text": ACASXV_TEXT.get(_bits(octet, 7, 4))},
                "poxpr": {"populated": bool(_bits(octet, 3, 3)),
                          "supported": bool(_bits(octet, 2, 2))},
            }
        elif index == 4:
            ext = {
                "poact": {"populated": bool(_bits(octet, 8, 8)),
                          "active": bool(_bits(octet, 7, 7))},
                "dtfxpr": {"populated": bool(_bits(octet, 6, 6)),
                           "supported": bool(_bits(octet, 5, 5))},
                "dtfact": {"populated": bool(_bits(octet, 4, 4)),
                           "active": bool(_bits(octet, 3, 3))},
                "spare_bit_2": _bits(octet, 2, 2),
            }
        else:
            ext = {
                "irmxpr": {"populated": bool(_bits(octet, 8, 8)),
                           "capable": bool(_bits(octet, 7, 7))},
                "irmact": {"populated": bool(_bits(octet, 6, 6)),
                           "active": bool(_bits(octet, 5, 5))},
                "spare_bits_4_2": _bits(octet, 4, 2),
            }
        extensions.append(ext)
    out["extensions"] = extensions
    return out


def _encode_020(item: dict) -> bytes:
    exts = item.get("extensions") or []
    first = (item["typ"] << 5) | (int(item["sim"]) << 4) | (item["rdp"] << 3) \
        | (int(item["spi"]) << 2) | (int(item["rab"]) << 1)
    octets = [first | (codec.FX if exts else 0)]
    for index, ext in enumerate(exts, start=1):
        last = index == len(exts)
        if index == 1:
            octet = (int(ext["tst"]) << 7) | (int(ext["err"]) << 6) | (int(ext["xpp"]) << 5) \
                | (int(ext["me"]) << 4) | (int(ext["mi"]) << 3) | (ext["foe_fri"] << 1)
        elif index == 2:
            octet = (int(ext["adsb"]["populated"]) << 7) | (int(ext["adsb"]["available"]) << 6) \
                | (int(ext["scn"]["populated"]) << 5) | (int(ext["scn"]["available"]) << 4) \
                | (int(ext["pai"]["populated"]) << 3) | (int(ext["pai"]["available"]) << 2) \
                | (ext["spare_bit_2"] << 1)
        elif index == 3:
            octet = (int(ext["acasxv"]["populated"]) << 7) | (ext["acasxv"]["value"] << 3) \
                | (int(ext["poxpr"]["populated"]) << 2) | (int(ext["poxpr"]["supported"]) << 1)
        elif index == 4:
            octet = (int(ext["poact"]["populated"]) << 7) | (int(ext["poact"]["active"]) << 6) \
                | (int(ext["dtfxpr"]["populated"]) << 5) \
                | (int(ext["dtfxpr"]["supported"]) << 4) \
                | (int(ext["dtfact"]["populated"]) << 3) | (int(ext["dtfact"]["active"]) << 2) \
                | (ext["spare_bit_2"] << 1)
        else:
            octet = (int(ext["irmxpr"]["populated"]) << 7) | (int(ext["irmxpr"]["capable"]) << 6) \
                | (int(ext["irmact"]["populated"]) << 5) | (int(ext["irmact"]["active"]) << 4) \
                | (ext["spare_bits_4_2"] << 1)
        octets.append(octet | (0 if last else codec.FX))
    return bytes(octets)


def _decode_030(block: bytes) -> dict:
    codes = []
    for octet in block:
        code = _bits(octet, 8, 2)
        codes.append({"code": code, "text": WARNING_ERROR_TEXT.get(code)})
    return {"codes": codes}


def _encode_030(item: dict) -> bytes:
    codes = item["codes"]
    return bytes((entry["code"] << 1) | (0 if index == len(codes) - 1 else codec.FX)
                 for index, entry in enumerate(codes))


def _decode_040(block: bytes) -> dict:
    rho_raw = codec.read_unsigned(block, 0, 2)
    theta_raw = codec.read_unsigned(block, 2, 2)
    return {
        "rho_raw": rho_raw, "rho_nm": codec.from_raw("rho", rho_raw),
        "theta_raw": theta_raw, "theta_deg": codec.from_raw("theta", theta_raw),
    }


def _encode_040(item: dict) -> bytes:
    return codec.write_unsigned(item["rho_raw"], 2) + codec.write_unsigned(item["theta_raw"], 2)


def _decode_042(block: bytes) -> dict:
    x_raw = codec.read_unsigned(block, 0, 2)
    y_raw = codec.read_unsigned(block, 2, 2)
    return {
        "x_raw": x_raw, "x_nm": codec.from_raw("cartesian", x_raw),
        "y_raw": y_raw, "y_nm": codec.from_raw("cartesian", y_raw),
    }


def _encode_042(item: dict) -> bytes:
    return codec.write_unsigned(item["x_raw"], 2) + codec.write_unsigned(item["y_raw"], 2)


def _decode_mode_code_2octet(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    return {
        "v": _bits(raw, 16, 16), "g": _bits(raw, 15, 15), "l": _bits(raw, 14, 14),
        "spare_bit_13": _bits(raw, 13, 13),
        "code_raw": _bits(raw, 12, 1),
        "code_octal": codec.decode_octal(_bits(raw, 12, 1), 4),
    }


def _encode_mode_code_2octet(item: dict) -> bytes:
    raw = (item["v"] << 15) | (item["g"] << 14) | (item["l"] << 13) \
        | (item["spare_bit_13"] << 12) | item["code_raw"]
    return codec.write_unsigned(raw, 2)


def _decode_055(block: bytes) -> dict:
    raw = block[0]
    return {
        "v": _bits(raw, 8, 8), "g": _bits(raw, 7, 7), "l": _bits(raw, 6, 6),
        "code_raw": _bits(raw, 5, 1),
        # Five bits: A4 A2 A1 B2 B1, which is two octal digits with the low one truncated.
        "code_octal": codec.decode_octal(_bits(raw, 5, 1), 2),
    }


def _encode_055(item: dict) -> bytes:
    return bytes([(item["v"] << 7) | (item["g"] << 6) | (item["l"] << 5) | item["code_raw"]])


def _decode_060(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    return {"spare_bits_16_13": _bits(raw, 16, 13), "quality_bits": _quality_bits(raw, 12)}


def _encode_060(item: dict) -> bytes:
    return codec.write_unsigned((item["spare_bits_16_13"] << 12)
                                | _quality_raw(item["quality_bits"]), 2)


def _decode_065(block: bytes) -> dict:
    raw = block[0]
    return {"spare_bits_8_6": _bits(raw, 8, 6), "quality_bits": _quality_bits(raw, 5)}


def _encode_065(item: dict) -> bytes:
    return bytes([(item["spare_bits_8_6"] << 5) | _quality_raw(item["quality_bits"])])


def _decode_090(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    level_raw = _bits(raw, 14, 1)
    return {
        "v": _bits(raw, 16, 16), "g": _bits(raw, 15, 15),
        "flight_level_raw": level_raw,
        # "LSB= 1/4 FL in two's complement form" — Edition 1.32's own clarification. An
        # unsigned read puts a negative flight level at FL 4000.
        "flight_level": codec.from_raw("flight_level", level_raw),
    }


def _encode_090(item: dict) -> bytes:
    return codec.write_unsigned((item["v"] << 15) | (item["g"] << 14)
                                | item["flight_level_raw"], 2)


def _decode_100(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 4)
    return {
        "v": _bits(raw, 32, 32), "g": _bits(raw, 31, 31),
        "spare_bits_30_29": _bits(raw, 30, 29),
        # NOT Gray-decoded. The item is sent "only … when a not validated or undecodable Mode C
        # code has been received", so decoding it would manufacture the value it exists to say
        # is unavailable — and this document states no Gray table. Settlement 5.
        "mode_c_gray_raw": _bits(raw, 28, 17),
        "spare_bits_16_13": _bits(raw, 16, 13),
        "quality_bits": _quality_bits(_bits(raw, 12, 1), 12),
    }


def _encode_100(item: dict) -> bytes:
    raw = (item["v"] << 31) | (item["g"] << 30) | (item["spare_bits_30_29"] << 28) \
        | (item["mode_c_gray_raw"] << 16) | (item["spare_bits_16_13"] << 12) \
        | _quality_raw(item["quality_bits"])
    return codec.write_unsigned(raw, 4)


def _decode_110(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    height_raw = _bits(raw, 14, 1)
    return {
        "spare_bits_16_15": _bits(raw, 16, 15),
        "height_raw": height_raw,
        "height_ft": codec.from_raw("height_3d", height_raw),
    }


def _encode_110(item: dict) -> bytes:
    return codec.write_unsigned((item["spare_bits_16_15"] << 14) | item["height_raw"], 2)


def _decode_120(block: bytes) -> dict:
    primary = block[0]
    out: dict[str, Any] = {"primary": {"cal": bool(_bits(primary, 8, 8)),
                                       "rds": bool(_bits(primary, 7, 7))}}
    at = 1
    if _bits(primary, 8, 8):
        raw = codec.read_unsigned(block, at, 2)
        cal_raw = _bits(raw, 10, 1)
        out["cal"] = {
            "doubtful": bool(_bits(raw, 16, 16)),
            "spare_bits_15_11": _bits(raw, 15, 11),
            "cal_raw": cal_raw,
            "calculated_doppler_mps": codec.from_raw("doppler", cal_raw),
        }
        at += 2
    if _bits(primary, 7, 7):
        out["rds"] = {
            "rep": block[at],
            "dop_raw": codec.read_unsigned(block, at + 1, 2),
            "amb_raw": codec.read_unsigned(block, at + 3, 2),
            "frq_raw": codec.read_unsigned(block, at + 5, 2),
        }
        out["rds"]["doppler_mps"] = float(out["rds"]["dop_raw"])
        out["rds"]["ambiguity_mps"] = float(out["rds"]["amb_raw"])
        out["rds"]["frequency_mhz"] = float(out["rds"]["frq_raw"])
    return out


def _encode_120(item: dict) -> bytes:
    primary = (int(item["primary"]["cal"]) << 7) | (int(item["primary"]["rds"]) << 6)
    out = bytearray([primary])
    if item["primary"]["cal"]:
        cal = item["cal"]
        out += codec.write_unsigned(
            (int(cal["doubtful"]) << 15) | (cal["spare_bits_15_11"] << 10) | cal["cal_raw"], 2)
    if item["primary"]["rds"]:
        rds = item["rds"]
        out += bytes([rds["rep"]])
        out += codec.write_unsigned(rds["dop_raw"], 2)
        out += codec.write_unsigned(rds["amb_raw"], 2)
        out += codec.write_unsigned(rds["frq_raw"], 2)
    return bytes(out)


#: I048/130's seven subfields, in primary-subfield bit order: (flag, key, form).
SUBFIELDS_130: tuple[tuple[str, str, str], ...] = (
    ("srl", "ssr_plot_runlength_deg", "runlength"),
    ("srr", "ssr_reply_count", None),
    ("sam", "ssr_amplitude_dbm", "amplitude"),
    ("prl", "psr_plot_runlength_deg", "runlength"),
    ("pam", "psr_amplitude_dbm", "amplitude"),
    ("rpd", "range_difference_nm", "range_difference"),
    ("apd", "azimuth_difference_deg", "azimuth_difference"),
)


def _decode_130(block: bytes) -> dict:
    primary = block[0]
    present = {flag: bool(primary & (1 << (7 - index)))
               for index, (flag, _key, _form) in enumerate(SUBFIELDS_130)}
    out: dict[str, Any] = {"primary": present}
    at = 1
    for flag, key, form in SUBFIELDS_130:
        if not present[flag]:
            continue
        raw = block[at]
        out[flag] = {"raw": raw}
        out[flag][key] = float(raw) if form is None else codec.from_raw(form, raw)
        at += 1
    return out


def _encode_130(item: dict) -> bytes:
    primary = 0
    for index, (flag, _key, _form) in enumerate(SUBFIELDS_130):
        if item["primary"].get(flag):
            primary |= 1 << (7 - index)
    out = bytearray([primary])
    for flag, _key, _form in SUBFIELDS_130:
        if item["primary"].get(flag):
            out.append(item[flag]["raw"])
    return bytes(out)


def _decode_140(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 3)
    return {"time_of_day_raw": raw, "time_of_day_s": codec.from_raw("tod", raw)}


def _encode_140(item: dict) -> bytes:
    return codec.write_unsigned(item["time_of_day_raw"], 3)


def _decode_161(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    return {"spare_bits_16_13": _bits(raw, 16, 13), "track_number": _bits(raw, 12, 1)}


def _encode_161(item: dict) -> bytes:
    return codec.write_unsigned((item["spare_bits_16_13"] << 12) | item["track_number"], 2)


def _decode_170(block: bytes) -> dict:
    first = block[0]
    out: dict[str, Any] = {
        "cnf": _bits(first, 8, 8),
        "rad": _bits(first, 7, 6), "rad_text": RAD_TEXT[_bits(first, 7, 6)],
        "dou": _bits(first, 5, 5),
        "mah": _bits(first, 4, 4),
        "cdm": _bits(first, 3, 2), "cdm_text": CDM_TEXT[_bits(first, 3, 2)],
    }
    if len(block) > 1:
        octet = block[1]
        out["extent"] = {
            "tre": _bits(octet, 8, 8), "gho": _bits(octet, 7, 7),
            "sup": _bits(octet, 6, 6), "tcc": _bits(octet, 5, 5),
            "spare_bits_4_2": _bits(octet, 4, 2),
        }
    return out


def _encode_170(item: dict) -> bytes:
    extent = item.get("extent")
    first = (item["cnf"] << 7) | (item["rad"] << 5) | (item["dou"] << 4) \
        | (item["mah"] << 3) | (item["cdm"] << 1)
    octets = [first | (codec.FX if extent else 0)]
    if extent:
        octets.append((extent["tre"] << 7) | (extent["gho"] << 6) | (extent["sup"] << 5)
                      | (extent["tcc"] << 4) | (extent["spare_bits_4_2"] << 1))
    return bytes(octets)


def _decode_200(block: bytes) -> dict:
    speed_raw = codec.read_unsigned(block, 0, 2)
    heading_raw = codec.read_unsigned(block, 2, 2)
    return {
        "groundspeed_raw": speed_raw,
        "groundspeed_nm_s": codec.from_raw("groundspeed", speed_raw),
        "heading_raw": heading_raw,
        "heading_deg": codec.from_raw("heading", heading_raw),
    }


def _encode_200(item: dict) -> bytes:
    return codec.write_unsigned(item["groundspeed_raw"], 2) \
        + codec.write_unsigned(item["heading_raw"], 2)


def _decode_210(block: bytes) -> dict:
    return {
        "sigma_x_raw": block[0], "sigma_x_nm": codec.from_raw("sigma_position", block[0]),
        "sigma_y_raw": block[1], "sigma_y_nm": codec.from_raw("sigma_position", block[1]),
        "sigma_v_raw": block[2], "sigma_v_nm_s": codec.from_raw("sigma_speed", block[2]),
        "sigma_h_raw": block[3], "sigma_h_deg": codec.from_raw("sigma_heading", block[3]),
    }


def _encode_210(item: dict) -> bytes:
    return bytes([item["sigma_x_raw"], item["sigma_y_raw"],
                  item["sigma_v_raw"], item["sigma_h_raw"]])


def _decode_220(block: bytes) -> dict:
    return {"address_raw": codec.read_unsigned(block, 0, 3),
            "address": block.hex().upper()}


def _encode_220(item: dict) -> bytes:
    return codec.write_unsigned(item["address_raw"], 3)


def _decode_230(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 2)
    com = _bits(raw, 16, 14)
    stat = _bits(raw, 13, 11)
    return {
        "com": com, "com_text": COM_TEXT.get(com),
        "stat": stat, "stat_text": STAT_TEXT.get(stat),
        "si": _bits(raw, 10, 10), "spare_bit_9": _bits(raw, 9, 9),
        "mssc": _bits(raw, 8, 8), "arc": _bits(raw, 7, 7), "aic": _bits(raw, 6, 6),
        "b1a": _bits(raw, 5, 5), "b1b": _bits(raw, 4, 1),
    }


def _encode_230(item: dict) -> bytes:
    raw = (item["com"] << 13) | (item["stat"] << 10) | (item["si"] << 9) \
        | (item["spare_bit_9"] << 8) | (item["mssc"] << 7) | (item["arc"] << 6) \
        | (item["aic"] << 5) | (item["b1a"] << 4) | item["b1b"]
    return codec.write_unsigned(raw, 2)


def _decode_240(block: bytes) -> dict:
    raw = codec.read_unsigned(block, 0, 6)
    return {"identification_raw": raw, "identification": codec.decode_six_bit(raw, 8)}


def _encode_240(item: dict) -> bytes:
    return codec.write_unsigned(item["identification_raw"], 6)


def _decode_250(block: bytes) -> dict:
    rep = block[0]
    registers = []
    for index in range(rep):
        at = 1 + index * 8
        data = block[at:at + 7]
        code = block[at + 7]
        bds1, bds2 = _bits(code, 8, 5), _bits(code, 4, 1)
        registers.append({
            # 56 bits of hex, NOT decoded: the registers are a separate set with their own
            # document ([Ref. 2] ED-73F/DO-181F), which nothing here pins. Settlement 10.
            "data": data.hex(),
            "bds1": bds1, "bds2": bds2,
            # Note 3's trap: `0,0` is NOT register 0,0. An adapter treating it as an address
            # would mislabel every broadcast-extracted register.
            "extraction": "Comm-B broadcast, register unidentified" if (bds1 == 0 and bds2 == 0)
            else f"GICB register {bds1},{bds2}",
        })
    return {"rep": rep, "registers": registers}


def _encode_250(item: dict) -> bytes:
    out = bytearray([item["rep"]])
    for register in item["registers"]:
        out += bytes.fromhex(register["data"])
        out.append((register["bds1"] << 4) | register["bds2"])
    return bytes(out)


def _decode_260(block: bytes) -> dict:
    # NOT decoded. The only decode authority the item cites is "ICAO Draft SARPs for ACAS" —
    # a draft, unnamed by edition, absent from §2.2's reference list — and there is no field
    # breakdown of the 56 bits anywhere in the document. Settlement 10.
    return {"acas_ra": block.hex()}


def _encode_260(item: dict) -> bytes:
    return bytes.fromhex(item["acas_ra"])


def _decode_explicit(block: bytes) -> dict:
    """SP and RE: a one-octet length INCLUDING itself, then opaque contents.

    Neither field has a §5.2 description anywhere in this document — they appear only as FRN 27
    and FRN 28 of Table 2, with a length notation `1+1+` the UAP's own legend does not define —
    so the form is Part 1's. Carried verbatim so a record containing one round-trips without
    being interpreted.
    """
    return {"length": block[0], "contents": block[1:].hex()}


def _encode_explicit(item: dict) -> bytes:
    return bytes([item["length"]]) + bytes.fromhex(item["contents"])


# ========================================================================= the UAP
#
# §5.3.1 Table 2. The fourth column is the item's own §5.2 structure, not Table 2's notation —
# `1+1+` and `1+8*n` are undefined by the UAP's legend (ambiguity 7), so lengths come from the
# item descriptions. Names are §5.2's headings, with Table 2's own name recorded where the two
# disagree (ambiguity 8, most consequentially FRN 10: Table 2 still says "Mode S MB Data" three
# editions after Edition 1.29 renamed the item "BDS Register Data").


def _len_fixed(width: int):
    def rule(data: bytes, offset: int) -> int:
        return width
    return rule


def _len_variable(item: str, max_octets: int | None, locus: str):
    """An FX-extending item, with the number of octets its own §5.2 section DEFINES.

    `max_octets` is load-bearing rather than defensive. §5.2.19's first extent documents its FX
    as "= 1 Extension into second extent" and then defines no second extent; §5.2.2's fifth
    extension documents its FX as "= 1 Extension into next extension" and then defines no sixth.
    Both are `FX` bits that lead somewhere that does not exist, and both must refuse for the
    reason a Not-Used FRN refuses: there is nothing to decode, so it cannot be skipped, and
    guessing a length would desynchronise every following item.

    Without this cap the refusal still happens — the FX chain eventually runs off the end of the
    record — but it says the wrong thing, and a refusal that misidentifies its own cause is a
    refusal nobody can act on. That is what the `track_status_second_extent` fixture caught.

    `None` means genuinely unbounded: I048/030's extents each carry a NEW CODE rather than more
    fields of one value ("Extension into first extent (next W/E condition value)"), so a series
    of any length is exactly what Note 1 says the item is for.
    """
    def rule(data: bytes, offset: int) -> int:
        length = 1
        while True:
            if offset + length - 1 >= len(data):
                raise _refuse(
                    f"{item}: the FX chain runs past the end of the block", data, offset)
            if not data[offset + length - 1] & codec.FX:
                return length
            if max_octets is not None and length >= max_octets:
                raise _refuse(
                    f"{item}: octet {length} sets its FX bit, but {locus} defines only "
                    f"{max_octets} octet(s) for this item — the bit leads to a part of the "
                    "item that does not exist. There is nothing to decode, so it cannot be "
                    "skipped, and guessing a length would desynchronise every following item "
                    "in the record", data, offset)
            length += 1
    return rule


def _len_explicit(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("an explicit-length item's length octet is past the end of the block",
                      data, offset)
    stated = data[offset]
    if stated < 1:
        raise _refuse(
            "an explicit-length item states a length of 0, but the length octet counts itself "
            "so the minimum is 1", data, offset)
    return stated


def _len_250(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("I048/250's REP octet is past the end of the block", data, offset)
    return 1 + 8 * data[offset]


def _len_120(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("I048/120's primary subfield is past the end of the block", data, offset)
    primary = data[offset]
    if _bits(primary, 6, 2):
        raise _refuse(
            "I048/120's primary subfield sets a bit in 6/2, which §5.2.15 documents as "
            "'(Spare) Subfields #3/7: Spare' — presence bits for subfields that do not exist. "
            "There is nothing to decode, so it cannot be skipped, and guessing a length would "
            "desynchronise every following item", data, offset)
    if primary & codec.FX:
        raise _refuse(
            "I048/120's primary subfield sets its FX bit, but §5.2.15 defines no second "
            "primary octet and no subfields beyond #2", data, offset)
    return 1 + (2 if _bits(primary, 8, 8) else 0) + (7 if _bits(primary, 7, 7) else 0)


def _len_130(data: bytes, offset: int) -> int:
    if offset >= len(data):
        raise _refuse("I048/130's primary subfield is past the end of the block", data, offset)
    primary = data[offset]
    if primary & codec.FX:
        raise _refuse(
            "I048/130's primary subfield sets its FX bit — §5.2.16 documents it as "
            "'Extension of Primary Subfield into next octet', and defines only seven "
            "subfields, so a second primary octet has no subfields behind it", data, offset)
    return 1 + bin(primary >> 1).count("1")


#: (FRN, item, §5.2 name, Table 2 name, length rule, decoder, encoder).
UAP: tuple[tuple[int, str, str, str, Any, Any, Any], ...] = (
    (1, "I048/010", "Data Source Identifier", "Data Source Identifier",
     _len_fixed(2), _decode_010, _encode_010),
    (2, "I048/140", "Time of Day", "Time-of-Day",
     _len_fixed(3), _decode_140, _encode_140),
    (3, "I048/020", "Type and Properties of the Target Report and Target Capabilities",
     "Type and Properties of the Target Report and Target Capabilities",
     _len_variable("I048/020", 6, "§5.2.2 (a first part plus five extensions)"),
     _decode_020, _encode_020),
    (4, "I048/040", "Measured Position in Polar Co-ordinates",
     "Measured Position in Slant Polar Coordinates", _len_fixed(4), _decode_040, _encode_040),
    (5, "I048/070", "Mode-3/A Code in Octal Representation",
     "Mode-3/A Code in Octal Representation",
     _len_fixed(2), _decode_mode_code_2octet, _encode_mode_code_2octet),
    (6, "I048/090", "Flight Level in Binary Representation",
     "Flight Level in Binary Representation", _len_fixed(2), _decode_090, _encode_090),
    (7, "I048/130", "Radar Plot Characteristics", "Radar Plot Characteristics",
     _len_130, _decode_130, _encode_130),
    (8, "I048/220", "Aircraft Address", "Aircraft Address",
     _len_fixed(3), _decode_220, _encode_220),
    (9, "I048/240", "Aircraft Identification", "Aircraft Identification",
     _len_fixed(6), _decode_240, _encode_240),
    (10, "I048/250", "BDS Register Data", "Mode S MB Data",
     _len_250, _decode_250, _encode_250),
    (11, "I048/161", "Track Number", "Track Number", _len_fixed(2), _decode_161, _encode_161),
    (12, "I048/042", "Calculated Position in Cartesian Co-ordinates",
     "Calculated Position in Cartesian Coordinates", _len_fixed(4), _decode_042, _encode_042),
    (13, "I048/200", "Calculated Track Velocity in Polar Co-ordinates",
     "Calculated Track Velocity in Polar Representation",
     _len_fixed(4), _decode_200, _encode_200),
    (14, "I048/170", "Track Status", "Track Status",
     _len_variable("I048/170", 2, "§5.2.19 (a first part plus ONE extent)"),
     _decode_170, _encode_170),
    (15, "I048/210", "Track Quality", "Track Quality", _len_fixed(4), _decode_210, _encode_210),
    (16, "I048/030", "Warning/Error Conditions and Target Classification",
     "Warning/Error Conditions/Target Classification",
     _len_variable("I048/030", None, "§5.2.3"), _decode_030, _encode_030),
    (17, "I048/080", "Mode-3/A Code Confidence Indicator",
     "Mode-3/A Code Confidence Indicator", _len_fixed(2), _decode_060, _encode_060),
    (18, "I048/100", "Mode-C Code and Code Confidence Indicator",
     "Mode-C Code and Confidence Indicator", _len_fixed(4), _decode_100, _encode_100),
    (19, "I048/110", "Height Measured by a 3D Radar", "Height Measured by 3D Radar",
     _len_fixed(2), _decode_110, _encode_110),
    (20, "I048/120", "Radial Doppler Speed", "Radial Doppler Speed",
     _len_120, _decode_120, _encode_120),
    (21, "I048/230", "Communications/ACAS Capability and Flight Status",
     "Communications / ACAS Capability and Flight Status",
     _len_fixed(2), _decode_230, _encode_230),
    (22, "I048/260", "ACAS Resolution Advisory Report", "ACAS Resolution Advisory Report",
     _len_fixed(7), _decode_260, _encode_260),
    (23, "I048/055", "Mode-1 Code in Octal Representation",
     "Mode-1 Code in Octal Representation", _len_fixed(1), _decode_055, _encode_055),
    (24, "I048/050", "Mode-2 Code in Octal Representation",
     "Mode-2 Code in Octal Representation",
     _len_fixed(2), _decode_mode_code_2octet, _encode_mode_code_2octet),
    (25, "I048/065", "Mode-1 Code Confidence Indicator", "Mode-1 Code Confidence Indicator",
     _len_fixed(1), _decode_065, _encode_065),
    (26, "I048/060", "Mode-2 Code Confidence Indicator", "Mode-2 Code Confidence Indicator",
     _len_fixed(2), _decode_060, _encode_060),
    (27, "SP", "Special Purpose Field", "Special Purpose Field",
     _len_explicit, _decode_explicit, _encode_explicit),
    (28, "RE", "Reserved Expansion Field", "Reserved Expansion Field",
     _len_explicit, _decode_explicit, _encode_explicit),
)

UAP_BY_FRN = {frn: entry for entry in UAP for frn in (entry[0],)}
FRN_BY_ITEM = {entry[1]: entry[0] for entry in UAP}
ENCODERS = {entry[1]: entry[6] for entry in UAP}

#: §5.2.1 "This Item shall be present in every ASTERIX record" and §5.2.2 "This Data Item shall
#: be present in every target record". I048/140 is deliberately NOT here: its Encoding Rule
#: permits omission "in case of failure of all sources of time-stamping", which is a stated
#: absence rather than a defect. Settlement 4.
MANDATORY_ITEMS = ("I048/010", "I048/020")


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
                f"record {index}: FSPEC sets FRN {frn}, which the category 048 UAP does not "
                f"define — Table 2 defines {codec.MAX_FRN}. There is no item to decode, so it "
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

    missing = [item for item in MANDATORY_ITEMS if item not in items]
    if missing:
        raise _refuse(
            f"record {index} is missing {', '.join(missing)}. §5.2.1 says I048/010 'shall be "
            "present in every ASTERIX record' and §5.2.2 says I048/020 'shall be present in "
            "every target record'. ASTERIX carries no checksum at any level, so the mandatory "
            "items are part of what replaces one", data, fspec_start)

    _check_mode_s_items(items, data, fspec_start, index)
    return {"index": index, "fspec": fspec.hex(), "items": items,
            "item_octets": item_octets}, at


def _is_track_end(items: dict) -> bool:
    """I048/170 First Extension bit 8. The only observable trigger for the relaxation.

    §5.2.4 Note 1 and §5.2.20's Encoding Rule call the same shape a "track cancellation
    message" while five other items call it an "End of Track Message", and the document defines
    neither term — ambiguity 2. `TRE` is what can actually be read, so it is what is used.
    """
    return bool(((items.get("I048/170") or {}).get("extent") or {}).get("tre"))


def _check_mode_s_items(items: dict, data: bytes, offset: int, index: int) -> None:
    """I048/220 and I048/230 on a Mode S record — and the Edition 1.30 relaxation.

    Only these two of the four relaxed items are gateable, and the reason is not the relaxation:
    I048/240's rule conditions on "After the first extraction of aircraft identification" and
    I048/250's on "provided BDS Register Data has been extracted in the last scan", both of
    which are facts about the STATION'S HISTORY that a stateless translator cannot observe. So
    their absence is never a refusal, whatever TRE says.
    """
    typ = items["I048/020"]["typ"]
    if typ not in MODE_S_TYP or _is_track_end(items):
        return
    for item in ("I048/220", "I048/230"):
        if item not in items:
            raise _refuse(
                f"record {index}: I048/020 TYP = {typ} ({TYP_TEXT[typ]}) says this record "
                f"conveys data related to a Mode S target, so {item}'s Encoding Rule says it "
                "'shall be present'. The Edition 1.30 relaxation applies only to an 'End of "
                "Track Message' (I048/170 First Extension bit 8), and this record does not "
                "set it", data, offset)


def parse_block(data: bytes) -> dict:
    """One data block into the parsed form. Every refusal quotes the offending octets."""
    if len(data) < BLOCK_HEADER_OCTETS:
        raise Cat048ParseError(
            f"a CAT048 data block is at least {BLOCK_HEADER_OCTETS} octets (CAT + LEN); "
            f"got {len(data)}: {data.hex()}"
        )
    category = data[0]
    if category != CATEGORY:
        raise _refuse(
            f"CAT octet is {category} (0x{category:02X}), not {CATEGORY}. This adapter speaks "
            "one category, and a block from another decoded against the category 048 UAP "
            "yields a plausible wrong aircraft rather than an error", data, 0)
    stated = codec.read_unsigned(data, 1, 2)
    if stated != len(data):
        raise _refuse(
            f"LEN says {stated} octets and the buffer holds {len(data)}. §4.6.2 makes LEN 'the "
            "total length in octets of the Data Block, including the CAT and LEN fields', so "
            "reading to the end of the buffer instead would translate whatever followed the "
            "block as if it were part of it", data, 1)

    records: list[dict] = []
    at = BLOCK_HEADER_OCTETS
    while at < len(data):
        record, at = _parse_record(data, at, index=len(records))
        records.append(record)
    if at != len(data):  # pragma: no cover - the loop condition makes this unreachable
        raise _refuse("the records do not tile LEN exactly", data, at)
    if not records:
        raise Cat048ParseError(
            f"the block states LEN = {stated} and holds no records. An empty block is not a "
            "payload that legitimately carries nothing: §4.6.2's layout has at least one "
            f"FSPEC after LEN. Octets: {data.hex()}"
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
            entry = UAP_BY_FRN[frn]
            item = entry[1]
            parsed = record["items"][item]
            emitted = ENCODERS[item](parsed)
            parked = record.get("item_octets", {}).get(item)
            if parked is not None and emitted.hex() != parked:
                raise Cat048ParseError(
                    f"re-encoding {item} produced {emitted.hex()} and the octets parked on "
                    f"ingest were {parked}. The round trip is only byte-exact if every bit the "
                    "decoder read is a bit the encoder writes back, spare bits included — "
                    "§4.4 only RECOMMENDS zeroing them, so a conforming encoder may set them "
                    "to anything"
                )
            body += emitted
    return bytes([CATEGORY]) + codec.write_unsigned(len(body) + BLOCK_HEADER_OCTETS, 2) + body


# ============================================================================ the time


def _resolve_time_of_day(seconds: float, received_at: _dt.datetime) -> tuple[_dt.datetime, str]:
    """A time of day plus the receipt date, resolved to the nearest candidate instant.

    §5.2.17 gives "a number of 1/128 s elapsed since last midnight" and Note 1 says the counter
    "is reset to 0 each day at midnight", so the candidates are that time of day on the receipt
    date, the day before and the day after; the nearest to the receipt instant wins. Same rule
    as `asterix_cat021.py`, and the fixtures echo its values on purpose.
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
    tod = items.get("I048/140")
    if tod is None:
        return received_at, {
            "item": None,
            "reason": "the record carries no I048/140. §5.2.17's Encoding Rule permits exactly "
                      "this — 'shall be present in every ASTERIX record, EXCEPT in case of "
                      "failure of all sources of time-stamping' — so this is a STATED absence "
                      "and not a defect",
            "date_from": "the injected clock",
            "time_of_day_from": "the injected clock; the record stated no time of day",
        }
    seconds = tod["time_of_day_s"]
    low, high, lsb = codec.bounds("tod")
    if seconds > high:
        raise Cat048ParseError(
            f"I048/140 states {tod['time_of_day_raw']} units of 1/128 s = {seconds:.7f} s "
            f"since midnight, which §5.2.17's own structure block excludes: 'Acceptable Range "
            f"of values: 0<= Time-of-Day<=24 hrs', i.e. {high:.0f} s inclusive. Twenty-four "
            "bits at 1/128 s reach 131071.9921875 s, so the field can express times of day "
            "the item's range does not admit. Refusing rather than taking it modulo a day — a "
            "modulo would move this contact by hours and leave every other check passing"
        )
    instant, note = _resolve_time_of_day(seconds, received_at)
    basis = {
        "item": "I048/140",
        "time_of_day_s": seconds,
        "time_of_day_raw": tod["time_of_day_raw"],
        "lsb_seconds": lsb,
        "date_from": note,
    }
    if seconds == high:
        # Ambiguity 1. §5.2.17's range is inclusive at the top and Note 1's reset makes 86400
        # unreachable; the normative structure block governs, and note prose cannot narrow a
        # stated range. One LSB past it is a refusal, which is what pins the edge.
        basis["boundary"] = (
            f"the value is exactly {high:.0f} s, the top of §5.2.17's INCLUSIVE stated range. "
            "Accepted on that inequality and resolved as 00:00:00.000 of the following day. "
            "Note 1 says the counter 'is reset to 0 each day at midnight', which makes this "
            "value unreachable — the two sentences disagree and the normative structure block "
            "governs. FORMAT_COVERAGE.md ambiguity 1, and ambiguity 14 for the cross-adapter "
            "consequence: asterix_cat021.py refuses this value on a different recorded basis"
        )
    return instant, basis


# ======================================================================== the geometry


def _height_for_slant(items: dict) -> tuple[float, dict] | tuple[None, dict]:
    """The target height in metres above mean sea level, and how it was obtained.

    Precedence from settlement 3. I048/110 first — a measured geometric height, MSL-referenced
    by its own Definition. I048/090 second, and it is an APPROXIMATION recorded as one: a
    pressure altitude standing in for a geometric height. I048/100 never: settlement 5 declines
    to decode it, and a height this row set refuses to read cannot become one it silently uses.
    """
    if "I048/110" in items:
        feet = items["I048/110"]["height_ft"]
        return feet * codec.FEET_TO_METRES, {
            "item": "I048/110",
            "datum": "mean sea level, per §5.2.14 — 'The height shall use mean sea level as "
                     "the zero reference level'",
            "height_ft": feet,
            "approximation": None,
        }
    if "I048/090" in items:
        level = items["I048/090"]["flight_level"]
        return level * 100.0 * codec.FEET_TO_METRES, {
            "item": "I048/090",
            "datum": "the 1013.25 hPa flight-level datum, NOT a geometric height",
            "flight_level": level,
            "approximation": "a PRESSURE altitude is standing in for a geometric height "
                             "because no I048/110 was present. The two differ by hundreds of "
                             "metres in ordinary weather, so the derived position inherits "
                             "that error through the slant-range correction",
        }
    return None, {"item": None, "approximation": None}


def _derive_position(items: dict, site: tuple[float, float, float] | None) -> tuple[
        Position | None, dict]:
    """`Entity.position`, or None, and the basis in either case.

    Settlement 3, and every declaration it requires is written into the basis rather than left
    implicit — because the pinned document contains NONE of this arithmetic. §4.3.2.1 gives only
    the radar-plane identities and §4.3.2.2 names the ellipsoid and defers the projection.
    """
    measured = items.get("I048/040")
    basis: dict[str, Any] = {
        "derived": False,
        "arithmetic_source": "THIS ADAPTER, not the specification. §4.3.2.1 gives only "
                             "'X = RHO * SIN(THETA); Y = RHO * COS(THETA)' and §4.3.2.2 names "
                             "the WGS-84 ellipsoid and then defers the projection to 'a "
                             "suitable projection technique … (e.g. a stereographical "
                             "projection)'. FORMAT_COVERAGE.md gap 24",
    }
    if measured is None:
        basis["reason"] = "the record carries no I048/040, so there is no measured position"
        return None, basis
    basis["rho_nm"] = measured["rho_nm"]
    basis["theta_deg"] = measured["theta_deg"]
    basis["azimuth_reference"] = ("local geographical north, per §4.3.1 — 'The reference for "
                                 "the azimuth shall be local geographical north'. A TRUE "
                                 "bearing, so no magnetic declination enters")
    if site is None:
        basis["reason"] = ("no sensor_position was injected at construction. §4.3.1 makes 'the "
                           "radar site location' the origin of the polar co-ordinate system "
                           "and no data item in Table 2 carries it, so without the caller's "
                           "value there is nothing to convert against")
        return None, basis

    extended_range = _extended_range_floor(items)
    if extended_range:
        basis["reason"] = ("I048/020's ERR bit is set and RHO is at its maximum, which §5.2.4 "
                           "NOTE 4 recommends when the un-pinned REF's ERR item carries the "
                           "real range. That makes RHO a FLOOR and not a measurement, and a "
                           "bound cannot be converted into a position")
        return None, basis

    height_m, height_basis = _height_for_slant(items)
    basis["height"] = height_basis
    if height_m is None:
        basis["reason"] = ("no usable height item. A slant range needs one: §4.3.2.2 concedes "
                           "the radar's own conversion uses 'either the measured height or an "
                           "assumed target height'. Assuming Δh = 0 is refused rather than "
                           "accepted as a small error — a target at FL350 directly overhead "
                           "has a slant range of 5.76 NM and a ground range near zero, so "
                           "treating slant as ground would paint it 10.7 km from the antenna")
        return None, basis

    site_lat, site_lon, site_alt_m = site
    delta_h = height_m - site_alt_m
    ground_m = codec.ground_range_m(measured["rho_nm"], delta_h)
    if ground_m is None:
        basis["reason"] = (
            f"the geometry is impossible: |Δh| = {abs(delta_h):.1f} m exceeds the slant range "
            f"{measured['rho_nm'] * codec.METRES_PER_NM:.1f} m, so no ground range exists. "
            "This happens in practice when a PRESSURE altitude stands in for a geometric "
            "height. NO ROW OF THE RULING DOCUMENT COVERS THIS CASE: deriving nothing and "
            "saying so is chosen over refusing the record (which would filter a translatable "
            "report) and over clamping the ground range to zero (which would put the contact "
            "at the antenna)")
        return None, basis

    lat, lon = codec.direct(site_lat, site_lon, measured["theta_deg"], ground_m)
    basis.update({
        "derived": True,
        "earth_model": codec.EARTH_MODEL,
        "earth_model_basis": ("§4.3.2.2's own ellipsoid — 'a plane tangential to the WGS-84 "
                              "Ellipsoid at the location of the radar head'"),
        "sensor_position": {"lat": site_lat, "lon": site_lon, "alt_m_msl": site_alt_m},
        "slant_treatment": ("RHO is a SLANT range (§4.3.1, 'slant polar co-ordinates'), so the "
                            "ground range is sqrt(RHO² - Δh²) and the position is the geodesic "
                            "direct solution from the site at that distance on bearing THETA"),
        "delta_h_m": delta_h,
        "ground_range_m": ground_m,
        "reason": None,
    })
    if (items.get("I048/020") or {}).get("typ") == 0:
        basis["extrapolated"] = (
            "I048/020 TYP = 0 is 'No detection', and §5.2.4 Note 1 says 'In case of no "
            "detection, the extrapolated position expressed in slant polar co-ordinates may "
            "be sent'. So the polar values this position was derived from are an "
            "EXTRAPOLATION and not a measurement")
    return Position(
        lat=lat, lon=lon,
        # `alt_m` is metres above the WGS-84 ellipsoid; I048/110 is MSL-referenced and I048/090
        # is a pressure altitude, and converting either needs a geoid model nothing here
        # carries. The height DIFFERENCE used above is a different quantity — the geoid largely
        # cancels across a sensor-to-target baseline — so using Δh and declining alt_m is one
        # consistent position rather than two.
        alt_m=None,
        # `PositionSource` offers GNSS, INERTIAL, MANUAL and ESTIMATED, and none of them names a
        # sensor measurement. ESTIMATED is the only one that is not an outright false statement
        # about a computed product of a measurement, an injected site and possibly a pressure
        # altitude — and it answers the enum's own purpose correctly, since a radar fix is not
        # GNSS and survives jamming a GNSS fix does not. The missing member is a 1.1.0
        # candidate; gap 24.
        position_source=PositionSource.ESTIMATED,
        # I048/210's per-axis σ are "within the local grid system"; collapsing them into one
        # horizontal figure is a modelling choice, and this derivation adds error nothing in
        # the record bounds. Gap 17.
        accuracy_m=None,
    ), basis


def _extended_range_floor(items: dict) -> bool:
    """ERR set with RHO at its maximum: §5.2.4 NOTE 4's floor rather than a range."""
    extensions = (items.get("I048/020") or {}).get("extensions") or []
    err = bool(extensions and extensions[0].get("err"))
    measured = items.get("I048/040")
    if not err or measured is None:
        return False
    return measured["rho_raw"] == 0xFFFF


# ======================================================================== the adapter


class AsterixCat048Adapter(Adapter):
    """CAT048 data blocks in, CDM out; CAT048-origin Entities back out to a data block."""

    name = "cat048"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: EMPTY, and that is a claim rather than an oversight — the same claim
    #: `asterix_cat021.py` makes, for the same two reasons.
    #:
    #: A declared transform is an EXEMPTION from the never-drop check, and this adapter needs
    #: none: every wire value is parked verbatim as well as converted. The octets of every item
    #: at `attributes.cat048_items`, the polar integers at
    #: `attributes.cat048_measured_position`, the raw 1/128 s count at
    #: `attributes.cat048_time`, and the whole decoded item tree at
    #: `attributes.source_extras`. So `lossless.unrepresented()` runs at full strength over
    #: every fixture with nothing excused.
    #:
    #: And structurally it could not be used even if it were wanted: TRANSFORMS matches dotted
    #: paths, and this adapter's parsed form has an ARRAY of records at its root, so any path a
    #: declaration could name is either per-record-index or the whole subtree.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed RECORD this adapter re-emits under a name of its own. Short on
    #: purpose: the decoded values are parked wholesale and the canonical fields are additions
    #: on top, so consuming a mapped field would DELETE the evidence rather than move it.
    CONSUMED = ("index", "fspec", "item_octets", "record_count")

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 sensor_position: tuple[float, float, float] | None = None) -> None:
        """`sensor_position` is `(lat, lon, alt_m)` for the radar site, or None.

        MSL-referenced altitude, in metres, so that `alt_m - I048/110` is a height DIFFERENCE
        between two MSL figures — which is what the slant correction needs and what makes the
        geoid largely cancel.

        CONFIGURATION and not state, exactly like the injected clock and like `adsb.py`'s
        reference position: a constant of the deployment, supplied here, never accumulated from
        the data stream and never inferred from a payload. None is the default, so the default
        behaviour is the conservative one — the polar measurement is parked and no position is
        derived. Settlement 3.
        """
        super().__init__(clock, synthetic=synthetic)
        if sensor_position is not None:
            if len(sensor_position) != 3:
                raise ValueError(
                    f"sensor_position must be (lat, lon, alt_m), got {sensor_position!r}"
                )
            lat, lon, alt = (float(v) for v in sensor_position)
            if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
                raise ValueError(
                    f"sensor_position ({lat}, {lon}) is not a WGS-84 coordinate. Every derived "
                    "position in this adapter is measured from it, so a wrong site moves every "
                    "contact by the same error and nothing in the output would show it"
                )
            sensor_position = (lat, lon, alt)
        self._site = sensor_position

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One data block -> [Entity, Event] per record, in block order.

        Several records in one block are several TARGET REPORTS, not one target's history. They
        may name several aircraft, one may be a plot and another a track for the same target
        (§4.6.2 defines one UAP for both), and associating them is the plot-to-track association
        the RADAR performs and reports its own confidence in through I048/170 `DOU`. Doing it
        again here would redo the source's work invisibly with less information than it had.
        Settlement 11.
        """
        parsed = self._as_parsed(raw)
        records = parsed.get("records")
        if not isinstance(records, list) or not records:
            raise Cat048ParseError(
                "CAT048 payload holds no records — refusing to translate; top-level keys: "
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
        raise Cat048ParseError(
            f"a CAT048 payload is a data block (bytes) or its parsed twin (dict), "
            f"got {type(raw).__name__}"
        )

    def _translate(self, record: dict, block: dict, received_at: _dt.datetime,
                   source: Any) -> tuple[Entity, Event]:
        items = record["items"]
        unavailable: list[str] = []
        unresolved: dict[str, Any] = {}

        observed_at, time_basis = _observed_at(items, received_at)
        if time_basis["item"] is None:
            unavailable.append("I048/140 (the record states no time of day)")

        source_ids, identity_basis, identity_caveat = self._identity(record, items, observed_at)
        position, position_basis = _derive_position(items, self._site)
        kinematics, course_basis = self._kinematics(items)

        attributes = self._attributes(record, block, items, position_basis, course_basis,
                                      identity_basis, identity_caveat, unavailable, unresolved)

        typ = items["I048/020"]["typ"]
        entity = Entity(
            source=source,
            source_ids=source_ids,
            entity_id=identity_basis["entity_id"],
            entity_type=ENTITY_TYPE_BY_TYP[typ],
            # UNKNOWN, always. Settlement 9: an IFF result belongs to an IFF authority, and
            # over-claiming FRIENDLY is the dangerous direction.
            affiliation=Affiliation.UNKNOWN,
            symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                   synthetic=self._synthetic),
            position=position,
            kinematics=kinematics,
            attributes=attributes,
            valid_from=observed_at,
            # None on EVERY record, including an End of Track Message. `TRE` ends "a track
            # record within a particular track file" (I048/161), not the airframe the
            # entity_id names, so closing the interval here would be a false statement about a
            # longer-lived thing. Settlement 8, gap 26.
            valid_to=None,
            # Every quality statement CAT048 carries is a pulse-level flag, a per-axis standard
            # deviation or a plot-to-track association verdict. None is a 0..1 assessment of
            # the object's identity, and a standard deviation in nautical miles is not a
            # probability.
            confidence=None,
        )
        severity, event_type, severity_basis = self._severity(items)
        event = Event(
            source=source,
            source_ids=source_ids,
            event_id=ids.derive(identity_basis["system"],
                                f"{identity_basis['external_id']}|{times.render(observed_at)}",
                                kind="event"),
            event_type=event_type,
            severity=severity,
            related_entities=[entity.entity_id],
            # None. The position lives on the Entity, as for every other point-target adapter
            # here; Event.geometry is for footprints.
            geometry=None,
            payload={
                "observed_at_basis": time_basis,
                "severity_basis": severity_basis,
                "record_index": record["index"],
                "record_count": record.get("record_count", block.get("record_count")),
                "cat048_bds_registers": (items.get("I048/250") or {}).get("registers"),
                "cat048_acas_resolution_advisory": items.get("I048/260"),
            },
            observed_at=observed_at,
            received_at=received_at,
        )
        return entity, event

    # ------------------------------------------------------------------ identity

    def _identity(self, record: dict, items: dict,
                  observed_at: _dt.datetime) -> tuple[list[SourceId], dict, str | None]:
        """Settlement 9's two-step chain. The track number is never step two."""
        address = (items.get("I048/220") or {}).get("address")
        if address:
            system, external_id = ICAO_SYSTEM, address
            basis_note = (
                "I048/220, the 24-bit Mode S aircraft address, filed under ICAO24 — the same "
                "system name adsb.py and asterix_cat021.py use, so one airframe seen by a "
                "radar and by an ADS-B ground station derives the SAME entity_id without the "
                "adapters coordinating. That is a pure function of the address and not a join"
            )
        else:
            source_id = (items.get("I048/010") or {})
            measured = items.get("I048/040") or {}
            system = REPORT_SYSTEM
            external_id = "|".join(str(part) for part in (
                f"{source_id.get('sac', 0):02X}{source_id.get('sic', 0):02X}",
                (items.get("I048/140") or {}).get("time_of_day_raw", "no-time"),
                measured.get("rho_raw", "no-rho"),
                measured.get("theta_raw", "no-theta"),
                record["index"],
            ))
            basis_note = (
                "the record states no aircraft address, so the id is scoped to THIS REPORT — "
                "keyed on the SAC/SIC, the raw time of day, the raw RHO and THETA and the "
                "record index. A report with no stated airframe identity IS a one-shot "
                "observation, and an id that says so is more honest than one implying "
                "continuity. Deliberately NOT the I048/161 track number: a station-scoped, "
                "recycled 12-bit number keyed into entity_id merges two different airframes "
                "into one entity, which is a false statement. FORMAT_COVERAGE.md gap 27 "
                "records the truncation — consecutive scans of one PSR track get different "
                "entity_id values"
            )
        entity_id = ids.derive(system, external_id, kind="entity")
        caveat = None
        codes = {entry["code"] for entry in (items.get("I048/030") or {}).get("codes", [])}
        if 16 in codes:
            caveat = ("I048/030 code 16, 'Duplicated or Illegal Mode S Aircraft Address' — the "
                      "source is telling us the key in I048/220 may not be unique, so this "
                      "entity may conflate two airframes")
        return (
            [SourceId(system=system, external_id=external_id)],
            {"system": system, "external_id": external_id, "entity_id": entity_id,
             "note": basis_note},
            caveat,
        )

    # ------------------------------------------------------------------ kinematics

    def _kinematics(self, items: dict) -> tuple[Kinematics | None, dict | None]:
        """I048/200 only. I048/120 is a line-of-sight scalar and reaches no Kinematics field."""
        velocity = items.get("I048/200")
        if velocity is None:
            return None, None
        speed_nm_s = velocity["groundspeed_nm_s"]
        basis = {
            "speed_item": "I048/200 CALCULATED GROUNDSPEED, LSB 2^-14 NM/s x 1852 m = "
                          "0.113037109375 m/s per unit, exact in float64",
            "course_item": "I048/200's angular component",
            "course_basis": (
                "Mapped on §5.2.20's DEFINITION — 'Calculated track velocity expressed in "
                "polar co-ordinates' — because the angular component of a velocity vector is a "
                "course by construction, and on its NOTE, which pins the datum: 'The "
                "calculated heading is related to the geographical North at the aircraft "
                "position'. Geographic north is STATED, so gap 7's magnetic-versus-true hazard "
                "is absent BY THE TEXT here. The bit-diagram label reads 'CALCULATED HEADING' "
                "and does not govern; an encoder putting a bow heading there contradicts its "
                "own item's Definition. FORMAT_COVERAGE.md ambiguity 3"),
            # None, always. CAT048 states no vertical rate: I048/170's CDM is a four-value
            # category and I048/120 is a line-of-sight scalar.
            "climb_item": None,
        }
        _low, high, _lsb = codec.bounds("groundspeed")
        if speed_nm_s > 2.0:
            basis["over_stated_maximum"] = (
                f"the field is labelled 'CALCULATED GROUNDSPEED (max. 2 NM/s)' and states "
                f"{speed_nm_s} NM/s. The FIELD's range reaches {high} NM/s, and 2 NM/s is "
                "7200 kt, so the label is a design envelope rather than an encoding limit. "
                "Carried with this flag rather than refused — ambiguity 6")
        return Kinematics(
            speed_mps=speed_nm_s * codec.METRES_PER_NM,
            course_deg=velocity["heading_deg"] % 360.0,
            climb_mps=None,
        ), basis

    # ------------------------------------------------------------------ severity

    def _severity(self, items: dict) -> tuple[Severity, EventType, dict]:
        """Exactly one bit raises severity, and three named things deliberately do not."""
        extensions = (items.get("I048/020") or {}).get("extensions") or []
        military_emergency = bool(extensions and extensions[0].get("me"))
        typ = items["I048/020"]["typ"]
        if _is_track_end(items):
            event_type = EventType.STATUS_CHANGE
            type_note = ("I048/170 First Extension bit 8 (TRE) is set — 'End of track lifetime "
                         "(last report for this track)'. The reportable fact is the end of a "
                         "track's lifetime, so STATUS_CHANGE overrides what the record would "
                         "otherwise be")
        elif typ == 0:
            event_type = EventType.TRACK_UPDATE
            type_note = ("I048/020 TYP = 0 is 'No detection' (§5.2.4 Note 1), so this is a "
                         "track report with no plot behind it. Calling it a DETECTION would "
                         "claim a detection the item explicitly denies")
        else:
            event_type = EventType.DETECTION
            type_note = ("a monoradar target report IS a sensor detection — the first adapter "
                         "in this set whose ordinary case is DETECTION rather than "
                         "TRACK_UPDATE, because AIS, ADS-B and CAT021 receive self-reports and "
                         "a radar detects")
        basis: dict[str, Any] = {"event_type_basis": type_note}
        declined = []
        stat = (items.get("I048/230") or {}).get("stat")
        if stat in (2, 3, 4):
            declined.append(
                f"I048/230 STAT = {stat} ({STAT_TEXT[stat]}) — a Mode S flight-status alert "
                "fires on a Mode 3/A code change as well as on an emergency, so it is a "
                "procedural condition. The reading CAT021 gives I021/200 SS = 2")
        if items["I048/020"].get("spi"):
            declined.append("I048/020 SPI — Special Position Identification, an ident pulse a "
                            "controller asked for, not an emergency")
        if "I048/260" in items:
            declined.append(
                "I048/260 is present, and its two sentences assert different things. The "
                "Definition says 'Currently active Resolution Advisory (RA), if any'; the "
                "Encoding Rule says 'shall be present when a Resolution Advisory (RA) has been "
                "generated in the LAST SCAN'. An RA generated last scan need not still be "
                "active, so presence asserts LESS than the Definition's word 'currently' — and "
                "because the 56 bits are undecodable from this document, this adapter cannot "
                "tell which of the two it is holding. Severity stays a consumer's act. Note "
                "the divergence from CAT021's I021/008 row, which declines on the judgement "
                "ground that grading an equipment status would be the translator judging; this "
                "declines on a weaker and more specific ground — the text does not establish "
                "that an advisory is active at all")
        basis["declined"] = declined
        if military_emergency:
            basis["raised_by"] = (
                "I048/020 first extension ME, 'Military emergency' — the standard's own "
                "emergency declaration, and the ONLY bit in CAT048 that raises severity. The "
                "line sits exactly where ais.py puts navigational status 14, adsb.py puts "
                "emergency state 1-6 and asterix_cat021.py puts I021/200 ME")
            return Severity.CRITICAL, EventType.ALERT, basis
        basis["raised_by"] = None
        return Severity.INFO, event_type, basis

    # ------------------------------------------------------------------ attributes

    def _attributes(self, record: dict, block: dict, items: dict, position_basis: dict,
                    course_basis: dict | None, identity_basis: dict,
                    identity_caveat: str | None, unavailable: list[str],
                    unresolved: dict[str, Any]) -> dict:
        attributes: dict[str, Any] = {}
        source_id = items.get("I048/010") or {}
        typ = items["I048/020"]["typ"]

        attributes["cat048_block"] = dict(block)
        attributes["cat048_fspec"] = record["fspec"]
        attributes["cat048_items"] = dict(record.get("item_octets") or {})
        attributes["data_source"] = {
            "sac": source_id.get("sac"), "sic": source_id.get("sic"),
            "basis": ("I048/010, 'Identification of the radar station from which the data is "
                      "received' (§5.2.1's Definition), whose Encoding Rule is 'This Item "
                      "shall be present in every ASTERIX record'. NOT a SourceId: it "
                      "identifies the SENSOR, not the target, and filing a station under the "
                      "object's identifiers is how a fused picture ends up with an entity per "
                      "receiver. Sharper here than in CAT021 — every measurement in the record "
                      "is relative to this station, so the SAC/SIC is the key a consumer would "
                      "need to resolve the geometry at all, and the CDM has nowhere canonical "
                      "for a producing sensor. Gaps 14 and 24"),
        }
        attributes["report_type"] = {"typ": typ, "text": TYP_TEXT[typ]}
        attributes["entity_type_basis"] = (
            f"from I048/020 TYP = {typ} ({TYP_TEXT[typ]}), a MANDATORY item (§5.2.2: 'shall be "
            "present in every target record'). NOT from I048/030's classification codes, whose "
            "own Note 7 says 'The use of this Data Item is implementation specific and shall "
            "be described in the ICD of the system generating the Category 048 target "
            "reports' — a per-deployment convention is not a canonical classification. A "
            "primary return is an ECHO before it is an object, so TYP 0 and 1 read UNKNOWN. "
            "The known infelicity: a flock of birds detected by an SSR-equipped station still "
            "reads PLATFORM")
        attributes["affiliation_basis"] = (
            "UNKNOWN, always. I048/020's first extension carries FOE/FRI with the literal "
            "value '01 Friendly target', plus MI 'Military identification' — and turning an "
            "IFF interrogation result into FRIENDLY is an identification decision belonging to "
            "an IFF authority, not to a translator. Over-claiming FRIENDLY is also the "
            "dangerous direction. Two further reasons are in the text: §5.2.2's M4E note "
            "forces FOE/FRI to '00' whenever the real three-level result is in the REF, so "
            "'00' is ambiguous between 'not interrogated' and 'unreadable here'; and '10' is "
            "spelled 'Unknown target' rather than 'not interrogated', so the vocabulary makes "
            "three distinct claims that an affiliation would collapse")
        attributes["symbol_basis"] = (
            "derived from the affiliation through symbology.sidc_from_affiliation, so every "
            "CAT048 contact is an UNKNOWN glyph. CAT048 carries no symbology of any kind")
        attributes["integrity_basis"] = (
            "CAT048 defines NO checksum at any level — neither §4.6.2 nor §4.7 nor any §5.2 "
            "item specifies a CRC, checksum or parity field at block, record or item level. "
            "What passed is the structural gate: LEN matched the buffer, the records tiled it "
            "exactly, every FSPEC bit named a defined FRN, every variable item terminated "
            "inside the record, no FX led nowhere, and the mandatory items were present. This "
            "is weaker than a CRC and the difference is named rather than smoothed over: a "
            "single bit flipped inside a fixed-length field satisfies every check above and "
            "reaches the CDM as a measurement")
        attributes["identity_basis"] = identity_basis["note"]
        if identity_caveat:
            attributes["identity_caveat"] = identity_caveat
        attributes["position_basis"] = position_basis
        if position_basis.get("derived"):
            attributes["position_source_basis"] = (
                "ESTIMATED. PositionSource offers GNSS, INERTIAL, MANUAL and ESTIMATED and "
                "NONE of them names a sensor measurement. ESTIMATED is the only value that is "
                "not an outright false statement about what reaches Position here — a computed "
                "product of a measurement, an injected site and possibly a pressure altitude — "
                "and it answers the enum's own stated purpose correctly, since a radar fix is "
                "not GNSS and survives jamming a GNSS fix does not. The missing member is a "
                "1.1.0 candidate rather than a schema change; gap 24")
        if course_basis:
            attributes["course_basis"] = course_basis

        self._park_items(items, attributes, unavailable, unresolved)

        if identity_basis["system"] == REPORT_SYSTEM and "I048/161" in items:
            unavailable.append(
                "the source-stated track continuity in I048/161 — carried as a claim and "
                "deliberately not used as an identity key. Gap 27")
        attributes["unavailable_fields"] = sorted(unavailable)
        attributes["unresolved_raw"] = unresolved
        attributes["source_extras"] = lossless.residual(record, self.CONSUMED)
        return attributes

    def _park_items(self, items: dict, attributes: dict, unavailable: list[str],
                    unresolved: dict[str, Any]) -> None:
        """Every item's decoded fields, under the key the row set names for it."""
        first_ext = ((items.get("I048/020") or {}).get("extensions") or [{}])[0] \
            if (items.get("I048/020") or {}).get("extensions") else {}
        descriptor = items["I048/020"]
        attributes["simulated_target"] = {
            "sim": descriptor["sim"],
            "basis": ("parked, and it does NOT rewrite Entity.source.synthetic — that is a "
                      "deployment declaration about the feed and a payload bit may not flip "
                      "it. The Legion EXERCISE_* rule and CAT021's SIM row, reached from one "
                      "bit"),
        }
        attributes["rdp_chain"] = {
            "rdp": descriptor["rdp"],
            "basis": ("Report from RDP Chain 1 or 2 — a station-internal routing fact. What "
                      "would make it interpretable is CAT034, which is out of scope: "
                      "settlement 2"),
        }
        attributes["special_position_identification"] = {
            "spi": descriptor["spi"],
            "basis": ("parked, NOT a severity — an ident pulse is a procedural request. "
                      "§5.2.2's note adds 'For Mode S aircraft, the SPI information is also "
                      "contained in I048/230', so the same fact can arrive twice; both are "
                      "parked and neither is preferred"),
        }
        attributes["report_source"] = {
            "rab": descriptor["rab"],
            "basis": ("Report from aircraft transponder, or from a field monitor (fixed "
                      "transponder). Parked and deliberately NOT turned into FACILITY — "
                      "CAT021's identical decision: it says who transmitted, not what kind of "
                      "thing it is"),
        }
        if first_ext:
            attributes["test_target"] = first_ext.get("tst")
            attributes["extended_range"] = {
                "err": first_ext.get("err"),
                "basis": ("decoded and load-bearing: §5.2.4 NOTE 4 recommends RHO be set to "
                          "all-ones when the un-pinned REF's ERR item carries the real range, "
                          "so this bit is what says the parked RHO is a FLOOR rather than a "
                          "measurement"),
            }
            attributes["x_pulse"] = {
                "xpp": first_ext.get("xpp"),
                "basis": ("§5.2.2's note: 'This bit shall always be set when the X-pulse has "
                          "been extracted, independent from the Mode it was extracted with' — "
                          "so it says nothing about WHICH mode"),
            }
            attributes["military_identification"] = first_ext.get("mi")
            attributes["mode_4_foe_fri"] = {
                "value": first_ext.get("foe_fri"),
                "text": first_ext.get("foe_fri_text"),
                "basis": ("parked in full and never an affiliation. §5.2.2's M4E note: "
                          "interrogators with three-level classification 'shall encode the "
                          "detailed response information in data item M4E of the Reserved "
                          "Expansion Field … In this case the value for FOE/FRI in I048/020 "
                          "shall be set to “00”'. So 00 is ambiguous between 'no "
                          "interrogation' and 'the answer is in the un-pinned REF'"),
            }
            if _extended_range_floor(items):
                unresolved["I048/040 RHO"] = {
                    "raw": items["I048/040"]["rho_raw"],
                    "reason": ("ERR is set and RHO is at its maximum, which §5.2.4 NOTE 4 "
                               "recommends when the REF's ERR item holds the real range. This "
                               "is a FLOOR and not a range — the AIS 102.2 kt discipline — and "
                               "no position is derived from it"),
                }
        extensions = (items.get("I048/020") or {}).get("extensions") or []
        for index, ext in enumerate(extensions[1:], start=2):
            key = {2: "external_data", 3: "acas_and_transponder_capabilities",
                   4: "transponder_capabilities_contd", 5: "irm_capabilities"}[index]
            attributes[key] = ext
            for name, sub in ext.items():
                if isinstance(sub, dict) and sub.get("populated") is False:
                    unresolved[f"I048/020 extension {index} {name}"] = {
                        "reason": ("the Element Populated bit is CLEAR. 'Not populated' is NOT "
                                   "a value of zero — the Part 1 convention CAT021's REF "
                                   "needed, used here without being named"),
                    }
            acasxv = ext.get("acasxv")
            if acasxv and acasxv.get("populated") and acasxv.get("text") is None:
                unresolved["I048/020 extension 3 ACASXV"] = {
                    "raw": acasxv.get("value"),
                    "reason": "§5.2.2 defines 0, 1 and 2 and reserves '3 - 15 … for future "
                              "versions'",
                }

        we = items.get("I048/030")
        if we is not None:
            attributes["cat048_warning_error_codes"] = we["codes"]
            attributes["cat048_warning_error_basis"] = (
                "an ORDERED list in WIRE ORDER, duplicates preserved, never sorted and never "
                "deduplicated: §5.2.3's FX annotation reads 'Extension into first extent (next "
                "W/E condition value)' and Note 1 stresses that 'a series of one or more codes "
                "can be reported per target report'. The order is data, and egress is only "
                "byte-exact if the codes go back out in the order they came in. Settlement 7")
            for entry in we["codes"]:
                code = entry["code"]
                if code == 0:
                    unavailable.append(
                        "I048/030 code 0 — 'The zero value for this field means no warning "
                        "neither error conditions and that the target classification is "
                        "unknown'. Accepted despite the Encoding Rule's 'transmitted only if "
                        "different from zero', because the code has a stated meaning and "
                        "refusing a whole target report over one redundant octet would be "
                        "filtering")
                elif code > MANUFACTURER_CODE_MAX or entry["text"] is None:
                    band = ("the manufacturer range 64..127, which 'shall be described in the "
                            "corresponding ICD' and no ICD is pinned here"
                            if code > AMG_CODE_MAX else
                            "the AMG range 0..63, allocated to the AMG and not yet assigned — "
                            "a FUTURE standard value, which is a different fact from a private "
                            "one")
                    unresolved[f"I048/030 code {code}"] = {"reason": band}
            codes = {entry["code"] for entry in we["codes"]}
            if codes & {33, 34} and 15 not in codes:
                attributes["cat048_warning_error_nonconformance"] = (
                    "§5.2.3: 'If Codes 33 or 34 are sent, also Code 15 shall be sent'. Code 15 "
                    "is absent. Recorded as a non-conformance and NOT a refusal — Note 4 "
                    "explains the redundancy ('Code 15 is kept for backwards compatibility'), "
                    "and its violation costs nothing structurally")
            if codes & {35, 36}:
                attributes["ic_conflict_basis"] = (
                    "§5.2.3 NOTE 6: 'Together with Codes 35 and 36 the possibility to "
                    "communicate the area within which the detection of an IC Conflict is "
                    "possible was implemented in the Category 034 Specification Ref. [5] by "
                    "means of Message Type 008.' CAT034 is out of scope, so the WHERE is "
                    "unreadable here. Code 36 also carries its own nested NOTE: 'Although "
                    "implementation dependent, the use of this code should be limited to the "
                    "target acquisition phase'")
            if 37 in codes:
                unresolved["I048/030 code 37"] = {
                    "reason": ("'Duplicate Mode 5 PIN (refer to the Mode 5 items in the REF)' "
                               "— the code's entire definition is a pointer into the "
                               "Reserved Expansion Field, which is not pinned. Settlement 1"),
                }

        measured = items.get("I048/040")
        if measured is not None:
            attributes["cat048_measured_position"] = {
                "rho_raw": measured["rho_raw"], "rho_nm": measured["rho_nm"],
                "rho_lsb_nm": codec.bounds("rho")[2],
                "theta_raw": measured["theta_raw"], "theta_deg": measured["theta_deg"],
                "theta_lsb_deg": codec.bounds("theta")[2],
                "azimuth_reference": "local geographical north (§4.3.1)",
                "relative_to": {"sac": (items.get("I048/010") or {}).get("sac"),
                                "sic": (items.get("I048/010") or {}).get("sic")},
                "basis": ("carried losslessly whether or not a position was derived, because "
                          "egress re-emits from these integers and a derived Position is a "
                          "one-way view. §5.2.4 Note 3 adds provenance: 'In case of combined "
                          "detection by a PSR and an SSR, then the SSR position is sent'"),
            }
        elif items["I048/020"]["typ"] != 0:
            attributes["cat048_measured_position_nonconformance"] = (
                "§5.2.4's Encoding Rule is 'This item shall be sent when there is a "
                f"detection', and TYP = {items['I048/020']['typ']} states one. Recorded as a "
                "non-conformance and NOT a refusal — the record is otherwise complete and "
                "suppressing it would be filtering")

        calculated = items.get("I048/042")
        if calculated is not None:
            tcc = ((items.get("I048/170") or {}).get("extent") or {}).get("tcc")
            attributes["cat048_calculated_position"] = {
                **calculated,
                "tcc": tcc,
                "basis": ("still never a Position, even with a site injected. Its origin "
                          "'coincides with the radar head position' (§4.3.2.2), but WHICH of "
                          "two transforms produced it is signalled in a DIFFERENT item — TCC "
                          "in I048/170 — and the projection is named only as 'e.g. a "
                          "stereographical projection'. Deriving from it would need a "
                          "cross-item join and an unnamed projection, so I048/040 is the "
                          "single source of derived geometry and the arithmetic has one owner"),
            }

        self._park_altitudes(items, attributes, unavailable, unresolved)
        self._park_mode_codes(items, attributes, unavailable, unresolved)
        self._park_track(items, attributes, unavailable, unresolved)
        self._park_doppler(items, attributes)
        self._park_plot_characteristics(items, attributes)
        self._park_comms(items, attributes, unavailable, unresolved)
        self._park_opaque(items, attributes, unresolved)

        tod = items.get("I048/140")
        if tod is not None:
            attributes["cat048_time"] = {
                "time_of_day_raw": tod["time_of_day_raw"],
                "time_of_day_s": tod["time_of_day_s"],
                "lsb_seconds": codec.bounds("tod")[2],
                "basis": ("parked, and EGRESS RE-EMITS FROM THIS rather than recomputing from "
                          "observed_at: 1/128 s is 7.8125 ms, not a whole number of "
                          "milliseconds, and times.render emits three decimal places. §4.2.1 "
                          "adds that 'The target time stamp shall be consistent with the "
                          "reported plot position', which is why gap 13's one-record-two-"
                          "instants problem does not arise in this format"),
            }

    def _park_altitudes(self, items: dict, attributes: dict, unavailable: list[str],
                        unresolved: dict[str, Any]) -> None:
        level = items.get("I048/090")
        if level is not None:
            attributes["flight_level"] = {
                "flight_level": level["flight_level"],
                "unit": "FL, the source's own unit",
                "v": level["v"], "g": level["g"],
                "basis": ("gap 9. A PRESSURE altitude against the flight-level datum, LSB 1/4 "
                          "FL 'in two's complement form' — Edition 1.32's own clarification. "
                          "Not Position.alt_m, which is metres above the WGS-84 ellipsoid. "
                          "Note the collision named rather than resolved: adsb.py parks the "
                          "concept at attributes.baro_altitude_ft and asterix_cat021.py at "
                          "attributes.flight_level, and converging on one key would repeat gap "
                          "1's mistake"),
                "g_meaning": ("§5.2.12 Note 4: 'For Mode S, bit 15 (G) is set to one when an "
                              "error correction has been attempted' — a statement about the "
                              "STATION'S processing"),
            }
            attributes["flight_level_range_basis"] = (
                "§5.2.12 Note 3 is 'The value shall be within the range described by ICAO "
                "Annex 10'. Annex 10 is not among §2.2's five reference documents and nothing "
                "here pins it, so the ENFORCED range is the field's own: 14 bits of two's "
                f"complement at 1/4 FL, {codec.bounds('flight_level')[0]} to "
                f"{codec.bounds('flight_level')[1]} FL. The narrower ICAO bound the item defers "
                "to was not readable")
        mode_c = items.get("I048/100")
        if mode_c is not None:
            unresolved["I048/100 Mode-C reply"] = {
                "gray_raw": mode_c["mode_c_gray_raw"],
                "reason": ("NOT decoded, deliberately. §5.2.13's Encoding Rule sends this item "
                           "'only … when a not validated or undecodable Mode C code has been "
                           "received', so THE ITEM EXISTS TO REPORT THAT THE ALTITUDE COULD "
                           "NOT BE ESTABLISHED — Gray-decoding it would manufacture precisely "
                           "the value it says is unavailable. No Gray table appears anywhere "
                           "in this document either"),
            }
            attributes["mode_c_confidence"] = {
                "quality_bits": mode_c["quality_bits"],
                "v": mode_c["v"], "g": mode_c["g"],
                "basis": ("twelve per-pulse confidence bits. Note the Mode S case: §5.2.13 "
                          "says 'if this item is sent because of an undecodable Mode-C code "
                          "received in a Mode S altitude reply, all pulse quality bits will be "
                          "set to high (zero)' — so all-zero does NOT mean twelve good pulses"),
                "d1_q_dependency": (
                    "§5.2.13 Note 1: 'For Mode S, D1 is also designated as Q, and is used to "
                    "denote either 25ft or 100ft reporting' — and the capability is in a "
                    "DIFFERENT item, I048/230's ARC. Both parked, the dependency recorded, the "
                    "join declined"),
            }
        height = items.get("I048/110")
        if height is not None:
            attributes["height_3d_ft"] = {
                "height_ft": height["height_ft"],
                "datum": ("mean sea level — §5.2.14: 'The height shall use mean sea level as "
                          "the zero reference level'"),
                "basis": ("a GEOMETRIC height, LSB 25 ft, two's complement. A THIRD datum "
                          "alongside HAE and the pressure datum, which sharpens gap 9's "
                          "existing datum note rather than opening a new gap. Never "
                          "Position.alt_m: MSL is not the ellipsoid and the geoid separation "
                          "needs a model nothing here carries"),
            }
        if level is not None and height is not None:
            fl_feet = level["flight_level"] * 100.0
            attributes["cat048_altitude_disagreement"] = {
                "i048_090_flight_level": level["flight_level"],
                "i048_090_as_feet": fl_feet,
                "i048_110_height_ft": height["height_ft"],
                "difference_ft": height["height_ft"] - fl_feet,
                "basis": ("RECORDED, NEVER ADJUDICATED. These are NOT the same quantity: "
                          "I048/090 is a pressure altitude against the flight-level datum and "
                          "I048/110 is a geometric height above mean sea level, so A BARE "
                          "NUMERIC COMPARISON IS ITSELF A DEFECT and the difference above is a "
                          "statement about the record rather than an error. Nothing is "
                          "preferred, averaged or dropped"),
            }
            source_codes = {entry["code"]
                            for entry in (items.get("I048/030") or {}).get("codes", [])}
            named = {code: text for code, text in ALTITUDE_WE_CODES.items()
                     if code in source_codes}
            attributes["altitude_basis"] = {
                "source_stated_disagreement": named or None,
                "note": ("§5.2.12's Notes 1 and 2 route the two altitude failure cases into "
                         "I048/030 BY NAME — an undecodable code should raise code 18, and a "
                         "value the tracker judges abnormal should raise code 12. So a "
                         "conforming station tells us, in a third item, that its own altitudes "
                         "disagree. The source's verdict is carried as the source's and this "
                         "adapter adds none of its own"),
            }

    def _park_mode_codes(self, items: dict, attributes: dict, unavailable: list[str],
                         unresolved: dict[str, Any]) -> None:
        mode_3a = items.get("I048/070")
        if mode_3a is not None:
            attributes["mode_3a_code"] = {
                **mode_3a,
                "basis": ("§5.2.10, in the source's own octal representation. NOT a SourceId — "
                          "a squawk is assigned per flight, reassigned, and duplicated across "
                          "regions. Note that L means something DIFFERENT here than in "
                          "I048/050 and I048/055: in /070 it is 'Mode-3/A code not extracted "
                          "during the last scan', in /050 and /055 it is 'Smoothed … code as "
                          "provided by a local tracker'. Same letter, same relative position, "
                          "different claim, so each is parked with its own item's wording"),
                "encoding_rule_note": (
                    "§5.2.10: 'For Mode S, once a Mode-3/A code is seen, that code shall be "
                    "sent every scan, provided the radar is receiving replies for that "
                    "aircraft' — so a repeated code is not fresh extraction, and a consumer "
                    "counting code changes would otherwise read continuity as re-confirmation"),
                "v_note": (
                    "§5.2.10 Note 2: 'For Mode S, bit 16 is normally set to zero, but can "
                    "exceptionally be set to one to indicate a non-validated Mode-3/A code' — "
                    "so a V set on a Mode S record is not the same event as on a Mode A/C one"),
            }
        mode_2 = items.get("I048/050")
        if mode_2 is not None:
            attributes["mode_2_code"] = {
                **mode_2,
                "basis": ("§5.2.6, octal, with V/G/L. The 1.32 NOTE routing an alternative "
                          "value to I048/REF/GEN48/ALTM2 is an un-pinned pointer; settlement 1"),
            }
        mode_1 = items.get("I048/055")
        if mode_1 is not None:
            attributes["mode_1_code"] = {
                **mode_1,
                "basis": ("§5.2.7, five bits, with V/G/L. Its NOTE ties V, G, L, A4, A2, A1, "
                          "B2 and B1 to 'subfield #5 of data item “MD5 -Mode 5 "
                          "Reports”' in the Reserved Expansion Field — recorded, "
                          "unreadable here"),
            }
        confidence = {}
        for item, label in (("I048/060", "mode_2"), ("I048/065", "mode_1"),
                            ("I048/080", "mode_3a")):
            if item in items:
                confidence[label] = items[item]
        if confidence:
            attributes["code_confidence"] = {
                **confidence,
                "basis": ("per-pulse confidence for Mode-2, Mode-1 and Mode-3/A. Each is sent "
                          "'only when at least one pulse is of low quality', so THE ITEM'S "
                          "PRESENCE IS ITSELF THE SIGNAL and its absence is not a claim of "
                          "perfect quality. None reaches Entity.confidence"),
            }
        identification = items.get("I048/240")
        if identification is not None:
            attributes["aircraft_identification"] = identification["identification"]
            attributes["aircraft_identification_basis"] = (
                "gap 1, a sixth private key for one concept. Eight characters at six bits "
                "each — and THIS DOCUMENT STATES NO CHARACTER TABLE. §5.2.25 Note 1 says 'For "
                "the transmission of BDS Register 2,0, Data Item I048/240 is used', and BDS "
                "2,0's coding is in [Ref. 2] ED-73F/DO-181F, which nothing here pins; the "
                "alphabet used is the ICAO Annex 10 Vol. IV Table 3-8 set that adsb.py and "
                "asterix_cat021.py both apply to the same six bits, cited as their basis "
                "rather than as this document's. §5.2.24 also puts two different kinds of "
                "string in one field — 'aircraft identification when flight plan is available "
                "or the registration marking when no flight plan is available' — with nothing "
                "saying which, so that is recorded rather than guessed")
            if "#" in identification["identification"]:
                unresolved["I048/240 identification"] = {
                    "raw": identification["identification_raw"],
                    "reason": ("a six-bit code the ICAO alphabet does not define, kept visible "
                               "as '#' rather than cleaned away — a decodable record with an "
                               "undefined character is different from a refusal"),
                }

    def _park_track(self, items: dict, attributes: dict, unavailable: list[str],
                    unresolved: dict[str, Any]) -> None:
        number = items.get("I048/161")
        if number is not None:
            attributes["track_number"] = {
                "track_number": number["track_number"],
                "scoped_to": {"sac": (items.get("I048/010") or {}).get("sac"),
                              "sic": (items.get("I048/010") or {}).get("sic")},
                "basis": ("A CARRIED CLAIM, NEVER AN IDENTITY KEY. §5.2.18 calls it 'a unique "
                          "reference to a track record within a particular track file' — "
                          "twelve bits, 0..4095, station-scoped and RECYCLED. Keying entity_id "
                          "on it would merge two different airframes hours apart into one "
                          "entity, which is a false statement in the field the CDM guarantees "
                          "is stable across updates; CAT021's declines table rejected exactly "
                          "that. It cannot ride on a Track either: Track has track_id, "
                          "entity_id, samples and track_quality and no extension bag, which is "
                          "the existing Track.attributes 1.1.0 candidate. Gap 27"),
            }
        status = items.get("I048/170")
        if status is None:
            return
        extent = status.get("extent") or {}
        attributes["track_status"] = {
            "cnf": status["cnf"],
            "cnf_text": "Tentative Track" if status["cnf"] else "Confirmed Track",
            "rad": status["rad"], "rad_text": status["rad_text"],
            "dou": status["dou"],
            "mah": status["mah"],
            "cdm": status["cdm"], "cdm_text": status["cdm_text"],
            "extent": extent or None,
            "basis": ("CNF is a tracker's promotion state and NOT a confidence, so it does not "
                      "reach Entity.confidence. DOU 'Signals level of confidence in plot to "
                      "track association process' — a DATA-ASSOCIATION verdict, not a "
                      "confidence in the object. CDM is a four-value CATEGORY and never "
                      "Kinematics.climb_mps, which is metres per second; CAT048 states no "
                      "vertical rate anywhere. RAD's own note adds 'RAD can change after a "
                      "number of non-matching with TYP in item 020', so RAD and TYP may "
                      "legitimately disagree within one record"),
        }
        if status["rad"] == 3:
            unresolved["I048/170 RAD"] = {
                "raw": 3, "reason": "§5.2.19 spells value 11 'Invalid'",
            }
        if status["cdm"] == 3:
            unavailable.append("I048/170 CDM — §5.2.19 spells value 11 'Unknown'")
        if extent.get("tre"):
            attributes["track_end"] = {
                "tre": True,
                "basis": ("I048/170 First Extension bit 8 — 'Signal for End_of_Track; = 1 End "
                          "of track lifetime (last report for this track)'. THE ONLY EXPLICIT "
                          "TERMINAL DECLARATION ANY SOURCE IN THIS DOCUMENT MAKES, AND THE CDM "
                          "CANNOT HOLD IT. Entity.valid_to stays None: valid_to is 'When it "
                          "ceased' on an object whose entity_id is a 24-bit airframe address, "
                          "while TRE ends 'a track record within a particular track file' "
                          "(§5.2.18). Writing the track-end instant there would tell every "
                          "consumer that did not read a basis key that the AIRCRAFT'S state "
                          "ceased. Event.event_type becomes STATUS_CHANGE instead. Gap 26"),
                "relaxation": (
                    "Edition 1.30 relaxed the Encoding Rules of I048/220, /230, /240 and /250 "
                    "for this message shape, and all four notes recommend that systems already "
                    "sending them 'continue to do so'. That recommendation is honoured by "
                    "FIDELITY rather than by policy: what was on the wire goes back on the "
                    "wire, and egress never ADDS an item to a TRE record that arrived without "
                    "one"),
                "terminology": (
                    "§5.2.4 Note 1 and §5.2.20's Encoding Rule call the same shape a 'track "
                    "cancellation message' while five items call it an 'End of Track Message', "
                    "and the document defines NEITHER term. TRE is the only observable "
                    "trigger, so it is the one used. Ambiguity 2"),
            }
            for item in ("I048/220", "I048/230", "I048/240", "I048/250"):
                if item not in items:
                    unavailable.append(
                        f"{item} — a PERMITTED absence in an End of Track Message: its "
                        "Encoding Rule reads 'except for an “End of Track Message” "
                        "(i.e. I048/170, First Extension, Bit 8 is set to “1”) in "
                        "which this Data Item is optional'")
        if extent.get("gho"):
            attributes["ghost_target"] = {
                "gho": True,
                "basis": ("§5.2.19: 'Ghost target track'. The object is still emitted IN FULL "
                          "— the source's verdict is carried, and suppressing or downgrading "
                          "the record would be the filtering the Adapter contract refuses. "
                          "CAT021's RCF row, one format later"),
            }
        if extent.get("sup"):
            attributes["cluster_supported_track"] = {
                "sup": True,
                "basis": ("track maintained with information from a neighbouring node on the "
                          "cluster or network — a STATION-TOPOLOGY fact. It says another "
                          "sensor contributed and names neither it nor how, so nothing about "
                          "it is actionable here"),
            }
        quality = items.get("I048/210")
        if quality is not None:
            attributes["cat048_track_quality"] = {
                **quality,
                "basis": ("§5.2.21's 'vector of standard deviations' in the LOCAL GRID SYSTEM. "
                          "Parked in the source's units and never Position.accuracy_m: "
                          "local-grid axes are the same unresolvable frame as I048/042's, "
                          "collapsing sigma(X) and sigma(Y) into one horizontal figure is a "
                          "modelling choice, and a standard deviation in nautical miles is not "
                          "a probability so Track.track_quality stays None. Gaps 17 and 24"),
            }

    def _park_doppler(self, items: dict, attributes: dict) -> None:
        doppler = items.get("I048/120")
        if doppler is None:
            return
        parked: dict[str, Any] = {"primary": doppler["primary"]}
        if "cal" in doppler:
            parked["calculated"] = doppler["cal"]
        if "rds" in doppler:
            parked["raw"] = doppler["rds"]
        parked["basis"] = (
            "PARKS — reaches no Kinematics field. A radial Doppler speed is the PROJECTION of "
            "a velocity onto the radar's line of sight, so a target flying tangentially across "
            "the beam has a radial speed of zero and a ground speed of three hundred knots. "
            "Kinematics.speed_mps is a speed over the ground, and writing a line-of-sight "
            "component into it would not be imprecise — it would be a different quantity under "
            "a name every consumer reads as a ground speed. Settlement 6, gap 25")
        parked["sign_basis"] = (
            "§5.2.15's Note, quoted whole: 'Although the meaning of a positive or negative "
            "value is implementation dependent and shall be described in the ICD of the system "
            "generating the ASTERIX record, it is recommended to transmit a positive value for "
            "targets moving away from the radar.' A field whose SIGN CONVENTION is a "
            "per-deployment ICD matter, with a recommendation rather than a rule as the "
            "fallback, cannot be normalised into a canonical model without inventing the "
            "convention. The recommendation was NOT applied as an assumption")
        if "rds" in doppler:
            parked["raw_basis"] = (
                "AMB is a Doppler ambiguity interval and FRQ is a transmitter frequency — "
                "NEITHER IS A PROPERTY OF THE TARGET AT ALL")
        if doppler["primary"]["cal"] and doppler["primary"]["rds"]:
            parked["nonconformance"] = (
                "§5.2.15's Encoding Rule is 'When used, only one secondary subfield shall be "
                "present', and both CAL and RDS are set. Both parsed and parked, the "
                "non-conformance recorded, and the record NOT refused: both subfields are "
                "fixed-length so nothing desynchronises, and refusing a decodable target "
                "report over a redundancy rule would be filtering. Ambiguity 5")
        attributes["radial_doppler"] = parked

    def _park_plot_characteristics(self, items: dict, attributes: dict) -> None:
        plot = items.get("I048/130")
        if plot is None:
            return
        parked = {key: value for key, value in plot.items()}
        parked["basis"] = (
            "§5.2.16, the radar's own account of the QUALITY OF THE DETECTION — a different "
            "thing from the quality of the track. SAM and PAM are amplitudes in dBm, two's "
            "complement per their own notes, and are link measurements never read as a range "
            "or a confidence (adsb.py's message-amplitude rule)")
        for flag, key in (("rpd", "range_difference_nm"), ("apd", "azimuth_difference_deg")):
            sub = plot.get(flag)
            if sub is None:
                continue
            form = "range_difference" if flag == "rpd" else "azimuth_difference"
            if sub["raw"] == 0x7F:
                sub["at_or_beyond_maximum"] = (
                    f"§5.2.16: 'Sending the maximum value means that the difference in range "
                    f"is equal or greater than the maximum value' — a FLOOR, not a value. "
                    f"Recorded as one, the AIS 102.2 kt discipline. The field's maximum is "
                    f"{codec.bounds(form)[1]}")
        if plot.get("apd") is not None:
            parked["apd_note_wording"] = (
                "§5.2.16 subfield #7's third note reads 'the difference in RANGE is equal or "
                "greater than the maximum value' — a copy-paste from subfield #6, since APD is "
                "an azimuth difference. Read as azimuth, since the subfield carries nothing "
                "else, and the wording is recorded. Ambiguity 4")
        attributes["plot_characteristics"] = parked

    def _park_comms(self, items: dict, attributes: dict, unavailable: list[str],
                    unresolved: dict[str, Any]) -> None:
        comms = items.get("I048/230")
        if comms is None:
            return
        attributes["comms_capability"] = {
            **comms,
            "com_ambiguity": (
                "§5.2.23's Encoding Rule adds 'If the datalink capability has not been "
                "extracted yet, bits 16/14 shall be set to zero', so COM = 0 is AMBIGUOUS "
                "between 'No communications capability (surveillance only)' and 'not yet "
                "extracted'. Both readings recorded, neither chosen — a transponder with no "
                "datalink and one not yet interrogated are different facts and the field "
                "cannot distinguish them. Ambiguity 9") if comms["com"] == 0 else None,
            "arc_dependency": (
                "ARC is the altitude reporting capability (100 ft or 25 ft) that I048/100's "
                "D1/Q bit needs, and the join is declined"),
            "b1_basis": (
                "B1A is 'BDS 1,0 bit 16' and B1B is 'BDS 1,0 bits 37/40' — five bits lifted "
                "out of a register whose other 51 bits are not here. Parked as the register "
                "FRAGMENTS they are, never as a decoded capability"),
            "si_basis": ("SI/II transponder capability, added in Edition 1.16, so a record from "
                         "an older encoder carries a spare bit here instead"),
        }
        if comms["com"] in (5, 6, 7):
            unresolved["I048/230 COM"] = {"raw": comms["com"],
                                          "reason": "§5.2.23 spells values 5 to 7 'Not assigned'"}
        if comms["stat"] == 6:
            unresolved["I048/230 STAT"] = {"raw": 6,
                                           "reason": "§5.2.23 spells value 6 'Not assigned'"}
        if comms["stat"] == 7:
            unavailable.append("I048/230 STAT — §5.2.23 spells value 7 'Unknown'")

    def _park_opaque(self, items: dict, attributes: dict, unresolved: dict[str, Any]) -> None:
        registers = items.get("I048/250")
        if registers is not None:
            attributes["bds_registers"] = {
                **registers,
                "basis": ("PARKED, NOT EXEMPTED. Each register is 56 bits of hex plus its "
                          "BDS1/BDS2 address and extraction mode; not decoded, because the "
                          "registers are a separate set with their own document ([Ref. 2] "
                          "ED-73F/DO-181F) which nothing here pins, and adsb.py already names "
                          "a Mode S BDS adapter as a DIFFERENT adapter. Three traps carried "
                          "with them: BDS1 = BDS2 = 0 means 'Comm-B broadcast, register "
                          "unidentified' and NOT register 0,0 (Note 3); the register set is "
                          "split across three items, since 2,0 is in I048/240, 3,0 is in "
                          "I048/260 and 3,1 comes back into I048/250 for ACAS Xu (Notes 1 and "
                          "2); and the stride is eight octets per register after the one-octet "
                          "REP, which the prose, the bit diagram and Table 2's '1+8*n' all "
                          "agree on"),
            }
        advisory = items.get("I048/260")
        if advisory is not None:
            attributes["acas_ra_active"] = {
                "acas_ra": advisory["acas_ra"],
                "definition": ("Currently active Resolution Advisory (RA), if any, generated "
                               "by the ACAS associated with the transponder transmitting the "
                               "report and threat identity data"),
                "encoding_rule": ("This item shall be present when a Resolution Advisory (RA) "
                                  "has been generated in the last scan"),
                "basis": ("THE TWO SENTENCES ABOVE ASSERT DIFFERENT THINGS. An RA generated "
                          "last scan need not still be ACTIVE, so the item's presence asserts "
                          "less than the Definition's word 'currently' — and because the 56 "
                          "bits are undecodable here, this adapter cannot tell which of the "
                          "two it is holding. Severity stays a consumer's act"),
                "decode_declined": (
                    "the only decode authority the item cites is Note 1, 'Refer to ICAO Draft "
                    "SARPs for ACAS for detailed explanations' — a DRAFT, unnamed by edition, "
                    "absent from §2.2's reference list, and there is no field breakdown of the "
                    "56 bits anywhere in this document"),
                "acas_xu_split": (
                    "Note 2: 'In case of ACAS Xu, the Resolution Advisory consists of two "
                    "parts (BDS30 and BDS31). BDS31 will be transmitted using item 250.' So on "
                    "ACAS Xu the advisory is SPLIT ACROSS TWO ITEMS and either half alone is "
                    "incomplete; I048/020 extension 3's ACASXV is what says whether this "
                    "applies"),
            }
            unresolved["I048/260 ACASRA"] = {
                "raw": advisory["acas_ra"],
                "reason": "the advisory vocabulary is defined outside this specification, in a "
                          "DRAFT the document does not identify by edition",
            }
        special = items.get("SP")
        if special is not None:
            attributes["special_purpose_field"] = {
                **special,
                "basis": ("opaque by definition. Parked verbatim as hex and NEVER WRITTEN TO "
                          "on egress — its contents are settled by bilateral agreement between "
                          "one sender and one receiver, so a byte invented here is a byte some "
                          "deployment already means something by. No §5.2 description exists "
                          "for it in this document"),
            }
        expansion = items.get("RE")
        if expansion is not None:
            attributes["reserved_expansion_field"] = {
                **expansion,
                "basis": ("PARKED VERBATIM AND NEVER DECODED, and the reason is PROCEDURAL "
                          "rather than textual: the appendix that defines it "
                          "(SPEC-0149-4A, listed at Edition 1.13 of 4 December 2024 with "
                          "Edition 1.12 contemporaneous with the pinned core) is a public "
                          "download that was identified and simply not acquired. This document "
                          "defines no part of the RE — FRN 28 has no §5.2 entry — so decoding "
                          "it FROM THE PINNED TEXT ALONE would mean inventing a structure, but "
                          "that is not the reason. Weaker than GMTIF's §L.4 '(TO BE PROVIDED)' "
                          "blocker and the NITS XSD row, which are genuinely unobtainable. "
                          "Reopen condition: acquire and pin Appendix A. Settlement 1"),
            }
            losses = []
            if _extended_range_floor(items):
                losses.append("the ERR bit is set, so this target's real range is in the REF's "
                              "Extended Range Report and the parked RHO is a floor")
            extensions = (items.get("I048/020") or {}).get("extensions") or []
            if extensions and extensions[0].get("foe_fri") == 0:
                losses.append("FOE/FRI is '00', which is ambiguous between 'No Mode 4 "
                              "interrogation' and 'the three-level result is in the REF's M4E' "
                              "— A MODE 4 INTERROGATION THAT HAPPENED IS INDISTINGUISHABLE "
                              "FROM ONE THAT DID NOT")
            codes = {entry["code"] for entry in (items.get("I048/030") or {}).get("codes", [])}
            if 37 in codes:
                losses.append("I048/030 code 37's entire definition is a pointer into the REF")
            attributes["reserved_expansion_basis"] = {
                "exposed_to": losses or None,
                "note": ("which of settlement 1's named losses this particular record is "
                         "exposed to. Empty means the RE arrived and none of the four "
                         "interpretations this adapter cannot read is in play for this record"),
            }

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities that CAME FROM CAT048 back to one data block, byte-exactly.

        Everything derived — `observed_at`, `entity_type`, the `Kinematics` floats and the
        `Position` settlement 3 computes — is a one-way view and is **not** the source of any
        emitted byte. That matters more here than in any previous adapter: re-encoding `RHO`
        from a derived latitude would run the imported geodesy in both directions and hide any
        error in it, whereas re-emitting the parked integers means a conversion defect can only
        ever affect the CDM view and never the wire.
        """
        entities = [obj for obj in objects if isinstance(obj, Entity)]
        tracks = [obj for obj in objects if type(obj).__name__ == "Track"]
        if tracks and not entities:
            raise Cat048ParseError(
                "a CDM Track cannot become a CAT048 data block, and settlement 3 NARROWS the "
                "reason rather than removing it. With a sensor_position injected the geometry "
                "IS invertible — geodetic to RHO/THETA is the same arithmetic run backwards — "
                "so the refusal no longer rests on the transform. It rests on what the CDM "
                "does not carry: I048/010 'shall be present in every ASTERIX record' (§5.2.1) "
                "and there is no SAC/SIC anywhere in a Track; there is no FSPEC, no I048/020 "
                "TYP, and no height item, so the inverse slant correction has no delta-h "
                "either. A caller may supply a SITE, which locates a system; inventing a "
                "SAC/SIC would NAME one, which is a different and larger act"
            )
        if not entities:
            raise Cat048ParseError(
                f"nothing to emit: {len(objects)} object(s) and no Entity among them"
            )
        records = []
        for entity in entities:
            record = self._record_from_entity(entity)
            records.append(record)
        return build_block(records)

    def _record_from_entity(self, entity: Entity) -> dict:
        parked = entity.attributes.get("source_extras") or {}
        items = parked.get("items") if isinstance(parked, dict) else None
        fspec = entity.attributes.get("cat048_fspec")
        octets = entity.attributes.get("cat048_items")
        if not items or not fspec:
            missing = [name for name, value in
                       (("source_extras.items", items), ("cat048_fspec", fspec)) if not value]
            raise Cat048ParseError(
                f"Entity {entity.entity_id} did not come from CAT048: {', '.join(missing)} "
                "is absent from its attributes. There is no SAC/SIC to write and §5.2.1 says "
                "I048/010 'shall be present in every ASTERIX record'; there is no FSPEC, no "
                "I048/020 TYP and no height item for the inverse slant correction. Note what "
                "is NOT on that list any more: the site position, which a caller may now "
                "supply. The refusal names each missing input rather than inventing one"
            )
        return {"index": 0, "fspec": fspec, "items": items,
                "item_octets": dict(octets or {})}
