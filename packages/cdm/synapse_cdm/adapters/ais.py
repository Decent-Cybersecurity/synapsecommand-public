"""AIS — NMEA 0183 AIVDM/AIVDO sentences in, CDM out; CDM out to AIVDM sentences.

Adapter #3, and the second bidirectional one. It implements the AIS table in
FORMAT_COVERAGE.md row by row; that table is this module's specification, and a test resolves
every CDM path in it against the models so the two cannot drift.

WHAT EACH DIRECTION IS
----------------------
INGEST  one AIS *message* — delivered as one or more `!AIVDM`/`!AIVDO` sentences — becomes an
        Entity + an Event. The same "one payload, two objects" split as the other adapters: a
        message describes a thing that EXISTS (a vessel, at a place, with a name and a hull)
        and a thing that HAPPENED (that state was broadcast at an instant).

EGRESS  one Entity, or one Track, becomes the sentences that restate it. An Entity emits the
        message type it arrived as; a Track emits one position report per sample, in the
        track's own order, which is the only shape AIS has for a history.

MESSAGE TYPES IN SCOPE
----------------------
1, 2, 3 (Class A position report) · 4 (base station report) · 5 (static and voyage data) ·
18, 19 (Class B position, and Class B extended) · 21 (aid to navigation). Everything else is
named in FORMAT_COVERAGE.md with the reason it is out, because "unsupported" without a reason
is indistinguishable from "nobody thought about it" — and one of those reasons is structural
rather than effort: see the type 24 note, which is the same purity argument that keeps this
adapter from holding a fragment-reassembly buffer across payloads.

THE SENTINELS, WHICH ARE THE WHOLE POINT
-----------------------------------------
AIS spells "not available" as an in-band value in a field that otherwise carries a real
measurement, and every one of them is a plausible-looking number:

    latitude 91         a coordinate 1 degree past the pole
    longitude 181       half a degree past the antimeridian
    speed 102.3 kn      the number the CDM's own docstrings are named after
    course 360.0 deg    a bearing the CDM's [0, 360) range cannot even hold
    heading 511         nine bits, all set
    rate of turn -128   the eight-bit two's-complement floor
    draught 0.0 m       *the dangerous one* — the only sentinel that is also a plausible
                        reading, so a forwarder that nulls the other six can still state
                        that a laden tanker draws nothing
    UTC second 60-63    not a second at all: not available, manual input, dead reckoning,
                        positioning system inoperative
    IMO / ETA / dims 0  not available on each, so an absent dimension is absent and never 0 m

Every one of them becomes an ABSENT CDM field, never a value, and every one is declared in
TRANSFORMS so the exemption is a printed line in each harness report. Which fields the SOURCE
marked unavailable is itself recorded, at `attributes.unavailable_fields`: "the vessel said it
does not know its heading" and "this adapter had nothing to say" are different facts, and only
one of them is in the data.

Note the direction that is NOT a sentinel, the mirror of the CoT adapter's 0/0 rule: latitude
0 longitude 0 is a real position in the Gulf of Guinea and is translated as one. And note the
value next to a sentinel that is real: speed 102.2 means "102.2 knots or higher", a floored
measurement rather than an absence, so it is kept and the floor is recorded.

WHY THE POSITION-ACCURACY FLAG IS NOT `Position.accuracy_m`
------------------------------------------------------------
AIS states position accuracy as ONE BIT: high (DGNSS-corrected, better than 10 m) or low.
`Position.accuracy_m` is a 1-sigma figure in metres. Writing `10.0` into it would state an
error the source never measured — a threshold is not a measurement — so the flag is parked at
`attributes.position_accuracy_high` and `accuracy_m` stays None, which means unknown.

WHERE THE TIME COMES FROM
-------------------------
AIS is the awkward case the CDM's `observed_at` was not written for: a position report states
a SECOND OF THE MINUTE and no date at all. Three answers, and this adapter uses all three
depending on what the message actually says:

1. Type 4 carries a full UTC date and time. It is used directly and nothing is reconciled.
2. Types 1/2/3/18/19/21 carry `utc_second`. The instant is the one bearing that second
   NEAREST the reception time — exact arithmetic, given that an AIS message is VHF
   line-of-sight and arrives in the same minute it was sent. `payload.observed_at_basis`
   names both halves, and the raw second (60-63 included, which are not seconds) is kept at
   `attributes.utc_second_raw`.
3. Type 5 carries no time whatsoever. `observed_at` is the reception instant and the basis
   says exactly that, rather than implying the vessel stated it.

The reception instant is itself read rather than assumed where the feed provides one: an
NMEA 0183 v4.10 TAG block (`\\s:RX,c:1777444260*hh\\`) carries the receiver's own timestamp.
Absent a TAG block it is `self.now()` — the injected clock, never `datetime.now()`.

EGRESS INTO A FORMAT WITH NO EXTENSION POINT
---------------------------------------------
The CoT adapter can graft what it could not map onto a `<synapse_plan/>` element, because
CoT's `<detail>` is an open bag by design. **AIS has no such thing.** The bit layout of each
message type is fixed and fully allocated; there is no spare field, no vendor block, and a bit
this adapter invented would be read by a receiver as the field the standard says lives there.

So egress here is lossy for CDM-native facts by construction, and that is a property of AIS
rather than of this adapter. `entity_id`, `track_id`, `track_quality`, `schema_version` and
the whole provenance block have nowhere to go. The round-trip test therefore excludes them BY
NAME with a reason attached to each, rather than measuring a loss it cannot fix — and every
field that AIS CAN carry is measured, including the ones inside the armoured payload, which
the test unpacks rather than exempts.

What egress is NOT lossy for is a message this adapter ingested: the parked fields are read
back, so `to_cdm()` then `from_cdm()` reproduces the original sentences byte for byte. That is
asserted, not hoped for, and it is the strongest statement available about a translation.
"""
from __future__ import annotations

import datetime as _dt
import json
from typing import Any, Sequence

from synapse_cdm import ids, lossless, times
from synapse_cdm.adapter import Adapter
from synapse_cdm.enums import (
    Affiliation,
    EntityType,
    EventType,
    PositionSource,
    Severity,
)
from synapse_cdm.models import CDMBase, Entity, Event, Kinematics, Position, Track
from synapse_cdm.symbology import sidc_from_affiliation

SYSTEM = "AIS"

#: The IMO number is a SECOND source id, not a replacement for the MMSI. An MMSI changes with
#: the flag; an IMO number is fixed for the life of the hull. Both belong, under their own
#: system names, and fusion is what joins a report carrying one to a report carrying the other.
IMO_SYSTEM = "IMO"

# ------------------------------------------------------------------ the sentinels
#
# Compared for EQUALITY, never with a threshold: a threshold would be this adapter deciding
# that some large-but-real value is unknown, which is a judgement. Each of these is the
# documented value.
LAT_UNAVAILABLE = 91.0
LON_UNAVAILABLE = 181.0
SOG_UNAVAILABLE = 102.3
SOG_AT_OR_ABOVE_MAXIMUM = 102.2
COG_UNAVAILABLE = 360.0
HEADING_UNAVAILABLE = 511
ROT_UNAVAILABLE = -128
ROT_MAGNITUDE_FLOOR = 127

#: `utc_second` beyond 59 is not a second. These are the source telling us how it got the fix,
#: which is why they land on `position_source` and not only in `attributes`.
SECOND_NOT_AVAILABLE = 60
SECOND_MANUAL = 61
SECOND_DEAD_RECKONING = 62
SECOND_INOPERATIVE = 63

#: Sentinels that are zero. Separated from the list above because they are the ones a
#: forwarder gets wrong: nothing about the number 0 looks like an absence.
ZERO_MEANS_UNAVAILABLE = ("imo_number", "ship_type", "draught_m", "aid_type",
                          "dim_to_bow", "dim_to_stern", "dim_to_port", "dim_to_starboard",
                          "eta_month", "eta_day")

# --------------------------------------------------------------- world vocabularies

#: Navigational status, from the standard's own wording. The CODE is what travels; the text is
#: a convenience for a human reading `attributes`, and both are parked because a consumer that
#: only got the text would have to parse English to get back to the field.
NAVIGATIONAL_STATUS: dict[int, str] = {
    0: "under way using engine",
    1: "at anchor",
    2: "not under command",
    3: "restricted manoeuvrability",
    4: "constrained by her draught",
    5: "moored",
    6: "aground",
    7: "engaged in fishing",
    8: "under way sailing",
    9: "reserved (high speed craft)",
    10: "reserved (wing in ground craft)",
    11: "power-driven vessel towing astern",
    12: "power-driven vessel pushing ahead or towing alongside",
    13: "reserved",
    14: "AIS-SART, MOB or EPIRB active",
    15: "undefined",
}

