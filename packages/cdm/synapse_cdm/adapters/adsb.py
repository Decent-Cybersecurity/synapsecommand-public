"""ADS-B 1090ES — Mode S extended squitter frames in, CDM out; CDM out to DF17 frames.

Adapter #4, and the third bidirectional one. It implements the ADS-B table in
FORMAT_COVERAGE.md row by row; that table is this module's specification, and a test resolves
every CDM path in it against the models so the two cannot drift.

WHAT EACH DIRECTION IS
----------------------
INGEST  one 112-bit extended squitter *frame* — delivered as 28 hex characters in the AVR text
        form (`*8D…;`) — becomes an Entity + an Event. The same "one payload, two objects"
        split as the other adapters: a frame describes a thing that EXISTS (an aircraft, at a
        place, with a callsign) and a thing that HAPPENED (that state was broadcast).

EGRESS  one Entity, or one Track, becomes the DF17 frames that restate it. An Entity emits the
        type code it arrived as; a Track emits one position frame per sample, in the track's
        own order, which is the only shape 1090ES has for a history.

TYPE CODES IN SCOPE
-------------------
1-4 (aircraft identification) · 5-8 (surface position) · 0 and 9-18 (airborne position,
barometric altitude) · 19 subtypes 1-4 (airborne velocity) · 20-22 (airborne position, GNSS
height) · 28 subtype 1 (aircraft status) · 31 subtype 0 (aircraft operational status).
Everything else is named in FORMAT_COVERAGE.md with the reason it is out, because
"unsupported" without a reason is indistinguishable from "nobody thought about it".

THREE THINGS THIS FORMAT DOES NOT HAVE, AND AIS DID
---------------------------------------------------
1. **No time.** Not a date, not a second of the minute, nothing. The `T` bit says only whether
   the position is synchronised to a 0.2 s UTC epoch — a flag about time, not a time. So
   `observed_at` is the receipt instant on every frame and `payload.observed_at_basis` says
   exactly that, rather than implying the aircraft stated it. Where AIS gave a second and made
   us find the minute, ADS-B gives nothing and makes us say so.
2. **No usable receiver clock either.** The AVR `@` form carries a 48-bit timestamp, and it is
   a free-running 12 MHz counter since the receiver started — not a wall clock. It is parked
   and never read as one: an adapter that treated it as a UNIX epoch would date every frame to
   1970. This is the exact mirror of the NMEA TAG block, which IS a wall clock and IS read.
3. **No unambiguous position in one frame.** See THE CPR DECISION below — the design question
   this format forces and AIS did not.

THE CPR DECISION: PAIRING TWO FRAMES IS FUSION, NOT TRANSLATION
---------------------------------------------------------------
A position frame carries latitude and longitude as 17-bit Compact Position Reporting values,
which state a position *within a zone* and not a position. There are two ways to recover a
coordinate, and this adapter takes exactly one of them.

GLOBAL decoding pairs an even-parity frame with an odd-parity frame received within about ten
seconds and needs no prior knowledge. **It is out of scope, and the reason is structural rather
than effort.** Two frames of opposite parity are two transmissions that must be joined on the
ICAO address across time; an `Adapter` is a pure function of one payload (see adapter.py), so a
global-decoding translator either emits a half-populated object or holds a cache — and a cache
in a translator is fusion done where nothing audits it. That is word for word the argument that
keeps AIS message type 24 out of scope, and applying it consistently is the point: type 24's
parts A and B, AIS cross-payload fragment reassembly, and CPR even/odd pairing are one decision
made three times. It is also why a payload holding two frames is refused outright — accepting
one would smuggle the pair in through the framing.

LOCAL decoding needs one frame plus a reference position already known to be within about
180 NM (airborne) or 45 NM (surface). **It is in scope, because the reference is configuration
rather than state.** `AdsbAdapter(reference_position=(lat, lon))` takes the receiver's own
surveyed antenna position: a constant of the deployment, supplied at construction exactly like
the injected clock and `synthetic`, not accumulated from the data stream and not changing
between frames. Every fix it produces records what it was decoded against, at
`attributes.position_reference`, so nothing downstream is asked to trust a coordinate without
seeing its basis.

**With no reference configured there is no position**, which makes the default the safe one:
`position` is None, the three CPR fields are parked verbatim, and
`attributes.position_unavailable_reason` states that one frame does not state a position. The
raw CPR fields are parked on EVERY frame, decoded or not, so a fusion layer holding a proper
even/odd pair can discard our answer and compute its own.

The residual risk is named rather than hidden: a local decode more than one zone from the
reference returns a plausible coordinate in the wrong zone, and no single frame can reveal that
it did. `attributes.position_decode_basis` states the range within which the answer is
unambiguous.

THE TWO ALTITUDES, WHICH ARE NOT ONE FIELD AND NOT ONE ENCODING
---------------------------------------------------------------
Type codes 9-18 and 20-22 share one 56-bit layout, and the twelve bits at ME 9-20 are the same
wire position in both. Everything else about them differs — the measurement, the reference
surface, the unit AND the encoding:

    9-18    barometric pressure altitude against the 1013.25 hPa datum, in 25-foot steps
            offset by 1000 ft behind a Q bit  (or the Gillham encoding when Q is clear)
    20-22   GNSS height, as the PLAIN DECIMAL VALUE of all twelve bits in METRES — no Q bit,
            no offset, no 25-foot increment

Source for the second: mode-s.org, "The 1090MHz Riddle", airborne position chapter — "the
12-bit altitude field is used for the encoding of the GNSS height ... the decimal value of all
12 bits translates into the height of aircraft in meters". It is worth stating where that came
from, because assuming the two ranges shared the barometric arithmetic is a mistake that stays
plausible: it reports an altitude wrong by roughly a factor of eight and every other check
passes. The consequence is also worth knowing — twelve bits of metres saturate at 4095 m, about
13 435 ft, which is why type codes 20-22 are little used in practice and why a higher altitude
is an encode ERROR here rather than a clipped value.

`Position.alt_m` is documented as metres HAE, so the GNSS one maps and the barometric one does
NOT. They differ by hundreds of metres in ordinary weather, and writing a pressure altitude
into an HAE field would be the same class of false statement as writing AIS's ten-metre
accuracy threshold into `accuracy_m`. So barometric altitude is parked at
`attributes.baro_altitude_ft`, GNSS height beside it at `attributes.gnss_altitude_m` — the key
names carry the unit because the fields do — and gap 9 records what that costs. The type 19
GNSS-barometric difference field is parked with them, because it is the offset that relates the
two.

Two things this adapter ASSERTS rather than reads, both recorded in the objects themselves:

- **The all-zero GNSS-height field is read as "not available".** The reference documents that
  meaning for the barometric field and is silent for this one, so it is a decision taken in the
  safe direction — 0 m would place an airborne aircraft exactly on the ellipsoid, and an absent
  altitude is recoverable where a false one is not. `attributes.altitude_basis` says so.
- **The datum.** DO-260 version 0 transmitters broadcast this height against MEAN SEA LEVEL;
  DO-260A/B against the ellipsoid. The frame does not carry its own version — that is in a type
  31 operational-status frame — so calling it HAE is an assertion of exactly the shape gap 7's
  magnetic-versus-true heading problem has. `attributes.altitude_type` names both readings.

The Gillham case is the remaining half of the barometric side. Q = 0 means the 100-foot
reflected-Gray encoding used above 50 175 ft, and it is deliberately NOT decoded: the
permutation from this 12-bit field into the Mode C layout is the kind of detail that is either
exactly right or yields a confident wrong flight level, and no pinned reference for it exists in
this repository. The raw twelve bits are parked and the altitude is absent — logged as a gap
rather than guessed, which is the rule this project already applies to a field definition it
cannot source.

THE SENTINELS
-------------
ADS-B spells "not available" as zero in fields that are otherwise offset by one, so the whole
family shares one shape: a wire value of 0 means unknown and a wire value of v means v-1.

    altitude (12 bits, all zero)    altitude not available
    east-west / north-south speed   0 = not available; a component missing yields NO speed,
                                    never a speed computed from the other axis
    airspeed                        0 = not available
    vertical rate                   0 = not available, NOT level flight
    GNSS-baro difference            0 = not available
    surface movement                0 = not available; 1 = stopped, which IS a measurement of
                                    stillness; 124 = "175 kt or above", a floor and not a
                                    speed, kept with the floor recorded as AIS's 102.2 kt is
    emitter category                0 = "no category information", a stated absence

Two fields are not sentinel-valued at all and are absent by a STATUS BIT instead — the surface
ground track and the airborne heading. "The aircraft cleared the validity bit" and "the field
happened to be zero" are different statements, so the two mechanisms are kept apart and both
feed `attributes.unavailable_fields`.

WHY NOTHING HERE IS AN IDENTIFICATION
-------------------------------------
`affiliation` is UNKNOWN on every frame, and for a stronger reason than AIS's. AIS states no
identity; 1090ES states one and it must not be trusted. Every field is self-declared by the
transmitter and there is no integrity mechanism beyond the CRC, which detects corruption and
not forgery — a callsign, an emitter category and an ICAO address are all trivially spoofable.
`attributes.affiliation_basis` records which of the two situations produced the UNKNOWN.

DF18 IS NOT DF17 WITH A DIFFERENT NUMBER
----------------------------------------
DF18 reuses the DF17 ME layouts and changes what a frame MEANS, and the control field is the
only thing that says so. Two consequences are load-bearing rather than cosmetic:

- CF 1 and CF 5 mean the address is **not** an ICAO 24-bit address — it is anonymous or
  self-assigned. Filing one under `ICAO24` would let fusion join the contact to a real airframe
  that happens to share the number, so the source id system becomes `ADSB_NONICAO` instead.
- CF 2 and CF 5 are fine-format TIS-B: a ground station rebroadcasting a surveillance track it
  derived by other means. `position_source` is ESTIMATED there and never GNSS, because GNSS
  would promise a fix that survives jamming — the same dangerous direction as calling an AIS
  integrated navigation system INERTIAL.

THE CRC IS A GATE, NOT AN ANNOTATION
------------------------------------
The 24-bit parity field of a DF17/DF18 frame is a plain CRC over the preceding 88 bits (unlike
DF4/5/11/20/21, where it is overlaid with the address — which is one of the two reasons the
rest of Mode S is a different adapter). It is verified on ingest and a frame that fails is
REFUSED, never best-effort decoded: a bit flip in the ME field moves an aircraft rather than
failing to parse. On egress it is COMPUTED and never copied, because a frame carrying a stale
parity field is discarded by every receiver, silently.

EGRESS INTO A FORMAT WITH NO EXTENSION POINT
--------------------------------------------
AIS had no extension point; ADS-B has none and then some. All 56 ME bits are allocated per type
code, and the parity is a CRC over the other 88 — so a bit invented here would either be read
as the field the standard says lives there, or would break the CRC and be dropped by every
receiver. `entity_id`, `track_id`, `track_quality`, `schema_version`, the affiliation, the
symbol and the whole provenance block therefore have nowhere to go. The round-trip test excludes
them BY NAME with a reason each, rather than measuring a loss it cannot fix — and every field
ADS-B CAN carry is measured, by unpacking the emitted frames bit by bit rather than exempting
them.

What egress is NOT lossy for is a frame this adapter ingested: the parked fields are read back,
so `to_cdm()` then `from_cdm()` reproduces the original frame byte for byte, CRC included.

There is exactly ONE exception, and it is a refusal rather than a loss. A frame whose callsign
contains a six-bit value the ICAO alphabet does not define cannot be re-emitted: `_callsign_bits`
raises instead of substituting a character, because a callsign silently altered on the wire reads
as the aircraft's real callsign to every receiver. The malformed string survives in
`attributes.callsign_raw`, so nothing is lost — what cannot happen is a re-transmission that
looks valid and names a different aircraft.
"""
from __future__ import annotations

import json
import math
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

SYSTEM = "ADSB"

#: The source id system for the 24-bit address, and it is NOT the adapter's own name. The
#: address is an ICAO Annex 10 aircraft address: stable for the airframe and carried
#: identically by Mode S replies, ACAS and ASTERIX. A fusion layer joining an ADS-B contact to
#: a radar track keys on exactly this string, and `ids.derive` then agrees across both adapters
#: without coordinating — which is the whole reason identity is derived rather than drawn.
#: `source.system` records that this particular copy arrived over ADS-B.
ICAO_SYSTEM = "ICAO24"

#: DF18 CF 1 and CF 5 say the address is anonymous or self-assigned. It is still the only
#: identifier the frame carries, so it is still the source id — under a system name that keeps
#: it out of the ICAO24 space, because a self-assigned number colliding with a real airframe's
#: address must not become a fused track.
NONICAO_SYSTEM = "ADSB_NONICAO"

# ------------------------------------------------------------------ the frame wire form

#: A DF17/DF18 extended squitter is exactly 112 bits — 28 hex characters. Fixed length, so
#: anything else is a refusal rather than a truncated read.
FRAME_BITS = 112
FRAME_HEX_CHARS = FRAME_BITS // 4

#: Where the fields sit in the 112 bits. Spelled out because every offset below depends on it.
ME_START, ME_END = 32, 88
PARITY_BITS = 24

#: The AVR text markers. `*` is a bare frame; `@` prefixes a 48-bit receiver timestamp counter.
PREFIX_BARE = "*"
PREFIX_TIMESTAMPED = "@"
FRAME_TERMINATOR_CHAR = ";"
TIMESTAMP_HEX_CHARS = 12

#: Unlike NMEA, no standard mandates a line terminator for a hex frame stream. `\n` is what
#: dump1090 and readsb emit; it is named here rather than assumed so a golden file is
#: comparable byte for byte.
FRAME_TERMINATOR = "\n"

#: The Mode S CRC generator, as 25 bits: x^24 + x^23 + ... + x^3 + 1 (0x1FFF409). The low 24
#: bits, 0xFFF409, are the polynomial as it is usually quoted.
CRC_GENERATOR = 0x1FFF409

DF_ADSB = 17
DF_TISB = 18
DF_IN_SCOPE = (DF_ADSB, DF_TISB)

