"""STANAG 4607 / AEDP-4607 Edition A Version 1 — GMTI packets in, CDM out, and back. Adapter #8.

It implements the STANAG 4607 row set in FORMAT_COVERAGE.md field by field, including everything
its seven amendments overturned; that section is this module's specification, `LAYOUTS` and
`SUBRECORDS` below are the same 212 fields in machine-readable form, and a test asserts that the
two agree in both directions — so a field nobody decided about fails the build rather than being
quietly absent.

WHAT THE INPUT IS
-----------------
`to_cdm()` takes ONE GMTIF packet: the raw bytes, or the already-decoded dict a fixture twin
holds. The standard draws the boundary itself — §2.2, "the format does not specify error
detection/correction, encryption, or the physical transmission of the data … the format requires
these functions to be accomplished by the lower layers of the communications media", and there is
"no provision or need within AEDP-4607 for Start- or End-of Message characters". Guide §D.4 puts
sequence numbers, loss detection and channelisation in a mux/demux layer explicitly outside the
format. So there is no socket here, no reassembly buffer, no sequence-number window and no cache
of previous packets. Splitting a stream into packets is the caller's job, by instruction.

A DETECTION IS NOT A TRACK, AND NO TARGET TRACK IS EVER EMITTED
---------------------------------------------------------------
This is the first adapter in the set that emits no `Track` for its subject matter, and the reason
is that the format carries no identifier for a real target anywhere in its core segments. `D32.1`
MTI Report Index is "the sequential count of this MTI report WITHIN the dwell" by its own
definition and is Conditional besides; `(D2, D3)` does not identify a Dwell Segment, because guide
§D.2 says "multiple dwell segments may be sent with the same Dwell Index"; and `D3` wraps.
Associating reports across dwells is what a GMTI tracker does, and the format's own implementation
guide sends the reader to the sensor vendor for the rule (FAQ Q10) — so a translator may not
invent one. Each target report becomes one `Entity` and one `DETECTION` `Event`, and the `Entity`'s
key ends in two POSITIONAL ordinals whose fragility is stated on the object rather than hidden.

THE PLATFORM IS THE ONE REAL IDENTITY, AND IT GETS THE ONLY TRACK
-----------------------------------------------------------------
§3.1.8 makes each nation responsible for its platforms being "uniquely identified within the set
of platforms it owns", so `P3` + `P8` is a globally unique key and a genuine `SourceId`. Its
positions arrive in two segments with two DIFFERENT KINDS OF INSTANT: `D6` is "the temporal center
of the dwell" (§3.4.6) and `L1` is "the time the report is prepared" (§3.15.1). Both are on the
wire, under one Packet Header, so no association step is performed — but a consumer interpolating
across a mixed run would be averaging an observation midpoint against an authoring timestamp, so
every sample parks its own `time_basis` and source segment. The argument rests on those two field
definitions and NOT on guide §E.8, which speaks only about the positions coinciding and is silent
about the instants.

WHAT A PAYLOAD FIELD MAY NOT DO — INCLUDING WHEN IT AGREES
-----------------------------------------------------------
`P7` Exercise Indicator is Mandatory on every packet and says "real", "simulated" or "synthesized"
in as many words. It NEVER writes `source.synthetic`, in any direction, agreement included: a rule
that let a payload field set a deployment declaration whenever the two happened to match would
bind only on disagreement, which is a default with a conflict check bolted on. Three branches: a
PURE-simulated `P7` against a real declaration refuses, a PURE-real `P7` against a synthetic
declaration refuses, and `synthesized` — "a mix of real and simulated data", §3.1.7 — contradicts
neither pure declaration and parks visibly without a refusal. `D32.10`'s simulated half obeys the
same rule, and a simulated target inside a packet declaring real data is a SEPARATE refusal —
payload against payload rather than payload against deployment — reported independently, because a
refusal that names the wrong cause is a guess wearing a refusal's clothes.

THE TAGGING-DEVICE EXEMPTION IS KEYED ON THE LABEL, NOT ON 142
---------------------------------------------------------------
`D32.16` and `D32.17` are each "sent only if the MTI Target in this report is simulated OR a
tagging device is detected" — a disjunction, so the standard itself treats a tagging device as
distinct from simulation. The value carrying that label has been 140, then 143, then 142 across
three editions (the trail is ambiguity 3 in the row set), so `_states_simulation` keys on
`Tagging Device` as a STRING and the next renumbering moves the exemption with the label. The
prose's stale citation of 140 is not re-based to 142 anywhere in this file: doing that would be a
translator making an editorial correction to a normative document, and the row set declines it for
the same reason `stanag4676.py` uses the acknowledged-wrong `nga.gov` namespace. So `D32.17`'s tag
identification number — the one candidate `SourceId` in the whole format — is deferred rather than
minted, and the system name it would take, `GMTIF-TAG`, is written down here so that whoever gets
the custodian's erratum knows what the five-line change is.

REFUSING VERSUS RECORDING, AND WHY IT IS NOT A VALIDATION ANNEX'S PREFERENCE
----------------------------------------------------------------------------
§3.2.1 is silent on receiver behaviour and guide Annex G is stale — its own references name STANAG
4607 Edition 2 of 2007, which is how it comes to publish a `P6` codeword table contradicting the
standard's. So the split rests on something this code can verify: whether the byte offsets of
everything after the problem are still known. A reserved or extension segment type is skipped
EXACTLY, because §3.2.2 makes `S2` "the number of bytes in this header and the data segment which
follows this header" — so the parse continues with no guessing, and the segment is logged and
recorded (type code, size, raw bytes) because a silent skip would make a packet carrying an
Advanced Dwell Segment indistinguishable from one carrying nothing. A mask violation, a broken
conditional group or a size mismatch destroys exactly that property: a Dwell Segment's field
offsets are a function of `D1`, so one wrong bit desynchronises everything after it and there is
nothing to continue from. Skipping is available where the format hands over a length, and withheld
where it does not.

TRANSFORMS IS EMPTY, AND THAT IS A CLAIM
-----------------------------------------
Every decoded field is parked verbatim in `attributes.gmti_packet` and `attributes.gmti_segments`
as well as converted into canonical fields, so the never-drop rule is satisfied by PRESENCE rather
than by a declared exemption and `lossless.unrepresented()` runs at full strength with nothing
excused. The park is also what makes the byte-exact round trip structural: egress re-encodes from
the parked field values, and `test_cdm_gmtif_adapter` asserts `encode(decode(b)) == b` on every
fixture.
"""
from __future__ import annotations

import datetime as _dt
from typing import Any, Iterable, Sequence

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.adapters import gmtif_codec as codec
from synapse_cdm.enums import Affiliation, EntityType, EventType, PositionSource, Severity
from synapse_cdm.models import (CDMBase, Entity, Event, Kinematics, Position, SourceId, Track,
                                TrackSample)

SYSTEM = "GMTIF"

#: `P1` Version ID for AEDP-4607 Edition A Version 1. §3.1.1: "of the form 'mn', where 'm'
#: reflects the edition of the standard and 'n' reflects the version", with edition A = 4.
VERSION_ID = "41"

PACKET_HEADER_BYTES = 32
SEGMENT_HEADER_BYTES = 5


class GmtifError(ValueError):
    """A GMTI packet this adapter refuses to translate. Every message quotes what it read."""


# ============================================================== the segment layouts
#
# 212 fields, transcribed from AEDP-4607 Ed A V1 Tables 3-1, 3-6, 3-7, 3-9, 3-10, 3-12, 3-13,
# 3-14, 3-19, 3-20, 3-21, 3-22, 3-24, 4-1 and 4-2. This is the row set in machine-readable form
# and `test_the_layout_tables_match_the_row_set` checks the two against each other in BOTH
# directions, so neither can drift.
#
#   (field id, M/C/O, form, width)
#
# `width` restates the codec's own width for fixed forms so the layout can be summed against the
# byte count the standard prints for each segment — `test_every_segment_layout_sums_to_the_
# standards_own_byte_count` does exactly that, and it is what catches a transposed form.
# "A" is a fixed-width BCS field; "REST" is the remainder of the segment (only `F3` uses it).

Field = tuple[str, str, str, int]

PACKET_HEADER: list[Field] = [
    ("P1", "M", "A", 2), ("P2", "M", "I32", 4), ("P3", "M", "A", 2), ("P4", "M", "E8", 1),
    ("P5", "M", "A", 2), ("P6", "M", "FL16", 2), ("P7", "M", "E8", 1), ("P8", "M", "A", 10),
    ("P9", "M", "I32", 4), ("P10", "M", "I32", 4),
]

SEGMENT_HEADER: list[Field] = [
    ("S1", "M", "E8", 1), ("S2", "M", "I32", 4),
]

MISSION: list[Field] = [
    ("M1", "M", "A", 12), ("M2", "M", "A", 12), ("M3", "M", "E8", 1), ("M4", "M", "A", 10),
    ("M5", "M", "I16", 2), ("M6", "M", "I8", 1), ("M7", "M", "I8", 1),
]

#: `D2`-`D31`, in the order Figure 3-1 assigns them existence-mask bits. The order IS the mask,
#: so this list may not be reordered for readability.
DWELL: list[Field] = [
    ("D2", "M", "I16", 2), ("D3", "M", "I16", 2), ("D4", "M", "FL8", 1), ("D5", "M", "I16", 2),
    ("D6", "M", "I32", 4), ("D7", "M", "SA32", 4), ("D8", "M", "BA32", 4), ("D9", "M", "S32", 4),
    ("D10", "C", "SA32", 4), ("D11", "C", "BA32", 4),
    ("D12", "O", "I32", 4), ("D13", "O", "I32", 4), ("D14", "O", "I16", 2),
    ("D15", "C", "BA16", 2), ("D16", "C", "I32", 4), ("D17", "C", "S8", 1),
    ("D18", "O", "I8", 1), ("D19", "O", "I16", 2), ("D20", "O", "I16", 2),
    ("D21", "C", "BA16", 2), ("D22", "C", "SA16", 2), ("D23", "C", "SA16", 2),
    ("D24", "M", "SA32", 4), ("D25", "M", "BA32", 4), ("D26", "M", "B16", 2),
    ("D27", "M", "BA16", 2), ("D28", "O", "BA16", 2), ("D29", "O", "SA16", 2),
    ("D30", "O", "SA16", 2), ("D31", "O", "I8", 1),
]

TARGET_REPORT: list[Field] = [
    ("D32.1", "C", "I16", 2), ("D32.2", "C", "SA32", 4), ("D32.3", "C", "BA32", 4),
    ("D32.4", "C", "S16", 2), ("D32.5", "C", "S16", 2), ("D32.6", "O", "S16", 2),
    ("D32.7", "O", "S16", 2), ("D32.8", "O", "I16", 2), ("D32.9", "O", "S8", 1),
    ("D32.10", "O", "E8", 1), ("D32.11", "O", "I8", 1),
    ("D32.12", "C", "I16", 2), ("D32.13", "C", "I16", 2), ("D32.14", "C", "I8", 1),
    ("D32.15", "C", "I16", 2), ("D32.16", "C", "I8", 1), ("D32.17", "C", "I32", 4),
    ("D32.18", "O", "S8", 1),
]

#: `H2`-`H31`, in Figure 3-4's mask order.
HRR: list[Field] = [
    ("H2", "M", "I16", 2), ("H3", "M", "I16", 2), ("H4", "M", "FL8", 1), ("H5", "C", "I16", 2),
    ("H6", "C", "I16", 2), ("H7", "C", "I16", 2), ("H8", "M", "I16", 2), ("H9", "C", "I8", 1),
    ("H10", "M", "I8", 1), ("H11", "M", "B16", 2), ("H12", "M", "B16", 2), ("H13", "M", "H32", 4),
    ("H14", "M", "H32", 4), ("H15", "C", "B32", 4), ("H16", "M", "E8", 1), ("H17", "M", "E8", 1),
    ("H18", "M", "E8", 1), ("H19", "M", "B16", 2), ("H20", "O", "S8", 1), ("H21", "C", "S16", 2),
    ("H22", "C", "H32", 4), ("H23", "M", "E8", 1), ("H24", "M", "FL8", 1), ("H25", "M", "I8", 1),
    ("H26", "M", "I8", 1), ("H27", "O", "I8", 1), ("H28", "O", "I32", 4), ("H29", "O", "I8", 1),
    ("H30", "O", "B32", 4), ("H31", "O", "B32", 4),
]

#: `H32.1`-`H32.4`, which occupy the last four existence-mask bits and are NEVER decoded. The
#: scatterer array is a signature, the declines table rejects mapping it, and its record layout
#: is width-variable (`H25`, `H26`) with a record COUNT the standard states two incompatible ways
#: (`H6` "pixels that exceed target scatterer threshold", `H7` "total number of scatterer records"
#: for a sparse chip). So the array is parked as the remainder of the segment, whose end `S2`
#: gives exactly, and the H6/H7 question is left where the standard left it.
HRR_SCATTERER_MASK: tuple[tuple[str, str], ...] = (
    ("H32.1", "M"), ("H32.2", "C"), ("H32.3", "C"), ("H32.4", "C"),
)

JOB_DEFINITION: list[Field] = [
    ("J1", "M", "I32", 4), ("J2", "M", "E8", 1), ("J3", "M", "A", 6), ("J4", "M", "FL8", 1),
    ("J5", "M", "I8", 1),
    ("J6", "M", "SA32", 4), ("J7", "M", "BA32", 4), ("J8", "M", "SA32", 4),
    ("J9", "M", "BA32", 4), ("J10", "M", "SA32", 4), ("J11", "M", "BA32", 4),
    ("J12", "M", "SA32", 4), ("J13", "M", "BA32", 4),
    ("J14", "M", "E8", 1), ("J15", "M", "I16", 2),
    ("J16", "M", "I16", 2), ("J17", "M", "I16", 2), ("J18", "M", "I16", 2),
    ("J19", "M", "I8", 1), ("J20", "M", "I16", 2), ("J21", "M", "I16", 2),
    ("J22", "M", "BA16", 2), ("J23", "M", "I16", 2), ("J24", "M", "I8", 1),
    ("J25", "M", "I8", 1), ("J26", "M", "I8", 1), ("J27", "M", "E8", 1), ("J28", "M", "E8", 1),
]

FREE_TEXT: list[Field] = [
    ("F1", "M", "A", 10), ("F2", "M", "A", 10), ("F3", "M", "REST", 0),
]

TEST_STATUS: list[Field] = [
    ("T1", "M", "I32", 4), ("T2", "M", "I16", 2), ("T3", "M", "I16", 2), ("T4", "M", "I32", 4),
    ("T5", "M", "FL8", 1), ("T6", "M", "FL8", 1),
]