#: The ONE navigational status the standard itself defines as an active distress transmission.
#: The severity line is drawn here and nowhere else on purpose: grading "aground" or "not under
#: command" as a warning would be this translator judging operational significance, which
#: belongs to fusion where it is visible and attributable. See adapter.py on what an adapter
#: may not do.
STATUS_DISTRESS = 14

#: Electronic position fixing device -> how much the fix may be trusted.
#:
#: Two mappings are worth defending. EPFD 6, "integrated navigation system", becomes ESTIMATED
#: and NOT inertial: an integrated system's fix may well be GNSS-derived, and `position_source`
#: is the field a commander uses to decide what still holds under jamming — so calling it
#: INERTIAL would promise survival this adapter cannot know about, which is the dangerous
#: direction. EPFD 7, "surveyed", becomes MANUAL, which is exactly what a charted position is.
#: Loran-C and Chayka are real fixes from a terrestrial system the CDM has no member for;
#: ESTIMATED understates them, which is the safe direction.
EPFD: dict[int, PositionSource] = {
    1: PositionSource.GNSS,        # GPS
    2: PositionSource.GNSS,        # GLONASS
    3: PositionSource.GNSS,        # combined GPS/GLONASS
    4: PositionSource.ESTIMATED,   # Loran-C
    5: PositionSource.ESTIMATED,   # Chayka
    6: PositionSource.ESTIMATED,   # integrated navigation system — see the docstring
    7: PositionSource.MANUAL,      # surveyed
    8: PositionSource.GNSS,        # Galileo
    15: PositionSource.GNSS,       # internal GNSS
}
EPFD_TEXT: dict[int, str] = {
    0: "undefined", 1: "GPS", 2: "GLONASS", 3: "combined GPS/GLONASS", 4: "Loran-C",
    5: "Chayka", 6: "integrated navigation system", 7: "surveyed", 8: "Galileo",
    15: "internal GNSS",
}

#: `utc_second` values that are a statement about the positioning system rather than a time.
SECOND_POSITION_SOURCE: dict[int, PositionSource] = {
    SECOND_MANUAL: PositionSource.MANUAL,
    SECOND_DEAD_RECKONING: PositionSource.ESTIMATED,
    SECOND_INOPERATIVE: PositionSource.ESTIMATED,
}
SECOND_TEXT: dict[int, str] = {
    SECOND_NOT_AVAILABLE: "time stamp not available",
    SECOND_MANUAL: "positioning system in manual input mode",
    SECOND_DEAD_RECKONING: "positioning system in dead-reckoning mode",
    SECOND_INOPERATIVE: "positioning system inoperative",
}

#: Ship type, by the standard's decade groups. Deliberately NOT mapped to `entity_type`: a
#: tanker, a tug and a pleasure craft are all PLATFORM, and inventing a finer CDM distinction
#: from this byte would be the translator making a judgement. The wording is parked so a
#: consumer that wants it has it without a table of its own.
SHIP_TYPE_GROUP: dict[int, str] = {
    2: "wing in ground craft",
    3: "special craft",
    4: "high speed craft",
    5: "special craft",
    6: "passenger",
    7: "cargo",
    8: "tanker",
    9: "other type",
}
SHIP_TYPE_SPECIFIC: dict[int, str] = {
    30: "fishing", 31: "towing", 32: "towing, length over 200 m or breadth over 25 m",
    33: "dredging or underwater operations", 34: "diving operations",
    35: "military operations", 36: "sailing", 37: "pleasure craft",
    50: "pilot vessel", 51: "search and rescue vessel", 52: "tug", 53: "port tender",
    54: "anti-pollution equipment", 55: "law enforcement", 56: "spare — local",
    57: "spare — local", 58: "medical transport",
    59: "noncombatant ship per Resolution No. 18",
}

AID_TYPE: dict[int, str] = {
    0: "not specified", 1: "reference point", 2: "RACON", 3: "fixed offshore structure",
    4: "spare", 5: "light without sectors", 6: "light with sectors",
    7: "leading light front", 8: "leading light rear", 9: "beacon, cardinal N",
    10: "beacon, cardinal E", 11: "beacon, cardinal S", 12: "beacon, cardinal W",
    13: "beacon, port hand", 14: "beacon, starboard hand", 15: "beacon, preferred channel port",
    16: "beacon, preferred channel starboard", 17: "beacon, isolated danger",
    18: "beacon, safe water", 19: "beacon, special mark", 20: "cardinal mark N",
    21: "cardinal mark E", 22: "cardinal mark S", 23: "cardinal mark W",
    24: "port hand mark", 25: "starboard hand mark", 26: "preferred channel port hand",
    27: "preferred channel starboard hand", 28: "isolated danger", 29: "safe water",
    30: "special mark", 31: "light vessel, LANBY or rig",
}

#: MMSI prefixes, from the ITU numbering plan. This is the standard's own structure and not a
#: country table: the MID digits are recorded, the country they belong to is NOT looked up.
#: Longest prefix first, because "970" and "99" would otherwise both match a SART.
MMSI_PREFIXES: tuple[tuple[str, str, slice | None], ...] = (
    ("111", "SAR aircraft", slice(3, 6)),
    ("970", "AIS-SART (search and rescue transmitter)", None),
    ("972", "man-overboard device", None),
    ("974", "EPIRB-AIS", None),
    ("00", "coast station", slice(2, 5)),
    ("99", "aid to navigation", slice(2, 5)),
    ("98", "craft associated with a parent ship", slice(2, 5)),
    ("0", "group of ships", slice(1, 4)),
)
MMSI_SHIP_STATION = "ship station"

#: MMSI categories whose station is a fixed installation whatever message type it sends. A
#: buoy transmitting a position report is still a buoy, so this overrides the message type.
MMSI_FACILITY_CATEGORIES = ("coast station", "aid to navigation")

#: Message type -> what kind of thing the CDM says it is, before the MMSI and the virtual-aid
#: flag refine it.
MESSAGE_ENTITY_TYPE: dict[int, EntityType] = {
    1: EntityType.PLATFORM, 2: EntityType.PLATFORM, 3: EntityType.PLATFORM,
    4: EntityType.FACILITY,
    5: EntityType.PLATFORM,
    18: EntityType.PLATFORM, 19: EntityType.PLATFORM,
    21: EntityType.FACILITY,
}

POSITION_REPORTS = (1, 2, 3, 18, 19, 21, 4)
CLASS_A_POSITION_REPORTS = (1, 2, 3)

# ------------------------------------------------------------------- bit layouts
#
# (name, width, kind), in wire order. kind: u unsigned · i signed two's complement ·
# m MMSI (unsigned, rendered as a nine-digit string so a leading zero survives) · t six-bit
# text · b one-bit flag. A width of None means "whatever is left, in whole characters", which
# only the type 21 name extension uses.
#
# Spare and reserved bits are LISTED rather than skipped. They carry no meaning today and are
# the bits a regional authority allocates tomorrow; decoding them is what makes the encoder an
# exact inverse, and an exact inverse is what makes the round-trip claim checkable.
_COMMON = (("type", 6, "u"), ("repeat_indicator", 2, "u"), ("mmsi", 30, "m"))

LAYOUTS: dict[int, tuple[tuple[str, int | None, str], ...]] = {}
for _t in (1, 2, 3):
    LAYOUTS[_t] = _COMMON + (
        ("navigational_status", 4, "u"), ("rate_of_turn_raw", 8, "i"),
        ("sog_tenths", 10, "u"), ("position_accuracy", 1, "b"),
        ("lon_min4", 28, "i"), ("lat_min4", 27, "i"),
        ("cog_tenths", 12, "u"), ("true_heading_raw", 9, "u"), ("utc_second", 6, "u"),
        ("manoeuvre_indicator", 2, "u"), ("spare", 3, "u"), ("raim", 1, "b"),
        ("radio_status", 19, "u"),
    )