# ---------------------------------------------------------------- world vocabularies

#: DF18's control field. The same three bits are DF17's capability field, which is why the wire
#: name in the layout is neutral: what they mean depends on the downlink format.
CONTROL_FIELD: dict[int, str] = {
    0: "ADS-B ES/NT device with ICAO 24-bit address",
    1: "ADS-B ES/NT device with anonymous or self-assigned address",
    2: "fine-format TIS-B message with ICAO 24-bit address",
    3: "coarse-format TIS-B message",
    4: "TIS-B management message",
    5: "fine-format TIS-B message with anonymous or self-assigned address",
    6: "ADS-B rebroadcast (ADS-R)",
    7: "reserved",
}

#: The address in these frames is not an ICAO allocation.
CF_NON_ICAO = (1, 5)
#: A ground station's rebroadcast of a surveillance track — not the aircraft's own GNSS fix.
CF_TISB_SURVEILLANCE = (2, 5)
#: A rebroadcast of a genuine ADS-B message: the original fix IS the aircraft's GNSS.
CF_RELAY = (6,)
#: Refused by name. CF 3 has a DIFFERENT ME layout (a coarser position with its own field
#: widths), so decoding it with the fine-format layout would produce a plausible wrong position
#: rather than an error — which is worse than refusing. CF 4 addresses the ground station's
#: link and not the world; CF 7 is reserved and has no layout to read.
CF_REFUSED = (3, 4, 7)

#: Airborne position, surveillance status field. 1 is the standard's own emergency indication
#: and the ONLY value here that raises severity: an ident-code change or an SPI pulse is a
#: procedural condition, and grading one would be this translator judging operational
#: significance — which belongs to fusion, where it is visible and attributable. The line sits
#: exactly where the AIS adapter draws it at navigational status 14.
SURVEILLANCE_STATUS: dict[int, str] = {
    0: "no condition information",
    1: "permanent alert (emergency condition)",
    2: "temporary alert (change of Mode A identity code)",
    3: "SPI (special position identification)",
}
SURVEILLANCE_STATUS_EMERGENCY = 1

#: Type code 28 subtype 1. 1-6 are the standard's own emergency declarations; 0 is no
#: emergency and 7 is reserved.
EMERGENCY_STATE: dict[int, str] = {
    0: "no emergency",
    1: "general emergency",
    2: "lifeguard or medical emergency",
    3: "minimum fuel",
    4: "no communications",
    5: "unlawful interference",
    6: "downed aircraft",
    7: "reserved",
}
EMERGENCY_STATES_DECLARED = (1, 2, 3, 4, 5, 6)

#: The emitter category, keyed on (type code, category) because the type code selects the
#: category SET and neither number means anything alone.
CATEGORY_SET: dict[int, str] = {1: "D", 2: "C", 3: "B", 4: "A"}
NO_CATEGORY = "no ADS-B emitter category information"
EMITTER_CATEGORY: dict[tuple[int, int], str] = {
    (4, 0): NO_CATEGORY,
    (4, 1): "light (below 15 500 lb)",
    (4, 2): "small (15 500 to 75 000 lb)",
    (4, 3): "large (75 000 to 300 000 lb)",
    (4, 4): "high-vortex large",
    (4, 5): "heavy (above 300 000 lb)",
    (4, 6): "high performance (above 5 g acceleration and 400 kt)",
    (4, 7): "rotorcraft",
    (3, 0): NO_CATEGORY,
    (3, 1): "glider or sailplane",
    (3, 2): "lighter-than-air",
    (3, 3): "parachutist or skydiver",
    (3, 4): "ultralight, hang-glider or paraglider",
    (3, 5): "reserved",
    (3, 6): "unmanned aerial vehicle",
    (3, 7): "space or transatmospheric vehicle",
    (2, 0): NO_CATEGORY,
    (2, 1): "surface vehicle — emergency vehicle",
    (2, 2): "surface vehicle — service vehicle",
    (2, 3): "point obstacle (includes tethered balloon)",
    (2, 4): "cluster obstacle",
    (2, 5): "line obstacle",
    (2, 6): "reserved",
    (2, 7): "reserved",
    **{(1, code): "reserved (category set D)" for code in range(8)},
}

#: The one place the emitter category refines `entity_type`. An obstacle is a fixed structure
#: and not a platform — the same call the AIS adapter makes for an aid to navigation, and for
#: the same reason. Everything else stays PLATFORM: a light aircraft, a heavy and a rotorcraft
#: are all platforms, and inventing a finer CDM distinction from this byte would put a
#: judgement in a translator, exactly as an AIS ship type does not.
OBSTACLE_CATEGORIES = ((2, 3), (2, 4), (2, 5))

#: Type code 19 subtypes. 2 and 4 are the supersonic variants, whose velocity fields count in
#: four-knot units — a scale factor, not a different field.
VELOCITY_SUBTYPE: dict[int, str] = {
    1: "velocity over ground, subsonic",
    2: "velocity over ground, supersonic",
    3: "airspeed and heading, subsonic",
    4: "airspeed and heading, supersonic",
}
VELOCITY_SUBTYPES_GROUND = (1, 2)
VELOCITY_SUBTYPES_AIR = (3, 4)
SUPERSONIC_SUBTYPES = (2, 4)
SUPERSONIC_MULTIPLIER = 4

AIRSPEED_TYPE: dict[int, str] = {0: "indicated airspeed", 1: "true airspeed"}
VERTICAL_RATE_SOURCE: dict[int, str] = {0: "GNSS (geometric)", 1: "barometric"}

#: Type code 31's horizontal reference direction — the datum for every heading and track this
#: airframe transmits. It arrives in a DIFFERENT frame than the heading does, which is the
#: cross-frame join named in gap 7: a canonical heading field needs this datum beside it, and
#: ADS-B cannot supply the two from one frame.
HEADING_REFERENCE: dict[int, str] = {0: "true north", 1: "magnetic north"}

#: ADS-B version, which is what says how several other fields are to be read.
ADSB_VERSION: dict[int, str] = {0: "DO-260", 1: "DO-260A", 2: "DO-260B"}

#: The ICAO 6-bit callsign alphabet, indexed by wire value. `#` marks a value the standard does
#: not define — kept as a character rather than dropped, so a malformed callsign is VISIBLE.
CALLSIGN_ALPHABET = (
    "#ABCDEFGHIJKLMNOPQRSTUVWXYZ#####"  # 0-31: 1-26 are A-Z, the rest undefined
    " "                                  # 32: space, the pad character
    "###############"                    # 33-47: undefined
    "0123456789"                         # 48-57
    "######"                             # 58-63: undefined
)
CALLSIGN_UNDEFINED = "#"
CALLSIGN_PAD = " "

#: Surface movement: a non-linear 7-bit bucket table, in (lowest raw, highest raw, knots at the
#: lowest raw, knots per step). Kept as data so the boundaries are checkable by eye against
#: DO-260B rather than buried in a chain of comparisons.
MOVEMENT_BUCKETS: tuple[tuple[int, int, float, float], ...] = (
    (2, 8, 0.125, 0.125),
    (9, 12, 1.0, 0.25),
    (13, 38, 2.0, 0.5),
    (39, 93, 15.0, 1.0),
    (94, 108, 70.0, 2.0),
    (109, 123, 100.0, 5.0),
)
MOVEMENT_NOT_AVAILABLE = 0
#: Below 0.125 kt. This IS a measurement of stillness and becomes 0.0 m/s — the mirror of the
#: AIS rule that a life raft making 0.0 kn has been measured, not left unstated.
MOVEMENT_STOPPED = 1
#: "175 kt or above": a floor and not a speed, so the value is kept and the floor is recorded,
#: exactly as AIS's 102.2 kn is.
MOVEMENT_AT_OR_ABOVE_MAXIMUM = 124
MOVEMENT_MAXIMUM_KNOTS = 175.0
MOVEMENT_RESERVED = (125, 126, 127)

# --------------------------------------------------------------------- unit constants

#: A nautical mile is 1852 m by definition, an international foot 0.3048 m exactly. Both
#: conversions below are therefore exact rather than approximate, which is why they are
#: declared transforms and not parked values.
KNOT_MPS = 1852.0 / 3600.0
FOOT_M = 0.3048
FEET_PER_MINUTE_MPS = FOOT_M / 60.0

#: The BAROMETRIC altitude field's arithmetic, Q = 1: eleven bits of 25-foot steps, offset so
#: the field can express 1000 ft below the datum. Named for the measurement rather than for the
#: wire position, because the same twelve bits mean something entirely different on a
#: GNSS-height frame — see GNSS_HEIGHT_MAX_M.
BARO_STEP_FEET = 25
BARO_OFFSET_FEET = 1000
BARO_Q_BIT_INDEX = 7

#: The GNSS-height field is the plain decimal value of all twelve bits, in METRES: no Q bit, no
#: offset, no 25-foot increment (mode-s.org, "Airborne Position": "the decimal value of all 12
#: bits translates into the height of aircraft in meters"). So it saturates at 4095 m — about
#: 13 435 ft — which is why type codes 20-22 are little used in practice and why an altitude
#: above that range is an ENCODE ERROR here rather than something to saturate: a cruise level
#: clipped to 4095 m would read as a real, low, wrong altitude.
GNSS_HEIGHT_MAX_M = (1 << 12) - 1

#: Ground track is 128 steps of a full circle; heading is 1024 steps of one.
TRACK_STEPS = 128
HEADING_STEPS = 1024

VERTICAL_RATE_STEP_FEET_PER_MINUTE = 64
GNSS_BARO_DIFFERENCE_STEP_FEET = 25

# ------------------------------------------------------------------------ CPR

#: The number of latitude zones between the equator and a pole. A constant of the CPR scheme.
CPR_ZONES = 15
CPR_SCALE = 1 << 17

#: Airborne CPR spans the whole globe; surface CPR spans a quarter of it, which is what buys
#: the extra resolution and costs the wider ambiguity.
CPR_SPAN_AIRBORNE = 360.0
CPR_SPAN_SURFACE = 90.0

#: The distance within which a LOCAL decode is unambiguous, per DO-260B. Stated in the basis
#: string on every fix rather than checked, because no single frame can reveal that the
#: aircraft was further away than this — the decode would simply return the wrong zone.
CPR_LOCAL_RANGE_NM_AIRBORNE = 180
CPR_LOCAL_RANGE_NM_SURFACE = 45

# ------------------------------------------------------------------- frame layouts
#
# (name, width, kind), in wire order. kind: u unsigned · b one-bit flag · x hex string (so a
# leading zero survives, the way AIS renders an MMSI as nine digits) · c ICAO six-bit callsign
# text.
#
# Reserved fields are LISTED rather than skipped, for AIS's reason: they carry no meaning today
# and are the bits a future DO-260 revision allocates, and decoding them is what makes the
# encoder an exact inverse — which is what makes the round-trip claim checkable rather than
# reviewable.

_HEADER: tuple[tuple[str, int, str], ...] = (
    ("df", 5, "u"),
    # CA on DF17, CF on DF18. One wire position, two meanings, so the wire name is neutral and
    # `_control_field()` is where the meaning is resolved against `df`.
    ("capability", 3, "u"),
    ("icao", 24, "x"),
)
_PARITY: tuple[tuple[str, int, str], ...] = (("parity", PARITY_BITS, "u"),)

#: Frame kind -> the 56-bit ME layout. Every one sums to exactly 56; a test asserts it.
ME_LAYOUTS: dict[str, tuple[tuple[str, int, str], ...]] = {
    "identification": (
        ("type_code", 5, "u"), ("emitter_category", 3, "u"), ("callsign", 48, "c"),
    ),
    "surface_position": (
        ("type_code", 5, "u"), ("movement_raw", 7, "u"), ("track_valid", 1, "b"),
        ("ground_track_raw", 7, "u"), ("time_sync", 1, "b"), ("cpr_format", 1, "u"),
        ("cpr_lat", 17, "u"), ("cpr_lon", 17, "u"),
    ),
    "airborne_position": (
        ("type_code", 5, "u"), ("surveillance_status", 2, "u"),
        ("nic_supplement_b", 1, "b"), ("altitude_raw", 12, "u"), ("time_sync", 1, "b"),
        ("cpr_format", 1, "u"), ("cpr_lat", 17, "u"), ("cpr_lon", 17, "u"),
    ),
    "airborne_velocity_ground": (
        ("type_code", 5, "u"), ("subtype", 3, "u"), ("intent_change", 1, "b"),
        ("ifr_capability", 1, "b"), ("nav_uncertainty_velocity", 3, "u"),
        ("ew_sign", 1, "u"), ("ew_velocity_raw", 10, "u"),
        ("ns_sign", 1, "u"), ("ns_velocity_raw", 10, "u"),
        ("vertical_rate_source", 1, "u"), ("vertical_rate_sign", 1, "u"),
        ("vertical_rate_raw", 9, "u"), ("reserved_velocity", 2, "u"),
        ("gnss_baro_diff_sign", 1, "u"), ("gnss_baro_diff_raw", 7, "u"),
    ),
    "airborne_velocity_air": (
        ("type_code", 5, "u"), ("subtype", 3, "u"), ("intent_change", 1, "b"),
        ("ifr_capability", 1, "b"), ("nav_uncertainty_velocity", 3, "u"),
        ("heading_valid", 1, "b"), ("heading_raw", 10, "u"),
        ("airspeed_type", 1, "u"), ("airspeed_raw", 10, "u"),
        ("vertical_rate_source", 1, "u"), ("vertical_rate_sign", 1, "u"),
        ("vertical_rate_raw", 9, "u"), ("reserved_velocity", 2, "u"),
        ("gnss_baro_diff_sign", 1, "u"), ("gnss_baro_diff_raw", 7, "u"),
    ),
    "aircraft_status": (
        ("type_code", 5, "u"), ("subtype", 3, "u"), ("emergency_state", 3, "u"),
        ("mode_a_code_raw", 13, "u"), ("reserved_status", 32, "u"),
    ),
    "operational_status": (
        ("type_code", 5, "u"), ("subtype", 3, "u"), ("capability_class", 16, "u"),
        ("operational_mode", 16, "u"), ("version", 3, "u"),
        ("nic_supplement_a", 1, "b"), ("nac_position", 4, "u"),
        ("geometric_vertical_accuracy", 2, "u"), ("source_integrity_level", 2, "u"),
        ("nic_baro", 1, "b"), ("horizontal_reference_direction", 1, "u"),
        ("sil_supplement", 1, "b"), ("reserved_status_b", 1, "u"),
    ),
}

