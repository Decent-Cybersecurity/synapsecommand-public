"""ASTERIX Category 062 — SDPS Track Messages. Data blocks in, CDM out, and back.

Adapter #13, and **the first in this repository whose input is already the output of a fusion
process.**

INGEST  one ASTERIX **data block** — `CAT | LEN | FSPEC + items | ...` — becomes an Entity + an
        Event per record, in block order. The Entity is the tracked target.
EGRESS  Entities that CAME FROM CAT062 become one data block, byte-exactly. Anything else is a
        refusal that names what is missing.

Implements the row set in `FORMAT_COVERAGE.md` under "ASTERIX Category 062", which was written and
reviewed as a specification BEFORE this file existed. Where the code and a row disagree the row
wins, or the row changes in the same commit; the changes made here are listed in that section
under "What Phase 2 changed in the Phase 1 row set" and each is noted at its site.

SETTLEMENT 1 IS THE ONE THAT DECIDES EVERY DISPOSITION, AND IT IS NOT THE USUAL ONE
------------------------------------------------------------------------------------
Every other adapter here refuses to fuse. This one refuses to fuse *a fused product*, which is a
distinction that has to be made explicitly because it is easy to lose. Category 062 is what a
Surveillance Data Processing System emits after correlating plots and local tracks from radars,
Mode S interrogators, multilateration, ADS-B and ADS-C into one system track. So the record is full
of metadata ABOUT that correlation — per-technology update ages in `I062/290`, per-parameter ages in
`I062/295`, amalgamation and coasting and staleness flags in `I062/080`, the tracker's own estimated
standard deviations in `I062/500`, contributing-sensor lists in the REF, and a whole item of LAST
MEASURED values in `I062/340` standing beside the calculated ones.

**All of it is the upstream system's statement about its own processing, and it is translated as a
statement.** Concretely, six things this adapter does not do, each of which would pass every check
in the harness:

1. It does not combine records. One record is one Entity and one Event; no `Track` is emitted.
2. It does not arbitrate between the altitudes. `MRH` is the tracker's opinion and §5.2.6's fourth
   NOTE says the three altitude items may be sent in parallel "independent from the value
   transmitted on I062/080 (MRH)".
3. It does not resolve `I062/340`'s measured values against the calculated ones.
4. It does not turn the contributing-sensor lists into objects or joins.
5. It does not compute the ages into instants. `I062/290` NOTE 3 gives the tracker's own formula and
   the formula is RECORDED, not applied — an instant computed here would be indistinguishable in
   the output from one the source stated.
6. It does not read any of the three callsign-shaped strings as identity.

`attributes.fusion_provenance` is where the tracker's statements are collected, under that name, so
a consumer can see whose opinion each one is.

IDENTITY: THE ADDRESS IS THE BASIS, THE TRACK NUMBER NEVER IS
--------------------------------------------------------------
`I062/380` Subfield #1's 24-bit Mode S address, filed under `ICAO24` — the same string `adsb.py`,
`asterix_cat021.py` and `asterix_cat048.py` use, so one airframe seen by four adapters derives one
`entity_id` without them coordinating. `I062/040` is mandatory in every record and is **never** the
basis: sixteen bits allocated by the emitting system and recycled would merge two airframes into one
entity, and CAT023's `I023/100` bit 2 exists in the same family precisely to announce that a
track-number space has been reused. Where no address is stated the id is scoped to the RECORD and
says so — settlement 3, and gap 27's truncation is recorded rather than papered over.

THE INJECTED CLOCK, AND THERE IS NO SECOND INJECTED VALUE
----------------------------------------------------------
`clock`, as every adapter has: `I062/070` is a count of 1/128 s since midnight with no date, so the
date comes from the injected clock and the adapter never reads the wall clock. Unlike
`asterix_cat048.py` there is NO `sensor_position` argument and no `reference_point` argument —
`I062/105` is already WGS-84, and the one item that would need a reference point is declined for the
two reasons settlement 6 gives. Accepting one anyway would create a silent authority for a
projection the specification does not pin.

NO CHECKSUM, SO THE GATE IS STRUCTURAL — AND THINNER THAN CAT034'S
-------------------------------------------------------------------
Neither §4.6 nor §4.7 nor any §5.2 item defines a CRC, checksum or parity field at any level. So the
block must satisfy LEN, the records must tile it exactly, every FSPEC bit must name a defined and
non-spare FRN, every compound item's presence bits must name a subfield that exists, every `FX` must
lead somewhere the document defines, every repetitive item's `REP` must be non-zero, and the four
unconditionally mandatory items must be present. **There is no Table 2 here** — §4.1 gives the
category one message type and §4.4 says "The Encoding Rules are contained in each Data Item" — so
unlike CAT034 there is no per-type expectation for a missing item to violate.
`attributes.integrity_basis` records that this is what passed and that it is weaker than a CRC.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any

from synapse_cdm import ids, lossless, symbology, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import cat062_codec as codec
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, Position, SourceId

#: This adapter's own system name, for `SourceRef.system`.
SYSTEM = "ASTERIX_CAT062"

#: The source id system for a 24-bit ICAO aircraft address, and the string is what matters rather
#: than the count: **every adapter here that has a 24-bit Mode S address files it under this
#: name**, so one airframe seen through any of them derives the SAME `entity_id` without them
#: coordinating. `adsb.py`, `asterix_cat021.py`, `asterix_cat048.py` and `stanag4676.py` are the
#: others today, and `tests/test_cdm_prose_counts.py` derives that set by AST rather than from a
#: list — which is why this comment names the property and the sentences that state a NUMBER are
#: checked against the derivation. That is not a join: it is a pure function of the address, and
#: it is what lets a fusion layer do the joining where the join is audited.
ICAO24_SYSTEM = "ICAO24"

#: Settlement 3's step 2. A record with no aircraft address states no airframe identity, so the id
#: is scoped to the RECORD and says so. Deliberately NOT the track number on its own: sixteen bits
#: allocated by the emitting SDPS and recycled after a track ends would merge two airframes into
#: one entity, which is a false statement in the direction nothing downstream can detect. The track
#: number IS part of the key below, which is a different thing — inside a record-scoped id it
#: distinguishes two tracks in one block and promises nothing, because the time of day is in the
#: key beside it.
REPORT_SYSTEM = "CAT062_TRACK_REPORT"

#: One octet, and this adapter speaks exactly one category.
#:
#: NO SIBLING LIST HERE, AND THAT IS DELIBERATE. `asterix_cat048.py` states the same fact as "A
#: CAT021 or CAT062 block decoded against the CAT048 UAP yields a plausible wrong aircraft rather
#: than an error", and that enumeration went stale the day CAT034 shipped — the CAT048 declines
#: table says so itself ("034 has left this list"). A comment that lists siblings acquires a defect
#: every time a sibling lands, so this one states the PROPERTY: a data block of any other ASTERIX
#: category decoded against the category 062 UAP yields a plausible wrong aircraft rather than an
#: error, because every category has its own item catalogue and its own FSPEC ceiling. The roster
#: is `adapter.roster()` and it is derived, not written down twice.
CATEGORY = 62

#: CAT (1) + LEN (2). LEN counts itself and the CAT octet, per §4.6.
BLOCK_HEADER_OCTETS = 3


class Cat062ParseError(ValueError):
    """A block this adapter refuses. Every message quotes the offending octets."""


def _refuse(message: str, data: bytes, offset: int, span: int = 8) -> Cat062ParseError:
    window = data[max(0, offset - 2):offset + span]
    return Cat062ParseError(
        f"{message} (at octet {offset} of {len(data)}; octets here: {window.hex()})"
    )


# ===================================================================== the vocabularies

#: §5.2.6 primary, bits 5/3. The source of the calculated altitude for I062/130. Parked at
#: `attributes.altitude_source` and NEVER written to `Position.position_source`: that field is about
#: the HORIZONTAL fix, and two of these eight values describe an altitude that was not measured.
SRC_TEXT: dict[int, str] = {
    0: "no source", 1: "GNSS", 2: "3D radar", 3: "triangulation",
    4: "height from coverage", 5: "speed look-up table", 6: "default height",
    7: "multilateration",
}

#: §5.2.6 second extent, bits 7/6 and 3/2. The Mode 4 and Mode 5 interrogation results.
#:
#: "Friendly target" is a VALUE here and it is not read as an affiliation. An authenticated
#: military-mode reply says a cryptographic exchange succeeded; reading it as FRIENDLY is an
#: IDENTIFICATION DECISION, which is a fusion judgement and not a fact on a wire. The CAT021
#: refusal, reached again — see `_affiliation_basis`.
MILITARY_MODE_TEXT: dict[int, str] = {
    0: "No interrogation", 1: "Friendly target", 2: "Unknown target", 3: "No reply",
}

#: §5.2.6 fourth extent, bits 8/7.
SDS_TEXT: dict[int, str] = {
    0: "Combined", 1: "Co-operative only", 2: "Non-Cooperative only", 3: "Not defined",
}

#: §5.2.6 fourth extent, bits 6/4 — Emergency Status Indication. One of the three fields in this
#: category that raise severity, and the ONLY one whose eight values the core specification
#: defines directly.
EMS_TEXT: dict[int, str] = {
    0: "No emergency", 1: "General emergency", 2: "Lifeguard / medical", 3: "Minimum fuel",
    4: "No communications", 5: "Unlawful interference", 6: "“Downed” Aircraft",
    7: "Undefined",
}

#: §5.2.6's own back-mapping table, transcribed. It appears TWICE in the document — once under
#: I062/080's EMS and once under I062/380 SF#11's STAT — in the same eight rows, and it is what
#: makes the core items LOSSY on ADS-B Version 3 equipment: `2` and both distress values collapse.
#: Carried so that a consumer meeting only the core item can see what may have been lost.
PS3_BACK_MAPPING: dict[int, int] = {0: 0, 1: 1, 2: 4, 3: 3, 4: 4, 5: 5, 6: 1, 7: 1}

#: Appendix A §2.7 Subfield #1, bits 7/5. The ADS-B Version 3 priority status, and the three values
#: with no representation in the core items at all are 2, 6 and 7.
PS3_TEXT: dict[int, str] = {
    0: "No emergency / not reported", 1: "General emergency", 2: "UAS/RPAS - Lost Link",
    3: "Minimum fuel", 4: "No communications", 5: "Unlawful interference",
    6: "Aircraft in Distress - Automatic Activation",
    7: "Aircraft in Distress - Manual Activation",
}

#: The emergency values that raise `Event.severity`, keyed by the value the two vocabularies share.
#: `EMS` and `PS3` agree on 0, 1, 3, 4 and 5 and differ on 2, 6 and 7, so the table is per
#: vocabulary and the two are never merged.
_EMS_SEVERITY: dict[int, Severity] = {
    0: Severity.INFO, 1: Severity.CRITICAL, 2: Severity.WARNING, 3: Severity.WARNING,
    4: Severity.WARNING, 5: Severity.CRITICAL, 6: Severity.CRITICAL, 7: Severity.ADVISORY,
}
_PS3_SEVERITY: dict[int, Severity] = {
    0: Severity.INFO, 1: Severity.CRITICAL, 2: Severity.WARNING, 3: Severity.WARNING,
    4: Severity.WARNING, 5: Severity.CRITICAL, 6: Severity.CRITICAL, 7: Severity.CRITICAL,
}

#: Ordered worst-first, so "the more severe of two statements" is a lookup rather than a comparison
#: somebody has to get the direction of right.
_SEVERITY_ORDER = (Severity.CRITICAL, Severity.WARNING, Severity.ADVISORY, Severity.INFO)

#: §5.2.15's four two-bit fields. The tracker's own classification of the motion, parked and never
#: used to sign or modify a number the same record states.
MODE_OF_MOVEMENT_TEXT: dict[str, dict[int, str]] = {
    "trans": {0: "Constant Course", 1: "Right Turn", 2: "Left Turn", 3: "Undetermined"},
    "long": {0: "Constant Groundspeed", 1: "Increasing Groundspeed",
             2: "Decreasing Groundspeed", 3: "Undetermined"},
    "vert": {0: "Level", 1: "Climb", 2: "Descent", 3: "Undetermined"},
}

#: §5.2.18's STI, bits 56/55. `11` is spelled "Invalid" by the item itself.
STI_TEXT: dict[int, str] = {
    0: "Callsign or registration downlinked from target", 1: "Callsign not downlinked from target",
    2: "Registration not downlinked from target", 3: "Invalid",
}

#: The ICAO Annex 10 Vol. IV Table 3-8 six-bit alphabet, as `I062/245` and `I062/380` Subfield #2
#: both use it. Index is the six-bit value; "#" marks a code the alphabet does not define, kept
#: visible rather than cleaned away for the reason `adsb.py` keeps it.
#:
#: NOT IMPORTED FROM `asterix_cat021.py`, and the reason is the citation rather than the bytes.
#: §5.2.18's NOTE 1 cites the coding to "section 3.1.2.9 of [Ref. 3]" and §5.2.24 Subfield #2 cites
#: it to "[3] Section 3.1.2.9.1.2 and Table 3-9" — the same alphabet, two different section
#: numbers, and [Ref. 3] is ICAO Document 4444, which is the PANS-ATM procedures document and not
#: where the alphabet lives. It is in ICAO Annex 10 Vol. IV, which is [Ref. 2] in this document's
#: own list. So the table below is the sibling's table under the sibling's provenance, restated
#: here because this document's two citations to it are both wrong and differ from each other.
#: FORMAT_COVERAGE.md ambiguity 6.
IDENTIFICATION_ALPHABET = (
    "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####"
    " ###############0123456789######"
)
IDENTIFICATION_UNDEFINED = "#"

#: §5.2.22's Vehicle Fleet Identification. Seventeen values, every one of them a ground vehicle, so
#: the item refines `entity_type` to PLATFORM and refines nothing else — `7` and `8` are NOT read as
#: an affiliation or a severity, which is the GMTIF platform-type refusal reached again.
VFI_TEXT: dict[int, str] = {
    0: "Unknown type of vehicle", 1: "ATC equipment maintenance", 2: "Airport maintenance",
    3: "Fire", 4: "Bird scarer", 5: "Snow plough", 6: "Runway sweeper", 7: "Emergency",
    8: "Police", 9: "Bus", 10: "Tug (push/tow)", 11: "Grass cutter", 12: "Fuel", 13: "Baggage",
    14: "Catering", 15: "Aircraft maintenance", 16: "Flyco (follow me)",
}

#: §5.2.24 Subfield #21's Emitter Category, transcribed with the document's own wording including
#: its reserved rows. The ONE item that refines `entity_type` beyond the default, and the
#: refinement is coarse on purpose — see `_entity_type`.
ECAT_TEXT: dict[int, str] = {
    1: "light aircraft <= 7000 kg", 2: "reserved",
    3: "7000 kg < medium aircraft < 136000 kg", 4: "reserved",
    5: "136000 kg <= heavy aircraft",
    6: "highly manoeuvrable (5g acceleration capability) and high speed (>400 knots cruise)",
    7: "reserved", 8: "reserved", 9: "reserved",
    10: "rotocraft", 11: "glider / sailplane", 12: "lighter-than-air",
    13: "unmanned aerial vehicle", 14: "space / transatmospheric vehicle",
    15: "ultralight / handglider / paraglider", 16: "parachutist / skydiver",
    17: "reserved", 18: "reserved", 19: "reserved",
    20: "surface emergency vehicle", 21: "surface service vehicle",
    22: "fixed ground or tethered obstruction", 23: "reserved", 24: "reserved",
}

#: The emitter categories that are NOT aircraft. 20 and 21 are vehicles and 22 is an obstruction,
#: and only the third of the three changes the entity type away from PLATFORM.
_ECAT_FACILITY = frozenset({22})

#: §5.2.24 Subfield #9's Point Type, twelve values with the document's own LT/VT annotations.
POINT_TYPE_TEXT: dict[int, str] = {
    0: "Unknown", 1: "Fly by waypoint (LT)", 2: "Fly over waypoint (LT)", 3: "Hold pattern (LT)",
    4: "Procedure hold (LT)", 5: "Procedure turn (LT)", 6: "RF leg (LT)", 7: "Top of climb (VT)",
    8: "Top of descent (VT)", 9: "Start of level (VT)", 10: "Cross-over altitude (VT)",
    11: "Transition altitude (VT)",
}

#: §5.2.24 Subfield #10's COM and STAT. `5` to `7` of COM are "Not assigned"; STAT's `6` is "Not
#: defined" and `7` is "Unknown or not yet extracted" — two different non-statements, kept apart.
COM_CAPABILITY_TEXT: dict[int, str] = {
    0: "No communications capability (surveillance only)", 1: "Comm. A and Comm. B capability",
    2: "Comm. A, Comm. B and Uplink ELM", 3: "Comm. A, Comm. B, Uplink ELM and Downlink ELM",
    4: "Level 5 Transponder capability", 5: "Not assigned", 6: "Not assigned", 7: "Not assigned",
}
FLIGHT_STATUS_TEXT: dict[int, str] = {
    0: "No alert, no SPI, aircraft airborne", 1: "No alert, no SPI, aircraft on ground",
    2: "Alert, no SPI, aircraft airborne", 3: "Alert, no SPI, aircraft on ground",
    4: "Alert, SPI, aircraft airborne or on ground",
    5: "No alert, SPI, aircraft airborne or on ground", 6: "Not defined",
    7: "Unknown or not yet extracted",
}

#: §5.2.24 Subfield #11's three two-bit operational-status fields, all with the same four values.
ADSB_OPERATIONAL_TEXT: dict[str, dict[int, str]] = {
    "ac": {0: "unknown", 1: "ACAS not operational", 2: "ACAS operational", 3: "invalid"},
    "mn": {0: "unknown", 1: "Multiple navigational aids not operating",
           2: "Multiple navigational aids operating", 3: "invalid"},
    "dc": {0: "unknown", 1: "Differential correction", 2: "No differential correction",
           3: "invalid"},
}

#: §5.2.24 Subfield #16's Turn Indicator.
TURN_INDICATOR_TEXT: dict[int, str] = {
    0: "Not available", 1: "Left", 2: "Right", 3: "Straight",
}

#: §5.2.24 Subfield #6's Selected Altitude source. `SAS` = 0 makes this field NOT A STATEMENT —
#: "No source information provided" — which is a different fact from `Source` = 0 "Unknown", and the
#: item distinguishes them.
SELECTED_ALTITUDE_SOURCE_TEXT: dict[int, str] = {
    0: "Unknown", 1: "Aircraft Altitude", 2: "FCU/MCP Selected Altitude",
    3: "FMS Selected Altitude",
}

#: §5.2.23 Subfield #6's Report Type.
MEASURED_TYP_TEXT: dict[int, str] = {
    0: "No detection", 1: "Single PSR detection", 2: "Single SSR detection",
    3: "SSR + PSR detection", 4: "Single ModeS All-Call", 5: "Single ModeS Roll-Call",
    6: "ModeS All-Call + PSR", 7: "ModeS Roll-Call +PSR",
}

#: §5.2.25 Subfield #4's four fields.
FLIGHT_CATEGORY_TEXT: dict[str, dict[int, str]] = {
    "gat_oat": {0: "Unknown", 1: "General Air Traffic", 2: "Operational Air Traffic",
                3: "Not applicable"},
    "fr": {0: "Instrument Flight Rules", 1: "Visual Flight rules", 2: "Not applicable",
           3: "Controlled Visual Flight Rules"},
    "rvsm": {0: "Unknown", 1: "Approved", 2: "Exempt", 3: "Not Approved"},
}

#: §5.2.25 Subfield #3's TYP.
IFPS_TYP_TEXT: dict[int, str] = {
    0: "Plan Number", 1: "Unit 1 internal flight number", 2: "Unit 2 internal flight number",
    3: "Unit 3 internal flight number",
}

#: §5.2.25 Subfield #6's Wake Turbulence Category, and the document says "should be one of the
#: following values" rather than "shall", so a fifth character is recorded rather than refused.
WTC_TEXT: dict[str, str] = {"L": "Light", "M": "Medium", "H": "Heavy", "J": "“Super”"}

#: §5.2.25 Subfield #12's TYP — fourteen values, and NOTE says which are the flight plan's and
#: which are the FUSION SYSTEM's: "Estimated times are derived from flight plan systems. Predicted
#: times are derived by the fusion system, based on surveillance data." Settlement 1's authorship
#: distinction inside one subfield.
TOD_TYP_TEXT: dict[int, str] = {
    0: "Scheduled off-block time", 1: "Estimated off-block time", 2: "Estimated take-off time",
    3: "Actual off-block time", 4: "Predicted time at runway hold",
    5: "Actual time at runway hold", 6: "Actual line-up time", 7: "Actual take-off time",
    8: "Estimated time of arrival", 9: "Predicted landing time", 10: "Actual landing time",
    11: "Actual time off runway", 12: "Predicted time to gate", 13: "Actual on-block time",
}

#: Which of those the fusion system produces, read off the NOTE rather than kept as a second list.
_PREDICTED_TODS = frozenset({4, 9, 12})

#: §5.2.25 Subfield #12's DAY.
TOD_DAY_TEXT: dict[int, str] = {0: "Today", 1: "Yesterday", 2: "Tomorrow", 3: "Invalid"}

#: §5.2.25 Subfield #14's two fields.
STAND_STATUS_TEXT: dict[str, dict[int, str]] = {
    "emp": {0: "Empty", 1: "Occupied", 2: "Unknown", 3: "Invalid"},
    "avl": {0: "Available", 1: "Not available", 2: "Unknown", 3: "Invalid"},
}

#: Appendix A §2.3 and §2.4's TYP, ten defined values and a reserved range.
REF_SENSOR_TYP_TEXT: dict[int, str] = {
    0: "No detection", 1: "Single PSR detection", 2: "Single SSR detection",
    3: "SSR+PSR detection", 4: "Single Mode S All-Call", 5: "Single Mode S Roll-Call",
    6: "Mode S All-Call + PSR", 7: "Mode S Roll-Call + PSR", 8: "ADS-B", 9: "WAM",
}

#: Appendix A §2.7 Subfield #2's four value fields.
V3_AIRCRAFT_STATUS_TEXT: dict[str, dict[int, str]] = {
    "rce": {0: "Not RCE", 1: "TABS", 2: "Reserved for future use", 3: "Other RCE"},
    "rrl": {0: "Reply Rate Limiting is not active", 1: "Reply Rate Limiting is active"},
    "tpw": {0: "Unavailable, Unknown, or less than 70 W", 1: "70 W", 2: "125 W", 3: "200W"},
    "tsi": {0: "Unknown", 1: "Transponder #1 (left/pilot side or single)",
            2: "Transponder #2 (right/co-pilot side)", 3: "Transponder #3 (auxiliary or Back-up)"},
}

#: Appendix A §2.7 Subfields #3 and #4.
V3_UAS_TEXT: dict[str, dict[int, str]] = {
    "muo": {0: "Manned Operation", 1: "Unmanned Operation"},
    "daa": {0: "No RWC Capability", 1: "RWC/RA/OCM Capability", 2: "RWC/OCM Capability",
            3: "Invalid ASTERIX Value"},
    "rwc": {0: "RWC Corrective Alert not active", 1: "RWC Corrective Alert active"},
}
V3_CASS_TEXT: dict[str, dict[int, str]] = {
    "svh": {0: "Vertical Only", 1: "Horizontal Only", 2: "Blended",
            3: "Vertical Only or Horizontal Only per intruder"},
    "catc": {0: "Active CAS (TCAS II) or no CAS", 1: "Active CAS (not TCAS II)",
             2: "Active CAS (not TCAS II) with OCM transmit capability",
             3: "Active CAS of Junior Status",
             4: "Passive CAS with 1030 TCAS Resolution Message receive capability",
             5: "Passive CAS with only OCM receive capability", 6: "Reserved for future use",
             7: "Reserved for future use"},
}

#: The four items whose own Encoding Rule reads "This Item shall be present in every ASTERIX
#: record". THE WHOLE PRESENCE GATE — §4.1 gives the category one message type and §4.4 says "The
#: Encoding Rules are contained in each Data Item", so there is no Table 2 and no per-type
#: expectation. `I062/015` is NOT here: its rule reads "This Item is optional", which a reader
#: expecting CAT023's arrangement would not guess.
ALWAYS_MANDATORY = ("I062/010", "I062/040", "I062/070", "I062/080")

#: §5.2.20 NOTE 6, §5.2.16 NOTE 2, §5.2.24 SF#16 NOTE 2 and all eight of §5.2.26's subfields say
#: it: "Maximum value means maximum value or above". So a value at the field's maximum is a FLOOR
#: and not a measurement — the AIS 102.2 kt discipline — and it is carried as the number with a
#: flag, because a consumer differentiating two saturated readings computes a zero rate of change.
AT_OR_ABOVE_MAXIMUM_NOTE = "Maximum value means maximum value or above"

#: §4.8's own list, verbatim. Two items whose MEANING the specification declines to state, deferring
#: it to a per-deployment Interface Control Document this repository cannot have.
IMPLEMENTATION_DEPENDENT = ("I062/080 (Track Status), Fifth Extension, Bit-5 (SFC)",
                            "I062/340 (Measured Information)")
IMPLEMENTATION_DEPENDENT_QUOTE = (
    "§4.8: 'Such a data item will be marked as “implementation dependent” in a "
    "note. The exact meaning of the data item shall then be described in the Interface Control "
    "Document (ICD) of the respective system. In such a case the provisions of the ICD will "
    "reflect the actual implementation of the data item.'"
)


# =========================================================================== bit helpers


def _bits(value: int, high: int, low: int) -> int:
    """Bits `high`..`low` of `value`, numbered as the document numbers them (1 = LSB)."""
    return codec.bits(value, high, low)


def _octal(twelve_bits: int) -> str:
    """Four octal digits from a twelve-bit Mode code field, A4A2A1 B4B2B1 C4C2C1 D4D2D1."""
    return "".join(str(_bits(twelve_bits, high, high - 2)) for high in (12, 9, 6, 3))


def _octal_to_raw(text: str) -> int:
    if len(text) != 4 or any(c not in "01234567" for c in text):
        raise codec.CodecError(f"{text!r} is not a four-digit octal Mode code")
    value = 0
    for digit in text:
        value = (value << 3) | int(digit)
    return value


def _characters(value: int, count: int) -> str:
    """`count` six-bit characters, most significant first, through the ICAO alphabet."""
    out = []
    for index in range(count - 1, -1, -1):
        code = (value >> (6 * index)) & 0x3F
        out.append(IDENTIFICATION_ALPHABET[code])
    return "".join(out)


def _ascii(block: bytes) -> str:
    """An ASCII field as the document describes it — left adjusted, space padded.

    Returned UNSTRIPPED. The trailing spaces are what the wire carried and the adapter parks both
    the raw form and the trimmed one, because a callsign whose padding was stripped cannot be
    re-emitted byte-exactly and a callsign that is all spaces is a real thing a flight plan system
    sends.
    """
    return "".join(chr(b) if 32 <= b < 127 else IDENTIFICATION_UNDEFINED for b in block)


# ==================================================================== the item decoders
#
# Every decoder takes exactly the octets its length rule measured and returns a dict of RAW fields
# plus every spare bit as sent. Every encoder is its inverse and writes those spare bits back
# unchanged — §4.5 "Unused Bits in Data Items" is what makes that a rule rather than a preference,
# and `build_block` proves the pair round-trips on every fixture.


def _decode_010(block: bytes) -> dict:
    return {"sac": block[0], "sic": block[1]}


def _encode_010(item: dict) -> bytes:
    return bytes([item["sac"], item["sic"]])


def _decode_015(block: bytes) -> dict:
    return {"service_identification": block[0]}


def _encode_015(item: dict) -> bytes:
    return bytes([item["service_identification"]])


def _decode_040(block: bytes) -> dict:
    return {"track_number": codec.read_unsigned(block, 0, 2)}


def _encode_040(item: dict) -> bytes:
    return codec.write_unsigned(item["track_number"], 2)


def _decode_060(block: bytes) -> dict:
    word = codec.read_unsigned(block, 0, 2)
    return {"v": _bits(word, 16, 16), "g": _bits(word, 15, 15), "ch": _bits(word, 14, 14),
            "spare_bit_13": _bits(word, 13, 13), "mode_3a": _bits(word, 12, 1)}


def _encode_060(item: dict) -> bytes:
    return codec.write_unsigned(
        (item["v"] << 15) | (item["g"] << 14) | (item["ch"] << 13)
        | (item["spare_bit_13"] << 12) | item["mode_3a"], 2)


def _decode_070(block: bytes) -> dict:
    return {"time_of_day_raw": codec.read_unsigned(block, 0, 3)}


def _encode_070(item: dict) -> bytes:
    return codec.write_unsigned(item["time_of_day_raw"], 3)


def _decode_100(block: bytes) -> dict:
    return {"x_raw": codec.read_unsigned(block, 0, 3), "y_raw": codec.read_unsigned(block, 3, 3)}


def _encode_100(item: dict) -> bytes:
    return codec.write_unsigned(item["x_raw"], 3) + codec.write_unsigned(item["y_raw"], 3)


def _decode_105(block: bytes) -> dict:
    return {"latitude_raw": codec.read_unsigned(block, 0, 4),
            "longitude_raw": codec.read_unsigned(block, 4, 4)}


def _encode_105(item: dict) -> bytes:
    return codec.write_unsigned(item["latitude_raw"], 4) + \
        codec.write_unsigned(item["longitude_raw"], 4)


def _decode_120(block: bytes) -> dict:
    word = codec.read_unsigned(block, 0, 2)
    return {"spare_bits_16_13": _bits(word, 16, 13), "mode_2": _bits(word, 12, 1)}


def _encode_120(item: dict) -> bytes:
    return codec.write_unsigned((item["spare_bits_16_13"] << 12) | item["mode_2"], 2)


def _decode_130(block: bytes) -> dict:
    return {"altitude_raw": codec.read_unsigned(block, 0, 2)}


def _encode_130(item: dict) -> bytes:
    return codec.write_unsigned(item["altitude_raw"], 2)


def _decode_135(block: bytes) -> dict:
    word = codec.read_unsigned(block, 0, 2)
    return {"qnh": _bits(word, 16, 16), "ctba_raw": _bits(word, 15, 1)}


def _encode_135(item: dict) -> bytes:
    return codec.write_unsigned((item["qnh"] << 15) | item["ctba_raw"], 2)


def _decode_136(block: bytes) -> dict:
    return {"flight_level_raw": codec.read_unsigned(block, 0, 2)}


def _encode_136(item: dict) -> bytes:
    return codec.write_unsigned(item["flight_level_raw"], 2)


def _decode_185(block: bytes) -> dict:
    return {"vx_raw": codec.read_unsigned(block, 0, 2), "vy_raw": codec.read_unsigned(block, 2, 2)}


def _encode_185(item: dict) -> bytes:
    return codec.write_unsigned(item["vx_raw"], 2) + codec.write_unsigned(item["vy_raw"], 2)


def _decode_200(block: bytes) -> dict:
    octet = block[0]
    return {"trans": _bits(octet, 8, 7), "long": _bits(octet, 6, 5), "vert": _bits(octet, 4, 3),
            "adf": _bits(octet, 2, 2), "spare_bit_1": _bits(octet, 1, 1)}


def _encode_200(item: dict) -> bytes:
    return bytes([(item["trans"] << 6) | (item["long"] << 4) | (item["vert"] << 2)
                  | (item["adf"] << 1) | item["spare_bit_1"]])


def _decode_210(block: bytes) -> dict:
    return {"ax_raw": block[0], "ay_raw": block[1]}


def _encode_210(item: dict) -> bytes:
    return bytes([item["ax_raw"], item["ay_raw"]])


def _decode_220(block: bytes) -> dict:
    return {"rate_raw": codec.read_unsigned(block, 0, 2)}


def _encode_220(item: dict) -> bytes:
    return codec.write_unsigned(item["rate_raw"], 2)


def _decode_245(block: bytes) -> dict:
    return {"sti": _bits(block[0], 8, 7), "spare_bits_54_49": _bits(block[0], 6, 1),
            "characters_raw": codec.read_unsigned(block, 1, 6)}


def _encode_245(item: dict) -> bytes:
    return bytes([(item["sti"] << 6) | item["spare_bits_54_49"]]) + \
        codec.write_unsigned(item["characters_raw"], 6)


def _decode_300(block: bytes) -> dict:
    return {"vfi": block[0]}


def _encode_300(item: dict) -> bytes:
    return bytes([item["vfi"]])


# --------------------------------------------------------------- I062/080, six extents
#
# §5.2.6. A one-octet primary and up to six one-octet extents, each chained by FX. Edition 1.21
# added the sixth ("Added Mode 5 Interrogation to I062/080"), which is why an adapter written
# against Edition 1.20 refuses a record whose fifth extent sets FX — a refusal rather than a
# misread, and the good direction to fail in.

#: (field name, high bit, low bit) per extent, in the document's own order. The primary is index 0.
_080_LAYOUT: tuple[tuple[tuple[str, int, int], ...], ...] = (
    (("mon", 8, 8), ("spi", 7, 7), ("mrh", 6, 6), ("src", 5, 3), ("cnf", 2, 2)),
    (("sim", 8, 8), ("tse", 7, 7), ("tsb", 6, 6), ("fpc", 5, 5), ("aff", 4, 4),
     ("stp", 3, 3), ("kos", 2, 2)),
    (("ama", 8, 8), ("md4", 7, 6), ("me", 5, 5), ("mi", 4, 4), ("md5", 3, 2)),
    (("cst", 8, 8), ("psr", 7, 7), ("ssr", 6, 6), ("mds", 5, 5), ("ads", 4, 4),
     ("suc", 3, 3), ("aac", 2, 2)),
    (("sds", 8, 7), ("ems", 6, 4), ("pft", 3, 3), ("fplt", 2, 2)),
    (("dupt", 8, 8), ("dupf", 7, 7), ("dupm", 6, 6), ("sfc", 5, 5), ("idd", 4, 4),
     ("iec", 3, 3), ("mlat", 2, 2)),
    (("m5i", 8, 8), ("spare_bits_7_2", 7, 2)),
)

#: The names §5.2.6 gives the seven octets, for refusal messages that a reader can match against
#: the document's own headings.
_080_NAMES = ("primary subfield", "First Extent", "Second Extent", "Third Extent",
              "Fourth Extent", "Fifth Extent", "Sixth Extent")


def _decode_080(block: bytes) -> dict:
    octets = []
    for index, octet in enumerate(block):
        parsed: dict[str, Any] = {}
        for name, high, low in _080_LAYOUT[index]:
            parsed[name] = _bits(octet, high, low)
        parsed["fx"] = _bits(octet, 1, 1)
        octets.append(parsed)
    return {"octets": octets}


def _encode_080(item: dict) -> bytes:
    out = bytearray()
    for index, parsed in enumerate(item["octets"]):
        octet = parsed["fx"]
        for name, high, low in _080_LAYOUT[index]:
            octet |= parsed[name] << (low - 1)
        out.append(octet)
    return bytes(out)


def _len_080(data: bytes, offset: int) -> int:
    """One octet per extent while FX is set, and a refusal after the sixth.

    §5.2.6 defines a primary and six extents and no seventh, so a set FX on the sixth announces
    something the document does not define: there is nothing to decode, it cannot be skipped, and
    guessing a length would desynchronise every following item. The `asterix_cat034.py`
    `_len_compound` disposition, and here it is a hole the NEWEST edition opened — every extent
    this document adds re-opens the same one at the end of the chain.
    """
    count = 0
    while True:
        if offset + count >= len(data):
            raise _refuse(
                f"I062/080's {_080_NAMES[min(count, 6)]} is past the end of the block", data,
                offset)
        octet = data[offset + count]
        count += 1
        if not octet & codec.FX:
            return count
        if count >= len(_080_LAYOUT):
            raise _refuse(
                f"I062/080's {_080_NAMES[count - 1]} sets its FX bit, but §5.2.6 defines a "
                f"primary subfield and {len(_080_LAYOUT) - 1} extents and no seventh. A seventh "
                "extent has no bits defined behind it: there is nothing to decode, so it cannot "
                "be skipped, and guessing a length would desynchronise every following item. "
                "Edition 1.21 added the Sixth Extent, so this hole is the newest edition's and "
                "every future extent re-opens it", data, offset + count - 1)


# ------------------------------------------------------------ I062/270, an FX chain of three
#
# §5.2.19. A first part carrying LENGTH, a first extent carrying ORIENTATION and a second extent
# carrying WIDTH — three octets that mean three different things, chained by FX. Not a repetition.

_270_FIELDS = ("length", "orientation", "width")


def _decode_270(block: bytes) -> dict:
    octets = []
    for index, octet in enumerate(block):
        octets.append({"field": _270_FIELDS[index], "value_raw": _bits(octet, 8, 2),
                       "fx": _bits(octet, 1, 1)})
    return {"octets": octets}


def _encode_270(item: dict) -> bytes:
    return bytes((parsed["value_raw"] << 1) | parsed["fx"] for parsed in item["octets"])


def _len_270(data: bytes, offset: int) -> int:
    count = 0
    while True:
        if offset + count >= len(data):
            raise _refuse("I062/270's next octet is past the end of the block", data, offset)
        octet = data[offset + count]
        count += 1
        if not octet & codec.FX:
            return count
        if count >= len(_270_FIELDS):
            raise _refuse(
                "I062/270's second extent sets its FX bit, but §5.2.19 defines a first part "
                "and two extents and no third. There is nothing to decode, so it cannot be "
                "skipped, and guessing a length would desynchronise every following item", data,
                offset + count - 1)


# -------------------------------------------------------- I062/510, a genuine FX repetition
#
# §5.2.27. Three octets per unit — an 8-bit System Unit Identification, a 15-bit System Track
# Number and FX — repeated. UNLIKE every other FX in this category, this chain is genuinely
# unbounded: "Structure of next Extents" is DEFINED and identical to the first part, so a set FX on
# the last extent read is legal and the item continues. That is the general ASTERIX FX semantics,
# and the reason the other FX bits refuse is that the document NAMES a continuation it does not
# define rather than that a chain cannot continue.


def _decode_510(block: bytes) -> dict:
    units = []
    for start in range(0, len(block), 3):
        unit = block[start]
        word = codec.read_unsigned(block, start + 1, 2)
        units.append({"system_unit": unit, "system_track_number": _bits(word, 16, 2),
                      "fx": _bits(word, 1, 1)})
    return {"units": units}


def _encode_510(item: dict) -> bytes:
    out = bytearray()
    for unit in item["units"]:
        out.append(unit["system_unit"])
        out += codec.write_unsigned((unit["system_track_number"] << 1) | unit["fx"], 2)
    return bytes(out)


def _len_510(data: bytes, offset: int) -> int:
    count = 0
    while True:
        if offset + count + 3 > len(data):
            raise _refuse("I062/510's next three-octet extent runs past the end of the block",
                          data, offset + count)
        count += 3
        if not data[offset + count - 1] & codec.FX:
            return count


# ======================================================= the compound items, table-driven
#
# Six items share one shape — a presence map of one to five octets with an FX at the bottom of each,
# then the present subfields in order — and one length rule and one refusal pair serve all six.
# The per-item tables below are the ONLY thing that differs, which is what makes a set spare
# presence bit refusable uniformly: in every one of the six, a spare presence bit announces a
# subfield the document does not define.

#: (subfield name, high bit, low bit) per presence octet. The bit numbers are the DOCUMENT'S
#: within-octet numbering, 8 down to 1, so bit 1 is always the FX and never a subfield.
_PRESENCE: dict[str, tuple[tuple[tuple[str, int], ...], ...]] = {
    # §5.2.9, one octet, seven subfields.
    "I062/110": ((("sum", 8), ("pmn", 7), ("pos", 6), ("ga", 5), ("em1", 4), ("tos", 3),
                  ("xp", 2)),),
    # §5.2.20, two octets, ten subfields, four spare presence bits in octet 2.
    "I062/290": ((("trk", 8), ("psr", 7), ("ssr", 6), ("mds", 5), ("ads", 4), ("es", 3),
                  ("vdl", 2)),
                 (("uat", 8), ("lop", 7), ("mlt", 6))),
    # §5.2.21, five octets, thirty-one subfields, four spare presence bits in octet 5.
    "I062/295": ((("mfl", 8), ("md1", 7), ("md2", 6), ("mda", 5), ("md4", 4), ("md5", 3),
                  ("mhg", 2)),
                 (("ias", 8), ("tas", 7), ("sal", 6), ("fss", 5), ("tid", 4), ("com", 3),
                  ("sab", 2)),
                 (("acs", 8), ("bvr", 7), ("gvr", 6), ("ran", 5), ("tar", 4), ("tan", 3),
                  ("gsp", 2)),
                 (("vun", 8), ("met", 7), ("emc", 6), ("pos", 5), ("gal", 4), ("pun", 3),
                  ("mb", 2)),
                 (("iar", 8), ("mac", 7), ("bps", 6))),
    # §5.2.23, one octet, six subfields, one spare presence bit.
    "I062/340": ((("sid", 8), ("pos", 7), ("hei", 6), ("mdc", 5), ("mda", 4), ("typ", 3)),),
    # §5.2.24, four octets, twenty-eight subfields, no spare presence bits at all.
    "I062/380": ((("adr", 8), ("id", 7), ("mhg", 6), ("ias", 5), ("tas", 4), ("sal", 3),
                  ("fss", 2)),
                 (("tis", 8), ("tid", 7), ("com", 6), ("sab", 5), ("acs", 4), ("bvr", 3),
                  ("gvr", 2)),
                 (("ran", 8), ("tar", 7), ("tan", 6), ("gsp", 5), ("vun", 4), ("met", 3),
                  ("emc", 2)),
                 (("pos", 8), ("gal", 7), ("pun", 6), ("mb", 5), ("iar", 4), ("mac", 3),
                  ("bps", 2))),
    # §5.2.25, three octets, eighteen subfields, three spare presence bits in octet 3.
    "I062/390": ((("tag", 8), ("csn", 7), ("ifi", 6), ("fct", 5), ("tac", 4), ("wtc", 3),
                  ("dep", 2)),
                 (("dst", 8), ("rds", 7), ("cfl", 6), ("ctl", 5), ("tod", 4), ("ast", 3),
                  ("sts", 2)),
                 (("std", 8), ("sta", 7), ("pem", 6), ("pec", 5))),
    # §5.2.26, two octets, eight subfields, six spare presence bits in octet 2.
    "I062/500": ((("apc", 8), ("cov", 7), ("apw", 6), ("aga", 5), ("aba", 4), ("atv", 3),
                  ("aa", 2)),
                 (("arc", 8),)),
}

#: §5.2 locus per compound item, for refusal messages.
_COMPOUND_LOCUS = {"I062/110": "§5.2.9", "I062/290": "§5.2.20",
                   "I062/295": "§5.2.21", "I062/340": "§5.2.23",
                   "I062/380": "§5.2.24", "I062/390": "§5.2.25",
                   "I062/500": "§5.2.26"}


def _spare_presence_mask(octet_layout: tuple[tuple[str, int], ...]) -> int:
    """Bits 8..2 of a presence octet that no subfield claims. Bit 1 is the FX and is excluded."""
    claimed = {bit for _name, bit in octet_layout}
    mask = 0
    for bit in range(2, 9):
        if bit not in claimed:
            mask |= 1 << (bit - 1)
    return mask


def _read_presence(item: str, data: bytes, offset: int) -> tuple[list[str], int]:
    """The present subfield names in order, and how many presence octets were consumed.

    Two refusals, and both are `asterix_cat034.py`'s `_len_compound` disposition reached again.

    **FX on the last defined presence octet.** The item's own §5.2 entry defines exactly as many
    presence octets as its subfields need, so a further octet has no subfields behind it.

    **A set SPARE presence bit.** In all six compound items the unclaimed bits of a presence octet
    are spares — `I062/290` octet 2 bits 5/2, `I062/295` octet 5 bits 5/2, `I062/340` bit 2,
    `I062/390` octet 3 bits 4/2, `I062/500` octet 2 bits 7/2 — and a set one claims a subfield the
    document does not define. `I062/380` has none, which is why the check has to be derived from
    the layout rather than written out per item.
    """
    layout = _PRESENCE[item]
    locus = _COMPOUND_LOCUS[item]
    present: list[str] = []
    for index, octet_layout in enumerate(layout):
        if offset + index >= len(data):
            raise _refuse(f"{item}'s presence octet {index + 1} is past the end of the block",
                          data, offset)
        octet = data[offset + index]
        spare = _spare_presence_mask(octet_layout)
        if octet & spare:
            raise _refuse(
                f"{item}'s presence octet {index + 1} (0x{octet:02X}) sets a bit that "
                f"{locus} marks spare (mask 0x{spare:02X}). A spare presence bit claims a "
                "subfield the document does not define: there is nothing to decode, so it cannot "
                "be skipped, and guessing a length would desynchronise every following item",
                data, offset + index)
        for name, bit in octet_layout:
            if octet & (1 << (bit - 1)):
                present.append(name)
        if not octet & codec.FX:
            return present, index + 1
        if index + 1 >= len(layout):
            raise _refuse(
                f"{item}'s presence octet {len(layout)} sets its FX bit, but {locus} defines "
                f"{sum(len(o) for o in layout)} subfields in exactly {len(layout)} presence "
                "octet(s). A further presence octet has no subfields behind it: there is nothing "
                "to decode, so it cannot be skipped, and guessing a length would desynchronise "
                "every following item", data, offset + index)
    raise _refuse(f"{item}'s presence map did not terminate", data, offset)


# --------------------------------------------------------------- the compound subfields
#
# Each entry is (fixed length) or a callable measuring a variable-length one. `None` marks a
# subfield whose length depends on its own contents.

def _fixed_ages(names: tuple[str, ...], width: int = 1) -> dict[str, Any]:
    return {name: width for name in names}


#: Every subfield's octet length. §5.2's own figures, item by item — the UAP's fourth column is
#: never read, because it gives `1+` to four structurally different mechanics.
_SUBFIELD_OCTETS: dict[str, dict[str, Any]] = {
    "I062/110": {"sum": 1, "pmn": 4, "pos": 6, "ga": 2, "em1": 2, "tos": 1, "xp": 1},
    "I062/290": {"trk": 1, "psr": 1, "ssr": 1, "mds": 1,
                 # THE ONE NON-UNIFORM SUBFIELD IN THE ITEM, and the most dangerous uniformity
                 # assumption in the category: "Max. value = 16383.75s (> 4 hours)" needs two
                 # octets where the other nine need one. A decoder that read it as one would
                 # desynchronise the record with no length error anywhere, and Edition 1.21's
                 # change record says "Length of I062/290/SI#5 corrected" — so an earlier edition
                 # got exactly this wrong.
                 "ads": 2,
                 "es": 1, "vdl": 1, "uat": 1, "lop": 1, "mlt": 1},
    # All thirty-one are one octet at 1/4 s. Generated rather than written out, because
    # thirty-one hand-typed `1`s is thirty-one chances to type a `2`.
    "I062/295": _fixed_ages(tuple(name for octet in _PRESENCE["I062/295"] for name, _ in octet)),
    "I062/340": {"sid": 2, "pos": 4, "hei": 2, "mdc": 2, "mda": 2, "typ": 1},
    "I062/380": {"adr": 3, "id": 6, "mhg": 2, "ias": 2, "tas": 2, "sal": 2, "fss": 2,
                 "tis": None, "tid": None, "com": 2, "sab": 2, "acs": 7, "bvr": 2, "gvr": 2,
                 "ran": 2, "tar": 2, "tan": 2, "gsp": 2, "vun": 1, "met": 8, "emc": 1,
                 "pos": 6, "gal": 2, "pun": 1, "mb": None, "iar": 2, "mac": 2, "bps": 2},
    "I062/390": {"tag": 2, "csn": 7, "ifi": 4, "fct": 1, "tac": 4, "wtc": 1, "dep": 4,
                 "dst": 4, "rds": 3, "cfl": 2, "ctl": 2, "tod": None, "ast": 6, "sts": 1,
                 "std": 7, "sta": 7, "pem": 2, "pec": 7},
    "I062/500": {"apc": 4, "cov": 2, "apw": 4, "aga": 1, "aba": 1, "atv": 2, "aa": 2, "arc": 1},
}


def _len_variable_subfield(item: str, name: str, data: bytes, offset: int) -> int:
    """The three subfields whose length is a function of their own contents.

    `I062/380` SF#8 is a one-octet FX chain with no extent defined, so a set FX refuses.
    `I062/380` SF#9 and SF#25 and `I062/390` SF#12 are repetitive, and each one's Format says "at
    least one", so a REP of 0 is excluded by the item's own words — the `I034/070` disposition.
    """
    if item == "I062/380" and name == "tis":
        if offset >= len(data):
            raise _refuse("I062/380 Subfield #8 is past the end of the block", data, offset)
        if data[offset] & codec.FX:
            raise _refuse(
                "I062/380 Subfield #8 sets its FX bit, documented as 'Extension into next "
                "extent', and §5.2.24 defines no extent for this subfield. There is nothing "
                "to decode, so it cannot be skipped", data, offset)
        return 1
    if item == "I062/380" and name == "tid":
        return _repetitive(data, offset, 15, "I062/380 Subfield #9",
                           "at least one Trajectory Intent Point comprising fifteen octets")
    if item == "I062/380" and name == "mb":
        return _repetitive(data, offset, 8, "I062/380 Subfield #25",
                           "at least one BDS report comprising one seven octet BDS register and "
                           "one octet BDS code")
    if item == "I062/390" and name == "tod":
        return _repetitive(data, offset, 4, "I062/390 Subfield #12",
                           "a one-octet Field Repetition Indicator (REP) followed by the "
                           "four-octet entries")
    raise Cat062ParseError(f"no variable length rule for {item} subfield {name!r}")


def _repetitive(data: bytes, offset: int, element: int, label: str, quoted: str) -> int:
    if offset >= len(data):
        raise _refuse(f"{label}'s REP octet is past the end of the block", data, offset)
    rep = data[offset]
    if rep == 0:
        raise _refuse(
            f"{label} states REP = 0. Its Format is '{quoted}', so a zero-length repetition is "
            "excluded by the subfield's own words — and a subfield whose presence bit is set and "
            "whose content is empty is not an empty list, it is a record whose presence map and "
            "body disagree", data, offset)
    return 1 + element * rep


def _len_compound(item: str):
    def rule(data: bytes, offset: int) -> int:
        present, consumed = _read_presence(item, data, offset)
        total = consumed
        for name in present:
            stated = _SUBFIELD_OCTETS[item][name]
            if stated is None:
                total += _len_variable_subfield(item, name, data, offset + total)
            else:
                total += stated
        return total
    return rule


def _decode_compound(item: str):
    def decode(block: bytes) -> dict:
        present, consumed = _read_presence(item, block, 0)
        parsed: dict[str, Any] = {"presence": block[:consumed].hex(), "subfields": {}}
        at = consumed
        for name in present:
            stated = _SUBFIELD_OCTETS[item][name]
            length = (_len_variable_subfield(item, name, block, at) if stated is None else stated)
            parsed["subfields"][name] = _SUBFIELD_DECODERS[item][name](block[at:at + length])
            at += length
        return parsed
    return decode


def _encode_compound(item: str):
    def encode(parsed: dict) -> bytes:
        presence = bytes.fromhex(parsed["presence"])
        order, _consumed = _read_presence(item, presence, 0)
        out = bytearray(presence)
        for name in order:
            out += _SUBFIELD_ENCODERS[item][name](parsed["subfields"][name])
        return bytes(out)
    return encode


# --------------------------------------------------------- I062/110's seven subfields


def _d110_sum(b: bytes) -> dict:
    o = b[0]
    return {"m5": _bits(o, 8, 8), "id": _bits(o, 7, 7), "da": _bits(o, 6, 6),
            "m1": _bits(o, 5, 5), "m2": _bits(o, 4, 4), "m3": _bits(o, 3, 3),
            "mc": _bits(o, 2, 2), "x": _bits(o, 1, 1)}


def _e110_sum(s: dict) -> bytes:
    return bytes([(s["m5"] << 7) | (s["id"] << 6) | (s["da"] << 5) | (s["m1"] << 4)
                  | (s["m2"] << 3) | (s["m3"] << 2) | (s["mc"] << 1) | s["x"]])


def _d110_pmn(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 4)
    return {"spare_bits_32_31": _bits(w, 32, 31), "pin": _bits(w, 30, 17),
            "spare_bits_16_14": _bits(w, 16, 14), "nat": _bits(w, 13, 9),
            "spare_bits_8_7": _bits(w, 8, 7), "mis": _bits(w, 6, 1)}


def _e110_pmn(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["spare_bits_32_31"] << 30) | (s["pin"] << 16) | (s["spare_bits_16_14"] << 13)
        | (s["nat"] << 8) | (s["spare_bits_8_7"] << 6) | s["mis"], 4)


def _d110_pos(b: bytes) -> dict:
    return {"latitude_raw": codec.read_unsigned(b, 0, 3),
            "longitude_raw": codec.read_unsigned(b, 3, 3)}


def _e110_pos(s: dict) -> bytes:
    return codec.write_unsigned(s["latitude_raw"], 3) + codec.write_unsigned(s["longitude_raw"], 3)


def _d110_ga(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"spare_bit_16": _bits(w, 16, 16), "res": _bits(w, 15, 15), "ga_raw": _bits(w, 14, 1)}


def _e110_ga(s: dict) -> bytes:
    return codec.write_unsigned((s["spare_bit_16"] << 15) | (s["res"] << 14) | s["ga_raw"], 2)


def _d110_em1(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"spare_bits_16_13": _bits(w, 16, 13), "extended_mode_1": _bits(w, 12, 1)}


def _e110_em1(s: dict) -> bytes:
    return codec.write_unsigned((s["spare_bits_16_13"] << 12) | s["extended_mode_1"], 2)


def _d110_tos(b: bytes) -> dict:
    return {"tos_raw": b[0]}


def _e110_tos(s: dict) -> bytes:
    return bytes([s["tos_raw"]])


def _d110_xp(b: bytes) -> dict:
    o = b[0]
    return {"spare_bits_8_6": _bits(o, 8, 6), "x5": _bits(o, 5, 5), "xc": _bits(o, 4, 4),
            "x3": _bits(o, 3, 3), "x2": _bits(o, 2, 2), "x1": _bits(o, 1, 1)}


def _e110_xp(s: dict) -> bytes:
    return bytes([(s["spare_bits_8_6"] << 5) | (s["x5"] << 4) | (s["xc"] << 3) | (s["x3"] << 2)
                  | (s["x2"] << 1) | s["x1"]])


# ------------------------------------------------- the ages: one decoder for forty-one fields


def _d_age1(b: bytes) -> dict:
    return {"age_raw": b[0]}


def _e_age1(s: dict) -> bytes:
    return bytes([s["age_raw"]])


def _d_age2(b: bytes) -> dict:
    return {"age_raw": codec.read_unsigned(b, 0, 2)}


def _e_age2(s: dict) -> bytes:
    return codec.write_unsigned(s["age_raw"], 2)


# ----------------------------------------------------------- I062/340's six subfields


def _d340_sid(b: bytes) -> dict:
    return {"sac": b[0], "sic": b[1]}


def _e340_sid(s: dict) -> bytes:
    return bytes([s["sac"], s["sic"]])


def _d340_pos(b: bytes) -> dict:
    return {"rho_raw": codec.read_unsigned(b, 0, 2), "theta_raw": codec.read_unsigned(b, 2, 2)}


def _e340_pos(s: dict) -> bytes:
    return codec.write_unsigned(s["rho_raw"], 2) + codec.write_unsigned(s["theta_raw"], 2)


def _d340_hei(b: bytes) -> dict:
    return {"height_raw": codec.read_unsigned(b, 0, 2)}


def _e340_hei(s: dict) -> bytes:
    return codec.write_unsigned(s["height_raw"], 2)


def _d340_mdc(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"v": _bits(w, 16, 16), "g": _bits(w, 15, 15), "mode_c_raw": _bits(w, 14, 1)}


def _e340_mdc(s: dict) -> bytes:
    return codec.write_unsigned((s["v"] << 15) | (s["g"] << 14) | s["mode_c_raw"], 2)


def _d340_mda(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"v": _bits(w, 16, 16), "g": _bits(w, 15, 15), "l": _bits(w, 14, 14),
            "spare_bit_13": _bits(w, 13, 13), "mode_3a": _bits(w, 12, 1)}


def _e340_mda(s: dict) -> bytes:
    return codec.write_unsigned((s["v"] << 15) | (s["g"] << 14) | (s["l"] << 13)
                                | (s["spare_bit_13"] << 12) | s["mode_3a"], 2)


def _d340_typ(b: bytes) -> dict:
    o = b[0]
    return {"typ": _bits(o, 8, 6), "sim": _bits(o, 5, 5), "rab": _bits(o, 4, 4),
            "tst": _bits(o, 3, 3), "spare_bits_2_1": _bits(o, 2, 1)}


def _e340_typ(s: dict) -> bytes:
    return bytes([(s["typ"] << 5) | (s["sim"] << 4) | (s["rab"] << 3) | (s["tst"] << 2)
                  | s["spare_bits_2_1"]])


# ------------------------------------------------------ I062/380's twenty-eight subfields


def _d380_adr(b: bytes) -> dict:
    return {"address": codec.read_unsigned(b, 0, 3)}


def _e380_adr(s: dict) -> bytes:
    return codec.write_unsigned(s["address"], 3)


def _d380_id(b: bytes) -> dict:
    return {"characters_raw": codec.read_unsigned(b, 0, 6)}


def _e380_id(s: dict) -> bytes:
    return codec.write_unsigned(s["characters_raw"], 6)


def _d_word(field: str):
    def decode(b: bytes) -> dict:
        return {field: codec.read_unsigned(b, 0, 2)}
    return decode


def _e_word(field: str):
    def encode(s: dict) -> bytes:
        return codec.write_unsigned(s[field], 2)
    return encode


def _d_octet(field: str):
    def decode(b: bytes) -> dict:
        return {field: b[0]}
    return decode


def _e_octet(field: str):
    def encode(s: dict) -> bytes:
        return bytes([s[field]])
    return encode


def _d380_ias(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"im": _bits(w, 16, 16), "air_speed_raw": _bits(w, 15, 1)}


def _e380_ias(s: dict) -> bytes:
    return codec.write_unsigned((s["im"] << 15) | s["air_speed_raw"], 2)


def _d380_sal(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"sas": _bits(w, 16, 16), "source": _bits(w, 15, 14), "altitude_raw": _bits(w, 13, 1)}


def _e380_sal(s: dict) -> bytes:
    return codec.write_unsigned((s["sas"] << 15) | (s["source"] << 13) | s["altitude_raw"], 2)


def _d380_fss(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"mv": _bits(w, 16, 16), "ah": _bits(w, 15, 15), "am": _bits(w, 14, 14),
            "altitude_raw": _bits(w, 13, 1)}


def _e380_fss(s: dict) -> bytes:
    return codec.write_unsigned((s["mv"] << 15) | (s["ah"] << 14) | (s["am"] << 13)
                                | s["altitude_raw"], 2)


def _d380_tis(b: bytes) -> dict:
    o = b[0]
    return {"nav": _bits(o, 8, 8), "nvb": _bits(o, 7, 7), "spare_bits_6_2": _bits(o, 6, 2),
            "fx": _bits(o, 1, 1)}


def _e380_tis(s: dict) -> bytes:
    return bytes([(s["nav"] << 7) | (s["nvb"] << 6) | (s["spare_bits_6_2"] << 1) | s["fx"]])


def _d380_tid(b: bytes) -> dict:
    rep = b[0]
    points = []
    for index in range(rep):
        at = 1 + 15 * index
        first = b[at]
        altitude = codec.read_unsigned(b, at + 1, 2)
        latitude = codec.read_unsigned(b, at + 3, 3)
        longitude = codec.read_unsigned(b, at + 6, 3)
        tail = codec.read_unsigned(b, at + 9, 4)
        ttr = codec.read_unsigned(b, at + 13, 2)
        points.append({
            "tca": _bits(first, 8, 8), "nc": _bits(first, 7, 7), "tcp_number": _bits(first, 6, 1),
            "altitude_raw": altitude, "latitude_raw": latitude, "longitude_raw": longitude,
            "point_type": _bits(tail, 32, 29), "td": _bits(tail, 28, 27),
            "tra": _bits(tail, 26, 26), "toa": _bits(tail, 25, 25), "tov_raw": _bits(tail, 24, 1),
            "ttr_raw": ttr,
        })
    return {"rep": rep, "points": points}


def _e380_tid(s: dict) -> bytes:
    out = bytearray([s["rep"]])
    for point in s["points"]:
        out.append((point["tca"] << 7) | (point["nc"] << 6) | point["tcp_number"])
        out += codec.write_unsigned(point["altitude_raw"], 2)
        out += codec.write_unsigned(point["latitude_raw"], 3)
        out += codec.write_unsigned(point["longitude_raw"], 3)
        out += codec.write_unsigned(
            (point["point_type"] << 28) | (point["td"] << 26) | (point["tra"] << 25)
            | (point["toa"] << 24) | point["tov_raw"], 4)
        out += codec.write_unsigned(point["ttr_raw"], 2)
    return bytes(out)


def _d380_com(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"com": _bits(w, 16, 14), "stat": _bits(w, 13, 11),
            "spare_bits_10_9": _bits(w, 10, 9), "ssc": _bits(w, 8, 8), "arc": _bits(w, 7, 7),
            "aic": _bits(w, 6, 6), "b1a": _bits(w, 5, 5), "b1b": _bits(w, 4, 1)}


def _e380_com(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["com"] << 13) | (s["stat"] << 10) | (s["spare_bits_10_9"] << 8) | (s["ssc"] << 7)
        | (s["arc"] << 6) | (s["aic"] << 5) | (s["b1a"] << 4) | s["b1b"], 2)


def _d380_sab(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"ac": _bits(w, 16, 15), "mn": _bits(w, 14, 13), "dc": _bits(w, 12, 11),
            "gbs": _bits(w, 10, 10), "spare_bits_9_4": _bits(w, 9, 4), "stat": _bits(w, 3, 1)}


def _e380_sab(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["ac"] << 14) | (s["mn"] << 12) | (s["dc"] << 10) | (s["gbs"] << 9)
        | (s["spare_bits_9_4"] << 3) | s["stat"], 2)


def _d380_acs(b: bytes) -> dict:
    return {"acas_ra": b.hex()}


def _e380_acs(s: dict) -> bytes:
    return bytes.fromhex(s["acas_ra"])


def _d380_tar(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"ti": _bits(w, 16, 15), "spare_bits_14_9": _bits(w, 14, 9),
            "rate_of_turn_raw": _bits(w, 8, 2), "spare_bit_1": _bits(w, 1, 1)}


def _e380_tar(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["ti"] << 14) | (s["spare_bits_14_9"] << 8) | (s["rate_of_turn_raw"] << 1)
        | s["spare_bit_1"], 2)


def _d380_met(b: bytes) -> dict:
    flags = b[0]
    return {"ws": _bits(flags, 8, 8), "wd": _bits(flags, 7, 7), "tmp": _bits(flags, 6, 6),
            "trb": _bits(flags, 5, 5), "spare_bits_60_57": _bits(flags, 4, 1),
            "wind_speed_raw": codec.read_unsigned(b, 1, 2),
            "wind_direction_raw": codec.read_unsigned(b, 3, 2),
            "temperature_raw": codec.read_unsigned(b, 5, 2), "turbulence_raw": b[7]}


def _e380_met(s: dict) -> bytes:
    return bytes([(s["ws"] << 7) | (s["wd"] << 6) | (s["tmp"] << 5) | (s["trb"] << 4)
                  | s["spare_bits_60_57"]]) \
        + codec.write_unsigned(s["wind_speed_raw"], 2) \
        + codec.write_unsigned(s["wind_direction_raw"], 2) \
        + codec.write_unsigned(s["temperature_raw"], 2) + bytes([s["turbulence_raw"]])


def _d380_pos(b: bytes) -> dict:
    return {"latitude_raw": codec.read_unsigned(b, 0, 3),
            "longitude_raw": codec.read_unsigned(b, 3, 3)}


def _e380_pos(s: dict) -> bytes:
    return codec.write_unsigned(s["latitude_raw"], 3) + codec.write_unsigned(s["longitude_raw"], 3)


def _d380_pun(b: bytes) -> dict:
    o = b[0]
    return {"spare_bits_8_5": _bits(o, 8, 5), "pun": _bits(o, 4, 1)}


def _e380_pun(s: dict) -> bytes:
    return bytes([(s["spare_bits_8_5"] << 4) | s["pun"]])


def _d380_mb(b: bytes) -> dict:
    rep = b[0]
    registers = []
    for index in range(rep):
        at = 1 + 8 * index
        registers.append({"bds_data": b[at:at + 7].hex(), "bds1": _bits(b[at + 7], 8, 5),
                          "bds2": _bits(b[at + 7], 4, 1)})
    return {"rep": rep, "registers": registers}


def _e380_mb(s: dict) -> bytes:
    out = bytearray([s["rep"]])
    for register in s["registers"]:
        out += bytes.fromhex(register["bds_data"])
        out.append((register["bds1"] << 4) | register["bds2"])
    return bytes(out)


def _d380_bps(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 2)
    return {"spare_bits_16_13": _bits(w, 16, 13), "bps_raw": _bits(w, 12, 1)}


def _e380_bps(s: dict) -> bytes:
    return codec.write_unsigned((s["spare_bits_16_13"] << 12) | s["bps_raw"], 2)


# ------------------------------------------------------ I062/390's eighteen subfields


def _d390_ifi(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 4)
    return {"typ": _bits(w, 32, 31), "spare_bits_30_28": _bits(w, 30, 28), "nbr": _bits(w, 27, 1)}


def _e390_ifi(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["typ"] << 30) | (s["spare_bits_30_28"] << 27) | s["nbr"], 4)


def _d390_fct(b: bytes) -> dict:
    o = b[0]
    return {"gat_oat": _bits(o, 8, 7), "fr": _bits(o, 6, 5), "rvsm": _bits(o, 4, 3),
            "hpr": _bits(o, 2, 2), "spare_bit_1": _bits(o, 1, 1)}


def _e390_fct(s: dict) -> bytes:
    return bytes([(s["gat_oat"] << 6) | (s["fr"] << 4) | (s["rvsm"] << 2) | (s["hpr"] << 1)
                  | s["spare_bit_1"]])


def _d_text(field: str):
    def decode(b: bytes) -> dict:
        return {field: b.hex()}
    return decode


def _e_text(field: str):
    def encode(s: dict) -> bytes:
        return bytes.fromhex(s[field])
    return encode


def _d390_rds(b: bytes) -> dict:
    return {"nu1": b[0], "nu2": b[1], "ltr": b[2]}


def _e390_rds(s: dict) -> bytes:
    return bytes([s["nu1"], s["nu2"], s["ltr"]])


def _d390_ctl(b: bytes) -> dict:
    return {"centre": b[0], "position": b[1]}


def _e390_ctl(s: dict) -> bytes:
    return bytes([s["centre"], s["position"]])


def _d390_tod(b: bytes) -> dict:
    rep = b[0]
    entries = []
    for index in range(rep):
        at = 1 + 4 * index
        word = codec.read_unsigned(b, at, 4)
        entries.append({
            "typ": _bits(word, 32, 28), "day": _bits(word, 27, 26),
            "spare_bits_25_22": _bits(word, 25, 22), "hor": _bits(word, 21, 17),
            "spare_bits_16_15": _bits(word, 16, 15), "min": _bits(word, 14, 9),
            "avs": _bits(word, 8, 8), "spare_bit_7": _bits(word, 7, 7), "sec": _bits(word, 6, 1),
        })
    return {"rep": rep, "entries": entries}


def _e390_tod(s: dict) -> bytes:
    out = bytearray([s["rep"]])
    for entry in s["entries"]:
        out += codec.write_unsigned(
            (entry["typ"] << 27) | (entry["day"] << 25) | (entry["spare_bits_25_22"] << 21)
            | (entry["hor"] << 16) | (entry["spare_bits_16_15"] << 14) | (entry["min"] << 8)
            | (entry["avs"] << 7) | (entry["spare_bit_7"] << 6) | entry["sec"], 4)
    return bytes(out)


def _d390_sts(b: bytes) -> dict:
    o = b[0]
    return {"emp": _bits(o, 8, 7), "avl": _bits(o, 6, 5), "spare_bits_4_1": _bits(o, 4, 1)}


def _e390_sts(s: dict) -> bytes:
    return bytes([(s["emp"] << 6) | (s["avl"] << 4) | s["spare_bits_4_1"]])


def _d390_pem(b: bytes) -> dict:
    """§5.2.25 Subfield #17, and the bit numbering here is FORMAT_COVERAGE.md ambiguity 8.

    The prose says "bits-16/13 Spare bits set to 0" and then "bit-13 (VA) Validity" — bit 13
    assigned twice in four lines. The structure diagram shows three zeros then `VA`, i.e. bits
    16/14 spare and bit 13 = `VA`, and the diagram is preferred: it is the only one of the two
    statements that is internally consistent, and it agrees with the twelve-bit Mode 3/A field
    below it. Decoding on the prose's reading would put `VA` inside the spare field and lose it.
    """
    w = codec.read_unsigned(b, 0, 2)
    return {"spare_bits_16_14": _bits(w, 16, 14), "va": _bits(w, 13, 13),
            "mode_3a": _bits(w, 12, 1)}


def _e390_pem(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["spare_bits_16_14"] << 13) | (s["va"] << 12) | s["mode_3a"], 2)


# ------------------------------------------------------- I062/500's eight subfields


def _d500_pair16(b: bytes) -> dict:
    return {"x_raw": codec.read_unsigned(b, 0, 2), "y_raw": codec.read_unsigned(b, 2, 2)}


def _e500_pair16(s: dict) -> bytes:
    return codec.write_unsigned(s["x_raw"], 2) + codec.write_unsigned(s["y_raw"], 2)


def _d500_pair8(b: bytes) -> dict:
    return {"x_raw": b[0], "y_raw": b[1]}


def _e500_pair8(s: dict) -> bytes:
    return bytes([s["x_raw"], s["y_raw"]])


#: Per-item subfield decoders and encoders. Assembled as tables rather than as long if-chains so
#: that `_decode_compound` and `_encode_compound` serve all six items — which is what makes the
#: spare-presence-bit refusal uniform across them.
_SUBFIELD_DECODERS: dict[str, dict[str, Any]] = {
    "I062/110": {"sum": _d110_sum, "pmn": _d110_pmn, "pos": _d110_pos, "ga": _d110_ga,
                 "em1": _d110_em1, "tos": _d110_tos, "xp": _d110_xp},
    "I062/290": {name: (_d_age2 if name == "ads" else _d_age1)
                 for octet in _PRESENCE["I062/290"] for name, _ in octet},
    "I062/295": {name: _d_age1 for octet in _PRESENCE["I062/295"] for name, _ in octet},
    "I062/340": {"sid": _d340_sid, "pos": _d340_pos, "hei": _d340_hei, "mdc": _d340_mdc,
                 "mda": _d340_mda, "typ": _d340_typ},
    "I062/380": {
        "adr": _d380_adr, "id": _d380_id, "mhg": _d_word("heading_raw"), "ias": _d380_ias,
        "tas": _d_word("true_airspeed_raw"), "sal": _d380_sal, "fss": _d380_fss,
        "tis": _d380_tis, "tid": _d380_tid, "com": _d380_com, "sab": _d380_sab,
        "acs": _d380_acs, "bvr": _d_word("vertical_rate_raw"),
        "gvr": _d_word("vertical_rate_raw"), "ran": _d_word("roll_angle_raw"), "tar": _d380_tar,
        "tan": _d_word("track_angle_raw"), "gsp": _d_word("ground_speed_raw"),
        "vun": _d_octet("velocity_uncertainty"), "met": _d380_met, "emc": _d_octet("ecat"),
        "pos": _d380_pos, "gal": _d_word("geometric_altitude_raw"), "pun": _d380_pun,
        "mb": _d380_mb, "iar": _d_word("indicated_airspeed_raw"),
        "mac": _d_word("mach_number_raw"), "bps": _d380_bps,
    },
    "I062/390": {
        "tag": _d340_sid, "csn": _d_text("callsign_raw"), "ifi": _d390_ifi, "fct": _d390_fct,
        "tac": _d_text("aircraft_type_raw"), "wtc": _d_octet("wtc"),
        "dep": _d_text("departure_raw"), "dst": _d_text("destination_raw"), "rds": _d390_rds,
        "cfl": _d_word("cleared_flight_level_raw"), "ctl": _d390_ctl, "tod": _d390_tod,
        "ast": _d_text("aircraft_stand_raw"), "sts": _d390_sts, "std": _d_text("sid_raw"),
        "sta": _d_text("star_raw"), "pem": _d390_pem, "pec": _d_text("pre_emergency_raw"),
    },
    "I062/500": {"apc": _d500_pair16, "cov": _d_word("covariance_raw"), "apw": _d500_pair16,
                 "aga": _d_octet("accuracy_raw"), "aba": _d_octet("accuracy_raw"),
                 "atv": _d500_pair8, "aa": _d500_pair8, "arc": _d_octet("accuracy_raw")},
}
_SUBFIELD_ENCODERS: dict[str, dict[str, Any]] = {
    "I062/110": {"sum": _e110_sum, "pmn": _e110_pmn, "pos": _e110_pos, "ga": _e110_ga,
                 "em1": _e110_em1, "tos": _e110_tos, "xp": _e110_xp},
    "I062/290": {name: (_e_age2 if name == "ads" else _e_age1)
                 for octet in _PRESENCE["I062/290"] for name, _ in octet},
    "I062/295": {name: _e_age1 for octet in _PRESENCE["I062/295"] for name, _ in octet},
    "I062/340": {"sid": _e340_sid, "pos": _e340_pos, "hei": _e340_hei, "mdc": _e340_mdc,
                 "mda": _e340_mda, "typ": _e340_typ},
    "I062/380": {
        "adr": _e380_adr, "id": _e380_id, "mhg": _e_word("heading_raw"), "ias": _e380_ias,
        "tas": _e_word("true_airspeed_raw"), "sal": _e380_sal, "fss": _e380_fss,
        "tis": _e380_tis, "tid": _e380_tid, "com": _e380_com, "sab": _e380_sab,
        "acs": _e380_acs, "bvr": _e_word("vertical_rate_raw"),
        "gvr": _e_word("vertical_rate_raw"), "ran": _e_word("roll_angle_raw"), "tar": _e380_tar,
        "tan": _e_word("track_angle_raw"), "gsp": _e_word("ground_speed_raw"),
        "vun": _e_octet("velocity_uncertainty"), "met": _e380_met, "emc": _e_octet("ecat"),
        "pos": _e380_pos, "gal": _e_word("geometric_altitude_raw"), "pun": _e380_pun,
        "mb": _e380_mb, "iar": _e_word("indicated_airspeed_raw"),
        "mac": _e_word("mach_number_raw"), "bps": _e380_bps,
    },
    "I062/390": {
        "tag": _e340_sid, "csn": _e_text("callsign_raw"), "ifi": _e390_ifi, "fct": _e390_fct,
        "tac": _e_text("aircraft_type_raw"), "wtc": _e_octet("wtc"),
        "dep": _e_text("departure_raw"), "dst": _e_text("destination_raw"), "rds": _e390_rds,
        "cfl": _e_word("cleared_flight_level_raw"), "ctl": _e390_ctl, "tod": _e390_tod,
        "ast": _e_text("aircraft_stand_raw"), "sts": _e390_sts, "std": _e_text("sid_raw"),
        "sta": _e_text("star_raw"), "pem": _e390_pem, "pec": _e_text("pre_emergency_raw"),
    },
    "I062/500": {"apc": _e500_pair16, "cov": _e_word("covariance_raw"), "apw": _e500_pair16,
                 "aga": _e_octet("accuracy_raw"), "aba": _e_octet("accuracy_raw"),
                 "atv": _e500_pair8, "aa": _e500_pair8, "arc": _e_octet("accuracy_raw")},
}


# ============================================ the Reserved Expansion Field, Appendix A 1.3
#
# IN SCOPE and decoded in full — FORMAT_COVERAGE.md settlement 2. Five items behind a one-octet
# length and a one-octet items indicator, and the indicator's bit 1 is a SPARE and not an FX, so a
# set bit 1 is parked as sent rather than refused. That is the opposite treatment from every
# compound item in the core specification and getting it backwards would refuse a legal REF.

#: Appendix A §2.2, bits 8 to 4. Bits 3/1 are spares.
_REF_ITEMS = (("cst", 8), ("csn", 7), ("tvs", 6), ("sts", 5), ("v3", 4))

#: Appendix A §2.7, the ADS-B Version 3 item's own presence map: bits 8 to 5, bits 4/2 spare, FX.
_REF_V3_SUBFIELDS = (("ps3", 8), ("as", 7), ("uas", 6), ("cass", 5))
_REF_V3_OCTETS = {"ps3": 1, "as": 3, "uas": 1, "cass": 1}


def _decode_ref(block: bytes) -> dict:
    """The whole REF: its own length octet, its items indicator, and the items present.

    The length is a SECOND length statement inside a record that already has one, so it must tile
    exactly: `_len_explicit` has already used it to bound this block, and this function checks that
    the items the indicator names consume all of it. A REF whose length and contents disagree is
    refused, because the two readings would put the next core item in two different places.
    """
    stated = block[0]
    indicator = block[1]
    parsed: dict[str, Any] = {
        "length": stated,
        "items_indicator": indicator,
        "spare_bits_3_1": _bits(indicator, 3, 1),
        "items": {},
    }
    at = 2
    for name, bit in _REF_ITEMS:
        if not indicator & (1 << (bit - 1)):
            continue
        length = _ref_item_length(name, block, at)
        parsed["items"][name] = _REF_DECODERS[name](block[at:at + length])
        at += length
    if at != len(block):
        raise Cat062ParseError(
            f"the Reserved Expansion Field states a length of {stated} octets and the items its "
            f"indicator (0x{indicator:02X}) names consume {at}. Appendix A §2.1 makes the "
            "length 'the total length in octets of the Reserved Expansion Field (including the "
            "REF length itself)', so the two have to agree exactly — a disagreement puts the next "
            "core item in two different places"
        )
    return parsed


def _encode_ref(parsed: dict) -> bytes:
    body = bytearray()
    for name, bit in _REF_ITEMS:
        if parsed["items_indicator"] & (1 << (bit - 1)):
            body += _REF_ENCODERS[name](parsed["items"][name])
    return bytes([parsed["length"], parsed["items_indicator"]]) + bytes(body)


def _ref_item_length(name: str, data: bytes, offset: int) -> int:
    if name == "cst":
        return _repetitive(data, offset, 5, "I062/REF/CST", "at least one 5 byte subfield")
    if name == "csn":
        return _repetitive(data, offset, 3, "I062/REF/CSN", "at least one 3 byte subfield")
    if name == "tvs":
        return 4
    if name == "sts":
        if offset >= len(data):
            raise _refuse("I062/REF/STS is past the end of the Reserved Expansion Field", data,
                          offset)
        if data[offset] & codec.FX:
            raise _refuse(
                "I062/REF/STS sets its FX bit, documented as 'Extension of data item into next "
                "octet', and Appendix A §2.6 defines one octet and no extension. There is "
                "nothing to decode, so it cannot be skipped", data, offset)
        return 1
    if name == "v3":
        if offset >= len(data):
            raise _refuse("I062/REF/V3's primary subfield is past the end of the Reserved "
                          "Expansion Field", data, offset)
        primary = data[offset]
        if primary & codec.FX:
            raise _refuse(
                "I062/REF/V3's primary subfield sets its FX bit and Appendix A §2.7 defines "
                "four subfields in one octet. A second primary octet has no subfields behind it",
                data, offset)
        spare = 0b00001110
        if primary & spare:
            raise _refuse(
                f"I062/REF/V3's primary subfield (0x{primary:02X}) sets a bit in 4/2, which "
                "Appendix A §2.7 marks 'Spare bits, set to “0”'. A spare presence "
                "bit claims a subfield that does not exist", data, offset)
        total = 1
        for sub, bit in _REF_V3_SUBFIELDS:
            if primary & (1 << (bit - 1)):
                total += _REF_V3_OCTETS[sub]
        return total
    raise Cat062ParseError(f"no length rule for REF item {name!r}")


def _d_ref_cst(b: bytes) -> dict:
    rep = b[0]
    sensors = []
    for index in range(rep):
        at = 1 + 5 * index
        sensors.append({"sac": b[at], "sic": b[at + 1],
                        "spare_bits_24_21": _bits(b[at + 2], 8, 5),
                        "typ": _bits(b[at + 2], 4, 1),
                        "local_track_number": codec.read_unsigned(b, at + 3, 2)})
    return {"rep": rep, "sensors": sensors}


def _e_ref_cst(s: dict) -> bytes:
    out = bytearray([s["rep"]])
    for sensor in s["sensors"]:
        out += bytes([sensor["sac"], sensor["sic"],
                      (sensor["spare_bits_24_21"] << 4) | sensor["typ"]])
        out += codec.write_unsigned(sensor["local_track_number"], 2)
    return bytes(out)


def _d_ref_csn(b: bytes) -> dict:
    rep = b[0]
    sensors = []
    for index in range(rep):
        at = 1 + 3 * index
        sensors.append({"sac": b[at], "sic": b[at + 1],
                        "spare_bits_8_5": _bits(b[at + 2], 8, 5),
                        "typ": _bits(b[at + 2], 4, 1)})
    return {"rep": rep, "sensors": sensors}


def _e_ref_csn(s: dict) -> bytes:
    out = bytearray([s["rep"]])
    for sensor in s["sensors"]:
        out += bytes([sensor["sac"], sensor["sic"],
                      (sensor["spare_bits_8_5"] << 4) | sensor["typ"]])
    return bytes(out)


def _d_ref_tvs(b: bytes) -> dict:
    return {"vx_raw": codec.read_unsigned(b, 0, 2), "vy_raw": codec.read_unsigned(b, 2, 2)}


def _e_ref_tvs(s: dict) -> bytes:
    return codec.write_unsigned(s["vx_raw"], 2) + codec.write_unsigned(s["vy_raw"], 2)


def _d_ref_sts(b: bytes) -> dict:
    o = b[0]
    return {"fdr": _bits(o, 8, 8), "lnav_ep": _bits(o, 7, 7), "lnav_val": _bits(o, 6, 6),
            "spare_bits_5_2": _bits(o, 5, 2), "fx": _bits(o, 1, 1)}


def _e_ref_sts(s: dict) -> bytes:
    return bytes([(s["fdr"] << 7) | (s["lnav_ep"] << 6) | (s["lnav_val"] << 5)
                  | (s["spare_bits_5_2"] << 1) | s["fx"]])


def _d_ref_v3(b: bytes) -> dict:
    primary = b[0]
    parsed: dict[str, Any] = {"primary": primary, "spare_bits_4_2": _bits(primary, 4, 2),
                              "fx": _bits(primary, 1, 1), "subfields": {}}
    at = 1
    for name, bit in _REF_V3_SUBFIELDS:
        if not primary & (1 << (bit - 1)):
            continue
        width = _REF_V3_OCTETS[name]
        parsed["subfields"][name] = _V3_DECODERS[name](b[at:at + width])
        at += width
    return parsed


def _e_ref_v3(s: dict) -> bytes:
    out = bytearray([s["primary"]])
    for name, bit in _REF_V3_SUBFIELDS:
        if s["primary"] & (1 << (bit - 1)):
            out += _V3_ENCODERS[name](s["subfields"][name])
    return bytes(out)


def _d_v3_ps3(b: bytes) -> dict:
    o = b[0]
    return {"ps3_ep": _bits(o, 8, 8), "ps3_val": _bits(o, 7, 5),
            "spare_bits_4_1": _bits(o, 4, 1)}


def _e_v3_ps3(s: dict) -> bytes:
    return bytes([(s["ps3_ep"] << 7) | (s["ps3_val"] << 4) | s["spare_bits_4_1"]])


def _d_v3_as(b: bytes) -> dict:
    w = codec.read_unsigned(b, 0, 3)
    return {"rce_ep": _bits(w, 24, 24), "rce_val": _bits(w, 23, 22),
            "rrl_ep": _bits(w, 21, 21), "rrl_val": _bits(w, 20, 20),
            "tpw_ep": _bits(w, 19, 19), "tpw_val": _bits(w, 18, 17),
            "tsi_ep": _bits(w, 16, 16), "tsi_val": _bits(w, 15, 14),
            "tao_ep": _bits(w, 13, 13), "re": _bits(w, 12, 12), "tao_val": _bits(w, 11, 6),
            "spare_bits_5_1": _bits(w, 5, 1)}


def _e_v3_as(s: dict) -> bytes:
    return codec.write_unsigned(
        (s["rce_ep"] << 23) | (s["rce_val"] << 21) | (s["rrl_ep"] << 20) | (s["rrl_val"] << 19)
        | (s["tpw_ep"] << 18) | (s["tpw_val"] << 16) | (s["tsi_ep"] << 15) | (s["tsi_val"] << 13)
        | (s["tao_ep"] << 12) | (s["re"] << 11) | (s["tao_val"] << 5) | s["spare_bits_5_1"], 3)


def _d_v3_uas(b: bytes) -> dict:
    o = b[0]
    return {"muo_ep": _bits(o, 8, 8), "muo_val": _bits(o, 7, 7), "daa_ep": _bits(o, 6, 6),
            "daa_val": _bits(o, 5, 4), "rwc_ep": _bits(o, 3, 3), "rwc_val": _bits(o, 2, 2),
            "spare_bit_1": _bits(o, 1, 1)}


def _e_v3_uas(s: dict) -> bytes:
    return bytes([(s["muo_ep"] << 7) | (s["muo_val"] << 6) | (s["daa_ep"] << 5)
                  | (s["daa_val"] << 3) | (s["rwc_ep"] << 2) | (s["rwc_val"] << 1)
                  | s["spare_bit_1"]])


def _d_v3_cass(b: bytes) -> dict:
    o = b[0]
    return {"svh_ep": _bits(o, 8, 8), "svh_val": _bits(o, 7, 6), "catc_ep": _bits(o, 5, 5),
            "catc_val": _bits(o, 4, 2), "spare_bit_1": _bits(o, 1, 1)}


def _e_v3_cass(s: dict) -> bytes:
    return bytes([(s["svh_ep"] << 7) | (s["svh_val"] << 5) | (s["catc_ep"] << 4)
                  | (s["catc_val"] << 1) | s["spare_bit_1"]])


_REF_DECODERS = {"cst": _d_ref_cst, "csn": _d_ref_csn, "tvs": _d_ref_tvs, "sts": _d_ref_sts,
                 "v3": _d_ref_v3}
_REF_ENCODERS = {"cst": _e_ref_cst, "csn": _e_ref_csn, "tvs": _e_ref_tvs, "sts": _e_ref_sts,
                 "v3": _e_ref_v3}
_V3_DECODERS = {"ps3": _d_v3_ps3, "as": _d_v3_as, "uas": _d_v3_uas, "cass": _d_v3_cass}
_V3_ENCODERS = {"ps3": _e_v3_ps3, "as": _e_v3_as, "uas": _e_v3_uas, "cass": _e_v3_cass}


def _decode_sp(block: bytes) -> dict:
    """SP: a one-octet length INCLUDING itself, then opaque contents.

    NEVER DECODED and never written to. A Special Purpose Field's contents are settled by bilateral
    agreement between one sender and one receiver, so a byte invented here is a byte some
    deployment already means something by. The length convention is inherited from the shipped
    ASTERIX siblings, because ASTERIX Part 1 defines it and this document cites Part 1 at edition
    3.1 without reproducing it — and Part 1 is not pinned in this repository.
    """
    return {"length": block[0], "contents": block[1:].hex()}


def _encode_sp(item: dict) -> bytes:
    return bytes([item["length"]]) + bytes.fromhex(item["contents"])


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


def _len_fixed(width: int):
    def rule(data: bytes, offset: int) -> int:
        return width
    return rule


# ========================================================================= the UAP
#
# §5.3 Table 1. (FRN, item, §5.2 name, length rule, decoder, encoder). The Spare FRNs are absent
# from this table by construction: `_parse_record` checks `codec.SPARE_FRNS` before it looks here,
# so a set spare bit gets the refusal that quotes the document's own reason for the slot rather
# than a generic "no such FRN".

UAP: tuple[tuple[int, str, str, Any, Any, Any], ...] = (
    (1, "I062/010", "Data Source Identifier", _len_fixed(2), _decode_010, _encode_010),
    (3, "I062/015", "Service Identification", _len_fixed(1), _decode_015, _encode_015),
    (4, "I062/070", "Time Of Track Information", _len_fixed(3), _decode_070, _encode_070),
    (5, "I062/105", "Calculated Position In WGS-84 Co-ordinates", _len_fixed(8),
     _decode_105, _encode_105),
    (6, "I062/100", "Calculated Track Position. (Cartesian)", _len_fixed(6),
     _decode_100, _encode_100),
    (7, "I062/185", "Calculated Track Velocity (Cartesian)", _len_fixed(4),
     _decode_185, _encode_185),
    (8, "I062/210", "Calculated Acceleration (Cartesian)", _len_fixed(2),
     _decode_210, _encode_210),
    (9, "I062/060", "Track Mode 3/A Code", _len_fixed(2), _decode_060, _encode_060),
    (10, "I062/245", "Target Identification", _len_fixed(7), _decode_245, _encode_245),
    (11, "I062/380", "Aircraft Derived Data", _len_compound("I062/380"),
     _decode_compound("I062/380"), _encode_compound("I062/380")),
    (12, "I062/040", "Track Number", _len_fixed(2), _decode_040, _encode_040),
    (13, "I062/080", "Track Status", _len_080, _decode_080, _encode_080),
    (14, "I062/290", "System Track Update Ages", _len_compound("I062/290"),
     _decode_compound("I062/290"), _encode_compound("I062/290")),
    (15, "I062/200", "Mode of Movement", _len_fixed(1), _decode_200, _encode_200),
    (16, "I062/295", "Track Data Ages", _len_compound("I062/295"),
     _decode_compound("I062/295"), _encode_compound("I062/295")),
    (17, "I062/136", "Measured Flight Level", _len_fixed(2), _decode_136, _encode_136),
    (18, "I062/130", "Calculated Track Geometric Altitude", _len_fixed(2),
     _decode_130, _encode_130),
    (19, "I062/135", "Calculated Track Barometric Altitude", _len_fixed(2),
     _decode_135, _encode_135),
    (20, "I062/220", "Calculated Rate Of Climb/Descent", _len_fixed(2), _decode_220, _encode_220),
    (21, "I062/390", "Flight Plan Related Data", _len_compound("I062/390"),
     _decode_compound("I062/390"), _encode_compound("I062/390")),
    (22, "I062/270", "Target Size & Orientation", _len_270, _decode_270, _encode_270),
    (23, "I062/300", "Vehicle Fleet Identification", _len_fixed(1), _decode_300, _encode_300),
    (24, "I062/110", "Mode 5 Data reports & Extended Mode 1 Code", _len_compound("I062/110"),
     _decode_compound("I062/110"), _encode_compound("I062/110")),
    (25, "I062/120", "Track Mode 2 Code", _len_fixed(2), _decode_120, _encode_120),
    (26, "I062/510", "Composed Track Number", _len_510, _decode_510, _encode_510),
    (27, "I062/500", "Estimated Accuracies", _len_compound("I062/500"),
     _decode_compound("I062/500"), _encode_compound("I062/500")),
    (28, "I062/340", "Measured Information", _len_compound("I062/340"),
     _decode_compound("I062/340"), _encode_compound("I062/340")),
    (34, "RE", "Reserved Expansion Field", _len_explicit, _decode_ref, _encode_ref),
    (35, "SP", "Reserved For Special Purpose Indicator", _len_explicit, _decode_sp, _encode_sp),
)

UAP_BY_FRN = {entry[0]: entry for entry in UAP}
FRN_BY_ITEM = {entry[1]: entry[0] for entry in UAP}
ENCODERS = {entry[1]: entry[5] for entry in UAP}


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
                f"record {index}: FSPEC sets FRN {frn}, which §5.3 Table 1 marks '- Spare -'. "
                f"{codec.spare_frn_reason(frn)}. A spare slot names no item, so there is nothing "
                "to decode, it cannot be skipped, and guessing a length would desynchronise every "
                "following item in the record", data, fspec_start)
        entry = UAP_BY_FRN.get(frn)
        if entry is None:
            raise _refuse(
                f"record {index}: FSPEC sets FRN {frn}, which the category 062 UAP does not "
                f"define — Table 1 lists {codec.MAX_FRN} slots. There is no item to decode, so "
                "it cannot be skipped, and guessing a length would desynchronise every following "
                "item in the record", data, fspec_start)
        _frn, item, _name, rule, decode, _encode = entry
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
            f"record {index} is missing {', '.join(missing)}. Each one's own Encoding Rule reads "
            "'This Item shall be present in every ASTERIX record' — §4.1 gives this category ONE "
            "message type and §4.4 says 'The Encoding Rules are contained in each Data Item', so "
            "there is no per-type table to consult and these four are unconditional. ASTERIX "
            "carries no checksum at any level, so the mandatory items are part of what replaces "
            "one", data, fspec_start)

    return {"index": index, "fspec": fspec.hex(), "items": items,
            "item_octets": item_octets}, at


def parse_block(data: bytes) -> dict:
    """One data block into the parsed form. Every refusal quotes the offending octets."""
    if len(data) < BLOCK_HEADER_OCTETS:
        raise Cat062ParseError(
            f"a CAT062 data block is at least {BLOCK_HEADER_OCTETS} octets (CAT + LEN); "
            f"got {len(data)}: {data.hex()}"
        )
    category = data[0]
    if category != CATEGORY:
        raise _refuse(
            f"CAT octet is {category} (0x{category:02X}), not {CATEGORY}. This adapter speaks "
            "one category, and a data block of any other ASTERIX category decoded against the "
            "category 062 UAP yields a plausible wrong aircraft rather than an error — every "
            "category has its own item catalogue and its own FSPEC ceiling", data, 0)
    stated = codec.read_unsigned(data, 1, 2)
    if stated != len(data):
        raise _refuse(
            f"LEN says {stated} octets and the buffer holds {len(data)}. §4.6 makes LEN 'a "
            "two-octet field indicating the total length in octets of the Data Block, including "
            "the CAT and LEN fields', so reading to the end of the buffer instead would "
            "translate whatever followed the block as if it were part of it", data, 1)

    records: list[dict] = []
    at = BLOCK_HEADER_OCTETS
    while at < len(data):
        record, at = _parse_record(data, at, index=len(records))
        records.append(record)
    if not records:
        raise Cat062ParseError(
            f"the block states LEN = {stated} and holds no records. An empty block is not a "
            "payload that legitimately carries nothing: §4.6's layout has at least one FSPEC "
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
    were parked on ingest**. That check is the point: it makes byte-exactness a proven property of
    the decoder/encoder pair rather than a trivial consequence of copying the input back out, and
    it is what would catch a spare bit the decoder read and the encoder forgot — of which this
    category has more than the other two ASTERIX adapters combined.
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
                raise Cat062ParseError(
                    f"re-encoding {item} produced {emitted.hex()} and the octets parked on "
                    f"ingest were {parked}. The round trip is only byte-exact if every bit the "
                    "decoder read is a bit the encoder writes back, spare bits included — "
                    "§4.5 addresses unused bits and does not require them to be zero, so a "
                    "conforming encoder may set them to anything"
                )
            body += emitted
    return bytes([CATEGORY]) + codec.write_unsigned(len(body) + BLOCK_HEADER_OCTETS, 2) + body


# ============================================================================ the time


def _resolve_time_of_day(seconds: float, received_at: _dt.datetime) -> tuple[_dt.datetime, str]:
    """A time of day plus the receipt date, resolved to the nearest candidate instant.

    §5.2.5 gives "elapsed time since last midnight, expressed as UTC" and NOTE 2 says "The time
    is reset to zero at every midnight", so the candidates are that time of day on the receipt
    date, the day before and the day after; the nearest to the receipt instant wins. Same rule as
    `asterix_cat021.py`, `asterix_cat048.py` and `asterix_cat034.py`, reached a fourth time.
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
    """`Event.observed_at` from I062/070, which is mandatory in every record."""
    raw = items["I062/070"]["time_of_day_raw"]
    seconds = codec.from_raw("tod", raw)
    if seconds >= codec.SECONDS_PER_DAY:
        raise Cat062ParseError(
            f"I062/070 states {raw} units of 1/128 s = {seconds:.7f} s since midnight, and a "
            f"day is {codec.SECONDS_PER_DAY} s. Twenty-four bits at 1/128 s reach "
            "131071.9921875 s, so the field can express counts no time of day can mean. "
            "Refusing rather than taking it modulo a day — a modulo would move this record by "
            "hours and leave every other check passing. "
            "THE BASIS IS NOT A STATED RANGE, and the difference from Part 4 is recorded rather "
            "than smoothed over: CAT048 §5.2.17 prints a normative structure block, 'Acceptable "
            "Range of values: 0<= Time-of-Day<=24 hrs', and ACCEPTS 86400 s itself on that "
            "inclusive inequality. CAT062 §5.2.5 prints no range at all, so the bound here comes "
            "from the Definition ('elapsed time since last midnight') and NOTE 2 ('The time is "
            "reset to zero at every midnight'), which together make 86400 s unreachable. Same "
            "width, same LSB, different authority, and a boundary that therefore differs by one "
            "value — the CAT034 disposition and not the CAT048 one"
        )
    instant, note = _resolve_time_of_day(seconds, received_at)
    return instant, {
        "item": "I062/070",
        "time_of_day_s": seconds,
        "time_of_day_raw": raw,
        "lsb_seconds": codec.bounds("tod")[2],
        "date_from": note,
        "definition": ("Absolute time stamping of the information provided in the track message, "
                       "in the form of elapsed time since last midnight, expressed as UTC"),
        "note_1": "This is the time of the track state vector",
    }