PROCESSING_HISTORY: list[Field] = [
    ("C1", "M", "I8", 1), ("C2", "M", "A", 2), ("C3", "M", "A", 10),
    ("C4", "M", "I32", 4), ("C5", "M", "I32", 4),
]

PROCESSING_RECORD: list[Field] = [
    ("C6.1", "M", "I8", 1), ("C6.2", "M", "A", 2), ("C6.3", "M", "A", 10),
    ("C6.4", "M", "I32", 4), ("C6.5", "M", "I32", 4), ("C6.6", "M", "FL16", 2),
]

PLATFORM_LOCATION: list[Field] = [
    ("L1", "M", "I32", 4), ("L2", "M", "SA32", 4), ("L3", "M", "BA32", 4), ("L4", "M", "S32", 4),
    ("L5", "M", "BA16", 2), ("L6", "M", "I32", 4), ("L7", "M", "S8", 1),
]

JOB_REQUEST: list[Field] = [
    ("R1", "M", "A", 10), ("R2", "M", "A", 10), ("R3", "M", "I8", 1),
    ("R4", "M", "SA32", 4), ("R5", "M", "BA32", 4), ("R6", "M", "SA32", 4),
    ("R7", "M", "BA32", 4), ("R8", "M", "SA32", 4), ("R9", "M", "BA32", 4),
    ("R10", "M", "SA32", 4), ("R11", "M", "BA32", 4),
    ("R12", "M", "E8", 1), ("R13", "M", "I16", 2), ("R14", "M", "I16", 2),
    ("R15", "M", "I16", 2), ("R16", "M", "I8", 1), ("R17", "M", "I8", 1), ("R18", "M", "I8", 1),
    ("R19", "M", "I8", 1), ("R20", "M", "I8", 1), ("R21", "M", "I16", 2),
    ("R22", "M", "I16", 2), ("R23", "M", "I16", 2), ("R24", "M", "E8", 1),
    ("R25", "M", "A", 6), ("R26", "M", "FL8", 1),
]

JOB_ACKNOWLEDGE: list[Field] = [
    ("A1", "M", "I32", 4), ("A2", "M", "A", 10), ("A3", "M", "A", 10), ("A4", "M", "E8", 1),
    ("A5", "M", "A", 6), ("A6", "M", "I8", 1),
    ("A7", "M", "SA32", 4), ("A8", "M", "BA32", 4), ("A9", "M", "SA32", 4),
    ("A10", "M", "BA32", 4), ("A11", "M", "SA32", 4), ("A12", "M", "BA32", 4),
    ("A13", "M", "SA32", 4), ("A14", "M", "BA32", 4),
    ("A15", "M", "E8", 1), ("A16", "M", "I16", 2), ("A17", "M", "I16", 2),
    ("A18", "M", "E8", 1), ("A19", "M", "I16", 2), ("A20", "M", "I8", 1), ("A21", "M", "I8", 1),
    ("A22", "M", "I8", 1), ("A23", "M", "I8", 1), ("A24", "M", "I8", 1), ("A25", "M", "A", 2),
]

LAYOUTS: dict[str, list[Field]] = {
    "packet_header": PACKET_HEADER, "segment_header": SEGMENT_HEADER, "mission": MISSION, "dwell": DWELL, "hrr": HRR,
    "job_definition": JOB_DEFINITION, "free_text": FREE_TEXT, "test_status": TEST_STATUS,
    "processing_history": PROCESSING_HISTORY, "platform_location": PLATFORM_LOCATION,
    "job_request": JOB_REQUEST, "job_acknowledge": JOB_ACKNOWLEDGE,
}

SUBRECORDS: dict[str, list[Field]] = {
    "target_report": TARGET_REPORT, "processing_record": PROCESSING_RECORD,
}

#: The byte count the standard's own tables imply for each fixed-length segment, restated so the
#: layout can be checked against the document rather than against itself.
SEGMENT_BYTES = {"packet_header": 32, "segment_header": 5, "mission": 39, "job_definition": 68,
                 "test_status": 14, "processing_history": 21, "platform_location": 23,
                 "job_request": 79, "job_acknowledge": 79, "target_report": 36,
                 "processing_record": 23}

#: The seven fields the row set gives a row and this module implements as STRUCTURE rather than as
#: a value at an offset. Each is real and each is exercised; none is a layout entry, because a
#: layout entry is something read at a computed offset and these are what compute the offsets.
#: `test_the_layout_tables_match_the_row_set` accounts for them explicitly so the 212 fields add
#: up without a fudge.
STRUCTURAL_FIELDS: dict[str, str] = {
    "D1": "the Dwell Segment existence mask — MASKED['dwell']['mask_field'], read before any "
          "field because it decides which fields exist and therefore where each one starts",
    "D32": "the target report container — SUBRECORDS['target_report'], repeated D5 times",
    "H1": "the HRR Segment existence mask — MASKED['hrr']['mask_field']",
    "H32": "the scatterer record container — parked whole as the remainder of the segment, per "
           "the declines table, so it has no per-field layout by design",
    "C6": "the processing record container — SUBRECORDS['processing_record'], repeated C1 times",
}

# ------------------------------------------------------------------ segment types, Table 3-6

SEGMENT_KINDS: dict[int, str] = {
    1: "mission", 2: "dwell", 3: "hrr", 5: "job_definition", 6: "free_text",
    10: "test_status", 12: "processing_history", 13: "platform_location",
    101: "job_request", 102: "job_acknowledge",
}

#: The reserved codes the standard NAMES, versus the bare ranges. Both are skipped and recorded;
#: the name is carried because "Group Segment" tells a consumer more than "type 8".
RESERVED_NAMED: dict[int, str] = {
    4: "Reserved (the Range-Doppler Segment)",
    7: "Low Reflectivity Index (LRI) Segment",
    8: "Group Segment",
    9: "Attached Target Segment",
    11: "System-Specific Segment",
}

#: Guide Annex L.3.1's registry. Approved and validated extension segment types whose field
#: tables §L.4 does not contain — it reads "(TO BE PROVIDED)" — so they are a BLOCKER rather than
#: a decline, and the name is all this adapter can honestly say about one.
CONTROLLED_EXTENSIONS: dict[int, str] = {
    128: "Advanced Dwell Segment", 129: "Advanced Job Definition Segment",
    130: "Advanced Platform Location Segment", 131: "Target Centroid Segment",
    132: "Releasability Segment",
}


def reserved_name(code: int) -> str:
    if code in RESERVED_NAMED:
        return RESERVED_NAMED[code]
    if code in CONTROLLED_EXTENSIONS:
        return f"{CONTROLLED_EXTENSIONS[code]} (registered in guide Annex L.3.1, §L.4 empty)"
    if 14 <= code <= 100:
        return "Reserved for new Segments"
    if 103 <= code <= 127:
        return "Reserved for future use"
    if 128 <= code <= 255:
        return "Reserved for Extensions (unregistered)"
    return "unknown segment type"


# ------------------------------------------------------- existence masks, Figures 3-1 and 3-4
#
# The mask's bit order IS the field order, and the standard says which end it starts at: "the
# most-significant bit (bit 7) of the high-order byte (byte 7) corresponds to the first field (D2)
# … where the high-order byte shall be transmitted first". So read as one big-endian integer of
# the mask's width, field k (0-based, D2 = 0) sits at bit (total_bits - 1 - k).

MASKED: dict[str, dict[str, Any]] = {
    "dwell": {"mask_field": "D1", "mask_form": "FL64",
              "body": DWELL, "sub": TARGET_REPORT, "sub_mask": TARGET_REPORT},
    "hrr": {"mask_field": "H1", "mask_form": "FL40",
            "body": HRR, "sub": None, "sub_mask": HRR_SCATTERER_MASK},
}


def mask_order(kind: str) -> list[tuple[str, str]]:
    """(field id, M/C/O) in existence-mask bit order, body fields then subrecord fields."""
    spec = MASKED[kind]
    order = [(f[0], f[1]) for f in spec["body"]]
    order += [(f[0], f[1]) for f in spec["sub_mask"]]
    return order


def mask_bit(kind: str, field: str) -> int:
    """The bit position of `field` in `kind`'s mask, numbered from the mask's own msb."""
    total = 8 * codec.WIDTHS[MASKED[kind]["mask_form"]]
    for index, (name, _mco) in enumerate(mask_order(kind)):
        if name == field:
            return total - 1 - index
    raise KeyError(field)


def present(kind: str, mask: int, field: str) -> bool:
    return bool(mask >> mask_bit(kind, field) & 1)


# ------------------------------------------------------ conditional groups, per settlement 7
#
# Each entry is a rule the standard states in the fields' own text, checked as a group and
# reported as a group. Every violated rule appears in ONE refusal, prefixed by its name: the
# STANAG 4676 ordering rule says first-match-wins means a producer only ever hears about
# whichever check happened to run first.

#: (name, kind, fields) — all present or all absent.
TOGETHER: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("SENSOR POSITION UNCERTAINTY", "dwell", ("D12", "D13", "D14")),
    ("SENSOR VELOCITY", "dwell", ("D15", "D16", "D17")),
    ("SENSOR VELOCITY UNCERTAINTY", "dwell", ("D18", "D19", "D20")),
    ("PLATFORM ORIENTATION", "dwell", ("D21", "D22", "D23")),
    ("SCALE FACTORS", "dwell", ("D10", "D11")),
    ("HI-RES TARGET LOCATION", "dwell", ("D32.2", "D32.3")),
    ("DELTA TARGET LOCATION", "dwell", ("D32.4", "D32.5")),
    ("TARGET LOS VELOCITY", "dwell", ("D32.7", "D32.8")),
    ("TRUTH TAG", "dwell", ("D32.16", "D32.17")),
)

#: (name, kind, first group, second group) — exactly one of the two, never both and never neither.
EXCLUSIVE: tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("TARGET LOCATION", "dwell", ("D32.2", "D32.3"), ("D32.4", "D32.5")),
)

#: (name, kind, dependent, prerequisite) — the dependent may appear only if the prerequisite does.
REQUIRES: tuple[tuple[str, str, str, str], ...] = (
    # §3.4.10/§3.4.11: D10 and D11 "are sent if and only if the optional difference fields Delta
    # Latitude (D32.4) and Delta Longitude (D32.5) are sent in the Target Report".
    ("SCALE FACTORS", "dwell", "D10", "D32.4"),
    ("SCALE FACTORS", "dwell", "D32.4", "D10"),
    # §3.4.32.12-15: "sent only if fields D12, D13, and D14 of the Dwell Segment are sent".
    ("TARGET UNCERTAINTY", "dwell", "D32.12", "D12"),
    ("TARGET UNCERTAINTY", "dwell", "D32.13", "D12"),
    ("TARGET UNCERTAINTY", "dwell", "D32.14", "D12"),
    ("TARGET UNCERTAINTY", "dwell", "D32.15", "D12"),
    # …and D32.14 additionally requires D32.6, D32.15 additionally requires D32.7.
    ("HEIGHT UNCERTAINTY", "dwell", "D32.14", "D32.6"),
    ("RADIAL VELOCITY UNCERTAINTY", "dwell", "D32.15", "D32.7"),
)

#: `H23` Type of HRR/RDM governs five HRR conditionals: (name, field, required-for, optional-for).
#: A value outside 0-7 makes these unevaluable, so the checks are SKIPPED with the skip recorded
#: rather than failed against a condition nobody can evaluate.
HRR_BY_TYPE: tuple[tuple[str, str, tuple[int, ...] | None, tuple[int, ...] | None], ...] = (
    # §3.5.5: H5 "must be used in conjunction with data types 1 thru 4".
    ("HRR REPORT INDEX", "H5", (1, 2, 3, 4), None),
    # §3.5.15: H15 "must be used in conjunction with all HRR/RDM data types except types 1 and 3.
    # This field is optional for data types 1 and 3."
    ("HRR CENTER FREQUENCY", "H15", (0, 2, 4, 5, 6, 7), (1, 3)),
    # §3.5.21/§3.5.22: "must be used in conjunction with HRR/RDM data type 4 and 6. This field is
    # optional for all other HRR/RDM data types."
    ("HRR ORIGIN", "H21", (4, 6), (0, 1, 2, 3, 5, 7)),
    ("HRR ORIGIN", "H22", (4, 6), (0, 1, 2, 3, 5, 7)),
    # §3.5.9: H9 "must be used in conjunction with data type (per H23) 3".
    ("HRR CLUTTER POWER", "H9", (3,), (0, 1, 2, 4, 5, 6, 7)),
)

# ------------------------------------------------------------------ No Statement values, §2.4
#
# §2.4: "For Mandatory Fields for which no information is being provided, a 'No Statement' value
# may be transmitted, where the No Statement value is defined in the Value Range column". So a
# Mandatory field is always PRESENT and may still say nothing — a fourth category the existence
# mask cannot express — and `unavailable_fields` keeps "the source did not send it" apart from
# "the source sent it and said it does not know".

NO_STATEMENT: dict[str, Any] = {
    "J16": 65535, "J17": 65535, "J18": 65535, "J19": 255, "J20": 65535,
    "J21": 65535, "J23": 65535, "J24": 255, "J25": 255, "J26": 255,
    "J2": 255, "R24": 255, "R25": "None",
    "H11": 0.0, "H12": 0.0, "H17": 0, "H18": 0, "H19": 0.0,
    "P6": 0, "D32.16": 0, "D32.17": 0,
}

#: `J22` is a BA16 whose No-Statement value the table gives as the ANGLE 180.0, not as an integer.
J22_NO_STATEMENT = 180.0

#: Alphanumeric fields whose all-space form is a stated absence in the field's own text.
BLANK_IS_A_STATED_ABSENCE = ("P5", "M1", "M2", "M4")


# ============================================================== Table 3-11, D32.10
#
# Every one of the 256 values accounted for, per the row set's enumeration table. The mapping is
# uniform after amendment 1: a vehicle, vessel or aircraft is a PLATFORM and everything else parks
# as UNKNOWN. FACILITY appears nowhere — `Stationary Rotator` and `Ground Rotator` name a Doppler
# signature class, and reading an installation off a motion characteristic is the inference this
# adapter already refuses for `M3` Platform Type.

_P = EntityType.PLATFORM
_U = EntityType.UNKNOWN