#: Type codes whose altitude field is a GNSS height above the ellipsoid rather than a pressure
#: altitude. The whole of gap 9 turns on this three-element tuple.
TC_GNSS_HEIGHT = (20, 21, 22)
TC_BAROMETRIC = (0,) + tuple(range(9, 19))
TC_IDENTIFICATION = (1, 2, 3, 4)
TC_SURFACE_POSITION = (5, 6, 7, 8)
TC_VELOCITY = 19
TC_AIRCRAFT_STATUS = 28
TC_OPERATIONAL_STATUS = 31

#: Type code 0 is "no position information": the frame states an altitude and the CPR fields
#: carry nothing. They are zero, and zero CPR values are NOT a position at the equator — they
#: are the absence of one, which is why this constant exists rather than a falsiness check.
TC_NO_POSITION_INFORMATION = 0

#: Frame kinds that state a position at all, and those that state motion. Used to pick an
#: event type: a frame carrying neither is a STATUS_CHANGE, because calling it a track update
#: would claim a position it does not have — the AIS type 5 argument.
KINDS_WITH_POSITION = ("airborne_position", "surface_position")
KINDS_WITH_MOTION = ("airborne_velocity_ground", "airborne_velocity_air", "surface_position")

#: The Mode A identity field's bit order, as the standard interleaves it:
#: C1 A1 C2 A2 C4 A4 X B1 D1 B2 D2 B4 D4. Each digit is read from three non-adjacent bits, so
#: the indices are spelled out rather than sliced — an off-by-one here yields a plausible wrong
#: squawk, and 7500 and 7600 differ by exactly one such digit.
MODE_A_BITS: dict[str, tuple[int, int, int]] = {
    # digit: (the 4-weight bit, the 2-weight bit, the 1-weight bit)
    "A": (5, 3, 1),
    "B": (11, 9, 7),
    "C": (4, 2, 0),
    "D": (12, 10, 8),
}
MODE_A_SPARE_BIT = 6


# ============================================================== the codec: the frame


def crc(bits: str) -> int:
    """The Mode S 24-bit CRC of `bits`: polynomial division over GF(2), remainder returned.

    Pinned in `tests/test_cdm_adsb_adapter.py` against published frames rather than against
    this encoder, because a CRC that is only its own inverse would accept every corrupted
    frame this module produced and reject every real one.
    """
    length = len(bits)
    value = int(bits, 2) << PARITY_BITS
    for index in range(length):
        top = length + PARITY_BITS - 1 - index
        if value >> top & 1:
            value ^= CRC_GENERATOR << (top - PARITY_BITS)
    return value & ((1 << PARITY_BITS) - 1)


def _bits_of_hex(text: str) -> str:
    """Hex characters as a bit string of exactly four bits each, leading zeros preserved."""
    try:
        value = int(text, 16)
    except ValueError as e:
        raise ValueError(
            f"ADS-B frame {text!r} is not hexadecimal — the payload is corrupted or is not a "
            "Mode S frame"
        ) from e
    return bin(value)[2:].zfill(len(text) * 4)


def _hex_of_bits(bits: str) -> str:
    """The inverse, upper case: that is how every receiver and every recorded frame prints it."""
    return f"{int(bits, 2):0{len(bits) // 4}X}"


def _parse_frame_line(line: str) -> dict[str, Any]:
    """One AVR text line into its envelope, CRC verified.

    Three accepted forms, all of them real: `*<28 hex>;`, `@<12 hex><28 hex>;` and 28 bare hex
    characters. The prefix is RECORDED rather than normalised, because egress reproduces the
    form the frame arrived in and a golden file is compared byte for byte.
    """
    text = line.strip()
    if not text:
        raise ValueError("ADS-B frame line is empty — nothing to translate")

    prefix, timestamp = "", None
    if text[0] in (PREFIX_BARE, PREFIX_TIMESTAMPED):
        prefix, body = text[0], text[1:]
        if not body.endswith(FRAME_TERMINATOR_CHAR):
            raise ValueError(
                f"ADS-B frame line opens with {prefix!r} and is not terminated with "
                f"{FRAME_TERMINATOR_CHAR!r}: {text[:40]!r} — refusing to guess where the frame "
                "ends, because a truncated frame fails the CRC for the wrong reason"
            )
        body = body[:-1]
        if prefix == PREFIX_TIMESTAMPED:
            if len(body) < TIMESTAMP_HEX_CHARS + FRAME_HEX_CHARS:
                raise ValueError(
                    f"ADS-B '@' form carries {len(body)} hex characters; a "
                    f"{TIMESTAMP_HEX_CHARS}-character receiver timestamp plus a "
                    f"{FRAME_HEX_CHARS}-character frame needs "
                    f"{TIMESTAMP_HEX_CHARS + FRAME_HEX_CHARS}"
                )
            timestamp, body = body[:TIMESTAMP_HEX_CHARS], body[TIMESTAMP_HEX_CHARS:]
    else:
        body = text

    body = body.upper()
    if len(body) != FRAME_HEX_CHARS:
        raise ValueError(
            f"ADS-B frame is {len(body)} hex characters, expected exactly {FRAME_HEX_CHARS} "
            f"({FRAME_BITS} bits): {text[:40]!r}. An extended squitter is fixed length, so a "
            "different length is a framing error and not a shorter message"
        )

    bits = _bits_of_hex(body)
    stated = int(bits[ME_END:], 2)
    computed = crc(bits[:ME_END])
    if stated != computed:
        raise ValueError(
            f"ADS-B frame parity is {stated:06X} but the CRC of its first {ME_END} bits is "
            f"{computed:06X} — refusing to decode a frame that arrived corrupted; a bit flip "
            "in the ME field moves an aircraft rather than failing to parse"
        )

    frame: dict[str, Any] = {"hex": body, "prefix": prefix}
    if timestamp is not None:
        # Parked, never read as a time. It is a free-running 12 MHz counter since the receiver
        # started, so reading it as a UNIX epoch would date every frame to 1970.
        frame["timestamp_raw"] = timestamp.upper()
    return frame


def frame_kind(type_code: int, subtype: int | None = None) -> str | None:
    """Which ME layout a type code (and, where it matters, a subtype) selects.

    None means "not in this adapter's scope", and the caller turns that into a refusal naming
    FORMAT_COVERAGE.md — so an out-of-scope frame produces a decision the reader can look up
    rather than a KeyError.
    """
    if type_code in TC_IDENTIFICATION:
        return "identification"
    if type_code in TC_SURFACE_POSITION:
        return "surface_position"
    if type_code in TC_BAROMETRIC or type_code in TC_GNSS_HEIGHT:
        return "airborne_position"
    if type_code == TC_VELOCITY:
        if subtype in VELOCITY_SUBTYPES_GROUND:
            return "airborne_velocity_ground"
        if subtype in VELOCITY_SUBTYPES_AIR:
            return "airborne_velocity_air"
        return None
    if type_code == TC_AIRCRAFT_STATUS:
        return "aircraft_status" if subtype == 1 else None
    if type_code == TC_OPERATIONAL_STATUS:
        return "operational_status" if subtype == 0 else None
    return None


def _layout_for(message: dict[str, Any]) -> tuple[tuple[str, int, str], ...]:
    """The full 112-bit layout for a decoded message — header, ME and parity."""
    type_code = int(message["type_code"])
    subtype = message.get("subtype")
    kind = frame_kind(type_code, None if subtype is None else int(subtype))
    if kind is None:
        raise ValueError(
            f"ADS-B type code {type_code}"
            + (f" subtype {subtype}" if subtype is not None else "")
            + " is not in this adapter's scope. Every type code that is out is named in "
              "FORMAT_COVERAGE.md with the reason, so this is a decision rather than an "
              "omission"
        )
    return _HEADER + ME_LAYOUTS[kind] + _PARITY


# ================================================================ the codec: fields


def _callsign_of(bits: str) -> str:
    """Six-bit ICAO text, trailing pad characters stripped.

    Only TRAILING pads are stripped, and only spaces: a `#` — a value the alphabet does not
    define — is kept wherever it falls, so a malformed callsign is visible in the output rather
    than cleaned into something that looks like a real one.
    """
    out = []
    for index in range(0, len(bits) - 5, 6):
        out.append(CALLSIGN_ALPHABET[int(bits[index:index + 6], 2)])
    return "".join(out).rstrip(CALLSIGN_PAD)


def _callsign_bits(text: str, width: int) -> str:
    """A callsign as six-bit text of exactly `width` bits, space-padded.

    Refuses rather than truncating or substituting, for the reason the AIS adapter refuses a
    long vessel name: a callsign cut short on the wire reads as the aircraft's real callsign to
    every receiver. A `#` is refused too — it is not a character the alphabet can carry, and
    encoding it as some other value would misstate the field rather than fail.
    """
    characters = width // 6
    upper = (text or "").upper()
    if len(upper) > characters:
        raise ValueError(
            f"callsign is {len(upper)} characters and the ADS-B field holds {characters} "
            f"({text!r}) — refusing to truncate: a callsign cut short on the wire reads as the "
            "aircraft's real callsign to every receiver"
        )
    bits = []
    for character in upper.ljust(characters, CALLSIGN_PAD):
        value = CALLSIGN_ALPHABET.find(character)
        if value < 0 or character == CALLSIGN_UNDEFINED:
            raise ValueError(
                f"callsign contains {character!r}, which the ICAO six-bit alphabet cannot "
                f"carry ({text!r}) — refusing to substitute a placeholder, which would "
                "misstate the value rather than fail"
            )
        bits.append(f"{value:06b}")
    return "".join(bits)


def decode(bits: str) -> dict[str, Any]:
    """One extended squitter's bits into its named fields, sentinels LEFT IN PLACE.

    Every bit is decoded, reserved fields included, which is what lets `encode()` be an exact
    inverse. Translating "not available" into an absent CDM field is the adapter's job one
    layer up, where the decision can be declared in TRANSFORMS.
    """
    if len(bits) != FRAME_BITS:
        raise ValueError(
            f"ADS-B frame is {len(bits)} bits; an extended squitter is exactly {FRAME_BITS}. "
            "Refusing to decode a frame of another length rather than reporting whatever the "
            "padding says"
        )
    downlink_format = int(bits[0:5], 2)
    if downlink_format not in DF_IN_SCOPE:
        raise ValueError(
            f"downlink format {downlink_format} is not an extended squitter. This adapter "
            f"translates DF{DF_ADSB} and DF{DF_TISB}; the rest of Mode S overlays its parity "
            "with the aircraft address, so a frame's address can only be recovered by guessing "
            "it from a candidate list — that is a different adapter, and FORMAT_COVERAGE.md "
            "names it"
        )
    control = int(bits[5:8], 2)
    if downlink_format == DF_TISB and control in CF_REFUSED:
        raise ValueError(
            f"DF{DF_TISB} control field {control} — {CONTROL_FIELD[control]} — is not in this "
            "adapter's scope. CF 3 carries a DIFFERENT ME layout, so decoding it with the "
            "fine-format one would produce a plausible wrong position instead of an error; "
            "CF 4 addresses the ground station's link and CF 7 is reserved. See "
            "FORMAT_COVERAGE.md"
        )

    type_code = int(bits[ME_START:ME_START + 5], 2)
    subtype = (int(bits[ME_START + 5:ME_START + 8], 2)
               if type_code in (TC_VELOCITY, TC_AIRCRAFT_STATUS, TC_OPERATIONAL_STATUS)
               else None)
    kind = frame_kind(type_code, subtype)
    if kind is None:
        raise ValueError(
            f"ADS-B type code {type_code}"
            + (f" subtype {subtype}" if subtype is not None else "")
            + " is not in this adapter's scope. The type codes in scope are 0-8, 9-18, 19 "
              "(subtypes 1-4), 20-22, 28 (subtype 1) and 31 (subtype 0); every other one is "
              "named in FORMAT_COVERAGE.md with the reason it is out, so this is a decision "
              "rather than an omission"
        )

    fields: dict[str, Any] = {}
    offset = 0
    for name, width, kindmark in _HEADER + ME_LAYOUTS[kind] + _PARITY:
        chunk = bits[offset:offset + width]
        offset += width
        if kindmark == "c":
            fields[name] = _callsign_of(chunk)
        elif kindmark == "b":
            fields[name] = chunk == "1"
        elif kindmark == "x":
            fields[name] = f"{int(chunk, 2):0{width // 4}X}"
        else:
            fields[name] = int(chunk, 2)
    return fields


def encode(message: dict[str, Any]) -> str:
    """The exact inverse of `decode()`, except that the parity is COMPUTED and never copied.

    Exact, and a test asserts it over every fixture — that property is what makes the
    round-trip claim measurable rather than reviewable. The parity is the one deliberate
    exception: a frame carrying a stale parity field is discarded by every receiver, silently,
    so it is recomputed from the bits actually being emitted.
    """
    layout = _layout_for(message)
    bits = []
    for name, width, kindmark in layout:
        if name == "parity":
            continue
        value = message.get(name)
        if kindmark == "c":
            bits.append(_callsign_bits("" if value is None else str(value), width))
            continue
        if value is None:
            raise ValueError(
                f"cannot encode ADS-B type code {message.get('type_code')}: field {name!r} is "
                "missing. Every bit of the ME field is allocated, so there is no way to omit "
                "one — the caller must supply the standard's not-available value instead"
            )
        if kindmark == "b":
            bits.append("1" if value else "0")
        elif kindmark == "x":
            bits.append(f"{int(str(value), 16):0{width}b}")
        else:
            bits.append(f"{int(value):0{width}b}")
    head = "".join(bits)
    if len(head) != ME_END:
        raise AssertionError(  # pragma: no cover - layout invariant, asserted by a test
            f"encoded {len(head)} bits before the parity field, expected {ME_END}"
        )
    return head + f"{crc(head):0{PARITY_BITS}b}"