LAYOUTS[4] = _COMMON + (
    ("utc_year", 14, "u"), ("utc_month", 4, "u"), ("utc_day", 5, "u"),
    ("utc_hour", 5, "u"), ("utc_minute", 6, "u"), ("utc_second", 6, "u"),
    ("position_accuracy", 1, "b"), ("lon_min4", 28, "i"), ("lat_min4", 27, "i"),
    ("epfd", 4, "u"), ("spare", 10, "u"), ("raim", 1, "b"), ("radio_status", 19, "u"),
)
LAYOUTS[5] = _COMMON + (
    ("ais_version", 2, "u"), ("imo_number", 30, "u"), ("call_sign", 42, "t"),
    ("vessel_name", 120, "t"), ("ship_type", 8, "u"),
    ("dim_to_bow", 9, "u"), ("dim_to_stern", 9, "u"),
    ("dim_to_port", 6, "u"), ("dim_to_starboard", 6, "u"), ("epfd", 4, "u"),
    ("eta_month", 4, "u"), ("eta_day", 5, "u"), ("eta_hour", 5, "u"),
    ("eta_minute", 6, "u"), ("draught_tenths", 8, "u"), ("destination", 120, "t"),
    ("dte", 1, "b"), ("spare", 1, "u"),
)
LAYOUTS[18] = _COMMON + (
    ("reserved_regional_1", 8, "u"), ("sog_tenths", 10, "u"),
    ("position_accuracy", 1, "b"), ("lon_min4", 28, "i"), ("lat_min4", 27, "i"),
    ("cog_tenths", 12, "u"), ("true_heading_raw", 9, "u"), ("utc_second", 6, "u"),
    ("reserved_regional_2", 2, "u"), ("cs_unit", 1, "b"), ("display_flag", 1, "b"),
    ("dsc_flag", 1, "b"), ("band_flag", 1, "b"), ("message_22_flag", 1, "b"),
    ("assigned_mode", 1, "b"), ("raim", 1, "b"), ("radio_status", 20, "u"),
)
LAYOUTS[19] = _COMMON + (
    ("reserved_regional_1", 8, "u"), ("sog_tenths", 10, "u"),
    ("position_accuracy", 1, "b"), ("lon_min4", 28, "i"), ("lat_min4", 27, "i"),
    ("cog_tenths", 12, "u"), ("true_heading_raw", 9, "u"), ("utc_second", 6, "u"),
    ("reserved_regional_2", 4, "u"), ("vessel_name", 120, "t"), ("ship_type", 8, "u"),
    ("dim_to_bow", 9, "u"), ("dim_to_stern", 9, "u"),
    ("dim_to_port", 6, "u"), ("dim_to_starboard", 6, "u"), ("epfd", 4, "u"),
    ("raim", 1, "b"), ("dte", 1, "b"), ("assigned_mode", 1, "b"), ("spare", 4, "u"),
)
LAYOUTS[21] = _COMMON + (
    ("aid_type", 5, "u"), ("name", 120, "t"), ("position_accuracy", 1, "b"),
    ("lon_min4", 28, "i"), ("lat_min4", 27, "i"),
    ("dim_to_bow", 9, "u"), ("dim_to_stern", 9, "u"),
    ("dim_to_port", 6, "u"), ("dim_to_starboard", 6, "u"), ("epfd", 4, "u"),
    ("utc_second", 6, "u"), ("off_position", 1, "b"), ("regional_reserved", 8, "u"),
    ("raim", 1, "b"), ("virtual_aid", 1, "b"), ("assigned_mode", 1, "b"),
    ("spare", 1, "u"), ("name_extension", None, "t"),
)

#: Fields whose wire units are not the units the parsed form reports. Applied on the way out of
#: the decoder and inverted on the way into the encoder, so `parsed` reads in the units the
#: standard talks in — knots, degrees, metres — rather than in tenths of things.
SCALED: dict[str, tuple[str, float, int]] = {
    # wire field      parsed field        divisor   decimals
    "lat_min4":       ("lat",             600000.0, 7),
    "lon_min4":       ("lon",             600000.0, 7),
    "sog_tenths":     ("sog_knots",       10.0,     1),
    "cog_tenths":     ("cog_deg",         10.0,     1),
    "draught_tenths": ("draught_m",       10.0,     1),
    "true_heading_raw": ("true_heading_deg", 1.0,   0),
}

#: The maximum payload characters this adapter puts in one sentence. NMEA 0183 caps a sentence
#: at 82 characters including the `!`, the CRLF and the checksum, and the AIVDM envelope costs
#: about 20 of them. 62 leaves room for a TAG block on the same line.
MAX_PAYLOAD_CHARS = 62

#: NMEA sentences are terminated by CR LF, not LF. Spelled out because a golden file written
#: with the wrong one is a difference no reader would see and every strict parser would.
SENTENCE_TERMINATOR = "\r\n"


# ============================================================== the codec: sentences


def _checksum(body: str) -> str:
    """NMEA 0183 checksum: XOR of every character between the delimiters, two hex digits.

    Upper case, because that is what the standard prints and what a byte comparison against a
    recorded sentence expects.
    """
    value = 0
    for character in body:
        value ^= ord(character)
    return f"{value:02X}"


def _parse_tag_block(line: str) -> tuple[dict[str, Any], str]:
    """Split an NMEA 0183 v4.10 TAG block off the front of a line.

    A TAG block is `\\<parameters>*<checksum>\\` before the sentence, and `c:` in it is the
    receiver's own delivery timestamp — the only trustworthy statement of WHEN in a format
    whose messages carry a second of the minute and no date. Its checksum is verified for the
    same reason the sentence's is: a corrupted timestamp is worse than an absent one, because
    an absent one falls back to the clock and says so.
    """
    if not line.startswith("\\"):
        return {}, line
    end = line.find("\\", 1)
    if end == -1:
        raise ValueError(
            "NMEA TAG block is opened with a backslash and never closed — refusing to guess "
            f"where the sentence starts in {line[:40]!r}"
        )
    block, rest = line[1:end], line[end + 1:]
    body, _, stated = block.partition("*")
    if stated and _checksum(body) != stated.upper():
        raise ValueError(
            f"NMEA TAG block checksum is {stated.upper()!r} but the body computes to "
            f"{_checksum(body)!r} — a corrupted receipt timestamp is worse than none, because "
            "an absent one falls back to the injected clock and records that it did"
        )
    tag: dict[str, Any] = {}
    for parameter in body.split(","):
        key, _, value = parameter.partition(":")
        if not key:
            continue
        # `c` is seconds, or milliseconds when the feed emits 13 digits. Both are in the wild
        # and the difference is 44 years, so it is read from the magnitude rather than assumed.
        tag[key] = int(value) if key == "c" and value.isdigit() else value
    return tag, rest


def _parse_sentence(line: str) -> dict[str, Any]:
    """One `!AIVDM`/`!AIVDO` line into its envelope fields, checksum verified."""
    tag, rest = _parse_tag_block(line.strip())
    if not rest.startswith("!"):
        raise ValueError(
            f"AIS payload line does not start with '!': {rest[:40]!r}. An AIVDM sentence is "
            "an encapsulation sentence and the '!' is what says so"
        )
    body, star, stated = rest[1:].partition("*")
    if not star:
        raise ValueError(f"AIS sentence carries no '*' checksum delimiter: {rest[:60]!r}")
    computed = _checksum(body)
    if computed != stated.strip().upper():
        raise ValueError(
            f"AIS sentence checksum is {stated.strip().upper()!r} but the body computes to "
            f"{computed!r} — refusing to decode a sentence that arrived corrupted; a bit flip "
            "in the payload moves a vessel rather than failing to parse"
        )
    fields = body.split(",")
    if len(fields) != 7:
        raise ValueError(
            f"AIS sentence has {len(fields)} comma-separated fields, expected 7 "
            f"(formatter, fragment count, fragment number, sequential id, channel, payload, "
            f"fill bits): {rest[:60]!r}"
        )
    formatter, count, number, sequential, channel, payload, fill = fields
    if formatter[2:] not in ("VDM", "VDO"):
        raise ValueError(
            f"sentence formatter {formatter!r} is not VDM or VDO — this adapter translates AIS "
            "VHF data-link messages, and another formatter is another format"
        )
    sentence: dict[str, Any] = {
        "talker": formatter,
        "fragment_count": int(count),
        "fragment_number": int(number),
        "sequential_id": sequential,
        "channel": channel,
        "payload": payload,
        "fill_bits": int(fill),
        "checksum": computed,
    }
    if tag:
        sentence["tag"] = tag
    return sentence


def _bits_of(payload: str, fill_bits: int) -> str:
    """The armoured payload as a bit string, with the trailing fill bits removed.

    Six-bit ASCII: subtract 48, and subtract a further 8 above 40. The gap exists because the
    printable ASCII range it maps into is not contiguous, and getting it wrong shifts every
    field after the first character rather than failing.
    """
    bits = []
    for character in payload:
        value = ord(character) - 48
        if value > 40:
            value -= 8
        if not 0 <= value <= 63:
            raise ValueError(
                f"character {character!r} is not in the AIS six-bit armour alphabet — the "
                "payload is corrupted or is not an AIS payload"
            )
        bits.append(f"{value:06b}")
    joined = "".join(bits)
    if fill_bits:
        joined = joined[:-fill_bits]
    return joined


def _armour(bits: str) -> tuple[str, int]:
    """The inverse: a bit string as armoured characters plus the number of fill bits added."""
    fill = (-len(bits)) % 6
    padded = bits + "0" * fill
    out = []
    for index in range(0, len(padded), 6):
        value = int(padded[index:index + 6], 2)
        out.append(chr(value + 56 if value > 39 else value + 48))
    return "".join(out), fill


# ================================================================ the codec: fields