# ======================================================================== the position


def _position(items: dict, unresolved: dict) -> tuple[Position | None, dict]:
    """`Entity.position` from I062/105, and from nothing else. Settlement 6.

    No geodesy runs here and none is imported: §5.2.8 already states WGS-84 latitude and longitude,
    so the work is two scalings. The three other position-shaped items in the category are parked
    and the basis says why each is.
    """
    item = items.get("I062/105")
    if item is None:
        return None, {
            "item": None,
            "reason": ("the record carries no I062/105. Its Encoding Rule is 'This Item is "
                       "optional', so the absence is ordinary — and an absent Position is the "
                       "honest statement, never a Position holding zeros, which is a real point "
                       "in the Gulf of Guinea"),
            "altitude_has_nowhere_to_go": (
                "AND THAT TAKES THE ALTITUDE WITH IT. `Position` requires a latitude and a "
                "longitude — the CDM's null-never-zero rule is structural rather than advisory — "
                "so a record carrying I062/130 and no I062/105 has no Position, and therefore no "
                "alt_m, however well-defined the altitude is. The figure is still in "
                "Event.payload.calculated_geometric_altitude with its LSB and its raw field; what "
                "is absent is the canonical field, and it is absent because the canonical field "
                "is part of an object this record cannot support"),
            "cartesian_declined": ("I062/100 is present in some records and is NEVER converted: "
                                   "§4.3.2's projection is relative to a reference point no "
                                   "CAT062 item carries and names the projection only by example"),
        }
    lat = codec.from_raw("latitude_105", item["latitude_raw"])
    lon = codec.from_raw("longitude_105", item["longitude_raw"])
    low, high, lsb = codec.bounds("latitude_105")
    if not low <= lat <= high:
        field_low, field_high = codec.width("latitude_105")
        raise Cat062ParseError(
            f"I062/105 states a latitude of {lat!r} degrees, and §5.2.8 states 'Range -90 <= "
            f"latitude <= 90 deg'. Thirty-two bits at {lsb!r} degrees reach "
            f"[{field_low!r}, {field_high!r}], so the field can express latitudes the item's own "
            "range excludes. Refusing rather than clamping — a clamped target is a target "
            "somewhere real, and every downstream check would pass"
        )
    accuracy, accuracy_basis = _accuracy(items, lat, unresolved)
    basis = {
        "item": "I062/105",
        "definition": "Calculated Position in WGS-84 Co-ordinates",
        "latitude_raw": item["latitude_raw"],
        "longitude_raw": item["longitude_raw"],
        "lsb_degrees": lsb,
        "position_source_basis": (
            "ESTIMATED, always, and it is a ruling rather than a fit. §3.1.2 defines a Calculated "
            "Item as 'A piece of information (e.g. the position of a target) derived from raw "
            "information through an intermediate processing such as transformation of "
            "co-ordinates, TRACKING, code conversion', so a tracker's filtered output is an "
            "estimate by construction whatever the sensors underneath it were. GNSS would claim "
            "the fix came from a satellite receiver, which is sometimes UPSTREAM of it and never "
            "what the item states; INERTIAL and MANUAL are plainly wrong. The underlying "
            "technologies are named separately in I062/290 and in the REF's contributing-sensor "
            "lists, so a consumer can see that a track was ADS-B-only without this adapter having "
            "relabelled the estimate as a GNSS fix"),
        "accuracy": accuracy_basis,
    }
    return Position(
        lat=lat, lon=lon,
        # None from this item. Four altitude quantities exist and settlement 5 rules which one
        # reaches `alt_m`; `_altitude` fills it in.
        alt_m=_altitude(items),
        position_source=PositionSource.ESTIMATED,
        accuracy_m=accuracy,
    ), basis