def _parse_frames(text: str | bytes) -> dict:
    """AVR text into `{frame: {...}, message: {...}}` — the parsed form.

    This is what a `.parsed.json` fixture holds and what the never-drop check is measured
    against. Both forms of every fixture ship for the reason the other binary adapters give:
    handed raw bytes the harness has no leaf structure to harvest, so `lossless` reports SKIP,
    and an adapter whose fixtures are all binary would show a green run with its most important
    check never executed.

    ONE frame per payload. A payload holding two is refused rather than half-translated, and
    that refusal is load-bearing here in a way it was not for AIS: two frames of opposite CPR
    parity are exactly what a global position decode needs, so accepting them would smuggle
    fusion in through the framing. Splitting a stream into frames is the feed reader's job.
    """
    if isinstance(text, (bytes, bytearray)):
        text = text.decode("ascii", errors="strict")
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        raise ValueError("ADS-B payload is empty — nothing to translate")
    if len(lines) != 1:
        raise ValueError(
            f"ADS-B payload holds {len(lines)} frames. This adapter translates exactly one "
            "frame per payload: it keeps no buffer across payloads, because a buffer is state "
            "and state in a translator is fusion done where nothing audits it. Two frames of "
            "opposite CPR parity are precisely what a global position decode needs, so "
            "accepting a pair here would be that decision made by accident"
        )
    frame = _parse_frame_line(lines[0])
    return {"frame": frame, "message": decode(_bits_of_hex(frame["hex"]))}


def _render_frame(message: dict[str, Any], envelope: dict[str, Any]) -> str:
    """One message's fields as the AVR line that carries it, parity computed.

    The envelope's prefix and receiver timestamp are reproduced where ingest parked them, which
    is what makes a re-emission byte-identical to the frame it came from.
    """
    body = _hex_of_bits(encode(message))
    prefix = envelope.get("prefix", PREFIX_BARE)
    if prefix == PREFIX_TIMESTAMPED:
        return f"{prefix}{envelope.get('timestamp_raw', '0' * TIMESTAMP_HEX_CHARS)}{body};"
    if prefix == PREFIX_BARE:
        return f"{PREFIX_BARE}{body}{FRAME_TERMINATOR_CHAR}"
    return body


# ====================================================================== CPR


def cpr_longitude_zones(latitude: float) -> int:
    """How many longitude zones the CPR grid uses at this latitude — the NL function.

    The three special cases are the standard's, not conveniences: the zone count collapses to
    one at the poles, and the closed form divides by cos(latitude)^2.
    """
    if latitude == 0.0:
        return 59
    if abs(latitude) == 87.0:
        return 2
    if abs(latitude) > 87.0:
        return 1
    inner = 1.0 - (1.0 - math.cos(math.pi / (2 * CPR_ZONES))) / \
        math.cos(math.radians(latitude)) ** 2
    return int(math.floor(2 * math.pi / math.acos(inner)))


def cpr_decode_local(cpr_lat: int, cpr_lon: int, cpr_format: int,
                     reference: tuple[float, float], *, span: float) -> tuple[float, float]:
    """One frame's CPR values plus a reference position -> a coordinate.

    The reference selects which zone the aircraft is in; the CPR values place it inside that
    zone. Unambiguous only within roughly one zone of the reference — see the module docstring
    on what that risk is and how it is recorded rather than checked.
    """
    ref_lat, ref_lon = reference
    d_lat = span / (60 - cpr_format)
    lat_fraction = cpr_lat / CPR_SCALE
    zone_lat = math.floor(ref_lat / d_lat) + math.floor(
        (ref_lat % d_lat) / d_lat - lat_fraction + 0.5)
    latitude = d_lat * (zone_lat + lat_fraction)

    zones = max(cpr_longitude_zones(latitude) - cpr_format, 1)
    d_lon = span / zones
    lon_fraction = cpr_lon / CPR_SCALE
    zone_lon = math.floor(ref_lon / d_lon) + math.floor(
        (ref_lon % d_lon) / d_lon - lon_fraction + 0.5)
    return latitude, d_lon * (zone_lon + lon_fraction)


def cpr_encode(latitude: float, longitude: float, cpr_format: int,
               *, span: float) -> tuple[int, int]:
    """A coordinate -> the CPR values that carry it. Needs NO reference position.

    That asymmetry is why egress is straightforward where ingest is not: encoding throws the
    zone away, and it is recovering the zone that needs either a second frame or a reference.
    """
    d_lat = span / (60 - cpr_format)
    lat_value = math.floor(CPR_SCALE * ((latitude % d_lat) / d_lat) + 0.5)
    rounded_lat = d_lat * (lat_value / CPR_SCALE + math.floor(latitude / d_lat))

    zones = max(cpr_longitude_zones(rounded_lat) - cpr_format, 1)
    d_lon = span / zones
    lon_value = math.floor(CPR_SCALE * ((longitude % d_lon) / d_lon) + 0.5)
    return int(lat_value) % CPR_SCALE, int(lon_value) % CPR_SCALE


# ====================================================================== field arithmetic


def baro_altitude_feet(raw: int) -> tuple[int | None, str]:
    """The BAROMETRIC altitude field in feet, and the sentence saying how it was read.

    Type codes 0 and 9-18 only. Q = 1 is the 25-foot encoding and is decoded. Q = 0 is the
    100-foot Gillham encoding used above 50 175 ft and is deliberately NOT: the permutation into
    the Mode C layout is either exactly right or yields a confident wrong flight level, and this
    repository has no pinned reference for it. Returning None with a reason is the honest
    outcome; the raw bits are parked so a consumer holding the reference can decode what we
    would not.
    """
    if raw == 0:
        return None, "the twelve-bit altitude field is all zero — altitude not available"
    bits = f"{raw:012b}"
    if bits[BARO_Q_BIT_INDEX] != "1":
        return None, (
            "Q bit clear — the 100-foot Gillham (reflected Gray) encoding used above 50 175 ft, "
            "which this adapter does not decode: the permutation into the Mode C layout is "
            "either exactly right or produces a confident wrong flight level, and no pinned "
            "reference for it exists here. The raw twelve bits are parked at "
            "attributes.unresolved_raw"
        )
    steps = int(bits[:BARO_Q_BIT_INDEX] + bits[BARO_Q_BIT_INDEX + 1:], 2)
    return (steps * BARO_STEP_FEET - BARO_OFFSET_FEET,
            f"Q bit set — {BARO_STEP_FEET}-foot increments, "
            f"{steps} x {BARO_STEP_FEET} - {BARO_OFFSET_FEET} ft")


def baro_altitude_raw(feet: float) -> int:
    """Feet back into the 12-bit barometric field, Q = 1. The inverse of the decoded half only.

    A Gillham altitude cannot be produced here for the same reason it is not read, so a value
    the 25-foot encoding cannot express is refused rather than approximated into one it can.
    """
    steps = round((feet + BARO_OFFSET_FEET) / BARO_STEP_FEET)
    if not 0 <= steps < (1 << 11):
        raise ValueError(
            f"altitude {feet} ft does not fit the ADS-B 25-foot encoding "
            f"({-BARO_OFFSET_FEET} ft to "
            f"{(1 << 11) * BARO_STEP_FEET - BARO_OFFSET_FEET - BARO_STEP_FEET} ft). "
            "Above that the standard uses the 100-foot Gillham encoding, which this adapter "
            "does not produce — refusing rather than emitting a wrong flight level"
        )
    bits = f"{steps:011b}"
    return int(bits[:BARO_Q_BIT_INDEX] + "1" + bits[BARO_Q_BIT_INDEX:], 2)


def gnss_height_m(raw: int) -> tuple[int | None, str]:
    """The GNSS-HEIGHT field in metres: the plain decimal value of all twelve bits.

    Type codes 20-22 only. No Q bit, no offset, no 25-foot increment — the same twelve wire bits
    mean something completely different here than on a barometric frame, which is why this is a
    separate function rather than a flag on one.

    All twelve bits zero is read as "not available", and that reading is THIS ADAPTER'S
    DECISION rather than a documented sentinel: the reference states it for the barometric field
    and is silent for this one. The safe direction decides it. Reading 0 as a measurement would
    place an airborne aircraft exactly on the ellipsoid — a confident false statement — whereas
    reading it as absent loses at most a genuine 0 m and leaves the wire value in
    `attributes.unresolved_raw` for anyone who disagrees. `attributes.altitude_basis` records
    which of the two happened, so the decision is auditable rather than a property of this code.
    """
    if raw == 0:
        return None, (
            "the twelve-bit GNSS-height field is all zero, read as not available. The reference "
            "documents that meaning for the BAROMETRIC field and is silent for this one, so this "
            "is the adapter's decision taken in the safe direction: 0 m would place an airborne "
            "aircraft on the ellipsoid, and an absent altitude is recoverable where a false one "
            "is not. The raw value is kept"
        )
    return raw, (
        f"the plain decimal value of all twelve bits, in metres — {raw} m above the ellipsoid. "
        "No Q bit, no offset and no 25-foot increment: this field is not the barometric one")


def gnss_height_raw(metres: float) -> int:
    """Metres back into the 12-bit GNSS-height field. The exact inverse of `gnss_height_m`.

    Out of range is an ERROR and never a saturation. The field holds 0 to 4095 m, so a cruise
    level does not fit — clipping one to 4095 m would put an airliner at 13 400 ft on a
    consumer's map, which is a plausible-looking wrong altitude rather than a visible failure.
    """
    value = round(metres)
    if not 0 <= value <= GNSS_HEIGHT_MAX_M:
        raise ValueError(
            f"GNSS height {metres} m does not fit the ADS-B twelve-bit field, which holds 0 to "
            f"{GNSS_HEIGHT_MAX_M} m (about "
            f"{round(GNSS_HEIGHT_MAX_M / FOOT_M):d} ft) as a plain decimal value. Refusing to "
            "saturate: a cruise level clipped to the top of the field reads as a real low "
            "altitude to every consumer. A barometric frame (type code 9-18) is the message "
            "that carries higher altitudes"
        )
    return value


def movement_knots(raw: int) -> tuple[float | None, str, bool]:
    """The surface movement field in knots, its wording, and whether the value is a FLOOR.

    Zero is not available. One is "stopped", which IS a measurement of stillness and becomes
    0.0 — the mirror of the AIS rule that a stationary life raft has been measured. 124 means
    "175 kt or above", a floor rather than a speed, so the number is kept and the floor is
    recorded exactly as AIS's 102.2 kn is. 125-127 are reserved and yield nothing.
    """
    if raw == MOVEMENT_NOT_AVAILABLE:
        return None, "ground speed not available", False
    if raw == MOVEMENT_STOPPED:
        return 0.0, "stopped (below 0.125 kt)", False
    if raw == MOVEMENT_AT_OR_ABOVE_MAXIMUM:
        return MOVEMENT_MAXIMUM_KNOTS, f"{MOVEMENT_MAXIMUM_KNOTS:.0f} kt or above", True
    if raw in MOVEMENT_RESERVED:
        return None, f"reserved movement value {raw}", False
    for low, high, base, step in MOVEMENT_BUCKETS:
        if low <= raw <= high:
            knots = base + (raw - low) * step
            return knots, f"{knots:g} kt", False
    raise ValueError(f"movement value {raw} is outside the seven-bit field")


def movement_raw(knots: float) -> int:
    """Knots back into the movement field: the bucket whose speed is nearest.

    Exact for any value this module produced, which is what the round trip needs; nearest for
    anything else, because the field IS a bucket table and there is no finer answer to give.
    """
    candidates = [MOVEMENT_STOPPED] + [
        raw for low, high, _, _ in MOVEMENT_BUCKETS for raw in range(low, high + 1)
    ] + [MOVEMENT_AT_OR_ABOVE_MAXIMUM]
    return min(candidates, key=lambda raw: abs((movement_knots(raw)[0] or 0.0) - knots))


def mode_a_code(raw: int) -> str:
    """The 13-bit Mode A identity field as its four octal digits.

    Each digit is read from three non-adjacent bits, so the indices come from MODE_A_BITS
    rather than from a slice: an off-by-one here produces a plausible wrong squawk, and 7500
    (unlawful interference) differs from 7600 (radio failure) by exactly one digit.
    """
    bits = f"{raw:013b}"
    digits = []
    for digit in ("A", "B", "C", "D"):
        four, two, one = MODE_A_BITS[digit]
        digits.append(str(int(bits[four]) * 4 + int(bits[two]) * 2 + int(bits[one])))
    return "".join(digits)


def mode_a_raw(code: str) -> int:
    """The inverse: four octal digits back into the interleaved 13-bit field."""
    if len(code) != 4 or any(character not in "01234567" for character in code):
        raise ValueError(
            f"Mode A code {code!r} is not four octal digits — refusing to emit an identity "
            "code that no interrogator would read back as the one intended"
        )
    bits = ["0"] * 13
    for digit, value in zip(("A", "B", "C", "D"), (int(c) for c in code)):
        four, two, one = MODE_A_BITS[digit]
        bits[four], bits[two], bits[one] = str(value >> 2 & 1), str(value >> 1 & 1), str(value & 1)
    return int("".join(bits), 2)


def _offset_by_one(raw: int, *, step: float = 1.0, multiplier: int = 1) -> float | None:
    """The ADS-B family sentinel: 0 means not available, and v means (v - 1) units.

    One function rather than nine open-coded subtractions, because the shape is the same in
    every field that carries it and the failure — forgetting the offset — is a value that is
    one unit wrong and looks entirely plausible.
    """
    return None if raw == 0 else (raw - 1) * step * multiplier


def _signed(magnitude: float | None, sign_bit: int) -> float | None:
    """A magnitude and its direction bit, where 1 means the negative direction."""
    return None if magnitude is None else (-magnitude if sign_bit else magnitude)


# ====================================================================== translation