def _text_of(bits: str) -> str:
    """Six-bit text: values 0-31 are '@'..'_', 32-63 are ' '..'?'.

    Trailing '@' — the standard's own pad character — is stripped, and so are trailing spaces,
    which real encoders use instead. That normalisation is one-way: re-encoding pads with '@',
    so a space-padded source comes back '@'-padded. Same string, same field, different bits,
    and it is declared rather than left for a byte comparison to discover.
    """
    out = []
    for index in range(0, len(bits) - 5, 6):
        value = int(bits[index:index + 6], 2)
        out.append(chr(value + 64) if value < 32 else chr(value))
    return "".join(out).rstrip("@").rstrip()


def _text_bits(text: str, width: int, *, field: str) -> str:
    """A string as six-bit text of exactly `width` bits, '@'-padded.

    Refuses rather than truncating or substituting. AIS's alphabet has no lower case and no
    accented characters, and a vessel name silently corrupted on the wire is the failure that
    looks like success — the same reason the CoT adapter refuses a drawing with no vertices
    instead of emitting an empty one.
    """
    characters = width // 6
    upper = text.upper()
    if len(upper) > characters:
        raise ValueError(
            f"{field} is {len(upper)} characters and the AIS field holds {characters} "
            f"({text!r}) — refusing to truncate: a name cut short on the wire reads as the "
            "vessel's real name to every receiver"
        )
    bits = []
    for character in upper.ljust(characters, "@"):
        code = ord(character)
        if 64 <= code <= 95:
            value = code - 64
        elif 32 <= code <= 63:
            value = code
        else:
            raise ValueError(
                f"{field} contains {character!r}, which the AIS six-bit alphabet cannot carry "
                f"({text!r}) — refusing to substitute a placeholder, which would misstate the "
                "value rather than fail"
            )
        bits.append(f"{value:06b}")
    return "".join(bits)


def _signed(bits: str) -> int:
    value = int(bits, 2)
    return value - (1 << len(bits)) if bits[0] == "1" else value


def _twos_complement_bits(value: int, width: int) -> str:
    return f"{value & ((1 << width) - 1):0{width}b}"