def _altitude(items: dict) -> float | None:
    """`Position.alt_m` from I062/130 and from nothing else. Settlement 5.

    Four altitude quantities in the category and six altitude-shaped numbers, no two of them the
    same measurement. `Position.alt_m` documents itself as "Metres HAE" — height above the WGS 84
    ellipsoid — and I062/130 is the only one of the six DEFINED as exactly that: "Vertical distance
    between the target and the projection of its position on the earth's ellipsoid, as defined by
    WGS84". A flight level is a pressure altitude and is not a height above anything; I062/340
    SF#3's datum is whatever the contributing sensor used and is not stated; I062/380 SF#23 is the
    aircraft's own opinion.

    `MRH` DOES NOT ARBITRATE, and §5.2.6's fourth NOTE is why: "Data Items I062/130, I062/135, and
    I062/136 may be transmitted in parallel whenever the respective information is available. This
    is independent from the value transmitted on I062/080 (MRH)." So promoting I062/135 when MRH
    says barometric would put a pressure altitude in a field documented as an ellipsoidal height.
    """
    item = items.get("I062/130")
    if item is None:
        return None
    feet = codec.from_raw("geometric_altitude", item["altitude_raw"])
    low, high, _lsb = codec.bounds("geometric_altitude")
    if not low <= feet <= high:
        raise Cat062ParseError(
            f"I062/130 states {feet!r} ft and §5.2.11 states 'Vmin = {low!r} ft, Vmax = {high!r} "
            "ft'. Sixteen bits at 6.25 ft reach ±204800, so the field can express altitudes the "
            "item's own range excludes. Refusing rather than clamping"
        )
    # Feet to metres, the international foot, exactly. Declared in TRANSFORMS.
    return feet * 0.3048