#: The standard's own "not available" value for every field this adapter can emit. Used to
#: build a frame for a CDM object that never came from ADS-B: all 56 ME bits are allocated, so
#: there is no way to omit a field, and the only honest encoding of "we do not know" is the
#: value the format reserves for it.
NOT_AVAILABLE: dict[str, Any] = {
    "capability": 0,
    "surveillance_status": 0, "nic_supplement_b": False, "altitude_raw": 0,
    "time_sync": False, "cpr_format": 0, "cpr_lat": 0, "cpr_lon": 0,
    "movement_raw": MOVEMENT_NOT_AVAILABLE, "track_valid": False, "ground_track_raw": 0,
    "emitter_category": 0, "callsign": "",
    "subtype": 1, "intent_change": False, "ifr_capability": False,
    "nav_uncertainty_velocity": 0,
    "ew_sign": 0, "ew_velocity_raw": 0, "ns_sign": 0, "ns_velocity_raw": 0,
    "heading_valid": False, "heading_raw": 0, "airspeed_type": 0, "airspeed_raw": 0,
    "vertical_rate_source": 0, "vertical_rate_sign": 0, "vertical_rate_raw": 0,
    "reserved_velocity": 0, "gnss_baro_diff_sign": 0, "gnss_baro_diff_raw": 0,
    "emergency_state": 0, "mode_a_code_raw": 0, "reserved_status": 0,
    "capability_class": 0, "operational_mode": 0, "version": 0,
    "nic_supplement_a": False, "nac_position": 0, "geometric_vertical_accuracy": 0,
    "source_integrity_level": 0, "nic_baro": False, "horizontal_reference_direction": 0,
    "sil_supplement": False, "reserved_status_b": 0,
}

#: The type codes an object that never came from ADS-B is emitted as. **Both are the NIC 0
#: members of their range.** The type code encodes a navigation integrity category, so it is a
#: claim about accuracy and not only a message selector — defaulting to type code 9 or 20 would
#: assert a containment radius nobody measured.
DEFAULT_TYPE_CODE_NO_ALTITUDE = 18
DEFAULT_TYPE_CODE_WITH_ALTITUDE = 22

#: (parsed field, the value that means "the source does not know"). Walked to build
#: `attributes.unavailable_fields`, so "the aircraft said it does not know" and "this adapter
#: had nothing to say" stay distinguishable in the CDM.
UNAVAILABLE_WHEN: tuple[tuple[str, Any], ...] = (
    ("altitude_raw", 0),
    ("movement_raw", MOVEMENT_NOT_AVAILABLE),
    ("emitter_category", 0),
    ("ew_velocity_raw", 0), ("ns_velocity_raw", 0),
    ("airspeed_raw", 0), ("vertical_rate_raw", 0), ("gnss_baro_diff_raw", 0),
    ("callsign", ""),
)

#: (parsed field, the status bit that validates it). A DIFFERENT mechanism from the table
#: above and kept apart from it on purpose: these two fields are absent because the aircraft
#: cleared a validity bit, not because they hold a reserved value, and collapsing the two
#: would lose which of the two statements the source actually made.
UNAVAILABLE_WHEN_FLAG_CLEAR: tuple[tuple[str, str], ...] = (
    ("ground_track_raw", "track_valid"),
    ("heading_raw", "heading_valid"),
)


class AdsbAdapter(Adapter):
    """1090ES extended squitter frames in, CDM out; an Entity or a Track out to DF17 frames."""

    name = "adsb"
    version = "1.0.0"
    direction = "bidirectional"
    system = SYSTEM

    TRANSFORMS = {
        "message.altitude_raw":
            "the twelve-bit altitude field, and it holds TWO DIFFERENT ENCODINGS of two "
            "different measurements — which is the whole of gap 9. On a type code 20-22 frame "
            "it is the plain decimal value of all twelve bits in METRES (no Q bit, no offset, "
            "no 25-foot increment), it is a GNSS height, and it becomes Position.alt_m "
            "unconverted; the field therefore saturates at 4095 m and a higher altitude is an "
            "encode error rather than a clipped value. On a type code 0 or 9-18 frame it is a "
            "BAROMETRIC pressure altitude in 25-foot steps offset by 1000 ft behind a Q bit, "
            "and it is PARKED at attributes.baro_altitude_ft because alt_m means height above "
            "the ellipsoid and the two differ by hundreds of metres. A clear Q bit on a "
            "barometric frame is the 100-foot Gillham encoding, which this adapter does not "
            "decode: the altitude is absent and the raw bits are parked. All-zero becomes an "
            "absent altitude on both, never 0",
        "message.movement_raw":
            "the surface movement bucket table, knots -> metres per second. 0 means not "
            "available and becomes null; 1 means 'stopped, below 0.125 kt' and becomes 0.0, "
            "because stillness IS a measurement; 124 means '175 kt or above' and is kept with "
            "the floor recorded at attributes.movement_at_or_above_maximum, exactly as AIS's "
            "102.2 kn is; 125-127 are reserved and become null",
        "message.ground_track_raw":
            "128 steps of 360 degrees -> Kinematics.course_deg, an exact and reversible scale "
            "change. Valid only while track_valid is set; cleared, the course is absent and "
            "the field is named in attributes.unavailable_fields",
        "message.ew_velocity_raw":
            "the east-west velocity component. 0 means not available; otherwise (v - 1) knots, "
            "times four on the supersonic subtypes. Combined with the north-south component "
            "into Kinematics.speed_mps and course_deg — and a MISSING component yields no "
            "speed and no course at all, rather than a speed computed from one axis, which "
            "would render as a bearing of exactly 000 or 090 and look like a measurement",
        "message.ns_velocity_raw":
            "the north-south velocity component, on the same terms as the east-west one",
        "message.heading_raw":
            "1024 steps of 360 degrees -> attributes.heading_deg (gap 7 — the CDM has no "
            "heading field distinct from course). Valid only while heading_valid is set. Note "
            "the datum: an ADS-B heading is referenced to MAGNETIC north unless a type code 31 "
            "frame's HRD bit says otherwise, while an AIS true heading is referenced to true "
            "north — which is why gap 7 now asks for a datum and not only a field",
        "message.airspeed_raw":
            "0 means not available; otherwise (v - 1) knots, times four on the supersonic "
            "subtypes. PARKED at attributes.airspeed_kt and deliberately NOT written to "
            "Kinematics.speed_mps, which is a speed over the ground: an indicated or true "
            "airspeed is a different measurement, and the difference between the two is the "
            "wind (gap 10)",
        "message.vertical_rate_raw":
            "0 means not available and becomes null, never level flight; otherwise (v - 1) x "
            "64 ft/min -> Kinematics.climb_mps, feet per minute to metres per second. The sign "
            "convention already matches the CDM's, negative being a descent",
        "message.gnss_baro_diff_raw":
            "0 means not available; otherwise (v - 1) x 25 ft -> "
            "attributes.gnss_baro_difference_ft. Parked, and it is the offset that relates "
            "gap 9's two altitudes to each other, so it belongs with whichever field closes "
            "that gap",
    }

    # Dotted paths in the PARSED form that this adapter maps to canonical fields or places
    # under a name of its own. Everything else is collected by `lossless.residual()` and parked
    # with its structure intact, which is also what lets egress rebuild the frame.
    #
    # Kept as data rather than buried in the translation so that "what does this adapter
    # understand?" is answerable by reading one list. Note what is absent on purpose: the whole
    # frame envelope, the reserved fields, the intent-change and IFR-capability flags, the
    # navigation-uncertainty and integrity categories, the capability class, the operational
    # mode, the time-sync bit and the direction bits are NOT consumed, so they park
    # automatically. An unmapped field parked is the never-drop rule working, not a gap.
    CONSUMED = (
        "message.df",
        "message.capability",
        "message.icao",
        "message.type_code",
        "message.subtype",
        "message.parity",
        "message.cpr_lat",
        "message.cpr_lon",
        "message.cpr_format",
        "message.altitude_raw",
        "message.surveillance_status",
        "message.movement_raw",
        "message.ground_track_raw",
        "message.callsign",
        "message.emitter_category",
        "message.ew_velocity_raw",
        "message.ns_velocity_raw",
        "message.heading_raw",
        "message.airspeed_raw",
        "message.vertical_rate_raw",
        "message.gnss_baro_diff_raw",
        "message.emergency_state",
        "message.mode_a_code_raw",
        "message.version",
        "message.horizontal_reference_direction",
    )

    def __init__(self, clock: times.Clock | None = None, *, synthetic: bool = True,
                 reference_position: tuple[float, float] | None = None) -> None:
        """`reference_position` is the receiver's own surveyed antenna position, or None.

        It is CONFIGURATION and not state: a constant of the deployment, supplied here exactly
        like the injected clock, never accumulated from the data stream and never changing
        between frames. That distinction is what keeps a local CPR decode inside the adapter
        contract while global even/odd pairing stays outside it — see the module docstring.

        None is the default, and therefore the default behaviour is the conservative one: no
        position is decoded at all, and the CPR fields are parked for a fusion layer that holds
        a proper pair.
        """
        super().__init__(clock, synthetic=synthetic)
        if reference_position is not None:
            latitude, longitude = reference_position
            if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
                raise ValueError(
                    f"reference_position {reference_position} is not a coordinate. A CPR local "
                    "decode is measured FROM this point, so a bad reference silently moves "
                    "every aircraft it decodes rather than failing"
                )
            reference_position = (float(latitude), float(longitude))
        self._reference = reference_position

    # ------------------------------------------------------------------ ingest

    def to_cdm(self, raw: bytes | dict) -> list[CDMBase]:
        """One ADS-B frame -> [Entity, Event]. Raises on a payload it cannot read."""
        parsed = self._as_parsed(raw)
        message = parsed.get("message")
        if not isinstance(message, dict) or "type_code" not in message:
            raise ValueError(
                "ADS-B payload has no decoded message — refusing to translate; top-level keys: "
                f"{sorted(parsed) if isinstance(parsed, dict) else type(parsed).__name__}"
            )
        icao = str(message.get("icao") or "")
        if not icao:
            raise ValueError(
                f"ADS-B type code {message.get('type_code')} frame carries no address — "
                "refusing to translate. The 24-bit address is the only identifier 1090ES "
                "repeats across transmissions, so an object without one could never be "
                "recognised as the same aircraft twice"
            )

        received_at = self.now()
        # A frame states no time whatsoever, so `observed_at` IS the receipt instant and the
        # basis says so rather than implying the aircraft stated it. The `@` form's counter is
        # not a clock and is not used here — see the module docstring.
        observed_at = received_at
        observed_basis = (
            "an ADS-B extended squitter carries no time field at all — not a date, not a "
            "second of the minute. The receipt instant is used, and the frame itself states "
            "nothing about when. The AVR '@' timestamp, where present, is a free-running "
            "12 MHz receiver counter and not a wall clock, so it is parked and never read as "
            "one"
        )

        id_system = _source_id_system(message)
        source = self.source_ref()
        entity_id = ids.derive(id_system, icao, kind="entity")
        # Keyed on BOTH the address and the instant, for the reason the other adapters give:
        # an address identifies the AIRFRAME and repeats on every frame, so an event id keyed
        # on it alone would collapse a whole flight into one event.
        event_id = ids.derive(id_system, f"{icao}@{times.render(observed_at)}", kind="event")

        emergency, emergency_note = _emergency(message)
        attributes = _attributes(message, parsed, self.CONSUMED, self._reference,
                                 observed_basis=observed_basis)

        entity = Entity(
            source=source,
            entity_id=entity_id,
            source_ids=[{"system": id_system, "external_id": icao}],
            entity_type=_entity_type(message),
            # 1090ES states an identity and it must not be trusted: nothing in it is
            # authenticated. UNKNOWN is not a collapse here and it is not mere silence either
            # — see attributes.affiliation_basis.
            affiliation=Affiliation.UNKNOWN,
            symbol=sidc_from_affiliation(Affiliation.UNKNOWN, synthetic=self._synthetic),
            position=_position(message, self._reference),
            kinematics=_kinematics(message),
            valid_from=observed_at,
            # ADS-B has no staleness field. How long a frame stays good depends on the
            # transmission interval its type code implies, which is a judgement about data and
            # therefore fusion's to make, not a translator's.
            valid_to=None,
            confidence=None,
            attributes={k: v for k, v in attributes.items() if v is not None},
        )

        kind = str(attributes["adsb_frame_kind"])
        event = Event(
            source=source,
            source_ids=[{"system": id_system, "external_id": icao}],
            event_id=event_id,
            # A frame carrying neither a position nor motion is not a track update: saying so
            # would claim a position it does not have, which is the AIS type 5 argument. An
            # emergency the standard itself declares — a surveillance status of 1, or a type
            # code 28 emergency state of 1 to 6 — is an ALERT and nothing else is.
            event_type=(EventType.ALERT if emergency else
                        EventType.TRACK_UPDATE
                        if kind in KINDS_WITH_POSITION or kind in KINDS_WITH_MOTION
                        else EventType.STATUS_CHANGE),
            severity=Severity.CRITICAL if emergency else Severity.INFO,
            related_entities=[entity_id],
            # No geometry: a frame states one position and it belongs to the aircraft. Copying
            # it onto the event would be a second representation of one measurement.
            geometry=None,
            payload={
                "adsb_type_code": int(message["type_code"]),
                "adsb_frame_kind": kind,
                "observed_at_basis": observed_basis,
                "received_at_basis": (
                    "the injected clock. An ADS-B frame stream carries no wall-clock "
                    "timestamp — the AVR '@' field is a receiver counter — so unlike AIS there "
                    "is no feed-supplied delivery instant to prefer over ours"),
                "event_id_basis": "frame address + observed_at",
                "frame_parity": int(message["parity"]),
                "parity_basis": (
                    f"the frame's 24-bit parity field, {int(message['parity']):06X}, verified "
                    f"as the Mode S CRC of its first {ME_END} bits. A frame that fails is "
                    "refused rather than best-effort decoded"),
                "severity_basis": emergency_note,
            },
            observed_at=observed_at,
            received_at=received_at,
        )
        return [entity, event]

    # ------------------------------------------------------------------- egress

    def from_cdm(self, objects: list[CDMBase]) -> bytes:
        """One Entity or one Track -> the DF17 frames that restate it, as ASCII bytes.

        Exactly one emittable object. An Entity emits the type code it arrived as (or a NIC 0
        position frame, for an Entity that never came from ADS-B); a Track emits one position
        frame per sample, which is the only shape 1090ES has for a history.

        An `Event` in the list is not emittable on its own — ADS-B has no report object
        separate from the frame — and unlike AIS it does not even supply a time, because no
        frame has a time field to put one in.
        """
        emittable = [o for o in objects if isinstance(o, (Entity, Track))]
        if len(emittable) != 1:
            kinds = [getattr(o, "object_kind", type(o).__name__) for o in objects]
            raise ValueError(
                f"from_cdm() emits the frames for ONE object and was given "
                f"{len(emittable)} emittable ones (kinds: {kinds or 'none'}). Push several "
                "objects as several transmissions — an extended squitter addresses one "
                "aircraft. An Event alone is not emittable: the frame is both the object and "
                "the report about it."
            )

        subject = emittable[0]
        lines = (self._track_frames(subject) if isinstance(subject, Track)
                 else self._entity_frames(subject))
        return (FRAME_TERMINATOR.join(lines) + FRAME_TERMINATOR).encode("ascii")

    def _entity_frames(self, entity: Entity) -> list[str]:
        """An Entity as the frame it arrived as, or as the frames a transponder would send.

        1090ES has no frame that carries both a position and a velocity: an airborne position
        frame states where, a type 19 frame states how fast, and a real transponder interleaves
        the two. So an Entity holding both is TWO frames rather than one frame with the velocity
        dropped — that is what the format actually does, and it is the difference between an
        egress that loses a measurement and one that does not.

        The exception is an Entity that came FROM ADS-B. Its parked type code says which frame
        it was, so exactly that frame is re-emitted: a surface position frame carries movement
        and ground track in the same 56 bits, and synthesising a second frame beside it would
        invent a transmission the aircraft never made — and would break the byte-exact round
        trip that is this direction's strongest claim.
        """
        envelope = _parked_frame(entity.attributes.get("source_extras") or {})
        if entity.attributes.get("adsb_type_code") is not None:
            return [_render_frame(_message_from_entity(entity), envelope)]

        frames = []
        if entity.position is not None:
            frames.append(_render_frame(_message_from_entity(entity), envelope))
        if _states_motion(entity.kinematics):
            frames.append(_render_frame(_velocity_message(entity), envelope))
        if not frames:
            raise ValueError(
                f"cannot emit ADS-B for entity {entity.entity_id}: it states no position, no "
                "motion, and no adsb_type_code to say which frame it came from. Every frame "
                "type in scope carries at least one of those, so there is nothing to transmit "
                "— and a frame of pure not-available values would put an aircraft on 1090 MHz "
                "saying nothing about itself"
            )
        return frames

    def _track_frames(self, track: Track) -> list[str]:
        """A Track as one airborne position frame per sample, in the track's own order.

        Two decisions worth defending. The type code follows the MEASUREMENT: a sample stating
        `alt_m` gets type code 22, whose altitude field is a GNSS height, and one that does not
        gets type code 18, whose altitude field is emitted as not-available. Writing an HAE
        figure into a barometric field would be exactly the conflation this adapter refuses on
        ingest, and dropping the altitude instead would lose real data.

        And the CPR parity is ALWAYS EVEN. Alternating even and odd would invite a receiver to
        globally pair two samples taken at different times, and a global decode of a
        non-simultaneous pair yields a position the aircraft was never at — so the one frame
        shape that cannot be misused is the one that is emitted.
        """
        icao = _address_of(track)
        lines = []
        for sample in track.samples:
            altitude_m = sample.position.alt_m
            message = dict(NOT_AVAILABLE)
            message.update({
                "df": DF_ADSB,
                "icao": icao,
                "type_code": (DEFAULT_TYPE_CODE_WITH_ALTITUDE if altitude_m is not None
                              else DEFAULT_TYPE_CODE_NO_ALTITUDE),
                "cpr_format": 0,
            })
            cpr_lat, cpr_lon = cpr_encode(sample.position.lat, sample.position.lon,
                                          0, span=CPR_SPAN_AIRBORNE)
            message["cpr_lat"], message["cpr_lon"] = cpr_lat, cpr_lon
            if altitude_m is not None:
                # Type code 22 is a GNSS-height frame, so its altitude field counts whole
                # metres — `alt_m` goes in as-is rather than through a foot conversion.
                message["altitude_raw"] = gnss_height_raw(altitude_m)
            lines.append(_render_frame(message, {}))
        return lines

    # ------------------------------------------------------------------ helpers

    def _as_parsed(self, raw: bytes | dict) -> dict:
        """AVR text -> the parsed dict form; a dict passes straight through."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, (bytes, bytearray, str)):
            text = raw.decode("ascii") if isinstance(raw, (bytes, bytearray)) else raw
            if text.lstrip().startswith("{"):
                # A .json fixture handed over as bytes. Distinguished by inspection rather than
                # by suffix, because the harness does not tell an adapter what it opened.
                return json.loads(text)
            return _parse_frames(text)
        raise TypeError(
            f"ADS-B adapter takes AVR frame text as bytes or str, a JSON string, or a parsed "
            f"dict, got {type(raw).__name__}"
        )


# ---------------------------------------------------------------- ingest helpers


def _control_field(message: dict) -> int | None:
    """DF18's control field, or None on a DF17 frame where those bits mean something else."""
    return (int(message.get("capability", 0))
            if int(message.get("df", DF_ADSB)) == DF_TISB else None)