def decode(bits: str) -> dict[str, Any]:
    """An AIS message's bits into its named fields, in the units the standard talks in.

    Every bit is decoded, spares and radio state included, which is what lets `encode()` be an
    exact inverse. Sentinels are LEFT IN PLACE here: this function reports what the message
    says, and translating "not available" into an absent CDM field is the adapter's job, one
    layer up, where the decision can be declared in TRANSFORMS.
    """
    if len(bits) < 38:
        raise ValueError(
            f"AIS payload is {len(bits)} bits; the common header alone is 38 — refusing to "
            "decode a truncated message rather than reporting whatever the padding says"
        )
    message_type = int(bits[0:6], 2)
    layout = LAYOUTS.get(message_type)
    if layout is None:
        raise ValueError(
            f"AIS message type {message_type} is not in this adapter's scope. The types in "
            f"scope are {sorted(LAYOUTS)}; every other type is named in FORMAT_COVERAGE.md "
            "with the reason it is out, so this is a decision rather than an omission"
        )
    fields: dict[str, Any] = {}
    offset = 0
    for name, width, kind in layout:
        if width is None:
            # The variable tail. Whole characters only: a remainder of fewer than six bits is
            # armour padding, not content.
            remaining = ((len(bits) - offset) // 6) * 6
            if remaining <= 0:
                continue
            width = remaining
        chunk = bits[offset:offset + width]
        if len(chunk) < width:
            raise ValueError(
                f"AIS type {message_type} message is {len(bits)} bits, too short for field "
                f"{name!r} at offset {offset} (+{width}) — refusing to read past the end, "
                "which would report padding as a measurement"
            )
        offset += width
        if kind == "t":
            fields[name] = _text_of(chunk)
        elif kind == "b":
            fields[name] = chunk == "1"
        elif kind == "m":
            fields[name] = f"{int(chunk, 2):09d}"
        else:
            raw = _signed(chunk) if kind == "i" else int(chunk, 2)
            if name in SCALED:
                parsed_name, divisor, decimals = SCALED[name]
                scaled = raw / divisor
                fields[parsed_name] = round(scaled, decimals) if decimals else int(scaled)
            else:
                fields[name] = raw
    return fields


def encode(message: dict[str, Any]) -> str:
    """The exact inverse of `decode()`: named fields back to the message's bits.

    Exact, not approximate, and a test asserts it over every fixture. That property is what
    makes the round-trip claim measurable rather than reviewable: if re-encoding reproduces
    the original armoured payload character for character, no field was quietly rounded,
    reordered or dropped on the way through the CDM.
    """
    message_type = int(message["type"])
    layout = LAYOUTS.get(message_type)
    if layout is None:
        raise ValueError(f"cannot encode AIS message type {message_type}: not in scope")
    unscale = {parsed: (wire, divisor) for wire, (parsed, divisor, _) in SCALED.items()}
    bits = []
    for name, width, kind in layout:
        parsed_name, divisor = next(
            ((p, d) for p, (w, d) in unscale.items() if w == name), (name, None))
        value = message.get(parsed_name)
        if width is None:
            # The variable tail is present only when it carries something.
            if not value:
                continue
            width = 6 * len(str(value))
        if kind == "t":
            bits.append(_text_bits("" if value is None else str(value), width, field=name))
            continue
        if value is None:
            raise ValueError(
                f"cannot encode AIS type {message_type}: field {parsed_name!r} is missing. "
                "Every bit of an AIS message is allocated, so there is no way to omit one — "
                "the caller must supply the standard's not-available value instead"
            )
        if kind == "b":
            bits.append("1" if value else "0")
            continue
        number = round(float(value) * divisor) if divisor else int(value)
        if kind == "i":
            bits.append(_twos_complement_bits(int(number), width))
        else:
            bits.append(f"{int(number):0{width}b}")
    return "".join(bits)


def _parse_nmea(text: str | bytes) -> dict:
    """AIVDM/AIVDO sentences into `{sentences: [...], message: {...}}` — the parsed form.

    This is what a `.parsed.json` fixture holds, and what the never-drop check is measured
    against. Both forms of every fixture ship for the reason the CoT adapter's docstring gives:
    handed raw bytes the harness has no leaf structure to harvest, so `lossless` reports SKIP,
    and an adapter whose fixtures are all binary would show a green run with its most important
    check never executed.

    ONE message per payload, spanning as many sentences as it needs. A payload holding two
    distinct messages is refused rather than half-translated: framing a stream into messages is
    the feed reader's job, and an adapter that guessed at it would be holding state — the same
    argument that keeps AIS type 24 out of scope.
    """
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("ascii", errors="strict")
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        raise ValueError("AIS payload is empty — nothing to translate")
    sentences = [_parse_sentence(line) for line in lines]

    count = sentences[0]["fragment_count"]
    numbers = [s["fragment_number"] for s in sentences]
    if len(sentences) != count or numbers != list(range(1, count + 1)):
        raise ValueError(
            f"AIS payload holds {len(sentences)} sentence(s) numbered {numbers} but the first "
            f"declares a {count}-fragment message. This adapter translates exactly one whole "
            "message per payload: it keeps no reassembly buffer across payloads, because a "
            "buffer is state and state in a translator is fusion done where nothing audits it"
        )
    if len({s["fragment_count"] for s in sentences}) != 1 or \
            len({s["sequential_id"] for s in sentences}) != 1:
        raise ValueError(
            "AIS fragments disagree about their fragment count or sequential id — they are "
            "parts of different messages and reassembling them would invent a payload"
        )
    # Fill bits belong to the LAST fragment only; the earlier ones are whole by construction.
    bits = "".join(_bits_of(s["payload"], s["fill_bits"] if s is sentences[-1] else 0)
                   for s in sentences)
    return {"sentences": sentences, "message": decode(bits)}


def _render_sentences(message: dict[str, Any], envelope: dict[str, Any]) -> list[str]:
    """One message's fields as the sentences that carry it, checksums computed.

    Multi-fragment splitting is deterministic — MAX_PAYLOAD_CHARS per fragment, in order — so
    a message this adapter ingested comes back out with the same split it arrived with, and a
    golden file can be compared byte for byte.
    """
    payload, fill = _armour(encode(message))
    chunks = [payload[i:i + MAX_PAYLOAD_CHARS]
              for i in range(0, len(payload), MAX_PAYLOAD_CHARS)] or [""]
    talker = envelope.get("talker") or "AIVDM"
    channel = envelope.get("channel") or "A"
    sequential = envelope.get("sequential_id") or ("1" if len(chunks) > 1 else "")
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        # Fill bits are declared on the last fragment, where the padding actually is.
        body = (f"{talker},{len(chunks)},{index},{sequential},{channel},{chunk},"
                f"{fill if index == len(chunks) else 0}")
        lines.append(f"!{body}*{_checksum(body)}")
    return lines


# ====================================================================== translation

#: 1 knot in metres per second, exactly: a nautical mile is 1852 m by definition.
KNOT_MPS = 1852.0 / 3600.0

#: The standard's own "not available" value for every field this adapter can emit. Used to
#: build a message for a CDM object that never came from AIS: every bit of an AIS message is
#: allocated, so there is no way to omit a field — the only honest encoding of "we do not
#: know" is the value the format reserves for it, and 0 is that value for almost none of them.
NOT_AVAILABLE: dict[str, Any] = {
    "repeat_indicator": 0, "navigational_status": 15, "rate_of_turn_raw": ROT_UNAVAILABLE,
    "sog_knots": SOG_UNAVAILABLE, "position_accuracy": False,
    "lon": LON_UNAVAILABLE, "lat": LAT_UNAVAILABLE, "cog_deg": COG_UNAVAILABLE,
    "true_heading_deg": HEADING_UNAVAILABLE, "utc_second": SECOND_NOT_AVAILABLE,
    "manoeuvre_indicator": 0, "spare": 0, "raim": False, "radio_status": 0,
    "utc_year": 0, "utc_month": 0, "utc_day": 0, "utc_hour": 24, "utc_minute": 60,
    "epfd": 0, "ais_version": 0, "imo_number": 0, "call_sign": "", "vessel_name": "",
    "ship_type": 0, "dim_to_bow": 0, "dim_to_stern": 0, "dim_to_port": 0,
    "dim_to_starboard": 0, "eta_month": 0, "eta_day": 0, "eta_hour": 24, "eta_minute": 60,
    "draught_m": 0.0, "destination": "", "dte": True,
    "reserved_regional_1": 0, "reserved_regional_2": 0, "cs_unit": False,
    "display_flag": False, "dsc_flag": False, "band_flag": False, "message_22_flag": False,
    "assigned_mode": False, "aid_type": 0, "name": "", "off_position": False,
    "regional_reserved": 0, "virtual_aid": False, "name_extension": "",
}

#: (parsed field, the value that means "the source does not know"). Walked to build
#: `attributes.unavailable_fields`, so the distinction between "the vessel said it does not
#: know" and "this adapter had nothing to say" survives into the CDM.
UNAVAILABLE_WHEN: tuple[tuple[str, Any], ...] = (
    ("lat", LAT_UNAVAILABLE), ("lon", LON_UNAVAILABLE),
    ("sog_knots", SOG_UNAVAILABLE), ("cog_deg", COG_UNAVAILABLE),
    ("true_heading_deg", HEADING_UNAVAILABLE), ("rate_of_turn_raw", ROT_UNAVAILABLE),
    ("utc_second", SECOND_NOT_AVAILABLE), ("navigational_status", 15), ("epfd", 0),
    ("imo_number", 0), ("ship_type", 0), ("draught_m", 0.0),
    ("dim_to_bow", 0), ("dim_to_stern", 0), ("dim_to_port", 0), ("dim_to_starboard", 0),
    ("eta_month", 0), ("eta_day", 0), ("eta_hour", 24), ("eta_minute", 60),
    ("call_sign", ""), ("vessel_name", ""), ("destination", ""), ("name", ""),
)


class AisAdapter(Adapter):
    """AIVDM/AIVDO sentences in, CDM out; an Entity or a Track out to AIVDM sentences."""

    name = "ais"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    TRANSFORMS = {
        "message.lat": "AIS's 91 'not available' sentinel becomes an ABSENT position rather "
                       "than a latitude one degree past the pole; a real coordinate is "
                       "carried through unchanged, 0.0 included, so this only ever covers "
                       "the sentinel",
        "message.lon": "AIS's 181 sentinel becomes an absent position; a real longitude is "
                       "carried unchanged, 0.0 included",
        "message.sog_knots": "knots converted to metres per second (1 kn = 1852/3600 m/s) for "
                             "Kinematics.speed_mps — an exact, reversible unit change, which "
                             "is why it is declared rather than parked. The 102.3 sentinel "
                             "additionally becomes null; 102.2 means '102.2 knots or higher' "
                             "and IS kept, with the floor recorded at "
                             "attributes.sog_at_or_above_maximum",
        "message.cog_deg": "AIS's 360.0 sentinel becomes null — a value Kinematics.course_deg "
                           "could not hold in any case, its range being [0, 360)",
        "message.true_heading_deg": "the 511 sentinel becomes null; a real heading is parked "
                                    "verbatim at attributes.true_heading_deg (gap 7 — the CDM "
                                    "has no heading field distinct from course)",
        "message.draught_m": "AIS spells 'draught not available' as 0.0, the only sentinel "
                             "here that is also a plausible reading. It becomes null; a real "
                             "draught is parked verbatim at attributes.draught_m",
        "message.imo_number": "0 means 'no IMO number stated' and yields no IMO source id at "
                              "all, rather than a source id of zero; a real number becomes a "
                              "second SourceId under system IMO",
        "message.ship_type": "0 means 'not available' and becomes null rather than the "
                             "ship-type code zero; a real code is parked verbatim",
        "message.dim_to_bow": "0 means 'dimension not available' and becomes null, never a "
                              "bow that is 0 m from the position reference point",
        "message.dim_to_stern": "0 means 'dimension not available' and becomes null",
        "message.dim_to_port": "0 means 'dimension not available' and becomes null",
        "message.dim_to_starboard": "0 means 'dimension not available' and becomes null",
    }

    # Dotted paths in the PARSED form that this adapter maps to canonical fields. Everything
    # else is collected by lossless.residual() and parked with its structure intact, which is
    # also what lets egress rebuild the message — see _message_from_entity().
    #
    # Kept as data rather than buried in the translation so that "what does this adapter
    # understand?" is answerable by reading one list. Note what is absent on purpose: the
    # spare and reserved bits, the SOTDMA/ITDMA radio state, the Class B equipment flags, the
    # manoeuvre indicator, RAIM, DTE and the whole sentence envelope are NOT consumed, so they
    # park automatically. An unmapped field parked is the never-drop rule working rather than
    # a gap.
    CONSUMED = (
        "sentences[0].tag.c",
        "message.type",
        "message.mmsi",
        "message.repeat_indicator",
        "message.navigational_status",
        "message.rate_of_turn_raw",
        "message.sog_knots",
        "message.position_accuracy",
        "message.lon",
        "message.lat",
        "message.cog_deg",
        "message.true_heading_deg",
        "message.utc_second",
        "message.utc_year",
        "message.utc_month",
        "message.utc_day",
        "message.utc_hour",
        "message.utc_minute",
        "message.epfd",
        "message.imo_number",
        "message.call_sign",
        "message.vessel_name",
        "message.ship_type",
        "message.dim_to_bow",
        "message.dim_to_stern",
        "message.dim_to_port",
        "message.dim_to_starboard",
        "message.eta_month",
        "message.eta_day",
        "message.eta_hour",
        "message.eta_minute",
        "message.draught_m",
        "message.destination",
        "message.aid_type",
        "message.name",
        "message.name_extension",
        "message.virtual_aid",
        "message.off_position",
    )

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One AIS message -> [Entity, Event]. Raises on a payload it cannot read."""
        parsed = self._as_parsed(raw)
        message = parsed.get("message")
        if not isinstance(message, dict) or "type" not in message:
            raise ValueError(
                "AIS payload has no decoded message — refusing to translate; top-level keys: "
                f"{sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
            )
        sentences = parsed.get("sentences") or []
        message_type = int(message["type"])
        mmsi = str(message.get("mmsi") or "")
        if not mmsi:
            raise ValueError(
                f"AIS type {message_type} message carries no MMSI — refusing to translate. "
                "The MMSI is the only identifier AIS repeats across reports, so an object "
                "without one could never be recognised as the same station twice"
            )

        received_at, received_basis, received_unix = self._received_at(sentences)
        observed_at, observed_basis = _observed_at(message, received_at)
        category, mid = _mmsi_category(mmsi)
        source = self.source_ref()
        entity_id = ids.derive(SYSTEM, mmsi, kind="entity")
        # Keyed on BOTH the MMSI and the instant, for the reason the CoT adapter gives: an
        # MMSI identifies the STATION and repeats on every report, so an event id derived from
        # it alone would collapse a whole voyage into one event.
        event_id = ids.derive(SYSTEM, f"{mmsi}@{times.render(observed_at)}", kind="event")

        distress = message.get("navigational_status") == STATUS_DISTRESS
        attributes = _attributes(message, parsed, self.CONSUMED, category, mid,
                                 observed_basis=observed_basis)

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=_source_ids(mmsi, message),
            entity_type=_entity_type(message, category),
            # AIS states no identity. UNKNOWN is not a collapse here — it is the honest report
            # of a format that carries nothing to collapse. See attributes.affiliation_basis.
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=_position(message),
            kinematics=_kinematics(message),
            valid_from=observed_at,
            # AIS has no staleness field. How long a report stays good depends on the
            # reporting interval a navigational status implies, which is a judgement about
            # data and therefore fusion's to make, not a translator's.
            valid_to=None,
            confidence=None,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )

        event = Event(
            source=source,
            source_ids=_source_ids(mmsi, message),
            event_id=event_id,
            # A static-and-voyage broadcast is not a track update: it carries no position, and
            # saying TRACK_UPDATE would claim one. Navigational status 14 is the one value the
            # standard itself defines as an active distress transmission, so it — and only it
            # — becomes an ALERT.
            event_type=(EventType.ALERT if distress else
                        EventType.STATUS_CHANGE if message_type == 5 else
                        EventType.TRACK_UPDATE),
            severity=Severity.CRITICAL if distress else Severity.INFO,
            related_entities=[entity_id],
            # No geometry: AIS carries one position and it belongs to the station. Copying it
            # onto the event would be a second representation of one measurement.
            geometry=None,
            payload={
                "ais_message_type": message_type,
                "observed_at_basis": observed_basis,
                "received_at_basis": received_basis,
                "received_at_unix": received_unix,
                "event_id_basis": "message MMSI + observed_at",
                "severity_basis": (
                    f"navigational status {STATUS_DISTRESS} — the standard's own active "
                    "distress transmission" if distress else
                    "AIS states no urgency outside navigational status 14; INFO is the "
                    "format's silence, not an assessment that nothing is wrong"),
            },
            observed_at=observed_at,
            received_at=received_at,
        )
        return [entity, event]

    def _received_at(self, sentences: Sequence[dict]) -> tuple[_dt.datetime, str, int | None]:
        """When WE took delivery: the feed's own TAG-block stamp, or the injected clock.

        Read rather than assumed wherever the feed states it, because `observed_at` is
        reconciled against this instant — an AIS message gives a second of the minute and the
        minute has to come from somewhere. A clock that is two minutes out moves every
        position report into the wrong minute, silently and by exactly two minutes.
        """
        for sentence in sentences:
            stamp = (sentence.get("tag") or {}).get("c") if isinstance(sentence, dict) else None
            if isinstance(stamp, int):
                # Feeds emit seconds or milliseconds and both are in the wild; the difference
                # is 44 years, so it is read off the magnitude rather than configured.
                seconds = stamp / 1000.0 if stamp >= 10 ** 12 else float(stamp)
                return (_dt.datetime.fromtimestamp(seconds, tz=_dt.timezone.utc),
                        f"NMEA TAG block c:{stamp} — the receiver's own delivery timestamp",
                        stamp)
        return (self.now(),
                "no NMEA TAG block on any sentence; the injected clock is the delivery instant",
                None)

    # ------------------------------------------------------------------- egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """One Entity or one Track -> the AIVDM sentences that restate it, as UTF-8 bytes.

        Exactly one emittable object. An Entity emits the one message type it arrived as (or a
        Class A position report, for an Entity that never came from AIS); a Track emits one
        position report per sample, which is the only shape AIS has for a history.

        An `Event` in the list is not emittable on its own — AIS has no report object separate
        from the message — but it is not ignored either: its `observed_at` supplies the second
        of the minute, which is the only time field an AIS position report has.
        """
        emittable = [o for o in objects if isinstance(o, (Entity, Track))]
        if len(emittable) != 1:
            kinds = [getattr(o, "object_kind", type(o).__name__) for o in objects]
            raise ValueError(
                f"from_cdm() emits the sentences for ONE object and was given "
                f"{len(emittable)} emittable ones (kinds: {kinds or 'none'}). Push several "
                "objects as several transmissions — an AIS message addresses one station. An "
                "Event alone is not emittable: the AIS message is both the object and the "
                "report about it."
            )

        subject = emittable[0]
        if isinstance(subject, Track):
            lines = self._track_sentences(subject)
        else:
            lines = self._entity_sentences(subject, objects)
        return (SENTENCE_TERMINATOR.join(lines) + SENTENCE_TERMINATOR).encode("ascii")

    def _entity_sentences(self, entity: Entity, objects: list[CDMBase]) -> list[str]:
        attributes = dict(entity.attributes)
        extras = attributes.get("source_extras") or {}
        envelope = _first_sentence(extras)
        message = _message_from_entity(entity, _observed_at_for(entity, objects))
        return _render_sentences(message, envelope)

    def _track_sentences(self, track: Track) -> list[str]:
        """A Track as one Class A position report per sample, in the track's own order.

        Type 1 is not a guess about the transponder: a Track carries no statement of what the
        station was, and 1 is the only position report every AIS receiver decodes. What a
        Track's samples CANNOT carry is why this direction is honest about its limits — see
        the module docstring on AIS having no extension point. Each sample states a second of
        the minute and nothing more, so the date, the speed and the course are transmitted as
        the standard's not-available values rather than as zeros.
        """
        mmsi = _mmsi_of(track)
        lines = []
        for sample in track.samples:
            message = dict(NOT_AVAILABLE)
            message.update({
                "type": 1, "mmsi": mmsi,
                "lat": sample.position.lat, "lon": sample.position.lon,
                "utc_second": sample.observed_at.second,
                "position_accuracy": False,
            })
            lines += _render_sentences(message, {})
        return lines

    # ------------------------------------------------------------------ helpers

    def _as_parsed(self, raw: bytes | dict) -> dict:
        """NMEA text -> the parsed dict form; a dict passes straight through."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, str)):
            text = raw.decode("ascii") if isinstance(raw, (bytes, bytearray)) else raw
            if text.lstrip().startswith("{"):
                # A .json fixture handed over as bytes. Distinguished by inspection rather than
                # by suffix, because the harness does not tell an adapter what it opened.
                return json.loads(text)
            return _parse_nmea(text)
        raise TypeError(
            f"AIS adapter takes NMEA sentences as bytes or str, a JSON string, or a parsed "
            f"dict, got {type(raw).__name__}"
        )


# ---------------------------------------------------------------- ingest helpers


def _mmsi_category(mmsi: str) -> tuple[str, str | None]:
    """What KIND of station this MMSI belongs to, and its MID digits.

    Read from the ITU numbering plan's own prefixes — this is structure the standard defines,
    not a lookup. The MID digits are recorded and the country they are allocated to is
    deliberately NOT looked up: a flag of registration is not an affiliation, and a table
    mapping one to the other inside a translator is exactly the enrichment adapters may not
    do. Longest prefix first, or "970" would be read as an aid to navigation.
    """
    for prefix, category, mid_slice in MMSI_PREFIXES:
        if mmsi.startswith(prefix):
            return category, (mmsi[mid_slice] if mid_slice else None)
    return MMSI_SHIP_STATION, mmsi[:3]


def _entity_type(message: dict, category: str) -> EntityType:
    """What the CDM says this station IS.

    Three inputs in precedence order. A virtual aid to navigation is an OVERLAY_OBJECT and not
    a FACILITY: nothing physical floats there, and painting a chart symbol as a structure is a
    false statement about the sea. An MMSI in the coast-station or aid-to-navigation range is
    a fixed installation whatever message type it happens to send — a buoy transmitting a
    position report is still a buoy. Otherwise the message type decides.
    """
    if int(message.get("type", 0)) == 21 and message.get("virtual_aid"):
        return EntityType.OVERLAY_OBJECT
    if category in MMSI_FACILITY_CATEGORIES:
        return EntityType.FACILITY
    return MESSAGE_ENTITY_TYPE.get(int(message.get("type", 0)), EntityType.UNKNOWN)


def _position_source(message: dict) -> tuple[PositionSource, str]:
    """How the fix was obtained, and the sentence that says how we concluded that.

    AIS states this in two different places depending on the message type, and on a Class A
    position report it states it in a field that is otherwise a clock: `utc_second` values
    61-63 mean manual input, dead reckoning and positioning-system-inoperative. Those are read
    FIRST, because they are the source explicitly telling us the fix is not a GNSS fix, and
    they appear on exactly the messages that carry no EPFD field.

    Where neither is available the answer is ESTIMATED, which understates. That is the safe
    direction: `position_source` is what a commander uses to tell a fix from a guess in a
    GNSS-denied environment, and a guess promoted to a fix is the error that gets acted on.
    """
    second = message.get("utc_second")
    if isinstance(second, int) and second in SECOND_POSITION_SOURCE:
        return (SECOND_POSITION_SOURCE[second],
                f"utc_second {second} — {SECOND_TEXT[second]}")
    epfd = message.get("epfd")
    if isinstance(epfd, int) and epfd:
        return (EPFD.get(epfd, PositionSource.ESTIMATED),
                f"EPFD {epfd} — {EPFD_TEXT.get(epfd, 'unrecognised code')}")
    if isinstance(second, int) and second <= 59:
        return (PositionSource.GNSS,
                f"utc_second {second} is a real UTC second, which only a positioning system "
                "synchronised to UTC supplies; this message type states no EPFD")
    return (PositionSource.ESTIMATED,
            "no EPFD and no usable UTC second — ESTIMATED understates rather than overstates "
            "the fix, which is the safe direction for this field")


def _position(message: dict) -> Position | None:
    """A Position only when AIS actually stated one.

    The check is for the SENTINELS and for absence, never for falsiness: `if not lat` would
    discard a real position on the equator, and AIS feeds carry the Gulf of Guinea like any
    other water. 0/0 is a real coordinate here — the same rule the CoT adapter states.
    """
    lat, lon = message.get("lat"), message.get("lon")
    if lat is None or lon is None:
        return None
    if lat == LAT_UNAVAILABLE or lon == LON_UNAVAILABLE:
        return None
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(
            f"AIS position {lat}/{lon} is outside the valid range and is not one of the "
            f"documented sentinels ({LAT_UNAVAILABLE}/{LON_UNAVAILABLE}) — refusing to place "
            "a contact at a coordinate that cannot exist"
        )
    source, _ = _position_source(message)
    return Position(
        lat=lat, lon=lon,
        # AIS position reports carry no altitude; a vessel is at sea level by construction and
        # inventing 0.0 would be a measurement nobody made.
        alt_m=None,
        position_source=source,
        # NOT the position-accuracy flag: that bit states a THRESHOLD (better or worse than
        # 10 m) and this field is a 1-sigma figure in metres. Writing 10.0 here would state an
        # error the source never measured. The flag is parked instead.
        accuracy_m=None,
    )


def _kinematics(message: dict) -> Kinematics | None:
    """Motion, or None when AIS stated none. Absent is unknown, never zero."""
    sog = message.get("sog_knots")
    cog = message.get("cog_deg")
    speed = None if sog is None or sog == SOG_UNAVAILABLE else round(sog * KNOT_MPS, 4)
    # >= rather than ==: 360.0 is the sentinel and anything above it is out of range on a
    # field whose whole domain is a bearing. Either way the honest answer is "not stated".
    course = None if cog is None or cog >= COG_UNAVAILABLE else cog
    if speed is None and course is None:
        return None
    return Kinematics(speed_mps=speed, course_deg=course)


def _reconcile_second(second: int, reference: _dt.datetime) -> _dt.datetime:
    """The instant bearing `second` nearest `reference` — how AIS time actually works.

    A position report states a second of the minute and no date. The minute, hour and date can
    only come from the receiver, and the arithmetic is exact given one physical fact: AIS is
    VHF line-of-sight, so a message is delivered in the same minute it was transmitted or the
    one on either side of it. Picking the nearest of those three is therefore a derivation and
    not a guess — and `payload.observed_at_basis` names both halves so a consumer can see
    which clock contributed what.
    """
    base = reference.replace(second=0, microsecond=0)
    candidates = [base + _dt.timedelta(minutes=offset, seconds=second)
                  for offset in (-1, 0, 1)]
    return min(candidates, key=lambda c: abs((c - reference).total_seconds()))


def _observed_at(message: dict, reference: _dt.datetime) -> tuple[_dt.datetime, str]:
    """When the SOURCE saw it, and the sentence explaining where each part came from."""
    if int(message.get("type", 0)) == 4:
        stated = _base_station_utc(message)
        if stated is not None:
            return stated, ("base station UTC date and time (message 4) — the one message in "
                            "scope that states a full instant; nothing is reconciled")
    second = message.get("utc_second")
    if isinstance(second, int) and second <= 59:
        return (_reconcile_second(second, reference),
                f"message utc_second {second}, reconciled to the nearest minute of the "
                f"reception instant {times.render(reference)} — AIS states a second and no date")
    if isinstance(second, int):
        return (reference,
                f"message utc_second {second} is {SECOND_TEXT.get(second, 'out of range')} "
                "and not a time; the reception instant is used and the message states no other")
    return (reference,
            f"AIS type {message.get('type')} carries no time field at all; the reception "
            "instant is used, and the message itself states nothing about when")


def _base_station_utc(message: dict) -> _dt.datetime | None:
    """A type 4 message's stated instant, or None when any part of it is a sentinel."""
    parts = {name: message.get(f"utc_{name}")
             for name in ("year", "month", "day", "hour", "minute", "second")}
    if any(not isinstance(v, int) for v in parts.values()):
        return None
    if parts["year"] == 0 or parts["month"] == 0 or parts["day"] == 0 \
            or parts["hour"] > 23 or parts["minute"] > 59 or parts["second"] > 59:
        return None
    try:
        return _dt.datetime(parts["year"], parts["month"], parts["day"], parts["hour"],
                            parts["minute"], parts["second"], tzinfo=_dt.timezone.utc)
    except ValueError:
        # A calendar-impossible date (31 February) is data, not a crash. Falling through to
        # the reconciliation path is honest: the message did not state a usable instant.
        return None


def _source_ids(mmsi: str, message: dict) -> list[dict[str, str]]:
    """The MMSI, plus the IMO number when the message states one.

    Two entries rather than a choice between them. An MMSI is reassigned when a vessel changes
    flag; an IMO number is fixed for the life of the hull. A consumer holding one and looking
    for the other is exactly what `source_ids` being a LIST is for.
    """
    source_ids = [{"system": SYSTEM, "external_id": mmsi}]
    imo = message.get("imo_number")
    if isinstance(imo, int) and imo:
        source_ids.append({"system": IMO_SYSTEM, "external_id": str(imo)})
    return source_ids


def _ship_type_text(code: int) -> str:
    """The standard's wording for a ship-type byte: the specific entry, or its decade group."""
    if code in SHIP_TYPE_SPECIFIC:
        return SHIP_TYPE_SPECIFIC[code]
    group = SHIP_TYPE_GROUP.get(code // 10)
    return f"{group} (code {code})" if group else f"unrecognised ship type {code}"


def _unavailable_fields(message: dict) -> list[str]:
    """The fields the SOURCE explicitly marked not-available, by name, sorted.

    "The vessel said it does not know its heading" and "this adapter had nothing to say" are
    different facts, and without this list only one of them survives into the CDM — both
    render as an absent field. Recording it costs one sorted list and makes the null-versus-
    sentinel distinction auditable rather than a property of the code that produced it.
    """
    return sorted(name for name, sentinel in UNAVAILABLE_WHEN
                  if name in message and message[name] == sentinel)


def _dimension(message: dict, name: str) -> int | None:
    """One hull dimension in metres, with AIS's 0 meaning "not available", never 0 m."""
    value = message.get(name)
    return value if isinstance(value, int) and value else None


def _attributes(message: dict, parsed: dict, consumed: Sequence[str], category: str,
                mid: str | None, *, observed_basis: str) -> dict[str, Any]:
    """Everything about this station that is not a canonical field. Nones are dropped later."""
    message_type = int(message.get("type", 0))
    _, position_source_basis = _position_source(message)
    second = message.get("utc_second")
    rot_raw = message.get("rate_of_turn_raw")
    status = message.get("navigational_status")
    ship_type = message.get("ship_type")
    aid_type = message.get("aid_type")
    epfd = message.get("epfd")
    heading = message.get("true_heading_deg")
    sog = message.get("sog_knots")
    bow, stern = _dimension(message, "dim_to_bow"), _dimension(message, "dim_to_stern")
    port, starboard = _dimension(message, "dim_to_port"), _dimension(message, "dim_to_starboard")
    sentences = parsed.get("sentences") or []
    aid_name_base = message.get("name")
    aid_name_extension = message.get("name_extension")

    attributes: dict[str, Any] = {
        "ais_message_type": message_type,
        # AIVDM is another station, AIVDO is the receiver's own. Recorded and NOT read as an
        # affiliation: the formatter says whose transmitter it is, not whose side they are on,
        # and a feed relayed from a partner's receiver would make their ship ours by accident.
        "ais_talker": (sentences[0].get("talker") if sentences else None),
        "mmsi_category": category,
        "mmsi_mid": mid,
        "repeat_indicator": message.get("repeat_indicator"),
        "affiliation_basis": "AIS is a collision-avoidance broadcast and states no identity; "
                             "UNKNOWN is the format's silence, not a collapsed vocabulary",
        "symbol_basis": "derived from affiliation; AIS states no symbol and no identity",
        "valid_from_basis": observed_basis,
        "entity_id_basis": "message MMSI",
        "position_source_basis": position_source_basis,
        # A threshold, not a measurement — which is why it is here and not in accuracy_m.
        "position_accuracy_high": message.get("position_accuracy"),
        "utc_second_raw": second,
        "utc_second_meaning": SECOND_TEXT.get(second) if isinstance(second, int) else None,
        "navigational_status": status,
        "navigational_status_text": (NAVIGATIONAL_STATUS.get(status)
                                     if isinstance(status, int) else None),
        # gap 7: no canonical heading distinct from course, and no canonical turn rate.
        "true_heading_deg": None if heading in (None, HEADING_UNAVAILABLE) else heading,
        "rate_of_turn_raw": rot_raw,
        "rate_of_turn_deg_per_min": _rate_of_turn(rot_raw),
        "epfd": epfd,
        "epfd_text": EPFD_TEXT.get(epfd) if isinstance(epfd, int) else None,
        # gap 1: no canonical name field. The tally of keys and adapters lives in gap 1
        # and is deliberately not repeated here — this comment said "four keys across two
        # adapters" and gap 1 now counts eight and seven.
        "vessel_name": message.get("vessel_name") or None,
        "call_sign": message.get("call_sign") or None,
        "destination": message.get("destination") or None,
        "ship_type": ship_type if ship_type else None,
        "ship_type_text": _ship_type_text(ship_type) if ship_type else None,
        "aid_type": aid_type if isinstance(aid_type, int) else None,
        "aid_type_text": AID_TYPE.get(aid_type) if isinstance(aid_type, int) else None,
        "virtual_aid": message.get("virtual_aid"),
        "off_position": message.get("off_position"),
        # gap 8: no canonical extent. Length and beam are derived; each is None unless BOTH
        # halves were stated, because half a hull is not a shorter hull.
        "dim_to_bow": bow, "dim_to_stern": stern,
        "dim_to_port": port, "dim_to_starboard": starboard,
        "length_m": (bow + stern) if bow and stern else None,
        "beam_m": (port + starboard) if port and starboard else None,
        "draught_m": message.get("draught_m") or None,
        "imo_number": message.get("imo_number") or None,
        "unavailable_fields": _unavailable_fields(message),
        "source_extras": lossless.residual(parsed, consumed),
    }
    if sog == SOG_AT_OR_ABOVE_MAXIMUM:
        # 102.2 is a floored measurement, not an absence: the vessel IS moving at least that
        # fast. Kept, with the floor recorded so nobody reads it as an exact speed.
        attributes["sog_at_or_above_maximum"] = True
    if isinstance(rot_raw, int) and abs(rot_raw) == ROT_MAGNITUDE_FLOOR:
        attributes["rate_of_turn_at_or_above_floor"] = True
    if message_type == 21:
        attributes["aid_name"] = (f"{aid_name_base or ''}{aid_name_extension or ''}") or None
        attributes["aid_name_base"] = aid_name_base or None
        attributes["aid_name_extension"] = aid_name_extension or None
    if message_type == 5:
        # The four numbers AIS states, NOT a timestamp: AIS gives no year, so assembling one
        # would need an invented year, and an ETA in the wrong year is worse than four honest
        # numbers a consumer can read.
        attributes["eta"] = {name: message.get(f"eta_{name}")
                             for name in ("month", "day", "hour", "minute")}
    if message_type == 4:
        attributes["base_station_utc"] = {
            name: message.get(f"utc_{name}")
            for name in ("year", "month", "day", "hour", "minute", "second")}
    return attributes


def _rate_of_turn(raw: Any) -> float | None:
    """ROT_AIS back to degrees per minute: the standard's own inverse of 4.733*sqrt(rate).

    None for the -128 sentinel and for +-127, which mean "turning faster than 5 degrees per
    30 seconds" — a floor, not a rate. Returning 127 squared there would be a measurement
    nobody made. Note that 0 IS a measurement: the vessel is not turning.
    """
    if not isinstance(raw, int) or raw == ROT_UNAVAILABLE or abs(raw) == ROT_MAGNITUDE_FLOOR:
        return None
    return round((1 if raw >= 0 else -1) * (abs(raw) / 4.733) ** 2, 1)


# ----------------------------------------------------------------- egress helpers


def _mmsi_of(obj: CDMBase) -> str:
    """This object's MMSI, or a refusal. An AIS message with no MMSI addresses nobody."""
    for source_id in obj.source_ids:
        if source_id.system == SYSTEM:
            return source_id.external_id
    systems = sorted({s.system for s in obj.source_ids})
    raise ValueError(
        f"cannot emit AIS for an object with no {SYSTEM} source id (it has: {systems or 'none'}). "
        "The MMSI is the address field of every AIS message; deriving one from the CDM id "
        "would put a station on the VHF data link under a number nobody allocated"
    )


def _first_sentence(extras: Any) -> dict[str, Any]:
    """The parked envelope of the first sentence, so a re-emission keeps its talker and channel."""
    if isinstance(extras, dict):
        sentences = extras.get("sentences")
        if isinstance(sentences, list) and sentences and isinstance(sentences[0], dict):
            return sentences[0]
    return {}


def _observed_at_for(entity: Entity, objects: list[CDMBase]) -> _dt.datetime:
    """The `observed_at` of an Event about this entity — where the second of the minute is."""
    for candidate in objects:
        if isinstance(candidate, Event) and entity.entity_id in candidate.related_entities:
            return candidate.observed_at
    return entity.valid_from


def _message_from_entity(entity: Entity, observed_at: _dt.datetime) -> dict[str, Any]:
    """An Entity back into the fields of one AIS message, restoring what ingest parked.

    Three layers, in this order: the standard's not-available value for every field, so an
    Entity that never came from AIS still encodes; then the parked source fields, which is
    what the spare bits and the radio state come back from; then the canonical CDM values,
    which WIN — a position edited in the CDM must reach the wire, or egress would be a replay
    rather than a translation.
    """
    attributes = dict(entity.attributes)
    extras = attributes.get("source_extras") or {}
    parked = extras.get("message") if isinstance(extras, dict) else None
    message_type = int(attributes.get("ais_message_type") or 1)

    message: dict[str, Any] = dict(NOT_AVAILABLE)
    if isinstance(parked, dict):
        message.update(parked)
    message["type"] = message_type
    message["mmsi"] = _mmsi_of(entity)
    message["repeat_indicator"] = attributes.get("repeat_indicator") or 0

    position = entity.position
    message["lat"] = position.lat if position else LAT_UNAVAILABLE
    message["lon"] = position.lon if position else LON_UNAVAILABLE
    message["position_accuracy"] = bool(attributes.get("position_accuracy_high"))

    kinematics = entity.kinematics
    speed = kinematics.speed_mps if kinematics else None
    course = kinematics.course_deg if kinematics else None
    message["sog_knots"] = SOG_UNAVAILABLE if speed is None else round(speed / KNOT_MPS, 1)
    message["cog_deg"] = COG_UNAVAILABLE if course is None else course
    message["true_heading_deg"] = attributes.get("true_heading_deg", HEADING_UNAVAILABLE)
    if attributes.get("rate_of_turn_raw") is not None:
        message["rate_of_turn_raw"] = attributes["rate_of_turn_raw"]

    # The second of the minute, from the source's own field where ingest parked it — including
    # 60-63, which are not seconds and could never be recovered from a datetime.
    if attributes.get("utc_second_raw") is not None:
        message["utc_second"] = attributes["utc_second_raw"]
    else:
        message["utc_second"] = observed_at.second
    stated_utc = attributes.get("base_station_utc")
    if isinstance(stated_utc, dict):
        message.update({f"utc_{name}": value for name, value in stated_utc.items()})
    elif message_type == 4:
        for name in ("year", "month", "day", "hour", "minute", "second"):
            message[f"utc_{name}"] = getattr(observed_at, name)

    for field in ("navigational_status", "epfd", "ship_type", "aid_type"):
        if attributes.get(field) is not None:
            message[field] = attributes[field]
    message["vessel_name"] = attributes.get("vessel_name") or ""
    message["call_sign"] = attributes.get("call_sign") or ""
    message["destination"] = attributes.get("destination") or ""
    message["name"] = attributes.get("aid_name_base") or ""
    message["name_extension"] = attributes.get("aid_name_extension") or ""
    message["virtual_aid"] = bool(attributes.get("virtual_aid"))
    message["off_position"] = bool(attributes.get("off_position"))
    message["draught_m"] = float(attributes.get("draught_m") or 0.0)
    for field in ("dim_to_bow", "dim_to_stern", "dim_to_port", "dim_to_starboard"):
        message[field] = int(attributes.get(field) or 0)
    eta = attributes.get("eta")
    if isinstance(eta, dict):
        message.update({f"eta_{name}": value for name, value in eta.items()})

    # The IMO number comes from `source_ids` rather than from `attributes`: it is a canonical
    # identifier of the hull, and the canonical layer wins for the same reason the position does.
    message["imo_number"] = next(
        (int(s.external_id) for s in entity.source_ids
         if s.system == IMO_SYSTEM and s.external_id.isdigit()), 0)
    return message