TARGET_CLASSIFICATION: dict[int, tuple[str, EntityType]] = {
    0: ("No Information, Live Target", _U),
    1: ("Tracked Vehicle, Live Target", _P),
    2: ("Wheeled Vehicle, Live Target", _P),
    3: ("Rotary Wing Aircraft, Live Target", _P),
    4: ("Fixed Wing Aircraft, Live Target", _P),
    5: ("Stationary Rotator, Live Target", _U),
    6: ("Maritime, Live Target", _P),
    7: ("Beacon, Live Target", _U),
    8: ("Amphibious, Live Target", _P),
    9: ("Person, Live Target", _U),
    10: ("Vehicle, Live Target", _P),
    11: ("Animal, Live Target", _U),
    12: ("Large Multiple-Return, Live Land Target", _U),
    13: ("Large Multiple-Return, Live Maritime Target", _U),
    14: ("Clutter, Live Target", _U),
    15: ("Phantom Live", _U),
    16: ("Ground Rotator Live", _U),
    17: ("Small Vehicle, Live Target", _P),
    18: ("Low-slow Flyer, Live Target", _P),
    126: ("Other, Live Target", _U),
    127: ("Unknown, Live Target", _U),
    128: ("No Information, Simulated Target", _U),
    129: ("Tracked Vehicle, Simulated Target", _P),
    130: ("Wheeled Vehicle, Simulated Target", _P),
    131: ("Rotary Wing Aircraft, Simulated Target", _P),
    132: ("Fixed Wing Aircraft, Simulated Target", _P),
    133: ("Stationary Rotator, Simulated Target", _U),
    134: ("Maritime, Simulated Target", _P),
    135: ("Beacon, Simulated Target", _U),
    136: ("Amphibious, Simulated Target", _P),
    137: ("Person, Simulated Target", _U),
    138: ("Vehicle, Simulated Target", _P),
    139: ("Animal, Simulated Target", _U),
    140: ("Large Multiple-Return, Simulated Land Target", _U),
    141: ("Large Multiple-Return, Simulated Maritime Target", _U),
    142: ("Tagging Device", _U),
    143: ("Reserved", _U),
    144: ("Clutter, Simulated Target", _U),
    145: ("Phantom Simulated", _U),
    146: ("Ground Rotator Simulated", _U),
    147: ("Small Vehicle, Simulated Target", _P),
    148: ("Low-slow Flyer, Simulated Target", _P),
    254: ("Other, Simulated Target", _U),
    255: ("Unknown, Simulated Target", _U),
}

#: The two labels in the upper half the table does NOT mark "Simulated", so a report carrying one
#: makes no simulation claim. **Keyed on the label and not on a value** (amendment 6): the
#: `Tagging Device` label has been carried by 140, then 143, then 142 across three editions, so a
#: rule written against the number would silently change behaviour on the next renumbering.
CONFLICT_EXEMPT_LABELS = ("Tagging Device", "Reserved")

#: Codes with no row in Table 3-11 at all — the bare reserved ranges.
RESERVED_CLASSIFICATIONS = tuple(list(range(19, 126)) + list(range(149, 254)))


def classification_label(code: int) -> str:
    named = TARGET_CLASSIFICATION.get(code)
    return named[0] if named else "Reserved"


def classification_type(code: int) -> EntityType:
    named = TARGET_CLASSIFICATION.get(code)
    return named[1] if named else EntityType.UNKNOWN


def _states_simulation(code: int) -> bool:
    """Does this classification value declare the target simulated?

    Keyed on the LABEL. `D32.16` is "sent only if the MTI Target in this report is simulated OR a
    tagging device is detected" (§3.4.32.16) — a disjunction, which is only meaningful if a
    tagging device is not simulated — so a `Tagging Device` report is a real detection of a real
    emitter that happens to sit in the numeric range above 127. `Reserved` is exempt for a WEAKER
    reason and the basis says which: the table does not mark it Simulated, but no clause says what
    it is either, so the exemption there is withholding an inference rather than reading a stated
    distinction.
    """
    if classification_label(code) in CONFLICT_EXEMPT_LABELS:
        return False
    return code >= 128


# ------------------------------------------------------------------ P7, Table 3-5

P7_MEANING: dict[int, tuple[str, str, str]] = {
    0: ("Operation, Real Data", "operation", "real"),
    1: ("Operation, Simulated Data", "operation", "simulated"),
    2: ("Operation, Synthesized Data", "operation", "synthesized"),
    128: ("Exercise, Real Data", "exercise", "real"),
    129: ("Exercise, Simulated Data", "exercise", "simulated"),
    130: ("Exercise, Synthesized Data", "exercise", "synthesized"),
}

# ------------------------------------------------------------------ small enumerations

P4_CLASSIFICATION = {1: "TOP SECRET", 2: "SECRET", 3: "CONFIDENTIAL", 4: "RESTRICTED",
                     5: "UNCLASSIFIED"}

T5_HARDWARE = {7: "Antenna Status", 6: "RF Electronics Status", 5: "Processor Status",
               4: "Datalink Status", 3: "Calibration Mode Status"}
T6_MODE = {7: "Range Limit Exceeded", 6: "Azimuth Limit Exceeded",
           5: "Elevation Limit Exceeded", 4: "Temperature Limit Exceeded"}
J4_FILTERING = {0: "area filtering within the Dwell/Bounding intersection",
                1: "Area Blanking applied", 2: "Sector Blanking applied"}
H24_PROCESSING = {7: "Clutter Cancellation", 6: "Single-Ambiguity Keystoning",
                  5: "Multi-Ambiguity Keystoning", 0: "Unknown"}
C6_6_PROCESSING = {
    0: "Area Filtering", 1: "Target Classification Filtering", 2: "LOS Velocity Filtering",
    3: "SNR Filtering", 4: "De-clutter Filtering", 5: "Bandwidth Filtering",
    6: "Revisit Filtering", 7: "Location Adjustment", 8: "Geoid Adjustment",
    9: "Location Registration", 10: "Time Filtering", 11: "Security Filtering",
    12: "Data Augmentation", 13: "Target Coordinate Conversion",
}

MS_PER_DAY = 86_400_000

#: Table 3-9's stated maximum for `D6`/`T4`/`L1`, which §3.3.7 and Annex C-3 both contradict by
#: naming the full I32 range ("49 days and 17 hours"). Ambiguity 2: the value is CONVERTED, the
#: raw integer parked, and the excursion recorded — refusing would reject a value two of the
#: standard's three statements permit.
D6_TABLE_MAXIMUM = 4_000_000_000


# ============================================================== decoding, bytes -> dict


def _decode_fields(data: bytes, offset: int, layout: Sequence[Field],
                   mask: int | None = None, kind: str | None = None,
                   *, where: str) -> tuple[dict[str, Any], int]:
    """Read a run of fields at `offset`, honouring the existence mask where there is one."""
    out: dict[str, Any] = {}
    for field, _mco, form, width in layout:
        if mask is not None and kind is not None and not present(kind, mask, field):
            continue
        if form == "A":
            out[field] = codec.read_bcs(data, offset, width, field=f"{where} {field}")
            offset += width
        elif form == "REST":
            remaining = len(data) - offset
            out[field] = codec.read_bcs(data, offset, remaining,
                                        field=f"{where} {field}", strip=False)
            offset += remaining
        else:
            out[field] = codec.read(form, data, offset)
            offset += codec.WIDTHS[form]
    return out, offset


def _record_width(layout: Sequence[Field], mask: int, kind: str) -> int:
    return sum(codec.WIDTHS[form] if form not in ("A", "REST") else width
               for field, _mco, form, width in layout if present(kind, mask, field))


def decode_packet(data: bytes) -> dict:
    """One GMTI packet -> the decoded dict this adapter also accepts directly.

    Every value is the DECODED one — an integer for an integer form, a float for a scaled one, a
    trailing-pad-stripped string for an alphanumeric — because `test_cdm_gmtif_codec` asserts
    `write(read(b)) == b` exhaustively for the 8- and 16-bit forms and by boundary sampling for
    the 32-bit ones, so re-encoding from the value is byte-exact. That is what makes a fixture
    twin readable: a `.parsed.json` full of wire integers would carry the same information and
    tell a reviewer nothing.
    """
    if len(data) < PACKET_HEADER_BYTES:
        raise GmtifError(
            f"packet is {len(data)} bytes and the Packet Header is {PACKET_HEADER_BYTES}. §3.1.2: "
            "\"the minimum packet size shall be the number of bytes in the Packet Header\""
        )
    header, offset = _decode_fields(data, 0, PACKET_HEADER, where="Packet Header")
    if header["P2"] != len(data):
        raise GmtifError(
            f"P2 Packet Size is {header['P2']} and the payload holds {len(data)} bytes. §3.1.2 "
            "makes P2 \"the number of bytes in the entire packet, including this header\", so the "
            "two disagreeing means either a truncated delivery or a mis-framed packet — and a "
            "partial parse of a byte-aligned format reads every subsequent segment from the wrong "
            "offset"
        )

    segments: list[dict] = []
    while offset < len(data):
        if offset + SEGMENT_HEADER_BYTES > len(data):
            raise GmtifError(
                f"truncated Segment Header at offset {offset}: {SEGMENT_HEADER_BYTES} bytes "
                f"needed, {len(data) - offset} available"
            )
        head, _ = _decode_fields(data, offset, SEGMENT_HEADER, where="Segment Header")
        s1, s2 = head["S1"], head["S2"]
        available = len(data) - offset
        if s2 < SEGMENT_HEADER_BYTES or s2 > available:
            raise GmtifError(
                f"segment type {s1} at offset {offset} declares S2 = {s2} bytes and {available} "
                f"remain in the packet. §3.2.2 makes S2 \"the number of bytes in this header and "
                "the data segment which follows this header\", not to exceed the packet size "
                "minus the header, so this is a truncated or mis-sized packet. S2 is the only "
                "thing that makes a skip safe, and a skip that runs past the end is not a skip"
            )
        body = data[offset + SEGMENT_HEADER_BYTES:offset + s2]
        segments.append(_decode_segment(s1, s2, body, len(segments)))
        offset += s2
    return {"header": header, "segments": segments}


def _decode_segment(s1: int, s2: int, body: bytes, ordinal: int) -> dict:
    kind = SEGMENT_KINDS.get(s1)
    if kind is None:
        # Skip-and-record, on §3.2.1's reservation plus §3.2.2's length. NEVER a silent skip: a
        # consumer must be able to tell that the packet held material this adapter did not read.
        return {"type": s1, "size": s2, "ordinal": ordinal, "unsupported": reserved_name(s1),
                "raw_hex": body.hex()}

    entry: dict[str, Any] = {"type": s1, "size": s2, "ordinal": ordinal}
    where = f"segment[{ordinal}] type {s1}"

    if kind in MASKED:
        spec = MASKED[kind]
        mask_form = spec["mask_form"]
        entry["mask"] = codec.read(mask_form, body, 0)
        offset = codec.WIDTHS[mask_form]
        fields, offset = _decode_fields(body, offset, spec["body"], entry["mask"], kind,
                                        where=where)
        entry["fields"] = fields
        _check_mask(kind, entry, where)
        if kind == "dwell":
            entry["targets"] = _decode_targets(body, offset, entry, where)
        else:
            # The scatterer array is the remainder. Parked whole, never mapped — the declines
            # table rejects it, and its record count is stated two incompatible ways.
            entry["scatterers_hex"] = body[offset:].hex()
    elif kind == "processing_history":
        fields, offset = _decode_fields(body, 0, PROCESSING_HISTORY, where=where)
        entry["fields"] = fields
        records = []
        for index in range(fields["C1"]):
            record, offset = _decode_fields(body, offset, PROCESSING_RECORD,
                                            where=f"{where} record[{index}]")
            records.append(record)
        if offset != len(body):
            raise GmtifError(
                f"{where}: C1 Processing History Count is {fields['C1']}, which needs "
                f"{fields['C1'] * SEGMENT_BYTES['processing_record']} bytes of records after the "
                f"{SEGMENT_BYTES['processing_history']}-byte main body, and the segment holds "
                f"{len(body)}. C1 is \"a count of the number of processing records included in "
                "this segment\", so a mismatch is a packet with an error"
            )
        entry["records"] = records
    else:
        fields, offset = _decode_fields(body, 0, LAYOUTS[kind], where=where)
        entry["fields"] = fields
        if offset != len(body) and kind != "free_text":
            raise GmtifError(
                f"{where}: the {kind} layout consumes {offset} bytes and the segment holds "
                f"{len(body)}. A fixed-length segment whose size disagrees with its layout is a "
                "packet with an error, and continuing would read the next segment header from "
                "the wrong offset"
            )
    return entry


def _decode_targets(body: bytes, offset: int, entry: dict, where: str) -> list[dict]:
    """`D5` target reports, or none at all if `D5` is zero.

    §3.4.1's own exception, and it has to be checked BEFORE the mask: "if field D5=0 (i.e. no
    targets present) then it shall be assumed that the target report fields (D32.1-D32.18) are
    not present even if the existence mask indicates they are. This allows producers to implement
    constant values in the existence mask for these fields regardless of whether targets are
    reported in each dwell segment." So a Dwell Segment with a zero count and target-report bits
    set is CONFORMANT, and honouring the mask instead would consume bytes belonging to the next
    segment.
    """
    count = entry["fields"]["D5"]
    if count == 0:
        entry["d5_override"] = bool(entry["mask"] & ((1 << (mask_bit("dwell", "D32.18"))) |
                                                     sum(1 << mask_bit("dwell", f[0])
                                                         for f in TARGET_REPORT)))
        if offset != len(body):
            raise GmtifError(
                f"{where}: D5 Target Report Count is 0, so §3.4.1 says the target report fields "
                f"are not present, and {len(body) - offset} bytes remain after the dwell body"
            )
        return []
    width = _record_width(TARGET_REPORT, entry["mask"], "dwell")
    if width == 0:
        raise GmtifError(
            f"{where}: D5 Target Report Count is {count} and the existence mask marks every "
            "target report field absent, so the reports have no content at all"
        )
    needed = count * width
    if len(body) - offset != needed:
        raise GmtifError(
            f"{where}: D5 Target Report Count is {count} at {width} bytes per report "
            f"(from the existence mask), which needs {needed} bytes, and "
            f"{len(body) - offset} remain in the segment. §3.4.5 makes D5 the count of targets "
            "\"sent in this Dwell Segment\", so a mismatch is a packet with an error"
        )
    targets = []
    for index in range(count):
        report, offset = _decode_fields(body, offset, TARGET_REPORT, entry["mask"], "dwell",
                                        where=f"{where} target[{index}]")
        targets.append(report)
    return targets