def _source_id_system(message: dict) -> str:
    """Which id space this frame's address belongs to.

    DF18 CF 1 and CF 5 state that the address is anonymous or self-assigned. Filing one under
    ICAO24 would let fusion join the contact to a real airframe that happens to share the
    number — a wrong join is worse than no join, because it merges two aircraft into one track.
    """
    control = _control_field(message)
    return NONICAO_SYSTEM if control in CF_NON_ICAO else ICAO_SYSTEM


def _entity_type(message: dict) -> EntityType:
    """What the CDM says this transmitter IS.

    PLATFORM unless the emitter category says otherwise, and it only ever says otherwise for
    an obstacle: a point, cluster or line obstacle is a fixed structure and becomes FACILITY,
    the same call the AIS adapter makes for an aid to navigation. A light aircraft, a heavy and
    a rotorcraft are all PLATFORM — inventing a finer CDM distinction from the category byte
    would put a judgement in a translator, exactly as an AIS ship type does not.

    Note the limit, which is named rather than worked around: the emitter category arrives only
    in an identification frame, so an obstacle's POSITION frame is a PLATFORM until an
    identification frame says otherwise. Reconciling the two is a cross-frame join, and this
    adapter does not hold one.
    """
    type_code = int(message.get("type_code", 0))
    category = message.get("emitter_category")
    if isinstance(category, int) and (type_code, category) in OBSTACLE_CATEGORIES:
        return EntityType.FACILITY
    return EntityType.PLATFORM


def _position_source(message: dict) -> tuple[PositionSource, str]:
    """How the fix was obtained, and the sentence saying how we concluded that.

    The one case that is not GNSS is the one that matters most in a denied environment: DF18
    CF 2 and CF 5 are fine-format TIS-B, a ground station rebroadcasting a surveillance track
    it derived by other means. Calling that GNSS would promise a fix that survives jamming,
    which is the dangerous direction — the same reason the AIS adapter refuses to call an
    integrated navigation system INERTIAL.
    """
    control = _control_field(message)
    if control in CF_TISB_SURVEILLANCE:
        return PositionSource.ESTIMATED, (
            f"DF{DF_TISB} control field {control} — {CONTROL_FIELD[control]}: a ground "
            "station's rebroadcast of a surveillance track it derived by other means, not the "
            "aircraft's own GNSS fix. ESTIMATED understates rather than overstates the fix, "
            "which is the safe direction for this field")
    if control in CF_RELAY:
        return PositionSource.GNSS, (
            f"DF{DF_TISB} control field {control} — {CONTROL_FIELD[control]}: a rebroadcast of "
            "a genuine ADS-B message, so the original fix IS the aircraft's own GNSS. The relay "
            "is recorded at attributes.adsb_relay")
    if control is not None:
        return PositionSource.GNSS, (
            f"DF{DF_TISB} control field {control} — {CONTROL_FIELD[control]}: an ADS-B "
            "transmitting device, so the position is its own GNSS fix")
    return PositionSource.GNSS, (
        f"DF{DF_ADSB} extended squitter — an ADS-B position is the aircraft's own GNSS fix")


def _position_span(message: dict) -> tuple[float, int]:
    """The CPR span for this frame's type code, and the range its local decode holds within."""
    if int(message.get("type_code", 0)) in TC_SURFACE_POSITION:
        return CPR_SPAN_SURFACE, CPR_LOCAL_RANGE_NM_SURFACE
    return CPR_SPAN_AIRBORNE, CPR_LOCAL_RANGE_NM_AIRBORNE


def _states_position(message: dict) -> bool:
    """Whether this frame carries position fields that mean anything at all.

    Type code 0 is "no position information": the CPR fields are present and carry nothing.
    They are zero, and zero CPR values are NOT a position on the equator — they are the absence
    of one. This is checked by TYPE CODE rather than by falsiness for exactly that reason, and
    it is the mirror of the rule that a real 0/0 coordinate must survive.
    """
    type_code = int(message.get("type_code", 0))
    if type_code == TC_NO_POSITION_INFORMATION:
        return False
    kind = frame_kind(type_code, message.get("subtype"))
    return kind in KINDS_WITH_POSITION and "cpr_lat" in message and "cpr_lon" in message


def _position_decode(message: dict, reference: tuple[float, float] | None
                     ) -> tuple[tuple[float, float] | None, str]:
    """The coordinate this frame states, if any, and the sentence explaining the outcome.

    Four outcomes, and each one is a different fact: the frame carries no position; there is no
    reference to decode against; the decode succeeded; or the decode produced something outside
    the world, which is a defect rather than data.
    """
    type_code = int(message.get("type_code", 0))
    if not _states_position(message):
        if type_code == TC_NO_POSITION_INFORMATION:
            return None, (
                f"type code {TC_NO_POSITION_INFORMATION} states NO POSITION INFORMATION. Its "
                "CPR fields are zero, and zero CPR values are the absence of a position and "
                "not a position on the equator")
        return None, f"an ADS-B type code {type_code} frame carries no position fields"

    if reference is None:
        span, _ = _position_span(message)
        return None, (
            "a single extended squitter states a position only WITHIN a CPR zone, and no "
            "reference position is configured on this adapter. Recovering the zone needs "
            "either a second frame of the opposite parity — which is a join across time and "
            "therefore fusion, see FORMAT_COVERAGE.md — or a receiver reference position. The "
            f"raw CPR fields (span {span:.0f} degrees) are parked verbatim so a fusion layer "
            "holding a proper pair can decode them itself")

    span, range_nm = _position_span(message)
    latitude, longitude = cpr_decode_local(
        int(message["cpr_lat"]), int(message["cpr_lon"]), int(message.get("cpr_format", 0)),
        reference, span=span)
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        raise ValueError(
            f"CPR local decode produced {latitude}/{longitude}, which is outside the world. "
            f"The reference position {reference} and the frame's CPR values are inconsistent — "
            "refusing to place an aircraft at a coordinate that cannot exist"
        )
    return (latitude, longitude), (
        f"CPR local decode against the configured receiver reference {reference[0]}/"
        f"{reference[1]}, CPR parity {'odd' if int(message.get('cpr_format', 0)) else 'even'}, "
        f"zone span {span:.0f} degrees. Unambiguous only within about {range_nm} NM of that "
        "reference: further away the decode returns a plausible coordinate in the WRONG zone "
        "and no single frame can reveal that it did, which is why the raw CPR fields are parked")


def _position(message: dict, reference: tuple[float, float] | None) -> Position | None:
    """A Position only when the frame stated one AND it could be decoded."""
    coordinate, _ = _position_decode(message, reference)
    if coordinate is None:
        return None
    source, _ = _position_source(message)
    altitude_m, _ = _altitude_m(message)
    return Position(
        lat=coordinate[0], lon=coordinate[1],
        # Only a GNSS-height frame supplies this. A barometric altitude is a pressure altitude
        # and NOT a height above the ellipsoid, so it is parked instead — gap 9.
        alt_m=altitude_m,
        position_source=source,
        # NOT the type code's navigation integrity category: that is a containment radius, an
        # integrity bound rather than the 1-sigma metre figure this field holds, and recovering
        # it needs the NICa supplement from a different frame anyway.
        accuracy_m=None,
    )


def _altitude_m(message: dict) -> tuple[float | None, str]:
    """`Position.alt_m` — set ONLY by a GNSS-height frame. The whole of gap 9 is this function.

    `alt_m` is documented as metres above the WGS84 ellipsoid, which is what a type code 20-22
    frame states. Type codes 0 and 9-18 state a barometric pressure altitude against the
    1013.25 hPa datum instead: a different measurement, differing by hundreds of metres in
    ordinary weather, so it is parked at attributes.baro_altitude_ft and this returns None.
    """
    type_code = int(message.get("type_code", 0))
    if type_code not in TC_GNSS_HEIGHT:
        return None, ""
    metres, note = gnss_height_m(int(message.get("altitude_raw", 0)))
    return (None if metres is None else float(metres)), note


def _velocity_multiplier(message: dict) -> int:
    """Four on the supersonic subtypes, one otherwise. A scale, not a different field."""
    return (SUPERSONIC_MULTIPLIER if int(message.get("subtype", 1)) in SUPERSONIC_SUBTYPES
            else 1)


def _ground_velocity(message: dict) -> tuple[float | None, float | None]:
    """Ground speed in m/s and track in degrees, from the two signed components.

    Both components are REQUIRED. A speed computed from one axis would understate by up to a
    factor of root two, and a course from one axis would be exactly 000, 090, 180 or 270 — a
    number that looks like a measurement, which is worse than an absent field.
    """
    multiplier = _velocity_multiplier(message)
    east = _signed(_offset_by_one(int(message.get("ew_velocity_raw", 0)),
                                 multiplier=multiplier), int(message.get("ew_sign", 0)))
    north = _signed(_offset_by_one(int(message.get("ns_velocity_raw", 0)),
                                  multiplier=multiplier), int(message.get("ns_sign", 0)))
    if east is None or north is None:
        return None, None
    knots = math.hypot(east, north)
    course = math.degrees(math.atan2(east, north)) % 360.0
    return round(knots * KNOT_MPS, 4), round(course, 4)