def _accuracy(items: dict, latitude: float,
              unresolved: dict) -> tuple[float | None, dict]:
    """`Position.accuracy_m` from I062/500 Subfield #3, and the arithmetic stated in the object.

    THE ONLY CANONICAL VALUE IN THIS ADAPTER COMPUTED FROM MORE THAN ONE WIRE FIELD. The
    combination, the constant and the independence assumption are `cat062_codec.degrees_to_metres`'s
    and are restated here in the object, because a consumer comparing accuracies across sources
    needs to know what was assumed rather than to read this module.
    """
    accuracies = items.get("I062/500")
    subfield = (accuracies or {}).get("subfields", {}).get("apw")
    if subfield is None:
        return None, {
            "item": None,
            "reason": ("no I062/500 Subfield #3 in this record, so the accuracy is UNKNOWN. "
                       "accuracy_m stays None, which means unknown and never perfect — and it is "
                       "deliberately NOT derived from Subfield #1, whose components are in the "
                       "Cartesian frame settlement 6 declines to invert"),
        }
    lat_sigma = codec.from_raw("accuracy_position_deg", subfield["x_raw"])
    lon_sigma = codec.from_raw("accuracy_position_deg", subfield["y_raw"])
    metres = codec.degrees_to_metres(lat_sigma, lon_sigma, latitude)
    _low, high, _lsb = codec.bounds("accuracy_position_deg")
    saturated = [name for name, raw in (("latitude_component", subfield["x_raw"]),
                                        ("longitude_component", subfield["y_raw"]))
                 if codec.from_raw("accuracy_position_deg", raw) >= high]
    if saturated:
        unresolved["I062/500 SF#3 at maximum"] = {
            "raw": {name: subfield[key] for name, key in
                    (("latitude_component", "x_raw"), ("longitude_component", "y_raw"))},
            "reason": (
                f"{', '.join(saturated)} is at the field's maximum, and §5.2.26 says "
                f"'{AT_OR_ABOVE_MAXIMUM_NOTE}'. So the value is a FLOOR and not a measurement: "
                "accuracy_m carries the number and a consumer differentiating two saturated "
                "readings would compute a zero rate of change from two saturated readings"),
        }
    return metres, {
        "item": "I062/500 Subfield #3",
        "definition": ("Estimated accuracy (i.e. standard deviation) of the calculated position "
                       "of a target expressed in WGS-84"),
        "latitude_component_deg": lat_sigma,
        "longitude_component_deg": lon_sigma,
        "latitude_component_raw": subfield["x_raw"],
        "longitude_component_raw": subfield["y_raw"],
        "lsb_degrees": codec.bounds("accuracy_position_deg")[2],
        "metres": metres,
        "at_or_above_maximum": saturated or None,
        "arithmetic": (
            "sqrt(lat_m^2 + lon_m^2), where lat_m is the latitude component times 111120 m per "
            "degree (1 degree = 60 NM = 60 x 1852 m, ICAO's own nautical mile) and lon_m is the "
            "longitude component times the same figure times cos(latitude) at I062/105's own "
            "latitude. The spherical constant is a DECLARED approximation: the true "
            "metres-per-degree of latitude varies by about 0.5 % between equator and pole, and "
            "the quantity being scaled is a standard deviation the source has already rounded to "
            "180/2^25 degrees"),
        "independence_assumed": (
            "YES, and the assumption is the SPECIFICATION'S SILENCE rather than a modelling "
            "choice. §5.2.26 states two component standard deviations and states a covariance in "
            "a SEPARATE subfield, #2 — in the CARTESIAN frame, which settlement 6 declines to "
            "invert — so there is no stated WGS-84 covariance to use. Taking the larger component "
            "would discard half the information and taking the sum would overstate the "
            "uncertainty by up to 41 %"),
        "declared_transform": (
            "I062/500 subfields.apw, in TRANSFORMS. The only declared transform in this adapter, "
            "and it is declared because the two components become one number and the never-drop "
            "check has to be told that rather than left to find two missing values"),
    }


# ====================================================================== the kinematics


def _kinematics(items: dict) -> tuple[Kinematics | None, dict | None]:
    """`Kinematics` from I062/185 and I062/220, and from nothing else.

    THE ONE PLACE A VECTOR BECOMES THE CDM'S SCALARS IN THIS ADAPTER, and the frame is the
    document's: §5.2.14's NOTE says "The y-axis points to the Geographical North at the location of
    the target", so the bearing is measured from `Vy` toward `Vx` and the call is `atan2(Vx, Vy)`
    and not `atan2(Vy, Vx)`. Getting that backwards produces a course reflected about 45 degrees,
    which is wrong everywhere and looks plausible everywhere.

    The aircraft's own ground speed (I062/380 SF#18) and track angle (SF#17) are NOT used: they are
    a different observer's statement and choosing between them and the tracker's is the arbitration
    settlement 1 refuses. The two aircraft-reported vertical rates (SF#13 and SF#14) are not used
    either, and there being TWO of them is the sharper form of the same argument.
    """
    velocity = items.get("I062/185")
    climb = items.get("I062/220")
    if velocity is None and climb is None:
        return None, None
    basis: dict[str, Any] = {}
    speed = course = None
    if velocity is not None:
        vx = codec.from_raw("velocity_mps", velocity["vx_raw"])
        vy = codec.from_raw("velocity_mps", velocity["vy_raw"])
        speed = math.hypot(vx, vy)
        course = math.degrees(math.atan2(vx, vy)) % 360.0
        basis["velocity"] = {
            "item": "I062/185",
            "vx_mps": vx, "vy_mps": vy,
            "vx_raw": velocity["vx_raw"], "vy_raw": velocity["vy_raw"],
            "lsb_mps": codec.bounds("velocity_mps")[2],
            "speed_arithmetic": "hypot(Vx, Vy)",
            "course_arithmetic": (
                "degrees(atan2(Vx, Vy)) mod 360. atan2(Vx, Vy) and NOT atan2(Vy, Vx), because "
                "§5.2.14's NOTE fixes the frame: 'The y-axis points to the Geographical North at "
                "the location of the target'. The components are parked beside the scalars so a "
                "course derived from a near-zero vector is visible for what it is"),
            "high_resolution_declined": (
                "§5.2.14's second NOTE says the 0.25 m/s resolution 'is not sufficient for all "
                "applications addressing the ground segment especially for slow moving targets' "
                "and points at I062/REF/MOI/FPVHR — a container Appendix A Edition 1.3 does not "
                "define. So on a surface target this is the resolution available, and the "
                "document says so"),
        }
    if climb is not None:
        feet_per_minute = codec.from_raw("rate_of_climb", climb["rate_raw"])
        basis["rate_of_climb"] = {
            "item": "I062/220",
            "feet_per_minute": feet_per_minute,
            "raw": climb["rate_raw"],
            "lsb_feet_per_minute": codec.bounds("rate_of_climb")[2],
            "sign": ("§5.2.17's NOTE: 'A positive value indicates a climb, whereas a negative "
                     "value indicates a descent' — the same sign convention climb_mps uses, so "
                     "no negation is applied"),
            "arithmetic": "feet per minute x 0.3048 / 60 = metres per second, exact in float64",
            "aircraft_rates_declined": (
                "I062/380 Subfields #13 and #14 are the aircraft's own barometric and geometric "
                "vertical rates. Neither reaches climb_mps: there are TWO of them and one of "
                "I062/220, so any promotion would be an arbitration between three numbers"),
        }
    return Kinematics(
        speed_mps=speed,
        course_deg=course,
        climb_mps=(None if climb is None
                   else codec.from_raw("rate_of_climb", climb["rate_raw"]) * 0.3048 / 60.0),
    ), basis


# ========================================================================= the identity