def _check_mask(kind: str, entry: dict, where: str) -> None:
    """Settlement 7's four rules. Every violated group is listed in ONE refusal."""
    mask = entry["mask"]
    fields = entry["fields"]
    problems: list[str] = []

    for field, mco in mask_order(kind):
        if mco == "M" and not present(kind, mask, field):
            if kind == "dwell" and field.startswith("D32.") and fields.get("D5") == 0:
                continue
            problems.append(
                f"MANDATORY FIELD ABSENT: {field} is Mandatory and its existence-mask bit "
                f"{mask_bit(kind, field)} is clear. Figures 3-1 and 3-4 give every Mandatory bit "
                "the value 1, and the mask governs field offsets — one cleared bit "
                "desynchronises every field after it"
            )

    d5_zero = kind == "dwell" and fields.get("D5") == 0

    def _on(field: str) -> bool:
        if d5_zero and field.startswith("D32."):
            return False
        return present(kind, mask, field)

    for name, group_kind, group in TOGETHER:
        if group_kind != kind:
            continue
        states = {field: _on(field) for field in group}
        if any(states.values()) and not all(states.values()):
            problems.append(
                f"CONDITIONAL GROUP {name}: the standard says these fields are always sent "
                f"together, and the mask has {sorted(f for f, on in states.items() if on)} "
                f"present with {sorted(f for f, on in states.items() if not on)} absent"
            )
    for name, group_kind, first, second in EXCLUSIVE:
        if group_kind != kind or d5_zero:
            continue
        a, b = all(_on(f) for f in first), all(_on(f) for f in second)
        if a == b:
            problems.append(
                f"CONDITIONAL GROUP {name}: exactly one of {list(first)} and {list(second)} is "
                f"sent — §3.4.32.2 says \"if fields D32.2 and D32.3 are sent, then fields D32.4 "
                f"and D32.5 are not sent\" and §3.4.32.4 says the converse — and the mask has "
                f"{'both' if a else 'neither'}. A target report with no location at all reports "
                "a detection nobody can place"
            )
    for name, group_kind, dependent, prerequisite in REQUIRES:
        if group_kind != kind:
            continue
        if _on(dependent) and not _on(prerequisite):
            problems.append(
                f"CONDITIONAL GROUP {name}: {dependent} is present and {prerequisite}, which the "
                "standard makes its precondition, is absent"
            )

    if kind == "hrr":
        problems += _check_hrr_conditionals(mask, fields, entry)

    if problems:
        raise GmtifError(
            f"{where}: existence mask 0x{mask:0{2 * codec.WIDTHS[MASKED[kind]['mask_form']]}X} "
            f"violates {len(problems)} rule(s) — "
            + " | ".join(problems)
        )


def _check_hrr_conditionals(mask: int, fields: dict, entry: dict) -> list[str]:
    problems: list[str] = []
    if not (present("hrr", mask, "H6") or present("hrr", mask, "H7")):
        problems.append(
            "CONDITIONAL GROUP HRR SCATTERER COUNT: §3.5.6 and §3.5.7 both say \"either H6 or H7 "
            "or both must be reported\", and the mask has neither"
        )
    h23 = fields.get("H23")
    if h23 is None or h23 > 7:
        # A reserved H23 makes five conditionals unevaluable. Skipped WITH THE SKIP RECORDED
        # rather than failed against a condition nobody can evaluate.
        entry["h23_unevaluable"] = (
            f"H23 Type of HRR/RDM is {h23}, which Table 3-12 reserves (8-255), so the five "
            "conditional rules it governs — H5, H15, H21, H22 and H9 — cannot be evaluated and "
            "were skipped rather than failed")
        return problems
    for name, field, required_for, optional_for in HRR_BY_TYPE:
        on = present("hrr", mask, field)
        if required_for is not None and h23 in required_for and not on:
            problems.append(
                f"CONDITIONAL GROUP {name}: {field} is required for H23 = {h23} and is absent")
        if required_for is not None and optional_for is not None and \
                h23 not in required_for and h23 not in optional_for and on:
            problems.append(
                f"CONDITIONAL GROUP {name}: {field} is present and H23 = {h23} neither requires "
                "nor permits it")
    if present("hrr", mask, "H32.2") != bool(fields.get("H26")):
        problems.append(
            f"CONDITIONAL GROUP HRR SCATTERER PHASE: §3.5.26 says a H26 of 0 \"indicates no phase "
            f"data is present and H32.2 is not populated\", and H26 is {fields.get('H26')} with "
            f"the H32.2 mask bit {'set' if present('hrr', mask, 'H32.2') else 'clear'}")
    for field, allowed in (("H25", (1, 2)), ("H26", (0, 1, 2))):
        if fields.get(field) not in allowed:
            problems.append(
                f"SCATTERER RECORD WIDTH: {field} is {fields.get(field)} and §3.5.25/§3.5.26 "
                f"allow only {list(allowed)}. The scatterer array's record width is a function of "
                "both, so any other value makes the array's length indeterminate")
    return problems


# ============================================================== encoding, dict -> bytes


def encode_packet(parsed: dict) -> bytes:
    """The exact inverse of `decode_packet`, byte for byte.

    `P2` and every `S2` are RECOMPUTED and then checked against the parked values. Recomputing
    without checking would let a decoder bug and an encoder bug cancel out invisibly, which is
    precisely what a round-trip test is supposed to catch.
    """
    body = b"".join(_encode_segment(segment) for segment in parsed["segments"])
    header = dict(parsed["header"])
    size = PACKET_HEADER_BYTES + len(body)
    if header.get("P2") != size:
        raise GmtifError(
            f"P2 Packet Size is parked as {header.get('P2')} and the encoded packet is {size} "
            "bytes. The two must agree or the emitted packet declares its own length wrongly"
        )
    return _encode_fields(header, PACKET_HEADER) + body


def _encode_fields(values: dict, layout: Sequence[Field],
                   mask: int | None = None, kind: str | None = None) -> bytes:
    out = bytearray()
    for field, _mco, form, width in layout:
        if mask is not None and kind is not None and not present(kind, mask, field):
            continue
        if field not in values:
            raise GmtifError(f"{field} is absent from the parked segment and its mask bit is set")
        value = values[field]
        if form == "A":
            out += codec.write_bcs(value, width, field=field)
        elif form == "REST":
            out += codec.write_bcs(value, len(value.encode("ascii")), field=field)
        else:
            out += codec.write(form, value)
    return bytes(out)


def _encode_segment(segment: dict) -> bytes:
    s1 = segment["type"]
    if "unsupported" in segment:
        body = bytes.fromhex(segment["raw_hex"])
    else:
        kind = SEGMENT_KINDS[s1]
        if kind in MASKED:
            spec = MASKED[kind]
            mask = segment["mask"]
            body = codec.write(spec["mask_form"], mask)
            body += _encode_fields(segment["fields"], spec["body"], mask, kind)
            if kind == "dwell":
                for report in segment.get("targets") or []:
                    body += _encode_fields(report, TARGET_REPORT, mask, kind)
            else:
                body += bytes.fromhex(segment.get("scatterers_hex") or "")
        elif kind == "processing_history":
            body = _encode_fields(segment["fields"], PROCESSING_HISTORY)
            for record in segment.get("records") or []:
                body += _encode_fields(record, PROCESSING_RECORD)
        else:
            body = _encode_fields(segment["fields"], LAYOUTS[kind])
    size = SEGMENT_HEADER_BYTES + len(body)
    if segment.get("size") is not None and segment["size"] != size:
        raise GmtifError(
            f"segment type {s1} is parked with S2 = {segment['size']} and encodes to {size} bytes"
        )
    return _encode_fields({"S1": s1, "S2": size}, SEGMENT_HEADER) + body


# ============================================================== the reference date, §3.3


class ReferenceDate:
    """Where the mission date came from, carried on every instant it produced.

    §3.3 puts the date in the Mission Segment and says a Dwell Time "will not be resolved as to
    the day of the mission until the Mission Segment is received from the transmitting platform",
    with the segment sent "at least once every two minutes". So mission context carries across
    packets in a stream, and carrying it is the caller's job — this adapter holds no state between
    payloads. Three paths and no fourth; the injected clock is never one of them.
    """

    def __init__(self, date: _dt.date | None, basis: str) -> None:
        self.date = date
        self.basis = basis

    @property
    def midnight(self) -> _dt.datetime:
        if self.date is None:
            raise GmtifError(self.basis)
        return _dt.datetime(self.date.year, self.date.month, self.date.day,
                            tzinfo=_dt.timezone.utc)

    def at(self, milliseconds: int, *, field: str, where: str) -> tuple[_dt.datetime, str]:
        """`midnight + milliseconds`, exact addition and no wrapping of any kind.

        §3.4.6: "the Dwell Time corresponds to the day's UTC time converted to milliseconds, with
        the possible addition of multiples of 86400000 for multi-day missions", and Annex C-3
        prints the worked example — reference date 2002/08/24, a dwell at 08:45:35.2 of the NEXT
        day, D6 = 117,935,200. So a value at or above 86 400 000 is a conformant statement that
        the dwell happened on a later day, not an out-of-range value to reduce modulo a day.
        """
        if self.date is None:
            raise GmtifError(f"{where} states {field} = {milliseconds} ms after midnight and "
                             f"there is no date to add it to. {self.basis}")
        if milliseconds < 0:
            raise GmtifError(f"{where}: {field} is {milliseconds}, and it is a count of "
                             "milliseconds after midnight")
        days, remainder = divmod(milliseconds, MS_PER_DAY)
        basis = (f"{field} = {milliseconds} ms after midnight UTC on "
                 f"{self.date.isoformat()} ({self.basis})")
        if days:
            basis += (f"; {days} whole day(s) past the reference date, per §3.4.6's \"possible "
                      f"addition of multiples of 86400000 for multi-day missions\" — exact "
                      f"addition, never a modulo")
        if milliseconds > D6_TABLE_MAXIMUM:
            basis += (f"; above Table 3-9's stated maximum of {D6_TABLE_MAXIMUM} ms and inside "
                      "the full I32 range §3.3.7 and Annex C-3 both describe as \"49 days\" — "
                      "converted and recorded, per ambiguity 2")
        return self.midnight + _dt.timedelta(milliseconds=milliseconds), basis


def read_reference_date(parsed: dict, supplied: _dt.date | None) -> ReferenceDate:
    """The three paths, and the two conditions amendment 4 attached to the middle one."""
    missions = [s for s in parsed["segments"] if s["type"] == 1]
    on_wire: _dt.date | None = None
    if missions:
        fields = missions[0]["fields"]
        try:
            on_wire = _dt.date(fields["M5"], fields["M6"], fields["M7"])
        except ValueError as exc:
            raise GmtifError(
                f"Mission Segment Reference Time is M5={fields['M5']}, M6={fields['M6']}, "
                f"M7={fields['M7']}, which is not a date ({exc}). Every instant in the packet is "
                "computed from it, so there is nothing to fall back to"
            ) from exc

    if on_wire is not None and supplied is not None and on_wire != supplied:
        raise GmtifError(
            f"the packet's own Mission Segment states a reference date of {on_wire.isoformat()} "
            f"and the caller supplied {supplied.isoformat()}. Neither silently wins: letting the "
            "wire win discards a caller statement that may indicate the caller has mis-tracked "
            "the stream, and letting the argument persist over an in-packet Mission Segment lets "
            "a stale caller-held date override the place §3.3 puts the answer. A contradiction "
            "here means the caller's stream tracking and the producer disagree about what day it "
            "is, which is an operator's problem rather than a precedence rule's"
        )
    if on_wire is not None:
        basis = f"in_packet: Mission Segment M5/M6/M7 = {on_wire.isoformat()}"
        if supplied is not None:
            basis += " (the caller supplied the same date, which agreed and was not used)"
        return ReferenceDate(on_wire, basis)
    if supplied is not None:
        return ReferenceDate(supplied, (
            f"caller_supplied_stream_context: {supplied.isoformat()}, supplied as an explicit "
            "argument. THIS PACKET DID NOT CARRY IT — §3.3 sends the Mission Segment at least "
            "once every two minutes, so the caller who owns the stream is relaying an earlier "
            "packet's date. A stand-in for absent wire context, NOT a deployment declaration: it "
            "gets no protection against the wire, and a contradicting Mission Segment is a "
            "refusal"))
    return ReferenceDate(None, (
        "no reference date: this packet carries no Mission Segment and no caller-supplied date "
        "was given, so the milliseconds-after-midnight fields in it resolve to no instant. The "
        "injected clock is NOT a third path — writing the receipt instant's date into the mission "
        "reference would date every dwell in the packet to the day we happened to read it, every "
        "other check would pass, and a mission flying across midnight UTC would produce a picture "
        "24 hours wrong with no symptom"))


# ============================================================== the adapter