def _climb_mps(message: dict) -> float | None:
    """Vertical rate in m/s. 0 means not available and becomes null, NOT level flight."""
    rate = _signed(_offset_by_one(int(message.get("vertical_rate_raw", 0)),
                                 step=VERTICAL_RATE_STEP_FEET_PER_MINUTE),
                   int(message.get("vertical_rate_sign", 0)))
    return None if rate is None else round(rate * FEET_PER_MINUTE_MPS, 4)


def _kinematics(message: dict) -> Kinematics | None:
    """Motion, or None when the frame stated none. Absent is unknown, never zero."""
    kind = frame_kind(int(message.get("type_code", 0)), message.get("subtype"))
    speed = course = climb = None
    if kind == "airborne_velocity_ground":
        speed, course = _ground_velocity(message)
        climb = _climb_mps(message)
    elif kind == "airborne_velocity_air":
        # Airspeed is NOT a ground speed and does not go in speed_mps — gap 10. The vertical
        # rate on this subtype is the same measurement as on the other, so it does travel.
        climb = _climb_mps(message)
    elif kind == "surface_position":
        knots, _, _ = movement_knots(int(message.get("movement_raw", 0)))
        speed = None if knots is None else round(knots * KNOT_MPS, 4)
        if message.get("track_valid"):
            course = round(int(message.get("ground_track_raw", 0)) * 360.0 / TRACK_STEPS, 4)
    if speed is None and course is None and climb is None:
        return None
    return Kinematics(speed_mps=speed, course_deg=course, climb_mps=climb)


def _emergency(message: dict) -> tuple[bool, str]:
    """Whether the FORMAT ITSELF declares an emergency, and the sentence recording the verdict.

    Two fields can say so and nothing else may. A surveillance status of 1 is the standard's
    own permanent-alert indication; a type code 28 emergency state of 1 to 6 is its explicit
    emergency declaration. A temporary alert (an ident-code change) and an SPI pulse are
    procedural conditions and do NOT raise severity — grading those would be this translator
    judging operational significance, which belongs to fusion. The line sits exactly where the
    AIS adapter draws it at navigational status 14.
    """
    status = message.get("surveillance_status")
    if status == SURVEILLANCE_STATUS_EMERGENCY:
        return True, (
            f"surveillance status {SURVEILLANCE_STATUS_EMERGENCY} — "
            f"{SURVEILLANCE_STATUS[SURVEILLANCE_STATUS_EMERGENCY]}, the standard's own alert "
            "indication")
    state = message.get("emergency_state")
    if isinstance(state, int) and state in EMERGENCY_STATES_DECLARED:
        return True, (
            f"type code {TC_AIRCRAFT_STATUS} emergency state {state} — "
            f"{EMERGENCY_STATE[state]}, the standard's own emergency declaration")
    return False, (
        "ADS-B states no urgency outside a surveillance status of "
        f"{SURVEILLANCE_STATUS_EMERGENCY} and a type code {TC_AIRCRAFT_STATUS} emergency "
        "state; INFO is the format's silence, not an assessment that nothing is wrong")


def _unavailable_fields(message: dict) -> list[str]:
    """The fields the SOURCE marked not-available, by name, sorted.

    Two mechanisms feed this and they are kept apart in the tables above: a zero sentinel in a
    field that is otherwise offset by one, and a cleared status bit that invalidates a field
    holding a real-looking number. Both render as an absent CDM field, and without this list
    neither is distinguishable from "this adapter had nothing to say".
    """
    found = {name for name, sentinel in UNAVAILABLE_WHEN
             if name in message and message[name] == sentinel}
    found |= {name for name, flag in UNAVAILABLE_WHEN_FLAG_CLEAR
              if name in message and not message.get(flag)}
    if int(message.get("type_code", 0)) == TC_NO_POSITION_INFORMATION:
        # The frame says outright that it has no position. That is a stated absence, not a
        # sentinel value, and it belongs in this list for the same reason the others do.
        found |= {"cpr_lat", "cpr_lon"}
    return sorted(found)


def _attributes(message: dict, parsed: dict, consumed: Sequence[str],
                reference: tuple[float, float] | None, *,
                observed_basis: str) -> dict[str, Any]:
    """Everything about this aircraft that is not a canonical field. Nones are dropped later."""
    type_code = int(message.get("type_code", 0))
    subtype = message.get("subtype")
    kind = frame_kind(type_code, subtype)
    control = _control_field(message)
    _, position_source_basis = _position_source(message)
    coordinate, position_decode_basis = _position_decode(message, reference)

    category = message.get("emitter_category")
    status = message.get("surveillance_status")
    state = message.get("emergency_state")
    mode_a = message.get("mode_a_code_raw")
    version = message.get("version")
    hrd = message.get("horizontal_reference_direction")
    multiplier = _velocity_multiplier(message)

    attributes: dict[str, Any] = {
        "adsb_type_code": type_code,
        "adsb_frame_kind": kind,
        "adsb_subtype": subtype,
        "adsb_downlink_format": int(message.get("df", DF_ADSB)),
        "adsb_capability": int(message.get("capability", 0)),
        "adsb_control_field_text": CONTROL_FIELD.get(control) if control is not None else None,
        "adsb_relay": True if control in CF_RELAY else None,
        "icao_address": message.get("icao"),
        # 1090ES is unauthenticated, so its self-declared contents are not an identification.
        # This is a DIFFERENT situation from AIS's silence and the wording distinguishes them.
        "affiliation_basis": (
            "ADS-B is an unauthenticated cooperative broadcast: it states an identity — a "
            "callsign, an emitter category, an address — and there is no integrity mechanism "
            "beyond the CRC, which detects corruption and not forgery. UNKNOWN is therefore "
            "not the format's silence but a refusal to read a self-declared, spoofable claim "
            "as an identification"),
        "symbol_basis": "derived from affiliation; ADS-B states no symbol",
        "valid_from_basis": observed_basis,
        "entity_id_basis": "frame address",
        # Three keys, and exactly one of the last two is ever set. A frame that produced a
        # position says what it was decoded against and within what range that holds; one that
        # did not says why. Writing the same sentence under both names would make the pair look
        # like two facts.
        "position_source_basis": (position_source_basis
                                  if _states_position(message) else None),
        "position_decode_basis": position_decode_basis if coordinate is not None else None,
        "position_reference": (list(reference) if coordinate is not None and reference
                               else None),
        "position_unavailable_reason": position_decode_basis if coordinate is None else None,
        # Parked on EVERY frame, decoded or not, so a fusion layer holding a proper even/odd
        # pair can discard our answer and compute its own.
        "cpr_lat": message.get("cpr_lat"),
        "cpr_lon": message.get("cpr_lon"),
        "cpr_format": message.get("cpr_format"),
        "cpr_format_text": (None if message.get("cpr_format") is None else
                            ("odd" if int(message["cpr_format"]) else "even")),
        "surveillance_status": status,
        "surveillance_status_text": (SURVEILLANCE_STATUS.get(status)
                                     if isinstance(status, int) else None),
        # gap 1: no canonical name field — and note that the TAK adapter already parks a CoT
        # callsign under this same key, which is the finding recorded in that gap's note.
        "callsign": _callsign(message),
        "callsign_raw": message.get("callsign"),
        "emitter_category": category,
        "emitter_category_set": (CATEGORY_SET.get(type_code)
                                 if isinstance(category, int) else None),
        "emitter_category_text": (EMITTER_CATEGORY.get((type_code, category))
                                  if isinstance(category, int) else None),
        # gap 7: no canonical heading distinct from course — and the datum problem, which is
        # what ADS-B adds to that gap rather than merely re-reporting it.
        "heading_deg": _heading(message),
        "heading_reference": (HEADING_REFERENCE.get(hrd) if isinstance(hrd, int) else None),
        "horizontal_reference_direction": hrd,
        # gap 10: speed_mps is a speed over the ground and this is not one.
        "airspeed_kt": _offset_by_one(int(message["airspeed_raw"]), multiplier=multiplier)
                       if "airspeed_raw" in message else None,
        "airspeed_type": (AIRSPEED_TYPE.get(int(message["airspeed_type"]))
                          if "airspeed_type" in message else None),
        "velocity_subtype_text": (VELOCITY_SUBTYPE.get(int(subtype))
                                  if kind and kind.startswith("airborne_velocity") else None),
        "vertical_rate_source": (
            VERTICAL_RATE_SOURCE.get(int(message["vertical_rate_source"]))
            if "vertical_rate_source" in message else None),
        # gap 9: no canonical barometric altitude. This is the majority of an air picture.
        "baro_altitude_ft": _baro_altitude_ft(message),
        # The GNSS altitude is parked BESIDE Position.alt_m rather than only inside it, and
        # symmetrically with the barometric key above. `Position` requires a latitude and a
        # longitude, so an altitude with no horizontal fix has nowhere canonical to go — and
        # ADS-B produces exactly that on every position frame this adapter cannot decode a
        # coordinate for. Without this key the altitude would be silently lost on those frames,
        # which the byte-exact round trip caught. See the note under gap 9.
        #
        # Note the UNITS in the two key names, which are the wire's own and not a shared one:
        # the barometric field counts 25-foot steps and the GNSS field counts whole metres. A
        # single `altitude` key would have to pick one and convert the other, and the conversion
        # is exactly where the two measurements would start looking like one.
        "gnss_altitude_m": _gnss_altitude_m(message),
        "altitude_basis": _altitude_basis(message),
        # The DATUM is asserted by this adapter and NOT carried in the frame — see the gap 9
        # note. DO-260 version 0 aircraft broadcast this height against mean sea level;
        # DO-260A/B against the ellipsoid, and the version lives in a type 31 frame.
        "altitude_type": ("GNSS height above the WGS84 ellipsoid (DO-260A/B; a DO-260 v0 "
                          "transmitter states this against mean sea level instead, and the "
                          "version is in a different frame)"
                         if type_code in TC_GNSS_HEIGHT else
                         "barometric pressure altitude (1013.25 hPa datum)"
                         if type_code in TC_BAROMETRIC else None),
        "gnss_baro_difference_ft": _signed(
            _offset_by_one(int(message["gnss_baro_diff_raw"]),
                           step=GNSS_BARO_DIFFERENCE_STEP_FEET),
            int(message.get("gnss_baro_diff_sign", 0))) if "gnss_baro_diff_raw" in message
            else None,
        "ground_track_valid": message.get("track_valid"),
        "movement_text": (movement_knots(int(message["movement_raw"]))[1]
                          if "movement_raw" in message else None),
        "emergency_state": state,
        "emergency_state_text": (EMERGENCY_STATE.get(state) if isinstance(state, int)
                                 else None),
        # A squawk identifies a FLIGHT, not an airframe: ATC assigns it and reassigns it
        # afterwards, so a source id keyed on it would split one aircraft into many entities.
        "mode_a_code": mode_a_code(int(mode_a)) if isinstance(mode_a, int) else None,
        "mode_a_code_raw": mode_a,
        "adsb_version": version,
        "adsb_version_text": (ADSB_VERSION.get(version) if isinstance(version, int) else None),
        "unavailable_fields": _unavailable_fields(message),
        # A DIFFERENT fact from unavailable_fields, and the pair is the point: that list is
        # "the source said it does not know", this one is "the source said something and this
        # adapter could not turn it into a CDM value, so here are its bits". Both render as an
        # absent field, and without both only one of them survives.
        "unresolved_raw": _unresolved_raw(message) or None,
        "source_extras": lossless.residual(parsed, consumed),
    }
    if int(message.get("movement_raw", 0)) == MOVEMENT_AT_OR_ABOVE_MAXIMUM:
        # A floored measurement, not an absence: the aircraft IS moving at least that fast.
        # Kept, with the floor recorded so nobody reads it as an exact speed. AIS's 102.2 kn.
        attributes["movement_at_or_above_maximum"] = True
    return attributes


def _callsign(message: dict) -> str | None:
    """The callsign, or None when the frame did not state a usable one.

    A `#` means the frame carried a six-bit value the ICAO alphabet does not define, so the
    string is not a callsign — it is evidence of a malformed one. `callsign_raw` keeps it
    verbatim; this returns None rather than a cleaned-up name that would read as real.
    """
    raw = message.get("callsign")
    if not isinstance(raw, str) or not raw or CALLSIGN_UNDEFINED in raw:
        return None
    return raw


def _heading(message: dict) -> float | None:
    """The airborne heading in degrees, or None while its validity bit is clear."""
    if not message.get("heading_valid") or "heading_raw" not in message:
        return None
    return round(int(message["heading_raw"]) * 360.0 / HEADING_STEPS, 4)


def _baro_altitude_ft(message: dict) -> int | None:
    """The barometric altitude in feet — gap 9's parked value, on a barometric frame only."""
    if int(message.get("type_code", 0)) not in TC_BAROMETRIC or "altitude_raw" not in message:
        return None
    feet, _ = baro_altitude_feet(int(message["altitude_raw"]))
    return feet


def _gnss_altitude_m(message: dict) -> int | None:
    """The GNSS height in metres, on a GNSS-height frame only.

    Two functions rather than one taking a range, because the two fields no longer share an
    encoding OR a unit: this one is the plain decimal value of twelve bits in metres and the
    other counts 25-foot steps behind a Q bit. Parameterising over the type code was what let an
    earlier version read this field with the barometric arithmetic and report an altitude that
    was wrong by a factor of about eight — silently, because the number stayed plausible.
    """
    if int(message.get("type_code", 0)) not in TC_GNSS_HEIGHT or "altitude_raw" not in message:
        return None
    metres, _ = gnss_height_m(int(message["altitude_raw"]))
    return metres