def _identity(record: dict, items: dict) -> tuple[list[SourceId], dict, str]:
    """Settlement 3's two-step chain. The track number is never step two."""
    address = ((items.get("I062/380") or {}).get("subfields", {}).get("adr") or {}).get("address")
    track_number = items["I062/040"]["track_number"]
    source = items["I062/010"]
    sac_sic = f"{source['sac']:02X}{source['sic']:02X}"
    if address is not None:
        system, external_id = ICAO24_SYSTEM, f"{address:06X}"
        note = (
            "I062/380 Subfield #1, the 24-bit Mode S Target Address, filed under ICAO24 — the "
            "same system name every adapter here that has a 24-bit Mode S address uses, so "
            "one airframe seen by a raw 1090ES frame, an ADS-B ground station, a radar, a "
            "NITS track and an SDPS derives the SAME entity_id without any of them "
            "coordinating. That is a pure function of the address and not a join. "
            "Settlement 3 step 1")
    else:
        system = REPORT_SYSTEM
        external_id = "|".join(str(part) for part in (
            sac_sic, items["I062/070"]["time_of_day_raw"], track_number, record["index"]))
        note = (
            "the record states no Mode S address, so the id is scoped to THIS RECORD — keyed on "
            "the SAC/SIC of the emitting system, the raw time of track information, the track "
            "number and the record index. Settlement 3 step 2. "
            "THE TRACK NUMBER IS IN THE KEY AND IS NOT THE BASIS OF IT, which is a distinction "
            "worth stating: inside a record-scoped id it distinguishes two tracks in one block, "
            "and it promises no continuity because the time of day is in the key beside it. "
            "Keying entity_id on (SAC/SIC, track number) alone was considered and DECLINED: the "
            "pair is unique within one SDPS at one moment and entity_id has no expiry, so a key "
            "that is reused after a track ends produces one entity spanning two aircraft and "
            "there is no field on Entity in which that can be disclosed. FORMAT_COVERAGE.md gap "
            "27 records the truncation — consecutive updates of one address-less system track get "
            "different entity_id values, and that is the honest statement. The continuity the "
            "format DOES state is carried where a consumer can act on it: the raw track number, "
            "TSB, TSE, I062/510's composed track number and I062/290's track age are all in the "
            "object")
    return (
        [SourceId(system=system, external_id=external_id)],
        {"system": system, "external_id": external_id,
         "entity_id": ids.derive(system, external_id, kind="entity"), "note": note,
         "track_number": track_number,
         "track_number_basis": (
             "I062/040, §5.2.3, 'Identification of a track', two octets, and its Encoding Rule is "
             "'This Item shall be present in every ASTERIX record'. Parked and NEVER the identity "
             "basis: sixteen bits allocated by the emitting system and recycled when a track ends "
             "would merge two airframes into one entity, which is false in the direction nothing "
             "downstream can detect. I062/080's TSB and TSE put the track boundary on the wire, "
             "and being able to see the boundary does not stop the number on the other side of it "
             "belonging to a different aircraft. ASTERIX itself found this worth a dedicated "
             "status bit in another part: CAT023's I023/100 bit 2 is 'Renumbering Indication for "
             "Track ID', whose NOTE reads 'the allocation of Track-IDs (Item I021/161) was "
             "re-started'. Different number space, same class of identifier"),
         "emitting_system": {
             "item": "I062/010", "sac": source["sac"], "sic": source["sic"],
             "external_id": sac_sic,
             "basis": (
                 "§5.2.1, 'Identification of the system sending the data', M in every record. "
                 "PARKED, not a SourceId — the CAT048 disposition and the INVERSE of CAT034's, "
                 "and the difference is the whole reason both rows exist: there the SAC/SIC IS "
                 "the object's identity because the station is the object, and here it identifies "
                 "the SDPS that formed the opinion. Filing a processor under the target's "
                 "identifiers is how a fused picture ends up with an entity per processor"),
             "note": ("The up-to-date list of SACs is published on the EUROCONTROL Web Site "
                      "(http://www.eurocontrol.int/asterix)"),
         }},
        # THE CAVEAT IS PRESENT ON EVERY OBJECT AND IS NOT CONDITIONAL, which is the opposite of
        # asterix_cat048.py's, where I048/030 code 16 warns of a duplicated Mode S address. This
        # category has AAC (Assigned Mode A Code Conflict), DUPT (Duplicate Mode 3/A Code) and IDD
        # (Duplicate Flight-ID) and not one bit about the address. An absent caveat field would
        # read as "no conflict"; what is true is "this category cannot tell you".
        "CAT062 carries no duplicate-Mode-S-address indication of any kind. I062/080's AAC is "
        "about an assigned Mode A code, DUPT about a duplicated Mode 3/A code and IDD about a "
        "duplicated Flight-ID; none of them is about the 24-bit address this entity may be keyed "
        "on. So unlike asterix_cat048.py, which raises a caveat from I048/030 code 16 "
        "('Duplicated or Illegal Mode S Aircraft Address'), there is nothing here to raise and "
        "the absence of a warning is not evidence of uniqueness",
    )


def _entity_type(items: dict, unresolved: dict) -> tuple[EntityType, dict]:
    """PLATFORM by default, refined only by I062/380 Subfield #21 and I062/300.

    Neither refinement touches affiliation, and both are the GMTIF platform-type refusal reached
    again: an emitter category is a performance and mass class and a vehicle fleet identification
    is an airport job description, and reading either as an allegiance or a severity is an
    identification decision.
    """
    basis: dict[str, Any] = {"default": (
        "PLATFORM. A system track is a track of a moving thing, and every value either refining "
        "item can carry is a vehicle, an aircraft or a fixed obstruction. Nothing in the category "
        "distinguishes a crewed from an uncrewed aircraft in a way the CDM has a member for — "
        "Appendix A's UAS/RPAS Status does say so and PLATFORM covers both, which is recorded as "
        "a gap-shaped absence rather than forced")}
    resolved = EntityType.PLATFORM
    ecat = ((items.get("I062/380") or {}).get("subfields", {}).get("emc") or {}).get("ecat")
    if ecat is not None:
        text = ECAT_TEXT.get(ecat)
        basis["emitter_category"] = {"raw": ecat, "text": text}
        if text is None or text == "reserved":
            unresolved["I062/380 SF#21 ECAT"] = {
                "raw": ecat,
                "reason": ("§5.2.24 Subfield #21 defines values 1 to 22 with 2, 4, 7-9, 17-19 and "
                           "23-24 spelled 'reserved'. This value is one this edition does not "
                           "assign, so entity_type keeps its default rather than being refined "
                           "from a code with no meaning"),
            }
        elif ecat in _ECAT_FACILITY:
            resolved = EntityType.FACILITY
            basis["emitter_category"]["refined_to"] = (
                "FACILITY. 'fixed ground or tethered obstruction' is the one emitter category "
                "that is not a vehicle at all — it does not move and is not a platform. The two "
                "surface-vehicle categories, 20 and 21, stay PLATFORM: an emergency vehicle is a "
                "vehicle, and 'surface emergency vehicle' is NOT read as an affiliation or a "
                "severity")
    vfi = (items.get("I062/300") or {}).get("vfi")
    if vfi is not None:
        text = VFI_TEXT.get(vfi)
        basis["vehicle_fleet"] = {
            "raw": vfi, "text": text,
            "refined_to": ("PLATFORM. All seventeen values are ground vehicles, so the item "
                           "confirms the default and refines nothing else. 7 'Emergency' and 8 "
                           "'Police' are NOT read as an affiliation or a severity — the GMTIF "
                           "platform-type refusal, reached again"),
        }
        if text is None:
            unresolved["I062/300 VFI"] = {
                "raw": vfi,
                "reason": ("§5.2.22 defines values 0 to 16 and this record states one above the "
                           "table. The value is parked; what is unresolved is what kind of "
                           "vehicle it is"),
            }
    return resolved, basis


# ======================================================================= the emergencies


def _emergency(items: dict, unresolved: dict) -> tuple[Severity, EventType, dict]:
    """`Event.severity` and `Event.event_type` from the THREE emergency statements.

    §5.2.6's `EMS`, §5.2.24 Subfield #11's `STAT` and Appendix A §2.7's `PS3`, and the document is
    explicit that they are independent and can disagree. `EMS`'s NOTE 1: "other than subfield #11
    of data item I062/380, these bits allow the SDPS to set the emergency indication as derived
    from OTHER SOURCES THAN ADS-B (e.g. based on the Mode 3/A code)."

    THE RULE, and each half is a decision:

    **Where `PS3` is present it is preferred**, because both core items are LOSSY by construction on
    ADS-B Version 3 equipment: their own back-mapping tables collapse `2 (UAS/RPAS Lost Link)` onto
    `4 (No communication)` and both distress values onto `1 (General emergency)`. So the core item
    is legally correct and less informative, and the REF has the value the aircraft sent.

    **Where the two core items disagree, the MORE SEVERE is taken and the disagreement is
    recorded.** Taking either one by position would make the field's meaning depend on which item
    the record happened to carry; taking the more severe is the only rule that cannot under-report,
    and `attributes.emergency_disagreement` is where a consumer sees that there were two.

    `I062/080`'s `IEC` — "Inconsistent Emergency Code", set when "the comparison between various
    sources has revealed an inconsistency" — is the tracker saying the same thing about its own
    inputs, and it is carried beside the disagreement rather than merged with it.
    """
    statements: list[dict] = []
    track = items.get("I062/080")
    if track is not None and len(track["octets"]) >= 5:
        value = track["octets"][4]["ems"]
        statements.append({"source": "I062/080 EMS", "raw": value, "text": EMS_TEXT.get(value),
                           "severity": _EMS_SEVERITY[value], "vocabulary": "pre-Version-3"})
    sab = ((items.get("I062/380") or {}).get("subfields", {}).get("sab") or {})
    if sab:
        value = sab["stat"]
        statements.append({"source": "I062/380 SF#11 STAT", "raw": value,
                           "text": EMS_TEXT.get(value), "severity": _EMS_SEVERITY[value],
                           "vocabulary": "pre-Version-3"})
    ps3 = (((items.get("RE") or {}).get("items", {}).get("v3") or {})
           .get("subfields", {}).get("ps3"))
    if ps3 is not None:
        if ps3["ps3_ep"]:
            value = ps3["ps3_val"]
            statements.append({"source": "I062/REF/PS3", "raw": value, "text": PS3_TEXT[value],
                               "severity": _PS3_SEVERITY[value], "vocabulary": "Version 3",
                               "back_maps_to": PS3_BACK_MAPPING[value]})
        else:
            statements.append({
                "source": "I062/REF/PS3", "raw": ps3["ps3_val"], "text": None,
                "severity": None, "vocabulary": "Version 3",
                "not_populated": (
                    "PS3#EP is 0, so the three value bits are NOT A STATEMENT and no severity is "
                    "taken from them. Appendix A's NOTE 2 is explicit that the Element Populated "
                    "bit exists for the future — 'Since in this edition of the REF I062/REF/PS3 "
                    "is the only Element in this Item, the Element Populated Bit strictly would "
                    "not be necessary' — and honouring it anyway is what keeps a later edition's "
                    "spare-bit use from silently becoming an emergency"),
            })

    preferred = next((s for s in statements
                      if s["source"] == "I062/REF/PS3" and s["severity"] is not None), None)
    if preferred is None:
        graded = [s for s in statements if s["severity"] is not None]
        if graded:
            preferred = min(graded, key=lambda s: _SEVERITY_ORDER.index(s["severity"]))

    basis: dict[str, Any] = {
        "statements": statements,
        "preferred": None if preferred is None else preferred["source"],
        "rule": (
            "I062/REF/PS3 wins where it is present and populated, because both core items are "
            "LOSSY on ADS-B Version 3 equipment by their own back-mapping tables — 2 becomes 4 "
            "and both distress values become 1. Otherwise the MORE SEVERE of the two core "
            "statements wins, because taking either by position would make the field's meaning "
            "depend on which item the record happened to carry"),
        "version_number_finding": (
            "§5.2.6's and §5.2.24's notes both say I062/REF/PS3 'is to be used exclusively for "
            "Version 3 ADS-B systems as defined in I062/380/SF#11/VN' — and THERE IS NO VN FIELD "
            "IN SUBFIELD #11. Its sixteen bits are AC, MN, DC, GBS, six spares and STAT. So the "
            "field that decides which vocabulary applies is named twice by the core specification "
            "and defined nowhere in it. What is used instead is the PRESENCE of PS3, which "
            "Appendix A §2.7 defines as 'Information transmitted by aircraft equipped with an "
            "ADS-B Version 3 System' — an inference from the REF, stated as one. "
            "FORMAT_COVERAGE.md ambiguity 13"),
    }
    graded = [s for s in statements if s["severity"] is not None]
    if len({s["severity"] for s in graded}) > 1:
        basis["disagreement"] = {
            "sources": [{"source": s["source"], "raw": s["raw"], "text": s["text"]}
                        for s in graded],
            "reason": ("two or more independent emergency statements in one record with different "
                       "severities. §5.2.6's NOTE 1 says EMS may be 'derived from other sources "
                       "than ADS-B', so the two are not expected to agree — carried, not resolved "
                       "away, and I062/080's IEC bit is the tracker saying the same thing"),
        }
    for statement in statements:
        if statement["text"] == "Undefined":
            unresolved[f"{statement['source']} = 7"] = {
                "raw": statement["raw"],
                "reason": ("§5.2.6 spells value 7 'Undefined' in the item's own table, which is a "
                           "stated non-statement rather than a value this edition does not "
                           "define. ADVISORY is the CDM's middle value and the only one that "
                           "leaves the record visible to a consumer filtering on severity while "
                           "claiming nothing about what it means"),
            }
    if preferred is None or preferred["severity"] in (None, Severity.INFO):
        return Severity.INFO, EventType.TRACK_UPDATE, basis
    return preferred["severity"], EventType.ALERT, basis


# ======================================================================== the adapter