class GmtifAdapter(Adapter):
    """One GMTI packet in, CDM objects out, and one GMTI packet back."""

    name = "gmti"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    #: Empty, and that is a claim. Every decoded field is parked verbatim as well as converted,
    #: so the never-drop rule is satisfied by PRESENCE and `lossless.unrepresented()` runs at
    #: full strength with nothing excused.
    TRANSFORMS: dict[str, str] = {}

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 mission_reference_date: _dt.date | None = None,
                 confidentiality_label: dict[str, Any] | None = None,
                 platform_identity: dict[str, Any] | None = None) -> None:
        """Three explicit arguments, and each is a different KIND of thing.

        `mission_reference_date` is a **stand-in for absent wire context** — the date an earlier
        packet in the same stream stated, relayed by the caller who owns the stream. It is not a
        deployment declaration and gets no protection against the wire: a Mission Segment
        contradicting it is a refusal quoting both.

        `confidentiality_label` IS a deployment declaration, in `source.synthetic`'s category —
        `{"P4": int, "P5": str, "P6": int}`. It is the second of the three egress label paths and
        the only one not read from a source; a CDM-native object has no parked `P4`/`P5`/`P6` and
        the three fields are Mandatory on every packet.

        `platform_identity` is a deployment declaration too — `{"P3": str, "P8": str}`, which
        platform WE are. Egress of a CDM-native object needs it because `P3` and `P8` are
        Mandatory and nothing in the CDM states either.
        """
        super().__init__(clock, synthetic=synthetic)
        self._reference_date = mission_reference_date
        self._label = dict(confidentiality_label) if confidentiality_label else None
        self._identity = dict(platform_identity) if platform_identity else None

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        parsed = decode_packet(bytes(raw)) if isinstance(raw, (bytes, bytearray)) else raw
        if not isinstance(parsed, dict) or "header" not in parsed:
            raise GmtifError(
                f"expected a GMTI packet or its decoded dict, got {type(parsed).__name__}")
        return self._translate(parsed)

    def _translate(self, parsed: dict) -> list[CDMBase]:
        header = parsed["header"]
        version = str(header.get("P1") or "")
        if version != VERSION_ID:
            raise GmtifError(
                f"P1 Version ID is {version!r} and this adapter decodes {VERSION_ID!r} — AEDP-4607 "
                "Edition A Version 1 — only. Guide Annex M item 28 moves Tagging Device from 143 "
                "to 142 and adds ten target classifications between Edition 3 and Edition A, so "
                "an Edition 3 packet decoded here would misclassify targets with no structural "
                "symptom: every length checks out and the targets are simply the wrong kind of "
                "object. One adapter with a version-dispatched enumeration table is the right "
                "shape and Edition 3's tables are not pinned in this repository, so earlier "
                "editions are deferred rather than best-effort decoded"
            )

        segments = parsed["segments"]
        kinds = {s["type"] for s in segments}
        dwell_like = bool(kinds & {2, 3, 4})
        if dwell_like and header["P10"] == 0:
            raise GmtifError(
                "P10 Job ID is 0 and the packet carries a Dwell, HRR or Range-Doppler segment. "
                "§3.4: \"a Dwell Segment may be sent only if the Job ID in the associated Packet "
                "Header is not equal to zero\", and §3.1.10 requires the header's Job ID to be "
                "\"the non-zero Job ID corresponding to those segments\" — so a zero here leaves "
                "the dwell belonging to no job a consumer can name"
            )

        reference = read_reference_date(parsed, self._reference_date)
        p7_basis = self._check_exercise_indicator(header)
        classification_basis = self._check_simulated_targets(header, segments)
        received = self.now()

        objects: list[CDMBase] = []
        shared = {
            "header": header, "reference": reference, "received": received,
            "p7_basis": p7_basis, "classification_basis": classification_basis,
            "label": self._label_from(header),
            # The Dwell Segments of THIS packet, so an HRR segment's H2/H3 can borrow the dwell's
            # D6 as its observed_at. Reading a time from the same payload is not a join; resolving
            # H5 to a target report would be, and that is refused.
            "dwells": [s for s in segments if s["type"] == 2],
        }
        platform = self._platform(parsed, shared, dwell_like)
        objects.append(platform["entity"])
        if platform["track"] is not None:
            objects.append(platform["track"])

        for segment in segments:
            objects += self._from_segment(segment, shared, platform["entity"].entity_id)
        return objects

    # ------------------------------------------------- packet-level checks

    def _check_exercise_indicator(self, header: dict) -> str:
        """`P7` against the deployment declaration. Three branches; agreement is not a write.

        `P7` NEVER writes `source.synthetic`, in any direction. A rule that let a payload field
        set a deployment declaration whenever the two happened to match would bind only on
        disagreement, which is a default with a conflict check bolted on.
        """
        p7 = header["P7"]
        meaning = P7_MEANING.get(p7)
        if meaning is None:
            return (f"P7 Exercise Indicator is {p7}, which Table 3-5 reserves (3-127, 131-255), "
                    "so the packet's provenance declaration is unreadable — which is NOT the same "
                    f"as the packet not making one. No conflict check ran; source.synthetic is "
                    f"the deployment declaration ({self._synthetic}) and P7 never sets it")
        text, programme, provenance = meaning
        if provenance == "real" and self._synthetic:
            raise GmtifError(
                f"P7 Exercise Indicator is {p7} ({text!r}) — PURELY real data — and this "
                "deployment declares source.synthetic=true. P7 is a payload field and synthetic "
                "is a deployment declaration, so the adapter will not flip one to match the other "
                "in either direction; the conflict is reported instead. A feed declared synthetic "
                "that receives purely real data is a replay of genuine data through a synthetic "
                "pipeline, which is a configuration question an operator must be told about"
            )
        if provenance == "simulated" and not self._synthetic:
            raise GmtifError(
                f"P7 Exercise Indicator is {p7} ({text!r}) — PURELY simulated data — and this "
                "deployment declares source.synthetic=false. A payload field may not rewrite a "
                "deployment declaration, so the conflict is reported rather than resolved: the "
                "feed has either been misconfigured or been fed the wrong data"
            )
        basis = (f"P7 = {p7} ({text!r}) parked verbatim: programme {programme!r}, provenance "
                 f"{provenance!r}. It NEVER sets source.synthetic, which is the deployment "
                 f"declaration ({self._synthetic}) — agreement is not an exception to that rule")
        if provenance == "synthesized":
            basis += ("; §3.1.7 defines this value as \"a mix of real and simulated data\", so it "
                      "contradicts neither a purely-real nor a purely-synthetic declaration and "
                      "parks visibly WITHOUT a refusal. The CDM's boolean cannot hold a mixture, "
                      "and refusing would reject the case §3.1.7 exists to describe")
        elif programme == "exercise":
            basis += ("; the exercise programme axis parks too — exercise data \"originates from "
                      "live-fly or other non-simulated operational sources\" as often as not")
        return basis

    def _check_simulated_targets(self, header: dict, segments: list[dict]) -> str:
        """`D32.10`'s simulated half against `P7`. A SEPARATE refusal from the deployment check.

        Payload-against-payload rather than payload-against-deployment, checked and reported
        independently: a refusal that names the wrong cause is a guess wearing a refusal's
        clothes, and `P7 = 2` is precisely the value the format provides for the packet the
        producer actually has.
        """
        codes: dict[int, int] = {}
        for segment in segments:
            for report in segment.get("targets") or []:
                code = report.get("D32.10")
                if code is not None and _states_simulation(code):
                    codes[code] = codes.get(code, 0) + 1
        meaning = P7_MEANING.get(header["P7"])
        provenance = meaning[2] if meaning else None
        if codes and provenance == "real":
            listing = ", ".join(f"{code} ({classification_label(code)!r}) x{n}"
                                for code, n in sorted(codes.items()))
            raise GmtifError(
                f"P7 Exercise Indicator is {header['P7']} ({meaning[0]!r}) and the packet carries "
                f"target reports whose D32.10 declares them simulated: {listing}. This is an "
                "INTRA-PAYLOAD contradiction — the producer has stated two incompatible things "
                "about its own data — and it is a different refusal from a conflict with the "
                "deployment declaration. P7 = 2, \"Operation, Synthesized Data … a mix of real "
                "and simulated data\", is the value this packet needed. Note that the Tagging "
                "Device and Reserved labels are exempt and are not counted here, because "
                "§3.4.32.16's condition is a disjunction — \"simulated OR a tagging device is "
                "detected\" — so the standard itself treats a tag as distinct from simulation"
            )
        if not codes:
            return ("no target report declares itself simulated, so the intra-payload check found "
                    "nothing to compare against P7")
        return (f"{sum(codes.values())} target report(s) declare a simulated classification "
                f"({sorted(codes)}) and P7's provenance is {provenance!r}, which does not "
                "contradict them. The classification is parked in full and never sets "
                "source.synthetic")

    def _label_from(self, header: dict) -> dict[str, Any]:
        """`P4`/`P5`/`P6`, verbatim, as a triple. `P6` as the raw integer plus its set bits.

        Never as codeword names: standard Table 3-4 assigns `0x0001` to "EU (Releasable To
        European Commission)" and guide Annex G Table G-1 assigns the same bit to "NOCONTRACT",
        with fifteen more divergences — and the standard's own note says the table is
        "representative … not an exhaustive list" and that "each nation shall be responsible for
        developing and publishing their own packet security handling codes". So `P6`'s meaning is
        a function of `P5`, and the digraph travels with the label structurally.
        """
        return {
            "P4": header["P4"],
            "classification": P4_CLASSIFICATION.get(header["P4"], "reserved"),
            "P5": header["P5"],
            "system": header["P5"] or None,
            "P6": header["P6"],
            "code_bits": codec.set_bits(header["P6"], 2),
        }

    # ------------------------------------------------- the platform entity and its track

    def _platform(self, parsed: dict, shared: dict, dwell_like: bool) -> dict:
        header = parsed["header"]
        reference: ReferenceDate = shared["reference"]
        external = f"{header['P3']}/{header['P8']}"
        entity_id = ids.derive(SYSTEM, external, kind="entity")
        source_ids = [SourceId(system="GMTIF-PLATFORM", external_id=external)]

        samples: list[dict] = []
        unavailable: list[str] = []
        unresolved: list[str] = []
        for segment in parsed["segments"]:
            if segment["type"] == 2:
                samples.append(self._dwell_sample(segment, reference, len(samples)))
            elif segment["type"] == 13:
                samples.append(self._location_sample(segment, reference, len(samples)))
        instants = [s["observed_at"] for s in samples]
        out_of_order = [f"sample {i} at {times.render(instants[i])} precedes sample {i - 1} at "
                        f"{times.render(instants[i - 1])}"
                        for i in range(1, len(instants)) if instants[i] < instants[i - 1]]
        if out_of_order:
            raise GmtifError(
                "the packet's platform positions run backwards in time: " +
                " | ".join(out_of_order) +
                ". Sorting them would hide a source defect the caller needs to see, and the "
                "format promises no ordering of segments within a packet — so a producer that "
                "emits them out of order produces a Track this adapter refuses"
            )

        attributes = self._platform_attributes(parsed, shared, samples, unavailable, unresolved,
                                               dwell_like)
        state = samples[-1] if samples else None
        entity = Entity(
            source=self.source_ref(), source_ids=source_ids, entity_id=entity_id,
            entity_type=EntityType.PLATFORM, affiliation=Affiliation.UNKNOWN, symbol=None,
            position=state["position"] if state else None,
            kinematics=state["kinematics"] if state else None,
            attributes=attributes,
            valid_from=state["observed_at"] if state else shared["received"],
            valid_to=None, confidence=None,
        )
        track = None
        if samples:
            track = Track(
                source=self.source_ref(), source_ids=source_ids,
                track_id=ids.derive(SYSTEM, external, kind="track"),
                entity_id=entity_id,
                samples=[TrackSample(position=s["position"], observed_at=s["observed_at"])
                         for s in samples],
                track_quality=None,
            )
        return {"entity": entity, "track": track}

    def _dwell_sample(self, segment: dict, reference: ReferenceDate, index: int) -> dict:
        fields = segment["fields"]
        where = f"Dwell Segment[{segment['ordinal']}]"
        observed, basis = reference.at(fields["D6"], field="D6", where=where)
        position = Position(
            lat=fields["D7"], lon=_to_signed_longitude(fields["D8"]),
            alt_m=fields["D9"] / 100.0,       # D9 is CENTIMETRES; D32.6 is METRES
            position_source=PositionSource.ESTIMATED, accuracy_m=None,
        )
        kinematics = None
        if "D15" in fields:
            kinematics = Kinematics(course_deg=fields["D15"], speed_mps=fields["D16"] / 1000.0,
                                    climb_mps=fields["D17"] / 10.0)
        return {"position": position, "kinematics": kinematics, "observed_at": observed,
                "index": index, "time_basis": "dwell_center", "source_segment": "dwell",
                "segment_ordinal": segment["ordinal"], "observed_at_basis": basis,
                "reference_date_basis": reference.basis}

    def _location_sample(self, segment: dict, reference: ReferenceDate, index: int) -> dict:
        fields = segment["fields"]
        where = f"Platform Location Segment[{segment['ordinal']}]"
        observed, basis = reference.at(fields["L1"], field="L1", where=where)
        position = Position(
            lat=fields["L2"], lon=_to_signed_longitude(fields["L3"]),
            alt_m=fields["L4"] / 100.0,       # L4 is CENTIMETRES, matching D9 and not D32.6
            position_source=PositionSource.ESTIMATED, accuracy_m=None,
        )
        kinematics = Kinematics(course_deg=fields["L5"], speed_mps=fields["L6"] / 1000.0,
                                climb_mps=fields["L7"] / 10.0)
        return {"position": position, "kinematics": kinematics, "observed_at": observed,
                "index": index, "time_basis": "report_prepared",
                "source_segment": "platform_location", "segment_ordinal": segment["ordinal"],
                "observed_at_basis": basis, "reference_date_basis": reference.basis}

    def _platform_attributes(self, parsed: dict, shared: dict, samples: list[dict],
                             unavailable: list[str], unresolved: list[str],
                             dwell_like: bool) -> dict[str, Any]:
        header = parsed["header"]
        reference: ReferenceDate = shared["reference"]
        segments = parsed["segments"]

        for field in BLANK_IS_A_STATED_ABSENCE:
            for holder, name in [(header, field)] + [
                    (s["fields"], field) for s in segments if s["type"] == 1]:
                if holder.get(name) == "":
                    unavailable.append(f"{name}: all-BCS-space, which the field's own text makes "
                                       "a stated absence rather than an empty value")
        if header["P7"] not in P7_MEANING:
            unresolved.append(f"P7 = {header['P7']}, reserved in Table 3-5")
        if header["P4"] not in P4_CLASSIFICATION:
            unresolved.append(f"P4 = {header['P4']}, which Table 3-2 does not define")
        if header["P6"] & 0xFE00:
            unresolved.append(
                f"P6 = 0x{header['P6']:04X} sets bits Table 3-4 marks \"UNDEFINED. FOR FUTURE "
                "USE\" (0x0200-0x8000) — and which sixteen codewords those bits mean is what the "
                "standard and guide Annex G disagree about, so only the raw integer travels")
        for segment in segments:
            unavailable += _no_statement_fields(segment)
            unresolved += _unresolved_values(segment)
        skipped = [{"type": s["type"], "size": s["size"], "name": s["unsupported"],
                    "raw_hex": s["raw_hex"], "byte_count": len(s["raw_hex"]) // 2}
                   for s in segments if "unsupported" in s]

        job_definitions = [s for s in segments if s["type"] == 5]
        attributes: dict[str, Any] = {
            "gmti_packet": header,
            "gmti_segments": segments,
            "platform_id": header["P8"],
            "platform_nationality": header["P3"],
            "confidentiality_label": shared["label"],
            "confidentiality_label_basis": "round_tripped: read from the source packet",
            "synthetic_basis": shared["p7_basis"],
            "target_classification_conflict_basis": shared["classification_basis"],
            "reference_date_basis": reference.basis,
            "entity_key_basis": (
                f"P3 + P8 = {header['P3']}/{header['P8']}. §3.1.8 makes the owning nation "
                "responsible for its platforms being \"uniquely identified within the set of "
                "platforms it owns\", so this is the one globally unique identifier in the format "
                "and the only SourceId this adapter mints from a stated key"),
            "affiliation_basis": (
                "UNKNOWN. GMTIF states no affiliation, no IFF, no identity and no allegiance "
                "anywhere in any segment — it is a radar detection format and a Doppler return "
                "carries no allegiance. P3 Nationality is the PLATFORM's country and is parked at "
                "attributes.platform_nationality; reading it as an affiliation would invent a "
                "coalition membership from a country code"),
            "symbol_basis": (
                "None. symbology.sidc_from_affiliation needs an affiliation, and composing a "
                "symbol from a target classification alone would draw one with an invented "
                "standard identity"),
            "position_source_basis": (
                "ESTIMATED. The platform's position comes from a navigation system the format "
                "never names, so GNSS would be a fabrication — and it is the one value whose "
                "wrongness costs something in a PNT-denied environment"),
            "accuracy_basis": (
                "None, always. The format states twelve uncertainty figures and not one is a "
                "single horizontal 1-sigma metre value: D12 and D13 are two orthogonal "
                "horizontal components in centimetres and reducing them to one scalar means "
                "choosing an RSS, a semi-major axis or a DRMS the source did not state; D32.12 is "
                "a SLANT-range standard deviation, which is not a horizontal error without a "
                "grazing angle the format never gives; and J22, the nominal fallback §3.7.16 "
                "mandates, is an angle in degrees. None means unknown accuracy, never perfect"),
            "alt_datum_basis": (
                "Metres HAE. §3.4.9, §3.15.4 and §3.4.32.6 each say \"above the WGS 84 "
                "ellipsoid\" without qualification, and the standard is followed — but guide §E.8 "
                "says heights are measured \"either from the reference ellipsoid, or from mean sea "
                "level if a geoid model is being used\", and the two readings differ by the geoid "
                "undulation, up to about 105 m. The declared models are parked at J27/J28"),
            "valid_to_basis": (
                "None. A GMTI packet states where the platform was at an instant and makes no "
                "claim about when that ceased to be true"),
            "integrity_basis": (
                "the packet passed structural checks and nothing more: P2 against the byte count, "
                "each S2 against the segment boundaries, and each existence mask against its "
                "field sequence. §2.2 puts error detection in \"the lower layers of the "
                "communications media\", so GMTIF carries no checksum or cryptographic "
                "protection of any kind"),
            "processing_history_absent": not any(s["type"] == 12 for s in segments),
            "job_definition_count": len(job_definitions),
        }
        if not any(s["type"] == 12 for s in segments):
            attributes["processing_history_basis"] = (
                "no Processing History Segment. Guide FAQ Q11: \"if processing is not applied to "
                "the original radar job, then the Processing History Segment is not "
                "transmitted\", so its absence means the data are unmodified — a fact worth "
                "recording rather than an absence of one")
        if job_definitions:
            ended = [s["fields"]["J5"] for s in job_definitions if s["fields"]["J5"] == 255]
            if ended:
                attributes["job_ended"] = True
                attributes["job_ended_basis"] = (
                    "J5 Priority is 255, which §3.7.5 makes \"the Job is ended\" — a state change "
                    "hidden in a priority field. Recorded, never acted on: acting on it means "
                    "holding job state across packets")
            attributes["job_p10_basis"] = self._job_cross_check(header, job_definitions,
                                                               dwell_like)
        if samples:
            attributes["platform_track_points"] = [
                {"sample_index": s["index"], "time_basis": s["time_basis"],
                 "source_segment": s["source_segment"], "segment_ordinal": s["segment_ordinal"],
                 "observed_at": times.render(s["observed_at"]),
                 "observed_at_basis": s["observed_at_basis"],
                 "reference_date_basis": s["reference_date_basis"]}
                for s in samples]
            bases = [s["time_basis"] for s in samples]
            counts = {basis: bases.count(basis) for basis in dict.fromkeys(bases)}
            attributes["platform_track_basis"] = {
                "counts": counts,
                "mixed": len(counts) > 1,
                "note": (
                    "D6 is \"the temporal center of the dwell\" (§3.4.6) and L1 is \"the time the "
                    "report is prepared\" (§3.15.1) — a midpoint of an interval whose duration the "
                    "format never states, and a producer's authoring instant. A consumer "
                    "interpolating or averaging across a MIXED run would be mixing an observation "
                    "midpoint with an authoring timestamp, so a mixed track is the one it must "
                    "not smooth. The samples belong to one Track because P3 + P8 identifies the "
                    "platform in the shared Packet Header and each segment states its own "
                    "instant, not because guide §E.8 says the two positions coincide — that "
                    "sentence is silent about the instants and cannot license an ordered list"),
            }
            attributes["position_basis"] = (
                f"the last platform position in the packet (sample {samples[-1]['index']}, from "
                f"the {samples[-1]['source_segment']} segment). Position and kinematics come from "
                "the SAME sample: taking them from different samples would put two instants into "
                "one Entity with nothing recording the offset")
            attributes["kinematics_basis"] = (
                "from the same sample as the position" if samples[-1]["kinematics"]
                else "the last positioned sample states no velocity (D15/D16/D17 absent), and it "
                     "is never back-filled from an earlier sample")
            attributes["valid_from_basis"] = attributes["position_basis"]
            attributes["track_quality_basis"] = (
                "None. GMTIF states no track quality because it states no track. J25 Nominal "
                "Detection Probability is the probability that \"an unobscured ten square-meter "
                "target will be detected\" — a sensor performance figure about a hypothetical "
                "target, not a quality of this history")
        else:
            attributes["position_basis"] = (
                "this packet carries no Dwell or Platform Location Segment, so it states no "
                "platform position")
            attributes["kinematics_basis"] = attributes["position_basis"]
            attributes["valid_from_basis"] = (
                "the injected clock: the packet states no platform position and therefore no "
                "instant for the platform's state")
        if skipped:
            attributes.setdefault("source_extras", {})["unsupported_segments"] = skipped
            attributes["unsupported_segment_basis"] = (
                f"{len(skipped)} segment(s) were skipped by S2, parked and recorded — never a "
                "silent skip. §3.2.1 reserves their type codes \"for future use\" so this adapter "
                "knows it cannot decode them, and §3.2.2 makes S2 \"the number of bytes in this "
                "header and the data segment which follows\" so it knows exactly where they end. "
                "A silent skip would make a packet carrying an Advanced Dwell Segment "
                "indistinguishable from one carrying nothing, and that segment's absence from the "
                "output would look like an empty dwell")
        if unavailable:
            attributes["unavailable_fields"] = unavailable
        if unresolved:
            attributes["unresolved_raw"] = unresolved
        residual = lossless.residual(parsed, ["header", "segments"])
        if residual:
            attributes.setdefault("source_extras", {})["residual"] = residual
        attributes["coverage_basis"] = (
            "the dwell area (D24-D27), the bounding area (J6-J13), the minimum detectable "
            "velocity (D31/J24), the detection probability (J25) and the false alarm density "
            "(J26) are parked and none becomes a Geometry. Guide §D.2: \"the fact that the radar "
            "has looked at a particular area and found no targets can be just as important as "
            "receiving targets in an area\" — and the CDM has no object for a searched area, so a "
            "Dwell Segment with D5 = 0 produces a platform sample and nothing else. Gap 22")
        return attributes

    @staticmethod
    def _job_cross_check(header: dict, job_definitions: list[dict], dwell_like: bool) -> str:
        """`J1` against `P10`, and the cross-check applies only where §3.1.10 makes them equal.

        Reading it unconditionally makes a Job-Definition-only packet unrepresentable: §3.1.10
        requires `P10 = 0` when the packet carries no Dwell, HRR or Range-Doppler segment, and
        §3.7.1 gives `J1` a range of 1 to 4 294 967 295 — so `J1` could never equal `P10`, and the
        guide's own Figure 2-1 shows exactly such a packet. So the equality is required only under
        §3.1.10's own condition, which is that the packet DOES carry one of those segments.
        """
        j1s = [s["fields"]["J1"] for s in job_definitions]
        if not dwell_like:
            if header["P10"] != 0:
                return (f"P10 is {header['P10']} and the packet carries no Dwell, HRR or "
                        "Range-Doppler segment, where §3.1.10 says it \"shall be 0\". Recorded "
                        "rather than refused: nothing downstream is ambiguous, because there is "
                        "no dwell data for the header's Job ID to apply to. J1 = "
                        f"{j1s} is the job being DEFINED and is not required to equal it")
            return (f"P10 is 0 per §3.1.10 (no Dwell, HRR or Range-Doppler segment in this "
                    f"packet) and J1 = {j1s} is the job being defined. The J1/P10 equality is "
                    "required only under §3.1.10's own condition — see ambiguity 16")
        mismatched = [j1 for j1 in j1s if j1 != header["P10"]]
        if mismatched:
            raise GmtifError(
                f"J1 Job ID is {mismatched} and P10 is {header['P10']} in a packet that carries "
                "a Dwell, HRR or Range-Doppler segment. §3.1.10 requires the header's Job ID to "
                "be \"the non-zero Job ID corresponding to those segments\", so the dwell data "
                "cannot be attributed to a job"
            )
        return f"J1 = {j1s} agrees with P10 = {header['P10']}, per §3.1.10"

    # ------------------------------------------------- per-segment objects

    def _from_segment(self, segment: dict, shared: dict, platform_id: Any) -> list[CDMBase]:
        kind = SEGMENT_KINDS.get(segment["type"])
        if kind == "dwell":
            return self._from_dwell(segment, shared)
        if kind == "hrr":
            return [self._from_hrr(segment, shared, platform_id)]
        if kind == "free_text":
            return [self._from_free_text(segment, shared, platform_id)]
        if kind == "test_status":
            return [self._from_test_status(segment, shared, platform_id)]
        if kind == "processing_history":
            return [self._from_processing_history(segment, shared, platform_id)]
        # Mission, Job Definition, Job Request and Job Acknowledge become no object of their own:
        # they are parked whole on the platform Entity through `gmti_segments`.
        return []

    def _from_dwell(self, segment: dict, shared: dict) -> list[CDMBase]:
        header = shared["header"]
        reference: ReferenceDate = shared["reference"]
        fields = segment["fields"]
        where = f"Dwell Segment[{segment['ordinal']}]"
        observed, observed_basis = reference.at(fields["D6"], field="D6", where=where)

        out: list[CDMBase] = []
        for index, report in enumerate(segment.get("targets") or []):
            external = "/".join(str(part) for part in (
                header["P3"], header["P8"], header["P9"], header["P10"],
                fields["D2"], fields["D3"], f"s{segment['ordinal']}", f"r{index}"))
            entity_id = ids.derive(SYSTEM, external, kind="entity")
            position, position_basis = self._target_position(report, fields, where, index)
            code = report.get("D32.10")
            entity_type = classification_type(code) if code is not None else EntityType.UNKNOWN
            attributes = self._target_attributes(report, segment, shared, external,
                                                 position_basis, observed_basis, code)
            out.append(Entity(
                source=self.source_ref(),
                source_ids=[SourceId(system="GMTIF-TARGET", external_id=external)],
                entity_id=entity_id, entity_type=entity_type,
                affiliation=Affiliation.UNKNOWN, symbol=None,
                position=position, kinematics=None, attributes=attributes,
                valid_from=observed, valid_to=None, confidence=None,
            ))
            out.append(Event(
                source=self.source_ref(),
                source_ids=[SourceId(system="GMTIF-TARGET", external_id=external)],
                event_id=ids.derive(SYSTEM, external, kind="event"),
                event_type=EventType.DETECTION, severity=Severity.INFO,
                related_entities=[entity_id], geometry=None,
                payload={
                    "gmti_target_report": report,
                    "gmti_dwell": {k: v for k, v in fields.items()},
                    "observed_at_basis": observed_basis,
                    "reference_date_basis": reference.basis,
                    "severity_basis": (
                        "INFO. GMTIF grades nothing — there is no severity, priority-of-threat or "
                        "alert level anywhere in the format. J5 and R3 are tasking priorities and "
                        "are parked"),
                    "geometry_basis": (
                        "None. The fix lives on the Entity this event's related_entities names, "
                        "matching asterix_cat021.py and adsb.py: duplicating one measurement into "
                        "two objects invites the two to diverge"),
                },
                observed_at=observed, received_at=shared["received"],
            ))
        return out

    def _target_position(self, report: dict, fields: dict, where: str,
                         index: int) -> tuple[Position, str]:
        """Hi-res, or the delta reconstruction guide §E.7 states in the INTEGER domain."""
        if "D32.2" in report:
            return Position(
                lat=report["D32.2"], lon=_to_signed_longitude(report["D32.3"]),
                alt_m=float(report["D32.6"]) if "D32.6" in report else None,
                position_source=PositionSource.ESTIMATED, accuracy_m=None,
            ), ("hi_res: D32.2/D32.3 as SA32/BA32, exact binary-angle conversions with a "
                "4.7 mm and 9.3 mm LSB respectively")

        # Guide §E.7 requires this on the ENCODED integers, not on degrees, and requires the
        # longitude case to wrap: "it is essential that the ANSI Standard C conventions for
        # unsigned integer arithmetic be adhered to … that overflow from addition or underflow
        # from subtraction yield a result that is congruent mod 2^n".
        delta_lat = report["D32.4"]
        delta_lon = report["D32.5"]
        scale_lat = codec.to_raw("SA32", fields["D10"])
        scale_lon = codec.to_raw("BA32", fields["D11"])
        ref_lat = int.from_bytes(codec.write("SA32", fields["D24"]), "big", signed=True)
        ref_lon = codec.to_raw("BA32", fields["D25"])

        lat_raw = ref_lat + delta_lat * _as_signed(scale_lat, 32)
        if not -(1 << 31) <= lat_raw < (1 << 31):
            raise GmtifError(
                f"{where} target[{index}]: the delta-latitude reconstruction "
                f"({fields['D24']} + {delta_lat} x {fields['D10']}) overflows signed 32-bit "
                "arithmetic. Guide §E.7 does the latitude case in S32 and the longitude case in "
                "I32 for a reason: a longitude wraps at the prime meridian by design and a "
                "latitude has no seam to wrap at, so this is a refusal rather than a conversion"
            )
        # Unsigned, wrapping mod 2^32 — which IS the 360/0 seam for a BA32.
        magnitude = abs(delta_lon) * scale_lon
        lon_raw = (ref_lon + magnitude if delta_lon >= 0 else ref_lon - magnitude) % (1 << 32)
        latitude = codec.from_raw("SA32", lat_raw & 0xFFFFFFFF)
        longitude = codec.from_raw("BA32", lon_raw)
        return Position(
            lat=latitude, lon=_to_signed_longitude(longitude),
            alt_m=float(report["D32.6"]) if "D32.6" in report else None,
            position_source=PositionSource.ESTIMATED, accuracy_m=None,
        ), (f"delta_recovered: (D32.4 {delta_lat} x D10 {fields['D10']}) + D24 {fields['D24']} "
            f"and (D32.5 {delta_lon} x D11 {fields['D11']}) + D25 {fields['D25']}, computed on "
            "the ENCODED integers per guide §E.7 — signed 32-bit for latitude, unsigned 32-bit "
            "for longitude with the wrap the guide requires — and converted ONCE at the end, "
            "never two conversions with arithmetic in between")

    def _target_attributes(self, report: dict, segment: dict, shared: dict, external: str,
                           position_basis: str, observed_basis: str,
                           code: int | None) -> dict[str, Any]:
        reference: ReferenceDate = shared["reference"]
        attributes: dict[str, Any] = {
            "gmti_target_report": report,
            "confidentiality_label": shared["label"],
            "confidentiality_label_basis": "round_tripped: read from the source packet",
            "synthetic_basis": shared["p7_basis"],
            "reference_date_basis": reference.basis,
            "observed_at_basis": observed_basis,
            "position_basis": position_basis,
            "position_source_basis": (
                "ESTIMATED. A target position is a radar geolocation through the terrain and "
                "geoid models J27/J28 — processing code 0x2000 \"Target Coordinate Conversion\" "
                "says so outright. Never GNSS: the target did not report itself"),
            "accuracy_basis": (
                "None. D32.12 is a SLANT-range standard deviation and projecting it to a ground "
                "error needs a grazing angle the format never states; D32.13 is a cross-range "
                "figure in decimetres, orthogonal to it, and combining two orthogonal components "
                "into one scalar means choosing a convention the source did not"),
            "kinematics_basis": (
                "None. D32.7 is \"the component of velocity … along the line of sight\", one "
                "component of a vector whose tangential part is physically unobservable to a "
                "single-look MTI radar — so the target's speed is unknown (the radial component "
                "is a LOWER BOUND, and writing a lower bound into speed_mps would state a "
                "measurement nobody made) and its course is unknown. D32.7 and D32.8 park in "
                "full and the Doppler un-wrapping D32.8 invites is not performed: §3.4.32.8 "
                "addresses it to \"the tracker\" and makes the multiple depend on an expected "
                "speed nobody stated. Gap 21"),
            "confidence_basis": (
                "None. D32.11 is \"the estimated probability that the target classification "
                "appearing in field D32.10 is correctly classified\" — a confidence about the "
                "CLASSIFICATION — and Entity.confidence is a bare float with no stated subject, "
                "so writing 70 there would say \"we are 70% sure this object exists\" about a "
                "source that said \"we are 70% sure it is a wheeled vehicle\". Gap 18"),
            "entity_key_basis": (
                f"P3/P8/P9/P10/D2/D3 plus the Dwell Segment's ordinal position in the packet and "
                f"the report's ordinal position in the segment: {external!r}. The last two are "
                "POSITIONAL and therefore not stable under any re-segmentation of the packet — "
                "and §3.4.32 permits exactly that re-segmentation (\"targets detected within a "
                "dwell may be split among multiple Dwell Segments\"), as does guide §D.2. D32.1 "
                "MTI Report Index is dwell-scoped by its own definition and Conditional besides, "
                "so there is nothing stabler to key on. Gap 20"),
            "affiliation_basis": (
                "UNKNOWN. GMTIF states no affiliation, no IFF and no identity anywhere"),
            "symbol_basis": "None; there is no affiliation to derive one from",
            "valid_to_basis": (
                "None, and it is the least satisfactory statement in this row set. A GMTI "
                "detection asserts existence at ONE instant and asserts nothing afterwards: "
                "valid_to = valid_from would say the object ceased to exist immediately, which is "
                "false, and None reads as \"still current\" to anything holding state. There is "
                "no third option in the model. Gap 20"),
            "track_basis": (
                "no Track. Associating target reports across dwells is what a GMTI tracker does, "
                "and guide FAQ Q10 says the way to do it \"is best recommended by the sensor "
                "manufacturer as it may depend on the sensor's particular design purpose and "
                "mission\" — a format whose own implementation guide sends the reader to the "
                "vendor for the association rule is not one a translator may invent one for"),
        }
        if code is not None:
            attributes["target_classification"] = code
            attributes["target_classification_text"] = classification_label(code)
            attributes["entity_type_basis"] = self._classification_basis(code)
        else:
            attributes["entity_type_basis"] = (
                "UNKNOWN: D32.10 Target Classification is Optional and this report's existence-"
                "mask bit is clear, so the source stated no classification at all")
        return attributes

    @staticmethod
    def _classification_basis(code: int) -> str:
        """Why this value maps where it does — and the simulated-half note is APPENDED, not chosen.

        A value can be both a signature denial and a simulated one (144 is `Clutter, Simulated`),
        and the `128 + n` trap is exactly what a decoder of that value gets wrong, so the two
        statements have to coexist rather than one winning.
        """
        label = classification_label(code)
        mapped = classification_type(code)
        basis = f"D32.10 = {code} ({label!r}) -> {mapped.value}"
        if code in RESERVED_CLASSIFICATIONS:
            return basis + ("; Table 3-11 reserves this value, so it parks in unresolved_raw — "
                            "the source said something this adapter cannot use")
        if _states_simulation(code):
            basis += (
                "; the type half is READ and the simulated half is only RECORDED — it does not "
                "set source.synthetic. Note that 128 + n maps to n for n = 0..13 and for no other "
                "n: 144-148 mirror 14-18 at an offset of +130, so this is a lookup and never "
                "arithmetic")
        if label in ("Stationary Rotator, Live Target", "Ground Rotator Live",
                     "Stationary Rotator, Simulated Target", "Ground Rotator Simulated"):
            return basis + (
                "; a rotator class is a statement about the RETURN's spectrum, not about a "
                "structure — the format never says the scatterer is installed, mounted, "
                "permanent or man-made. FACILITY would assert an installation from a motion "
                "characteristic and SENSOR would additionally assert a function, which is the "
                "inference this adapter already refuses for M3 Platform Type")
        if label == "Person, Live Target" or label == "Person, Simulated Target":
            return basis + (
                "; UNIT names a military formation and EVACUEE_GROUP a humanitarian role, and "
                "both state something specific and false. This diverges from the shipped CAT021 "
                "adapter, which maps emitter category 16 Parachutist to PLATFORM because there "
                "PLATFORM is the class-wide default and a skydiver is an oddity inside it; here "
                "there is no default. The divergence is recorded in gap 20 with both arguments as "
                "a 1.1.0 resolution question")
        if label in ("Clutter, Live Target", "Phantom Live", "Clutter, Simulated Target",
                     "Phantom Simulated"):
            return basis + ("; an explicit statement that this is NOT an object. The CDM has no "
                            "way to emit a detection while denying that anything is there, so the "
                            "Entity is emitted as UNKNOWN and the denial is in the wording")
        if label.startswith("Large Multiple-Return"):
            return basis + ("; an unresolved GROUP of objects of unstated size, so even one "
                            "Entity is a slight overstatement — one object standing for several")
        if label == "Tagging Device":
            return basis + (
                "; the value that breaks the halves, and the EXEMPTION FROM THE INTRA-PAYLOAD "
                "SIMULATION CHECK IS KEYED ON THIS LABEL rather than on 142. §3.4.32.16's "
                "condition is a disjunction — \"simulated OR a tagging device is detected\" — so "
                "the standard itself treats a tag as distinct from simulation, and the label has "
                "been carried by 140, then 143, then 142 across three editions")
        return basis

    def _from_hrr(self, segment: dict, shared: dict, platform_id: Any) -> Event:
        """One `DETECTION` `Event` carrying the segment's parameters. The array is parked whole."""
        reference: ReferenceDate = shared["reference"]
        header = shared["header"]
        fields = segment["fields"]
        external = f"{header['P3']}/{header['P8']}/{header['P9']}/{header['P10']}/hrr" \
                   f"{segment['ordinal']}"
        owning = [s for s in shared.get("dwells", [])
                  if s["fields"]["D2"] == fields["H2"] and s["fields"]["D3"] == fields["H3"]]
        if owning:
            observed, observed_basis = reference.at(owning[0]["fields"]["D6"], field="D6",
                                                   where=f"the Dwell Segment H2/H3 names")
            unresolved = None
        else:
            observed = shared["received"]
            observed_basis = (
                f"the injected clock. The HRR Segment carries H2 Revisit Index = {fields['H2']} "
                f"and H3 Dwell Index = {fields['H3']} and NO TIME OF ITS OWN, and no Dwell "
                "Segment in this packet names that revisit and dwell — so the format stated no "
                "source time for this object. Recorded on the object rather than left as a "
                "plausible instant nobody can account for")
            unresolved = (f"H2/H3 = {fields['H2']}/{fields['H3']} names a dwell that is not in "
                          "this packet; resolving it would be a cross-packet join")
        payload: dict[str, Any] = {
            "gmti_hrr": segment,
            "observed_at_basis": observed_basis,
            "reference_date_basis": reference.basis,
            "severity_basis": "INFO; GMTIF grades nothing",
            "geometry_basis": ("None. An HRR segment states range-Doppler indices in a "
                              "sensor-relative space, not a position"),
            "scatterer_basis": (
                f"the scatterer array is parked whole as {len(segment.get('scatterers_hex') or '') // 2} "
                "raw bytes and never mapped. H32.1-H32.4 are magnitudes, phases and bin indices "
                "in a sensor-relative range-Doppler space — a SIGNATURE, not track state — and "
                "turning one into anything canonical needs a target-recognition model, which is a "
                "different discipline with its own standards. The record COUNT is also stated two "
                "incompatible ways (H6 \"pixels that exceed target scatterer threshold\" against "
                "H7 \"the total number of scatterer records\" for a sparse chip), so the array is "
                "bounded by S2 and the question is left where the standard left it"),
            "h5_basis": (
                f"H5 MTI Report Index = {fields.get('H5')} points at a D32.1 in the same revisit "
                "and dwell. Resolving it to a target report is a join even within the packet, so "
                "related_entities stays empty and the reference is recorded"
                if "H5" in fields else "H5 is absent; this segment carries an RDM with no "
                                       "corresponding target detection"),
        }
        if unresolved:
            payload["unresolved_references"] = [unresolved]
        if segment.get("h23_unevaluable"):
            payload["mask_basis"] = segment["h23_unevaluable"]
        return Event(
            source=self.source_ref(),
            source_ids=[SourceId(system="GMTIF-HRR", external_id=external)],
            event_id=ids.derive(SYSTEM, external, kind="event"),
            event_type=EventType.DETECTION, severity=Severity.INFO,
            related_entities=[], geometry=None, payload=payload,
            observed_at=observed, received_at=shared["received"],
        )

    def _from_free_text(self, segment: dict, shared: dict, platform_id: Any) -> Event:
        header = shared["header"]
        fields = segment["fields"]
        external = f"{header['P3']}/{header['P8']}/{header['P9']}/text{segment['ordinal']}"
        return Event(
            source=self.source_ref(),
            source_ids=[SourceId(system="GMTIF-FREETEXT", external_id=external)],
            event_id=ids.derive(SYSTEM, external, kind="event"),
            event_type=EventType.STATUS_CHANGE, severity=Severity.INFO,
            related_entities=[platform_id], geometry=None,
            payload={
                "gmti_free_text": segment,
                "observed_at_basis": (
                    "the injected clock. The Free Text Segment states no time of any kind, so "
                    "there is no source instant to read; recorded on the object rather than left "
                    "unexplained"),
                "severity_basis": "INFO; the format grades nothing, including an operator message",
                "originator_basis": (
                    "F1 and F2 are parked and neither is a SourceId or a related entity. The "
                    "segment's own note disclaims them: \"fields F1 and F2 (originator and "
                    "recipient ID, respectively) do not have any formal significance in this "
                    "standard\""),
                "text_basis": (
                    "F3 is carried verbatim and NEVER parsed. An operator's message is not a "
                    "structured field, and searching it for coordinates or callsigns would be "
                    "inventing data. Its trailing spaces are kept because its width is the "
                    "remainder of the segment rather than a declared number"),
            },
            observed_at=shared["received"], received_at=shared["received"],
        )

    def _from_test_status(self, segment: dict, shared: dict, platform_id: Any) -> Event:
        reference: ReferenceDate = shared["reference"]
        header = shared["header"]
        fields = segment["fields"]
        observed, observed_basis = reference.at(
            fields["T4"], field="T4", where=f"Test and Status Segment[{segment['ordinal']}]")
        external = f"{header['P3']}/{header['P8']}/{header['P9']}/status{segment['ordinal']}"
        failures = [T5_HARDWARE.get(bit, f"spare bit {bit}")
                    for bit in codec.set_bits(fields["T5"], 1)]
        exceeded = [T6_MODE.get(bit, f"spare bit {bit}")
                    for bit in codec.set_bits(fields["T6"], 1)]
        return Event(
            source=self.source_ref(),
            source_ids=[SourceId(system="GMTIF-STATUS", external_id=external)],
            event_id=ids.derive(SYSTEM, external, kind="event"),
            event_type=EventType.STATUS_CHANGE, severity=Severity.INFO,
            related_entities=[platform_id], geometry=None,
            payload={
                "gmti_test_status": segment,
                "hardware_failures": failures,
                "mode_limits_exceeded": exceeded,
                "observed_at_basis": observed_basis,
                "reference_date_basis": reference.basis,
                "severity_basis": (
                    "INFO, and this is the row where that costs the most. T5 bit 4 is a FAILED "
                    "DATALINK — the most gradeable thing in the format — and grading it is an "
                    "operational judgement about a platform this adapter knows nothing else "
                    "about. The format grades nothing, so the bits are named and the severity is "
                    "not raised"),
                "index_basis": (
                    f"T2 = {fields['T2']} and T3 = {fields['T3']}. Table 3-20 ranges both 1 to "
                    "65535 where their D2/D3 and H2/H3 counterparts start at 0, and §3.4.2 "
                    "defines a Revisit Index of 0 as the FIRST revisit — so a Test and Status "
                    "Segment reporting the first dwell of the first revisit cannot state it. "
                    "Parked as read, neither corrected nor refused"),
            },
            observed_at=observed, received_at=shared["received"],
        )

    def _from_processing_history(self, segment: dict, shared: dict, platform_id: Any) -> Event:
        header = shared["header"]
        fields = segment["fields"]
        external = (f"{header['P3']}/{header['P8']}/{header['P9']}/"
                    f"processing{segment['ordinal']}")
        chain = []
        for record in segment.get("records") or []:
            chain.append({
                "sequence": record["C6.1"],
                "dataset_id": f"{record['C6.2']}/{record['C6.3']}/{record['C6.4']}/"
                              f"{record['C6.5']}",
                "processing_performed": [C6_6_PROCESSING.get(bit, f"reserved bit {bit}")
                                         for bit in codec.set_bits(record["C6.6"], 2)],
            })
        return Event(
            source=self.source_ref(),
            source_ids=[SourceId(system="GMTIF-PROCESSING", external_id=external)],
            event_id=ids.derive(SYSTEM, external, kind="event"),
            event_type=EventType.STATUS_CHANGE, severity=Severity.INFO,
            related_entities=[platform_id], geometry=None,
            payload={
                "gmti_processing_history": segment,
                "based_on_dataset_id": f"{fields['C2']}/{fields['C3']}/{fields['C4']}/"
                                       f"{fields['C5']}",
                "chain": chain,
                "observed_at_basis": (
                    "the injected clock. The Processing History Segment states no time of any "
                    "kind"),
                "severity_basis": "INFO; the format grades nothing",
                "resolution_basis": (
                    "carried in full, in order, and resolved never. C2-C5 name the original radar "
                    "job and each C6.2-C6.5 record names one modifying system, so the chain is a "
                    "provenance graph across packets this adapter will never see. Gap 14 and "
                    "gap 19"),
                "completeness_basis": (
                    "eight of C6.6's fourteen operations are ELIMINATIONS — area, classification, "
                    "LOS-velocity, SNR, de-clutter, bandwidth, revisit and time filtering — so "
                    "this field is the closest the format comes to saying what is missing, and it "
                    "says only THAT something was removed and never WHAT. Gap 22"),
                "unresolved_references": [
                    f"based-on <DataSetID> {fields['C2']}/{fields['C3']}/{fields['C4']}/"
                    f"{fields['C5']} names a radar job that is not this packet"],
            },
            observed_at=shared["received"], received_at=shared["received"],
        )

    # ------------------------------------------------------------------ egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """Two paths and a refusal, and the refusal is the decision the declines table asked for.

        1. **Round-tripped** — objects carrying a parked GMTI packet: re-encoded byte for byte
           from `attributes.gmti_packet` and `attributes.gmti_segments`.
        2. **CDM-native platform state** — an `Entity` with a position and a `Kinematics`, plus a
           deployment-configured `platform_identity`, `mission_reference_date` and
           `confidentiality_label`: emitted as a Mission Segment and one Platform Location
           Segment under `P10 = 0`, which is exactly the packet shape §3.1.10 provides for.
        3. **Refusal** for anything else, and specifically for any attempt to emit a CDM-native
           TARGET as a Dwell Segment target report. `D7`/`D8`/`D9` state where the sensor was and
           `D24`-`D27` state what area it swept; all seven are Mandatory and no CDM object states
           any of them. A configured value for them would be a fabricated observation footprint,
           which is not a deployment declaration — it is an invented measurement, and emitting a
           GMTI packet that claims a radar saw something it did not is the "silent UNCLASSIFIED"
           failure in a different field.
        """
        entities = [o for o in objects if isinstance(o, Entity)]
        tracks = [o for o in objects if isinstance(o, Track)]
        parked = [e for e in entities if isinstance(e.attributes.get("gmti_packet"), dict)]

        if parked:
            if len(parked) > 1:
                headers = {tuple(sorted(e.attributes["gmti_packet"].items())) for e in parked}
                if len(headers) > 1:
                    raise GmtifError(
                        f"{len(parked)} objects carry parked GMTI packet headers and they are not "
                        "the same packet. One emitted packet has ONE Packet Header — one "
                        "nationality, one platform, one mission, one job and one classification — "
                        "so merging two contexts under one header would attribute one producer's "
                        "data to another's platform. Emit them separately"
                    )
            native = [e for e in entities if e not in parked
                      and not any(e.entity_id in (p.entity_id for p in parked) for _ in [0])]
            foreign = [e for e in native if e.source.system != SYSTEM]
            if foreign:
                raise GmtifError(
                    f"{len(foreign)} object(s) from other systems "
                    f"({sorted({e.source.system for e in foreign})}) were passed alongside a "
                    "round-tripped GMTI packet. Nothing from another format's parked context may "
                    "cross into an emitted packet, so this is refused rather than merged"
                )
            root = parked[0]
            return encode_packet({"header": dict(root.attributes["gmti_packet"]),
                                  "segments": list(root.attributes["gmti_segments"])})

        return self._native_packet(entities, tracks)

    def _native_packet(self, entities: list[Entity], tracks: list[Track]) -> bytes:
        if len(entities) != 1:
            raise GmtifError(
                f"CDM-native egress takes exactly one Entity and {len(entities)} were passed. A "
                "GMTI packet's Packet Header names one platform, and there is no segment that "
                "carries several objects' states without a Dwell Segment — which needs a sensor "
                "position and a dwell area no CDM object states"
            )
        entity = entities[0]
        if entity.entity_type is not EntityType.PLATFORM:
            raise GmtifError(
                f"CDM-native egress refuses an Entity of type {entity.entity_type.value}. The "
                "only segment that carries an object's position without stating where a sensor "
                "was and what area it swept is the Platform Location Segment, which is \"the "
                "location of the sensor platform\" (§3.15) — so a non-platform object would have "
                "to become a Dwell Segment target report, and D7/D8/D9 and D24-D27 are Mandatory "
                "and unstated. A configured dwell area is a fabricated observation footprint, not "
                "a deployment declaration"
            )
        missing = [name for name, value in (("position", entity.position),
                                            ("kinematics", entity.kinematics)) if value is None]
        if missing:
            raise GmtifError(
                f"CDM-native egress needs {' and '.join(missing)} on the Entity: L2-L4 and L5-L7 "
                "are all Mandatory in the Platform Location Segment and none has a No-Statement "
                "value"
            )
        if entity.kinematics.course_deg is None or entity.kinematics.speed_mps is None or \
                entity.kinematics.climb_mps is None:
            raise GmtifError(
                "CDM-native egress needs course_deg, speed_mps and climb_mps: L5, L6 and L7 are "
                "Mandatory and none has a No-Statement value, so an absent one cannot be omitted"
            )
        owning = [t for t in tracks if t.entity_id == entity.entity_id]
        if any(len(t.samples) > 1 for t in owning):
            raise GmtifError(
                "CDM-native egress refuses a Track with more than one sample. Every Platform "
                "Location Segment carries its own Mandatory L5/L6/L7 velocity and the CDM holds "
                "ONE Kinematics per Entity, so emitting N segments would repeat one velocity at "
                "every sample — a fabrication for all but the one the Entity's state came from. "
                "That is gap 16 arriving on the egress side, and the honest answer is a refusal "
                "rather than N plausible velocities"
            )
        if not self._identity or not self._identity.get("P3") or not self._identity.get("P8"):
            raise GmtifError(
                "CDM-native egress needs platform_identity={'P3': ..., 'P8': ...}. P3 Nationality "
                "and P8 Platform ID are Mandatory, §3.1.8 makes P8 a real platform's tail number "
                "or satellite designator, and no CDM object states either — so which platform WE "
                "are is a deployment declaration someone has to write down"
            )
        if self._reference_date is None:
            raise GmtifError(
                "CDM-native egress needs mission_reference_date. M5/M6/M7 are Mandatory and every "
                "instant in the packet is a millisecond count from midnight on that date"
            )
        label = self._egress_label(entities)

        instant = times.parse(entity.valid_from)
        midnight = _dt.datetime(self._reference_date.year, self._reference_date.month,
                                self._reference_date.day, tzinfo=_dt.timezone.utc)
        offset_ms = int(round((instant - midnight).total_seconds() * 1000))
        if offset_ms < 0:
            raise GmtifError(
                f"the Entity's valid_from is {times.render(instant)} and the configured mission "
                f"reference date is {self._reference_date.isoformat()}, so L1 would be negative. "
                "L1 is a count of milliseconds AFTER midnight on the reference date"
            )
        # Quantised to each field's own LSB, which is what encoding is. See codec.snap: SA32
        # holds 4.7 mm and BA32 9.3 mm, so a position loses nothing an operator can see; BA16's
        # 0.0055 deg LSB can move L5 Platform Track by up to 2.7 millidegrees, and that is the
        # one loss on this path worth naming.
        mission = {"M1": "", "M2": "", "M3": 0, "M4": "",
                   "M5": self._reference_date.year, "M6": self._reference_date.month,
                   "M7": self._reference_date.day}
        location = {
            "L1": offset_ms,
            "L2": codec.snap("SA32", entity.position.lat),
            "L3": codec.snap("BA32", _to_unsigned_longitude(entity.position.lon)),
            "L4": int(round((entity.position.alt_m or 0.0) * 100)),
            "L5": codec.snap("BA16", entity.kinematics.course_deg),
            "L6": int(round(entity.kinematics.speed_mps * 1000)),
            "L7": int(round(entity.kinematics.climb_mps * 10)),
        }
        segments = [
            {"type": 1, "size": SEGMENT_HEADER_BYTES + SEGMENT_BYTES["mission"],
             "ordinal": 0, "fields": mission},
            {"type": 13, "size": SEGMENT_HEADER_BYTES + SEGMENT_BYTES["platform_location"],
             "ordinal": 1, "fields": location},
        ]
        size = PACKET_HEADER_BYTES + sum(s["size"] for s in segments)
        header = {
            "P1": VERSION_ID, "P2": size,
            "P3": self._identity["P3"], "P4": label["P4"], "P5": label["P5"], "P6": label["P6"],
            # A CDM-native packet states no P7 of its own, and the deployment's `synthetic`
            # declaration is NOT written into it either: that would be the amendment-2 rule run
            # backwards. The value emitted is the one §3.1.7 gives for a packet whose provenance
            # the emitter is not competent to state about somebody else's data — and there is no
            # such value, so the deployment's own declaration is the only honest source and it is
            # recorded as a configured value rather than as a reading of the payload.
            "P7": 1 if self._synthetic else 0,
            "P8": self._identity["P8"],
            "P9": int(self._identity.get("P9", 0)),
            # §3.1.10: 0 because this packet carries no Dwell, HRR or Range-Doppler segment.
            "P10": 0,
        }
        return encode_packet({"header": header, "segments": segments})

    def _egress_label(self, entities: list[Entity]) -> dict[str, Any]:
        """Three paths: the park, the deployment's configured triple, or a refusal.

        `P4`, `P5` and `P6` are Mandatory on every packet, so every emitted packet needs them and
        "somewhere" is enumerated rather than defaulted.
        """
        for entity in entities:
            parked = entity.attributes.get("confidentiality_label")
            if isinstance(parked, dict) and parked.get("P4") is not None:
                return {"P4": parked["P4"], "P5": parked["P5"], "P6": parked["P6"]}
        if self._label and self._label.get("P4") is not None:
            missing = [k for k in ("P4", "P5", "P6") if self._label.get(k) is None]
            if missing:
                raise GmtifError(
                    f"the configured confidentiality label is missing {missing}. A classification "
                    "with no system digraph is a marking whose policy has been removed: P6's bits "
                    "mean different things under different national code sets, and P4's "
                    "RESTRICTED is a level several systems do not have, so the triple travels "
                    "together or not at all"
                )
            return dict(self._label)
        raise GmtifError(
            "no confidentiality label. P4, P5 and P6 are Mandatory on every packet, and there are "
            "exactly three ways to get them: re-emit the parked triple of a round-tripped GMTI "
            "object, take an explicit deployment-supplied triple from "
            "GmtifAdapter(confidentiality_label={'P4': ..., 'P5': ..., 'P6': ...}), or refuse. "
            "There is no safe fourth. A defaulted P4 = 5 (UNCLASSIFIED) is a downgrade decision "
            "taken by a translator, and the absence of a mandatory field is a fact about the "
            "packet rather than a fact about the data's sensitivity"
        )


# ============================================================== small shared helpers


def _to_signed_longitude(degrees: float) -> float:
    """`BA32`/`BA16` longitudes arrive 0-360 East; `Position.lon` is [-180, 180]. Exact."""
    return degrees - 360.0 if degrees > 180.0 else degrees


def _to_unsigned_longitude(degrees: float) -> float:
    return degrees + 360.0 if degrees < 0.0 else degrees


def _as_signed(raw: int, bits: int) -> int:
    return raw - (1 << bits) if raw >> (bits - 1) else raw


def _no_statement_fields(segment: dict) -> list[str]:
    """Mandatory fields present with their own documented No-Statement value.

    Distinct from a field the mask says is absent, and `unavailable_fields` keeps the two apart:
    "the source did not send it" and "the source sent it and said it does not know" are different
    statements about the same missing number.
    """
    out = []
    for field, value in (segment.get("fields") or {}).items():
        sentinel = NO_STATEMENT.get(field)
        if sentinel is not None and value == sentinel:
            out.append(f"{field}: present with its documented No-Statement value {sentinel!r} "
                       "(§2.4), so the source sent the field and said it does not know")
    if (segment.get("fields") or {}).get("J22") == J22_NO_STATEMENT:
        out.append("J22: present with its documented No-Statement value 180.0 degrees (§2.4)")
    return out


def _unresolved_values(segment: dict) -> list[str]:
    """Values read and not usable: a reserved enumeration literal, or an over-range instant."""
    out = []
    fields = segment.get("fields") or {}
    if segment["type"] == 1 and fields.get("M3") is not None and 57 <= fields["M3"] <= 254:
        out.append(f"M3 Platform Type = {fields['M3']}, which Table 3-8 leaves \"Available for "
                   "Future Use\"")
    if fields.get("P7") is not None and fields["P7"] not in P7_MEANING:
        out.append(f"P7 = {fields['P7']}, reserved in Table 3-5")
    for field, top in (("J2", 254), ("R24", 254)):
        if fields.get(field) is not None and 36 <= fields[field] <= top:
            out.append(f"{field} Sensor ID Type = {fields[field]}, \"Available for Future Use\" "
                       "in Table 3-15")
    for field, limit in (("J27", 13), ("J28", 3), ("H16", 1), ("H17", 2), ("H18", 2),
                         ("H23", 7), ("A18", 10)):
        if fields.get(field) is not None and fields[field] > limit:
            out.append(f"{field} = {fields[field]}, above the highest value its enumeration "
                       f"table defines ({limit})")
    for report in segment.get("targets") or []:
        code = report.get("D32.10")
        if code is not None and code in RESERVED_CLASSIFICATIONS:
            out.append(f"D32.10 = {code}, which Table 3-11 reserves")
    for field in ("D6", "T4", "L1"):
        if fields.get(field) is not None and fields[field] > D6_TABLE_MAXIMUM:
            out.append(f"{field} = {fields[field]} ms, above Table 3-9's stated maximum of "
                       f"{D6_TABLE_MAXIMUM} and inside the full I32 range §3.3.7 and Annex C-3 "
                       "call \"49 days\" — converted and recorded, per ambiguity 2")
    if segment.get("d5_override"):
        out.append("D5 Target Report Count is 0 with target-report existence-mask bits set, "
                   "which §3.4.1 makes conformant: \"it shall be assumed that the target report "
                   "fields are not present even if the existence mask indicates they are\"")
    return out