def _altitude_basis(message: dict) -> str | None:
    """How the altitude field was read, or why it was not.

    Dispatches on the type code because the field does. Never silent about a Gillham frame, and
    never silent about the all-zero GNSS case either, since that reading is the adapter's
    decision rather than a documented sentinel.
    """
    if "altitude_raw" not in message:
        return None
    raw = int(message["altitude_raw"])
    if int(message.get("type_code", 0)) in TC_GNSS_HEIGHT:
        return gnss_height_m(raw)[1]
    return baro_altitude_feet(raw)[1]


def _unresolved_raw(message: dict) -> dict[str, int]:
    """Wire values this adapter read, could not turn into a CDM value, and will not discard.

    One rule with one name rather than five special cases, because the shape recurs: a field
    holds something real, the derived value cannot be produced from it, and the never-drop rule
    still applies. Each entry below is a case the byte-exact round trip found or would find.

    - a Gillham altitude, which this adapter declines to decode;
    - a ground track or a heading whose validity bit is CLEAR: the field holds a real-looking
      number and the aircraft is saying not to read it, so the number is neither a measurement
      nor something to throw away;
    - a reserved surface movement value, which has no defined speed;
    - a velocity component whose partner is not available. `_ground_velocity` refuses to
      compute a speed from one axis, and that refusal must not cost the axis it did have.
    """
    unresolved: dict[str, int] = {}

    # Barometric only: a Gillham frame is the one altitude this adapter declines to decode.
    # Every non-zero GNSS-height value decodes, so there is nothing there to leave unresolved.
    if "altitude_raw" in message and int(message.get("type_code", 0)) in TC_BAROMETRIC:
        raw = int(message["altitude_raw"])
        if raw != 0 and baro_altitude_feet(raw)[0] is None:
            unresolved["altitude_raw"] = raw

    for field, flag in UNAVAILABLE_WHEN_FLAG_CLEAR:
        if field in message and not message.get(flag) and int(message[field]) != 0:
            unresolved[field] = int(message[field])

    if int(message.get("movement_raw", 0)) in MOVEMENT_RESERVED:
        unresolved["movement_raw"] = int(message["movement_raw"])

    if frame_kind(int(message.get("type_code", 0)), message.get("subtype")) == \
            "airborne_velocity_ground" and _ground_velocity(message) == (None, None):
        for field in ("ew_velocity_raw", "ns_velocity_raw"):
            if int(message.get(field, 0)) != 0:
                unresolved[field] = int(message[field])
    return unresolved


# ----------------------------------------------------------------- egress helpers


def _address_of(obj: CDMBase) -> str:
    """This object's 24-bit address, or a refusal. A frame with no address addresses nobody."""
    for source_id in obj.source_ids:
        if source_id.system in (ICAO_SYSTEM, NONICAO_SYSTEM):
            return source_id.external_id
    systems = sorted({s.system for s in obj.source_ids})
    raise ValueError(
        f"cannot emit ADS-B for an object with no {ICAO_SYSTEM} source id (it has: "
        f"{systems or 'none'}). The 24-bit address is the address field of every extended "
        "squitter; deriving one from the CDM id would put an aircraft on 1090 MHz under a "
        "number nobody allocated"
    )


def _states_motion(kinematics: Kinematics | None) -> bool:
    """Whether there is any motion to put in a velocity frame at all.

    Checked field by field rather than by the object's presence: a Kinematics holding three
    Nones is a legitimate object meaning "nothing measured", and emitting a velocity frame for
    it would transmit three not-available values as if they were a report.
    """
    return kinematics is not None and any(
        value is not None for value in
        (kinematics.speed_mps, kinematics.course_deg, kinematics.climb_mps))


def _velocity_message(entity: Entity) -> dict[str, Any]:
    """The type 19 subtype 1 frame for an Entity's kinematics.

    Subtype 1 — velocity over ground — because `Kinematics.speed_mps` IS a speed over the
    ground. Emitting subtype 3 would restate it as an airspeed, which is the gap 10 conflation
    running outbound.
    """
    message = dict(NOT_AVAILABLE)
    attributes = dict(entity.attributes)
    message.update({
        "df": int(attributes.get("adsb_downlink_format") or DF_ADSB),
        "capability": int(attributes.get("adsb_capability") or 0),
        "icao": _address_of(entity),
        "type_code": TC_VELOCITY,
        "subtype": 1,
    })
    _fill_ground_velocity(message, entity)
    _fill_vertical_rate(message, entity, attributes)
    return message


def _parked_frame(extras: Any) -> dict[str, Any]:
    """The parked frame envelope, so a re-emission keeps its AVR form and receiver counter."""
    if isinstance(extras, dict):
        frame = extras.get("frame")
        if isinstance(frame, dict):
            return frame
    return {}


def _message_from_entity(entity: Entity) -> dict[str, Any]:
    """An Entity back into the fields of one ADS-B frame, restoring what ingest parked.

    Three layers, in this order: the standard's not-available value for every field, so an
    Entity that never came from ADS-B still encodes; then the parked source fields, which is
    where the reserved bits and the integrity categories come back from; then the canonical CDM
    values, which WIN — a position edited in the CDM must reach the wire, or egress would be a
    replay rather than a translation.
    """
    attributes = dict(entity.attributes)
    extras = attributes.get("source_extras") or {}
    parked = extras.get("message") if isinstance(extras, dict) else None

    position = entity.position
    stated_type_code = attributes.get("adsb_type_code")
    type_code = int(stated_type_code) if stated_type_code is not None else (
        DEFAULT_TYPE_CODE_WITH_ALTITUDE if position is not None and position.alt_m is not None
        else DEFAULT_TYPE_CODE_NO_ALTITUDE)

    message: dict[str, Any] = dict(NOT_AVAILABLE)
    if isinstance(parked, dict):
        message.update(parked)
    message["df"] = int(attributes.get("adsb_downlink_format") or DF_ADSB)
    message["capability"] = int(attributes.get("adsb_capability") or 0)
    message["icao"] = _address_of(entity)
    message["type_code"] = type_code
    if attributes.get("adsb_subtype") is not None:
        message["subtype"] = int(attributes["adsb_subtype"])

    kind = frame_kind(type_code, message.get("subtype"))
    if kind is None:
        raise ValueError(
            f"cannot emit ADS-B type code {type_code} subtype {message.get('subtype')}: not in "
            "this adapter's scope. FORMAT_COVERAGE.md names every type code that is out and why"
        )

    if kind in KINDS_WITH_POSITION:
        span, _ = _position_span(message)
        cpr_format = int(attributes.get("cpr_format") or 0)
        message["cpr_format"] = cpr_format
        if position is not None:
            message["cpr_lat"], message["cpr_lon"] = cpr_encode(
                position.lat, position.lon, cpr_format, span=span)
        else:
            # Nothing is invented: the CPR fields go out as the parked ones, or as zeros, which
            # for type code 0 is exactly what "no position information" looks like on the wire.
            message["cpr_lat"] = int(attributes.get("cpr_lat") or 0)
            message["cpr_lon"] = int(attributes.get("cpr_lon") or 0)

    if kind == "airborne_position":
        message["surveillance_status"] = int(attributes.get("surveillance_status") or 0)
        message["altitude_raw"] = _altitude_raw_for(entity, type_code, attributes)

    if kind == "surface_position":
        kinematics = entity.kinematics
        speed = kinematics.speed_mps if kinematics else None
        course = kinematics.course_deg if kinematics else None
        unresolved = attributes.get("unresolved_raw") or {}
        message["movement_raw"] = (
            int(unresolved["movement_raw"]) if "movement_raw" in unresolved
            else MOVEMENT_NOT_AVAILABLE if speed is None
            else movement_raw(speed / KNOT_MPS))
        message["track_valid"] = course is not None
        message["ground_track_raw"] = (
            round(course * TRACK_STEPS / 360.0) % TRACK_STEPS if course is not None
            else int(unresolved.get("ground_track_raw", 0)))

    if kind == "identification":
        message["emitter_category"] = int(attributes.get("emitter_category") or 0)
        message["callsign"] = attributes.get("callsign") or attributes.get("callsign_raw") or ""

    if kind == "airborne_velocity_ground":
        _fill_ground_velocity(message, entity)
    if kind == "airborne_velocity_air":
        _fill_air_velocity(message, attributes)
    if kind in ("airborne_velocity_ground", "airborne_velocity_air"):
        _fill_vertical_rate(message, entity, attributes)

    if kind == "aircraft_status":
        message["emergency_state"] = int(attributes.get("emergency_state") or 0)
        code = attributes.get("mode_a_code")
        message["mode_a_code_raw"] = (mode_a_raw(str(code)) if code
                                      else int(attributes.get("mode_a_code_raw") or 0))

    if kind == "operational_status":
        message["version"] = int(attributes.get("adsb_version") or 0)
        if attributes.get("horizontal_reference_direction") is not None:
            message["horizontal_reference_direction"] = int(
                attributes["horizontal_reference_direction"])
    return message


def _altitude_raw_for(entity: Entity, type_code: int, attributes: dict[str, Any]) -> int:
    """The twelve-bit altitude field for an airborne position frame.

    The measurement decides where it comes from, which is the egress half of gap 9: a
    GNSS-height frame takes `Position.alt_m`, a barometric frame takes the parked
    `attributes.baro_altitude_ft`, and neither ever takes the other's value. A frame whose raw
    bits were parked undecoded (Gillham) gets them back untouched.
    """
    parked_raw = (attributes.get("unresolved_raw") or {}).get("altitude_raw")
    if parked_raw is not None:
        return int(parked_raw)
    if type_code in TC_GNSS_HEIGHT:
        # The canonical copy WINS where there is one: an altitude edited in the CDM has to
        # reach the wire, or egress would be a replay rather than a translation. The parked
        # figure is the fallback for a frame whose coordinate could not be decoded, which is
        # the only case in which there is no Position to hold it.
        altitude_m = entity.position.alt_m if entity.position else None
        if altitude_m is not None:
            return gnss_height_raw(altitude_m)
        metres = attributes.get("gnss_altitude_m")
        return 0 if metres is None else gnss_height_raw(float(metres))
    feet = attributes.get("baro_altitude_ft")
    return 0 if feet is None else baro_altitude_raw(float(feet))


def _fill_ground_velocity(message: dict[str, Any], entity: Entity) -> None:
    """Speed and course back into the two signed components.

    A null speed or a null course emits 0 on BOTH components, which is the standard's "not
    available" — the null-to-zero defect running outbound is the same defect, and a stationary
    aircraft is not what the CDM said.
    """
    kinematics = entity.kinematics
    speed = kinematics.speed_mps if kinematics else None
    course = kinematics.course_deg if kinematics else None
    if speed is None or course is None:
        # The parked components come back where one axis was real and its partner was not:
        # refusing to compute a speed from one axis must not cost the axis we had.
        unresolved = entity.attributes.get("unresolved_raw") or {}
        message["ew_velocity_raw"] = int(unresolved.get("ew_velocity_raw", 0))
        message["ns_velocity_raw"] = int(unresolved.get("ns_velocity_raw", 0))
        return
    multiplier = _velocity_multiplier(message)
    knots = speed / KNOT_MPS
    east = knots * math.sin(math.radians(course))
    north = knots * math.cos(math.radians(course))
    for axis, value in (("ew", east), ("ns", north)):
        magnitude = round(abs(value) / multiplier)
        if magnitude + 1 >= (1 << 10):
            raise ValueError(
                f"{axis} velocity component {value:.1f} kt does not fit the ten-bit ADS-B "
                f"field at subtype {message.get('subtype')} — refusing to wrap a velocity "
                "round to a small one, which would read as a slow aircraft"
            )
        message[f"{axis}_sign"] = 0 if value >= 0 else 1
        message[f"{axis}_velocity_raw"] = magnitude + 1


def _fill_air_velocity(message: dict[str, Any], attributes: dict[str, Any]) -> None:
    """Airspeed and heading back from where ingest parked them — gaps 10 and 7 in reverse.

    It takes only `attributes`, and the missing parameter is the point: `Kinematics.speed_mps`
    is a speed over the GROUND, so writing it into an airspeed field would state an airspeed
    nobody measured — the same conflation this adapter refuses on ingest, pointed the other way.
    Not being handed the Entity is what makes that mistake impossible here rather than merely
    discouraged.
    """
    multiplier = _velocity_multiplier(message)
    unresolved = attributes.get("unresolved_raw") or {}
    heading = attributes.get("heading_deg")
    message["heading_valid"] = heading is not None
    message["heading_raw"] = (
        round(float(heading) * HEADING_STEPS / 360.0) % HEADING_STEPS if heading is not None
        else int(unresolved.get("heading_raw", 0)))
    airspeed = attributes.get("airspeed_kt")
    message["airspeed_raw"] = (0 if airspeed is None
                               else int(round(float(airspeed) / multiplier)) + 1)
    stated_type = attributes.get("airspeed_type")
    if stated_type is not None:
        message["airspeed_type"] = next(
            (code for code, text in AIRSPEED_TYPE.items() if text == stated_type),
            int(message.get("airspeed_type", 0)))


def _fill_vertical_rate(message: dict[str, Any], entity: Entity,
                        attributes: dict[str, Any]) -> None:
    """Climb rate and the GNSS-barometric difference back onto a velocity frame."""
    climb = entity.kinematics.climb_mps if entity.kinematics else None
    if climb is None:
        message["vertical_rate_raw"] = 0
        message["vertical_rate_sign"] = 0
    else:
        feet_per_minute = climb / FEET_PER_MINUTE_MPS
        message["vertical_rate_sign"] = 0 if feet_per_minute >= 0 else 1
        message["vertical_rate_raw"] = round(
            abs(feet_per_minute) / VERTICAL_RATE_STEP_FEET_PER_MINUTE) + 1
    difference = attributes.get("gnss_baro_difference_ft")
    if difference is None:
        message["gnss_baro_diff_raw"] = 0
        message["gnss_baro_diff_sign"] = 0
    else:
        message["gnss_baro_diff_sign"] = 0 if float(difference) >= 0 else 1
        message["gnss_baro_diff_raw"] = round(
            abs(float(difference)) / GNSS_BARO_DIFFERENCE_STEP_FEET) + 1