class AsterixCat062Adapter(Adapter):
    """CAT062 data blocks in, CDM out; CAT062-origin Entities back out to a data block."""

    name = "cat062"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: EMPTY, and that is a claim rather than an oversight — the claim `asterix_cat021.py`,
    #: `asterix_cat048.py` and `asterix_cat034.py` all make, for the same reason and against a
    #: prediction this row set got wrong.
    #:
    #: A declared transform is an EXEMPTION from the never-drop check, and this adapter needs none:
    #: every wire value is parked verbatim as well as converted — the octets of every item at
    #: `attributes.cat062_items`, the raw integers beside every decoded figure, and the whole
    #: decoded item tree at `attributes.source_extras`. So `lossless.unrepresented()` runs at full
    #: strength over every fixture with nothing excused.
    #:
    #: **THE PHASE 1 ROW SET PREDICTED ONE ENTRY AND WAS WRONG, and the correction is recorded
    #: rather than the row quietly rewritten.** It reasoned that `I062/500` Subfield #3's two
    #: angular components become ONE metric scalar in `Position.accuracy_m` and that the two
    #: DECIMAL DEGREE figures therefore appear nowhere in the output. Both halves are true and the
    #: conclusion does not follow: the never-drop check compares SOURCE LEAF VALUES against output
    #: values, and the source leaves are the two RAW INTEGERS, which are parked at
    #: `attributes.position_basis.accuracy`. The degrees were never a leaf of the parsed form. So
    #: the exemption would have covered nothing, and an exemption covering nothing reads as a live
    #: ruling — measured by removing it and re-running the check over all 28 fixtures, which
    #: reported zero losses either way. FORMAT_COVERAGE.md records it under "What Phase 2 changed
    #: in the Phase 1 row set".
    #:
    #: And structurally the declaration would have been fragile even if it had been needed:
    #: `TRANSFORMS` matches dotted paths, and this adapter's parsed form has an ARRAY of records at
    #: its root, so any path it could name is either per-record-index or the whole subtree.
    TRANSFORMS: dict[str, str] = {}

    #: Dotted paths in a parsed RECORD this adapter re-emits under a name of its own. Short on
    #: purpose: the decoded values are parked wholesale and the canonical fields are additions on
    #: top, so consuming a mapped field would DELETE the evidence rather than move it.
    CONSUMED = ("index", "fspec", "item_octets", "record_count")

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One data block -> [Entity, Event] per record, in block order.

        Several records in one block are several TRACK UPDATES, not one track's history. They may
        name several tracks, and two records of one track number are two statements about it at two
        instants rather than one accumulated state — assembling that state is exactly the
        accumulation settlement 1 refuses, and the CDM makes it expressible for a consumer rather
        than performing it here. **No `Track` is ever emitted**, and the reason is not the
        arithmetic: `Track.samples` are observations across time and one record is one state vector
        at one instant.
        """
        parsed = self._as_parsed(raw)
        records = parsed.get("records")
        if not isinstance(records, list) or not records:
            raise Cat062ParseError(
                "CAT062 payload holds no records — refusing to translate; top-level keys: "
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
        raise Cat062ParseError(
            f"a CAT062 payload is a data block (bytes) or its parsed twin (dict), "
            f"got {type(raw).__name__}"
        )

    def _translate(self, record: dict, block: dict, received_at: _dt.datetime,
                   source: Any) -> tuple[Entity, Event]:
        items = record["items"]
        unavailable: list[str] = []
        unresolved: dict[str, Any] = {}

        observed_at, time_basis = _observed_at(items, received_at)
        source_ids, identity_basis, identity_caveat = _identity(record, items)
        position, position_basis = _position(items, unresolved)
        kinematics, kinematics_basis = _kinematics(items)
        entity_type, entity_type_basis = _entity_type(items, unresolved)
        severity, event_type, emergency_basis = _emergency(items, unresolved)

        attributes = self._attributes(record, block, items, identity_basis, identity_caveat,
                                      position_basis, entity_type_basis, unavailable, unresolved)
        entity = Entity(
            source=source,
            source_ids=source_ids,
            entity_id=identity_basis["entity_id"],
            entity_type=entity_type,
            # UNKNOWN, ALWAYS. §5.2.6's MD4 and MD5 carry "Friendly target" as a value and it is
            # not read as an affiliation; §5.2.25's GAT/OAT carries "Operational Air Traffic" and
            # that is a flight-rules category, not an allegiance; the emitter category carries a
            # fighter's performance class and that is not one either. Three candidate inferences,
            # three refusals, and the reasons are on the rows.
            affiliation=Affiliation.UNKNOWN,
            symbol=symbology.sidc_from_affiliation(Affiliation.UNKNOWN,
                                                   synthetic=self._synthetic),
            position=position,
            kinematics=kinematics,
            attributes=attributes,
            valid_from=observed_at,
            # None on EVERY record, INCLUDING one where TSE is set. I062/080's TSE is "last message
            # transmitted to the user for the track", which ends the TRACK; valid_to on an entity
            # whose entity_id is a 24-bit airframe address would say the aircraft ceased to exist.
            # The CAT048 disposition, and the flag is in Event.payload where a consumer can act.
            valid_to=None,
            # None, always. I062/500's figures are metric standard deviations and I062/080's CNF is
            # a two-valued confirmed/tentative flag; mapping either to a 0..1 float would invent a
            # scale the source does not state.
            confidence=None,
        )
        event = Event(
            source=source,
            source_ids=source_ids,
            event_id=ids.derive(
                identity_basis["system"],
                f"{identity_basis['external_id']}|{times.render(observed_at)}|{record['index']}",
                kind="event"),
            event_type=event_type,
            severity=severity,
            related_entities=[entity.entity_id],
            # None, ALWAYS. The category carries no geometry: I062/105 is a point (which is a
            # Position, not an Event geometry), I062/100 is in a frame settlement 6 declines to
            # invert, and I062/380 Subfield #9's trajectory intent points are PREDICTIONS. A
            # LineString through predicted waypoints would render as a flown path.
            geometry=None,
            payload=self._payload(record, block, items, time_basis, kinematics_basis,
                                  emergency_basis, unresolved),
            observed_at=observed_at,
            received_at=received_at,
        )
        return entity, event

    # ------------------------------------------------------------------ the two bags

    def _attributes(self, record: dict, block: dict, items: dict, identity_basis: dict,
                    identity_caveat: str, position_basis: dict, entity_type_basis: dict,
                    unavailable: list[str], unresolved: dict[str, Any]) -> dict:
        attributes: dict[str, Any] = {}
        attributes["cat062_block"] = dict(block)
        attributes["cat062_fspec"] = record["fspec"]
        attributes["cat062_items"] = dict(record.get("item_octets") or {})
        attributes["data_source"] = identity_basis["emitting_system"]
        attributes["identity_basis"] = identity_basis["note"]
        attributes["identity_caveat"] = identity_caveat
        attributes["track_number"] = {
            "raw": identity_basis["track_number"],
            "basis": identity_basis["track_number_basis"],
        }
        attributes["entity_type_basis"] = entity_type_basis
        attributes["affiliation_basis"] = (
            "UNKNOWN, always, and three separate inferences are declined to keep it that way. "
            "§5.2.6's MD4 and MD5 spell one value 'Friendly target' — an authenticated "
            "military-mode reply says a cryptographic exchange succeeded, and reading it as an "
            "affiliation is an IDENTIFICATION DECISION, which is the asterix_cat021.py Mode 5 "
            "refusal. §5.2.25 Subfield #4's GAT/OAT spells one value 'Operational Air Traffic', "
            "which is a set of flight rules and not an allegiance. §5.2.24 Subfield #21 spells one "
            "emitter category 'highly manoeuvrable (5g acceleration capability) and high speed "
            "(>400 knots cruise)', which describes a fighter and is a performance class — the "
            "GMTIF platform-type refusal. All three are parked with the document's own wording so "
            "a fusion layer can make the call where it is attributable")
        attributes["symbol_basis"] = (
            "derived from the affiliation through symbology.sidc_from_affiliation, so every "
            "CAT062 track is an UNKNOWN glyph in the reality or exercise context its "
            "SourceRef.synthetic states. CAT062 carries no symbology of any kind")
        attributes["integrity_basis"] = (
            "CAT062 defines NO checksum at any level — neither §4.6 nor §4.7 nor any §5.2 item "
            "specifies a CRC, checksum or parity field at block, record or item level. What "
            "passed is the structural gate: LEN matched the buffer, the records tiled it exactly, "
            "every FSPEC bit named a defined and non-spare FRN, every compound item's presence "
            "bits named a subfield that exists, every FX led somewhere §5.2 defines, every "
            "repetitive item's REP was non-zero, the Reserved Expansion Field's own length tiled "
            "its contents exactly, and the four items whose Encoding Rule reads 'This Item shall "
            "be present in every ASTERIX record' were present. "
            "THIS GATE IS THINNER THAN CAT034'S AND THE DIFFERENCE IS THE ABSENCE OF A TABLE 2: "
            "§4.1 gives this category ONE message type, so there is no per-type expectation for a "
            "record to be internally inconsistent with. A record carrying only the four mandatory "
            "items is legal, minimal and complete. A single bit flipped inside a fixed-length "
            "field satisfies every check above and reaches the CDM as a track position")
        attributes["position_basis"] = position_basis
        if position_basis.get("item"):
            attributes["position_quantisation_m"] = {
                "quoted": codec.WGS84_25_QUANTISATION_NOTE,
                "basis": ("PARKED, and deliberately NOT written to Position.accuracy_m. "
                          "180/2^25 degrees is the QUANTISATION STEP of the encoding — the "
                          "finest difference the field can express, and the finest in this "
                          "repository — and reporting it as an accuracy would claim the tracker "
                          "knows where the target is to 0.6 m when the document says only that it "
                          "cannot say so more finely. accuracy_m comes from I062/500 Subfield #3 "
                          "or stays None"),
            }
        attributes["implementation_dependent"] = {
            "items": list(IMPLEMENTATION_DEPENDENT),
            "quoted": IMPLEMENTATION_DEPENDENT_QUOTE,
            "basis": (
                "§4.8 is a NORMATIVE DELEGATION of meaning to a per-deployment Interface Control "
                "Document, which is not a document this repository could acquire. Every other "
                "park in this adapter is a park because the CDM has no home for the value; these "
                "two are parks because THE DOCUMENT SAYS the value's meaning is not standardised. "
                "§5.2.23 repeats it twice more for I062/340: 'The term \"last report\" may refer "
                "to the \"latest used\" or \"latest measured\". The actual meaning is "
                "implementation dependent' and 'The availability of the various data items "
                "differs depending on the surveillance technology used and is implementation "
                "dependent.' A consumer comparing I062/340 across two SDPSs without knowing this "
                "will get a number"),
        }
        attributes["fusion_provenance"] = self._fusion_provenance(items)
        self._park_flight_plan(items, attributes)
        self._park_aircraft_derived(items, attributes)
        self._park_expansion(items, attributes)
        conformance = self._encoder_conformance(items)
        if conformance:
            attributes["encoder_conformance"] = conformance
        attributes["unavailable_fields"] = sorted(unavailable)
        attributes["unresolved_raw"] = unresolved
        attributes["source_extras"] = lossless.residual(record, self.CONSUMED)
        return attributes

    # ------------------------------------------------------------------ settlement 1

    def _fusion_provenance(self, items: dict) -> dict:
        """Every item that is the upstream tracker's statement about its own processing.

        Collected under ONE key, deliberately, and with the SAC/SIC of the system that said it, so
        that a consumer can see whose opinion each of these is. Settlement 1's whole argument is
        that translating a fused product is not fusing, and the argument is only checkable if the
        statements are identifiable as statements — scattered through `attributes` alongside the
        target's own measurements they would read as facts about the aircraft.
        """
        source = items["I062/010"]
        provenance: dict[str, Any] = {
            "stated_by": {"sac": source["sac"], "sic": source["sic"],
                          "external_id": f"{source['sac']:02X}{source['sic']:02X}"},
            "basis": (
                "EVERY FIELD BELOW IS THE UPSTREAM SDPS'S STATEMENT ABOUT ITS OWN PROCESSING, not "
                "a measurement of the target. §3.1.11 defines a track as a 'Time sequence of "
                "state vectors of an object estimated by some real time filtering technique using "
                "surveillance data as input', §3.1.1 defines amalgamation as merging tracks from "
                "co-operating systems, and §3.1.2 defines a Calculated Item as one derived "
                "'through an intermediate processing such as transformation of co-ordinates, "
                "tracking, code conversion'. So the document is explicit that its content has "
                "been through a fusion process, and this adapter translates that content and "
                "performs no fusion of its own. Nothing here is acted on: no age becomes an "
                "instant, no staleness flag suppresses a value, no reliability flag arbitrates "
                "between two altitudes, no contributing sensor becomes an object or a join"),
        }
        track = items.get("I062/080")
        if track is not None:
            octets = track["octets"]
            flags: dict[str, Any] = {}
            primary = octets[0]
            flags["mon"] = {
                "raw": primary["mon"],
                "text": "Monosensor track" if primary["mon"] else "Multisensor track",
                "basis": ("THE MOST DIRECT SINGLE BIT IN THE CATEGORY: the tracker saying whether "
                          "it fused anything for this track"),
            }
            flags["mrh"] = {
                "raw": primary["mrh"],
                "text": ("Geometric altitude more reliable" if primary["mrh"]
                         else "Barometric altitude (Mode C) more reliable"),
                "basis": ("the tracker's assessment, and it ARBITRATES NOTHING here. §5.2.6's "
                          "fourth NOTE: 'Data Items I062/130, I062/135, and I062/136 may be "
                          "transmitted in parallel whenever the respective information is "
                          "available. This is independent from the value transmitted on I062/080 "
                          "(MRH).' Position.alt_m comes from I062/130 because it is the one item "
                          "defined as a height above the WGS 84 ellipsoid, not because MRH said "
                          "so — settlement 5"),
            }
            flags["src"] = {
                "raw": primary["src"], "text": SRC_TEXT[primary["src"]],
                "basis": ("the source of the calculated altitude for I062/130, and its first NOTE "
                          "says it 'may be sent whether data item I062/130 is present or not'. "
                          "PARKED and never written to Position.position_source, which is about "
                          "the HORIZONTAL fix — and two of these eight values, 'speed look-up "
                          "table' and 'default height', describe an altitude that was not "
                          "measured at all"),
            }
            flags["cnf"] = {"raw": primary["cnf"],
                            "text": "Tentative track" if primary["cnf"] else "Confirmed track"}
            if len(octets) >= 3:
                third = octets[2]
                flags["ama"] = {
                    "raw": third["ama"],
                    "text": ("track resulting from amalgamation process" if third["ama"]
                             else "track not resulting from amalgamation process"),
                    "basis": ("the clearest statement in the category that the input is fused. "
                              "§3.1.1: 'Amalgamation is the process by which tracks from "
                              "co-operating systems are merged to form an “amalgamated” track'"),
                }
            if len(octets) >= 4:
                fourth = octets[3]
                staleness = {name: fourth[name] for name in
                             ("cst", "psr", "ssr", "mds", "ads")}
                if len(octets) >= 6:
                    staleness["mlat"] = octets[5]["mlat"]
                if len(octets) >= 7:
                    staleness["m5i"] = octets[6]["m5i"]
                flags["staleness"] = {
                    "raw": staleness,
                    "basis": (
                        "coasting, plus one bit per technology reading 'Age of the last received "
                        "... track update is higher than system dependent threshold'. THE "
                        "THRESHOLD IS SYSTEM-DEPENDENT AND UNSTATED, so these are the tracker's "
                        "verdicts and not derivable figures. NOTES 2 and 3 are load-bearing and "
                        "are carried verbatim: 'If the system supports the technology, default "
                        "value (0) means that the technology was used to produce the report' and "
                        "'If the system does not support the technology, default value is "
                        "MEANINGLESS.' So a clear bit means two different things and the record "
                        "does not say which — which is why a clear bit is never inverted into "
                        "'this technology contributed'"),
                    "extended_coasting_unreachable": (
                        "NOTE 4 points at I062/REF/STS/CSX for an extended coasting indication, "
                        "and Appendix A Edition 1.3's STS defines FDR and LNAV and no CSX. One of "
                        "the eight REF containers the core specification names and its own newest "
                        "appendix does not define"),
                }
                flags["suc"] = {"raw": fourth["suc"],
                                "text": ("Special Used Code (Mode A codes to be defined in the "
                                         "system to mark a track with special interest)"
                                         if fourth["suc"] else "Default value")}
                flags["aac"] = {"raw": fourth["aac"],
                                "text": ("Assigned Mode A Code Conflict (same discrete Mode A "
                                         "Code assigned to another track)" if fourth["aac"]
                                         else "Default value")}
            if len(octets) >= 5:
                fifth = octets[4]
                flags["sds"] = {"raw": fifth["sds"], "text": SDS_TEXT[fifth["sds"]]}
                flags["pft"] = {
                    "raw": fifth["pft"],
                    "text": "Potential False Track Indication" if fifth["pft"] else "No indication",
                    "basis": (
                        "PARKED rather than raised, and the document declines to standardise what "
                        "to do with it: 'If and how this information is processed and displayed "
                        "on the CWP is a LOCAL MATTER AND NOT SUBJECT TO THE CATEGORY 062 "
                        "SPECIFICATION.' So this adapter does not decide either. And it is NOT "
                        "read as InterferenceType.SPOOFING or EventType.GNSS_INTERFERENCE: that "
                        "enum member is paired with GnssInterferencePayload, whose fields exist "
                        "for the PNTMAP adapter, and a possibly-spoofed radar track is not a GNSS "
                        "interference event. FORMAT_COVERAGE.md gap 29"),
                }
                flags["fplt"] = {
                    "raw": fifth["fplt"],
                    "text": ("Track created / updated with FPL data" if fifth["fplt"]
                             else "Default value"),
                    "basis": (
                        "THE ONE BIT THAT SAYS THE POSITION MAY NOT BE A MEASUREMENT OF ANYTHING. "
                        "Its NOTE: the target report 'has been updated by flight plan related "
                        "data BECAUSE NO SURVEILLANCE DATA WAS AVAILABLE for the target, or was "
                        "created based on flight plan related data in areas with no "
                        "surveillance'"),
                }
            if len(octets) >= 2:
                second = octets[1]
                flags["fpc"] = {
                    "raw": second["fpc"],
                    "text": ("Flight plan correlated" if second["fpc"]
                             else "Not flight-plan correlated"),
                    "basis": ("the bit that says whether everything in I062/390 is about this "
                              "target. A consumer reading I062/390 without reading this bit is "
                              "reading an uncorrelated flight plan"),
                }
                flags["aff"] = {
                    "raw": second["aff"],
                    "text": ("ADS-B data inconsistent with other surveillance information"
                             if second["aff"] else "default value"),
                    "basis": "the tracker reporting a disagreement between its own inputs",
                }
                flags["simulated_flag"] = {
                    "raw": second["sim"],
                    "text": "Simulated track" if second["sim"] else "Actual track",
                    "basis": (
                        "PARKED and it does NOT set SourceRef.synthetic. `synthetic` states "
                        "whether the object came from a real source AS THIS PLATFORM IS DEPLOYED, "
                        "and a payload field cannot decide that: a live SDPS can emit a simulated "
                        "track and an exercise replay can emit an actual one. The GMTIF "
                        "settlement 4 ruling and the CAT048 one, reached again — and note that "
                        "I062/340 Subfield #6 carries TWO more such bits, SIM and TST"),
                }
                flags["tsb"] = {"raw": second["tsb"],
                                "text": ("first message transmitted to the user for the track"
                                         if second["tsb"] else "default value")}
                flags["tse"] = {
                    "raw": second["tse"],
                    "text": ("last message transmitted to the user for the track"
                             if second["tse"] else "default value"),
                    "basis": ("the track lifecycle, on the wire. It does NOT set Entity.valid_to: "
                              "this ends the TRACK, and valid_to on an entity whose entity_id is "
                              "a 24-bit airframe address would say the aircraft ceased to exist"),
                }
                flags["stp"] = {"raw": second["stp"],
                                "text": "Slave Track Promotion" if second["stp"] else "default"}
                flags["kos"] = {"raw": second["kos"],
                                "text": ("Background service used" if second["kos"]
                                         else "Complementary service used")}
            if len(octets) >= 6:
                sixth = octets[5]
                flags["duplicates"] = {
                    "raw": {name: sixth[name] for name in ("dupt", "dupf", "dupm", "idd")},
                    "text": {"dupt": "Duplicate Mode 3/A Code", "dupf": "Duplicate Flight Plan",
                             "dupm": "Duplicate Flight Plan due to manual correlation",
                             "idd": "Duplicate Flight-ID"},
                    "basis": ("four correlation-failure statements, each with its own NOTE. NONE "
                              "OF THEM IS ABOUT THE MODE S ADDRESS, which is why "
                              "attributes.identity_caveat says this category warns of no address "
                              "duplication"),
                }
                flags["sfc"] = {
                    "raw": sixth["sfc"],
                    "text": "Surface target" if sixth["sfc"] else "Default value",
                    "basis": ("§4.8 marks THIS BIT SPECIFICALLY as implementation dependent, and "
                              "NOTE 5 says it 'is set to 1 when the SDPS considers the target to "
                              "be on the Surface (the actual meaning is implementation dependent "
                              "— please refer to chapter 4.8 above)'. It does NOT change "
                              "entity_type: a surface target may be an aircraft or a vehicle and "
                              "the bit does not say which"),
                }
                flags["iec"] = {
                    "raw": sixth["iec"],
                    "text": ("Inconsistent Emergency Code" if sixth["iec"] else "Default value"),
                    "basis": ("the tracker reporting that its own emergency inputs disagree, "
                              "which is what payload.emergency_basis.disagreement is beside"),
                }
            flags["military"] = self._military_flags(octets)
            provenance["track_status"] = flags
        ages = items.get("I062/290")
        if ages is not None:
            provenance["update_ages"] = self._update_ages(ages)
        data_ages = items.get("I062/295")
        if data_ages is not None:
            provenance["data_ages"] = self._data_ages(data_ages)
        accuracies = items.get("I062/500")
        if accuracies is not None:
            provenance["estimated_accuracies"] = self._estimated_accuracies(accuracies)
        measured = items.get("I062/340")
        if measured is not None:
            provenance["measured_information"] = self._measured(measured)
        composed = items.get("I062/510")
        if composed is not None:
            provenance["composed_track_number"] = {
                "units": [dict(unit) for unit in composed["units"]],
                "basis": (
                    "§5.2.27, an ORDERED list, master first — its NOTE says 'The first unit "
                    "identification identifies the unit that is responsible for the track "
                    "amalgamation', so the order is data. THE ITEM THAT PROVES SETTLEMENT 3'S "
                    "POINT: it exists because a bare track number is ambiguous between "
                    "co-operating units, and it carries a system unit identification alongside "
                    "each number precisely so the PAIR is unique. No slave track number is joined "
                    "to anything — each names another unit's track in that unit's own space"),
            }
        return provenance

    def _military_flags(self, octets: list[dict]) -> dict:
        out: dict[str, Any] = {"basis": (
            "PARKED with the document's own wording and NOT read as an affiliation. An "
            "authenticated military-mode reply says a cryptographic exchange succeeded; reading it "
            "as FRIENDLY is an identification decision, which is a fusion judgement and not a "
            "fact on a wire — the asterix_cat021.py Mode 5 refusal reached again")}
        if len(octets) >= 3:
            third = octets[2]
            out["md4"] = {"raw": third["md4"], "text": MILITARY_MODE_TEXT[third["md4"]]}
            out["md5"] = {"raw": third["md5"], "text": MILITARY_MODE_TEXT[third["md5"]]}
            out["military_emergency"] = {
                "raw": third["me"],
                "text": ("Military Emergency present in the last report received from a sensor "
                         "capable of decoding this data" if third["me"] else "default value"),
                "basis": ("PARKED and it does NOT raise Event.severity. It is a statement about a "
                          "PAST REPORT from an unnamed sensor; the emergency vocabularies in this "
                          "category are I062/080's EMS, I062/380 Subfield #11's STAT and "
                          "I062/REF/PS3, and raising severity from a fourth independent source "
                          "would make the field's meaning depend on which one the record carried"),
            }
            out["military_identification"] = {
                "raw": third["mi"],
                "text": ("Military Identification present in the last report received from a "
                         "sensor capable of decoding this data" if third["mi"] else "default"),
            }
        if len(octets) >= 7:
            out["m5i_age_unreachable"] = (
                "the Sixth Extent's NOTE says 'Age of Mode 5 interrogation is provided in "
                "I062/REF/MOI/AM5I', and Appendix A Edition 1.3 defines no MOI item at all")
        return out

    def _update_ages(self, ages: dict) -> dict:
        """I062/290's ten per-technology ages, and the formula that is recorded not applied."""
        labels = {
            "trk": "Actual track age since first occurrence",
            "psr": "Age of the last primary detection used to update the track",
            "ssr": "Age of the last secondary detection used to update the track",
            "mds": "Age of the last Mode S detection used to update the track",
            "ads": "Age of the last ADS-C report used to update the track",
            "es": "Age of the last 1090 Extended Squitter ADS-B report used to update the track",
            "vdl": "Age of the last VDL Mode 4 ADS-B report used to update the track",
            "uat": "Age of the last UAT ADS-B report used to update the track",
            "lop": "Age of the last magnetic loop detection",
            "mlt": "Age of the last MLT detection",
        }
        out: dict[str, Any] = {"basis": (
            "§5.2.20. Every age is carried as an AGE IN SECONDS and never as an instant. NOTE 3 "
            "gives the tracker's own formula — 'Age = Time of track information - Time of last "
            "detection used to update the track' — and NOTE 4 says 'The time of last detection is "
            "derived from monosensor category time of day', so the ages are anchored in ANOTHER "
            "CATEGORY'S clock. Performing the subtraction here would produce an instant "
            "indistinguishable in the output from one the source stated, which is settlement 1's "
            "fifth refusal"), "formula": (
            "Age = Time of track information - Time of last detection used to update the track"),
            "absence_semantics": (
                "NOTE 5: 'If the data has never been received, then the corresponding subfield is "
                "not sent.' SO AN ABSENT SUBFIELD IS A STATED NEVER, not an unknown — the "
                "strongest absence semantics in the category, and the opposite of I062/080's "
                "technology bits, whose clear value is 'meaningless' if the technology is "
                "unsupported"),
            "ages": {}}
        _low, high, _lsb = codec.bounds("age_quarter_s")
        _low16, high16, _lsb16 = codec.bounds("age_quarter_s_16")
        for name, subfield in ages["subfields"].items():
            form = "age_quarter_s_16" if name == "ads" else "age_quarter_s"
            seconds = codec.from_raw(form, subfield["age_raw"])
            ceiling = high16 if name == "ads" else high
            entry: dict[str, Any] = {
                "raw": subfield["age_raw"], "seconds": seconds,
                "definition": labels[name],
                "lsb_seconds": codec.bounds(form)[2],
            }
            if seconds >= ceiling:
                entry["at_or_above_maximum"] = AT_OR_ABOVE_MAXIMUM_NOTE
            if name == "ads":
                entry["width_note"] = (
                    "TWO OCTETS, where the other nine subfields of this item are one. Edition "
                    "1.21's change record reads 'Length of I062/290/SI#5 corrected', so an "
                    "earlier edition had it wrong — and a decoder that read it as one octet would "
                    "desynchronise the record with no length error anywhere")
            if name == "trk":
                entry["excepted_from_the_formula"] = (
                    "NOTE 3 says 'EXCEPT FOR TRACK AGE, the ages are counted from Data Item "
                    "I062/070', so this one is measured from the track's first occurrence")
            out["ages"][name] = entry
        return out

    def _data_ages(self, ages: dict) -> dict:
        """I062/295's thirty-one ages, each naming the I062/380 subfield it dates."""
        dates = {
            "mfl": "I062/136 and I062/REF/MOI/ALTQCMFL", "md1": "I062/110 Mode 1",
            "md2": "I062/120", "mda": "I062/060 or I062/REF/MTI/EXM3A", "md4": "Mode 4 code",
            "md5": "I062/110 Mode 5", "mhg": "I062/380 Subfield #3",
            "ias": "I062/380 Subfield #4", "tas": "I062/380 Subfield #5",
            "sal": "I062/380 Subfield #6", "fss": "I062/380 Subfield #7",
            "tid": "I062/380 Subfield #8", "com": "I062/380 Subfield #10",
            "sab": "I062/380 Subfield #11", "acs": "I062/380 Subfield #12",
            "bvr": "I062/380 Subfield #13", "gvr": "I062/380 Subfield #14",
            "ran": "I062/380 Subfield #15", "tar": "I062/380 Subfield #16",
            "tan": "I062/380 Subfield #17", "gsp": "I062/380 Subfield #18",
            "vun": "I062/380 Subfield #19", "met": "I062/380 Subfield #20",
            "emc": "I062/380 Subfield #21", "pos": "I062/380 Subfield #22",
            "gal": "I062/380 Subfield #23", "pun": "I062/380 Subfield #24",
            "mb": "I062/380 Subfield #25", "iar": "I062/380 Subfield #26",
            "mac": "I062/380 Subfield #27", "bps": "I062/380 Subfield #28",
        }
        _low, high, lsb = codec.bounds("age_quarter_s")
        out: dict[str, Any] = {"basis": (
            "§5.2.21. Thirty-one one-octet ages at 1/4 s, each parked WITH THE FIELD IT DATES — "
            "which is the only thing that makes thirty-one integers readable. The item's final "
            "NOTE: 'In all the subfields, the age is the time delay since the value was measured.' "
            "Recorded and not applied, settlement 1's fifth refusal"), "ages": {}}
        for name, subfield in ages["subfields"].items():
            seconds = codec.from_raw("age_quarter_s", subfield["age_raw"])
            entry: dict[str, Any] = {"raw": subfield["age_raw"], "seconds": seconds,
                                     "dates": dates[name], "lsb_seconds": lsb}
            if seconds >= high:
                entry["at_or_above_maximum"] = AT_OR_ABOVE_MAXIMUM_NOTE
            if name == "ias":
                entry["superseded"] = (
                    "dates the SUPERSEDED I062/380 Subfield #4. Its own NOTE says the subfield 'is "
                    "kept free in order to prevent a full incompatibility with previous releases', "
                    "and Subfields #29 and #30 date the two replacements separately — so a record "
                    "may legally carry all three")
            if name == "mb":
                entry["one_age_for_many_registers"] = (
                    "ONE age for the whole repetitive I062/380 Subfield #25, so a record carrying "
                    "five BDS registers carries one age for all five. Its NOTE points at "
                    "I062/REF/MOI/SI#10 for a per-register version, which Appendix A Edition 1.3 "
                    "does not define")
            out["ages"][name] = entry
        return out

    def _estimated_accuracies(self, accuracies: dict) -> dict:
        """I062/500's eight subfields. One reaches `Position.accuracy_m`; seven are parked."""
        out: dict[str, Any] = {"basis": (
            "§5.2.26, 'Overview of all important accuracies' — THE TRACKER'S OWN ESTIMATED "
            "STANDARD DEVIATIONS, which makes them settlement 1 material. All eight subfields "
            "carry 'Maximum value means maximum value or above', so a saturated value is a FLOOR "
            "and not a measurement. Subfield #3 reaches Position.accuracy_m; the other seven are "
            "parked, and Subfields #4, #5 and #8 are the third source in this repository to state "
            "a vertical accuracy the CDM has no field for — FORMAT_COVERAGE.md gap 6")}
        subs = accuracies["subfields"]
        if "apc" in subs:
            out["cartesian_position"] = {
                "x_metres": codec.from_raw("accuracy_position_m", subs["apc"]["x_raw"]),
                "y_metres": codec.from_raw("accuracy_position_m", subs["apc"]["y_raw"]),
                "x_raw": subs["apc"]["x_raw"], "y_raw": subs["apc"]["y_raw"],
                "basis": ("in the CARTESIAN frame settlement 6 declines to invert, so it is NOT "
                          "used for Position.accuracy_m even when Subfield #3 is absent"),
            }
        if "cov" in subs:
            out["xy_covariance"] = {
                "metres": codec.from_raw("accuracy_covariance_m", subs["cov"]["covariance_raw"]),
                "raw": subs["cov"]["covariance_raw"],
                "formula": "XY covariance component = sign{Cov(X,Y)} * sqrt{abs[Cov (X,Y)]}",
                "basis": (
                    "the ONE signed accuracy field, in the Cartesian frame. NOTE 2 prints 'The "
                    "maximum value for the (unsigned) XY covariance component is 16.383 km' and "
                    "sixteen bits at 0.5 m reach 16383.5 m, so the printed figure is the field's "
                    "positive extreme minus one LSB and is not a bound the encoder could honour "
                    "as stated. The WIDTH is the bound and the figure is recorded — the "
                    "cat034_codec.py `rho` disposition"),
            }
        if "apw" in subs:
            out["wgs84_position"] = {
                "latitude_component_deg": codec.from_raw("accuracy_position_deg",
                                                         subs["apw"]["x_raw"]),
                "longitude_component_deg": codec.from_raw("accuracy_position_deg",
                                                          subs["apw"]["y_raw"]),
                "x_raw": subs["apw"]["x_raw"], "y_raw": subs["apw"]["y_raw"],
                "basis": "THE ONE SUBFIELD THAT REACHES A CANONICAL FIELD — see position_basis",
            }
        for name, form, label in (
                ("aga", "accuracy_geometric_altitude", "calculated geometric altitude, in feet"),
                ("aba", "accuracy_barometric_altitude",
                 "calculated barometric altitude, in flight levels"),
                ("arc", "accuracy_rate_of_climb",
                 "calculated rate of climb/descent, in feet per minute")):
            if name in subs:
                value = codec.from_raw(form, subs[name]["accuracy_raw"])
                entry = {"value": value, "raw": subs[name]["accuracy_raw"], "of": label}
                if value >= codec.bounds(form)[1]:
                    entry["at_or_above_maximum"] = AT_OR_ABOVE_MAXIMUM_NOTE
                out[name] = entry
        for name, form, label in (
                ("atv", "accuracy_velocity_mps", "calculated track velocity, in m/s per component"),
                ("aa", "accuracy_acceleration_mps2",
                 "calculated acceleration, in m/s^2 per component")):
            if name in subs:
                out[name] = {
                    "x": codec.from_raw(form, subs[name]["x_raw"]),
                    "y": codec.from_raw(form, subs[name]["y_raw"]),
                    "x_raw": subs[name]["x_raw"], "y_raw": subs[name]["y_raw"], "of": label,
                }
        return out

    def _measured(self, measured: dict) -> dict:
        """I062/340, the item §4.8 marks implementation dependent in its entirety."""
        subs = measured["subfields"]
        out: dict[str, Any] = {"basis": (
            "§5.2.23, 'All measured data related to the last report used to update the track' — "
            "the LAST MEASURED values standing beside the calculated ones, which is settlement 1's "
            "third refusal: a measured Mode 3/A that differs from I062/060, or a measured position "
            "that differs from I062/105, is two statements and stays two statements. §4.8 marks "
            "this whole item implementation dependent, so the STRUCTURE is standardised and the "
            "MEANING is delegated to a per-deployment ICD")}
        if "sid" in subs:
            out["sensor"] = {
                "sac": subs["sid"]["sac"], "sic": subs["sid"]["sic"],
                "external_id": f"{subs['sid']['sac']:02X}{subs['sid']['sic']:02X}",
                "basis": ("the contributing sensor, by SAC/SIC. NOT a SourceId and NOT joined to "
                          "anything: resolving it against a CAT034 station Entity or a CAT048 "
                          "report is cross-payload state"),
            }
        if "pos" in subs:
            out["measured_position"] = {
                "rho_nm": codec.from_raw("rho", subs["pos"]["rho_raw"]),
                "theta_deg": codec.from_raw("theta", subs["pos"]["theta_raw"]),
                "rho_raw": subs["pos"]["rho_raw"], "theta_raw": subs["pos"]["theta_raw"],
                "basis": ("polar co-ordinates from the sensor above, whose own position is NOT in "
                          "the record. No geodesy, and the sensor position is doubly absent — the "
                          "CAT048 settlement 3 refusal with nothing to inject"),
                "which_case_is_unstated": (
                    "the item's NOTE gives three: 'In case of a plot, the measured bias-corrected "
                    "polar co-ordinates; In case of a sensor local track, the measured "
                    "bias-corrected polar co-ordinates of the plot associated to the track; In "
                    "case of a local track without detection, the EXTRAPOLATED bias-corrected "
                    "polar co-ordinates.' One of the three is an extrapolation and the item does "
                    "not say which case it is in — §4.8's implementation dependence in the item's "
                    "own words"),
            }
        if "hei" in subs:
            out["measured_height"] = {
                "feet": codec.from_raw("measured_height", subs["hei"]["height_raw"]),
                "raw": subs["hei"]["height_raw"],
                "basis": ("§5.2.23 Subfield #3, 25 ft two's complement, and its NOTE: 'The "
                          "reference level for this height information is the same as the "
                          "reference level applied by the sensor system providing this "
                          "information' — A DATUM THE RECORD DOES NOT STATE, which is why it never "
                          "reaches Position.alt_m. Edition 1.19's change record says "
                          "'clarification added on structure (Two's Complement)', so an earlier "
                          "edition left even the signedness open"),
            }
        if "mdc" in subs:
            out["measured_mode_c"] = {
                "flight_level": codec.from_raw("measured_mode_c", subs["mdc"]["mode_c_raw"]),
                "raw": subs["mdc"]["mode_c_raw"], "validated": not subs["mdc"]["v"],
                "garbled": bool(subs["mdc"]["g"]),
                "basis": ("carried WITH both flags, and carried even when V says 'Code not "
                          "validated' — dropping an unvalidated code would hide that the sensor "
                          "reported one"),
            }
        if "mda" in subs:
            out["measured_mode_3a"] = {
                "octal": _octal(subs["mda"]["mode_3a"]), "raw": subs["mda"]["mode_3a"],
                "validated": not subs["mda"]["v"], "garbled": bool(subs["mda"]["g"]),
                "smoothed": bool(subs["mda"]["l"]),
                "basis": ("the L bit is a THIRD value's provenance: 'Smoothed MODE 3/A code as "
                          "provided by a sensor local tracker', used per its NOTE 'in case of "
                          "absence of MODE 3/A code information in the plot or in case of "
                          "difference between plot and sensor local track MODE 3/A code "
                          "information' — so a smoothed code is itself the output of a "
                          "disagreement the sensor resolved"),
            }
        if "typ" in subs:
            typ = subs["typ"]
            out["report_type"] = {
                "raw": typ["typ"], "text": MEASURED_TYP_TEXT[typ["typ"]],
                "simulated": bool(typ["sim"]), "field_monitor": bool(typ["rab"]),
                "test": bool(typ["tst"]),
                "basis": ("§5.2.23 Subfield #6. NEITHER SIM NOR TST SETS SourceRef.synthetic — two "
                          "more payload flags describing the report where `synthetic` describes "
                          "the deployment. RAB is 'Report from field monitor (fixed transponder)', "
                          "a calibration transponder rather than an aircraft, and it does not "
                          "change entity_type: the object is still whatever the SDPS is tracking "
                          "and the bit describes the last report's provenance"),
            }
        return out

    # ------------------------------------------------------------------ the other parks

    def _park_flight_plan(self, items: dict, attributes: dict) -> None:
        """I062/390, eighteen subfields, every one a ground system's statement.

        `I062/080`'s `FPC` bit is what says whether any of it is about this target, and it is
        recorded here as well as in `fusion_provenance` because a reader who finds a callsign will
        look for it beside the callsign.
        """
        plan = items.get("I062/390")
        if plan is None:
            return
        subs = plan["subfields"]
        parked: dict[str, Any] = {"basis": (
            "§5.2.25, 'All flight plan related information, provided by ground-based systems'. "
            "Everything here is a ground system's statement about an intention rather than an "
            "observation of the target, and I062/080's FPC bit is what says whether the "
            "correlation happened at all")}
        if "tag" in subs:
            parked["fpps"] = {
                "sac": subs["tag"]["sac"], "sic": subs["tag"]["sic"],
                "basis": ("the flight plan processing system, by SAC/SIC — a THIRD system named in "
                          "one record after I062/010 and I062/340 Subfield #1, and joined to "
                          "nothing"),
            }
        for key, name, label in (("csn", "callsign_raw", "callsign"),
                                 ("tac", "aircraft_type_raw", "aircraft_type"),
                                 ("dep", "departure_raw", "departure_airport"),
                                 ("dst", "destination_raw", "destination_airport"),
                                 ("ast", "aircraft_stand_raw", "aircraft_stand"),
                                 ("std", "sid_raw", "standard_instrument_departure"),
                                 ("sta", "star_raw", "standard_instrument_arrival"),
                                 ("pec", "pre_emergency_raw", "pre_emergency_callsign")):
            if key in subs:
                raw = bytes.fromhex(subs[key][name])
                parked[label] = {"text": _ascii(raw), "trimmed": _ascii(raw).rstrip(),
                                 "octets": subs[key][name]}
        if "callsign" in parked:
            parked["callsign"]["basis"] = (
                "SEVEN ASCII OCTETS, left adjusted and space padded — and I062/380 Subfield #2's "
                "identification is EIGHT SIX-BIT CHARACTERS. Two callsign encodings in one record, "
                "which is one of the reasons neither is promoted to a canonical name; the other is "
                "that the CDM has no canonical name to promote to, which is gap 1. The untrimmed "
                "form is parked as well as the trimmed one, because the padding is what the wire "
                "carried and a callsign that is all spaces is a real thing a flight plan system "
                "sends")
        if "aircraft_type" in parked:
            parked["aircraft_type"]["basis"] = (
                "four ASCII characters, NEVER RESOLVED. The designators are ICAO Document 8643, "
                "which is not in §2.2's reference list at all — and §5.2.25's NOTE 2 cites them to "
                "'[Ref.4]', which is ICAO Annex 14, the aerodrome design annex. "
                "FORMAT_COVERAGE.md ambiguity 6")
        for label in ("departure_airport", "destination_airport"):
            if label in parked:
                parked[label]["basis"] = (
                    "four ASCII characters, never resolved. 'The Airport Names are indicated in "
                    "the ICAO Location Indicators book', which is not in hand")
        if "ifi" in subs:
            parked["ifps_flight_id"] = {
                "typ": subs["ifi"]["typ"], "typ_text": IFPS_TYP_TEXT[subs["ifi"]["typ"]],
                "number": subs["ifi"]["nbr"],
                "basis": ("§5.2.25 Subfield #3, a 27-bit NBR the item describes as 'Number from 0 "
                          "to 99 999 999'. Twenty-seven bits reach 134 217 727, so the stated "
                          "range is narrower than the field in the useful direction"),
            }
        if "fct" in subs:
            fct = subs["fct"]
            parked["flight_category"] = {
                "gat_oat": {"raw": fct["gat_oat"],
                            "text": FLIGHT_CATEGORY_TEXT["gat_oat"][fct["gat_oat"]]},
                "flight_rules": {"raw": fct["fr"], "text": FLIGHT_CATEGORY_TEXT["fr"][fct["fr"]]},
                "rvsm": {"raw": fct["rvsm"], "text": FLIGHT_CATEGORY_TEXT["rvsm"][fct["rvsm"]]},
                "high_priority": bool(fct["hpr"]),
                "basis": ("PARKED, and 'Operational Air Traffic' is NOT read as an affiliation: it "
                          "is a set of flight rules for military and state flights, not an "
                          "allegiance. HPR is a handling priority, not a threat, and it does not "
                          "raise severity"),
            }
        if "wtc" in subs:
            character = chr(subs["wtc"]["wtc"]) if 32 <= subs["wtc"]["wtc"] < 127 else None
            parked["wake_turbulence_category"] = {
                "raw": subs["wtc"]["wtc"], "character": character,
                "text": WTC_TEXT.get(character or ""),
                "basis": ("§5.2.25 Subfield #6, one ASCII character which 'SHOULD be one of the "
                          "following values: L, M, H, J'. 'Should' and not 'shall', and the field "
                          "is a whole octet, so a fifth character is recorded rather than refused"),
            }
        if "rds" in subs:
            parked["runway_designation"] = {
                "nu1": chr(subs["rds"]["nu1"]), "nu2": chr(subs["rds"]["nu2"]),
                "ltr": chr(subs["rds"]["ltr"]),
                "text": "".join(chr(subs["rds"][k]) for k in ("nu1", "nu2", "ltr")),
                "basis": ("three ASCII characters. §5.2.25's NOTE 2 cites 'refer to.[5] Section 5' "
                          "and [5] is EUROCAE ED-102B, the 1090 MHz ADS-B MOPS, which has no "
                          "runway-designation section. Ambiguity 6"),
            }
        if "cfl" in subs:
            parked["cleared_flight_level"] = {
                "flight_level": codec.from_raw("cleared_flight_level",
                                               subs["cfl"]["cleared_flight_level_raw"]),
                "raw": subs["cfl"]["cleared_flight_level_raw"],
                "basis": ("A CLEARANCE IS NOT A MEASUREMENT. It is what the controller told the "
                          "aircraft to do, so it reaches no altitude field. Edition 1.19's change "
                          "record says 'clarification added on range' for exactly this subfield"),
            }
        if "ctl" in subs:
            parked["current_control_position"] = {
                "centre": subs["ctl"]["centre"], "position": subs["ctl"]["position"],
                "basis": ("two 8-bit codes, and the item's NOTE says both 'have to be defined "
                          "between communication partners'. Meaningless without a bilateral "
                          "agreement, so parked as integers and never resolved"),
            }
        if "tod" in subs:
            parked["times_of_departure_arrival"] = {
                "rep": subs["tod"]["rep"],
                "entries": [
                    {"typ": entry["typ"], "typ_text": TOD_TYP_TEXT.get(entry["typ"]),
                     "authored_by": ("the fusion system, from surveillance data"
                                     if entry["typ"] in _PREDICTED_TODS
                                     else "a flight plan system"),
                     "day": entry["day"], "day_text": TOD_DAY_TEXT[entry["day"]],
                     "hours": entry["hor"], "minutes": entry["min"],
                     "seconds": None if entry["avs"] else entry["sec"],
                     "seconds_available": not entry["avs"], "seconds_raw": entry["sec"]}
                    for entry in subs["tod"]["entries"]],
                "basis": (
                    "§5.2.25 Subfield #12, an ORDERED list of typed times. NO ABSOLUTE INSTANT IS "
                    "DERIVED, for three independent reasons: DAY is relative to a date the item "
                    "does not state, AVS can mark the seconds absent, and DAY = 3 is spelled "
                    "'Invalid'. Any one of the three would make an instant an invention"),
                "authorship_note": (
                    "the item's NOTE: 'Estimated times are derived from flight plan systems. "
                    "PREDICTED TIMES ARE DERIVED BY THE FUSION SYSTEM, based on surveillance "
                    "data.' So three of the fourteen TYP values are the tracker's own predictions "
                    "and eleven are the flight plan's, and the TYP is what tells them apart — "
                    "settlement 1's authorship distinction inside one subfield"),
            }
        if "sts" in subs:
            parked["stand_status"] = {
                "occupancy": {"raw": subs["sts"]["emp"],
                              "text": STAND_STATUS_TEXT["emp"][subs["sts"]["emp"]]},
                "availability": {"raw": subs["sts"]["avl"],
                                 "text": STAND_STATUS_TEXT["avl"][subs["sts"]["avl"]]},
                "basis": ("A STAND STATUS IS ABOUT A PIECE OF GROUND, not about the aircraft, and "
                          "it does not become a second Entity: inventing a FACILITY per stand from "
                          "a track message would be creating objects the source did not send"),
            }
        if "pem" in subs:
            pem = subs["pem"]
            parked["pre_emergency_mode_3a"] = {
                "valid": bool(pem["va"]), "raw": pem["mode_3a"],
                "octal": _octal(pem["mode_3a"]) if pem["va"] else None,
                "basis": (
                    "§5.2.25 Subfield #17, 'used only when the aircraft is transmitting an "
                    "emergency Mode 3/A code'. VA = 0 makes the twelve bits MEANINGLESS by the "
                    "item's own NOTE 2, so no code is rendered and the raw bits go to "
                    "unresolved_raw. THE BIT NUMBERING IS AMBIGUITY 8: the prose says 'bits-16/13 "
                    "Spare bits set to 0' and then 'bit-13 (VA) Validity', assigning bit 13 twice "
                    "in four lines. The structure diagram — three zeros then VA — is preferred, "
                    "because it is the only one of the two statements that is internally "
                    "consistent and it agrees with the twelve-bit Mode 3/A field below it"),
            }
            if "pre_emergency_callsign" in parked:
                parked["pre_emergency_callsign"]["basis"] = (
                    "§5.2.25 Subfield #18, 'used only when an emergency Mode 3/A is associated "
                    "with the track'. THE PAIR IS THE ONLY PLACE IN THE CATEGORY THAT SAYS WHAT "
                    "THE TARGET WAS CALLED BEFORE IT STARTED SQUAWKING AN EMERGENCY CODE — exactly "
                    "the value an operator needs, and exactly the value a translator must not "
                    "overwrite the current callsign with")
        attributes["flight_plan"] = parked

    def _park_aircraft_derived(self, items: dict, attributes: dict) -> None:
        """I062/380, twenty-eight subfields, every one the aircraft's own statement."""
        derived = items.get("I062/380")
        if derived is None:
            return
        subs = derived["subfields"]
        parked: dict[str, Any] = {"basis": (
            "§5.2.24, 'Data derived directly by the aircraft'. Everything here is the AIRCRAFT'S "
            "statement rather than the tracker's calculation, so nothing in it becomes a canonical "
            "field except Subfield #1, which is settlement 3's identity basis. Where a subfield "
            "competes with a tracker-calculated value — ground speed against I062/185, track angle "
            "against the derived course, the two vertical rates against I062/220, the geometric "
            "altitude against I062/130, the position against I062/105 — the aircraft's value is "
            "PARKED and the tracker's is used, because choosing between two observers is the "
            "arbitration settlement 1 refuses and there is no basis in the record for making it")}
        if "adr" in subs:
            parked["target_address"] = {"raw": subs["adr"]["address"],
                                        "icao24": f"{subs['adr']['address']:06X}"}
        if "id" in subs:
            text = _characters(subs["id"]["characters_raw"], 8)
            parked["target_identification"] = {
                "text": text, "trimmed": text.rstrip(),
                "raw": subs["id"]["characters_raw"],
                "undefined_codes": text.count(IDENTIFICATION_UNDEFINED),
                "basis": ("eight six-bit characters through the ICAO Annex 10 Vol. IV Table 3-8 "
                          "alphabet, '#' marking a code the alphabet does not define. §5.2.24 "
                          "cites the coding to '[3] Section 3.1.2.9.1.2 and Table 3-9' and "
                          "§5.2.18 cites the same alphabet to 'section 3.1.2.9 of [Ref. 3]' — two "
                          "section numbers for one table, and [Ref. 3] is ICAO Doc 4444, which is "
                          "not where the alphabet lives. Ambiguity 6"),
            }
        for key, field, form, label, unit in (
                ("mhg", "heading_raw", "heading_16", "magnetic_heading", "deg"),
                ("tas", "true_airspeed_raw", "true_airspeed", "true_airspeed", "kt"),
                ("tan", "track_angle_raw", "heading_16", "track_angle", "deg"),
                ("iar", "indicated_airspeed_raw", "indicated_airspeed", "indicated_airspeed",
                 "kt"),
                ("mac", "mach_number_raw", "mach_number", "mach_number", "Mach"),
                ("gal", "geometric_altitude_raw", "geometric_altitude", "geometric_altitude",
                 "ft"),
                ("ran", "roll_angle_raw", "roll_angle", "roll_angle", "deg"),
                ("gsp", "ground_speed_raw", "ground_speed", "ground_speed", "NM/s")):
            if key in subs:
                parked[label] = {"value": codec.from_raw(form, subs[key][field]),
                                 "raw": subs[key][field], "unit": unit,
                                 "lsb": codec.bounds(form)[2]}
        if "magnetic_heading" in parked:
            parked["magnetic_heading"]["basis"] = (
                "A MAGNETIC HEADING, NOT A TRUE ONE, and the CDM has no heading field at all — "
                "FORMAT_COVERAGE.md gap 7, which this row is the fourth source to open against. "
                "The datum is stated here because a bare heading_deg would hold two different "
                "measurements")
        for key, label in (("bvr", "barometric_vertical_rate"), ("gvr", "geometric_vertical_rate")):
            if key in subs:
                parked[label] = {
                    "feet_per_minute": codec.from_raw("vertical_rate",
                                                      subs[key]["vertical_rate_raw"]),
                    "raw": subs[key]["vertical_rate_raw"],
                    "basis": ("the AIRCRAFT'S vertical rate. Neither of the two reaches "
                              "Kinematics.climb_mps: there are two of them and one I062/220, so "
                              "any promotion would arbitrate between three numbers"),
                }
        if "ias" in subs:
            im = subs["ias"]["im"]
            form = "airspeed_mach" if im else "airspeed_nm_s"
            parked["indicated_airspeed_or_mach"] = {
                "im": im, "selects": "Mach" if im else "IAS in NM/s",
                "value": codec.from_raw(form, subs["ias"]["air_speed_raw"]),
                "raw": subs["ias"]["air_speed_raw"], "lsb": codec.bounds(form)[2],
                "basis": ("THE SUPERSEDED Subfield #4: one field holding either an indicated "
                          "airspeed at 2^-14 NM/s or a Mach number at 0.001, selected by the IM "
                          "bit. Subfields #26 and #27 replaced it and this one is 'kept free in "
                          "order to prevent a full incompatibility with previous releases', so a "
                          "record may legally carry all three. Its NOTE names 'bit-37' as its "
                          "presence bit in a four-octet primary numbered 32 to 1 — a bit that does "
                          "not exist; the diagram gives bit-29 and the diagram is preferred. "
                          "Ambiguity 7"),
            }
        for key, label in (("sal", "selected_altitude"), ("fss", "final_state_selected_altitude")):
            if key in subs:
                entry: dict[str, Any] = {
                    "feet": codec.from_raw("selected_altitude", subs[key]["altitude_raw"]),
                    "raw": subs[key]["altitude_raw"],
                }
                if key == "sal":
                    entry["source_stated"] = bool(subs[key]["sas"])
                    entry["source"] = subs[key]["source"]
                    entry["source_text"] = SELECTED_ALTITUDE_SOURCE_TEXT[subs[key]["source"]]
                    entry["basis"] = (
                        "SAS = 0 means 'No source information provided', so the Source field is "
                        "then NOT A STATEMENT — which is a different fact from Source = 0 "
                        "'Unknown', and the item distinguishes them. Both are carried")
                else:
                    entry["managed_vertical_mode"] = bool(subs[key]["mv"])
                    entry["altitude_hold"] = bool(subs[key]["ah"])
                    entry["approach_mode"] = bool(subs[key]["am"])
                    entry["lateral_navigation_mode"] = (
                        "in I062/REF/STS/LNAV, per §5.2.24's NOTE — and it is THE ONE relocation "
                        "the core specification names that Appendix A Edition 1.3 actually defines")
                parked[label] = entry
        if "tis" in subs:
            parked["trajectory_intent_status"] = {
                "available": not subs["tis"]["nav"], "valid": not subs["tis"]["nvb"],
                "basis": ("§5.2.24 Subfield #8, and both bits are stated INVERTED — NAV = 1 is "
                          "'Trajectory Intent Data is NOT available' and NVB = 1 is 'not valid'. "
                          "Carried as the positive sense with the inversion named, because the "
                          "wording is what a reader will check against"),
            }
        if "tid" in subs:
            parked["trajectory_intent"] = {
                "rep": subs["tid"]["rep"],
                "points": [self._intent_point(point) for point in subs["tid"]["points"]],
                "basis": (
                    "§5.2.24 Subfield #9, an ORDERED list of fifteen-octet Trajectory Change "
                    "Points with duplicates preserved. THE ONE REPETITIVE STRUCTURE IN THE "
                    "CATEGORY WHOSE ELEMENT IS A POSITION, and no Track and no Event.geometry is "
                    "produced from it: a trajectory intent is a PREDICTION, Track.samples are "
                    "observations, and a LineString through predicted waypoints would render as a "
                    "flown path"),
            }
        if "com" in subs:
            com = subs["com"]
            parked["communications_capability"] = {
                "com": {"raw": com["com"], "text": COM_CAPABILITY_TEXT[com["com"]]},
                "flight_status": {"raw": com["stat"], "text": FLIGHT_STATUS_TEXT[com["stat"]]},
                "specific_service_capability": bool(com["ssc"]),
                "altitude_reporting": "25 ft resolution" if com["arc"] else "100 ft resolution",
                "aircraft_identification_capability": bool(com["aic"]),
                "bds_1_0_bit_16": com["b1a"], "bds_1_0_bits_37_40": com["b1b"],
                "basis": ("§5.2.24 Subfield #10. THE FLIGHT STATUS'S ALERT VALUES DO NOT RAISE "
                          "SEVERITY: this is the transponder's own status, its values 4 and 5 "
                          "conflate airborne and on-ground, and the emergency vocabularies in "
                          "this category are EMS, Subfield #11's STAT and I062/REF/PS3"),
            }
        if "sab" in subs:
            sab = subs["sab"]
            parked["status_reported_by_adsb"] = {
                "acas": {"raw": sab["ac"], "text": ADSB_OPERATIONAL_TEXT["ac"][sab["ac"]]},
                "navigational_aids": {"raw": sab["mn"],
                                      "text": ADSB_OPERATIONAL_TEXT["mn"][sab["mn"]]},
                "differential_correction": {"raw": sab["dc"],
                                            "text": ADSB_OPERATIONAL_TEXT["dc"][sab["dc"]]},
                "ground_bit_set": bool(sab["gbs"]),
                "priority_status": {"raw": sab["stat"], "text": EMS_TEXT.get(sab["stat"]),
                                    "back_mapped_from_version_3": PS3_BACK_MAPPING},
                "basis": ("§5.2.24 Subfield #11. Its STAT is one of the three emergency "
                          "statements — see payload.emergency_basis — and on ADS-B Version 3 "
                          "equipment it is LOSSY BY CONSTRUCTION: the item's own note prints the "
                          "back-mapping table, in which 2 becomes 4 and both distress values "
                          "become 1. There is no VN field in this subfield despite two notes "
                          "citing 'I062/380/SF#11/VN' — ambiguity 13"),
            }
        if "acs" in subs:
            parked["acas_resolution_advisory"] = {
                "octets": subs["acs"]["acas_ra"],
                "basis": ("§5.2.24 Subfield #12, seven octets, '56-bit message conveying Mode S "
                          "Comm B message data of BDS Register 3,0 and ADS-B'. PARKED WHOLE AS "
                          "HEX AND NEVER DECODED: the only decode authority the item cites is "
                          "'Refer to ICAO Draft SARPs for ACAS for detailed explanations' — a "
                          "DRAFT, unnamed by edition, absent from §2.2's reference list, and there "
                          "is no field breakdown of the 56 bits anywhere in this document. The "
                          "asterix_cat048.py I048/260 disposition"),
            }
        if "tar" in subs:
            tar = subs["tar"]
            rate = codec.from_raw("rate_of_turn", tar["rate_of_turn_raw"])
            entry = {
                "turn_indicator": {"raw": tar["ti"], "text": TURN_INDICATOR_TEXT[tar["ti"]]},
                "rate_of_turn_deg_s": rate, "raw": tar["rate_of_turn_raw"],
                "basis": ("§5.2.24 Subfield #16. A SEVEN-BIT two's-complement rate in bits 8/2 "
                          "with a spare bit 1, so the field reaches ±16 and the stated range is "
                          "±15. NO turn_rate_dpm exists on Kinematics — gap 7's second half"),
            }
            if abs(rate) >= codec.bounds("rate_of_turn")[1]:
                entry["at_or_above_maximum"] = "Value 15 means 15°/s or above"
            parked["track_angle_rate"] = entry
        if "vun" in subs:
            parked["velocity_uncertainty"] = {
                "raw": subs["vun"]["velocity_uncertainty"],
                "basis": ("§5.2.24 Subfield #19, 'Velocity uncertainty category of the least "
                          "accurate velocity component'. A CATEGORY and not a metric value, and "
                          "the document defines no scale for it anywhere — so it is parked as the "
                          "integer and nothing is derived from it"),
            }
        if "met" in subs:
            met = subs["met"]
            parked["meteorological_data"] = {
                "wind_speed": {"valid": bool(met["ws"]),
                               "knots": codec.from_raw("wind_speed", met["wind_speed_raw"]),
                               "raw": met["wind_speed_raw"]},
                "wind_direction": {"valid": bool(met["wd"]),
                                   "degrees": codec.from_raw("wind_direction",
                                                             met["wind_direction_raw"]),
                                   "raw": met["wind_direction_raw"]},
                "temperature": {"valid": bool(met["tmp"]),
                                "celsius": codec.from_raw("temperature", met["temperature_raw"]),
                                "raw": met["temperature_raw"]},
                "turbulence": {"valid": bool(met["trb"]), "value": met["turbulence_raw"]},
                "basis": ("§5.2.24 Subfield #20. EACH OF THE FOUR MEASUREMENTS HAS ITS OWN "
                          "VALIDITY BIT, so an invalid measurement is PRESENT AND MARKED rather "
                          "than absent — carried as the value plus the flag, because a consumer "
                          "ignoring the flag would read a placeholder as a measurement. Wind "
                          "direction's stated low bound is 1, not 0, so a zero is outside the "
                          "item's own range and is refused rather than read as north — the one "
                          "place in this category where zero is excluded from an angle"),
            }
        if "emc" in subs:
            parked["emitter_category"] = {"raw": subs["emc"]["ecat"],
                                          "text": ECAT_TEXT.get(subs["emc"]["ecat"])}
        if "pos" in subs:
            parked["position"] = {
                "latitude": codec.from_raw("latitude_23", subs["pos"]["latitude_raw"]),
                "longitude": codec.from_raw("longitude_23", subs["pos"]["longitude_raw"]),
                "latitude_raw": subs["pos"]["latitude_raw"],
                "longitude_raw": subs["pos"]["longitude_raw"],
                "quantisation": codec.WGS84_23_QUANTISATION_NOTE,
                "basis": ("§5.2.24 Subfield #22, the AIRCRAFT'S OWN fix via ADS-B at 180/2^23 "
                          "degrees. Never Entity.position: choosing between the aircraft's fix and "
                          "the tracker's is arbitration, and note that the tracker's is four times "
                          "finer at 180/2^25"),
            }
        if "pun" in subs:
            parked["position_uncertainty"] = {
                "raw": subs["pun"]["pun"],
                "basis": ("§5.2.24 Subfield #24, a four-bit PUN. The document defines NO SCALE for "
                          "it, so nothing is derived and it never reaches Position.accuracy_m"),
            }
        if "mb" in subs:
            parked["bds_registers"] = {
                "rep": subs["mb"]["rep"],
                "registers": [dict(register) for register in subs["mb"]["registers"]],
                "basis": ("§5.2.24 Subfield #25, an ordered list of 56-bit registers with their "
                          "two four-bit addresses. PARKED WHOLE AS HEX PER REGISTER, NEVER "
                          "DECODED: the register semantics are in ICAO Annex 10, and the item's "
                          "own NOTE says the subfield is for DAPs 'that cannot be encoded into "
                          "other subfields of this item' — so what is in it is by definition not "
                          "what the item's other subfields cover. The I048/250 disposition"),
            }
        if "bps" in subs:
            parked["barometric_pressure_setting"] = {
                "millibars_above_800": codec.from_raw("barometric_pressure", subs["bps"]["bps_raw"]),
                "raw": subs["bps"]["bps_raw"],
                "basis": ("§5.2.24 Subfield #28, and its NOTE is why the key is named as it is: "
                          "'BPS is the barometric pressure setting of the aircraft MINUS 800 mb'. "
                          "So the number is an offset and not a pressure, and Edition 1.19 removed "
                          "the note '(derived from Mode S BDS 4,0)' to allow it via ADS-B"),
            }
        attributes["aircraft_derived_data"] = parked

    def _intent_point(self, point: dict) -> dict:
        entry: dict[str, Any] = {
            "tcp_number": point["tcp_number"],
            "tcp_number_available": not point["tca"],
            "compliance": "TCP non-compliance" if point["nc"] else "TCP compliance",
            "altitude_ft": codec.from_raw("tid_altitude", point["altitude_raw"]),
            "latitude": codec.from_raw("latitude_23", point["latitude_raw"]),
            "longitude": codec.from_raw("longitude_23", point["longitude_raw"]),
            "point_type": {"raw": point["point_type"],
                           "text": POINT_TYPE_TEXT.get(point["point_type"])},
            "turn_direction": point["td"],
            "turn_radius_available": bool(point["tra"]),
            "turn_radius_nm": codec.from_raw("turn_radius", point["ttr_raw"]),
            "time_over_point_available": not point["toa"],
            "time_over_point_raw": point["tov_raw"],
        }
        if point["toa"]:
            entry["time_over_point_note"] = (
                "TOA = 1, and NOTE 6 says 'TOV is meaningful only if TOA is set to 0'. So the "
                "24-bit field is parked raw and no instant is resolved from it")
        else:
            entry["time_over_point_seconds"] = codec.from_raw("tov", point["tov_raw"])
            entry["time_over_point_note"] = (
                "TOA = 0, so NOTE 5 applies: TOV 'is defined as the absolute time from midnight' "
                "at an LSB of 1 s — a SECOND time-of-day-shaped field in the category, at a "
                "different resolution from I062/070's 1/128 s")
        return entry

    def _park_expansion(self, items: dict, attributes: dict) -> None:
        """The Reserved Expansion Field, decoded, and the Special Purpose Field, not."""
        ref = items.get("RE")
        if ref is not None:
            parked: dict[str, Any] = {
                "length": ref["length"],
                "items_indicator": ref["items_indicator"],
                "spare_bits_3_1": ref["spare_bits_3_1"],
                "basis": (
                    "IN SCOPE AND DECODED IN FULL, which is the CAT021 disposition and not the "
                    "CAT034 one, because the core specification RELOCATES load-bearing content "
                    "here and says so in its own abstract: 'Most modifications for the "
                    "implementation of ADS-B Version 3 have been performed in the Reserved "
                    "Expansion Field (I062/REF). To make use of these modifications it is "
                    "recommended also to implement the I062/REF (Edition 1.3 or later).' "
                    "Appendix A Edition 1.3 defines five items and this adapter reads all five"),
                "no_fx_finding": (
                    "Appendix A §2.2's bit 1 is a SPARE and not a Field Extension Indicator — the "
                    "only presence map in either document that cannot extend — so a set bit 1 here "
                    "is a spare bit parked as sent and NOT a refusal. That is the opposite "
                    "treatment from every compound item in the core specification, and getting it "
                    "backwards would refuse a legal REF. Its NOTE says why: 'The allocation of "
                    "additional items is the responsibility of the AMG and shall be coordinated in "
                    "advance!'"),
                "eight_containers_the_core_text_names_and_this_edition_does_not_define": [
                    "I062/REF/STS/CSX (extended coasting, §5.2.6 NOTE 4)",
                    "I062/REF/MOI/SCT (special-used-code text, §5.2.6 NOTES 5 and 6)",
                    "I062/REF/MOI/AM5I (Mode 5 interrogation age, §5.2.6 sixth extent and §5.2.20 NOTE 1)",
                    "I062/REF/MOI/AM5L2S (Mode 5 Level 2 Squitter age, §5.2.20 NOTE 2)",
                    "I062/REF/MOI/CTBA (the other QNH variant, §5.2.12 NOTE)",
                    "I062/REF/MOI/ALTQCMFL (QNH-corrected measured flight level, §5.2.13 NOTE 5)",
                    "I062/REF/MOI/FPVHR (high-resolution velocity, §5.2.14 NOTE)",
                    "I062/REF/MOI/SI#10 (per-register BDS ages, §5.2.21 SF#28 NOTE)",
                    "I062/REF/MTI/EXM3A (extended Mode 3/A, §5.2.21 SF#4)",
                ],
                "items": {},
            }
            for name, sub in ref["items"].items():
                parked["items"][name] = self._ref_item(name, sub)
            attributes["reserved_expansion_field"] = parked
        special = items.get("SP")
        if special is not None:
            attributes["special_purpose_field"] = {
                **special,
                "basis": (
                    "opaque by construction. Parked verbatim as hex and NEVER WRITTEN TO on "
                    "egress — a Special Purpose Field's contents are settled by bilateral "
                    "agreement between one sender and one receiver, so a byte invented here is a "
                    "byte some deployment already means something by. No §5.2 description exists "
                    "for it, and the one-octet-length-counting-itself convention is inherited from "
                    "the shipped ASTERIX siblings: ASTERIX Part 1 defines it, this document cites "
                    "Part 1 as SPEC-0149 edition 3.1 without reproducing it, and Part 1 is not "
                    "pinned in this repository"),
            }

    def _ref_item(self, name: str, sub: dict) -> dict:
        if name in ("cst", "csn"):
            return {
                "rep": sub["rep"],
                "sensors": [
                    {**{k: v for k, v in sensor.items() if k != "typ"},
                     "typ": sensor["typ"], "typ_text": REF_SENSOR_TYP_TEXT.get(sensor["typ"])}
                    for sensor in sub["sensors"]],
                "basis": (
                    "Appendix A §2.3 and §2.4 — the contributing sensors, with SAC/SIC, a "
                    "detection TYP, and (in CST) the sensor's own LOCAL TRACK NUMBER. SETTLEMENT "
                    "1'S MOST DIRECT FUSION PROVENANCE: the SDPS naming which systems updated this "
                    "track in this cycle. Parked as an ORDERED list; no local track number is "
                    "joined to anything, and no Entity is created per sensor. The two lists mean "
                    "one thing and differ only in whether the sensor supplied a local track "
                    "number, so a sensor's presence in one and absence from the other is "
                    "information. TYP values 1010-1111 are 'Reserved for future use'"),
            }
        if name == "tvs":
            return {
                "vx_mps": codec.from_raw("ref_velocity_mps", sub["vx_raw"]),
                "vy_mps": codec.from_raw("ref_velocity_mps", sub["vy_raw"]),
                "vx_raw": sub["vx_raw"], "vy_raw": sub["vy_raw"],
                "basis": (
                    "Appendix A §2.5, the same shape as I062/185 and A DIFFERENT FRAME: its NOTE "
                    "says 'The y-axis points to the Geographical North at the SYSTEM REFERENCE "
                    "POINT as available in the Reserved Expansion Field of category 065.' So the "
                    "two vectors have different axes and only I062/185's are stated at the target "
                    "— which is why this one is never converted to speed and course"),
            }
        if name == "sts":
            return {
                "flight_data_retained": bool(sub["fdr"]),
                "lnav_populated": bool(sub["lnav_ep"]),
                "lnav_engaged": (None if not sub["lnav_ep"] else not sub["lnav_val"]),
                "lnav_val_raw": sub["lnav_val"],
                "spare_bits_5_2": sub["spare_bits_5_2"],
                "basis": (
                    "Appendix A §2.6. FDR distinguishes flight plan data from an active FDPS from "
                    "data 'retained from no longer active FDPS'. LNAV arrives with the "
                    "Element-Populated convention and ITS SENSE IS INVERTED relative to every "
                    "other flag in either document — 'LNAV#VAL = 0 LNAV Mode Engaged' — so the "
                    "wording is carried verbatim rather than paraphrased, and lnav_engaged is None "
                    "when the element is not populated. This is the ONE relocation the core "
                    "specification names that Appendix A Edition 1.3 actually defines"),
            }
        if name == "v3":
            out: dict[str, Any] = {"primary": sub["primary"],
                                   "spare_bits_4_2": sub["spare_bits_4_2"], "subfields": {}}
            subs = sub["subfields"]
            if "ps3" in subs:
                out["subfields"]["ps3"] = {
                    "populated": bool(subs["ps3"]["ps3_ep"]), "raw": subs["ps3"]["ps3_val"],
                    "text": PS3_TEXT[subs["ps3"]["ps3_val"]],
                    "back_maps_to": PS3_BACK_MAPPING[subs["ps3"]["ps3_val"]],
                    "basis": ("Appendix A §2.7 Subfield #1 — THE VALUE SETTLEMENT 2 EXISTS FOR. "
                              "Three of its eight values have no representation in I062/080's EMS "
                              "or I062/380 Subfield #11's STAT at all: 'UAS/RPAS - Lost Link', "
                              "and both aircraft-in-distress values"),
                }
            if "as" in subs:
                a = subs["as"]
                out["subfields"]["aircraft_status"] = {
                    "reduced_capability": self._element(a, "rce", V3_AIRCRAFT_STATUS_TEXT["rce"]),
                    "reply_rate_limiting": self._element(a, "rrl",
                                                         V3_AIRCRAFT_STATUS_TEXT["rrl"]),
                    "transmit_power": self._element(a, "tpw", V3_AIRCRAFT_STATUS_TEXT["tpw"]),
                    "transponder_side": self._element(a, "tsi", V3_AIRCRAFT_STATUS_TEXT["tsi"]),
                    "transponder_antenna_offset": {
                        "populated": bool(a["tao_ep"]), "raw": a["tao_val"],
                        "range_exceeded": bool(a["re"]),
                        "basis": ("NOTE 3 makes the RE bit a STATED SATURATION FLAG: 'Bit-12 shall "
                                  "be set to 1 when the aircraft transmits the maximum encodable "
                                  "value (i.e. 31 representing a TAO greater than 58m). In this "
                                  "case TAO#VAL shall be set to the maximum encodable TAO (i.e. "
                                  "58m).' The at-or-above-maximum discipline made explicit in the "
                                  "wire format rather than in a note about a maximum. NOTE 4: 'The "
                                  "TAO is measured along the longitudinal axis of the aircraft "
                                  "from the forward end'"),
                    },
                    "spare_bits_5_1": a["spare_bits_5_1"],
                }
            if "uas" in subs:
                u = subs["uas"]
                out["subfields"]["uas_status"] = {
                    "manned_unmanned": self._element(u, "muo", V3_UAS_TEXT["muo"]),
                    "detect_and_avoid": self._element(u, "daa", V3_UAS_TEXT["daa"]),
                    "remain_well_clear": self._element(u, "rwc", V3_UAS_TEXT["rwc"]),
                    "basis": ("Appendix A §2.7 Subfield #3. MUO DOES NOT CHANGE entity_type: an "
                              "unmanned aircraft is still a PLATFORM and the CDM has no "
                              "crewed/uncrewed distinction, which is recorded as a gap-shaped "
                              "absence rather than forced. DAA's value 3 is spelled 'Invalid "
                              "ASTERIX Value' by the document itself"),
                }
            if "cass" in subs:
                c = subs["cass"]
                out["subfields"]["collision_avoidance_status"] = {
                    "sense": self._element(c, "svh", V3_CASS_TEXT["svh"]),
                    "type_and_capability": self._element(c, "catc", V3_CASS_TEXT["catc"]),
                }
            return out
        return dict(sub)

    def _element(self, subfield: dict, name: str, vocabulary: dict[int, str]) -> dict:
        """One Element-Populated pair: the flag, the raw value, and the wording where it applies.

        The Element-Populated convention is Appendix A's and it is honoured rather than flattened:
        a value under a clear EP bit is NOT A STATEMENT, so `text` is None there. Flattening it
        would turn every unpopulated element into whatever its zero happens to mean.
        """
        populated = bool(subfield[f"{name}_ep"])
        raw = subfield[f"{name}_val"]
        return {"populated": populated, "raw": raw,
                "text": vocabulary.get(raw) if populated else None}

    def _encoder_conformance(self, items: dict) -> dict:
        """Non-conformances read and carried rather than refused. Settlement 9's collection point."""
        out: dict[str, Any] = {}
        target_id = items.get("I062/245")
        if target_id is not None:
            text = _characters(target_id["characters_raw"], 8)
            out["I062/245_present"] = {
                "sti": target_id["sti"], "sti_text": STI_TEXT[target_id["sti"]],
                "text": text, "trimmed": text.rstrip(),
                "basis": (
                    "§5.2.18's NOTE 2 says of this item: 'As the Callsign of the target can "
                    "already be transmitted (in I062/380 Subfield #2 if downlinked from the "
                    "aircraft or in I062/390 Subfield #2 if the target is correlated to a flight "
                    "plan), and in order to avoid confusion at end user's side, this item SHALL "
                    "not be used.' So a record carrying it is NON-CONFORMANT — and it is DECODED "
                    "AND PARKED, never refused, for three reasons in order of weight. 'SHALL not "
                    "be used' binds an ENCODER and this is a decoder, so refusing would discard "
                    "data the FSPEC correctly announced. The item is fully specified, so there is "
                    "no ambiguity about what its octets mean. And the prohibition is itself worth "
                    "carrying: a record that uses I062/245 tells a consumer something about the "
                    "system that emitted it, and that can only be carried if the item is read. "
                    "The two items it defers to are NOT merged with it — all three park "
                    "separately, because choosing one as 'the' callsign is arbitration and doing "
                    "it on the authority of a note that forbids one of the three would be worse"),
            }
            if STI_TEXT[target_id["sti"]] == "Invalid":
                out["I062/245_sti_invalid"] = (
                    "the STI is 11, which §5.2.18's own table spells 'Invalid'. The eight "
                    "characters are still parked; what is invalid is the claim about what kind of "
                    "identification they are")
        return out

    # ------------------------------------------------------------------ the payload

    def _payload(self, record: dict, block: dict, items: dict, time_basis: dict,
                 kinematics_basis: dict | None, emergency_basis: dict,
                 unresolved: dict[str, Any]) -> dict:
        payload: dict[str, Any] = {
            "observed_at_basis": time_basis,
            "emergency_basis": emergency_basis,
            "record_index": record["index"],
            "record_count": record.get("record_count", block.get("record_count")),
            "track_number": items["I062/040"]["track_number"],
        }
        if kinematics_basis:
            payload["kinematics_basis"] = kinematics_basis
        service = items.get("I062/015")
        if service is not None:
            payload["service_identification"] = {
                "raw": service["service_identification"],
                "basis": ("§5.2.2, one octet, 'Identification of the service provided to one or "
                          "more users', and its NOTE says 'the service identification is allocated "
                          "by the system'. Its Encoding Rule is 'This Item is optional' — which a "
                          "reader expecting CAT023's arrangement would not guess, since CAT023 "
                          "makes its equivalent mandatory for two of three report types. CAT023's "
                          "I023/015 NOTE 2 names the join to I021/015; a consumer may perform it "
                          "and this adapter may not"),
            }
        cartesian = items.get("I062/100")
        if cartesian is not None:
            payload["cartesian_position"] = {
                "x_metres": codec.from_raw("cartesian_m", cartesian["x_raw"]),
                "y_metres": codec.from_raw("cartesian_m", cartesian["y_raw"]),
                "x_raw": cartesian["x_raw"], "y_raw": cartesian["y_raw"],
                "lsb_metres": codec.bounds("cartesian_m")[2],
                "basis": (
                    "§5.2.7, parked as metres and NEVER CONVERTED TO A COORDINATE. §4.3.2 states "
                    "the projection: 'a projection is performed on a plane tangential to the "
                    "WGS-84 Ellipsoid at the location of the reference point. The Y-axis points to "
                    "the geographical north at that position. The X-axis is perpendicular to the "
                    "Y-axis and points to the east. The X, Y co-ordinates are calculated using a "
                    "suitable projection technique for the final 3D to 2D conversion (e.g. a "
                    "stereographical projection). It is slant range corrected, the source of "
                    "altitude being indicated in I062/080 Track Status, Octet 1, bit 6 (MRH).' "
                    "TWO INDEPENDENT UNKNOWNS, either of them fatal: the reference point is not in "
                    "any CAT062 item — Appendix A §2.5's NOTE says it is 'available in the "
                    "Reserved Expansion Field of CATEGORY 065' — and the projection is named only "
                    "by example, so two conforming SDPSs can emit different X for one aircraft and "
                    "nothing in the record distinguishes them. This is a STRONGER decline than "
                    "CAT048 settlement 3's, where the geodesy was absent from the document but the "
                    "inputs were on the wire and a caller could inject the missing one. A consumer "
                    "holding a CAT065 reference point may invert it visibly"),
            }
        acceleration = items.get("I062/210")
        if acceleration is not None:
            ax = codec.from_raw("acceleration_mps2", acceleration["ax_raw"])
            ay = codec.from_raw("acceleration_mps2", acceleration["ay_raw"])
            entry: dict[str, Any] = {
                "ax_mps2": ax, "ay_mps2": ay,
                "ax_raw": acceleration["ax_raw"], "ay_raw": acceleration["ay_raw"],
                "lsb": codec.bounds("acceleration_mps2")[2],
                "basis": ("§5.2.16, the same north-oriented frame as I062/185's. PARKED — THE CDM "
                          "HAS NO ACCELERATION FIELD, and adding one in passing would be widening "
                          "the model for one source"),
            }
            low, high = codec.bounds("acceleration_mps2")[0], codec.bounds("acceleration_mps2")[1]
            if ax in (low, high) or ay in (low, high):
                entry["at_or_above_maximum"] = AT_OR_ABOVE_MAXIMUM_NOTE
            payload["calculated_acceleration"] = entry
        mode3a = items.get("I062/060")
        if mode3a is not None:
            payload["track_mode_3a"] = {
                "octal": _octal(mode3a["mode_3a"]), "raw": mode3a["mode_3a"],
                "validated": not mode3a["v"], "garbled": bool(mode3a["g"]),
                "changed": bool(mode3a["ch"]),
                "basis": ("§5.2.4, twelve bits of octal Mode 3/A with V, G and CH. CH is the "
                          "tracker saying the code changed, which is a statement about a PREVIOUS "
                          "RECORD this adapter has not seen — carried, not acted on"),
            }
        mode2 = items.get("I062/120")
        if mode2 is not None:
            payload["track_mode_2"] = {
                "octal": _octal(mode2["mode_2"]), "raw": mode2["mode_2"],
                "basis": ("§5.2.10, twelve bits of octal Mode 2. NO VALIDITY OR GARBLE BITS AT "
                          "ALL, unlike I062/060 and unlike I062/340 Subfield #5 — so a Mode 2 code "
                          "in this category carries no quality statement, and the absence is "
                          "recorded rather than filled in"),
            }
        for key, item_name, form, unit, note in (
                ("calculated_geometric_altitude", "I062/130", "geometric_altitude", "ft", None),
                ("measured_flight_level", "I062/136", "measured_flight_level", "FL", None)):
            item = items.get(item_name)
            if item is None:
                continue
            field = "altitude_raw" if item_name == "I062/130" else "flight_level_raw"
            payload[key] = {"value": codec.from_raw(form, item[field]), "unit": unit,
                            "raw": item[field], "lsb": codec.bounds(form)[2]}
        if "calculated_geometric_altitude" in payload:
            payload["calculated_geometric_altitude"]["basis"] = (
                "§5.2.11, 'Vertical distance between the target and the projection of its position "
                "on the earth's ellipsoid, as defined by WGS84'. THE ONE ALTITUDE THAT REACHES "
                "Position.alt_m, because it is the only one of six defined as a height above the "
                "ellipsoid, which is what alt_m documents itself as. NOTE 1's 'LSB is required to "
                "be less than 10 ft by ICAO' is a constraint on the encoding, not an accuracy")
        if "measured_flight_level" in payload:
            payload["measured_flight_level"]["basis"] = (
                "§5.2.13, 'Last valid and credible flight level used to update the track'. Its "
                "NOTES are the point: 'The criteria to determine the credibility of the flight "
                "level are TRACKER DEPENDENT' and 'Credible means: within reasonable range of "
                "change with respect to the previous detection' — so the item's own filter is "
                "unspecified. And NOTE 4: 'This item includes the barometric altitude received "
                "from ADS-B', so a MEASURED flight level here may not have come from a Mode C "
                "reply at all and nothing in the item says which it was. Its NOTE 5 points at "
                "I062/REF/MOI/ALTQCMFL for the QNH-corrected variant, undefined in Appendix A "
                "Edition 1.3")
        baro = items.get("I062/135")
        if baro is not None:
            payload["calculated_barometric_altitude"] = {
                "flight_level": codec.from_raw("barometric_altitude", baro["ctba_raw"]),
                "raw": baro["ctba_raw"],
                "qnh_correction_applied": bool(baro["qnh"]),
                "basis": ("§5.2.12. PARKED, never Position.alt_m — a pressure altitude is not a "
                          "height above anything. Its NOTE is load-bearing: 'This item enables the "
                          "provision of either QNH or non-QNH corrected Calculated Track "
                          "Barometric Altitude, BUT NOT BOTH. If needed, the other variant can be "
                          "provided in I062/REF/MOI/CTBA' — a container Appendix A Edition 1.3 "
                          "does not define, so the other variant is unreachable here"),
            }
        climb = items.get("I062/220")
        if climb is not None:
            payload["calculated_rate_of_climb"] = {
                "feet_per_minute": codec.from_raw("rate_of_climb", climb["rate_raw"]),
                "raw": climb["rate_raw"], "lsb": codec.bounds("rate_of_climb")[2],
            }
        movement = items.get("I062/200")
        if movement is not None:
            payload["mode_of_movement"] = {
                "transversal": {"raw": movement["trans"],
                                "text": MODE_OF_MOVEMENT_TEXT["trans"][movement["trans"]]},
                "longitudinal": {"raw": movement["long"],
                                 "text": MODE_OF_MOVEMENT_TEXT["long"][movement["long"]]},
                "vertical": {"raw": movement["vert"],
                             "text": MODE_OF_MOVEMENT_TEXT["vert"][movement["vert"]]},
                "altitude_discrepancy": bool(movement["adf"]),
                "basis": ("§5.2.15, 'Calculated Mode of Movement of a target' — THE TRACKER'S OWN "
                          "CLASSIFICATION of the motion, parked as four fields and never used to "
                          "sign or modify climb_mps or course_deg, which are numbers the same "
                          "record states"),
                "adf_basis": ("the ADF NOTE: 'The ADF, if set, indicates that a difference has "
                              "been detected in the altitude information derived from radar as "
                              "compared to other technologies (such as ADS-B).' So it is the "
                              "tracker telling you two of the altitude items disagree — "
                              "settlement 1's fused-content statement in one bit"),
            }
        size = items.get("I062/270")
        if size is not None:
            payload["target_size_and_orientation"] = self._target_size(size)
        mode5 = items.get("I062/110")
        if mode5 is not None:
            payload["mode_5"] = self._mode_5(mode5, time_basis, unresolved)
        return payload

    def _target_size(self, size: dict) -> dict:
        """I062/270, and ambiguity 10 is what makes the first field's meaning conditional."""
        fields = {octet["field"]: octet["value_raw"] for octet in size["octets"]}
        has_width = "width" in fields
        out: dict[str, Any] = {
            "length_metres": codec.from_raw("target_length_m", fields["length"]),
            "length_raw": fields["length"],
            "width_present": has_width,
            "length_means": (
                "the target's LENGTH, because a WIDTH extent follows" if has_width else
                "the target's LARGEST DIMENSION, because no WIDTH extent follows"),
            "basis": (
                "§5.2.19. NOTE 2 MAKES THE FIRST FIELD'S MEANING DEPEND ON WHETHER A LATER FIELD "
                "IS PRESENT: 'When the length only is sent, the largest dimension is provided.' So "
                "a length-only record states a largest dimension and a length-and-width record "
                "states a length — two different measurements in one field, selected by an FX bit "
                "two octets later. The raw field is parked with this flag so both readings "
                "survive; calling it a length unconditionally would be wrong for every length-only "
                "record. FORMAT_COVERAGE.md ambiguity 10"),
        }
        if "orientation" in fields:
            out["orientation_degrees"] = codec.from_raw("target_orientation",
                                                        fields["orientation"])
            out["orientation_raw"] = fields["orientation"]
            out["orientation_basis"] = (
                "§5.2.19 NOTE 1: 'The orientation gives the direction which the target nose is "
                "pointing to, relative to the Geographical North.' Seven bits at 360/2^7 ≈ 2.81°, "
                "so the printed LSB and the field's width agree — 128 is 2^7 and bit 1 is the FX. "
                "PARKED and never Kinematics.course_deg: a nose bearing is not a course, and the "
                "course comes from I062/185's velocity vector")
        if has_width:
            out["width_metres"] = codec.from_raw("target_length_m", fields["width"])
            out["width_raw"] = fields["width"]
        return out

    def _mode_5(self, mode5: dict, time_basis: dict, unresolved: dict[str, Any]) -> dict:
        """I062/110, and settlement 4's substitution is stated in the object here."""
        subs = mode5["subfields"]
        out: dict[str, Any] = {"presence": mode5["presence"]}
        offset_seconds = 0.0
        if "tos" in subs:
            offset_seconds = codec.from_raw("time_offset", subs["tos"]["tos_raw"])
        out["time_basis"] = {
            "offset_seconds": offset_seconds,
            "offset_raw": subs.get("tos", {}).get("tos_raw"),
            "offset_present": "tos" in subs,
            "base_instant_from": "I062/070",
            "substitution": (
                "THE SPECIFICATION NAMES AN ITEM OF A DIFFERENT CATEGORY AND I062/070 IS "
                "SUBSTITUTED. §5.2.9 Subfield #6 reads: 'The time at which the Mode 5 Reported "
                "Position (Subfield #3) and Mode 5 GNSS-derived Altitude (Subfield #4) are valid "
                "is given by Time of Day (I048/140) plus Time Offset.' I048/140 is PART 4's item — "
                "Category 048 — and Category 062 has no I048/140 and no item numbered 140 at all. "
                "Its own time of day is I062/070, at the same LSB of 1/128 s, and the sentence has "
                "been carried over from the CAT048 specification without renumbering. Following it "
                "literally is impossible; the only reading that produces a value substitutes "
                "I062/070. That is a RULING and not a transcription, so it is stated here beside "
                "the value rather than applied quietly. FORMAT_COVERAGE.md ambiguity 9"),
            "applies_to": ("Subfields #3 and #4 ONLY — the Mode 5 reported position and the Mode 5 "
                           "GNSS-derived altitude. Never the track's own time, which is "
                           "I062/070 unmodified"),
            "absent_is_a_stated_zero": (
                "§5.2.9's NOTE: 'TOS shall be assumed to be zero if Subfield #6 is not present.' "
                "So an absent Subfield #6 is not an unknown offset, it is a STATED ZERO — the one "
                "place in this category where an absent field has a defined value rather than "
                "meaning 'not reported'"),
        }
        if "sum" in subs:
            summary = subs["sum"]
            out["summary"] = {
                **{k: bool(v) for k, v in summary.items()},
                "basis": (
                    "§5.2.9 Subfield #1. NO AFFILIATION IS READ FROM AN AUTHENTICATED REPLY — the "
                    "asterix_cat021.py refusal. NOTES 1 to 3 are carried: the M2, M3 and MC flags "
                    "'refer to the contents of data items I062/120, I062/060 and I062/135 "
                    "respectively' and M1 to Subfield #5; an authenticated reply with the "
                    "Emergency bit set is what sets I062/080's ME; and one with the Identification "
                    "of Position bit set is what sets I062/080's SPI"),
            }
        if "pmn" in subs:
            out["pin_national_origin_mission"] = {
                **subs["pmn"],
                "basis": (
                    "§5.2.9 Subfield #2, parked as three integers. NO NATIONAL ORIGIN IS RESOLVED "
                    "TO A NATION: the table is not in this document and reading one would be an "
                    "identification decision. Its NOTE says NATO changed the layout in 2011 and "
                    "that the new one is in I062/REF/M5N, WHICH APPENDIX A EDITION 1.3 DOES NOT "
                    "DEFINE — and the consequence is sharper here than for the other seven "
                    "dangling pointers, because the item says equipment certified to the new "
                    "layout uses the REF version: a modern reply's national origin is unreachable "
                    "in this category"),
            }
        if "pos" in subs:
            out["reported_position"] = {
                "latitude": codec.from_raw("latitude_23", subs["pos"]["latitude_raw"]),
                "longitude": codec.from_raw("longitude_23", subs["pos"]["longitude_raw"]),
                "latitude_raw": subs["pos"]["latitude_raw"],
                "longitude_raw": subs["pos"]["longitude_raw"],
                "valid_at_offset_seconds": offset_seconds,
                "basis": ("§5.2.9 Subfield #3, at 180/2^23 degrees. PARKED; never "
                          "Entity.position. Its NOTE: 'The resolution implied by the LSB is better "
                          "than the resolution with which Mode 5 position reports are transmitted "
                          "from aircraft transponders using currently defined formats'"),
            }
        if "ga" in subs:
            ga = subs["ga"]
            out["gnss_derived_altitude"] = {
                "feet": codec.from_raw("gnss_altitude", ga["ga_raw"]),
                "raw": ga["ga_raw"],
                "reported_granularity": "25 ft increments" if ga["res"] else "100 ft increments",
                "valid_at_offset_seconds": offset_seconds,
                "basis": (
                    "§5.2.9 Subfield #4. THE RES BIT DOES NOT CHANGE THE ARITHMETIC — NOTE 1: 'GA "
                    "is coded as a 14-bit two's complement binary number with an LSB of 25 ft "
                    "IRRESPECTIVE OF THE SETTING OF RES' — so RES says what the reporting "
                    "granularity was and the LSB is always 25 ft. Getting that backwards would "
                    "scale every 100-ft-granularity altitude by four. NOTE 2's 'The minimum value "
                    "of GA that can be reported is -1000 ft' is a statement about the TRANSPONDER "
                    "rather than a range on the field, so it is carried as a floor and a pattern "
                    "below it is not refused"),
                "stated_minimum_reportable_ft": -1000,
            }
        if "em1" in subs:
            out["extended_mode_1"] = {
                "octal": _octal(subs["em1"]["extended_mode_1"]),
                "raw": subs["em1"]["extended_mode_1"],
                "from_mode_5_reply": (bool(subs["sum"]["m1"]) if "sum" in subs else False),
                "basis": ("§5.2.9 Subfield #5. Its NOTE gives a STATED DEFAULT rather than an "
                          "unknown: 'If Subfield #1 is present, the M1 bit in Subfield #1 "
                          "indicates whether the Extended Mode 1 Code is from a Mode 5 reply or a "
                          "Mode 1 reply. If Subfield #1 is not present, the Extended Mode 1 Code "
                          "is from a Mode 1 reply'"),
            }
        if "xp" in subs:
            xp = subs["xp"]
            out["x_pulse_presence"] = {
                **{k: bool(v) for k, v in xp.items() if k.startswith("x")},
                "spare_bits_8_6": xp["spare_bits_8_6"],
                "basis": ("§5.2.9 Subfield #7, five X-pulse flags. NOTE THE DUPLICATION: "
                          "Subfield #1's bit 1 is also an X pulse 'from Mode 5 Data reply or "
                          "Report', in the same words as this subfield's X5. Two fields, one "
                          "measurement, and the document does not say they must agree — so both "
                          "are parked and a disagreement is recorded, never resolved"),
            }
            if "sum" in subs and subs["sum"]["x"] != xp["x5"]:
                unresolved["I062/110 X pulse disagreement"] = {
                    "raw": {"subfield_1_x": subs["sum"]["x"], "subfield_7_x5": xp["x5"]},
                    "reason": ("Subfield #1's X and Subfield #7's X5 both report the X pulse from "
                               "a Mode 5 Data reply, in the same words, and this record states "
                               "them differently. The document does not say which wins, so "
                               "neither is preferred"),
                }
        return out

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Entities that CAME FROM CAT062 back to one data block, byte-exactly.

        Everything derived — `observed_at`, `Position`, `Kinematics`, `accuracy_m`, the decoded
        degrees and seconds and flight levels — is a one-way view and is **not** the source of any
        emitted byte. Re-encoding a latitude from `Position.lat` would run the scaling in both
        directions and hide an error in it; re-encoding a course and speed into `Vx` and `Vy` would
        be worse, because the vector-to-scalar map is not injective and any choice of components
        would be an invention; and re-encoding `accuracy_m` would need an inverse of
        `sqrt(a² + b²)` that does not exist. Re-emitting the parked integers means a conversion
        defect can only ever affect the CDM view and never the wire.
        """
        entities = [obj for obj in objects if isinstance(obj, Entity)]
        if not entities:
            raise Cat062ParseError(
                f"nothing to emit: {len(objects)} object(s) and no Entity among them. A CDM "
                "Track cannot become a CAT062 data block either, and the reason is not the "
                "arithmetic: this adapter never emits a Track, so a Track reaching here did not "
                "come from CAT062 and carries no FSPEC, no track number and no time of track "
                "information. Inventing a track number would NAME a system track that does not "
                "exist"
            )
        return build_block([self._record_from_entity(entity) for entity in entities])

    def _record_from_entity(self, entity: Entity) -> dict:
        parked = entity.attributes.get("source_extras") or {}
        items = parked.get("items") if isinstance(parked, dict) else None
        fspec = entity.attributes.get("cat062_fspec")
        octets = entity.attributes.get("cat062_items")
        if not items or not fspec:
            missing = [name for name, value in
                       (("source_extras.items", items), ("cat062_fspec", fspec)) if not value]
            raise Cat062ParseError(
                f"Entity {entity.entity_id} did not come from CAT062: {', '.join(missing)} "
                "is absent from its attributes. There is no track number and §5.2.3's Encoding "
                "Rule says I062/040 'shall be present in every ASTERIX record'; there is no time "
                "of track information and §5.2.5 says the same of I062/070; there is no track "
                "status and §5.2.6 says the same of I062/080; and there is no FSPEC, so nothing "
                "states which items the record claimed to carry. The refusal names each missing "
                "input rather than inventing one"
            )
        return {"index": 0, "fspec": fspec, "items": items,
                "item_octets": dict(octets or {})}
